from __future__ import annotations

import json
import os
import hashlib
import stat
import sys
import tempfile
import unittest
from pathlib import Path

from harnesscoder.core.policy import ToolPolicy
from harnesscoder.core.repo_map import build_repo_map
from harnesscoder.core.runner import AgentRunner, RunResult
from harnesscoder.core.session import SessionStore
from harnesscoder.core.state import AgentState, ModelAction
from harnesscoder.core.models import ModelAdapterError
from harnesscoder.core.artifacts import store_large_observation
from harnesscoder.core.tools import (
    ToolRegistry,
    ToolResult,
    normalize_python_command,
    redact_sensitive_text,
    safe_subprocess_env,
)
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

    def test_run_tests_uses_current_interpreter_for_python_command(self) -> None:
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
            (root / "test_sample.py").write_text(
                "import unittest\n\n"
                "class SampleTest(unittest.TestCase):\n"
                "    def test_ok(self):\n"
                "        self.assertEqual(1 + 1, 2)\n",
                encoding="utf-8",
            )

            os.environ["PATH"] = f"{fake_bin}{os.pathsep}{previous_path}"
            try:
                result = ToolRegistry(root).run_tests(
                    call_id="call_tests",
                    cmd="python -m unittest discover",
                    timeout=30,
                )
            finally:
                os.environ["PATH"] = previous_path

        self.assertTrue(result.ok, result.output)
        self.assertEqual(result.metadata["returncode"], 0)
        self.assertNotIn("fake python should not run", result.output)

    def test_normalize_python_command_only_rewrites_bare_python(self) -> None:
        self.assertEqual(
            normalize_python_command(["python", "-m", "unittest"]),
            [sys.executable, "-m", "unittest"],
        )
        self.assertEqual(
            normalize_python_command(["python3.11", "-m", "unittest"]),
            [sys.executable, "-m", "unittest"],
        )
        self.assertEqual(
            normalize_python_command(["/usr/bin/python3", "-m", "unittest"]),
            ["/usr/bin/python3", "-m", "unittest"],
        )

    def test_repo_map_extracts_python_symbols_and_omits_local_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "models.toml").write_text("api_key = 'secret'\n", encoding="utf-8")
            (root / ".env").write_text("TOKEN=secret\n", encoding="utf-8")
            (root / "billing.py").write_text(
                "import decimal\n\n"
                "class Invoice:\n"
                "    def total(self, cents):\n"
                "        return cents\n\n"
                "def prorate_monthly():\n"
                "    return 1\n",
                encoding="utf-8",
            )

            result = build_repo_map(root, query="invoice prorate", max_tokens=600)

        self.assertIn("billing.py", result.text)
        self.assertIn("class Invoice", result.text)
        self.assertIn("prorate_monthly", result.text)
        self.assertNotIn("models.toml", result.text)
        self.assertNotIn(".env", result.text)
        self.assertEqual(result.metadata["files_indexed"], 1)

    def test_repo_map_skips_symlinks_that_escape_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            outside = Path(tmp) / "outside_secret.py"
            root.mkdir()
            outside.write_text("def leaked_symbol():\n    return 'secret'\n", encoding="utf-8")
            (root / "app.py").write_text("def visible_symbol():\n    return 1\n", encoding="utf-8")
            try:
                (root / "linked_secret.py").symlink_to(outside)
            except OSError:
                self.skipTest("symlinks are not supported on this filesystem")

            result = build_repo_map(root, query="symbol leaked visible", max_tokens=600)

        self.assertIn("app.py", result.text)
        self.assertIn("visible_symbol", result.text)
        self.assertNotIn("linked_secret.py", result.text)
        self.assertNotIn("leaked_symbol", result.text)

    def test_file_tools_do_not_expose_local_secret_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("DEEPSEEK_API_KEY=secret-value\n", encoding="utf-8")
            (root / "models.toml").write_text(
                "[models.local]\napi_key = 'secret-value'\n",
                encoding="utf-8",
            )
            (root / "app.py").write_text("TOKEN_NAME = 'public symbol'\n", encoding="utf-8")
            registry = ToolRegistry(root)

            read_env = registry.read_file(call_id="call_read_env", path=".env")
            search = registry.search_code(call_id="call_search", query="secret-value", path=".")

        self.assertFalse(read_env.ok)
        self.assertIn("sensitive local file", read_env.error or "")
        self.assertTrue(search.ok, search.error)
        self.assertNotIn("secret-value", search.output)
        self.assertNotIn("DEEPSEEK_API_KEY", search.output)
        self.assertNotIn("models.toml", search.output)

    def test_subprocess_env_helpers_drop_and_redact_sensitive_values(self) -> None:
        previous = os.environ.get("HARNESSCODER_TEST_API_KEY")
        os.environ["HARNESSCODER_TEST_API_KEY"] = "secret-value-123"
        try:
            env = safe_subprocess_env({"PYTHONUTF8": "1"})
            redacted = redact_sensitive_text(
                "leaked=secret-value-123\nDEEPSEEK_API_KEY=hardcoded-value\n"
            )
        finally:
            if previous is None:
                os.environ.pop("HARNESSCODER_TEST_API_KEY", None)
            else:
                os.environ["HARNESSCODER_TEST_API_KEY"] = previous

        self.assertNotIn("HARNESSCODER_TEST_API_KEY", env)
        self.assertEqual(env["PYTHONUTF8"], "1")
        self.assertNotIn("secret-value-123", redacted)
        self.assertIn("DEEPSEEK_API_KEY=[REDACTED]", redacted)

    def test_search_code_treats_query_as_literal_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "sample.py").write_text(
                "def lookup(value):\n"
                "    return mapping[value]\n"
                "needle = 'foo(bar)[baz].txt'\n",
                encoding="utf-8",
            )
            registry = ToolRegistry(root)

            result = registry.search_code(
                call_id="call_search_literal",
                query="foo(bar)[baz].txt",
                path=".",
            )

        self.assertTrue(result.ok, result.error)
        self.assertIn("sample.py", result.output)


