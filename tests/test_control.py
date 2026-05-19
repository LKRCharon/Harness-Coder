from __future__ import annotations

import unittest

from harnesscoder.core.control import (
    ACTIVE_RUN_READ_ONLY_COMMANDS,
    RunControlPlane,
    normalize_slash_command,
)


class RunControlPlaneTests(unittest.TestCase):
    def test_start_run_blocks_when_active_run_exists(self) -> None:
        decision = RunControlPlane().start_run(active_run=True)

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.status, "run blocked: active run")
        self.assertEqual(decision.reason, "active_run")

    def test_exit_blocks_when_active_run_exists(self) -> None:
        decision = RunControlPlane().request_exit(active_run=True)

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.status, "exit blocked: active run")
        self.assertIn("Cancellation is not implemented yet", decision.message)

    def test_active_run_allows_read_only_slash_commands(self) -> None:
        control = RunControlPlane()

        for command in ACTIVE_RUN_READ_ONLY_COMMANDS:
            with self.subTest(command=command):
                self.assertTrue(
                    control.slash_command(command, active_run=True).allowed
                )

    def test_active_run_blocks_mutating_slash_command(self) -> None:
        decision = RunControlPlane().slash_command("/edit", active_run=True)

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.status, "/edit blocked: active run")
        self.assertIn("/status", decision.message)
        self.assertIn("/trace", decision.message)

    def test_slash_command_allowed_when_idle(self) -> None:
        decision = RunControlPlane().slash_command("/edit", active_run=False)

        self.assertTrue(decision.allowed)

    def test_normalize_slash_command(self) -> None:
        self.assertEqual(normalize_slash_command("/status"), "status")
        self.assertEqual(normalize_slash_command("status"), "status")


if __name__ == "__main__":
    unittest.main()
