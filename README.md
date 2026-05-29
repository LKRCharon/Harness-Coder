# HarnessCoder

[English](README.md) | [简体中文](README.zh.md)

HarnessCoder is a local coding-agent runtime and eval harness for real
repository tasks. The 1.0 story is deliberately narrow:

- event-sourced structured tool-use loop
- policy-gated tools
- trace/replay/eval
- context governance: memory, compression, and RepoMap

It is not a fork of CoreCoder, not a smaller LangGraph clone, and not a web UI.
The first goal is a controllable runtime that can run a structured tool-use
loop, gate tool execution with policy, and write every important decision into
a replayable JSONL trace.

The core loop is dynamic and tool-use driven:

```text
state -> model proposes action -> policy checks -> tool executes
      -> tool result appended -> state updated -> model proposes again
```

That shape matters because coding tasks are rarely a fixed DAG. The useful next
step depends on the current repo, tool results, failures, test output, and the
model's evolving plan. A DAG or LangGraph-style workflow can be useful for the
eval pipeline around the agent, but the runtime itself should remain a
policy-gated tool-use loop.

## What It Provides

HarnessCoder is infrastructure for running and studying coding-agent behavior,
not a claim that one scaffold is universally strong. It provides:

- A dynamic structured tool-use loop with policy-gated local tools:
  `read_file`, `search_code`, `repo_map`, `write_file`, `edit_file`,
  `run_tests`, and `run_command`.
- JSONL traces under `.harnesscoder/runs/<run_id>/trace.jsonl`, with
  `run_started`, `context_packed`, `model_action`, `policy_decision`,
  `tool_result`, `test_result`, `checkpoint_created`, `model_retry`, and
  `run_finished` events.
- Isolated eval workspaces under `.harnesscoder/eval-workspaces/...`, so cases
  can be replayed without mutating the source fixtures.
- Markdown eval reports with pass/fail, verifier pass, tool-use metrics, policy
  denials, model errors, context metrics, artifact integrity, and failure
  categories.
- Context governance through prompt packing, task-local memory, observation
  compression, durable session context, and lightweight RepoMap injection.
- Context ablations over memory, RepoMap, compaction, and policy recovery using
  the same cases and the same model.
- OpenAI-compatible real-model profiles for Responses API and Chat Completions
  endpoints, including tolerant action parsing, `tool_calls` support, and
  trace-visible retry/backoff for transient provider failures.
- HC-Train-40 for training-trace collection, HC-Bench-20 for controlled
  runtime comparison, and HC-Bench-40 as a harder heldout scorecard.
- A deterministic `hc-bench-oracle` provider that validates fixture solvability,
  verifier contracts, and report generation before real models are compared.

Common entrypoints:

```bash
python -m harnesscoder "看一下这个 repo 是做什么的"
python -m harnesscoder --replay .harnesscoder/runs/<run_id>/trace.jsonl
python -m harnesscoder --resume .harnesscoder/runs/<run_id>/checkpoint.json
python -m harnesscoder --session interview "继续刚才那个 repo 解释"
python -m harnesscoder --eval eval/cases.json
python -m harnesscoder --provider hc-bench-oracle --eval eval/hc_bench_20.json
python -m harnesscoder --provider hc-bench-oracle --eval eval/hc_bench_40.json
python -m harnesscoder --provider hc-bench-oracle --eval eval/hc_bench_20.json --context-ablations
```

The scripted model currently performs a small repo-orientation pass: search for
project mentions, read `README.md`, list files, and then produce a final answer.

## Design Principles

1. Dynamic tool-use runtime, fixed eval wrapper.
   Coding tasks require adaptive model decisions and tool use, while evaluation
   should remain reproducible.
2. Tool calls are proposed by the model, not trusted by the runtime.
   Every tool call passes through a policy gate before execution.
3. Trace first.
   If a run cannot be inspected, replayed, or scored, it is not useful for agent
   research.
4. Context is a controlled resource.
   Prompt packing, memory, RepoMap, and session context should be measurable and
   ablatable.
5. Benchmarks are diagnostic tools, not marketing claims.
   Local suites are used to compare runtime scaffolds, policies, and context
   strategies under controlled conditions.

## Evidence Snapshot

The numbers below are local controlled runs from this workspace. HC-Bench-20/40
are synthetic microbenchmarks for runtime, policy, context, and verifier
diagnostics. They should not be presented as real-world issue-resolution
performance. Oracle results validate harness solvability and report integrity;
real-model rows are the model comparison evidence.

