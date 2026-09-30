"""flow_desk/ingest/positions.py: parse the brokerage positions export.

Input shape: a wide CSV, sometimes with a few preamble lines above the
header and a disclaimer trailer below the data.

    Symbol,Security type,Quantity,Call/put,Strike,Expiration,Delta,...

Output: a contracts.PositionBook. The book carries the file's path, digest
and timestamps so the never-from-memory gate can prove, at any later point
in the run, that these positions came from that file and not from a cache,
a constant, or a model's recollection.

Notes on honesty of the extraction: a real brokerage export packs the whole
option contract into one symbol string. This public slice uses explicit
columns instead, so synthetic data can never resemble a real option symbol.
The defensive parts (preamble skip, duplicated column names, accounting
negatives, trailer rows, loud failure on an unknown header) are the real ones.
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

from ..contracts import Position, PositionBook, cell_cp, cell_date, cell_float, cell_str
from ._csvio import read_table

REQUIRED = ("symbol", "quantity", "securitytype")
ALIASES = {
    "callput": "cp", "putcall": "cp",
    "expiration": "expiry", "expirationdate": "expiry",
    "qty": "quantity", "type": "securitytype",
}
_SEC_TYPES = {"option": "option", "stock": "stock", "equity": "stock", "etf": "stock",
              "cash": "cash", "core": "cash", "moneymarket": "cash"}


def parse_positions(path):
    """Rows of the export as Position records. Raises FeedFormatError when the
    header is not recognized: an export format change must fail loudly, not
    return an empty book that reads as "no positions"."""
    _, rows = read_table(path, REQUIRED, ALIASES)
    out = []
    for r in rows:
        symbol = cell_str(r.get("symbol")).upper()
        if not symbol or symbol.startswith(("DISCLAIMER", "THE DATA", "DATE DOWNLOADED")):
            continue                                   # trailer text, not a holding
        sec = _SEC_TYPES.get(cell_str(r.get("securitytype")).lower().replace(" ", ""))
        qty = cell_float(r.get("quantity"))
        if sec is None or qty is None:
            continue
        cp = cell_cp(r.get("cp")) if sec == "option" else None
        out.append(Position(
            symbol=symbol, sec_type=sec, qty=qty, cp=cp,
            strike=cell_float(r.get("strike")) if sec == "option" else None,
            expiry=cell_date(r.get("expiry")) if sec == "option" else None,
            contract_delta=cell_float(r.get("delta")),
        ))
    return out


def load_position_book(path) -> PositionBook:
    """The ONE supported way to get positions into a run: read the file now."""
    p = Path(path)
    raw = p.read_bytes()
    return PositionBook(
        positions=parse_positions(p),
        source=str(p),
        sha256=hashlib.sha256(raw).hexdigest(),
        file_mtime=datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds"),
        loaded_at=datetime.now().isoformat(timespec="seconds"),
    )
