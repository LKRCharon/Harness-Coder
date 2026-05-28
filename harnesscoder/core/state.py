from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import uuid4

from harnesscoder.core.memory import (
    MemoryBlock,
    default_memory_blocks,
    memory_blocks_from_records,
    memory_blocks_to_records,
)


ActionKind = Literal["tool", "finish"]
Phase = Literal["init", "explore", "edit", "verify", "done", "failed"]


@dataclass(slots=True)
class PlanStep:
    step_id: str
    title: str
    status: str = "pending"
    details: str | None = None

    def to_record(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "title": self.title,
            "status": self.status,
            "details": self.details,
        }

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> "PlanStep":
        return cls(
            step_id=str(record.get("step_id") or ""),
            title=str(record.get("title") or ""),
            status=str(record.get("status") or "pending"),
            details=(
                str(record["details"]) if record.get("details") is not None else None
            ),
        )


@dataclass(slots=True)
class AgentPlan:
    steps: list[PlanStep] = field(default_factory=list)
    revision: int = 0
    last_reflection: str | None = None

    def to_record(self) -> dict[str, Any]:
        return {
            "steps": [step.to_record() for step in self.steps],
            "revision": self.revision,
            "last_reflection": self.last_reflection,
        }

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> "AgentPlan":
        steps = [
            PlanStep.from_record(item)
            for item in record.get("steps", [])
            if isinstance(item, dict)
        ]
        return cls(
            steps=steps,
            revision=int(record.get("revision", 0)),
            last_reflection=(
                str(record["last_reflection"])
                if record.get("last_reflection") is not None
                else None
            ),
        )


