from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from harnesscoder.core.policy import ToolPolicy
from harnesscoder.core.runner import AgentRunner
from harnesscoder.core.state import AgentState, ModelAction
from harnesscoder.core.tools import ToolRegistry
from harnesscoder.eval_runner import load_eval_cases, render_markdown_report
from harnesscoder.replay import reconstruct_state_from_trace, summarize_trace


class ToolRegistryTests(unittest.TestCase):
    def test_write_file_creates_new_file_and_blocks_accidental_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = ToolRegistry(root)

            created = registry.write_file(
                call_id="call_create",
                path="pkg/module.py",
                content="VALUE = 1\n",
            )
            duplicate = registry.write_file(
                call_id="call_duplicate",
                path="pkg/module.py",
                content="VALUE = 2\n",
            )
            overwritten = registry.write_file(
                call_id="call_overwrite",
                path="pkg/module.py",
                content="VALUE = 2\n",
                overwrite=True,
            )

            self.assertTrue(created.ok, created.error)
            self.assertTrue(created.metadata["created"])
            self.assertFalse(duplicate.ok)
            self.assertTrue(overwritten.ok, overwritten.error)
            self.assertFalse(overwritten.metadata["created"])
            self.assertEqual((root / "pkg" / "module.py").read_text(), "VALUE = 2\n")

    def test_edit_file_requires_unique_old_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "sample.py"
            target.write_text("value = 1\nvalue = 1\n", encoding="utf-8")

            registry = ToolRegistry(root)
            duplicate = registry.edit_file(
                call_id="call_duplicate",
                path="sample.py",
                old="value = 1",
                new="value = 2",
            )
            self.assertFalse(duplicate.ok)
            self.assertEqual(duplicate.metadata["match_count"], 2)

            ok = registry.edit_file(
                call_id="call_ok",
                path="sample.py",
                old="value = 1\nvalue = 1\n",
                new="value = 2\n",
            )
            self.assertTrue(ok.ok)
            self.assertTrue(ok.metadata["changed"])
            self.assertEqual(target.read_text(encoding="utf-8"), "value = 2\n")

    def test_run_tests_executes_python_unittest_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "test_sample.py").write_text(
                "import unittest\n\n"
                "class SampleTest(unittest.TestCase):\n"
                "    def test_ok(self):\n"
                "        self.assertEqual(1 + 1, 2)\n",
                encoding="utf-8",
            )
            registry = ToolRegistry(root)
            result = registry.run_tests(
                call_id="call_tests",
                cmd="python -m unittest discover",
                timeout=30,
            )
        self.assertTrue(result.ok, result.output)
        self.assertEqual(result.metadata["returncode"], 0)


class PolicyTests(unittest.TestCase):
    def test_allowed_tools_can_scope_a_run(self) -> None:
        policy = ToolPolicy(allowed_tools={"read_file"})
        root = Path.cwd()

        allowed = policy.check("read_file", {"path": "README.md"}, root)
        denied = policy.check(
            "write_file",
            {"path": "new.py", "content": "print('hi')\n"},
            root,
        )

        self.assertTrue(allowed.allowed, allowed.reason)
        self.assertFalse(denied.allowed)

    def test_run_tests_policy_is_narrower_than_run_command(self) -> None:
        policy = ToolPolicy()
        root = Path.cwd()

        allowed = policy.check(
            "run_tests",
            {"cmd": "python -m unittest discover -s tests"},
            root,
        )
        self.assertTrue(allowed.allowed, allowed.reason)

        denied = policy.check("run_tests", {"cmd": "python -c 'print(1)'"}, root)
        self.assertFalse(denied.allowed)

    def test_edit_file_rejects_workspace_escape(self) -> None:
        policy = ToolPolicy()
        decision = policy.check(
            "edit_file",
            {"path": "../outside.py", "old": "a", "new": "b"},
            Path.cwd(),
        )
        self.assertFalse(decision.allowed)


class ReplayTests(unittest.TestCase):
    def test_summarize_trace_counts_tools_and_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            trace = Path(tmp) / "trace.jsonl"
            records = [
                {"type": "run_started", "run_id": "run_x", "task": "demo"},
                {
                    "type": "model_action",
                    "run_id": "run_x",
                    "action": {
                        "kind": "tool",
                        "tool_name": "read_file",
                        "call_id": "call_x",
                    },
                },
                {
                    "type": "tool_result",
                    "run_id": "run_x",
                    "result": {
                        "call_id": "call_x",
                        "tool_name": "read_file",
                        "ok": True,
                        "metadata": {"path": "README.md"},
                    },
                },
                {
                    "type": "tool_result",
                    "run_id": "run_x",
                    "result": {
                        "call_id": "call_edit",
                        "tool_name": "edit_file",
                        "ok": True,
                        "metadata": {"path": "README.md", "changed": True},
                    },
                },
                {
                    "type": "state_updated",
                    "run_id": "run_x",
                    "state": {
                        "run_id": "run_x",
                        "task": "demo",
                        "done": True,
                        "final_answer": "done",
                    },
                },
                {
                    "type": "run_finished",
                    "run_id": "run_x",
                    "status": "success",
                    "final_answer": "done",
                },
            ]
            trace.write_text(
                "\n".join(json.dumps(record) for record in records) + "\n",
                encoding="utf-8",
            )

            summary = summarize_trace(trace)
            state = reconstruct_state_from_trace(trace)

        self.assertEqual(summary["run_id"], "run_x")
        self.assertEqual(summary["tool_counts"], {"edit_file": 1, "read_file": 1})
        self.assertEqual(summary["modified_files"], ["README.md"])
        self.assertEqual(state["final_answer"], "done")


class EvalRunnerTests(unittest.TestCase):
    def test_load_cases_and_render_report(self) -> None:
        cases = load_eval_cases("eval/cases.json")
        self.assertGreaterEqual(len(cases), 1)
        report = render_markdown_report([])
        self.assertIn("# HarnessCoder Eval Report", report)


class ContextMemoryRunnerTests(unittest.TestCase):
    def test_runner_records_context_injection_and_memory_updates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# Demo\n\nUseful fact.\n", encoding="utf-8")
            runner = AgentRunner(
                model=_ReadThenFinishModel(),
                cwd=root,
                trace_root=root / ".harnesscoder" / "runs",
                max_iterations=3,
                context_mode="memory",
            )

            result = runner.run("Read the README.")
            summary = summarize_trace(result.trace_path)
            state = reconstruct_state_from_trace(result.trace_path)

        self.assertEqual(result.status, "success")
        metrics = summary["metrics"]
        self.assertEqual(metrics["context_injected_count"], 2)
        self.assertGreater(metrics["estimated_context_tokens"], 0)
        self.assertEqual(metrics["memory_updated_count"], 1)
        self.assertIn("task/explored_files", state["memory_blocks"])
        self.assertIn("read README.md", state["memory_blocks"]["task/explored_files"]["value"])


class _ReadThenFinishModel:
    name = "read-then-finish"

    def next_action(self, state: AgentState, _context=None) -> ModelAction:
        if state.latest_observation_for("read_file") is None:
            return ModelAction(
                kind="tool",
                rationale="Read the README.",
                tool_name="read_file",
                tool_args={"path": "README.md"},
            )
        return ModelAction(
            kind="finish",
            rationale="Enough context.",
            content="done",
        )


if __name__ == "__main__":
    unittest.main()
