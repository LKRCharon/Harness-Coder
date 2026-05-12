# Development Process Notes

This document records engineering decisions, bugs, debugging traces, and
interview-ready lessons from building HarnessCoder. It is intentionally more
process-oriented than the README: the README explains what the project is, while
this file explains what problems appeared during development and how they were
handled.

## How To Use This Document In Interviews

When asked "what problems did you run into while building this project?", answer
from the pattern below:

1. Start from the system goal: HarnessCoder is an event-sourced coding-agent
   runtime, not only a CLI wrapper around an LLM.
2. Pick one concrete issue from this document.
3. Explain the root cause, the tradeoff, and the fix.
4. Connect it back to agent reliability: reproducible traces, policy gating,
   controlled tool execution, or robust model-output parsing.

## Project Direction Decisions

### 1. Dynamic Agent Loop Instead Of DAG Runtime

Problem:
Coding-agent tasks are not naturally fixed workflows. The next useful action
depends on repository state, command output, read results, policy decisions,
failures, and the model's evolving plan.

Decision:
The core runtime is a dynamic loop:

```text
state -> model action -> policy decision -> tool result -> state update
      -> next model action
```

Eval can still be workflow-shaped around the agent:

```text
setup repo -> run agent -> run tests -> collect trace -> score -> report
```

Interview angle:
This avoids forcing coding behavior into a static DAG too early. The harness
keeps the agent loop flexible while making every step auditable through JSONL
events.

### 2. ScriptedModel Before Real LLM

Problem:
If the first implementation calls a live LLM immediately, debugging becomes
mixed with model availability, API shape, token behavior, and network failures.

Decision:
The MVP began with `ScriptedModel`, a deterministic fake model that emits tool
actions. This let the runtime, policy, tools, state update, and trace writer be
validated before adding a real provider.

Interview angle:
This is a classic isolation move: first prove the harness semantics with a
deterministic model, then plug in real model adapters behind the same
`next_action(state)` interface.

### 3. Event-Sourced JSONL Trace As The Core Artifact

Problem:
Agent failures are hard to debug if only final stdout is preserved. For a coding
agent, we need to know what the model decided, what policy allowed or denied,
what tool actually ran, and how state changed.

Decision:
Every run writes append-only JSONL under:

```text
.harnesscoder/runs/<run_id>/trace.jsonl
```

The MVP trace includes:

- `run_started`
- `model_action`
- `policy_decision`
- `tool_result`
- `state_updated`
- `model_error`
- `run_finished`

Interview angle:
The trace is the foundation for replay, checkpoint/resume, eval scoring, and
failure analysis. It turns agent behavior from an opaque conversation into a
structured execution log.

## Runtime And Tooling Issues

### 4. Empty Skeleton, No Git Repo

Symptom:
The project directory initially only had empty folders:

```text
core/
docs/
eval/
examples/
replay/
```

and was not a git repository.

Fix:
Create the Python package from scratch under `harnesscoder/` instead of treating
the existing `core/` folder as already-designed source. Keep the first slice
small: state, runner, trace, tools, policy, CLI, README.

Interview angle:
The important part was avoiding a large architecture draft. The first milestone
was a runnable vertical slice.

### 5. Local Tool Output Polluted By `__pycache__`

Symptom:
After running compile and smoke tests, `find` results included Python cache
files, and the scripted summary listed `__pycache__` paths.

Fix:
Adjust the file-listing command used by `ScriptedModel` to exclude:

```text
*/__pycache__/*
```

Interview angle:
Even small local tools need output hygiene. Agent observations are future model
context, so noisy observations can degrade later decisions.

### 6. Shell Quoting Difference Between Manual Commands And Tool Execution

Symptom:
A manual shell check with:

```bash
find . -maxdepth 3 -type f -not -path ./.harnesscoder/* -not -path */__pycache__/*
```

failed because the shell expanded the unquoted wildcard.

Why it did not break the agent:
`run_command` uses `subprocess.run(parts, shell=False)`, so the agent does not
run through shell glob expansion.

