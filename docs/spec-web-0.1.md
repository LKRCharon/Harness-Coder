# HarnessCoder Web 0.1 Spec

## Goal

Add a local web control panel and observability surface for HarnessCoder
without changing the ownership boundary of the runtime.

HarnessCoder Core remains a Python runtime:

- `AgentRunner` owns the loop
- local tools and workspace access remain in Python
- traces, checkpoints, notes, and eval reports remain the source of truth

The web surface is a local control panel:

- submit tasks
- inspect runs
- inspect traces
- inspect notes, context, and plan evidence

This release only implements `Phase 0: Trace Viewer`.

## Product Boundary

The web layer must not turn HarnessCoder into a web-native agent app.

Correct structure:

```text
Browser
-> HC Web API
-> HC Runtime
-> Model Provider + Tools + Workspace
-> TraceWriter
-> Browser
```

Forbidden in 0.1:

- browser direct-to-model API calls
- browser direct filesystem access
- browser as source of truth for run state
- replacing CLI/TUI/runtime with frontend logic

## Scope

### Phase 0: Trace Viewer

Read-only local dashboard for existing traces.

Deliverables:

- local FastAPI backend
- local React frontend
- runs list page
- run detail page
- trace event timeline
- event-type filtering
- structured panels for core event kinds

### Out of Scope

- launching new runs from the web UI
- streaming active runs
- editing files from the browser
- multi-user support
- authentication
- cloud deployment
- online IDE/editor

## Architecture

### Backend

Location:

- `harnesscoder/web_api/`

Responsibilities:

- enumerate local runs from trace roots
- read and parse `trace.jsonl`
- summarize runs using existing replay logic where useful
- expose read-only JSON endpoints

Do not duplicate runtime logic already implemented in:

- `harnesscoder/core/*`
- `harnesscoder/replay.py`

### Frontend

Location:

- `apps/web/`

Responsibilities:

- render run list
- render run detail
- filter and inspect trace events
- show structured runtime evidence

Recommended stack:

- Vite
- React
- TypeScript
- Tailwind CSS
- shadcn/ui

## Pages

### 1. Runs Page

Path:

- `/`
- `/runs`

Purpose:

- list existing runs under local trace roots

Each row shows:

- `run_id`
- task preview
- status
- model / provider
- started time
- duration
- total events
- iteration count
- failure category

### 2. Run Detail Page

Path:

- `/runs/:runId`

Purpose:

- inspect one trace as a structured runtime timeline

Layout:

- left: event timeline
- center: selected event detail
- right: run summary / context / notes / plan facts

Panels:

- run header
- event-type filters
- timeline list
- selected event JSON/detail card
- summary sidebar

## Backend API

### `GET /api/health`

Returns:

```json
{
  "ok": true
}
```

### `GET /api/runs`

List local runs.

Response:

```json
{
  "runs": [
    {
      "run_id": "run_abc",
      "trace_path": "/abs/path/.harnesscoder/runs/run_abc/trace.jsonl",
      "task": "Inspect the repo",
      "status": "success",
      "model": "scripted",
      "provider": "scripted",
      "started_at": "2026-05-28T12:00:00Z",
      "duration_seconds": 1.23,
      "iterations": 2,
      "max_iterations": 8,
      "total_events": 18,
      "failure_category": "success"
    }
  ]
}
```

### `GET /api/runs/{run_id}`

Return one run summary.

Response:

```json
{
  "run": {
    "run_id": "run_abc",
    "trace_path": "/abs/path/.harnesscoder/runs/run_abc/trace.jsonl",
    "summary": {}
  }
}
```

`summary` should be derived from `harnesscoder.replay.summarize_trace(...)`.

### `GET /api/runs/{run_id}/events`

Return parsed trace events for one run.

Query params:

- `event_type` optional repeatable filter
- `limit` optional integer

Response:

```json
{
  "run_id": "run_abc",
  "events": [
    {
      "index": 0,
      "type": "run_started",
      "ts": "2026-05-28T12:00:00Z",
      "payload": {}
    }
  ]
}
```

### `GET /api/runs/{run_id}/trace`

Return raw trace metadata:

```json
{
  "run_id": "run_abc",
  "trace_path": "/abs/path/.harnesscoder/runs/run_abc/trace.jsonl",
  "event_count": 18
}
```

## SSE Event Shape

SSE is specified in 0.1 for forward compatibility, but not required to be
implemented until run-launch support exists.

Endpoint shape:

- `GET /api/runs/{run_id}/stream`

Event payload shape:

```json
{
  "run_id": "run_abc",
  "index": 12,
  "type": "tool_result",
  "ts": "2026-05-28T12:00:02Z",
  "payload": {}
}
```

Rules:

- each SSE item corresponds to one trace event
- event ordering follows trace line order
- UI must treat SSE payloads as trace-derived facts, not inferred state

## Trace Mapping

The UI should render facts by mapping existing trace events, not by inventing a
parallel client-side state machine.

### Run Header

Derived from:

- `run_started`
- `run_finished`
- replay summary

### Timeline

Render these event types with distinct cards:

- `run_started`
- `session_context_loaded`
- `context_packed`
- `context_quality_evaluated`
- `note_injected`
- `model_action`
- `plan_created`
- `plan_updated`
- `step_started`
- `step_completed`
- `step_blocked`
- `policy_decision`
- `tool_result`
- `test_result`
- `memory_updated`
- `checkpoint_created`
- `run_finished`
- `model_error`

### Right Sidebar

#### Summary panel

Derived from replay summary:

- status
- duration
- iterations
- failure category
- tool counts

#### Notes panel

Derived from:

- `note_created`
- `note_retrieved`
- `note_injected`

#### Context panel

Derived from:

- `context_packed`
- `context_quality_evaluated`

Show:

- relevant note count
- context token estimate
- reduced sections
- dropped blocks
- context quality score
- warnings / suggestions

#### Plan panel

Derived from:

- `plan_created`
- `plan_updated`
- `step_started`
- `step_completed`
- `step_blocked`
- `model_action.current_step_id`

Show:

- plan revision count
- steps
- current step
- blocked count
- action-with-step ratio

## Frontend Components

Phase 0 should keep a small component set:

- `RunTable`
- `RunStatusBadge`
- `EventTypeFilter`
- `EventTimeline`
- `TraceEventCard`
- `SummaryPanel`
- `NotesPanel`
- `ContextPanel`
- `PlanPanel`

## Acceptance

- local backend starts and lists existing runs
- local frontend starts and displays the runs list
- clicking a run opens a detail page
- run detail shows timeline entries for existing trace events
- event-type filters work
- notes/context/plan summary panels are derived from trace/replay facts
- no browser-side model calls or filesystem mutation exists

## Interview Angle

Web 0.1 is not a pivot away from the runtime.

> HarnessCoder keeps the Python runtime as the only agent executor. The web
> layer is an observability panel over replayable traces, not a replacement for
> the runtime. That preserves the core claim: runs are still explained by trace,
> checkpoint, notes, and replay, while the UI simply makes those artifacts
> inspectable.
