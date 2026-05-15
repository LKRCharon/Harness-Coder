import unittest

from csv_config import (
    dedupe_headers,
    normalize_header,
    parse_duration_seconds,
    parse_env_list,
    parse_int_list,
    parse_key_values,
    parse_mode,
    parse_optional_limit,
)


class TrainRecoveryTests(unittest.TestCase):
    def test_header_normalization_accepts_spaces_and_case(self):
        self.assertEqual(normalize_header(" User Id "), "user_id")

    def test_parse_int_list_skips_empty_items(self):
        self.assertEqual(parse_int_list("1, 2, ,3"), [1, 2, 3])

    def test_parse_duration_units(self):
        self.assertEqual(parse_duration_seconds("2m"), 120)
        self.assertEqual(parse_duration_seconds("15s"), 15)
        self.assertEqual(parse_duration_seconds("1500ms"), 1)

    def test_parse_env_list(self):
        self.assertEqual(parse_env_list("prod; ; stage"), ["prod", "stage"])

    def test_parse_key_values_keeps_colons_in_value(self):
        self.assertEqual(parse_key_values("url=https://a:b,mode=fast"), {"url": "https://a:b", "mode": "fast"})

    def test_dedupe_headers_case_insensitive(self):
        self.assertEqual(dedupe_headers([" User ", "user", "Email"]), ["User", "Email"])

    def test_parse_optional_limit(self):
        self.assertIsNone(parse_optional_limit(" "))
        self.assertEqual(parse_optional_limit(" 3 "), 3)

    def test_parse_mode_validates_values(self):
        self.assertEqual(parse_mode(" FAST "), "fast")
        with self.assertRaises(ValueError):
            parse_mode("unsafe")


if __name__ == "__main__":
    unittest.main()
