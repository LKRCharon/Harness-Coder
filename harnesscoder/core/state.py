from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import uuid4


ActionKind = Literal["tool", "finish"]


@dataclass(slots=True)
class ModelAction:
    """A model decision emitted for one agent-loop step."""

    kind: ActionKind
    rationale: str
    tool_name: str | None = None
    tool_args: dict[str, Any] = field(default_factory=dict)
    content: str | None = None
    call_id: str = field(default_factory=lambda: f"call_{uuid4().hex[:12]}")

    def to_record(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "rationale": self.rationale,
            "tool_name": self.tool_name,
            "tool_args": self.tool_args,
            "content": self.content,
            "call_id": self.call_id,
        }


@dataclass(slots=True)
class ToolObservation:
    """A tool result as appended back into agent state."""

    call_id: str
    tool_name: str
    ok: bool
    output: str
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def short_output(self, limit: int = 800) -> str:
        if len(self.output) <= limit:
            return self.output
        return f"{self.output[:limit]}... [truncated {len(self.output) - limit} chars]"

    def to_record(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "tool_name": self.tool_name,
            "ok": self.ok,
            "output": self.output,
            "error": self.error,
            "metadata": self.metadata,
        }


@dataclass(slots=True)
class AgentState:
    """Mutable runtime state reconstructed from traceable events."""

    run_id: str
    task: str
    cwd: str
    max_iterations: int
    iterations: int = 0
    done: bool = False
    final_answer: str | None = None
    actions: list[dict[str, Any]] = field(default_factory=list)
    observations: list[ToolObservation] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)

    def append_action(self, action: ModelAction) -> None:
        self.actions.append(action.to_record())
        if action.kind == "tool":
            self.messages.append(
                {
                    "role": "assistant",
                    "type": "tool_call",
                    "tool_name": action.tool_name,
                    "tool_args": action.tool_args,
                    "call_id": action.call_id,
                    "rationale": action.rationale,
                }
            )

    def append_observation(self, observation: ToolObservation) -> None:
        self.iterations += 1
        self.observations.append(observation)
        self.messages.append(
            {
                "role": "tool",
                "tool_name": observation.tool_name,
                "call_id": observation.call_id,
                "ok": observation.ok,
                "content": observation.short_output(),
                "error": observation.error,
            }
        )

    def finish(self, answer: str) -> None:
        self.done = True
        self.final_answer = answer
        self.messages.append({"role": "assistant", "type": "final", "content": answer})

    def latest_observation_for(self, tool_name: str) -> ToolObservation | None:
        for observation in reversed(self.observations):
            if observation.tool_name == tool_name:
                return observation
        return None

    def snapshot(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "task": self.task,
            "cwd": self.cwd,
            "iterations": self.iterations,
            "max_iterations": self.max_iterations,
            "done": self.done,
            "final_answer": self.final_answer,
            "action_count": len(self.actions),
            "observation_count": len(self.observations),
            "last_observation": (
                self.observations[-1].to_record() if self.observations else None
            ),
        }

