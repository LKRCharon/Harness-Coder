from __future__ import annotations

from pathlib import Path


def export_report(base_dir, name, content):
    base = Path(base_dir) / "reports"
    base.mkdir(parents=True, exist_ok=True)
    target = base / name
    target.write_text(content, encoding="utf-8")
    return target