Fix:
Keep `run_command` shell-free and quote wildcard paths in manual debugging
commands.

Interview angle:
This is why the tool runner avoids `shell=True`. It reduces injection risk and
removes a class of shell expansion surprises.

### 7. macOS Locale Assumption

Symptom:
The first `run_command` environment set:

```text
LC_ALL=C.UTF-8
LANG=C.UTF-8
```

This can be less portable on macOS, where `C.UTF-8` is not always available.

Fix:
Use:

```text
PYTHONUTF8=1
```

instead of forcing a system locale.

Interview angle:
The harness should be local-first and Mac-friendly. Avoid assuming Linux-only
locale names when the user target is macOS.

## Policy And Safety Issues

### 8. MVP Policy Was Too Blunt Around Git

Problem:
The first policy blocked `git` completely as a potentially dangerous command.
But real coding-agent repo inspection often needs read-only commands like:

```text
git status
git diff
git log
git show
git ls-files
```

Fix:
Allow only a small set of read-only git subcommands and continue blocking risky
commands by default.

Interview angle:
The policy layer should not be "allow everything" or "block everything." It
should encode operation classes: read-only inspection, workspace mutation,
network access, and destructive actions.

### 9. Explicit Policy Decision Events

Problem:
If a tool call is denied but the trace only records a generic tool failure, it
is hard to tell whether the problem was the model, the policy, or the tool.

Fix:
Write a separate `policy_decision` event before `tool_result`.

Interview angle:
This separation is useful for eval too. A failed task caused by policy denial is
different from a failed task caused by a broken tool or bad model reasoning.

## OpenAI-Compatible Provider Issues

### 10. Do Not Store API Keys In The Repo

Problem:
The real model provider needs an API key, but this is an interview project and
may become public or be shared.

Decision:
Do not commit secrets. Read the key from:

```text
OPENAI_API_KEY
```

Support local `.env`, and keep `.env` ignored by git.

Interview angle:
This is not just security hygiene. A reproducible local harness should separate
runtime configuration from source code.

### 11. `.env` Must Load Before Argparse Defaults

Symptom:
The CLI originally read environment variables while constructing argparse
defaults. If `.env` was loaded after argument parsing, values like
`OPENAI_API_KEY` or model config would not affect defaults.

Fix:
Load `.env` before building the parser:

```text
load_dotenv_for_argv(argv)
build_parser()
```

It loads `.env` from the current directory and from `--cwd` when different.

Interview angle:
Configuration loading order matters. CLI defaults backed by environment
variables must see the final environment before parser construction.

### 12. Base URL Normalization For Sub2API

Problem:
OpenAI-compatible proxies differ on whether users configure:

```text
https://api.dest.space
```

or:

```text
https://api.dest.space/v1
```

Fix:
Normalize the base URL so the adapter calls:

```text
<base>/v1/responses
```

if `/v1` is not already present.

Interview angle:
This avoids `/v1/v1` bugs and makes the local harness friendlier to different
OpenAI-compatible proxy conventions.

### 13. Missing Model Name Should Fail Early

Symptom:
The API key existed in `.env`, but no model was configured.

Fix:
Require one of:

```text
HARNESSCODER_OPENAI_MODEL
OPENAI_MODEL
--openai-model
```

and fail before making a network request if the model name is missing.

Interview angle:
Fail fast on incomplete configuration. It saves time and produces a clear error
instead of a vague provider-side failure.

### 14. Sandbox DNS Failure Was Not A Code Bug

Symptom:
The first live request to:

```text
https://api.dest.space
```

failed with DNS resolution inside the sandbox:

```text
nodename nor servname provided, or not known
```

Fix:
Rerun the exact command with network escalation. The next result reached the
server, proving the first failure was environmental rather than a code-level API
bug.

Interview angle:
When debugging API integration, separate local sandbox/network problems from
actual provider or adapter bugs.

### 15. Cloudflare Blocked Default Python Client Signature

Symptom:
After network access worked, the provider returned:

```text
HTTP 403
Cloudflare Error 1010
browser_signature_banned
```

