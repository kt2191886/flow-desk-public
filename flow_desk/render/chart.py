"""flow_desk/render/chart.py: the one chart, as a standalone SVG.

Question the chart answers: did open interest follow the alert?
One bar per alerted contract. Bar length is open-interest growth as a share
of the alert size. Two reference lines mark the partial and confirm ratios.

A contract with no evidence gets NO bar and the words "no evidence yet".
Drawing it as a zero-length bar would say "nothing happened", which is a
different claim.

Standard library only: the SVG is assembled as text.
"""
from __future__ import annotations

from typing import List
from xml.sax.saxutils import escape

from .. import config
from .debrief import label

PAPER, INK, MUTED, RULE = "#F3EEE3", "#15130F", "#6F695D", "#CFC8B8"
LIGHT = "#A39C8C"
VERMILION = "#C8331F"          # reserved: marks a row that waits on a person
MONO = "'JetBrains Mono', ui-monospace, Menlo, Consolas, monospace"
HEAD = "'Bricolage Grotesque', 'Helvetica Neue', Arial, sans-serif"

FILL = {"CONFIRMED": INK, "PARTIAL": MUTED}
MAX_ROWS = 28
X_CAP = 1.5                     # ratios above this are drawn at the cap and labeled
W, LEFT, RIGHT, TOP, ROW = 760, 196, 150, 96, 20


def _rows(scored: List[dict]) -> List[dict]:
    have = [s for s in scored if s["axes"]["oi_support"]["ratio"] is not None]
    none = [s for s in scored if s["axes"]["oi_support"]["ratio"] is None]
    have.sort(key=lambda s: -s["axes"]["oi_support"]["ratio"])
    return (have + none)[:MAX_ROWS]


def render_chart(scored: List[dict], day: str) -> str:
    rows = _rows(scored)
    plot_w = W - LEFT - RIGHT
    height = TOP + ROW * max(len(rows), 1) + 64

    def x(ratio):
        return LEFT + plot_w * min(max(ratio, 0.0), X_CAP) / X_CAP

    o = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" '
         'role="img" aria-label="Open-interest growth as a share of alert size, by contract">'
         % (W, height, W, height),
         '<rect width="%d" height="%d" fill="%s"/>' % (W, height, PAPER),
         '<text x="16" y="30" font-family="%s" font-size="18" font-weight="700" fill="%s">'
         'Did open interest follow the alert?</text>' % (HEAD, INK),
         '<text x="16" y="50" font-family="%s" font-size="11" fill="%s">'
         'Growth in open interest as a share of alert size. One bar per alerted contract. '
         'Synthetic data, %s.</text>' % (MONO, MUTED, escape(day))]

    # reference lines: partial and confirm ratios, then the x axis ticks
    bottom = TOP + ROW * max(len(rows), 1)
    for ratio, name in ((config.PARTIAL_RATIO, "partial"), (config.CONFIRM_RATIO, "confirm")):
        o.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="%s" stroke-width="1" '
                 'stroke-dasharray="3 3"/>' % (x(ratio), TOP - 14, x(ratio), bottom, INK))
        o.append('<text x="%.1f" y="%d" font-family="%s" font-size="10" fill="%s" '
                 'text-anchor="middle">%s %d%%</text>'
                 % (x(ratio), TOP - 19, MONO, INK, name, round(ratio * 100)))
    for tick in (0.0, 0.5, 1.0, 1.5):
        o.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="%s" stroke-width="1"/>'
                 % (x(tick), bottom, x(tick), bottom + 4, RULE))
        o.append('<text x="%.1f" y="%d" font-family="%s" font-size="10" fill="%s" '
                 'text-anchor="middle">%d%%</text>'
                 % (x(tick), bottom + 16, MONO, MUTED, round(tick * 100)))
    o.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="%s" stroke-width="1"/>'
             % (LEFT, bottom, W - RIGHT, bottom, RULE))
    o.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="%s" stroke-width="1"/>'
             % (LEFT, TOP - 4, LEFT, bottom, INK))

    clear = x(config.PARTIAL_RATIO) + 6      # short bars: start the note past the first line
    for n, s in enumerate(rows):
        y = TOP + ROW * n
        ratio = s["axes"]["oi_support"]["ratio"]
        verdict = s["confirmation"]
        waits = s["read"] in ("NEEDS_STRIKE_DRILL", "NEEDS_OPENCLOSE")
        if waits:                     # marker sits just left of the right-aligned label
            mx = LEFT - 8 - 6.4 * len(label(s)) - 12
            o.append('<rect x="%.1f" y="%d" width="6" height="6" fill="%s"/>'
                     % (mx, y + 5, VERMILION))
        o.append('<text x="%d" y="%d" font-family="%s" font-size="10.5" fill="%s" '
                 'text-anchor="end">%s</text>' % (LEFT - 8, y + 12, MONO, INK, escape(label(s))))
        if ratio is None:
            o.append('<text x="%.1f" y="%d" font-family="%s" font-size="10" fill="%s" '
                     'stroke="%s" stroke-width="4" paint-order="stroke">no evidence yet</text>'
                     % (clear, y + 12, MONO, MUTED, PAPER))
            continue
        width = max(x(ratio) - LEFT, 1.0)
        o.append('<rect x="%d" y="%d" width="%.1f" height="10" fill="%s">'
                 '<title>%s: growth %d%% of alert size, %s</title></rect>'
                 % (LEFT, y + 4, width, FILL.get(verdict, LIGHT), escape(label(s)),
                    round(ratio * 100), verdict))
        note = "%d%%%s  %s" % (round(ratio * 100), "+" if ratio > X_CAP else "",
                               verdict.replace("_", " ").lower())
        o.append('<text x="%.1f" y="%d" font-family="%s" font-size="10" fill="%s" '
                 'stroke="%s" stroke-width="4" paint-order="stroke">%s</text>'
                 % (max(LEFT + width + 6, clear), y + 12, MONO, INK, PAPER, escape(note)))
    if not rows:
        o.append('<text x="%d" y="%d" font-family="%s" font-size="11" fill="%s">'
                 'No alerts in the window.</text>' % (LEFT + 6, TOP + 13, MONO, MUTED))

    # legend (identity is also written on every bar, so it never rests on tone alone)
    ly = bottom + 40
    lx = 16
    for fill, name in ((INK, "confirmed"), (MUTED, "partial"), (LIGHT, "not settled or not confirmed")):
        o.append('<rect x="%d" y="%d" width="14" height="8" fill="%s"/>' % (lx, ly - 8, fill))
        o.append('<text x="%d" y="%d" font-family="%s" font-size="10" fill="%s">%s</text>'
                 % (lx + 20, ly, MONO, INK, name))
        lx += 34 + 7 * len(name)
    o.append('<rect x="%d" y="%d" width="6" height="6" fill="%s"/>' % (lx, ly - 7, VERMILION))
    o.append('<text x="%d" y="%d" font-family="%s" font-size="10" fill="%s">'
             'waits on a person</text>' % (lx + 12, ly, MONO, INK))
    o.append("</svg>")
    return "\n".join(o) + "\n"
