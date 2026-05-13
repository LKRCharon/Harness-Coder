from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class PolicyDecision:
    allowed: bool
    reason: str

    def to_record(self) -> dict[str, Any]:
        return {"allowed": self.allowed, "reason": self.reason}


class ToolPolicy:
    """Small local policy gate for MVP tool execution."""

    def __init__(self, allowed_tools: set[str] | None = None) -> None:
        self.allowed_tools = set(allowed_tools) if allowed_tools is not None else None

    _blocked_command_heads = {
        "rm",
        "rmdir",
        "mv",
        "cp",
        "chmod",
        "chown",
        "sudo",
        "ssh",
        "scp",
        "curl",
        "wget",
        "pip",
        "npm",
        "pnpm",
        "yarn",
    }
    _blocked_shell_tokens = {";", "&&", "||", "|", ">", ">>", "<", "`", "$("}
    _allowed_git_subcommands = {
        "branch",
        "diff",
        "grep",
        "log",
        "ls-files",
        "rev-parse",
        "show",
        "status",
    }
    _allowed_test_modules = {"pytest", "unittest"}
    _allowed_test_commands = {"py.test", "pytest", "unittest"}
    _allowed_python_test_flags = {"-B", "-E", "-I", "-s", "-S"}

    def check(
        self,
        tool_name: str | None,
        tool_args: dict[str, Any],
        cwd: Path,
    ) -> PolicyDecision:
        if not tool_name:
            return PolicyDecision(False, "missing tool name")
        if self.allowed_tools is not None and tool_name not in self.allowed_tools:
            return PolicyDecision(False, f"tool is not allowed for this run: {tool_name}")

        if tool_name in {"read_file", "search_code"}:
            return self._check_path_tool(tool_name, tool_args, cwd)

        if tool_name == "repo_map":
            return self._check_repo_map(tool_args)

        if tool_name == "write_file":
            return self._check_write_file(tool_args, cwd)

        if tool_name == "edit_file":
            return self._check_edit_file(tool_args, cwd)

        if tool_name == "run_tests":
            return self._check_run_tests(tool_args, cwd)

        if tool_name == "run_command":
            return self._check_run_command(tool_args)

        return PolicyDecision(False, f"unknown tool: {tool_name}")

    def _check_path_tool(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        cwd: Path,
    ) -> PolicyDecision:
        raw_path = tool_args.get("path", ".")
        if not isinstance(raw_path, str):
            return PolicyDecision(False, "path must be a string")
        base = cwd.resolve()
        target = (base / raw_path).resolve()
        if not _is_relative_to(target, base):
            return PolicyDecision(False, f"{tool_name} path escapes workspace")
        return PolicyDecision(True, f"{tool_name} path is inside workspace")

    def _check_repo_map(self, tool_args: dict[str, Any]) -> PolicyDecision:
        query = tool_args.get("query")
        if query is not None and not isinstance(query, str):
            return PolicyDecision(False, "query must be a string or null")
        max_tokens = tool_args.get("max_tokens", 1200)
        if (
            not isinstance(max_tokens, int)
            or isinstance(max_tokens, bool)
            or max_tokens <= 0
        ):
            return PolicyDecision(False, "max_tokens must be a positive integer")
        if max_tokens > 8000:
            return PolicyDecision(False, "max_tokens exceeds repo_map policy limit")
        refresh = tool_args.get("refresh", False)
        if not isinstance(refresh, bool):
            return PolicyDecision(False, "refresh must be a boolean")
        return PolicyDecision(True, "repo_map query is read-only and allowed")

    def _check_edit_file(
        self,
        tool_args: dict[str, Any],
        cwd: Path,
    ) -> PolicyDecision:
        path_decision = self._check_path_tool("edit_file", tool_args, cwd)
        if not path_decision.allowed:
            return path_decision

        old = tool_args.get("old")
        new = tool_args.get("new")
        if not isinstance(old, str) or not old:
            return PolicyDecision(False, "old must be a non-empty string")
        if not isinstance(new, str):
            return PolicyDecision(False, "new must be a string")
        return PolicyDecision(True, "edit_file path and replacement are allowed")

    def _check_write_file(
        self,
        tool_args: dict[str, Any],
        cwd: Path,
    ) -> PolicyDecision:
        path_decision = self._check_path_tool("write_file", tool_args, cwd)
        if not path_decision.allowed:
            return path_decision

        content = tool_args.get("content")
        if not isinstance(content, str):
            return PolicyDecision(False, "content must be a string")
        overwrite = tool_args.get("overwrite", False)
        if not isinstance(overwrite, bool):
            return PolicyDecision(False, "overwrite must be a boolean")
        return PolicyDecision(True, "write_file path and content are allowed")

    def _check_run_command(self, tool_args: dict[str, Any]) -> PolicyDecision:
        cmd = tool_args.get("cmd")
        if not isinstance(cmd, str) or not cmd.strip():
            return PolicyDecision(False, "cmd must be a non-empty string")

        for token in self._blocked_shell_tokens:
            if token in cmd:
                return PolicyDecision(False, f"shell control token blocked: {token}")

        try:
            parts = shlex.split(cmd)
        except ValueError as exc:
            return PolicyDecision(False, f"could not parse command: {exc}")

        if not parts:
            return PolicyDecision(False, "cmd parsed to no arguments")

        if parts[0] == "git":
            if len(parts) < 2:
                return PolicyDecision(False, "git command must include a subcommand")
            if parts[1] not in self._allowed_git_subcommands:
                return PolicyDecision(False, f"git subcommand is not allowed: {parts[1]}")
            return PolicyDecision(True, "read-only git command allowed by MVP policy")

        if parts[0] in self._blocked_command_heads:
            return PolicyDecision(False, f"command is not allowed in MVP policy: {parts[0]}")

        return PolicyDecision(True, "command allowed by MVP read-oriented policy")

    def _check_run_tests(
        self,
        tool_args: dict[str, Any],
        cwd: Path,
    ) -> PolicyDecision:
        cmd = tool_args.get("cmd")
        if cmd is None or (isinstance(cmd, str) and not cmd.strip()):
            return PolicyDecision(True, "default unittest command allowed")
        if not isinstance(cmd, str):
            return PolicyDecision(False, "cmd must be a string when provided")

        for token in self._blocked_shell_tokens:
            if token in cmd:
                return PolicyDecision(False, f"shell control token blocked: {token}")

        try:
            parts = shlex.split(cmd)
        except ValueError as exc:
            return PolicyDecision(False, f"could not parse command: {exc}")

        if not parts:
            return PolicyDecision(False, "cmd parsed to no arguments")

        command_decision = self._check_test_command_shape(parts)
        if not command_decision.allowed:
            return command_decision

        path_decision = self._check_test_path_args(parts, cwd)
        if not path_decision.allowed:
            return path_decision

        return PolicyDecision(True, "local test command allowed")

    def _check_test_command_shape(self, parts: list[str]) -> PolicyDecision:
        head = Path(parts[0]).name
        if head in self._allowed_test_commands:
            return PolicyDecision(True, "pytest/unittest command allowed")

        if not _is_python_head(head):
            return PolicyDecision(False, f"test command is not allowed: {parts[0]}")

        index = 1
        while index < len(parts) and parts[index] in self._allowed_python_test_flags:
            index += 1

        if index >= len(parts):
            return PolicyDecision(False, "python test command must include a test target")

        if parts[index] == "-m":
            if index + 1 >= len(parts):
                return PolicyDecision(False, "python -m test command must include a module")
            module = parts[index + 1]
            if module not in self._allowed_test_modules:
                return PolicyDecision(False, f"python test module is not allowed: {module}")
            return PolicyDecision(True, f"python -m {module} command allowed")

        if self._looks_like_test_script(parts[index]):
            return PolicyDecision(True, "local python test script allowed")

        return PolicyDecision(
            False,
            "python test command must use -m unittest, -m pytest, or a local test script",
        )

    def _check_test_path_args(self, parts: list[str], cwd: Path) -> PolicyDecision:
        base = cwd.resolve()
        for raw_part in parts[1:]:
            candidates = _path_candidates_from_arg(raw_part)
            for candidate in candidates:
                target = (base / candidate).resolve()
                if not _is_relative_to(target, base):
                    return PolicyDecision(False, f"test path escapes workspace: {candidate}")
        return PolicyDecision(True, "test path arguments stay inside workspace")

    def _looks_like_test_script(self, value: str) -> bool:
        path = value.split("::", 1)[0]
        name = Path(path).name
        return path.endswith(".py") and (
            name.startswith("test_")
            or name.endswith("_test.py")
            or "tests/" in path
            or "tests\\" in path
        )


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
    except ValueError:
        return False
    return True


def _is_python_head(head: str) -> bool:
    if head in {"python", "python3"}:
        return True
    if not head.startswith("python3."):
        return False
    suffix = head[len("python3.") :]
    return suffix.isdigit()


def _path_candidates_from_arg(value: str) -> list[str]:
    candidates: list[str] = []
    parts = [value]
    if value.startswith("-") and "=" in value:
        parts = [value.split("=", 1)[1]]

    for part in parts:
        candidate = part.split("::", 1)[0]
        if not candidate or candidate.startswith("-"):
            continue
        if _looks_like_path(candidate):
            candidates.append(candidate)
    return candidates


def _looks_like_path(value: str) -> bool:
    if value in {".", ".."}:
        return True
    if value.startswith(("/", "./", "../", "~")):
        return True
    if "/" in value or "\\" in value:
        return True
    if "*" in value or "?" in value:
        return True
    return value.endswith((".py", ".toml", ".ini", ".cfg", ".json", ".txt"))
