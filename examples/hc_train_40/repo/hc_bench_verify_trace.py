from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--modified-file", required=True)
    parser.add_argument("--min-tool", action="append", default=[])
    parser.add_argument("--min-failed-tests", type=int, default=0)
    parser.add_argument("--min-policy-denials", type=int, default=0)
    parser.add_argument("--max-read-limit", type=int, default=1_000_000)
    args = parser.parse_args()

    trace_path = Path(os.environ["HARNESSCODER_TRACE_PATH"])
    events = [
        json.loads(line)
        for line in trace_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    tools = {}
    failed_tests = 0
    denials = 0
    modified = set()
    read_limit_ok = True

    for event in events:
        if event.get("type") == "tool_result":
            result = event.get("result") or {}
            name = result.get("tool_name")
            tools[name] = tools.get(name, 0) + 1
            metadata = result.get("metadata") or {}
            if result.get("ok") and metadata.get("changed") and metadata.get("path"):
                modified.add(metadata["path"])
            if name == "read_file" and metadata.get("limit", 0) > args.max_read_limit:
                read_limit_ok = False
        if event.get("type") == "test_result" and event.get("passed") is False:
            failed_tests += 1
        if event.get("type") == "policy_decision":
            decision = event.get("decision") or {}
            if decision.get("allowed") is False:
                denials += 1

    required_tools = {}
    for raw in args.min_tool:
        name, count = raw.split("=", 1)
        required_tools[name] = int(count)

    missing = {
        name: count
        for name, count in required_tools.items()
        if tools.get(name, 0) < count
    }

    if args.modified_file != "README.md" and args.modified_file not in modified:
        raise AssertionError(f"missing modified file {args.modified_file!r}: {sorted(modified)}")
    if missing:
        raise AssertionError(f"missing tool counts: tools={tools} missing={missing}")
    if failed_tests < args.min_failed_tests:
        raise AssertionError(f"failed_tests={failed_tests} < {args.min_failed_tests}")
    if denials < args.min_policy_denials:
        raise AssertionError(f"denials={denials} < {args.min_policy_denials}")
    if not read_limit_ok:
        raise AssertionError("read_file limit exceeded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
