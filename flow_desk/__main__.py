"""python -m flow_desk demo | eval

demo  generate a synthetic day, run the pipeline, write four outputs to out/
eval  score the gates and the T+1 confirmation against the planted truth
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime

from . import eval as evaluation
from . import pipeline, synth
from .contracts import Position, PositionBook


def _demo(args) -> int:
    now = datetime.now()
    out_dir = args.out
    feed_dir = os.path.join(out_dir, "feeds")
    synth.generate(feed_dir, seed=args.seed, now=now)
    kwargs = {"operator_away": args.away}
    if args.fault == "memory":
        kwargs["book"] = PositionBook(positions=[Position("ZZXY", "stock", 100)])
    elif args.fault:
        synth.FAULTS[args.fault](feed_dir, now)
    got = pipeline.run(feed_dir, out_dir, now=now, **kwargs)

    print(got["text"])
    print()
    if got["result"] is None:
        print("Reads withheld. Outputs carry the blocker list only.")
    else:
        r = got["result"]
        print("%d contracts scored. Needs a person: %d." % (r["n_contracts"], len(r["drill_queue"])))
    for name in sorted(got["paths"]):
        print("  wrote %s" % os.path.join(out_dir, name))
    print("notify: %s" % got["delivery"]["detail"])
    return got["exit_code"]


def _eval(args) -> int:
    res = evaluation.run_eval(seeds=args.seeds)
    print(evaluation.render_eval(res))
    return 0 if evaluation.passed(res) else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m flow_desk", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    d = sub.add_parser("demo", help="run one synthetic day end to end")
    d.add_argument("--out", default="out", help="output directory (default: out)")
    d.add_argument("--seed", type=int, default=7)
    d.add_argument("--fault", choices=sorted(list(synth.FAULTS) + ["memory"]),
                   help="break the day on purpose and watch the gate turn RED")
    d.add_argument("--away", action="store_true", help="operator has declared an absence")
    e = sub.add_parser("eval", help="gate scenarios and confirmation precision/recall")
    e.add_argument("--seeds", type=int, default=evaluation.DEFAULT_SEEDS)
    args = ap.parse_args(argv)
    if args.cmd == "demo":
        return _demo(args)
    if args.cmd == "eval":
        return _eval(args)
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
