from __future__ import annotations

import json
import re
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

from harnesscoder.core.prompt import ContextAssembly
from harnesscoder.core.state import AgentState, ModelAction
from harnesscoder.core.hc_bench_oracle import hc_bench_oracle_action


MODEL_TOOL_NAMES = (
    "read_file",
    "search_code",
    "repo_map",
    "write_file",
    "edit_file",
    "run_tests",
    "run_command",
    "create_note",
    "search_notes",
)
TOOL_NAME_ALIASES = {
    "read": "read_file",
    "readfile": "read_file",
    "read_file": "read_file",
    "search": "search_code",
    "search_code": "search_code",
    "searchcode": "search_code",
    "grep": "search_code",
    "repo_map": "repo_map",
    "repomap": "repo_map",
    "repo-map": "repo_map",
    "write": "write_file",
    "write_file": "write_file",
    "writefile": "write_file",
    "create_file": "write_file",
    "createfile": "write_file",
    "edit": "edit_file",
    "edit_file": "edit_file",
    "editfile": "edit_file",
    "replace": "edit_file",
    "run_test": "run_tests",
    "run_tests": "run_tests",
    "runtests": "run_tests",
    "test": "run_tests",
    "pytest": "run_tests",
    "unittest": "run_tests",
    "run_command": "run_command",
    "runcommand": "run_command",
    "command": "run_command",
    "shell": "run_command",
    "bash": "run_command",
}
TOOL_ARG_KEYS = {
    "read_file": ("path", "offset", "limit"),
    "search_code": ("query", "path"),
    "repo_map": ("query", "max_tokens", "refresh"),
    "write_file": ("path", "content", "overwrite"),
    "edit_file": ("path", "old", "new"),
    "run_tests": ("cmd", "command", "timeout"),
    "run_command": ("cmd", "command", "timeout"),
}
REASONING_EFFORTS = ("minimal", "low", "medium", "high", "xhigh")
REASONING_EFFORT_CHOICES = ("none", *REASONING_EFFORTS)


class ModelAdapter(Protocol):
    name: str

    def next_action(
        self,
        state: AgentState,
        context: ContextAssembly | None = None,
    ) -> ModelAction:
        """Return the next model decision for the current agent state."""


