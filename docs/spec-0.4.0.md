# HarnessCoder 0.4.0 Scoped Spec

Version 0.4.0 proves the first real bugfix loop. The goal is not a larger
benchmark yet; it is one honest closed loop where a live model sees a failing
test, edits source code through HarnessCoder tools, reruns tests, and leaves a
trace that can be replayed.

## Goals

- Add a bugfix fixture with an intentionally failing Python unittest.
- Run fixture cases in copied workspaces so evals never mutate source fixtures.
- Preserve the run trace, external test result, workspace path, and modified
  files in the eval report.
- Keep the same dynamic agent loop: model action, policy gate, tool result,
  state update, checkpoint, replay.

## Case Schema Addition

Eval cases may define:

```json
{
  "repo_fixture": "examples/bugfix_demo/repo"
}
```

When `repo_fixture` is present, the eval runner must:

- Resolve the fixture relative to the workspace root or cases file directory.
- Copy it to `.harnesscoder/eval-workspaces/<case_id>/<timestamp>/repo`.
- Run the agent and tests inside the copied repo.
- Leave the original fixture unchanged.
- Include the copied workspace path in the result and Markdown report.

## Acceptance

- `eval/bugfix_cases.json` contains a real bugfix case.
- The fixture's test command fails before a successful agent edit.
- A real OpenAI-compatible model run can pass the case within 8 iterations.
- Replay metrics show at least one `edit_file` and at least two `run_tests`
  events for the successful run.
- Unit tests verify fixture isolation and report rendering.

## Non-Goals

- Multiple model comparison.
- Streaming API responses.
- Strong filesystem sandboxing.
- A broad benchmark suite.
