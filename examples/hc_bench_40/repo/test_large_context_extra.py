import unittest

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
