from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


JsonRecord = dict[str, Any]


def load_trace(path: str | Path) -> list[JsonRecord]:
    """Load a HarnessCoder JSONL trace.

    ``path`` may point directly at ``trace.jsonl`` or at a run directory that
    contains it.
    """

    trace_path = _resolve_trace_path(path)
    records: list[JsonRecord] = []
    with trace_path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"{trace_path}:{line_number}: invalid JSON: {exc.msg}"
                ) from exc
            if not isinstance(record, dict):
                raise ValueError(f"{trace_path}:{line_number}: expected JSON object")
            records.append(record)
    return records


def summarize_trace(path: str | Path) -> JsonRecord:
    """Return a structured summary for a HarnessCoder trace."""

    records = load_trace(path)
    event_counts = Counter(_event_type(record) for record in records)
    tool_stats = _summarize_tools(records)
    state = reconstruct_state_from_records(records)
    run_started = _last_event(records, "run_started") or {}
    run_finished = _last_event(records, "run_finished") or {}
    timing = _timing_summary(records, run_started, run_finished)
    status = _status_from_trace(records, state)
    policy_denials = _policy_denials(records)
    failed_tools = _failed_tools(records)
    test_result = _test_result(records)
    verifier_result = _verifier_result(records)
    metrics = _metrics_summary(
        records=records,
        tool_stats=tool_stats,
        policy_denials=policy_denials,
        failed_tools=failed_tools,
        test_result=test_result,
        verifier_result=verifier_result,
        status=status,
        state=state,
    )

    return {
        "run_id": _first_run_id(records, state),
        "status": status,
        "task": state.get("task") or run_started.get("task"),
        "cwd": state.get("cwd") or run_started.get("cwd"),
        "model": run_started.get("model"),
        "iterations": state.get("iterations"),
        "max_iterations": state.get("max_iterations")
        or run_started.get("max_iterations"),
        "total_events": len(records),
        "event_counts": dict(sorted(event_counts.items())),
        "tool_counts": _tool_counts(tool_stats),
        "tool_stats": tool_stats,
        "metrics": metrics,
        "failure_category": metrics["failure_category"],
        "test_result": test_result,
        "verifier_result": verifier_result,
        "policy_denials": policy_denials,
        "failed_tools": failed_tools,
        "modified_files": _modified_files(records),
        "final_answer": _final_answer(records, state),
        "duration_seconds": timing.get("duration_seconds"),
        "timing": timing,
    }


def reconstruct_state_from_trace(path: str | Path) -> JsonRecord:
    """Reconstruct the final known state for a HarnessCoder trace."""

    return reconstruct_state_from_records(load_trace(path))


