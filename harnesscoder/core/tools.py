from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


MAX_TOOL_OUTPUT = 16_000


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
        self._tools: dict[str, ToolFn] = {
            "read_file": self.read_file,
            "search_code": self.search_code,
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
                "--hidden",
                "--glob",
                "!.git/**",
                "--glob",
                "!.harnesscoder/**",
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

    def run_command(
        self,
        call_id: str,
        cmd: str,
        timeout: int = 30,
    ) -> ToolResult:
        tool_name = "run_command"
        timeout = max(1, min(int(timeout), 120))
        try:
            parts = shlex.split(cmd)
        except ValueError as exc:
            return ToolResult(call_id, tool_name, False, "", f"could not parse cmd: {exc}")

        env = {
            **os.environ,
            "PYTHONUTF8": "1",
        }
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
            output = (exc.stdout or "") + (exc.stderr or "")
            return ToolResult(
                call_id,
                tool_name,
                False,
                _truncate(output),
                f"command timed out after {timeout}s",
            )

        combined = "\n".join(part for part in [completed.stdout, completed.stderr] if part)
        return ToolResult(
            call_id=call_id,
            tool_name=tool_name,
            ok=completed.returncode == 0,
            output=_truncate(combined.strip()),
            error=None if completed.returncode == 0 else f"exit code {completed.returncode}",
            metadata={"cmd": cmd, "timeout": timeout, "returncode": completed.returncode},
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
            if ".git" in candidate.parts or ".harnesscoder" in candidate.parts:
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
