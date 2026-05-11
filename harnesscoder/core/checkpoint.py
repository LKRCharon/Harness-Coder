from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from harnesscoder.core.state import AgentState


CHECKPOINT_VERSION = 1


@dataclass(slots=True)
class Checkpoint:
    state: AgentState
    trace_path: Path


def default_checkpoint_path(trace_path: Path) -> Path:
    return trace_path.resolve().parent / "checkpoint.json"


def save_checkpoint(
    checkpoint_path: Path,
    *,
    state: AgentState,
    trace_path: Path,
) -> None:
    checkpoint_path = checkpoint_path.resolve()
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": CHECKPOINT_VERSION,
        "run_id": state.run_id,
        "trace_path": str(trace_path.resolve()),
        "state": state.to_record(),
    }
    temp_path = checkpoint_path.with_name(f"{checkpoint_path.name}.tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(checkpoint_path)


def load_checkpoint(checkpoint_path: Path) -> Checkpoint:
    payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("checkpoint must be a JSON object")
    if payload.get("version") != CHECKPOINT_VERSION:
        raise ValueError(f"unsupported checkpoint version: {payload.get('version')}")

    state_payload = payload.get("state")
    if not isinstance(state_payload, dict):
        raise ValueError("checkpoint state must be a JSON object")

    trace_path = payload.get("trace_path")
    if not isinstance(trace_path, str) or not trace_path:
        raise ValueError("checkpoint trace_path must be a non-empty string")

    return Checkpoint(
        state=AgentState.from_record(state_payload),
        trace_path=Path(trace_path).resolve(),
    )
