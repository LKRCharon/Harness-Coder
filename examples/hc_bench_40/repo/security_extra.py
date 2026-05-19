from __future__ import annotations


def redact_headers(headers):
    return dict(headers)


def build_checkout_command(ref):
    return f"git checkout {ref}"
