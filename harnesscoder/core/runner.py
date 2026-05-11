from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

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

        status = "success"
        while not state.done and state.iterations < state.max_iterations:
            try:
                action = self.model.next_action(state)
            except Exception as exc:
                status = "model_error"
                answer = f"Model adapter failed: {type(exc).__name__}: {exc}"
                trace.emit(
                    "model_error",
                    error_type=type(exc).__name__,
                    error=str(exc),
                    state=state.snapshot(),
                )
                state.finish(answer)
                trace.emit("state_updated", state=state.snapshot())
                trace.emit("run_finished", status=status, final_answer=answer)
                return RunResult(run_id, status, answer, trace.trace_path)

            state.append_action(action)
            trace.emit("model_action", action=action.to_record())

            if action.kind == "finish":
                answer = action.content or ""
                state.finish(answer)
                trace.emit("state_updated", state=state.snapshot())
                trace.emit("run_finished", status=status, final_answer=answer)
                return RunResult(run_id, status, answer, trace.trace_path)

            decision = self.policy.check(action.tool_name, action.tool_args, self.cwd)
            trace.emit(
                "policy_decision",
                call_id=action.call_id,
                tool_name=action.tool_name,
                decision=decision.to_record(),
            )

            result = self._execute_or_deny(action, decision)
            trace.emit("tool_result", result=result.to_record())

            state.append_observation(
                ToolObservation(
                    call_id=result.call_id,
                    tool_name=result.tool_name,
                    ok=result.ok,
                    output=result.output,
                    error=result.error,
                    metadata=result.metadata,
                )
            )
            trace.emit("state_updated", state=state.snapshot())

        status = "max_iterations"
        answer = f"Stopped after {state.max_iterations} iterations without a final answer."
        state.finish(answer)
        trace.emit("state_updated", state=state.snapshot())
        trace.emit("run_finished", status=status, final_answer=answer)
        return RunResult(run_id, status, answer, trace.trace_path)

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

    def _new_run_id(self) -> str:
        return f"run_{uuid4().hex[:12]}"
