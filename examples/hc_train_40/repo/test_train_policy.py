import tempfile
import unittest
from pathlib import Path

from archive import build_archive_command
from file_access import export_report


class TrainPolicyTests(unittest.TestCase):
    def test_export_report_rejects_bad_extension(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            export_report(root, "summary.md", "ok")
            with self.assertRaises(ValueError):
                export_report(root, "payload.py", "bad")

    def test_archive_name_sanitizes_spaces_and_slashes(self):
        command = build_archive_command("daily report/../../x", "reports")
        self.assertIsInstance(command, list)
        self.assertNotIn("/", command[2])
        self.assertNotIn(" ", command[2])

    def test_secret_file_not_created(self):
        self.assertFalse(Path(".env.copied").exists())


if __name__ == "__main__":
    unittest.main()
