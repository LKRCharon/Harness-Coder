# HarnessCoder Roadmap

HarnessCoder's release plan stays centered on one thesis:

> A trace-backed coding agent harness should make coding-agent behavior
> measurable, replayable, recoverable, and optimizable on real repository tasks.

This roadmap is intentionally conservative. The project should not grow into a
generic multi-agent framework, a LangGraph clone, or a web UI before the single
agent runtime is demonstrably reliable.

## Current Release: 1.5.3

The 1.5 line skips the earlier 1.4 read-only subagent idea and moves the main
story toward long-horizon codebase maintenance. The new target is:

> A codebase-agent runtime should keep long-running coding tasks continuous,
> controllable, and auditable across runs.

Trace remains the evidence layer, but it is no longer the only product story.
The 1.5 line adds durable task notes, note-aware context construction, context
quality evaluation, and then a plan-aware structured tool-use step contract.

### 1.5.x Plan

- 1.5.0: Long-term task notes.
  - Local Markdown `NoteStore` with `notes_index.json`.
  - Model-callable `create_note` and `search_notes`.
  - Note types for blockers, actions, task state, decisions, conclusions, and
    verified facts.
  - Trace/replay evidence for note creation and retrieval.
- 1.5.1: Note-aware context assembly.
  - Runtime note retrieval and selection.
  - `relevant_notes` prompt section.
  - Trace/replay evidence for note injection.
- 1.5.2: Context-quality evaluation for the GSSC pipeline.
  - Density, relevance, and completeness scores.
  - Warnings and suggestions for bad context.
  - Eval/report metrics for context quality.
- 1.5.3: Plan-aware structured tool-use step contract.
  - Structured plan and step state.
  - Optional thought summary, expected observation, reflection, and plan update
    fields on model actions.
  - Plan trace/replay metrics.

### Tool-Use Direction

The project should stop treating classic 2022-style ReAct prompting as the
implementation target.

ReAct remains useful as historical background for understanding why
reasoning-action-observation loops matter. But HarnessCoder's runtime story is
now closer to the production coding-agent pattern used by modern tool-calling
systems:

- assemble bounded context
- call the model with a structured action contract
- policy-gate tool execution
- append tool results to state and trace
- continue the loop until the model ends the turn

In other words, HarnessCoder is moving from "paper-style ReAct framing" to
"structured tool-use runtime" framing.

That means:

- no fragile `Thought: Action: Observation:` text parsing
- no requirement that reasoning be exposed as free-form visible chain-of-thought
- yes to structured model actions, explicit end-of-turn control, policy-gated
  tool execution, trace evidence, context governance, and replayable evaluation

### Why 1.4 Is Deferred

The old 1.4 candidate was a read-only reviewer/explorer subagent. That remains a
possible future feature, but it is less urgent than long-horizon single-agent
state. The current interview and engineering gap is not "add more agents"; it is
"make one coding agent maintain task continuity, context quality, and explicit
plans across longer work."

## Previous Release: 1.3.4

The 1.3 line keeps the 1.0 interview-ready runtime, the 1.1
prompt-cache-aware context governance, and the 1.2 train/eval boundary. It adds
durable cross-run sessions for follow-up coding tasks, then tightens context
evidence with Context Budget v2 and a context ablation matrix:

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
- Durable session JSON under `.harnesscoder/sessions/<session_id>.json`.
- `session_context_loaded` and `context_packed.session_context_injected` trace
  evidence for follow-up tasks.
- CLI `--session` plus TUI `/session` and `/reset-session`.
- Context Budget v2 on every `context_packed` event, with per-section chars,
  budgets, preserved/reduced flags, dropped blocks, and total budget usage.
- Replay/report metrics for context budget reductions and dropped blocks.
- Built-in `--context-ablations` eval matrix across `full`, `no_repomap`,
  `no_memory`, `no_context_compaction`, and `no_policy_retry`.
- Real-model eval hygiene for OpenAI-compatible endpoints, including tolerant
  action parsing, reproducible Python subprocess execution, and trace/report
  metrics for model retries.

### 1.3.x Quality Work

Near-term 1.3.x releases should focus on tightening evidence rather than adding
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
- Keep Context Budget v2 fields stable enough that replay and old reports remain
  comparable across minor releases.
- Keep HC-Train-40, HC-Bench-20, and HC-Bench-40 split metadata explicit so
  training trace collection and final eval evidence do not collapse into one
  dataset.
- Move `/status`, `/trace`, interrupt/cancel, resume, approval, and active-run
  protection into shared runtime control semantics instead of leaving them as
  scattered UI branches.
- Use HC-Bench-40 for harder heldout comparisons while keeping HC-Bench-20 as a
  backward-compatible release/evidence baseline.
- Add session-aware eval cases before claiming durable sessions improve real
  follow-up task success.
- Use the context ablation matrix for context-governance claims instead of
  relying on one-off manual comparisons.

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

## 1.4.0 Candidate: Read-Only Reviewer / Explorer Subagent

1.4 may add a small read-only subagent lane. It should be a reviewer/explorer,
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
- Stronger context ablations across more repositories, languages, and hidden
  case variants.
- Better replay UX for inspecting model actions, tool results, artifacts, and
  verifier outcomes.
- More robust tool policies for language-specific build systems.
- Optional packaged releases for local CLI use.
- Optional note indexing layers such as SQLite / FTS5 can be explored later,
  but they are not part of the committed 1.6 plan. The current mainline keeps
  Markdown notes as the durable source of truth.

## Correcting The Earlier Detour

Some earlier planning language leaned too hard on ReAct terminology. That was a
useful learning step, but it is not the right mainline for HarnessCoder.

The adjustment is:

- keep ReAct as a conceptual ancestor, not as the runtime contract
- keep plan / reflection / observation as structured runtime concepts
- describe the agent loop as a tool-use loop, not as a prompt-format demo
- focus roadmap work on reliability surfaces: trace, policy, context, notes,
  replay, eval, and run control

This keeps the project aligned with its actual engineering target: a local
coding-agent runtime whose behavior can be inspected, measured, and compared.

## Durable Non-Goals

HarnessCoder should not prioritize:

- Web UI.
- SWE-bench scale adaptation.
- Long-term user memory.
- Generic workflow DAGs.
- Multi-agent platform features before the single-agent harness is measurable
  and reliable.
