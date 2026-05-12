from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from harnesscoder.core.runner import RunResult
from harnesscoder.tui import ActiveRun, HarnessCoderTui, TuiConfig


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

    def test_draw_places_status_above_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            tui = HarnessCoderTui(make_config(cwd))
            tui.messages.clear()
            tui.status = "ready"
            tui.input_buffer = "hello"
            screen = _FakeScreen(height=10, width=40)

            tui._draw(screen)

            self.assertEqual(screen.text_at(8, 0), "ready")
            self.assertEqual(screen.text_at(9, 0), "> hello")

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
