# HarnessCoder 1.3.2 Spec

## Goal

Add an ablation matrix for context governance.

HC is an eval harness, so context features should not only be described in docs.
They should be switchable and measurable on the same fixture-backed cases.
1.3.2 adds a one-command matrix that compares the full context stack against
several disabled variants.

## Scope

- Add `ContextAblation` definitions for:
  - `full`
  - `no_repomap`
  - `no_memory`
  - `no_context_compaction`
  - `no_policy_retry`
- Add `run_context_ablation_matrix(...)`.
- Add `render_context_ablation_matrix(...)`.
- Add CLI flag `--context-ablations` for `--eval`.
- Allow the ablation matrix to run with:
  - a direct `--provider`, or
  - one configured `--model-profile`.
- Keep `--context-ablations` separate from multi-profile `--model-profiles` so
  the report has one clean axis: context configuration.
- Report pass/fail and behavior metrics per ablation:
  - pass rate
  - agent success
  - patch/test/verifier pass
  - average tool calls
  - repeated reads
  - invalid calls
  - policy denials
  - tool failures
  - max-iteration failures
  - context injection count
  - estimated context tokens
  - context budget reductions
  - dropped blocks
  - RepoMap use
  - first target read step
  - memory updates
  - compression count
  - failure breakdown

## Ablation Definitions

```text
full:
  context_mode=memory
  repo_map_mode=auto
  allow_policy_recovery=true

no_repomap:
  context_mode=memory
  repo_map_mode=none
  allow_policy_recovery=true

no_memory:
  context_mode=pack
  repo_map_mode=auto
  allow_policy_recovery=true

no_context_compaction:
  context_mode=none
  repo_map_mode=none
  allow_policy_recovery=true

no_policy_retry:
  context_mode=memory
  repo_map_mode=auto
  allow_policy_recovery=false
```

`no_policy_retry` is deliberately narrow. For policy cases, the eval runner
clamps the effective iteration budget to one step so the report can separate
"the first model action hit policy" from "the runtime allowed a recovery turn."

## CLI

Run the deterministic control version:

```bash
python -m harnesscoder \
  --provider hc-bench-oracle \
  --eval eval/hc_bench_20.json \
  --context-ablations \
  --max-iterations 8 \
  --eval-report .harnesscoder/reports/hc-bench-20-context-ablations.md
```

Run the same ablations with one configured model profile:

```bash
python -m harnesscoder \
  --model-config models.toml \
  --model-profile deepseek \
  --eval eval/hc_bench_20.json \
  --context-ablations \
  --max-iterations 8 \
  --eval-report .harnesscoder/reports/hc-bench-20-deepseek-context-ablations.md
```

## Acceptance

- `python -m unittest tests.test_eval_matrix -v` passes.
- The matrix includes exactly the default ablation names.
- `no_context_compaction` reports zero context injections.
- The report includes budget reductions, dropped blocks, first target read step,
  repeated reads, invalid calls, policy denials, and max-iteration failures.
- A configured single `--model-profile` can be used as the model under test.
- The CLI exits 0 when all ablation profiles finish and the report is rendered,
  even if an intentionally disabled ablation has lower pass rate.

## Non-goals

- No statistical claim from one local run.
- No hidden cases in this release.
- No multi-dimensional report that mixes many models and many ablations at once.
- No claim that the deterministic oracle proves model capability.

## Interview Angle

1.3.2 is the answer to "how do you know RepoMap, memory, and compaction help?"

The precise answer is:

> I do not argue it subjectively. HC can run the same fixture-backed cases under
> `full`, `no_repomap`, `no_memory`, `no_context_compaction`, and
> `no_policy_retry`. The report compares pass rate, tool count, repeated reads,
> invalid calls, policy denials, max-iteration failures, estimated context
> tokens, budget reductions, dropped blocks, RepoMap usage, and first target read
> step. That turns context governance into an eval axis rather than a buzzword.