class ObservationArtifactTests(unittest.TestCase):
    def test_artifact_filename_sanitizes_call_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_path = Path(tmp)
            raw_output = "x" * 5000
            result = ToolResult(
                call_id="../call/with spaces",
                tool_name="run_tests",
                ok=True,
                output=raw_output,
            )

            stored = store_large_observation(
                result,
                run_path=run_path,
                preview_chars=100,
            ).result

            artifact_path = Path(stored.metadata["artifact_path"])
            resolved = (run_path / artifact_path).resolve()
            artifact_exists = resolved.is_file()
            artifact_text = resolved.read_text(encoding="utf-8")
            inside_run_path = resolved.is_relative_to(run_path.resolve())

        self.assertEqual(artifact_path.parts[0], "artifacts")
        self.assertEqual(artifact_path.name, "call_with_spaces.txt")
        self.assertTrue(inside_run_path)
        self.assertTrue(artifact_exists)
        self.assertEqual(artifact_text, raw_output)

    def test_artifact_store_redacts_sensitive_patterns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_path = Path(tmp)
            secret_line = "OPENAI_API_KEY=literal-secret"
            result = ToolResult(
                call_id="call_secret",
                tool_name="read_file",
                ok=True,
                output=(secret_line + "\n") * 400,
            )

            stored = store_large_observation(
                result,
                run_path=run_path,
                preview_chars=120,
            ).result
            artifact_text = (
                run_path / stored.metadata["artifact_path"]
            ).read_text(encoding="utf-8")

        self.assertNotIn(secret_line, artifact_text)
        self.assertNotIn(secret_line, stored.output)
        self.assertIn("OPENAI_API_KEY=[REDACTED]", artifact_text)

    def test_artifact_write_failure_keeps_preview_and_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            blocking_file = Path(tmp) / "not-a-directory"
            blocking_file.write_text("blocked\n", encoding="utf-8")
            result = ToolResult(
                call_id="call_large",
                tool_name="run_tests",
                ok=True,
                output="x" * 5000,
            )

            stored = store_large_observation(
                result,
                run_path=blocking_file,
                preview_chars=100,
            )

        self.assertFalse(stored.stored)
        self.assertFalse(stored.result.metadata["artifact_stored"])
        self.assertIn("artifact_error", stored.result.metadata)
        self.assertLessEqual(len(stored.result.output), 100)


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

    def test_read_file_policy_rejects_sensitive_local_files(self) -> None:
        policy = ToolPolicy()
        root = Path.cwd()

        for path in (".env", ".env.local", "models.toml", "keys/private.pem"):
            decision = policy.check("read_file", {"path": path}, root)
            self.assertFalse(decision.allowed, path)

    def test_run_command_policy_is_allowlisted_and_blocks_secret_bypasses(self) -> None:
        policy = ToolPolicy()
        root = Path.cwd()
        allowed = policy.check("run_command", {"cmd": "find . -maxdepth 1 -type f"}, root)
        self.assertTrue(allowed.allowed, allowed.reason)

        for command in (
            "env",
            "printenv",
            "cat .env",
            "python -c 'print(1)'",
            "find .env -maxdepth 1",
            "find keys/private.pem -maxdepth 1",
            "find . -exec cat README.md {}",
        ):
            decision = policy.check("run_command", {"cmd": command}, root)
            self.assertFalse(decision.allowed, command)

    def test_repo_map_policy_is_read_only_and_bounded(self) -> None:
        policy = ToolPolicy()
        allowed = policy.check(
            "repo_map",
            {"query": "Invoice", "max_tokens": 1200, "refresh": False},
            Path.cwd(),
        )
        denied = policy.check(
            "repo_map",
            {"query": "Invoice", "max_tokens": 100_000},
            Path.cwd(),
        )

        self.assertTrue(allowed.allowed, allowed.reason)
        self.assertFalse(denied.allowed)


