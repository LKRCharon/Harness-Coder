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

### 3.1. Small Control Plane Instead Of Multi-Platform Gateway

Problem:
Hermes-style Gateway architecture has a useful lesson: user entrypoints and
agent runtime should be separated. But copying the product shape would send HC
in the wrong direction. HarnessCoder does not need Telegram, Discord, email, or
web gateways before the local runtime is reliable.

Decision:
Keep the entrypoints local:

```text
CLI / TUI / Eval
-> run control
-> runner
-> trace/checkpoint
-> replay/eval report
```

The first runtime control slice is `harnesscoder/core/control.py`. It centralizes
active-run rules that apply across entrypoints:

- do not start a second run while one run is active;
- do not exit during an active run until cancellation is implemented;
- while a run is active, only allow read-only commands such as `/help`,
  `/status`, and `/trace`.

Interview angle:
This keeps HC's identity as a reliability runtime, not a platform gateway. The
control plane is about run lifecycle, status, trace inspection, interrupt,
resume, approval, and active-run protection. UI code should render those
decisions, while trace/checkpoint/replay remain the source of truth.

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

### 5.1. Large Tool Outputs Need Artifact Storage, Not Blind Truncation

Symptom:
Long test output or search output can overflow the live prompt, but plain
truncation destroys evidence that replay and failure analysis may need later.

Decision:
Keep tool-level redaction in `ToolRegistry`, then let `AgentRunner` persist
large observations under the run directory before appending them to state and
trace. The trace keeps a bounded preview plus metadata such as raw character
count, preview character count, artifact path, and SHA-256 hash. Replay and eval
reports aggregate raw output volume, stored artifact count, largest output size,
artifact integrity, and observation compression ratio. Artifact storage also
does a second generic redaction pass and records `artifact_error` instead of
crashing the run if the local filesystem write fails.

Interview angle:
This turns context hygiene into an auditable runtime behavior: the model sees a
bounded observation, while the evaluator can still inspect the full output and
explain whether a failure came from noisy tools, lost evidence, or model
decisions.

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
https://your-openai-compatible-endpoint.example
```

or:

```text
https://your-openai-compatible-endpoint.example/v1
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
https://your-openai-compatible-endpoint.example
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
The request reached the OpenAI-compatible endpoint, but the edge layer blocked the default Python
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
A real model returned a valid JSON action twice in one response:

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

### 17. Live Real-Model Run Confirmed The Full Loop

Command:

