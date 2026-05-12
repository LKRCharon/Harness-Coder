# HarnessCoder 0.6.0 Scoped Spec

Version 0.6.0 absorbs the useful parts of Pico without copying its shape. The
release adds a minimal greenfield coding loop and richer eval case constraints,
while keeping HarnessCoder's differentiator: event-sourced trace, policy-gated
tools, replay, checkpoint, and eval matrix.

## Goals

- Add `write_file` so the agent can create new source and test files.
- Add greenfield eval fixtures that start without application code.
- Support case-level `allowed_tools` and `step_budget`.
- Support a post-test `verifier` command.
- Include verifier status in normal eval reports and matrix reports.

## Tool Addition

`write_file(path, content, overwrite=false)` creates a UTF-8 file inside the
workspace. It creates parent directories as needed. It refuses to overwrite an
existing file unless `overwrite=true`.

Trace metadata must include:

- `path`
- `changed`
- `created`
- `overwrite`
- `content_length`

## Eval Case Additions

Eval cases may now include:

```json
{
  "allowed_tools": ["write_file", "read_file", "run_tests"],
  "step_budget": 8,
  "verifier": "python -c \"import math_utils; assert math_utils.add_one(41) == 42\""
}
```

`allowed_tools` is enforced by the same policy layer that gates every tool call.
`step_budget` caps the agent loop for that case. `verifier` runs after the agent
and test command, and a case passes only if the agent, tests, and verifier pass.

## Demo

`eval/greenfield_cases.json` asks the model to create:

- `math_utils.py`
- `test_math_utils.py`

from a nearly empty fixture, then pass `python -m unittest discover` and a
separate import/assert verifier.

## Acceptance

- `write_file` can create nested files and refuses accidental overwrite.
- `allowed_tools` can deny tools outside a case's declared contract.
- Greenfield eval passes with a deterministic test model.
- Real model greenfield eval can create code from scratch within the step budget.
- Reports include verifier pass rate and per-run verifier status.

## Non-Goals

- Full project scaffolding for web apps.
- Dependency installation.
- Shell sandboxing beyond current policy checks.
- Multi-agent implementation.
