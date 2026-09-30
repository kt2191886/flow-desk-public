"""flow_desk/render/html.py: the brief as one self-contained page.

Same records, same order as the markdown debrief: verdict, blockers,
integrity table, then reads. No scripts, no external requests, no fonts
fetched: the page works opened from disk with the network off.

One color rule: vermilion appears only where a person has a decision to
make (a blocker to clear, a row in the needs-a-person queue).
"""
from __future__ import annotations

from html import escape
from typing import Optional

from ..integrity.gates import AMBER, RED
from .debrief import TOP_N, label, verdict_counts

_CSS = """
:root{--paper:#F3EEE3;--ink:#15130F;--muted:#6F695D;--rule:#CFC8B8;--decide:#C8331F}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);
 font-family:'Newsreader',Georgia,'Times New Roman',serif;font-size:17px;line-height:1.45}
main{max-width:860px;margin:0 auto;padding:28px 16px 56px}
h1,h2{font-family:'Bricolage Grotesque','Helvetica Neue',Arial,sans-serif;margin:0}
h1{font-size:30px;letter-spacing:-0.01em}
h2{font-size:15px;text-transform:uppercase;letter-spacing:0.08em;margin:34px 0 10px;
 padding-top:10px;border-top:1px solid var(--ink)}
.mono,td,th,.meta{font-family:'JetBrains Mono',ui-monospace,Menlo,Consolas,monospace;font-size:12.5px}
.meta{color:var(--muted);margin-top:6px}
.verdict{display:inline-block;margin-top:16px;padding:10px 14px;border:1px solid var(--ink);
 background:var(--paper);box-shadow:4px 4px 0 var(--ink);
 font-family:'Bricolage Grotesque','Helvetica Neue',Arial,sans-serif;font-weight:700}
.verdict.red{box-shadow:4px 4px 0 var(--decide);border-color:var(--decide)}
ul{padding-left:0;list-style:none;margin:0}
li{padding:8px 0 8px 12px;border-left:3px solid var(--rule);margin-bottom:6px}
li.decide{border-left-color:var(--decide)}
.scroll{overflow-x:auto}
table{border-collapse:collapse;width:100%}
th{text-align:left;font-weight:600;border-bottom:1px solid var(--ink);padding:6px 10px 6px 0;white-space:nowrap}
td{border-bottom:1px solid var(--rule);padding:6px 10px 6px 0;vertical-align:top}
svg{max-width:100%;height:auto;border:1px solid var(--ink);box-shadow:4px 4px 0 var(--ink)}
footer{margin-top:40px;padding-top:10px;border-top:1px solid var(--ink);color:var(--muted)}
"""

_HEADLINE = {"GREEN": "GREEN: inputs passed every gate",
             "AMBER": "AMBER: reads carry the caveats below",
             "RED": "RED: reads withheld"}


def _pct(x) -> str:
    return "n/a" if x is None else "%d%%" % round(x * 100)


def render_html(report: dict, result: Optional[dict], chart_svg: Optional[str]) -> str:
    overall = report["overall"]
    e = escape
    o = ["<!doctype html>", '<html lang="en"><head><meta charset="utf-8">',
         '<meta name="viewport" content="width=device-width, initial-scale=1">',
         "<title>Morning brief %s</title>" % e(report["day"]),
         "<style>%s</style></head><body><main>" % _CSS,
         "<h1>Morning brief</h1>",
         '<div class="meta">%s &middot; generated %s &middot; synthetic data</div>'
         % (e(report["day"]), e(report["generated_at"])),
         '<div class="verdict%s">Integrity %s</div>'
         % (" red" if overall == RED else "", e(_HEADLINE[overall])),
         "<h2>1. Blockers</h2>"]
    flagged = [c for c in report["checks"] if c["status"] in (RED, AMBER)]
    if not flagged:
        o.append("<p>None.</p>")
    else:
        o.append("<ul>")
        for c in sorted(flagged, key=lambda c: c["status"] != RED):
            o.append('<li class="%s"><span class="mono">%s %s</span><br>%s</li>'
                     % ("decide" if c["status"] == RED else "", e(c["status"]),
                        e(c["check"]), e(c["detail"])))
        o.append("</ul>")

    o.append('<h2>2. Integrity checks</h2><div class="scroll"><table><tr><th>Check</th>'
             "<th>Status</th><th>Detail</th></tr>")
    for c in report["checks"]:
        o.append("<tr><td>%s</td><td>%s</td><td>%s</td></tr>"
                 % (e(c["check"]), e(c["status"]), e(c["detail"])))
    o.append("</table></div><h2>3. Reads</h2>")

    if overall == RED or result is None:
        o.append("<p>Withheld. A read built on inputs that failed a gate would look exactly "
                 "like a read built on good ones. Clear the blockers and run again.</p>")
    else:
        queue = result["drill_queue"]
        o.append("<p><strong>Needs a person (%d).</strong></p>" % len(queue))
        if queue:
            o.append("<ul>")
            for q in queue[:TOP_N]:
                o.append('<li class="decide"><span class="mono">%s &middot; %s</span><br>%s</li>'
                         % (e(label(q)), e(q["read"]), e(q["reason"])))
            o.append("</ul>")
        else:
            o.append("<p>Nothing waiting on a decision.</p>")
        counts = ", ".join("%s %d" % vc for vc in verdict_counts(result["scored"]))
        o.append("<p><strong>T+1 confirmation.</strong> %s. Pending means no evidence yet; "
                 "it is never counted as a miss.</p>" % e(counts or "No alerts in window"))
        if chart_svg:
            o.append(chart_svg)
        o.append('<p><strong>Corroborated and building.</strong></p><div class="scroll"><table>'
                 "<tr><th>Score</th><th>Read</th><th>Contract</th><th>Size</th>"
                 "<th>OI growth</th><th>T+1</th><th>Open/close</th><th>Build</th></tr>")
        for s in [s for s in result["scored"] if s["read"] in ("CORROBORATED", "BUILDING")][:TOP_N]:
            ax = s["axes"]
            agree = ax["open_close"]["agree"]
            oc = "agrees" if agree is True else ("disagrees" if agree is False else "unknown")
            o.append("<tr><td>%d</td><td>%s</td><td>%s</td><td>%d</td><td>%s</td><td>%s</td>"
                     "<td>%s</td><td>%dd</td></tr>"
                     % (s["score"], e(s["read"]), e(label(s)), s["size"],
                        _pct(ax["oi_support"]["ratio"]), e(s["confirmation"]), oc,
                        ax["build_days"]))
        o.append("</table></div>")
    o.append("<footer class=\"meta\">Not advice and not a signal. It ranks what to look at "
             "and shows its evidence. A person decides.</footer></main></body></html>")
    return "\n".join(o) + "\n"
