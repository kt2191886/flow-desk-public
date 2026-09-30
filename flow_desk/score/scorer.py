"""flow_desk/score/scorer.py: the five-axis alert scorer.

For each alerted contract it scores five independent axes and renders a
read, so a person can rank fresh flow without re-reading every alert:

  1. held       does the alert press on a short strike the book actually
                holds, in the same expiry cycle? (relevance to the book)
  2. build      distinct days the SAME contract recurs (accumulation)
  3. oi_support the T+1 verdict: did settled open interest follow the alert?
  4. open_close the account-type report agrees, at CONTRACT grain
  5. opening    the feed's own opening tag

Read is one of CORROBORATED / BUILDING / UNCONFIRMED / NEEDS_STRIKE_DRILL /
NEEDS_OPENCLOSE. The read is rule-based. The 0-100 score only orders rows
inside a read; it never upgrades one. (The private desk calls its top read
by the same word as the T+1 verdict. This slice renames it so the two can
not be confused: CONFIRMED is always the T+1 verdict, CORROBORATED is
always the scorer's read.)

This is the mechanism. The weights in config.py are neutral and the
thresholds are demo defaults: the public repo shows how a score is
assembled, not what the desk trades on.

score_alert() is pure (it takes a pre-loaded ctx), so it unit-tests with no
files. score_all() refuses to run on a RED integrity report.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Dict, List, Optional

from .. import config
from ..integrity.gates import require_pass

READ_CORROBORATED = "CORROBORATED"   # T+1 confirmed AND a second, independent axis agrees
READ_BUILDING = "BUILDING"
READ_UNCONFIRMED = "UNCONFIRMED"
READ_DRILL = "NEEDS_STRIKE_DRILL"        # only a blended read exists: check the strike
READ_NEEDS_OPENCLOSE = "NEEDS_OPENCLOSE"  # deep in the money: account type unresolved
HUMAN_QUEUE = (READ_DRILL, READ_NEEDS_OPENCLOSE)


def _d(s) -> Optional[date]:
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# The five axes (pure)

def held_overlap(alert, positions) -> dict:
    """A held SHORT whose strike the alert presses on: an alert put at or
    below a short put strike, or an alert call at or above a short call.

    Strike alone is not enough. A build only threatens a held short when it
    shares the short's expiry cycle (within SAME_CYCLE_MAX_DAYS). A match on
    strike in a different cycle is counted as context and never as overlap.
    """
    best, cross = None, 0
    a_exp = _d(alert.expiry)
    for p in positions or []:
        if not p.is_option or p.qty >= 0 or p.cp != alert.cp:
            continue
        presses = (alert.strike <= p.strike) if alert.cp == "P" else (alert.strike >= p.strike)
        if not presses:
            continue
        p_exp = _d(p.expiry)
        if not a_exp or not p_exp or abs((a_exp - p_exp).days) > config.SAME_CYCLE_MAX_DAYS:
            cross += 1
            continue
        if best is None or abs(p.strike - alert.strike) < abs(best.strike - alert.strike):
            best = p
    return {"overlap": best is not None,
            "held_strike": best.strike if best else None,
            "held_expiry": best.expiry if best else None,
            "cross_cycle_matches": cross}


def build_count(alert, days_by_key: Dict[str, set]) -> int:
    return len(days_by_key.get(alert.key, ()))


def oi_support(confirmation: Optional[dict]) -> dict:
    """Read straight from the T+1 verdict, so the scorer can never call
    open interest "supported" when the confirmation step has not."""
    conf = confirmation or {}
    return {"ratio": conf.get("growth_ratio"),
            "supported": conf.get("verdict") == "CONFIRMED",
            "partial": conf.get("verdict") == "PARTIAL"}


def open_close_support(contract_rows, ticker_rows, today: date) -> dict:
    """Corroboration from the account-type report.

    `agree` is True only at contract grain, on a fresh read, with adequate
    coverage, when the corroborating account is a net buyer with conviction.
    It is False when the read is there and says otherwise. It is None when
    the question cannot be answered: a stale read, a blended (ticker) read,
    or no read at all. None is never rounded to True or to False.
    """
    out = {"grain": "none", "agree": None, "imbalance": None, "coverage": None,
           "session": None, "opposing": False}
    if contract_rows:
        r = max(contract_rows, key=lambda x: x.session_date)
        net = r.cust_net if config.CORROBORATING_ACCOUNT == "customer" else r.firm_net
        imb = (net / float(r.total)) if r.total else 0.0
        out.update({"imbalance": round(imb, 3), "coverage": r.coverage,
                    "session": r.session_date, "opposing": r.opposing()})
        sess = _d(r.session_date)
        if sess and (today - sess).days > config.MAX_OPENCLOSE_AGE_DAYS:
            out["grain"] = "contract-stale"    # context with a date on it, not support
            return out
        cov_ok = r.coverage is None or r.coverage >= config.COVERAGE_FLOOR
        out["grain"] = "contract"
        out["agree"] = bool(net > 0 and imb >= config.IMBALANCE_FLOOR and cov_ok)
        return out
    if ticker_rows:
        r = max(ticker_rows, key=lambda x: x.session_date)
        out.update({"grain": "ticker", "session": r.session_date})
    return out


def deep_itm(alert) -> bool:
    """In the money by more than DEEP_ITM_MONEYNESS of the underlying price.
    Such prints are often one leg of a financing or synthetic structure, so
    the aggressor side says little. False when the price is unknown: never
    flag on a guess."""
    if not alert.spot or not alert.strike:
        return False
    depth = (alert.strike - alert.spot) if alert.cp == "P" else (alert.spot - alert.strike)
    return depth / alert.spot > config.DEEP_ITM_MONEYNESS


# ---------------------------------------------------------------------------
# Combine

def score_alert(alert, ctx: dict) -> dict:
    """ctx = {positions, days_by_key, confirmation, contract_open_close,
    ticker_open_close, today}. Returns the axis breakdown, a score and a read."""
    ho = held_overlap(alert, ctx.get("positions"))
    bc = build_count(alert, ctx.get("days_by_key", {}))
    oi = oi_support(ctx.get("confirmation"))
    oc = open_close_support(ctx.get("contract_open_close"), ctx.get("ticker_open_close"),
                            ctx.get("today") or date.today())
    is_build = bc >= config.BUILD_MIN_DAYS
    is_deep = deep_itm(alert)
    w = config.AXIS_WEIGHTS

    score = 0
    if oi["supported"]:
        score += w["oi_support"]
    elif oi["partial"]:
        score += w["oi_support"] // 2
    if oc["agree"] is True:
        score += w["open_close"]
    if is_build:
        score += w["build"]
    if alert.is_opening:
        score += w["opening"]
    if ho["overlap"]:
        score += w["held"]

    interesting = is_build or alert.is_opening or ho["overlap"] or oi["partial"] or oi["supported"]
    if is_deep and oc["grain"] != "contract" and interesting:
        # Hard guard. Never confirm a deep in-the-money print, or call it
        # directional, from the aggressor side. Ask for the account-type read.
        read = READ_NEEDS_OPENCLOSE
        oc["agree"] = None
    elif oi["supported"] and (oc["agree"] is True or is_build):
        read = READ_CORROBORATED
    elif oc["grain"] == "ticker" and interesting and not oi["supported"]:
        read = READ_DRILL
    elif is_build or alert.is_opening or oi["partial"]:
        read = READ_BUILDING
    else:
        read = READ_UNCONFIRMED

    conf = ctx.get("confirmation") or {}
    return {"alert_id": alert.alert_id, "symbol": alert.symbol, "strike": alert.strike,
            "cp": alert.cp, "expiry": alert.expiry, "size": alert.size,
            "last_seen": alert.session_date, "score": score, "read": read,
            "confirmation": conf.get("verdict", "PENDING"), "deep_itm": is_deep,
            "axes": {"held": ho, "build_days": bc, "oi_support": oi, "open_close": oc,
                     "opening": bool(alert.is_opening)}}


def _reason(row: dict) -> str:
    if row["read"] == READ_NEEDS_OPENCLOSE:
        return "deep in the money, account type unresolved: pull the contract open/close"
    return "only a blended open/close read exists: check this strike"


def score_all(report, alerts, confirmations, open_close, book, now: datetime) -> dict:
    """Score every alerted contract once. Refuses to run unless the integrity
    report passed: a scorer fed stale or partial inputs produces confident
    numbers, which is worse than producing none."""
    require_pass(report)
    days_by_key: Dict[str, set] = {}
    latest: Dict[str, object] = {}
    for a in alerts or []:
        days_by_key.setdefault(a.key, set()).add(a.session_date)
        prev = latest.get(a.key)
        if prev is None or a.session_date > prev.session_date \
                or (a.is_opening and not prev.is_opening):
            latest[a.key] = a
    oc_contract: Dict[str, list] = {}
    oc_ticker: Dict[str, list] = {}
    for r in open_close or []:
        if r.scope == "contract":
            oc_contract.setdefault(r.key, []).append(r)
        else:
            oc_ticker.setdefault(r.symbol, []).append(r)

    scored: List[dict] = []
    for a in latest.values():
        ctx = {"positions": book.held_options(a.symbol) if book else [],
               "days_by_key": days_by_key,
               "confirmation": (confirmations or {}).get(a.alert_id),
               "contract_open_close": oc_contract.get(a.key),
               "ticker_open_close": oc_ticker.get(a.symbol),
               "today": now.date()}
        scored.append(score_alert(a, ctx))
    scored.sort(key=lambda s: (-s["score"], s["symbol"], s["strike"]))

    by_read: Dict[str, int] = {}
    for s in scored:
        by_read[s["read"]] = by_read.get(s["read"], 0) + 1
    queue = [dict(alert_id=s["alert_id"], symbol=s["symbol"], strike=s["strike"], cp=s["cp"],
                  expiry=s["expiry"], read=s["read"], score=s["score"], reason=_reason(s))
             for s in scored if s["read"] in HUMAN_QUEUE]
    return {"day": now.date().isoformat(), "n_contracts": len(scored),
            "by_read": by_read, "scored": scored, "drill_queue": queue}
