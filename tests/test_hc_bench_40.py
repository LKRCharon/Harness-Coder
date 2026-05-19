from __future__ import annotations

from collections import Counter
import unittest
from pathlib import Path

from harnesscoder.core.hc_bench_oracle import _load_plan
from harnesscoder.eval_runner import load_eval_cases


ROOT = Path(__file__).resolve().parents[1]


class HCBench40Tests(unittest.TestCase):
    def test_hc_bench_40_declares_expected_categories(self) -> None:
        cases = load_eval_cases(ROOT / "eval" / "hc_bench_40.json")

        self.assertEqual(len(cases), 40)
        self.assertEqual(
            Counter(case.category for case in cases),
            {
                "bugfix": 11,
                "recovery": 6,
                "greenfield": 10,
                "context": 7,
                "policy": 6,
            },
        )
        self.assertEqual(len({case.id for case in cases}), 40)
        self.assertTrue(all(case.repo_fixture == "examples/hc_bench_40/repo" for case in cases))
        self.assertTrue(all(case.allowed_tools for case in cases))
        self.assertTrue(all(case.step_budget for case in cases))
        self.assertTrue(all(case.verifier for case in cases))
        self.assertTrue(all(case.split == "heldout" for case in cases))
        self.assertTrue(
            all(case.source == "synthetic-microbenchmark" for case in cases)
        )

    def test_hc_bench_40_extends_bench_20_without_relabeling_train_cases(self) -> None:
        bench20 = load_eval_cases(ROOT / "eval" / "hc_bench_20.json")
        bench40 = load_eval_cases(ROOT / "eval" / "hc_bench_40.json")
        train = load_eval_cases(ROOT / "eval" / "hc_train_40.json")

        bench20_ids = {case.id for case in bench20}
        bench40_ids = {case.id for case in bench40}
        train_ids = {case.id for case in train}

        self.assertTrue(bench20_ids.issubset(bench40_ids))
        self.assertFalse((bench40_ids - bench20_ids) & train_ids)

    def test_hc_bench_40_oracle_plan_covers_every_case(self) -> None:
        cases = load_eval_cases(ROOT / "eval" / "hc_bench_40.json")
        plan = _load_plan()

        self.assertTrue({case.id for case in cases}.issubset(plan))
        self.assertTrue(all(plan[case.id] for case in cases))


if __name__ == "__main__":
    unittest.main()
