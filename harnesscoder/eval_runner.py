from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
import os
import shutil
import shlex
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from harnesscoder.core.models import (
    HCBenchOracleModel,
    ModelAdapter,
    OpenAIChatModel,
    OpenAICodexModel,
    ScriptedModel,
)
from harnesscoder.core.policy import ToolPolicy
from harnesscoder.core.prompt import ContextMode
from harnesscoder.core.runner import AgentRunner, RepoMapMode
from harnesscoder.core.tools import redact_sensitive_text, safe_subprocess_env
from harnesscoder.model_profiles import ModelProfile
from harnesscoder.replay import summarize_trace


@dataclass(frozen=True, slots=True)
class _PreparedWorkspace:
    path: Path
    run_root: Path


@dataclass(slots=True)
class EvalCase:
    id: str
    category: str
    task: str
    cwd: str
    test_command: str
    timeout: int
    repo_fixture: str | None = None
    allowed_tools: tuple[str, ...] | None = None
    step_budget: int | None = None
    verifier: str | None = None
    success_contains: str | tuple[str, ...] | None = None
    success_returncode: int | None = None

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> "EvalCase":
        case_id = _required_str(record, "id")
        category = _optional_str(record, "category", "general")
        assert category is not None
        task = _required_str(record, "task")
        cwd = _required_str(record, "cwd")
        test_command = _required_str(record, "test_command")
        timeout = _required_int(record, "timeout")
        repo_fixture = _optional_str(record, "repo_fixture", None)
        allowed_tools = _optional_str_tuple(record, "allowed_tools", None)
        step_budget = _optional_int(record, "step_budget", None)
        verifier = _optional_str(record, "verifier", None)
        success_contains = _success_contains(record.get("success_contains"))
        success_returncode = _optional_int(record, "success_returncode", None)

        if success_contains is None and success_returncode is None:
            raise ValueError(
                f"eval case {case_id!r} must define success_contains or "
                "success_returncode"
            )

        return cls(
            id=case_id,
            category=category,
            task=task,
            cwd=cwd,
            test_command=test_command,
            timeout=timeout,
            repo_fixture=repo_fixture,
            allowed_tools=allowed_tools,
            step_budget=step_budget,
            verifier=verifier,
            success_contains=success_contains,
            success_returncode=success_returncode,
        )


@dataclass(slots=True)
class EvalResult:
    case_id: str
    category: str
    task: str
    cwd: Path
    workspace_path: Path
    passed: bool
    reason: str
    run_id: str
    runner_status: str
    final_answer: str
    trace_path: Path
    tool_counts: dict[str, int] = field(default_factory=dict)
    test_command: str = ""
    test_returncode: int | None = None
    test_stdout: str = ""
    test_stderr: str = ""
    test_timed_out: bool = False
    test_duration_seconds: float = 0.0
    test_passed: bool = False
    verifier_command: str = ""
    verifier_returncode: int | None = None
    verifier_stdout: str = ""
    verifier_stderr: str = ""
    verifier_timed_out: bool = False
    verifier_duration_seconds: float = 0.0
    verifier_passed: bool = True
    patch_success: bool = False
    agent_success: bool = False
    failure_category: str = "incomplete"
    metrics: dict[str, Any] = field(default_factory=dict)
    trace_summary: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class EvalMatrixProfileResult:
    profile_name: str
    provider: str
    results: list[EvalResult]
    error: str | None = None
    planned_case_ids: list[str] = field(default_factory=list)


