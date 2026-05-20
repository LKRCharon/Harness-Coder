from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal

from harnesscoder.core.memory import render_working_memory
from harnesscoder.core.state import AgentState


ContextMode = Literal["none", "pack", "memory"]
CONTEXT_BUDGET_VERSION = 2
CONTEXT_SECTION_BUDGETS = {
    "system": 12000,
    "task_contract": 2400,
    "available_tools": 3600,
    "packed_context": 16000,
    "working_memory": 4800,
    "repo_map": 8000,
    "session_context": 4200,
    "recent_observations": 12000,
}
PRESERVED_CONTEXT_SECTIONS = {"task_contract"}


@dataclass(frozen=True, slots=True)
class ContextAssembly:
    mode: ContextMode
    system_instructions: str
    task_contract: dict[str, Any]
    available_tools: list[str]
    recent_observations: list[dict[str, Any]]
    packed_context: dict[str, Any] | None
    working_memory: str | None
    repo_map: str | None
    session_context: dict[str, Any] | None
    context_injected: bool
    estimated_tokens: int
    prompt_fingerprint: dict[str, str]
    prompt_sections: dict[str, int]
    context_budget: dict[str, Any]

    def to_model_input(self) -> list[dict[str, str]]:
        payload = {
            "task_contract": self.task_contract,
            "available_tools": self.available_tools,
            "recent_observations": self.recent_observations,
        }
        if self.packed_context is not None:
            payload["packed_context"] = self.packed_context
        if self.working_memory is not None:
            payload["working_memory"] = self.working_memory
        if self.repo_map is not None:
            payload["repo_map"] = self.repo_map
        if self.session_context is not None:
            payload["session_context"] = self.session_context
        return [
            {"role": "system", "content": self.system_instructions},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]

    def to_trace_record(self) -> dict[str, Any]:
        return {
            "context_mode": self.mode,
            "context_injected": self.context_injected,
            "estimated_tokens": self.estimated_tokens,
            "task_contract": self.task_contract,
            "available_tools": list(self.available_tools),
            "recent_observation_count": len(self.recent_observations),
            "working_memory_injected": self.working_memory is not None,
            "repo_map_injected": self.repo_map is not None,
            "session_context_injected": self.session_context is not None,
            "session_id": (
                self.session_context.get("session_id")
                if isinstance(self.session_context, dict)
                else None
            ),
            "prompt_fingerprint": dict(self.prompt_fingerprint),
            "prompt_sections": dict(self.prompt_sections),
            "context_budget": dict(self.context_budget),
            "context_budget_sections": dict(self.context_budget.get("sections", {})),
            "context_reduced_sections": list(
                self.context_budget.get("reduced_sections", [])
            ),
            "context_dropped_blocks": self.context_budget.get("dropped_blocks", 0),
            "context_budget_total_chars": self.context_budget.get("total_chars", 0),
            "context_budget_total_budget": self.context_budget.get("total_budget", 0),
            "stable_prefix_tokens": self.prompt_sections["stable_prefix_tokens"],
            "semi_stable_tokens": self.prompt_sections["semi_stable_tokens"],
            "dynamic_suffix_tokens": self.prompt_sections["dynamic_suffix_tokens"],
        }


