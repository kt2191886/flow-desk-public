"""Every integrity gate, each in its passing and failing shape."""
import os
import unittest
from datetime import datetime, timedelta

from flow_desk import config, pipeline, synth
from flow_desk.contracts import OIChange, Position, PositionBook
from flow_desk.ingest import load_position_book
from flow_desk.integrity import (AMBER, GREEN, RED, IntegrityBlocked, check_completeness,
                                 check_data_clock, check_held_coverage,
                                 check_positions_from_disk, check_rows, check_staleness,
                                 require_pass, run_gates, summarize)
from flow_desk.score import score_all

from .helpers import CLOCK, FeedCase


class CompletenessGate(FeedCase):
    def test_all_layers_present_is_green(self):
        self.assertEqual(check_completeness(pipeline.feed_paths(self.feeds))["status"], GREEN)

    def test_missing_required_layer_is_red(self):
        os.remove(self.path("oi_change"))
        c = check_completeness(pipeline.feed_paths(self.feeds))
        self.assertEqual(c["status"], RED)
        self.assertIn("oi_change", c["detail"])

    def test_missing_optional_layer_is_amber(self):
        os.remove(self.path("open_close"))
        self.assertEqual(check_completeness(pipeline.feed_paths(self.feeds))["status"], AMBER)


class StalenessGate(FeedCase):
    def test_fresh_file_is_green(self):
        self.assertEqual(check_staleness("oi_change", self.path("oi_change"), CLOCK)["status"], GREEN)

    def test_older_than_limit_is_red(self):
        limit = config.STALE_AFTER_HOURS["oi_change"]
        synth.set_mtimes(self.feeds, CLOCK - timedelta(hours=limit + 1), only="oi_change")
        c = check_staleness("oi_change", self.path("oi_change"), CLOCK)
        self.assertEqual(c["status"], RED)
        self.assertIn("stale", c["detail"])

    def test_exactly_at_limit_is_still_green(self):
        limit = config.STALE_AFTER_HOURS["oi_change"]
        synth.set_mtimes(self.feeds, CLOCK - timedelta(hours=limit), only="oi_change")
        self.assertEqual(check_staleness("oi_change", self.path("oi_change"), CLOCK)["status"], GREEN)

    def test_no_file_is_red(self):
        self.assertEqual(check_staleness("oi_change", None, CLOCK)["status"], RED)

    def test_operator_away_softens_manual_layer_to_amber(self):
        synth.fault_stale_positions(self.feeds, CLOCK)
        c = check_staleness("positions", self.path("positions"), CLOCK, operator_away=True)
        self.assertEqual(c["status"], AMBER)
        self.assertIn("EXPECTED", c["detail"])

    def test_operator_away_does_not_soften_machine_layer(self):
        synth.fault_stale(self.feeds, CLOCK)
        c = check_staleness("oi_change", self.path("oi_change"), CLOCK, operator_away=True)
        self.assertEqual(c["status"], RED)


class RowsGate(unittest.TestCase):
    def test_zero_rows_required_is_red(self):
        self.assertEqual(check_rows("flow_alerts", [])["status"], RED)

    def test_zero_rows_optional_is_amber(self):
        self.assertEqual(check_rows("open_close", [])["status"], AMBER)

    def test_parse_error_is_red_and_carries_reason(self):
        c = check_rows("positions", None, parse_error="no header row")
        self.assertEqual(c["status"], RED)
        self.assertIn("no header row", c["detail"])

    def test_rows_present_is_green(self):
        self.assertEqual(check_rows("flow_alerts", [1, 2])["status"], GREEN)


class DataClockGate(unittest.TestCase):
    def _row(self, day):
        return OIChange(day, "ZZXY", "2026-04-17", 50.0, "P", open_int=10)

    def test_current_session_is_green(self):
        self.assertEqual(check_data_clock([self._row("2026-03-10")], CLOCK)["status"], GREEN)

    def test_fresh_file_old_data_is_red(self):
        c = check_data_clock([self._row("2026-03-02")], CLOCK)
        self.assertEqual(c["status"], RED)
        self.assertIn("old data", c["detail"])

    def test_monday_accepts_friday(self):
        monday = datetime(2026, 3, 9, 7, 30)
        self.assertEqual(check_data_clock([self._row("2026-03-06")], monday)["status"], GREEN)

    def test_no_rows_is_red(self):
        self.assertEqual(check_data_clock([], CLOCK)["status"], RED)


