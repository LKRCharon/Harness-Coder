from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from harnesscoder.cli import main
from harnesscoder.eval_runner import (
    EvalMatrixProfileResult,
    EvalCase,
    EvalResult,
    _run_command_for_eval,
    render_markdown_report,
    render_markdown_matrix,
    run_eval_cases,
    run_eval_matrix,
)
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
                "[models.oracle]\n"
                'provider = "hc-bench-oracle"\n\n'
                "[models.gpt]\n"
                'provider = "openai-codex"\n'
                'model = "gpt-test"\n'
                'base_url = "https://example.test/v1"\n'
                'api_key_env = "OPENAI_API_KEY"\n\n'
                "[models.deepseek]\n"
                'provider = "openai-chat"\n'
                'model = "deepseek-v4-pro"\n'
                'base_url = "https://api.deepseek.com"\n'
                'api_key_env = "DEEPSEEK_API_KEY"\n',
                encoding="utf-8",
            )

            profiles = load_model_profiles(config)

        self.assertEqual(sorted(profiles), ["deepseek", "gpt", "oracle", "scripted"])
        self.assertEqual(profiles["scripted"].provider, "scripted")
        self.assertEqual(profiles["oracle"].provider, "hc-bench-oracle")
        self.assertEqual(profiles["gpt"].provider, "openai-codex")
        self.assertEqual(profiles["gpt"].model, "gpt-test")
        self.assertEqual(profiles["deepseek"].provider, "openai-chat")
        self.assertEqual(profiles["deepseek"].api_key_env, "DEEPSEEK_API_KEY")

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

    def test_eval_report_splits_patch_and_agent_success(self) -> None:
        results = [
            _result(
                "both-ok",
                passed=True,
                agent_success=True,
                patch_success=True,
                runner_status="success",
                test_passed=True,
                verifier_passed=True,
            ),
            _result(
                "patch-only",
                passed=False,
                agent_success=False,
                patch_success=True,
                runner_status="max_iterations",
                test_passed=True,
                verifier_passed=True,
            ),
            _result(
                "agent-only",
                passed=False,
                agent_success=True,
                patch_success=False,
                runner_status="success",
                test_passed=False,
                verifier_passed=True,
            ),
        ]

        report = render_markdown_report(results)
        matrix_report = render_markdown_matrix(
            [
                EvalMatrixProfileResult(
                    profile_name="demo",
                    provider="scripted",
                    results=results,
                )
            ]
        )

        self.assertIn("| Agent success rate | 66.7% (2/3) |", report)
        self.assertIn("| Patch success rate | 66.7% (2/3) |", report)
        self.assertIn("| Patch success but agent failed | 1 |", report)
        self.assertIn("| Case | Category | Result | Agent | Patch |", report)
        self.assertIn("Patch success", matrix_report)
        self.assertIn("Patch ok / agent failed", matrix_report)
        self.assertIn("| demo | scripted | 3 | 33.3% (1/3) | 66.7% (2/3) | 66.7% (2/3) |", matrix_report)

    def test_eval_matrix_records_profile_initialization_error(self) -> None:
        matrix = run_eval_matrix(
            cases_path=ROOT / "eval" / "bugfix_cases.json",
            workspace_root=ROOT,
            profiles=[
                ModelProfile(
                    name="real_missing_key",
                    provider="openai-chat",
                    model="codex-test",
                    api_key_env="HARNESSCODER_TEST_MISSING_KEY",
                ),
            ],
            max_iterations=1,
        )

        self.assertEqual(len(matrix), 1)
        self.assertEqual(matrix[0].results, [])
        self.assertEqual(matrix[0].planned_case_ids, ["bugfix-add-one"])
        self.assertIn("HARNESSCODER_TEST_MISSING_KEY", matrix[0].error or "")

        report = render_markdown_matrix(matrix)
        self.assertIn("Profile Errors", report)
        self.assertIn("real_missing_key", report)
        self.assertIn("- Cases: 1", report)
        self.assertIn("SKIP", report)
        self.assertIn("profile_error=1", report)

    def test_eval_subprocess_redacts_sensitive_environment_output(self) -> None:
        import os

        previous = os.environ.get("HARNESSCODER_TEST_SECRET")
        os.environ["HARNESSCODER_TEST_SECRET"] = "super-secret-value"
        try:
            result = _run_command_for_eval(
                (
                    "python -c \"import os; "
                    "print(os.environ.get('HARNESSCODER_TEST_SECRET')); "
                    "print('OPENAI_API_KEY=literal-secret')\""
                ),
                ROOT,
                10,
            )
        finally:
            if previous is None:
                os.environ.pop("HARNESSCODER_TEST_SECRET", None)
            else:
                os.environ["HARNESSCODER_TEST_SECRET"] = previous

        self.assertEqual(result.returncode, 0)
        self.assertIn("None", result.stdout)
        self.assertNotIn("super-secret-value", result.stdout)
        self.assertIn("OPENAI_API_KEY=[REDACTED]", result.stdout)

    def test_fixture_eval_trace_root_is_relative_to_workspace_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = root / "fixture"
            fixture.mkdir()
            (fixture / "test_sample.py").write_text(
                "import unittest\n\n"
                "class SampleTest(unittest.TestCase):\n"
                "    def test_ok(self):\n"
                "        self.assertTrue(True)\n",
                encoding="utf-8",
            )
            cases = root / "cases.json"
            cases.write_text(
                (
                    '{"cases":[{"id":"trace-root-case","category":"smoke",'
                    '"task":"Finish immediately.",'
                    '"cwd":".","repo_fixture":"fixture",'
                    '"test_command":"python -m unittest discover",'
                    '"timeout":30,"success_returncode":0}]}'
                ),
                encoding="utf-8",
            )

            results = run_eval_cases(
                cases_path=cases,
                workspace_root=root,
                provider="hc-bench-oracle",
                trace_root=".harnesscoder/eval-runs",
                max_iterations=1,
            )

        self.assertEqual(len(results), 1)
        trace_path = results[0].trace_path
        self.assertTrue(
            trace_path.is_relative_to((root / ".harnesscoder/eval-runs").resolve()),
            trace_path,
        )
        self.assertFalse(
            trace_path.is_relative_to(
                (root / ".harnesscoder/eval-workspaces").resolve()
            ),
            trace_path,
        )

    def test_cli_matrix_returns_nonzero_for_profile_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "matrix.md"
            code = main(
                [
                    "--model-profiles",
                    "openai-chat",
                    "--eval",
                    str(ROOT / "eval" / "bugfix_cases.json"),
                    "--eval-report",
                    str(report_path),
                ]
            )

        self.assertEqual(code, 1)

def _result(
    case_id: str,
    *,
    passed: bool,
    agent_success: bool,
    patch_success: bool,
    runner_status: str,
    test_passed: bool,
    verifier_passed: bool,
) -> EvalResult:
    return EvalResult(
        case_id=case_id,
        category="demo",
        task=f"Task {case_id}",
        cwd=ROOT,
        workspace_path=ROOT,
        passed=passed,
        reason="demo",
        run_id=f"run_{case_id}",
        runner_status=runner_status,
        final_answer="done" if agent_success else "",
        trace_path=ROOT / "trace.jsonl",
        test_returncode=0 if test_passed else 1,
        verifier_returncode=0 if verifier_passed else 1,
        test_passed=test_passed,
        verifier_passed=verifier_passed,
        patch_success=patch_success,
        agent_success=agent_success,
        failure_category="success" if passed else "demo_failed",
        metrics={
            "average_tool_calls": 1.0,
            "finish_grace_attempt_count": 0,
            "finish_grace_success_count": 0,
        },
    )


if __name__ == "__main__":
    unittest.main()
