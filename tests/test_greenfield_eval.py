from __future__ import annotations

import unittest
from pathlib import Path

from harnesscoder.core.state import AgentState, ModelAction
from harnesscoder.eval_runner import load_eval_cases, render_markdown_report, run_eval_cases
from harnesscoder.replay import summarize_trace


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "examples" / "greenfield_demo" / "repo"


class GreenfieldScriptedModel:
    name = "greenfield-scripted"

    def next_action(self, state: AgentState) -> ModelAction:
        if state.latest_observation_for("write_file") is None:
            return ModelAction(
                kind="tool",
                rationale="Create the source module from scratch.",
                tool_name="write_file",
                tool_args={
                    "path": "math_utils.py",
                    "content": "def add_one(value):\n    return value + 1\n",
                },
            )

        write_observations = [
            observation
            for observation in state.observations
            if observation.tool_name == "write_file"
        ]
        if len(write_observations) == 1:
            return ModelAction(
                kind="tool",
                rationale="Create unittest coverage for the new module.",
                tool_name="write_file",
                tool_args={
                    "path": "test_math_utils.py",
                    "content": (
                        "import unittest\n\n"
                        "from math_utils import add_one\n\n\n"
                        "class AddOneTests(unittest.TestCase):\n"
                        "    def test_adds_one(self):\n"
                        "        self.assertEqual(add_one(1), 2)\n"
                        "        self.assertEqual(add_one(-3), -2)\n\n\n"
                        "if __name__ == '__main__':\n"
                        "    unittest.main()\n"
                    ),
                },
            )

        if state.latest_observation_for("run_tests") is None:
            return ModelAction(
                kind="tool",
                rationale="Verify the generated module with unittest.",
                tool_name="run_tests",
                tool_args={"cmd": "python -m unittest discover"},
            )

        return ModelAction(
            kind="finish",
            rationale="The generated module and tests pass.",
            content="Created math_utils.py and test_math_utils.py; tests pass.",
        )


class GreenfieldEvalTests(unittest.TestCase):
    def test_greenfield_case_declares_constraints(self) -> None:
        cases = load_eval_cases(ROOT / "eval" / "greenfield_cases.json")

        self.assertEqual(len(cases), 1)
        case = cases[0]
        self.assertEqual(case.id, "greenfield-add-one-module")
        self.assertEqual(case.repo_fixture, "examples/greenfield_demo/repo")
        self.assertIn("write_file", case.allowed_tools or ())
        self.assertEqual(case.step_budget, 8)
        self.assertIsNotNone(case.verifier)

    def test_greenfield_eval_writes_files_and_verifies(self) -> None:
        self.assertFalse((FIXTURE / "math_utils.py").exists())
        self.assertFalse((FIXTURE / "test_math_utils.py").exists())

        results = run_eval_cases(
            cases_path=ROOT / "eval" / "greenfield_cases.json",
            workspace_root=ROOT,
            provider="scripted",
            max_iterations=8,
            model=GreenfieldScriptedModel(),
        )

        self.assertEqual(len(results), 1)
        result = results[0]
        self.assertTrue(result.passed, result.reason)
        self.assertTrue(result.test_passed)
        self.assertTrue(result.verifier_passed)
        self.assertEqual(result.tool_counts.get("write_file"), 2)
        self.assertIn("math_utils.py", result.trace_summary["modified_files"])
        self.assertIn("test_math_utils.py", result.trace_summary["modified_files"])
        self.assertFalse((FIXTURE / "math_utils.py").exists())
        self.assertFalse((FIXTURE / "test_math_utils.py").exists())

        report = render_markdown_report(results)
        self.assertIn("Verifier pass rate", report)
        self.assertIn("greenfield-add-one-module", report)

    def test_replay_classifies_failed_verifier(self) -> None:
        results = run_eval_cases(
            cases_path=ROOT / "eval" / "greenfield_cases.json",
            workspace_root=ROOT,
            provider="scripted",
            max_iterations=8,
            model=GreenfieldScriptedModel(),
        )
        result = results[0]
        with result.trace_path.open("a", encoding="utf-8") as handle:
            handle.write(
                '{"type":"verifier_result","run_id":"%s","passed":false,'
                '"returncode":1,"command":"python -c false"}\n' % result.run_id
            )

        summary = summarize_trace(result.trace_path)

        self.assertEqual(summary["failure_category"], "verifier_failed")
        self.assertFalse(summary["metrics"]["verifier_passed"])


if __name__ == "__main__":
    unittest.main()