class ModelAdapterError(RuntimeError):
    """Raised when a model adapter cannot produce a valid action."""

    def __init__(
        self,
        message: str,
        *,
        category: str = "adapter_error",
        status_code: int | None = None,
        retryable: bool = False,
        response_excerpt: str | None = None,
        provider_error_type: str | None = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.status_code = status_code
        self.retryable = retryable
        self.response_excerpt = response_excerpt
        self.provider_error_type = provider_error_type

    def to_trace_record(self) -> dict[str, Any]:
        record: dict[str, Any] = {
            "category": self.category,
            "retryable": self.retryable,
        }
        if self.status_code is not None:
            record["status_code"] = self.status_code
        if self.response_excerpt:
            record["response_excerpt"] = self.response_excerpt
        if self.provider_error_type:
            record["provider_error_type"] = self.provider_error_type
        return record


class ScriptedModel:
    """Deterministic fake model used to exercise the runtime loop and trace."""

    name = "scripted"

    def next_action(
        self,
        state: AgentState,
        context: ContextAssembly | None = None,
    ) -> ModelAction:
        if state.latest_observation_for("search_code") is None:
            return ModelAction(
                kind="tool",
                rationale="Find existing project mentions before reading files.",
                tool_name="search_code",
                tool_args={"query": "HarnessCoder", "path": "."},
            )

        if state.latest_observation_for("read_file") is None:
            return ModelAction(
                kind="tool",
                rationale="Read the README to understand the repo contract.",
                tool_name="read_file",
                tool_args={"path": "README.md", "offset": 0, "limit": 160},
            )

        if state.latest_observation_for("run_command") is None:
            return ModelAction(
                kind="tool",
                rationale="List files to confirm the current project shape.",
                tool_name="run_command",
                tool_args={
                    "cmd": "find . -maxdepth 3 -type f -not -path ./.harnesscoder/* -not -path */__pycache__/*",
                    "timeout": 10,
                },
            )

        return ModelAction(
            kind="finish",
            rationale="Enough local context has been gathered for a short answer.",
            content=self._summarize(state),
        )

    def _summarize(self, state: AgentState) -> str:
        readme = state.latest_observation_for("read_file")
        file_list = state.latest_observation_for("run_command")
        search = state.latest_observation_for("search_code")

        parts = [
            "HarnessCoder appears to be a local event-sourced coding agent harness.",
            "Its current MVP focuses on a controllable agent loop, policy-gated tools, and JSONL traces.",
        ]
        if search and search.output:
            parts.append("The repo contains HarnessCoder references in the project files.")
        if readme and readme.ok:
            parts.append("README.md describes why the agent loop is dynamic instead of DAG-shaped.")
        if file_list and file_list.output:
            files = ", ".join(
                line.removeprefix("./") for line in file_list.output.splitlines()[:8]
            )
            parts.append(f"Current files include: {files}.")
        return " ".join(parts)


class HCBenchOracleModel:
    """Deterministic model for exercising the local HC-Bench fixture suite.

    The oracle is intentionally boring: it is a stable local baseline that proves
    the eval harness, policy layer, traces, and reports work across all cases.
    Real model profiles can then run the same cases for capability comparison.
    """

    name = "hc-bench-oracle"

    def next_action(
        self,
        state: AgentState,
        context: ContextAssembly | None = None,
    ) -> ModelAction:
        action = hc_bench_oracle_action(state)
        if action is not None:
            return action
        return ScriptedModel().next_action(state, context)


@dataclass(slots=True)
class OpenAICodexModel:
    """OpenAI-compatible Responses API adapter for Codex-style model decisions."""

    api_key: str
    model: str
    base_url: str = "https://api.openai.com/v1"
    timeout: int = 60
    max_output_tokens: int = 1200
    reasoning_effort: str | None = None
    name: str = "openai-codex"

    def __post_init__(self) -> None:
        self.base_url = _normalize_openai_base_url(self.base_url)
        self.reasoning_effort = normalize_reasoning_effort(self.reasoning_effort)

    def next_action(
        self,
        state: AgentState,
        context: ContextAssembly | None = None,
    ) -> ModelAction:
        response = self._post_responses(self._build_payload(state, context))
        text = _extract_response_text(response)
        action_payload = _parse_action_json(text)
        return _model_action_from_payload(action_payload)

    def _build_payload(
        self,
        state: AgentState,
        context: ContextAssembly | None = None,
    ) -> dict[str, Any]:
        input_messages = (
            context.to_model_input()
            if context is not None
            else [
                {"role": "system", "content": MODEL_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(_state_view(state), ensure_ascii=False),
                },
            ]
        )
        payload = {
            "model": self.model,
            "input": input_messages,
            "temperature": 0,
            "max_output_tokens": self.max_output_tokens,
        }
        reasoning = reasoning_payload_for_responses(self.reasoning_effort)
        if reasoning is not None:
            payload["reasoning"] = reasoning
        return payload

    def _post_responses(self, payload: dict[str, Any]) -> dict[str, Any]:
        return _post_json(
            url=f"{self.base_url}/responses",
            payload=payload,
            api_key=self.api_key,
            timeout=self.timeout,
        )

    def model_metadata(self) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "provider": self.name,
            "model": self.model,
            "base_url": self.base_url,
            "max_output_tokens": self.max_output_tokens,
        }
        if self.reasoning_effort is not None:
            metadata["reasoning_effort"] = self.reasoning_effort
            effective = effective_responses_reasoning_effort(self.reasoning_effort)
            if effective is not None:
                metadata["effective_reasoning_effort"] = effective
        return metadata


@dataclass(slots=True)
class OpenAIChatModel:
    """OpenAI-compatible Chat Completions adapter for model decisions."""

    api_key: str
    model: str
    base_url: str = "https://api.openai.com/v1"
    timeout: int = 60
    max_output_tokens: int = 1200
    extra_body: dict[str, Any] | None = None
    name: str = "openai-chat"

    def __post_init__(self) -> None:
        self.base_url = _normalize_openai_base_url(self.base_url)

    def next_action(
        self,
        state: AgentState,
        context: ContextAssembly | None = None,
    ) -> ModelAction:
        response = self._post_chat_completions(self._build_payload(state, context))
        text = _extract_response_text(response)
        action_payload = _parse_action_json(text)
        return _model_action_from_payload(action_payload)

    def _build_payload(
        self,
        state: AgentState,
        context: ContextAssembly | None = None,
    ) -> dict[str, Any]:
        messages = (
            context.to_model_input()
            if context is not None
            else [
                {"role": "system", "content": MODEL_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(_state_view(state), ensure_ascii=False),
                },
            ]
        )
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": self.max_output_tokens,
            "stream": False,
        }
        if self.extra_body:
            payload.update(self.extra_body)
        return payload

    def _post_chat_completions(self, payload: dict[str, Any]) -> dict[str, Any]:
        return _post_json(
            url=f"{self.base_url}/chat/completions",
            payload=payload,
            api_key=self.api_key,
            timeout=self.timeout,
        )

    def model_metadata(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "model": self.model,
            "base_url": self.base_url,
            "max_output_tokens": self.max_output_tokens,
            "extra_body": _safe_metadata(self.extra_body) if self.extra_body else {},
        }


