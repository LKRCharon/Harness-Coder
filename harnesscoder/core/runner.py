from __future__ import annotations

import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from harnesscoder.core.artifacts import store_large_observation
from harnesscoder.core.checkpoint import (
    default_checkpoint_path,
    load_checkpoint,
    save_checkpoint,
)
from harnesscoder.core.context import build_context_pack
from harnesscoder.core.memory import apply_memory_reducer, memory_blocks_to_records
from harnesscoder.core.models import (
    MODEL_SYSTEM_PROMPT,
    MODEL_TOOL_NAMES,
    ModelAdapter,
    ModelAdapterError,
)
from harnesscoder.core.policy import PolicyDecision, ToolPolicy
from harnesscoder.core.prompt import ContextMode, assemble_context
from harnesscoder.core.repo_map import RepoMapCache
from harnesscoder.core.state import AgentState, ModelAction, ToolObservation
from harnesscoder.core.tools import ToolRegistry, ToolResult
from harnesscoder.core.trace import TraceWriter


RepoMapMode = Literal["none", "auto"]


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
        context_mode: ContextMode = "none",
        policy: ToolPolicy | None = None,
        tools: ToolRegistry | None = None,
        repo_map_max_tokens: int = 1200,
        repo_map_mode: RepoMapMode = "auto",
    ) -> None:
        self.model = model
        self.cwd = cwd.resolve()
        self.trace_root = trace_root
        self.max_iterations = max_iterations
        self.context_mode = context_mode
        self.policy = policy or ToolPolicy()
        self.tools = tools or ToolRegistry(self.cwd)
        self.repo_map = RepoMapCache(self.cwd)
        self.repo_map_max_tokens = repo_map_max_tokens
        self.repo_map_mode = repo_map_mode
        self._stable_prefix_hash: str | None = None

    def run(
        self,
        task: str,
        *,
        session_context: dict[str, Any] | None = None,
    ) -> RunResult:
        run_id = self._new_run_id()
        trace = TraceWriter(run_id=run_id, trace_root=self.trace_root, cwd=self.cwd)
        state = AgentState(
            run_id=run_id,
            task=task,
            cwd=str(self.cwd),
            max_iterations=self.max_iterations,
            session_context=session_context,
        )
        state.messages.append({"role": "user", "content": task})

        trace.emit(
            "run_started",
            task=task,
            cwd=str(self.cwd),
            model=getattr(self.model, "name", type(self.model).__name__),
            model_metadata=self._model_metadata(),
            max_iterations=self.max_iterations,
            context_mode=self.context_mode,
            repo_map_max_tokens=self.repo_map_max_tokens,
            repo_map_mode=self.repo_map_mode,
            session_id=_session_id(session_context),
            session_turn_count=_session_turn_count(session_context),
            session_context_injected=session_context is not None,
        )
        if session_context is not None:
            trace.emit(
                "session_context_loaded",
                session_id=_session_id(session_context),
                turn_count=_session_turn_count(session_context),
                summary=session_context.get("summary"),
                recent_turn_count=len(session_context.get("recent_turns") or []),
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

    def _run_loop(
        self,
        state: AgentState,
        trace: TraceWriter,
    ) -> RunResult:
        if state.done:
            status = "success" if state.phase == "done" else "failed"
            answer = state.final_answer or ""
            trace.emit("run_finished", status=status, final_answer=answer)
            return RunResult(state.run_id, status, answer, trace.trace_path)

        status = "success"
        while not state.done and state.iterations < state.max_iterations:
            context_pack = build_context_pack(state)
            repo_map_result = None
            if self.context_mode in {"pack", "memory"} and self.repo_map_mode == "auto":
                repo_map_result = self.repo_map.render(
                    query=state.task,
                    max_tokens=self.repo_map_max_tokens,
                )
                if repo_map_result.metadata.get("built") is True:
                    trace.emit(
                        "repo_map_built",
                        reason="context_assembly",
                        **repo_map_result.metadata,
                    )
                trace.emit(
                    "repo_map_used",
                    reason="context_assembly",
                    injected=True,
                    **repo_map_result.metadata,
                )
            context = assemble_context(
                state=state,
                system_instructions=MODEL_SYSTEM_PROMPT,
                available_tools=self._available_tools(),
                context_pack=context_pack,
                context_mode=self.context_mode,
                repo_map=repo_map_result.text if repo_map_result is not None else None,
                session_context=state.session_context,
            )
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
                **self._prompt_cache_trace_fields(context),
                **context.to_trace_record(),
                **context_pack,
            )

            try:
                action = self._next_model_action_with_retry(
                    state,
                    context,
                    trace,
                    reason="model_step",
                )
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
            result = store_large_observation(result, run_path=trace.run_path).result
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
            changed_memory = apply_memory_reducer(
                state.memory_blocks,
                result=result,
                step=state.iterations,
            )
            result.metadata["changed_state"] = (
                state.governance_snapshot(include_budget=False) != before_governance
            )
            trace.emit("tool_result", result=result.to_record())
            if changed_memory:
                trace.emit(
                    "memory_updated",
                    call_id=result.call_id,
                    tool_name=result.tool_name,
                    updated_blocks=changed_memory,
                    memory_blocks=memory_blocks_to_records(state.memory_blocks),
                )
            if result.tool_name == "repo_map" and result.ok:
                if result.metadata.get("built") is True:
                    trace.emit(
                        "repo_map_built",
                        reason="tool_call",
                        call_id=result.call_id,
                        **result.metadata,
                    )
                trace.emit(
                    "repo_map_used",
                    reason="tool_call",
                    call_id=result.call_id,
                    injected=False,
                    **result.metadata,
                )
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
        if self._eligible_for_finish_grace(state):
            trace.emit(
                "finish_grace_started",
                reason="max_iterations_after_successful_verification",
                iterations=state.iterations,
                max_iterations=state.max_iterations,
            )
            try:
                context_pack = build_context_pack(state)
                context = assemble_context(
                    state=state,
                    system_instructions=MODEL_SYSTEM_PROMPT,
                    available_tools=[],
                    context_pack=context_pack,
                    context_mode=self.context_mode,
                    repo_map=None,
                    session_context=state.session_context,
                )
                trace.emit(
                    "context_packed",
                    reason="finish_grace",
                    source_event_index=state.iterations,
                    input_message_count=len(state.messages),
                    kept_message_count=min(len(state.messages), 6),
                    dropped_message_count=max(0, len(state.messages) - 6),
                    summary=context_pack["cold_trace_summary"],
                    packed_context=context_pack,
                    context_pack=context_pack,
                    finish_grace=True,
                    **self._prompt_cache_trace_fields(context),
                    **context.to_trace_record(),
                    **context_pack,
                )
                action = self._next_model_action_with_retry(
                    state,
                    context,
                    trace,
                    reason="finish_grace",
                )
            except Exception as exc:
                trace.emit(
                    "finish_grace_result",
                    accepted=False,
                    action_kind=None,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
            else:
                state.append_action(action)
                trace.emit("model_action", action=action.to_record(), finish_grace=True)
                if action.kind == "finish":
                    answer = action.content or ""
                    state.finish(answer)
                    self._emit_state_updated(trace, state)
                    trace.emit(
                        "finish_grace_result",
                        accepted=True,
                        action_kind=action.kind,
                    )
                    trace.emit(
                        "run_finished",
                        status="success",
                        final_answer=answer,
                        finish_grace=True,
                    )
                    return RunResult(state.run_id, "success", answer, trace.trace_path)
                trace.emit(
                    "finish_grace_result",
                    accepted=False,
                    action_kind=action.kind,
                    tool_name=action.tool_name,
                    reason="finish_grace_accepts_only_finish",
                )
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

    def _next_model_action(self, state: AgentState, context: object) -> ModelAction:
        method = self.model.next_action
        try:
            signature = inspect.signature(method)
        except (TypeError, ValueError):
            return method(state, context)  # type: ignore[misc]

        positional = [
            parameter
            for parameter in signature.parameters.values()
            if parameter.kind
            in {
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            }
        ]
        has_varargs = any(
            parameter.kind == inspect.Parameter.VAR_POSITIONAL
            for parameter in signature.parameters.values()
        )
        if not has_varargs and len(positional) <= 1:
            return method(state)  # type: ignore[call-arg]
        return method(state, context)  # type: ignore[misc]

    def _next_model_action_with_retry(
        self,
        state: AgentState,
        context: object,
        trace: TraceWriter,
        *,
        reason: str,
    ) -> ModelAction:
        try:
            return self._next_model_action(state, context)
        except ModelAdapterError as exc:
            if not _is_retryable_model_adapter_error(exc):
                raise
            trace.emit(
                "model_retry",
                reason=reason,
                attempt=1,
                max_retries=1,
                error_type=type(exc).__name__,
                error=str(exc),
                state=state.snapshot(),
            )
            return self._next_model_action(state, context)

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

    def _available_tools(self) -> list[str]:
        if self.policy.allowed_tools is None:
            return list(MODEL_TOOL_NAMES)
        return [
            tool_name
            for tool_name in MODEL_TOOL_NAMES
            if tool_name in self.policy.allowed_tools
        ]

    def _model_metadata(self) -> dict[str, object]:
        metadata_provider = getattr(self.model, "model_metadata", None)
        if callable(metadata_provider):
            metadata = metadata_provider()
            if isinstance(metadata, dict):
                return dict(metadata)
        return {
            "provider": getattr(self.model, "name", type(self.model).__name__),
        }

    def _prompt_cache_trace_fields(self, context: object) -> dict[str, object]:
        fingerprint = getattr(context, "prompt_fingerprint", {})
        stable_hash = (
            fingerprint.get("stable_prefix_hash")
            if isinstance(fingerprint, dict)
            else None
        )
        previous_hash = self._stable_prefix_hash
        if previous_hash is None:
            self._stable_prefix_hash = stable_hash
            return {
                "stable_prefix_changed": False,
                "cache_break_reason": None,
            }
        if stable_hash == previous_hash:
            return {
                "stable_prefix_changed": False,
                "cache_break_reason": None,
            }
        self._stable_prefix_hash = stable_hash
        return {
            "stable_prefix_changed": True,
            "cache_break_reason": "stable prompt prefix changed",
        }

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

    def _eligible_for_finish_grace(self, state: AgentState) -> bool:
        latest_successful_test_index: int | None = None
        for index, observation in enumerate(state.observations):
            if observation.tool_name == "run_tests" and observation.ok:
                latest_successful_test_index = index
        if latest_successful_test_index is None:
            return False

        for observation in state.observations[latest_successful_test_index + 1 :]:
            if observation.tool_name == "run_tests" and not observation.ok:
                return False
            if observation.tool_name in {"edit_file", "write_file"} and observation.ok:
                metadata = observation.metadata
                if metadata.get("changed") is True or metadata.get("created") is True:
                    return False
        return True

    def _new_run_id(self) -> str:
        return f"run_{uuid4().hex[:12]}"


def _session_id(session_context: dict[str, Any] | None) -> str | None:
    if not isinstance(session_context, dict):
        return None
    value = session_context.get("session_id")
    return str(value) if value is not None else None


def _session_turn_count(session_context: dict[str, Any] | None) -> int:
    if not isinstance(session_context, dict):
        return 0
    value = session_context.get("turn_count")
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _is_retryable_model_adapter_error(exc: ModelAdapterError) -> bool:
    message = str(exc)
    retryable_markers = (
        "model API response did not include text output",
        "model did not return valid action JSON:",
        "model API request failed:",
        "model API returned HTTP 408:",
        "model API returned HTTP 409:",
        "model API returned HTTP 429:",
        "model API returned HTTP 500:",
        "model API returned HTTP 502:",
        "model API returned HTTP 503:",
        "model API returned HTTP 504:",
        "model API returned non-JSON response:",
    )
    return any(marker in message for marker in retryable_markers)
