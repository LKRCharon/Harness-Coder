from __future__ import annotations

from collections import Counter
import unittest
from pathlib import Path

from harnesscoder.core.hc_bench_oracle import _load_plan
from harnesscoder.eval_runner import load_eval_cases, render_markdown_report


ROOT = Path(__file__).resolve().parents[1]


class HCTrain40Tests(unittest.TestCase):
    def test_hc_train_40_declares_training_split(self) -> None:
        cases = load_eval_cases(ROOT / "eval" / "hc_train_40.json")

        self.assertEqual(len(cases), 40)
        self.assertEqual(
            Counter(case.category for case in cases),
            {
                "bugfix": 7,
                "context": 14,
                "recovery": 8,
                "policy": 6,
                "greenfield": 5,
            },
        )
        self.assertEqual(len({case.id for case in cases}), 40)
        self.assertTrue(all(case.split == "train" for case in cases))
        self.assertTrue(
            all(case.source == "synthetic-microbenchmark" for case in cases)
        )
        self.assertTrue(
            all(case.repo_fixture == "examples/hc_train_40/repo" for case in cases)
        )
        self.assertFalse(
            {case.id for case in cases}
            & {case.id for case in load_eval_cases(ROOT / "eval" / "hc_bench_20.json")}
        )

    def test_train_oracle_plan_covers_every_train_case(self) -> None:
        cases = load_eval_cases(ROOT / "eval" / "hc_train_40.json")
        plan = _load_plan()

        self.assertTrue({case.id for case in cases}.issubset(plan))
        self.assertTrue(all(plan[case.id] for case in cases))

    def test_train_suite_has_search_and_bounded_read_pressure(self) -> None:
        raw = (ROOT / "eval" / "hc_train_40.json").read_text(encoding="utf-8")
        cases = load_eval_cases(ROOT / "eval" / "hc_train_40.json")

        self.assertGreaterEqual(raw.count("--min-tool search_code=1"), 25)
        self.assertGreaterEqual(raw.count("--max-read-limit 80"), 14)
        self.assertGreaterEqual(
            sum(1 for case in cases if "policy-deny" in case.id),
            4,
        )

    def test_report_includes_split_and_source_breakdowns(self) -> None:
        report = render_markdown_report([])

        self.assertIn("Split breakdown", report)
        self.assertIn("Source breakdown", report)


if __name__ == "__main__":
    unittest.main()
