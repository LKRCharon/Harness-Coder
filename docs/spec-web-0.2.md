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

### Runtime Workbench Direction

Web 0.2 should no longer read like a dashboard or a trace-admin page. The
target surface is a local runtime workbench:

- left: threads/navigation
- center: conversation workspace
- right: inspector
- bottom: command-style composer

The browser still remains a control + observability surface over the Python
runtime, but the UI should present that runtime as a readable execution story,
not a pile of tables or metric cards.

### Visual System Rules

The web surface should follow these rules:

- use low-contrast gray-blue dark surfaces, not pure black
- do not use terminal-style full-black dark mode
- use a Codex-like layered workbench, not a flat monitor wall
- use semantic color roles, not decorative accent color
- let surface hierarchy, spacing, and density carry structure
- keep borders minimal; borders are hints, not the skeleton
- keep the center workspace and bottom composer as the visual priority

Spatial expression:

- left sidebar behaves like a quiet app shell
- center workspace is the primary execution surface
- right inspector and bottom composer should read as operating surfaces floating
  above the workspace
- layering should be communicated through surface brightness, shadow, radius,
  and spacing before border

Color roles:

- blue: active, focus, running, links
- green: success, connected, completed
- amber: attention, approval, warning, pending
- red: failed, error, destructive states
- purple: context, memory, notes when those concepts are shown
- cyan: trace, tool, stream when a secondary accent is helpful

Surface hierarchy:

- `L0`: app background
- `L1`: navigation and inspector
- `L2`: workspace background
- `L3`: content blocks such as messages, runtime summaries, and timeline items
- `L4`: composer, current selection, and focused states

The UI should make the current focus legible even with borders turned down.

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

### Runtime Workbench Expression

As the runs page evolves into `/workbench`, it should follow this expression:

- user task appears as a message bubble, not a field card
- runtime summary appears as an agent response, not a KPI grid
- tool activity appears as timeline events, not thick stacked cards
- composer appears as a command bar, not a settings form

The center column should answer this reading flow:

1. what the user asked
2. what the runtime is currently doing
3. which actions it took
4. whether approval or attention is needed
5. what result it produced

The right column should absorb detailed properties, traces, files, and context
metadata so that the center column stays readable.

The workbench should feel layered rather than boxed:

- the sidebar stays quiet
- the workspace stays broad and stable
- the inspector and composer feel slightly elevated from the workspace
- hierarchy should come from surfaces and spacing, not thick dividers

For a more detailed visual system, see `docs/workbench-design-language.md`.

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
