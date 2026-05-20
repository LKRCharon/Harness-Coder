from __future__ import annotations

import curses
import json
import locale
import os
import signal
import shlex
import threading
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import uuid4

from harnesscoder.core.models import (
    HCBenchOracleModel,
    OpenAIChatModel,
    OpenAICodexModel,
    REASONING_EFFORT_CHOICES,
    ScriptedModel,
    normalize_reasoning_effort,
)
from harnesscoder.core.artifacts import store_large_observation
from harnesscoder.core.control import ACTIVE_RUN_READ_ONLY_COMMANDS, RunControlPlane
from harnesscoder.core.policy import ToolPolicy
from harnesscoder.core.prompt import ContextMode
from harnesscoder.core.runner import AgentRunner, RepoMapMode, RunResult
from harnesscoder.core.session import (
    DEFAULT_SESSION_ID,
    DEFAULT_SESSION_ROOT,
    SessionStore,
    normalize_session_id,
)
from harnesscoder.core.tools import ToolRegistry


Role = Literal["system", "user", "assistant", "tool", "error"]
ACTIVE_RUN_ALLOWED_COMMANDS = ACTIVE_RUN_READ_ONLY_COMMANDS


@dataclass(slots=True)
class TuiConfig:
    cwd: Path
    trace_root: Path
    provider: str
    openai_base_url: str
    openai_model: str | None
    openai_api_key_env: str
    max_iterations: int
    reasoning_effort: str | None = None
    context_mode: ContextMode = "none"
    repo_map_mode: RepoMapMode = "auto"
    session_id: str = DEFAULT_SESSION_ID
    session_root: Path = DEFAULT_SESSION_ROOT

    def __post_init__(self) -> None:
        self.reasoning_effort = normalize_reasoning_effort(self.reasoning_effort)
        self.session_id = normalize_session_id(self.session_id)


@dataclass(slots=True)
class Message:
    role: Role
    text: str


@dataclass(slots=True)
class ActiveRun:
    prompt: str
    config: TuiConfig
    started_at: float
    known_traces: set[Path]
    thread: threading.Thread | None = None
    result: RunResult | None = None
    error: str | None = None
    done: bool = False
    trace_path: Path | None = None


