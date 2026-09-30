"""
时间工具：机场本地日历与 UTC 双重校验。

关键点：跨日不能只减字符串日期。所有时刻内部统一用 timezone-aware UTC datetime；
"是否跨了本地日期"按转机点机场的 IANA 时区观察本地日历来判定，
停留/最短最长停留日按出发地与转机地的本地日期差计算。
"""

from datetime import timedelta
from zoneinfo import ZoneInfo

MIN_TRANSFER_MINUTES = 40
MAX_TRANSFER_MINUTES = 24 * 60
STOPOVER_MINUTES = 24 * 60


def local_dt(utc_dt, airport):
    """UTC 时刻 -> 某机场本地时刻。"""
    return utc_dt.astimezone(ZoneInfo(airport.timezone))


def layover_minutes(arrival_utc, departure_utc):
    """转机衔接分钟数：真实时间差，绝不是日期字符串相减。"""
    delta = departure_utc - arrival_utc
    return round(delta.total_seconds() / 60)


def local_date_changed(arrival_utc, departure_utc, transit_airport):
    """
    在中转机场的本地日历上，到达与后续出发是否落在不同的本地日期。
    例：PEK->XIY 23:50 本地到，次日 00:50 本地飞 => True（即便 UTC 可能仍是同日）。
    """
    return local_dt(arrival_utc, transit_airport).date() != \
        local_dt(departure_utc, transit_airport).date()


def is_stopover(arrival_utc, departure_utc):
    """>=24 小时为停留；<24 小时（含跨零点）为转机。"""
    return layover_minutes(arrival_utc, departure_utc) >= STOPOVER_MINUTES


def calendar_stay_days(departure_utc, origin_airport,
                       return_departure_utc, destination_airport):
    """
    往返停留日：从去程出发（起点本地日历）到回程出发（折返点本地日历）的日历日差。
    两个日期分别在各自机场本地日历上取值。
    """
    out_date = local_dt(departure_utc, origin_airport).date()
    back_date = local_dt(return_departure_utc, destination_airport).date()
    return (back_date - out_date).days


def saturday_night(departure_utc, origin_airport,
                   return_departure_utc, destination_airport):
    """
    周六过夜规则（简化）：去程出发后、回程出发前的停留窗口，是否覆盖某个
    折返点本地的周六深夜（周六 23:00 为判定时刻）。
    """
    import datetime as _dt
    tz = ZoneInfo(destination_airport.timezone)
    start = local_dt(departure_utc, origin_airport)
    end = local_dt(return_departure_utc, destination_airport)
    day = start.date()
    while day <= end.date():
        if day.weekday() == 5:  # Monday=0 ... Saturday=5
            sat_night = _dt.datetime.combine(
                day, _dt.time(23, 0)).replace(tzinfo=tz)
            if start <= sat_night < end:
                return True
        day += timedelta(days=1)
    return False
