# HarnessCoder

[English](README.md) | [简体中文](README.zh.md)

HarnessCoder is a local coding agent harness for real repository tasks. The 1.0
story is deliberately narrow:

- event-sourced agent loop
- policy-gated tools
- trace/replay/eval
- context governance: memory, compression, and RepoMap

It is not a fork of CoreCoder, not a smaller LangGraph clone, and not a web UI.
The first goal is a controllable runtime that can run an agent loop, gate tool
execution with policy, and write every important decision into a replayable
JSONL trace.

The core loop is dynamic:

```text
state -> model decides action -> policy checks -> tool executes
      -> observation appended -> state updated -> model decides again
```

That shape matters because coding tasks are rarely a fixed DAG. The useful next
step depends on the current repo, tool observations, failures, test output, and
the model's evolving plan. A DAG or LangGraph-style workflow can be useful for
the eval pipeline around the agent, but the agent itself should remain a
policy-gated loop.

## Current Status

Version `1.2.1` is a runnable local runtime with real bugfix and minimal
greenfield eval loops, HC-Bench-20/40, trace replay, eval reporting,
model-profile comparison, context-governed prompt assembly, task-local memory,
compression metrics, lightweight RepoMap, checkpoint/resume support, and a
large-output artifact store for audit/replay. It also separates training trace
collection from live evaluation through HC-Train-40 and HC-Bench-20/40. It
includes:

- A `ScriptedModel` that simulates model actions without calling a real LLM.
- Tool execution for:
  - `read_file(path, offset=0, limit=200)`
  - `search_code(query, path=".")`
  - `repo_map(query=None, max_tokens=1200, refresh=false)`
  - `write_file(path, content, overwrite=false)`
  - `edit_file(path, old, new)`
  - `run_tests(cmd=None, timeout=60)`
  - `run_command(cmd, timeout=30)`
- A minimal policy gate before every tool call.
- JSONL traces under `.harnesscoder/runs/<run_id>/trace.jsonl`.
- Large tool observations are previewed in trace/model context and persisted
  under the run's `artifacts/` directory with size and hash metadata.
- `context_packed`, `checkpoint_created`, `run_resumed`, and `test_result`
  events for reliability-oriented replay.
- `repo_map_built` and `repo_map_used` events for repository-level context
  governance.
- Trace replay summaries through `python -m harnesscoder.replay`.
- A minimal eval harness that runs cases, executes tests, scores results, and
  renders a Markdown report.
- Fixture-backed bugfix evals that copy a repo into
  `.harnesscoder/eval-workspaces/...` before editing it.
- A greenfield eval that starts from a nearly empty fixture and creates source
  plus tests from scratch.
- Case-level `allowed_tools`, `step_budget`, and `verifier` fields inspired by
  benchmark harnesses such as Pico.
- Model profiles and Markdown eval matrices for comparing the same cases across
  providers.
- HC-Bench-20: the original 20-case fixture-backed scorecard across bugfix,
  recovery, greenfield, context-governance, and policy/safety categories.
- HC-Bench-40: a harder heldout scorecard that keeps HC-Bench-20 comparable and
  adds ProgramBench-style programming repairs, parser recovery, richer
  greenfield tasks, large-context lookup tasks, and policy/security cases.
- HC-Train-40: 40 fixture-backed training cases for teacher/current-policy trace
  collection, with explicit `split=train` and `source=synthetic-microbenchmark`
  metadata.
- A deterministic `hc-bench-oracle` provider that proves the benchmark and
  report pipeline are solvable before comparing real models.
- CLI entrypoints:

```bash
python -m harnesscoder "看一下这个 repo 是做什么的"
python -m harnesscoder --replay .harnesscoder/runs/<run_id>/trace.jsonl
python -m harnesscoder --resume .harnesscoder/runs/<run_id>/checkpoint.json
python -m harnesscoder --eval eval/cases.json
python -m harnesscoder --provider hc-bench-oracle --eval eval/hc_bench_20.json
python -m harnesscoder --provider hc-bench-oracle --eval eval/hc_bench_40.json
```

The scripted model currently performs a small repo-orientation pass: search for
project mentions, read `README.md`, list files, and then produce a final answer.

## TUI

HarnessCoder also has a lightweight standard-library terminal UI:

```bash
python -m harnesscoder --tui
```

