from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Sequence

from harnesscoder import __version__
from harnesscoder.core.models import OpenAICodexModel, ScriptedModel
from harnesscoder.core.runner import AgentRunner


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
        "--trace-root",
        default=".harnesscoder/runs",
        help="Directory where run traces are written.",
    )
    parser.add_argument(
        "--eval-trace-root",
        default=".harnesscoder/eval-runs",
        help="Directory where eval run traces are written.",
    )
    parser.add_argument(
        "--provider",
        choices=["scripted", "openai-codex"],
        default=os.environ.get("HARNESSCODER_MODEL_PROVIDER", "scripted"),
        help="Model provider. Defaults to scripted.",
    )
    parser.add_argument(
        "--openai-base-url",
        default=os.environ.get("HARNESSCODER_OPENAI_BASE_URL")
        or os.environ.get("OPENAI_BASE_URL")
        or "https://api.openai.com/v1",
        help="OpenAI-compatible base URL for --provider openai-codex.",
    )
    parser.add_argument(
        "--openai-model",
        default=os.environ.get("HARNESSCODER_OPENAI_MODEL")
        or os.environ.get("OPENAI_MODEL"),
        help="Model name for --provider openai-codex.",
    )
    parser.add_argument(
        "--openai-api-key-env",
        default="OPENAI_API_KEY",
        help="Environment variable that stores the API key.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv_for_argv(argv)
    parser = build_parser()
    args = parser.parse_args(argv)

    task = " ".join(args.task).strip()
    cwd = Path(args.cwd).resolve()

    if args.replay:
        from harnesscoder.replay import summarize_trace

        import json

        summary = summarize_trace(args.replay)
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    if args.eval:
        from harnesscoder.eval_runner import render_markdown_report, run_eval_cases

        model = build_model(args)
        results = run_eval_cases(
            cases_path=args.eval,
            workspace_root=cwd,
            provider=args.provider,
            trace_root=Path(args.eval_trace_root),
            max_iterations=args.max_iterations,
            model=model,
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

        return run_tui(
            TuiConfig(
                cwd=cwd,
                trace_root=Path(args.trace_root),
                provider=args.provider,
                openai_base_url=args.openai_base_url,
                openai_model=args.openai_model,
                openai_api_key_env=args.openai_api_key_env,
                max_iterations=args.max_iterations,
            ),
            initial_message=task or None,
        )

    if not task:
        parser.error("task is required unless --tui is used")

    runner = AgentRunner(
        model=build_model(args),
        cwd=cwd,
        trace_root=Path(args.trace_root),
        max_iterations=args.max_iterations,
    )
    result = runner.run(task)

    print(result.final_answer)
    print()
    print(f"status: {result.status}")
    print(f"run_id: {result.run_id}")
    print(f"trace: {result.trace_path}")

    return 0 if result.status == "success" else 1


def build_model(args: argparse.Namespace) -> ScriptedModel | OpenAICodexModel:
    if args.provider == "scripted":
        return ScriptedModel()

    api_key = os.environ.get(args.openai_api_key_env)
    if not api_key:
        raise SystemExit(
            f"{args.openai_api_key_env} is required for --provider openai-codex"
        )
    if not args.openai_model:
        raise SystemExit(
            "HARNESSCODER_OPENAI_MODEL, OPENAI_MODEL, or --openai-model is required for "
            "--provider openai-codex"
        )

    return OpenAICodexModel(
        api_key=api_key,
        base_url=args.openai_base_url,
        model=args.openai_model,
    )


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
