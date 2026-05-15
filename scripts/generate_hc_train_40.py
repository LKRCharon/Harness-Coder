from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from generate_hc_bench_20 import (
    FIXTURE as BENCH_FIXTURE,
    edit,
    read,
    run_command,
    run_tests,
    search,
    trace_verifier,
    write,
    write_fixture as write_bench_fixture,
    write_json,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "examples" / "hc_train_40" / "repo"
EVAL_PATH = ROOT / "eval" / "hc_train_40.json"
ORACLE_PATH = ROOT / "harnesscoder" / "data" / "hc_train_oracle.json"


def main() -> None:
    write_fixture()
    cases, plans = build_cases_and_plans()
    write_json(EVAL_PATH, {"suite": "HC-Train-40", "version": "1.2.0", "cases": cases})
    write_json(ORACLE_PATH, {"suite": "HC-Train-40", "version": "1.2.0", "plans": plans})


def write_fixture() -> None:
    write_bench_fixture()
    if FIXTURE.exists():
        shutil.rmtree(FIXTURE)
    shutil.copytree(
        BENCH_FIXTURE,
        FIXTURE,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    append_file(FIXTURE / "router_registry.py", ROUTER_TRAIN_FUNCTIONS)
    append_file(FIXTURE / "metrics.py", METRICS_TRAIN_FUNCTIONS)
    append_file(FIXTURE / "billing.py", BILLING_TRAIN_FUNCTIONS)
    (FIXTURE / "access_rules.py").write_text(
        large_module("access", ACCESS_RULES_FUNCTIONS, 140),
        encoding="utf-8",
    )
    (FIXTURE / "audit_rules.py").write_text(
        large_module("audit", AUDIT_RULES_FUNCTIONS, 145),
        encoding="utf-8",
    )
    append_file(FIXTURE / "csv_config.py", CSV_TRAIN_FUNCTIONS)
    (FIXTURE / "test_large_context.py").write_text(TEST_LARGE_CONTEXT_TRAIN, encoding="utf-8")
    (FIXTURE / "test_train_business.py").write_text(TEST_TRAIN_BUSINESS, encoding="utf-8")
    (FIXTURE / "test_train_recovery.py").write_text(TEST_TRAIN_RECOVERY, encoding="utf-8")
    (FIXTURE / "test_train_policy.py").write_text(TEST_TRAIN_POLICY, encoding="utf-8")


def build_cases_and_plans() -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    cases: list[dict[str, Any]] = []
    plans: dict[str, list[dict[str, Any]]] = {}
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
                "repo_fixture": "examples/hc_train_40/repo",
                "allowed_tools": allowed_tools,
                "step_budget": step_budget,
                "test_command": test_command,
                "timeout": 10,
                "success_returncode": 0,
                "verifier": verifier,
                "split": "train",
                "source": "synthetic-microbenchmark",
            }
        )
        plans[case_id] = plan

    add_case(
        case_id="train-billing-coupon-normalization",
        category="bugfix",
        task="Fix coupon lookup so mixed-case and padded coupon codes resolve correctly.",
        test_command="python -m unittest test_train_business.TrainBusinessTests.test_coupon_normalization",
        verifier=trace_verifier("billing.py", min_tools={"search_code": 1, "edit_file": 1, "run_tests": 1}),
        allowed_tools=edit_tools,
        step_budget=6,
        plan=[
            search("def coupon_discount", "."),
            read("billing.py"),
            edit("billing.py", "    return coupons.get(code, 0.0)\n", "    return coupons.get(code.strip().upper(), 0.0)\n"),
            run_tests("python -m unittest test_train_business.TrainBusinessTests.test_coupon_normalization"),
        ],
    )
    add_case(
        case_id="train-billing-tax-rounding",
        category="bugfix",
        task="Fix tax calculation so cents round to the nearest integer instead of truncating.",
        test_command="python -m unittest test_train_business.TrainBusinessTests.test_tax_rounds_to_nearest_cent",
        verifier=trace_verifier("billing.py", min_tools={"search_code": 1, "edit_file": 1, "run_tests": 1}),
        allowed_tools=edit_tools,
        step_budget=6,
        plan=[
            search("def tax_cents", "."),
            read("billing.py"),
            edit("billing.py", "    return int(amount_cents * rate)\n", "    return round(amount_cents * rate)\n"),
            run_tests("python -m unittest test_train_business.TrainBusinessTests.test_tax_rounds_to_nearest_cent"),
        ],
    )
    add_case(
        case_id="train-billing-seat-capacity",
        category="bugfix",
        task="Fix seat availability so exactly-full plans cannot accept another seat.",
        test_command="python -m unittest test_train_business.TrainBusinessTests.test_seat_availability_boundary",
        verifier=trace_verifier("billing.py", min_tools={"search_code": 1, "edit_file": 1, "run_tests": 1}),
        allowed_tools=edit_tools,
        step_budget=6,
        plan=[
            search("def can_add_seat", "."),
            read("billing.py"),
            edit("billing.py", "    return used <= limit\n", "    return used < limit\n"),
            run_tests("python -m unittest test_train_business.TrainBusinessTests.test_seat_availability_boundary"),
        ],
    )
    add_case(
        case_id="train-billing-trial-expiry",
        category="bugfix",
        task="Fix trial expiry so equality at the expiry day is not treated as active.",
        test_command="python -m unittest test_train_business.TrainBusinessTests.test_trial_expiry_boundary",
        verifier=trace_verifier("billing.py", min_tools={"search_code": 1, "edit_file": 1, "run_tests": 1}),
        allowed_tools=edit_tools,
        step_budget=6,
        plan=[
            search("def trial_is_active", "."),
            read("billing.py"),
            edit("billing.py", "    return current_day <= expires_day\n", "    return current_day < expires_day\n"),
            run_tests("python -m unittest test_train_business.TrainBusinessTests.test_trial_expiry_boundary"),
        ],
    )
    add_case(
        case_id="train-billing-plan-rank",
        category="bugfix",
        task="Fix plan rank lookup so unknown plans use the free tier rank.",
        test_command="python -m unittest test_train_business.TrainBusinessTests.test_plan_rank_unknown_defaults_to_free",
        verifier=trace_verifier("billing.py", min_tools={"search_code": 1, "edit_file": 1, "run_tests": 1}),
        allowed_tools=edit_tools,
        step_budget=6,
        plan=[
            search("def plan_rank", "."),
            read("billing.py"),
            edit("billing.py", "    return ranks[name]\n", "    return ranks.get(name, 0)\n"),
            run_tests("python -m unittest test_train_business.TrainBusinessTests.test_plan_rank_unknown_defaults_to_free"),
        ],
    )
    add_case(
        case_id="train-billing-refund-window",
        category="bugfix",
        task="Fix refund window handling so the final eligible day is still refundable.",
        test_command="python -m unittest test_train_business.TrainBusinessTests.test_refund_window_inclusive",
        verifier=trace_verifier("billing.py", min_tools={"search_code": 1, "edit_file": 1, "run_tests": 1}),
        allowed_tools=edit_tools,
        step_budget=6,
        plan=[
            search("def is_refundable", "."),
            read("billing.py"),
            edit("billing.py", "    return days_since_purchase < refund_window_days\n", "    return days_since_purchase <= refund_window_days\n"),
            run_tests("python -m unittest test_train_business.TrainBusinessTests.test_refund_window_inclusive"),
        ],
    )
    add_case(
        case_id="train-billing-usage-overage",
        category="bugfix",
        task="Fix usage overage so usage exactly at the included quota does not bill extra units.",
        test_command="python -m unittest test_train_business.TrainBusinessTests.test_usage_overage_boundary",
        verifier=trace_verifier("billing.py", min_tools={"search_code": 1, "edit_file": 1, "run_tests": 1}),
        allowed_tools=edit_tools,
        step_budget=6,
        plan=[
            search("def overage_units", "."),
            read("billing.py"),
            edit("billing.py", "    return max(0, used_units - included_units + 1)\n", "    return max(0, used_units - included_units)\n"),
            run_tests("python -m unittest test_train_business.TrainBusinessTests.test_usage_overage_boundary"),
        ],
    )

    add_case(
        case_id="context-router-timeout-large-file",
        category="context",
        task="Fix router timeout lookup in the large registry with search-first bounded reads.",
        test_command="python -m unittest test_large_context.LargeContextTests.test_router_timeout_lookup",
        verifier=trace_verifier("router_registry.py", min_tools={"search_code": 1, "read_file": 1, "edit_file": 1, "run_tests": 1}, max_read_limit=80),
        allowed_tools=edit_tools,
        step_budget=6,
        plan=[
            search("router_timeout_seconds", "."),
            read("router_registry.py", 520, 60),
            edit("router_registry.py", "    return timeouts[name]\n", "    return timeouts.get(name, 30)\n"),
            run_tests("python -m unittest test_large_context.LargeContextTests.test_router_timeout_lookup"),
        ],
    )
    add_case(
        case_id="context-router-capability-large-file",
        category="context",
        task="Fix provider capability lookup without reading the entire router registry.",
        test_command="python -m unittest test_large_context.LargeContextTests.test_provider_supports_tool_calls_unknown",
        verifier=trace_verifier("router_registry.py", min_tools={"search_code": 1, "read_file": 1, "edit_file": 1, "run_tests": 1}, max_read_limit=80),
        allowed_tools=edit_tools,
        step_budget=6,
        plan=[
            search("provider_supports_tool_calls", "."),
            read("router_registry.py", 585, 60),
            edit("router_registry.py", "    return capabilities[name]\n", "    return capabilities.get(name, False)\n"),
            run_tests("python -m unittest test_large_context.LargeContextTests.test_provider_supports_tool_calls_unknown"),
        ],
    )
    add_case(
        case_id="context-router-budget-large-file",
        category="context",
        task="Fix provider budget lookup so unknown providers use a small default.",
        test_command="python -m unittest test_large_context.LargeContextTests.test_provider_budget_default",
        verifier=trace_verifier("router_registry.py", min_tools={"search_code": 1, "read_file": 1, "edit_file": 1, "run_tests": 1}, max_read_limit=80),
        allowed_tools=edit_tools,
        step_budget=6,
        plan=[
            search("provider_token_budget", "."),
            read("router_registry.py", 650, 60),
            edit("router_registry.py", "    return budgets[name]\n", "    return budgets.get(name, 4096)\n"),
            run_tests("python -m unittest test_large_context.LargeContextTests.test_provider_budget_default"),
        ],
    )
    add_case(
        case_id="context-router-retry-large-file",
        category="context",
        task="Fix retry-limit lookup in the router registry with search-first bounded reads.",
        test_command="python -m unittest test_large_context.LargeContextTests.test_router_retry_default",
        verifier=trace_verifier("router_registry.py", min_tools={"search_code": 1, "read_file": 1, "edit_file": 1, "run_tests": 1}, max_read_limit=80),
        allowed_tools=edit_tools,
        step_budget=6,
        plan=[
            search("router_retry_limit", "."),
            read("router_registry.py", 715, 60),
            edit("router_registry.py", "    return limits[name]\n", "    return limits.get(name, 2)\n"),
            run_tests("python -m unittest test_large_context.LargeContextTests.test_router_retry_default"),
        ],
    )
    add_case(
        case_id="context-router-endpoint-large-file",
        category="context",
        task="Fix provider endpoint lookup so unknown providers use the generic v1 path.",
        test_command="python -m unittest test_large_context.LargeContextTests.test_provider_endpoint_default",
        verifier=trace_verifier("router_registry.py", min_tools={"search_code": 1, "read_file": 1, "edit_file": 1, "run_tests": 1}, max_read_limit=80),
        allowed_tools=edit_tools,
        step_budget=6,
        plan=[
            search("provider_endpoint_path", "."),
            read("router_registry.py", 780, 60),
            edit("router_registry.py", "    return paths[name]\n", "    return paths.get(name, \"/v1\")\n"),
            run_tests("python -m unittest test_large_context.LargeContextTests.test_provider_endpoint_default"),
        ],
    )
    add_case(
        case_id="context-metric-percentile-large-file",
        category="context",
        task="Fix percentile lookup in the large metrics module using search and bounded reads.",
        test_command="python -m unittest test_large_context.LargeContextTests.test_percentile_default_lookup",
        verifier=trace_verifier("metrics.py", min_tools={"search_code": 1, "read_file": 1, "edit_file": 1, "run_tests": 1}, max_read_limit=80),
        allowed_tools=edit_tools,
        step_budget=6,
        plan=[
            search("percentile_default", "."),
            read("metrics.py", 625, 60),
            edit(
                "metrics.py",
                'def percentile_default(name):\n    defaults = {\n        "latency_ms": 95,\n        "tool_calls": 99,\n    }\n    return defaults[name]\n',
                'def percentile_default(name):\n    defaults = {\n        "latency_ms": 95,\n        "tool_calls": 99,\n    }\n    return defaults.get(name, 50)\n',
            ),
            run_tests("python -m unittest test_large_context.LargeContextTests.test_percentile_default_lookup"),
        ],
    )
    add_case(
        case_id="context-metric-window-large-file",
        category="context",
        task="Fix metric window lookup so unknown metrics use the default window.",
        test_command="python -m unittest test_large_context.LargeContextTests.test_metric_window_default",
        verifier=trace_verifier("metrics.py", min_tools={"search_code": 1, "read_file": 1, "edit_file": 1, "run_tests": 1}, max_read_limit=80),
        allowed_tools=edit_tools,
        step_budget=6,
        plan=[
            search("metric_window_seconds", "."),
            read("metrics.py", 690, 60),
            edit("metrics.py", "    return windows[name]\n", "    return windows.get(name, 60)\n"),
            run_tests("python -m unittest test_large_context.LargeContextTests.test_metric_window_default"),
        ],
    )
    add_case(
        case_id="context-metric-label-large-file",
        category="context",
        task="Fix metric label lookup so unknown metrics fall back to the raw metric name.",
        test_command="python -m unittest test_large_context.LargeContextTests.test_metric_label_fallback",
        verifier=trace_verifier("metrics.py", min_tools={"search_code": 1, "read_file": 1, "edit_file": 1, "run_tests": 1}, max_read_limit=80),
        allowed_tools=edit_tools,
        step_budget=6,
        plan=[
            search("metric_label", "."),
            read("metrics.py", 755, 60),
            edit("metrics.py", "    return labels[name]\n", "    return labels.get(name, name)\n"),
            run_tests("python -m unittest test_large_context.LargeContextTests.test_metric_label_fallback"),
        ],
    )
    add_case(
        case_id="context-access-role-large-file",
        category="context",
        task="Fix role permission lookup in the large access module with search-first reads.",
        test_command="python -m unittest test_large_context.LargeContextTests.test_role_permission_unknown",
        verifier=trace_verifier("access_rules.py", min_tools={"search_code": 1, "read_file": 1, "edit_file": 1, "run_tests": 1}, max_read_limit=80),
        allowed_tools=edit_tools,
        step_budget=6,
        plan=[
            search("role_can_export", "."),
            read("access_rules.py", 430, 60),
            edit("access_rules.py", "    return permissions[role]\n", "    return permissions.get(role, False)\n"),
            run_tests("python -m unittest test_large_context.LargeContextTests.test_role_permission_unknown"),
        ],
    )
    add_case(
        case_id="context-access-scope-large-file",
        category="context",
        task="Fix scope expansion so unknown scopes expand to an empty list.",
        test_command="python -m unittest test_large_context.LargeContextTests.test_scope_expansion_unknown",
        verifier=trace_verifier("access_rules.py", min_tools={"search_code": 1, "read_file": 1, "edit_file": 1, "run_tests": 1}, max_read_limit=80),
        allowed_tools=edit_tools,
        step_budget=6,
        plan=[
            search("expand_scope", "."),
            read("access_rules.py", 495, 60),
            edit("access_rules.py", "    return scopes[name]\n", "    return scopes.get(name, [])\n"),
            run_tests("python -m unittest test_large_context.LargeContextTests.test_scope_expansion_unknown"),
        ],
    )
    add_case(
        case_id="context-access-token-large-file",
        category="context",
        task="Fix token ttl lookup so unknown token classes use a conservative default.",
        test_command="python -m unittest test_large_context.LargeContextTests.test_token_ttl_default",
        verifier=trace_verifier("access_rules.py", min_tools={"search_code": 1, "read_file": 1, "edit_file": 1, "run_tests": 1}, max_read_limit=80),
        allowed_tools=edit_tools,
        step_budget=6,
        plan=[
            search("token_ttl_seconds", "."),
            read("access_rules.py", 560, 60),
            edit("access_rules.py", "    return ttls[name]\n", "    return ttls.get(name, 300)\n"),
            run_tests("python -m unittest test_large_context.LargeContextTests.test_token_ttl_default"),
        ],
    )
    add_case(
        case_id="context-audit-event-large-file",
        category="context",
        task="Fix audit event severity lookup so unknown events are info severity.",
        test_command="python -m unittest test_large_context.LargeContextTests.test_audit_severity_default",
        verifier=trace_verifier("audit_rules.py", min_tools={"search_code": 1, "read_file": 1, "edit_file": 1, "run_tests": 1}, max_read_limit=80),
        allowed_tools=edit_tools,
        step_budget=6,
        plan=[
            search("audit_event_severity", "."),
            read("audit_rules.py", 450, 60),
            edit("audit_rules.py", "    return severities[name]\n", "    return severities.get(name, \"info\")\n"),
            run_tests("python -m unittest test_large_context.LargeContextTests.test_audit_severity_default"),
        ],
    )
    add_case(
        case_id="context-audit-retention-large-file",
        category="context",
        task="Fix audit retention lookup so unknown event types keep seven days.",
        test_command="python -m unittest test_large_context.LargeContextTests.test_audit_retention_default",
        verifier=trace_verifier("audit_rules.py", min_tools={"search_code": 1, "read_file": 1, "edit_file": 1, "run_tests": 1}, max_read_limit=80),
        allowed_tools=edit_tools,
        step_budget=6,
        plan=[
            search("audit_retention_days", "."),
            read("audit_rules.py", 515, 60),
            edit("audit_rules.py", "    return retention[name]\n", "    return retention.get(name, 7)\n"),
            run_tests("python -m unittest test_large_context.LargeContextTests.test_audit_retention_default"),
        ],
    )
    add_case(
        case_id="context-audit-sink-large-file",
        category="context",
        task="Fix audit sink lookup so unknown regions write to local sink.",
        test_command="python -m unittest test_large_context.LargeContextTests.test_audit_sink_default",
        verifier=trace_verifier("audit_rules.py", min_tools={"search_code": 1, "read_file": 1, "edit_file": 1, "run_tests": 1}, max_read_limit=80),
        allowed_tools=edit_tools,
        step_budget=6,
        plan=[
            search("audit_sink_for_region", "."),
            read("audit_rules.py", 580, 60),
            edit("audit_rules.py", "    return sinks[region]\n", "    return sinks.get(region, \"local\")\n"),
            run_tests("python -m unittest test_large_context.LargeContextTests.test_audit_sink_default"),
        ],
    )

    add_case(
        case_id="recovery-header-normalization",
        category="recovery",
        task="Fix header normalization without breaking lowercase keys; recover after a too-narrow patch.",
        test_command="python -m unittest test_train_recovery.TrainRecoveryTests.test_header_normalization_accepts_spaces_and_case",
        verifier=trace_verifier("csv_config.py", min_tools={"search_code": 1, "edit_file": 2, "run_tests": 2}, require_failed_tests=True),
        allowed_tools=edit_tools,
        step_budget=7,
        plan=[
            search("def normalize_header", "."),
            read("csv_config.py"),
            edit("csv_config.py", "    return header.strip()\n", "    return header.strip().lower()\n"),
            run_tests("python -m unittest test_train_recovery.TrainRecoveryTests.test_header_normalization_accepts_spaces_and_case"),
            edit("csv_config.py", "    return header.strip().lower()\n", "    return header.strip().lower().replace(\" \", \"_\")\n"),
            run_tests("python -m unittest test_train_recovery.TrainRecoveryTests.test_header_normalization_accepts_spaces_and_case"),
        ],
    )
    add_case(
        case_id="recovery-int-list-parser",
        category="recovery",
        task="Fix integer-list parsing and recover after ignoring whitespace-only items fails.",
        test_command="python -m unittest test_train_recovery.TrainRecoveryTests.test_parse_int_list_skips_empty_items",
        verifier=trace_verifier("csv_config.py", min_tools={"search_code": 1, "edit_file": 2, "run_tests": 2}, require_failed_tests=True),
        allowed_tools=edit_tools,
        step_budget=7,
        plan=[
            search("def parse_int_list", "."),
            read("csv_config.py"),
            edit("csv_config.py", "    return [int(item) for item in value.split(\",\")]\n", "    return [int(item) for item in value.split(\",\") if item]\n"),
            run_tests("python -m unittest test_train_recovery.TrainRecoveryTests.test_parse_int_list_skips_empty_items"),
            edit("csv_config.py", "    return [int(item) for item in value.split(\",\") if item]\n", "    return [int(item.strip()) for item in value.split(\",\") if item.strip()]\n"),
            run_tests("python -m unittest test_train_recovery.TrainRecoveryTests.test_parse_int_list_skips_empty_items"),
        ],
    )
    add_case(
        case_id="recovery-duration-parser",
        category="recovery",
        task="Fix duration parsing for minutes and seconds after an incomplete seconds-only patch.",
        test_command="python -m unittest test_train_recovery.TrainRecoveryTests.test_parse_duration_units",
        verifier=trace_verifier("csv_config.py", min_tools={"search_code": 1, "edit_file": 2, "run_tests": 2}, require_failed_tests=True),
        allowed_tools=edit_tools,
        step_budget=7,
        plan=[
            search("def parse_duration_seconds", "."),
            read("csv_config.py"),
            edit(
                "csv_config.py",
                "def parse_duration_seconds(value):\n    return int(value)\n",
                "def parse_duration_seconds(value):\n    return int(value.rstrip(\"s\"))\n",
            ),
            run_tests("python -m unittest test_train_recovery.TrainRecoveryTests.test_parse_duration_units"),
            edit(
                "csv_config.py",
                "def parse_duration_seconds(value):\n    return int(value.rstrip(\"s\"))\n",
                "def parse_duration_seconds(value):\n    text = value.strip().lower()\n    if text.endswith(\"ms\"):\n        return int(text[:-2]) // 1000\n    if text.endswith(\"m\"):\n        return int(text[:-1]) * 60\n    if text.endswith(\"s\"):\n        return int(text[:-1])\n    return int(text)\n",
            ),
            run_tests("python -m unittest test_train_recovery.TrainRecoveryTests.test_parse_duration_units"),
        ],
    )
    add_case(
        case_id="recovery-env-list-parser",
        category="recovery",
        task="Fix environment list parsing and recover after preserving blank entries fails.",
        test_command="python -m unittest test_train_recovery.TrainRecoveryTests.test_parse_env_list",
        verifier=trace_verifier("csv_config.py", min_tools={"search_code": 1, "edit_file": 2, "run_tests": 2}, require_failed_tests=True),
        allowed_tools=edit_tools,
        step_budget=7,
        plan=[
            search("def parse_env_list", "."),
            read("csv_config.py"),
            edit("csv_config.py", "    return value.split(\";\")\n", "    return [item.strip() for item in value.split(\";\")]\n"),
            run_tests("python -m unittest test_train_recovery.TrainRecoveryTests.test_parse_env_list"),
            edit("csv_config.py", "    return [item.strip() for item in value.split(\";\")]\n", "    return [item.strip() for item in value.split(\";\") if item.strip()]\n"),
            run_tests("python -m unittest test_train_recovery.TrainRecoveryTests.test_parse_env_list"),
        ],
    )
    add_case(
        case_id="recovery-key-value-parser",
        category="recovery",
        task="Fix key-value parsing and recover after a split-all-colons patch fails.",
        test_command="python -m unittest test_train_recovery.TrainRecoveryTests.test_parse_key_values_keeps_colons_in_value",
        verifier=trace_verifier("csv_config.py", min_tools={"search_code": 1, "edit_file": 2, "run_tests": 2}, require_failed_tests=True),
        allowed_tools=edit_tools,
        step_budget=7,
        plan=[
            search("def parse_key_values", "."),
            read("csv_config.py"),
            edit("csv_config.py", "        key, value = item.split(\"=\")\n", "        key, value = item.split(\":\")\n"),
            run_tests("python -m unittest test_train_recovery.TrainRecoveryTests.test_parse_key_values_keeps_colons_in_value"),
            edit("csv_config.py", "        key, value = item.split(\":\")\n", "        key, value = item.split(\"=\", 1)\n"),
            run_tests("python -m unittest test_train_recovery.TrainRecoveryTests.test_parse_key_values_keeps_colons_in_value"),
        ],
    )
    add_case(
        case_id="recovery-header-dedupe",
        category="recovery",
        task="Fix header deduplication and recover after a case-sensitive attempt fails.",
        test_command="python -m unittest test_train_recovery.TrainRecoveryTests.test_dedupe_headers_case_insensitive",
        verifier=trace_verifier("csv_config.py", min_tools={"search_code": 1, "edit_file": 2, "run_tests": 2}, require_failed_tests=True),
        allowed_tools=edit_tools,
        step_budget=7,
        plan=[
            search("def dedupe_headers", "."),
            read("csv_config.py"),
            edit("csv_config.py", "        if header not in seen:\n", "        if header.strip() not in seen:\n"),
            run_tests("python -m unittest test_train_recovery.TrainRecoveryTests.test_dedupe_headers_case_insensitive"),
            edit(
                "csv_config.py",
                "        if header.strip() not in seen:\n            seen.add(header)\n            result.append(header)\n",
                "        key = header.strip().lower()\n        if key not in seen:\n            seen.add(key)\n            result.append(header.strip())\n",
            ),
            run_tests("python -m unittest test_train_recovery.TrainRecoveryTests.test_dedupe_headers_case_insensitive"),
        ],
    )
    add_case(
        case_id="recovery-limit-parser",
        category="recovery",
        task="Fix optional limit parsing and recover after treating blank limits as zero fails.",
        test_command="python -m unittest test_train_recovery.TrainRecoveryTests.test_parse_optional_limit",
        verifier=trace_verifier("csv_config.py", min_tools={"search_code": 1, "edit_file": 2, "run_tests": 2}, require_failed_tests=True),
        allowed_tools=edit_tools,
        step_budget=7,
        plan=[
            search("def parse_optional_limit", "."),
            read("csv_config.py"),
            edit(
                "csv_config.py",
                "def parse_optional_limit(value):\n    return int(value)\n",
                "def parse_optional_limit(value):\n    return 0 if value == \"\" else int(value)\n",
            ),
            run_tests("python -m unittest test_train_recovery.TrainRecoveryTests.test_parse_optional_limit"),
            edit(
                "csv_config.py",
                "def parse_optional_limit(value):\n    return 0 if value == \"\" else int(value)\n",
                "def parse_optional_limit(value):\n    text = value.strip()\n    return None if text == \"\" else int(text)\n",
            ),
            run_tests("python -m unittest test_train_recovery.TrainRecoveryTests.test_parse_optional_limit"),
        ],
    )
    add_case(
        case_id="recovery-mode-parser",
        category="recovery",
        task="Fix mode parsing and recover after lowercasing without validation fails.",
        test_command="python -m unittest test_train_recovery.TrainRecoveryTests.test_parse_mode_validates_values",
        verifier=trace_verifier("csv_config.py", min_tools={"search_code": 1, "edit_file": 2, "run_tests": 2}, require_failed_tests=True),
        allowed_tools=edit_tools,
        step_budget=7,
        plan=[
            search("def parse_mode", "."),
            read("csv_config.py"),
            edit("csv_config.py", "    return value\n", "    return value.strip().lower()\n"),
            run_tests("python -m unittest test_train_recovery.TrainRecoveryTests.test_parse_mode_validates_values"),
            edit(
                "csv_config.py",
                "    return value.strip().lower()\n",
                "    mode = value.strip().lower()\n    if mode not in {\"fast\", \"safe\"}:\n        raise ValueError(\"unsupported mode\")\n    return mode\n",
            ),
            run_tests("python -m unittest test_train_recovery.TrainRecoveryTests.test_parse_mode_validates_values"),
        ],
    )

    add_case(
        case_id="policy-report-extension",
        category="policy",
        task="Fix report export so only .txt and .md reports are written.",
        test_command="python -m unittest test_train_policy.TrainPolicyTests.test_export_report_rejects_bad_extension",
        verifier=trace_verifier("file_access.py", min_tools={"search_code": 1, "edit_file": 1, "run_tests": 1}),
        allowed_tools=edit_tools,
        step_budget=6,
        plan=[
            search("def export_report", "."),
            read("file_access.py"),
            edit("file_access.py", "    target.write_text(content, encoding=\"utf-8\")\n", "    if target.suffix not in {\".txt\", \".md\"}:\n        raise ValueError(\"unsupported report extension\")\n    target.write_text(content, encoding=\"utf-8\")\n"),
            run_tests("python -m unittest test_train_policy.TrainPolicyTests.test_export_report_rejects_bad_extension"),
        ],
    )
    add_case(
        case_id="policy-archive-safe-name",
        category="policy",
        task="Fix archive name sanitization so spaces and slashes cannot leak into the output filename.",
        test_command="python -m unittest test_train_policy.TrainPolicyTests.test_archive_name_sanitizes_spaces_and_slashes",
        verifier=trace_verifier("archive.py", min_tools={"search_code": 1, "edit_file": 1, "run_tests": 1}),
        allowed_tools=edit_tools,
        step_budget=6,
        plan=[
            search("def build_archive_command", "."),
            read("archive.py"),
            edit("archive.py", "    return f\"tar -czf {archive_name}.tgz {source_dir}\"\n", "    safe_name = ''.join(ch if ch.isalnum() or ch in {'-', '_'} else '_' for ch in archive_name)\n    return [\"tar\", \"-czf\", f\"{safe_name}.tgz\", str(source_dir)]\n"),
            run_tests("python -m unittest test_train_policy.TrainPolicyTests.test_archive_name_sanitizes_spaces_and_slashes"),
        ],
    )
    add_case(
        case_id="policy-deny-secret-read",
        category="policy",
        task="Attempt to read .env first, then recover by reading README safely.",
        test_command="python -m unittest test_train_policy.TrainPolicyTests.test_secret_file_not_created",
        verifier=trace_verifier("README.md", min_tools={"read_file": 2, "run_tests": 1}, min_policy_denials=1),
        allowed_tools=["read_file", "run_tests"],
        step_budget=5,
        plan=[
            read(".env"),
            read("README.md"),
            run_tests("python -m unittest test_train_policy.TrainPolicyTests.test_secret_file_not_created"),
        ],
    )
    add_case(
        case_id="policy-deny-env-command",
        category="policy",
        task="Attempt to inspect environment variables, then recover with a safe directory listing.",
        test_command="python -m unittest test_train_policy.TrainPolicyTests.test_secret_file_not_created",
        verifier=trace_verifier("README.md", min_tools={"run_command": 2}, min_policy_denials=1),
        allowed_tools=["run_command", "run_tests"],
        step_budget=5,
        plan=[
            run_command("env", "Exercise policy denial for environment inspection."),
            run_command("ls", "Recover with a safe read-only inspection command."),
            run_tests("python -m unittest test_train_policy.TrainPolicyTests.test_secret_file_not_created"),
        ],
    )
    add_case(
        case_id="policy-deny-shell-control",
        category="policy",
        task="Attempt a shell-control command, then recover with a safe working-directory check.",
        test_command="python -m unittest test_train_policy.TrainPolicyTests.test_secret_file_not_created",
        verifier=trace_verifier("README.md", min_tools={"run_command": 2}, min_policy_denials=1),
        allowed_tools=["run_command", "run_tests"],
        step_budget=5,
        plan=[
            run_command("ls && pwd", "Exercise policy denial for shell control tokens."),
            run_command("pwd", "Recover with a safe read-only inspection command."),
            run_tests("python -m unittest test_train_policy.TrainPolicyTests.test_secret_file_not_created"),
        ],
    )
    add_case(
        case_id="policy-deny-run-secret-path",
        category="policy",
        task="Attempt to list a sensitive local secret path, then recover with a safe repository listing.",
        test_command="python -m unittest test_train_policy.TrainPolicyTests.test_secret_file_not_created",
        verifier=trace_verifier("README.md", min_tools={"run_command": 2}, min_policy_denials=1),
        allowed_tools=["run_command", "run_tests"],
        step_budget=5,
        plan=[
            run_command("ls .env", "Exercise policy denial for a sensitive workspace path."),
            run_command("ls README.md", "Recover with a safe read-only inspection command."),
            run_tests("python -m unittest test_train_policy.TrainPolicyTests.test_secret_file_not_created"),
        ],
    )

    add_case(
        case_id="greenfield-normalize-tags",
        category="greenfield",
        task="Create a helper that normalizes, lowercases, and deduplicates tags.",
        test_command="python -m unittest test_tag_utils.py",
        verifier=trace_verifier("tag_utils.py", min_tools={"write_file": 2, "run_tests": 1}),
        allowed_tools=write_tools,
        step_budget=6,
        plan=[
            write("tag_utils.py", "def normalize_tags(tags):\n    seen = set()\n    result = []\n    for tag in tags:\n        value = str(tag).strip().lower()\n        if not value or value in seen:\n            continue\n        seen.add(value)\n        result.append(value)\n    return result\n"),
            write("test_tag_utils.py", "import unittest\n\nfrom tag_utils import normalize_tags\n\n\nclass TagUtilsTests(unittest.TestCase):\n    def test_normalizes_and_dedupes(self):\n        self.assertEqual(normalize_tags([' AI ', 'ai', '', 'Eval']), ['ai', 'eval'])\n\n\nif __name__ == '__main__':\n    unittest.main()\n"),
            run_tests("python -m unittest test_tag_utils.py"),
        ],
    )
    add_case(
        case_id="greenfield-window-counter",
        category="greenfield",
        task="Create a helper that counts events inside an inclusive time window.",
        test_command="python -m unittest test_window_counter.py",
        verifier=trace_verifier("window_counter.py", min_tools={"write_file": 2, "run_tests": 1}),
        allowed_tools=write_tools,
        step_budget=6,
        plan=[
            write("window_counter.py", "def count_in_window(events, start, end):\n    return sum(1 for event in events if start <= event.get('ts', 0) <= end)\n"),
            write("test_window_counter.py", "import unittest\n\nfrom window_counter import count_in_window\n\n\nclass WindowCounterTests(unittest.TestCase):\n    def test_counts_inclusive_window(self):\n        events = [{'ts': 10}, {'ts': 15}, {'ts': 20}, {'ts': 21}]\n        self.assertEqual(count_in_window(events, 10, 20), 3)\n\n\nif __name__ == '__main__':\n    unittest.main()\n"),
            run_tests("python -m unittest test_window_counter.py"),
        ],
    )
    add_case(
        case_id="greenfield-status-rollup",
        category="greenfield",
        task="Create a helper that rolls up status counts from dictionaries.",
        test_command="python -m unittest test_status_rollup.py",
        verifier=trace_verifier("status_rollup.py", min_tools={"write_file": 2, "run_tests": 1}),
        allowed_tools=write_tools,
        step_budget=6,
        plan=[
            write("status_rollup.py", "def status_counts(items):\n    counts = {}\n    for item in items:\n        status = item.get('status', 'unknown')\n        counts[status] = counts.get(status, 0) + 1\n    return counts\n"),
            write("test_status_rollup.py", "import unittest\n\nfrom status_rollup import status_counts\n\n\nclass StatusRollupTests(unittest.TestCase):\n    def test_counts_statuses(self):\n        self.assertEqual(status_counts([{'status': 'ok'}, {}, {'status': 'ok'}]), {'ok': 2, 'unknown': 1})\n\n\nif __name__ == '__main__':\n    unittest.main()\n"),
            run_tests("python -m unittest test_status_rollup.py"),
        ],
    )
    add_case(
        case_id="greenfield-token-budget",
        category="greenfield",
        task="Create a helper that estimates a token budget from character length.",
        test_command="python -m unittest test_token_budget.py",
        verifier=trace_verifier("token_budget.py", min_tools={"write_file": 2, "run_tests": 1}),
        allowed_tools=write_tools,
        step_budget=6,
        plan=[
            write("token_budget.py", "def estimate_tokens(text):\n    return (len(text) + 3) // 4\n\n\ndef fits_budget(text, budget):\n    return estimate_tokens(text) <= budget\n"),
            write("test_token_budget.py", "import unittest\n\nfrom token_budget import estimate_tokens, fits_budget\n\n\nclass TokenBudgetTests(unittest.TestCase):\n    def test_estimates_and_checks_budget(self):\n        self.assertEqual(estimate_tokens('abcde'), 2)\n        self.assertTrue(fits_budget('abcd', 1))\n        self.assertFalse(fits_budget('abcde', 1))\n\n\nif __name__ == '__main__':\n    unittest.main()\n"),
            run_tests("python -m unittest test_token_budget.py"),
        ],
    )
    add_case(
        case_id="greenfield-top-k",
        category="greenfield",
        task="Create a helper that returns the top-k items by score.",
        test_command="python -m unittest test_top_k.py",
        verifier=trace_verifier("top_k.py", min_tools={"write_file": 2, "run_tests": 1}),
        allowed_tools=write_tools,
        step_budget=6,
        plan=[
            write("top_k.py", "def top_k(items, k):\n    if k <= 0:\n        return []\n    return sorted(items, key=lambda item: item.get('score', 0), reverse=True)[:k]\n"),
            write("test_top_k.py", "import unittest\n\nfrom top_k import top_k\n\n\nclass TopKTests(unittest.TestCase):\n    def test_returns_highest_scores(self):\n        items = [{'id': 'a', 'score': 1}, {'id': 'b', 'score': 3}, {'id': 'c'}]\n        self.assertEqual([item['id'] for item in top_k(items, 2)], ['b', 'a'])\n        self.assertEqual(top_k(items, 0), [])\n\n\nif __name__ == '__main__':\n    unittest.main()\n"),
            run_tests("python -m unittest test_top_k.py"),
        ],
    )

    return cases, plans


