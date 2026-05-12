from __future__ import annotations

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
    context_injected: bool
    estimated_tokens: int

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
        }


def assemble_context(
    *,
    state: AgentState,
    system_instructions: str,
    available_tools: list[str],
    context_pack: dict[str, Any],
    context_mode: ContextMode,
) -> ContextAssembly:
    if context_mode not in {"none", "pack", "memory"}:
        raise ValueError(f"unsupported context mode: {context_mode}")

    recent_observations = _recent_observations(state)
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

    assembly = ContextAssembly(
        mode=context_mode,
        system_instructions=system_instructions,
        task_contract=task_contract,
        available_tools=available_tools,
        recent_observations=recent_observations,
        packed_context=packed_context,
        working_memory=working_memory,
        context_injected=context_mode in {"pack", "memory"},
        estimated_tokens=0,
    )
    estimated_tokens = estimate_tokens(assembly.to_model_input())
    return ContextAssembly(
        mode=assembly.mode,
        system_instructions=assembly.system_instructions,
        task_contract=assembly.task_contract,
        available_tools=assembly.available_tools,
        recent_observations=assembly.recent_observations,
        packed_context=assembly.packed_context,
        working_memory=assembly.working_memory,
        context_injected=assembly.context_injected,
        estimated_tokens=estimated_tokens,
    )


def estimate_tokens(value: Any) -> int:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return max(1, (len(text) + 3) // 4)


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
