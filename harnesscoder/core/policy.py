from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from harnesscoder.core.notes import (
    MAX_NOTE_CONTENT_CHARS,
    MAX_NOTE_QUERY_CHARS,
    MAX_NOTE_SEARCH_LIMIT,
    MAX_NOTE_TAG_CHARS,
    MAX_NOTE_TAGS,
    MAX_NOTE_TITLE_CHARS,
    NOTE_TYPES,
)
from harnesscoder.core.safety_rules import (
    SENSITIVE_FILE_NAMES,
    SENSITIVE_FILE_SUFFIXES,
    is_python_executable,
    is_sensitive_workspace_path,
    parse_command,
)
from harnesscoder.core.tool_schema import ToolSchema

READONLY_DELEGATE_TOOLS = frozenset({"read_file", "search_code", "repo_map", "search_notes"})
DEFAULT_READONLY_DELEGATE_MAX_ITERATIONS = 3
MAX_READONLY_DELEGATE_ITERATIONS = 6


@dataclass(slots=True)
class PolicyDecision:
    allowed: bool
    reason: str

    def to_record(self) -> dict[str, Any]:
        return {"allowed": self.allowed, "reason": self.reason}


class ToolPolicy:
    """Small local policy gate for MVP tool execution."""

    def __init__(
        self,
        allowed_tools: set[str] | None = None,
        schemas: dict[str, ToolSchema] | None = None,
    ) -> None:
        self.allowed_tools = set(allowed_tools) if allowed_tools is not None else None
        self._schemas = schemas or {}

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
    _allowed_run_commands = {"find", "ls", "pwd", "wc"}
    _blocked_run_command_options = {"-exec", "-execdir", "-delete"}
    _blocked_env_commands = {"env", "printenv"}
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

        schema = self._schemas.get(tool_name)
        if schema is not None:
            error = schema.validate_args(tool_args)
            if error:
                return PolicyDecision(False, f"schema validation: {error}")

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
            return self._check_run_command(tool_args, cwd)

        if tool_name == "create_note":
            return self._check_create_note(tool_args)

        if tool_name == "search_notes":
            return self._check_search_notes(tool_args)

        if tool_name == "delegate_readonly":
            return self._check_delegate_readonly(tool_args)

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
        if tool_name == "read_file" and is_sensitive_workspace_path(target, base):
            return PolicyDecision(False, "read_file target is a sensitive local file")
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

    def _check_run_command(self, tool_args: dict[str, Any], cwd: Path) -> PolicyDecision:
        cmd = tool_args.get("cmd")
        if not isinstance(cmd, str) or not cmd.strip():
            return PolicyDecision(False, "cmd must be a non-empty string")

        for token in self._blocked_shell_tokens:
            if token in cmd:
                return PolicyDecision(False, f"shell control token blocked: {token}")

        parts, parse_error = parse_command(cmd)
        if parts is None:
            if parse_error == "cmd parsed to no arguments":
                return PolicyDecision(False, parse_error)
            return PolicyDecision(False, f"could not parse command: {parse_error}")

        head = Path(parts[0]).name

        if head in self._blocked_env_commands:
            return PolicyDecision(False, f"environment inspection is not allowed: {head}")

        if head == "git":
            if len(parts) < 2:
                return PolicyDecision(False, "git command must include a subcommand")
            if parts[1] not in self._allowed_git_subcommands:
                return PolicyDecision(False, f"git subcommand is not allowed: {parts[1]}")
            return PolicyDecision(True, "read-only git command allowed by MVP policy")

        if head in self._blocked_command_heads:
            return PolicyDecision(False, f"command is not allowed in MVP policy: {head}")

        if head not in self._allowed_run_commands:
            return PolicyDecision(False, f"command is not allowed in MVP policy: {head}")

        path_decision = self._check_run_command_path_args(parts, cwd)
        if not path_decision.allowed:
            return path_decision

        return PolicyDecision(True, "read-only repository inspection command allowed")

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

        parts, parse_error = parse_command(cmd)
        if parts is None:
            if parse_error == "cmd parsed to no arguments":
                return PolicyDecision(False, parse_error)
            return PolicyDecision(False, f"could not parse command: {parse_error}")

        command_decision = self._check_test_command_shape(parts)
        if not command_decision.allowed:
            return command_decision

        path_decision = self._check_test_path_args(parts, cwd)
        if not path_decision.allowed:
            return path_decision

        return PolicyDecision(True, "local test command allowed")

    def _check_create_note(self, tool_args: dict[str, Any]) -> PolicyDecision:
        note_type = tool_args.get("note_type", "general")
        if not isinstance(note_type, str) or note_type not in NOTE_TYPES:
            return PolicyDecision(False, "note_type is not supported")

        title = tool_args.get("title")
        if not isinstance(title, str) or not title.strip():
            return PolicyDecision(False, "title must be a non-empty string")
        if len(" ".join(title.split())) > MAX_NOTE_TITLE_CHARS:
            return PolicyDecision(False, "title is too long")

        content = tool_args.get("content")
        if not isinstance(content, str) or not content.strip():
            return PolicyDecision(False, "content must be a non-empty string")
        if len(content.strip()) > MAX_NOTE_CONTENT_CHARS:
            return PolicyDecision(False, "content is too long")

        tags = tool_args.get("tags", [])
        if tags is None:
            tags = []
        if not isinstance(tags, list):
            return PolicyDecision(False, "tags must be a list of strings")
        if len(tags) > MAX_NOTE_TAGS:
            return PolicyDecision(False, "too many tags")
        for tag in tags:
            if not isinstance(tag, str):
                return PolicyDecision(False, "tags must be a list of strings")
            if len(tag.strip()) > MAX_NOTE_TAG_CHARS:
                return PolicyDecision(False, "tag is too long")

        return PolicyDecision(True, "note creation is allowed")

    def _check_search_notes(self, tool_args: dict[str, Any]) -> PolicyDecision:
        query = tool_args.get("query")
        if not isinstance(query, str) or not query.strip():
            return PolicyDecision(False, "query must be a non-empty string")
        if len(" ".join(query.split())) > MAX_NOTE_QUERY_CHARS:
            return PolicyDecision(False, "query is too long")

        limit = tool_args.get("limit", 5)
        if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
            return PolicyDecision(False, "limit must be a positive integer")
        if limit > MAX_NOTE_SEARCH_LIMIT:
            return PolicyDecision(False, "limit is too high")

        note_type = tool_args.get("note_type")
        if note_type is not None and (
            not isinstance(note_type, str) or note_type not in NOTE_TYPES
        ):
            return PolicyDecision(False, "note_type is not supported")

        return PolicyDecision(True, "note search is read-only and allowed")

    def _check_delegate_readonly(self, tool_args: dict[str, Any]) -> PolicyDecision:
        task = tool_args.get("task")
        if not isinstance(task, str) or not task.strip():
            return PolicyDecision(False, "delegate task must be a non-empty string")
        if len(" ".join(task.split())) > 2000:
            return PolicyDecision(False, "delegate task is too long")

        scope = tool_args.get("scope")
        if scope is not None and not isinstance(scope, str):
            return PolicyDecision(False, "delegate scope must be a string or null")

        max_iterations = tool_args.get("max_iterations", DEFAULT_READONLY_DELEGATE_MAX_ITERATIONS)
        if (
            not isinstance(max_iterations, int)
            or isinstance(max_iterations, bool)
            or max_iterations <= 0
        ):
            return PolicyDecision(False, "delegate max_iterations must be a positive integer")
        if max_iterations > MAX_READONLY_DELEGATE_ITERATIONS:
            return PolicyDecision(False, "delegate max_iterations exceeds policy limit")

        allowed_tools = tool_args.get("allowed_tools")
        if allowed_tools is None:
            return PolicyDecision(True, "read-only delegation allowed")
        if not isinstance(allowed_tools, list) or not all(
            isinstance(item, str) for item in allowed_tools
        ):
            return PolicyDecision(False, "delegate allowed_tools must be a list of strings")
        requested = set(allowed_tools)
        if not requested:
            return PolicyDecision(False, "delegate allowed_tools cannot be empty")
        unsafe = requested - READONLY_DELEGATE_TOOLS
        if unsafe:
            return PolicyDecision(
                False,
                "delegate allowed_tools must stay read-only: " + ", ".join(sorted(unsafe)),
            )
        return PolicyDecision(True, "read-only delegation allowed")

    def _check_test_command_shape(self, parts: list[str]) -> PolicyDecision:
        head = Path(parts[0]).name
        if head in self._allowed_test_commands:
            return PolicyDecision(True, "pytest/unittest command allowed")

        if not is_python_executable(head):
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

    def _check_run_command_path_args(self, parts: list[str], cwd: Path) -> PolicyDecision:
        base = cwd.resolve()
        for raw_part in parts[1:]:
            if raw_part in self._blocked_run_command_options:
                return PolicyDecision(False, f"command option is not allowed: {raw_part}")
            if _mentions_sensitive_path(raw_part):
                return PolicyDecision(False, f"command mentions a sensitive local path: {raw_part}")
            candidates = _path_candidates_from_arg(raw_part)
            for candidate in candidates:
                target = (base / candidate).resolve()
                if not _is_relative_to(target, base):
                    return PolicyDecision(False, f"command path escapes workspace: {candidate}")
                if is_sensitive_workspace_path(target, base):
                    return PolicyDecision(False, f"command path is sensitive: {candidate}")
        return PolicyDecision(True, "command path arguments stay inside workspace")

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


def _mentions_sensitive_path(value: str) -> bool:
    cleaned = value.strip("'\"")
    path = Path(cleaned)
    parts = path.parts or (cleaned,)
    for part in parts:
        stripped = part.strip("*?[]{}")
        if stripped in SENSITIVE_FILE_NAMES or stripped.startswith(".env."):
            return True
        if stripped.endswith(SENSITIVE_FILE_SUFFIXES):
            return True
    return False


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