class ReplayTests(unittest.TestCase):
    def test_summarize_trace_counts_tools_and_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            trace = Path(tmp) / "trace.jsonl"
            records = [
                {
                    "type": "run_started",
                    "run_id": "run_x",
                    "task": "demo",
                    "model_metadata": {
                        "provider": "openai-codex",
                        "model": "codex-test",
                        "reasoning_effort": "high",
                    },
                },
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
        self.assertEqual(summary["model_metadata"]["reasoning_effort"], "high")
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
        self.assertGreater(metrics["stable_prefix_tokens"], 0)
        self.assertGreater(metrics["dynamic_suffix_tokens"], 0)
        self.assertEqual(metrics["stable_prefix_change_count"], 0)
        self.assertEqual(metrics["memory_updated_count"], 1)
        self.assertIn("task/explored_files", state["memory_blocks"])
        self.assertIn("read README.md", state["memory_blocks"]["task/explored_files"]["value"])

    def test_runner_records_safe_model_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runner = AgentRunner(
                model=_MetadataFinishModel(),
                cwd=root,
                trace_root=root / ".harnesscoder" / "runs",
                max_iterations=1,
            )

            result = runner.run("Finish.")
            summary = summarize_trace(result.trace_path)
            records = [
                json.loads(line)
                for line in result.trace_path.read_text(encoding="utf-8").splitlines()
            ]
            run_started = next(record for record in records if record["type"] == "run_started")

        self.assertEqual(result.status, "success")
        self.assertEqual(
            run_started["model_metadata"]["reasoning_effort"],
            "xhigh",
        )
        self.assertEqual(summary["model_metadata"]["effective_reasoning_effort"], "xhigh")
        self.assertNotIn("api_key", json.dumps(run_started["model_metadata"]))

    def test_runner_retries_retryable_model_adapter_error_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model = _RetryableErrorThenFinishModel()
            runner = AgentRunner(
                model=model,
                cwd=root,
                trace_root=root / ".harnesscoder" / "runs",
                max_iterations=1,
            )

            result = runner.run("Finish after a retry.")
            summary = summarize_trace(result.trace_path)
            records = [
                json.loads(line)
                for line in result.trace_path.read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(result.status, "success")
        self.assertEqual(model.calls, 2)
        self.assertEqual(summary["metrics"]["model_retry_count"], 1)
        retry = next(record for record in records if record["type"] == "model_retry")
        self.assertEqual(retry["reason"], "model_step")
        self.assertEqual(retry["attempt"], 1)
        self.assertEqual(retry["max_retries"], 1)
        self.assertIn("did not include text output", retry["error"])

    def test_runner_does_not_retry_non_retryable_model_adapter_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model = _UnknownToolErrorModel()
            runner = AgentRunner(
                model=model,
                cwd=root,
                trace_root=root / ".harnesscoder" / "runs",
                max_iterations=1,
            )

            result = runner.run("Fail with a protocol error.")
            summary = summarize_trace(result.trace_path)

        self.assertEqual(result.status, "model_error")
        self.assertEqual(model.calls, 1)
        self.assertEqual(summary["metrics"]["model_retry_count"], 0)

    def test_runner_injects_repo_map_in_pack_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text(
                "class Target:\n"
                "    pass\n\n"
                "def solve_target():\n"
                "    return Target()\n",
                encoding="utf-8",
            )
            runner = AgentRunner(
                model=_CaptureContextModel(),
                cwd=root,
                trace_root=root / ".harnesscoder" / "runs",
                max_iterations=2,
                context_mode="pack",
            )

            result = runner.run("Find Target.")
            summary = summarize_trace(result.trace_path)

        self.assertEqual(result.status, "success")
        self.assertIn("repo_map", _CaptureContextModel.last_payload)
        self.assertIn("app.py", _CaptureContextModel.last_payload)
        self.assertEqual(summary["metrics"]["repo_map_built_count"], 1)
        self.assertEqual(summary["metrics"]["repo_map_injected_count"], 1)

    def test_runner_records_session_context_injection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runner = AgentRunner(
                model=_CaptureContextModel(),
                cwd=root,
                trace_root=root / ".harnesscoder" / "runs",
                max_iterations=1,
                context_mode="pack",
            )
            session_context = {
                "session_id": "interview",
                "turn_count": 1,
                "summary": "1. user='inspect repo'; status=success",
                "recent_turns": [
                    {
                        "turn_index": 1,
                        "user_message": "inspect repo",
                        "final_answer": "repo inspected",
                        "status": "success",
                        "run_id": "run_prev",
                    }
                ],
            }

            result = runner.run("Continue.", session_context=session_context)
            summary = summarize_trace(result.trace_path)
            records = [
                json.loads(line)
                for line in result.trace_path.read_text(encoding="utf-8").splitlines()
            ]
            run_started = next(record for record in records if record["type"] == "run_started")

        self.assertEqual(result.status, "success")
        self.assertIn("repo inspected", _CaptureContextModel.last_payload)
        self.assertEqual(run_started["session_id"], "interview")
        self.assertEqual(summary["metrics"]["session_context_loaded_count"], 1)
        self.assertEqual(summary["metrics"]["session_context_injected_count"], 1)

    def test_session_store_persists_runs_and_builds_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = SessionStore(Path(".harnesscoder/sessions"), root)
            result = RunResult(
                run_id="run_abc",
                status="success",
                final_answer="first answer",
                trace_path=root / ".harnesscoder/runs/run_abc/trace.jsonl",
            )

            record = store.append_run(
                "interview",
                user_message="inspect repo",
                result=result,
            )
            context = store.build_context("interview")
            path = store.path_for("interview")
            path_exists = path.is_file()

        self.assertTrue(path_exists)
        self.assertEqual(record.session_id, "interview")
        self.assertEqual(context["turn_count"], 1)
        self.assertEqual(context["recent_turns"][0]["run_id"], "run_abc")
        self.assertIn("inspect repo", context["summary"])

    def test_finish_grace_accepts_finish_after_successful_tests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "test_sample.py").write_text(
                "import unittest\n\n"
                "class SampleTest(unittest.TestCase):\n"
                "    def test_ok(self):\n"
                "        self.assertTrue(True)\n",
                encoding="utf-8",
            )
            runner = AgentRunner(
                model=_FinishOnGraceModel(),
                cwd=root,
                trace_root=root / ".harnesscoder" / "runs",
                max_iterations=1,
            )

            result = runner.run("Run tests, then finish.")
            summary = summarize_trace(result.trace_path)
            records = [
                json.loads(line)
                for line in result.trace_path.read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(result.status, "success")
        self.assertEqual(summary["metrics"]["finish_grace_attempt_count"], 1)
        self.assertEqual(summary["metrics"]["finish_grace_success_count"], 1)
        self.assertTrue(
            any(
                record.get("type") == "run_finished"
                and record.get("finish_grace") is True
                for record in records
            )
        )

    def test_finish_grace_rejects_tool_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# Demo\n", encoding="utf-8")
            (root / "test_sample.py").write_text(
                "import unittest\n\n"
                "class SampleTest(unittest.TestCase):\n"
                "    def test_ok(self):\n"
                "        self.assertTrue(True)\n",
                encoding="utf-8",
            )
            runner = AgentRunner(
                model=_ToolOnGraceModel(),
                cwd=root,
                trace_root=root / ".harnesscoder" / "runs",
                max_iterations=1,
            )

            result = runner.run("Run tests, then try another tool.")
            summary = summarize_trace(result.trace_path)

        self.assertEqual(result.status, "max_iterations")
        self.assertEqual(summary["metrics"]["finish_grace_attempt_count"], 1)
        self.assertEqual(summary["metrics"]["finish_grace_success_count"], 0)
        self.assertEqual(summary["metrics"]["stable_prefix_change_count"], 1)
        self.assertEqual(summary["failure_category"], "max_iterations")

    def test_finish_grace_is_not_offered_without_successful_tests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# Demo\n", encoding="utf-8")
            runner = AgentRunner(
                model=_ReadOnlyModel(),
                cwd=root,
                trace_root=root / ".harnesscoder" / "runs",
                max_iterations=1,
            )

            result = runner.run("Read only.")
            summary = summarize_trace(result.trace_path)

        self.assertEqual(result.status, "max_iterations")
        self.assertEqual(summary["metrics"]["finish_grace_attempt_count"], 0)
        self.assertEqual(summary["metrics"]["finish_grace_success_count"], 0)

    def test_finish_grace_is_not_offered_after_later_failed_test(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "test_sample.py").write_text(
                "import unittest\n\n"
                "class SampleTest(unittest.TestCase):\n"
                "    def test_ok(self):\n"
                "        self.assertTrue(True)\n",
                encoding="utf-8",
            )
            runner = AgentRunner(
                model=_PassThenFailTestsModel(),
                cwd=root,
                trace_root=root / ".harnesscoder" / "runs",
                max_iterations=2,
            )

            result = runner.run("Run passing then failing tests.")
            summary = summarize_trace(result.trace_path)

        self.assertEqual(result.status, "max_iterations")
        self.assertEqual(summary["metrics"]["finish_grace_attempt_count"], 0)
        self.assertEqual(summary["metrics"]["finish_grace_success_count"], 0)

    def test_large_tool_output_is_previewed_and_stored_as_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            large_payload = "x" * 5200
            (root / "test_large_output.py").write_text(
                "import unittest\n\n"
                "class LargeOutputTest(unittest.TestCase):\n"
                "    def test_noisy_success(self):\n"
                f"        print({large_payload!r})\n"
                "        self.assertTrue(True)\n",
                encoding="utf-8",
            )
            runner = AgentRunner(
                model=_LargeOutputThenFinishModel(),
                cwd=root,
                trace_root=root / ".harnesscoder" / "runs",
                max_iterations=3,
            )

            result = runner.run("Run the noisy test.")
            summary = summarize_trace(result.trace_path)
            records = [
                json.loads(line)
                for line in result.trace_path.read_text(encoding="utf-8").splitlines()
            ]
            tool_record = next(
                record
                for record in records
                if record.get("type") == "tool_result"
                and record.get("result", {}).get("tool_name") == "run_tests"
            )
            tool_result = tool_record["result"]
            metadata = tool_result["metadata"]
            artifact_path = result.trace_path.parent / metadata["artifact_path"]
            artifact_exists = artifact_path.is_file()
            artifact_text = artifact_path.read_text(encoding="utf-8")
            artifact_sha256 = hashlib.sha256(artifact_text.encode("utf-8")).hexdigest()
            state_updated = next(
                record
                for record in records
                if record.get("type") == "state_updated"
            )
            checkpoint_path = Path(
                next(
                    record["checkpoint_path"]
                    for record in records
                    if record.get("type") == "checkpoint_created"
                )
            )
            checkpoint_text = checkpoint_path.read_text(encoding="utf-8")

        self.assertEqual(result.status, "success")
        self.assertTrue(metadata["artifact_stored"])
        self.assertTrue(artifact_exists)
        self.assertIn(large_payload, artifact_text)
        self.assertNotIn(large_payload, tool_result["output"])
        self.assertNotIn(large_payload, state_updated["state"]["last_observation"]["output"])
        self.assertNotIn(large_payload, checkpoint_text)
        self.assertNotIn(large_payload, _LargeOutputThenFinishModel.last_payload)
        self.assertIn("full output stored as artifact", _LargeOutputThenFinishModel.last_payload)
        self.assertLessEqual(len(tool_result["output"]), 4000)
        self.assertEqual(metadata["artifact_chars"], metadata["raw_output_chars"])
        self.assertEqual(metadata["observation_preview_chars"], len(tool_result["output"]))
        self.assertEqual(metadata["artifact_sha256"], artifact_sha256)
        metrics = summary["metrics"]
        self.assertEqual(metrics["stored_artifact_count"], 1)
        self.assertGreater(metrics["raw_tool_output_chars"], metrics["tool_output_preview_chars"])
        self.assertLess(metrics["observation_compression_ratio"], 1)


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


class _CaptureContextModel:
    name = "capture-context"
    last_payload = ""

    def next_action(self, _state: AgentState, context=None) -> ModelAction:
        self.__class__.last_payload = context.to_model_input()[1]["content"]
        return ModelAction(
            kind="finish",
            rationale="Captured context.",
            content="done",
        )


class _MetadataFinishModel:
    name = "metadata-finish"

    def model_metadata(self) -> dict[str, object]:
        return {
            "provider": "openai-codex",
            "model": "codex-test",
            "reasoning_effort": "xhigh",
            "effective_reasoning_effort": "xhigh",
        }

    def next_action(self, _state: AgentState, _context=None) -> ModelAction:
        return ModelAction(
            kind="finish",
            rationale="Done.",
            content="done",
        )


class _RetryableErrorThenFinishModel:
    name = "retryable-error-then-finish"

    def __init__(self) -> None:
        self.calls = 0

    def next_action(self, _state: AgentState, _context=None) -> ModelAction:
        self.calls += 1
        if self.calls == 1:
            raise ModelAdapterError("model API response did not include text output")
        return ModelAction(
            kind="finish",
            rationale="Retry produced a valid action.",
            content="done",
        )


class _UnknownToolErrorModel:
    name = "unknown-tool-error"

    def __init__(self) -> None:
        self.calls = 0

    def next_action(self, _state: AgentState, _context=None) -> ModelAction:
        self.calls += 1
        raise ModelAdapterError("tool action requested unknown tool: fly_to_moon")


class _FinishOnGraceModel:
    name = "finish-on-grace"

    def next_action(self, state: AgentState, _context=None) -> ModelAction:
        if state.latest_observation_for("run_tests") is None:
            return ModelAction(
                kind="tool",
                rationale="Run tests.",
                tool_name="run_tests",
                tool_args={"cmd": "python -m unittest discover"},
            )
        return ModelAction(
            kind="finish",
            rationale="Tests passed.",
            content="done",
        )


class _ToolOnGraceModel:
    name = "tool-on-grace"

    def next_action(self, state: AgentState, _context=None) -> ModelAction:
        if state.latest_observation_for("run_tests") is None:
            return ModelAction(
                kind="tool",
                rationale="Run tests.",
                tool_name="run_tests",
                tool_args={"cmd": "python -m unittest discover"},
            )
        return ModelAction(
            kind="tool",
            rationale="Try a tool after tests.",
            tool_name="read_file",
            tool_args={"path": "README.md"},
        )


class _ReadOnlyModel:
    name = "read-only"

    def next_action(self, _state: AgentState, _context=None) -> ModelAction:
        return ModelAction(
            kind="tool",
            rationale="Read README.",
            tool_name="read_file",
            tool_args={"path": "README.md"},
        )


class _PassThenFailTestsModel:
    name = "pass-then-fail-tests"

    def next_action(self, state: AgentState, _context=None) -> ModelAction:
        tests = [
            observation
            for observation in state.observations
            if observation.tool_name == "run_tests"
        ]
        if not tests:
            return ModelAction(
                kind="tool",
                rationale="Run passing tests.",
                tool_name="run_tests",
                tool_args={"cmd": "python -m unittest discover"},
            )
        return ModelAction(
            kind="tool",
            rationale="Run a failing command.",
            tool_name="run_tests",
            tool_args={"cmd": "python -m unittest missing_module"},
        )


class _LargeOutputThenFinishModel:
    name = "large-output-then-finish"
    last_payload = ""

    def next_action(self, state: AgentState, context=None) -> ModelAction:
        if state.latest_observation_for("run_tests") is None:
            return ModelAction(
                kind="tool",
                rationale="Run the noisy test.",
                tool_name="run_tests",
                tool_args={"cmd": "python -m unittest test_large_output.py"},
            )
        self.__class__.last_payload = context.to_model_input()[1]["content"]
        return ModelAction(
            kind="finish",
            rationale="Noisy test passed.",
            content="done",
        )


if __name__ == "__main__":
    unittest.main()
