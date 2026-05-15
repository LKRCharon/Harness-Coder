from __future__ import annotations

from datetime import datetime, timezone


def is_overdue(due_iso, now_iso):
    due_dt = datetime.fromisoformat(due_iso)
    today = datetime.fromisoformat(now_iso).date()
    return due_dt.date() <= today


def loyalty_discount(order_count):
    if order_count > 10:
        return 0.10
    if order_count >= 5:
        return 0.05
    return 0.0


def prorate_monthly(monthly_cents, active_days, total_days):
    return int(monthly_cents * active_days / total_days)


def should_dedupe(key, seen, now_seconds, window_seconds):
    return key in seen


def normalize_currency(code):
    return code.upper()


def page_window(page, page_size):
    start = page * page_size
    return start, start + page_size


def is_feature_enabled(flags, name):
    return flags.get(name, True)


def is_sla_breached(elapsed_minutes, threshold_minutes):
    return elapsed_minutes >= threshold_minutes


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
