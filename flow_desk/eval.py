"""flow_desk/eval.py: does it work, measured against a truth it cannot see.

Two questions, two numbers.

1. Do the gates catch what they claim to catch?
   Each fault scenario breaks a clean synthetic day in one specific way and
   states the verdict the gates must return. The score is scenarios that
   returned the expected verdict, out of scenarios run.

2. How good is the T+1 confirmation?
   synth.py plants which alerts truly opened a position. The pipeline only
   ever sees the feeds. Precision and recall of the CONFIRMED verdict are
   computed against the planted truth, pooled over many seeds.

   The synthetic world includes masked opens, look-alike flow and contracts
   with no data, so neither number is 1.0 and neither should be.

   One more count is reported because it is the invariant that matters
   most: alerts with NO evidence that were nevertheless marked
   NOT_CONFIRMED. That number must be zero.

The clock is fixed so the result is identical on every machine.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from datetime import datetime

from . import pipeline, synth
from .contracts import Position, PositionBook
from .ingest import load_position_book
from .integrity import AMBER, GREEN, RED, check_positions_from_disk
from .score import confirm_all

CLOCK = datetime(2026, 3, 11, 7, 30)        # a Wednesday morning, after the publish hour
DEFAULT_SEEDS = 25


def _memory_book() -> PositionBook:
    """Positions typed in from memory instead of read from a file."""
    return PositionBook(positions=[Position("ZZXY", "stock", 100)])


def _scenarios():
    # (name, fault function or None, extra run() arguments, expected verdict)
    return [
        ("clean day", None, {}, GREEN),
        ("required feed is stale", synth.fault_stale, {}, RED),
        ("required layer missing", synth.fault_missing, {}, RED),
        ("optional layer missing", synth.fault_optional_missing, {}, AMBER),
        ("feed parses to zero rows", synth.fault_empty, {}, RED),
        ("fresh file, old data", synth.fault_old_data, {}, RED),
        ("export format changed", synth.fault_format_change, {}, RED),
        ("positions supplied from memory", None, {"book": _memory_book()}, RED),
        ("stale positions, operator present", synth.fault_stale_positions, {}, RED),
        ("stale positions, operator away", synth.fault_stale_positions,
         {"operator_away": True}, AMBER),
    ]


def run_gate_scenarios(seed: int = 7) -> list:
    rows = []
    for name, fault, kwargs, expected in _scenarios():
        tmp = tempfile.mkdtemp(prefix="flow_desk_eval_")
        try:
            feeds, out = os.path.join(tmp, "feeds"), os.path.join(tmp, "out")
            synth.generate(feeds, seed=seed, now=CLOCK)
            if fault:
                fault(feeds, CLOCK)
            got = pipeline.run(feeds, out, now=CLOCK, send=False, **kwargs)
            overall = got["report"]["overall"]
            withheld = got["result"] is None
            ok = overall == expected and withheld == (expected == RED)
            rows.append({"scenario": name, "expected": expected, "got": overall, "ok": ok})
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    rows.append(_swap_scenario(seed))
    return rows


def _swap_scenario(seed: int) -> dict:
    """The positions file is replaced after it was read."""
    tmp = tempfile.mkdtemp(prefix="flow_desk_eval_")
    try:
        synth.generate(tmp, seed=seed, now=CLOCK)
        path = pipeline.feed_paths(tmp)["positions"]
        book = load_position_book(path)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("WWWQ,Stock,999,,,,\n")
        got = check_positions_from_disk(book)["status"]
        return {"scenario": "positions file swapped after load", "expected": RED,
                "got": got, "ok": got == RED}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run_confirmation_eval(seeds: int = DEFAULT_SEEDS) -> dict:
    tp = fp = fn = tn = 0
    no_evidence = fabricated = total = 0
    for seed in range(1, seeds + 1):
        tmp = tempfile.mkdtemp(prefix="flow_desk_eval_")
        try:
            truth = synth.generate(tmp, seed=seed, now=CLOCK)["alerts"]
            layers, _, _ = pipeline.ingest(tmp)
            verdicts = confirm_all(layers["flow_alerts"], layers["oi_change"], CLOCK)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        for aid, t in truth.items():
            v = verdicts[aid]["verdict"]
            total += 1
            said, was = v == "CONFIRMED", t["opened"]
            tp += said and was
            fp += said and not was
            fn += (not said) and was
            tn += (not said) and not was
            if not t["evidence"]:
                no_evidence += 1
                fabricated += v == "NOT_CONFIRMED"
    return {"seeds": seeds, "alerts": total, "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": round(tp / float(tp + fp), 3) if tp + fp else None,
            "recall": round(tp / float(tp + fn), 3) if tp + fn else None,
            "no_evidence_alerts": no_evidence, "fabricated_verdicts": fabricated}


def run_eval(seeds: int = DEFAULT_SEEDS) -> dict:
    gates = run_gate_scenarios()
    return {"gates": gates, "gates_passed": sum(g["ok"] for g in gates),
            "gates_total": len(gates), "confirmation": run_confirmation_eval(seeds)}


def render_eval(res: dict) -> str:
    c = res["confirmation"]
    lines = ["Gate scenarios: %d of %d returned the expected verdict"
             % (res["gates_passed"], res["gates_total"])]
    for g in res["gates"]:
        lines.append("  [%s] %-36s expected %-5s got %s"
                     % ("ok" if g["ok"] else "FAIL", g["scenario"], g["expected"], g["got"]))
    lines += ["",
              "T+1 confirmation against planted truth (%d seeds, %d alerts)"
              % (c["seeds"], c["alerts"]),
              "  precision %.3f   recall %.3f" % (c["precision"] or 0, c["recall"] or 0),
              "  confirmed and truly opened %d, confirmed but not opened %d, "
              "opened but not confirmed %d" % (c["tp"], c["fp"], c["fn"]),
              "  alerts with no evidence: %d. Marked NOT_CONFIRMED anyway: %d (must be 0)"
              % (c["no_evidence_alerts"], c["fabricated_verdicts"])]
    return "\n".join(lines)


def passed(res: dict) -> bool:
    return (res["gates_passed"] == res["gates_total"]
            and res["confirmation"]["fabricated_verdicts"] == 0)
