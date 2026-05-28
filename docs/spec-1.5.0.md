# HarnessCoder 1.5.0 Spec

## Goal

Add long-term task notes for codebase maintenance runs.

HarnessCoder already has task-local memory blocks and durable cross-run session
summaries. Those are useful, but they do not yet model the codebase-maintenance
facts that should survive across runs: blockers, actions, task state, decisions,
conclusions, and verified facts. 1.5.0 adds a local NoteStore and model-callable
note tools so long-horizon coding work can keep explicit task state without
depending on an external agent framework.

## Scope

- Add `harnesscoder/core/notes.py` with a local Markdown-backed `NoteStore`.
- Store notes under `.harnesscoder/notes/` by default as:
  - one note per Markdown file with frontmatter
  - a machine index at `.harnesscoder/notes/notes_index.json`
- Define note types:
  - `blocker`
  - `action`
  - `task_state`
  - `decision`
  - `conclusion`
  - `verified_fact`
  - `general`
- Add model-callable tools:
  - `create_note`
  - `search_notes`
- Add policy validation for note type, title/content shape, tag shape, and
  bounded query/limit values.
- Add prompt/tool-schema instructions that tell the model when notes are useful.
- Add trace and replay evidence:
  - `note_created`
  - `note_retrieved`
  - `note_created_count`
  - `note_retrieved_count`
- Keep notes local, ignored, human-readable, and secret-safe.

## Runtime Contract

Notes are durable task-state records, not hidden chat memory:

```json
{
  "note_id": "note_...",
  "type": "blocker",
  "title": "Tests fail in billing proration",
  "content": "The targeted test fails because ...",
  "tags": ["billing", "regression"],
  "source_run_id": "run_...",
  "source_call_id": "call_...",
  "created_at": "2026-05-28T...",
  "updated_at": "2026-05-28T..."
}
```

The model can explicitly write a note when a fact should survive the current
run:

```text
ModelAction(create_note) -> policy -> NoteStore -> ToolObservation
```

The model can explicitly retrieve notes before continuing a long-horizon task:

```text
ModelAction(search_notes) -> policy -> NoteStore.search(query) -> observation
```

1.5.0 does not automatically inject all notes into every prompt. Automatic note
selection belongs in 1.5.1 so this release can keep the first boundary simple:
durable note creation and retrieval are explicit, policy-gated tool actions.

## Acceptance

- `python -m unittest tests.test_runtime_features tests.test_model_adapter -v`
  passes.
- `python -m harnesscoder --version` reports `harnesscoder 1.5.0`.
- `create_note` writes a note under `.harnesscoder/notes/*.md` and updates
  `.harnesscoder/notes/notes_index.json`.
- `search_notes` returns bounded, relevant note records.
- Policy rejects unsupported note types, empty content, invalid tags, and
  excessive search limits.
- Trace summaries include note creation and retrieval counts.
- The model prompt lists both note tools and explains their intended use.

## Non-goals

- No dependency on `hello-agents` or any external agent framework.
- No vector database or semantic RAG.
- No automatic note injection into every prompt.
- No long-term user profile memory.
- No multi-agent planner.
- No note synchronization to a remote service.

## Interview Angle

1.5.0 is the answer to "how does HC support long-running codebase maintenance?"

> HC treats durable task knowledge as explicit, policy-gated notes. A run can
> record a blocker, decision, action, task state, conclusion, or verified fact,
> and later retrieve those notes as tool observations. This keeps long-horizon
> state auditable: notes are local Markdown files, every creation/retrieval is
> traced, and replay reports can show whether the agent used durable task memory
> instead of silently stuffing old chat into context.