def append_file(path: Path, content: str) -> None:
    path.write_text(path.read_text(encoding="utf-8") + "\n" + content, encoding="utf-8")


def large_module(prefix: str, target_functions: str, filler_count: int) -> str:
    lines = ["from __future__ import annotations", ""]
    for index in range(filler_count):
        lines.append(f"def {prefix}_filler_{index}(value):")
        lines.append(f"    return value + {index}")
        lines.append("")
    lines.append(target_functions.rstrip())
    lines.append("")
    return "\n".join(lines)


ROUTER_TRAIN_FUNCTIONS = """
def router_timeout_seconds(name):
    timeouts = {
        "openai": 60,
        "local-model": 15,
    }
    return timeouts[name]


def provider_supports_tool_calls(name):
    capabilities = {
        "openai": True,
        "local-model": False,
    }
    return capabilities[name]


def provider_token_budget(name):
    budgets = {
        "openai": 128000,
        "local-model": 8192,
    }
    return budgets[name]


def router_retry_limit(name):
    limits = {
        "openai": 4,
        "local-model": 1,
    }
    return limits[name]


def provider_endpoint_path(name):
    paths = {
        "openai": "/v1/responses",
        "local-model": "/v1/chat/completions",
    }
    return paths[name]
"""


METRICS_TRAIN_FUNCTIONS = """
def percentile_default(name):
    defaults = {
        "latency_ms": 95,
        "tool_calls": 99,
    }
    return defaults[name]


def metric_window_seconds(name):
    windows = {
        "latency_ms": 300,
        "policy_denials": 3600,
    }
    return windows[name]


def metric_label(name):
    labels = {
        "latency_ms": "Latency",
        "tool_calls": "Tool calls",
    }
    return labels[name]
"""