Root cause:
The request reached `api.dest.space`, but Cloudflare blocked the default Python
HTTP client signature.

Fix:
Set an explicit user agent:

```text
User-Agent: HarnessCoder/0.1
```

After this change, the request reached the model backend.

Interview angle:
This is an example of an integration bug outside the core algorithm. The fix was
small, but the important step was distinguishing DNS, edge-layer blocking, and
model-response parsing.

### 16. Real Model Returned Duplicate JSON Actions

Symptom:
`gpt-5.5` returned a valid JSON action twice in one response:

```text
{...}{...}
```

Strict `json.loads()` failed, even though the first object was usable.

Fix:
Use `json.JSONDecoder().raw_decode()` as a fallback to parse the first complete
JSON object from the model output.

Interview angle:
LLM outputs are probabilistic even under strict prompting. A production harness
should validate model actions strictly but tolerate common formatting noise when
safe.

### 17. Live `gpt-5.5` Run Confirmed The Full Loop

Command:

```bash
python -m harnesscoder \
  --provider openai-codex \
  --openai-base-url https://api.dest.space \
  --openai-model gpt-5.5 \
  "看一下这个 repo 是做什么的"
```

Result:

```text
status: success
run_id: run_2b81f31259c6
```

The trace showed multiple model/tool turns with `run_command`, `read_file`, and
final answer generation.

Interview angle:
At this point the project was no longer only a fake runtime. The real loop was:

```text
sub2api gpt-5.5 -> model_action JSON -> policy gate -> local tool
-> observation -> next model_action -> trace
```

## Reference Project Analysis

### 18. MiniClaudeCode And Audit CLI: What To Learn, What Not To Copy

Question:
Should HarnessCoder learn from a MiniClaudeCode-style coding-agent CLI and an
Audit CLI for agent regression evaluation?

Decision:
Yes, but selectively.

Overlap with MiniClaudeCode:

- agent loop and tool abstraction
- permission modes
- context compression
- CLI runtime
- read-before-edit and mtime checks
- project instruction injection

Overlap with Audit CLI:

- run trace statistics
- tool-call count
- token and cost tracking
- failed or repeated tool calls
- static checks such as pytest, ruff, mypy, bandit
- regression reports

Boundary:
HarnessCoder should not become only a Claude Code clone. Its differentiator is
the runtime/harness layer: event sourcing, replay, checkpoint/resume, policy
gating, and eval.

Interview angle:
The project learned from existing coding-agent CLI patterns but scoped them into
a harness architecture. MiniClaudeCode informs runtime ergonomics; Audit CLI
informs eval and reporting.

## Current Talking Points

### 19. TUI Before Full Interactive Agent Product

Problem:
The project needs an interface that feels closer to real coding agents such as
Claude Code or CoreCoder, but building a polished clone too early would distract
from the runtime/harness goal.

Decision:
Add a small standard-library `curses` TUI first. It supports normal messages,
slash commands, model/provider switching, direct tool calls, and a simple ASCII
runtime diagram:

```text
[message] -> [model] -> [policy] -> [tools] -> [trace]
```

Current commands include:

```text
/help
/status
/model gpt-5.5
/model scripted
/provider openai-codex
/base-url https://api.dest.space
/read README.md
/search HarnessCoder
/run git status --short
/trace latest
```

Boundary:
Each normal message currently runs a standalone agent task and writes its own
trace. This is enough for MVP interaction, while true persistent conversation
state, streaming tool updates, and trace browsing can be added later.

Interview angle:
The TUI is not the core differentiator. It is a practical control surface over
the harness: send messages, switch models, invoke tools, and expose traces
without hiding the event-sourced runtime underneath.

### 20. Curses Cursor Support Is Terminal-Dependent

Symptom:
The first pseudo-terminal smoke test for `python -m harnesscoder --tui` failed
with:

```text
_curses.error: curs_set() returned ERR
```

Root cause:
Some terminal environments do not support changing cursor visibility even though
they support enough curses features to run the UI.

