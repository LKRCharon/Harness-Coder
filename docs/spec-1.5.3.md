# HarnessCoder 1.5.3 Spec

## Goal

Add a plan-driven ReAct-style step contract.

After durable notes and context quality are in place, HarnessCoder can make the
agent loop more explicit: every tool action should be tied to a short plan step,
and each observation should be interpreted before the next action.

## Scope

- Add `AgentPlan` and `PlanStep` to runtime state.
- Extend model actions with optional:
  - `thought_summary`
  - `current_step_id`
  - `expected_observation`
  - `reflection`
  - `plan_update`
- Keep JSON model output; do not switch to fragile `Thought: Action:` text
  parsing.
- Emit plan trace events:
  - `plan_created`
  - `plan_updated`
  - `step_started`
  - `step_completed`
  - `step_blocked`
- Add replay metrics:
  - plan step count
  - plan revision count
  - blocked step count
  - action-with-step ratio

## Runtime Contract

```text
Plan -> Act -> Observe -> Reflect -> Revise Plan -> Verify -> Finish
```

This is ReAct-inspired, not a strict reproduction of the original prompt-only
paper demo. The runtime keeps structured JSON, policy gates, trace, checkpoint,
and eval compatibility.

## Acceptance

- Existing model payloads remain backward-compatible.
- New payload fields are recorded in trace when present.
- A deterministic test model can create a plan, execute a step, reflect on an
  observation, and finish.
- Replay reports plan metrics.

## Non-goals

- No multi-agent planner/actor split.
- No hidden chain-of-thought exposure.
- No graph/DAG framework.
- No dependency on external agent libraries.

## Interview Angle

1.5.3 is the answer to "is this just a while loop?"

> HC keeps a structured plan-state-action-observation contract. The model does
> not merely call tools repeatedly; each action can be tied to a plan step, each
> observation can revise the plan, and trace/replay can show whether the agent
> actually followed, changed, or blocked its plan.