class NeverFromMemoryGate(FeedCase):
    def test_book_loaded_from_file_is_green(self):
        book = load_position_book(self.path("positions"))
        self.assertEqual(check_positions_from_disk(book)["status"], GREEN)

    def test_no_book_is_red(self):
        self.assertEqual(check_positions_from_disk(None)["status"], RED)

    def test_book_built_in_memory_is_red(self):
        book = PositionBook(positions=[Position("ZZXY", "stock", 100)])
        c = check_positions_from_disk(book)
        self.assertEqual(c["status"], RED)
        self.assertIn("in-memory", c["detail"])

    def test_file_changed_after_load_is_red(self):
        book = load_position_book(self.path("positions"))
        with open(self.path("positions"), "a", encoding="utf-8") as fh:
            fh.write("WWWQ,Stock,999,,,,\n")
        self.assertEqual(check_positions_from_disk(book)["status"], RED)

    def test_file_deleted_after_load_is_red(self):
        book = load_position_book(self.path("positions"))
        os.remove(self.path("positions"))
        self.assertEqual(check_positions_from_disk(book)["status"], RED)


class HeldCoverageGate(unittest.TestCase):
    def test_held_symbol_without_data_is_amber_and_named(self):
        book = PositionBook(positions=[Position("QQZX", "option", -1, "P", 50.0, "2026-04-17")])
        rows = [OIChange("2026-03-10", "ZZXY", "2026-04-17", 50.0, "P", open_int=10)]
        c = check_held_coverage(book, rows)
        self.assertEqual(c["status"], AMBER)
        self.assertIn("QQZX", c["detail"])

    def test_covered_is_green(self):
        book = PositionBook(positions=[Position("ZZXY", "option", -1, "P", 50.0, "2026-04-17")])
        rows = [OIChange("2026-03-10", "ZZXY", "2026-04-17", 50.0, "P", open_int=10)]
        self.assertEqual(check_held_coverage(book, rows)["status"], GREEN)


class VerdictBlocksDownstream(FeedCase):
    def test_worst_check_wins(self):
        rep = summarize([{"check": "a", "status": GREEN, "detail": ""},
                         {"check": "b", "status": RED, "detail": ""},
                         {"check": "c", "status": AMBER, "detail": ""}], CLOCK)
        self.assertEqual(rep["overall"], RED)
        self.assertEqual(rep["reds"], ["b"])
        self.assertEqual(rep["ambers"], ["c"])

    def test_require_pass_raises_on_red_and_on_no_report(self):
        red = summarize([{"check": "b", "status": RED, "detail": ""}], CLOCK)
        self.assertRaises(IntegrityBlocked, require_pass, red)
        self.assertRaises(IntegrityBlocked, require_pass, None)

    def test_require_pass_allows_green_and_amber(self):
        for status in (GREEN, AMBER):
            rep = summarize([{"check": "a", "status": status, "detail": ""}], CLOCK)
            self.assertIs(require_pass(rep), rep)

    def test_scorer_refuses_a_red_report(self):
        red = summarize([{"check": "b", "status": RED, "detail": ""}], CLOCK)
        self.assertRaises(IntegrityBlocked, score_all, red, [], {}, [], None, CLOCK)

    def test_clean_day_is_green(self):
        layers, book, errors = pipeline.ingest(self.feeds)
        rep = run_gates(pipeline.feed_paths(self.feeds), layers, book, CLOCK, errors)
        self.assertEqual(rep["overall"], GREEN, rep)

    def test_red_run_withholds_every_read(self):
        synth.fault_stale(self.feeds, CLOCK)
        got = pipeline.run(self.feeds, self.out, now=CLOCK, send=False)
        self.assertEqual(got["report"]["overall"], RED)
        self.assertIsNone(got["result"])
        self.assertEqual(got["exit_code"], 2)
        self.assertNotIn("chart.svg", got["paths"])
        with open(got["paths"]["debrief.md"], encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("Withheld", text)
        self.assertNotIn("Corroborated", text)

    def test_a_check_that_raises_is_amber_not_green(self):
        class Broken(object):
            source, sha256 = "x", "y"

            @property
            def positions(self):
                raise RuntimeError("boom")
        layers, _, errors = pipeline.ingest(self.feeds)
        rep = run_gates(pipeline.feed_paths(self.feeds), layers, Broken(), CLOCK, errors)
        self.assertIn("check_error", [c["check"] for c in rep["checks"]])
        self.assertNotEqual(rep["overall"], GREEN)


if __name__ == "__main__":
    unittest.main()
