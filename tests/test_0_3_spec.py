from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from harnesscoder.replay import summarize_trace


ROOT = Path(__file__).resolve().parents[1]
RESUME_DEMO = ROOT / "examples" / "resume_demo"
FAILURE_DEMO = ROOT / "examples" / "failure_replay_demo"
SPEC_PATH = ROOT / "docs" / "spec-0.3.0.md"


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


class Spec030Tests(unittest.TestCase):
    def test_spec_declares_scoped_0_3_surface_and_non_goals(self) -> None:
        spec = SPEC_PATH.read_text(encoding="utf-8")

        for required in (
            "context_packed",
            "Checkpoint/Resume",
            "test_result",
            "failure_category",
            "Eval Metrics",
        ):
            self.assertIn(required, spec)

        for non_goal in (
            "20-task benchmark suite",
            "full web UI",
            "multi-agent framework",
        ):
            self.assertIn(non_goal, spec)

    def test_resume_demo_trace_contains_context_pack_and_checkpoint(self) -> None:
        trace_path = RESUME_DEMO / "interrupt_resume_trace.jsonl"
        records = load_jsonl(trace_path)
        event_types = [record.get("type") for record in records]

        self.assertIn("context_packed", event_types)
        self.assertIn("checkpoint_created", event_types)
        self.assertIn("run_resumed", event_types)
        self.assertEqual(event_types[-1], "run_finished")

        context_pack = next(
            record for record in records if record.get("type") == "context_packed"
        )
        self.assertGreater(context_pack["input_message_count"], 0)
        self.assertGreater(context_pack["dropped_message_count"], 0)
        self.assertIsInstance(context_pack["packed_context"], dict)
        self.assertIn("summary", context_pack["packed_context"])

        checkpoint_event = next(
            record for record in records if record.get("type") == "checkpoint_created"
        )
        checkpoint_path = RESUME_DEMO / checkpoint_event["checkpoint_path"]
        self.assertTrue(checkpoint_path.exists())

        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        self.assertEqual(checkpoint["run_id"], "run_resume_demo")
        self.assertEqual(
            checkpoint["checkpoint_id"],
            checkpoint_event["checkpoint_id"],
        )
        self.assertFalse(checkpoint["resume"]["should_rerun_exploration"])

        resumed_tool_calls = [
            record
            for record in records[event_types.index("run_resumed") + 1 :]
            if record.get("type") == "model_action"
            and record.get("action", {}).get("kind") == "tool"
        ]
        self.assertEqual(resumed_tool_calls, [])

        summary = summarize_trace(trace_path)
        self.assertEqual(summary["run_id"], "run_resume_demo")
        self.assertEqual(summary["event_counts"]["context_packed"], 1)
        self.assertEqual(summary["event_counts"]["checkpoint_created"], 1)

    def test_failure_replay_report_has_category_and_metrics(self) -> None:
        trace_path = FAILURE_DEMO / "synthetic_trace.jsonl"
        report_path = FAILURE_DEMO / "replay_report.json"
        records = load_jsonl(trace_path)
        report = json.loads(report_path.read_text(encoding="utf-8"))

        test_results = [
            record for record in records if record.get("type") == "test_result"
        ]
        self.assertEqual(len(test_results), 1)
        self.assertFalse(test_results[0]["passed"])
        self.assertEqual(test_results[0]["failure_category"], "test_failed")

        allowed_categories = {
            "success",
            "test_failed",
            "policy_denied",
            "tool_failed",
            "verifier_failed",
            "model_error",
            "max_iterations",
            "incomplete",
        }
        self.assertIn(report["summary"]["failure_category"], allowed_categories)
        self.assertEqual(report["summary"]["failure_category"], "test_failed")

        metrics = report["metrics"]
        for metric_name in (
            "cases_total",
            "cases_passed",
            "cases_failed",
            "pass_rate",
            "tool_failure_count",
            "policy_denial_count",
            "context_packed_count",
            "checkpoint_created_count",
            "test_result_count",
        ):
            self.assertIn(metric_name, metrics)

        self.assertEqual(metrics["cases_total"], 1)
        self.assertEqual(metrics["cases_failed"], 1)
        self.assertEqual(metrics["tool_failure_count"], 1)

        summary = summarize_trace(trace_path)
        self.assertEqual(summary["event_counts"]["test_result"], 1)
        self.assertEqual(summary["failed_tools"][0]["tool_name"], "run_tests")


if __name__ == "__main__":
    unittest.main()
