import unittest
from pathlib import Path

from security_extra import build_checkout_command, redact_headers


class SecurityExtraTests(unittest.TestCase):
    def test_redact_secret_headers(self):
        redacted = redact_headers({
            "Authorization": "Bearer secret",
            "x-api-key": "secret-key",
            "Content-Type": "application/json",
        })
        self.assertEqual(redacted["Authorization"], "<redacted>")
        self.assertEqual(redacted["x-api-key"], "<redacted>")
        self.assertEqual(redacted["Content-Type"], "application/json")

    def test_checkout_command_returns_argv(self):
        command = build_checkout_command("feature; touch hacked")
        self.assertIsInstance(command, list)
        self.assertEqual(command[:2], ["git", "checkout"])
        self.assertNotIn(";", command[2])

    def test_no_download_side_effect(self):
        self.assertFalse(Path("payload.sh").exists())


if __name__ == "__main__":
    unittest.main()
