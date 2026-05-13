from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_REPO_MAP_MAX_FILES = 80
DEFAULT_REPO_MAP_MAX_TOKENS = 1200

_IGNORED_DIRS = {
    ".git",
    ".harnesscoder",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "node_modules",
}
_SENSITIVE_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    ".envrc",
    "models.toml",
}
_SENSITIVE_SUFFIXES = (".key", ".pem", ".p12", ".pfx", ".pyc", ".sqlite", ".db")
_TEXT_EXTENSIONS = {
    ".cfg",
    ".ini",
    ".json",
    ".md",
    ".py",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}


@dataclass(frozen=True, slots=True)
class RepoMapEntry:
    path: str
    imports: tuple[str, ...] = ()
    classes: tuple[str, ...] = ()
    functions: tuple[str, ...] = ()
    symbols: tuple[str, ...] = ()
    parse_error: str | None = None
    score: int = 0


@dataclass(frozen=True, slots=True)
class RepoMapResult:
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


class RepoMapCache:
    """Small repo-map cache keyed by file path, mtime, and size."""

    def __init__(self, cwd: Path) -> None:
        self.cwd = cwd.resolve()
        self._snapshot: tuple[tuple[str, int, int], ...] | None = None
        self._entries: tuple[RepoMapEntry, ...] = ()

    def render(
        self,
        *,
        query: str | None = None,
        max_tokens: int = DEFAULT_REPO_MAP_MAX_TOKENS,
        max_files: int = DEFAULT_REPO_MAP_MAX_FILES,
        refresh: bool = False,
    ) -> RepoMapResult:
        max_tokens = max(100, min(int(max_tokens), 8000))
        max_files = max(1, min(int(max_files), 500))
        snapshot = _snapshot_repo(self.cwd)
        built = refresh or self._snapshot != snapshot
        if built:
            self._entries = tuple(_build_entries(self.cwd, snapshot))
            self._snapshot = snapshot

        ranked = _rank_entries(self._entries, query)
        text, render_metadata = _render_entries(
            ranked,
            query=query,
            max_tokens=max_tokens,
            max_files=max_files,
        )
        metadata = {
            "query": query or "",
            "max_tokens": max_tokens,
            "max_files": max_files,
            "built": built,
            "files_indexed": len(self._entries),
            **render_metadata,
        }
        return RepoMapResult(text=text, metadata=metadata)


def build_repo_map(
    cwd: Path,
    *,
    query: str | None = None,
    max_tokens: int = DEFAULT_REPO_MAP_MAX_TOKENS,
    max_files: int = DEFAULT_REPO_MAP_MAX_FILES,
) -> RepoMapResult:
    return RepoMapCache(cwd).render(
        query=query,
        max_tokens=max_tokens,
        max_files=max_files,
        refresh=True,
    )


def _snapshot_repo(cwd: Path) -> tuple[tuple[str, int, int], ...]:
    rows: list[tuple[str, int, int]] = []
    for path in sorted(cwd.rglob("*")):
        if path.is_symlink() or not path.is_file() or _is_ignored(path, cwd):
            continue
        try:
            path.resolve().relative_to(cwd.resolve())
            stat = path.stat()
            rel = path.relative_to(cwd).as_posix()
        except (OSError, ValueError):
            continue
        rows.append((rel, stat.st_mtime_ns, stat.st_size))
    return tuple(rows)


def _build_entries(
    cwd: Path,
    snapshot: tuple[tuple[str, int, int], ...],
) -> list[RepoMapEntry]:
    entries: list[RepoMapEntry] = []
    for rel_path, _mtime, size in snapshot:
        if size > 250_000:
            entries.append(RepoMapEntry(path=rel_path, parse_error="skipped_large_file"))
            continue
        path = cwd / rel_path
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            entries.append(RepoMapEntry(path=rel_path, parse_error=type(exc).__name__))
            continue
        if path.suffix == ".py":
            entries.append(_python_entry(rel_path, text))
        else:
            entries.append(_fallback_entry(rel_path, text))
    return entries


def _python_entry(rel_path: str, text: str) -> RepoMapEntry:
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return _fallback_entry(rel_path, text, parse_error=f"SyntaxError:{exc.lineno}")

    imports: list[str] = []
    classes: list[str] = []
    functions: list[str] = []

    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imports.extend(_format_imports(node))
            continue
        if isinstance(node, ast.ClassDef):
            classes.append(_class_signature(node))
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    functions.append(
                        f"{node.name}.{_function_signature(child)}"
                    )
            continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(_function_signature(node))

    symbols = tuple(
        _dedupe(
            [
                *(_symbol_name(item) for item in classes),
                *(_symbol_name(item) for item in functions),
            ]
        )
    )
    return RepoMapEntry(
        path=rel_path,
        imports=tuple(_dedupe(imports)),
        classes=tuple(classes),
        functions=tuple(functions),
        symbols=symbols,
    )


