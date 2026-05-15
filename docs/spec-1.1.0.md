# HarnessCoder 1.1.0 Spec

## Goal

Add prompt-cache-aware context governance inspired by Claude Code's prompt
caching lessons while keeping HarnessCoder provider-neutral.

HarnessCoder 1.1.0 does not call a provider-specific cache API. It records enough
prompt structure to evaluate whether a run would preserve stable prompt prefixes.

## Scope

- Split assembled prompts into stable, semi-stable, and dynamic sections.
- Fingerprint system instructions, available tools, task contract, context
  payload, and full stable prefix.
- Record prompt section token estimates in trace.
- Detect stable-prefix changes within a run.
- Surface prompt cache-break metrics in replay and Markdown eval reports.
- Keep tool ordering deterministic.

## Trace Contract

Every `context_packed` event includes:

```json
{
  "prompt_fingerprint": {
    "system_hash": "...",
    "tool_schema_hash": "...",
    "task_contract_hash": "...",
    "context_payload_hash": "...",
    "stable_prefix_hash": "...",
    "dynamic_suffix_hash": "..."
  },
  "prompt_sections": {
    "stable_prefix_tokens": 123,
    "semi_stable_tokens": 45,
    "dynamic_suffix_tokens": 67
  },
  "stable_prefix_changed": false,
  "cache_break_reason": null
}
```

If the stable prefix changes after the first model step, the event records
`stable_prefix_changed=true` and a human-readable `cache_break_reason`.

## Non-goals

- No provider-specific prompt cache API.
- No dynamic tool loading system.
- No long-term memory.
- No subagent mode changes in this milestone.