The highest-value readout order is:

1. real model matrix
2. context ablation
3. policy recovery
4. trace/replay integrity
5. failure taxonomy

### Real Model Matrix

This is the most valuable table: different real models, the same benchmark, and
the same context mode. These rows use HC-Bench-20 with
`--context-mode pack --repo-map-mode auto`.

| Model | Pass rate | Verifier pass | Avg tool calls | Invalid JSON/action | Policy denials | Tool failures | Max-iteration failures | Avg runtime | Failure breakdown |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| gpt-5.4 | 45.0% (9/20) | 50.0% (10/20) | 3.80 | 0 | 2 | 22 | 2 | not summarized | success=9, tool_failed=1, verifier_failed=10 |
| gpt-5.5 | 25.0% (5/20) | 55.0% (11/20) | 4.90 | 0 | 1 | 21 | 11 | not summarized | model_error=1, success=5, tool_failed=6, verifier_failed=8 |
| deepseek | 15.0% (3/20) | 55.0% (11/20) | 5.00 | 0 | 13 | 30 | 13 | not summarized | model_error=3, policy_denied=3, success=3, test_failed=1, tool_failed=4, verifier_failed=6 |

The useful signal is not just pass/fail. These reports show that a model can
make tests pass while still missing trace-level workflow requirements such as
search-first evidence, failed-test -> repair -> retest recovery, or safe
continuation after a denied action.

A newer single-profile report shape adds patch success, artifact integrity,
budget chars, stable-prefix changes, output compression, and model retry counts.
That report format should be used for future real-model matrices. `Avg runtime`
is present in replay timing but is not yet summarized in the matrix table.

### Context Ablation

Context governance is useful only if it can be measured and ablated. This
oracle matrix keeps the same cases fixed and switches off one runtime behavior
at a time.

| Ablation | Pass rate | First target read step | Repeated reads | Estimated context tokens | Dropped blocks | Failure category |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| full | 100.0% (20/20) | 2 | 0 | 240194 est. tokens | 0 | success=20 |
| no_repomap | 100.0% (20/20) | n/a | 0 | 144308 est. tokens | 0 | success=20 |
| no_memory | 100.0% (20/20) | 2 | 0 | 230034 est. tokens | 0 | success=20 |
| no_context_compaction | 100.0% (20/20) | n/a | 0 | 98434 est. tokens | 0 | success=20 |
| no_policy_retry | 85.0% (17/20) | 2 | 0 | 216479 est. tokens | 0 | success=17, verifier_failed=3 |

This does not prove a model is smarter with RepoMap or memory. It proves the
runtime can switch those context features on and off on the same tasks, and can
report the behavior changes instead of relying on feature names.

### Policy Recovery

Policy cases are designed to check whether a model can recover after an unsafe
or disallowed action.

| Condition | Denial count | Recovery success rate | Repeat denial count | Policy-caused max iteration | Readout |
| --- | ---: | ---: | ---: | ---: | --- |
| full oracle runtime | 1 | 3/3 | 0 | 0 | Denial is trace-visible and the agent gets a recovery turn. |
| no_policy_retry ablation | 1 | 0/3 | 0 | 3 | Removing the recovery turn makes all policy cases fail. |
| gpt-5.5 real-model matrix row | 1 | 1/3 | not summarized | 2 | Real models often make safe progress but miss the exact recovery workflow. |

### Trace And Replay Integrity

Every case should leave replayable evidence: trace, workspace, verifier result,
artifact metadata, and checkpoints. A report is useful only when those evidence
paths explain what happened.

| Evidence | Count |
| --- | ---: |
| Case traces | 20 |
| `context_packed` events | 99 in the full oracle ablation |
| `checkpoint_created` events | 99 in the full oracle ablation |
| Replay success | trace summary generated for each case |
| Stored artifacts | 6 in one recent real-model HC-Bench-20 run |
| Artifact missing / hash mismatch | 0 / 0 |
| Context budget reductions / dropped blocks | 0 / 0 |
| Resume success | n/a in these reports; supported by checkpoint/resume smoke tests |

### Failure Taxonomy

Failure categories are interview-friendly because they show diagnostics beyond
pass/fail. The current gpt-5.5 HC-Bench-20 matrix row breaks down strict
outcomes this way:

