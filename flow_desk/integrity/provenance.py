"""flow_desk/integrity/provenance.py: inputs_asof stamps and the stale-input check.

The problem: several producers write files on different clocks. A report can
ship minutes before a newer input lands, and nobody can tell afterwards.

The contract: every generated artifact ends with one stamp listing the input
files it actually read and their timestamps. check() compares the stamp with
the files as they are now and lists every input that is newer than stamped,
has gone missing, or has appeared since.

Stamp format for text artifacts: one comment block appended at the end of
the file (a comment placed before an html doctype changes how browsers
render the page, so the end is the only safe place). For json artifacts the
generator places the same dict under an "inputs_asof" key.

Paths are stored relative to the feed directory, never absolute.
Stamping is best-effort by design: it must never fail a build.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import List, Optional

VERSION = 1
_STAMP_RE = re.compile(
    r"<!--\s*inputs_asof\s+v(\d+)\s+generated=(\S+)\s+generator=(\S*)\s*\n(.*?)-->", re.S)


def _mtime_iso(path) -> Optional[str]:
    if not os.path.exists(path):
        return None
    return datetime.fromtimestamp(os.path.getmtime(path)).isoformat(timespec="seconds")


def snapshot(feed_dir: str, names: List[str]) -> List[dict]:
    out = []
    for name in names:
        m = _mtime_iso(os.path.join(feed_dir, name))
        out.append({"path": name, "mtime": m or "", "missing": 0 if m else 1})
    return out


def stamp_dict(feed_dir: str, names: List[str], generator: str, now: datetime) -> dict:
    return {"v": VERSION, "generated": now.isoformat(timespec="seconds"),
            "generator": generator, "inputs": snapshot(feed_dir, names)}


def stamp_text(stamp: dict) -> str:
    """The end-of-file comment block for .md and .html artifacts."""
    lines = ["<!-- inputs_asof v%d generated=%s generator=%s"
             % (stamp["v"], stamp["generated"], stamp["generator"] or "-")]
    for s in stamp["inputs"]:
        lines.append("src\t%s\t%s\t%d" % (s["path"], s["mtime"] or "-", s["missing"]))
    lines.append("-->")
    return "\n" + "\n".join(lines) + "\n"


def parse_stamp(text: str) -> Optional[dict]:
    m = None
    for m in _STAMP_RE.finditer(text):       # last stamp wins (re-renders append again)
        pass
    if m is None:
        return None
    inputs = []
    for ln in m.group(4).splitlines():
        parts = ln.split("\t")
        if len(parts) >= 4 and parts[0] == "src":
            inputs.append({"path": parts[1], "mtime": "" if parts[2] == "-" else parts[2],
                           "missing": int(parts[3] or 0)})
    return {"v": int(m.group(1)), "generated": m.group(2),
            "generator": m.group(3), "inputs": inputs}


def load_stamp(artifact_path: str) -> Optional[dict]:
    try:
        with open(artifact_path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        if artifact_path.endswith(".json"):
            return json.loads(text).get("inputs_asof")
        return parse_stamp(text)
    except (OSError, ValueError, AttributeError):
        return None


def check(artifact_path: str, feed_dir: str) -> Optional[List[dict]]:
    """Stale inputs for one artifact. None means the artifact carries no
    stamp (callers show that as AMBER: unknown is not the same as clean)."""
    stamp = load_stamp(artifact_path)
    if not stamp:
        return None
    stale = []
    for s in stamp.get("inputs", []):
        cur = _mtime_iso(os.path.join(feed_dir, s["path"]))
        if cur is None:
            if not s.get("missing"):
                stale.append({"source": s["path"], "reason": "missing_now"})
        elif s.get("missing"):
            stale.append({"source": s["path"], "reason": "appeared"})
        elif cur > s["mtime"]:
            stale.append({"source": s["path"], "reason": "newer",
                          "stamped": s["mtime"], "current": cur})
    return stale
