# HarnessCoder 1.5.3 Spec

## Goal

Add a plan-aware structured tool-use step contract.

After durable notes and context quality are in place, HarnessCoder can make the
agent loop more explicit: every tool action should be tied to a short plan step,
and each tool result should be interpreted before the next action.

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
Plan -> Tool Use -> Tool Result -> Reflect -> Revise Plan -> Verify -> Finish
```

This is a structured tool-use runtime contract, not a reproduction of the
classic prompt-only ReAct paper format. The runtime keeps structured JSON,
policy gates, trace, checkpoint, and eval compatibility.

The optional `thought_summary`, `expected_observation`, and `reflection` fields
should be understood as runtime hints, not as a requirement to expose a visible
chain-of-thought transcript.

## Acceptance

- Existing model payloads remain backward-compatible.
- New payload fields are recorded in trace when present.
- A deterministic test model can create a plan, execute a step, reflect on an
  observation, and finish.
- Replay reports plan metrics.

## Non-goals

- No multi-agent planner/actor split.
- No `Thought -> Action -> Observation` text-template loop.
- No hidden chain-of-thought exposure.
- No graph/DAG framework.
- No dependency on external agent libraries.

## Interview Angle

1.5.3 is the answer to "is this just a while loop?"

> HC keeps a structured plan-state-tool-use contract. The model does not merely
> call tools repeatedly; each action can be tied to a plan step, each tool
> result can revise the plan, and trace/replay can show whether the agent
> actually followed, changed, or blocked its plan.
