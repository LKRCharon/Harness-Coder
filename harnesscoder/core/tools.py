from __future__ import annotations

import os
import re
import json
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

from harnesscoder.core.notes import NoteStore
from harnesscoder.core.repo_map import RepoMapCache
from harnesscoder.core.safety_rules import (
    SENSITIVE_FILE_NAMES,
    SENSITIVE_FILE_SUFFIXES,
    is_python_executable,
    is_sensitive_workspace_path,
    iter_sensitive_file_globs,
    parse_command,
)
from harnesscoder.core.tool_schema import ToolSchema, harness_tool


DEFAULT_TEST_COMMAND = "python -m unittest discover"
MAX_COMMAND_TIMEOUT = 120
MACOS_SANDBOX_EXECUTABLE = "/usr/bin/sandbox-exec"
MACOS_SANDBOX_PROTECTED_PATHS = (".git", ".codex", ".agents")
MACOS_SANDBOX_SENSITIVE_FILE_PATTERNS = (
    ".env",
    ".env.local",
    ".env.production",
    ".envrc",
    "models.toml",
    "*.key",
    "*.pem",
    "*.p12",
    "*.pfx",
    "*.sqlite",
    "*.db",
)
MACOS_SANDBOX_MACH_LOOKUPS = (
    "com.apple.system.opendirectoryd.libinfo",
    "com.apple.cfprefsd.agent",
    "com.apple.cfprefsd.daemon",
    "com.apple.PowerManagement.control",
    "com.apple.system.notification_center",
    "com.apple.trustd",
    "com.apple.trustd.agent",
    "com.apple.logd",
    "com.apple.logd.events",
)
MACOS_SANDBOX_HOME_PROTECTED_PATHS = (
    ".ssh",
    ".aws",
    ".gnupg",
    ".config/gcloud",
    ".npmrc",
    ".pypirc",
)
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


@dataclass(slots=True)
class CommandExecutionResult:
    returncode: int
    stdout: str
    stderr: str
    duration_seconds: float
    backend: str
    sandboxed: bool
    timed_out: bool = False


class CommandExecutor(Protocol):
    def run(
        self,
        *,
        parts: list[str],
        cwd: Path,
        env: dict[str, str],
        timeout: int,
    ) -> CommandExecutionResult: ...


class LocalCommandExecutor:
    backend = "local"
    sandboxed = False

    def run(
        self,
        *,
        parts: list[str],
        cwd: Path,
        env: dict[str, str],
        timeout: int,
    ) -> CommandExecutionResult:
        started = time.monotonic()
        completed = subprocess.run(
            parts,
            cwd=cwd,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
            env=env,
        )
        return CommandExecutionResult(
            returncode=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
            duration_seconds=time.monotonic() - started,
            backend=self.backend,
            sandboxed=self.sandboxed,
        )


class MacOSSeatbeltExecutor:
    backend = "macos-seatbelt"
    sandboxed = True

    def __init__(self, workspace_root: Path, sandbox_executable: str = MACOS_SANDBOX_EXECUTABLE) -> None:
        self.workspace_root = workspace_root.resolve()
        self.sandbox_executable = sandbox_executable

    def run(
        self,
        *,
        parts: list[str],
        cwd: Path,
        env: dict[str, str],
        timeout: int,
    ) -> CommandExecutionResult:
        profile = _build_macos_seatbelt_profile(self.workspace_root)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".sb",
            delete=False,
        ) as handle:
            handle.write(profile)
            profile_path = Path(handle.name)

        started = time.monotonic()
        try:
            completed = subprocess.run(
                [self.sandbox_executable, "-f", str(profile_path), *parts],
                cwd=cwd,
                text=True,
                capture_output=True,
                timeout=timeout,
                check=False,
                env=env,
            )
        finally:
            profile_path.unlink(missing_ok=True)

        return CommandExecutionResult(
            returncode=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
            duration_seconds=time.monotonic() - started,
            backend=self.backend,
            sandboxed=self.sandboxed,
        )


