"""定价 / 改签试算核心。

设计要点（培训口径）：
* 一个多航段行程不是逐段票价相加，而是切成一个或多个“运价组件(fare
  component)”：单程 OW 组件覆盖一个航段，来回程 RT 组件一次覆盖去+回两个
  航段、只收一次 RT 价。穷举所有组件切分作为候选方案，逐方案跑规则。
* 所有金额 Decimal 核算并 quantize 到分；税费按舱等逐段计收、分别列示。
* 转机/停留按 UTC 物理间隔 24h 阈值判定；最短/最长停留按机场当地日历日差。
* 每个规则命中结果都带 fare/规则版本主键，试算可追溯。
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from itertools import product

from django.utils import timezone

from .models import (
    CabinInventory,
    Fare,
    Flight,
    Rule,
    TaxDefinition,
    TicketCoupon,
)
from .rules_lang import RuleContextError, RuleSyntaxError, evaluate_bool
from .timeutils import (
    elapsed_hours,
    junction_kind,
    local_date,
    local_str,
    valid_chronology,
)

CENT = Decimal("0.01")


def money(value) -> Decimal:
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass
class LoadedSegment:
    index: int
    flight: Flight
    rbd: str
    cabin_name: str
    seats: int
    dep_tz: str = ""
    arr_tz: str = ""

    @property
    def dep_utc(self):
        return self.flight.dep_utc

    @property
    def arr_utc(self):
        return self.flight.arr_utc

    def as_dict(self):
        f = self.flight
        return {
            "index": self.index,
            "flight": f"{f.carrier}{f.number}",
            "carrier": f.carrier,
            "dep_airport": f.dep_airport_id,
            "arr_airport": f.arr_airport_id,
            "rbd": self.rbd,
            "cabin_name": self.cabin_name,
            "seats": self.seats,
            "dep_utc": f.dep_utc.isoformat(),
            "arr_utc": f.arr_utc.isoformat(),
            "dep_local": local_str(f.dep_utc, self.dep_tz),
            "arr_local": local_str(f.arr_utc, self.arr_tz),
        }


def load_segments(raw_segments: list[dict]) -> tuple[list[LoadedSegment] | None, dict | None]:
    """把 [{flight_id, rbd}] 加载成带舱位/机场信息的航段。

    任一航段所选舱位不存在或无座，立即返回结构化错误（对应“某段舱位不可用”）。
    """
    if not raw_segments:
        return None, {"code": "EMPTY_ITINERARY", "message": "至少需要一个航段"}

    loaded: list[LoadedSegment] = []
    for i, raw in enumerate(raw_segments):
        flight = (
            Flight.objects.select_related("dep_airport", "arr_airport")
            .filter(pk=raw.get("flight_id"))
            .first()
        )
        if flight is None:
            return None, {
                "code": "UNKNOWN_FLIGHT",
                "segment_index": i,
                "message": f"第 {i + 1} 段航班不存在（虚构航班库中无此航班）",
            }
        rbd = (raw.get("rbd") or "").upper()
        cabin = CabinInventory.objects.filter(flight=flight, rbd=rbd).first()
        if cabin is None:
            return None, {
                "code": "CABIN_NOT_OFFERED",
                "segment_index": i,
                "flight": f"{flight.carrier}{flight.number}",
                "rbd": rbd,
                "message": f"第 {i + 1} 段 {flight.carrier}{flight.number} 不销售 {rbd} 舱",
            }
        if cabin.seats <= 0:
            return None, {
                "code": "CABIN_UNAVAILABLE",
                "segment_index": i,
                "flight": f"{flight.carrier}{flight.number}",
                "rbd": rbd,
                "cabin_name": cabin.cabin_name,
                "message": f"第 {i + 1} 段 {flight.carrier}{flight.number} 的 {rbd} 舱无可用座位",
            }
        loaded.append(
            LoadedSegment(
                index=i,
                flight=flight,
                rbd=rbd,
                cabin_name=cabin.cabin_name,
                seats=cabin.seats,
                dep_tz=flight.dep_airport.tz,
                arr_tz=flight.arr_airport.tz,
            )
        )
        # 航段必须首尾机场相接（虚构图里没有地面段/缺口程开口）。
        if len(loaded) >= 2 and loaded[-2].flight.arr_airport_id != flight.dep_airport_id:
            return None, {
                "code": "BAD_CONNECTION",
                "segment_index": i,
                "message": (
                    f"第 {i} 段落地 {loaded[-2].flight.arr_airport_id} 与第 {i + 1} 段"
                    f"起飞 {flight.dep_airport_id} 不是同一机场，无法联程"
                ),
            }

    seg_dicts = [
        {
            "arr_airport_id": s.flight.arr_airport_id,
            "dep_airport_id": s.flight.dep_airport_id,
            "dep_utc": s.dep_utc,
            "arr_utc": s.arr_utc,
        }
        for s in loaded
    ]
    ok, reason = valid_chronology(seg_dicts)
    if not ok:
        return None, {"code": "BAD_CHRONOLOGY", "message": reason}
    return loaded, None


def build_junctions(segments: list[LoadedSegment]) -> list[dict]:
    """相邻航段之间的接续点：用 UTC 算间隔，用机场当地日历展示跨日。

    两段来回程时唯一接续点是“折返点(stay turnaround)”，其长短受最短/最长
    停留约束，但不计入“中途停留 stopovers”；多段单程时各接续点才按 24h
    阈值分 transfer / stopover。
    """
    n = len(segments)
    junctions = []
    for j, (prev, nxt) in enumerate(zip(segments, segments[1:])):
        airport = prev.flight.arr_airport_id
        gap_h = round(elapsed_hours(prev.arr_utc, nxt.dep_utc), 2)
        arr_local_date = local_date(prev.arr_utc, prev.arr_tz)
        dep_local_date = local_date(nxt.dep_utc, nxt.dep_tz)
        utc_date_diff = (
            nxt.dep_utc.date() - prev.arr_utc.date()
        ).days
        is_turnaround = (
            n == 2
            and prev.flight.arr_airport_id == nxt.flight.dep_airport_id
            and prev.flight.dep_airport_id == nxt.flight.arr_airport_id
        )
        if is_turnaround:
            kind = "TURNAROUND_STAY"
        else:
            kind = junction_kind(gap_h)
        junctions.append(
            {
                "airport": airport,
                "between_segments": [prev.index, nxt.index],
                "is_turnaround": is_turnaround,
                "arr_local": local_str(prev.arr_utc, prev.arr_tz),
                "dep_local": local_str(nxt.dep_utc, nxt.dep_tz),
                "arr_local_date": arr_local_date.isoformat(),
                "dep_local_date": dep_local_date.isoformat(),
                "local_calendar_diff_days": (dep_local_date - arr_local_date).days,
                "utc_date_diff_days": utc_date_diff,
                "gap_hours": gap_h,
                "kind": kind,
            }
        )
    return junctions


# ---------- 组件切分穷举 ----------


def _block_fares(block: tuple[int, int], segments: list[LoadedSegment]):
    """返回某一切分块可适用的运价候选 [(Fare, direction), ...]。"""
    a, b = block
    first = segments[a]
    if b == a + 1:
        fares = Fare.objects.filter(
            active=True,
            direction="OW",
            origin=first.flight.dep_airport_id,
            destination=first.flight.arr_airport_id,
            rbd=first.rbd,
        ).select_related("current_rule_version")
        return [(f, "OW") for f in fares]

    # RT 块：恰好覆盖两个航段，去程终点=回程起点，且首尾机场互换。
    last = segments[b - 1]
    if b != a + 2:
        return []
    if (
        first.flight.arr_airport_id != last.flight.dep_airport_id
        or first.flight.dep_airport_id != last.flight.arr_airport_id
        or first.rbd != last.rbd
    ):
        return []
    fares = Fare.objects.filter(
        active=True,
        direction="RT",
        origin=first.flight.dep_airport_id,
        destination=first.flight.arr_airport_id,
        rbd=first.rbd,
    ).select_related("current_rule_version")
    return [(f, "RT") for f in fares]


def _enumerate_blocks(n: int, start: int = 0) -> list[list[tuple[int, int]]]:
    """把 n 个航段切成 (OW=1段 / RT=2段) 的连续块，穷举所有切分。"""
    if start == n:
        return [[]]
    results = []
    for size in (1, 2):
        if start + size <= n:
            for rest in _enumerate_blocks(n, start + size):
                results.append([(start, start + size), *rest])
    return results


def _evaluate_rules(version, context) -> list[dict]:
    hits = []
    rules = Rule.objects.filter(version=version).order_by("id")
    for rule in rules:
        # 报价阶段只跑门限类规则；改签手续费规则在改签时单独判定。
        if rule.code == "CHANGE_FEE":
            continue
        hit = {
            "rule_id": rule.id,
            "code": rule.code,
            "description": rule.description,
            "expression": rule.expression,
            "version_id": version.id,
            "version_number": version.version,
            "rule_note": version.note,
            "fare_id": version.fare_id,
        }
        try:
            hit["passed"] = evaluate_bool(rule.expression, context)
        except (RuleSyntaxError, RuleContextError) as exc:
            hit["passed"] = False
            hit["error"] = str(exc)
        hits.append(hit)
    return hits


def _taxes_for(segments: list[LoadedSegment]) -> dict:
    """按每段舱等逐段计税，分项列示。"""
    # 以税码为行展开，每段该舱等适用的税费逐段列出。
    by_code: dict[str, dict] = {}
    for seg in segments:
        for d in TaxDefinition.objects.filter(cabin_name=seg.cabin_name):
            row = by_code.setdefault(
                d.code,
                {"code": d.code, "name": d.name, "per_segment": [], "total": Decimal("0"),
                 "_applied_flights": []},
            )
            row["per_segment"].append(
                {"segment_index": seg.index, "flight": f"{seg.flight.carrier}{seg.flight.number}",
                 "amount": money(d.amount_cny)}
            )
            row["_applied_flights"].append(seg.index)
            row["total"] += d.amount_cny
    items = []
    total = Decimal("0")
    for row in by_code.values():
        row["total"] = money(row["total"])
        total += row["total"]
        del row["_applied_flights"]
        items.append(row)
    return {"items": items, "total": money(total)}


def quote(raw_segments: list[dict]) -> dict:
    """主入口：返回所有候选组合方案（含失败方案与命中规则）。"""
    segments, error = load_segments(raw_segments)
    if error:
        return {"ok": False, "error": error}

    junctions = build_junctions(segments)
    # 折返点长间隔是“停留(stay)”，不计入禁止性的中途停留 stopover。
    stopovers = sum(1 for j in junctions if j["kind"] == "STOPOVER")
    transfers = sum(1 for j in junctions if j["kind"] == "TRANSFER")
    turnaround_stay = next(
        (j["local_calendar_diff_days"] for j in junctions if j["is_turnaround"]), None
    )

    base_context_common = {
        "n_segments": len(segments),
        "stopovers": stopovers,
        "transfers": transfers,
        "all_rbds": [s.rbd for s in segments],
        "all_carriers": [s.flight.carrier for s in segments],
    }

    solutions = []
    for blocks in _enumerate_blocks(len(segments)):
        options_per_block = [_block_fares(b, segments) for b in blocks]
        if any(not opts for opts in options_per_block):
            # 这种切分没有可适用运价（例如 RT 首尾不闭环），记一个失败占位。
            missing_at = next(
                i for i, opts in enumerate(options_per_block) if not opts
            )
            solutions.append(
                {
                    "valid": False,
                    "blocks": [
                        {"segments": list(range(a, b)), "fare": None}
                        for a, b in blocks
                    ],
                    "reason": "NO_FARE_FOR_COMPONENT",
                    "message": (
                        f"第 {missing_at + 1} 个运价组件找不到适用运价"
                        "（注意 RT 运价要求去/回首尾机场闭环）"
                    ),
                }
            )
            continue

        for fare_choices in product(*options_per_block):
            components = []
            base_total = Decimal("0")
            for (a, b), (fare, direction) in zip(blocks, fare_choices):
                covered = list(range(a, b))
                components.append(
                    {
                        "fare_id": fare.id,
                        "fare_code": fare.fare_code,
                        "carrier": fare.carrier,
                        "direction": direction,
                        "rbd": fare.rbd,
                        "origin": fare.origin,
                        "destination": fare.destination,
                        "segments": covered,
                        "amount": money(fare.amount_cny),
                    }
                )
                base_total += fare.amount_cny

            carriers = {s.flight.carrier for s in segments} | {
                f.carrier for f, _ in fare_choices
            }
            same_carrier = len(carriers) == 1
            stay_days = turnaround_stay
            base_ctx = {
                **base_context_common,
                "components_count": len(components),
                "same_carrier": same_carrier,
                "stay_days": stay_days,
                "components": components,
            }

            rule_hits = []
            for component, (fare, _direction) in zip(components, fare_choices):
                version = fare.current_rule_version
                if version is None:
                    rule_hits.append(
                        {
                            "fare_id": fare.id,
                            "fare_code": fare.fare_code,
                            "version_id": None,
                            "passed": True,
                            "description": "该运价未挂规则版本",
                        }
                    )
                    continue
                # 规则按“本运价组件”求值：component 指向当前组件自身。
                ctx = {**base_ctx, "component": component}
                for hit in _evaluate_rules(version, ctx):
                    hit["fare_code"] = fare.fare_code
                    hit["component_segments"] = component["segments"]
                    rule_hits.append(hit)

            valid = all(h.get("passed", False) for h in rule_hits)
            taxes = _taxes_for(segments)
            solutions.append(
                {
                    "valid": valid,
                    "blocks": [
                        {
                            "segments": list(range(a, b)),
                            "fare": f"{f.fare_code} {f.origin}-{f.destination} {direction}",
                            "fare_id": f.id,
                            "rule_version_id": f.current_rule_version_id,
                        }
                        for (a, b), (f, direction) in zip(blocks, fare_choices)
                    ],
                    "components": components,
                    "rule_hits": rule_hits,
                    "base_amount": money(base_total),
                    "taxes": taxes,
                    "total_amount": money(base_total + taxes["total"]),
                }
            )

    valid_solutions = [s for s in solutions if s.get("valid")]
    valid_solutions.sort(key=lambda s: s["total_amount"])
    if valid_solutions:
        valid_solutions[0]["cheapest_valid"] = True

    return {
        "ok": True,
        "segments": [s.as_dict() for s in segments],
        "junctions": junctions,
        "trip_summary": {
            **base_context_common,
            # 去程终点 = 回程起点的两段来回程接续点即“折返点”，
            # 其当地日历日差就是最短/最长停留规则使用的 stay_days。
            "turnaround_stay_days_local": turnaround_stay,
        },
        "solutions": solutions,
        "valid_solution_count": len(valid_solutions),
        "currency": "CNY",
        "disclaimer": "虚构航班与运价的培训试算，不构成真实报价，不产生购票/出票/退款指令。",
    }


# ---------- 改签 ----------


@dataclass
class ChangePlan:
    first_changed_seq: int
    # 重算行程：取自第一张变更票联到最后一张票联的全部航段。
    # 例如来回程只改回程，去程也必须纳入重算，否则 RT 组件无法成立、
    # 最短/最长停留规则也无从校验。
    segment_inputs: list[dict]
    coupon_rows: list[TicketCoupon]
    changed_seqs: list[int]


def _check_coupons(order, changes: dict[int, dict]) -> tuple[list[dict], ChangePlan | None]:
    """改签第一步：逐张检查剩余票联状态，任何一张不开放即终止。

    重算起点取“变更票联所在运价组件的第一张票联”（取自出票快照）：只改 RT
    回程时去程票联也要带回重算，否则 RT 组件无法成立、最短/最长停留无法
    校验。价差核算与票联状态检查仍逐张进行，不受重算起点影响。
    """
    checks = []
    # order.coupons 已在 rebook() 中 prefetch_related，这里在内存排序即可，
    # 不要再调用 .select_related()（会在 prefetch 缓存的 manager 上另发查询）。
    coupons = sorted(order.coupons.all(), key=lambda c: c.seq)
    coupon_by_seq = {c.seq: c for c in coupons}

    unknown = [s for s in changes if s not in coupon_by_seq]
    if unknown:
        checks.append({"passed": False, "stage": "COUPON",
                       "message": f"票联序号不存在: {unknown}"})
        return checks, None

    first_changed = min(changes)
    reprice_from = first_changed
    for comp in order.fare_snapshot.get("components", []):
        seqs = comp.get("coupon_seqs") or []
        if first_changed in seqs:
            reprice_from = min(reprice_from, min(seqs))

    plan = ChangePlan(
        first_changed_seq=reprice_from,
        segment_inputs=[],
        coupon_rows=[],
        changed_seqs=sorted(changes),
    )
    ok = True
    for c in coupons:
        if c.seq < reprice_from:
            checks.append(
                {"passed": True, "stage": "COUPON", "coupon_seq": c.seq,
                 "status": c.status, "message": f"第 {c.seq} 段在变更组件之前（原票联保留，不重算）"}
            )
            continue
        passed = c.status == TicketCoupon.Status.OPEN
        ok = ok and passed
        checks.append(
            {
                "passed": passed,
                "stage": "COUPON",
                "coupon_seq": c.seq,
                "status": c.status,
                "message": (
                    f"第 {c.seq} 段票联状态 {c.status}，可换开"
                    if passed
                    else f"第 {c.seq} 段票联状态为 {c.status}，不可改签（必须为 OPEN）"
                ),
            }
        )
        new_spec = changes.get(c.seq)
        plan.segment_inputs.append(
            new_spec
            if new_spec is not None
            else {"flight_id": c.flight_id, "rbd": c.rbd}
        )
        plan.coupon_rows.append(c)
    return checks, plan if ok else None


def _change_fee(original_fare_id: int, context: dict) -> dict:
    """按原运价*当前生效*规则版本判定手续费，并回链版本以便追溯。"""
    fare = (
        Fare.objects.select_related("current_rule_version")
        .filter(pk=original_fare_id)
        .first()
    )
    if fare is None or fare.current_rule_version is None:
        return {
            "original_fare_id": original_fare_id,
            "applied_version_id": None,
            "applied_version_number": None,
            "applied_version_note": "",
            "evaluated": [],
            "fee": Decimal("0.00"),
            "matched_rule_id": None,
        }
    version = fare.current_rule_version
    fee_rows = Rule.objects.filter(version=version, code="CHANGE_FEE").order_by("id")
    chosen = None
    evaluated = []
    for rule in fee_rows:
        try:
            passed = evaluate_bool(rule.expression, context)
        except (RuleSyntaxError, RuleContextError) as exc:
            passed, err = False, str(exc)
        else:
            err = None
        evaluated.append(
            {
                "rule_id": rule.id,
                "expression": rule.expression,
                "description": rule.description,
                "passed": passed,
                "fee": money(rule.fee_cny or 0),
                "version_id": version.id,
                "version_number": version.version,
                "error": err,
            }
        )
        if passed and chosen is None:
            chosen = rule
    return {
        "original_fare_id": fare.id,
        "applied_version_id": version.id,
        "applied_version_number": version.version,
        "applied_version_note": version.note,
        "evaluated": evaluated,
        "fee": money(chosen.fee_cny or 0) if chosen else Decimal("0.00"),
        "matched_rule_id": chosen.id if chosen else None,
    }


def rebook(pnr: str, changes_raw: list[dict], now=None) -> dict:
    """改签试算：先票联状态 -> 再舱位/重算价格 -> 手续费 -> 分项税费。"""
    from .models import Order

    order = Order.objects.filter(pnr=pnr.upper()).prefetch_related("coupons__flight").first()
    if order is None:
        return {"ok": False, "error": {"code": "UNKNOWN_PNR", "message": f"查无虚构客票 {pnr}"}}

    changes: dict[int, dict] = {}
    for ch in changes_raw:
        seq = ch.get("coupon_seq")
        if not isinstance(seq, int):
            return {"ok": False, "error": {"code": "BAD_REQUEST", "message": "coupon_seq 必须为整数"}}
        changes[seq] = {"flight_id": ch.get("new_flight_id"), "rbd": (ch.get("new_rbd") or "").upper()}

    checks, plan = _check_coupons(order, changes)
    coupon_by_seq = {c.seq: c for c in order.coupons.all()}
    if plan is None:
        return {
            "ok": True,
            "eligible": False,
            "pnr": order.pnr,
            "checks": checks,
            "message": "票联状态检查未通过，改签流程在计价前终止。",
            "disclaimer": "仅培训试算，不生成真实换开/退款指令。",
        }

    # 新行程（含未变更但在变更点之后的票联）重新定价。
    requote = quote(plan.segment_inputs)
    if not requote.get("ok"):
        checks.append({"passed": False, "stage": "NEW_ITINERARY", "message": requote["error"]["message"]})
        return {"ok": True, "eligible": False, "pnr": order.pnr, "checks": checks,
                "error_detail": requote["error"],
                "disclaimer": "仅培训试算，不生成真实换开/退款指令。"}
    checks.append({"passed": True, "stage": "NEW_ITINERARY",
                   "message": "新行程时间衔接与舱位可用性检查通过"})

    best = next((s for s in requote["solutions"] if s.get("cheapest_valid")), None)
    if best is None:
        checks.append({"passed": False, "stage": "REPRICE", "message": "新行程无任何通过规则的运价组合"})
        return {"ok": True, "eligible": False, "pnr": order.pnr, "checks": checks,
                "requote": requote,
                "disclaimer": "仅培训试算，不生成真实换开/退款指令。"}

    now = now or timezone.now()
    # 手续费看“第一张实际变更票联”的新航班起飞时间，不能取未改动的去程。
    changed_specs = [plan.segment_inputs[i]
                     for i, c in enumerate(plan.coupon_rows)
                     if c.seq in changes]
    first_new_dep = min(
        Flight.objects.get(pk=spec["flight_id"]).dep_utc for spec in changed_specs
    )
    fee_context = {
        "changed_segments": len(changes),
        "same_cabin": all(
            coupon_by_seq[seq].rbd == changes[seq]["rbd"] for seq in changes
        ),
        "days_before_departure": (first_new_dep.date() - now.date()).days,
    }
    original_fare_id = order.fare_snapshot.get("components", [{}])[0].get("fare_id")
    fee_result = _change_fee(original_fare_id, fee_context) if original_fare_id else None

    snapshot_coupons = {row["seq"]: row for row in order.fare_snapshot.get("coupons", [])}
    old_base = sum(
        (Decimal(str(snapshot_coupons.get(c.seq, {}).get("base", "0"))) for c in plan.coupon_rows),
        Decimal("0"),
    )
    old_tax = sum(
        (Decimal(str(snapshot_coupons.get(c.seq, {}).get("tax", "0"))) for c in plan.coupon_rows),
        Decimal("0"),
    )
    fare_diff = money(best["base_amount"] - old_base)
    tax_diff = money(best["taxes"]["total"] - old_tax)
    fee = fee_result["fee"] if fee_result else Decimal("0.00")
    collect = money(max(fare_diff, Decimal("0")) + max(tax_diff, Decimal("0")) + fee)

    return {
        "ok": True,
        "eligible": True,
        "pnr": order.pnr,
        "checks": checks,
        "change_context": fee_context,
        "snapshot_rule_version_id": order.fare_snapshot.get("rule_version_id"),
        "snapshot_at": order.issued_at.isoformat(),
        "fee": fee_result,
        "comparison": {
            "old_remaining_base": money(old_base),
            "new_base": best["base_amount"],
            "base_fare_diff": fare_diff,
            "old_remaining_tax": money(old_tax),
            "new_tax": best["taxes"],
            "tax_diff": tax_diff,
            "change_fee": fee,
            "collect_amount": collect,
            "refund_portion_if_any": money(-fare_diff) if fare_diff < 0 else Decimal("0.00"),
        },
        "requote": requote,
        "message": "价差为负的部分仅作可退差额展示，系统不生成真实退款指令。",
        "disclaimer": "虚构客票培训试算，不产生真实购票、出票（MCO/PTA）、换开或退款指令。",
    }
