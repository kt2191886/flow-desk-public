"""T+1 confirmation and the scorer. Pure functions, no files."""
import unittest
from datetime import date, datetime

from flow_desk import config
from flow_desk.contracts import FlowAlert, OIChange, OpenClose, Position
from flow_desk.score.confirm import (build_snapshots, compute_verdict, confirm_all,
                                     oi_available_for, oi_series, pick_eod_oi)
from flow_desk.score.scorer import (deep_itm, held_overlap, open_close_support, score_alert)

TODAY = date(2026, 3, 11)
NOW = datetime(2026, 3, 11, 7, 30)


def alert(day="2026-03-04", size=1000, oi=500, cp="P", strike=50.0, spot=52.0,
          opening=False, expiry="2026-04-17"):
    return FlowAlert("A1", day, "ZZXY", expiry, strike, cp, size, spot=spot,
                     oi_at_alert=oi, is_opening=opening)


def rows(pairs, cp="P", strike=50.0, expiry="2026-04-17"):
    return [OIChange(d, "ZZXY", expiry, strike, cp, open_int=oi) for d, oi in pairs]


class PublishWindow(unittest.TestCase):
    def test_not_available_before_next_morning(self):
        self.assertFalse(oi_available_for("2026-03-10", datetime(2026, 3, 10, 21, 0)))
        self.assertFalse(oi_available_for("2026-03-10", datetime(2026, 3, 11, 6, 59)))
        self.assertTrue(oi_available_for("2026-03-10", datetime(2026, 3, 11, 7, 0)))

    def test_friday_publishes_monday(self):
        self.assertFalse(oi_available_for("2026-03-06", datetime(2026, 3, 7, 12, 0)))
        self.assertTrue(oi_available_for("2026-03-06", datetime(2026, 3, 9, 7, 0)))

    def test_future_date_is_never_available(self):
        self.assertFalse(oi_available_for("2026-03-12", NOW))


class EndOfDayRule(unittest.TestCase):
    def test_eod_is_read_from_the_next_session(self):
        series = oi_series(rows([("2026-03-04", 500), ("2026-03-05", 1400)]))["ZZXY|2026-04-17|50|P"]
        self.assertEqual(pick_eod_oi(series, "2026-03-04"), 1400)

    def test_no_later_session_is_none_not_zero(self):
        series = oi_series(rows([("2026-03-04", 500)]))["ZZXY|2026-04-17|50|P"]
        self.assertIsNone(pick_eod_oi(series, "2026-03-04"))
        self.assertIsNone(pick_eod_oi({}, "2026-03-04"))

    def test_gap_beyond_limit_is_no_evidence(self):
        far = "2026-03-%02d" % (4 + config.OI_MAX_GAP_DAYS + 1)
        series = oi_series(rows([(far, 9000)]))["ZZXY|2026-04-17|50|P"]
        self.assertIsNone(pick_eod_oi(series, "2026-03-04"))

    def test_empty_cell_is_skipped(self):
        series = oi_series(rows([("2026-03-05", None), ("2026-03-06", 800)]))["ZZXY|2026-04-17|50|P"]
        self.assertEqual(pick_eod_oi(series, "2026-03-04"), 800)


class Verdicts(unittest.TestCase):
    def _verdict(self, a, pairs, today=TODAY, now=NOW):
        series = oi_series(rows(pairs)).get(a.key, {})
        return compute_verdict(a, build_snapshots(a, series, now), today)

    def test_growth_in_window_confirms(self):
        v = self._verdict(alert(), [("2026-03-05", 1100)])
        self.assertEqual(v["verdict"], "CONFIRMED")
        self.assertEqual(v["growth_ratio"], 0.6)

    def test_no_evidence_is_pending_never_not_confirmed(self):
        v = self._verdict(alert(), [])
        self.assertEqual(v["verdict"], "PENDING")
        self.assertIsNone(v["growth_ratio"])

    def test_not_confirmed_needs_observed_days(self):
        one_day = self._verdict(alert(), [("2026-03-05", 500)])
        self.assertEqual(one_day["verdict"], "AMBIGUOUS")       # one observation is not enough
        flat = [("2026-03-05", 500), ("2026-03-06", 498), ("2026-03-09", 500), ("2026-03-10", 499)]
        self.assertEqual(self._verdict(alert(), flat)["verdict"], "NOT_CONFIRMED")

    def test_partial_is_provisional(self):
        v = self._verdict(alert(), [("2026-03-05", 700)])
        self.assertEqual((v["verdict"], v["final"]), ("PARTIAL", False))

    def test_late_growth_does_not_confirm_until_finalize(self):
        a = alert(day="2026-03-02")
        late = [("2026-03-03", 500), ("2026-03-04", 500), ("2026-03-05", 500),
                ("2026-03-06", 500), ("2026-03-09", 500), ("2026-03-10", 500),
                ("2026-03-11", 1200)]
        v = self._verdict(a, late)
        self.assertEqual(v["max_growth_day"], 8)
        self.assertNotEqual(v["verdict"], "CONFIRMED")
        locked = self._verdict(a, late, today=date(2026, 3, 12), now=datetime(2026, 3, 12, 7, 30))
        self.assertEqual((locked["verdict"], locked["final"]), ("CONFIRMED", True))

    def test_expired_contract(self):
        a = alert(expiry="2026-03-06")
        series = oi_series(rows([("2026-03-05", 1500)], expiry="2026-03-06"))[a.key]
        v = compute_verdict(a, build_snapshots(a, series, NOW), TODAY)
        self.assertEqual(v["verdict"], "EXPIRED")

    def test_same_day_alert_waits_for_publish(self):
        a = alert(day="2026-03-10")
        early = datetime(2026, 3, 10, 16, 30)
        out = confirm_all([a], rows([("2026-03-11", 5000)]), early)
        self.assertEqual(out["A1"]["verdict"], "PENDING")

    def test_old_alerts_leave_the_window(self):
        a = alert(day="2026-01-05")
        self.assertEqual(confirm_all([a], [], NOW), {})


