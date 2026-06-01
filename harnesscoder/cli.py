from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Sequence

from harnesscoder import __version__
from harnesscoder.core.models import (
    HCBenchOracleModel,
    ModelAdapter,
    OpenAIChatModel,
    OpenAICodexModel,
    REASONING_EFFORT_CHOICES,
    ScriptedModel,
)
from harnesscoder.core.runner import AgentRunner
from harnesscoder.replay import summarize_trace
from harnesscoder.core.session import DEFAULT_SESSION_ID, DEFAULT_SESSION_ROOT, SessionStore
from harnesscoder.model_profiles import (
    ModelProfile,
    load_model_profiles,
    parse_profile_names,
    resolve_model_config_path,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="harnesscoder",
        description="Run the HarnessCoder local coding agent harness.",
    )
    parser.add_argument("task", nargs="*", help="Task for the agent to run.")
    parser.add_argument(
        "--tui",
        action="store_true",
        help="Start the interactive terminal UI.",
    )
    parser.add_argument(
        "--replay",
        metavar="TRACE",
        help="Summarize a trace.jsonl file or run directory and exit.",
    )
    parser.add_argument(
        "--resume",
        metavar="CHECKPOINT",
        help="Resume an interrupted run from checkpoint.json.",
    )
    parser.add_argument(
        "--eval",
        metavar="CASES_JSON",
        help="Run eval cases and print a Markdown report.",
    )
    parser.add_argument(
        "--eval-report",
        metavar="PATH",
        help="Write the eval Markdown report to a file.",
    )
    parser.add_argument(
        "--model-config",
        default=os.environ.get("HARNESSCODER_MODEL_CONFIG", "models.toml"),
        help="TOML model profile config. Defaults to models.toml.",
    )
    parser.add_argument(
        "--model-profile",
        help="Run a single configured model profile.",
    )
    parser.add_argument(
        "--investigator-model-profile",
        default=os.environ.get("HARNESSCODER_INVESTIGATOR_MODEL_PROFILE"),
        help=(
            "Optional model profile for read-only investigator delegations, "
            "for example mimo-v2.5."
        ),
    )
    parser.add_argument(
        "--model-profiles",
        help="Comma-separated profiles for eval matrix mode, for example scripted,gpt55.",
    )
    parser.add_argument(
        "--context-ablations",
        action="store_true",
        help=(
            "Run the context ablation matrix for --eval "
            "(full/no_repomap/no_memory/no_context_compaction/no_policy_retry)."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"harnesscoder {__version__}",
    )
    parser.add_argument(
        "--cwd",
        default=".",
        help="Repository working directory. Defaults to the current directory.",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=8,
        help="Maximum agent loop iterations.",
    )
    parser.add_argument(
        "--context-mode",
        choices=["none", "pack", "memory"],
        default=os.environ.get("HARNESSCODER_CONTEXT_MODE", "none"),
        help="Prompt context mode: none, pack, or memory.",
    )
    parser.add_argument(
        "--repo-map-mode",
        choices=["none", "auto"],
        default=os.environ.get("HARNESSCODER_REPO_MAP_MODE", "auto"),
        help="RepoMap prompt injection mode. Defaults to auto.",
    )
    parser.add_argument(
        "--notes-mode",
        choices=["none", "auto"],
        default=os.environ.get("HARNESSCODER_NOTES_MODE", "auto"),
        help="Durable note retrieval mode. Defaults to auto.",
    )
    parser.add_argument(
        "--trace-root",
        default=".harnesscoder/runs",
        help="Directory where run traces are written.",
    )
    parser.add_argument(
        "--session",
        metavar="ID",
        help=(
            "Use a durable cross-run session for this task. "
            f"Defaults to {DEFAULT_SESSION_ID!r} in the TUI."
        ),
    )
    parser.add_argument(
        "--session-root",
        default=str(DEFAULT_SESSION_ROOT),
        help="Directory where durable session JSON files are written.",
    )
    parser.add_argument(
        "--eval-trace-root",
        default=".harnesscoder/eval-runs",
        help="Directory where eval run traces are written.",
    )
    parser.add_argument(
        "--provider",
        choices=["scripted", "hc-bench-oracle", "openai-codex", "openai-chat"],
        default=os.environ.get("HARNESSCODER_MODEL_PROVIDER", "scripted"),
        help="Model provider. Defaults to scripted.",
    )
    parser.add_argument(
        "--openai-base-url",
        default=os.environ.get("HARNESSCODER_OPENAI_BASE_URL")
        or os.environ.get("OPENAI_BASE_URL")
        or "https://api.openai.com/v1",
        help="OpenAI-compatible base URL for --provider openai-codex/openai-chat.",
    )
    parser.add_argument(
        "--openai-model",
        default=os.environ.get("HARNESSCODER_OPENAI_MODEL")
        or os.environ.get("OPENAI_MODEL"),
        help="Model name for --provider openai-codex/openai-chat.",
    )
    parser.add_argument(
        "--openai-api-key-env",
        default="OPENAI_API_KEY",
        help="Environment variable that stores the API key.",
    )
    parser.add_argument(
        "--reasoning-effort",
        choices=REASONING_EFFORT_CHOICES,
        default=os.environ.get("HARNESSCODER_REASONING_EFFORT"),
        help=(
            "Codex Responses reasoning effort for --provider openai-codex: "
            "none, minimal, low, medium, high, or xhigh."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv_for_argv(argv)
    parser = build_parser()
    args = parser.parse_args(argv)

    task = " ".join(args.task).strip()
    cwd = Path(args.cwd).resolve()

    if args.replay:
        import json

        summary = summarize_trace(args.replay)
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    if args.resume:
        runner = AgentRunner(
            model=build_model(args),
            readonly_investigator_model=build_investigator_model(args, cwd),
            cwd=cwd,
            trace_root=Path(args.trace_root),
            max_iterations=args.max_iterations,
            context_mode=args.context_mode,
            repo_map_mode=args.repo_map_mode,
            notes_mode=args.notes_mode,
        )
        result = runner.resume_from_checkpoint(args.resume)
        print(result.final_answer)
        print()
        print(f"status: {result.status}")
        print(f"run_id: {result.run_id}")
        print(f"trace: {result.trace_path}")
        return 0 if result.status == "success" else 1

    if args.eval:
        from harnesscoder.eval_runner import (
            render_context_ablation_matrix,
            render_markdown_matrix,
            render_markdown_report,
            run_context_ablation_matrix,
            run_eval_cases,
            run_eval_matrix,
        )

        if args.context_ablations:
            if args.model_profiles:
                raise SystemExit(
                    "--context-ablations accepts --provider or one --model-profile; "
                    "do not combine it with --model-profiles."
                )
            profile = (
                resolve_model_profile(args.model_profile, args, cwd)
                if args.model_profile
                else None
            )
            matrix = run_context_ablation_matrix(
                cases_path=args.eval,
                workspace_root=cwd,
                provider=args.provider,
                profile=profile,
                trace_root=Path(args.eval_trace_root),
                max_iterations=args.max_iterations,
            )
            report = render_context_ablation_matrix(matrix)
            if args.eval_report:
                report_path = Path(args.eval_report)
                report_path.parent.mkdir(parents=True, exist_ok=True)
                report_path.write_text(report, encoding="utf-8")
                print(f"context ablation report: {report_path.resolve()}")
            else:
                print(report, end="")
            matrix_completed = all(item.error is None for item in matrix)
            return 0 if matrix_completed else 1

        if args.model_profiles:
            profiles = build_eval_profiles(args, cwd)
            matrix = run_eval_matrix(
                cases_path=args.eval,
                workspace_root=cwd,
                profiles=profiles,
                trace_root=Path(args.eval_trace_root),
                max_iterations=args.max_iterations,
                context_mode=args.context_mode,
                repo_map_mode=args.repo_map_mode,
                notes_mode=args.notes_mode,
            )
            report = render_markdown_matrix(matrix)
            if args.eval_report:
                report_path = Path(args.eval_report)
                report_path.parent.mkdir(parents=True, exist_ok=True)
                report_path.write_text(report, encoding="utf-8")
                print(f"eval matrix report: {report_path.resolve()}")
            else:
                print(report, end="")
            matrix_passed = all(
                profile_result.error is None
                and profile_result.results
                and all(result.passed for result in profile_result.results)
                for profile_result in matrix
            )
            return 0 if matrix_passed else 1

        model = build_model(args)
        results = run_eval_cases(
            cases_path=args.eval,
            workspace_root=cwd,
            provider=args.provider,
            trace_root=Path(args.eval_trace_root),
            max_iterations=args.max_iterations,
            model=model,
            context_mode=args.context_mode,
            repo_map_mode=args.repo_map_mode,
            notes_mode=args.notes_mode,
        )
        report = render_markdown_report(results)
        if args.eval_report:
            report_path = Path(args.eval_report)
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(report, encoding="utf-8")
            print(f"eval report: {report_path.resolve()}")
        else:
            print(report, end="")
        return 0 if all(result.passed for result in results) else 1

    if args.tui:
        from harnesscoder.tui import TuiConfig, run_tui

        if args.model_profile:
            raise SystemExit(
                "--model-profile is not supported with --tui yet; use --provider, "
                "--openai-model, --openai-base-url, and --openai-api-key-env instead."
            )
        return run_tui(
            TuiConfig(
                cwd=cwd,
                trace_root=Path(args.trace_root),
                provider=args.provider,
                openai_base_url=args.openai_base_url,
                openai_model=args.openai_model,
                openai_api_key_env=args.openai_api_key_env,
                reasoning_effort=args.reasoning_effort,
                max_iterations=args.max_iterations,
                context_mode=args.context_mode,
                repo_map_mode=args.repo_map_mode,
                notes_mode=args.notes_mode,
                session_id=args.session or DEFAULT_SESSION_ID,
                session_root=Path(args.session_root),
            ),
            initial_message=task or None,
        )

    if not task:
        parser.error("task is required unless --tui is used")

    runner = AgentRunner(
        model=build_model(args),
        readonly_investigator_model=build_investigator_model(args, cwd),
        cwd=cwd,
        trace_root=Path(args.trace_root),
        max_iterations=args.max_iterations,
        context_mode=args.context_mode,
        repo_map_mode=args.repo_map_mode,
        notes_mode=args.notes_mode,
    )
    session_store = SessionStore(Path(args.session_root), cwd) if args.session else None
    session_context = (
        session_store.build_context(args.session) if session_store is not None else None
    )
    result = runner.run(task, session_context=session_context)
    if session_store is not None:
        session_store.append_run(args.session, user_message=task, result=result)

    print(result.final_answer)
    print()
    print(f"status: {result.status}")
    print(f"run_id: {result.run_id}")
    print(f"trace: {result.trace_path}")
    _print_runtime_summary(result.trace_path)
    if args.session:
        print(f"session: {session_store.path_for(args.session)}")

    return 0 if result.status == "success" else 1


def _print_runtime_summary(trace_path: Path) -> None:
    summary = summarize_trace(trace_path)
    metrics = summary.get("metrics", {})
    notes = int(metrics.get("note_injected_count") or 0)
    note_created = int(metrics.get("note_created_count") or 0)
    note_retrieved = int(metrics.get("note_retrieved_count") or 0)
    quality = metrics.get("average_context_quality_score")
    low_quality = int(metrics.get("low_quality_context_count") or 0)
    low_relevance = int(metrics.get("low_relevance_context_count") or 0)
    low_completeness = int(metrics.get("low_completeness_context_count") or 0)
    plan_steps = int(metrics.get("plan_step_count") or 0)
    plan_created = int(metrics.get("plan_created_count") or 0)
    plan_updated = int(metrics.get("plan_updated_count") or 0)
    blocked_steps = int(metrics.get("blocked_step_count") or 0)
    action_with_step_ratio = metrics.get("action_with_step_ratio")

    print(
        "notes: "
        f"injected={notes} created={note_created} retrieved={note_retrieved}"
    )
    if quality is not None:
        print(
            "context_quality: "
            f"score={quality} low_quality={low_quality} "
            f"low_relevance={low_relevance} low_completeness={low_completeness}"
        )
    else:
        print("context_quality: score=-")
    if action_with_step_ratio is None:
        plan_ratio = "-"
    else:
        plan_ratio = str(action_with_step_ratio)
    print(
        "plan: "
        f"created={plan_created} updated={plan_updated} "
        f"steps={plan_steps} blocked={blocked_steps} action_with_step_ratio={plan_ratio}"
    )


def build_model(args: argparse.Namespace) -> ModelAdapter:
    if args.model_profile:
        return resolve_model_profile(args.model_profile, args, Path(args.cwd).resolve()).build()

    if args.provider == "scripted":
        return ScriptedModel()

    if args.provider == "hc-bench-oracle":
        return HCBenchOracleModel()

    if args.provider not in {"openai-codex", "openai-chat"}:
        raise SystemExit(f"unsupported provider: {args.provider}")

    api_key = os.environ.get(args.openai_api_key_env)
    if not api_key:
        raise SystemExit(
            f"{args.openai_api_key_env} is required for --provider {args.provider}"
        )
    if not args.openai_model:
        raise SystemExit(
            "HARNESSCODER_OPENAI_MODEL, OPENAI_MODEL, or --openai-model is required for "
            f"--provider {args.provider}"
        )

    model_cls = OpenAICodexModel if args.provider == "openai-codex" else OpenAIChatModel
    if args.provider == "openai-chat" and args.reasoning_effort:
        raise SystemExit("--reasoning-effort is only supported by --provider openai-codex")
    model_kwargs = {
        "api_key": api_key,
        "base_url": args.openai_base_url,
        "model": args.openai_model,
    }
    if args.provider == "openai-codex":
        model_kwargs["reasoning_effort"] = args.reasoning_effort
    return model_cls(
        **model_kwargs,
    )


def build_investigator_model(
    args: argparse.Namespace,
    cwd: Path,
) -> ModelAdapter | None:
    profile_name = getattr(args, "investigator_model_profile", None)
    if not profile_name:
        return None
    return resolve_model_profile(profile_name, args, cwd).build()


def build_eval_profiles(
    args: argparse.Namespace,
    cwd: Path,
) -> list[ModelProfile]:
    if not args.model_profiles:
        return [resolve_model_profile(args.model_profile or args.provider, args, cwd)]

    try:
        names = parse_profile_names(args.model_profiles)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    return [resolve_model_profile(name, args, cwd) for name in names]


def resolve_model_profile(
    name: str,
    args: argparse.Namespace,
    cwd: Path,
) -> ModelProfile:
    config_profiles = _load_config_profiles_if_present(args.model_config, cwd)
    if name in config_profiles:
        return config_profiles[name]

    if name == "scripted":
        return ModelProfile(name="scripted", provider="scripted")
    if name == "hc-bench-oracle":
        return ModelProfile(name="hc-bench-oracle", provider="hc-bench-oracle")
    if name in {"openai", "openai-codex"}:
        return ModelProfile(
            name=name,
            provider="openai-codex",
            model=args.openai_model,
            base_url=args.openai_base_url,
            api_key_env=args.openai_api_key_env,
            reasoning_effort=args.reasoning_effort,
        )
    if name in {"openai-chat", "deepseek"}:
        return ModelProfile(
            name=name,
            provider="openai-chat",
            model=args.openai_model,
            base_url=args.openai_base_url,
            api_key_env=args.openai_api_key_env,
        )
    if name in {"mimo", "mimo-v2.5", "mimo-v2_5"}:
        return ModelProfile(
            name=name,
            provider="openai-chat",
            model="mimo-v2.5",
            base_url=args.openai_base_url,
            api_key_env=args.openai_api_key_env,
        )

    config_path = resolve_model_config_path(args.model_config, cwd)
    raise SystemExit(
        f"model profile {name!r} was not found in {config_path}. "
        "Use --model-config or one of the built-in profiles: scripted, "
        "hc-bench-oracle, openai-codex, openai-chat, mimo-v2.5."
    )


def _load_config_profiles_if_present(
    config_path: str,
    cwd: Path,
) -> dict[str, ModelProfile]:
    resolved = resolve_model_config_path(config_path, cwd)
    if not resolved.exists():
        return {}
    try:
        return load_model_profiles(resolved)
    except ValueError as exc:
        raise SystemExit(f"{resolved}: {exc}") from exc


def load_dotenv_for_argv(argv: Sequence[str] | None = None) -> None:
    """Load .env before argparse reads environment-backed defaults."""

    cwd_parser = argparse.ArgumentParser(add_help=False)
    cwd_parser.add_argument("--cwd", default=".")
    known, _ = cwd_parser.parse_known_args(argv)
    cwd = Path(known.cwd).resolve()

    load_dotenv(Path.cwd() / ".env")
    if cwd != Path.cwd().resolve():
        load_dotenv(cwd / ".env")


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        if not key or any(char.isspace() for char in key):
            continue

        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]

        os.environ.setdefault(key, value)