Inside the TUI, send a normal message to run the agent and write a new trace.
The UI keeps refreshing while a run is active, shows the latest trace event in
the status area, and folds the header on narrow or short terminals. Use slash
commands for direct tools and runtime controls:

```text
/help
/status
/model your-model-name
/model scripted
/provider openai-codex
/base-url https://your-openai-compatible-endpoint.example
/read README.md
/search HarnessCoder
/repo-map HarnessCoder
/edit README.md old new
/test python -m unittest discover -s tests
/run git status --short
/trace latest
```

The current TUI is intentionally small: it is a runnable control surface for the
runtime and eval harness, not a full Claude Code clone.

The control surface now goes through a small runtime control plane rather than
one-off TUI branches. During an active run, mutating commands are blocked and
only read-only controls such as `/help`, `/status`, and `/trace` remain
available. The project borrows Hermes' entrypoint/runtime layering lesson, not
its multi-platform Gateway shape.

## Context Governance

HarnessCoder's context governance has three task-local layers:

- Packed context summarizes hot observations, cold trace history, modified
  files, and budget.
- Working memory stores task-scoped facts such as failing tests, explored files,
  relevant symbols, patch summaries, verified facts, and open questions.
- RepoMap builds a bounded repository index from Python AST symbols, imports,
  classes, functions, and fallback regex symbols for non-Python text files.

Use prompt modes to ablate these layers:

```bash
python -m harnesscoder --context-mode none "inspect this repo"
python -m harnesscoder --context-mode pack "inspect this repo"
python -m harnesscoder --context-mode memory "inspect this repo"
```

RepoMap injection is enabled by default for `pack` and `memory` modes and can be
disabled independently:

```bash
python -m harnesscoder \
  --context-mode pack \
  --repo-map-mode none \
  "inspect this repo"
```

## OpenAI-Compatible Providers

The MVP includes two optional OpenAI-compatible real-model providers:

- `openai-codex` calls a Responses API endpoint at `/responses`.
- `openai-chat` calls a Chat Completions endpoint at `/chat/completions`.

Both providers ask the model to return a strict JSON action for the runtime to
execute.

Keep secrets out of the repo. Configure the provider with environment variables
or a local `.env` file:

```bash
export OPENAI_API_KEY="<your-api-key>"
export HARNESSCODER_OPENAI_BASE_URL="https://your-openai-compatible-endpoint.example/v1"
export HARNESSCODER_OPENAI_MODEL="your-codex-model-name"

python -m harnesscoder --provider openai-codex "看一下这个 repo 是做什么的"
```

For Codex Responses profiles, you can set runtime reasoning strength with
`--reasoning-effort` or `reasoning_effort` in `models.toml`:

```bash
python -m harnesscoder \
  --provider openai-codex \
  --reasoning-effort high \
  "fix the failing test"
```

Valid values are `none`, `minimal`, `low`, `medium`, `high`, and `xhigh`.
HarnessCoder records the configured and effective reasoning effort in the
`run_started` trace metadata so eval matrices can compare high/xhigh runs. Chat
Completions profiles such as DeepSeek do not receive this field.

If the base URL does not end in `/v1`, HarnessCoder appends `/v1` before calling
`/responses` or `/chat/completions`.

DeepSeek can be configured through the Chat Completions provider. Keep the API
key in `.env` or your shell environment and reference the variable from
`models.toml`:

```toml
[models.deepseek]
provider = "openai-chat"
model = "deepseek-v4-pro"
base_url = "https://api.deepseek.com"
api_key_env = "DEEPSEEK_API_KEY"
timeout = 120
max_output_tokens = 2000
```

Run a DeepSeek matrix:

```bash
python -m harnesscoder \
  --model-config models.toml \
  --model-profiles hc_bench_oracle,scripted,deepseek \
  --context-mode pack \
  --eval eval/hc_bench_20.json \
  --max-iterations 8 \
  --eval-report .harnesscoder/reports/hc-bench-20-deepseek-matrix.md
```

When launched from a repo, the CLI auto-loads `.env` from the current directory
and from `--cwd` if it is different. Existing shell environment variables win
over `.env` values. `OPENAI_MODEL` is also accepted as a fallback for
`HARNESSCODER_OPENAI_MODEL`.

## Trace Shape

Each run writes event records with a timestamp, run id, and event type. The
runtime trace includes at least:

