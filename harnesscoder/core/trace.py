from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class TraceWriter:
    """Append-only JSONL trace writer for one HarnessCoder run."""

    def __init__(self, run_id: str, trace_root: Path, cwd: Path) -> None:
        self.run_id = run_id
        self.cwd = cwd
        self.run_dir = (cwd / trace_root).resolve()
        self.run_path = self.run_dir / run_id
        self.trace_path = self.run_path / "trace.jsonl"
        self.run_path.mkdir(parents=True, exist_ok=True)

    @classmethod
    def resume(cls, run_id: str, trace_path: Path, cwd: Path) -> "TraceWriter":
        writer = cls.__new__(cls)
        writer.run_id = run_id
        writer.cwd = cwd
        writer.trace_path = trace_path.resolve()
        writer.run_path = writer.trace_path.parent
        writer.run_dir = writer.run_path.parent
        writer.run_path.mkdir(parents=True, exist_ok=True)
        return writer

    def emit(self, event_type: str, **payload: Any) -> None:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "run_id": self.run_id,
            "type": event_type,
            **payload,
        }
        with self.trace_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
