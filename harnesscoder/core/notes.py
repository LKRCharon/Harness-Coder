from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


NOTE_TYPES = (
    "blocker",
    "action",
    "task_state",
    "decision",
    "conclusion",
    "verified_fact",
    "general",
)
DEFAULT_NOTE_TYPE = "general"
DEFAULT_NOTES_ROOT = Path(".harnesscoder/notes")
NOTES_INDEX_FILENAME = "notes_index.json"
NOTE_FILE_SUFFIX = ".md"
NOTES_INDEX_VERSION = 1
MAX_NOTE_TITLE_CHARS = 160
MAX_NOTE_CONTENT_CHARS = 4000
MAX_NOTE_TAGS = 12
MAX_NOTE_TAG_CHARS = 40
MAX_NOTE_QUERY_CHARS = 240
MAX_NOTE_SEARCH_LIMIT = 20


@dataclass(slots=True)
class NoteRecord:
    note_id: str
    type: str
    title: str
    content: str
    tags: list[str] = field(default_factory=list)
    source_run_id: str | None = None
    source_call_id: str | None = None
    created_at: str = ""
    updated_at: str = ""
    file_path: str | None = None

    def to_record(self) -> dict[str, Any]:
        return {
            "note_id": self.note_id,
            "type": self.type,
            "title": self.title,
            "content": self.content,
            "tags": list(self.tags),
            "source_run_id": self.source_run_id,
            "source_call_id": self.source_call_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "file_path": self.file_path,
        }

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> "NoteRecord":
        note_type = str(record.get("type") or DEFAULT_NOTE_TYPE)
        if note_type not in NOTE_TYPES:
            note_type = DEFAULT_NOTE_TYPE
        tags = record.get("tags", [])
        return cls(
            note_id=str(record.get("note_id") or record.get("id") or ""),
            type=note_type,
            title=str(record.get("title") or ""),
            content=str(record.get("content") or ""),
            tags=[str(tag) for tag in tags if isinstance(tag, str)],
            source_run_id=(
                str(record["source_run_id"])
                if record.get("source_run_id") is not None
                else None
            ),
            source_call_id=(
                str(record["source_call_id"])
                if record.get("source_call_id") is not None
                else None
            ),
            created_at=str(record.get("created_at") or ""),
            updated_at=str(record.get("updated_at") or ""),
            file_path=(
                str(record["file_path"]) if record.get("file_path") is not None else None
            ),
        )


