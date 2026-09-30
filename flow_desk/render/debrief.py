"""flow_desk/render/debrief.py: the morning debrief, as markdown.

The shape is fixed and the order is the point: blockers first, then the
integrity table, then reads. A reader who stops after the first section
still knows whether anything below it can be trusted. On a RED run the
reads section is replaced by one line saying they were withheld.
"""
from __future__ import annotations

from typing import List, Optional

from ..integrity.gates import AMBER, GREEN, RED

_HEADLINE = {GREEN: "GREEN. Inputs passed every gate.",
             AMBER: "AMBER. Reads below carry the caveats listed under Blockers.",
             RED: "RED. Reads are withheld until the blockers are cleared."}
_VERDICT_ORDER = ["CONFIRMED", "PARTIAL", "AMBIGUOUS", "NOT_CONFIRMED", "PENDING", "EXPIRED"]
TOP_N = 15


def label(row: dict) -> str:
    return "%s %g%s %s" % (row["symbol"], row["strike"], row["cp"], row["expiry"])


def _pct(x) -> str:
    return "n/a" if x is None else "%d%%" % round(x * 100)


def verdict_counts(scored: List[dict]) -> List[tuple]:
    counts = {}
    for s in scored:
        counts[s["confirmation"]] = counts.get(s["confirmation"], 0) + 1
    return [(v, counts[v]) for v in _VERDICT_ORDER if v in counts]


def render_debrief(report: dict, result: Optional[dict]) -> str:
    overall = report["overall"]
    out = ["# Morning debrief: %s" % report["day"], "",
           "**Integrity: %s**" % _HEADLINE[overall], "",
           "_Synthetic data. Generated %s._" % report["generated_at"], "",
           "## 1. Blockers", ""]
    flagged = [c for c in report["checks"] if c["status"] in (RED, AMBER)]
    if not flagged:
        out.append("None.")
    for c in sorted(flagged, key=lambda c: c["status"] != RED):
        out.append("- **%s** `%s`: %s" % (c["status"], c["check"], c["detail"]))
    out += ["", "## 2. Integrity checks", "", "| Check | Status | Detail |", "|---|---|---|"]
    for c in report["checks"]:
        out.append("| `%s` | %s | %s |" % (c["check"], c["status"], c["detail"]))
    out += ["", "## 3. Reads", ""]

    if overall == RED or result is None:
        out += ["Withheld. A read built on inputs that failed a gate would look exactly "
                "like a read built on good ones. Clear the blockers and run again.", ""]
        return "\n".join(out)

    scored = result["scored"]
    queue = result["drill_queue"]
    out += ["### Needs a person (%d)" % len(queue), ""]
    if not queue:
        out.append("Nothing waiting on a decision.")
    for q in queue[:TOP_N]:
        out.append("- **%s** %s: %s" % (label(q), q["read"], q["reason"]))
    out += ["", "### T+1 confirmation (%d contracts)" % len(scored), "",
            ", ".join("%s %d" % vc for vc in verdict_counts(scored)) or "No alerts in window.",
            "", "PENDING means no evidence yet. It is never counted as a miss.", "",
            "### Corroborated and building (top %d by score)" % TOP_N, "",
            "| Score | Read | Contract | Size | OI growth | T+1 | Open/close | Build | Opening | Held |",
            "|---|---|---|---|---|---|---|---|---|---|"]
    top = [s for s in scored if s["read"] in ("CORROBORATED", "BUILDING")][:TOP_N]
    for s in top:
        ax = s["axes"]
        agree = ax["open_close"]["agree"]
        oc = "agrees" if agree is True else ("disagrees" if agree is False
                                             else "unknown (%s)" % ax["open_close"]["grain"])
        out.append("| %d | %s | %s | %d | %s | %s | %s | %dd | %s | %s |" % (
            s["score"], s["read"], label(s), s["size"], _pct(ax["oi_support"]["ratio"]),
            s["confirmation"], oc, ax["build_days"],
            "yes" if ax["opening"] else "no", "yes" if ax["held"]["overlap"] else "no"))
    if not top:
        out.append("| | | none | | | | | | | |")
    out += ["", "## 4. What this is not", "",
            "Not advice and not a signal. It ranks what to look at and shows its evidence. "
            "A person decides what, if anything, to do.", ""]
    return "\n".join(out)
