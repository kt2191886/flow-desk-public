"""flow_desk/notify/sender.py: the one sender. The only place anything leaves the machine.

If DISCORD_WEBHOOK_URL is set in the environment, the payload is posted to
that webhook. If it is not set, nothing is sent: the payload is already on
disk as notify.json and the sender says so. The URL is read from the
environment at send time and is never stored, logged or written anywhere.

Failures are log-and-continue by design. A dead webhook must never take
down a run, and it must never be reported as a delivery.

RED pages are de-duplicated (see should_push): page when the set of failing
checks CHANGES, re-page at most every RED_REPING_HOURS while it persists,
and send one recovery note when it clears. Without this, a known condition
re-pages on every scheduled run and the channel gets muted, which is how a
real page gets missed.
"""
from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime
from typing import Optional, Tuple

from .. import config

ENV_VAR = "DISCORD_WEBHOOK_URL"
STATE_FILE = ".notify_state.json"


def should_push(reds, state: Optional[dict], now: datetime) -> Tuple[bool, Optional[str]]:
    """(push?, kind) for the current RED set against the saved state. Pure.

    kind: 'new' (the set changed), 'heartbeat' (same set, re-page window
    passed), 'recovered' (set now empty, was not), None (stay quiet).
    """
    prev = set((state or {}).get("reds") or [])
    cur = set(reds or [])
    if not cur:
        return (True, "recovered") if prev else (False, None)
    if cur != prev:
        return True, "new"
    try:
        last = datetime.fromisoformat((state or {}).get("last_push_ts") or "")
    except ValueError:
        return True, "heartbeat"
    if (now - last).total_seconds() >= config.RED_REPING_HOURS * 3600:
        return True, "heartbeat"
    return False, None


def _load_state(out_dir: str) -> dict:
    try:
        with open(os.path.join(out_dir, STATE_FILE), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _save_state(out_dir: str, reds, pushed: bool, prev: dict, now: datetime) -> None:
    state = {"reds": sorted(set(reds or []))}
    # keep the earlier push time when this run stayed quiet
    state["last_push_ts"] = (now.isoformat(timespec="seconds") if pushed or not state["reds"]
                             else prev.get("last_push_ts"))
    try:
        with open(os.path.join(out_dir, STATE_FILE), "w", encoding="utf-8") as fh:
            json.dump(state, fh)
    except OSError:
        pass


def _post(url: str, content: str) -> bool:
    """POST one message. True on a 2xx answer. Never raises."""
    if not url.lower().startswith("https://"):
        print("notify: %s is not an https URL, refusing to send" % ENV_VAR)
        return False
    if len(content) > config.NOTIFY_MAX_CHARS:
        content = content[:config.NOTIFY_MAX_CHARS - 1] + "…"
    req = urllib.request.Request(
        url, data=json.dumps({"content": content}).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "flow-desk-notify"})
    try:
        with urllib.request.urlopen(req, timeout=config.NOTIFY_TIMEOUT_SEC) as resp:
            return 200 <= resp.status < 300
    except Exception as e:                       # noqa: BLE001 (log and continue, by design)
        print("notify: post failed (%s), continuing" % type(e).__name__)
        return False


def deliver(payload: dict, out_dir: str, now: datetime) -> dict:
    """Send the payload if a webhook is configured. Returns what happened:
    {"sent": bool, "kind": str, "detail": str}."""
    reds = payload.get("reds") or []
    prev = _load_state(out_dir)
    kind = "brief"
    if reds or prev.get("reds"):
        push, kind = should_push(reds, prev, now)
        if not push:
            _save_state(out_dir, reds, False, prev, now)
            return {"sent": False, "kind": "quiet",
                    "detail": "same RED set, inside the re-page window: staying quiet"}
    url = os.environ.get(ENV_VAR)
    if not url:
        _save_state(out_dir, reds, False, prev, now)
        return {"sent": False, "kind": kind,
                "detail": "%s is not set: payload written to notify.json, nothing was sent"
                          % ENV_VAR}
    title = payload.get("title", "")
    if kind == "heartbeat":
        title += " (re-page)"
    elif kind == "recovered":
        title = "Integrity recovered. " + title
    sent = _post(url, "**%s**\n%s" % (title, payload.get("body", "")))
    _save_state(out_dir, reds, sent, prev, now)
    return {"sent": sent, "kind": kind,
            "detail": "posted to the configured webhook" if sent else "post failed, see log line"}
