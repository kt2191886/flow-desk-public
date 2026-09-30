"""flow_desk/ingest/_csvio.py: the defensive read every parser shares.

Real feeds arrive with a byte-order mark, stray control characters, a few
lines of preamble above the header, and column names that drift. Each of
those has silently broken a parser at least once, so the cleanup lives in
one place and every parser goes through it.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Dict, List, Tuple

_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_MAX_PREAMBLE_LINES = 10


class FeedFormatError(ValueError):
    """The file is not the shape this parser reads.

    Raised instead of returning an empty list. A parser that answers "zero
    rows" to a file it does not understand looks exactly like a quiet day.
    """


def norm_col(name) -> str:
    """'Cust Buy' / 'cust_buy' / 'CustBuy' all become 'custbuy'."""
    return re.sub(r"[^a-z0-9]+", "", (name or "").lower())


def read_table(path, required, aliases=None) -> Tuple[List[str], List[Dict[str, str]]]:
    """Read a CSV into (canonical header, list of row dicts).

    required  canonical column names that must all be present
    aliases   {normalized raw name: canonical name}

    Steps, in order: decode and drop the byte-order mark; strip control
    characters; skip preamble lines until a row contains every required
    column; map raw names to canonical names; drop blank rows.
    """
    path = Path(path)
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    text = _CTRL_RE.sub("", text)
    rows = [r for r in csv.reader(text.splitlines()) if any(c.strip() for c in r)]
    aliases = aliases or {}

    def canon(cell):
        n = norm_col(cell)
        return aliases.get(n, n)

    header, start = None, 0
    for idx, row in enumerate(rows[:_MAX_PREAMBLE_LINES]):
        cand = [canon(c) for c in row]
        if set(required).issubset(cand):
            header, start = cand, idx + 1
            break
    if header is None:
        raise FeedFormatError("%s: no header row with columns %s in the first %d lines"
                              % (path.name, sorted(required), _MAX_PREAMBLE_LINES))
    out = []
    for raw in rows[start:]:
        if len(raw) < len(header):
            raw = raw + [""] * (len(header) - len(raw))
        rec = {}
        for name, value in zip(header, raw):
            rec.setdefault(name, value)      # duplicated column names: first one wins
        out.append(rec)
    return header, out
