# HarnessCoder 1.5.2 Spec

## Goal

Add context-quality evaluation for the Gather-Select-Structure-Compress
pipeline.

1.5.2 makes context governance inspectable. After each context assembly, the
runtime evaluates whether the context is dense, relevant, and complete enough
for the next model step.

## Scope

- Add a rule-based `ContextQualityEvaluator`.
- Score three dimensions:
  - information density
  - relevance
  - completeness
- Add warnings and optimization suggestions when:
  - key sections are empty
  - recent failures were compressed away
  - context budget reductions are heavy
  - relevant notes or repo map evidence are missing
  - repeated observations dominate the context
- Emit `context_quality_evaluated` trace records.
- Add replay/report metrics:
  - average context quality score
  - low-quality context count
  - low relevance count
  - low completeness count

## Runtime Contract

```text
gather -> select -> structure -> compress -> evaluate quality -> trace
```

The evaluator should be deterministic and local-first. LLM-as-judge may be
added later, but the first version must be reproducible in unit tests.

## Acceptance

- Every `context_packed` event can be paired with context-quality metrics.
- Unit tests cover low-density, low-relevance, and incomplete context cases.
- Eval reports surface quality metrics next to context budget metrics.
- No external model call is required for quality scoring.

## Non-goals

- No LLM summary compressor.
- No vector retrieval evaluation.
- No automatic prompt rewrite based on quality warnings.

## Interview Angle

1.5.2 is the answer to "how do you know your context builder is good?"

> HC treats context construction as a measurable GSSC pipeline. It does not only
> count tokens; it scores density, relevance, and completeness, emits warnings
> when critical evidence is likely missing, and lets eval reports correlate
> context quality with agent outcomes.
