# Bugfix Demo

This demo is the `0.4.0` closed-loop slice: the agent starts from a real failing
test, edits source code through the policy-gated `edit_file` tool, and produces
a trace-backed success report after tests pass.

Run it with a real OpenAI-compatible model:

```bash
python -m harnesscoder \
  --provider openai-codex \
  --openai-base-url "$HARNESSCODER_OPENAI_BASE_URL" \
  --openai-model "$HARNESSCODER_OPENAI_MODEL" \
  --eval eval/bugfix_cases.json \
  --max-iterations 8 \
  --eval-report .harnesscoder/reports/bugfix-demo.md
```

The eval runner copies `examples/bugfix_demo/repo` into
`.harnesscoder/eval-workspaces/...` before running, so the fixture remains
unchanged.
