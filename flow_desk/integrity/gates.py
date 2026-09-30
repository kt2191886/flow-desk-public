"""flow_desk/integrity/gates.py: the integrity gates.

Every check answers one question about the inputs and returns GREEN, AMBER
or RED with a one-line reason. The run's verdict is the worst single check.

  GREEN  proceed
  AMBER  proceed, and carry the caveat into every output
  RED    stop. Nothing downstream runs. The only output is the blocker list.

The gates never try to fix anything. Their job is to catch drift and say so
before a number reaches a person. Read-only. Standard library. Python 3.9.
"""
from __future__ import annotations

import hashlib
import os
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from .. import config

GREEN, AMBER, RED = "GREEN", "AMBER", "RED"
_RANK = {GREEN: 0, AMBER: 1, RED: 2}


class IntegrityBlocked(RuntimeError):
    """Raised when downstream code is asked to run on a RED (or absent) report."""


def chk(name: str, status: str, detail: str) -> dict:
    return {"check": name, "status": status, "detail": detail}


def _last_completed_session(today: date) -> date:
    """The most recent weekday strictly before `today`. Holiday-blind on
    purpose: this is a liveness heuristic, not an exchange calendar."""
    d = today - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


# ---------------------------------------------------------------------------
# The checks. Each returns chk(name, status, detail).

def check_completeness(feed_paths: Dict[str, str]) -> dict:
    """Required layers present. A missing required layer is RED; a missing
    optional layer is AMBER, because the run is still honest without it as
    long as the outputs say what was not available."""
    def missing(layers):
        return [n for n in layers
                if not (feed_paths.get(n) and os.path.isfile(feed_paths[n]))]
    req, opt = missing(config.REQUIRED_LAYERS), missing(config.OPTIONAL_LAYERS)
    if req:
        return chk("completeness", RED, "required layer missing: %s" % ", ".join(req))
    if opt:
        return chk("completeness", AMBER, "optional layer missing: %s" % ", ".join(opt))
    n = len(config.REQUIRED_LAYERS) + len(config.OPTIONAL_LAYERS)
    return chk("completeness", GREEN, "all %d layers present" % n)


def check_staleness(layer: str, path: Optional[str], now: datetime,
                    operator_away: bool = False) -> dict:
    """The file clock: data older than the layer's limit is RED.

    One exception, and it only ever softens to AMBER: when the operator has
    declared an absence, layers that a person drops by hand are expected to
    go dark. The check then reports the as-of time instead of paging. Layers
    that machines feed get no such allowance.
    """
    name = "staleness:%s" % layer
    limit = config.STALE_AFTER_HOURS.get(layer, 24)
    if not path or not os.path.isfile(path):
        return chk(name, RED, "no file to check")
    mtime = datetime.fromtimestamp(os.path.getmtime(path))
    age_h = (now - mtime).total_seconds() / 3600.0
    if age_h <= limit:
        return chk(name, GREEN, "%.1f h old (limit %d h)" % (max(age_h, 0.0), limit))
    asof = mtime.isoformat(timespec="minutes")
    if operator_away and layer in config.MANUAL_LAYERS:
        return chk(name, AMBER, "as of %s, stale EXPECTED (operator away)" % asof)
    return chk(name, RED, "stale: as of %s, %.1f h old (limit %d h)" % (asof, age_h, limit))


def check_rows(layer: str, records, parse_error: Optional[str] = None) -> dict:
    """A feed that parses to zero rows is an error, not a quiet day."""
    name = "rows:%s" % layer
    required = layer in config.REQUIRED_LAYERS
    if parse_error:
        return chk(name, RED if required else AMBER, "unreadable: %s" % parse_error[:120])
    n = len(records or [])
    if n == 0:
        return chk(name, RED if required else AMBER, "parsed to 0 rows")
    return chk(name, GREEN, "%d rows" % n)


def check_data_clock(oi_rows, now: datetime) -> dict:
    """The data clock: the newest session INSIDE the open-interest feed.

    A file can be freshly written and still carry old data (a cache re-saved,
    a vendor serving yesterday's snapshot). The file clock cannot see that.
    This check reads the dates in the rows themselves.
    """
    dates = [r.session_date for r in (oi_rows or []) if r.session_date]
    if not dates:
        return chk("data_clock", RED, "no session dates in the open-interest feed")
    newest = max(dates)
    need = _last_completed_session(now.date()).isoformat()
    if newest >= need:
        return chk("data_clock", GREEN, "newest session %s (need %s or later)" % (newest, need))
    return chk("data_clock", RED, "newest session %s is behind %s: fresh file, old data"
               % (newest, need))


