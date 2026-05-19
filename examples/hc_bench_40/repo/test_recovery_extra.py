import unittest

from parsers import parse_key_value_lines, parse_ranges, parse_semver


class RecoveryExtraTests(unittest.TestCase):
    def test_semver_ignores_prefix_and_prerelease(self):
        self.assertEqual(parse_semver("v1.2.3-alpha.1"), (1, 2, 3))
        self.assertEqual(parse_semver("2.0.1"), (2, 0, 1))

    def test_key_value_lines_keep_equals_in_value(self):
        text = "# comment\ntoken=a=b=c\n mode = safe \n\n"
        self.assertEqual(parse_key_value_lines(text), {"token": "a=b=c", "mode": "safe"})

    def test_range_parser_open_ended(self):
        self.assertEqual(parse_ranges("1-3, 5-"), [(1, 3), (5, None)])


if __name__ == "__main__":
    unittest.main()
