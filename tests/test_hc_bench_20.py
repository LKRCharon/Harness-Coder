from __future__ import annotations

from collections import Counter
import unittest
from pathlib import Path

from harnesscoder.core.hc_bench_oracle import _load_plan
from harnesscoder.eval_runner import (
    load_eval_cases,
    render_markdown_matrix,
    render_markdown_report,
    run_eval_matrix,
)
from harnesscoder.model_profiles import ModelProfile


ROOT = Path(__file__).resolve().parents[1]


class HCBench20Tests(unittest.TestCase):
    def test_hc_bench_20_declares_expected_categories(self) -> None:
        cases = load_eval_cases(ROOT / "eval" / "hc_bench_20.json")

        self.assertEqual(len(cases), 20)
        self.assertEqual(
            Counter(case.category for case in cases),
            {
                "bugfix": 7,
                "recovery": 3,
                "greenfield": 5,
                "context": 2,
                "policy": 3,
            },
        )
        self.assertEqual(len({case.id for case in cases}), 20)
        self.assertTrue(all(case.repo_fixture == "examples/hc_bench_20/repo" for case in cases))
        self.assertTrue(all(case.allowed_tools for case in cases))
        self.assertTrue(all(case.step_budget for case in cases))
        self.assertTrue(all(case.verifier for case in cases))
        self.assertTrue(all(case.split == "heldout" for case in cases))

    def test_oracle_plan_covers_every_case(self) -> None:
        cases = load_eval_cases(ROOT / "eval" / "hc_bench_20.json")
        plan = _load_plan()

        self.assertTrue({case.id for case in cases}.issubset(plan))
        self.assertTrue(all(plan[case.id] for case in cases))

    def test_reports_include_category_summary(self) -> None:
        matrix = run_eval_matrix(
            cases_path=ROOT / "eval" / "greenfield_cases.json",
            workspace_root=ROOT,
            profiles=[
                ModelProfile(name="scripted", provider="scripted"),
            ],
            max_iterations=4,
        )
        report = render_markdown_report(matrix[0].results)
        matrix_report = render_markdown_matrix(matrix)

        self.assertIn("Category Summary", report)
        self.assertIn("Category Summary", matrix_report)


if __name__ == "__main__":
    unittest.main()
