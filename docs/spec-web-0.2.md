# HarnessCoder Web 0.2 Spec

## Goal

Advance the web surface from a read-only trace viewer into a minimal local
runtime console.

Web 0.2 must keep HarnessCoder's ownership boundary intact:

- Python runtime stays authoritative
- `AgentRunner` still owns run execution
- trace JSONL remains the source of truth
- the browser becomes a control + observability surface, not a second runtime

## Scope

### In Scope

- `POST /api/runs` to launch one local run
- `GET /api/runs/{run_id}/stream` for SSE trace streaming
- a small "New Run" launcher on the runs page
- run detail live updates while a run is active

### Out of Scope

- browser-side file editing
- multi-user support
- auth
- cloud deployment
- eval matrix launch from Web
- session/thread management UI
- deep notes/context standalone pages

## Product Boundary

Correct flow:

```text
Browser
-> HC Web API
-> AgentRunner
-> TraceWriter
-> trace.jsonl
-> SSE / replay summary
-> Browser
```

Forbidden in 0.2:

- browser direct model calls
- browser direct filesystem writes
- frontend-owned run state that can diverge from trace/runtime state

## Launch Model

Web 0.2 launches exactly one foreground HC run per request, but the API returns
immediately and executes the run in a background thread inside the local HC web
process.

The launcher is intentionally narrow:

- `task`
- `model_profile`
- `max_iterations`
- `notes_mode`

Fixed runtime defaults for 0.2:

- `context_mode = "pack"`
- `repo_map_mode = "auto"`
- `cwd = repo workspace root`
- `trace_root = configured local trace root`

## Backend API

### `POST /api/runs`

Launch a new local run.

Request:

```json
{
  "task": "Summarize this repo in one sentence",
  "model_profile": "scripted",
  "max_iterations": 8,
  "notes_mode": "auto"
}
```

Request rules:

- `task` required, non-empty
- `model_profile` optional, defaults to `scripted`
- `max_iterations` optional, defaults to `8`
- `notes_mode` optional, one of `none|auto`, defaults to `auto`

Response:

```json
{
  "run": {
    "run_id": "run_abcd1234ef56",
    "task": "Summarize this repo in one sentence",
    "status": "queued",
    "model_profile": "scripted",
    "trace_path": "/abs/path/.harnesscoder/runs/run_abcd1234ef56/trace.jsonl",
    "submitted_at": "2026-05-28T14:00:00+00:00",
    "started_at": null,
    "is_active": true,
    "stream_path": "/api/runs/run_abcd1234ef56/stream",
    "max_iterations": 8,
    "notes_mode": "auto"
  }
}
```

Semantics:

- return `202 Accepted`
- allocate `run_id` before execution
- start the run asynchronously
- if the trace is not created yet, the run still exists in web-local active-run
  state

### `GET /api/runs/{run_id}/stream`

Server-Sent Events stream for one run.

Query params:

- `from_index` optional global trace event index offset, default `0`
- `event_type` optional repeatable filter
- `follow` optional bool, default `true`

Behavior:

- if trace already exists, emit matching historical events from `from_index`
- if run is still active, keep streaming appended events
- if run is active but trace is not created yet, keep the stream open and emit
  run-state updates
- if the run is finished and no more events remain, emit `end` and close

### SSE Event Shape

#### `event: connected`

```json
{
  "run_id": "run_abcd1234ef56",
  "from_index": 0
}
```

#### `event: run_state`

```json
{
  "run_id": "run_abcd1234ef56",
  "status": "running",
  "is_active": true,
  "trace_available": true,
  "submitted_at": "2026-05-28T14:00:00+00:00",
  "started_at": "2026-05-28T14:00:01+00:00",
  "ended_at": null,
  "error": null
}
```

#### `event: trace_event`

```json
{
  "run_id": "run_abcd1234ef56",
  "index": 3,
  "type": "tool_result",
  "ts": "2026-05-28T14:00:03+00:00",
  "payload": {
    "result": {}
  }
}
```

#### `event: end`

```json
{
  "run_id": "run_abcd1234ef56",
  "status": "success",
  "is_active": false
}
```

## Frontend

### Runs Page

Add a compact launcher panel above the runs table:

- task textarea
- model profile input
- max iterations input
- notes mode select
- launch button

### Run Detail Page

Keep the current trace-viewer layout, but make it live:

- fetch run summary
- fetch current filtered events
- open SSE stream
- append new matching events
- refresh summary while events arrive
- show connection/run-state badges

## Verification

Backend:

```bash
python -m unittest tests.test_web_api -v
python -m unittest discover -s tests
python -m harnesscoder --version
```

Frontend:

```bash
cd apps/web
npm run lint
npm run build
```
