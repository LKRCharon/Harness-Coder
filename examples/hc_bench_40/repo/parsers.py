from __future__ import annotations


def parse_semver(value):
    major, minor, patch = value.split(".")
    return int(major), int(minor), int(patch)


def parse_key_value_lines(text):
    result = {}
    for raw in text.splitlines():
        key, value = raw.split("=")
        result[key.strip()] = value.strip()
    return result


def parse_ranges(text):
    ranges = []
    for chunk in text.split(","):
        start, end = chunk.split("-")
        ranges.append((int(start), int(end)))
    return ranges
