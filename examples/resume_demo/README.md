# Resume Demo

This fixture shows the smallest 0.3.0 resume story:

1. The agent starts a repository-orientation task.
2. It completes exploration with `search_code` and `read_file`.
3. The runtime packs the explored context into `context_packed`.
4. An interrupt creates `checkpoint.json`.
5. A later resume loads the checkpoint and finishes from the packed context.

Files:

- `interrupt_resume_trace.jsonl`: synthetic trace for the full interrupted and
  resumed story.
- `checkpoint.json`: minimal checkpoint snapshot referenced by the trace.

The important behavior is that the resumed segment does not repeat the earlier
exploration tools. It continues from the packed context.
