"""flow_desk/config.py: every threshold in one place, by name.

These are NEUTRAL DEMO DEFAULTS. The private desk tunes its own values and
its own axis weights; none of those are published. What this file shows is
which knobs exist and what each one guards, not where the desk sets them.
"""

# --- integrity gates ---------------------------------------------------------
# Layers the pipeline cannot run without. A missing required layer is RED.
REQUIRED_LAYERS = ("flow_alerts", "oi_change", "positions")
# Layers that add corroboration. Missing is AMBER: proceed, but say so.
OPTIONAL_LAYERS = ("open_close",)
# File names inside a feed directory, one per layer.
LAYER_FILES = {
    "flow_alerts": "flow_alerts.csv",
    "oi_change": "oi_change.csv",
    "open_close": "open_close.csv",
    "positions": "positions.csv",
}
# A feed file older than this many hours is stale.
STALE_AFTER_HOURS = {
    "flow_alerts": 24,
    "oi_change": 24,
    "open_close": 72,
    "positions": 24,
}
# Layers a person drops by hand. When the operator has declared an absence,
# staleness on these caps at AMBER (expected dark), never RED. Machine-fed
# layers still go RED.
MANUAL_LAYERS = ("positions", "open_close")
# While a RED persists, re-send the page at most this often.
RED_REPING_HOURS = 6

# --- T+1 confirmation --------------------------------------------------------
CONFIRM_RATIO = 0.50        # open interest grew by this share of the alert size
PARTIAL_RATIO = 0.10        # grew a little: provisional, can still upgrade
NOT_CONFIRM_DAYS = 3        # observed days of no growth before saying "not confirmed"
CONFIRM_WINDOW_DAYS = 5     # growth only confirms if it shows up this soon
FINALIZE_DAYS = 10          # after this many days the verdict locks
AUDIT_WINDOW_DAYS = 21      # alerts older than this leave the audit
OI_MAX_GAP_DAYS = 5         # next-session evidence must land within this gap
OI_AVAILABLE_HOUR = 7       # next business day, local exchange clock

# --- alert scorer ------------------------------------------------------------
BUILD_MIN_DAYS = 2          # same contract on this many distinct days is a build
DEEP_ITM_MONEYNESS = 0.20   # deeper in the money than this: account type must be resolved first
IMBALANCE_FLOOR = 0.15      # net buying, as a share of volume, that counts as conviction
COVERAGE_FLOOR = 0.20       # the open/close feed must see at least this share of the volume
MAX_OPENCLOSE_AGE_DAYS = 3  # an older open/close read is context, not confirmation
SAME_CYCLE_MAX_DAYS = 10    # an alert only threatens a held short in the same expiry cycle
# Which account type corroborates an alert is a strategy choice. The synthetic
# data plants its signal on the customer side, so the demo reads that side.
CORROBORATING_ACCOUNT = "customer"
# Neutral: every axis counts the same. The desk's real weights are not published.
AXIS_WEIGHTS = {"oi_support": 20, "open_close": 20, "build": 20, "opening": 20, "held": 20}

# --- notify ------------------------------------------------------------------
NOTIFY_MAX_CHARS = 2000     # hard limit for one chat message
NOTIFY_TIMEOUT_SEC = 10
