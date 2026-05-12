import unittest

from math_utils import add_one


class AddOneTests(unittest.TestCase):
    def test_adds_exactly_one(self):
        self.assertEqual(add_one(1), 2)
        self.assertEqual(add_one(-3), -2)


if __name__ == "__main__":
    unittest.main()