MODEL_SYSTEM_PROMPT = """You are the model-decision layer inside HarnessCoder.
HarnessCoder is a local coding-agent harness. You do not directly access files,
run commands, or edit code. You choose the next action for the runtime.

Return exactly one JSON object and no Markdown.

Allowed tool action:
{
  "kind": "tool",
  "rationale": "why this tool call is the next useful step",
  "tool_name": "read_file | search_code | repo_map | write_file | edit_file | run_tests | run_command",
  "tool_args": {},
  "thought_summary": "brief non-sensitive reasoning summary",
  "current_step_id": "step identifier from the current plan",
  "expected_observation": "what this tool call should tell you",
  "reflection": "optional short reflection on the last observation",
  "plan_update": {
    "steps": [{"step_id": "step_1", "title": "inspect tests", "status": "in_progress"}]
  }
}

Allowed finish action:
{
  "kind": "finish",
  "rationale": "why enough information has been gathered",
  "content": "final answer to the user",
  "reflection": "optional short reflection on what resolved the task"
}

Use only tools listed in the current task's available_tools.

Finish discipline:
- If the relevant tests pass and no further edit is needed, emit finish
  immediately.
- Do not run extra exploratory tools after a targeted verification passes unless
  the latest result shows a real unresolved failure.
- Full-suite failures may be unrelated in benchmark fixtures; after the targeted
  case test passes, summarize unrelated failures in finish instead of looping.
- When remaining budget is low, prefer finish over redundant reads or repeated
  test commands.

Tool schemas:
- read_file(path: string, offset: int = 0, limit: int = 200)
- search_code(query: string, path: string = ".")
- repo_map(query: string | null = null, max_tokens: int = 1200, refresh: boolean = false)
- write_file(path: string, content: string, overwrite: boolean = false)
- edit_file(path: string, old: string, new: string)
- run_tests(cmd: string | null = null, timeout: int = 60)
- run_command(cmd: string, timeout: int = 30)
- create_note(title: string, content: string, note_type: string = "general", tags: string[] = [])
- search_notes(query: string, limit: int = 5, note_type: string | null = null)

Use write_file for new files in greenfield tasks. Use edit_file only for exact
replacements where old is expected to match once. Prefer run_tests for local
python/pytest/unittest test execution. Reserve run_command for repository
inspection and other policy-allowed commands. The policy layer may deny unsafe
commands. Use create_note only for durable task state that should survive the
current run: blockers, actions, task_state, decisions, conclusions, or verified
facts. Use search_notes when continuing long-running codebase work and prior
blockers, task state, decisions, or verified facts may affect the next action.
Answer in the user's language when finishing."""


def _normalize_openai_base_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if not normalized.endswith("/v1"):
        normalized = f"{normalized}/v1"
    return normalized


def normalize_reasoning_effort(effort: str | None) -> str | None:
    if effort is None:
        return None
    normalized = effort.strip().lower()
    if not normalized:
        return None
    if normalized not in REASONING_EFFORT_CHOICES:
        valid = ", ".join(REASONING_EFFORT_CHOICES)
        raise ValueError(f"reasoning_effort must be one of: {valid}")
    return normalized


def effective_responses_reasoning_effort(effort: str | None) -> str | None:
    normalized = normalize_reasoning_effort(effort)
    if normalized is None or normalized == "none":
        return None
    if normalized == "minimal":
        return "low"
    return normalized


def reasoning_payload_for_responses(effort: str | None) -> dict[str, str] | None:
    effective = effective_responses_reasoning_effort(effort)
    if effective is None:
        return None
    return {"effort": effective, "summary": "auto"}


