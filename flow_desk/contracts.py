"""flow_desk/contracts.py: the shared record model.

Every parser in ingest/ normalizes its raw feed into one of these records.
Everything downstream (gates, scorer, renderers) speaks only this vocabulary,
so a change in a vendor's column names is absorbed in exactly one parser.

Standard library only. Python 3.9.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Small, forgiving cell parsers (a feed is text; tolerate "", "--", None)

def cell_str(v: Any) -> str:
    return "" if v is None else str(v).strip()


def cell_float(v: Any) -> Optional[float]:
    s = cell_str(v).replace(",", "").replace("%", "")
    if not s or s in ("--", "-", "N/A"):
        return None
    neg = s.startswith("(") and s.endswith(")")     # accounting-style negative
    if neg:
        s = s[1:-1]
    try:
        x = float(s.replace("+", ""))
    except ValueError:
        return None
    return -x if neg else x


def cell_int(v: Any) -> Optional[int]:
    x = cell_float(v)
    return None if x is None else int(round(x))


def cell_date(v: Any) -> Optional[str]:
    """Normalize a date cell to ISO yyyy-mm-dd, or None if it is not a date."""
    s = cell_str(v).strip('"')
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d-%b-%Y", "%b-%d-%Y"):
        try:
            return datetime.strptime(s[:11].strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def cell_cp(v: Any) -> Optional[str]:
    s = cell_str(v).lower()
    if s.startswith("c"):
        return "C"
    if s.startswith("p"):
        return "P"
    return None


def contract_key(symbol, expiry, strike, cp) -> str:
    """Stable identity for one option contract: symbol|expiry|strike|cp."""
    return "%s|%s|%g|%s" % (str(symbol or "").upper(), str(expiry or "")[:10],
                            float(strike or 0), str(cp or "").upper()[:1])


# ---------------------------------------------------------------------------
# Records

@dataclass
class FlowAlert:
    """One large options print flagged by the flow feed."""
    alert_id: str
    session_date: str                 # ISO date the print happened
    symbol: str
    expiry: str
    strike: float
    cp: str                           # 'C' | 'P'
    size: int                         # contracts
    price: Optional[float] = None
    side: str = "MID"                 # 'ASK' | 'BID' | 'MID' (aggressor side, NOT account type)
    spot: Optional[float] = None      # underlying price at the alert
    oi_at_alert: Optional[int] = None  # open interest at the start of that session
    is_opening: bool = False          # the feed's own "opening" tag
    venue: Optional[str] = None
    trigger: str = ""

    @property
    def key(self) -> str:
        return contract_key(self.symbol, self.expiry, self.strike, self.cp)


@dataclass
class OIChange:
    """One contract's open interest for one session.

    open_int is START-of-session open interest, which equals the settled
    end-of-day figure of the previous session. See score/confirm.py for why
    that distinction is the whole game.
    """
    session_date: str
    symbol: str
    expiry: str
    strike: float
    cp: str
    open_int: Optional[int] = None
    oi_change: Optional[int] = None

    @property
    def key(self) -> str:
        return contract_key(self.symbol, self.expiry, self.strike, self.cp)


@dataclass
class OpenClose:
    """Buy/sell volume by account type for one contract (or a coarser scope).

    scope says how much this record can prove:
      contract  one specific strike and expiry. The only scope that can
                resolve who was on the other side of an alert.
      ticker    every contract of the symbol blended together.
      basket    a whole watchlist blended together.
    ticker and basket are screening color. They never resolve a single leg.
    """
    session_date: str
    symbol: str
    expiry: Optional[str]
    strike: Optional[float]
    cp: Optional[str]
    cust_buy: int = 0
    cust_sell: int = 0
    firm_buy: int = 0
    firm_sell: int = 0
    mm_buy: int = 0
    mm_sell: int = 0
    total: int = 0
    market_volume: Optional[int] = None   # all-venue volume, when the feed reports it
    scope: str = "contract"

    @property
    def key(self) -> str:
        return contract_key(self.symbol, self.expiry, self.strike, self.cp)

    @property
    def cust_net(self) -> int:
        return self.cust_buy - self.cust_sell

    @property
    def firm_net(self) -> int:
        return self.firm_buy - self.firm_sell

    @property
    def mm_net(self) -> int:
        return self.mm_buy - self.mm_sell

    @property
    def coverage(self) -> Optional[float]:
        """Share of the contract's volume this feed actually saw (0..1), if known."""
        if not self.market_volume:
            return None
        return round(min(1.0, self.total / float(self.market_volume)), 4)

    def opposing(self) -> bool:
        """Customer and firm nets point opposite ways. Both are kept, never averaged."""
        if self.cust_net == 0 or self.firm_net == 0:
            return False
        return (self.cust_net > 0) != (self.firm_net > 0)


@dataclass
class Position:
    """One row of the positions export."""
    symbol: str                       # underlying
    sec_type: str                     # 'option' | 'stock' | 'cash'
    qty: float                        # signed: positive long, negative short
    cp: Optional[str] = None
    strike: Optional[float] = None
    expiry: Optional[str] = None
    contract_delta: Optional[float] = None   # the option's own greek, per contract

    @property
    def is_option(self) -> bool:
        return self.sec_type == "option"

    @property
    def position_delta(self) -> Optional[float]:
        """Exports carry CONTRACT delta. Exposure is qty x contract delta x 100.

        A short call has a positive contract delta and a negative position
        delta. Reading the raw column for a short gets the sign wrong.
        """
        if self.sec_type == "stock":
            return self.qty
        if not self.is_option or self.contract_delta is None:
            return None
        return round(self.qty * self.contract_delta * 100.0, 2)


@dataclass
class PositionBook:
    """Positions plus the proof of where they came from.

    Build one ONLY with ingest.positions.load_position_book(path). A book
    assembled in memory has source=None and the never-from-memory gate turns
    the whole run RED.
    """
    positions: List[Position] = field(default_factory=list)
    source: Optional[str] = None      # path of the file that was read
    sha256: Optional[str] = None      # digest of that file at load time
    file_mtime: Optional[str] = None  # ISO timestamp of the file at load time
    loaded_at: Optional[str] = None   # ISO timestamp of the read

    def held_options(self, symbol: Optional[str] = None) -> List[Position]:
        return [p for p in self.positions if p.is_option
                and (symbol is None or p.symbol == symbol)]


@dataclass
class Notification:
    """One outbound message. The only thing that ever leaves the machine."""
    channel: str
    title: str
    body: str
    severity: str = "info"            # 'info' | 'warn' | 'critical'
    ts: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