- `run_started`
- `context_packed`
- `model_action`
- `policy_decision`
- `tool_result`
- `test_result`
- `state_updated`
- `checkpoint_created`
- `run_resumed`
- `run_finished`

These traces are intentionally append-only JSONL so later replay and eval code
can consume them without depending on in-memory state.

## Developer Process Notes

See [docs/development-process.md](docs/development-process.md) for the running
engineering log: design decisions, bugs encountered during real provider
integration, fixes, and interview-ready talking points.

For interview-facing material, see [docs/showcase.md](docs/showcase.md) and
[docs/architecture.md](docs/architecture.md).
For release checks, see [docs/release-checklist.md](docs/release-checklist.md)
and [docs/spec-1.0.0.md](docs/spec-1.0.0.md). The 1.0.1 evaluation tightening
is scoped in [docs/spec-1.0.1.md](docs/spec-1.0.1.md), the 1.0.2 observation
artifact store is scoped in [docs/spec-1.0.2.md](docs/spec-1.0.2.md), and the
1.1.0 prompt cache governance work is scoped in
[docs/spec-1.1.0.md](docs/spec-1.1.0.md). The 1.2.0 train/heldout benchmark
split is scoped in [docs/spec-1.2.0.md](docs/spec-1.2.0.md), and the 1.2.1
HC-Bench-40 / run-control / reasoning-strength release is scoped in
[docs/spec-1.2.1.md](docs/spec-1.2.1.md). The Claude Code
prompt caching note that motivated 1.1 is summarized in
[docs/blog/claude-code-prompt-caching.md](docs/blog/claude-code-prompt-caching.md).

## Replay And Eval

Replay loads a trace and reconstructs a structured summary:

```bash
python -m harnesscoder.replay .harnesscoder/runs/<run_id>/trace.jsonl
python -m harnesscoder --replay .harnesscoder/runs/<run_id>/trace.jsonl
```

Resume continues an interrupted run from the saved checkpoint:

```bash
python -m harnesscoder --resume .harnesscoder/runs/<run_id>/checkpoint.json
```

Eval stays workflow-shaped around the dynamic agent loop:

```text
setup repo -> run agent -> run tests -> collect trace -> score -> report
```

Run the local smoke eval:

```bash
python -m harnesscoder --eval eval/cases.json
```

Run one named model profile:

```bash
python -m harnesscoder \
  --model-profile scripted \
  --eval eval/cases.json
```

Run the real bugfix loop with an OpenAI-compatible model:

```bash
export OPENAI_API_KEY="<your-api-key>"
export HARNESSCODER_OPENAI_BASE_URL="https://your-openai-compatible-endpoint.example/v1"
export HARNESSCODER_OPENAI_MODEL="your-codex-model-name"

python -m harnesscoder \
  --provider openai-codex \
  --eval eval/bugfix_cases.json \
  --max-iterations 8 \
  --eval-report .harnesscoder/reports/bugfix-demo.md
```

`eval/bugfix_cases.json` uses `examples/bugfix_demo/repo` as a fixture. The
eval runner copies it into an isolated `.harnesscoder/eval-workspaces/...`
workspace before the agent edits files, so demo fixtures remain stable.

Run the minimal greenfield loop:

```bash
python -m harnesscoder \
  --provider openai-codex \
  --eval eval/greenfield_cases.json \
  --max-iterations 10 \
  --eval-report .harnesscoder/reports/greenfield-demo.md
```

`eval/greenfield_cases.json` starts from `examples/greenfield_demo/repo`, which
contains no application code. The agent must create `math_utils.py` and
`test_math_utils.py`, pass `python -m unittest discover`, and pass a separate
verifier command. The case also declares `allowed_tools` and `step_budget`, so
the eval contract is explicit instead of hidden in prose.

Compare profiles with an eval matrix:

```bash
cp models.example.toml models.toml
# Edit models.toml locally, then keep it out of git if it contains private endpoints.

python -m harnesscoder \
  --model-config models.toml \
  --model-profiles hc_bench_oracle,scripted,openai_codex,deepseek \
  --eval eval/hc_bench_20.json \
  --max-iterations 8 \
  --eval-report .harnesscoder/reports/hc-bench-20-real-matrix.md
```

The matrix report compares pass rate, test pass rate, verifier pass rate,
average tool calls, repeated reads, invalid calls, policy denials, tool
failures, memory/compression metrics, RepoMap use/injection metrics, observation
artifact metrics, and failure categories. Each profile/case run still keeps its
own trace and artifact directory. If a real-model
profile cannot initialize, the matrix records the profile error instead of
hiding the reason.

