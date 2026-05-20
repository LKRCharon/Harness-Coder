from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from harnesscoder.core.runner import RunResult


SESSION_VERSION = 1
DEFAULT_SESSION_ID = "default"
DEFAULT_SESSION_ROOT = Path(".harnesscoder/sessions")
MAX_RECENT_TURNS = 6
MAX_TEXT_CHARS = 1200
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


@dataclass(frozen=True, slots=True)
class SessionRecord:
    session_id: str
    cwd: str
    created_at: str
    updated_at: str
    summary: str
    turns: list[dict[str, Any]]

    def to_record(self) -> dict[str, Any]:
        return {
            "version": SESSION_VERSION,
            "session_id": self.session_id,
            "cwd": self.cwd,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "summary": self.summary,
            "turns": [dict(turn) for turn in self.turns],
        }


class SessionStore:
    """Durable cross-run session state for interactive HarnessCoder use."""

    def __init__(self, root: Path, cwd: Path) -> None:
        self.cwd = cwd.resolve()
        self.root = root if root.is_absolute() else self.cwd / root
        self.root = self.root.resolve()

    def path_for(self, session_id: str) -> Path:
        safe_id = normalize_session_id(session_id)
        return self.root / f"{safe_id}.json"

    def load(self, session_id: str) -> SessionRecord:
        safe_id = normalize_session_id(session_id)
        path = self.path_for(safe_id)
        if not path.is_file():
            now = _now()
            return SessionRecord(
                session_id=safe_id,
                cwd=str(self.cwd),
                created_at=now,
                updated_at=now,
                summary="",
                turns=[],
            )

        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"session must be a JSON object: {path}")
        if payload.get("version") != SESSION_VERSION:
            raise ValueError(f"unsupported session version: {payload.get('version')}")

        turns = [
            dict(turn)
            for turn in payload.get("turns", [])
            if isinstance(turn, dict)
        ]
        return SessionRecord(
            session_id=safe_id,
            cwd=str(payload.get("cwd") or self.cwd),
            created_at=str(payload.get("created_at") or _now()),
            updated_at=str(payload.get("updated_at") or _now()),
            summary=str(payload.get("summary") or ""),
            turns=turns,
        )

    def save(self, record: SessionRecord) -> Path:
        path = self.path_for(record.session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_name(f"{path.name}.tmp")
        temp_path.write_text(
            json.dumps(record.to_record(), ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        temp_path.replace(path)
        return path

    def reset(self, session_id: str) -> Path:
        record = self.load(session_id)
        now = _now()
        empty = SessionRecord(
            session_id=record.session_id,
            cwd=str(self.cwd),
            created_at=now,
            updated_at=now,
            summary="",
            turns=[],
        )
        return self.save(empty)

    def append_run(
        self,
        session_id: str,
        *,
        user_message: str,
        result: "RunResult",
    ) -> SessionRecord:
        record = self.load(session_id)
        turns = [dict(turn) for turn in record.turns]
        turn = {
            "turn_index": len(turns) + 1,
            "user_message": _clip(user_message, MAX_TEXT_CHARS),
            "run_id": result.run_id,
            "status": result.status,
            "final_answer": _clip(result.final_answer, MAX_TEXT_CHARS),
            "trace_path": str(result.trace_path),
            "created_at": _now(),
        }
        turns.append(turn)
        updated = SessionRecord(
            session_id=record.session_id,
            cwd=str(self.cwd),
            created_at=record.created_at,
            updated_at=_now(),
            summary=_summarize_turns(turns),
            turns=turns,
        )
        self.save(updated)
        return updated

    def build_context(self, session_id: str) -> dict[str, Any]:
        record = self.load(session_id)
        return session_context_from_record(record)


def normalize_session_id(session_id: str | None) -> str:
    value = (session_id or DEFAULT_SESSION_ID).strip()
    if not value:
        value = DEFAULT_SESSION_ID
    if not SESSION_ID_RE.fullmatch(value):
        raise ValueError(
            "session id must start with a letter or digit and contain only "
            "letters, digits, dot, underscore, or dash"
        )
    return value


def session_context_from_record(record: SessionRecord) -> dict[str, Any]:
    recent_turns = [
        {
            "turn_index": turn.get("turn_index"),
            "user_message": _clip(str(turn.get("user_message") or ""), MAX_TEXT_CHARS),
            "status": turn.get("status"),
            "final_answer": _clip(str(turn.get("final_answer") or ""), MAX_TEXT_CHARS),
            "run_id": turn.get("run_id"),
            "trace_path": turn.get("trace_path"),
        }
        for turn in record.turns[-MAX_RECENT_TURNS:]
    ]
    return {
        "version": SESSION_VERSION,
        "session_id": record.session_id,
        "cwd": record.cwd,
        "turn_count": len(record.turns),
        "summary": record.summary,
        "recent_turns": recent_turns,
    }


def _summarize_turns(turns: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for turn in turns[-MAX_RECENT_TURNS:]:
        user = _clip(str(turn.get("user_message") or ""), 180)
        answer = _clip(str(turn.get("final_answer") or ""), 180)
        status = str(turn.get("status") or "-")
        run_id = str(turn.get("run_id") or "-")
        lines.append(
            f"{turn.get('turn_index')}. user={user!r}; status={status}; "
            f"run_id={run_id}; answer={answer!r}"
        )
    return "\n".join(lines)


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 32)] + f"... [truncated {len(text) - limit} chars]"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
