from __future__ import annotations

import asyncio
import json
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from harnesscoder.cli import resolve_model_profile
from harnesscoder.core.models import ScriptedModel
from harnesscoder.core.runner import AgentRunner
from harnesscoder.core.session import DEFAULT_SESSION_ROOT, SessionStore, normalize_session_id
from harnesscoder.replay import load_trace, summarize_trace


DEFAULT_TRACE_ROOT = Path(".harnesscoder/runs")
DEFAULT_SESSION_ROOT_WEB = DEFAULT_SESSION_ROOT
WEB_DEFAULT_CONTEXT_MODE = "pack"
WEB_DEFAULT_REPO_MAP_MODE = "auto"


class LaunchRunRequest(BaseModel):
    task: str = Field(min_length=1)
    model_profile: str = Field(default="scripted", min_length=1)
    max_iterations: int = Field(default=8, ge=1, le=128)
    notes_mode: Literal["none", "auto"] = "auto"
    session_id: str | None = None


@dataclass(slots=True)
class ActiveRun:
    run_id: str
    session_id: str
    task: str
    model_profile: str
    max_iterations: int
    notes_mode: str
    trace_path: Path
    submitted_at: str
    status: str = "queued"
    is_active: bool = True
    started_at: str | None = None
    ended_at: str | None = None
    error: str | None = None
    result_status: str | None = None
    final_answer: str | None = None
    thread: threading.Thread | None = field(default=None, repr=False, compare=False)


