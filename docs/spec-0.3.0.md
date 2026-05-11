# HarnessCoder 0.3.0 Scoped Spec

Version 0.3.0 turns the next runtime target into demo-ready, testable assets.
It does not try to make HarnessCoder broad. The release should show that a
coding-agent run can be compacted, interrupted, resumed, tested, replayed, and
scored from structured artifacts.

## Goals

- Make context compaction visible in the JSONL trace.
- Make checkpoint/resume concrete enough to demo with a synthetic interrupted
  run.
- Normalize test execution results as first-class trace records.
- Classify failures into stable categories for replay reports.
- Define eval metrics that can be computed from traces and replay reports.

## Trace Compatibility

The trace remains append-only JSONL. Each record keeps the existing shape:

```json
{
  "ts": "2026-05-12T00:00:00+00:00",
  "run_id": "run_example",
  "type": "event_name"
}
```

Consumers must tolerate unknown event types. New 0.3.0 events should be useful
when present, but older 0.2.0 traces should still summarize and replay.

## In Scope

### `context_packed`

`context_packed` records that the runtime compacted conversation/tool context
before asking the model for another action.

Required fields:

- `reason`: why packing happened, such as `token_budget` or `resume_prepare`.
- `source_event_index`: the last trace event included in the packed input.
- `input_message_count`: message count before packing.
- `kept_message_count`: message count left verbatim after packing.
- `dropped_message_count`: message count replaced by the summary.
- `summary`: short human-readable summary of removed context.
- `packed_context`: structured context passed forward to the model.

Optional fields:

- `token_estimate_before`
- `token_estimate_after`

Acceptance:

- At least one demo trace contains `context_packed`.
- Replay summary event counts include `context_packed`.
- The packed record is self-describing without requiring model internals.

### Checkpoint/Resume

Checkpoint/resume makes interruption explicit. A checkpoint is a JSON snapshot
that is sufficient to continue a run without repeating earlier exploration.

Trace events:

- `checkpoint_created`: emitted when a checkpoint file is written.
- `run_resumed`: emitted when a run resumes from a checkpoint.

Checkpoint file minimum fields:

- `version`
- `run_id`
- `trace_path`
- `state`

Acceptance:

- The resume demo includes an interrupted exploration trace.
- The demo includes a checkpoint file referenced by the trace.
- The resumed segment reaches `run_finished` without replaying exploration
  tool calls.

### `test_result`

`test_result` records the normalized outcome of a test command. It is separate
from `tool_result` so eval and replay do not need to parse arbitrary stdout.

Required fields:

- `command` or `cmd`
- `returncode`
- `passed`
- `timed_out`
- `duration_seconds`
- `stdout_excerpt`
- `stderr_excerpt`

Optional fields:

- `failure_category`
- `metrics`

Acceptance:

- A failure replay fixture contains `test_result`.
- A failing `test_result` can be classified without scanning raw terminal
  output.

### `failure_category`

Failure replay reports must expose one stable top-level category. The initial
allowed values are:

- `success`
- `test_failed`
- `policy_denied`
- `tool_failed`
- `model_error`
- `max_iterations`
- `incomplete`

Acceptance:

- The failure replay demo report has `summary.failure_category`.
- The category matches the trace evidence.

### Eval Metrics

0.3.0 metrics are intentionally small and trace-derived:

- `cases_total`
- `cases_passed`
- `cases_failed`
- `pass_rate`
- `agent_success_rate`
- `test_pass_rate`
- `tool_failure_count`
- `policy_denial_count`
- `context_packed_count`
- `checkpoint_created_count`
- `resume_success_rate`
- `mean_test_duration_seconds`

Acceptance:

- Replay/eval reports include a `metrics` object.
- Metric names are stable enough for README screenshots and interview demos.
- Missing metrics should default to zero or `null`, not crash report rendering.

## Out Of Scope

0.3.0 will not include:

- A 20-task benchmark suite.
- A full web UI.
- A multi-agent framework.
- Browser automation as a required runtime feature.
- A persistent database for traces or checkpoints.
- Live provider quality comparisons.

These can become later milestones after the trace, checkpoint, replay, and eval
surfaces are stable.

## Demo Assets

The release includes two minimal examples:

- `examples/resume_demo/`: interrupt after exploration, write checkpoint,
  resume from packed context, finish.
- `examples/failure_replay_demo/`: synthetic failing test trace plus a replay
  report with `failure_category` and metrics.

The examples are fixtures first. Core runtime code may later generate the same
shape directly.
