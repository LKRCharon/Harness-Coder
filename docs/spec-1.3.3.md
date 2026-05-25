# HarnessCoder 1.3.3 Spec

## Goal

Tighten real-model eval hygiene without changing benchmark cases, scoring, or
the deterministic oracle.

1.3.3 focuses on the boundary where OpenAI-compatible providers return useful
but imperfect action payloads, or transiently fail before producing a valid
action. The harness should normalize common response shapes, keep Python
subprocess execution reproducible on L40, and make provider recovery visible in
trace/replay reports.

## Scope

- Normalize common real-model action shapes:
  - JSON surrounded by explanatory text or fenced blocks
  - wrapped payloads such as `next_action`, `model_action`, `decision`, and
    nested `action`
  - `type`/`action` aliases for `kind`
  - tool aliases such as `run_test`, `search`, `edit`, `bash`, and `shell`
  - string `arguments` for command-like tools
  - Chat Completions `tool_calls`
- Allow OpenAI-compatible Chat Completions profiles to set a redacted
  `extra_body` table for endpoint-specific options.
- Normalize bare `python` / `python3.x` subprocess commands to the current
  interpreter in tool execution and eval verifier commands.
- Retry clearly retryable model adapter failures with capped exponential
  backoff:
  - empty or missing model text
  - invalid action JSON
  - transient request failures
  - HTTP 408 / 409 / 429 / 5xx
  - non-JSON provider responses
- Emit `model_retry` trace events and aggregate `model_retry_count` in replay
  and eval reports.

## Non-Goals

- Do not change HC-Bench case definitions, verifiers, or pass/fail scoring.
- Do not special-case any model, provider, or benchmark case.
- Do not hide provider failures. A failed retry still becomes `model_error`.
- Do not turn HC into a prompt-tuning playground; this is runtime hygiene only.

## Trace Contract

A retryable adapter failure emits:

```json
{
  "type": "model_retry",
  "reason": "model_step",
  "attempt": 1,
  "max_retries": 2,
  "delay_seconds": 1.0,
  "retry_after_seconds": null,
  "backoff_strategy": "exponential",
  "error_type": "ModelAdapterError",
  "error": "...",
  "state": {}
}
```

`reason` is either `model_step` or `finish_grace`.

Default retry settings:

```text
max_retries = 2
base_delay_seconds = 1.0
max_delay_seconds = 30.0
```

For provider errors that include `retry_after` / `retry-after`, the runner uses
that value when it is larger than the exponential delay, capped by
`max_delay_seconds`. This avoids immediate retry storms while preventing a
single eval case from sleeping for minutes due to an overloaded endpoint.

Replay summaries expose:

```text
model_retry_count
```

Markdown eval reports include a top-level `Model retries` metric, and per-case
replay metrics include `model_retry_count`.

## Validation

Required local checks:

```bash
python -m unittest discover -s tests
python -m harnesscoder --version
python -m harnesscoder \
  --provider hc-bench-oracle \
  --eval eval/hc_bench_20.json \
  --max-iterations 8
```

Real-model evals may still be provider-limited. Reports should distinguish
provider/API errors from action/tool/verifier failures through `model_error`,
`model_retry_count`, and trace-level `model_retry` events.
