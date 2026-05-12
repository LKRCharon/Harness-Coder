from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from harnesscoder.core.state import AgentState, ModelAction


PLAN_PATH = Path(__file__).resolve().parents[1] / "data" / "hc_bench_oracle.json"


def hc_bench_oracle_action(state: AgentState) -> ModelAction | None:
    """Return the next deterministic HC-Bench action, if the task declares one."""

    case_id = _case_id_from_task(state.task)
    if not case_id:
        return None
    plan = _load_plan().get(case_id)
    if plan is None:
        return None

    index = len(state.actions)
    if index < len(plan):
        action = plan[index]
        return ModelAction(
            kind="tool",
            rationale=str(action["rationale"]),
            tool_name=str(action["tool_name"]),
            tool_args=dict(action["tool_args"]),
        )

    return ModelAction(
        kind="finish",
        rationale="The HC-Bench oracle completed the expected local workflow.",
        content=f"Completed {case_id}.",
    )


@lru_cache(maxsize=1)
def _load_plan() -> dict[str, list[dict[str, Any]]]:
    if not PLAN_PATH.exists():
        return {}
    data = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {}
    raw_plans = data.get("plans")
    if not isinstance(raw_plans, dict):
        return {}

    plans: dict[str, list[dict[str, Any]]] = {}
    for case_id, raw_plan in raw_plans.items():
        if not isinstance(case_id, str) or not isinstance(raw_plan, list):
            continue
        actions: list[dict[str, Any]] = []
        for raw_action in raw_plan:
            if not isinstance(raw_action, dict):
                continue
            rationale = raw_action.get("rationale")
            tool_name = raw_action.get("tool_name")
            tool_args = raw_action.get("tool_args")
            if (
                isinstance(rationale, str)
                and isinstance(tool_name, str)
                and isinstance(tool_args, dict)
            ):
                actions.append(
                    {
                        "rationale": rationale,
                        "tool_name": tool_name,
                        "tool_args": tool_args,
                    }
                )
        plans[case_id] = actions
    return plans


def _case_id_from_task(task: str) -> str | None:
    match = re.search(r"\[HC-Bench case:\s*([A-Za-z0-9_.-]+)\]", task)
    if match:
        return match.group(1)
    return None
