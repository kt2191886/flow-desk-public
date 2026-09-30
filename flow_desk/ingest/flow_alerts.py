"""flow_desk/ingest/flow_alerts.py: parse the flow feed's alert export.

Input shape: one CSV row per flagged print.

    [id,]date,time,symbol,expiry,strike,option,size,price,side,venue,spot,open_int,comments,trigger

Output: list of contracts.FlowAlert.

Two rules this parser holds on purpose:
  * `side` is the AGGRESSOR side (did the print lift the offer or hit the
    bid). It says nothing about who traded. Account type comes only from the
    open/close layer.
  * `is_opening` is the feed's own tag, read from the comments column. It is
    a claim to be verified against next-day open interest, not a fact.
"""
from __future__ import annotations

from typing import List

from ..contracts import FlowAlert, cell_cp, cell_date, cell_float, cell_int, cell_str
from ._csvio import read_table

REQUIRED = ("date", "symbol", "expiry", "strike", "option", "size")
ALIASES = {
    "sym": "symbol", "ticker": "symbol", "underlying": "symbol",
    "putcall": "option", "callput": "option", "cp": "option", "type": "option",
    "marketside": "side", "exchange": "venue",
    "openint": "open_int", "openinterest": "open_int",
    "triggerlabel": "trigger",
}


def _side(raw) -> str:
    s = cell_str(raw).lower().replace("-", "").replace(" ", "")
    if s in ("ask", "askside", "aboveask"):
        return "ASK"
    if s in ("bid", "bidside", "belowbid"):
        return "BID"
    return "MID"


def parse_flow_alerts(path) -> List[FlowAlert]:
    _, rows = read_table(path, REQUIRED, ALIASES)
    out: List[FlowAlert] = []
    for n, r in enumerate(rows):
        day = cell_date(r.get("date"))
        expiry = cell_date(r.get("expiry"))
        strike = cell_float(r.get("strike"))
        cp = cell_cp(r.get("option"))
        symbol = cell_str(r.get("symbol")).upper()
        size = cell_int(r.get("size"))
        if not (day and expiry and strike and cp and symbol and size):
            continue                                  # not a usable alert row
        out.append(FlowAlert(
            alert_id=cell_str(r.get("id")) or "%s-%04d" % (day, n + 1),
            session_date=day, symbol=symbol, expiry=expiry, strike=strike, cp=cp,
            size=size,
            price=cell_float(r.get("price")),
            side=_side(r.get("side")),
            spot=cell_float(r.get("spot")),
            oi_at_alert=cell_int(r.get("open_int")),
            is_opening="open" in cell_str(r.get("comments")).lower(),
            venue=cell_str(r.get("venue")) or None,
            trigger=cell_str(r.get("trigger")),
        ))
    return out
