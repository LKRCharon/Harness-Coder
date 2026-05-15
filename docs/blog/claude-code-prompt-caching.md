# Lessons From Claude Code Prompt Caching

Source: [Lessons from building Claude Code: Prompt caching is everything](https://claude.com/blog/lessons-from-building-claude-code-prompt-caching-is-everything)

Published: April 30, 2026

This note is an engineering summary, not a full translation. The useful lesson
for HarnessCoder is that long-running agent systems should treat prompt caching
as an architectural constraint, not as a late cost optimization.

## Core Points

Prompt caching is prefix-sensitive. Stable prompt sections should appear before
dynamic sections so requests can reuse the longest possible prefix. Claude Code's
ordering is roughly:

1. system instructions and tool definitions,
2. project-level context,
3. session-level context,
4. recent conversation messages.

Dynamic facts should not be injected by rewriting the stable system prompt.
Current time, file changes, and other live state should be appended later as
messages or tool observations.

Model and tool changes are cache boundaries. Switching models or changing tool
schemas in the middle of a long session can invalidate useful cached prefixes.
For agent modes such as planning, keeping the tool set stable and enforcing
permissions through policy is more cache-friendly than removing tools from the
prompt.

Large tool ecosystems should prefer deferred loading over dynamic deletion.
Lightweight stable stubs can preserve prompt order while full schemas are loaded
only when needed.

Context compression should also be cache-aware. A compaction request should reuse
the parent session's stable prompt, tool definitions, and context prefix, then add
the compaction instruction at the end.

## HarnessCoder Implications

HarnessCoder should not couple itself to one provider's prompt cache feature, but
it should make prompt-cache friendliness observable:

- keep system instructions and tool names deterministic;
- treat policy gates as the mechanism for mode changes instead of mutating the
  tool list;
- record prompt section fingerprints in trace events;
- report stable-prefix changes as cache-break events;
- make compression and future forked tasks preserve the parent prompt prefix
  where possible.

The practical 1.1 target is prompt cache governance: trace every model-step
prompt with a stable-prefix hash, dynamic-suffix hash, section token estimates,
and a cache-break reason when the stable prefix changes inside a run.
