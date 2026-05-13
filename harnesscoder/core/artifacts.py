from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from harnesscoder.core.tools import ToolResult, redact_sensitive_text


MAX_OBSERVATION_PREVIEW_CHARS = 4_000


@dataclass(frozen=True, slots=True)
class ObservationStorageResult:
    result: ToolResult
    stored: bool


def store_large_observation(
    result: ToolResult,
    *,
    run_path: Path,
    preview_chars: int = MAX_OBSERVATION_PREVIEW_CHARS,
) -> ObservationStorageResult:
    """Persist large tool output and return a preview suitable for model context."""

    raw_output = redact_sensitive_text(result.output)
    raw_chars = len(raw_output)
    metadata = dict(result.metadata)
    metadata["raw_output_chars"] = raw_chars

    if raw_chars <= preview_chars:
        metadata["observation_preview_chars"] = raw_chars
        metadata["artifact_stored"] = False
        return ObservationStorageResult(
            result=ToolResult(
                call_id=result.call_id,
                tool_name=result.tool_name,
                ok=result.ok,
                output=raw_output,
                error=result.error,
                metadata=metadata,
            ),
            stored=False,
        )

    artifact_rel_path = Path("artifacts") / f"{_artifact_name(result.call_id)}.txt"
    artifact_path = run_path / artifact_rel_path
    preview = _preview(raw_output, preview_chars)
    metadata["observation_preview_chars"] = len(preview)
    try:
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(raw_output, encoding="utf-8")
    except OSError as exc:
        metadata.update(
            {
                "artifact_stored": False,
                "artifact_error": f"{type(exc).__name__}: {exc}",
                "artifact_chars": 0,
            }
        )
        return ObservationStorageResult(
            result=ToolResult(
                call_id=result.call_id,
                tool_name=result.tool_name,
                ok=result.ok,
                output=preview,
                error=result.error,
                metadata=metadata,
            ),
            stored=False,
        )

    digest = hashlib.sha256(raw_output.encode("utf-8", errors="replace")).hexdigest()
    metadata.update(
        {
            "artifact_stored": True,
            "artifact_path": str(artifact_rel_path),
            "artifact_sha256": digest,
            "artifact_chars": raw_chars,
        }
    )
    return ObservationStorageResult(
        result=ToolResult(
            call_id=result.call_id,
            tool_name=result.tool_name,
            ok=result.ok,
            output=preview,
            error=result.error,
            metadata=metadata,
        ),
        stored=True,
    )


def _preview(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    suffix = "\n[full output stored as artifact; truncated output]"
    if limit <= len(suffix):
        return suffix[:limit]
    head_limit = limit - len(suffix)
    return f"{text[:head_limit]}{suffix}"


def _artifact_name(call_id: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", call_id).strip("._-")
    return cleaned or "tool_output"
