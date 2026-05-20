# AGENTS.md

This repository is a long-lived interview project for Agent Infra / Agent Eval /
Coding Agent Runtime work. Treat it as an engineering artifact, not a toy CLI.

## Project Identity

HarnessCoder is a local coding-agent runtime plus eval harness for real
repository tasks.

The core claim is reliability:

- event-sourced JSONL traces
- policy-gated tools
- context packing and compaction
- checkpoint / resume
- replay and failure reports
- fixture-backed eval suites and model comparison

Do not reposition the project as a Claude Code clone, a generic LangGraph/DAG
framework, or a UI-first app. The TUI is a control surface over the runtime; the
runtime and eval evidence are the important artifacts.

## High-Value Code Paths

- `harnesscoder/core/runner.py`: engine entrypoint. `AgentRunner.run()` creates a
  run and `_run_loop()` drives model -> policy -> tool -> state -> trace.
- `harnesscoder/core/state.py`: `AgentState`, `ModelAction`, and
  `ToolObservation`.
- `harnesscoder/core/tools.py`: tool registry and concrete local tools.
- `harnesscoder/core/policy.py`: pre-tool execution policy gate.
- `harnesscoder/core/context.py`: context packing emitted before model calls.
- `harnesscoder/core/trace.py`: append-only run trace writer.
- `harnesscoder/core/checkpoint.py`: checkpoint save/load.
- `harnesscoder/eval_runner.py`: fixture setup, verifier execution, scoring, and
  Markdown report rendering.
- `harnesscoder/tui.py`: curses control surface. Be especially careful with
  active-run concurrency.
- `eval/hc_bench_20.json`, `examples/hc_bench_20/repo`, and
  `harnesscoder/data/hc_bench_oracle.json`: HC-Bench-20 benchmark and oracle
  baseline.
- `docs/development-process.md`: durable engineering decisions and interview
  talking points.

## Current Working Rules

- Prefer small vertical slices that preserve the runtime contract.
- Every model/tool/state behavior change should remain traceable.
- Every new tool must be added consistently in:
  - tool registry
  - policy gate
  - model prompt/tool schema, if model-callable
  - trace/replay/eval metrics when relevant
  - tests
- Any state-changing action should either go through `AgentRunner` or have an
  explicit trace/audit story. Avoid hidden mutations.
- Keep local source mirrors under `~/github-upstream` read-only. Learn from them,
  but do not make feature edits there.
- Do not touch or stage `docs/papers/` unless the user explicitly asks. It is
  currently local research material.
- Do not commit `.env`, `models.toml`, `.harnesscoder/`, `__pycache__/`, eval
  workspaces, or generated local run traces.
- Preserve user changes in dirty files. If a file already has user edits, work
  with them rather than reverting them.

## TUI Safety Rules

The TUI runs agent tasks in a background thread while curses keeps refreshing.
This creates reliability hazards, so follow these rules:

- Do not allow `/quit`, `/exit`, Ctrl-C, or Ctrl-D to terminate the process while
  an agent run is active unless cancellation is implemented end-to-end.
- While a run is active, only allow read-only slash commands such as `/help`,
  `/status`, and `/trace`.
- Block or queue `/edit`, `/run`, `/test`, `/cwd`, `/model`, `/provider`,
  `/base-url`, and other commands that mutate workspace/config or block refresh.
- If cancellation is added later, it must write an explicit trace event such as
  `run_interrupted`, preserve checkpoint semantics, and handle subprocess
  termination deliberately.
- Live status should not become a hidden source of state. The final truth is the
  run trace and `RunResult`.

## Eval And Evidence Rules

- Keep eval cases structured and reproducible.
- Prefer fixture-backed cases over ad hoc examples.
- Reports should explain behavior with metrics, not just pass/fail.
- When adding a benchmark feature, include at least one verifier or replay metric
  that proves the runtime behavior.
- Keep deterministic baselines such as `scripted` and `hc-bench-oracle` working;
  they are control arms, not claims of model intelligence.
- For interview value, make failure categories and replay evidence visible.

## Experiment Scheduling Rules

For long-running experiment batches, prefer launch-and-log orchestration over
chat-window supervision.

- Use a queue runner, shell wrapper, or small scheduler that can launch the
  experiments and keep working after the conversation moves on.
- Maintain per-experiment-group logs and state files. The state model should have
  four explicit buckets: `queue`, `running`, `fail`, and `success`.
- Record stdout/stderr, command arguments, model/profile/config, start/end time,
  exit code, and report path for each group so failures can be resumed or
  explained without reconstructing them from chat.
- Store generated run artifacts under ignored local paths such as
  `.harnesscoder/experiments/` or `.harnesscoder/reports/`; do not stage them
  unless the user explicitly asks.
- When starting a batch, report the scheduler/log path and a short monitoring
  command instead of requiring the user to watch the dialogue window.

## Versioning And Commit Rhythm

- Use small local version milestones: `0.7.1`, `0.7.2`, etc.
- Update `harnesscoder/__init__.py` and `pyproject.toml` together when bumping a
  version.
- Update README and/or `docs/development-process.md` when the milestone changes
  the story, architecture, or interview talking points.
- Local git commits are enough unless the user asks for a remote push.
- Before committing, check `git status --short` and avoid staging unrelated
  files, especially local notes or research artifacts.

## Required Verification

For most code changes:

```bash
python -m unittest discover -s tests
python -m harnesscoder --version
```

For TUI changes:

```bash
python -m unittest tests.test_tui -v
python -m unittest discover -s tests
TERM=xterm-256color python -m harnesscoder --tui "Summarize this repo in one sentence"
```

Exit the TUI smoke with `/quit` after the run finishes.

For eval/report changes:

```bash
python -m harnesscoder --provider hc-bench-oracle --eval eval/hc_bench_20.json --max-iterations 8
python -m harnesscoder --eval eval/hc_bench_20.json --model-profiles scripted,hc-bench-oracle
```

Use a report path under `.harnesscoder/reports/` when you need a durable local
artifact, but do not stage generated reports unless the user asks.

## Design Lessons To Preserve

- Start deterministic, then add live models. `ScriptedModel` and
  `hc-bench-oracle` exist to isolate harness behavior from model variability.
- Trace first. If a behavior cannot be replayed or explained from trace, it is
  not a strong HC feature yet.
- Policy before execution. Tool use should be explicit, validated, and auditable.
- Context governance is a core differentiator. Search-first and bounded-read
  behavior should be measurable.
- Learn from Aider's repo map, Pico-style benchmark contracts, and OpenCode-style
  runtime surfaces, but keep HC's identity: reliability runtime + eval matrix.
- Avoid broad abstractions until a benchmark case or failure replay needs them.

## Interview Framing

When writing docs or project explanations, keep this line in mind:

> HarnessCoder is not a chat-style code assistant. It is a local coding-agent
> reliability runtime that records model decisions, policy decisions, tool
> results, state updates, checkpoints, and verifier outcomes into replayable
> traces, then evaluates those behaviors across fixture-backed coding tasks.

Good follow-up hooks:

- How do you know the agent did the right thing?
- What happens when context grows?
- What happens when a tool call is unsafe?
- Can the run resume after interruption?
- Can two model profiles be compared on the same task suite?
- How do traces explain failures, repeated reads, and policy denials?
