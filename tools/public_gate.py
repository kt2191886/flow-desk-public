#!/usr/bin/env python3
"""tools/public_gate.py: the last check before this tree is published.

Walks every file under the repo root (generated output included, .git
excluded) and fails on anything that must never be public. Exit 0 only when
there are zero hits. Exit 1 on any hit. Exit 2 when --require-blocklist is
given and no external blocklist was loaded.

Two layers of rules:

1. Generic rules, defined below and shipped with the repo. They describe
   SHAPES of private data: home-directory paths, long digit runs, URLs that
   are not on the allowlist, private network addresses, email addresses,
   webhook endpoints, key assignments, money amounts, option-symbol strings,
   and file kinds that should never travel (backups, databases, env files).

2. An external blocklist, kept OUTSIDE the repo and passed with --blocklist
   (or the FLOW_DESK_BLOCKLIST environment variable). It holds the actual
   private strings: real symbols, names, hosts, account fragments, provider
   names. Shipping that list inside the repo would publish the very things
   it exists to catch. One entry per line:

       ticker:ABC     whole word, case-sensitive
       re:<regex>     regular expression
       anything else  case-insensitive substring
       # comment

The gate catches strings, not meaning. It does not replace reading every
file once by eye before publishing.

    python tools/public_gate.py [--blocklist PATH] [--require-blocklist] [ROOT]
"""
from __future__ import annotations

import argparse
import os
import re
import sys

SKIP_DIRS = {".git", "__pycache__"}
# Directory names that must not exist anywhere in a public tree.
BLOCKED_DIRS = {"data", "db", "logs", "backups", "briefings", "research", "scratch"}
BLOCKED_FILE_RE = re.compile(r"(\.bak(\.|$)|\.db$|\.sqlite3?$|^\.env$|\.pem$|\.key$)")

# URLs that may appear. Everything else is a hit.
URL_ALLOW = (
    "http://www.w3.org/2000/svg",                       # the SVG namespace
    "https://github.com/kt2191886/flow-desk-public",    # this repo
    "https://example.invalid/",                         # reserved test host
)

# The standard license text is all capitals in places and collides with
# short whole-word symbols. Exempt from the ticker rule only.
TICKER_EXEMPT_FILES = {"LICENSE"}

# Patterns are assembled from pieces so this file does not match itself.
_HOME = "/" + "Users" + "/"
GENERIC_RULES = [
    ("home_path", re.compile(re.escape(_HOME) + r"|/home/[a-z]")),
    ("long_number", re.compile(r"\d{8,}")),
    ("private_ip", re.compile(r"\b(?:192\.168|10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b")),
    ("tailnet_host", re.compile(r"\.ts\.net\b")),
    ("email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+\.[A-Za-z]{2,}")),
    ("webhook", re.compile(r"discord(?:app)?\.com/api/" + "webhooks", re.I)),
    ("key_assignment", re.compile(
        r"(?i)\b(?:api[_-]?key|secret|token|passwd|password)\b\s*[:=]\s*[\"'][A-Za-z0-9_\-]{12,}[\"']")),
    ("bearer", re.compile(r"Bearer\s+[A-Za-z0-9._\-]{16,}")),
    ("money_amount", re.compile(r"\$\s?\d")),
    ("option_symbol", re.compile(r"(?<![A-Za-z0-9])-?[A-Z]{1,6}\d{6}[CP]\d+")),
]
URL_RE = re.compile(r"https?://[^\s\"'<>)\]]+")


def load_blocklist(path):
    """[(label, compiled regex, is_ticker)] from an external blocklist file."""
    rules = []
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("ticker:"):
                word = line[len("ticker:"):].strip()
                rules.append(("blocklist", re.compile(
                    r"(?<![A-Za-z0-9_])%s(?![A-Za-z0-9_])" % re.escape(word)), True))
            elif line.startswith("re:"):
                rules.append(("blocklist", re.compile(line[len("re:"):].strip()), False))
            else:
                rules.append(("blocklist", re.compile(re.escape(line), re.I), False))
    return rules


def scan(root, blocklist=None):
    """Return (sorted hit lines, files scanned). A hit reads
    'path:line: [rule] excerpt'."""
    hits, n_files = [], 0
    blocklist = blocklist or []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        rel_dir = os.path.relpath(dirpath, root)
        for d in dirnames:
            if d in BLOCKED_DIRS:
                hits.append("%s: [blocked_dir] directory name is not allowed in a public tree"
                            % os.path.normpath(os.path.join(rel_dir, d)))
        for name in sorted(filenames):
            rel = os.path.normpath(os.path.join(rel_dir, name))
            n_files += 1
            if BLOCKED_FILE_RE.search(name):
                hits.append("%s: [blocked_file] file kind is not allowed in a public tree" % rel)
                continue
            try:
                with open(os.path.join(dirpath, name), encoding="utf-8") as fh:
                    lines = fh.read().splitlines()
            except UnicodeDecodeError:
                hits.append("%s: [binary] not text, cannot be verified" % rel)
                continue
            for n, line in enumerate(lines, 1):
                for rule, rx in GENERIC_RULES:
                    m = rx.search(line)
                    if m:
                        hits.append("%s:%d: [%s] %s" % (rel, n, rule, m.group(0)[:60]))
                for m in URL_RE.finditer(line):
                    if not m.group(0).startswith(URL_ALLOW):
                        hits.append("%s:%d: [url] %s" % (rel, n, m.group(0)[:80]))
                for rule, rx, is_ticker in blocklist:
                    if is_ticker and name in TICKER_EXEMPT_FILES:
                        continue
                    m = rx.search(line)
                    if m:
                        hits.append("%s:%d: [%s] %s" % (rel, n, rule, m.group(0)[:60]))
    return sorted(hits), n_files


def main(argv=None):
    ap = argparse.ArgumentParser(description="Fail if the tree holds anything private.")
    ap.add_argument("root", nargs="?",
                    default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--blocklist", default=os.environ.get("FLOW_DESK_BLOCKLIST"))
    ap.add_argument("--require-blocklist", action="store_true")
    args = ap.parse_args(argv)

    blocklist = []
    if args.blocklist and os.path.isfile(args.blocklist):
        blocklist = load_blocklist(args.blocklist)
        print("external blocklist: loaded, %d entries" % len(blocklist))
    else:
        print("external blocklist: NOT LOADED (generic rules only)")
        if args.require_blocklist:
            print("FAIL: --require-blocklist was given and no blocklist could be read")
            return 2

    hits, files = scan(args.root, blocklist)
    for h in hits:
        print(h)
    print("scanned %d files under %s" % (files, os.path.basename(os.path.abspath(args.root))))
    print("PUBLIC GATE: %s (%d hits)" % ("PASS" if not hits else "FAIL", len(hits)))
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