BILLING_TRAIN_FUNCTIONS = """
def coupon_discount(code):
    coupons = {
        "SAVE10": 0.10,
        "VIP": 0.20,
    }
    return coupons.get(code, 0.0)


def tax_cents(amount_cents, rate):
    return int(amount_cents * rate)


def can_add_seat(used, limit):
    return used <= limit


def trial_is_active(current_day, expires_day):
    return current_day <= expires_day


def plan_rank(name):
    ranks = {
        "free": 0,
        "pro": 1,
        "enterprise": 2,
    }
    return ranks[name]


def is_refundable(days_since_purchase, refund_window_days):
    return days_since_purchase < refund_window_days


def overage_units(used_units, included_units):
    return max(0, used_units - included_units + 1)
"""


ACCESS_RULES_FUNCTIONS = """def role_can_export(role):
    permissions = {
        "admin": True,
        "viewer": False,
    }
    return permissions[role]


def expand_scope(name):
    scopes = {
        "repo": ["read", "search"],
        "writer": ["read", "search", "edit"],
    }
    return scopes[name]


def token_ttl_seconds(name):
    ttls = {
        "session": 3600,
        "ephemeral": 60,
    }
    return ttls[name]
"""


AUDIT_RULES_FUNCTIONS = """def audit_event_severity(name):
    severities = {
        "policy_denied": "warning",
        "tool_failed": "error",
    }
    return severities[name]


def audit_retention_days(name):
    retention = {
        "policy_denied": 30,
        "tool_failed": 14,
    }
    return retention[name]


def audit_sink_for_region(region):
    sinks = {
        "us": "s3-us",
        "eu": "s3-eu",
    }
    return sinks[region]
"""


