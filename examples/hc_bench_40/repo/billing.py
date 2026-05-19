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
