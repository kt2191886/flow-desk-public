"""flow_desk/synth.py: a day of synthetic feeds with a hidden ground truth.

generate() writes the four feed files the pipeline reads and RETURNS the
truth: for every alert, whether the print really opened a position. The
truth is never written next to the feeds and the pipeline never sees it.
Only eval.py holds both sides.

The world it simulates is deliberately not clean, so the eval number means
something:
  * an opening print adds open interest, but other participants closing
    can mask most of it (a true open that will look unconfirmed)
  * a non-opening print adds nothing, but unrelated opening flow in the same
    contract can look like confirmation (a false confirm)
  * some contracts are missing from the open-interest feed altogether (no
    evidence: the right answer is "pending", never "not confirmed")
  * the feed's own opening tag is a noisy claim, right most of the time

Symbols are invented and obviously fake. Nothing here resembles a real
instrument, account, or price. Deterministic for a given seed and clock.
"""
from __future__ import annotations

import csv
import os
import random
from datetime import datetime, timedelta
from typing import Dict, List

from . import config
from .contracts import contract_key

SYMBOLS = ["AAAA", "BBBX", "QQZX", "ZZXY", "XXYZ", "WWWQ"]
VENUES = ["XA", "XB", "XC", "XD"]
TRIGGERS = ["SIZE_VS_OI", "SWEEP", "REPEAT"]
N_SESSIONS = 10
N_ALERTS = 36


def sessions_before(now: datetime, n: int = N_SESSIONS) -> List[str]:
    """The last n weekdays strictly before now's date, oldest first."""
    out, d = [], now.date() - timedelta(days=1)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d -= timedelta(days=1)
    return out[::-1]


def _next_weekday(iso: str) -> str:
    d = datetime.strptime(iso, "%Y-%m-%d").date() + timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d.isoformat()


def _friday_on_or_after(d):
    while d.weekday() != 4:
        d += timedelta(days=1)
    return d


def _write(path: str, header: List[str], rows: List[list], preamble=None, trailer=None) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        for line in preamble or []:
            fh.write(line + "\n")
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)
        for line in trailer or []:
            fh.write(line + "\n")


