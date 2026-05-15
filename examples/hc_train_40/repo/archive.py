from __future__ import annotations


def build_archive_command(archive_name, source_dir):
    return f"tar -czf {archive_name}.tgz {source_dir}"
