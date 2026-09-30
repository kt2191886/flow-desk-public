"""flow_desk/score/confirm.py: T+1 confirmation of flow alerts.

An alert says "someone traded N contracts". It does not say whether that
opened a position or closed one. Open interest settles overnight, so the
morning after (T+1) is the first time the claim can be checked: if open
interest grew by a meaningful share of the alert size, the print opened.

For every alert in the audit window:
  1. For each business day since the alert, look up that day's end-of-day
     open interest for the exact contract.
  2. Track cumulative growth against the alert-day baseline.
  3. Compute a verdict from the multi-day evidence.

The cardinal rule: NO EVIDENCE means NO ROW. A missing observation is never
recorded as zero open interest. "We could not see it" and "it did not
happen" are different facts, and only the second may count against an alert.

Pure functions over records. Standard library. Python 3.9.
"""
from __future__ import annotations

from datetime import date, datetime, time as dtime, timedelta
from typing import Dict, List, Optional

from .. import config

CONFIRMED, PARTIAL, NOT_CONFIRMED = "CONFIRMED", "PARTIAL", "NOT_CONFIRMED"
AMBIGUOUS, PENDING, EXPIRED = "AMBIGUOUS", "PENDING", "EXPIRED"


def _d(s) -> date:
    return s if isinstance(s, date) else datetime.strptime(str(s)[:10], "%Y-%m-%d").date()


def next_business_day(d: date) -> date:
    n = d + timedelta(days=1)
    while n.weekday() >= 5:
        n += timedelta(days=1)
    return n


def business_days(start: date, end: date) -> List[date]:
    """Weekdays in [start, end)."""
    out, cur = [], start
    while cur < end:
        if cur.weekday() < 5:
            out.append(cur)
        cur += timedelta(days=1)
    return out


def oi_available_for(target, now: datetime) -> bool:
    """True once end-of-day open interest for `target` has been published.

    Rule: the figure for trading day D is readable once the clock reaches
    OI_AVAILABLE_HOUR on the next weekday after D. Asking earlier returns
    nothing, and "nothing" cached as an answer poisons every later read.
    `now` is taken as exchange-local time.
    """
    target = _d(target)
    if target > now.date():
        return False
    ready = datetime.combine(next_business_day(target), dtime(config.OI_AVAILABLE_HOUR, 0))
    return now >= ready


def oi_series(oi_rows) -> Dict[str, Dict[str, dict]]:
    """{contract key: {session date: {open_int, oi_change}}} from OIChange records."""
    out: Dict[str, Dict[str, dict]] = {}
    for r in oi_rows or []:
        out.setdefault(r.key, {})[r.session_date] = {
            "open_int": r.open_int, "oi_change": r.oi_change}
    return out


def pick_eod_oi(series: Dict[str, dict], d) -> Optional[int]:
    """End-of-day open interest for day `d`.

    A session's row carries START-of-day open interest, so the end of day d
    is the open_int on the first session strictly after d, provided it lands
    within OI_MAX_GAP_DAYS. Returns None when there is no such evidence.
    Callers must treat None as unknown, never as zero.
    """
    if not series:
        return None
    d = _d(d)
    for sd in sorted(series):
        if _d(sd) <= d:
            continue
        if (_d(sd) - d).days > config.OI_MAX_GAP_DAYS:
            return None
        oi = series[sd].get("open_int")
        if oi is None:
            continue                  # published row, empty cell: keep looking
        return int(oi)
    return None


def build_snapshots(alert, series: Dict[str, dict], now: datetime) -> List[dict]:
    """One snapshot per business day with published evidence, oldest first."""
    sent = _d(alert.session_date)
    baseline = int(alert.oi_at_alert or 0)
    out = []
    for d in business_days(sent, now.date()):
        if not oi_available_for(d, now):
            continue                  # not published yet: do not look, do not guess
        oi = pick_eod_oi(series, d)
        if oi is None:
            continue                  # no evidence => no row
        out.append({"snapshot_date": d.isoformat(), "days_since_alert": (d - sent).days,
                    "oi": oi, "oi_growth": oi - baseline})
    return out


def compute_verdict(alert, snapshots: List[dict], today: date) -> dict:
    """Synthesize a verdict from an alert and its snapshots.

    CONFIRMED      growth reached CONFIRM_RATIO of the alert size, in the window
    PARTIAL        some growth; provisional, can still upgrade
    NOT_CONFIRMED  enough observed days with no growth, or locked at finalize
    AMBIGUOUS      evidence exists and does not settle it yet
    PENDING        no evidence yet (too early, or the contract is not in the feed)
    EXPIRED        the contract expired before a verdict locked
    """
    blank = {"verdict": PENDING, "growth_ratio": None, "max_growth": None,
             "max_growth_day": None, "snapshots": 0, "final": False}
    if not snapshots:
        return blank

    size = max(1, int(alert.size or 0))
    max_growth, max_day = 0, None
    for s in snapshots:
        if s["oi_growth"] > max_growth:
            max_growth, max_day = s["oi_growth"], s["days_since_alert"]
    ratio = max_growth / float(size)
    days_since = (today - _d(alert.session_date)).days

    verdict, final = AMBIGUOUS, False
    if _d(alert.expiry) < today:
        verdict, final = EXPIRED, True
    elif ratio >= config.CONFIRM_RATIO and max_day is not None \
            and max_day <= config.CONFIRM_WINDOW_DAYS:
        verdict, final = CONFIRMED, True
    elif days_since >= config.FINALIZE_DAYS:
        if ratio >= config.CONFIRM_RATIO:
            verdict = CONFIRMED
        elif ratio >= config.PARTIAL_RATIO:
            verdict = PARTIAL
        else:
            verdict = NOT_CONFIRMED
        final = True
    elif (days_since >= config.NOT_CONFIRM_DAYS
          and len(snapshots) >= config.NOT_CONFIRM_DAYS and max_growth <= 0):
        # Calendar age alone is not enough. The days must have been OBSERVED:
        # a weekend or a feed outage is not three days of "no growth".
        verdict, final = NOT_CONFIRMED, True
    elif ratio >= config.PARTIAL_RATIO:
        verdict = PARTIAL

    return {"verdict": verdict, "growth_ratio": round(ratio, 3), "max_growth": max_growth,
            "max_growth_day": max_day, "snapshots": len(snapshots), "final": final}


def confirm_all(alerts, oi_rows, now: datetime) -> Dict[str, dict]:
    """{alert_id: verdict dict} for every alert inside the audit window."""
    series = oi_series(oi_rows)
    cutoff = now.date() - timedelta(days=config.AUDIT_WINDOW_DAYS)
    out = {}
    for a in alerts or []:
        if _d(a.session_date) < cutoff:
            continue
        snaps = build_snapshots(a, series.get(a.key, {}), now)
        out[a.alert_id] = compute_verdict(a, snaps, now.date())
    return out
