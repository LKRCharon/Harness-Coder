# HarnessCoder 0.7.0 Scoped Spec

Version 0.7.0 turns the single-case demos into HC-Bench-20: a local,
trace-backed benchmark suite for coding-agent reliability.

## Goals

- Add a 20-case eval suite that is small enough to run locally and rich enough
  to show distinct agent behaviors.
- Cover five categories:
  - bugfix
  - recovery
  - greenfield
  - context
  - policy
- Add category-level report and matrix summaries.
- Keep each case fixture-backed, isolated, policy-gated, step-budgeted, and
  verifier-checked.
- Add a deterministic `hc-bench-oracle` provider as a stable harness baseline.

## HC-Bench-20 Shape

The suite lives in `eval/hc_bench_20.json`.

Each case includes:

- `id`
- `category`
- `task`
- `repo_fixture`
- `allowed_tools`
- `step_budget`
- `test_command`
- `verifier`
- `success_returncode`

The fixture lives in `examples/hc_bench_20/repo`. Eval runs copy that fixture
into `.harnesscoder/eval-workspaces/<case_id>/.../repo` before editing, so the
source fixture remains intentionally broken and stable.

## Categories

### Bugfix

Business-like bugs: timezone boundaries, inclusive thresholds, proration,
idempotency windows, pagination offsets, feature flag defaults, and SLA
thresholds.

### Recovery

Cases that require an intermediate failing test and a second fix. These are
designed to prove the loop can record failure and continue.

### Greenfield

Small modules created from scratch through `write_file`, including tests.

### Context

Large-file tasks that should use search-first and bounded local reads instead
of full-file context stuffing.

### Policy

Security and tool-boundary tasks: path traversal, command injection, and a
repository-suggested dangerous command that must be denied by policy.

## Deterministic Oracle

`hc-bench-oracle` is a local deterministic provider. It is not a capability
claim about model intelligence. It exists to prove that:

- the suite fixtures are solvable,
- reports and matrices can aggregate 20 cases,
- verifiers can inspect traces,
- policy denials and failed-test recovery are visible in metrics.

Real model profiles should be compared against this same case suite.

## Reporting

Eval reports and matrix reports must include:

- suite-level pass/test/verifier rates,
- category-level summaries,
- failure category breakdowns,
- tool counts,
- repeated reads,
- invalid calls,
- policy denials,
- trace paths for every case.

## Acceptance

- `eval/hc_bench_20.json` contains exactly 20 unique cases.
- The category distribution is:
  - bugfix: 7
  - recovery: 3
  - greenfield: 5
  - context: 2
  - policy: 3
- `hc-bench-oracle` passes all 20 cases.
- A matrix can compare `scripted` against `hc-bench-oracle`.
- Unit tests cover loading HC-Bench-20, category reporting, and the oracle.

## Non-Goals

- SWE-bench adapter.
- Large Dockerized benchmark execution.
- Token/cost accounting.
- TUI session management.
- Production-grade sandboxing.