def reconstruct_state_from_records(records: list[JsonRecord]) -> JsonRecord:
    """Reconstruct the final known state from already-loaded trace records."""

    state_event = _last_state_event(records)
    if state_event is not None:
        state = dict(state_event)
        _fill_state_defaults(state, records)
        return state

    state = _fallback_state(records)
    _fill_state_defaults(state, records)
    return state


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m harnesscoder.replay",
        description="Summarize a HarnessCoder JSONL trace.",
    )
    parser.add_argument("trace_path", help="Path to trace.jsonl or a run directory.")
    args = parser.parse_args(argv)

    try:
        summary = summarize_trace(args.trace_path)
    except (FileNotFoundError, NotADirectoryError, ValueError) as exc:
        print(f"harnesscoder.replay: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _resolve_trace_path(path: str | Path) -> Path:
    trace_path = Path(path)
    if trace_path.is_dir():
        trace_path = trace_path / "trace.jsonl"
    return trace_path


def _event_type(record: JsonRecord) -> str:
    event_type = record.get("type")
    if isinstance(event_type, str) and event_type:
        return event_type
    return "<missing>"


def _last_event(records: list[JsonRecord], event_type: str) -> JsonRecord | None:
    for record in reversed(records):
        if record.get("type") == event_type:
            return record
    return None


def _last_state_event(records: list[JsonRecord]) -> JsonRecord | None:
    for record in reversed(records):
        if record.get("type") != "state_updated":
            continue
        state = record.get("state")
        if isinstance(state, dict):
            return state
    return None


def _summarize_tools(records: list[JsonRecord]) -> dict[str, JsonRecord]:
    counts: dict[str, JsonRecord] = {}

    for record in records:
        event_type = record.get("type")
        if event_type == "model_action":
            action = record.get("action")
            if isinstance(action, dict) and action.get("kind") == "tool":
                bucket = _tool_bucket(counts, _tool_name(action.get("tool_name")))
                bucket["requested"] += 1
        elif event_type == "policy_decision":
            bucket = _tool_bucket(counts, _tool_name(record.get("tool_name")))
            decision = record.get("decision")
            if isinstance(decision, dict) and decision.get("allowed") is False:
                bucket["denied"] += 1
        elif event_type == "tool_result":
            result = _tool_result(record)
            if result is None:
                continue
            bucket = _tool_bucket(counts, _tool_name(result.get("tool_name")))
            bucket["completed"] += 1
            if result.get("ok") is True:
                bucket["succeeded"] += 1
            else:
                bucket["failed"] += 1

    return {name: counts[name] for name in sorted(counts)}


def _tool_counts(tool_stats: dict[str, JsonRecord]) -> dict[str, int]:
    return {
        tool_name: int(stats["requested"] or stats["completed"])
        for tool_name, stats in tool_stats.items()
    }


def _metrics_summary(
    *,
    records: list[JsonRecord],
    tool_stats: dict[str, JsonRecord],
    policy_denials: list[JsonRecord],
    failed_tools: list[JsonRecord],
    test_result: JsonRecord | None,
    verifier_result: JsonRecord | None,
    status: str,
    state: JsonRecord,
) -> JsonRecord:
    tool_call_count = _total_tool_calls(tool_stats)
    metrics: JsonRecord = {
        "tool_call_count": tool_call_count,
        "average_tool_calls": float(tool_call_count),
        "repeated_tool_calls": _repeated_tool_calls(records),
        "repeated_read_count": _repeated_read_count(records),
        "invalid_tool_call_count": _invalid_tool_call_count(records),
        "policy_denial_count": len(policy_denials),
        "failed_tool_count": len(failed_tools),
        "context_packed_count": _event_count(records, "context_packed"),
        "context_injected_count": _context_injected_count(records),
        "estimated_context_tokens": _estimated_context_tokens(records),
        "memory_updated_count": _event_count(records, "memory_updated"),
        "repo_map_built_count": _event_count(records, "repo_map_built"),
        "repo_map_used_count": _event_count(records, "repo_map_used"),
        "repo_map_injected_count": _repo_map_injected_count(records),
        "first_repo_map_target_step": _first_repo_map_target_step(records),
        "compression_count": _compression_count(records),
        "hot_observation_count": _hot_observation_count(records),
        "cold_summary_chars": _cold_summary_chars(records),
        "time_to_first_edit": _time_to_first_edit(records),
        "search_to_edit_steps": _search_to_edit_steps(records),
        "edit_to_test_steps": _edit_to_test_steps(records),
        "checkpoint_created_count": _event_count(records, "checkpoint_created"),
        "run_resumed_count": _event_count(records, "run_resumed")
        + _event_count(records, "resume_started"),
        "test_result_count": _event_count(records, "test_result"),
        "verifier_result_count": _event_count(records, "verifier_result"),
        "resume_success_rate": _resume_success_rate(records, status),
        "test_passed": _test_passed(test_result),
        "verifier_passed": _test_passed(verifier_result),
    }
    metrics["failure_category"] = _failure_category(
        status=status,
        metrics=metrics,
        records=records,
        state=state,
    )
    return metrics


def _event_count(records: list[JsonRecord], event_type: str) -> int:
    return sum(1 for record in records if record.get("type") == event_type)


def _context_injected_count(records: list[JsonRecord]) -> int:
    return sum(
        1
        for record in records
        if record.get("type") == "context_packed"
        and record.get("context_injected") is True
    )


def _estimated_context_tokens(records: list[JsonRecord]) -> int:
    total = 0
    for record in records:
        if record.get("type") != "context_packed":
            continue
        total += _as_int(record.get("estimated_tokens"))
    return total


def _repo_map_injected_count(records: list[JsonRecord]) -> int:
    return sum(
        1
        for record in records
        if record.get("type") == "context_packed"
        and record.get("repo_map_injected") is True
    )


def _first_repo_map_target_step(records: list[JsonRecord]) -> int | None:
    repo_map_files: set[str] = set()
    for record in records:
        if record.get("type") != "repo_map_used":
            continue
        files = record.get("files")
        if isinstance(files, list):
            repo_map_files.update(path for path in files if isinstance(path, str))

    if not repo_map_files:
        return None

    for index, record in enumerate(records):
        result = _tool_result(record)
        if result is None or result.get("tool_name") != "read_file":
            continue
        metadata = result.get("metadata")
        if isinstance(metadata, dict) and metadata.get("path") in repo_map_files:
            return _tool_result_count_between(records, -1, index)
    return None


def _compression_count(records: list[JsonRecord]) -> int:
    explicit = _event_count(records, "context_compressed") + _event_count(
        records,
        "compression",
    )
    if explicit:
        return explicit
    return sum(
        1
        for record in records
        if record.get("type") == "context_packed"
        and _as_int(record.get("dropped_message_count")) > 0
    )


def _hot_observation_count(records: list[JsonRecord]) -> int:
    total = 0
    for record in records:
        if record.get("type") != "context_packed":
            continue
        hot_context = record.get("hot_context")
        if not isinstance(hot_context, dict):
            context_pack = record.get("context_pack")
            if isinstance(context_pack, dict):
                hot_context = context_pack.get("hot_context")
        if not isinstance(hot_context, dict):
            continue
        observations = hot_context.get("recent_observations")
        if isinstance(observations, list):
            total += len(observations)
    return total


def _cold_summary_chars(records: list[JsonRecord]) -> int:
    total = 0
    for record in records:
        if record.get("type") != "context_packed":
            continue
        summary = record.get("cold_trace_summary") or record.get("summary")
        if summary is None:
            continue
        total += len(_canonical_json(summary))
    return total


def _time_to_first_edit(records: list[JsonRecord]) -> float | None:
    start_ts: Any = None
    for record in records:
        if record.get("type") == "run_started":
            start_ts = record.get("ts")
            break
    if start_ts is None and records:
        start_ts = records[0].get("ts")
    edit_ts = None
    for record in records:
        result = _tool_result(record)
        if result is None or result.get("tool_name") not in {"edit_file", "write_file"}:
            continue
        metadata = result.get("metadata")
        if isinstance(metadata, dict) and (
            metadata.get("changed") is True or metadata.get("created") is True
        ):
            edit_ts = record.get("ts")
            break
    return _duration_seconds(start_ts, edit_ts)


def _search_to_edit_steps(records: list[JsonRecord]) -> int | None:
    search_index = _first_tool_result_index(records, {"search_code"})
    edit_index = _first_edit_result_index(records)
    if search_index is None or edit_index is None or edit_index < search_index:
        return None
    return _tool_result_count_between(records, search_index, edit_index)


def _edit_to_test_steps(records: list[JsonRecord]) -> int | None:
    edit_index = _first_edit_result_index(records)
    test_index = _first_tool_result_index(records, {"run_tests"}, start_after=edit_index)
    if edit_index is None or test_index is None or test_index < edit_index:
        return None
    return _tool_result_count_between(records, edit_index, test_index)


def _first_tool_result_index(
    records: list[JsonRecord],
    tool_names: set[str],
    *,
    start_after: int | None = None,
) -> int | None:
    for index, record in enumerate(records):
        if start_after is not None and index <= start_after:
            continue
        result = _tool_result(record)
        if result is not None and result.get("tool_name") in tool_names:
            return index
    return None


def _first_edit_result_index(records: list[JsonRecord]) -> int | None:
    for index, record in enumerate(records):
        result = _tool_result(record)
        if result is None or result.get("tool_name") not in {"edit_file", "write_file"}:
            continue
        metadata = result.get("metadata")
        if isinstance(metadata, dict) and (
            metadata.get("changed") is True or metadata.get("created") is True
        ):
            return index
    return None


def _tool_result_count_between(
    records: list[JsonRecord],
    start_index: int,
    end_index: int,
) -> int:
    return sum(
        1
        for record in records[start_index + 1 : end_index + 1]
        if _tool_result(record) is not None
    )


def _resume_success_rate(records: list[JsonRecord], status: str) -> float | None:
    resumed = _event_count(records, "run_resumed") + _event_count(records, "resume_started")
    if resumed == 0:
        return None
    succeeded = 1 if status in {"success", "finished"} else 0
    return succeeded / resumed


def _total_tool_calls(tool_stats: dict[str, JsonRecord]) -> int:
    total = 0
    for stats in tool_stats.values():
        requested = _as_int(stats.get("requested"))
        completed = _as_int(stats.get("completed"))
        total += max(requested, completed)
    return total


def _repeated_tool_calls(records: list[JsonRecord]) -> int:
    counts: Counter[tuple[str, str]] = Counter()
    for tool_name, args in _tool_call_signatures(records):
        counts[(tool_name, _canonical_json(args))] += 1
    return sum(count - 1 for count in counts.values() if count > 1)


def _repeated_read_count(records: list[JsonRecord]) -> int:
    counts: Counter[tuple[str, int, int]] = Counter()
    for tool_name, args in _tool_call_signatures(records):
        key = _read_call_key(tool_name, args)
        if key is not None:
            counts[key] += 1
    return sum(count - 1 for count in counts.values() if count > 1)


def _tool_call_signatures(records: list[JsonRecord]) -> list[tuple[str, JsonRecord]]:
    actions: list[tuple[str, JsonRecord]] = []
    for record in records:
        if record.get("type") != "model_action":
            continue
        action = record.get("action")
        if not isinstance(action, dict) or action.get("kind") != "tool":
            continue
        tool_args = action.get("tool_args")
        actions.append(
            (
                _tool_name(action.get("tool_name")),
                dict(tool_args) if isinstance(tool_args, dict) else {},
            )
        )

    if actions:
        return actions

    fallback: list[tuple[str, JsonRecord]] = []
    for record in records:
        result = _tool_result(record)
        if result is None:
            continue
        metadata = result.get("metadata")
        fallback.append(
            (
                _tool_name(result.get("tool_name")),
                dict(metadata) if isinstance(metadata, dict) else {},
            )
        )
    return fallback


def _read_call_key(tool_name: str, args: JsonRecord) -> tuple[str, int, int] | None:
    if tool_name != "read_file":
        return None
    path = args.get("path") or args.get("file") or args.get("filename")
    path_text = path if isinstance(path, str) and path else "<missing>"
    return (
        path_text,
        _as_int(args.get("offset"), default=0),
        _as_int(args.get("limit"), default=200),
    )


def _invalid_tool_call_count(records: list[JsonRecord]) -> int:
    invalid_call_ids: set[str] = set()
    anonymous_invalid = 0

    for record in records:
        if record.get("type") != "model_action":
            continue
        action = record.get("action")
        if not isinstance(action, dict) or action.get("kind") != "tool":
            continue
        if _model_tool_action_is_valid(action):
            continue
        call_id = action.get("call_id")
        if isinstance(call_id, str) and call_id:
            invalid_call_ids.add(call_id)
        else:
            anonymous_invalid += 1

    for record in records:
        result = _tool_result(record)
        if result is None or not _is_invalid_tool_error(result.get("error")):
            continue
        call_id = result.get("call_id")
        if isinstance(call_id, str) and call_id:
            invalid_call_ids.add(call_id)
        else:
            anonymous_invalid += 1

    return len(invalid_call_ids) + anonymous_invalid


def _model_tool_action_is_valid(action: JsonRecord) -> bool:
    tool_name = action.get("tool_name")
    tool_args = action.get("tool_args", {})
    return isinstance(tool_name, str) and bool(tool_name) and isinstance(tool_args, dict)


def _is_invalid_tool_error(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    invalid_prefixes = (
        "unknown tool:",
        "bad tool arguments:",
        "path must be",
        "old must be",
        "new must be",
        "cmd must be",
        "cmd parsed to no arguments",
        "could not parse cmd:",
    )
    return value.startswith(invalid_prefixes)


def _failure_category(
    *,
    status: str,
    metrics: JsonRecord,
    records: list[JsonRecord],
    state: JsonRecord,
) -> str:
    if not records or status in {"empty", "incomplete"}:
        return "incomplete"
    if status == "model_error" or _last_event(records, "model_error") is not None:
        return "model_error"
    if metrics.get("verifier_passed") is False:
        return "verifier_failed"
    if (
        status in {"success", "finished"}
        and metrics.get("test_passed") is not False
        and metrics.get("verifier_passed") is not False
    ):
        return "success"
    if metrics.get("test_passed") is False:
        return "test_failed"
    if _as_int(metrics.get("policy_denial_count")) > 0:
        return "policy_denied"
    if _as_int(metrics.get("failed_tool_count")) > 0:
        return "tool_failed"
    if status == "max_iterations":
        return "max_iterations"
    if state.get("done") is True:
        return "success"
    return "incomplete"


def _test_passed(test_result: JsonRecord | None) -> bool | None:
    if test_result is None:
        return None
    passed = test_result.get("passed")
    if isinstance(passed, bool):
        return passed
    if test_result.get("timed_out") is True:
        return False
    returncode = test_result.get("returncode")
    if isinstance(returncode, int) and not isinstance(returncode, bool):
        return returncode == 0
    return None


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except TypeError:
        return repr(value)


def _as_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    return default


def _tool_bucket(counts: dict[str, JsonRecord], tool_name: str) -> JsonRecord:
    if tool_name not in counts:
        counts[tool_name] = {
            "requested": 0,
            "completed": 0,
            "succeeded": 0,
            "failed": 0,
            "denied": 0,
        }
    return counts[tool_name]


def _tool_name(value: Any) -> str:
    if isinstance(value, str) and value:
        return value
    return "<missing>"


def _policy_denials(records: list[JsonRecord]) -> list[JsonRecord]:
    denials: list[JsonRecord] = []
    seen_call_ids: set[str] = set()

    for index, record in enumerate(records):
        if record.get("type") != "policy_decision":
            continue
        decision = record.get("decision")
        if not isinstance(decision, dict) or decision.get("allowed") is not False:
            continue

        denial = {
            "event_index": index,
            "ts": record.get("ts"),
            "call_id": record.get("call_id"),
            "tool_name": record.get("tool_name"),
            "reason": decision.get("reason"),
        }
        call_id = denial["call_id"]
        if isinstance(call_id, str):
            seen_call_ids.add(call_id)
        denials.append(denial)

    for index, record in enumerate(records):
        result = _tool_result(record)
        if result is None:
            continue
        call_id = result.get("call_id")
        error = result.get("error")
        if not isinstance(error, str) or not error.startswith("policy denied"):
            continue
        if isinstance(call_id, str) and call_id in seen_call_ids:
            continue
        denials.append(
            {
                "event_index": index,
                "ts": record.get("ts"),
                "call_id": call_id,
                "tool_name": result.get("tool_name"),
                "reason": error,
            }
        )

    return denials


def _failed_tools(records: list[JsonRecord]) -> list[JsonRecord]:
    failures: list[JsonRecord] = []
    for index, record in enumerate(records):
        result = _tool_result(record)
        if result is None or result.get("ok") is True:
            continue
        failures.append(
            {
                "event_index": index,
                "ts": record.get("ts"),
                "call_id": result.get("call_id"),
                "tool_name": result.get("tool_name"),
                "error": result.get("error"),
                "metadata": result.get("metadata")
                if isinstance(result.get("metadata"), dict)
                else {},
                "output_excerpt": _excerpt(result.get("output")),
            }
        )
    return failures


def _tool_result(record: JsonRecord) -> JsonRecord | None:
    if record.get("type") != "tool_result":
        return None
    result = record.get("result")
    if isinstance(result, dict):
        return result
    return None


def _test_result(records: list[JsonRecord]) -> JsonRecord | None:
    return _last_structured_result(records, "test_result")


def _verifier_result(records: list[JsonRecord]) -> JsonRecord | None:
    return _last_structured_result(records, "verifier_result")


def _last_structured_result(
    records: list[JsonRecord],
    event_type: str,
) -> JsonRecord | None:
    for index, record in reversed(list(enumerate(records))):
        if record.get("type") != event_type:
            continue
        payload = record.get("result")
        if not isinstance(payload, dict):
            payload = record
        result = {
            "event_index": index,
            "ts": record.get("ts"),
            "case_id": payload.get("case_id") or record.get("case_id"),
            "command": payload.get("command") or payload.get("cmd") or payload.get("test_command"),
            "passed": payload.get("passed"),
            "reason": payload.get("reason"),
            "returncode": payload.get("returncode"),
            "timed_out": payload.get("timed_out"),
            "duration_seconds": payload.get("duration_seconds"),
        }
        return {key: value for key, value in result.items() if value is not None}
    return None


def _modified_files(records: list[JsonRecord]) -> list[str]:
    files: list[str] = []
    seen: set[str] = set()
    for record in records:
        for value in _find_values_by_key(record, "modified_files"):
            for file_path in _flatten_file_paths(value):
                if file_path not in seen:
                    files.append(file_path)
                    seen.add(file_path)
        result = _tool_result(record)
        if result is None or result.get("tool_name") not in {"edit_file", "write_file"}:
            continue
        metadata = result.get("metadata")
        if not isinstance(metadata, dict) or metadata.get("changed") is not True:
            continue
        path = metadata.get("path")
        if isinstance(path, str) and path not in seen:
            files.append(path)
            seen.add(path)
    return files


def _find_values_by_key(value: Any, key: str) -> list[Any]:
    matches: list[Any] = []
    if isinstance(value, dict):
        for current_key, current_value in value.items():
            if current_key == key:
                matches.append(current_value)
            else:
                matches.extend(_find_values_by_key(current_value, key))
    elif isinstance(value, list):
        for item in value:
            matches.extend(_find_values_by_key(item, key))
    return matches


def _flatten_file_paths(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        paths: list[str] = []
        for item in value:
            paths.extend(_flatten_file_paths(item))
        return paths
    if isinstance(value, dict):
        for key in ("path", "file", "filename"):
            path = value.get(key)
            if isinstance(path, str):
                return [path]
    return []


def _final_answer(records: list[JsonRecord], state: JsonRecord) -> Any:
    run_finished = _last_event(records, "run_finished")
    if run_finished is not None and "final_answer" in run_finished:
        return run_finished.get("final_answer")
    if "final_answer" in state:
        return state.get("final_answer")
    for record in reversed(records):
        action = record.get("action")
        if (
            record.get("type") == "model_action"
            and isinstance(action, dict)
            and action.get("kind") == "finish"
        ):
            return action.get("content")
    return None


def _status_from_trace(records: list[JsonRecord], state: JsonRecord) -> str:
    run_finished = _last_event(records, "run_finished")
    if run_finished is not None:
        status = run_finished.get("status")
        if isinstance(status, str) and status:
            return status
        return "finished"
    if _last_event(records, "model_error") is not None:
        return "model_error"
    if state.get("done") is True:
        return "finished"
    if not records:
        return "empty"
    return "incomplete"


def _first_run_id(records: list[JsonRecord], state: JsonRecord) -> Any:
    if state.get("run_id") is not None:
        return state.get("run_id")
    for record in records:
        if record.get("run_id") is not None:
            return record.get("run_id")
    return None


def _fallback_state(records: list[JsonRecord]) -> JsonRecord:
    run_started = _last_event(records, "run_started") or {}
    actions = [
        record.get("action")
        for record in records
        if record.get("type") == "model_action" and isinstance(record.get("action"), dict)
    ]
    tool_results = [
        record.get("result")
        for record in records
        if record.get("type") == "tool_result" and isinstance(record.get("result"), dict)
    ]
    final_answer = _final_answer(records, {})
    return {
        "run_id": run_started.get("run_id"),
        "task": run_started.get("task"),
        "cwd": run_started.get("cwd"),
        "iterations": len(tool_results),
        "max_iterations": run_started.get("max_iterations"),
        "done": _last_event(records, "run_finished") is not None
        or final_answer is not None,
        "final_answer": final_answer,
        "action_count": len(actions),
        "observation_count": len(tool_results),
        "last_observation": tool_results[-1] if tool_results else None,
        "reconstructed_from": "events",
    }


def _fill_state_defaults(state: JsonRecord, records: list[JsonRecord]) -> None:
    run_started = _last_event(records, "run_started") or {}
    run_finished = _last_event(records, "run_finished") or {}

    _set_default_if_none(state, "run_id", _first_record_value(records, "run_id"))
    _set_default_if_none(state, "task", run_started.get("task"))
    _set_default_if_none(state, "cwd", run_started.get("cwd"))
    _set_default_if_none(state, "max_iterations", run_started.get("max_iterations"))
    _set_default_if_none(state, "final_answer", run_finished.get("final_answer"))
    state.setdefault("reconstructed_from", "state_updated")


def _set_default_if_none(record: JsonRecord, key: str, value: Any) -> None:
    if record.get(key) is None:
        record[key] = value


def _first_record_value(records: list[JsonRecord], key: str) -> Any:
    for record in records:
        if key in record:
            return record.get(key)
    return None


def _timing_summary(
    records: list[JsonRecord],
    run_started: JsonRecord,
    run_finished: JsonRecord,
) -> JsonRecord:
    first_event = records[0] if records else {}
    last_event = records[-1] if records else {}
    started_at = run_started.get("ts") or first_event.get("ts")
    finished_at = run_finished.get("ts") or last_event.get("ts")
    first_event_at = first_event.get("ts")
    last_event_at = last_event.get("ts")

    return {
        "started_at": started_at,
        "finished_at": finished_at,
        "first_event_at": first_event_at,
        "last_event_at": last_event_at,
        "duration_seconds": _duration_seconds(started_at, finished_at),
        "event_span_seconds": _duration_seconds(first_event_at, last_event_at),
    }


def _duration_seconds(start: Any, end: Any) -> float | None:
    start_dt = _parse_timestamp(start)
    end_dt = _parse_timestamp(end)
    if start_dt is None or end_dt is None:
        return None
    return max(0.0, (end_dt - start_dt).total_seconds())


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        timestamp = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)


def _excerpt(value: Any, limit: int = 500) -> str:
    if value is None:
        return ""
    text = str(value)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}... [truncated {len(text) - limit} chars]"


if __name__ == "__main__":
    raise SystemExit(main())
