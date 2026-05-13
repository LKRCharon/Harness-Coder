# HarnessCoder 1.0 Release Spec

HarnessCoder 1.0 is a trace-backed coding agent harness with real-model eval,
task-local memory, context compression, and repository-level context governance.

## Release Criteria

- Unit tests pass.
- HC-Bench-20 oracle benchmark passes 20/20.
- Real-model matrix has recorded results or explicit failure reasons.
- Context/memory/RepoMap ablations have Markdown reports.
- README explains reproduction commands.
- No secret, private endpoint, `.env`, or local `models.toml` leakage.
- License, CI, examples, and docs are present.

## Core Claims

- Event-sourced agent loop: every important model, policy, tool, memory,
  checkpoint, and result transition is traceable.
- Policy-gated tools: local file, command, and test effects pass through a
  small policy layer.
- Trace/replay/eval: traces can be replayed into metrics and evaluated through
  fixture-backed benchmark cases.
- Context governance: packed context, task-local memory, compression metrics,
  and RepoMap are measurable and ablatable.

## Non-Goals

- Subagents.
- Long-term memory platform.
- LangGraph/DAG clone.
- SWE-bench-scale adapter.
- Web UI.

## Next Release

`1.1.0` may add a read-only reviewer/explorer subagent. It is intentionally out
of scope for 1.0.
