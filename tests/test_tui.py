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


if __name__ == "__main__":
    unittest.main()
