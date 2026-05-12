from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

from harnesscoder.core.state import AgentState, ModelAction
from harnesscoder.core.hc_bench_oracle import hc_bench_oracle_action


MODEL_TOOL_NAMES = (
    "read_file",
    "search_code",
    "write_file",
    "edit_file",
    "run_tests",
    "run_command",
)


class ModelAdapter(Protocol):
    name: str

    def next_action(self, state: AgentState) -> ModelAction:
        """Return the next model decision for the current agent state."""


class ModelAdapterError(RuntimeError):
    """Raised when a model adapter cannot produce a valid action."""


class ScriptedModel:
    """Deterministic fake model used to exercise the runtime loop and trace."""

    name = "scripted"

    def next_action(self, state: AgentState) -> ModelAction:
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

    def next_action(self, state: AgentState) -> ModelAction:
        action = hc_bench_oracle_action(state)
        if action is not None:
            return action
        return ScriptedModel().next_action(state)


@dataclass(slots=True)
class OpenAICodexModel:
    """OpenAI-compatible Responses API adapter for Codex-style model decisions."""

    api_key: str
    model: str
    base_url: str = "https://api.openai.com/v1"
    timeout: int = 60
    max_output_tokens: int = 1200
    name: str = "openai-codex"

    def __post_init__(self) -> None:
        self.base_url = _normalize_openai_base_url(self.base_url)

    def next_action(self, state: AgentState) -> ModelAction:
        response = self._post_responses(self._build_payload(state))
        text = _extract_response_text(response)
        action_payload = _parse_action_json(text)
        return _model_action_from_payload(action_payload)

    def _build_payload(self, state: AgentState) -> dict[str, Any]:
        return {
            "model": self.model,
            "input": [
                {"role": "system", "content": MODEL_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(_state_view(state), ensure_ascii=False),
                },
            ],
            "temperature": 0,
            "max_output_tokens": self.max_output_tokens,
        }

    def _post_responses(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}/responses"
        request = urllib.request.Request(
            url=url,
            method="POST",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "HarnessCoder/0.1",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw_body = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise ModelAdapterError(
                f"model API returned HTTP {exc.code}: {_clip(error_body, 2000)}"
            ) from exc
        except urllib.error.URLError as exc:
            raise ModelAdapterError(f"model API request failed: {exc}") from exc

        try:
            parsed = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise ModelAdapterError(
                f"model API returned non-JSON response: {_clip(raw_body, 2000)}"
            ) from exc
        if not isinstance(parsed, dict):
            raise ModelAdapterError("model API response must be a JSON object")
        return parsed


MODEL_SYSTEM_PROMPT = """You are the model-decision layer inside HarnessCoder.
HarnessCoder is a local coding-agent harness. You do not directly access files,
run commands, or edit code. You choose the next action for the runtime.

Return exactly one JSON object and no Markdown.

Allowed tool action:
{
  "kind": "tool",
  "rationale": "why this tool call is the next useful step",
  "tool_name": "read_file | search_code | write_file | edit_file | run_tests | run_command",
  "tool_args": {}
}

Allowed finish action:
{
  "kind": "finish",
  "rationale": "why enough information has been gathered",
  "content": "final answer to the user"
}

Tool schemas:
- read_file(path: string, offset: int = 0, limit: int = 200)
- search_code(query: string, path: string = ".")
- write_file(path: string, content: string, overwrite: boolean = false)
- edit_file(path: string, old: string, new: string)
- run_tests(cmd: string | null = null, timeout: int = 60)
- run_command(cmd: string, timeout: int = 30)

Use write_file for new files in greenfield tasks. Use edit_file only for exact
replacements where old is expected to match once. Prefer run_tests for local
python/pytest/unittest test execution. Reserve run_command for repository
inspection and other policy-allowed commands. The policy layer may deny unsafe
commands.
Answer in the user's language when finishing."""


def _normalize_openai_base_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if not normalized.endswith("/v1"):
        normalized = f"{normalized}/v1"
    return normalized


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
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            return message["content"]

    raise ModelAdapterError("model API response did not include text output")


def _parse_action_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", stripped, flags=re.DOTALL)
    if fenced:
        stripped = fenced.group(1).strip()

    if not stripped.startswith("{"):
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start >= 0 and end > start:
            stripped = stripped[start : end + 1]

    decoder = json.JSONDecoder()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        try:
            parsed, _ = decoder.raw_decode(stripped)
        except json.JSONDecodeError as exc:
            raise ModelAdapterError(
                f"model did not return valid action JSON: {text}"
            ) from exc

    if not isinstance(parsed, dict):
        raise ModelAdapterError("model action JSON must be an object")
    return parsed


def _model_action_from_payload(payload: dict[str, Any]) -> ModelAction:
    payload = _normalize_action_payload(payload)
    kind = payload.get("kind")
    rationale = payload.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        rationale = "Model did not provide a rationale."

    if kind == "finish":
        content = payload.get("content") or payload.get("final_answer") or ""
        if not isinstance(content, str):
            raise ModelAdapterError("finish action content must be a string")
        return ModelAction(kind="finish", rationale=rationale, content=content)

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
        )

    raise ModelAdapterError("model action kind must be either 'tool' or 'finish'")


def _normalize_action_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    raw_kind = normalized.get("kind")
    raw_action = normalized.get("action")

    if not isinstance(raw_kind, str) or not raw_kind.strip():
        raw_kind = raw_action if isinstance(raw_action, str) else None
    kind = raw_kind.strip().lower() if isinstance(raw_kind, str) else None

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

    tool_args = normalized.get("tool_args")
    if not isinstance(tool_args, dict):
        for key in ("args", "arguments", "parameters", "input"):
            value = normalized.get(key)
            if isinstance(value, dict):
                normalized["tool_args"] = value
                break

    if normalized.get("kind") is None and isinstance(normalized.get("tool_name"), str):
        normalized["kind"] = "tool"

    if normalized.get("kind") == "finish" and "content" not in normalized:
        for key in ("final_answer", "answer", "message", "summary"):
            value = normalized.get(key)
            if isinstance(value, str):
                normalized["content"] = value
                break

    return normalized


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}... [truncated {len(text) - limit} chars]"
