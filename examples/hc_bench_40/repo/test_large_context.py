import unittest

from metrics import metric_default
from router_registry import normalize_provider_name


class LargeContextTests(unittest.TestCase):
    def test_provider_alias_resolution(self):
        self.assertEqual(normalize_provider_name(" OpenAI_Codex "), "openai")
        self.assertEqual(normalize_provider_name("local_model"), "local-model")

    def test_metric_default_lookup(self):
        self.assertEqual(metric_default("unknown_metric"), 0)
        self.assertEqual(metric_default("latency_ms"), 100)


if __name__ == "__main__":
    unittest.main()