CARD_MIN_WIDTH = 24


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
        self._active_run: ActiveRun | None = None
        self._active_lock = threading.Lock()
        self._control = RunControlPlane()
        self._spinner_index = 0
        self._interrupt_requested = False

    def run(self) -> int:
        self._configure_locale()
        previous_sigint_handler = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, self._handle_sigint)
        try:
            while True:
                try:
                    return curses.wrapper(self._main)
                except KeyboardInterrupt:
                    if self._request_exit():
                        return 0
        finally:
            signal.signal(signal.SIGINT, previous_sigint_handler)

    def _handle_sigint(self, _signum: int, _frame: object | None) -> None:
        self._interrupt_requested = True

    def _configure_locale(self) -> None:
        try:
            locale.setlocale(locale.LC_ALL, "")
        except locale.Error:
            pass

    def _main(self, screen: curses.window) -> int:
        try:
            curses.curs_set(1)
        except curses.error:
            pass
        self._configure_control_key_input()
        screen.keypad(True)
        screen.timeout(100)
        self._init_colors()

        if self.initial_message:
            initial_message = self.initial_message
            self.initial_message = None
            self._start_user_message(initial_message)

        try:
            while True:
                if self._handle_pending_interrupt():
                    return 0

                try:
                    self._poll_active_run()
                    self._draw(screen)
                    if self._handle_pending_interrupt():
                        return 0
                    key = screen.get_wch()
                except KeyboardInterrupt:
                    if self._request_exit():
                        return 0
                    continue
                except curses.error:
                    continue

                if key == curses.KEY_RESIZE:
                    continue

                if key in ("\n", "\r") or key == curses.KEY_ENTER:
                    line = self.input_buffer.strip()
                    self.input_buffer = ""
                    if not line:
                        continue
                    if line in {"/quit", "/exit"}:
                        if self._request_exit():
                            return 0
                        continue
                    if line.startswith("/"):
                        self._handle_slash_command(line, screen)
                    else:
                        self._start_user_message(line)
                    continue

                if key in (curses.KEY_BACKSPACE, "\b", "\x7f"):
                    self.input_buffer = self.input_buffer[:-1]
                    continue

                if key == "\x03" or key == "\x04":
                    if self._request_exit():
                        return 0
                    continue

                if isinstance(key, str) and key.isprintable():
                    self.input_buffer += key
        finally:
            self._restore_control_key_input()

    def _configure_control_key_input(self) -> None:
        try:
            curses.noqiflush()
        except curses.error:
            pass
        try:
            curses.raw()
        except curses.error:
            pass

    def _restore_control_key_input(self) -> None:
        try:
            curses.noraw()
        except curses.error:
            pass
        try:
            curses.qiflush()
        except curses.error:
            pass

    def _handle_pending_interrupt(self) -> bool:
        if not self._interrupt_requested:
            return False
        self._interrupt_requested = False
        return self._request_exit()

    def _init_colors(self) -> None:
        if not curses.has_colors():
            return
        curses.start_color()
        curses.use_default_colors()
        pairs = {
            "title": (curses.COLOR_CYAN, -1),
            "muted": (curses.COLOR_BLUE, -1),
            "border": (curses.COLOR_BLUE, -1),
            "status": (curses.COLOR_MAGENTA, -1),
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
        width = max(width, 8)
        if height < 8:
            self._draw_compact(screen, height, width)
            screen.refresh()
            return

        header_height = self._draw_header(screen, height, width)
        footer_height = 4
        body_start = header_height
        body_end = max(body_start, height - footer_height)
        body_height = max(1, body_end - body_start)

        body_lines = self._render_messages(width - 2)
        visible = body_lines[-body_height:]
        for row, (line, color_name) in enumerate(visible, start=body_start):
            if row >= body_end:
                break
            self._safe_addstr(screen, row, 1, self._clip(line, width - 2), color_name)

        self._draw_footer(screen, height, width)
        screen.refresh()

    def _draw_compact(self, screen: curses.window, height: int, width: int) -> None:
        badge, color = self._status_badge()
        lines = [
            (self._clip(f"HC [{badge}] {self._footer_status()}", width - 1), color),
            (self._clip("> " + self.input_buffer, width - 1), "user"),
        ]
        for row, (line, color_name) in enumerate(lines[:height]):
            self._safe_addstr(screen, row, 0, self._clip(line, width - 1), color_name)

    def _draw_header(self, screen: curses.window, height: int, width: int) -> int:
        card_width = self._panel_width(width)
        inner_width = max(8, card_width - 4)
        badge, badge_color = self._status_badge()
        model = self.config.openai_model or "-"
        cwd = self._compact_path(self.config.cwd, max(12, inner_width - 4))

        header_lines = [
            (
                self._key_value_line(
                    [
                        ("state", badge),
                        ("provider", self.config.provider),
                        ("model", model),
                    ],
                    inner_width,
                ),
                badge_color,
            ),
            (
                self._key_value_line(
                    [
                        ("context", self.config.context_mode),
                        ("repo-map", self.config.repo_map_mode),
                        ("iters", str(self.config.max_iterations)),
                        ("reasoning", self.config.reasoning_effort or "-"),
                    ],
                    inner_width,
                ),
                "muted",
            ),
        ]

        if height > 10:
            header_lines.append((f"cwd {cwd}", "muted"))
            pipeline = (
                "message -> model -> policy -> tools -> trace"
                if width >= 68
                else "msg -> model -> tools -> trace"
            )
            header_lines.append((pipeline, "title"))
        elif height > 8:
            header_lines.append((f"cwd {cwd}", "muted"))

        if self._active_run and height > 11:
            header_lines.append((self._active_run_line(), "tool"))

        self._safe_addstr(screen, 0, 0, self._card_title("HarnessCoder", card_width), "title")
        for index, (line, color_name) in enumerate(header_lines, start=1):
            self._safe_addstr(
                screen,
                index,
                0,
                self._card_body(line, card_width),
                color_name,
            )
        bottom_row = len(header_lines) + 1
        self._safe_addstr(screen, bottom_row, 0, self._card_edge(card_width), "border")
        return bottom_row + 1

    def _render_messages(self, width: int) -> list[tuple[str, str]]:
        card_width = self._panel_width(width)
        rendered: list[tuple[str, str]] = []
        for message in self.messages:
            title = {
                "system": "SYSTEM",
                "user": "YOU",
                "assistant": "AGENT",
                "tool": "TOOL",
                "error": "ERROR",
            }[message.role]
            color = {
                "system": "muted",
                "user": "user",
                "assistant": "assistant",
                "tool": "tool",
                "error": "error",
            }[message.role]
            rendered.append((self._card_title(title, card_width), "border"))
            for raw_line in message.text.splitlines() or [""]:
                for line in _wrap_display_lines(raw_line, max(8, card_width - 4)):
                    rendered.append((self._card_body(line, card_width), color))
            rendered.append((self._card_edge(card_width), "border"))
        return rendered

    def _draw_footer(self, screen: curses.window, height: int, width: int) -> None:
        card_width = self._panel_width(width)
        badge, badge_color = self._status_badge()
        status = self._clip(
            f"[{badge}] {self._footer_status()}",
            max(1, card_width - 1),
        )
        self._safe_addstr(screen, height - 4, 0, status, badge_color)

        title = "Prompt"
        if self._active_run:
            title = "Prompt locked"
        self._safe_addstr(screen, height - 3, 0, self._card_title(title, card_width), "title")
        prompt = "> " + self.input_buffer
        if self._active_run:
            prompt = "(running) " + prompt
        self._safe_addstr(screen, height - 2, 0, self._card_body(prompt, card_width), "user")
        self._safe_addstr(screen, height - 1, 0, self._card_edge(card_width), "border")

    def _status_badge(self) -> tuple[str, str]:
        if self._active_run:
            return ("RUNNING", "tool")
        status = self.status.lower()
        if any(marker in status for marker in ("failed", "error", "blocked", "denied")):
            return ("ATTENTION", "error")
        if "success" in status:
            return ("SUCCESS", "user")
        return ("READY", "status")

    def _card_title(self, title: str, width: int) -> str:
        width = self._panel_width(width)
        label = f"-- {self._clip(title, max(1, width - 7))} "
        return "+" + _pad_display(label, width - 2, fill="-") + "+"

    def _card_edge(self, width: int) -> str:
        width = self._panel_width(width)
        return "+" + ("-" * (width - 2)) + "+"

    def _card_body(self, text: str, width: int) -> str:
        width = self._panel_width(width)
        inner_width = max(1, width - 4)
        return f"| {_pad_display(text, inner_width)} |"

    def _panel_width(self, width: int) -> int:
        return max(4, width)

    def _clip(self, text: str, width: int) -> str:
        return _clip_display(text, width)

    def _compact_path(self, path: Path, width: int) -> str:
        text = str(path)
        if _display_width(text) <= width:
            return text
        name = path.name or text
        parent = path.parent.name
        compact = f".../{parent}/{name}" if parent else f".../{name}"
        return self._clip(compact, width)

    def _key_value_line(self, pairs: list[tuple[str, str]], width: int) -> str:
        text = "  ".join(f"{key} [{value}]" for key, value in pairs)
        return self._clip(text, width)

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

    def _start_user_message(self, line: str) -> None:
        decision = self._control.start_run(active_run=self._active_run is not None)
        if not decision.allowed:
            self.status = decision.status
            self.messages.append(Message("error", decision.message))
            return

        self.messages.append(Message("user", line))
        config = self._snapshot_config()
        active = ActiveRun(
            prompt=line,
            config=config,
            started_at=time.monotonic(),
            known_traces=self._existing_trace_paths(config),
        )
        active.thread = threading.Thread(
            target=self._run_agent_background,
            args=(active,),
            name="harnesscoder-tui-run",
            daemon=True,
        )
        self._active_run = active
        self.status = "agent running..."
        active.thread.start()

    def _run_agent_background(self, active: ActiveRun) -> None:
        try:
            model = self._build_model(active.config)
            runner = AgentRunner(
                model=model,
                cwd=active.config.cwd,
                trace_root=active.config.trace_root,
                max_iterations=active.config.max_iterations,
                context_mode=active.config.context_mode,
                repo_map_mode=active.config.repo_map_mode,
            )
            store = self._session_store(active.config)
            session_context = store.build_context(active.config.session_id)
            result = runner.run(active.prompt, session_context=session_context)
            store.append_run(
                active.config.session_id,
                user_message=active.prompt,
                result=result,
            )
        except Exception as exc:
            with self._active_lock:
                active.error = f"{type(exc).__name__}: {exc}"
                active.done = True
            return

        with self._active_lock:
            active.result = result
            active.trace_path = result.trace_path
            active.done = True

    def _poll_active_run(self) -> None:
        active = self._active_run
        if active is None:
            return

        self._spinner_index = (self._spinner_index + 1) % 4
        if active.trace_path is None:
            active.trace_path = self._discover_active_trace(active)

        with self._active_lock:
            done = active.done
            error = active.error
            result = active.result

        if not done:
            self.status = self._active_run_line()
            return

        if error is not None:
            self.status = "agent failed"
            self.messages.append(Message("error", error))
            self._active_run = None
            return

        if result is None:
            self.status = "agent failed"
            self.messages.append(Message("error", "agent finished without a result"))
            self._active_run = None
            return

        self.status = f"run {result.run_id}: {result.status}"
        self.last_trace_path = result.trace_path
        reply = (
            f"{result.final_answer}\n\n"
            f"status: {result.status}\n"
            f"trace: {result.trace_path}"
        )
        self.messages.append(Message("assistant", reply))
        self._active_run = None

    def _snapshot_config(self) -> TuiConfig:
        return TuiConfig(
            cwd=self.config.cwd,
            trace_root=self.config.trace_root,
            provider=self.config.provider,
            openai_base_url=self.config.openai_base_url,
            openai_model=self.config.openai_model,
            openai_api_key_env=self.config.openai_api_key_env,
            reasoning_effort=self.config.reasoning_effort,
            max_iterations=self.config.max_iterations,
            context_mode=self.config.context_mode,
            repo_map_mode=self.config.repo_map_mode,
            session_id=self.config.session_id,
            session_root=self.config.session_root,
        )

    def _existing_trace_paths(self, config: TuiConfig) -> set[Path]:
        root = self._trace_root_path(config)
        return {path.resolve() for path in root.glob("*/trace.jsonl")}

    def _discover_active_trace(self, active: ActiveRun) -> Path | None:
        root = self._trace_root_path(active.config)
        traces = sorted(
            root.glob("*/trace.jsonl"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for path in traces:
            resolved = path.resolve()
            if resolved not in active.known_traces:
                return resolved
        return None

    def _active_run_line(self) -> str:
        active = self._active_run
        if active is None:
            return self.status
        spinner = "|/-\\"[self._spinner_index]
        elapsed = time.monotonic() - active.started_at
        event = self._latest_trace_event_label(active.trace_path)
        trace = active.trace_path.parent.name if active.trace_path else "starting trace"
        return f"{spinner} running {elapsed:0.1f}s | {trace} | {event}"

    def _footer_status(self) -> str:
        if self._active_run:
            return self._active_run_line()
        return self.status

    def _request_exit(self) -> bool:
        decision = self._control.request_exit(active_run=self._active_run is not None)
        if decision.allowed:
            return True
        self.status = decision.status
        if not self.messages or self.messages[-1].text != decision.message:
            self.messages.append(Message("error", decision.message))
        return False

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

        decision = self._control.slash_command(
            command=command,
            active_run=self._active_run is not None,
        )
        if not decision.allowed:
            self.messages.append(Message("error", decision.message))
            self.status = decision.status
            return

        handlers = {
            "help": self._cmd_help,
            "status": self._cmd_status,
            "clear": self._cmd_clear,
            "provider": self._cmd_provider,
            "model": self._cmd_model,
            "base-url": self._cmd_base_url,
            "reasoning": self._cmd_reasoning,
            "cwd": self._cmd_cwd,
            "max-iterations": self._cmd_max_iterations,
            "tools": self._cmd_tools,
            "read": self._cmd_read,
            "search": self._cmd_search,
            "edit": self._cmd_edit,
            "test": self._cmd_test,
            "run": self._cmd_run,
            "trace": self._cmd_trace,
            "repo-map": self._cmd_repo_map,
            "session": self._cmd_session,
            "reset-session": self._cmd_reset_session,
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
                        "/provider [scripted|hc-bench-oracle|openai-codex|openai-chat] - show or change provider",
                        "/model [name|scripted] - show or change model",
                        "/base-url [url] - show or change OpenAI-compatible base URL",
                        "/reasoning [none|minimal|low|medium|high|xhigh|reset] - show or change Codex reasoning effort",
                        "/cwd [path] - show or change repository cwd",
                        "/max-iterations [n] - show or change loop limit",
                        "/session [id] - show or switch durable session",
                        "/reset-session [id] - clear a durable session",
                        "/tools - list direct slash tools",
                        "/repo-map [query] - call repo_map",
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
                        f"reasoning_effort: {self.config.reasoning_effort or '-'}",
                        f"max_iterations: {self.config.max_iterations}",
                        f"context_mode: {self.config.context_mode}",
                        f"repo_map_mode: {self.config.repo_map_mode}",
                        f"session_id: {self.config.session_id}",
                        f"session_root: {self._session_root_path()}",
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
        if provider not in {"scripted", "hc-bench-oracle", "openai-codex", "openai-chat"}:
            self.messages.append(
                Message(
                    "error",
                    "Provider must be scripted, hc-bench-oracle, openai-codex, or openai-chat.",
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

    def _cmd_reasoning(self, args: list[str], _line: str) -> None:
        if not args:
            self.messages.append(
                Message("system", f"reasoning_effort: {self.config.reasoning_effort or '-'}")
            )
            return
        effort = args[0].strip().lower()
        if effort == "reset":
            self.config.reasoning_effort = None
            self.messages.append(Message("system", "reasoning_effort reset"))
            return
        if effort not in REASONING_EFFORT_CHOICES:
            self.messages.append(
                Message(
                    "error",
                    "Reasoning effort must be none, minimal, low, medium, high, xhigh, or reset.",
                )
            )
            return
        self.config.reasoning_effort = effort
        self.messages.append(Message("system", f"reasoning_effort set to {effort}"))

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
                "/repo-map -> repo_map, /edit -> edit_file, /test -> run_tests, "
                "/run -> run_command with policy gate.",
            )
        )

    def _cmd_session(self, args: list[str], _line: str) -> None:
        try:
            if args:
                self.config.session_id = normalize_session_id(args[0])
            store = self._session_store()
            record = store.load(self.config.session_id)
        except Exception as exc:
            self.messages.append(Message("error", f"session error: {exc}"))
            return

        context = store.build_context(self.config.session_id)
        lines = [
            f"session_id: {self.config.session_id}",
            f"path: {store.path_for(self.config.session_id)}",
            f"turns: {context['turn_count']}",
        ]
        if record.summary:
            lines.append("summary:")
            lines.append(record.summary)
        else:
            lines.append("summary: <empty>")
        self.messages.append(Message("system", "\n".join(lines)))

    def _cmd_reset_session(self, args: list[str], _line: str) -> None:
        target = args[0] if args else self.config.session_id
        try:
            target = normalize_session_id(target)
            store = self._session_store()
            path = store.reset(target)
        except Exception as exc:
            self.messages.append(Message("error", f"session reset error: {exc}"))
            return
        if target == self.config.session_id:
            self.messages = [
                message for message in self.messages if message.role != "user"
            ]
            self.messages.append(Message("system", f"session reset: {target}\npath: {path}"))
        else:
            self.messages.append(Message("system", f"session reset: {target}\npath: {path}"))

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

    def _cmd_repo_map(self, args: list[str], _line: str) -> None:
        query = " ".join(args).strip() or None
        self._direct_tool(
            "repo_map",
            {"query": query, "max_tokens": 1200, "refresh": False},
        )

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
        result = store_large_observation(
            result,
            run_path=self._trace_root_path() / "slash-artifacts",
        ).result
        output = result.output or result.error or ""
        if len(output) > 4000:
            output = output[:4000] + f"... [truncated {len(output) - 4000} chars]"
        artifact_note = ""
        if result.metadata.get("artifact_stored") is True:
            artifact_note = (
                "\nartifact: "
                f"{self._trace_root_path() / 'slash-artifacts' / result.metadata['artifact_path']}"
            )
        role: Role = "tool" if result.ok else "error"
        self.messages.append(
            Message(
                role,
                f"{tool_name} ok={result.ok}\npolicy: {decision.reason}"
                f"{artifact_note}\n{output}",
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

    def _trace_root_path(self, config: TuiConfig | None = None) -> Path:
        config = config or self.config
        if config.trace_root.is_absolute():
            return config.trace_root
        return (config.cwd / config.trace_root).resolve()

    def _session_root_path(self, config: TuiConfig | None = None) -> Path:
        config = config or self.config
        if config.session_root.is_absolute():
            return config.session_root
        return (config.cwd / config.session_root).resolve()

    def _session_store(self, config: TuiConfig | None = None) -> SessionStore:
        config = config or self.config
        return SessionStore(config.session_root, config.cwd)

    def _latest_trace_event_label(self, trace_path: Path | None) -> str:
        if trace_path is None or not trace_path.is_file():
            return "waiting for run_started"
        try:
            last = self._read_last_trace_event(trace_path)
        except Exception:
            return "reading trace"
        if last is None:
            return "trace opened"

        event_type = str(last.get("type", "<missing>"))
        if event_type == "model_action":
            action = last.get("action")
            if isinstance(action, dict):
                kind = action.get("kind", "-")
                tool_name = action.get("tool_name") or ""
                return f"model_action {kind} {tool_name}".strip()
        if event_type in {"policy_decision", "test_result"}:
            tool_name = last.get("tool_name") or last.get("command") or ""
            return f"{event_type} {tool_name}".strip()
        if event_type == "tool_result":
            result = last.get("result")
            if isinstance(result, dict):
                tool_name = result.get("tool_name", "-")
                ok = result.get("ok", "-")
                return f"tool_result {tool_name} ok={ok}"
        if event_type == "state_updated":
            state = last.get("state")
            if isinstance(state, dict):
                phase = state.get("phase", "-")
                iterations = state.get("iterations", "-")
                return f"state_updated phase={phase} iter={iterations}"
        if event_type == "run_finished":
            return f"run_finished status={last.get('status', '-')}"
        return event_type

    def _read_last_trace_event(self, trace_path: Path) -> dict[str, object] | None:
        last_line = ""
        for line in trace_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.strip():
                last_line = line
        if not last_line:
            return None
        event = json.loads(last_line)
        if not isinstance(event, dict):
            return None
        return event

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

    def _build_model(
        self,
        config: TuiConfig | None = None,
    ) -> ScriptedModel | HCBenchOracleModel | OpenAICodexModel | OpenAIChatModel:
        config = config or self.config
        if config.provider == "scripted":
            return ScriptedModel()
        if config.provider == "hc-bench-oracle":
            return HCBenchOracleModel()

        api_key = os.environ.get(config.openai_api_key_env)
        if not api_key:
            raise ValueError(
                f"{config.openai_api_key_env} is required for {config.provider}"
            )
        if not config.openai_model:
            raise ValueError("A model name is required. Use /model <name>.")
        model_cls = (
            OpenAICodexModel
            if config.provider == "openai-codex"
            else OpenAIChatModel
        )
        if config.provider == "openai-chat":
            return model_cls(
                api_key=api_key,
                base_url=config.openai_base_url,
                model=config.openai_model,
            )
        return model_cls(
            api_key=api_key,
            base_url=config.openai_base_url,
            model=config.openai_model,
            reasoning_effort=config.reasoning_effort,
        )


def run_tui(config: TuiConfig, initial_message: str | None = None) -> int:
    return HarnessCoderTui(config, initial_message).run()


def _wrap_display_lines(text: str, width: int) -> list[str]:
    if width <= 0:
        return [""]
    lines: list[str] = []
    current = ""
    current_width = 0
    for char in text:
        char_width = _char_display_width(char)
        if current and current_width + char_width > width:
            lines.append(current)
            current = ""
            current_width = 0
        if char_width > width:
            lines.append(_clip_display(char, width))
            continue
        current += char
        current_width += char_width
    lines.append(current)
    return lines or [""]


def _clip_display(text: str, width: int) -> str:
    if width <= 0:
        return ""
    if _display_width(text) <= width:
        return text
    if width <= 1:
        return _take_display(text, width)
    return _take_display(text, width - 1) + "."


def _pad_display(text: str, width: int, fill: str = " ") -> str:
    clipped = _clip_display(text, width)
    padding = max(0, width - _display_width(clipped))
    return clipped + (fill * padding)


def _take_display(text: str, width: int) -> str:
    if width <= 0:
        return ""
    result = ""
    used = 0
    for char in text:
        char_width = _char_display_width(char)
        if used + char_width > width:
            break
        result += char
        used += char_width
    return result


def _display_width(text: str) -> int:
    return sum(_char_display_width(char) for char in text)


def _char_display_width(char: str) -> int:
    if not char:
        return 0
    category = unicodedata.category(char)
    if category in {"Mn", "Me", "Cf"}:
        return 0
    if unicodedata.east_asian_width(char) in {"F", "W"}:
        return 2
    return 1
