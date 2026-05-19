# HarnessCoder Release Checklist

Use this checklist before tagging or publishing the repository.

## Required Checks

```bash
python -m unittest discover -s tests

python -m harnesscoder \
  --provider hc-bench-oracle \
  --eval eval/hc_bench_20.json \
  --max-iterations 8 \
  --eval-report .harnesscoder/reports/hc-bench-20-oracle.md

python -m harnesscoder \
  --provider hc-bench-oracle \
  --eval eval/hc_bench_40.json \
  --max-iterations 8 \
  --eval-report .harnesscoder/reports/hc-bench-40-oracle.md

python -m harnesscoder --version
```

Optional real-model matrix:

```bash
python -m harnesscoder \
  --model-config models.toml \
  --model-profiles hc_bench_oracle,scripted,deepseek \
  --context-mode pack \
  --eval eval/hc_bench_20.json \
  --max-iterations 8 \
  --eval-report .harnesscoder/reports/hc-bench-20-real-matrix.md
```

Optional context/RepoMap ablation:

```bash
python -m harnesscoder \
  --provider hc-bench-oracle \
  --context-mode pack \
  --repo-map-mode none \
  --eval eval/hc_bench_20.json \
  --max-iterations 8 \
  --eval-report .harnesscoder/reports/hc-bench-20-pack-no-repomap.md

python -m harnesscoder \
  --provider hc-bench-oracle \
  --context-mode pack \
  --repo-map-mode auto \
  --eval eval/hc_bench_20.json \
  --max-iterations 8 \
  --eval-report .harnesscoder/reports/hc-bench-20-pack-repomap.md
```

## Public Repo Hygiene

- Keep `.env`, `models.toml`, and `.harnesscoder/` out of git.
- Do not publish private provider base URLs or real API keys.
- Public examples may reference environment variable names such as
  `OPENAI_API_KEY` or `DEEPSEEK_API_KEY`, but not their values.
- Check `README.md`, `docs/`, `examples/`, `eval/`, `harnesscoder/`, `tests/`,
  `scripts/`, and `models.example.toml` for accidental local endpoint names.
- Confirm `LICENSE`, CI, examples, and docs are present.

## Current Non-Goals

- No subagents.
- No long-term memory platform.
- No LangGraph/DAG clone.
- No SWE-bench-scale adapter.
- No Web UI.
