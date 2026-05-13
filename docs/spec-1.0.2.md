# HarnessCoder 1.0.2 Scoped Spec

Version 1.0.2 makes large tool observations auditable without letting them
dominate model context. The runtime should keep enough output in the live
observation stream for the model to continue, while preserving the full output
as a run-local artifact for replay, debugging, and eval metrics.

## Goals

- Store full large tool outputs under the run directory.
- Keep trace/state/model context bounded through deterministic previews.
- Record enough metadata to reconnect the preview with the stored artifact.
- Add replay and Markdown report metrics for observation volume and compression.
- Preserve secret hygiene by redacting sensitive patterns again before storing
  artifact files.

## Observation Artifact Store

Every tool still returns a `ToolResult`, but the runner normalizes that result
before appending it into state and trace:

```text
raw tool output
-> redaction in ToolRegistry
-> defensive redaction in artifact storage
-> artifact storage if output is large
-> preview output in state, trace, context, and test_result events
```

For outputs above the preview budget, the full text is written to:

```text
.harnesscoder/runs/<run_id>/artifacts/<call_id>.txt
```

The `tool_result.metadata` record includes:

- `raw_output_chars`
- `observation_preview_chars`
- `artifact_stored`
- `artifact_path`
- `artifact_sha256`
- `artifact_chars`
- `artifact_error` if storage fails

Short outputs do not create artifact files, but still record raw and preview
character counts. If artifact writing fails, the run should continue with a
bounded preview and an `artifact_error` metadata field instead of losing the tool
result.

## Replay And Report Metrics

Trace replay must aggregate:

- `raw_tool_output_chars`
- `tool_output_preview_chars`
- `stored_artifact_count`
- `artifact_missing_count`
- `artifact_hash_mismatch_count`
- `largest_tool_output_chars`
- `observation_compression_ratio`

Markdown eval reports and matrix reports should expose these metrics so model
comparisons can distinguish useful tool work from noisy output volume.

## Acceptance

- Unit tests prove large tool output is stored as an artifact.
- Unit tests prove trace/model observations use the preview, not the full raw
  output.
- Unit tests prove artifact hash and character-count metadata match the stored
  file.
- Unit tests prove artifact write failures do not crash the run path.
- Unit tests cover defensive redaction before artifact persistence.
- Markdown reports include raw output chars, preview chars, stored artifact
  count, artifact integrity, largest output size, and observation compression
  ratio.
- Existing unit tests remain green.
- HC-Bench-20 oracle remains 20/20.

## Non-Goals

- Do not store private `.env`, `models.toml`, or credential material.
- Do not add a remote artifact service.
- Do not change model providers or real-model credentials.
- Do not remove context packing, memory, compression, or RepoMap metrics.
