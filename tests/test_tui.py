from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from harnesscoder.core.runner import RunResult
from harnesscoder.tui import (
    ActiveRun,
    HarnessCoderTui,
    Message,
    TuiConfig,
    _clip_display,
    _display_width,
    _wrap_display_lines,
)


def make_config(cwd: Path) -> TuiConfig:
    return TuiConfig(
        cwd=cwd,
        trace_root=Path(".harnesscoder/runs"),
        provider="scripted",
        openai_base_url="https://api.openai.com/v1",
        openai_model=None,
        openai_api_key_env="OPENAI_API_KEY",
        max_iterations=8,
    )


class TuiRenderLogicTests(unittest.TestCase):
    def test_request_exit_blocks_when_agent_is_running(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            config = make_config(cwd)
            tui = HarnessCoderTui(config)
            tui._active_run = ActiveRun(
                prompt="task",
                config=config,
                started_at=time.monotonic(),
                known_traces=set(),
            )

            self.assertFalse(tui._request_exit())
            self.assertEqual(tui.status, "exit blocked: active run")
            self.assertIn("Agent is still running", tui.messages[-1].text)

    def test_pending_interrupt_blocks_when_agent_is_running(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            config = make_config(cwd)
            tui = HarnessCoderTui(config)
            tui._active_run = ActiveRun(
                prompt="task",
                config=config,
                started_at=time.monotonic(),
                known_traces=set(),
            )
            tui._interrupt_requested = True

            self.assertFalse(tui._handle_pending_interrupt())
            self.assertFalse(tui._interrupt_requested)
            self.assertEqual(tui.status, "exit blocked: active run")

    def test_pending_interrupt_exits_when_idle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            tui = HarnessCoderTui(make_config(cwd))
            tui._interrupt_requested = True

            self.assertTrue(tui._handle_pending_interrupt())
            self.assertFalse(tui._interrupt_requested)

    def test_active_run_blocks_mutating_slash_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            config = make_config(cwd)
            tui = HarnessCoderTui(config)
            tui._active_run = ActiveRun(
                prompt="task",
                config=config,
                started_at=time.monotonic(),
                known_traces=set(),
            )
            screen = _FakeScreen(height=10, width=40)

            tui._handle_slash_command("/edit README.md old new", screen)

            self.assertEqual(tui.status, "/edit blocked: active run")
            self.assertIn("blocked while the agent is running", tui.messages[-1].text)

    def test_active_run_allows_read_only_slash_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            config = make_config(cwd)
            tui = HarnessCoderTui(config)
            tui._active_run = ActiveRun(
                prompt="task",
                config=config,
                started_at=time.monotonic(),
                known_traces=set(),
            )
            screen = _FakeScreen(height=10, width=40)

            tui._handle_slash_command("/status", screen)

            self.assertTrue(any(message.text.startswith("cwd:") for message in tui.messages))
            self.assertNotIn("blocked", tui.status)

    def test_draw_places_status_card_above_prompt_card(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            tui = HarnessCoderTui(make_config(cwd))
            tui.messages.clear()
            tui.status = "ready"
            tui.input_buffer = "hello"
            screen = _FakeScreen(height=10, width=40)

            tui._draw(screen)

            self.assertEqual(screen.text_at(6, 0), "[READY] ready")
            self.assertEqual(screen.text_at(7, 0), "+-- Prompt ----------------------------+")
            self.assertEqual(screen.text_at(8, 0), "| > hello                              |")

    def test_render_messages_uses_role_cards(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            tui = HarnessCoderTui(make_config(cwd))
            tui.messages = [Message("user", "please inspect the repo")]

            rendered = tui._render_messages(40)

        self.assertEqual(rendered[0], ("+-- YOU -------------------------------+", "border"))
        self.assertEqual(rendered[1], ("| please inspect the repo              |", "user"))
        self.assertEqual(rendered[2], ("+--------------------------------------+", "border"))

    def test_render_messages_keeps_chinese_card_width_stable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            tui = HarnessCoderTui(make_config(cwd))
            tui.messages = [Message("user", "看一下这个 repo 是做什么的")]

            rendered = tui._render_messages(40)

        self.assertEqual(_display_width(rendered[0][0]), 40)
        self.assertEqual(_display_width(rendered[1][0]), 40)
        self.assertIn("看一下这个", rendered[1][0])

    def test_footer_prompt_keeps_chinese_card_width_stable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            tui = HarnessCoderTui(make_config(cwd))
            tui.input_buffer = "中文输入测试"
            screen = _FakeScreen(height=10, width=40)

            tui._draw(screen)

            prompt = screen.text_at(8, 0)
            assert prompt is not None
            self.assertEqual(_display_width(prompt), 40)
            self.assertIn("中文输入", prompt)

    def test_display_width_helpers_handle_chinese(self) -> None:
        self.assertEqual(_display_width("中文A"), 5)
        self.assertEqual(_clip_display("中文ABC", 5), "中文.")
        self.assertEqual(_wrap_display_lines("中文ABC", 4), ["中文", "ABC"])

    def test_latest_trace_event_label_describes_tool_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            trace_path = cwd / ".harnesscoder/runs/run_123/trace.jsonl"
            trace_path.parent.mkdir(parents=True)
            trace_path.write_text(
                "\n".join(
                    [
                        json.dumps({"type": "run_started", "run_id": "run_123"}),
                        json.dumps(
                            {
                                "type": "tool_result",
                                "run_id": "run_123",
                                "result": {"tool_name": "read_file", "ok": True},
                            }
                        ),
                    ]
                ),
                encoding="utf-8",
            )

            tui = HarnessCoderTui(make_config(cwd))

            self.assertEqual(
                tui._latest_trace_event_label(trace_path),
                "tool_result read_file ok=True",
            )

    def test_discover_active_trace_ignores_known_traces(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            old_trace = cwd / ".harnesscoder/runs/run_old/trace.jsonl"
            new_trace = cwd / ".harnesscoder/runs/run_new/trace.jsonl"
            old_trace.parent.mkdir(parents=True)
            new_trace.parent.mkdir(parents=True)
            old_trace.write_text('{"type":"run_started"}\n', encoding="utf-8")
            time.sleep(0.01)
            new_trace.write_text('{"type":"run_started"}\n', encoding="utf-8")

            config = make_config(cwd)
            tui = HarnessCoderTui(config)
            active = ActiveRun(
                prompt="task",
                config=config,
                started_at=time.monotonic(),
                known_traces={old_trace.resolve()},
            )

            self.assertEqual(tui._discover_active_trace(active), new_trace.resolve())

    def test_poll_active_run_appends_result_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            config = make_config(cwd)
            tui = HarnessCoderTui(config)
            trace_path = cwd / ".harnesscoder/runs/run_done/trace.jsonl"
            trace_path.parent.mkdir(parents=True)
            trace_path.write_text('{"type":"run_finished","status":"success"}\n')
            tui._active_run = ActiveRun(
                prompt="task",
                config=config,
                started_at=time.monotonic(),
                known_traces=set(),
                result=RunResult(
                    run_id="run_done",
                    status="success",
                    final_answer="done",
                    trace_path=trace_path,
                ),
                done=True,
                trace_path=trace_path,
            )

            tui._poll_active_run()

            self.assertIsNone(tui._active_run)
            self.assertEqual(tui.last_trace_path, trace_path)
            self.assertTrue(any(message.text.startswith("done") for message in tui.messages))

    def test_snapshot_config_preserves_context_and_repo_map_modes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            config = make_config(cwd)
            config.context_mode = "memory"
            config.repo_map_mode = "none"
            tui = HarnessCoderTui(config)

            snapshot = tui._snapshot_config()

        self.assertEqual(snapshot.context_mode, "memory")
        self.assertEqual(snapshot.repo_map_mode, "none")

    def test_snapshot_config_preserves_session_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            config = make_config(cwd)
            config.session_id = "interview"
            config.session_root = Path(".sessions")
            tui = HarnessCoderTui(config)

            snapshot = tui._snapshot_config()

        self.assertEqual(snapshot.session_id, "interview")
        self.assertEqual(snapshot.session_root, Path(".sessions"))

    def test_session_command_switches_and_reports_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            tui = HarnessCoderTui(make_config(cwd))
            screen = _FakeScreen(height=10, width=40)

            tui._handle_slash_command("/session interview", screen)

        self.assertEqual(tui.config.session_id, "interview")
        self.assertTrue(any("session_id: interview" in message.text for message in tui.messages))

    def test_reset_session_clears_session_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            tui = HarnessCoderTui(make_config(cwd))
            store = tui._session_store()
            store.append_run(
                "default",
                user_message="inspect repo",
                result=RunResult(
                    run_id="run_abc",
                    status="success",
                    final_answer="done",
                    trace_path=cwd / ".harnesscoder/runs/run_abc/trace.jsonl",
                ),
            )
            screen = _FakeScreen(height=10, width=40)

            tui._handle_slash_command("/reset-session", screen)
            context = store.build_context("default")

        self.assertEqual(context["turn_count"], 0)
        self.assertTrue(any("session reset: default" in message.text for message in tui.messages))

    def test_reasoning_command_updates_codex_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            config = make_config(cwd)
            tui = HarnessCoderTui(config)
            screen = _FakeScreen(height=10, width=40)

            tui._handle_slash_command("/reasoning high", screen)

        self.assertEqual(config.reasoning_effort, "high")
        self.assertTrue(any("reasoning_effort set to high" in message.text for message in tui.messages))

    def test_snapshot_config_preserves_reasoning_effort(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            config = make_config(cwd)
            config.reasoning_effort = "xhigh"
            tui = HarnessCoderTui(config)

            snapshot = tui._snapshot_config()

        self.assertEqual(snapshot.reasoning_effort, "xhigh")

    def test_run_agent_background_uses_context_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            config = make_config(cwd)
            config.provider = "hc-bench-oracle"
            config.context_mode = "pack"
            active = ActiveRun(
                prompt="Finish immediately.",
                config=config,
                started_at=time.monotonic(),
                known_traces=set(),
            )
            tui = HarnessCoderTui(config)

            tui._run_agent_background(active)

            self.assertIsNone(active.error)
            assert active.trace_path is not None
            events = [
                json.loads(line)
                for line in active.trace_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            run_started = next(event for event in events if event["type"] == "run_started")
            self.assertEqual(run_started["context_mode"], "pack")

    def test_run_agent_background_persists_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            config = make_config(cwd)
            config.provider = "hc-bench-oracle"
            config.context_mode = "pack"
            config.session_id = "interview"
            active = ActiveRun(
                prompt="Finish immediately.",
                config=config,
                started_at=time.monotonic(),
                known_traces=set(),
            )
            tui = HarnessCoderTui(config)

            tui._run_agent_background(active)
            context = tui._session_store(config).build_context("interview")

        self.assertIsNone(active.error)
        self.assertEqual(context["turn_count"], 1)
        assert active.result is not None
        self.assertEqual(context["recent_turns"][0]["run_id"], active.result.run_id)

    def test_direct_tool_large_output_uses_slash_artifact_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            large_payload = "x" * 5200
            (cwd / "test_large_output.py").write_text(
                "import unittest\n\n"
                "class LargeOutputTest(unittest.TestCase):\n"
                "    def test_noisy_success(self):\n"
                f"        print({large_payload!r})\n"
                "        self.assertTrue(True)\n",
                encoding="utf-8",
            )
            tui = HarnessCoderTui(make_config(cwd))

            tui._direct_tool(
                "run_tests",
                {"cmd": "python -m unittest test_large_output.py", "timeout": 30},
            )
            artifact = next(
                (cwd / ".harnesscoder/runs/slash-artifacts/artifacts").glob("*.txt")
            )
            artifact_text = artifact.read_text(encoding="utf-8")

        self.assertIn("artifact:", tui.messages[-1].text)
        self.assertIn("full output stored as artifact", tui.messages[-1].text)
        self.assertNotIn(large_payload, tui.messages[-1].text)
        self.assertIn(large_payload, artifact_text)


class _FakeScreen:
    def __init__(self, height: int, width: int) -> None:
        self.height = height
        self.width = width
        self.calls: list[tuple[int, int, str]] = []

    def erase(self) -> None:
        self.calls.clear()

    def getmaxyx(self) -> tuple[int, int]:
        return (self.height, self.width)

    def addstr(self, row: int, col: int, text: str, _attrs: int = 0) -> None:
        self.calls.append((row, col, text))

    def refresh(self) -> None:
        pass

    def text_at(self, row: int, col: int) -> str | None:
        for call_row, call_col, text in reversed(self.calls):
            if call_row == row and call_col == col:
                return text
        return None


if __name__ == "__main__":
    unittest.main()
