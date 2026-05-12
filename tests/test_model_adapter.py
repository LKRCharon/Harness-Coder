from __future__ import annotations

import unittest

from harnesscoder.core.models import _model_action_from_payload


class ModelAdapterNormalizationTests(unittest.TestCase):
    def test_accepts_tool_name_as_kind(self) -> None:
        action = _model_action_from_payload(
            {
                "kind": "read_file",
                "rationale": "Inspect the file named in the failure.",
                "args": {"path": "math_utils.py"},
            }
        )

        self.assertEqual(action.kind, "tool")
        self.assertEqual(action.tool_name, "read_file")
        self.assertEqual(action.tool_args, {"path": "math_utils.py"})

    def test_accepts_tool_action_with_arguments_alias(self) -> None:
        action = _model_action_from_payload(
            {
                "action": "tool_call",
                "tool": "run_tests",
                "arguments": {"cmd": "python -m unittest discover"},
            }
        )

        self.assertEqual(action.kind, "tool")
        self.assertEqual(action.tool_name, "run_tests")
        self.assertEqual(action.tool_args, {"cmd": "python -m unittest discover"})

    def test_accepts_done_as_finish_alias(self) -> None:
        action = _model_action_from_payload(
            {"kind": "done", "summary": "All tests pass."}
        )

        self.assertEqual(action.kind, "finish")
        self.assertEqual(action.content, "All tests pass.")


if __name__ == "__main__":
    unittest.main()
