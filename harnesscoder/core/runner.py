from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from harnesscoder.core.checkpoint import (
    default_checkpoint_path,
    load_checkpoint,
    save_checkpoint,
)
from harnesscoder.core.context import build_context_pack
from harnesscoder.core.models import ModelAdapter
from harnesscoder.core.policy import PolicyDecision, ToolPolicy
from harnesscoder.core.state import AgentState, ModelAction, ToolObservation
from harnesscoder.core.tools import ToolRegistry, ToolResult
from harnesscoder.core.trace import TraceWriter


@dataclass(slots=True)
class RunResult:
    run_id: str
    status: str
    final_answer: str
    trace_path: Path


class AgentRunner:
    def __init__(
        self,
        model: ModelAdapter,
        cwd: Path,
        trace_root: Path,
        max_iterations: int = 8,
        policy: ToolPolicy | None = None,
        tools: ToolRegistry | None = None,
    ) -> None:
        self.model = model
        self.cwd = cwd.resolve()
        self.trace_root = trace_root
        self.max_iterations = max_iterations
        self.policy = policy or ToolPolicy()
        self.tools = tools or ToolRegistry(self.cwd)

    def run(self, task: str) -> RunResult:
        run_id = self._new_run_id()
        trace = TraceWriter(run_id=run_id, trace_root=self.trace_root, cwd=self.cwd)
        state = AgentState(
            run_id=run_id,
            task=task,
            cwd=str(self.cwd),
            max_iterations=self.max_iterations,
        )
        state.messages.append({"role": "user", "content": task})

        trace.emit(
            "run_started",
            task=task,
            cwd=str(self.cwd),
            model=getattr(self.model, "name", type(self.model).__name__),
            max_iterations=self.max_iterations,
        )

        return self._run_loop(state, trace)

    def resume_from_checkpoint(self, checkpoint_path: str | Path) -> RunResult:
        checkpoint = load_checkpoint(Path(checkpoint_path))
        state = checkpoint.state
        checkpoint_cwd = Path(state.cwd).resolve()
        if checkpoint_cwd != self.cwd:
            raise ValueError(
                "checkpoint cwd does not match runner cwd: "
                f"{checkpoint_cwd} != {self.cwd}"
            )

        trace = TraceWriter.resume(
            run_id=state.run_id,
            trace_path=checkpoint.trace_path,
            cwd=self.cwd,
        )
        trace.emit(
            "run_resumed",
            checkpoint_path=str(Path(checkpoint_path).resolve()),
            trace_path=str(trace.trace_path),
            state=state.snapshot(),
        )
        return self._run_loop(state, trace)

    def _run_loop(self, state: AgentState, trace: TraceWriter) -> RunResult:
        if state.done:
            status = "success" if state.phase == "done" else "failed"
            answer = state.final_answer or ""
            trace.emit("run_finished", status=status, final_answer=answer)
            return RunResult(state.run_id, status, answer, trace.trace_path)

        status = "success"
        while not state.done and state.iterations < state.max_iterations:
            context_pack = build_context_pack(state)
            trace.emit(
                "context_packed",
                reason="model_step",
                source_event_index=state.iterations,
                input_message_count=len(state.messages),
                kept_message_count=min(len(state.messages), 6),
                dropped_message_count=max(0, len(state.messages) - 6),
                summary=context_pack["cold_trace_summary"],
                packed_context=context_pack,
                context_pack=context_pack,
                **context_pack,
            )

            try:
                action = self.model.next_action(state)
            except Exception as exc:
                status = "model_error"
                answer = f"Model adapter failed: {type(exc).__name__}: {exc}"
                state.last_error = answer
                trace.emit(
                    "model_error",
                    error_type=type(exc).__name__,
                    error=str(exc),
                    state=state.snapshot(),
                )
                state.finish(answer, failed=True)
                self._emit_state_updated(trace, state)
                trace.emit("run_finished", status=status, final_answer=answer)
                return RunResult(state.run_id, status, answer, trace.trace_path)

            state.append_action(action)
            trace.emit("model_action", action=action.to_record())

            if action.kind == "finish":
                answer = action.content or ""
                state.finish(answer)
                self._emit_state_updated(trace, state)
                trace.emit("run_finished", status=status, final_answer=answer)
                return RunResult(state.run_id, status, answer, trace.trace_path)

            decision = self.policy.check(action.tool_name, action.tool_args, self.cwd)
            trace.emit(
                "policy_decision",
                call_id=action.call_id,
                tool_name=action.tool_name,
                decision=decision.to_record(),
            )

            result = self._execute_or_deny(action, decision)
            self._attach_tool_metadata(state, action, result)
            observation = ToolObservation(
                call_id=result.call_id,
                tool_name=result.tool_name,
                ok=result.ok,
                output=result.output,
                error=result.error,
                metadata=result.metadata,
            )
            before_governance = state.governance_snapshot(include_budget=False)
            state.append_observation(observation)
            result.metadata["changed_state"] = (
                state.governance_snapshot(include_budget=False) != before_governance
            )
            trace.emit("tool_result", result=result.to_record())
            if result.tool_name == "run_tests":
                trace.emit(
                    "test_result",
                    call_id=result.call_id,
                    command=result.metadata.get("cmd"),
                    passed=result.ok,
                    ok=result.ok,
                    returncode=result.metadata.get("returncode"),
                    timed_out=result.metadata.get("timed_out", False),
                    duration_seconds=result.metadata.get("duration_seconds"),
                    output_excerpt=result.output,
                    stdout_excerpt=result.output,
                    stderr_excerpt=result.error or "",
                    error=result.error,
                    failure_category=self._classify_test_result(result),
                    metadata=dict(result.metadata),
                )

            self._emit_state_updated(trace, state)

        status = "max_iterations"
        answer = f"Stopped after {state.max_iterations} iterations without a final answer."
        state.last_error = answer
        state.finish(answer, failed=True)
        self._emit_state_updated(trace, state)
        trace.emit("run_finished", status=status, final_answer=answer)
        return RunResult(state.run_id, status, answer, trace.trace_path)

    def _execute_or_deny(
        self,
        action: ModelAction,
        decision: PolicyDecision,
    ) -> ToolResult:
        tool_name = action.tool_name or "<missing>"
        if not decision.allowed:
            return ToolResult(
                call_id=action.call_id,
                tool_name=tool_name,
                ok=False,
                output="",
                error=f"policy denied tool call: {decision.reason}",
            )
        return self.tools.execute(
            call_id=action.call_id,
            tool_name=tool_name,
            tool_args=action.tool_args,
        )

    def _attach_tool_metadata(
        self,
        state: AgentState,
        action: ModelAction,
        result: ToolResult,
    ) -> None:
        result.metadata = dict(result.metadata)
        result.metadata["repeated"] = self._is_repeated_tool_call(state, action)
        result.metadata["changed_state"] = False

    def _is_repeated_tool_call(self, state: AgentState, action: ModelAction) -> bool:
        for previous in state.actions[:-1]:
            if previous.get("kind") != "tool":
                continue
            if previous.get("tool_name") != action.tool_name:
                continue
            if previous.get("tool_args") == action.tool_args:
                return True
        return False

    def _emit_state_updated(self, trace: TraceWriter, state: AgentState) -> None:
        trace.emit("state_updated", state=state.snapshot())
        checkpoint_path = default_checkpoint_path(trace.trace_path)
        save_checkpoint(
            checkpoint_path,
            state=state,
            trace_path=trace.trace_path,
        )
        trace.emit(
            "checkpoint_created",
            checkpoint_path=str(checkpoint_path),
            state=state.snapshot(),
        )

    def _classify_test_result(self, result: ToolResult) -> str | None:
        if result.ok:
            return None
        detail = result.error or result.output
        if "policy denied" in detail:
            return "policy_denied"
        if "command not found" in detail or "timed out" in detail:
            return "environment_error"
        return "test_failed"

    def _new_run_id(self) -> str:
        return f"run_{uuid4().hex[:12]}"