def assemble_context(
    *,
    state: AgentState,
    system_instructions: str,
    available_tools: list[str],
    context_pack: dict[str, Any],
    context_mode: ContextMode,
    repo_map: str | None = None,
    session_context: dict[str, Any] | None = None,
) -> ContextAssembly:
    if context_mode not in {"none", "pack", "memory"}:
        raise ValueError(f"unsupported context mode: {context_mode}")

    raw_recent_observations = (
        _recent_observations(state) if context_mode == "none" else []
    )
    raw_task_contract = {
        "task": state.task,
        "cwd": state.cwd,
        "iterations": state.iterations,
        "max_iterations": state.max_iterations,
        "phase": state.phase,
    }
    raw_packed_context = context_pack if context_mode in {"pack", "memory"} else None
    raw_working_memory = (
        render_working_memory(state.memory_blocks)
        if context_mode == "memory"
        else None
    )
    raw_repo_map = repo_map if context_mode in {"pack", "memory"} else None

    sections, context_budget = apply_context_budget(
        {
            "system": system_instructions,
            "task_contract": raw_task_contract,
            "available_tools": available_tools,
            "packed_context": raw_packed_context,
            "working_memory": raw_working_memory,
            "repo_map": raw_repo_map,
            "session_context": session_context,
            "recent_observations": raw_recent_observations,
        }
    )

    assembly = ContextAssembly(
        mode=context_mode,
        system_instructions=str(sections["system"]),
        task_contract=dict(sections["task_contract"]),
        available_tools=list(sections["available_tools"]),
        recent_observations=list(sections["recent_observations"]),
        packed_context=_optional_dict(sections["packed_context"]),
        working_memory=_optional_str(sections["working_memory"]),
        repo_map=_optional_str(sections["repo_map"]),
        session_context=_optional_dict(sections["session_context"]),
        context_injected=context_mode in {"pack", "memory"},
        estimated_tokens=0,
        prompt_fingerprint={},
        prompt_sections={},
        context_budget=context_budget,
    )
    estimated_tokens = estimate_tokens(assembly.to_model_input())
    prompt_fingerprint, prompt_sections = prompt_cache_governance(assembly)
    return ContextAssembly(
        mode=assembly.mode,
        system_instructions=assembly.system_instructions,
        task_contract=assembly.task_contract,
        available_tools=assembly.available_tools,
        recent_observations=assembly.recent_observations,
        packed_context=assembly.packed_context,
        working_memory=assembly.working_memory,
        repo_map=assembly.repo_map,
        session_context=assembly.session_context,
        context_injected=assembly.context_injected,
        estimated_tokens=estimated_tokens,
        prompt_fingerprint=prompt_fingerprint,
        prompt_sections=prompt_sections,
        context_budget=context_budget,
    )


