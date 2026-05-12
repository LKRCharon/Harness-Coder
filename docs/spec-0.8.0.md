# HarnessCoder 0.8.x Scoped Spec

Version 0.8.x turns the 0.7 benchmark harness into a real-model context
governance harness. The line is intentionally narrow:

```text
trace-backed coding agent harness with real-model eval, task-local memory,
context compression metrics, and reproducible matrix reports
```

## 0.8.0 Real Model Baseline Matrix

Goal: collect real-model evidence on HC-Bench-20 without leaking local provider
details.

Acceptance:

- `hc-bench-oracle` remains the deterministic harness baseline.
- Matrix runs can include oracle, scripted, and `openai-codex` profiles.
- Matrix runs can also include `openai-chat` profiles for Chat Completions
  providers such as DeepSeek.
- Profile initialization failures are rendered in the Markdown matrix report.
- Public docs use generic endpoint placeholders only.
- Matrix metrics include pass rate, test pass, verifier pass, tool calls,
  repeated reads, invalid calls, policy denials, and failure category.

## 0.8.1 Context Pack Into Live Prompt

Goal: make `context_packed` affect real model input rather than only trace.

Context assembly:

```text
system instructions
+ task contract
+ packed context
+ recent observations
+ available tools
```

Switch:

```text
--context-mode none|pack|memory
```

Acceptance:

- `openai-codex` receives packed context in its Responses API payload when
  `--context-mode pack` is used.
- Trace records `context_injected=true` and `estimated_tokens`.
- Unit tests cover prompt construction without making a real API request.

## 0.8.2 Task-Local Memory Blocks

Goal: add task-scoped working memory without building long-term memory.

Blocks:

```text
task/failing_tests
task/explored_files
task/relevant_symbols
task/patch_summary
task/verified_facts
task/open_questions
```

Design:

```text
TaskMemory = reducer(trace events -> memory blocks)
MemoryBlock = label + value + limit + description + updated_step
```

Acceptance:

- Tool results update memory blocks during the run.
- Edits mark prior file summaries stale.
- Trace records `memory_updated`.
- `--context-mode memory` injects `<working_memory>...</working_memory>`.

## 0.8.3 Compression Metrics

Goal: make context compression measurable.

Metrics:

```text
estimated_context_tokens
compression_count
hot_observation_count
cold_summary_chars
repeated_read_count
time_to_first_edit
search_to_edit_steps
edit_to_test_steps
```

Acceptance:

- Replay summaries expose the metrics.
- Markdown reports show memory/compression metrics.
- Matrix runs support context-mode ablations.

## Non-Goals

- Subagents.
- Long-term memory.
- LangGraph/DAG clone.
- SWE-bench-scale adapter.
- Web UI.
