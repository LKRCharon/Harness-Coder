from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path

from harnesscoder.cli import main
from harnesscoder.eval_runner import (
    DEFAULT_CONTEXT_ABLATIONS,
    EvalMatrixProfileResult,
    EvalCase,
    EvalResult,
    _run_command_for_eval,
    render_context_ablation_matrix,
    render_markdown_report,
    render_markdown_matrix,
    run_context_ablation_matrix,
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
                'api_key_env = "OPENAI_API_KEY"\n'
                'reasoning_effort = "xhigh"\n\n'
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
        self.assertEqual(profiles["gpt"].reasoning_effort, "xhigh")
        self.assertEqual(profiles["deepseek"].provider, "openai-chat")
        self.assertEqual(profiles["deepseek"].api_key_env, "DEEPSEEK_API_KEY")

    def test_openai_chat_profile_accepts_extra_body(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "models.toml"
            config.write_text(
                "[models.qwen3]\n"
                'provider = "openai-chat"\n'
                'model = "qwen3-8b"\n'
                'base_url = "http://127.0.0.1:18000/v1"\n'
                "\n"
                "[models.qwen3.extra_body.chat_template_kwargs]\n"
                "enable_thinking = false\n",
                encoding="utf-8",
            )

            profiles = load_model_profiles(config)

        self.assertEqual(
            profiles["qwen3"].extra_body,
            {"chat_template_kwargs": {"enable_thinking": False}},
        )

    def test_openai_chat_profile_rejects_reasoning_effort(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "models.toml"
            config.write_text(
                "[models.deepseek]\n"
                'provider = "openai-chat"\n'
                'model = "deepseek-v4-pro"\n'
                'api_key_env = "DEEPSEEK_API_KEY"\n'
                'reasoning_effort = "high"\n',
                encoding="utf-8",
            )

            with self.assertRaises(ValueError):
                load_model_profiles(config)

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

    def test_context_ablation_matrix_compares_context_modes(self) -> None:
        matrix = run_context_ablation_matrix(
            cases_path=ROOT / "eval" / "bugfix_cases.json",
            workspace_root=ROOT,
            provider="hc-bench-oracle",
            max_iterations=4,
        )

        self.assertEqual(
            [item.profile_name for item in matrix],
            [ablation.name for ablation in DEFAULT_CONTEXT_ABLATIONS],
        )
        self.assertTrue(all(len(item.results) == 1 for item in matrix))
        self.assertTrue(matrix[0].results[0].metrics["context_injected_count"] > 0)
        no_context = next(
            item for item in matrix if item.profile_name == "no_context_compaction"
        )
        self.assertEqual(no_context.results[0].metrics["context_injected_count"], 0)

        report = render_context_ablation_matrix(matrix)
        self.assertIn("# HarnessCoder Context Ablation Matrix", report)
        self.assertIn("Budget reductions", report)
        self.assertIn("Dropped blocks", report)
        self.assertIn("First target read step", report)
        self.assertIn("no_policy_retry", report)

    def test_context_ablation_matrix_accepts_model_profile(self) -> None:
        matrix = run_context_ablation_matrix(
            cases_path=ROOT / "eval" / "bugfix_cases.json",
            workspace_root=ROOT,
            profile=ModelProfile(name="oracle_profile", provider="hc-bench-oracle"),
            max_iterations=4,
        )

        self.assertEqual(
            [item.profile_name for item in matrix],
            [ablation.name for ablation in DEFAULT_CONTEXT_ABLATIONS],
        )
        self.assertTrue(all(item.provider == "hc-bench-oracle" for item in matrix))
        for item in matrix:
            self.assertTrue(item.results)
            self.assertEqual(
                item.results[0].trace_summary["model_metadata"]["profile_name"],
                "oracle_profile",
            )

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
        self.assertIn("| Raw tool output chars | 3000 |", report)
        self.assertIn("| Tool output preview chars | 1200 |", report)
        self.assertIn("| Stored artifacts | 3 |", report)
        self.assertIn("| Largest tool output chars | 1000 |", report)
        self.assertIn("| Observation compression ratio | 40.0% |", report)
        self.assertIn("| Case | Category | Split | Result | Agent | Patch |", report)
        self.assertIn("| Split breakdown | unspecified=3 |", report)
        self.assertIn("Patch success", matrix_report)
        self.assertIn("Patch ok / agent failed", matrix_report)
        self.assertIn("Budget reductions", matrix_report)
        self.assertIn("Dropped blocks", matrix_report)
        self.assertIn("Artifacts", matrix_report)
        self.assertIn("Artifact integrity", matrix_report)
        self.assertIn("Raw output chars", matrix_report)
        self.assertIn("Output compression", matrix_report)
        self.assertIn(
            "| demo | scripted | - | 3 | 33.3% (1/3) | 66.7% (2/3) | 66.7% (2/3) |",
            matrix_report,
        )

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
        summary_row = next(
            line
            for line in report.splitlines()
            if line.startswith("| real_missing_key |")
        )
        self.assertEqual(
            summary_row.count("|"),
            "| Profile | Provider | Reasoning | Cases | Passed | Agent success | Patch success | Test pass | Verifier pass | Patch ok / agent failed | Avg tools | Repeated reads | Invalid calls | Policy denials | Tool failures | Context injected | Est. tokens | Budget reductions | Dropped blocks | Budget chars | Budget limit | Stable prefix changes | Memory updates | RepoMap used | RepoMap injected | Finish grace | Compression | Artifacts | Artifact integrity | Raw output chars | Output compression | Failure breakdown |".count("|"),
        )

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

    def test_eval_subprocess_uses_current_interpreter_for_python_command(self) -> None:
        previous_path = os.environ.get("PATH", "")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "fake-bin"
            fake_bin.mkdir()
            fake_python = fake_bin / "python"
            fake_python.write_text(
                "#!/bin/sh\n"
                "echo fake python should not run >&2\n"
                "exit 42\n",
                encoding="utf-8",
            )
            fake_python.chmod(
                fake_python.stat().st_mode
                | stat.S_IXUSR
                | stat.S_IXGRP
                | stat.S_IXOTH
            )

            os.environ["PATH"] = f"{fake_bin}{os.pathsep}{previous_path}"
            try:
                result = _run_command_for_eval(
                    "python -c \"import sys; print(sys.version_info[0])\"",
                    root,
                    10,
                )
            finally:
                os.environ["PATH"] = previous_path

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "3")
        self.assertNotIn("fake python should not run", result.stderr)

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

    def test_cli_context_ablations_return_zero_for_completed_experiment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "ablation.md"
            code = main(
                [
                    "--provider",
                    "hc-bench-oracle",
                    "--eval",
                    str(ROOT / "eval" / "bugfix_cases.json"),
                    "--context-ablations",
                    "--max-iterations",
                    "4",
                    "--eval-report",
                    str(report_path),
                ]
            )

            self.assertEqual(code, 0)
            self.assertIn("no_policy_retry", report_path.read_text(encoding="utf-8"))

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
        split="unspecified",
        source="unit-test",
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
            "raw_tool_output_chars": 1000,
            "tool_output_preview_chars": 400,
            "stored_artifact_count": 1,
            "artifact_missing_count": 0,
            "artifact_hash_mismatch_count": 0,
            "largest_tool_output_chars": 1000,
            "observation_compression_ratio": 0.4,
            "finish_grace_attempt_count": 0,
            "finish_grace_success_count": 0,
        },
    )


if __name__ == "__main__":
    unittest.main()
