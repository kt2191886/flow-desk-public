"""flow_desk/ingest: one parser per input shape.

Each module does exactly this: read a file, normalize it to the shared
record model in contracts.py, return records. No scoring, no judgment.
"""
from ._csvio import FeedFormatError
from .flow_alerts import parse_flow_alerts
from .oi_change import parse_oi_change
from .open_close import parse_open_close_csv, parse_open_close_text
from .positions import load_position_book, parse_positions

__all__ = ["FeedFormatError", "parse_flow_alerts", "parse_oi_change",
           "parse_open_close_csv", "parse_open_close_text",
           "load_position_book", "parse_positions"]