class NoteStore:
    """Local Markdown-backed store for durable task notes."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.path = root / NOTES_INDEX_FILENAME

    @classmethod
    def for_workspace(cls, cwd: Path) -> "NoteStore":
        return cls(cwd.resolve() / DEFAULT_NOTES_ROOT)

    def create(
        self,
        *,
        note_type: str = DEFAULT_NOTE_TYPE,
        title: str,
        content: str,
        tags: list[str] | None = None,
        source_run_id: str | None = None,
        source_call_id: str | None = None,
    ) -> NoteRecord:
        note_type = normalize_note_type(note_type)
        title = normalize_note_title(title)
        content = normalize_note_content(content)
        tags = normalize_note_tags(tags or [])
        now = _now_iso()
        note_id = f"note_{uuid4().hex[:12]}"
        file_path = f"{note_id}{NOTE_FILE_SUFFIX}"
        note = NoteRecord(
            note_id=note_id,
            type=note_type,
            title=title,
            content=content,
            tags=tags,
            source_run_id=source_run_id,
            source_call_id=source_call_id,
            created_at=now,
            updated_at=now,
            file_path=file_path,
        )
        self.root.mkdir(parents=True, exist_ok=True)
        self._write_note_file(note)
        index = self._load_index()
        index["notes"][note.note_id] = self._summary_record(note)
        self._write_index(index)
        return note

    def search(
        self,
        *,
        query: str,
        limit: int = 5,
        note_type: str | None = None,
    ) -> list[NoteRecord]:
        query = normalize_note_query(query)
        limit = normalize_note_search_limit(limit)
        if note_type is not None:
            note_type = normalize_note_type(note_type)
        notes = self.list_all()
        ranked: list[tuple[float, NoteRecord]] = []
        query_terms = _terms(query)
        for note in notes:
            if note_type is not None and note.type != note_type:
                continue
            score = _score_note(note, query_terms)
            if score <= 0:
                continue
            ranked.append((score, note))
        ranked.sort(key=lambda item: (-item[0], item[1].updated_at, item[1].note_id))
        return [note for _, note in ranked[:limit]]

    def list_recent(
        self,
        *,
        limit: int = 5,
        note_type: str | None = None,
    ) -> list[NoteRecord]:
        limit = normalize_note_search_limit(limit)
        if note_type is not None:
            note_type = normalize_note_type(note_type)
        index = self._load_index()
        summaries = list(index["notes"].values())
        filtered = [
            summary
            for summary in summaries
            if note_type is None or summary.get("type") == note_type
        ]
        filtered.sort(
            key=lambda summary: (
                str(summary.get("updated_at") or ""),
                str(summary.get("note_id") or ""),
            ),
            reverse=True,
        )
        notes: list[NoteRecord] = []
        for summary in filtered[:limit]:
            note = self._read_note_from_summary(summary)
            if note is not None:
                notes.append(note)
        return notes

    def list_all(self) -> list[NoteRecord]:
        index = self._load_index()
        notes: list[NoteRecord] = []
        for summary in index["notes"].values():
            note = self._read_note_from_summary(summary)
            if note is not None:
                notes.append(note)
        return notes

    def _summary_record(self, note: NoteRecord) -> dict[str, Any]:
        return {
            "note_id": note.note_id,
            "type": note.type,
            "title": note.title,
            "tags": list(note.tags),
            "source_run_id": note.source_run_id,
            "source_call_id": note.source_call_id,
            "created_at": note.created_at,
            "updated_at": note.updated_at,
            "file_path": note.file_path or f"{note.note_id}{NOTE_FILE_SUFFIX}",
        }

    def _write_note_file(self, note: NoteRecord) -> None:
        file_path = self.root / (note.file_path or f"{note.note_id}{NOTE_FILE_SUFFIX}")
        lines = [
            "---",
            f"note_id: {json.dumps(note.note_id, ensure_ascii=False)}",
            f"type: {json.dumps(note.type, ensure_ascii=False)}",
            f"title: {json.dumps(note.title, ensure_ascii=False)}",
            f"tags: {json.dumps(list(note.tags), ensure_ascii=False)}",
            f"source_run_id: {json.dumps(note.source_run_id, ensure_ascii=False)}",
            f"source_call_id: {json.dumps(note.source_call_id, ensure_ascii=False)}",
            f"created_at: {json.dumps(note.created_at, ensure_ascii=False)}",
            f"updated_at: {json.dumps(note.updated_at, ensure_ascii=False)}",
            "---",
            "",
            f"# {note.title}",
            "",
            note.content.rstrip(),
            "",
        ]
        file_path.write_text("\n".join(lines), encoding="utf-8")

    def _read_note_from_summary(self, summary: dict[str, Any]) -> NoteRecord | None:
        file_path = summary.get("file_path")
        if not isinstance(file_path, str) or not file_path:
            note_id = summary.get("note_id")
            if not isinstance(note_id, str) or not note_id:
                return None
            file_path = f"{note_id}{NOTE_FILE_SUFFIX}"
        target = self.root / file_path
        if not target.is_file():
            return None
        return self._read_note_file(target)

    def _read_note_file(self, path: Path) -> NoteRecord | None:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return None
        metadata, content = _parse_note_markdown(text)
        record = NoteRecord.from_record(metadata)
        record.content = normalize_note_content(content)
        record.file_path = str(path.relative_to(self.root))
        if not record.note_id or not record.title:
            return None
        return record

    def _load_index(self) -> dict[str, Any]:
        if self.path.is_file():
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                payload = None
            if isinstance(payload, dict) and isinstance(payload.get("notes"), dict):
                return {
                    "version": int(payload.get("version", NOTES_INDEX_VERSION)),
                    "notes": {
                        str(note_id): dict(summary)
                        for note_id, summary in payload["notes"].items()
                        if isinstance(summary, dict)
                    },
                }
        rebuilt = self._rebuild_index()
        self._write_index(rebuilt)
        return rebuilt

    def _rebuild_index(self) -> dict[str, Any]:
        notes: dict[str, dict[str, Any]] = {}
        if self.root.is_dir():
            for path in sorted(self.root.glob(f"*{NOTE_FILE_SUFFIX}")):
                note = self._read_note_file(path)
                if note is None:
                    continue
                notes[note.note_id] = self._summary_record(note)
        return {"version": NOTES_INDEX_VERSION, "notes": notes}

    def _write_index(self, index: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": NOTES_INDEX_VERSION,
            "notes": dict(sorted(index.get("notes", {}).items())),
        }
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def normalize_note_type(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        return DEFAULT_NOTE_TYPE
    normalized = value.strip().lower()
    if normalized not in NOTE_TYPES:
        valid = ", ".join(NOTE_TYPES)
        raise ValueError(f"note_type must be one of: {valid}")
    return normalized


def normalize_note_title(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("title must be a non-empty string")
    normalized = " ".join(value.split())
    if len(normalized) > MAX_NOTE_TITLE_CHARS:
        raise ValueError(f"title exceeds {MAX_NOTE_TITLE_CHARS} characters")
    return normalized


def normalize_note_content(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("content must be a non-empty string")
    normalized = value.strip()
    if len(normalized) > MAX_NOTE_CONTENT_CHARS:
        raise ValueError(f"content exceeds {MAX_NOTE_CONTENT_CHARS} characters")
    return normalized


def normalize_note_tags(value: list[str]) -> list[str]:
    if not isinstance(value, list):
        raise ValueError("tags must be a list of strings")
    if len(value) > MAX_NOTE_TAGS:
        raise ValueError(f"tags exceeds {MAX_NOTE_TAGS} items")
    tags: list[str] = []
    for raw_tag in value:
        if not isinstance(raw_tag, str):
            raise ValueError("tags must be a list of strings")
        tag = raw_tag.strip()
        if not tag:
            continue
        if len(tag) > MAX_NOTE_TAG_CHARS:
            raise ValueError(f"tag exceeds {MAX_NOTE_TAG_CHARS} characters")
        if tag not in tags:
            tags.append(tag)
    return tags


def normalize_note_query(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("query must be a non-empty string")
    normalized = " ".join(value.split())
    if len(normalized) > MAX_NOTE_QUERY_CHARS:
        raise ValueError(f"query exceeds {MAX_NOTE_QUERY_CHARS} characters")
    return normalized


def normalize_note_search_limit(value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError("limit must be a positive integer")
    if value > MAX_NOTE_SEARCH_LIMIT:
        raise ValueError(f"limit exceeds {MAX_NOTE_SEARCH_LIMIT}")
    return value


def _parse_note_markdown(text: str) -> tuple[dict[str, Any], str]:
    metadata: dict[str, Any] = {}
    if not text.startswith("---\n"):
        return metadata, text.strip()
    end_marker = text.find("\n---\n", 4)
    if end_marker < 0:
        return metadata, text.strip()
    frontmatter = text[4:end_marker]
    body = text[end_marker + len("\n---\n") :].lstrip("\n")
    for line in frontmatter.splitlines():
        if ":" not in line:
            continue
        key, raw_value = line.split(":", 1)
        key = key.strip()
        value = raw_value.strip()
        if not key:
            continue
        try:
            metadata[key] = json.loads(value)
        except json.JSONDecodeError:
            metadata[key] = value
    body_lines = body.splitlines()
    if body_lines and body_lines[0].startswith("# "):
        body_lines = body_lines[1:]
        if body_lines and not body_lines[0].strip():
            body_lines = body_lines[1:]
    return metadata, "\n".join(body_lines).strip()


def _score_note(note: NoteRecord, query_terms: set[str]) -> float:
    if not query_terms:
        return 0
    title_terms = _terms(note.title)
    content_terms = _terms(note.content)
    tag_terms = {term for tag in note.tags for term in _terms(tag)}
    score = 0.0
    score += len(query_terms & title_terms) * 4
    score += len(query_terms & tag_terms) * 3
    score += len(query_terms & content_terms)
    score += _type_weight(note.type)
    return score


def _type_weight(note_type: str) -> float:
    weights = {
        "blocker": 2.0,
        "task_state": 1.6,
        "verified_fact": 1.4,
        "decision": 1.2,
        "action": 1.0,
        "conclusion": 0.8,
        "general": 0.4,
    }
    return weights.get(note_type, 0.0)


def _terms(value: str) -> set[str]:
    normalized = value.lower()
    current: list[str] = []
    terms: set[str] = set()
    for char in normalized:
        if char.isalnum() or char in {"_", "-", "/"}:
            current.append(char)
        elif current:
            terms.add("".join(current))
            current = []
    if current:
        terms.add("".join(current))
    return {term for term in terms if len(term) > 1}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
