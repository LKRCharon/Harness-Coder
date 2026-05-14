# HarnessCoder Roadmap

HarnessCoder's release plan stays centered on one thesis:

> A trace-backed coding agent harness should make coding-agent behavior
> measurable, replayable, recoverable, and optimizable on real repository tasks.

This roadmap is intentionally conservative. The project should not grow into a
generic multi-agent framework, a LangGraph clone, or a web UI before the single
agent runtime is demonstrably reliable.

## Current Release: 1.0.x

The 1.0 line is the interview-ready baseline:

- Event-sourced agent loop with JSONL traces.
- Policy-gated local tools.
- Checkpoint and resume.
- Trace replay and failure attribution.
- HC-Bench-20 fixture-backed benchmark.
- Deterministic oracle and scripted control profiles.
- Real-model matrix reports through model profiles.
- Context governance through packing, task-local memory, compression metrics,
  and lightweight RepoMap.
- Observation artifact storage for large tool outputs.

### 1.0.x Quality Work

Near-term 1.0.x releases should focus on tightening evidence rather than adding
new product surfaces:

- Keep unit tests and HC-Bench-20 oracle green.
- Keep public docs free of private provider names, private endpoints, and local
  secrets.
- Improve failure categories when real-model runs expose ambiguous outcomes.
- Add small regression tests for trace, replay, context, memory, RepoMap, and
  artifact behavior whenever a bug is found.
- Keep matrix reports readable as metrics grow.
- Preserve deterministic baselines so model changes can be separated from
  harness regressions.

## 1.1.0: Read-Only Reviewer / Explorer Subagent

1.1 may add a small read-only subagent lane. It should be a reviewer/explorer,
not a general multi-agent platform.

Scope:

- Read-only repo exploration.
- Review current diff for likely bugs, missing tests, policy risks, and
  trace/report inconsistencies.
- Return findings with file and line references.
- Emit trace events for subagent prompts, findings, and disposition.

Acceptance:

- The main agent remains the only writer by default.
- Subagent results are auditable in the run trace.
- Reports can show whether a subagent finding led to a patch or was dismissed.
- Existing single-agent evals remain comparable without subagents.

Non-goals:

- No autonomous worker swarm.
- No long-term memory platform.
- No hidden edits from subagents.
- No graph/DAG orchestration framework.

## Future Directions

These are possible after 1.1, but only if backed by benchmark cases and replay
evidence:

- More realistic repo tasks with targeted verifiers.
- Stronger context ablations across `none`, `pack`, `memory`, and RepoMap modes.
- Better replay UX for inspecting model actions, tool results, artifacts, and
  verifier outcomes.
- More robust tool policies for language-specific build systems.
- Optional packaged releases for local CLI use.

## Durable Non-Goals

HarnessCoder should not prioritize:

- Web UI.
- SWE-bench scale adaptation.
- Long-term user memory.
- Generic workflow DAGs.
- Multi-agent platform features before the single-agent harness is measurable
  and reliable.
