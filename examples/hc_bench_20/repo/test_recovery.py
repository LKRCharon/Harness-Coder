import unittest

from csv_config import parse_bool, parse_csv_row, retry_delays


class RecoveryTests(unittest.TestCase):
    def test_empty_values_and_quoted_empty_strings(self):
        self.assertEqual(parse_csv_row('alpha,,omega'), ['alpha', None, 'omega'])
        self.assertEqual(parse_csv_row('alpha,"",omega'), ['alpha', '', 'omega'])

    def test_bool_parser_accepts_json_and_legacy_values(self):
        self.assertTrue(parse_bool('true'))
        self.assertTrue(parse_bool('yes'))
        self.assertTrue(parse_bool('1'))
        self.assertFalse(parse_bool('false'))

    def test_retry_schedule_includes_initial_attempt(self):
        self.assertEqual(retry_delays(4, 2), [0, 2, 4, 8])


if __name__ == "__main__":
    unittest.main()
