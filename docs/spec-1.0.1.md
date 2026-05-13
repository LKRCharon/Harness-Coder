# HarnessCoder 1.0.1 Scoped Spec

Version 1.0.1 tightens the real-model eval loop after the first three-model
HC-Bench-20 comparison. The core issue is that the current score mixes two
different questions:

- Did the model produce a correct patch?
- Did the agent obey the harness protocol and explicitly finish?

1.0.1 keeps explicit `finish` as part of the agent contract, but makes the
contract less brittle and reports patch quality separately from agent protocol
quality.

## Goals

- Strengthen the model prompt so models know when to stop.
- Add one finish-only grace step after the last successful verification action.
- Split eval reporting into `patch_success` and `agent_success`.
- Preserve trace-backed auditability for normal finishes and grace finishes.
- Keep HC-Bench-20 comparable across DeepSeek, GPT-5.4, and GPT-5.5.

## Finish Prompt Contract

The system prompt must explicitly tell the model:

- If the relevant tests pass and no further edit is needed, emit `finish`
  immediately.
- Do not run extra exploratory tools after a targeted verification passes unless
  the latest result shows a real unresolved failure.
- Full-suite failures may be unrelated in HC-Bench fixtures; after the targeted
  case test passes, summarize unrelated failures in `finish` instead of looping.
- When remaining budget is low, prefer `finish` over redundant reads or repeated
  test commands.

Prompt tests should assert that these rules are present in the adapter prompt
without calling a real model API.

## Finish Grace Step

When the agent reaches `max_iterations`, the runner may offer exactly one
additional model decision if the latest useful state indicates that the patch is
already verified.

The grace step must be:

- Finish-only: accepted action kind is `finish`; any tool action ends as
  `max_iterations`.
- Trace-backed: emit a dedicated event such as `finish_grace_started` before the
  extra model call, and `finish_grace_result` after it.
- Bounded: at most one extra model call per run.
- Transparent: `run_finished` should still distinguish normal success from
  grace success through trace metadata.

Suggested eligibility:

- The last `run_tests` tool result succeeded, or the last task-relevant test
  result succeeded.
- There is no later edit/write after that successful verification.
- The last failed test, if any, is followed by a successful targeted test.

The grace step is not a hidden auto-pass. The model still has to emit a valid
`finish` JSON object.

## Eval Metrics

Reports must show two success notions:

- `patch_success`: external test criteria and verifier both pass.
- `agent_success`: runner status is `success`.

Final case `passed` may continue to require both:

```text
passed = patch_success && agent_success
```

But the report must make the split visible so a run like "patch correct, no
finish" is not misread as a pure coding failure.

Required report additions:

- Patch success rate.
- Agent success rate.
- Patch-success-but-agent-failed count.
- Finish grace attempts.
- Finish grace successes.
- Failure breakdown should keep `max_iterations` / `tool_failed` distinct from
  verifier/test failures where possible.

## Acceptance

- Unit tests cover the stronger finish prompt text.
- Unit tests cover max-iteration behavior with and without grace eligibility.
- Unit tests cover a grace step that accepts only `finish`.
- Unit tests cover eval report rendering for:
  - patch success + agent success
  - patch success + agent failure
  - patch failure + agent success
- Existing unit tests remain green.
- HC-Bench-20 oracle remains 20/20.
- Real-model matrix can be rerun and now reports `patch_success` and
  `agent_success` separately.

## Non-Goals

- Do not change HC-Bench-20 tasks to make the benchmark easier.
- Do not auto-finish without a model `finish` action.
- Do not remove explicit `finish` from the agent protocol.
- Do not introduce subagents.
- Do not change provider credentials or public documentation with private
  endpoints.
