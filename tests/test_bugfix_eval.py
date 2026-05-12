from __future__ import annotations

import unittest
from pathlib import Path

from harnesscoder.eval_runner import load_eval_cases, render_markdown_report, run_eval_cases


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "examples" / "bugfix_demo" / "repo"


class BugfixEvalTests(unittest.TestCase):
    def test_bugfix_case_declares_isolated_fixture(self) -> None:
        cases = load_eval_cases(ROOT / "eval" / "bugfix_cases.json")

        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0].id, "bugfix-add-one")
        self.assertEqual(cases[0].repo_fixture, "examples/bugfix_demo/repo")

    def test_fixture_eval_runs_in_copy_without_mutating_source(self) -> None:
        original_source = (FIXTURE / "math_utils.py").read_text(encoding="utf-8")

        results = run_eval_cases(
            cases_path=ROOT / "eval" / "bugfix_cases.json",
            workspace_root=ROOT,
            provider="scripted",
            max_iterations=4,
        )

        self.assertEqual(len(results), 1)
        result = results[0]
        self.assertNotEqual(result.workspace_path, FIXTURE)
        self.assertTrue(result.workspace_path.exists())
        self.assertTrue(result.cwd.exists())
        self.assertTrue(str(result.workspace_path).startswith(str(ROOT / ".harnesscoder")))
        self.assertEqual(
            (FIXTURE / "math_utils.py").read_text(encoding="utf-8"),
            original_source,
        )
        self.assertEqual((result.workspace_path / "math_utils.py").read_text(encoding="utf-8"), original_source)

        report = render_markdown_report(results)
        self.assertIn("Workspace", report)
        self.assertIn(str(result.workspace_path), report)


if __name__ == "__main__":
    unittest.main()