@dataclass(slots=True)
class ModelAction:
    """A model decision emitted for one agent-loop step."""

    kind: ActionKind
    rationale: str
    tool_name: str | None = None
    tool_args: dict[str, Any] = field(default_factory=dict)
    content: str | None = None
    thought_summary: str | None = None
    current_step_id: str | None = None
    expected_observation: str | None = None
    reflection: str | None = None
    plan_update: dict[str, Any] | None = None
    call_id: str = field(default_factory=lambda: f"call_{uuid4().hex[:12]}")

    def to_record(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "rationale": self.rationale,
            "tool_name": self.tool_name,
            "tool_args": self.tool_args,
            "content": self.content,
            "thought_summary": self.thought_summary,
            "current_step_id": self.current_step_id,
            "expected_observation": self.expected_observation,
            "reflection": self.reflection,
            "plan_update": self.plan_update,
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
    modified_files: list[str] = field(default_factory=list)
    actions: list[dict[str, Any]] = field(default_factory=list)
    observations: list[ToolObservation] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)
    phase: Phase = "init"
    file_summaries: dict[str, str] = field(default_factory=dict)
    last_error: str | None = None
    open_questions: list[str] = field(default_factory=list)
    budget: dict[str, Any] = field(default_factory=dict)
    memory_blocks: dict[str, MemoryBlock] = field(default_factory=default_memory_blocks)
    session_context: dict[str, Any] | None = None
    plan: AgentPlan = field(default_factory=AgentPlan)

    def __post_init__(self) -> None:
        self.current_open_questions()
        self.refresh_budget()

    def current_open_questions(self) -> list[str]:
        block = self.memory_blocks.get("task/open_questions")
        block_questions = _normalize_open_questions(
            block.value.splitlines() if block is not None else []
        )
        if block_questions:
            self.open_questions = list(block_questions)
            return list(block_questions)

        legacy_questions = _normalize_open_questions(self.open_questions)
        if block is not None and legacy_questions and not block.value.strip():
            block.value = "\n".join(legacy_questions)
        self.open_questions = list(legacy_questions)
        return list(legacy_questions)

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
        self._record_modified_file(observation)
        self._apply_observation_governance(observation)
        self.refresh_budget()
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

    def finish(self, answer: str, failed: bool = False) -> None:
        self.done = True
        self.final_answer = answer
        self.phase = "failed" if failed else "done"
        if failed and not self.last_error:
            self.last_error = answer
        self.refresh_budget()
        self.messages.append({"role": "assistant", "type": "final", "content": answer})

    def latest_observation_for(self, tool_name: str) -> ToolObservation | None:
        for observation in reversed(self.observations):
            if observation.tool_name == tool_name:
                return observation
        return None

    def snapshot(self) -> dict[str, Any]:
        self.refresh_budget()
        open_questions = self.current_open_questions()
        return {
            "run_id": self.run_id,
            "task": self.task,
            "cwd": self.cwd,
            "iterations": self.iterations,
            "max_iterations": self.max_iterations,
            "done": self.done,
            "final_answer": self.final_answer,
            "phase": self.phase,
            "file_summaries": dict(self.file_summaries),
            "last_error": self.last_error,
            "open_questions": open_questions,
            "budget": dict(self.budget),
            "memory_blocks": memory_blocks_to_records(self.memory_blocks),
            "session_context": (
                dict(self.session_context)
                if isinstance(self.session_context, dict)
                else None
            ),
            "plan": self.plan.to_record(),
            "modified_files": list(self.modified_files),
            "action_count": len(self.actions),
            "observation_count": len(self.observations),
            "last_observation": (
                self.observations[-1].to_record() if self.observations else None
            ),
        }

    def to_record(self) -> dict[str, Any]:
        self.refresh_budget()
        open_questions = self.current_open_questions()
        return {
            "run_id": self.run_id,
            "task": self.task,
            "cwd": self.cwd,
            "max_iterations": self.max_iterations,
            "iterations": self.iterations,
            "done": self.done,
            "final_answer": self.final_answer,
            "modified_files": list(self.modified_files),
            "actions": list(self.actions),
            "observations": [
                observation.to_record() for observation in self.observations
            ],
            "messages": list(self.messages),
            "phase": self.phase,
            "file_summaries": dict(self.file_summaries),
            "last_error": self.last_error,
            "open_questions": open_questions,
            "budget": dict(self.budget),
            "memory_blocks": memory_blocks_to_records(self.memory_blocks),
            "session_context": (
                dict(self.session_context)
                if isinstance(self.session_context, dict)
                else None
            ),
            "plan": self.plan.to_record(),
        }

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> "AgentState":
        observations = [
            ToolObservation(
                call_id=str(raw.get("call_id", "")),
                tool_name=str(raw.get("tool_name", "")),
                ok=bool(raw.get("ok")),
                output=str(raw.get("output", "")),
                error=(
                    str(raw["error"])
                    if raw.get("error") is not None
                    else None
                ),
                metadata=(
                    dict(raw.get("metadata", {}))
                    if isinstance(raw.get("metadata"), dict)
                    else {}
                ),
            )
            for raw in record.get("observations", [])
            if isinstance(raw, dict)
        ]
        phase = record.get("phase", "init")
        if phase not in {"init", "explore", "edit", "verify", "done", "failed"}:
            phase = "init"

        state = cls(
            run_id=str(record["run_id"]),
            task=str(record.get("task", "")),
            cwd=str(record.get("cwd", "")),
            max_iterations=int(record.get("max_iterations", 0)),
            iterations=int(record.get("iterations", 0)),
            done=bool(record.get("done", False)),
            final_answer=(
                str(record["final_answer"])
                if record.get("final_answer") is not None
                else None
            ),
            modified_files=[
                str(path) for path in record.get("modified_files", [])
            ],
            actions=[
                dict(action)
                for action in record.get("actions", [])
                if isinstance(action, dict)
            ],
            observations=observations,
            messages=[
                dict(message)
                for message in record.get("messages", [])
                if isinstance(message, dict)
            ],
            phase=phase,
            file_summaries=(
                {
                    str(path): str(summary)
                    for path, summary in record.get("file_summaries", {}).items()
                }
                if isinstance(record.get("file_summaries"), dict)
                else {}
            ),
            last_error=(
                str(record["last_error"])
                if record.get("last_error") is not None
                else None
            ),
            open_questions=[
                str(question) for question in record.get("open_questions", [])
            ],
            budget=(
                dict(record.get("budget", {}))
                if isinstance(record.get("budget"), dict)
                else {}
            ),
            memory_blocks=memory_blocks_from_records(record.get("memory_blocks")),
            session_context=(
                dict(record.get("session_context"))
                if isinstance(record.get("session_context"), dict)
                else None
            ),
            plan=(
                AgentPlan.from_record(record.get("plan", {}))
                if isinstance(record.get("plan"), dict)
                else AgentPlan()
            ),
        )
        state.refresh_budget()
        return state

    def refresh_budget(self) -> None:
        self.budget["max_iterations"] = self.max_iterations
        self.budget["iterations_used"] = self.iterations
        self.budget["remaining_iterations"] = max(
            0,
            self.max_iterations - self.iterations,
        )

    def governance_snapshot(self, include_budget: bool = True) -> dict[str, Any]:
        self.refresh_budget()
        open_questions = self.current_open_questions()
        snapshot = {
            "phase": self.phase,
            "file_summaries": dict(self.file_summaries),
            "last_error": self.last_error,
            "open_questions": open_questions,
            "modified_files": list(self.modified_files),
            "memory_blocks": memory_blocks_to_records(self.memory_blocks),
            "done": self.done,
            "final_answer": self.final_answer,
        }
        if include_budget:
            snapshot["budget"] = dict(self.budget)
        return snapshot

    def _record_modified_file(self, observation: ToolObservation) -> None:
        if observation.tool_name not in {"edit_file", "write_file"} or not observation.ok:
            return
        if observation.metadata.get("changed") is not True:
            return
        path = observation.metadata.get("path")
        if isinstance(path, str) and path not in self.modified_files:
            self.modified_files.append(path)

    def _apply_observation_governance(self, observation: ToolObservation) -> None:
        if not observation.ok:
            self.last_error = _format_observation_error(observation)

        if observation.tool_name in {"read_file", "search_code"}:
            self.phase = "explore"
        elif (
            observation.tool_name in {"edit_file", "write_file"}
            and observation.metadata.get("changed") is True
        ):
            self.phase = "edit"
        elif observation.tool_name == "run_tests":
            self.phase = "verify"
        elif observation.tool_name == "finish":
            self.phase = "done" if observation.ok else "failed"

        if observation.tool_name == "read_file" and observation.ok:
            path = observation.metadata.get("path")
            if isinstance(path, str):
                self.file_summaries[path] = _summarize_read_observation(observation)

        if (
            observation.tool_name in {"edit_file", "write_file"}
            and observation.ok
            and observation.metadata.get("changed") is True
        ):
            path = observation.metadata.get("path")
            if isinstance(path, str):
                stale_summary = self.file_summaries.get(path)
                if stale_summary is not None and not stale_summary.startswith("STALE:"):
                    self.file_summaries[path] = f"STALE after edit: {stale_summary}"