def _safe_metadata(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): ("<redacted>" if _looks_secret(str(key)) else _safe_metadata(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_safe_metadata(item) for item in value]
    if isinstance(value, tuple):
        return [_safe_metadata(item) for item in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)


def _looks_secret(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in ("api_key", "apikey", "secret", "token"))


def _post_json(
    *,
    url: str,
    payload: dict[str, Any],
    api_key: str,
    timeout: int,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url=url,
        method="POST",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "HarnessCoder/0.1",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw_body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        excerpt = _clip(error_body, 2000)
        raise ModelAdapterError(
            f"model API returned HTTP {exc.code}: {excerpt}",
            category=_http_error_category(exc.code),
            status_code=exc.code,
            retryable=_http_error_retryable(exc.code),
            response_excerpt=excerpt,
            provider_error_type=_provider_error_type(error_body),
        ) from exc
    except urllib.error.URLError as exc:
        raise ModelAdapterError(
            f"model API request failed: {exc}",
            category="connection_error",
            retryable=True,
        ) from exc
    except (TimeoutError, socket.timeout) as exc:
        raise ModelAdapterError(
            f"model API request timed out: {exc}",
            category="timeout",
            retryable=True,
        ) from exc

    try:
        parsed = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        excerpt = _clip(raw_body, 2000)
        raise ModelAdapterError(
            f"model API returned non-JSON response: {excerpt}",
            category="invalid_json_response",
            retryable=True,
            response_excerpt=excerpt,
        ) from exc
    if not isinstance(parsed, dict):
        raise ModelAdapterError(
            "model API response must be a JSON object",
            category="invalid_json_response",
        )
    return parsed


def _state_view(state: AgentState) -> dict[str, Any]:
    return {
        "task": state.task,
        "cwd": state.cwd,
        "iterations": state.iterations,
        "max_iterations": state.max_iterations,
        "available_tools": list(MODEL_TOOL_NAMES),
        "recent_observations": [
            {
                "tool_name": observation.tool_name,
                "ok": observation.ok,
                "output": observation.short_output(4000),
                "error": observation.error,
                "metadata": observation.metadata,
            }
            for observation in state.observations[-8:]
        ],
    }


def _extract_response_text(response: dict[str, Any]) -> str:
    output_text = response.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text

    output_parts: list[str] = []
    for item in response.get("output", []):
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []):
            if not isinstance(content, dict):
                continue
            text = content.get("text")
            if isinstance(text, str):
                output_parts.append(text)

    if output_parts:
        return "\n".join(output_parts)

    choices = response.get("choices", [])
    if choices and isinstance(choices[0], dict):
        message = choices[0].get("message", {})
        if isinstance(message, dict):
            tool_call_text = _text_from_chat_tool_call(message)
            if tool_call_text is not None:
                return tool_call_text
            content = message.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                text = _text_from_content_blocks(content)
                if text:
                    return text

    raise ModelAdapterError(
        "model API response did not include text output",
        category="missing_text_output",
    )


def _parse_action_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    candidates = _action_json_candidates(stripped)
    for candidate in candidates:
        if _looks_like_action_payload(candidate):
            return candidate
    if candidates:
        return candidates[0]
    raise ModelAdapterError(
        f"model did not return valid action JSON: {text}",
        category="action_parse_error",
        response_excerpt=_clip(text, 2000),
    )


def _model_action_from_payload(payload: dict[str, Any]) -> ModelAction:
    payload = _normalize_action_payload(_unwrap_action_payload(payload))
    kind = payload.get("kind")
    rationale = payload.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        rationale = "Model did not provide a rationale."
    thought_summary = _optional_payload_string(payload.get("thought_summary"))
    current_step_id = _optional_payload_string(payload.get("current_step_id"))
    expected_observation = _optional_payload_string(payload.get("expected_observation"))
    reflection = _optional_payload_string(payload.get("reflection"))
    plan_update = payload.get("plan_update")
    if plan_update is not None and not isinstance(plan_update, dict):
        raise ModelAdapterError(
            "plan_update must be an object when provided",
            category="action_schema_error",
        )

    if kind == "finish":
        content = payload.get("content") or payload.get("final_answer") or ""
        if not isinstance(content, str):
            raise ModelAdapterError(
                "finish action content must be a string",
                category="action_schema_error",
            )
        return ModelAction(
            kind="finish",
            rationale=rationale,
            content=content,
            thought_summary=thought_summary,
            current_step_id=current_step_id,
            expected_observation=expected_observation,
            reflection=reflection,
            plan_update=dict(plan_update) if isinstance(plan_update, dict) else None,
        )

    if kind == "tool":
        tool_name = payload.get("tool_name")
        tool_args = payload.get("tool_args", {})
        if not isinstance(tool_name, str):
            raise ModelAdapterError("tool action must include string tool_name")
        if tool_name not in MODEL_TOOL_NAMES:
            raise ModelAdapterError(f"tool action requested unknown tool: {tool_name}")
        if not isinstance(tool_args, dict):
            raise ModelAdapterError("tool action tool_args must be an object")
        return ModelAction(
            kind="tool",
            rationale=rationale,
            tool_name=tool_name,
            tool_args=tool_args,
            thought_summary=thought_summary,
            current_step_id=current_step_id,
            expected_observation=expected_observation,
            reflection=reflection,
            plan_update=dict(plan_update) if isinstance(plan_update, dict) else None,
        )

    raise ModelAdapterError("model action kind must be either 'tool' or 'finish'")


def _normalize_action_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    raw_kind = normalized.get("kind")
    raw_action = normalized.get("action")

    if not isinstance(raw_kind, str) or not raw_kind.strip():
        raw_kind = raw_action if isinstance(raw_action, str) else normalized.get("type")
    kind = raw_kind.strip().lower() if isinstance(raw_kind, str) else None

    if isinstance(kind, str):
        kind = _normalize_tool_name(kind) or kind

    if kind in MODEL_TOOL_NAMES:
        normalized["kind"] = "tool"
        normalized.setdefault("tool_name", kind)
    elif kind in {"tool", "tool_call", "call_tool", "use_tool"}:
        normalized["kind"] = "tool"
    elif kind in {"finish", "final", "answer", "done", "complete", "completed"}:
        normalized["kind"] = "finish"

    if "tool_name" not in normalized:
        for key in ("tool", "name"):
            value = normalized.get(key)
            if isinstance(value, str) and value.strip():
                normalized["tool_name"] = value.strip()
                break
    if isinstance(normalized.get("tool_name"), str):
        normalized["tool_name"] = _normalize_tool_name(str(normalized["tool_name"]))

    tool_args = normalized.get("tool_args")
    if not isinstance(tool_args, dict):
        for key in ("args", "arguments", "parameters", "input"):
            value = normalized.get(key)
            if isinstance(value, dict):
                normalized["tool_args"] = value
                break
            if isinstance(value, str):
                parsed_value = _parse_argument_object(value)
                if parsed_value is not None:
                    normalized["tool_args"] = parsed_value
                    break
                parsed_value = _parse_argument_string(
                    normalized.get("tool_name"),
                    value,
                )
                if parsed_value is not None:
                    normalized["tool_args"] = parsed_value
                    break

    if normalized.get("kind") is None and isinstance(normalized.get("tool_name"), str):
        normalized["kind"] = "tool"

    if normalized.get("kind") == "tool":
        normalized["tool_args"] = _fill_tool_args_from_top_level(normalized)

    if normalized.get("kind") == "finish" and "content" not in normalized:
        for key in ("final_answer", "answer", "message", "summary", "result"):
            value = normalized.get(key)
            if isinstance(value, str):
                normalized["content"] = value
                break

    return normalized


def _text_from_chat_tool_call(message: dict[str, Any]) -> str | None:
    tool_calls = message.get("tool_calls")
    if not isinstance(tool_calls, list) or not tool_calls:
        return None
    first = tool_calls[0]
    if not isinstance(first, dict):
        return None
    function = first.get("function")
    if not isinstance(function, dict):
        return None
    name = function.get("name")
    arguments = function.get("arguments")
    payload = {
        "kind": "tool",
        "tool_name": name,
        "tool_args": _parse_argument_object(arguments)
        if isinstance(arguments, str)
        else arguments,
    }
    return json.dumps(payload, ensure_ascii=False)


def _text_from_content_blocks(content: list[Any]) -> str:
    parts = []
    for block in content:
        if not isinstance(block, dict):
            continue
        text = block.get("text") or block.get("content")
        if isinstance(text, str):
            parts.append(text)
    return "\n".join(parts)


def _action_json_candidates(text: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    decoder = json.JSONDecoder()

    for fenced in re.finditer(r"```(?:json|JSON)?\s*(.*?)\s*```", text, flags=re.DOTALL):
        _append_json_candidate(candidates, seen, fenced.group(1).strip(), decoder)

    _append_json_candidate(candidates, seen, text, decoder)
    for index, char in enumerate(text):
        if char != "{":
            continue
        _append_json_candidate(candidates, seen, text[index:], decoder)
    return candidates


def _append_json_candidate(
    candidates: list[dict[str, Any]],
    seen: set[str],
    text: str,
    decoder: json.JSONDecoder,
) -> None:
    if not text:
        return
    try:
        parsed, _ = decoder.raw_decode(text)
    except json.JSONDecodeError:
        return
    if not isinstance(parsed, dict):
        return
    key = json.dumps(parsed, ensure_ascii=False, sort_keys=True)
    if key in seen:
        return
    candidates.append(parsed)
    seen.add(key)


def _unwrap_action_payload(payload: dict[str, Any]) -> dict[str, Any]:
    for key in ("next_action", "model_action", "decision", "response"):
        value = payload.get(key)
        if isinstance(value, dict):
            return _unwrap_action_payload(value)

    action = payload.get("action")
    if isinstance(action, dict):
        merged = dict(action)
        if "rationale" not in merged and isinstance(payload.get("rationale"), str):
            merged["rationale"] = payload["rationale"]
        return _unwrap_action_payload(merged)

    function_call = payload.get("function_call")
    if isinstance(function_call, dict):
        return _function_call_payload(function_call, payload)

    tool_calls = payload.get("tool_calls")
    if isinstance(tool_calls, list) and tool_calls:
        first = tool_calls[0]
        if isinstance(first, dict):
            function = first.get("function")
            if isinstance(function, dict):
                return _function_call_payload(function, payload)
    return payload


def _function_call_payload(function: dict[str, Any], parent: dict[str, Any]) -> dict[str, Any]:
    arguments = function.get("arguments")
    return {
        "kind": "tool",
        "tool_name": function.get("name"),
        "tool_args": (
            _parse_argument_object(arguments)
            if isinstance(arguments, str)
            else arguments
        ),
        "rationale": parent.get("rationale") or parent.get("reasoning") or "Tool call response.",
    }


def _looks_like_action_payload(payload: dict[str, Any]) -> bool:
    normalized = _normalize_action_payload(_unwrap_action_payload(payload))
    kind = normalized.get("kind")
    if kind == "finish":
        return True
    return kind == "tool" and normalized.get("tool_name") in MODEL_TOOL_NAMES


def _normalize_tool_name(value: str) -> str:
    key = value.strip().lower().replace("-", "_").replace(" ", "_")
    return TOOL_NAME_ALIASES.get(key, key)


def _parse_argument_object(value: str) -> dict[str, Any] | None:
    stripped = value.strip()
    if not stripped:
        return {}
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _parse_argument_string(tool_name: Any, value: str) -> dict[str, Any] | None:
    if tool_name not in {"run_tests", "run_command"}:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return {"cmd": stripped}


def _fill_tool_args_from_top_level(payload: dict[str, Any]) -> dict[str, Any]:
    tool_args = payload.get("tool_args")
    tool_name = payload.get("tool_name")
    if not isinstance(tool_name, str):
        return {} if not isinstance(tool_args, dict) else tool_args
    args = dict(tool_args) if isinstance(tool_args, dict) else {}
    for key in TOOL_ARG_KEYS.get(tool_name, ()):
        if key in payload:
            target_key = "cmd" if key == "command" else key
            args[target_key] = payload[key]
    if tool_name in {"run_tests", "run_command"} and "cmd" not in args:
        command = args.get("command")
        if isinstance(command, str):
            args["cmd"] = command
            args.pop("command", None)
    return args


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}... [truncated {len(text) - limit} chars]"


def _optional_payload_string(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ModelAdapterError(
            "optional action text fields must be strings",
            category="action_schema_error",
        )
    stripped = value.strip()
    return stripped or None


def _http_error_category(status_code: int) -> str:
    if status_code == 429:
        return "rate_limited"
    if status_code in {408, 504}:
        return "timeout"
    if 500 <= status_code <= 599:
        return "provider_5xx"
    if 400 <= status_code <= 499:
        return "provider_4xx"
    return "http_error"


def _http_error_retryable(status_code: int) -> bool:
    return status_code == 429 or status_code in {408, 409, 425} or 500 <= status_code <= 599


def _provider_error_type(body: str) -> str | None:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    error = payload.get("error")
    if not isinstance(error, dict):
        return None
    value = error.get("type")
    return value if isinstance(value, str) and value else None
