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
    _parse_action_json,
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

    def test_extracts_action_json_after_reasoning_text(self) -> None:
        payload = _parse_action_json(
            "I will inspect the file first.\n"
            '{"kind":"tool","tool_name":"read_file","tool_args":{"path":"app.py"}}'
        )
        action = _model_action_from_payload(payload)

        self.assertEqual(action.kind, "tool")
        self.assertEqual(action.tool_name, "read_file")
        self.assertEqual(action.tool_args, {"path": "app.py"})

    def test_prefers_action_like_json_over_explanatory_json(self) -> None:
        payload = _parse_action_json(
            '{"note":"analysis only"}\n'
            "Now the action:\n"
            '{"kind":"tool","tool_name":"search","query":"def solve"}'
        )
        action = _model_action_from_payload(payload)

        self.assertEqual(action.kind, "tool")
        self.assertEqual(action.tool_name, "search_code")
        self.assertEqual(action.tool_args, {"query": "def solve"})

    def test_accepts_wrapped_next_action_payload(self) -> None:
        action = _model_action_from_payload(
            {
                "next_action": {
                    "action": {
                        "type": "tool",
                        "name": "run_test",
                        "arguments": {"command": "python -m unittest discover"},
                    },
                    "rationale": "Verify the fix.",
                }
            }
        )

        self.assertEqual(action.kind, "tool")
        self.assertEqual(action.tool_name, "run_tests")
        self.assertEqual(action.tool_args, {"cmd": "python -m unittest discover"})

    def test_accepts_type_field_and_string_command_arguments(self) -> None:
        action = _model_action_from_payload(
            {
                "type": "tool",
                "tool": "bash",
                "arguments": "python -m unittest discover",
            }
        )

        self.assertEqual(action.kind, "tool")
        self.assertEqual(action.tool_name, "run_command")
        self.assertEqual(action.tool_args, {"cmd": "python -m unittest discover"})

    def test_accepts_top_level_tool_arguments(self) -> None:
        action = _model_action_from_payload(
            {
                "kind": "edit",
                "path": "app.py",
                "old": "return 1",
                "new": "return 2",
            }
        )

        self.assertEqual(action.kind, "tool")
        self.assertEqual(action.tool_name, "edit_file")
        self.assertEqual(
            action.tool_args,
            {"path": "app.py", "old": "return 1", "new": "return 2"},
        )

    def test_accepts_optional_plan_and_reflection_fields(self) -> None:
        action = _model_action_from_payload(
            {
                "kind": "tool",
                "rationale": "Inspect the file.",
                "tool_name": "read_file",
                "tool_args": {"path": "README.md"},
                "current_step_id": "step_1",
                "thought_summary": "Need the README first.",
                "expected_observation": "README content",
                "reflection": "Starting the first step.",
                "plan_update": {
                    "steps": [
                        {
                            "step_id": "step_1",
                            "title": "Inspect README",
                            "status": "in_progress",
                        }
                    ]
                },
            }
        )

        self.assertEqual(action.current_step_id, "step_1")
        self.assertEqual(action.thought_summary, "Need the README first.")
        self.assertEqual(action.expected_observation, "README content")
        self.assertEqual(action.reflection, "Starting the first step.")
        self.assertEqual(action.plan_update["steps"][0]["title"], "Inspect README")

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

    def test_openai_codex_payload_uses_reasoning_effort(self) -> None:
        state = AgentState(
            run_id="run_test",
            task="Inspect this repo.",
            cwd=".",
            max_iterations=4,
        )
        model = OpenAICodexModel(
            api_key="sk-test",
            model="codex-test",
            base_url="https://example.test/v1",
            reasoning_effort="high",
        )

        payload = model._build_payload(state)
        metadata = model.model_metadata()

        self.assertEqual(payload["reasoning"], {"effort": "high", "summary": "auto"})
        self.assertEqual(metadata["reasoning_effort"], "high")
        self.assertEqual(metadata["effective_reasoning_effort"], "high")

    def test_openai_codex_minimal_reasoning_clamps_to_low(self) -> None:
        state = AgentState(
            run_id="run_test",
            task="Inspect this repo.",
            cwd=".",
            max_iterations=4,
        )
        model = OpenAICodexModel(
            api_key="sk-test",
            model="codex-test",
            base_url="https://example.test/v1",
            reasoning_effort="minimal",
        )

        payload = model._build_payload(state)
        metadata = model.model_metadata()

        self.assertEqual(payload["reasoning"], {"effort": "low", "summary": "auto"})
        self.assertEqual(metadata["reasoning_effort"], "minimal")
        self.assertEqual(metadata["effective_reasoning_effort"], "low")

    def test_openai_codex_none_reasoning_omits_reasoning_payload(self) -> None:
        state = AgentState(
            run_id="run_test",
            task="Inspect this repo.",
            cwd=".",
            max_iterations=4,
        )
        model = OpenAICodexModel(
            api_key="sk-test",
            model="codex-test",
            base_url="https://example.test/v1",
            reasoning_effort="none",
        )

        payload = model._build_payload(state)
        metadata = model.model_metadata()

        self.assertNotIn("reasoning", payload)
        self.assertEqual(metadata["reasoning_effort"], "none")
        self.assertNotIn("effective_reasoning_effort", metadata)

    def test_openai_codex_rejects_unknown_reasoning_effort(self) -> None:
        with self.assertRaises(ValueError):
            OpenAICodexModel(
                api_key="sk-test",
                model="codex-test",
                base_url="https://example.test/v1",
                reasoning_effort="turbo",
            )

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

    def test_pack_context_includes_open_questions_from_memory_block(self) -> None:
        state = AgentState(
            run_id="run_test",
            task="Fix the failing tests.",
            cwd=".",
            max_iterations=4,
        )
        state.memory_blocks["task/open_questions"].value = (
            "fix failing tests from python -m unittest discover"
        )
        state.memory_blocks["task/open_questions"].updated_step = 2

        context = assemble_context(
            state=state,
            system_instructions=MODEL_SYSTEM_PROMPT,
            available_tools=["run_tests"],
            context_pack=build_context_pack(state),
            context_mode="pack",
        )
        payload = context.to_model_input()[1]["content"]

        self.assertIn("open_questions", payload)
        self.assertIn("fix failing tests from python -m unittest discover", payload)

    def test_agent_state_hydrates_open_questions_block_from_legacy_record(self) -> None:
        state = AgentState.from_record(
            {
                "run_id": "run_test",
                "task": "Fix the failing tests.",
                "cwd": ".",
                "max_iterations": 4,
                "open_questions": [
                    " fix failing tests from python -m unittest discover ",
                    "fix failing tests from python -m unittest discover",
                ],
            }
        )

        self.assertEqual(
            state.current_open_questions(),
            ["fix failing tests from python -m unittest discover"],
        )
        self.assertEqual(
            state.memory_blocks["task/open_questions"].value,
            "fix failing tests from python -m unittest discover",
        )
        self.assertEqual(
            state.snapshot()["open_questions"],
            ["fix failing tests from python -m unittest discover"],
        )

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

    def test_context_assembly_injects_session_context(self) -> None:
        state = AgentState(
            run_id="run_test",
            task="Continue the prior task.",
            cwd=".",
            max_iterations=4,
        )
        session_context = {
            "session_id": "interview",
            "turn_count": 1,
            "summary": "1. user='inspect repo'; status=success",
            "recent_turns": [
                {
                    "turn_index": 1,
                    "user_message": "inspect repo",
                    "final_answer": "repo inspected",
                    "status": "success",
                    "run_id": "run_prev",
                }
            ],
        }

        context = assemble_context(
            state=state,
            system_instructions=MODEL_SYSTEM_PROMPT,
            available_tools=["read_file"],
            context_pack=build_context_pack(state),
            context_mode="pack",
            session_context=session_context,
        )
        payload = context.to_model_input()[1]["content"]
        record = context.to_trace_record()

        self.assertIn("session_context", payload)
        self.assertIn("repo inspected", payload)
        self.assertTrue(record["session_context_injected"])
        self.assertEqual(record["session_id"], "interview")

    def test_context_assembly_injects_relevant_notes_and_quality(self) -> None:
        state = AgentState(
            run_id="run_test",
            task="Investigate billing regression.",
            cwd=".",
            max_iterations=4,
        )
        context = assemble_context(
            state=state,
            system_instructions=MODEL_SYSTEM_PROMPT,
            available_tools=["read_file"],
            context_pack=build_context_pack(state),
            context_mode="pack",
            relevant_notes=[
                {
                    "note_id": "note_1",
                    "type": "blocker",
                    "title": "Billing blocker",
                    "content": "Proration test fails.",
                    "tags": ["billing"],
                }
            ],
        )
        payload = context.to_model_input()[1]["content"]
        record = context.to_trace_record()

        self.assertIn("relevant_notes", payload)
        self.assertIn("Billing blocker", payload)
        self.assertEqual(record["relevant_note_count"], 1)
        self.assertIn("context_quality", record)
        self.assertGreaterEqual(record["context_quality"]["score"], 0)

    def test_context_budget_records_section_reductions(self) -> None:
        state = AgentState(
            run_id="run_test",
            task="Inspect this repo.",
            cwd=".",
            max_iterations=4,
        )
        context_pack = build_context_pack(state)
        context_pack["hot_context"]["recent_observations"] = [
            {
                "tool_name": "read_file",
                "ok": True,
                "output": "x" * 2000,
                "error": None,
                "metadata": {"path": f"file_{index}.py"},
            }
            for index in range(8)
        ]

        context = assemble_context(
            state=state,
            system_instructions=MODEL_SYSTEM_PROMPT,
            available_tools=["read_file"],
            context_pack=context_pack,
            context_mode="pack",
        )
        record = context.to_trace_record()
        budget = record["context_budget"]

        self.assertEqual(budget["version"], 2)
        self.assertTrue(budget["sections"]["task_contract"]["preserved"])
        self.assertIn("packed_context", budget["reduced_sections"])
        packed = budget["sections"]["packed_context"]
        self.assertTrue(packed["reduced"])
        self.assertGreater(packed["raw_chars"], packed["chars"])
        self.assertGreaterEqual(budget["dropped_blocks"], 0)
        self.assertEqual(record["context_budget_sections"], budget["sections"])
        self.assertEqual(record["context_dropped_blocks"], budget["dropped_blocks"])

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
        self.assertNotIn("reasoning", payload)
        self.assertNotIn("input", payload)
        self.assertEqual(payload["stream"], False)
        self.assertIn("packed_context", payload["messages"][1]["content"])
        self.assertEqual(model.base_url, "https://api.deepseek.com/v1")

    def test_openai_chat_payload_includes_extra_body(self) -> None:
        state = AgentState(
            run_id="run_test",
            task="Inspect this repo.",
            cwd=".",
            max_iterations=4,
        )
        model = OpenAIChatModel(
            api_key="sk-test",
            model="qwen3-8b",
            base_url="http://127.0.0.1:18000/v1",
            extra_body={
                "chat_template_kwargs": {"enable_thinking": False},
                "secret_token": "should-not-leak",
            },
        )

        payload = model._build_payload(state)
        metadata = model.model_metadata()

        self.assertEqual(
            payload["chat_template_kwargs"],
            {"enable_thinking": False},
        )
        self.assertEqual(payload["secret_token"], "should-not-leak")
        self.assertEqual(
            metadata["extra_body"]["chat_template_kwargs"],
            {"enable_thinking": False},
        )
        self.assertEqual(metadata["extra_body"]["secret_token"], "<redacted>")

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

    def test_extracts_chat_completion_tool_call(self) -> None:
        text = _extract_response_text(
            {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "run_test",
                                        "arguments": '{"command":"python -m unittest"}',
                                    }
                                }
                            ]
                        }
                    }
                ]
            }
        )
        action = _model_action_from_payload(_parse_action_json(text))

        self.assertEqual(action.kind, "tool")
        self.assertEqual(action.tool_name, "run_tests")
        self.assertEqual(action.tool_args, {"cmd": "python -m unittest"})

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

    def test_system_prompt_describes_durable_note_tools(self) -> None:
        prompt = " ".join(MODEL_SYSTEM_PROMPT.split())
        self.assertIn("create_note", prompt)
        self.assertIn("search_notes", prompt)
        self.assertIn("durable task state", prompt)
        self.assertIn("blockers, actions, task_state, decisions, conclusions", prompt)

    def test_model_adapter_errors_have_categories(self) -> None:
        self.assertEqual(_http_error_category(503), "provider_5xx")
        self.assertEqual(_http_error_category(504), "timeout")
        self.assertEqual(_http_error_category(429), "rate_limited")

        with self.assertRaises(ModelAdapterError) as caught:
            _parse_action_json("not json")

        self.assertEqual(caught.exception.category, "action_parse_error")
        self.assertEqual(caught.exception.to_trace_record()["retryable"], False)

if __name__ == "__main__":
    unittest.main()
