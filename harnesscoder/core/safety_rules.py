from __future__ import annotations

from pathlib import Path


SENSITIVE_FILE_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    ".envrc",
    "models.toml",
}
SENSITIVE_FILE_SUFFIXES = (".key", ".pem", ".p12", ".pfx", ".sqlite", ".db")


def iter_sensitive_file_globs() -> tuple[str, ...]:
    globs: list[str] = []
    for name in sorted(SENSITIVE_FILE_NAMES):
        globs.append(f"!**/{name}")
    globs.append("!**/.env.*")
    for suffix in SENSITIVE_FILE_SUFFIXES:
        globs.append(f"!**/*{suffix}")
    return tuple(globs)


def is_python_executable(head: str) -> bool:
    if head in {"python", "python3"}:
        return True
    if not head.startswith("python3."):
        return False
    suffix = head[len("python3.") :]
    return bool(suffix) and all(part.isdigit() for part in suffix.split("."))


def is_sensitive_workspace_path(path: Path, cwd: Path) -> bool:
    try:
        rel = path.relative_to(cwd)
    except ValueError:
        return True
    for part in rel.parts:
        if part in SENSITIVE_FILE_NAMES or part.startswith(".env."):
            return True
    return path.name.endswith(SENSITIVE_FILE_SUFFIXES)