| Failure Category | Count | Example | Likely Cause |
| --- | ---: | --- | --- |
| success | 5 | `business-feature-flag-default` | Patch, tests, and verifier all passed. |
| verifier_failed | 8 | `business-discount-boundary` | Tests passed or progress was made, but the trace missed required workflow evidence. |
| tool_failed | 6 | `business-overdue-timezone` | Agent hit the iteration budget or a tool failure after partial progress. |
| model_error | 1 | `greenfield-rate-limiter` | Provider/model call failed before the run produced a valid final state. |

This table is the point of the harness: failures are not only "wrong answer" but
runtime-diagnosable behaviors that can feed prompt changes, policy changes, or
post-training data generation. The next badcase layer should split broad
categories into causes such as `target_not_found`, `invalid_action`,
`patch_failed`, `policy_recovery_failed`, `max_iterations`, and `test_timeout`.

### Claim Hygiene

Do not describe oracle pass rate as model performance. Say: the deterministic
oracle reaches 100% on HC-Bench-20/40, validating that the benchmark fixtures,
verifiers, and reporting pipeline are solvable.

Do not describe HC-Bench-20/40 as real-world coding-agent performance. Say:
HC-Bench-20/40 are controlled microbenchmarks for runtime and scaffold
evaluation. Real-world issue-resolution evaluation is future work.

Do not claim "context governance improves reliability" without numbers. Say:
context governance enables ablation over prompt packing, memory, and RepoMap
injection. Current reports compare pass rate, repeated reads, first target read
step, dropped blocks, and failure categories.

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
/session interview
/reset-session
```

The current TUI is intentionally small: it is a runnable control surface for the
runtime and eval harness, not a full Claude Code clone. It now supports durable
sessions for follow-up tasks: `/session <id>` switches the session, each completed
run appends a bounded turn summary under `.harnesscoder/sessions/`, and the next
run receives that session context through the same prompt/trace path as other
context governance inputs.

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

Every model-step `context_packed` trace records Context Budget v2 evidence:
per-section `raw_chars`, final `chars`, `budget`, `preserved`, `reduced`, and
`dropped_blocks`. The current task contract is preserved while lower-priority
sections such as observations, packed context, session context, RepoMap, and
working memory can be clipped or reduced. Replay and eval reports aggregate
budget reductions, dropped blocks, total context chars, and total budget.

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
- `session_context_loaded`
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

A `context_packed` event also carries `context_budget`, for example:

```json
{
  "type": "context_packed",
  "context_budget": {
    "version": 2,
    "sections": {
      "task_contract": {"chars": 250, "budget": 2400, "preserved": true},
      "packed_context": {"raw_chars": 21000, "chars": 15900, "budget": 16000, "reduced": true}
    },
    "reduced_sections": ["packed_context"],
    "dropped_blocks": 2
  }
}
```

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
[docs/spec-1.2.1.md](docs/spec-1.2.1.md). The 1.3.0 durable session release is
scoped in [docs/spec-1.3.0.md](docs/spec-1.3.0.md), Context Budget v2 is scoped
in [docs/spec-1.3.1.md](docs/spec-1.3.1.md), and the context ablation matrix is
scoped in [docs/spec-1.3.2.md](docs/spec-1.3.2.md). Real-model eval hygiene is
scoped in [docs/spec-1.3.3.md](docs/spec-1.3.3.md). The Claude Code
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
failures, memory/compression metrics, RepoMap use/injection metrics, context
budget reductions and dropped blocks, observation artifact metrics, and failure
categories. Each profile/case run still keeps its own trace and artifact directory. If a real-model
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

Run the built-in context ablation matrix:

```bash
python -m harnesscoder \
  --provider hc-bench-oracle \
  --eval eval/hc_bench_20.json \
  --context-ablations \
  --max-iterations 8 \
  --eval-report .harnesscoder/reports/hc-bench-20-context-ablations.md
```

The ablation matrix compares `full`, `no_repomap`, `no_memory`,
`no_context_compaction`, and `no_policy_retry` on the same cases. It reports
pass rate, tool calls, repeated reads, invalid calls, policy denials,
max-iteration failures, context tokens, budget reductions, dropped blocks,
RepoMap use, first target read step, memory updates, compression, and failure
breakdown.

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
- Add session-aware eval cases that measure follow-up task quality across runs.
- Add richer failure replay fixtures under `replay/`.
- Add token/cost accounting when providers return usage data.