def _fallback_entry(
    rel_path: str,
    text: str,
    *,
    parse_error: str | None = None,
) -> RepoMapEntry:
    symbols: list[str] = []
    for pattern in (
        r"\bclass\s+([A-Za-z_][A-Za-z0-9_]*)",
        r"\bdef\s+([A-Za-z_][A-Za-z0-9_]*)",
        r"\bfunction\s+([A-Za-z_][A-Za-z0-9_]*)",
        r"\bconst\s+([A-Za-z_][A-Za-z0-9_]*)",
    ):
        symbols.extend(match.group(1) for match in re.finditer(pattern, text))
    return RepoMapEntry(
        path=rel_path,
        symbols=tuple(_dedupe(symbols[:20])),
        parse_error=parse_error,
    )


def _format_imports(node: ast.Import | ast.ImportFrom) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    module = "." * node.level + (node.module or "")
    return [f"{module}.{alias.name}".strip(".") for alias in node.names]


def _class_signature(node: ast.ClassDef) -> str:
    bases = [_safe_unparse(base) for base in node.bases]
    if not bases:
        return f"class {node.name}"
    return f"class {node.name}({', '.join(bases)})"


def _function_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    args = [_arg.arg for _arg in [*node.args.posonlyargs, *node.args.args]]
    if node.args.vararg is not None:
        args.append(f"*{node.args.vararg.arg}")
    elif node.args.kwonlyargs:
        args.append("*")
    args.extend(_arg.arg for _arg in node.args.kwonlyargs)
    if node.args.kwarg is not None:
        args.append(f"**{node.args.kwarg.arg}")
    prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
    return f"{prefix}{node.name}({', '.join(args)})"


def _safe_unparse(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return type(node).__name__


def _rank_entries(
    entries: tuple[RepoMapEntry, ...],
    query: str | None,
) -> list[RepoMapEntry]:
    query_tokens = _tokens(query or "")
    ranked: list[RepoMapEntry] = []
    for entry in entries:
        score = _entry_score(entry, query_tokens)
        ranked.append(
            RepoMapEntry(
                path=entry.path,
                imports=entry.imports,
                classes=entry.classes,
                functions=entry.functions,
                symbols=entry.symbols,
                parse_error=entry.parse_error,
                score=score,
            )
        )
    return sorted(ranked, key=lambda item: (-item.score, item.path))


def _entry_score(entry: RepoMapEntry, query_tokens: set[str]) -> int:
    if not query_tokens:
        return 0
    path_tokens = _tokens(entry.path)
    symbol_tokens = _tokens(" ".join([*entry.symbols, *entry.imports]))
    score = 0
    for token in query_tokens:
        if token in path_tokens:
            score += 4
        if token in symbol_tokens:
            score += 3
        if token in entry.path.lower():
            score += 1
    return score


def _render_entries(
    entries: list[RepoMapEntry],
    *,
    query: str | None,
    max_tokens: int,
    max_files: int,
) -> tuple[str, dict[str, Any]]:
    lines = [
        "# RepoMap",
        f"query: {query or '-'}",
        "format: path plus imports/classes/functions/symbols",
    ]
    rendered_files: list[str] = []
    truncated = False

    for entry in entries[:max_files]:
        candidate = _entry_lines(entry)
        if _estimate_tokens("\n".join([*lines, *candidate])) > max_tokens:
            truncated = True
            break
        lines.extend(candidate)
        rendered_files.append(entry.path)

    text = "\n".join(lines)
    return text, {
        "files_rendered": len(rendered_files),
        "files": rendered_files,
        "estimated_tokens": _estimate_tokens(text),
        "truncated": truncated or len(entries) > len(rendered_files),
    }


def _entry_lines(entry: RepoMapEntry) -> list[str]:
    lines = [f"- {entry.path}"]
    if entry.score:
        lines.append(f"  score: {entry.score}")
    if entry.imports:
        lines.append(f"  imports: {', '.join(entry.imports[:12])}")
    if entry.classes:
        lines.append(f"  classes: {', '.join(entry.classes[:12])}")
    if entry.functions:
        lines.append(f"  functions: {', '.join(entry.functions[:16])}")
    fallback_symbols = [
        symbol
        for symbol in entry.symbols
        if symbol not in " ".join([*entry.classes, *entry.functions])
    ]
    if fallback_symbols:
        lines.append(f"  symbols: {', '.join(fallback_symbols[:16])}")
    if entry.parse_error:
        lines.append(f"  note: {entry.parse_error}")
    return lines


def _is_ignored(path: Path, cwd: Path) -> bool:
    try:
        rel = path.relative_to(cwd)
    except ValueError:
        return True
    if any(part in _IGNORED_DIRS for part in rel.parts):
        return True
    name = path.name
    if name in _SENSITIVE_NAMES or name.startswith(".env."):
        return True
    if name.endswith(_SENSITIVE_SUFFIXES):
        return True
    return not (path.suffix in _TEXT_EXTENSIONS or path.suffix == "")


def _symbol_name(value: str) -> str:
    value = value.removeprefix("class ")
    value = value.removeprefix("async ")
    return value.split("(", 1)[0]


def _tokens(value: str) -> set[str]:
    return {
        token.lower()
        for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*|\d+", value)
        if len(token) > 1
    }


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        deduped.append(value)
        seen.add(value)
    return deduped


def _estimate_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)