class ToolRegistry:
    def __init__(
        self,
        cwd: Path,
        command_executor: CommandExecutor | None = None,
    ) -> None:
        self.cwd = cwd.resolve()
        self._repo_map = RepoMapCache(self.cwd)
        self._notes = NoteStore.for_workspace(self.cwd)
        self._command_executor = command_executor or build_command_executor(self.cwd)
        self._tools: dict[str, ToolFn] = {
            "read_file": self.read_file,
            "search_code": self.search_code,
            "repo_map": self.repo_map,
            "write_file": self.write_file,
            "edit_file": self.edit_file,
            "run_tests": self.run_tests,
            "run_command": self.run_command,
            "create_note": self.create_note,
            "search_notes": self.search_notes,
        }
        self._schemas: dict[str, ToolSchema] = {}
        for name, fn in self._tools.items():
            schema = getattr(fn, "__tool_schema__", None)
            if schema is not None:
                self._schemas[name] = schema

    def get_schemas(self) -> dict[str, ToolSchema]:
        return dict(self._schemas)

    def get_prompt_text(self) -> str:
        return "\n".join(schema.to_prompt_text() for schema in self._schemas.values())

    @property
    def command_executor_backend(self) -> str:
        return getattr(self._command_executor, "backend", "local")

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

    @harness_tool(
        description="Read a file from the workspace with optional offset and limit.",
        path=("string", "Relative path to the file.", True),
        offset=("int", "Line number to start reading from.", False, 0),
        limit=("int", "Maximum number of lines to read.", False, 200),
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
        if is_sensitive_workspace_path(target, self.cwd):
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
            output=numbered,
            metadata={
                "path": str(target.relative_to(self.cwd)),
                "offset": offset,
                "limit": limit,
                "total_lines": len(lines),
            },
        )

    @harness_tool(
        description="Search the workspace for a literal string using ripgrep.",
        query=("string", "Literal text to search for.", True),
        path=("string", "Directory to search in, relative to workspace root.", False, "."),
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
            ]
            for pattern in iter_sensitive_file_globs():
                cmd.extend(["--glob", pattern])
            cmd.extend([query, str(target.relative_to(self.cwd))])
            env = safe_subprocess_env()
            try:
                execution = self._command_executor.run(
                    parts=cmd,
                    cwd=self.cwd,
                    env=env,
                    timeout=20,
                )
            except FileNotFoundError:
                return ToolResult(call_id, tool_name, False, "", "command not found: rg")
            except subprocess.TimeoutExpired:
                output = redact_sensitive_text("")
                sandboxed = getattr(self._command_executor, "sandboxed", False)
                return ToolResult(
                    call_id,
                    tool_name,
                    False,
                    output,
                    "search_code timed out after 20s",
                    metadata={
                        "query": query,
                        "path": str(target.relative_to(self.cwd)),
                        "backend": "rg",
                        "executor_backend": getattr(self._command_executor, "backend", "local"),
                        "sandboxed": sandboxed,
                        "timed_out": True,
                        "sandbox_error": _is_sandbox_error(
                            sandboxed,
                            output,
                            timed_out=True,
                        ),
                    },
                )
            ok = execution.returncode in {0, 1}
            output = execution.stdout if execution.stdout else execution.stderr
            output = redact_sensitive_text(output.strip())
            return ToolResult(
                call_id=call_id,
                tool_name=tool_name,
                ok=ok,
                output=output,
                error=None if ok else output,
                metadata={
                    "query": query,
                    "path": str(target.relative_to(self.cwd)),
                    "backend": "rg",
                    "returncode": execution.returncode,
                    "executor_backend": execution.backend,
                    "sandboxed": execution.sandboxed,
                    "sandbox_error": _is_sandbox_error(
                        execution.sandboxed,
                        output,
                        returncode=execution.returncode,
                    ),
                },
            )

        return self._search_code_python(call_id=call_id, query=query, target=target)

    @harness_tool(
        description="Get a symbol-level map of the repository.",
        query=("string | null", "Optional filter to narrow the map.", False, None),
        max_tokens=("int", "Maximum tokens for the map output.", False, 1200),
        refresh=("boolean", "Force refresh the cached map.", False, False),
    )
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
            output=result.text,
            metadata=result.metadata,
        )

    @harness_tool(
        description="Run a shell command in the workspace.",
        cmd=("string", "The command to execute.", True),
        timeout=("int", "Timeout in seconds.", False, 30),
    )
    def run_command(
        self,
        call_id: str,
        cmd: str,
        timeout: int = 30,
    ) -> ToolResult:
        tool_name = "run_command"
        timeout = max(1, min(int(timeout), MAX_COMMAND_TIMEOUT))
        parts, parse_error = parse_command(cmd)
        if parts is None:
            if parse_error == "cmd parsed to no arguments":
                return ToolResult(call_id, tool_name, False, "", parse_error)
            return ToolResult(call_id, tool_name, False, "", f"could not parse cmd: {parse_error}")

        return self._run_subprocess(
            call_id=call_id,
            tool_name=tool_name,
            cmd=cmd,
            parts=parts,
            timeout=timeout,
        )

    @harness_tool(
        description="Replace an exact string in a file with a new string.",
        path=("string", "Relative path to the file.", True),
        old=("string", "Exact string to find and replace (must match once).", True),
        new=("string", "Replacement string.", True),
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

    @harness_tool(
        description="Write content to a new file in the workspace.",
        path=("string", "Relative path to the file.", True),
        content=("string", "Content to write.", True),
        overwrite=("boolean", "Allow overwriting an existing file.", False, False),
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

    @harness_tool(
        description="Create a durable note for task-scoped facts.",
        title=("string", "Note title.", True),
        content=("string", "Note content.", True),
        note_type=("string", "Note category: general, blocker, decision, fact.", False, "general"),
        tags=("string[]", "Optional tags for filtering.", False, []),
    )
    def create_note(
        self,
        call_id: str,
        title: str,
        content: str,
        note_type: str = "general",
        tags: list[str] | None = None,
    ) -> ToolResult:
        tool_name = "create_note"
        try:
            note = self._notes.create(
                note_type=note_type,
                title=title,
                content=content,
                tags=tags or [],
                source_call_id=call_id,
            )
        except ValueError as exc:
            return ToolResult(call_id, tool_name, False, "", str(exc))

        return ToolResult(
            call_id=call_id,
            tool_name=tool_name,
            ok=True,
            output=f"Created {note.type} note {note.note_id}: {note.title}",
            metadata={
                "note_id": note.note_id,
                "note_type": note.type,
                "title": note.title,
                "tags": list(note.tags),
                "notes_path": str(self._notes.path.relative_to(self.cwd)),
            },
        )

    @harness_tool(
        description="Search durable notes by query text.",
        query=("string", "Search query.", True),
        limit=("int", "Maximum results to return.", False, 5),
        note_type=("string | null", "Filter by note type.", False, None),
    )
    def search_notes(
        self,
        call_id: str,
        query: str,
        limit: int = 5,
        note_type: str | None = None,
    ) -> ToolResult:
        tool_name = "search_notes"
        try:
            notes = self._notes.search(
                query=query,
                limit=limit,
                note_type=note_type,
            )
        except ValueError as exc:
            return ToolResult(call_id, tool_name, False, "", str(exc))

        records = [note.to_record() for note in notes]
        return ToolResult(
            call_id=call_id,
            tool_name=tool_name,
            ok=True,
            output=json.dumps(records, ensure_ascii=False, indent=2, sort_keys=True),
            metadata={
                "query": query,
                "limit": limit,
                "note_type": note_type,
                "note_count": len(records),
                "note_ids": [record["note_id"] for record in records],
            },
        )

    @harness_tool(
        description="Run tests using the specified or default test command.",
        cmd=("string | null", "Test command. Defaults to python -m unittest discover.", False, None),
        timeout=("int", "Timeout in seconds.", False, 60),
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
            parts, parse_error = parse_command(cmd)
            if parts is None:
                if parse_error == "cmd parsed to no arguments":
                    return ToolResult(call_id, tool_name, False, "", parse_error)
                return ToolResult(
                    call_id,
                    tool_name,
                    False,
                    "",
                    f"could not parse cmd: {parse_error}",
                )
            parts = normalize_python_command(parts)
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
        try:
            execution = self._command_executor.run(
                parts=parts,
                cwd=self.cwd,
                env=env,
                timeout=timeout,
            )
        except FileNotFoundError:
            return ToolResult(call_id, tool_name, False, "", f"command not found: {parts[0]}")
        except subprocess.TimeoutExpired as exc:
            output = redact_sensitive_text((exc.stdout or "") + (exc.stderr or ""))
            sandboxed = getattr(self._command_executor, "sandboxed", False)
            return ToolResult(
                call_id,
                tool_name,
                False,
                output,
                f"command timed out after {timeout}s",
                metadata={
                    "cmd": cmd,
                    "timeout": timeout,
                    "duration_seconds": getattr(exc, "duration", None),
                    "timed_out": True,
                    "sandboxed": sandboxed,
                    "backend": getattr(self._command_executor, "backend", "local"),
                    "sandbox_error": _is_sandbox_error(
                        sandboxed,
                        output,
                        timed_out=True,
                    ),
                },
            )

        combined = "\n".join(part for part in [execution.stdout, execution.stderr] if part)
        combined = redact_sensitive_text(combined)
        return ToolResult(
            call_id=call_id,
            tool_name=tool_name,
            ok=execution.returncode == 0,
            output=combined.strip(),
            error=None if execution.returncode == 0 else f"exit code {execution.returncode}",
            metadata={
                "cmd": cmd,
                "timeout": timeout,
                "returncode": execution.returncode,
                "duration_seconds": execution.duration_seconds,
                "timed_out": execution.timed_out,
                "sandboxed": execution.sandboxed,
                "backend": execution.backend,
                "sandbox_error": _is_sandbox_error(
                    execution.sandboxed,
                    combined,
                    returncode=execution.returncode,
                    timed_out=execution.timed_out,
                ),
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
            output="\n".join(matches),
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


BUBBLEWRAP_EXECUTABLE = "bwrap"


class BubblewrapExecutor:
    backend = "bubblewrap"
    sandboxed = True

    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root.resolve()

    def run(
        self,
        *,
        parts: list[str],
        cwd: Path,
        env: dict[str, str],
        timeout: int,
    ) -> CommandExecutionResult:
        bwrap_args = self._build_bwrap_args(cwd)
        full_cmd = ["bwrap", *bwrap_args, "--", *parts]
        started = time.monotonic()
        try:
            completed = subprocess.run(
                full_cmd,
                cwd=cwd,
                text=True,
                capture_output=True,
                timeout=timeout,
                check=False,
                env=env,
            )
        except FileNotFoundError:
            return CommandExecutionResult(
                returncode=127,
                stdout="",
                stderr="bwrap: command not found",
                duration_seconds=time.monotonic() - started,
                backend=self.backend,
                sandboxed=self.sandboxed,
            )

        return CommandExecutionResult(
            returncode=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
            duration_seconds=time.monotonic() - started,
            backend=self.backend,
            sandboxed=self.sandboxed,
        )

    def _build_bwrap_args(self, cwd: Path) -> list[str]:
        workspace = str(self.workspace_root)
        args: list[str] = [
            "--ro-bind", "/", "/",
            "--bind", workspace, workspace,
            "--bind", "/tmp", "/tmp",
            "--dev", "/dev",
            "--proc", "/proc",
            "--unshare-net",
            "--die-with-parent",
            "--new-session",
        ]
        for target in _protected_sensitive_paths(self.workspace_root):
            _append_bwrap_mask(args, target)
        return args


def _has_bubblewrap() -> bool:
    return shutil.which(BUBBLEWRAP_EXECUTABLE) is not None


def build_command_executor(cwd: Path) -> CommandExecutor:
    if sys.platform == "darwin" and Path(MACOS_SANDBOX_EXECUTABLE).is_file():
        return MacOSSeatbeltExecutor(cwd)
    if sys.platform == "linux" and _has_bubblewrap():
        return BubblewrapExecutor(cwd)
    return LocalCommandExecutor()


def _build_macos_seatbelt_profile(workspace_root: Path) -> str:
    workspace_root = workspace_root.resolve()
    allowed_write_paths = _dedupe_existing_paths(
        [workspace_root, Path("/tmp"), Path("/private/tmp"), Path("/var/tmp"), Path("/private/var/tmp")]
    )
    write_rules = "\n".join(
        _sandbox_write_clause(path, workspace_root)
        for path in allowed_write_paths
    )
    deny_rules = "\n".join(
        _sandbox_deny_clause(path)
        for path in _protected_sensitive_paths(workspace_root)
    )
    return "\n".join(
        [
            "(version 1)",
            "(deny default)",
            "(allow process-exec)",
            "(allow process-fork)",
            "(allow signal (target same-sandbox))",
            "(allow process-info* (target same-sandbox))",
            "(deny network*)",
            '(allow file-write-data (literal "/dev/null"))',
            "(allow file-read* file-test-existence (subpath \"/\"))",
            "(allow file-read-metadata (literal \"/\"))",
            "(allow file-read* file-write* (subpath \"/dev\"))",
            "(allow file-ioctl (subpath \"/dev\"))",
            "(allow pseudo-tty)",
            "(allow sysctl-read)",
            "(allow mach-lookup",
            *[f'  (global-name "{name}")' for name in MACOS_SANDBOX_MACH_LOOKUPS],
            '  (local-name "com.apple.cfprefsd.agent")',
            ")",
            "(allow ipc-posix-sem)",
            "(allow ipc-posix-shm*)",
            "(allow system-socket)",
            "(allow file-map-executable",
            '  (subpath "/System")',
            '  (subpath "/Library")',
            '  (subpath "/usr")',
            '  (subpath "/opt/homebrew")',
            '  (subpath "/usr/local")',
            ")",
            *([deny_rules] if deny_rules else []),
            "(allow file-write*",
            write_rules,
            ")",
        ]
    )


def _dedupe_existing_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        try:
            resolved = path.resolve()
        except OSError:
            continue
        key = str(resolved)
        if key in seen or not resolved.exists():
            continue
        seen.add(key)
        result.append(resolved)
    return result


def _protected_sensitive_paths(workspace_root: Path) -> list[Path]:
    protected: list[Path] = []
    for relative in MACOS_SANDBOX_PROTECTED_PATHS:
        protected.append(workspace_root / relative)
    protected.extend(_iter_sensitive_workspace_paths(workspace_root))
    home = Path.home()
    for relative in MACOS_SANDBOX_HOME_PROTECTED_PATHS:
        protected.append(home / relative)
    return _dedupe_existing_paths(protected)


def _iter_sensitive_workspace_paths(workspace_root: Path) -> list[Path]:
    paths: list[Path] = []
    pending = [workspace_root]
    while pending:
        directory = pending.pop()
        try:
            children = list(directory.iterdir())
        except OSError:
            continue
        for candidate in children:
            if candidate.is_symlink():
                continue
            if candidate.is_dir():
                if candidate.name in IGNORED_SEARCH_DIRS:
                    continue
                pending.append(candidate)
                continue
            try:
                if candidate.is_file() and is_sensitive_workspace_path(candidate, workspace_root):
                    paths.append(candidate)
            except OSError:
                continue
    return paths


def _append_bwrap_mask(args: list[str], target: Path) -> None:
    if target.is_dir():
        args.extend(["--tmpfs", str(target)])
        return
    if target.is_file():
        args.extend(["--ro-bind", "/dev/null", str(target)])


def _sandbox_deny_clause(path: Path) -> str:
    escaped = _escape_sbpl_path(path)
    operations = "file-read* file-write* file-read-metadata file-test-existence"
    if path.is_dir():
        return "\n".join(
            [
                f'(deny {operations} (literal "{escaped}"))',
                f'(deny {operations} (subpath "{escaped}"))',
            ]
        )
    return f'(deny {operations} (literal "{escaped}"))'


def _sandbox_write_clause(path: Path, workspace_root: Path) -> str:
    escaped = _escape_sbpl_path(path)
    exclusions: list[Path] = []
    if path == workspace_root:
        exclusions.extend(workspace_root / relative for relative in MACOS_SANDBOX_PROTECTED_PATHS)
        exclusions.extend(_protected_sensitive_paths(workspace_root))
    exclusion_checks = []
    for excluded in _dedupe_existing_paths(exclusions):
        escaped_excluded = _escape_sbpl_path(excluded)
        exclusion_checks.append(f'(require-not (literal "{escaped_excluded}"))')
        exclusion_checks.append(f'(require-not (subpath "{escaped_excluded}"))')
    if not exclusion_checks:
        return f'  (subpath "{escaped}")'
    checks = " ".join([f'(subpath "{escaped}")', *exclusion_checks])
    return f"  (require-all {checks})"


def _escape_sbpl_path(path: Path) -> str:
    return str(path).replace("\\", "\\\\").replace('"', '\\"')


def _is_sandbox_error(
    sandboxed: bool,
    output: str,
    *,
    returncode: int | None = None,
    timed_out: bool = False,
) -> bool:
    if not sandboxed:
        return False
    if returncode is not None and returncode < 0:
        return True
    normalized = output.lower()
    markers = (
        "operation not permitted",
        "sandbox-exec:",
        "sandbox violation",
        "deny(",
        "bwrap:",
        "bubblewrap",
    )
    if any(marker in normalized for marker in markers):
        return True
    if timed_out and "sandbox" in normalized:
        return True
    return False


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


def normalize_python_command(parts: list[str]) -> list[str]:
    if not parts:
        return parts
    head = parts[0]
    if is_python_executable(head):
        return [sys.executable, *parts[1:]]
    return parts


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
    return is_sensitive_workspace_path(path, cwd)