```bash
python -m harnesscoder \
  --provider openai-codex \
  --openai-base-url https://your-openai-compatible-endpoint.example \
  --openai-model your-model-name \
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
real model -> model_action JSON -> policy gate -> local tool
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
/model your-model-name
/model scripted
/provider openai-codex
/base-url https://your-openai-compatible-endpoint.example
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

## 0.8.3 Milestone

### 39. Context Packs Now Reach The Live Model Prompt

Problem:
`context_packed` was useful trace evidence, but the real model adapter still
received only a compact state view. That meant context governance was observable
but not actually steering model input.

Decision:
Add a context assembly layer with `--context-mode none|pack|memory`. The
assembly combines system instructions, task contract, packed context, recent
observations, and available tools. `openai-codex` now builds its Responses API
payload from this assembly, while scripted and oracle providers remain
deterministic control arms.

Interview angle:
This turns context governance from "we logged a summary" into a measurable
prompting strategy that can be ablated.

### 40. Task-Local Memory Is Trace-Backed, Not Long-Term Memory

Problem:
A coding agent needs working memory during a task, but adding a broad memory
platform would distract from the 1.0 harness story.

Decision:
Add task-local memory blocks:

```text
task/failing_tests
task/explored_files
task/relevant_symbols
task/patch_summary
task/verified_facts
task/open_questions
```

The reducer updates these blocks from tool results, writes `memory_updated`
events, and injects `<working_memory>...</working_memory>` only in
`--context-mode memory`.

Interview angle:
The memory design is deliberately scoped. It is not a product claim about
personal memory; it is a way to make one coding run easier to audit and
optimize.

### 41. Compression Metrics Are First-Class Eval Signals

Problem:
"Compression" can become hand-wavy if the harness only says it summarized
context. The eval story needs concrete measurements.

Decision:
Replay and reports now expose estimated context tokens, compression count, hot
observation count, cold summary chars, repeated reads, time to first edit,
search-to-edit steps, and edit-to-test steps. Matrix reports include context
injection, estimated tokens, memory updates, and compression counts by profile.

Interview angle:
This lets the project explain whether context governance changes behavior, not
just whether a final answer passed.

## 0.8.4 Milestone

### 42. DeepSeek Uses A Chat Completions Provider, Not A Responses Gateway

Problem:
HarnessCoder's first real-model adapter was `openai-codex`, which calls the
Responses API. DeepSeek's public API is OpenAI-compatible at the Chat
Completions layer, so forcing it through a Responses gateway would add an extra
failure source to eval results.

Decision:
Add a generic `openai-chat` provider. It uses the same model-decision prompt and
JSON action parser as `openai-codex`, but sends payloads to
`/chat/completions` with `messages`, `max_tokens`, and `stream=false`.
DeepSeek is configured as a local model profile:

```toml
[models.deepseek]
provider = "openai-chat"
model = "deepseek-v4-pro"
base_url = "https://api.deepseek.com"
api_key_env = "DEEPSEEK_API_KEY"
```

Interview angle:
This keeps the harness honest. Direct provider support makes model failures,
prompt failures, and tool-loop failures easier to separate than a hidden gateway
translation layer.

### 43. Codex Reasoning Effort Is A Runtime Setting

Problem:
When comparing Codex-style profiles, `high` versus `xhigh` reasoning should be a
runtime-controlled variable, not a remembered CLI detail. Hermes handles this
well: config/commands are normalized first, then the Codex transport translates
the value into the provider-specific Responses payload.

Decision:
Add `reasoning_effort` for `openai-codex` only. The supported values are
`none`, `minimal`, `low`, `medium`, `high`, and `xhigh`; `minimal` is sent as
`low` for Responses API compatibility. The value can come from
`--reasoning-effort`, `HARNESSCODER_REASONING_EFFORT`, `models.toml`, or the TUI
`/reasoning` command. `openai-chat` rejects profile-level reasoning config and
does not send a reasoning field, which keeps DeepSeek's Chat Completions path
clean.

Trace/eval effect:
`run_started.model_metadata` records the provider, model, configured
`reasoning_effort`, and effective Responses effort without API keys. Replay
surfaces `model_metadata`, and the eval matrix summary includes a `Reasoning`
column so high/xhigh runs can be compared without guessing from command history.

Interview angle:
This is a small but real runtime-control feature. The model does not decide its
own reasoning level; the runtime receives a profile/CLI/TUI setting, validates
it, applies provider-specific translation, and records it in trace for later
attribution.

## 0.9.0 Milestone

### 44. RepoMap Makes Repository Context A Governed Input

Problem:
Search and bounded reads are useful, but larger repositories still need a
compact map of likely-relevant files and symbols. Pulling in a full external
repo-map implementation would blur the harness story and make evaluation harder
to explain.

Decision:
Add a clean-room `harnesscoder/core/repo_map.py`. It indexes text files while
omitting local secrets such as `.env` and `models.toml`, extracts Python imports,
classes, functions, and signatures through `ast`, falls back to regex symbols
for other text files, ranks entries by query overlap, and renders within
`max_tokens` / `max_files` bounds.

The runtime exposes this as both:

```text
repo_map(query=None, max_tokens=1200, refresh=False)
```

and prompt injection for `--context-mode pack|memory` when
`--repo-map-mode auto` is enabled. Traces record `repo_map_built` and
`repo_map_used`, replay metrics count RepoMap use/injection, and matrix reports
surface those metrics.

Interview angle:
RepoMap is not "another feature"; it is the repository-level context governance
layer. It lets the project explain whether the agent found the right file
sooner, used fewer broad reads, or changed tool behavior under an ablation.

## 0.9.1 Milestone

### 45. Showcase Docs Turn Eval Evidence Into An Interview Story

Problem:
The runtime and benchmark evidence existed, but an interviewer should not need
to reconstruct the architecture, replay story, or failure attribution story from
raw source files and reports.

Decision:
Add `docs/showcase.md` and `docs/architecture.md`. The showcase doc summarizes
the 1.0 thesis, HC-Bench-20 oracle evidence, real-model matrix evidence,
RepoMap ablation evidence, replay example, and failure attribution example. The
architecture doc gives the event-sourced loop, context-governance layers, trace
event taxonomy, and eval flow with Mermaid diagrams.

README now opens with the four durable pillars:

```text
event-sourced agent loop
policy-gated tools
trace/replay/eval
context governance: memory + compression + RepoMap
```

Interview angle:
This makes the project legible as agent infrastructure: measurable, auditable,
recoverable, and optimizable, rather than a loose pile of features.

## 1.0.0 Milestone

### 46. Interview Release Means Reproducible Evidence And Public Hygiene

Problem:
A project can have strong internal evidence and still fail as a portfolio
artifact if it lacks a license, CI, a release checklist, or clear non-goals.

Decision:
Cut the 1.0 surface around the original thesis:

```text
trace-backed coding agent harness with real-model eval, task-local memory,
context compression, and repo-level context governance
```

Add an MIT license, GitHub Actions CI for unit tests plus HC-Bench-20 oracle,
`docs/release-checklist.md`, and `docs/spec-1.0.0.md`. Keep `.env`,
`models.toml`, and `.harnesscoder/` ignored and local. Public docs use generic
model and endpoint placeholders.

Interview angle:
1.0 is not a bigger feature set. It is a clean release boundary: reproducible,
auditable, benchmarked, and safe to show.

## 1.2.1 Milestone

### 47. HC-Bench-40 Expands Heldout Coverage Without Polluting Train Data

Problem:
HC-Bench-20 was useful as a compact interview benchmark, but real-model results
quickly showed that 20 cases are too small to stress different failure modes.
At the same time, HC-Train-40 already exists as a training trace pool, so simply
renaming it as a benchmark would destroy the train/eval boundary.

Decision:
Add `eval/hc_bench_40.json` and `harnesscoder/data/hc_bench_40_oracle.json`.
The suite keeps all HC-Bench-20 cases for backward-compatible comparison and
adds 20 new heldout cases with `split=heldout` and
`source=synthetic-microbenchmark`. The new cases are inspired by public
benchmark patterns rather than copied from them:

- TRAJECT-Bench's lesson: evaluate the tool trajectory, not only final output.
- ProgramBench-style lesson: include harder programming and parser edge cases
  where the agent must infer behavior from tests.
- SWE-style lesson: keep repo fixture isolation, tests, and verifier contracts as
  the evidence boundary.

The added coverage includes algorithm/programming repairs, recovery cases that
require a failed test and a second patch, greenfield helper modules, large-file
context lookup tasks, and policy/security cases. The deterministic oracle covers
all 40 cases so harness, policy, trace, replay, and report behavior can be
validated before comparing live models.

Interview angle:
This is the right way to answer "can you expand the benchmark?" The answer is
not "add more toy questions"; it is "preserve the split, add distinct failure
modes, keep oracle solvability, and make the new suite measurable through the
same trace-backed report pipeline."

## 1.3.0 Milestone

### 48. Durable Sessions Without Turning HC Into A Chat Product

Problem:
HC already had task-internal multi-step agent loops, but user-level follow-up
messages in the TUI were weak. The message pane showed prior messages, yet each
normal user input started a fresh `AgentRunner.run(...)` with a new `run_id` and
no durable cross-run context.

Decision:
Add a small `SessionStore` that persists bounded turn summaries under
`.harnesscoder/sessions/<session_id>.json`. CLI can opt in with
`--session <id>`, and TUI exposes `/session [id]` plus `/reset-session [id]`.
Before a session-backed run starts, the runtime loads compact `session_context`
and injects it through prompt assembly. The trace records `session_context_loaded`
and `context_packed.session_context_injected`, and `AgentState` stores the
session context so checkpoint/resume does not silently lose it.

The boundary stays narrow:

```text
session JSON -> compact session_context -> fresh run_id and trace
completed run -> append bounded turn summary back to session JSON
```

Interview angle:
The accurate answer to "does HC have multi-turn conversation?" is now stronger:
HC has task-internal multi-step loops and durable cross-run task sessions. It
still does not claim to be a long-term chat memory product. The important part is
that even conversation continuity is trace-backed and replay-visible.

## 1.3.1 Milestone

### 49. Context Budget v2 Makes Compaction Explainable

Problem:
HC already had `context_packed`, task-local memory, RepoMap injection, and
compression metrics, but a skeptical interviewer could still ask: "how do you
know the compaction did not silently drop the important part?" A single compact
summary is not enough evidence.

Decision:
Add Context Budget v2 in prompt assembly. Each model-step context is split into
named sections such as `system`, `task_contract`, `available_tools`,
`packed_context`, `working_memory`, `repo_map`, `session_context`, and
`recent_observations`. The task contract is preserved; lower-priority sections
can be clipped or reduced. The `context_packed` trace records per-section
`raw_chars`, final `chars`, `budget`, `preserved`, `reduced`, and
`dropped_blocks`, plus aggregate budget totals.

Replay and reports now aggregate:

```text
context_budget_reduced_count
context_budget_dropped_blocks
context_budget_total_chars
context_budget_total_budget
```

Interview angle:
The answer is no longer "we summarize context." The answer is "we budget context
by section, preserve the current task contract, reduce lower-priority sections,
and record each reduction into the append-only trace."

## 1.3.2 Milestone

### 50. Context Ablation Matrix Turns Governance Into An Eval Axis

Problem:
RepoMap, memory, and compaction are easy to oversell if they only appear as
features. HC is an eval harness, so those features need a comparable report:
same cases, same model, different context configuration.

Decision:
Add `--context-ablations` and a dedicated context ablation matrix. The default
ablations are:

```text
full
no_repomap
no_memory
no_context_compaction
no_policy_retry
```

The report compares pass rate, agent/patch/test/verifier success, average tool
calls, repeated reads, invalid calls, policy denials, tool failures,
max-iteration failures, context injection count, estimated context tokens,
budget reductions, dropped blocks, RepoMap use, first target read step, memory
updates, compression count, and failure breakdown. The CLI accepts either a
direct provider or one configured model profile as the model under test; it does
not mix multi-profile comparison with context ablation in one table.

Interview angle:
This is the right way to answer "does RepoMap or memory actually help?" The
answer is not subjective. HC can run a controlled ablation matrix and compare
local behavior metrics from replay-backed traces.

Release evidence boundary:
The deterministic oracle context ablation is valid runtime evidence because it
does not depend on an external model provider. The real-model `gpt55_high`
context ablation run for this release is not a valid context-capability
conclusion: most non-`full` cells failed as `model_error` before a tool action
was produced, with provider-side HTTP 503/504/429 and response-format failures.
Keep that report as instability evidence, but do not use it to claim
`no_repomap`, `no_memory`, or `no_context_compaction` are worse. A follow-up
release should split transient provider failures from action-parse failures and
make retry/backoff visible in trace.