def generate(feed_dir: str, seed: int = 7, now: datetime = None) -> dict:
    """Write the feeds into feed_dir and return the hidden truth."""
    now = now or datetime.now()
    rng = random.Random(seed)
    os.makedirs(feed_dir, exist_ok=True)
    sessions = sessions_before(now)
    publish = _next_weekday(sessions[-1])          # the row that settles the last session
    near = _friday_on_or_after(now.date() + timedelta(days=18))
    far = near + timedelta(days=28)

    # --- the contract universe -------------------------------------------
    spot = {s: round(rng.uniform(40, 220), 2) for s in SYMBOLS}
    contracts = []                                  # (symbol, expiry, strike, cp)
    for s in SYMBOLS:
        for exp in (near.isoformat(), far.isoformat()):
            for m in (0.85, 0.95, 1.0, 1.05, 1.15):
                strike = float(round(spot[s] * m))
                contracts.append((s, exp, strike, "P" if m <= 1.0 else "C"))
    deep = [(SYMBOLS[0], near.isoformat(), float(round(spot[SYMBOLS[0]] * 1.4)), "P"),
            (SYMBOLS[1], near.isoformat(), float(round(spot[SYMBOLS[1]] * 0.65)), "C")]
    contracts += deep
    builders = rng.sample(contracts[:-2], 4)        # contracts that recur across days
    dark = set(rng.sample([c for c in contracts[:-2] if c not in builders], 4))

    # --- alerts, with the planted truth ----------------------------------
    plan = []                                       # (session, contract, opened)
    for c in builders:
        for day in rng.sample(sessions[:-1], rng.choice((2, 3))):
            plan.append((day, c, rng.random() < 0.8))
    for c in deep:
        plan.append((rng.choice(sessions[-4:]), c, False))
    while len(plan) < N_ALERTS:
        plan.append((rng.choice(sessions), rng.choice(contracts[:-2]), rng.random() < 0.5))
    plan.sort(key=lambda p: (p[0], p[1]))

    alerts, truth = [], {}
    flow_by = {}                                    # (contract, session) -> OI added that day
    for n, (day, c, opened) in enumerate(plan):
        aid = "A%03d" % (n + 1)
        size = rng.choice((300, 500, 800, 1200, 2000, 3000))
        if opened:
            masked = rng.random() < 0.15            # others closing hide most of it
            added = size * (rng.uniform(0.05, 0.4) if masked else rng.uniform(0.6, 1.1))
        else:
            unrelated = rng.random() < 0.12         # someone else opened in the same contract
            added = size * rng.uniform(0.5, 0.9) if unrelated else 0.0
        flow_by[(c, day)] = flow_by.get((c, day), 0.0) + added
        tagged = rng.random() < (0.75 if opened else 0.2) or c in deep
        alerts.append({"id": aid, "day": day, "c": c, "size": size, "opened": opened,
                       "tagged": tagged,
                       "side": "AskSide" if rng.random() < (0.7 if opened else 0.4) else "BidSide",
                       "price": round(rng.uniform(0.5, 12), 2),
                       "time": "%02d:%02d:%02d" % (rng.randint(9, 15), rng.randint(0, 59),
                                                   rng.randint(0, 59))})
        truth[aid] = {"opened": opened, "evidence": c not in dark,
                      "key": contract_key(*c), "session": day}

    # --- open interest paths ---------------------------------------------
    oi_rows, start_oi = [], {}
    for c in contracts:
        oi = rng.randint(200, 5000)
        prev = None
        for day in sessions + [publish]:
            start_oi[(c, day)] = oi
            if c not in dark:
                oi_rows.append([day, c[0], c[1], "%g" % c[2], "Put" if c[3] == "P" else "Call",
                                oi, "" if prev is None else oi - prev])
            prev = oi
            oi = max(0, oi + int(round(flow_by.get((c, day), 0.0))) + int(rng.gauss(0, 12)))
    _write(os.path.join(feed_dir, config.LAYER_FILES["oi_change"]),
           ["date", "symbol", "expiry", "strike", "put_call", "open_int", "oi_change"], oi_rows)

    _write(os.path.join(feed_dir, config.LAYER_FILES["flow_alerts"]),
           ["id", "date", "time", "symbol", "expiry", "strike", "option", "size", "price",
            "side", "venue", "spot", "open_int", "comments", "trigger"],
           [[a["id"], a["day"], a["time"], a["c"][0], a["c"][1], "%g" % a["c"][2],
             "Put" if a["c"][3] == "P" else "Call", a["size"], a["price"], a["side"],
             rng.choice(VENUES), spot[a["c"][0]], start_oi[(a["c"], a["day"])],
             "Opening" if a["tagged"] else "", rng.choice(TRIGGERS)] for a in alerts])

    # --- open/close: contract grain for about half, ticker grain for one symbol
    oc_rows = []
    for a in alerts:
        if a["c"] in deep or a["c"][0] == SYMBOLS[-1] or rng.random() > 0.55:
            continue
        market = int(a["size"] * rng.uniform(1.2, 2.5))
        seen = max(10, int(market * rng.uniform(0.12, 0.7)))
        if a["opened"]:
            cb, cs = int(seen * rng.uniform(0.5, 0.75)), int(seen * rng.uniform(0.02, 0.15))
        else:
            cb, cs = int(seen * rng.uniform(0.2, 0.4)), int(seen * rng.uniform(0.2, 0.45))
        fb, fs = int(seen * rng.uniform(0.0, 0.15)), int(seen * rng.uniform(0.0, 0.15))
        oc_rows.append([a["day"], a["c"][0], a["c"][1], "%g" % a["c"][2],
                        "Put" if a["c"][3] == "P" else "Call",
                        cb, cs, fb, fs, cs + fs, cb + fb, cb + cs + fb + fs, market])
    seen = int(rng.uniform(4000, 9000))             # one blended, ticker-grain row
    oc_rows.append([sessions[-1], SYMBOLS[-1], "", "", "", int(seen * 0.4), int(seen * 0.3),
                    int(seen * 0.1), int(seen * 0.2), int(seen * 0.5), int(seen * 0.5), seen, ""])
    _write(os.path.join(feed_dir, config.LAYER_FILES["open_close"]),
           ["date", "symbol", "expiry", "strike", "put_call", "cust_buy", "cust_sell",
            "firm_buy", "firm_sell", "mm_buy", "mm_sell", "total", "market_volume"], oc_rows)

    # --- positions: a small synthetic book ---------------------------------
    alerted = sorted({a["c"] for a in alerts if a["c"] not in deep})
    puts = [c for c in alerted if c[3] == "P"][:2]
    calls = [c for c in alerted if c[3] == "C"][:1]
    pos = [[SYMBOLS[2], "Stock", 200, "", "", "", ""],
           [SYMBOLS[3], "Stock", 100, "", "", "", ""],
           ["CASHX", "Cash", "12,500.00", "", "", "", ""]]
    for c in puts:                                  # short puts the alerts can press on
        pos.append([c[0], "Option", -2, "Put", "%g" % c[2], c[1], round(-rng.uniform(0.2, 0.5), 3)])
    for c in calls:                                 # same strike, the OTHER cycle (context only)
        other = far.isoformat() if c[1] == near.isoformat() else near.isoformat()
        pos.append([c[0], "Option", -1, "Call", "%g" % c[2], other, round(rng.uniform(0.2, 0.5), 3)])
    _write(os.path.join(feed_dir, config.LAYER_FILES["positions"]),
           ["Symbol", "Security type", "Quantity", "Call/put", "Strike", "Expiration", "Delta"],
           pos, preamble=["Synthetic positions export", "Account: SYNTHETIC-DEMO"],
           trailer=["Disclaimer: synthetic data. No real account, holding, or price."])

    set_mtimes(feed_dir, now - timedelta(minutes=20))
    return {"seed": seed, "now": now.isoformat(timespec="seconds"), "alerts": truth}


