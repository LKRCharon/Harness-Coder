import unittest

from billing import (
    is_feature_enabled,
    is_overdue,
    is_sla_breached,
    loyalty_discount,
    page_window,
    prorate_monthly,
    should_dedupe,
)


class BusinessBugTests(unittest.TestCase):
    def test_overdue_timezone_boundary(self):
        self.assertFalse(is_overdue("2026-05-12T09:00:00+08:00", "2026-05-12T09:00:00+08:00"))
        self.assertTrue(is_overdue("2026-05-12T08:59:59+08:00", "2026-05-12T09:00:00+08:00"))
        self.assertFalse(is_overdue("2026-05-12T10:00:00+08:00", "2026-05-12T01:30:00+00:00"))

    def test_discount_thresholds_are_inclusive(self):
        self.assertEqual(loyalty_discount(10), 0.10)
        self.assertEqual(loyalty_discount(5), 0.05)

    def test_proration_rounds_cents(self):
        self.assertEqual(prorate_monthly(1000, 2, 3), 667)

    def test_idempotency_window_uses_time_delta(self):
        self.assertTrue(should_dedupe("k1", {"k1": 95}, 100, 10))
        self.assertFalse(should_dedupe("k1", {"k1": 50}, 100, 10))
        self.assertFalse(should_dedupe("missing", {"k1": 95}, 100, 10))

    def test_pagination_page_one_offset(self):
        self.assertEqual(page_window(1, 25), (0, 25))
        self.assertEqual(page_window(3, 10), (20, 30))

    def test_missing_feature_flag_is_disabled(self):
        self.assertFalse(is_feature_enabled({}, "beta_checkout"))
        self.assertTrue(is_feature_enabled({"beta_checkout": True}, "beta_checkout"))

    def test_sla_threshold_is_not_breach(self):
        self.assertFalse(is_sla_breached(30, 30))
        self.assertTrue(is_sla_breached(31, 30))


if __name__ == "__main__":
    unittest.main()