def create_app(
    trace_root: Path | None = None,
    workspace_root: Path | None = None,
    session_root: Path | None = None,
) -> FastAPI:
    app = FastAPI(title="HarnessCoder Web API", version="0.2.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    resolved_workspace_root = (workspace_root or Path(".")).resolve()
    resolved_trace_root = _resolve_trace_root(resolved_workspace_root, trace_root)
    resolved_session_root = _resolve_session_root(resolved_workspace_root, session_root)
    app.state.workspace_root = resolved_workspace_root
    app.state.trace_root = resolved_trace_root
    app.state.session_store = SessionStore(resolved_session_root, resolved_workspace_root)
    app.state.active_runs = {}
    app.state.active_runs_lock = threading.Lock()

    @app.get("/api/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/api/runs")
    def list_runs() -> dict[str, list[dict[str, Any]]]:
        return {"runs": _list_run_cards(app)}

    @app.get("/api/threads")
    def list_threads() -> dict[str, list[dict[str, Any]]]:
        return {"threads": _list_thread_cards(app)}

    @app.get("/api/threads/{session_id}")
    def get_thread(session_id: str) -> dict[str, Any]:
        normalized_session_id = normalize_session_id(session_id)
        thread = _thread_detail(app, normalized_session_id)
        if thread is None:
            raise HTTPException(status_code=404, detail=f"thread not found: {normalized_session_id}")
        return {"thread": thread}

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, Any]:
        trace_path = _trace_path_for_run(resolved_trace_root, run_id)
        active_run = _get_active_run(app, run_id)
        if trace_path.is_file():
            summary = _overlay_summary(summarize_trace(trace_path), active_run)
        elif active_run is not None:
            summary = _active_run_summary(active_run)
        else:
            raise HTTPException(status_code=404, detail=f"run not found: {run_id}")
        return {
            "run": {
                "run_id": run_id,
                "trace_path": str(trace_path),
                "summary": summary,
                "stream_path": f"/api/runs/{run_id}/stream",
                "is_active": bool(active_run and active_run.is_active),
            }
        }

    @app.post("/api/runs", status_code=202)
    def create_run(request: LaunchRunRequest) -> dict[str, Any]:
        run_id = _new_run_id()
        trace_path = _trace_path_for_run(resolved_trace_root, run_id)
        session_id = normalize_session_id(request.session_id) if request.session_id else f"thread_{uuid4().hex[:10]}"
        active_run = ActiveRun(
            run_id=run_id,
            session_id=session_id,
            task=request.task.strip(),
            model_profile=request.model_profile.strip(),
            max_iterations=request.max_iterations,
            notes_mode=request.notes_mode,
            trace_path=trace_path,
            submitted_at=_now(),
        )
        _store_active_run(app, active_run)
        worker = threading.Thread(
            target=_run_in_background,
            args=(app, active_run),
            daemon=True,
            name=f"hc-web-{run_id}",
        )
        active_run.thread = worker
        worker.start()
        return {"run": _active_run_card(active_run)}

    @app.get("/api/runs/{run_id}/trace")
    def get_trace_meta(run_id: str) -> dict[str, Any]:
        trace_path = _trace_path_for_run(resolved_trace_root, run_id)
        if not trace_path.is_file():
            raise HTTPException(status_code=404, detail=f"run not found: {run_id}")
        records = load_trace(trace_path)
        return {
            "run_id": run_id,
            "trace_path": str(trace_path),
            "event_count": len(records),
        }

    @app.get("/api/runs/{run_id}/events")
    def get_run_events(
        run_id: str,
        event_type: list[str] = Query(default=[]),
        limit: int | None = Query(default=None, ge=1, le=5000),
    ) -> dict[str, Any]:
        trace_path = _trace_path_for_run(resolved_trace_root, run_id)
        active_run = _get_active_run(app, run_id)
        if not trace_path.is_file():
            if active_run is not None:
                return {"run_id": run_id, "events": []}
            raise HTTPException(status_code=404, detail=f"run not found: {run_id}")
        filtered = _filter_records(load_trace(trace_path), event_type)
        if limit is not None:
            filtered = filtered[:limit]
        return {"run_id": run_id, "events": filtered}

    @app.get("/api/runs/{run_id}/stream")
    async def stream_run_events(
        run_id: str,
        from_index: int = Query(default=0, ge=0),
        event_type: list[str] = Query(default=[]),
        follow: bool = Query(default=True),
    ) -> StreamingResponse:
        trace_path = _trace_path_for_run(resolved_trace_root, run_id)
        active_run = _get_active_run(app, run_id)
        if not trace_path.is_file() and active_run is None:
            raise HTTPException(status_code=404, detail=f"run not found: {run_id}")

        async def event_stream() -> Any:
            next_index = from_index
            last_run_state: dict[str, Any] | None = None
            yield _sse_frame("connected", {"run_id": run_id, "from_index": from_index})
            while True:
                active_snapshot = _get_active_run(app, run_id)
                run_state = _run_state_payload(run_id, trace_path, active_snapshot)
                if run_state != last_run_state:
                    yield _sse_frame("run_state", run_state)
                    last_run_state = run_state

                if trace_path.is_file():
                    records = load_trace(trace_path)
                    for event in _filter_records(records, event_type, from_index=next_index):
                        yield _sse_frame("trace_event", {"run_id": run_id, **event})
                        next_index = event["index"] + 1
                    if _trace_is_finished(records) and not (active_snapshot and active_snapshot.is_active):
                        yield _sse_frame(
                            "end",
                            {"run_id": run_id, "status": run_state["status"], "is_active": False},
                        )
                        break
                elif not follow:
                    yield _sse_frame(
                        "end",
                        {
                            "run_id": run_id,
                            "status": run_state["status"],
                            "is_active": run_state["is_active"],
                        },
                    )
                    break

                if not follow:
                    yield _sse_frame(
                        "end",
                        {
                            "run_id": run_id,
                            "status": run_state["status"],
                            "is_active": run_state["is_active"],
                        },
                    )
                    break

                if active_snapshot is None and not trace_path.is_file():
                    break
                await asyncio.sleep(0.25)

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    return app


def _resolve_trace_root(workspace_root: Path, trace_root: Path | None) -> Path:
    if trace_root is None:
        return (workspace_root / DEFAULT_TRACE_ROOT).resolve()
    if trace_root.is_absolute():
        return trace_root.resolve()
    return (workspace_root / trace_root).resolve()


def _resolve_session_root(workspace_root: Path, session_root: Path | None) -> Path:
    if session_root is None:
        return (workspace_root / DEFAULT_SESSION_ROOT_WEB).resolve()
    if session_root.is_absolute():
        return session_root.resolve()
    return (workspace_root / session_root).resolve()