def check_positions_from_disk(book) -> dict:
    """Never from memory. Positions must come from a file on disk, read
    during this run, and that file must still be the one that was read.

    RED when: there is no book; the book was assembled in code instead of
    loaded (no source); the source file is gone; or its digest no longer
    matches the digest taken at load time.
    """
    name = "positions_from_disk"
    if book is None:
        return chk(name, RED, "no position book")
    if not getattr(book, "source", None) or not getattr(book, "sha256", None):
        return chk(name, RED, "positions were not loaded from a file (in-memory book refused)")
    if not os.path.isfile(book.source):
        return chk(name, RED, "source file is gone: %s" % os.path.basename(book.source))
    with open(book.source, "rb") as fh:
        digest = hashlib.sha256(fh.read()).hexdigest()
    if digest != book.sha256:
        return chk(name, RED, "source file changed after it was read: reload it")
    return chk(name, GREEN, "%d rows read from %s at %s"
               % (len(book.positions), os.path.basename(book.source), book.loaded_at))


def check_held_coverage(book, oi_rows) -> dict:
    """Every symbol with a held option should appear in the open-interest
    feed. A held name with no data is the one the reader most needs to know
    about, so it is named, not averaged away."""
    held = sorted({p.symbol for p in (book.positions if book else []) if p.is_option})
    if not held:
        return chk("held_coverage", GREEN, "no held options to cover")
    seen = {r.symbol for r in (oi_rows or [])}
    gaps = [s for s in held if s not in seen]
    if gaps:
        return chk("held_coverage", AMBER, "held with no open-interest data: %s" % ", ".join(gaps))
    return chk("held_coverage", GREEN, "all %d held symbols covered" % len(held))


# ---------------------------------------------------------------------------
# Orchestration

def summarize(checks: List[dict], now: datetime) -> dict:
    """Fold checks into a report. The verdict is the worst single check."""
    overall = GREEN
    for c in checks:
        if _RANK[c["status"]] > _RANK[overall]:
            overall = c["status"]
    return {"day": now.date().isoformat(),
            "generated_at": now.isoformat(timespec="seconds"),
            "overall": overall, "checks": checks,
            "reds": [c["check"] for c in checks if c["status"] == RED],
            "ambers": [c["check"] for c in checks if c["status"] == AMBER]}


def run_gates(feed_paths: Dict[str, str], layers: dict, book, now: datetime,
              parse_errors: Optional[dict] = None, operator_away: bool = False) -> dict:
    """Run every gate. `layers` maps layer name to its parsed records (or None
    when the file was absent). A check that itself raises becomes AMBER with
    the reason: a broken check must never read as a passing one."""
    parse_errors = parse_errors or {}
    plan = [lambda: check_completeness(feed_paths)]
    for layer in config.REQUIRED_LAYERS + config.OPTIONAL_LAYERS:
        path = feed_paths.get(layer)
        if path and os.path.isfile(path):
            plan.append(lambda l=layer, p=path: check_staleness(l, p, now, operator_away))
            plan.append(lambda l=layer: check_rows(
                l, book.positions if (l == "positions" and book) else layers.get(l),
                parse_errors.get(l)))
    plan.append(lambda: check_data_clock(layers.get("oi_change"), now))
    plan.append(lambda: check_positions_from_disk(book))
    plan.append(lambda: check_held_coverage(book, layers.get("oi_change")))
    checks = []
    for fn in plan:
        try:
            checks.append(fn())
        except Exception as e:
            checks.append(chk("check_error", AMBER, "a check raised: %s" % str(e)[:80]))
    return summarize(checks, now)


def require_pass(report: Optional[dict]) -> dict:
    """The gate itself. Scoring and rendering of reads call this first."""
    if not report or report.get("overall") not in (GREEN, AMBER):
        reds = ", ".join((report or {}).get("reds") or ["no integrity report"])
        raise IntegrityBlocked("integrity is RED, reads withheld: %s" % reds)
    return report


def render_text(report: dict) -> str:
    lines = ["Integrity %s: %s" % (report["day"], report["overall"])]
    for c in report["checks"]:
        lines.append("  [%-5s] %-24s %s" % (c["status"], c["check"], c["detail"]))
    return "\n".join(lines)
