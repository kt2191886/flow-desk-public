"""flow_desk/ingest/open_close.py: parse the open/close (account type) report.

The report splits a contract's volume by who traded: customer, firm, market
maker, each as buy and sell. It arrives two ways and both are parsed here.

1. CSV delivery:

    date,symbol,expiry,strike,put_call,cust_buy,cust_sell,firm_buy,firm_sell,mm_buy,mm_sell,total[,market_volume]

   Rows with a strike and a put/call are contract scope. Rows without are a
   blended aggregate (ticker scope) and are marked so.

2. Pasted text from a terminal:

    ZZXY Jul26 370 Puts
    Time   CustBuy CustSell FirmBuy FirmSell MMBuy MMSell Total
    15:30        9       13       1       26    66     37    76

Output: list of contracts.OpenClose.

Rules held here:
  * Customer and firm nets can point opposite ways on the same strike. Both
    are returned. They are never averaged into one number.
  * The report covers a subset of venues. `coverage` (when the feed gives
    all-venue volume) says how much of the contract it actually saw.
  * Only contract scope can resolve one leg. Coarser scopes are labeled and
    the scorer refuses to confirm from them.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import List, Optional

from ..contracts import OpenClose, cell_cp, cell_date, cell_float, cell_int, cell_str
from ._csvio import norm_col, read_table

REQUIRED = ("symbol", "cust_buy", "cust_sell", "firm_buy", "firm_sell", "mm_buy", "mm_sell")
ALIASES = {
    "sym": "symbol", "ticker": "symbol", "underlying": "symbol",
    "custbuy": "cust_buy", "customerbuy": "cust_buy", "custbuyvol": "cust_buy",
    "custsell": "cust_sell", "customersell": "cust_sell", "custsellvol": "cust_sell",
    "firmbuy": "firm_buy", "firmbuyvol": "firm_buy",
    "firmsell": "firm_sell", "firmsellvol": "firm_sell",
    "mmbuy": "mm_buy", "marketmakerbuy": "mm_buy", "mmbuyvol": "mm_buy",
    "mmsell": "mm_sell", "marketmakersell": "mm_sell", "mmsellvol": "mm_sell",
    "tot": "total", "totalvol": "total", "totalvolume": "total",
    "marketvolume": "market_volume", "allvenuevolume": "market_volume",
    "putcall": "put_call", "callput": "put_call", "cp": "put_call", "type": "put_call",
    "expiration": "expiry", "exp": "expiry",
}
_FIELDS = ("cust_buy", "cust_sell", "firm_buy", "firm_sell", "mm_buy", "mm_sell")


def parse_open_close_csv(path) -> List[OpenClose]:
    _, rows = read_table(path, REQUIRED, ALIASES)
    out: List[OpenClose] = []
    for r in rows:
        symbol = cell_str(r.get("symbol")).upper()
        if not symbol:
            continue
        vols = {f: cell_int(r.get(f)) or 0 for f in _FIELDS}
        strike = cell_float(r.get("strike"))
        cp = cell_cp(r.get("put_call"))
        out.append(OpenClose(
            session_date=cell_date(r.get("date")) or "",
            symbol=symbol,
            expiry=cell_date(r.get("expiry")),
            strike=strike, cp=cp,
            total=cell_int(r.get("total")) or sum(vols.values()),
            market_volume=cell_int(r.get("market_volume")),
            scope="contract" if (strike and cp) else "ticker",
            **vols))
    return out


# ---------------------------------------------------------------------------
# Pasted-text form

_CONTRACT_RE = re.compile(
    r"(?P<symbol>[A-Z\.]{1,6})\s+"
    r"(?P<expiry>[A-Z][a-z]{2}\d{2}|\d{4}-\d{2}-\d{2})\s+"
    r"(?:(?P<day>\d{1,2})(?:st|nd|rd|th)\s+)?"          # optional explicit day (weeklies)
    r"(?P<strike>\d+(?:\.\d+)?)\s+"
    r"(?P<cp>[Cc]alls?|[Pp]uts?|[CP])\b")
_NUM_ROW_RE = re.compile(r"^\s*(?:\d{1,2}:\d{2})?\s*((?:[\d,]+\s+){5,7}[\d,]+)\s*$")
_DEFAULT_ORDER = list(_FIELDS) + ["total"]


def _expiry(raw: str, day: Optional[str]) -> Optional[str]:
    if re.match(r"\d{4}-\d{2}-\d{2}$", raw):
        return raw
    try:
        d = datetime.strptime(raw, "%b%y")               # "Jul26": month and year only
        return d.date().replace(day=int(day) if day else 1).isoformat()
    except (ValueError, TypeError):
        return None


def parse_open_close_text(text: str, session_date: str = "") -> List[OpenClose]:
    """Parse one or more pasted blocks. Column order is read from each
    block's own header line, so a reordered export still lands correctly."""
    out: List[OpenClose] = []
    contract, order = None, None
    for line in (text or "").splitlines():
        names = [ALIASES.get(norm_col(t), norm_col(t)) for t in line.split()]
        if set(_FIELDS).issubset(names):          # a column header, in whatever order
            order = [n for n in names if n != "time"]
            continue
        m = _CONTRACT_RE.search(line)
        if m:
            contract = (m.group("symbol").upper(),
                        _expiry(m.group("expiry"), m.group("day")),
                        float(m.group("strike")), cell_cp(m.group("cp")))
            continue
        row = _NUM_ROW_RE.match(line)
        if row and contract:
            nums = [int(x.replace(",", "")) for x in re.findall(r"[\d,]+", row.group(1))]
            cols = order or _DEFAULT_ORDER
            data = dict(zip(cols, nums[-len(cols):]))
            vols = {f: data.get(f, 0) for f in _FIELDS}
            out.append(OpenClose(
                session_date=session_date, symbol=contract[0], expiry=contract[1],
                strike=contract[2], cp=contract[3],
                total=data.get("total", sum(vols.values())), scope="contract", **vols))
    return out
