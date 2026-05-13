from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from harnesscoder.core.repo_map import RepoMapCache


MAX_TOOL_OUTPUT = 16_000
DEFAULT_TEST_COMMAND = "python -m unittest discover"
MAX_COMMAND_TIMEOUT = 120
SENSITIVE_FILE_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    ".envrc",
    "models.toml",
}
SENSITIVE_FILE_SUFFIXES = (".key", ".pem", ".p12", ".pfx", ".sqlite", ".db")
SENSITIVE_ENV_MARKERS = (
    "API_KEY",
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "PASSWD",
    "AUTHORIZATION",
    "CREDENTIAL",
    "PRIVATE_KEY",
)
IGNORED_SEARCH_DIRS = {
    ".git",
    ".harnesscoder",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "node_modules",
}


@dataclass(slots=True)
class ToolResult:
    call_id: str
    tool_name: str
    ok: bool
    output: str
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "tool_name": self.tool_name,
            "ok": self.ok,
            "output": self.output,
            "error": self.error,
            "metadata": self.metadata,
        }


ToolFn = Callable[..., ToolResult]


class ToolRegistry:
    def __init__(self, cwd: Path) -> None:
        self.cwd = cwd.resolve()
        self._repo_map = RepoMapCache(self.cwd)
        self._tools: dict[str, ToolFn] = {
            "read_file": self.read_file,
            "search_code": self.search_code,
            "repo_map": self.repo_map,
            "write_file": self.write_file,
            "edit_file": self.edit_file,
            "run_tests": self.run_tests,
            "run_command": self.run_command,
        }

    def execute(self, call_id: str, tool_name: str, tool_args: dict[str, Any]) -> ToolResult:
        tool = self._tools.get(tool_name)
        if not tool:
            return ToolResult(
                call_id=call_id,
                tool_name=tool_name,
                ok=False,
                output="",
                error=f"unknown tool: {tool_name}",
            )
        try:
            return tool(call_id=call_id, **tool_args)
        except TypeError as exc:
            return ToolResult(
                call_id=call_id,
                tool_name=tool_name,
                ok=False,
                output="",
                error=f"bad tool arguments: {exc}",
            )
        except Exception as exc:  # pragma: no cover - safety net for trace completeness.
            return ToolResult(
                call_id=call_id,
                tool_name=tool_name,
                ok=False,
                output="",
                error=f"tool crashed: {type(exc).__name__}: {exc}",
            )

    def read_file(
        self,
        call_id: str,
        path: str,
        offset: int = 0,
        limit: int = 200,
    ) -> ToolResult:
        tool_name = "read_file"
        target = self._resolve_workspace_path(path)
        if _is_sensitive_workspace_path(target, self.cwd):
            return ToolResult(
                call_id,
                tool_name,
                False,
                "",
                f"refusing to read sensitive local file: {path}",
            )
        if not target.exists():
            return ToolResult(call_id, tool_name, False, "", f"file not found: {path}")
        if not target.is_file():
            return ToolResult(call_id, tool_name, False, "", f"not a file: {path}")

        offset = max(0, int(offset))
        limit = max(1, min(int(limit), 1_000))
        text = target.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        selected = lines[offset : offset + limit]
        numbered = "\n".join(
            f"{line_number:>5} | {line}"
            for line_number, line in enumerate(selected, start=offset + 1)
        )
        return ToolResult(
            call_id=call_id,
            tool_name=tool_name,
            ok=True,
            output=_truncate(numbered),
            metadata={
                "path": str(target.relative_to(self.cwd)),
                "offset": offset,
                "limit": limit,
                "total_lines": len(lines),
            },
        )

    def search_code(
        self,
        call_id: str,
        query: str,
        path: str = ".",
    ) -> ToolResult:
        tool_name = "search_code"
        target = self._resolve_workspace_path(path)
        if not target.exists():
            return ToolResult(call_id, tool_name, False, "", f"path not found: {path}")

        if shutil.which("rg"):
            cmd = [
                "rg",
                "-n",
                "--fixed-strings",
                "--hidden",
                "--glob",
                "!.git/**",
                "--glob",
                "!.harnesscoder/**",
                "--glob",
                "!**/.env",
                "--glob",
                "!**/.env.*",
                "--glob",
                "!**/.envrc",
                "--glob",
                "!**/models.toml",
                "--glob",
                "!**/*.key",
                "--glob",
                "!**/*.pem",
                "--glob",
                "!**/*.p12",
                "--glob",
                "!**/*.pfx",
                "--glob",
                "!**/*.sqlite",
                "--glob",
                "!**/*.db",
                query,
                str(target.relative_to(self.cwd)),
            ]
            completed = subprocess.run(
                cmd,
                cwd=self.cwd,
                text=True,
                capture_output=True,
                timeout=20,
                check=False,
            )
            ok = completed.returncode in {0, 1}
            output = completed.stdout if completed.stdout else completed.stderr
            return ToolResult(
                call_id=call_id,
                tool_name=tool_name,
                ok=ok,
                output=_truncate(output.strip()),
                error=None if ok else output.strip(),
                metadata={
                    "query": query,
                    "path": str(target.relative_to(self.cwd)),
                    "backend": "rg",
                    "returncode": completed.returncode,
                },
            )

        return self._search_code_python(call_id=call_id, query=query, target=target)

    def repo_map(
        self,
        call_id: str,
        query: str | None = None,
        max_tokens: int = 1200,
        refresh: bool = False,
    ) -> ToolResult:
        tool_name = "repo_map"
        if query is not None and not isinstance(query, str):
            return ToolResult(call_id, tool_name, False, "", "query must be a string or null")
        if not isinstance(refresh, bool):
            return ToolResult(call_id, tool_name, False, "", "refresh must be a boolean")

        try:
            result = self._repo_map.render(
                query=query,
                max_tokens=max_tokens,
                refresh=refresh,
            )
        except (TypeError, ValueError) as exc:
            return ToolResult(call_id, tool_name, False, "", f"bad repo_map arguments: {exc}")

        return ToolResult(
            call_id=call_id,
            tool_name=tool_name,
            ok=True,
            output=_truncate(result.text),
            metadata=result.metadata,
        )

    def run_command(
        self,
        call_id: str,
        cmd: str,
        timeout: int = 30,
    ) -> ToolResult:
        tool_name = "run_command"
        timeout = max(1, min(int(timeout), MAX_COMMAND_TIMEOUT))
        try:
            parts = shlex.split(cmd)
        except ValueError as exc:
            return ToolResult(call_id, tool_name, False, "", f"could not parse cmd: {exc}")
        if not parts:
            return ToolResult(call_id, tool_name, False, "", "cmd parsed to no arguments")

        return self._run_subprocess(
            call_id=call_id,
            tool_name=tool_name,
            cmd=cmd,
            parts=parts,
            timeout=timeout,
        )

    def edit_file(
        self,
        call_id: str,
        path: str,
        old: str,
        new: str,
    ) -> ToolResult:
        tool_name = "edit_file"
        if not isinstance(path, str):
            return ToolResult(call_id, tool_name, False, "", "path must be a string")
        if not isinstance(old, str) or not old:
            return ToolResult(call_id, tool_name, False, "", "old must be a non-empty string")
        if not isinstance(new, str):
            return ToolResult(call_id, tool_name, False, "", "new must be a string")

        try:
            target = self._resolve_workspace_path(path)
        except ValueError as exc:
            return ToolResult(call_id, tool_name, False, "", str(exc))
        rel_path = str(target.relative_to(self.cwd))

        if not target.exists():
            return ToolResult(call_id, tool_name, False, "", f"file not found: {path}")
        if not target.is_file():
            return ToolResult(call_id, tool_name, False, "", f"not a file: {path}")

        try:
            text = target.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            return ToolResult(
                call_id,
                tool_name,
                False,
                "",
                f"file is not valid UTF-8: {exc}",
                metadata={"path": rel_path, "changed": False, "replacement_count": 0},
            )
        except OSError as exc:
            return ToolResult(
                call_id,
                tool_name,
                False,
                "",
                f"could not read file: {exc}",
                metadata={"path": rel_path, "changed": False, "replacement_count": 0},
            )

        match_count = text.count(old)
        base_metadata = {
            "path": rel_path,
            "changed": False,
            "replacement_count": 0,
            "match_count": match_count,
            "old_length": len(old),
            "new_length": len(new),
        }
        if match_count == 0:
            return ToolResult(
                call_id,
                tool_name,
                False,
                "",
                "old text was not found",
                metadata=base_metadata,
            )
        if match_count > 1:
            return ToolResult(
                call_id,
                tool_name,
                False,
                "",
                f"old text is not unique: found {match_count} matches",
                metadata=base_metadata,
            )
        if old == new:
            return ToolResult(
                call_id=call_id,
                tool_name=tool_name,
                ok=True,
                output=f"No changes made to {rel_path}: old and new text are identical.",
                metadata=base_metadata,
            )

        updated = text.replace(old, new, 1)
        try:
            target.write_text(updated, encoding="utf-8")
        except OSError as exc:
            return ToolResult(
                call_id,
                tool_name,
                False,
                "",
                f"could not write file: {exc}",
                metadata=base_metadata,
            )

        metadata = dict(base_metadata)
        metadata["changed"] = True
        metadata["replacement_count"] = 1
        return ToolResult(
            call_id=call_id,
            tool_name=tool_name,
            ok=True,
            output=f"Replaced 1 occurrence in {rel_path}.",
            metadata=metadata,
        )

    def write_file(
        self,
        call_id: str,
        path: str,
        content: str,
        overwrite: bool = False,
    ) -> ToolResult:
        tool_name = "write_file"
        if not isinstance(path, str) or not path.strip():
            return ToolResult(call_id, tool_name, False, "", "path must be a non-empty string")
        if not isinstance(content, str):
            return ToolResult(call_id, tool_name, False, "", "content must be a string")
        if not isinstance(overwrite, bool):
            return ToolResult(call_id, tool_name, False, "", "overwrite must be a boolean")

        try:
            target = self._resolve_workspace_path(path)
        except ValueError as exc:
            return ToolResult(call_id, tool_name, False, "", str(exc))

        rel_path = str(target.relative_to(self.cwd))
        if target.exists() and target.is_dir():
            return ToolResult(
                call_id,
                tool_name,
                False,
                "",
                f"path is a directory: {path}",
                metadata={"path": rel_path, "changed": False, "created": False},
            )
        if target.exists() and not overwrite:
            return ToolResult(
                call_id,
                tool_name,
                False,
                "",
                f"file already exists: {path}",
                metadata={"path": rel_path, "changed": False, "created": False},
            )

        previous_text: str | None = None
        if target.exists():
            try:
                previous_text = target.read_text(encoding="utf-8")
            except UnicodeDecodeError as exc:
                return ToolResult(
                    call_id,
                    tool_name,
                    False,
                    "",
                    f"existing file is not valid UTF-8: {exc}",
                    metadata={"path": rel_path, "changed": False, "created": False},
                )
            except OSError as exc:
                return ToolResult(
                    call_id,
                    tool_name,
                    False,
                    "",
                    f"could not read existing file: {exc}",
                    metadata={"path": rel_path, "changed": False, "created": False},
                )

        created = previous_text is None
        changed = previous_text != content
        if not changed:
            return ToolResult(
                call_id=call_id,
                tool_name=tool_name,
                ok=True,
                output=f"No changes made to {rel_path}: content is identical.",
                metadata={
                    "path": rel_path,
                    "changed": False,
                    "created": False,
                    "overwrite": overwrite,
                    "content_length": len(content),
                },
            )

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        except OSError as exc:
            return ToolResult(
                call_id,
                tool_name,
                False,
                "",
                f"could not write file: {exc}",
                metadata={
                    "path": rel_path,
                    "changed": False,
                    "created": False,
                    "overwrite": overwrite,
                    "content_length": len(content),
                },
            )

        action = "Created" if created else "Overwrote"
        return ToolResult(
            call_id=call_id,
            tool_name=tool_name,
            ok=True,
            output=f"{action} {rel_path} ({len(content)} chars).",
            metadata={
                "path": rel_path,
                "changed": True,
                "created": created,
                "overwrite": overwrite,
                "content_length": len(content),
            },
        )

    def run_tests(
        self,
        call_id: str,
        cmd: str | None = None,
        timeout: int = 60,
    ) -> ToolResult:
        tool_name = "run_tests"
        timeout = max(1, min(int(timeout), MAX_COMMAND_TIMEOUT))
        defaulted = cmd is None or (isinstance(cmd, str) and not cmd.strip())
        if defaulted:
            command = DEFAULT_TEST_COMMAND
            parts = [sys.executable, "-m", "unittest", "discover"]
        elif isinstance(cmd, str):
            command = cmd
            try:
                parts = shlex.split(cmd)
            except ValueError as exc:
                return ToolResult(
                    call_id,
                    tool_name,
                    False,
                    "",
                    f"could not parse cmd: {exc}",
                )
            if not parts:
                return ToolResult(call_id, tool_name, False, "", "cmd parsed to no arguments")
        else:
            return ToolResult(
                call_id,
                tool_name,
                False,
                "",
                "cmd must be a string when provided",
            )

        result = self._run_subprocess(
            call_id=call_id,
            tool_name=tool_name,
            cmd=command,
            parts=parts,
            timeout=timeout,
        )
        result.metadata["defaulted"] = defaulted
        return result

    def _run_subprocess(
        self,
        call_id: str,
        tool_name: str,
        cmd: str,
        parts: list[str],
        timeout: int,
    ) -> ToolResult:
        timeout = max(1, min(int(timeout), MAX_COMMAND_TIMEOUT))

        env = safe_subprocess_env(
            {
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONUTF8": "1",
            }
        )
        started = time.monotonic()
        try:
            completed = subprocess.run(
                parts,
                cwd=self.cwd,
                text=True,
                capture_output=True,
                timeout=timeout,
                check=False,
                env=env,
            )
        except FileNotFoundError:
            return ToolResult(call_id, tool_name, False, "", f"command not found: {parts[0]}")
        except subprocess.TimeoutExpired as exc:
            duration_seconds = time.monotonic() - started
            output = redact_sensitive_text((exc.stdout or "") + (exc.stderr or ""))
            return ToolResult(
                call_id,
                tool_name,
                False,
                _truncate(output),
                f"command timed out after {timeout}s",
                metadata={
                    "cmd": cmd,
                    "timeout": timeout,
                    "duration_seconds": duration_seconds,
                    "timed_out": True,
                },
            )

        duration_seconds = time.monotonic() - started
        combined = "\n".join(part for part in [completed.stdout, completed.stderr] if part)
        combined = redact_sensitive_text(combined)
        return ToolResult(
            call_id=call_id,
            tool_name=tool_name,
            ok=completed.returncode == 0,
            output=_truncate(combined.strip()),
            error=None if completed.returncode == 0 else f"exit code {completed.returncode}",
            metadata={
                "cmd": cmd,
                "timeout": timeout,
                "returncode": completed.returncode,
                "duration_seconds": duration_seconds,
                "timed_out": False,
            },
        )

    def _search_code_python(
        self,
        call_id: str,
        query: str,
        target: Path,
    ) -> ToolResult:
        matches: list[str] = []
        roots = [target] if target.is_file() else target.rglob("*")
        for candidate in roots:
            if candidate.is_dir():
                continue
            if _is_ignored_search_path(candidate, self.cwd):
                continue
            try:
                text = candidate.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for line_number, line in enumerate(text.splitlines(), start=1):
                if query in line:
                    rel = candidate.relative_to(self.cwd)
                    matches.append(f"{rel}:{line_number}:{line}")
                    if len(matches) >= 200:
                        break
            if len(matches) >= 200:
                break

        return ToolResult(
            call_id=call_id,
            tool_name="search_code",
            ok=True,
            output=_truncate("\n".join(matches)),
            metadata={
                "query": query,
                "path": str(target.relative_to(self.cwd)),
                "backend": "python",
            },
        )

    def _resolve_workspace_path(self, path: str) -> Path:
        target = (self.cwd / path).resolve()
        try:
            target.relative_to(self.cwd)
        except ValueError as exc:
            raise ValueError(f"path escapes workspace: {path}") from exc
        return target