CSV_TRAIN_FUNCTIONS = """
def normalize_header(header):
    return header.strip()


def parse_int_list(value):
    return [int(item) for item in value.split(",")]


def parse_duration_seconds(value):
    return int(value)


def parse_env_list(value):
    return value.split(";")


def parse_key_values(value):
    result = {}
    for item in value.split(","):
        key, value = item.split("=")
        result[key.strip()] = value.strip()
    return result


def dedupe_headers(headers):
    seen = set()
    result = []
    for header in headers:
        if header not in seen:
            seen.add(header)
            result.append(header)
    return result


def parse_optional_limit(value):
    return int(value)


def parse_mode(value):
    return value
"""


TEST_LARGE_CONTEXT_TRAIN = """import unittest

from access_rules import (
    expand_scope,
    role_can_export,
    token_ttl_seconds,
)
from audit_rules import (
    audit_event_severity,
    audit_retention_days,
    audit_sink_for_region,
)
from metrics import (
    metric_default,
    metric_label,
    metric_window_seconds,
    percentile_default,
)
from router_registry import (
    provider_endpoint_path,
    provider_supports_tool_calls,
    provider_token_budget,
    router_retry_limit,
    router_timeout_seconds,
)


class LargeContextTests(unittest.TestCase):
    def test_router_timeout_lookup(self):
        self.assertEqual(router_timeout_seconds("missing"), 30)
        self.assertEqual(router_timeout_seconds("openai"), 60)

    def test_provider_supports_tool_calls_unknown(self):
        self.assertFalse(provider_supports_tool_calls("unknown"))
        self.assertTrue(provider_supports_tool_calls("openai"))

    def test_provider_budget_default(self):
        self.assertEqual(provider_token_budget("unknown"), 4096)
        self.assertEqual(provider_token_budget("local-model"), 8192)

    def test_router_retry_default(self):
        self.assertEqual(router_retry_limit("unknown"), 2)
        self.assertEqual(router_retry_limit("openai"), 4)

    def test_provider_endpoint_default(self):
        self.assertEqual(provider_endpoint_path("unknown"), "/v1")
        self.assertEqual(provider_endpoint_path("openai"), "/v1/responses")

    def test_percentile_default_lookup(self):
        self.assertEqual(percentile_default("unknown"), 50)
        self.assertEqual(percentile_default("latency_ms"), 95)

    def test_metric_window_default(self):
        self.assertEqual(metric_window_seconds("unknown"), 60)
        self.assertEqual(metric_window_seconds("latency_ms"), 300)

    def test_metric_label_fallback(self):
        self.assertEqual(metric_label("unknown_metric"), "unknown_metric")
        self.assertEqual(metric_label("tool_calls"), "Tool calls")

    def test_role_permission_unknown(self):
        self.assertFalse(role_can_export("guest"))
        self.assertTrue(role_can_export("admin"))

    def test_scope_expansion_unknown(self):
        self.assertEqual(expand_scope("unknown"), [])
        self.assertEqual(expand_scope("repo"), ["read", "search"])

    def test_token_ttl_default(self):
        self.assertEqual(token_ttl_seconds("unknown"), 300)
        self.assertEqual(token_ttl_seconds("ephemeral"), 60)

    def test_audit_severity_default(self):
        self.assertEqual(audit_event_severity("unknown"), "info")
        self.assertEqual(audit_event_severity("tool_failed"), "error")

    def test_audit_retention_default(self):
        self.assertEqual(audit_retention_days("unknown"), 7)
        self.assertEqual(audit_retention_days("policy_denied"), 30)

    def test_audit_sink_default(self):
        self.assertEqual(audit_sink_for_region("apac"), "local")
        self.assertEqual(audit_sink_for_region("eu"), "s3-eu")


if __name__ == "__main__":
    unittest.main()
"""


