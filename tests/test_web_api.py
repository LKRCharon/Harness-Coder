from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from harnesscoder.web_api.app import create_app


class WebApiTests(unittest.TestCase):
    def test_health_and_run_listing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            trace_path = root / "run_demo" / "trace.jsonl"
            trace_path.parent.mkdir(parents=True)
            trace_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "type": "run_started",
                                "run_id": "run_demo",
                                "task": "Inspect the repo",
                                "model": "scripted",
                                "model_metadata": {"provider": "scripted"},
                                "ts": "2026-05-28T12:00:00Z",
                            }
                        ),
                        json.dumps(
                            {
                                "type": "run_finished",
                                "run_id": "run_demo",
                                "status": "success",
                                "final_answer": "done",
                                "ts": "2026-05-28T12:00:01Z",
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            client = TestClient(create_app(root))

            health = client.get("/api/health")
            runs = client.get("/api/runs")

        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json(), {"ok": True})
        self.assertEqual(runs.status_code, 200)
        payload = runs.json()
        self.assertEqual(len(payload["runs"]), 1)
        self.assertEqual(payload["runs"][0]["run_id"], "run_demo")
        self.assertEqual(payload["runs"][0]["status"], "success")
        self.assertTrue(payload["runs"][0]["trace_path"].endswith("run_demo/trace.jsonl"))

    def test_run_detail_and_filtered_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            trace_path = root / "run_demo" / "trace.jsonl"
            trace_path.parent.mkdir(parents=True)
            trace_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "type": "run_started",
                                "run_id": "run_demo",
                                "task": "Inspect the repo",
                            }
                        ),
                        json.dumps(
                            {
                                "type": "note_injected",
                                "run_id": "run_demo",
                                "note_id": "note_1",
                            }
                        ),
                        json.dumps(
                            {
                                "type": "run_finished",
                                "run_id": "run_demo",
                                "status": "success",
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            client = TestClient(create_app(root))

            run_detail = client.get("/api/runs/run_demo")
            events = client.get(
                "/api/runs/run_demo/events",
                params=[("event_type", "note_injected")],
            )

        self.assertEqual(run_detail.status_code, 200)
        self.assertEqual(run_detail.json()["run"]["run_id"], "run_demo")
        self.assertEqual(events.status_code, 200)
        payload = events.json()
        self.assertEqual(len(payload["events"]), 1)
        self.assertEqual(payload["events"][0]["type"], "note_injected")

    def test_missing_run_returns_404(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = TestClient(create_app(Path(tmp)))

            response = client.get("/api/runs/missing-run")

        self.assertEqual(response.status_code, 404)

    def test_stream_returns_sse_events_for_existing_trace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            trace_path = root / "run_demo" / "trace.jsonl"
            trace_path.parent.mkdir(parents=True)
            trace_path.write_text(
                "\n".join(
                    [
                        json.dumps({"type": "run_started", "run_id": "run_demo", "task": "Inspect"}),
                        json.dumps({"type": "run_finished", "run_id": "run_demo", "status": "success"}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            client = TestClient(create_app(root, workspace_root=root))

            with client.stream(
                "GET",
                "/api/runs/run_demo/stream",
                params={"follow": "false"},
            ) as response:
                body = "".join(response.iter_text())

        self.assertEqual(response.status_code, 200)
        self.assertIn("event: connected", body)
        self.assertIn("event: trace_event", body)
        self.assertIn('"type": "run_finished"', body)
        self.assertIn("event: end", body)

    def test_post_run_launches_background_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("HarnessCoder test repo\n", encoding="utf-8")
            client = TestClient(create_app(root / ".harnesscoder" / "runs", workspace_root=root))

            response = client.post(
                "/api/runs",
                json={
                    "task": "Summarize this repo in one sentence",
                    "model_profile": "scripted",
                    "max_iterations": 4,
                    "notes_mode": "auto",
                },
            )
            self.assertEqual(response.status_code, 202)
            run_id = response.json()["run"]["run_id"]

            deadline = time.time() + 5
            detail = None
            while time.time() < deadline:
                detail_response = client.get(f"/api/runs/{run_id}")
                if detail_response.status_code == 200:
                    detail = detail_response.json()["run"]
                    if detail["summary"]["status"] == "success":
                        break
                time.sleep(0.1)

            self.assertIsNotNone(detail)
            assert detail is not None
            self.assertEqual(detail["summary"]["status"], "success")
            self.assertTrue(Path(detail["trace_path"]).is_file())
            events = client.get(f"/api/runs/{run_id}/events")
            self.assertEqual(events.status_code, 200)
            self.assertGreaterEqual(len(events.json()["events"]), 1)


if __name__ == "__main__":
    unittest.main()
