"""flow_desk/render: four outputs from the same records.

  debrief.md    the morning drill shape: blockers first, then reads
  chart.svg     one chart: did open interest follow the alert?
  brief.html    the artifact shape: one self-contained page
  notify.json   the notification payload

Every output is built from the same integrity report and the same scored
records, so the four can never disagree with each other.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Dict, Optional

from .. import config
from ..integrity import provenance
from ..integrity.gates import RED
from .chart import render_chart
from .debrief import render_debrief
from .html import render_html
from .payload import render_payload

__all__ = ["render_all", "render_chart", "render_debrief", "render_html", "render_payload"]


def _write(path: str, text: str) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)                 # readers never see a half-written file


def render_all(out_dir: str, feed_dir: str, report: dict, result: Optional[dict],
               now: datetime) -> Dict[str, str]:
    """Write the outputs and return {name: path}. On a RED report the chart
    is not written (and a chart left over from an earlier run is removed):
    a stale picture next to a RED verdict invites the wrong read."""
    os.makedirs(out_dir, exist_ok=True)
    stamp = provenance.stamp_dict(feed_dir, sorted(config.LAYER_FILES.values()),
                                  "flow_desk.render", now)
    tail = provenance.stamp_text(stamp)
    blocked = report["overall"] == RED or result is None
    paths = {n: os.path.join(out_dir, n)
             for n in ("debrief.md", "chart.svg", "brief.html", "notify.json")}

    svg = None
    if blocked:
        if os.path.exists(paths["chart.svg"]):
            os.remove(paths["chart.svg"])
        del paths["chart.svg"]
    else:
        svg = render_chart(result["scored"], report["day"])
        _write(paths["chart.svg"], svg)
    _write(paths["debrief.md"], render_debrief(report, result) + tail)
    _write(paths["brief.html"], render_html(report, result, svg) + tail)
    _write(paths["notify.json"],
           json.dumps(render_payload(report, result, stamp), indent=2) + "\n")
    return paths