Fix:
Treat `curses.curs_set(1)` as best-effort and catch `curses.error`.

Interview angle:
Terminal UI development has environment-dependent behavior. The fix was not to
add a dependency, but to make optional terminal features degrade gracefully.

### 21. TUI Should Expose Trace, Not Hide It

Problem:
An interactive UI can accidentally make the system feel like a black-box chat
client, which works against HarnessCoder's event-sourced harness goal.

Fix:
Add `/trace [latest|run_id|path]` so the TUI can summarize event counts and
recent events from `trace.jsonl`.

Interview angle:
The UI is a control surface over the harness. A good HarnessCoder interface
should keep traces visible because traceability is the core product idea.

If asked "what was the hardest part?", good answers are:

- Making model decisions structured enough for tools while still tolerating
  real LLM formatting noise.
- Separating model failures, policy denials, tool failures, and environment
  failures in the trace.
- Keeping the first milestone narrow enough to run end-to-end before adding
  edit tools, replay, or eval.
- Treating the runtime as an event-sourced system so future checkpoint/resume
  and failure replay are natural extensions.

If asked "what would you do next?", good answers are:

- Add edit tools with read-before-edit and mtime checks.
- Add context packing and compaction events.
- Add replay from `trace.jsonl`.
- Add an eval harness that runs tasks, tests the repo, scores traces, and
  compares regressions.
- Add policy profiles such as plan-only, accept-edits, and bypass-permissions.

## 0.2.0 Milestone

### 22. Edit And Test Tools Are Separate From Generic Commands

Problem:
If every model action uses `run_command`, test execution and file mutation are
hard to distinguish in traces and policy decisions.

Decision:
Add explicit `edit_file` and `run_tests` tools. `edit_file` only supports exact
old/new replacement and requires the old text to match exactly once. `run_tests`
is a narrower test-command wrapper for Python unittest/pytest style commands.

Interview angle:
This makes tool intent machine-readable. An eval report can now separate
repository inspection, mutation, and verification instead of treating every
local operation as an opaque shell command.

### 23. Trace Replay Became A First-Class Artifact

Problem:
A trace is useful only if the project can turn it back into a summary without
manual JSONL inspection.

Decision:
Add `harnesscoder.replay` with APIs to load traces, reconstruct final state, and
summarize event counts, tool counts, policy denials, failed tools, modified
files, timing, and final answers.

Interview angle:
Replay is the bridge between runtime and eval. It turns "the agent ran" into
"we can audit what happened and score behavior over time."

### 24. Eval Produces A Report, Not Just A Pass/Fail Exit Code

Problem:
For an interview project, the strongest artifact is not a one-off successful
demo. It is a report that compares runs and exposes traces.

Decision:
Add `harnesscoder.eval_runner` and `eval/cases.json`. Each case runs the agent,
executes a test command, counts trace tool usage, scores the result, and renders
a Markdown report.

Interview angle:
This is the first concrete version of the "Agent Runtime + Eval Harness"
positioning. The project can now show a trace-backed eval report, even before
larger benchmark suites and failure fixtures exist.

## 0.2.0 Spec Audit

Against the reliability spec, 0.2.0 was directionally correct but incomplete.

Implemented:

- Dynamic event-sourced loop with `model_action`, `policy_decision`,
  `tool_result`, `state_updated`, and `run_finished`.
- Policy-gated tools, including explicit `edit_file` and `run_tests`.
- JSONL trace replay summary and a first eval report.
- Basic modified-file tracking through `edit_file` metadata.

Gaps:

- No `context_packed` event or context layers.
- No checkpoint/resume.
- `run_tests` existed as a tool, but eval test results were not yet normalized
  as `test_result` trace events.
- No failure category metrics beyond failed tools and policy denials.
- `AgentState` did not yet carry phase, file summaries, last error, open
  questions, or budget.

Conclusion:
0.2.0 was a good replay/eval foundation, but not yet the reliability runtime
described by the full spec.

## 0.3.0 Milestone

### 25. Context Packing Became Traceable