def _list_run_summaries(trace_root: Path) -> list[dict[str, Any]]:
    if not trace_root.is_dir():
        return []
    summaries: list[dict[str, Any]] = []
    for trace_path in sorted(
        trace_root.glob("*/trace.jsonl"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    ):
        try:
            summaries.append(summarize_trace(trace_path))
        except Exception:
            continue
    return summaries


def _list_run_cards(app: FastAPI) -> list[dict[str, Any]]:
    trace_root = app.state.trace_root
    cards = {
        card["run_id"]: card
        for card in (
            _run_card(summary, trace_root, _get_active_run(app, summary.get("run_id")))
            for summary in _list_run_summaries(trace_root)
        )
        if card.get("run_id")
    }
    for active_run in _list_active_runs(app):
        cards.setdefault(active_run.run_id, _active_run_card(active_run))
    return sorted(
        cards.values(),
        key=lambda card: str(card.get("started_at") or card.get("submitted_at") or ""),
        reverse=True,
    )


def _run_card(
    summary: dict[str, Any],
    trace_root: Path,
    active_run: ActiveRun | None,
) -> dict[str, Any]:
    model_metadata = summary.get("model_metadata") or {}
    timing = summary.get("timing") or {}
    run_id = summary.get("run_id")
    status = summary.get("status")
    if active_run is not None:
        status = _display_status(summary.get("status"), active_run)
    return {
        "run_id": run_id,
        "session_id": summary.get("session_id") or (active_run.session_id if active_run else None),
        "trace_path": str(_trace_path_for_run(trace_root, run_id))
        if isinstance(run_id, str) and run_id
        else None,
        "task": summary.get("task"),
        "status": status,
        "model": summary.get("model") or (active_run.model_profile if active_run else None),
        "provider": model_metadata.get("provider"),
        "started_at": timing.get("started_at") if isinstance(timing, dict) else None,
        "submitted_at": active_run.submitted_at if active_run else None,
        "duration_seconds": summary.get("duration_seconds"),
        "iterations": summary.get("iterations"),
        "max_iterations": summary.get("max_iterations"),
        "total_events": summary.get("total_events"),
        "failure_category": summary.get("failure_category"),
        "is_active": bool(active_run and active_run.is_active),
        "stream_path": f"/api/runs/{run_id}/stream" if isinstance(run_id, str) and run_id else None,
    }


def _trace_path_for_run(trace_root: Path, run_id: str) -> Path:
    return (trace_root / run_id / "trace.jsonl").resolve()


def _filter_records(
    records: list[dict[str, Any]],
    event_types: list[str],
    *,
    from_index: int = 0,
) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    type_filter = set(event_types)
    for index, record in enumerate(records):
        if index < from_index:
            continue
        record_type = str(record.get("type", "<missing>"))
        if type_filter and record_type not in type_filter:
            continue
        payload = {key: value for key, value in record.items() if key not in {"type", "ts"}}
        filtered.append(
            {
                "index": index,
                "type": record_type,
                "ts": record.get("ts"),
                "payload": payload,
            }
        )
    return filtered


def _trace_is_finished(records: list[dict[str, Any]]) -> bool:
    return any(record.get("type") == "run_finished" for record in records)


def _sse_frame(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _new_run_id() -> str:
    return f"run_{uuid4().hex[:12]}"


def _run_in_background(app: FastAPI, active_run: ActiveRun) -> None:
    try:
        _update_active_run(app, active_run.run_id, status="running", started_at=_now())
        session_store: SessionStore = app.state.session_store
        session_context = session_store.build_context(active_run.session_id)
        runner = AgentRunner(
            model=_build_model_for_profile(active_run.model_profile, app.state.workspace_root),
            cwd=app.state.workspace_root,
            trace_root=app.state.trace_root,
            max_iterations=active_run.max_iterations,
            context_mode=WEB_DEFAULT_CONTEXT_MODE,
            repo_map_mode=WEB_DEFAULT_REPO_MAP_MODE,
            notes_mode=active_run.notes_mode,
        )
        result = runner.run(
            active_run.task,
            run_id=active_run.run_id,
            session_context=session_context,
        )
        session_store.append_run(
            active_run.session_id,
            user_message=active_run.task,
            result=result,
        )
    except Exception as exc:
        _update_active_run(
            app,
            active_run.run_id,
            status="launch_error",
            ended_at=_now(),
            is_active=False,
            error=f"{type(exc).__name__}: {exc}",
        )
        return

    _update_active_run(
        app,
        active_run.run_id,
        status=result.status,
        result_status=result.status,
        final_answer=result.final_answer,
        ended_at=_now(),
        is_active=False,
    )


def _build_model_for_profile(model_profile: str, workspace_root: Path) -> Any:
    profile_name = model_profile.strip()
    if profile_name == "scripted":
        return ScriptedModel()
    args = SimpleNamespace(
        model_config=os.environ.get("HARNESSCODER_MODEL_CONFIG", "models.toml"),
        cwd=str(workspace_root),
    )
    return resolve_model_profile(profile_name, args, workspace_root).build()


def _store_active_run(app: FastAPI, active_run: ActiveRun) -> None:
    with app.state.active_runs_lock:
        app.state.active_runs[active_run.run_id] = active_run


def _get_active_run(app: FastAPI, run_id: str | None) -> ActiveRun | None:
    if not run_id:
        return None
    with app.state.active_runs_lock:
        return app.state.active_runs.get(run_id)


def _list_active_runs(app: FastAPI) -> list[ActiveRun]:
    with app.state.active_runs_lock:
        return list(app.state.active_runs.values())


def _update_active_run(app: FastAPI, run_id: str, **changes: Any) -> None:
    with app.state.active_runs_lock:
        active_run = app.state.active_runs.get(run_id)
        if active_run is None:
            return
        for key, value in changes.items():
            setattr(active_run, key, value)


def _active_run_card(active_run: ActiveRun) -> dict[str, Any]:
    return {
        "run_id": active_run.run_id,
        "session_id": active_run.session_id,
        "trace_path": str(active_run.trace_path),
        "task": active_run.task,
        "status": active_run.status,
        "model": active_run.model_profile,
        "provider": None,
        "started_at": active_run.started_at,
        "submitted_at": active_run.submitted_at,
        "duration_seconds": None,
        "iterations": 0,
        "max_iterations": active_run.max_iterations,
        "total_events": 0,
        "failure_category": active_run.status if not active_run.is_active else None,
        "is_active": active_run.is_active,
        "stream_path": f"/api/runs/{active_run.run_id}/stream",
    }


def _active_run_summary(active_run: ActiveRun) -> dict[str, Any]:
    return {
        "run_id": active_run.run_id,
        "session_id": active_run.session_id,
        "status": active_run.status,
        "task": active_run.task,
        "model": active_run.model_profile,
        "failure_category": active_run.status if not active_run.is_active else None,
        "iterations": 0,
        "max_iterations": active_run.max_iterations,
        "total_events": 0,
        "duration_seconds": None,
        "event_counts": {},
        "metrics": {},
        "tool_counts": {},
        "timing": {
            "started_at": active_run.started_at,
            "submitted_at": active_run.submitted_at,
            "ended_at": active_run.ended_at,
        },
    }


def _overlay_summary(summary: dict[str, Any], active_run: ActiveRun | None) -> dict[str, Any]:
    if active_run is None:
        return summary
    merged = dict(summary)
    merged["session_id"] = summary.get("session_id") or active_run.session_id
    merged["status"] = _display_status(summary.get("status"), active_run)
    merged["task"] = summary.get("task") or active_run.task
    merged["model"] = summary.get("model") or active_run.model_profile
    timing = dict(summary.get("timing") or {})
    timing.setdefault("submitted_at", active_run.submitted_at)
    if active_run.started_at:
        timing["started_at"] = timing.get("started_at") or active_run.started_at
    if active_run.ended_at:
        timing["ended_at"] = timing.get("ended_at") or active_run.ended_at
    merged["timing"] = timing
    return merged


def _display_status(summary_status: Any, active_run: ActiveRun) -> str:
    if active_run.is_active:
        return active_run.status
    if isinstance(summary_status, str) and summary_status:
        return summary_status
    return active_run.status


def _run_state_payload(
    run_id: str,
    trace_path: Path,
    active_run: ActiveRun | None,
) -> dict[str, Any]:
    if active_run is None:
        status = summarize_trace(trace_path).get("status") if trace_path.is_file() else "unknown"
        return {
            "run_id": run_id,
            "status": status,
            "is_active": False,
            "trace_available": trace_path.is_file(),
            "submitted_at": None,
            "started_at": None,
            "ended_at": None,
            "error": None,
        }
    return {
        "run_id": run_id,
        "session_id": active_run.session_id,
        "status": active_run.status,
        "is_active": active_run.is_active,
        "trace_available": trace_path.is_file(),
        "submitted_at": active_run.submitted_at,
        "started_at": active_run.started_at,
        "ended_at": active_run.ended_at,
        "error": active_run.error,
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _list_thread_cards(app: FastAPI) -> list[dict[str, Any]]:
    cards: dict[str, dict[str, Any]] = {}
    session_store: SessionStore = app.state.session_store
    for session_path in sorted(session_store.root.glob("*.json")):
        try:
            session_id = session_path.stem
            record = session_store.load(session_id)
        except Exception:
            continue
        cards[record.session_id] = _thread_card_from_record(app, record)
    for active_run in _list_active_runs(app):
        existing = cards.get(active_run.session_id)
        if existing is None:
            cards[active_run.session_id] = _active_thread_card(active_run)
            continue
        existing["is_active"] = True
        existing["status"] = active_run.status
        existing["latest_run_id"] = active_run.run_id
        existing["task"] = active_run.task
        existing["updated_at"] = active_run.started_at or active_run.submitted_at
        existing["run_count"] = max(int(existing.get("run_count") or 0), 1)
    return sorted(
        cards.values(),
        key=lambda card: str(card.get("updated_at") or card.get("created_at") or ""),
        reverse=True,
    )


def _thread_detail(app: FastAPI, session_id: str) -> dict[str, Any] | None:
    session_store: SessionStore = app.state.session_store
    record = session_store.load(session_id)
    active_runs = [run for run in _list_active_runs(app) if run.session_id == session_id]
    if not record.turns and not active_runs:
        return None
    run_cards = _thread_run_cards(app, record, active_runs)
    latest_run_id = run_cards[0]["run_id"] if run_cards else None
    return {
        "session_id": record.session_id,
        "summary": record.summary,
        "cwd": record.cwd,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "turn_count": len(record.turns),
        "latest_run_id": latest_run_id,
        "is_active": any(run.is_active for run in active_runs),
        "runs": run_cards,
    }


def _thread_card_from_record(app: FastAPI, record: Any) -> dict[str, Any]:
    latest_turn = record.turns[-1] if record.turns else {}
    latest_run_id = latest_turn.get("run_id")
    latest_run_summary = _safe_run_summary(app.state.trace_root, latest_run_id)
    return {
        "session_id": record.session_id,
        "task": latest_turn.get("user_message") or None,
        "status": (
            latest_run_summary.get("status")
            if isinstance(latest_run_summary, dict)
            else latest_turn.get("status")
        ),
        "summary": record.summary,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "run_count": len(record.turns),
        "latest_run_id": latest_run_id,
        "is_active": False,
        "latest_run_status": latest_turn.get("status"),
    }


def _active_thread_card(active_run: ActiveRun) -> dict[str, Any]:
    return {
        "session_id": active_run.session_id,
        "task": active_run.task,
        "status": active_run.status,
        "summary": "",
        "created_at": active_run.submitted_at,
        "updated_at": active_run.started_at or active_run.submitted_at,
        "run_count": 1,
        "latest_run_id": active_run.run_id,
        "is_active": active_run.is_active,
        "latest_run_status": active_run.status,
    }


def _thread_run_cards(
    app: FastAPI,
    record: Any,
    active_runs: list[ActiveRun],
) -> list[dict[str, Any]]:
    active_by_run_id = {run.run_id: run for run in active_runs}
    cards: list[dict[str, Any]] = []
    for turn in reversed(record.turns):
        run_id = turn.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            continue
        summary = _safe_run_summary(app.state.trace_root, run_id)
        active_run = active_by_run_id.pop(run_id, None)
        if summary is not None:
            cards.append(_run_card(summary, app.state.trace_root, active_run))
            continue
        if active_run is not None:
            cards.append(_active_run_card(active_run))
            continue
        cards.append(
            {
                "run_id": run_id,
                "session_id": record.session_id,
                "trace_path": turn.get("trace_path"),
                "task": turn.get("user_message"),
                "status": turn.get("status"),
                "model": None,
                "provider": None,
                "started_at": turn.get("created_at"),
                "submitted_at": turn.get("created_at"),
                "duration_seconds": None,
                "iterations": None,
                "max_iterations": None,
                "total_events": None,
                "failure_category": None,
                "is_active": False,
                "stream_path": f"/api/runs/{run_id}/stream",
            }
        )
    for active_run in active_by_run_id.values():
        cards.insert(0, _active_run_card(active_run))
    return cards


def _safe_run_summary(trace_root: Path, run_id: Any) -> dict[str, Any] | None:
    if not isinstance(run_id, str) or not run_id:
        return None
    trace_path = _trace_path_for_run(trace_root, run_id)
    if not trace_path.is_file():
        return None
    try:
        return summarize_trace(trace_path)
    except Exception:
        return None


app = create_app()