def estimate_tokens(value: Any) -> int:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return max(1, (len(text) + 3) // 4)


def apply_context_budget(
    sections: dict[str, Any],
    budgets: dict[str, int] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    budgets = dict(budgets or CONTEXT_SECTION_BUDGETS)
    budgeted: dict[str, Any] = {}
    section_records: dict[str, dict[str, Any]] = {}
    reduced_sections: list[str] = []
    dropped_blocks = 0

    for name, value in sections.items():
        budget = int(budgets.get(name, 0))
        preserved = name in PRESERVED_CONTEXT_SECTIONS
        reduced_value, record = _budget_section(
            name=name,
            value=value,
            budget=budget,
            preserved=preserved,
        )
        budgeted[name] = reduced_value
        section_records[name] = record
        if record["reduced"]:
            reduced_sections.append(name)
        dropped_blocks += int(record["dropped_blocks"])

    report = {
        "version": CONTEXT_BUDGET_VERSION,
        "sections": section_records,
        "reduced_sections": reduced_sections,
        "dropped_blocks": dropped_blocks,
        "total_chars": sum(int(record["chars"]) for record in section_records.values()),
        "total_raw_chars": sum(
            int(record["raw_chars"]) for record in section_records.values()
        ),
        "total_budget": sum(int(record["budget"]) for record in section_records.values()),
        "preserved_sections": sorted(PRESERVED_CONTEXT_SECTIONS),
        "reduction_order": [
            "recent_observations",
            "packed_context",
            "session_context",
            "repo_map",
            "working_memory",
            "available_tools",
            "system",
        ],
    }
    return budgeted, report


def _budget_section(
    *,
    name: str,
    value: Any,
    budget: int,
    preserved: bool,
) -> tuple[Any, dict[str, Any]]:
    raw_chars = _section_chars(value)
    if value is None or preserved or budget <= 0 or raw_chars <= budget:
        chars = _section_chars(value)
        return value, _section_record(
            raw_chars=raw_chars,
            chars=chars,
            budget=budget,
            preserved=preserved,
            reduced=False,
            dropped_blocks=0,
        )

    if isinstance(value, str):
        reduced_value = _clip_text(value, budget)
        dropped = 0
    elif name == "recent_observations" and isinstance(value, list):
        reduced_value, dropped = _reduce_list_section(value, budget)
    elif name == "packed_context" and isinstance(value, dict):
        reduced_value, dropped = _reduce_structured_section(
            value,
            budget,
            list_paths=[
                ("hot_context", "recent_observations"),
                ("hot_context", "recent_actions"),
                ("cold_trace_summary", "recent_older_errors"),
            ],
        )
    elif name == "session_context" and isinstance(value, dict):
        reduced_value, dropped = _reduce_structured_section(
            value,
            budget,
            list_paths=[("recent_turns",)],
        )
    else:
        reduced_value, dropped = _reduce_structured_section(value, budget, list_paths=[])

    chars = _section_chars(reduced_value)
    return reduced_value, _section_record(
        raw_chars=raw_chars,
        chars=chars,
        budget=budget,
        preserved=preserved,
        reduced=True,
        dropped_blocks=dropped,
    )


def _section_record(
    *,
    raw_chars: int,
    chars: int,
    budget: int,
    preserved: bool,
    reduced: bool,
    dropped_blocks: int,
) -> dict[str, Any]:
    return {
        "raw_chars": raw_chars,
        "chars": chars,
        "budget": budget,
        "preserved": preserved,
        "reduced": reduced,
        "dropped_blocks": dropped_blocks,
    }


def _reduce_list_section(value: list[Any], budget: int) -> tuple[list[Any], int]:
    reduced = [_clip_strings(item, 900) for item in value]
    dropped = 0
    while len(reduced) > 1 and _section_chars(reduced) > budget:
        reduced.pop(0)
        dropped += 1
    if _section_chars(reduced) > budget:
        return [_json_summary(reduced, budget)], dropped + 1
    return reduced, dropped


def _reduce_structured_section(
    value: Any,
    budget: int,
    *,
    list_paths: list[tuple[str, ...]],
) -> tuple[Any, int]:
    reduced = _clip_strings(_json_copy(value), 900)
    dropped = 0
    for path in list_paths:
        items = _nested_list(reduced, path)
        while items is not None and len(items) > 1 and _section_chars(reduced) > budget:
            items.pop(0)
            dropped += 1
    if _section_chars(reduced) <= budget:
        return reduced, dropped
    reduced = _clip_strings(reduced, 360)
    if _section_chars(reduced) <= budget:
        return reduced, dropped
    return _json_summary(reduced, budget), dropped + 1


def _clip_strings(value: Any, limit: int) -> Any:
    if isinstance(value, str):
        return _clip_text(value, limit)
    if isinstance(value, list):
        return [_clip_strings(item, limit) for item in value]
    if isinstance(value, dict):
        return {key: _clip_strings(item, limit) for key, item in value.items()}
    return value


def _json_summary(value: Any, budget: int) -> dict[str, Any]:
    return {
        "truncated": True,
        "summary": _clip_text(
            json.dumps(value, ensure_ascii=False, sort_keys=True),
            max(64, budget - 128),
        ),
    }


def _nested_list(value: Any, path: tuple[str, ...]) -> list[Any] | None:
    cursor = value
    for key in path:
        if not isinstance(cursor, dict):
            return None
        cursor = cursor.get(key)
    return cursor if isinstance(cursor, list) else None


def _section_chars(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        return len(value)
    return len(json.dumps(value, ensure_ascii=False, sort_keys=True))


def _clip_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    suffix = f"... [truncated {len(text) - limit} chars]"
    keep = max(0, limit - len(suffix))
    return text[:keep] + suffix


def _json_copy(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _optional_dict(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    return dict(value) if isinstance(value, dict) else _json_summary(value, 1200)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def prompt_cache_governance(
    assembly: ContextAssembly,
) -> tuple[dict[str, str], dict[str, int]]:
    stable_prefix = {
        "system_instructions": assembly.system_instructions,
        "available_tools": list(assembly.available_tools),
    }
    semi_stable = {
        "task_contract": assembly.task_contract,
        "packed_context": assembly.packed_context,
        "working_memory": assembly.working_memory,
        "repo_map": assembly.repo_map,
        "session_context": assembly.session_context,
    }
    dynamic_suffix = {
        "recent_observations": assembly.recent_observations,
    }
    context_payload = {
        "task_contract": assembly.task_contract,
        "packed_context": assembly.packed_context,
        "working_memory": assembly.working_memory,
        "repo_map": assembly.repo_map,
        "session_context": assembly.session_context,
        "recent_observations": assembly.recent_observations,
    }
    fingerprint = {
        "system_hash": _stable_hash(assembly.system_instructions),
        "tool_schema_hash": _stable_hash(list(assembly.available_tools)),
        "task_contract_hash": _stable_hash(assembly.task_contract),
        "context_payload_hash": _stable_hash(context_payload),
        "stable_prefix_hash": _stable_hash(stable_prefix),
        "dynamic_suffix_hash": _stable_hash(dynamic_suffix),
    }
    sections = {
        "stable_prefix_tokens": estimate_tokens(stable_prefix),
        "semi_stable_tokens": estimate_tokens(semi_stable),
        "dynamic_suffix_tokens": estimate_tokens(dynamic_suffix),
    }
    return fingerprint, sections


def _stable_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _recent_observations(state: AgentState) -> list[dict[str, Any]]:
    return [
        {
            "tool_name": observation.tool_name,
            "ok": observation.ok,
            "output": observation.short_output(4000),
            "error": observation.error,
            "metadata": observation.metadata,
        }
        for observation in state.observations[-8:]
    ]
