import datetime as dt
import unittest

from cron_nearest_fire_utils import (
    CronError,
    cron_field_aliases,
    next_fire_time,
    parse_cron,
)


class TestParseCron(unittest.TestCase):
    def test_wildcard_all(self):
        s = parse_cron("* * * * *")
        self.assertEqual(s["minutes"], list(range(60)))
        self.assertEqual(s["hours"], list(range(24)))
        self.assertEqual(s["doms"], list(range(1, 32)))
        self.assertEqual(s["months"], list(range(1, 13)))
        self.assertEqual(s["dows"], list(range(7)))
        self.assertFalse(s["dom_restricted"])
        self.assertFalse(s["dow_restricted"])

    def test_step_values(self):
        s = parse_cron("*/15 * * * *")
        self.assertEqual(s["minutes"], [0, 15, 30, 45])

    def test_range_with_step(self):
        s = parse_cron("1-10/2 * * * *")
        self.assertEqual(s["minutes"], [1, 3, 5, 7, 9])

    def test_comma_list(self):
        s = parse_cron("1,5,10 * * * *")
        self.assertEqual(s["minutes"], [1, 5, 10])

    def test_named_months(self):
        s = parse_cron("0 0 1 jan,jul *")
        self.assertEqual(s["months"], [1, 7])

    def test_named_dow(self):
        s = parse_cron("0 0 * * mon,fri")
        self.assertEqual(s["dows"], [1, 5])

    def test_dow_7_mapped_to_0(self):
        # Some cron implementations allow 7 for Sunday.
        # This implementation does NOT — 7 is out of range [0-6].
        with self.assertRaises(CronError):
            parse_cron("0 0 * * 7")

    def test_alias_yearly(self):
        s = parse_cron("@yearly")
        self.assertEqual(s["minutes"], [0])
        self.assertEqual(s["months"], [1])
        self.assertEqual(s["doms"], [1])

    def test_too_few_fields(self):
        with self.assertRaises(CronError):
            parse_cron("* * *")

    def test_too_many_fields(self):
        with self.assertRaises(CronError):
            parse_cron("* * * * * *")

    def test_empty_expression(self):
        with self.assertRaises(CronError):
            parse_cron("")

    def test_invalid_step(self):
        with self.assertRaises(CronError):
            parse_cron("*/0 * * * *")

    def test_inverted_range(self):
        with self.assertRaises(CronError):
            parse_cron("5-1 * * * *")

    def test_out_of_range_minute(self):
        with self.assertRaises(CronError):
            parse_cron("60 * * * *")

    def test_out_of_range_hour(self):
        with self.assertRaises(CronError):
            parse_cron("* 24 * * *")

    def test_dom_zero(self):
        with self.assertRaises(CronError):
            parse_cron("* * 0 * *")

    def test_field_aliases_list(self):
        aliases = cron_field_aliases()
        names = [a[0] for a in aliases]
        self.assertIn("@daily", names)
        self.assertIn("@hourly", names)


class TestNextFireTime(unittest.TestCase):
    def test_next_minute(self):
        now = dt.datetime(2024, 1, 15, 10, 30, 0)
        result = next_fire_time("* * * * *", now)
        self.assertEqual(result, dt.datetime(2024, 1, 15, 10, 31, 0))

    def test_every_15_min(self):
        now = dt.datetime(2024, 1, 15, 10, 7, 0)
        result = next_fire_time("*/15 * * * *", now)
        self.assertEqual(result, dt.datetime(2024, 1, 15, 10, 15, 0))

    def test_hourly(self):
        now = dt.datetime(2024, 1, 15, 10, 30, 0)
        result = next_fire_time("0 * * * *", now)
        self.assertEqual(result, dt.datetime(2024, 1, 15, 11, 0, 0))

    def test_daily_midnight(self):
        now = dt.datetime(2024, 1, 15, 14, 30, 0)
        result = next_fire_time("0 0 * * *", now)
        self.assertEqual(result, dt.datetime(2024, 1, 16, 0, 0, 0))

    def test_specific_dom(self):
        now = dt.datetime(2024, 1, 15, 10, 0, 0)
        result = next_fire_time("0 0 1 * *", now)
        self.assertEqual(result, dt.datetime(2024, 2, 1, 0, 0, 0))

    def test_specific_month_and_dom(self):
        now = dt.datetime(2024, 6, 15, 10, 0, 0)
        result = next_fire_time("0 0 1 1 *", now)
        self.assertEqual(result, dt.datetime(2025, 1, 1, 0, 0, 0))

    def test_dow_friday(self):
        # 2024-01-15 is a Monday. Next Friday is Jan 19.
        now = dt.datetime(2024, 1, 15, 10, 0, 0)
        result = next_fire_time("0 0 * * 5", now)
        self.assertEqual(result, dt.datetime(2024, 1, 19, 0, 0, 0))

    def test_dow_sunday(self):
        # 2024-01-15 is a Monday. Next Sunday is Jan 21.
        now = dt.datetime(2024, 1, 15, 10, 0, 0)
        result = next_fire_time("0 0 * * 0", now)
        self.assertEqual(result, dt.datetime(2024, 1, 21, 0, 0, 0))

    def test_dom_and_dow_or_semantics(self):
        # Expression: 0 0 13 * 5 — fires on the 13th OR any Friday.
        # 2024-01-10 is a Wednesday. The 13th is Saturday.
        # Next Friday before the 13th is Jan 12.
        now = dt.datetime(2024, 1, 10, 10, 0, 0)
        result = next_fire_time("0 0 13 * 5", now)
        self.assertEqual(result, dt.datetime(2024, 1, 12, 0, 0, 0))

    def test_february_31_impossible(self):
        # Feb 31st never exists — should exhaust iterations and return None.
        now = dt.datetime(2024, 1, 1, 0, 0, 0)
        result = next_fire_time("0 0 31 2 *", now, max_iterations=100)
        self.assertIsNone(result)

    def test_now_excluded(self):
        # If now is exactly on the cron tick, the result must be the NEXT one.
        now = dt.datetime(2024, 1, 15, 10, 0, 0)
        result = next_fire_time("0 * * * *", now)
        self.assertEqual(result, dt.datetime(2024, 1, 15, 11, 0, 0))

    def test_february_leap_year(self):
        # Feb 29 exists in 2024 (leap year). 2024-02-29 is a Thursday.
        now = dt.datetime(2024, 1, 1, 0, 0, 0)
        result = next_fire_time("0 0 29 2 *", now)
        self.assertEqual(result, dt.datetime(2024, 2, 29, 0, 0, 0))

    def test_february_non_leap_year(self):
        # Feb 29 in 2023 (non-leap) should skip to 2024.
        now = dt.datetime(2023, 1, 1, 0, 0, 0)
        result = next_fire_time("0 0 29 2 *", now)
        self.assertEqual(result, dt.datetime(2024, 2, 29, 0, 0, 0))

    def test_named_dow_next(self):
        # 2024-01-15 Monday. Next Monday (mon) is Jan 22.
        now = dt.datetime(2024, 1, 15, 10, 0, 0)
        result = next_fire_time("0 0 * * mon", now)
        self.assertEqual(result, dt.datetime(2024, 1, 22, 0, 0, 0))

    def test_second_and_microsecond_stripped(self):
        now = dt.datetime(2024, 1, 15, 10, 30, 45, 123456)
        result = next_fire_time("* * * * *", now)
        self.assertEqual(result.second, 0)
        self.assertEqual(result.microsecond, 0)


if __name__ == "__main__":
    unittest.main()