Compare context modes:

```bash
python -m harnesscoder \
  --model-config models.toml \
  --model-profiles deepseek \
  --context-mode none \
  --eval eval/hc_bench_20.json \
  --eval-report .harnesscoder/reports/hc-bench-20-real-none.md

python -m harnesscoder \
  --model-config models.toml \
  --model-profiles deepseek \
  --context-mode pack \
  --eval eval/hc_bench_20.json \
  --eval-report .harnesscoder/reports/hc-bench-20-real-pack.md

python -m harnesscoder \
  --model-config models.toml \
  --model-profiles deepseek \
  --context-mode memory \
  --eval eval/hc_bench_20.json \
  --eval-report .harnesscoder/reports/hc-bench-20-real-memory.md
```

Compare RepoMap injection:

```bash
python -m harnesscoder \
  --model-config models.toml \
  --model-profiles deepseek \
  --context-mode pack \
  --repo-map-mode none \
  --eval eval/hc_bench_20.json \
  --eval-report .harnesscoder/reports/hc-bench-20-without-repo-map.md

python -m harnesscoder \
  --model-config models.toml \
  --model-profiles deepseek \
  --context-mode pack \
  --repo-map-mode auto \
  --eval eval/hc_bench_20.json \
  --eval-report .harnesscoder/reports/hc-bench-20-with-repo-map.md
```

Run HC-Bench-20 with the deterministic local oracle:

```bash
python -m harnesscoder \
  --provider hc-bench-oracle \
  --eval eval/hc_bench_20.json \
  --max-iterations 8 \
  --eval-report .harnesscoder/reports/hc-bench-20-oracle.md
```

HC-Bench-20 is the 0.7.0 interview benchmark. It contains 20 local cases:

- 7 bugfix cases for business-like defects.
- 3 recovery cases that require a failing test and a second fix.
- 5 greenfield cases that create modules and tests through `write_file`.
- 2 context cases that reward search-first, bounded reads in large files.
- 3 policy cases for path traversal, command injection, and dangerous command
  denial.

The oracle is not a claim about model intelligence. It is a stable baseline for
the harness itself: fixture isolation, policy gates, trace metrics, verifiers,
and category-level reports. Real providers can be compared against the same
suite through `--model-profiles`.

Generate and run the harder heldout HC-Bench-40 suite:

```bash
python scripts/generate_hc_bench_40.py

python -m harnesscoder \
  --provider hc-bench-oracle \
  --eval eval/hc_bench_40.json \
  --max-iterations 8 \
  --eval-report .harnesscoder/reports/hc-bench-40-oracle.md
```

HC-Bench-40 keeps the HC-Bench-20 cases intact for historical comparison and
adds 20 harder heldout cases:

- 4 ProgramBench-style programming/algorithm repairs.
- 3 recovery cases for parser and edge-case fixes that require a failed test and
  a second patch.
- 5 greenfield programming tasks that create source plus tests.
- 5 large-context lookup cases that measure search-first, bounded-read behavior.
- 3 policy/security cases for redaction, shell-safe argv construction, and
  denied network download recovery.

Generate and sanity-check HC-Train-40:

```bash
python scripts/generate_hc_train_40.py

python -m harnesscoder \
  --provider hc-bench-oracle \
  --eval eval/hc_train_40.json \
  --max-iterations 8 \
  --eval-report .harnesscoder/reports/hc-train-40-oracle.md
```

HC-Train-40 is a training trace pool, not the final scorecard. It contains 40
synthetic microbenchmark cases:

- 7 bugfix cases.
- 14 context cases that require search-first, bounded-read behavior.
- 8 recovery cases that require observing a failing test and patching again.
- 6 policy cases that exercise tool denials and safe recovery paths.
- 5 greenfield cases that create source plus tests through `write_file`.

Use HC-Train-40 to collect teacher/current-policy traces for post-training. Use
HC-Bench-20 for backward-compatible comparisons and HC-Bench-40 as the current
harder heldout scorecard for live model comparison.

Near-term TODOs:

- Improve the TUI with better history navigation and richer trace inspection
  commands.
- Add richer failure replay fixtures under `replay/`.
- Add token/cost accounting when providers return usage data.