def _truncate(text: str, limit: int = MAX_TOOL_OUTPUT) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}... [truncated {len(text) - limit} chars]"


def safe_subprocess_env(extra_env: dict[str, str] | None = None) -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not is_sensitive_env_name(key)
    }
    if extra_env:
        for key, value in extra_env.items():
            if not is_sensitive_env_name(key):
                env[key] = value
    return env


def redact_sensitive_text(text: str) -> str:
    redacted = text
    for key, value in os.environ.items():
        if not is_sensitive_env_name(key) or len(value) < 4:
            continue
        redacted = redacted.replace(value, "[REDACTED]")
    redacted = re.sub(
        r"(?i)\b([A-Z0-9_]*(?:API[_-]?KEY|TOKEN|SECRET|PASSWORD|PASSWD|AUTHORIZATION|CREDENTIAL|PRIVATE[_-]?KEY)[A-Z0-9_]*)=([^\s]+)",
        r"\1=[REDACTED]",
        redacted,
    )
    redacted = re.sub(
        r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+",
        "Bearer [REDACTED]",
        redacted,
    )
    return redacted


def is_sensitive_env_name(name: str) -> bool:
    upper = name.upper().replace("-", "_")
    return any(marker in upper for marker in SENSITIVE_ENV_MARKERS)


def _is_sensitive_workspace_path(path: Path, cwd: Path) -> bool:
    try:
        rel = path.relative_to(cwd)
    except ValueError:
        return True
    for part in rel.parts:
        if part in SENSITIVE_FILE_NAMES or part.startswith(".env."):
            return True
    return path.name.endswith(SENSITIVE_FILE_SUFFIXES)


def _is_ignored_search_path(path: Path, cwd: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        rel = path.relative_to(cwd)
    except ValueError:
        return True
    try:
        path.resolve().relative_to(cwd.resolve())
    except (OSError, ValueError):
        return True
    if any(part in IGNORED_SEARCH_DIRS for part in rel.parts):
        return True
    return _is_sensitive_workspace_path(path, cwd)
