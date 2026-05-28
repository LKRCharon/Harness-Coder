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

## Web UI Working Rules

For `apps/web` and other runtime-console web surfaces:

- Do not place product explanations, module introductions, README-style
  summaries, or marketing copy in the main hero area of the core workspace.
- The first screen of the app shell should show current context, run state,
  available actions, and high-value runtime evidence.
- Do not keep long explanatory subtitles under the page title.
- Put explanatory copy only in onboarding, empty states, tooltips, help
  popovers, or docs panels.
- If a sentence does not help the user judge state, take an action, understand a
  local field, or inspect a result, delete it.
- Optimize developer-tool pages for repeat users, not first-time visitors.
- Prefer structure, hierarchy, labels, tables, cards, and status signals over
  paragraph explanations.
- Do not write “this page is for...” copy.
- Do not turn the dashboard into a README.

## Web Workbench Direction

For the main HarnessCoder web product direction, prefer `Runtime Workbench` over
`Run Console` or dashboard-style history browsing.

### Information Architecture

- The top-level shell should be an app shell, not a dashboard.
- Do not make the first screen a stats header plus run cards.
- The primary question on entry is not “how many runs exist” but “what can the
  agent do now, what is it doing, and what evidence does it have”.
- Prefer a three-column workbench:
  - left: project / threads / navigation
  - center: thread view and live runtime flow
  - right: inspector rail for environment, plan, files, trace, context, and
    artifacts
- Keep the launcher anchored at the bottom as the main composer.

### Core Mental Model

- Model the primary UX around `threads`, not raw `runs`.
- A thread is the user-facing task conversation; a thread may contain multiple
  runs.
- Runs are execution records and evidence surfaces under a thread, not the main
  navigation primitive.
- The center column should feel like an agent thread, not a report page or log
  browser.

### Center Column

- The center column is the core product surface.
- Show user task messages as the main input history.
- Show agent output as structured runtime responses, not generic chat bubbles
  and not raw event dumps.
- Prefer these block types:
  - user message
  - agent summary
  - runtime block
- Runtime blocks may contain:
  - task understanding
  - plan
  - active step
  - tool call
  - shell command
  - file change
  - test result
  - approval request
  - failure reason
  - final summary
  - next-step suggestion
- Preserve a timeline feel, but do not let the center pane become a scrolling
  waterfall of low-level logs.

### SSE Presentation

- SSE is runtime evidence, not a raw log feed.
- Do not stream every event directly into the main UI.
- Present SSE in three layers:
  - status line
  - grouped, human-readable event summaries
  - raw trace stream in a debug-oriented trace view
- Default-visible runtime events should be the ones a human can act on or learn
  from quickly.
- Raw trace JSON belongs in a drawer, inspector tab, or debug panel, not the
  main thread body.

### Launcher

- The launcher is a task composer, not a form.
- The launcher should live at the bottom of the thread view.
- The main interaction is “give the agent a task in natural language”.
- Default-visible controls should stay minimal; expose only the most important
  parameters in the main bar.
- Put advanced options into a settings popover or expandable advanced section.
- Prefer default-visible parameters like:
  - mode
  - model profile
  - permission level
  - send action
- Candidate advanced parameters:
  - max iterations
  - notes mode
  - context source or budget
  - branch or worktree strategy
  - test command
  - allowed tools
  - auto commit
  - auto PR
- Do not make the launcher feel like a CI job form or Jenkins config screen.

### Permission UX

- Permission level is first-class UI, not an advanced setting.
- The user must be able to see and change permission scope from the main
  launcher surface.
- Prefer a small, clear set of permission levels such as:
  - read only
  - safe edit
  - full access
- Permission labels should make it obvious how they constrain reads, edits,
  commands, and approvals.

### Left Sidebar

- The left rail should be a compact thread list, not a board of large run cards.
- Useful contents:
  - current project
  - new thread action
  - thread list
  - lightweight filters
- Each thread row should stay dense and scannable:
  - title
  - status dot
  - recent time
  - small badges for approval, diff, or unread activity
- Favor compact rows over expressive cards.
- The sidebar should be collapsible, especially for smaller screens.

### Top Bar

- The top bar should be low-profile and global, similar in spirit to a code
  editor title bar.
- Show only high-value persistent state:
  - project
  - branch
  - work mode
  - connection status
  - environment status
  - git change counts
  - settings entry
- Do not turn the top bar into a hero header.

### Right Inspector

- The right column is an inspector rail, not a decorative info card area.
- It should stay persistent and operational.
- Prefer tabs such as:
  - Overview
  - Plan
  - Files
  - Trace
  - Context
- It should automatically surface the most important evidence for the current
  state, for example:
  - approval card when waiting for permission
  - changed files when diff exists
  - artifact preview when a report or file is produced
- The inspector should help the user check, approve, compare, and continue.

### Visual Language

- Prefer Codex-like workbench layout with One Dark Pro-like color sensibility.
- Keep the product dark by default for long-running local engineering work.
- Do not make the main thread pane uniformly black.
- Use layered dark surfaces:
  - page background darkest
  - thread surface slightly lighter
  - message and runtime blocks lighter still
  - code, command, and trace surfaces darker again for contrast
- Use status colors as sparse semantic accents, not decorative highlights.
- The right inspector should feel closer to an editor sidebar or panel than to a
  floating dashboard widget.

### Product Expression

- Prefer structured evidence over explanatory prose.
- Prefer a workbench that drives and inspects agent execution over a page that
  summarizes the product.
- The main `/workbench` or `/threads` experience should foreground:
  - current task
  - current runtime phase
  - approvals
  - changed files
  - tests
  - trace and context evidence
- Historical stats can exist, but should not dominate the initial viewport or
  the primary navigation model.

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
