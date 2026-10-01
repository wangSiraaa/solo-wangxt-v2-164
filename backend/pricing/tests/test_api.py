"""DRF 接口冒烟测试。"""
import json
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIClient


class ApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", stdout=StringIO())
        cls.client = APIClient()

    def _post_json(self, url, payload):
        return self.client.post(
            url, json.dumps(payload), content_type="application/json"
        )

    def _flight_ids(self):
        return {r["number"]: r["id"] for r in self.client.get("/api/flights/").data}

    def test_flights_list_has_local_and_utc_times(self):
        resp = self.client.get("/api/flights/")
        self.assertEqual(resp.status_code, 200)
        row = next(r for r in resp.data if r["number"] == "5601")
        self.assertIn("CST", row["dep_local"])
        self.assertIn("+06", row["arr_local"])
        self.assertTrue(any(c["rbd"] == "Y" for c in row["cabins"]))

    def test_quote_endpoint(self):
        flights = self._flight_ids()
        resp = self._post_json("/api/quote/", {
            "segments": [
                {"flight_id": flights["521"], "rbd": "Y"},
                {"flight_id": flights["524"], "rbd": "Y"},
            ]
        })
        self.assertEqual(resp.status_code, 200)
        self.assertGreaterEqual(resp.data["valid_solution_count"], 1)
        best = next(s for s in resp.data["solutions"] if s.get("cheapest_valid"))
        self.assertEqual(best["total_amount"], Decimal("3700.00"))
        # 实际网络负载里金额必须是 JSON 字符串，不能是裸数字（防 JS 浮点）。
        body = json.loads(resp.content)
        best_body = next(s for s in body["solutions"] if s.get("cheapest_valid"))
        self.assertIsInstance(best_body["total_amount"], str)
        self.assertEqual(best_body["total_amount"], "3700.00")

    def test_quote_cabin_unavailable_422(self):
        flights = self._flight_ids()
        resp = self._post_json("/api/quote/", {
            "segments": [{"flight_id": flights["5107"], "rbd": "Q"}]
        })
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.data["error"]["code"], "CABIN_UNAVAILABLE")

    def test_rebook_endpoint_used_coupon(self):
        resp = self._post_json("/api/rebook/", {
            "pnr": "TST202",
            "changes": [{"coupon_seq": 1, "new_flight_id": 1, "new_rbd": "Y"}],
        })
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertFalse(resp.data["eligible"])

    def test_fare_versions_are_traceable(self):
        resp = self.client.get("/api/fares/")
        yrt = next(f for f in resp.data if f["fare_code"] == "YRT")
        versions = self.client.get(f"/api/fares/{yrt['id']}/versions/").data
        self.assertEqual([v["version"] for v in versions], [2, 1])
        self.assertTrue(versions[0]["active_fare_uses_this"])
        change_rules = [
            r for v in versions for r in v["rules"] if r["code"] == "CHANGE_FEE"
        ]
        fees = sorted(str(r["fee_cny"]) for r in change_rules)
        self.assertEqual(fees, ["1000.00", "300.00", "500.00", "800.00"])
