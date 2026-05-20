# HarnessCoder 1.3.1 Spec

## Goal

Make context packing and compaction explainable from the trace itself.

Earlier releases already emitted `context_packed`, task-local memory, RepoMap
injection, and compression metrics. 1.3.1 adds a per-section budget record so a
reviewer can answer a sharper question: "what exactly was preserved, reduced,
or dropped before this model call?"

## Scope

- Add Context Budget v2 to prompt assembly.
- Apply section budgets before model input is serialized.
- Preserve the current task contract even when other sections are reduced.
- Record budget evidence on every `context_packed` event:
  - `context_budget.version`
  - `context_budget.sections`
  - `context_budget.reduced_sections`
  - `context_dropped_blocks`
  - `context_budget_total_chars`
  - `context_budget_total_budget`
- Extend replay metrics with:
  - `context_budget_reduced_count`
  - `context_budget_dropped_blocks`
  - `context_budget_total_chars`
  - `context_budget_total_budget`
- Surface context budget reductions and dropped blocks in eval reports.

## Runtime Contract

`context_packed` remains a normal append-only trace event. The new budget record
is nested inside that event:

```json
{
  "type": "context_packed",
  "run_id": "run_example",
  "context_mode": "memory",
  "context_budget": {
    "version": 2,
    "sections": {
      "system": {
        "raw_chars": 4200,
        "chars": 4200,
        "budget": 12000,
        "preserved": false,
        "reduced": false,
        "dropped_blocks": 0
      },
      "task_contract": {
        "raw_chars": 250,
        "chars": 250,
        "budget": 2400,
        "preserved": true,
        "reduced": false,
        "dropped_blocks": 0
      },
      "packed_context": {
        "raw_chars": 21000,
        "chars": 15900,
        "budget": 16000,
        "preserved": false,
        "reduced": true,
        "dropped_blocks": 2
      }
    },
    "reduced_sections": ["packed_context"],
    "dropped_blocks": 2,
    "total_chars": 24600,
    "total_budget": 63000
  },
  "context_reduced_sections": ["packed_context"],
  "context_dropped_blocks": 2
}
```

The important design choice is that compaction is not one free-form summary.
Prompt assembly works by sections:

```text
system
task_contract         preserved
available_tools
packed_context        reducible
working_memory        reducible
repo_map              reducible
session_context       reducible
recent_observations   reducible
```

For list-heavy sections such as recent observations, packed context, and session
turns, the reducer first clips long strings and then drops older blocks if the
section is still over budget. The current task contract is marked preserved so
the task, cwd, iteration budget, and phase survive section reduction.

## Acceptance

- `python -m unittest tests.test_model_adapter -v` passes.
- `context_packed` trace records include `context_budget.version == 2`.
- A large packed context marks `packed_context.reduced == true`.
- Replay reports budget reduction counts and dropped blocks.
- Normal eval reports and matrix reports expose budget reduction metrics.

## Non-goals

- No semantic guarantee that a model never needs a dropped token.
- No provider-specific prompt caching API.
- No hidden transcript stuffing.
- No global long-term memory.

## Interview Angle

1.3.1 is the answer to "how do you know context compression did not silently
drop key dependencies?"

The precise answer is:

> HC does not treat context compression as one opaque summary. Before every
> model call, it assembles named sections, applies per-section budgets, strongly
> preserves the current task contract, reduces lower-priority sections first,
> and writes the budget decision into the append-only trace. Replay and eval
> reports can then show exactly which sections were reduced and how many blocks
> were dropped.