def load_eval_cases(cases_path: str | Path) -> list[EvalCase]:
    data = json.loads(Path(cases_path).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        raw_cases = data.get("cases")
    else:
        raw_cases = data

    if not isinstance(raw_cases, list):
        raise ValueError(
            "eval cases must be a JSON list or an object with a cases list"
        )

    cases: list[EvalCase] = []
    seen_ids: set[str] = set()
    for raw_case in raw_cases:
        if not isinstance(raw_case, dict):
            raise ValueError("each eval case must be a JSON object")
        case = EvalCase.from_record(raw_case)
        if case.id in seen_ids:
            raise ValueError(f"duplicate eval case id: {case.id}")
        seen_ids.add(case.id)
        cases.append(case)
    return cases


def _prepare_case_workspace(
    *,
    case: EvalCase,
    workspace_root: Path,
    cases_path: Path,
) -> _PreparedWorkspace:
    if case.repo_fixture is None:
        return _PreparedWorkspace(path=workspace_root, run_root=workspace_root)

    fixture = _resolve_fixture_path(case.repo_fixture, workspace_root, cases_path)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    destination = (
        workspace_root
        / ".harnesscoder"
        / "eval-workspaces"
        / _safe_path_segment(case.id)
        / timestamp
        / "repo"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        fixture,
        destination,
        ignore=shutil.ignore_patterns(".git", ".harnesscoder", "__pycache__"),
    )
    return _PreparedWorkspace(path=destination, run_root=destination)


def run_eval_cases(
    cases_path: str | Path,
    workspace_root: str | Path,
    provider: str = "scripted",
    *,
    trace_root: str | Path = ".harnesscoder/eval-runs",
    max_iterations: int = 8,
    model: ModelAdapter | None = None,
    context_mode: ContextMode = "none",
    repo_map_mode: RepoMapMode = "auto",
) -> list[EvalResult]:
    root = Path(workspace_root).resolve()
    resolved_cases_path = _resolve_cases_path(cases_path, root)
    cases = load_eval_cases(resolved_cases_path)
    resolved_trace_root = _resolve_trace_root(trace_root, root)

    results: list[EvalResult] = []
    for case in cases:
        workspace = _prepare_case_workspace(
            case=case,
            workspace_root=root,
            cases_path=resolved_cases_path,
        )
        case_cwd = _resolve_inside(workspace.run_root, case.cwd)
        effective_max_iterations = case.step_budget or max_iterations
        runner = AgentRunner(
            model=model or _build_model(provider),
            cwd=case_cwd,
            trace_root=resolved_trace_root,
            max_iterations=effective_max_iterations,
            context_mode=context_mode,
            repo_map_mode=repo_map_mode,
            policy=ToolPolicy(set(case.allowed_tools) if case.allowed_tools else None),
        )
        run_result = runner.run(case.task)
        test_result = _run_test_command(case, case_cwd)
        verifier_result = _run_verifier(case, case_cwd, run_result)
        test_passed, test_reason = _score_test_result(case, test_result)
        verifier_passed, verifier_reason = _score_verifier_result(
            case,
            verifier_result,
        )
        patch_success = test_passed and verifier_passed
        agent_success = run_result.status == "success"
        passed, reason = _score_case(
            case,
            run_result.status,
            test_result,
            verifier_result,
        )
        _append_test_result_event(
            trace_path=run_result.trace_path,
            run_id=run_result.run_id,
            case=case,
            test_result=test_result,
            passed=test_passed,
            reason=test_reason,
        )
        if case.verifier is not None and verifier_result is not None:
            _append_verifier_result_event(
                trace_path=run_result.trace_path,
                run_id=run_result.run_id,
                case=case,
                verifier_result=verifier_result,
                passed=verifier_passed,
                reason=verifier_reason,
            )
        trace_summary = summarize_trace(run_result.trace_path)
        metrics = _metrics_from_summary(trace_summary)
        tool_counts = _tool_counts_from_summary(trace_summary)

        results.append(
            EvalResult(
                case_id=case.id,
                category=case.category,
                task=case.task,
                cwd=case_cwd,
                workspace_path=workspace.path,
                passed=passed,
                reason=reason,
                run_id=run_result.run_id,
                runner_status=run_result.status,
                final_answer=run_result.final_answer,
                trace_path=run_result.trace_path,
                tool_counts=tool_counts,
                test_command=case.test_command,
                test_returncode=test_result.returncode,
                test_stdout=test_result.stdout,
                test_stderr=test_result.stderr,
                test_timed_out=test_result.timed_out,
                test_duration_seconds=test_result.duration_seconds,
                test_passed=test_passed,
                verifier_command=case.verifier or "",
                verifier_returncode=(
                    verifier_result.returncode if verifier_result else None
                ),
                verifier_stdout=verifier_result.stdout if verifier_result else "",
                verifier_stderr=verifier_result.stderr if verifier_result else "",
                verifier_timed_out=(
                    verifier_result.timed_out if verifier_result else False
                ),
                verifier_duration_seconds=(
                    verifier_result.duration_seconds if verifier_result else 0.0
                ),
                verifier_passed=verifier_passed,
                patch_success=patch_success,
                agent_success=agent_success,
                failure_category=_failure_category_from_summary(trace_summary),
                metrics=metrics,
                trace_summary=trace_summary,
            )
        )

    return results


def run_eval_matrix(
    cases_path: str | Path,
    workspace_root: str | Path,
    profiles: list[ModelProfile],
    *,
    trace_root: str | Path = ".harnesscoder/eval-runs",
    max_iterations: int = 8,
    context_mode: ContextMode = "none",
    repo_map_mode: RepoMapMode = "auto",
) -> list[EvalMatrixProfileResult]:
    matrix: list[EvalMatrixProfileResult] = []
    root = Path(workspace_root).resolve()
    planned_case_ids = [case.id for case in load_eval_cases(_resolve_cases_path(cases_path, root))]
    for profile in profiles:
        try:
            model = profile.build()
        except Exception as exc:
            matrix.append(
                EvalMatrixProfileResult(
                    profile_name=profile.name,
                    provider=profile.provider,
                    results=[],
                    error=f"{type(exc).__name__}: {exc}",
                    planned_case_ids=planned_case_ids,
                )
            )
            continue
        results = run_eval_cases(
            cases_path=cases_path,
            workspace_root=workspace_root,
            provider=profile.provider,
            trace_root=trace_root,
            max_iterations=max_iterations,
            model=model,
            context_mode=context_mode,
            repo_map_mode=repo_map_mode,
        )
        matrix.append(
            EvalMatrixProfileResult(
                profile_name=profile.name,
                provider=profile.provider,
                results=results,
                planned_case_ids=planned_case_ids,
            )
        )
    return matrix


def render_markdown_report(results: list[EvalResult]) -> str:
    total = len(results)
    passed = sum(1 for result in results if result.passed)
    failed = total - passed
    task_successes = sum(1 for result in results if result.runner_status == "success")
    agent_successes = sum(1 for result in results if result.agent_success)
    test_passes = sum(1 for result in results if result.test_passed)
    verifier_passes = sum(1 for result in results if result.verifier_passed)
    patch_successes = sum(1 for result in results if result.patch_success)
    patch_success_agent_failures = sum(
        1 for result in results if result.patch_success and not result.agent_success
    )
    avg_tool_calls = _average_metric(results, "average_tool_calls")
    repeated_reads = _sum_metric(results, "repeated_read_count")
    invalid_tool_calls = _sum_metric(results, "invalid_tool_call_count")
    policy_denials = _sum_metric(results, "policy_denial_count")
    tool_failures = _sum_metric(results, "failed_tool_count")
    context_packs = _sum_metric(results, "context_packed_count")
    context_injections = _sum_metric(results, "context_injected_count")
    estimated_context_tokens = _sum_metric(results, "estimated_context_tokens")
    memory_updates = _sum_metric(results, "memory_updated_count")
    repo_map_built = _sum_metric(results, "repo_map_built_count")
    repo_map_used = _sum_metric(results, "repo_map_used_count")
    repo_map_injected = _sum_metric(results, "repo_map_injected_count")
    first_repo_map_target_step = _average_nullable_metric(
        results,
        "first_repo_map_target_step",
    )
    raw_tool_output_chars = _sum_metric(results, "raw_tool_output_chars")
    tool_output_preview_chars = _sum_metric(results, "tool_output_preview_chars")
    stored_artifacts = _sum_metric(results, "stored_artifact_count")
    artifact_missing = _sum_metric(results, "artifact_missing_count")
    artifact_hash_mismatch = _sum_metric(results, "artifact_hash_mismatch_count")
    largest_tool_output_chars = _max_metric(results, "largest_tool_output_chars")
    output_compression_ratio = _output_compression_ratio(results)
    compression_count = _sum_metric(results, "compression_count")
    hot_observation_count = _sum_metric(results, "hot_observation_count")
    cold_summary_chars = _sum_metric(results, "cold_summary_chars")
    time_to_first_edit = _average_nullable_metric(results, "time_to_first_edit")
    search_to_edit_steps = _average_nullable_metric(results, "search_to_edit_steps")
    edit_to_test_steps = _average_nullable_metric(results, "edit_to_test_steps")
    checkpoints = _sum_metric(results, "checkpoint_created_count")
    finish_grace_attempts = _sum_metric(results, "finish_grace_attempt_count")
    finish_grace_successes = _sum_metric(results, "finish_grace_success_count")
    resume_rate = _average_nullable_metric(results, "resume_success_rate")
    failure_breakdown = Counter(result.failure_category for result in results)
    category_breakdown = _category_summary(results)
    lines = [
        "# HarnessCoder Eval Report",
        "",
        f"- Cases: {total}",
        f"- Passed: {passed}",
        f"- Failed: {failed}",
        "",
        "## Metrics",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Task success rate | {_format_rate(task_successes, total)} |",
        f"| Agent success rate | {_format_rate(agent_successes, total)} |",
        f"| Patch success rate | {_format_rate(patch_successes, total)} |",
        f"| Patch success but agent failed | {patch_success_agent_failures} |",
        f"| Test pass rate | {_format_rate(test_passes, total)} |",
        f"| Verifier pass rate | {_format_rate(verifier_passes, total)} |",
        f"| Avg tool calls | {_format_number(avg_tool_calls)} |",
        f"| Repeated reads | {repeated_reads} |",
        f"| Invalid tool calls | {invalid_tool_calls} |",
        f"| Policy denials | {policy_denials} |",
        f"| Tool failures | {tool_failures} |",
        f"| Context packs | {context_packs} |",
        f"| Context injections | {context_injections} |",
        f"| Estimated context tokens | {estimated_context_tokens} |",
        f"| Memory updates | {memory_updates} |",
        f"| RepoMap builds | {repo_map_built} |",
        f"| RepoMap uses | {repo_map_used} |",
        f"| RepoMap injections | {repo_map_injected} |",
        f"| Avg first RepoMap target read step | {_format_nullable_number(first_repo_map_target_step)} |",
        f"| Raw tool output chars | {raw_tool_output_chars} |",
        f"| Tool output preview chars | {tool_output_preview_chars} |",
        f"| Stored artifacts | {stored_artifacts} |",
        f"| Artifact missing count | {artifact_missing} |",
        f"| Artifact hash mismatch count | {artifact_hash_mismatch} |",
        f"| Largest tool output chars | {largest_tool_output_chars} |",
        f"| Observation compression ratio | {_format_nullable_rate(output_compression_ratio)} |",
        f"| Compression count | {compression_count} |",
        f"| Hot observations | {hot_observation_count} |",
        f"| Cold summary chars | {cold_summary_chars} |",
        f"| Avg time to first edit | {_format_nullable_number(time_to_first_edit)} |",
        f"| Avg search-to-edit steps | {_format_nullable_number(search_to_edit_steps)} |",
        f"| Avg edit-to-test steps | {_format_nullable_number(edit_to_test_steps)} |",
        f"| Checkpoints | {checkpoints} |",
        f"| Finish grace attempts | {finish_grace_attempts} |",
        f"| Finish grace successes | {finish_grace_successes} |",
        f"| Resume success rate | {_format_nullable_rate(resume_rate)} |",
        f"| Failure category breakdown | {_format_breakdown(failure_breakdown)} |",
        "",
        "## Category Summary",
        "",
        "| Category | Cases | Passed | Agent success | Patch success | Test pass | Verifier pass | Avg tools | Policy denials | Artifacts | Failures |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for category, category_results in category_breakdown.items():
        category_total = len(category_results)
        category_passed = sum(1 for result in category_results if result.passed)
        category_agent_success = sum(
            1 for result in category_results if result.agent_success
        )
        category_patch_success = sum(
            1 for result in category_results if result.patch_success
        )
        category_test_passed = sum(1 for result in category_results if result.test_passed)
        category_verifier_passed = sum(
            1 for result in category_results if result.verifier_passed
        )
        category_failures = Counter(result.failure_category for result in category_results)
        lines.append(
            "| "
            + " | ".join(
                [
                    _md_cell(category),
                    str(category_total),
                    _format_rate(category_passed, category_total),
                    _format_rate(category_agent_success, category_total),
                    _format_rate(category_patch_success, category_total),
                    _format_rate(category_test_passed, category_total),
                    _format_rate(category_verifier_passed, category_total),
                    _format_number(_average_metric(category_results, "average_tool_calls")),
                    str(_sum_metric(category_results, "policy_denial_count")),
                    str(_sum_metric(category_results, "stored_artifact_count")),
                    _md_cell(_format_breakdown(category_failures)),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Runs",
            "",
            "| Case | Category | Result | Agent | Patch | Test | Verifier | Failure | Workspace | Run | Tools |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )

    for result in results:
        status = "PASS" if result.passed else "FAIL"
        test_status = (
            "timeout"
            if result.test_timed_out
            else f"rc={result.test_returncode}"
        )
        verifier_status = _verifier_status(result)
        lines.append(
            "| "
            + " | ".join(
                [
                    _md_cell(result.case_id),
                    _md_cell(result.category),
                    status,
                    _md_cell(result.runner_status),
                    "PASS" if result.patch_success else "FAIL",
                    _md_cell(test_status),
                    _md_cell(verifier_status),
                    _md_cell(result.failure_category),
                    _md_cell(str(result.workspace_path)),
                    _md_cell(f"{result.run_id}<br>{result.trace_path}"),
                    _md_cell(_format_tool_counts(result.tool_counts)),
                ]
            )
            + " |"
        )

    lines.append("")
    lines.append("## Case Details")
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        lines.extend(
            [
                "",
                f"### {result.case_id} - {status}",
                "",
                f"- Task: {_inline(result.task)}",
                f"- Category: `{result.category}`",
                f"- CWD: `{result.cwd}`",
                f"- Workspace: `{result.workspace_path}`",
                f"- Test command: `{result.test_command}`",
                f"- Verifier: `{result.verifier_command or '-'}`",
                f"- Reason: {result.reason}",
                f"- Agent success: `{result.agent_success}`",
                f"- Patch success: `{result.patch_success}`",
                f"- Failure category: `{result.failure_category}`",
                f"- Replay metrics: {_inline(_format_metrics(result.metrics))}",
                f"- Trace: `{result.trace_path}`",
                f"- Test duration: {result.test_duration_seconds:.2f}s",
                f"- Verifier duration: {result.verifier_duration_seconds:.2f}s",
            ]
        )
        output = _clip(
            "\n".join([result.test_stdout, result.test_stderr]).strip(),
            2000,
        )
        if output:
            lines.extend(["", "```text", output, "```"])

    return "\n".join(lines).rstrip() + "\n"


def render_markdown_matrix(matrix: list[EvalMatrixProfileResult]) -> str:
    total_profiles = len(matrix)
    all_case_ids = _case_ids_from_matrix(matrix)
    lines = [
        "# HarnessCoder Eval Matrix",
        "",
        f"- Profiles: {total_profiles}",
        f"- Cases: {len(all_case_ids)}",
        "",
        "## Profile Summary",
        "",
        "| Profile | Provider | Cases | Passed | Agent success | Patch success | Test pass | Verifier pass | Patch ok / agent failed | Avg tools | Repeated reads | Invalid calls | Policy denials | Tool failures | Context injected | Est. tokens | Memory updates | RepoMap used | RepoMap injected | Finish grace | Compression | Artifacts | Artifact integrity | Raw output chars | Output compression | Failure breakdown |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]

    for profile_result in matrix:
        results = profile_result.results
        if profile_result.error:
            planned_total = len(profile_result.planned_case_ids)
            lines.append(
                "| "
                + " | ".join(
                    [
                        _md_cell(profile_result.profile_name),
                        _md_cell(profile_result.provider),
                        str(planned_total),
                        "n/a",
                        "n/a",
                        "n/a",
                        "n/a",
                        "n/a",
                        "0",
                        "0",
                        "0",
                        "0",
                        "0",
                        "0",
                        "0",
                        "0",
                        "0",
                        "0",
                        "0",
                        "0/0",
                        "0",
                        "0",
                        "0 missing / 0 mismatch",
                        "0",
                        "n/a",
                        _md_cell(
                            f"profile_error=1 skipped={planned_total} ({profile_result.error})"
                        ),
                    ]
                )
                + " |"
            )
            continue
        total = len(results)
        passed = sum(1 for result in results if result.passed)
        agent_successes = sum(1 for result in results if result.agent_success)
        patch_successes = sum(1 for result in results if result.patch_success)
        patch_success_agent_failures = sum(
            1 for result in results if result.patch_success and not result.agent_success
        )
        test_passes = sum(1 for result in results if result.test_passed)
        verifier_passes = sum(1 for result in results if result.verifier_passed)
        failure_breakdown = Counter(result.failure_category for result in results)
        finish_grace_attempts = _sum_metric(results, "finish_grace_attempt_count")
        finish_grace_successes = _sum_metric(results, "finish_grace_success_count")
        lines.append(
            "| "
            + " | ".join(
                [
                    _md_cell(profile_result.profile_name),
                    _md_cell(profile_result.provider),
                    str(total),
                    _format_rate(passed, total),
                    _format_rate(agent_successes, total),
                    _format_rate(patch_successes, total),
                    _format_rate(test_passes, total),
                    _format_rate(verifier_passes, total),
                    str(patch_success_agent_failures),
                    _format_number(_average_metric(results, "average_tool_calls")),
                    str(_sum_metric(results, "repeated_read_count")),
                    str(_sum_metric(results, "invalid_tool_call_count")),
                    str(_sum_metric(results, "policy_denial_count")),
                    str(_sum_metric(results, "failed_tool_count")),
                    str(_sum_metric(results, "context_injected_count")),
                    str(_sum_metric(results, "estimated_context_tokens")),
                    str(_sum_metric(results, "memory_updated_count")),
                    str(_sum_metric(results, "repo_map_used_count")),
                    str(_sum_metric(results, "repo_map_injected_count")),
                    f"{finish_grace_successes}/{finish_grace_attempts}",
                    str(_sum_metric(results, "compression_count")),
                    str(_sum_metric(results, "stored_artifact_count")),
                    (
                        f"{_sum_metric(results, 'artifact_missing_count')} missing / "
                        f"{_sum_metric(results, 'artifact_hash_mismatch_count')} mismatch"
                    ),
                    str(_sum_metric(results, "raw_tool_output_chars")),
                    _format_nullable_rate(_output_compression_ratio(results)),
                    _md_cell(_format_breakdown(failure_breakdown)),
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## Category Summary",
            "",
            "| Profile | Category | Cases | Passed | Agent success | Patch success | Test pass | Verifier pass | Avg tools | Policy denials | RepoMap used | Artifacts | Failure breakdown |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for profile_result in matrix:
        for category, category_results in _category_summary(profile_result.results).items():
            category_total = len(category_results)
            category_passed = sum(1 for result in category_results if result.passed)
            category_agent_success = sum(
                1 for result in category_results if result.agent_success
            )
            category_patch_success = sum(
                1 for result in category_results if result.patch_success
            )
            category_test_passed = sum(
                1 for result in category_results if result.test_passed
            )
            category_verifier_passed = sum(
                1 for result in category_results if result.verifier_passed
            )
            category_failures = Counter(
                result.failure_category for result in category_results
            )
            lines.append(
                "| "
                + " | ".join(
                    [
                        _md_cell(profile_result.profile_name),
                        _md_cell(category),
                        str(category_total),
                        _format_rate(category_passed, category_total),
                        _format_rate(category_agent_success, category_total),
                        _format_rate(category_patch_success, category_total),
                        _format_rate(category_test_passed, category_total),
                        _format_rate(category_verifier_passed, category_total),
                        _format_number(
                            _average_metric(category_results, "average_tool_calls")
                        ),
                        str(_sum_metric(category_results, "policy_denial_count")),
                        str(_sum_metric(category_results, "repo_map_used_count")),
                        str(_sum_metric(category_results, "stored_artifact_count")),
                        _md_cell(_format_breakdown(category_failures)),
                    ]
                )
                + " |"
            )

    lines.extend(
        [
            "",
            "## Case Matrix",
            "",
            "| Case | " + " | ".join(_md_cell(item.profile_name) for item in matrix) + " |",
            "| --- | " + " | ".join("---" for _item in matrix) + " |",
        ]
    )
    by_profile = {
        item.profile_name: {result.case_id: result for result in item.results}
        for item in matrix
    }
    for case_id in all_case_ids:
        row = [case_id]
        for item in matrix:
            result = by_profile.get(item.profile_name, {}).get(case_id)
            if result is None:
                row.append("SKIP" if item.error else "-")
            else:
                status = "PASS" if result.passed else "FAIL"
                row.append(
                    _md_cell(
                        f"{status}<br>{result.failure_category}<br>{result.run_id}"
                    )
                )
        lines.append("| " + " | ".join(row) + " |")

    lines.extend(["", "## Run Details"])
    for profile_result in matrix:
        if profile_result.error:
            continue
        lines.extend(
            [
                "",
                f"### {profile_result.profile_name}",
                "",
                "| Case | Category | Result | Agent | Patch | Test | Verifier | Failure | Trace | Tools |",
                "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
            ]
        )
        for result in profile_result.results:
            status = "PASS" if result.passed else "FAIL"
            test_status = (
                "timeout"
                if result.test_timed_out
                else f"rc={result.test_returncode}"
            )
            verifier_status = _verifier_status(result)
            lines.append(
                "| "
                + " | ".join(
                    [
                        _md_cell(result.case_id),
                        _md_cell(result.category),
                        status,
                        _md_cell(result.runner_status),
                        "PASS" if result.patch_success else "FAIL",
                        _md_cell(test_status),
                        _md_cell(verifier_status),
                        _md_cell(result.failure_category),
                        _md_cell(str(result.trace_path)),
                        _md_cell(_format_tool_counts(result.tool_counts)),
                    ]
                )
                + " |"
            )

    errored_profiles = [item for item in matrix if item.error]
    if errored_profiles:
        lines.extend(["", "## Profile Errors", ""])
        for item in errored_profiles:
            lines.append(
                f"- `{item.profile_name}` (`{item.provider}`): "
                f"{_inline(item.error or '')}"
            )

    return "\n".join(lines).rstrip() + "\n"


def count_trace_tools(trace_path: str | Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    path = Path(trace_path)
    if not path.exists():
        return counts

    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("type") != "tool_result":
            continue
        result = record.get("result")
        if not isinstance(result, dict):
            continue
        tool_name = result.get("tool_name")
        if not isinstance(tool_name, str):
            continue
        counts[tool_name] = counts.get(tool_name, 0) + 1
    return counts


def _append_test_result_event(
    *,
    trace_path: Path,
    run_id: str,
    case: EvalCase,
    test_result: "_CommandResult",
    passed: bool,
    reason: str,
) -> None:
    event = {
        "type": "test_result",
        "ts": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "case_id": case.id,
        "command": case.test_command,
        "passed": passed,
        "reason": reason,
        "returncode": test_result.returncode,
        "stdout": _clip(test_result.stdout, 4000),
        "stderr": _clip(test_result.stderr, 4000),
        "timed_out": test_result.timed_out,
        "duration_seconds": test_result.duration_seconds,
    }
    with Path(trace_path).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def _append_verifier_result_event(
    *,
    trace_path: Path,
    run_id: str,
    case: EvalCase,
    verifier_result: "_CommandResult",
    passed: bool,
    reason: str,
) -> None:
    event = {
        "type": "verifier_result",
        "ts": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "case_id": case.id,
        "command": case.verifier,
        "passed": passed,
        "reason": reason,
        "returncode": verifier_result.returncode,
        "stdout": _clip(verifier_result.stdout, 4000),
        "stderr": _clip(verifier_result.stderr, 4000),
        "timed_out": verifier_result.timed_out,
        "duration_seconds": verifier_result.duration_seconds,
    }
    with Path(trace_path).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


@dataclass(slots=True)
class _CommandResult:
    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool
    duration_seconds: float


def _run_test_command(case: EvalCase, cwd: Path) -> _CommandResult:
    return _run_command_for_eval(case.test_command, cwd, case.timeout)


def _run_verifier(
    case: EvalCase,
    cwd: Path,
    run_result: "RunResult",
) -> _CommandResult | None:
    if case.verifier is None:
        return None
    return _run_command_for_eval(
        case.verifier,
        cwd,
        case.timeout,
        extra_env={
            "HARNESSCODER_TRACE_PATH": str(run_result.trace_path),
            "HARNESSCODER_RUN_ID": run_result.run_id,
            "HARNESSCODER_RUN_STATUS": run_result.status,
        },
    )


def _run_command_for_eval(
    command: str,
    cwd: Path,
    timeout: int,
    *,
    extra_env: dict[str, str] | None = None,
) -> _CommandResult:
    started = time.monotonic()
    try:
        parts = shlex.split(command)
    except ValueError as exc:
        return _CommandResult(
            returncode=None,
            stdout="",
            stderr=f"could not parse command: {exc}",
            timed_out=False,
            duration_seconds=time.monotonic() - started,
        )

    if not parts:
        return _CommandResult(
            returncode=None,
            stdout="",
            stderr="command parsed to no arguments",
            timed_out=False,
            duration_seconds=time.monotonic() - started,
        )

    env = safe_subprocess_env({"PYTHONUTF8": "1", **(extra_env or {})})
    try:
        completed = subprocess.run(
            parts,
            cwd=cwd,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
            env=env,
        )
    except FileNotFoundError:
        return _CommandResult(
            returncode=None,
            stdout="",
            stderr=f"command not found: {parts[0]}",
            timed_out=False,
            duration_seconds=time.monotonic() - started,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = redact_sensitive_text(_decode_timeout_output(exc.stdout))
        stderr = redact_sensitive_text(_decode_timeout_output(exc.stderr))
        return _CommandResult(
            returncode=None,
            stdout=stdout,
            stderr=stderr or f"command timed out after {timeout}s",
            timed_out=True,
            duration_seconds=time.monotonic() - started,
        )

    return _CommandResult(
        returncode=completed.returncode,
        stdout=redact_sensitive_text(completed.stdout),
        stderr=redact_sensitive_text(completed.stderr),
        timed_out=False,
        duration_seconds=time.monotonic() - started,
    )


def _score_case(
    case: EvalCase,
    runner_status: str,
    test_result: _CommandResult,
    verifier_result: _CommandResult | None,
) -> tuple[bool, str]:
    reasons: list[str] = []
    if runner_status != "success":
        reasons.append(f"agent status was {runner_status!r}")

    test_passed, test_reason = _score_test_result(case, test_result)
    if not test_passed:
        reasons.append(test_reason)

    verifier_passed, verifier_reason = _score_verifier_result(case, verifier_result)
    if not verifier_passed:
        reasons.append(verifier_reason)

    if reasons:
        return False, "; ".join(reasons)
    return True, "agent completed and success criteria matched"


def _score_test_result(
    case: EvalCase,
    test_result: _CommandResult,
) -> tuple[bool, str]:
    reasons: list[str] = []
    if test_result.timed_out:
        reasons.append(f"test command timed out after {case.timeout}s")

    if case.success_returncode is not None and (
        test_result.returncode != case.success_returncode
    ):
        reasons.append(
            f"expected return code {case.success_returncode}, got "
            f"{test_result.returncode}"
        )

    if case.success_contains is not None:
        output = "\n".join([test_result.stdout, test_result.stderr])
        needles = (
            (case.success_contains,)
            if isinstance(case.success_contains, str)
            else case.success_contains
        )
        missing = [needle for needle in needles if needle not in output]
        if missing:
            reasons.append(f"missing expected output: {missing}")

    if reasons:
        return False, "; ".join(reasons)
    return True, "success criteria matched"


def _score_verifier_result(
    case: EvalCase,
    verifier_result: _CommandResult | None,
) -> tuple[bool, str]:
    if case.verifier is None:
        return True, "no verifier configured"
    if verifier_result is None:
        return False, "verifier did not run"
    if verifier_result.timed_out:
        return False, f"verifier timed out after {case.timeout}s"
    if verifier_result.returncode != 0:
        return False, f"verifier expected return code 0, got {verifier_result.returncode}"
    return True, "verifier matched"


def _build_model(provider: str) -> ModelAdapter:
    if provider == "scripted":
        return ScriptedModel()

    if provider == "hc-bench-oracle":
        return HCBenchOracleModel()

    if provider in {"openai-codex", "openai-chat"}:
        api_key = os.environ.get("OPENAI_API_KEY")
        model = os.environ.get("HARNESSCODER_OPENAI_MODEL") or os.environ.get(
            "OPENAI_MODEL"
        )
        base_url = os.environ.get("HARNESSCODER_OPENAI_BASE_URL") or os.environ.get(
            "OPENAI_BASE_URL", "https://api.openai.com/v1"
        )
        if not api_key:
            raise ValueError(f"OPENAI_API_KEY is required for provider={provider!r}")
        if not model:
            raise ValueError(
                "HARNESSCODER_OPENAI_MODEL or OPENAI_MODEL is required for "
                f"provider={provider!r}"
            )
        model_cls = OpenAICodexModel if provider == "openai-codex" else OpenAIChatModel
        return model_cls(api_key=api_key, model=model, base_url=base_url)

    raise ValueError(f"unsupported eval provider: {provider}")


def _resolve_cases_path(cases_path: str | Path, workspace_root: Path) -> Path:
    path = Path(cases_path)
    if path.is_absolute():
        return path.resolve()
    return (workspace_root / path).resolve()


def _resolve_trace_root(trace_root: str | Path, workspace_root: Path) -> Path:
    path = Path(trace_root)
    if path.is_absolute():
        return path.resolve()
    return (workspace_root / path).resolve()


def _resolve_fixture_path(
    repo_fixture: str,
    workspace_root: Path,
    cases_path: Path,
) -> Path:
    raw_path = Path(repo_fixture)
    candidates: list[Path] = []
    if raw_path.is_absolute():
        candidates.append(raw_path)
    else:
        candidates.append(workspace_root / raw_path)
        candidates.append(cases_path.parent / raw_path)

    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.exists() and resolved.is_dir():
            return resolved

    searched = ", ".join(str(candidate.resolve()) for candidate in candidates)
    raise ValueError(f"repo_fixture does not exist or is not a directory: {searched}")


def _resolve_inside(root: Path, path: str) -> Path:
    target = (root / path).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"eval case cwd escapes workspace_root: {path}") from exc
    if not target.exists():
        raise ValueError(f"eval case cwd does not exist: {path}")
    if not target.is_dir():
        raise ValueError(f"eval case cwd is not a directory: {path}")
    return target


def _safe_path_segment(value: str) -> str:
    cleaned = "".join(
        char if char.isalnum() or char in {"-", "_", "."} else "-"
        for char in value
    )
    return cleaned.strip(".-") or "case"


def _required_str(record: dict[str, Any], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"eval case field {key!r} must be a non-empty string")
    return value


def _optional_str(
    record: dict[str, Any],
    key: str,
    default: str | None,
) -> str | None:
    value = record.get(key, default)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"eval case field {key!r} must be a non-empty string")
    return value


def _optional_str_tuple(
    record: dict[str, Any],
    key: str,
    default: tuple[str, ...] | None,
) -> tuple[str, ...] | None:
    value = record.get(key, default)
    if value is None:
        return None
    if not isinstance(value, list) or not value:
        raise ValueError(f"eval case field {key!r} must be a non-empty string list")
    items: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"eval case field {key!r} must contain non-empty strings")
        if item in items:
            raise ValueError(f"eval case field {key!r} contains duplicate tool: {item}")
        items.append(item)
    return tuple(items)


def _required_int(record: dict[str, Any], key: str) -> int:
    value = record.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"eval case field {key!r} must be an integer")
    if value <= 0:
        raise ValueError(f"eval case field {key!r} must be positive")
    return value


def _optional_int(
    record: dict[str, Any],
    key: str,
    default: int | None,
) -> int | None:
    value = record.get(key, default)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"eval case field {key!r} must be an integer")
    return value


def _success_contains(value: Any) -> str | tuple[str, ...] | None:
    if value is None:
        return None
    if isinstance(value, str) and value:
        return value
    if (
        isinstance(value, list)
        and value
        and all(isinstance(item, str) and item for item in value)
    ):
        return tuple(value)
    raise ValueError("success_contains must be a non-empty string or string list")


def _metrics_from_summary(summary: dict[str, Any]) -> dict[str, Any]:
    metrics = summary.get("metrics")
    return dict(metrics) if isinstance(metrics, dict) else {}


def _tool_counts_from_summary(summary: dict[str, Any]) -> dict[str, int]:
    counts = summary.get("tool_counts")
    if not isinstance(counts, dict):
        return {}
    return {
        str(name): count
        for name, count in counts.items()
        if isinstance(count, int) and not isinstance(count, bool)
    }


def _failure_category_from_summary(summary: dict[str, Any]) -> str:
    category = summary.get("failure_category")
    if isinstance(category, str) and category:
        return category
    metrics = summary.get("metrics")
    if isinstance(metrics, dict):
        category = metrics.get("failure_category")
        if isinstance(category, str) and category:
            return category
    return "incomplete"


def _category_summary(results: list[EvalResult]) -> dict[str, list[EvalResult]]:
    grouped: dict[str, list[EvalResult]] = {}
    for result in results:
        grouped.setdefault(result.category, []).append(result)
    return grouped


def _case_ids_from_matrix(matrix: list[EvalMatrixProfileResult]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for profile_result in matrix:
        for case_id in profile_result.planned_case_ids:
            if case_id in seen:
                continue
            seen.add(case_id)
            ordered.append(case_id)
        for result in profile_result.results:
            if result.case_id in seen:
                continue
            seen.add(result.case_id)
            ordered.append(result.case_id)
    return ordered


def _average_metric(results: list[EvalResult], key: str) -> float:
    if not results:
        return 0.0
    return _sum_metric(results, key) / len(results)


def _average_nullable_metric(results: list[EvalResult], key: str) -> float | None:
    values: list[float] = []
    for result in results:
        value = result.metrics.get(key)
        if isinstance(value, bool) or value is None:
            continue
        if isinstance(value, (int, float)):
            values.append(float(value))
    if not values:
        return None
    return sum(values) / len(values)


def _sum_metric(results: list[EvalResult], key: str) -> int:
    total = 0
    for result in results:
        value = result.metrics.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            total += value
        elif isinstance(value, float):
            total += int(value)
    return total


def _max_metric(results: list[EvalResult], key: str) -> int:
    largest = 0
    for result in results:
        value = result.metrics.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            largest = max(largest, value)
        elif isinstance(value, float):
            largest = max(largest, int(value))
    return largest


def _output_compression_ratio(results: list[EvalResult]) -> float | None:
    raw_chars = _sum_metric(results, "raw_tool_output_chars")
    preview_chars = _sum_metric(results, "tool_output_preview_chars")
    if raw_chars <= 0:
        return None
    return preview_chars / raw_chars


def _format_rate(count: int, total: int) -> str:
    if total <= 0:
        return "n/a"
    return f"{(count / total) * 100:.1f}% ({count}/{total})"


def _format_number(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return f"{value:.2f}"


def _format_nullable_rate(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.1f}%"


def _format_nullable_number(value: float | None) -> str:
    if value is None:
        return "n/a"
    return _format_number(value)


def _format_breakdown(counts: Counter[str]) -> str:
    if not counts:
        return "-"
    return ", ".join(f"{name}={count}" for name, count in sorted(counts.items()))


def _format_metrics(metrics: dict[str, Any]) -> str:
    if not metrics:
        return "-"
    preferred = [
        "average_tool_calls",
        "repeated_tool_calls",
        "repeated_read_count",
        "invalid_tool_call_count",
        "policy_denial_count",
        "failed_tool_count",
        "raw_tool_output_chars",
        "tool_output_preview_chars",
        "stored_artifact_count",
        "artifact_missing_count",
        "artifact_hash_mismatch_count",
        "largest_tool_output_chars",
        "observation_compression_ratio",
        "context_packed_count",
        "context_injected_count",
        "estimated_context_tokens",
        "memory_updated_count",
        "compression_count",
        "hot_observation_count",
        "cold_summary_chars",
        "time_to_first_edit",
        "search_to_edit_steps",
        "edit_to_test_steps",
        "checkpoint_created_count",
        "resume_success_rate",
        "test_passed",
        "failure_category",
    ]
    parts = [
        f"{key}={metrics[key]}"
        for key in preferred
        if key in metrics
    ]
    return ", ".join(parts) if parts else "-"


def _format_tool_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "-"
    return ", ".join(f"{name}={count}" for name, count in sorted(counts.items()))


def _verifier_status(result: EvalResult) -> str:
    if not result.verifier_command:
        return "-"
    if result.verifier_timed_out:
        return "timeout"
    return f"rc={result.verifier_returncode}"


def _md_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", "<br>")


def _inline(value: str) -> str:
    return value.replace("\n", " ")


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}... [truncated {len(text) - limit} chars]"


def _decode_timeout_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value