class Axes(unittest.TestCase):
    def test_held_overlap_needs_same_cycle(self):
        a = alert(strike=48.0)
        same = Position("ZZXY", "option", -2, "P", 50.0, "2026-04-17")
        other = Position("ZZXY", "option", -2, "P", 50.0, "2026-07-17")
        self.assertTrue(held_overlap(a, [same])["overlap"])
        far = held_overlap(a, [other])
        self.assertFalse(far["overlap"])
        self.assertEqual(far["cross_cycle_matches"], 1)

    def test_long_positions_and_wrong_side_never_overlap(self):
        a = alert(strike=48.0)
        long_put = Position("ZZXY", "option", 2, "P", 50.0, "2026-04-17")
        short_call = Position("ZZXY", "option", -2, "C", 50.0, "2026-04-17")
        above = Position("ZZXY", "option", -2, "P", 45.0, "2026-04-17")
        self.assertFalse(held_overlap(a, [long_put, short_call, above])["overlap"])

    def _oc(self, day, cust_buy, cust_sell, total, market=None, scope="contract"):
        return OpenClose(day, "ZZXY", "2026-04-17", 50.0, "P", cust_buy=cust_buy,
                         cust_sell=cust_sell, total=total, market_volume=market, scope=scope)

    def test_open_close_agrees_only_at_contract_grain_when_fresh(self):
        fresh = open_close_support([self._oc("2026-03-10", 80, 10, 100)], None, TODAY)
        self.assertEqual((fresh["grain"], fresh["agree"]), ("contract", True))
        stale = open_close_support([self._oc("2026-03-02", 80, 10, 100)], None, TODAY)
        self.assertEqual((stale["grain"], stale["agree"]), ("contract-stale", None))
        blended = open_close_support(None, [self._oc("2026-03-10", 80, 10, 100, scope="ticker")], TODAY)
        self.assertEqual((blended["grain"], blended["agree"]), ("ticker", None))
        self.assertEqual(open_close_support(None, None, TODAY)["agree"], None)

    def test_thin_coverage_cannot_agree(self):
        thin = open_close_support([self._oc("2026-03-10", 80, 10, 100, market=5000)], None, TODAY)
        self.assertIs(thin["agree"], False)

    def test_deep_itm(self):
        self.assertTrue(deep_itm(alert(cp="P", strike=80.0, spot=50.0)))
        self.assertFalse(deep_itm(alert(cp="P", strike=52.0, spot=50.0)))
        self.assertFalse(deep_itm(alert(cp="P", strike=80.0, spot=None)))


class Reads(unittest.TestCase):
    CONFIRMED = {"verdict": "CONFIRMED", "growth_ratio": 0.8}

    def _score(self, a, **ctx):
        ctx.setdefault("today", TODAY)
        return score_alert(a, ctx)

    def test_t1_alone_is_building_not_corroborated(self):
        s = self._score(alert(opening=True), confirmation=self.CONFIRMED)
        self.assertEqual(s["read"], "BUILDING")

    def test_t1_plus_build_is_corroborated(self):
        a = alert()
        s = self._score(a, confirmation=self.CONFIRMED,
                        days_by_key={a.key: {"2026-03-03", "2026-03-04"}})
        self.assertEqual(s["read"], "CORROBORATED")

    def test_deep_itm_without_contract_read_goes_to_a_person(self):
        a = alert(cp="P", strike=80.0, spot=50.0, opening=True)
        s = self._score(a, confirmation=self.CONFIRMED,
                        days_by_key={a.key: {"2026-03-03", "2026-03-04"}})
        self.assertEqual(s["read"], "NEEDS_OPENCLOSE")
        self.assertIsNone(s["axes"]["open_close"]["agree"])

    def test_blended_read_asks_for_a_strike_drill(self):
        blended = [OpenClose("2026-03-10", "ZZXY", None, None, None, cust_buy=9, total=10,
                             scope="ticker")]
        s = self._score(alert(opening=True), ticker_open_close=blended)
        self.assertEqual(s["read"], "NEEDS_STRIKE_DRILL")

    def test_nothing_is_unconfirmed(self):
        self.assertEqual(self._score(alert())["read"], "UNCONFIRMED")

    def test_score_is_the_sum_of_axis_weights(self):
        a = alert(opening=True, strike=48.0)
        held = [Position("ZZXY", "option", -1, "P", 50.0, "2026-04-17")]
        s = self._score(a, confirmation=self.CONFIRMED, positions=held,
                        days_by_key={a.key: {"2026-03-03", "2026-03-04"}})
        w = config.AXIS_WEIGHTS
        self.assertEqual(s["score"], w["oi_support"] + w["build"] + w["opening"] + w["held"])


if __name__ == "__main__":
    unittest.main()
