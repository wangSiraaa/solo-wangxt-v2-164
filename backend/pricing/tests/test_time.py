"""时区/当地日历双校验单测。"""
from datetime import datetime
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from pricing.timeutils import (
    elapsed_hours,
    junction_kind,
    local_date,
    local_date_diff,
    valid_chronology,
)

SHA = ZoneInfo("Asia/Shanghai")
URC = ZoneInfo("Asia/Urumqi")
NRT = ZoneInfo("Asia/Tokyo")


class TimeTests(SimpleTestCase):
    def test_local_dates_cross_timezone(self):
        # 上海 23:00(+08) = UTC 15:00；乌鲁木齐次日 03:30(+06) = UTC 21:30。
        dep = datetime(2026, 10, 5, 15, 0, tzinfo=ZoneInfo("UTC"))
        arr = datetime(2026, 10, 5, 21, 30, tzinfo=ZoneInfo("UTC"))
        self.assertEqual(local_date(dep, "Asia/Shanghai").isoformat(), "2026-10-05")
        # UTC 已经跨 21:30 仍是 10-05，当地乌鲁木齐也是 10-06 03:30。
        self.assertEqual(local_date(arr, "Asia/Urumqi").isoformat(), "2026-10-06")

    def test_stay_days_use_local_calendar_not_utc_subtraction(self):
        # 到达 URC 当地 10-06 凌晨，离开 URC 当地 10-06 上午 => 0 个当地停留日；
        # 若直接拿 UTC 日期相减会得到 1（UTC 从 10-05 到 10-06），正是常见错误。
        arr_utc = datetime(2026, 10, 5, 21, 30, tzinfo=ZoneInfo("UTC"))
        dep_utc = datetime(2026, 10, 6, 3, 0, tzinfo=ZoneInfo("UTC"))
        self.assertEqual(
            local_date_diff(arr_utc, "Asia/Urumqi", dep_utc, "Asia/Urumqi"), 0
        )
        self.assertGreaterEqual(elapsed_hours(arr_utc, dep_utc), 5)

    def test_junction_24h_threshold(self):
        self.assertEqual(junction_kind(23.9), "TRANSFER")
        self.assertEqual(junction_kind(24.0), "STOPOVER")

    def test_chronology(self):
        def seg(arr_hour, dep_hour):
            return {
                "arr_airport_id": "X",
                "dep_airport_id": "X",
                "arr_utc": datetime(2026, 10, 5, arr_hour, 0, tzinfo=ZoneInfo("UTC")),
                "dep_utc": datetime(2026, 10, 5, dep_hour, 0, tzinfo=ZoneInfo("UTC")),
            }
        # 第一段 01:00 起飞、02:00 到达；第二段 03:00 起飞 => 合法。
        good, _ = valid_chronology([seg(2, 1), seg(4, 3)])
        self.assertTrue(good)
        # 第二段 01:30 起飞，早于第一段 02:00 到达 => 非法。
        bad, reason = valid_chronology([seg(2, 1), seg(3, 1)])
        self.assertFalse(bad)
        self.assertIn("时间不衔接", reason)

    def test_naive_datetime_rejected(self):
        with self.assertRaises(ValueError):
            local_date(datetime(2026, 10, 5, 0, 0), "Asia/Shanghai")
