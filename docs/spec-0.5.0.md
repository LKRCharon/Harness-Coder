# HarnessCoder 0.5.0 Scoped Spec

Version 0.5.0 turns the 0.4.0 closed loop into a comparable eval matrix. The
core question changes from "can one model finish the bugfix loop?" to "how do
different model profiles behave on the same trace-backed cases?"

## Goals

- Load named model profiles from TOML.
- Keep built-in ad hoc profiles for `scripted` and `openai-codex`.
- Run the same eval cases across multiple profiles.
- Render a Markdown matrix with pass rate, test pass rate, tool calls, repeated
  reads, invalid calls, policy denials, tool failures, and failure categories.
- Keep per-run traces and workspaces for every profile/case pair.

## Model Config

Model profiles live in a local TOML file:

```toml
[models.scripted]
provider = "scripted"

[models.openai_codex]
provider = "openai-codex"
model = "your-codex-model-name"
base_url = "https://your-openai-compatible-endpoint.example/v1"
api_key_env = "OPENAI_API_KEY"
```

Secrets must stay in environment variables or local ignored files. The model
config stores environment variable names, not API keys.

## CLI

Single profile:

```bash
python -m harnesscoder --model-profile scripted --eval eval/cases.json
```

Matrix:

```bash
python -m harnesscoder \
  --model-config models.toml \
  --model-profiles scripted,openai_codex \
  --eval eval/bugfix_cases.json \
  --eval-report .harnesscoder/reports/bugfix-matrix.md
```

## Acceptance

- `models.example.toml` documents the profile shape.
- `--model-profile` can run one configured profile.
- `--model-profiles` runs a matrix report.
- Matrix rows compare task success, test pass, average tool calls, repeated
  reads, invalid tool calls, policy denials, tool failures, and failure
  categories.
- Unit tests cover profile parsing and matrix rendering.

## Non-Goals

- Statistical significance across large benchmarks.
- Token/cost accounting from provider usage objects.
- Live streaming responses.
- Strong filesystem sandboxing.