Problem:
Without an explicit context-packing event, the runtime cannot explain what the
model was shown when older observations are folded out of hot context.

Decision:
Add `context_packed` before each model decision. The record separates hot
context, working memory, cold trace summary, and budget.

Interview angle:
This is the first concrete answer to "what happens when context grows?" The
system can show what it kept hot and what it summarized.

### 26. Checkpoint And Resume Became Concrete

Problem:
0.2.0 could replay a finished trace, but it could not continue an interrupted
run.

Decision:
Persist `checkpoint.json` after state updates and add resume support that
appends `run_resumed` to the same trace.

Interview angle:
This moves checkpoint/resume from a README promise into an auditable runtime
surface.

### 27. Eval Metrics Now Come From Replay

Problem:
Eval reports should not maintain a separate understanding of traces.

Decision:
Eval appends normalized `test_result` events, replays the trace, and uses the
replay summary for failure category and metrics such as repeated reads, invalid
tool calls, context packs, and checkpoints.

Interview angle:
Replay is now the source of truth for both debugging and scoring.

## 0.4.0 Milestone

### 28. Real Bugfix Loop, Not Only Repo Orientation

Problem:
Earlier releases could inspect a repo, write traces, replay failures, and score
evals, but the strongest interview proof still requires a concrete code-change
loop: failing test, diagnosis, edit, rerun, pass.

Decision:
Add `examples/bugfix_demo/repo`, a tiny Python fixture where
`math_utils.add_one` returns the wrong value. `eval/bugfix_cases.json` asks a
real model to fix the failing unittest, run `python -m unittest discover`, and
finish only after tests pass.

Interview angle:
This is the first "agent generated code under harness control" milestone. The
project can now show `run_tests -> search/read -> edit_file -> run_tests ->
finish` in a replayable trace.

### 29. Fixture Evals Run In Copied Workspaces

Problem:
If evals edit fixture directories directly, the first successful bugfix destroys
the failing baseline and makes the demo non-reproducible.

Decision:
Add optional `repo_fixture` support to eval cases. When present, the eval runner
copies the fixture into:

```text
.harnesscoder/eval-workspaces/<case_id>/<timestamp>/repo
```

and runs the agent there. Reports include the copied workspace path and trace.

Interview angle:
This is a small but important eval-harness detail. Reliable evals need a fresh
repo setup per case, otherwise pass/fail numbers silently depend on previous
runs.

## 0.5.0 Milestone

### 30. Model Profiles Separate Runtime Config From Eval Logic

Problem:
Comparing models by manually changing CLI flags is hard to reproduce. It also
makes reports ambiguous because a run says which provider was used, but not the
named eval profile the candidate intended to compare.

Decision:
Add TOML model profiles. A profile stores provider, model name, base URL, API key
environment variable name, timeout, and output-token budget. Secrets remain in
the environment.

Interview angle:
This turns "I tried another model" into an auditable eval axis. The same task
and fixture setup can now be run against named model profiles.

### 31. Eval Matrix Is The Project's Strongest Demo Artifact

Problem:
A single successful bugfix is useful, but interviewers can still read it as a
demo. The project needs a report shape that naturally invites deeper questions
about runtime reliability and eval design.

Decision:
Add matrix mode:

```bash
python -m harnesscoder \
  --model-profiles scripted,openai_codex \
  --eval eval/bugfix_cases.json
```

The report compares pass rate, test pass rate, average tool calls, repeated
reads, invalid tool calls, policy denials, tool failures, and failure
categories. Every cell still points back to per-run traces.

Interview angle:
The differentiator is now visible: HarnessCoder is not just invoking a model to
write code. It is measuring model behavior under the same tool policy, fixture
setup, and replay metric pipeline.

## 0.6.0 Milestone

### 32. Greenfield Is Added As A Harnessed Capability, Not A Product Pivot

Problem:
0.5.0 could prove a real bugfix loop, but it could not create files from an
empty fixture. That makes the answer to "can it write code from zero?" too weak.

