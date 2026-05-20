# HarnessCoder 1.3.0 Spec

## Goal

Add durable cross-run sessions so HarnessCoder can handle follow-up coding
tasks without turning into a general chat assistant.

The release closes a known gap: earlier TUI messages were displayed in one pane,
but each normal user message started a fresh `AgentRunner.run(...)` with no
durable conversation context. 1.3.0 makes that boundary explicit and traceable.

## Scope

- Add `SessionStore` under `harnesscoder/core/session.py`.
- Persist bounded turn summaries in
  `.harnesscoder/sessions/<session_id>.json`.
- Add CLI `--session <id>` and `--session-root <path>`.
- Add TUI `/session [id]` and `/reset-session [id]`.
- Inject compact `session_context` into prompt assembly.
- Record session use through `run_started`, `session_context_loaded`, and
  `context_packed.session_context_injected`.
- Store session context in `AgentState` so checkpoint/resume keeps the same
  cross-run context for an interrupted session-backed run.
- Extend replay metrics with `session_context_loaded_count` and
  `session_context_injected_count`.

## Runtime Contract

Durable sessions are not raw chat transcripts. They are bounded task summaries:

```json
{
  "session_id": "interview",
  "turn_count": 2,
  "summary": "recent bounded turn summary",
  "recent_turns": [
    {
      "user_message": "inspect the repo",
      "status": "success",
      "final_answer": "repo inspected",
      "run_id": "run_abc",
      "trace_path": ".harnesscoder/runs/run_abc/trace.jsonl"
    }
  ]
}
```

Each follow-up still starts a new run and a new trace. The session only provides
task-level continuity:

```text
session JSON -> session_context -> AgentRunner.run(task)
new run_id -> trace.jsonl/checkpoint.json/replay
run result -> append bounded summary back to session JSON
```

## Acceptance

- `python -m unittest discover -s tests` passes.
- `python -m harnesscoder --version` reports `harnesscoder 1.3.0`.
- `python -m harnesscoder --context-mode pack --session smoke "inspect this repo"`
  writes `.harnesscoder/sessions/smoke.json`.
- A session-backed trace contains `session_context_loaded`.
- Replay reports nonzero `session_context_loaded_count` and
  `session_context_injected_count` for a session-backed run.
- TUI `/session` can switch or show the active session, and `/reset-session`
  clears its durable turn summaries.

## Non-goals

- No long-term user memory platform.
- No hidden raw transcript stuffing into every prompt.
- No multi-agent platform.
- No product-level Claude Code clone.
- No benchmark claim until session-aware eval cases exist.

## Interview Angle

1.3.0 is the right answer to "does HC support multi-turn conversation?" The
precise answer is now:

> HC supports task-internal multi-step agent loops and durable cross-run task
> sessions. Each user follow-up can receive compact session context, but every
> agent run still has its own `run_id`, trace, checkpoint, replay summary, and
> failure attribution.

That keeps the project aligned with its core identity: not a chat memory product,
but a trace-backed coding-agent runtime where even cross-run context is
auditable.
