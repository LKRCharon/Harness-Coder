from __future__ import annotations

import unittest

from harnesscoder.core.hc_bench_oracle import hc_bench_oracle_action
from harnesscoder.core.context import build_context_pack
from harnesscoder.core.models import (
    MODEL_SYSTEM_PROMPT,
    MODEL_TOOL_NAMES,
    OpenAIChatModel,
    OpenAICodexModel,
    _extract_response_text,
    _model_action_from_payload,
)
from harnesscoder.core.prompt import assemble_context
from harnesscoder.core.state import AgentState, ToolObservation


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

    def test_hc_bench_oracle_reads_case_id_from_task(self) -> None:
        state = AgentState(
            run_id="run_test",
            task="[HC-Bench case: greenfield-slugify] Create slugify.",
            cwd=".",
            max_iterations=8,
        )

        action = hc_bench_oracle_action(state)

        self.assertIsNotNone(action)
        assert action is not None
        self.assertEqual(action.kind, "tool")
        self.assertEqual(action.tool_name, "write_file")

    def test_openai_payload_uses_context_assembly(self) -> None:
        state = AgentState(
            run_id="run_test",
            task="Inspect this repo.",
            cwd=".",
            max_iterations=4,
        )
        state.file_summaries["README.md"] = "README.md: project overview"
        context_pack = build_context_pack(state)
        context = assemble_context(
            state=state,
            system_instructions=MODEL_SYSTEM_PROMPT,
            available_tools=["read_file"],
            context_pack=context_pack,
            context_mode="pack",
        )
        model = OpenAICodexModel(
            api_key="sk-test",
            model="codex-test",
            base_url="https://example.test/v1",
        )

        payload = model._build_payload(state, context)
        user_content = payload["input"][1]["content"]

        self.assertIn("packed_context", user_content)
        self.assertIn("README.md: project overview", user_content)
        self.assertEqual(context.context_injected, True)
        self.assertGreater(context.estimated_tokens, 0)

    def test_memory_context_renders_working_memory(self) -> None:
        state = AgentState(
            run_id="run_test",
            task="Fix tests.",
            cwd=".",
            max_iterations=4,
        )
        state.memory_blocks["task/verified_facts"].value = "tests passed once"
        state.memory_blocks["task/verified_facts"].updated_step = 2

        context = assemble_context(
            state=state,
            system_instructions=MODEL_SYSTEM_PROMPT,
            available_tools=["run_tests"],
            context_pack=build_context_pack(state),
            context_mode="memory",
        )

        assert context.working_memory is not None
        self.assertIn("<working_memory>", context.working_memory)
        self.assertIn("task/verified_facts", context.working_memory)
        self.assertIn("tests passed once", context.working_memory)

    def test_pack_context_does_not_duplicate_recent_observations(self) -> None:
        state = AgentState(
            run_id="run_test",
            task="Inspect this repo.",
            cwd=".",
            max_iterations=4,
        )
        state.observations.append(
            ToolObservation(
                call_id="call_1",
                tool_name="read_file",
                ok=True,
                output="important output",
                metadata={"path": "README.md"},
            )
        )

        context = assemble_context(
            state=state,
            system_instructions=MODEL_SYSTEM_PROMPT,
            available_tools=["read_file"],
            context_pack=build_context_pack(state),
            context_mode="pack",
        )
        payload = context.to_model_input()[1]["content"]

        self.assertIn("important output", payload)
        self.assertEqual(payload.count("important output"), 1)

    def test_context_assembly_records_prompt_cache_fingerprints(self) -> None:
        state = AgentState(
            run_id="run_test",
            task="Inspect this repo.",
            cwd=".",
            max_iterations=4,
        )

        context = assemble_context(
            state=state,
            system_instructions=MODEL_SYSTEM_PROMPT,
            available_tools=["read_file", "run_tests"],
            context_pack=build_context_pack(state),
            context_mode="pack",
        )
        record = context.to_trace_record()

        self.assertIn("stable_prefix_hash", record["prompt_fingerprint"])
        self.assertIn("tool_schema_hash", record["prompt_fingerprint"])
        self.assertGreater(record["prompt_sections"]["stable_prefix_tokens"], 0)
        self.assertEqual(
            record["stable_prefix_tokens"],
            record["prompt_sections"]["stable_prefix_tokens"],
        )

    def test_prompt_cache_fingerprint_changes_when_tool_order_changes(self) -> None:
        state = AgentState(
            run_id="run_test",
            task="Inspect this repo.",
            cwd=".",
            max_iterations=4,
        )
        first = assemble_context(
            state=state,
            system_instructions=MODEL_SYSTEM_PROMPT,
            available_tools=["read_file", "run_tests"],
            context_pack=build_context_pack(state),
            context_mode="pack",
        )
        second = assemble_context(
            state=state,
            system_instructions=MODEL_SYSTEM_PROMPT,
            available_tools=["run_tests", "read_file"],
            context_pack=build_context_pack(state),
            context_mode="pack",
        )

        self.assertNotEqual(
            first.prompt_fingerprint["stable_prefix_hash"],
            second.prompt_fingerprint["stable_prefix_hash"],
        )

    def test_openai_chat_payload_uses_chat_completions_shape(self) -> None:
        state = AgentState(
            run_id="run_test",
            task="Inspect this repo.",
            cwd=".",
            max_iterations=4,
        )
        context = assemble_context(
            state=state,
            system_instructions=MODEL_SYSTEM_PROMPT,
            available_tools=["read_file"],
            context_pack=build_context_pack(state),
            context_mode="pack",
        )
        model = OpenAIChatModel(
            api_key="sk-test",
            model="deepseek-v4-pro",
            base_url="https://api.deepseek.com",
        )

        payload = model._build_payload(state, context)

        self.assertEqual(payload["model"], "deepseek-v4-pro")
        self.assertIn("messages", payload)
        self.assertNotIn("input", payload)
        self.assertEqual(payload["stream"], False)
        self.assertIn("packed_context", payload["messages"][1]["content"])
        self.assertEqual(model.base_url, "https://api.deepseek.com/v1")

    def test_extracts_chat_completion_text(self) -> None:
        text = _extract_response_text(
            {
                "choices": [
                    {
                        "message": {
                            "content": '{"kind":"finish","content":"done"}'
                        }
                    }
                ]
            }
        )

        self.assertIn('"kind":"finish"', text)

    def test_system_prompt_lists_every_runtime_tool(self) -> None:
        for tool_name in MODEL_TOOL_NAMES:
            self.assertIn(tool_name, MODEL_SYSTEM_PROMPT)

    def test_system_prompt_tells_models_when_to_finish(self) -> None:
        prompt = " ".join(MODEL_SYSTEM_PROMPT.split())
        self.assertIn("If the relevant tests pass", prompt)
        self.assertIn("emit finish immediately", prompt)
        self.assertIn("targeted verification passes", prompt)
        self.assertIn("Full-suite failures may be unrelated", prompt)
        self.assertIn("remaining budget is low", prompt)


if __name__ == "__main__":
    unittest.main()
