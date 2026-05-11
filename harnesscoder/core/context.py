from __future__ import annotations

from collections import Counter
from typing import Any

from harnesscoder.core.state import AgentState, ToolObservation


def build_context_pack(state: AgentState, hot_limit: int = 6) -> dict[str, Any]:
    """Build the compact state view emitted before each model decision."""

    hot_limit = max(1, hot_limit)
    state.refresh_budget()
    recent_observations = state.observations[-hot_limit:]
    cold_observations = state.observations[:-hot_limit]

    return {
        "hot_context": {
            "phase": state.phase,
            "recent_actions": state.actions[-hot_limit:],
            "recent_observations": [
                _observation_context(observation)
                for observation in recent_observations
            ],
        },
        "working_memory": {
            "file_summaries": dict(state.file_summaries),
            "modified_files": list(state.modified_files),
            "last_error": state.last_error,
            "open_questions": list(state.open_questions),
        },
        "cold_trace_summary": _cold_trace_summary(state, cold_observations),
        "budget": dict(state.budget),
    }


def _observation_context(observation: ToolObservation) -> dict[str, Any]:
    return {
        "call_id": observation.call_id,
        "tool_name": observation.tool_name,
        "ok": observation.ok,
        "output": observation.short_output(1600),
        "error": observation.error,
        "metadata": dict(observation.metadata),
    }


def _cold_trace_summary(
    state: AgentState,
    observations: list[ToolObservation],
) -> dict[str, Any]:
    tool_counts = Counter(observation.tool_name for observation in observations)
    failed = [observation for observation in observations if not observation.ok]
    return {
        "total_actions": len(state.actions),
        "total_observations": len(state.observations),
        "older_observations": len(observations),
        "older_tool_counts": dict(sorted(tool_counts.items())),
        "older_error_count": len(failed),
        "recent_older_errors": [
            {
                "tool_name": observation.tool_name,
                "error": observation.error,
                "metadata": dict(observation.metadata),
            }
            for observation in failed[-3:]
        ],
    }
