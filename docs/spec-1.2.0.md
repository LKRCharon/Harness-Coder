# HarnessCoder 1.2.0 Spec

## Goal

Add a clear train/heldout benchmark boundary for post-training work.

HarnessCoder 1.2.0 introduces `HC-Train-40` as a training trace pool for
AgentTraceTune-style SFT/DPO data collection while keeping HC-Bench-20 separate
as the current live-eval control suite. The point is not to inflate benchmark
numbers. The point is to stop mixing teacher-trace collection and final
evaluation evidence.

## Scope

- Add `eval/hc_train_40.json` with 40 fixture-backed training cases.
- Add `examples/hc_train_40/repo` as an isolated synthetic microbenchmark repo.
- Add `harnesscoder/data/hc_train_oracle.json` so `hc-bench-oracle` can sanity
  check the full train pool.
- Keep all HC-Train-40 cases marked with `split=train` and
  `source=synthetic-microbenchmark`.
- Preserve HC-Bench-20 as a separate heldout/control suite; no HC-Train-40 case
  reuses an HC-Bench-20 case id.
- Surface split/source metadata in eval reports.

## HC-Train-40 Shape

The first training pool has this distribution:

```text
bugfix:      7
context:    14
recovery:    8
policy:      6
greenfield:  5
```

The extra weight on `context` is intentional. It creates more search-first and
bounded-read traces for training tool behavior such as "locate first, edit
second, verify last."

## Acceptance

- `python scripts/generate_hc_train_40.py` regenerates the suite.
- `python -m harnesscoder --provider hc-bench-oracle --eval eval/hc_train_40.json --max-iterations 8`
  passes 40/40.
- HC-Bench-20 oracle still passes 20/20.
- Unit tests cover category distribution, split/source metadata, oracle plan
  coverage, and train/eval id separation.
- Public docs do not expose private model providers, private endpoints, `.env`,
  or local `models.toml`.

## Non-goals

- No model training code inside HarnessCoder.
- No single `HC-Bench-100` used for both trace collection and final eval.
- No SWE-bench-scale adapter.
- No subagent platform work in this release.

## Next

The next benchmark step should be `HC-Heldout-30`: a never-train final eval set
with distinct fixtures and ids. Until then, HC-Bench-20 remains the heldout-like
control suite for live model comparison.
