from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from harnesscoder.core.models import (
    HCBenchOracleModel,
    ModelAdapter,
    OpenAICodexModel,
    ScriptedModel,
)


@dataclass(frozen=True, slots=True)
class ModelProfile:
    name: str
    provider: str
    model: str | None = None
    base_url: str | None = None
    api_key_env: str = "OPENAI_API_KEY"
    timeout: int = 60
    max_output_tokens: int = 1200

    @classmethod
    def from_record(cls, name: str, record: dict[str, Any]) -> "ModelProfile":
        provider = _required_str(record, "provider")
        model = _optional_str(record, "model")
        base_url = _optional_str(record, "base_url")
        api_key_env = _optional_str(record, "api_key_env") or "OPENAI_API_KEY"
        timeout = _optional_int(record, "timeout", 60)
        max_output_tokens = _optional_int(record, "max_output_tokens", 1200)

        if provider in {"scripted", "hc-bench-oracle"}:
            return cls(name=name, provider=provider)
        if provider == "openai-codex":
            return cls(
                name=name,
                provider=provider,
                model=model,
                base_url=base_url,
                api_key_env=api_key_env,
                timeout=timeout,
                max_output_tokens=max_output_tokens,
            )
        raise ValueError(f"unsupported model profile provider: {provider}")

    def build(self) -> ModelAdapter:
        if self.provider == "scripted":
            return ProfiledModel(self.name, ScriptedModel())

        if self.provider == "hc-bench-oracle":
            return ProfiledModel(self.name, HCBenchOracleModel())

        if self.provider == "openai-codex":
            api_key = os.environ.get(self.api_key_env)
            if not api_key:
                raise ValueError(
                    f"{self.api_key_env} is required for model profile {self.name!r}"
                )
            model = self.model or os.environ.get("HARNESSCODER_OPENAI_MODEL") or os.environ.get("OPENAI_MODEL")
            if not model:
                raise ValueError(
                    f"model profile {self.name!r} must set model or use "
                    "HARNESSCODER_OPENAI_MODEL/OPENAI_MODEL"
                )
            base_url = (
                self.base_url
                or os.environ.get("HARNESSCODER_OPENAI_BASE_URL")
                or os.environ.get("OPENAI_BASE_URL")
                or "https://api.openai.com/v1"
            )
            return ProfiledModel(
                self.name,
                OpenAICodexModel(
                    api_key=api_key,
                    model=model,
                    base_url=base_url,
                    timeout=self.timeout,
                    max_output_tokens=self.max_output_tokens,
                ),
            )

        raise ValueError(f"unsupported model profile provider: {self.provider}")


@dataclass(slots=True)
class ProfiledModel:
    profile_name: str
    adapter: ModelAdapter

    @property
    def name(self) -> str:
        adapter_name = getattr(self.adapter, "name", type(self.adapter).__name__)
        return f"{self.profile_name}:{adapter_name}"

    def next_action(self, state: Any) -> Any:
        return self.adapter.next_action(state)


def load_model_profiles(config_path: str | Path) -> dict[str, ModelProfile]:
    path = Path(config_path)
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("model config must be a TOML table")

    models = data.get("models")
    if not isinstance(models, dict) or not models:
        raise ValueError("model config must contain a non-empty [models] table")

    profiles: dict[str, ModelProfile] = {}
    for name, record in models.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError("model profile names must be non-empty strings")
        if not isinstance(record, dict):
            raise ValueError(f"model profile {name!r} must be a TOML table")
        profiles[name] = ModelProfile.from_record(name, record)
    return profiles


def parse_profile_names(value: str) -> list[str]:
    names = [part.strip() for part in value.split(",") if part.strip()]
    if not names:
        raise ValueError("profile list must contain at least one name")
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ValueError(f"duplicate model profiles: {', '.join(duplicates)}")
    return names


def resolve_model_config_path(config_path: str | Path, cwd: Path) -> Path:
    raw_path = Path(config_path)
    if raw_path.is_absolute():
        return raw_path

    cwd_candidate = (cwd / raw_path).resolve()
    if cwd_candidate.exists():
        return cwd_candidate

    return (Path.cwd() / raw_path).resolve()


def _required_str(record: dict[str, Any], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"model profile field {key!r} must be a non-empty string")
    return value


def _optional_str(record: dict[str, Any], key: str) -> str | None:
    value = record.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"model profile field {key!r} must be a non-empty string")
    return value


def _optional_int(record: dict[str, Any], key: str, default: int) -> int:
    value = record.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"model profile field {key!r} must be an integer")
    if value <= 0:
        raise ValueError(f"model profile field {key!r} must be positive")
    return value
