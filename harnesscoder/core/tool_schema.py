from __future__ import annotations

import functools
import inspect
from dataclasses import dataclass, field
from typing import Any, Callable

_MISSING = object()

_TYPE_VALIDATORS: dict[str, Callable[[Any], bool]] = {
    "string": lambda v: isinstance(v, str),
    "int": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "string[]": lambda v: isinstance(v, list) and all(isinstance(i, str) for i in v),
    "string | null": lambda v: v is None or isinstance(v, str),
    "int | null": lambda v: v is None or (isinstance(v, int) and not isinstance(v, bool)),
}


@dataclass(frozen=True)
class ToolParam:
    name: str
    type: str
    description: str
    required: bool = True
    default: Any = _MISSING


@dataclass(frozen=True)
class ToolSchema:
    name: str
    description: str
    params: tuple[ToolParam, ...]

    def to_prompt_text(self) -> str:
        sig_parts: list[str] = []
        for p in self.params:
            if p.required:
                sig_parts.append(f"{p.name}: {p.type}")
            elif p.default is not _MISSING:
                sig_parts.append(f"{p.name}: {p.type} = {p.default!r}")
            else:
                sig_parts.append(f"{p.name}: {p.type} = null")
        sig = ", ".join(sig_parts)
        return f"- {self.name}({sig})\n  {self.description}"

    def validate_args(self, args: dict[str, Any]) -> str | None:
        for p in self.params:
            if p.name not in args:
                if p.required:
                    return f"missing required parameter: {p.name}"
                continue
            value = args[p.name]
            validator = _TYPE_VALIDATORS.get(p.type)
            if validator and not validator(value):
                return f"{p.name} must be {p.type}, got {type(value).__name__}"
        return None


def harness_tool(description: str, **param_meta: tuple[str, str, bool] | tuple[str, str, bool, Any]):
    """Decorator that attaches a ToolSchema to a tool method.

    Usage:
        @harness_tool(
            description="Read a file.",
            path=("string", "Path to the file.", True),
            offset=("int", "Start line.", False, 0),
        )
        def read_file(self, call_id, path, offset=0): ...
    """
    params: list[ToolParam] = []
    for name, meta in param_meta.items():
        if len(meta) == 3:
            type_str, desc, required = meta
            default = _MISSING
        elif len(meta) == 4:
            type_str, desc, required, default = meta
        else:
            raise ValueError(f"param meta for {name} must be 3 or 4 elements, got {len(meta)}")
        params.append(ToolParam(name=name, type=type_str, description=desc, required=required, default=default))

    schema = ToolSchema(name="", description=description, params=tuple(params))

    def decorator(fn: Callable) -> Callable:
        tool_name = fn.__name__
        resolved_schema = ToolSchema(
            name=tool_name,
            description=schema.description,
            params=schema.params,
        )
        fn.__tool_schema__ = resolved_schema  # type: ignore[attr-defined]

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return fn(*args, **kwargs)

        wrapper.__tool_schema__ = resolved_schema  # type: ignore[attr-defined]
        return wrapper

    return decorator
