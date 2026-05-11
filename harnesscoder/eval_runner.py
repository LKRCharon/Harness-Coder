from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from harnesscoder.core.models import ModelAdapter, OpenAICodexModel, ScriptedModel
from harnesscoder.core.runner import AgentRunner


@dataclass(slots=True)
class EvalCase:
    id: str
    task: str
    cwd: str
    test_command: str
    timeout: int
    success_contains: str | tuple[str, ...] | None = None
    success_returncode: int | None = None

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> "EvalCase":
        case_id = _required_str(record, "id")
        task = _required_str(record, "task")
        cwd = _required_str(record, "cwd")
        test_command = _required_str(record, "test_command")
        timeout = _required_int(record, "timeout")
        success_contains = _success_contains(record.get("success_contains"))
        success_returncode = _optional_int(record, "success_returncode", None)

        if success_contains is None and success_returncode is None:
            raise ValueError(
                f"eval case {case_id!r} must define success_contains or "
                "success_returncode"
            )

        return cls(
            id=case_id,
            task=task,
            cwd=cwd,
            test_command=test_command,
            timeout=timeout,
            success_contains=success_contains,
            success_returncode=success_returncode,
        )


@dataclass(slots=True)
class EvalResult:
    case_id: str
    task: str
    cwd: Path
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


def run_eval_cases(
    cases_path: str | Path,
    workspace_root: str | Path,
    provider: str = "scripted",
    *,
    trace_root: str | Path = ".harnesscoder/eval-runs",
    max_iterations: int = 8,
    model: ModelAdapter | None = None,
) -> list[EvalResult]:
    root = Path(workspace_root).resolve()
    resolved_cases_path = _resolve_cases_path(cases_path, root)
    cases = load_eval_cases(resolved_cases_path)

    results: list[EvalResult] = []
    for case in cases:
        case_cwd = _resolve_inside(root, case.cwd)
        runner = AgentRunner(
            model=model or _build_model(provider),
            cwd=case_cwd,
            trace_root=Path(trace_root),
            max_iterations=max_iterations,
        )
        run_result = runner.run(case.task)
        test_result = _run_test_command(case, case_cwd)
        tool_counts = count_trace_tools(run_result.trace_path)
        passed, reason = _score_case(case, run_result.status, test_result)

        results.append(
            EvalResult(
                case_id=case.id,
                task=case.task,
                cwd=case_cwd,
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
            )
        )

    return results


def render_markdown_report(results: list[EvalResult]) -> str:
    total = len(results)
    passed = sum(1 for result in results if result.passed)
    failed = total - passed
    lines = [
        "# HarnessCoder Eval Report",
        "",
        f"- Cases: {total}",
        f"- Passed: {passed}",
        f"- Failed: {failed}",
        "",
        "| Case | Result | Agent | Test | Run | Tools |",
        "| --- | --- | --- | --- | --- | --- |",
    ]

    for result in results:
        status = "PASS" if result.passed else "FAIL"
        test_status = (
            "timeout"
            if result.test_timed_out
            else f"rc={result.test_returncode}"
        )
        lines.append(
            "| "
            + " | ".join(
                [
                    _md_cell(result.case_id),
                    status,
                    _md_cell(result.runner_status),
                    _md_cell(test_status),
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
                f"- CWD: `{result.cwd}`",
                f"- Test command: `{result.test_command}`",
                f"- Reason: {result.reason}",
                f"- Trace: `{result.trace_path}`",
                f"- Duration: {result.test_duration_seconds:.2f}s",
            ]
        )
        output = _clip(
            "\n".join([result.test_stdout, result.test_stderr]).strip(),
            2000,
        )
        if output:
            lines.extend(["", "```text", output, "```"])

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


@dataclass(slots=True)
class _CommandResult:
    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool
    duration_seconds: float


def _run_test_command(case: EvalCase, cwd: Path) -> _CommandResult:
    started = time.monotonic()
    try:
        parts = shlex.split(case.test_command)
    except ValueError as exc:
        return _CommandResult(
            returncode=None,
            stdout="",
            stderr=f"could not parse test_command: {exc}",
            timed_out=False,
            duration_seconds=time.monotonic() - started,
        )

    if not parts:
        return _CommandResult(
            returncode=None,
            stdout="",
            stderr="test_command parsed to no arguments",
            timed_out=False,
            duration_seconds=time.monotonic() - started,
        )

    env = {**os.environ, "PYTHONUTF8": "1"}
    try:
        completed = subprocess.run(
            parts,
            cwd=cwd,
            text=True,
            capture_output=True,
            timeout=case.timeout,
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
        stdout = _decode_timeout_output(exc.stdout)
        stderr = _decode_timeout_output(exc.stderr)
        return _CommandResult(
            returncode=None,
            stdout=stdout,
            stderr=stderr or f"test_command timed out after {case.timeout}s",
            timed_out=True,
            duration_seconds=time.monotonic() - started,
        )

    return _CommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        timed_out=False,
        duration_seconds=time.monotonic() - started,
    )


def _score_case(
    case: EvalCase,
    runner_status: str,
    test_result: _CommandResult,
) -> tuple[bool, str]:
    reasons: list[str] = []
    if runner_status != "success":
        reasons.append(f"agent status was {runner_status!r}")

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
    return True, "agent completed and success criteria matched"


def _build_model(provider: str) -> ModelAdapter:
    if provider == "scripted":
        return ScriptedModel()

    if provider == "openai-codex":
        api_key = os.environ.get("OPENAI_API_KEY")
        model = os.environ.get("HARNESSCODER_OPENAI_MODEL") or os.environ.get(
            "OPENAI_MODEL"
        )
        base_url = os.environ.get("HARNESSCODER_OPENAI_BASE_URL") or os.environ.get(
            "OPENAI_BASE_URL", "https://api.openai.com/v1"
        )
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required for provider='openai-codex'")
        if not model:
            raise ValueError(
                "HARNESSCODER_OPENAI_MODEL or OPENAI_MODEL is required for "
                "provider='openai-codex'"
            )
        return OpenAICodexModel(api_key=api_key, model=model, base_url=base_url)

    raise ValueError(f"unsupported eval provider: {provider}")


def _resolve_cases_path(cases_path: str | Path, workspace_root: Path) -> Path:
    path = Path(cases_path)
    if path.is_absolute():
        return path.resolve()
    return (workspace_root / path).resolve()


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


def _required_str(record: dict[str, Any], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"eval case field {key!r} must be a non-empty string")
    return value


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


def _format_tool_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "-"
    return ", ".join(f"{name}={count}" for name, count in sorted(counts.items()))


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
