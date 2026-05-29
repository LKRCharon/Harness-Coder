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
                                "session_id": "thread_demo",
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
        self.assertEqual(payload["runs"][0]["session_id"], "thread_demo")
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
                                "session_id": "thread_demo",
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

    def test_thread_listing_and_detail_group_runs_by_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            trace_root = root / ".harnesscoder" / "runs"
            session_root = root / ".harnesscoder" / "sessions"

            first_trace = trace_root / "run_first" / "trace.jsonl"
            first_trace.parent.mkdir(parents=True)
            first_trace.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "type": "run_started",
                                "run_id": "run_first",
                                "session_id": "thread_demo",
                                "task": "Inspect repo",
                                "model": "scripted",
                                "ts": "2026-05-28T12:00:00Z",
                            }
                        ),
                        json.dumps(
                            {
                                "type": "run_finished",
                                "run_id": "run_first",
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

            second_trace = trace_root / "run_second" / "trace.jsonl"
            second_trace.parent.mkdir(parents=True)
            second_trace.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "type": "run_started",
                                "run_id": "run_second",
                                "session_id": "thread_demo",
                                "task": "Only change web layer",
                                "model": "scripted",
                                "ts": "2026-05-28T12:05:00Z",
                            }
                        ),
                        json.dumps(
                            {
                                "type": "run_finished",
                                "run_id": "run_second",
                                "status": "success",
                                "final_answer": "done",
                                "ts": "2026-05-28T12:05:01Z",
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            session_root.mkdir(parents=True)
            (session_root / "thread_demo.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "session_id": "thread_demo",
                        "cwd": str(root),
                        "created_at": "2026-05-28T12:00:00Z",
                        "updated_at": "2026-05-28T12:05:02Z",
                        "summary": "1. inspect; 2. refine web layer",
                        "turns": [
                            {
                                "turn_index": 1,
                                "user_message": "Inspect repo",
                                "run_id": "run_first",
                                "status": "success",
                                "final_answer": "done",
                                "trace_path": str(first_trace),
                                "created_at": "2026-05-28T12:00:00Z",
                            },
                            {
                                "turn_index": 2,
                                "user_message": "Only change web layer",
                                "run_id": "run_second",
                                "status": "success",
                                "final_answer": "done",
                                "trace_path": str(second_trace),
                                "created_at": "2026-05-28T12:05:00Z",
                            },
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            client = TestClient(create_app(trace_root=trace_root, workspace_root=root, session_root=session_root))

            threads = client.get("/api/threads")
            thread = client.get("/api/threads/thread_demo")

        self.assertEqual(threads.status_code, 200)
        threads_payload = threads.json()
        self.assertEqual(len(threads_payload["threads"]), 1)
        self.assertEqual(threads_payload["threads"][0]["session_id"], "thread_demo")
        self.assertEqual(threads_payload["threads"][0]["run_count"], 2)
        self.assertEqual(threads_payload["threads"][0]["latest_run_id"], "run_second")

        self.assertEqual(thread.status_code, 200)
        thread_payload = thread.json()["thread"]
        self.assertEqual(thread_payload["session_id"], "thread_demo")
        self.assertEqual(thread_payload["turn_count"], 2)
        self.assertEqual(thread_payload["latest_run_id"], "run_second")
        self.assertEqual(len(thread_payload["runs"]), 2)
        self.assertEqual(thread_payload["runs"][0]["run_id"], "run_second")

    def test_post_run_uses_session_id_and_persists_thread(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("HarnessCoder test repo\n", encoding="utf-8")
            trace_root = root / ".harnesscoder" / "runs"
            session_root = root / ".harnesscoder" / "sessions"
            client = TestClient(create_app(trace_root=trace_root, workspace_root=root, session_root=session_root))

            response = client.post(
                "/api/runs",
                json={
                    "task": "Summarize this repo in one sentence",
                    "model_profile": "scripted",
                    "max_iterations": 4,
                    "notes_mode": "auto",
                    "session_id": "thread_demo",
                },
            )
            self.assertEqual(response.status_code, 202)
            payload = response.json()["run"]
            run_id = payload["run_id"]
            self.assertEqual(payload["session_id"], "thread_demo")

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
            thread = client.get("/api/threads/thread_demo")
            self.assertEqual(thread.status_code, 200)
            thread_payload = thread.json()["thread"]
            self.assertEqual(thread_payload["session_id"], "thread_demo")
            self.assertEqual(thread_payload["turn_count"], 1)
            self.assertEqual(thread_payload["latest_run_id"], run_id)
            self.assertEqual(thread_payload["runs"][0]["session_id"], "thread_demo")

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
