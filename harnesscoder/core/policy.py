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

    def check(
        self,
        tool_name: str | None,
        tool_args: dict[str, Any],
        cwd: Path,
    ) -> PolicyDecision:
        if not tool_name:
            return PolicyDecision(False, "missing tool name")

        if tool_name in {"read_file", "search_code"}:
            return self._check_path_tool(tool_name, tool_args, cwd)

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
        target = (cwd / raw_path).resolve()
        if not _is_relative_to(target, cwd):
            return PolicyDecision(False, f"{tool_name} path escapes workspace")
        return PolicyDecision(True, f"{tool_name} path is inside workspace")

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


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
    except ValueError:
        return False
    return True