Decision:
Add `write_file(path, content, overwrite=false)` and a greenfield eval case. The
case starts from a fixture that only has a README, asks the model to create a
small Python module and unittest file, then validates the result with both
`python -m unittest discover` and a separate verifier command.

Interview angle:
This is a deliberately small greenfield slice. It proves file creation and
verification without pretending to be a full app generator.

### 33. Pico-Inspired Constraints, HarnessCoder-Style Evidence

Problem:
Pico has a useful benchmark style: fixture repo, allowed tools, step budget, and
verifier. HarnessCoder should learn from that without losing its own identity as
a trace/replay/eval-matrix runtime.

Decision:
Add `allowed_tools`, `step_budget`, and `verifier` to eval cases. Tool
constraints are enforced by `ToolPolicy`, step budget maps to the agent loop
limit, and verifier results are appended to the same trace as structured
`verifier_result` events.

Interview angle:
The project can now say: "I borrowed the right benchmark contract ideas, but the
core artifact is still HarnessCoder's event-sourced run trace and comparable
matrix report."

## 0.7.0 Milestone

### 34. HC-Bench-20 Turns The Demo Into A Benchmark

Problem:
0.6.0 proved bugfix and greenfield loops, but each loop had only one case. That
was enough for a demo and not enough for an interview-ready eval story.

Decision:
Add `eval/hc_bench_20.json` with 20 fixture-backed local cases. The suite covers
bugfix, recovery, greenfield, context, and policy categories. Each case declares
allowed tools, a step budget, a focused test command, and a verifier that
inspects the resulting trace.

Interview angle:
This shifts the conversation from "can the agent solve a toy task?" to "can the
runtime compare model behavior across meaningful failure modes?"

### 35. The Oracle Provider Is A Harness Baseline, Not A Model Baseline

Problem:
A 20-case benchmark needs a stable way to prove that failures come from the
model/profile under test, not from broken fixtures or report plumbing.

Decision:
Add `hc-bench-oracle`, a deterministic provider backed by
`harnesscoder/data/hc_bench_oracle.json`. It executes known-good actions for the
HC-Bench cases and is used to validate the harness, reports, policy metrics, and
trace verifiers.

Interview angle:
The oracle is intentionally not "the coding agent." It is the control arm. Real
model profiles can be compared against it in the same matrix report.

### 36. Reports Now Aggregate By Category

Problem:
Raw pass rate hides why an agent failed. For interview use, category-level
signal is more valuable than a single aggregate number.

Decision:
Add category summaries to both normal eval reports and matrix reports. The
report now breaks down pass rate, test pass rate, verifier pass rate, average
tool calls, policy denials, and failure categories by benchmark category.

Interview angle:
This makes follow-up questions natural: "which models fail recovery tasks?",
"does the agent over-read large files?", "are policy denials expected or
regressions?"

## 0.7.1 Milestone

### 37. TUI Live Refresh Without Changing The Runtime Contract

Problem:
The 0.7.0 TUI could run the agent, but the screen blocked until the run
finished. That made long tasks feel opaque even though the runtime was already
writing useful trace events.

Decision:
Run each normal TUI message in a background thread, keep the curses loop
refreshing every 100ms, and render a compact live status line from the newest
trace event. The TUI now shows elapsed time, run id when available, and the
latest lifecycle event such as `model_action`, `policy_decision`, `tool_result`,
`state_updated`, or `run_finished`.

Interview angle:
This is a small but realistic agent-product detail: streaming UI does not need
to change the agent loop. It can be built by observing the same event-sourced
trace that powers replay and eval.

### 38. Adaptive Terminal Rendering

Problem:
The original TUI assumed enough terminal height for a fixed four-line header.
Small panes could squeeze the message area and make the interface feel brittle.

Decision:
Make the header return its actual height, collapse metadata into one line on
short terminals, use a shorter pipeline label on narrow terminals, and fall back
to a two-line compact mode for very small panes.

Interview angle:
The TUI remains standard-library only, but it behaves like a real terminal tool:
the control surface adapts to the user's pane instead of requiring one perfect
terminal size.
