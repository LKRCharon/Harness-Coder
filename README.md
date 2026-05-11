# HarnessCoder

HarnessCoder is a local coding agent harness for real repository tasks. It is not
a fork of CoreCoder, not a smaller LangGraph clone, and not a web UI. The first
goal is a controllable runtime that can run an agent loop, gate tool execution
with policy, and write every important decision into a replayable JSONL trace.

The core loop is dynamic:

```text
state -> model decides action -> policy checks -> tool executes
      -> observation appended -> state updated -> model decides again
```

That shape matters because coding tasks are rarely a fixed DAG. The useful next
step depends on the current repo, tool observations, failures, test output, and
the model's evolving plan. A DAG or LangGraph-style workflow can be useful for
the eval pipeline around the agent, but the agent itself should remain a
policy-gated loop.

## Current Status

Version `0.3.0` is a runnable local runtime with trace replay, eval reporting,
context governance, and checkpoint/resume support. It includes:

- A `ScriptedModel` that simulates model actions without calling a real LLM.
- Tool execution for:
  - `read_file(path, offset=0, limit=200)`
  - `search_code(query, path=".")`
  - `edit_file(path, old, new)`
  - `run_tests(cmd=None, timeout=60)`
  - `run_command(cmd, timeout=30)`
- A minimal policy gate before every tool call.
- JSONL traces under `.harnesscoder/runs/<run_id>/trace.jsonl`.
- `context_packed`, `checkpoint_created`, `run_resumed`, and `test_result`
  events for reliability-oriented replay.
- Trace replay summaries through `python -m harnesscoder.replay`.
- A minimal eval harness that runs cases, executes tests, scores results, and
  renders a Markdown report.
- CLI entrypoints:

```bash
python -m harnesscoder "看一下这个 repo 是做什么的"
python -m harnesscoder --replay .harnesscoder/runs/<run_id>/trace.jsonl
python -m harnesscoder --resume .harnesscoder/runs/<run_id>/checkpoint.json
python -m harnesscoder --eval eval/cases.json
```

The scripted model currently performs a small repo-orientation pass: search for
project mentions, read `README.md`, list files, and then produce a final answer.

## TUI

HarnessCoder also has a lightweight standard-library terminal UI:

```bash
python -m harnesscoder --tui
```

Inside the TUI, send a normal message to run the agent and write a new trace.
Use slash commands for direct tools and runtime controls:

```text
/help
/status
/model gpt-5.5
/model scripted
/provider openai-codex
/base-url https://api.dest.space
/read README.md
/search HarnessCoder
/edit README.md old new
/test python -m unittest discover -s tests
/run git status --short
/trace latest
```

The current TUI is intentionally small: it is a runnable scaffold for the final
interactive spec, not a full Claude Code clone.

## OpenAI-Compatible Codex Provider

The MVP also includes an optional `openai-codex` provider. It calls an
OpenAI-compatible Responses API endpoint and asks the model to return a strict
JSON action for the runtime to execute.

Keep secrets out of the repo. Configure the provider with environment variables
or a local `.env` file:

```bash
export OPENAI_API_KEY="sk-..."
export HARNESSCODER_OPENAI_BASE_URL="https://your-openai-compatible-endpoint.example/v1"
export HARNESSCODER_OPENAI_MODEL="your-codex-model-name"

python -m harnesscoder --provider openai-codex "看一下这个 repo 是做什么的"
```

If the base URL does not end in `/v1`, HarnessCoder appends `/v1` before calling
`/responses`.

When launched from a repo, the CLI auto-loads `.env` from the current directory
and from `--cwd` if it is different. Existing shell environment variables win
over `.env` values. `OPENAI_MODEL` is also accepted as a fallback for
`HARNESSCODER_OPENAI_MODEL`.

## Trace Shape

Each run writes event records with a timestamp, run id, and event type. The
runtime trace includes at least:

- `run_started`
- `context_packed`
- `model_action`
- `policy_decision`
- `tool_result`
- `test_result`
- `state_updated`
- `checkpoint_created`
- `run_resumed`
- `run_finished`

These traces are intentionally append-only JSONL so later replay and eval code
can consume them without depending on in-memory state.

## Developer Process Notes

See [docs/development-process.md](docs/development-process.md) for the running
engineering log: design decisions, bugs encountered during real provider
integration, fixes, and interview-ready talking points.

## Replay And Eval

Replay loads a trace and reconstructs a structured summary:

```bash
python -m harnesscoder.replay .harnesscoder/runs/<run_id>/trace.jsonl
python -m harnesscoder --replay .harnesscoder/runs/<run_id>/trace.jsonl
```

Resume continues an interrupted run from the saved checkpoint:

```bash
python -m harnesscoder --resume .harnesscoder/runs/<run_id>/checkpoint.json
```

Eval stays workflow-shaped around the dynamic agent loop:

```text
setup repo -> run agent -> run tests -> collect trace -> score -> report
```

Run the local smoke eval:

```bash
python -m harnesscoder --eval eval/cases.json
```

Near-term TODOs:

- Improve the TUI with streaming status, better history navigation, and trace
  inspection commands.
- Live-test and harden the OpenAI-compatible model adapter against real traffic.
- Use context packs directly in the live model prompt, not only in trace.
- Add richer failure replay fixtures under `replay/`.
- Add bug-fix eval cases that exercise `edit_file` with real failing tests.
