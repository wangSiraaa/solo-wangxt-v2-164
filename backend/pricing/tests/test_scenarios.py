"""端到端定价/改签场景测试（基于 seed_demo 虚构数据）。

覆盖用户点名的三类案例：
* 单段便宜但不能组合（特价舱 Q 的 COMBINABILITY）
* 跨日期变更（改签 + 最短/最长停留按当地日历重新校验）
* 某段舱位不可用（CABIN_UNAVAILABLE）
以及：RT 运价 vs 两个 OW 相加、转机/停留、跨时区日差、税项分列、
规则版本追溯、票联状态拦截。
"""
from datetime import datetime
from decimal import Decimal
from io import StringIO
from zoneinfo import ZoneInfo

from django.core.management import call_command
from django.test import TestCase

from pricing import engine
from pricing.models import Flight, Order


def fid(number, dep_local_date=None):
    qs = Flight.objects.filter(number=number)
    if dep_local_date:
        # 种子里用当地日期注释航段；测试用航班号唯一即可。
        qs = qs.filter(dep_utc__date=dep_local_date)
    return qs.first().id


class PricingScenarioTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", stdout=StringIO())

    def _codes_failed(self, solution):
        return {h["code"] for h in solution.get("rule_hits", []) if not h.get("passed")}

    def _cheapest_valid(self, result):
        return next(s for s in result["solutions"] if s.get("cheapest_valid"))

    def test_min_stay_failure_uses_local_calendar(self):
        result = engine.quote([
            {"flight_id": fid("521"), "rbd": "Y"},
            {"flight_id": fid("522"), "rbd": "Y"},
        ])
        self.assertTrue(result["ok"])
        junction = result["junctions"][0]
        self.assertEqual(junction["local_calendar_diff_days"], 1)
        rt = next(s for s in result["solutions"]
                  if [c["fare_code"] for c in s.get("components", [])] == ["YRT"])
        self.assertFalse(rt["valid"])
        self.assertIn("MIN_STAY", self._codes_failed(rt))
        self.assertEqual(result["valid_solution_count"], 0)

    def test_rt_is_one_fare_not_two_ow_sum(self):
        result = engine.quote([
            {"flight_id": fid("521"), "rbd": "Y"},
            {"flight_id": fid("524"), "rbd": "Y"},
        ])
        best = self._cheapest_valid(result)
        self.assertEqual([c["fare_code"] for c in best["components"]], ["YRT"])
        # RT 净额 3200；而两个 OW 相加为 2100*2 = 4200，RT 显著更低。
        self.assertEqual(best["base_amount"], Decimal("3200.00"))
        # 税费逐段计收并分列：CN 50*2 + YQ 120*2 + XT 80*2 = 500。
        tax_total = sum(Decimal(t["total"]) for t in best["taxes"]["items"])
        self.assertEqual(tax_total, Decimal("500.00"))
        self.assertEqual(best["total_amount"], Decimal("3700.00"))
        # 命中结果回链规则版本。
        hit = best["rule_hits"][0]
        self.assertIsNotNone(hit["version_id"])
        self.assertEqual(hit["version_number"], 2)

    def test_cross_timezone_local_zero_day_but_utc_one_day(self):
        result = engine.quote([
            {"flight_id": fid("5601"), "rbd": "Y"},
            {"flight_id": fid("5602"), "rbd": "Y"},
        ])
        j = result["junctions"][0]
        self.assertEqual(j["local_calendar_diff_days"], 0)
        self.assertEqual(j["utc_date_diff_days"], 1)
        rt = next(s for s in result["solutions"]
                  if [c["fare_code"] for c in s.get("components", [])] == ["YRTU"])
        self.assertIn("MIN_STAY", self._codes_failed(rt))
        # 两段 OW 相加可行（1800+1700），但比 RT 贵。
        ows = next(s for s in result["solutions"] if s.get("valid"))
        self.assertEqual(len(ows["components"]), 2)
        self.assertEqual(ows["base_amount"], Decimal("3500.00"))

    def test_urc_rt_valid_six_local_days(self):
        result = engine.quote([
            {"flight_id": fid("5601"), "rbd": "Y"},
            {"flight_id": fid("5604"), "rbd": "Y"},
        ])
        best = self._cheapest_valid(result)
        self.assertEqual([c["fare_code"] for c in best["components"]], ["YRTU"])
        self.assertEqual(result["junctions"][0]["local_calendar_diff_days"], 6)

    def test_triangle_one_stopover_all_y_valid_as_three_ow(self):
        result = engine.quote([
            {"flight_id": fid("5107"), "rbd": "Y"},
            {"flight_id": fid("5605"), "rbd": "Y"},
            {"flight_id": fid("5608"), "rbd": "Y"},
        ])
        self.assertTrue(result["ok"])
        kinds = [j["kind"] for j in result["junctions"]]
        self.assertEqual(kinds, ["TRANSFER", "STOPOVER"])
        best = self._cheapest_valid(result)
        self.assertEqual(len(best["components"]), 3)
        self.assertEqual(best["base_amount"], Decimal("1300.00") + Decimal("1100.00") + Decimal("1700.00"))

    def test_segment_cabin_unavailable_zero_seats(self):
        result = engine.quote([
            {"flight_id": fid("5107"), "rbd": "Q"},
            {"flight_id": fid("5605"), "rbd": "Q"},
        ])
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "CABIN_UNAVAILABLE")
        self.assertEqual(result["error"]["segment_index"], 0)

    def test_rbd_not_offered(self):
        result = engine.quote([{"flight_id": fid("5107"), "rbd": "Z"}])
        self.assertEqual(result["error"]["code"], "CABIN_NOT_OFFERED")

    def test_cheap_q_ow_cannot_be_combined(self):
        # 去程 Q 特价(450) + 回程 Y(1300)：单段便宜，但 Q 的组合限制 components_count==1。
        result = engine.quote([
            {"flight_id": fid("5101"), "rbd": "Q"},
            {"flight_id": fid("5104"), "rbd": "Y"},
        ])
        mixed = next(s for s in result["solutions"] if s.get("components"))
        self.assertFalse(mixed["valid"])
        failed = self._codes_failed(mixed)
        self.assertIn("COMBINABILITY", failed)
        self.assertEqual(result["valid_solution_count"], 0)

    def test_max_stay_failure(self):
        result = engine.quote([
            {"flight_id": fid("521"), "rbd": "Y"},
            {"flight_id": fid("526"), "rbd": "Y"},
        ])
        rt = next(s for s in result["solutions"]
                  if [c["fare_code"] for c in s.get("components", [])] == ["YRT"])
        self.assertIn("MAX_STAY", self._codes_failed(rt))

    def test_bad_connection_airport_mismatch(self):
        result = engine.quote([
            {"flight_id": fid("521"), "rbd": "Y"},   # SHA->NRT
            {"flight_id": fid("5104"), "rbd": "Y"},  # PEK->SHA
        ])
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "BAD_CONNECTION")


class RebookTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", stdout=StringIO())
        cls.now = datetime(2026, 10, 1, 12, 0, tzinfo=ZoneInfo("UTC"))

    def test_used_coupon_blocks_rebook_before_pricing(self):
        result = engine.rebook(
            "TST202",
            [{"coupon_seq": 1, "new_flight_id": fid("5103"), "new_rbd": "Y"}],
            now=self.now,
        )
        self.assertFalse(result["eligible"])
        stages = [(c["stage"], c["passed"]) for c in result["checks"]]
        self.assertIn(("COUPON", False), stages)
        # 计价阶段根本不应该出现。
        self.assertFalse(any(c["stage"] == "REPRICE" for c in result["checks"]))

    def test_cross_date_change_reprices_and_itemizes(self):
        result = engine.rebook(
            "TST101",
            [{"coupon_seq": 2, "new_flight_id": fid("524B"), "new_rbd": "Y"}],
            now=self.now,
        )
        self.assertTrue(result["eligible"])
        cmp_, fee = result["comparison"], result["fee"]
        # 同舱等、起飞前 11 天、现行 v2 规则 => 500。
        self.assertEqual(fee["applied_version_number"], 2)
        self.assertEqual(fee["fee"], Decimal("500.00"))
        self.assertEqual(cmp_["base_fare_diff"], Decimal("0.00"))
        self.assertEqual(cmp_["collect_amount"], Decimal("500.00"))
        # 税项分别列示。
        codes = {t["code"] for t in cmp_["new_tax"]["items"]}
        self.assertEqual(codes, {"CN", "YQ", "XT"})
        # 重算行程包含未改动的去程（组件完整性 + 停留校验）。
        self.assertEqual(
            [s["flight"] for s in result["requote"]["segments"]],
            ["MU521", "MU524B"],
        )

    def test_change_to_too_long_stay_rejected_by_rules(self):
        result = engine.rebook(
            "TST101",
            [{"coupon_seq": 2, "new_flight_id": fid("526"), "new_rbd": "Y"}],
            now=self.now,
        )
        self.assertFalse(result["eligible"])
        self.assertTrue(any(c["stage"] == "REPRICE" and not c["passed"]
                            for c in result["checks"]))

    def test_snapshot_v1_fee_still_judged_under_current_v2(self):
        order = Order.objects.get(pnr="TST303")
        self.assertEqual(order.fare_snapshot["rule_version_number"], 1)
        result = engine.rebook(
            "TST303",
            [{"coupon_seq": 2, "new_flight_id": fid("524"), "new_rbd": "Y"}],
            now=self.now,
        )
        self.assertTrue(result["eligible"])
        self.assertEqual(result["snapshot_rule_version_id"],
                         order.fare_snapshot["rule_version_id"])
        self.assertEqual(result["fee"]["applied_version_number"], 2)
        # v1 同场景是 300，v2 是 500：快照旧、计费新。
        self.assertEqual(result["fee"]["fee"], Decimal("500.00"))

    def test_unknown_pnr(self):
        result = engine.rebook("NOPE99", [], now=self.now)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "UNKNOWN_PNR")

    def test_no_real_order_mutation_on_quote(self):
        # 试算绝不改票联状态/不产生出票退款。
        before = list(
            Order.objects.get(pnr="TST101").coupons.values_list("seq", "status")
        )
        engine.rebook(
            "TST101",
            [{"coupon_seq": 2, "new_flight_id": fid("524B"), "new_rbd": "Y"}],
            now=self.now,
        )
        after = list(
            Order.objects.get(pnr="TST101").coupons.values_list("seq", "status")
        )
        self.assertEqual(before, after)
