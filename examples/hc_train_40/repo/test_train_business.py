import unittest

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