def _format_observation_error(observation: ToolObservation) -> str:
    detail = observation.error or observation.short_output(300)
    return f"{observation.tool_name} failed: {detail}"


def _summarize_read_observation(observation: ToolObservation) -> str:
    path = observation.metadata.get("path", "<unknown>")
    offset = observation.metadata.get("offset")
    total_lines = observation.metadata.get("total_lines")
    lines = [_strip_number_prefix(line).strip() for line in observation.output.splitlines()]
    content_lines = [line for line in lines if line]
    preview = " ".join(content_lines)
    preview = " ".join(preview.split())
    if len(preview) > 240:
        preview = f"{preview[:240]}... [truncated {len(preview) - 240} chars]"
    if not preview:
        preview = "empty or whitespace-only range"

    line_prefix = ""
    if isinstance(offset, int) and isinstance(total_lines, int):
        start_line = offset + 1
        end_line = min(total_lines, offset + len(lines))
        line_prefix = f"lines {start_line}-{end_line} of {total_lines}: "
    return f"{path}: {line_prefix}{preview}"


def _strip_number_prefix(line: str) -> str:
    if "|" not in line:
        return line
    prefix, content = line.split("|", 1)
    return content if prefix.strip().isdigit() else line


def _normalize_open_questions(questions: list[str] | tuple[str, ...]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for question in questions:
        item = " ".join(str(question).split())
        if not item or item in seen:
            continue
        seen.add(item)
        normalized.append(item)
    return normalized
