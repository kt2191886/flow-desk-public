"""flow_desk/pipeline.py: ingest -> gate -> confirm -> score -> render -> notify.

The order is the design. The integrity gates run after ingest and before
anything that produces a read. When the verdict is RED the pipeline still
renders and still notifies, but what it renders is the blocker list and
nothing else. There is no code path from a RED report to a scored alert.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Optional

from . import config
from .ingest import (FeedFormatError, load_position_book, parse_flow_alerts, parse_oi_change,
                     parse_open_close_csv)
from .integrity import RED, render_text, run_gates
from .notify import deliver
from .render import render_all
from .render.payload import render_payload
from .score import confirm_all, score_all

_PARSERS = {"flow_alerts": parse_flow_alerts, "oi_change": parse_oi_change,
            "open_close": parse_open_close_csv}
_UNSET = object()


def feed_paths(feed_dir: str) -> dict:
    return {layer: os.path.join(feed_dir, name) for layer, name in config.LAYER_FILES.items()}


def ingest(feed_dir: str):
    """Parse every layer that is present. Returns (layers, book, errors).
    A parser failure is captured, not raised: the gates decide what it means."""
    paths = feed_paths(feed_dir)
    layers, errors, book = {}, {}, None
    for layer, parse in _PARSERS.items():
        layers[layer] = None
        if os.path.isfile(paths[layer]):
            try:
                layers[layer] = parse(paths[layer])
            except (FeedFormatError, OSError, ValueError) as e:
                errors[layer] = str(e)
    if os.path.isfile(paths["positions"]):
        try:
            book = load_position_book(paths["positions"])
        except (FeedFormatError, OSError, ValueError) as e:
            errors["positions"] = str(e)
    return layers, book, errors


def run(feed_dir: str, out_dir: str, now: Optional[datetime] = None,
        operator_away: bool = False, book=_UNSET, send: bool = True) -> dict:
    """Run the whole day. Returns {report, result, paths, delivery, exit_code}.

    `book` exists so a caller can TRY to hand in positions it built itself.
    The never-from-memory gate is what stops that; see tests and eval.
    """
    now = now or datetime.now()
    layers, loaded_book, errors = ingest(feed_dir)
    if book is _UNSET:
        book = loaded_book
    report = run_gates(feed_paths(feed_dir), layers, book, now,
                       parse_errors=errors, operator_away=operator_away)

    result = None
    if report["overall"] != RED:
        confirmations = confirm_all(layers["flow_alerts"], layers["oi_change"], now)
        result = score_all(report, layers["flow_alerts"], confirmations,
                           layers.get("open_close"), book, now)

    paths = render_all(out_dir, feed_dir, report, result, now)
    delivery = {"sent": False, "kind": "off", "detail": "sending disabled for this run"}
    if send:
        delivery = deliver(render_payload(report, result), out_dir, now)
    return {"report": report, "result": result, "paths": paths, "delivery": delivery,
            "exit_code": 2 if report["overall"] == RED else 0,
            "text": render_text(report)}
