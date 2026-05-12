from __future__ import annotations

import curses
import json
import os
import shlex
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import uuid4

from harnesscoder.core.models import HCBenchOracleModel, OpenAICodexModel, ScriptedModel
from harnesscoder.core.policy import ToolPolicy
from harnesscoder.core.runner import AgentRunner
from harnesscoder.core.tools import ToolRegistry


Role = Literal["system", "user", "assistant", "tool", "error"]


@dataclass(slots=True)
class TuiConfig:
    cwd: Path
    trace_root: Path
    provider: str
    openai_base_url: str
    openai_model: str | None
    openai_api_key_env: str
    max_iterations: int


@dataclass(slots=True)
class Message:
    role: Role
    text: str


class HarnessCoderTui:
    def __init__(self, config: TuiConfig, initial_message: str | None = None) -> None:
        self.config = config
        self.initial_message = initial_message
        self.messages: list[Message] = [
            Message(
                "system",
                "Welcome to HarnessCoder TUI. Type a message to run the agent, "
                "or /help for slash commands.",
            )
        ]
        self.input_buffer = ""
        self.status = "ready"
        self.last_trace_path: Path | None = None
        self._colors: dict[str, int] = {}

    def run(self) -> int:
        return curses.wrapper(self._main)

    def _main(self, screen: curses.window) -> int:
        try:
            curses.curs_set(1)
        except curses.error:
            pass
        screen.keypad(True)
        self._init_colors()

        if self.initial_message:
            self._handle_user_message(self.initial_message, screen)

        while True:
            self._draw(screen)
            try:
                key = screen.get_wch()
            except KeyboardInterrupt:
                return 0

            if key in ("\n", "\r") or key == curses.KEY_ENTER:
                line = self.input_buffer.strip()
                self.input_buffer = ""
                if not line:
                    continue
                if line in {"/quit", "/exit"}:
                    return 0
                if line.startswith("/"):
                    self._handle_slash_command(line, screen)
                else:
                    self._handle_user_message(line, screen)
                continue

            if key in (curses.KEY_BACKSPACE, "\b", "\x7f"):
                self.input_buffer = self.input_buffer[:-1]
                continue

            if key == "\x03" or key == "\x04":
                return 0

            if isinstance(key, str) and key.isprintable():
                self.input_buffer += key

    def _init_colors(self) -> None:
        if not curses.has_colors():
            return
        curses.start_color()
        curses.use_default_colors()
        pairs = {
            "title": (curses.COLOR_CYAN, -1),
            "muted": (curses.COLOR_BLUE, -1),
            "user": (curses.COLOR_GREEN, -1),
            "assistant": (curses.COLOR_WHITE, -1),
            "tool": (curses.COLOR_YELLOW, -1),
            "error": (curses.COLOR_RED, -1),
        }
        for index, (name, colors) in enumerate(pairs.items(), start=1):
            curses.init_pair(index, colors[0], colors[1])
            self._colors[name] = curses.color_pair(index)

    def _draw(self, screen: curses.window) -> None:
        screen.erase()
        height, width = screen.getmaxyx()
        width = max(width, 20)
        body_height = max(1, height - 7)

        self._draw_header(screen, width)

        body_lines = self._render_messages(width - 2)
        visible = body_lines[-body_height:]
        for row, (line, color_name) in enumerate(visible, start=4):
            if row >= height - 3:
                break
            self._safe_addstr(screen, row, 1, line[: width - 2], color_name)

        divider = "-" * (width - 1)
        self._safe_addstr(screen, height - 3, 0, divider, "muted")
        prompt = "> " + self.input_buffer
        self._safe_addstr(screen, height - 2, 0, prompt[: width - 1], "user")
        self._safe_addstr(screen, height - 1, 0, self.status[: width - 1], "muted")
        screen.refresh()

    def _draw_header(self, screen: curses.window, width: int) -> None:
        title = " HarnessCoder TUI "
        top = "+" + title.center(max(0, width - 2), "-") + "+"
        self._safe_addstr(screen, 0, 0, top[:width], "title")

        model = self.config.openai_model or "-"
        cwd = str(self.config.cwd)
        meta = (
            f" provider={self.config.provider} model={model} "
            f"iters={self.config.max_iterations}"
        )
        self._safe_addstr(screen, 1, 1, meta[: max(1, width - 2)], "muted")
        self._safe_addstr(screen, 2, 1, f" cwd={cwd}"[: max(1, width - 2)], "muted")

        diagram = "[message] -> [model] -> [policy] -> [tools] -> [trace]"
        self._safe_addstr(screen, 3, 1, diagram[: max(1, width - 2)], "title")

    def _render_messages(self, width: int) -> list[tuple[str, str]]:
        rendered: list[tuple[str, str]] = []
        for message in self.messages:
            prefix = {
                "system": "[sys] ",
                "user": "[you] ",
                "assistant": "[agent] ",
                "tool": "[tool] ",
                "error": "[err] ",
            }[message.role]
            color = {
                "system": "muted",
                "user": "user",
                "assistant": "assistant",
                "tool": "tool",
                "error": "error",
            }[message.role]
            first_prefix = prefix
            next_prefix = " " * len(prefix)
            for raw_line in message.text.splitlines() or [""]:
                wrapped = textwrap.wrap(
                    raw_line,
                    width=max(10, width - len(prefix)),
                    replace_whitespace=False,
                    drop_whitespace=False,
                ) or [""]
                for index, line in enumerate(wrapped):
                    rendered.append(
                        (
                            (first_prefix if index == 0 else next_prefix) + line,
                            color,
                        )
                    )
                first_prefix = next_prefix
        return rendered

    def _safe_addstr(
        self,
        screen: curses.window,
        row: int,
        col: int,
        text: str,
        color_name: str,
    ) -> None:
        try:
            screen.addstr(row, col, text, self._colors.get(color_name, 0))
        except curses.error:
            pass

    def _handle_user_message(self, line: str, screen: curses.window) -> None:
        self.messages.append(Message("user", line))
        self.status = "running agent..."
        self._draw(screen)

        try:
            model = self._build_model()
            runner = AgentRunner(
                model=model,
                cwd=self.config.cwd,
                trace_root=self.config.trace_root,
                max_iterations=self.config.max_iterations,
            )
            result = runner.run(line)
        except Exception as exc:
            self.status = "agent failed"
            self.messages.append(Message("error", f"{type(exc).__name__}: {exc}"))
            return

        self.status = f"run {result.run_id}: {result.status}"
        self.last_trace_path = result.trace_path
        reply = (
            f"{result.final_answer}\n\n"
            f"status: {result.status}\n"
            f"trace: {result.trace_path}"
        )
        self.messages.append(Message("assistant", reply))

    def _handle_slash_command(self, line: str, screen: curses.window) -> None:
        try:
            parts = shlex.split(line)
        except ValueError as exc:
            self.messages.append(Message("error", f"Could not parse command: {exc}"))
            return

        if not parts:
            return

        command = parts[0][1:]
        args = parts[1:]

        handlers = {
            "help": self._cmd_help,
            "status": self._cmd_status,
            "clear": self._cmd_clear,
            "provider": self._cmd_provider,
            "model": self._cmd_model,
            "base-url": self._cmd_base_url,
            "cwd": self._cmd_cwd,
            "max-iterations": self._cmd_max_iterations,
            "tools": self._cmd_tools,
            "read": self._cmd_read,
            "search": self._cmd_search,
            "edit": self._cmd_edit,
            "test": self._cmd_test,
            "run": self._cmd_run,
            "trace": self._cmd_trace,
        }

        handler = handlers.get(command)
        if not handler:
            self.messages.append(
                Message("error", f"Unknown slash command: /{command}. Try /help.")
            )
            return

        self.status = f"running /{command}"
        self._draw(screen)
        handler(args, line)
        if self.status.startswith("running /"):
            self.status = "ready"

    def _cmd_help(self, _args: list[str], _line: str) -> None:
        self.messages.append(
            Message(
                "system",
                "\n".join(
                    [
                        "Slash commands:",
                        "/help - show this help",
                        "/status - show cwd/provider/model",
                        "/clear - clear the message pane",
                        "/provider [scripted|hc-bench-oracle|openai-codex] - show or change provider",
                        "/model [name|scripted] - show or change model",
                        "/base-url [url] - show or change OpenAI-compatible base URL",
                        "/cwd [path] - show or change repository cwd",
                        "/max-iterations [n] - show or change loop limit",
                        "/tools - list direct slash tools",
                        "/read <path> [offset] [limit] - call read_file",
                        "/search <query> [path] - call search_code",
                        "/edit <path> <old> <new> - call edit_file exact replacement",
                        "/test [cmd] - call run_tests through the test policy",
                        "/run <cmd> - call run_command through policy gate",
                        "/trace [latest|run_id|path] - summarize a trace",
                        "/quit - exit",
                    ]
                ),
            )
        )

    def _cmd_status(self, _args: list[str], _line: str) -> None:
        self.messages.append(
            Message(
                "system",
                "\n".join(
                    [
                        f"cwd: {self.config.cwd}",
                        f"provider: {self.config.provider}",
                        f"model: {self.config.openai_model or '-'}",
                        f"base_url: {self.config.openai_base_url}",
                        f"max_iterations: {self.config.max_iterations}",
                        f"trace_root: {self.config.trace_root}",
                    ]
                ),
            )
        )

    def _cmd_clear(self, _args: list[str], _line: str) -> None:
        self.messages.clear()
        self.messages.append(Message("system", "Message pane cleared."))

    def _cmd_provider(self, args: list[str], _line: str) -> None:
        if not args:
            self.messages.append(Message("system", f"provider: {self.config.provider}"))
            return
        provider = args[0]
        if provider not in {"scripted", "hc-bench-oracle", "openai-codex"}:
            self.messages.append(
                Message(
                    "error",
                    "Provider must be scripted, hc-bench-oracle, or openai-codex.",
                )
            )
            return
        self.config.provider = provider
        self.messages.append(Message("system", f"provider set to {provider}"))

    def _cmd_model(self, args: list[str], _line: str) -> None:
        if not args:
            self.messages.append(
                Message("system", f"model: {self.config.openai_model or self.config.provider}")
            )
            return
        model = args[0]
        if model == "scripted":
            self.config.provider = "scripted"
            self.config.openai_model = None
            self.messages.append(Message("system", "model set to scripted"))
            return
        if model == "hc-bench-oracle":
            self.config.provider = "hc-bench-oracle"
            self.config.openai_model = None
            self.messages.append(Message("system", "model set to hc-bench-oracle"))
            return
        self.config.provider = "openai-codex"
        self.config.openai_model = model
        self.messages.append(Message("system", f"model set to {model}"))

    def _cmd_base_url(self, args: list[str], _line: str) -> None:
        if not args:
            self.messages.append(Message("system", f"base_url: {self.config.openai_base_url}"))
            return
        self.config.openai_base_url = args[0]
        self.messages.append(Message("system", f"base_url set to {args[0]}"))

    def _cmd_cwd(self, args: list[str], _line: str) -> None:
        if not args:
            self.messages.append(Message("system", f"cwd: {self.config.cwd}"))
            return
        target = Path(args[0]).expanduser()
        if not target.is_absolute():
            target = (self.config.cwd / target).resolve()
        if not target.is_dir():
            self.messages.append(Message("error", f"Not a directory: {target}"))
            return
        self.config.cwd = target.resolve()
        self.messages.append(Message("system", f"cwd set to {self.config.cwd}"))

    def _cmd_max_iterations(self, args: list[str], _line: str) -> None:
        if not args:
            self.messages.append(
                Message("system", f"max_iterations: {self.config.max_iterations}")
            )
            return
        try:
            value = int(args[0])
        except ValueError:
            self.messages.append(Message("error", "max-iterations must be an integer."))
            return
        self.config.max_iterations = max(1, min(value, 50))
        self.messages.append(
            Message("system", f"max_iterations set to {self.config.max_iterations}")
        )

    def _cmd_tools(self, _args: list[str], _line: str) -> None:
        self.messages.append(
            Message(
                "system",
                "Direct tools: /read -> read_file, /search -> search_code, "
                "/edit -> edit_file, /test -> run_tests, /run -> run_command "
                "with policy gate.",
            )
        )

    def _cmd_read(self, args: list[str], _line: str) -> None:
        if not args:
            self.messages.append(Message("error", "Usage: /read <path> [offset] [limit]"))
            return
        offset = int(args[1]) if len(args) > 1 and args[1].isdigit() else 0
        limit = int(args[2]) if len(args) > 2 and args[2].isdigit() else 120
        self._direct_tool("read_file", {"path": args[0], "offset": offset, "limit": limit})

    def _cmd_search(self, args: list[str], _line: str) -> None:
        if not args:
            self.messages.append(Message("error", "Usage: /search <query> [path]"))
            return
        path = args[1] if len(args) > 1 else "."
        self._direct_tool("search_code", {"query": args[0], "path": path})

    def _cmd_edit(self, args: list[str], _line: str) -> None:
        if len(args) < 3:
            self.messages.append(Message("error", "Usage: /edit <path> <old> <new>"))
            return
        self._direct_tool(
            "edit_file",
            {"path": args[0], "old": args[1], "new": args[2]},
        )

    def _cmd_test(self, _args: list[str], line: str) -> None:
        prefix = "/test"
        cmd = line[len(prefix) :].strip()
        payload: dict[str, object] = {"timeout": 60}
        if cmd:
            payload["cmd"] = cmd
        self._direct_tool("run_tests", payload)

    def _cmd_run(self, _args: list[str], line: str) -> None:
        prefix = "/run "
        if not line.startswith(prefix):
            self.messages.append(Message("error", "Usage: /run <cmd>"))
            return
        cmd = line[len(prefix) :].strip()
        if not cmd:
            self.messages.append(Message("error", "Usage: /run <cmd>"))
            return
        self._direct_tool("run_command", {"cmd": cmd, "timeout": 30})

    def _cmd_trace(self, args: list[str], _line: str) -> None:
        try:
            trace_path = self._resolve_trace_path(args[0] if args else None)
            summary = self._summarize_trace(trace_path)
        except Exception as exc:
            self.messages.append(Message("error", f"trace error: {exc}"))
            return
        self.messages.append(Message("tool", summary))

    def _direct_tool(self, tool_name: str, tool_args: dict[str, object]) -> None:
        policy = ToolPolicy()
        decision = policy.check(tool_name, tool_args, self.config.cwd)
        if not decision.allowed:
            self.messages.append(
                Message("error", f"policy denied {tool_name}: {decision.reason}")
            )
            return

        registry = ToolRegistry(self.config.cwd)
        result = registry.execute(f"slash_{uuid4().hex[:12]}", tool_name, tool_args)
        output = result.output or result.error or ""
        if len(output) > 4000:
            output = output[:4000] + f"... [truncated {len(output) - 4000} chars]"
        role: Role = "tool" if result.ok else "error"
        self.messages.append(
            Message(
                role,
                f"{tool_name} ok={result.ok}\npolicy: {decision.reason}\n{output}",
            )
        )

    def _resolve_trace_path(self, value: str | None) -> Path:
        if value in {None, ""}:
            if self.last_trace_path:
                return self.last_trace_path
            value = "latest"

        assert value is not None
        root = self._trace_root_path()
        if value == "latest":
            traces = sorted(
                root.glob("*/trace.jsonl"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            if not traces:
                raise ValueError(f"no traces found under {root}")
            return traces[0]

        candidate = Path(value).expanduser()
        if candidate.is_file():
            return candidate.resolve()

        run_candidate = root / value / "trace.jsonl"
        if run_candidate.is_file():
            return run_candidate.resolve()

        relative_candidate = (self.config.cwd / value).resolve()
        if relative_candidate.is_file():
            return relative_candidate

        raise ValueError(f"trace not found: {value}")

    def _trace_root_path(self) -> Path:
        if self.config.trace_root.is_absolute():
            return self.config.trace_root
        return (self.config.cwd / self.config.trace_root).resolve()

    def _summarize_trace(self, trace_path: Path) -> str:
        counts: dict[str, int] = {}
        events: list[dict[str, object]] = []
        for line in trace_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            event_type = str(event.get("type", "<missing>"))
            counts[event_type] = counts.get(event_type, 0) + 1
            events.append(event)

        if not events:
            raise ValueError(f"empty trace: {trace_path}")

        run_id = events[0].get("run_id", trace_path.parent.name)
        last = events[-1]
        status = last.get("status", "-")
        lines = [
            f"trace: {trace_path}",
            f"run_id: {run_id}",
            f"status: {status}",
            "event_counts: "
            + ", ".join(f"{key}={value}" for key, value in sorted(counts.items())),
            "recent_events:",
        ]
        for event in events[-12:]:
            event_type = event.get("type", "<missing>")
            action = event.get("action")
            result = event.get("result")
            if isinstance(action, dict):
                lines.append(
                    f"- {event_type}: {action.get('kind')} {action.get('tool_name')}"
                )
            elif isinstance(result, dict):
                lines.append(
                    f"- {event_type}: {result.get('tool_name')} ok={result.get('ok')}"
                )
            else:
                lines.append(f"- {event_type}")
        return "\n".join(lines)

    def _build_model(self) -> ScriptedModel | HCBenchOracleModel | OpenAICodexModel:
        if self.config.provider == "scripted":
            return ScriptedModel()
        if self.config.provider == "hc-bench-oracle":
            return HCBenchOracleModel()

        api_key = os.environ.get(self.config.openai_api_key_env)
        if not api_key:
            raise ValueError(
                f"{self.config.openai_api_key_env} is required for openai-codex"
            )
        if not self.config.openai_model:
            raise ValueError("A model name is required. Use /model <name>.")
        return OpenAICodexModel(
            api_key=api_key,
            base_url=self.config.openai_base_url,
            model=self.config.openai_model,
        )


def run_tui(config: TuiConfig, initial_message: str | None = None) -> int:
    return HarnessCoderTui(config, initial_message).run()
