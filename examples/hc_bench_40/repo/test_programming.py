import unittest

from algorithms import json_pointer_get, merge_intervals, topological_order
from workflow import order_tasks


class ProgrammingBugTests(unittest.TestCase):
    def test_merge_touching_intervals(self):
        self.assertEqual(merge_intervals([(1, 3), (3, 5), (8, 9)]), [(1, 5), (8, 9)])

    def test_toposort_includes_dependency_only_nodes(self):
        order = topological_order({"package": ["build"], "build": ["test"]})
        self.assertEqual(order, ["test", "build", "package"])

    def test_json_pointer_unescapes_tokens(self):
        doc = {"a/b": {"tilde~key": 7}}
        self.assertEqual(json_pointer_get(doc, "/a~1b/tilde~0key"), 7)
        self.assertIs(json_pointer_get(doc, ""), doc)

    def test_priority_order_descending_stable(self):
        tasks = [
            {"id": "low", "priority": 1},
            {"id": "first-high", "priority": 10},
            {"id": "second-high", "priority": 10},
        ]
        self.assertEqual(
            [task["id"] for task in order_tasks(tasks)],
            ["first-high", "second-high", "low"],
        )


if __name__ == "__main__":
    unittest.main()
