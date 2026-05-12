# Greenfield Demo

This demo is the `0.6.0` greenfield slice: the agent starts from a nearly empty
fixture, writes new files through the policy-gated `write_file` tool, and
finishes with trace-backed tests and a verifier result.

Run it with a real OpenAI-compatible model:

```bash
python -m harnesscoder \
  --provider openai-codex \
  --openai-base-url "$HARNESSCODER_OPENAI_BASE_URL" \
  --openai-model "$HARNESSCODER_OPENAI_MODEL" \
  --eval eval/greenfield_cases.json \
  --max-iterations 10 \
  --eval-report .harnesscoder/reports/greenfield-demo.md
```

The eval case restricts tools with `allowed_tools`, caps loop steps with
`step_budget`, and runs a separate verifier after tests pass.
