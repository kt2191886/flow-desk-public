"""flow_desk/ingest/oi_change.py: parse the open-interest change report.

Input shape: one CSV row per contract per session.

    date,symbol,expiry,strike,put_call,open_int,oi_change[,bid_hist,mid_hist,ask_hist]

Output: list of contracts.OIChange.

Dating rule (binding): for a row dated D, `open_int` is the figure at the
START of session D, which is the settled end-of-day figure for D-1. The
end-of-day open interest for D is therefore found on the NEXT session's row.
Reading the same-day row as "today's close" is off by one session.

The optional *_hist columns are lifetime cumulative volume by side. They
look like a daily buy/sell split and are not one. This parser does not
expose them, so nothing downstream can read direction from them.
"""
from __future__ import annotations

from typing import List

from ..contracts import OIChange, cell_cp, cell_date, cell_float, cell_int, cell_str
from ._csvio import read_table

REQUIRED = ("date", "symbol", "expiry", "strike", "put_call", "open_int")
ALIASES = {
    "sym": "symbol", "ticker": "symbol", "underlying": "symbol",
    "putcall": "put_call", "callput": "put_call", "cp": "put_call", "option": "put_call",
    "openint": "open_int", "openinterest": "open_int",
    "oichange": "oi_change", "oichanged": "oi_change",
}


def parse_oi_change(path) -> List[OIChange]:
    _, rows = read_table(path, REQUIRED, ALIASES)
    out: List[OIChange] = []
    for r in rows:
        day = cell_date(r.get("date"))
        expiry = cell_date(r.get("expiry"))
        strike = cell_float(r.get("strike"))
        cp = cell_cp(r.get("put_call"))
        symbol = cell_str(r.get("symbol")).upper()
        if not (day and expiry and strike and cp and symbol):
            continue
        out.append(OIChange(
            session_date=day, symbol=symbol, expiry=expiry, strike=strike, cp=cp,
            # An empty cell stays None. "Not yet published" is not zero.
            open_int=cell_int(r.get("open_int")),
            oi_change=cell_int(r.get("oi_change")),
        ))
    return out
