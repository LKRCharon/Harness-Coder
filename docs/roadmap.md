# HarnessCoder Roadmap

HarnessCoder's release plan stays centered on one thesis:

> A trace-backed coding agent harness should make coding-agent behavior
> measurable, replayable, recoverable, and optimizable on real repository tasks.

This roadmap is intentionally conservative. The project should not grow into a
generic multi-agent framework, a LangGraph clone, or a web UI before the single
agent runtime is demonstrably reliable.

## Current Release: 1.2.x

The 1.2 line keeps the 1.0 interview-ready runtime, the 1.1 prompt-cache-aware
context governance, and adds a clean train/eval boundary for post-training
work:

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
- Prompt fingerprints, stable-prefix token estimates, and cache-break metrics
  for every model-step prompt.
- HC-Train-40 as a training trace pool with explicit split/source metadata.
- HC-Bench-20 kept separate as the current heldout-like control suite.
- HC-Bench-40 as the harder heldout scorecard, extending the 20-case suite
  without mixing in train cases.
- A small runtime control plane boundary for CLI/TUI/eval run-control decisions
  such as active-run protection and read-only status/trace commands.

### 1.2.x Quality Work

Near-term 1.2.x releases should focus on tightening evidence rather than adding
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
- Keep prompt/tool ordering deterministic and report stable-prefix changes.
- Keep HC-Train-40, HC-Bench-20, and HC-Bench-40 split metadata explicit so
  training trace collection and final eval evidence do not collapse into one
  dataset.
- Move `/status`, `/trace`, interrupt/cancel, resume, approval, and active-run
  protection into shared runtime control semantics instead of leaving them as
  scattered UI branches.
- Use HC-Bench-40 for harder heldout comparisons while keeping HC-Bench-20 as a
  backward-compatible release/evidence baseline.

### Control Plane Boundary

Hermes' Gateway design is useful as a layering lesson, not as a product target.
HarnessCoder should not add Telegram, Discord, email, or web gateways. Its local
entrypoints are enough:

```text
CLI / TUI / Eval
-> run control
-> runner
-> trace/checkpoint
-> replay/eval report
```

The run-control layer should answer questions such as:

- Is there already an active run?
- Which commands are safe while a run is active?
- How should interrupt, resume, and approval be represented?
- Which status and trace facts can the UI show without becoming the source of
  truth?

The final truth remains the run trace, checkpoint, replay summary, eval report,
and `RunResult`; the control plane only coordinates how entrypoints interact
with that runtime.

## 1.3.0: Read-Only Reviewer / Explorer Subagent

1.3 may add a small read-only subagent lane. It should be a reviewer/explorer,
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

These are possible after 1.2, but only if backed by benchmark cases and replay
evidence:

- Larger heldout suites beyond HC-Bench-40, but only when the new cases add
  distinct failure modes or language/runtime coverage.
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
