# HarnessCoder 1.2.1 Spec

## Goal

Package the post-1.2 quality work into a small release: a harder heldout
benchmark, a shared run-control boundary, and Codex reasoning-strength runtime
configuration.

This release keeps HarnessCoder on its existing identity: a local
trace-backed coding-agent runtime plus eval harness. It does not turn the
project into a general multi-platform Agent gateway.

## Scope

- Add `HC-Bench-40` as the current harder heldout scorecard.
- Keep HC-Bench-20 cases intact inside HC-Bench-40 for historical comparison.
- Add 20 new heldout cases covering programming repairs, recovery, greenfield
  coding, large-context lookup, and policy/security behavior.
- Add a small `RunControlPlane` for active-run protection shared by TUI-facing
  runtime decisions.
- Support Codex Responses reasoning strength through `--reasoning-effort`,
  `HARNESSCODER_REASONING_EFFORT`, `models.toml`, and TUI `/reasoning`.
- Record safe model metadata, including configured/effective reasoning effort,
  in `run_started` trace events and eval matrix summaries.
- Keep `openai-chat` clean: Chat Completions providers such as DeepSeek do not
  receive a Responses reasoning payload.

## HC-Bench-40 Shape

HC-Bench-40 has 40 fixture-backed heldout cases:

```text
bugfix:     11
recovery:    6
greenfield: 10
context:     7
policy:      6
```

The 20 added cases are not copied from external benchmarks. They are synthetic
microbenchmark cases inspired by benchmark design patterns:

- ProgramBench-style programming and parser edge cases.
- TRAJECT-Bench-style emphasis on the tool trajectory, not only final output.
- SWE-style fixture isolation, targeted tests, and verifier contracts.

## Reasoning Runtime Contract

Valid reasoning efforts are:

```text
none, minimal, low, medium, high, xhigh
```

For `openai-codex`, the adapter translates the configured effort into the
Responses API `reasoning` payload. `minimal` is sent as `low` for Responses API
compatibility. `none` omits the reasoning payload.

For `openai-chat`, profile-level `reasoning_effort` is rejected and direct CLI
usage with `--reasoning-effort` is blocked. This keeps DeepSeek and other Chat
Completions profiles on their native request shape.

## Acceptance

- `python scripts/generate_hc_bench_40.py` regenerates HC-Bench-40 and its
  oracle plan.
- `python -m unittest discover -s tests` passes.
- `python -m harnesscoder --provider hc-bench-oracle --eval eval/hc_bench_20.json --max-iterations 8`
  passes 20/20.
- `python -m harnesscoder --provider hc-bench-oracle --eval eval/hc_bench_40.json --max-iterations 8`
  passes 40/40.
- `python -m harnesscoder --version` reports `harnesscoder 1.2.1`.
- Public docs do not expose private model providers, private endpoints, `.env`,
  local `models.toml`, or generated `.harnesscoder/` traces.

## Non-goals

- No Hermes-style multi-platform Gateway.
- No subagents.
- No long-term memory platform.
- No SWE-bench-scale adapter.
- No real-model score claim in the release itself.

## Interview Angle

1.2.1 is a reliability release. It shows that HC can grow benchmark coverage
without polluting train/eval boundaries, can centralize runtime control instead
of scattering UI branches, and can treat provider knobs such as reasoning
strength as trace-backed runtime configuration rather than ad hoc command-line
folklore.
