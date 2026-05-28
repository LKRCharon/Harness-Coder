# HarnessCoder 1.5.1 Spec

## Goal

Inject relevant long-term notes into context assembly.

1.5.0 makes notes explicit tools. 1.5.1 turns notes into a first-class context
source: the runtime can gather, select, structure, and budget relevant notes
before a model step.

## Scope

- Add `notes_mode` to `AgentRunner`:
  - `none`
  - `auto`
- Retrieve relevant notes before context assembly when `notes_mode=auto`.
- Prioritize note types in selection:
  - `blocker`
  - `task_state`
  - `verified_fact`
  - `decision`
  - `action`
  - `conclusion`
  - `general`
- Add `relevant_notes` to `ContextAssembly`.
- Add context budget accounting for the `relevant_notes` section.
- Emit trace evidence:
  - `note_injected`
  - `note_injected_count`
  - selected note ids and note types
- Add replay/report metrics for note injection.

## Runtime Contract

```text
NoteStore.search(task)
-> select by type/query/recency
-> relevant_notes section
-> context_packed.note_injected
-> model step
```

The model sees notes as bounded evidence records, not raw transcripts.

## Acceptance

- Runs with `notes_mode=auto` inject relevant notes into prompt payloads.
- `context_packed` records note ids and note section budget usage.
- Replay metrics count note injection.
- Note injection is bounded and deterministic.
- Existing context modes remain backward-compatible.

## Non-goals

- No LLM-based note summarization in this release.
- No vector search.
- No automatic note creation from model free text.

## Interview Angle

1.5.1 connects long-term notes to context governance:

> HC does not blindly append all prior context. It retrieves a bounded set of
> relevant task notes, ranks blockers and verified facts first, injects them as a
> structured context section, and records the exact note ids in trace.