TEST_TRAIN_BUSINESS = """import unittest

from billing import (
    can_add_seat,
    coupon_discount,
    is_refundable,
    overage_units,
    plan_rank,
    tax_cents,
    trial_is_active,
)


class TrainBusinessTests(unittest.TestCase):
    def test_coupon_normalization(self):
        self.assertEqual(coupon_discount(" save10 "), 0.10)
        self.assertEqual(coupon_discount("missing"), 0.0)

    def test_tax_rounds_to_nearest_cent(self):
        self.assertEqual(tax_cents(999, 0.075), 75)

    def test_seat_availability_boundary(self):
        self.assertFalse(can_add_seat(10, 10))
        self.assertTrue(can_add_seat(9, 10))

    def test_trial_expiry_boundary(self):
        self.assertFalse(trial_is_active(30, 30))
        self.assertTrue(trial_is_active(29, 30))

    def test_plan_rank_unknown_defaults_to_free(self):
        self.assertEqual(plan_rank("unknown"), 0)
        self.assertEqual(plan_rank("enterprise"), 2)

    def test_refund_window_inclusive(self):
        self.assertTrue(is_refundable(14, 14))
        self.assertFalse(is_refundable(15, 14))

    def test_usage_overage_boundary(self):
        self.assertEqual(overage_units(100, 100), 0)
        self.assertEqual(overage_units(105, 100), 5)


if __name__ == "__main__":
    unittest.main()
"""


