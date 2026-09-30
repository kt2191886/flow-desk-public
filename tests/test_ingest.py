"""The parsers: each reads a file and returns records. Nothing else."""
import os
import tempfile
import unittest

from flow_desk.contracts import cell_date, cell_float, contract_key
from flow_desk.ingest import (FeedFormatError, load_position_book, parse_flow_alerts,
                              parse_oi_change, parse_open_close_csv, parse_open_close_text)

from .helpers import FeedCase


def _tmp(text, encoding="utf-8"):
    fd, path = tempfile.mkstemp(suffix=".csv")
    with os.fdopen(fd, "w", encoding=encoding) as fh:
        fh.write(text)
    return path


class Cells(unittest.TestCase):
    def test_float_tolerates_dashes_commas_and_accounting_negatives(self):
        self.assertIsNone(cell_float("--"))
        self.assertIsNone(cell_float(""))
        self.assertEqual(cell_float("1,250.5"), 1250.5)
        self.assertEqual(cell_float("(40.25)"), -40.25)

    def test_date_formats(self):
        self.assertEqual(cell_date("2026-04-17"), "2026-04-17")
        self.assertEqual(cell_date("04/17/2026"), "2026-04-17")
        self.assertIsNone(cell_date("soon"))

    def test_contract_key_is_stable_across_number_formats(self):
        self.assertEqual(contract_key("zzxy", "2026-04-17", "50.0", "p"),
                         contract_key("ZZXY", "2026-04-17", 50, "P"))


class FlowAlerts(FeedCase):
    def test_parses_synthetic_day(self):
        alerts = parse_flow_alerts(self.path("flow_alerts"))
        self.assertEqual(len(alerts), len(self.truth["alerts"]))
        self.assertEqual({a.alert_id for a in alerts}, set(self.truth["alerts"]))
        self.assertTrue(all(a.side in ("ASK", "BID", "MID") for a in alerts))

    def test_bom_control_chars_preamble_and_renamed_columns(self):
        text = ("﻿export generated for demo\n"
                "Date,Ticker,Expiry,Strike,Put Call,Size,Market Side,Comments\n"
                "2026-03-09,zzxy,2026-04-17,50,Put,40\x07,AskSide,Opening buyer\n")
        path = _tmp(text)
        try:
            (a,) = parse_flow_alerts(path)
        finally:
            os.remove(path)
        self.assertEqual((a.symbol, a.cp, a.size, a.side, a.is_opening),
                         ("ZZXY", "P", 40, "ASK", True))

    def test_unknown_header_raises_instead_of_returning_nothing(self):
        path = _tmp("a,b,c\n1,2,3\n")
        try:
            self.assertRaises(FeedFormatError, parse_flow_alerts, path)
        finally:
            os.remove(path)


class OIChangeParser(FeedCase):
    def test_empty_cell_stays_none_not_zero(self):
        path = _tmp("date,symbol,expiry,strike,put_call,open_int,oi_change\n"
                    "2026-03-09,ZZXY,2026-04-17,50,Put,,\n")
        try:
            (r,) = parse_oi_change(path)
        finally:
            os.remove(path)
        self.assertIsNone(r.open_int)
        self.assertIsNone(r.oi_change)

    def test_parses_synthetic_day(self):
        rows = parse_oi_change(self.path("oi_change"))
        self.assertGreater(len(rows), 100)
        self.assertTrue(all(r.cp in ("C", "P") for r in rows))


class OpenCloseParser(FeedCase):
    def test_csv_scope_and_nets(self):
        rows = parse_open_close_csv(self.path("open_close"))
        scopes = {r.scope for r in rows}
        self.assertEqual(scopes, {"contract", "ticker"})
        r = [x for x in rows if x.scope == "contract"][0]
        self.assertEqual(r.cust_net, r.cust_buy - r.cust_sell)
        self.assertTrue(0 < r.coverage <= 1)

    def test_pasted_text_with_reordered_columns(self):
        text = ("ZZXY Jul26 370 Puts\n"
                "Time  FirmBuy FirmSell CustBuy CustSell MMBuy MMSell Total\n"
                "15:30       1       26       9       13    66     37    76\n")
        (r,) = parse_open_close_text(text, session_date="2026-03-10")
        self.assertEqual((r.symbol, r.strike, r.cp), ("ZZXY", 370.0, "P"))
        self.assertEqual((r.cust_buy, r.cust_sell, r.firm_buy, r.firm_sell), (9, 13, 1, 26))
        self.assertEqual(r.total, 76)

    def test_opposing_customer_and_firm_are_both_kept(self):
        text = ("QQZX 2026-04-17 50 Calls\n"
                "CustBuy CustSell FirmBuy FirmSell MMBuy MMSell Total\n"
                "     90       10       5       60    20     45   115\n")
        (r,) = parse_open_close_text(text)
        self.assertTrue(r.opposing())
        self.assertEqual((r.cust_net, r.firm_net), (80, -55))


class PositionsParser(FeedCase):
    def test_book_carries_provenance(self):
        book = load_position_book(self.path("positions"))
        self.assertEqual(book.source, self.path("positions"))
        self.assertEqual(len(book.sha256), 64)
        self.assertTrue(book.loaded_at)

    def test_preamble_and_trailer_are_skipped(self):
        book = load_position_book(self.path("positions"))
        symbols = {p.symbol for p in book.positions}
        self.assertFalse(any(s.startswith("DISCLAIMER") or s.startswith("ACCOUNT")
                             for s in symbols))
        self.assertIn("cash", {p.sec_type for p in book.positions})

    def test_position_delta_is_qty_times_contract_delta_times_100(self):
        book = load_position_book(self.path("positions"))
        shorts = [p for p in book.positions if p.is_option and p.qty < 0 and p.cp == "P"]
        self.assertTrue(shorts)
        for p in shorts:                      # short put: negative contract delta, positive exposure
            self.assertLess(p.contract_delta, 0)
            self.assertGreater(p.position_delta, 0)
            self.assertAlmostEqual(p.position_delta, p.qty * p.contract_delta * 100, places=2)

    def test_format_change_fails_loudly(self):
        path = _tmp("Instrument,Kind,Units\nZZXY,Stock,100\n")
        try:
            self.assertRaises(FeedFormatError, load_position_book, path)
        finally:
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
