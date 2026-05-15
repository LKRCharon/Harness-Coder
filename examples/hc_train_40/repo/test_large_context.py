import unittest

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
