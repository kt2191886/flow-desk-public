"""flow_desk/render/payload.py: the notification payload.

Short on purpose. A notification carries the verdict and the counts, and
points at the brief. It never carries a read the brief would not show: on a
RED run the payload is the blocker list and nothing else.
"""
from __future__ import annotations

from typing import Optional

from ..contracts import Notification
from ..integrity.gates import RED
from .debrief import verdict_counts

CHANNEL = "morning-brief"


def render_payload(report: dict, result: Optional[dict], stamp: Optional[dict] = None) -> dict:
    overall = report["overall"]
    if overall == RED or result is None:
        reds = [c for c in report["checks"] if c["status"] == RED]
        note = Notification(
            channel=CHANNEL, severity="critical", ts=report["generated_at"],
            title="Integrity RED %s: reads withheld" % report["day"],
            body="\n".join("- %s: %s" % (c["check"], c["detail"]) for c in reds))
        counts = {}
    else:
        counts = dict(verdict_counts(result["scored"]))
        lines = ["Integrity %s. %d contracts scored." % (overall, result["n_contracts"]),
                 "T+1: " + (", ".join("%s %d" % kv for kv in counts.items()) or "none"),
                 "Needs a person: %d" % len(result["drill_queue"])]
        if report["ambers"]:
            lines.append("Caveats: " + ", ".join(report["ambers"]))
        note = Notification(
            channel=CHANNEL, severity="warn" if report["ambers"] else "info",
            ts=report["generated_at"],
            title="Morning brief %s: %s" % (report["day"], overall),
            body="\n".join(lines))
    payload = note.to_dict()
    payload.update({"integrity": overall, "reds": report["reds"], "ambers": report["ambers"],
                    "verdict_counts": counts, "synthetic": True})
    if stamp:
        payload["inputs_asof"] = stamp
    return payload
