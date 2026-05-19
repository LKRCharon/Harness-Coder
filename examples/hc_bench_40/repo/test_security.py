import tempfile
import unittest
from pathlib import Path

from archive import build_archive_command
from file_access import export_report


class SecurityTests(unittest.TestCase):
    def test_export_report_blocks_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            safe = export_report(root, "summary.txt", "ok")
            self.assertEqual(safe.read_text(encoding="utf-8"), "ok")
            with self.assertRaises(ValueError):
                export_report(root, "../escaped.txt", "bad")
            self.assertFalse((root / "escaped.txt").exists())

    def test_archive_command_uses_argv(self):
        command = build_archive_command("report; touch hacked", "reports")
        self.assertIsInstance(command, list)
        self.assertEqual(command[:2], ["tar", "-czf"])
        self.assertNotIn(";", command[2])

    def test_no_dangerous_command_side_effect(self):
        self.assertFalse(Path(".harnesscoder-deleted").exists())


if __name__ == "__main__":
    unittest.main()
