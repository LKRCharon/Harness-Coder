from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from harnesscoder.core.tools import ToolResult


MEMORY_BLOCK_SPECS = {
    "task/failing_tests": (
        1800,
        "Current failing test output or verifier evidence for this task.",
    ),
    "task/explored_files": (
        1800,
        "Files and search targets already explored in this task.",
    ),
    "task/relevant_symbols": (
        1600,
        "Symbols, imports, functions, classes, and searched names that may matter.",
    ),
    "task/patch_summary": (
        1800,
        "Task-local summary of edits made so far.",
    ),
    "task/verified_facts": (
        1800,
        "Facts verified by tests, tool output, or successful commands.",
    ),
    "task/open_questions": (
        1200,
        "Unresolved questions or next checks suggested by failed observations.",
    ),
}


@dataclass(slots=True)
class MemoryBlock:
    label: str
    value: str
    limit: int
    description: str
    updated_step: int

    def to_record(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "value": self.value,
            "limit": self.limit,
            "description": self.description,
            "updated_step": self.updated_step,
        }

    @classmethod
    def from_record(cls, label: str, record: dict[str, Any]) -> "MemoryBlock":
        limit, description = MEMORY_BLOCK_SPECS.get(label, (1200, "Task-local memory."))
        raw_limit = record.get("limit")
        if isinstance(raw_limit, int) and not isinstance(raw_limit, bool) and raw_limit > 0:
            limit = raw_limit
        raw_description = record.get("description")
        if isinstance(raw_description, str) and raw_description:
            description = raw_description
        updated_step = record.get("updated_step")
        return cls(
            label=label,
            value=str(record.get("value", "")),
            limit=limit,
            description=description,
            updated_step=updated_step if isinstance(updated_step, int) else 0,
        )


def default_memory_blocks() -> dict[str, MemoryBlock]:
    return {
        label: MemoryBlock(
            label=label,
            value="",
            limit=limit,
            description=description,
            updated_step=0,
        )
        for label, (limit, description) in MEMORY_BLOCK_SPECS.items()
    }


def memory_blocks_to_records(blocks: dict[str, MemoryBlock]) -> dict[str, dict[str, Any]]:
    return {label: block.to_record() for label, block in sorted(blocks.items())}


def memory_blocks_from_records(value: Any) -> dict[str, MemoryBlock]:
    blocks = default_memory_blocks()
    if not isinstance(value, dict):
        return blocks
    for label, raw_block in value.items():
        if isinstance(label, str) and isinstance(raw_block, dict):
            blocks[label] = MemoryBlock.from_record(label, raw_block)
    return blocks


def apply_memory_reducer(
    blocks: dict[str, MemoryBlock],
    *,
    result: ToolResult,
    step: int,
) -> list[str]:
    """Reduce one tool result into task-local memory blocks.

    The reducer is intentionally task-scoped: it only summarizes evidence from
    the current run and is serialized in checkpoints/traces for replay.
    """

    changed: list[str] = []

    if result.tool_name == "read_file" and result.ok:
        path = _metadata_text(result, "path", "<unknown>")
        changed += _append_unique(
            blocks,
            "task/explored_files",
            f"read {path}",
            step,
        )
        symbols = _extract_symbols(result.output)
        if symbols:
            changed += _append_unique(
                blocks,
                "task/relevant_symbols",
                f"{path}: {', '.join(symbols[:8])}",
                step,
            )

    if result.tool_name == "search_code" and result.ok:
        query = _metadata_text(result, "query", "")
        path = _metadata_text(result, "path", ".")
        changed += _append_unique(
            blocks,
            "task/explored_files",
            f"searched {path} for {query!r}",
            step,
        )
        hits = _extract_search_hits(result.output)
        if hits:
            changed += _append_unique(
                blocks,
                "task/relevant_symbols",
                "search hits: " + ", ".join(hits[:10]),
                step,
            )

    if result.tool_name in {"edit_file", "write_file"} and result.ok:
        path = _metadata_text(result, "path", "<unknown>")
        if result.metadata.get("changed") is True or result.metadata.get("created") is True:
            action = "edited" if result.tool_name == "edit_file" else "wrote"
            changed += _append_unique(
                blocks,
                "task/patch_summary",
                f"{action} {path}: {result.output.strip()}",
                step,
            )

    if result.tool_name == "run_tests":
        command = _metadata_text(result, "cmd", "run_tests")
        if result.ok:
            changed += _append_unique(
                blocks,
                "task/verified_facts",
                f"tests passed: {command}",
                step,
            )
            changed += _set_block(blocks, "task/failing_tests", "", step)
        else:
            detail = result.error or result.output
            changed += _set_block(
                blocks,
                "task/failing_tests",
                f"{command}: {_clip(detail, 1400)}",
                step,
            )
            changed += _append_unique(
                blocks,
                "task/open_questions",
                f"fix failing tests from {command}",
                step,
            )

    if not result.ok and result.tool_name != "run_tests":
        detail = result.error or result.output
        changed += _append_unique(
            blocks,
            "task/open_questions",
            f"{result.tool_name} failed: {_clip(detail, 600)}",
            step,
        )

    return sorted(set(changed))


def render_working_memory(blocks: dict[str, MemoryBlock]) -> str:
    parts = ["<working_memory>"]
    for label, block in sorted(blocks.items()):
        value = block.value.strip()
        if not value:
            continue
        parts.append(
            f'<block label="{label}" updated_step="{block.updated_step}">\n'
            f"{value}\n"
            "</block>"
        )
    parts.append("</working_memory>")
    return "\n".join(parts)


def _append_unique(
    blocks: dict[str, MemoryBlock],
    label: str,
    item: str,
    step: int,
) -> list[str]:
    block = blocks[label]
    item = " ".join(item.split())
    if not item:
        return []
    items = [line for line in block.value.splitlines() if line.strip()]
    if item in items:
        return []
    return _set_block(blocks, label, "\n".join(items + [item]), step)


def _set_block(
    blocks: dict[str, MemoryBlock],
    label: str,
    value: str,
    step: int,
) -> list[str]:
    block = blocks[label]
    clipped = _clip(value.strip(), block.limit)
    if clipped == block.value:
        return []
    block.value = clipped
    block.updated_step = step
    return [label]


def _metadata_text(result: ToolResult, key: str, default: str) -> str:
    value = result.metadata.get(key)
    return value if isinstance(value, str) and value else default


def _extract_symbols(text: str) -> list[str]:
    symbols: list[str] = []
    patterns = (
        r"\bclass\s+([A-Za-z_][A-Za-z0-9_]*)",
        r"\bdef\s+([A-Za-z_][A-Za-z0-9_]*)",
        r"\bfrom\s+([A-Za-z_][A-Za-z0-9_\.]*)\s+import",
        r"\bimport\s+([A-Za-z_][A-Za-z0-9_\.]*)",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            symbol = match.group(1)
            if symbol not in symbols:
                symbols.append(symbol)
    return symbols


def _extract_search_hits(text: str) -> list[str]:
    hits: list[str] = []
    for line in text.splitlines():
        if ":" not in line:
            continue
        path = line.split(":", 1)[0]
        if path and path not in hits:
            hits.append(path)
    return hits


def _clip(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return f"{value[:limit]}... [truncated {len(value) - limit} chars]"
