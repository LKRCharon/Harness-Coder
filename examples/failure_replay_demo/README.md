# Failure Replay Demo

This fixture shows the smallest 0.3.0 failure replay story:

1. The agent applies a plausible edit.
2. The test command runs and fails.
3. A normalized `test_result` records the failure.
4. The replay report classifies the run as `test_failed` and exposes metrics.

Files:

- `synthetic_trace.jsonl`: trace evidence for the failing run.
- `replay_report.json`: minimal replay summary produced from that evidence.

The fixture is synthetic so it can be used in tests without third-party
dependencies or a live model provider.