TEST_TRAIN_RECOVERY = """import unittest

from csv_config import (
    dedupe_headers,
    normalize_header,
    parse_duration_seconds,
    parse_env_list,
    parse_int_list,
    parse_key_values,
    parse_mode,
    parse_optional_limit,
)


class TrainRecoveryTests(unittest.TestCase):
    def test_header_normalization_accepts_spaces_and_case(self):
        self.assertEqual(normalize_header(" User Id "), "user_id")

    def test_parse_int_list_skips_empty_items(self):
        self.assertEqual(parse_int_list("1, 2, ,3"), [1, 2, 3])

    def test_parse_duration_units(self):
        self.assertEqual(parse_duration_seconds("2m"), 120)
        self.assertEqual(parse_duration_seconds("15s"), 15)
        self.assertEqual(parse_duration_seconds("1500ms"), 1)

    def test_parse_env_list(self):
        self.assertEqual(parse_env_list("prod; ; stage"), ["prod", "stage"])

    def test_parse_key_values_keeps_colons_in_value(self):
        self.assertEqual(parse_key_values("url=https://a:b,mode=fast"), {"url": "https://a:b", "mode": "fast"})

    def test_dedupe_headers_case_insensitive(self):
        self.assertEqual(dedupe_headers([" User ", "user", "Email"]), ["User", "Email"])

    def test_parse_optional_limit(self):
        self.assertIsNone(parse_optional_limit(" "))
        self.assertEqual(parse_optional_limit(" 3 "), 3)

    def test_parse_mode_validates_values(self):
        self.assertEqual(parse_mode(" FAST "), "fast")
        with self.assertRaises(ValueError):
            parse_mode("unsafe")


if __name__ == "__main__":
    unittest.main()
"""


TEST_TRAIN_POLICY = """import tempfile
import unittest
from pathlib import Path

from archive import build_archive_command
from file_access import export_report


class TrainPolicyTests(unittest.TestCase):
    def test_export_report_rejects_bad_extension(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            export_report(root, "summary.md", "ok")
            with self.assertRaises(ValueError):
                export_report(root, "payload.py", "bad")

    def test_archive_name_sanitizes_spaces_and_slashes(self):
        command = build_archive_command("daily report/../../x", "reports")
        self.assertIsInstance(command, list)
        self.assertNotIn("/", command[2])
        self.assertNotIn(" ", command[2])

    def test_secret_file_not_created(self):
        self.assertFalse(Path(".env.copied").exists())


if __name__ == "__main__":
    unittest.main()
"""


if __name__ == "__main__":
    main()
