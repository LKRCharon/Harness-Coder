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