def set_mtimes(feed_dir: str, when: datetime, only: str = None) -> None:
    """Pin file clocks (the staleness gate reads them)."""
    ts = when.timestamp()
    for layer, name in config.LAYER_FILES.items():
        path = os.path.join(feed_dir, name)
        if os.path.exists(path) and (only is None or only == layer):
            os.utime(path, (ts, ts))


# ---------------------------------------------------------------------------
# Faults: each breaks the feeds the way a real day does.

def fault_stale(feed_dir: str, now: datetime) -> None:
    """The open-interest drop did not arrive: yesterday's file is still there."""
    set_mtimes(feed_dir, now - timedelta(hours=30), only="oi_change")


def fault_missing(feed_dir: str, now: datetime) -> None:
    """A required layer never landed."""
    os.remove(os.path.join(feed_dir, config.LAYER_FILES["flow_alerts"]))


def fault_optional_missing(feed_dir: str, now: datetime) -> None:
    os.remove(os.path.join(feed_dir, config.LAYER_FILES["open_close"]))


def fault_empty(feed_dir: str, now: datetime) -> None:
    """Header only: parses cleanly to zero rows."""
    path = os.path.join(feed_dir, config.LAYER_FILES["flow_alerts"])
    with open(path, encoding="utf-8") as fh:
        header = fh.readline()
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(header)
    set_mtimes(feed_dir, now - timedelta(minutes=20), only="flow_alerts")


def fault_old_data(feed_dir: str, now: datetime) -> None:
    """A fresh file carrying old data: every session date pushed back two weeks."""
    path = os.path.join(feed_dir, config.LAYER_FILES["oi_change"])
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    for r in rows[1:]:
        d = datetime.strptime(r[0], "%Y-%m-%d").date() - timedelta(days=14)
        r[0] = d.isoformat()
    with open(path, "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(rows)
    set_mtimes(feed_dir, now - timedelta(minutes=5), only="oi_change")


def fault_format_change(feed_dir: str, now: datetime) -> None:
    """The export's header changed names overnight."""
    path = os.path.join(feed_dir, config.LAYER_FILES["positions"])
    with open(path, encoding="utf-8") as fh:
        text = fh.read().replace("Symbol,Security type,Quantity", "Instrument,Kind,Units")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    set_mtimes(feed_dir, now - timedelta(minutes=20), only="positions")


def fault_stale_positions(feed_dir: str, now: datetime) -> None:
    set_mtimes(feed_dir, now - timedelta(hours=60), only="positions")


FAULTS = {"stale": fault_stale, "missing": fault_missing, "empty": fault_empty,
          "olddata": fault_old_data, "format": fault_format_change}
