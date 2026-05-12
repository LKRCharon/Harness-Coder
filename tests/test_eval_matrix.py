from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from harnesscoder.eval_runner import render_markdown_matrix, run_eval_matrix
from harnesscoder.model_profiles import (
    ModelProfile,
    load_model_profiles,
    parse_profile_names,
)


ROOT = Path(__file__).resolve().parents[1]


class EvalMatrixTests(unittest.TestCase):
    def test_load_model_profiles_from_toml(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "models.toml"
            config.write_text(
                "[models.scripted]\n"
                'provider = "scripted"\n\n'
                "[models.gpt]\n"
                'provider = "openai-codex"\n'
                'model = "gpt-test"\n'
                'base_url = "https://example.test/v1"\n'
                'api_key_env = "OPENAI_API_KEY"\n',
                encoding="utf-8",
            )

            profiles = load_model_profiles(config)

        self.assertEqual(sorted(profiles), ["gpt", "scripted"])
        self.assertEqual(profiles["scripted"].provider, "scripted")
        self.assertEqual(profiles["gpt"].provider, "openai-codex")
        self.assertEqual(profiles["gpt"].model, "gpt-test")

    def test_parse_profile_names_rejects_duplicates(self) -> None:
        self.assertEqual(parse_profile_names("scripted,gpt"), ["scripted", "gpt"])
        with self.assertRaises(ValueError):
            parse_profile_names("scripted, scripted")

    def test_eval_matrix_report_compares_profiles(self) -> None:
        matrix = run_eval_matrix(
            cases_path=ROOT / "eval" / "bugfix_cases.json",
            workspace_root=ROOT,
            profiles=[
                ModelProfile(name="scripted_a", provider="scripted"),
                ModelProfile(name="scripted_b", provider="scripted"),
            ],
            max_iterations=4,
        )

        self.assertEqual(len(matrix), 2)
        self.assertTrue(all(len(item.results) == 1 for item in matrix))
        self.assertFalse(any(result.passed for item in matrix for result in item.results))

        report = render_markdown_matrix(matrix)
        self.assertIn("# HarnessCoder Eval Matrix", report)
        self.assertIn("Profile Summary", report)
        self.assertIn("Case Matrix", report)
        self.assertIn("scripted_a", report)
        self.assertIn("scripted_b", report)
        self.assertIn("bugfix-add-one", report)


if __name__ == "__main__":
    unittest.main()
