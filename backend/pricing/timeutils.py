"""时间核算工具。

所有存储与间隔计算用 aware UTC datetime；“停留日数”这类业务概念必须用
机场当地日历日期相减。跨时区时两者并不相等：
例如 SHA(UTC+8) 23:00 起飞、URC(UTC+6) 次日凌晨到达，UTC 已经跨日，
但用当地日历判断“几号到、几号走”才符合运价规则的本意。
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


def local_date(dt_utc: datetime, tz_name: str) -> datetime.date:
    """UTC 时刻 -> 机场当地日历日期。"""
    if dt_utc.tzinfo is None:
        raise ValueError("dep/arr 时间必须是带时区的 aware datetime")
    return dt_utc.astimezone(ZoneInfo(tz_name)).date()


def local_str(dt_utc: datetime, tz_name: str) -> str:
    """UTC 时刻 -> 'YYYY-MM-DD HH:mm 机场时区缩写'，供界面双列展示。"""
    lz = ZoneInfo(tz_name)
    local = dt_utc.astimezone(lz)
    return local.strftime("%Y-%m-%d %H:%M") + f" ({local.tzname()})"


def elapsed_hours(earlier_utc: datetime, later_utc: datetime) -> float:
    """两次事件之间的物理小时数（UTC 差值），转机/停留判定用它。"""
    return (later_utc - earlier_utc).total_seconds() / 3600.0


def local_date_diff(start_utc: datetime, start_tz: str,
                    end_utc: datetime, end_tz: str) -> int:
    """到达地当地到达日 与 离开地当地出发日 的日历日差。

    最短/最长停留按“当地日历日”计：到达当晚算第 0 天，次日走算 1 天。
    """
    return (local_date(end_utc, end_tz) - local_date(start_utc, start_tz)).days


# 行业惯例阈值：同城/同场接续 < 24h 视为转机（transfer），>= 24h 视为停留（stopover）。
STOPOVER_HOURS = 24.0


def junction_kind(gap_hours: float) -> str:
    return "STOPOVER" if gap_hours >= STOPOVER_HOURS else "TRANSFER"


def valid_chronology(segments: list[dict]) -> tuple[bool, str | None]:
    """航段必须按时间先后衔接：下一段起飞不早于上一段到达。"""
    for prev, nxt in zip(segments, segments[1:]):
        if nxt["dep_utc"] < prev["arr_utc"]:
            return False, (
                f"航段时间不衔接：{prev['arr_airport_id']} 到达 "
                f"{prev['arr_utc'].isoformat()} 晚于后续起飞 "
                f"{nxt['dep_utc'].isoformat()}"
            )
    return True, None
