from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal

from harnesscoder.core.memory import render_working_memory
from harnesscoder.core.state import AgentState


ContextMode = Literal["none", "pack", "memory"]


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
    context_injected: bool
    estimated_tokens: int
    prompt_fingerprint: dict[str, str]
    prompt_sections: dict[str, int]

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
            "prompt_fingerprint": dict(self.prompt_fingerprint),
            "prompt_sections": dict(self.prompt_sections),
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
) -> ContextAssembly:
    if context_mode not in {"none", "pack", "memory"}:
        raise ValueError(f"unsupported context mode: {context_mode}")

    recent_observations = (
        _recent_observations(state)
        if context_mode == "none"
        else []
    )
    task_contract = {
        "task": state.task,
        "cwd": state.cwd,
        "iterations": state.iterations,
        "max_iterations": state.max_iterations,
        "phase": state.phase,
    }
    packed_context = context_pack if context_mode in {"pack", "memory"} else None
    working_memory = (
        render_working_memory(state.memory_blocks)
        if context_mode == "memory"
        else None
    )
    injected_repo_map = repo_map if context_mode in {"pack", "memory"} else None

    assembly = ContextAssembly(
        mode=context_mode,
        system_instructions=system_instructions,
        task_contract=task_contract,
        available_tools=available_tools,
        recent_observations=recent_observations,
        packed_context=packed_context,
        working_memory=working_memory,
        repo_map=injected_repo_map,
        context_injected=context_mode in {"pack", "memory"},
        estimated_tokens=0,
        prompt_fingerprint={},
        prompt_sections={},
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
        context_injected=assembly.context_injected,
        estimated_tokens=estimated_tokens,
        prompt_fingerprint=prompt_fingerprint,
        prompt_sections=prompt_sections,
    )


def estimate_tokens(value: Any) -> int:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return max(1, (len(text) + 3) // 4)


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
    }
    dynamic_suffix = {
        "recent_observations": assembly.recent_observations,
    }
    context_payload = {
        "task_contract": assembly.task_contract,
        "packed_context": assembly.packed_context,
        "working_memory": assembly.working_memory,
        "repo_map": assembly.repo_map,
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
