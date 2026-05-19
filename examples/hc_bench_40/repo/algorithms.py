from __future__ import annotations


def merge_intervals(intervals):
    merged = []
    for start, end in sorted(intervals):
        if not merged or start >= merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return [tuple(item) for item in merged]


def topological_order(edges):
    nodes = set(edges)
    indegree = {node: 0 for node in nodes}
    children = {node: [] for node in nodes}
    for node, deps in edges.items():
        for dep in deps:
            indegree[node] += 1
            children.setdefault(dep, []).append(node)

    ready = sorted(node for node, degree in indegree.items() if degree == 0)
    order = []
    while ready:
        node = ready.pop(0)
        order.append(node)
        for child in children.get(node, []):
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
                ready.sort()
    return order


def json_pointer_get(document, pointer):
    parts = pointer.strip("/").split("/")
    current = document
    for part in parts:
        current = current[part]
    return current
