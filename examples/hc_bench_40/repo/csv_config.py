from __future__ import annotations


def parse_csv_row(line):
    values = []
    for raw in line.split(','):
        value = raw.strip().strip('"')
        values.append(value)
    return values


def parse_bool(value):
    return value.lower() == "yes"


def retry_delays(attempts, base_seconds):
    return [base_seconds * (2 ** attempt) for attempt in range(attempts)]
