from __future__ import annotations


def order_tasks(tasks):
    return sorted(tasks, key=lambda task: task.get("priority", 0))
