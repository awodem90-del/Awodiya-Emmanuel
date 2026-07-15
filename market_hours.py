"""Forex feed availability + IQ Option-style session labeling.

IQ Option trades these pairs as live instruments during the interbank Forex
week and as broker-generated OTC instruments on weekends. Twelve Data (our
live data source) only publishes real interbank ticks, so `is_forex_open()`
tells the scanner when fresh data can actually be fetched; `get_market_session()`
gives the human-facing session label shown on every signal, including the
weekend "OTC" label.
"""
from datetime import datetime, timezone


def is_forex_open(now_utc: datetime | None = None) -> bool:
    """True while the interbank Forex market (and therefore live Twelve Data
    quotes) is open: Sunday 22:00 UTC through Friday 22:00 UTC."""
    now_utc = now_utc or datetime.now(timezone.utc)
    weekday = now_utc.weekday()  # Monday=0 ... Sunday=6
    hour = now_utc.hour

    if weekday == 5:  # Saturday: always closed
        return False
    if weekday == 6:  # Sunday: closed until the Sydney open at 22:00 UTC
        return hour >= 22
    if weekday == 4:  # Friday: closes at the New York close, 22:00 UTC
        return hour < 22
    return True  # Monday - Thursday: open all day


def get_market_session(now_utc: datetime | None = None) -> str:
    """Human-facing session label used on every signal."""
    now_utc = now_utc or datetime.now(timezone.utc)
    if not is_forex_open(now_utc):
        return "Weekend (OTC)"

    hour = now_utc.hour
    if 0 <= hour < 8:
        return "Asian (Tokyo/Sydney)"
    if 8 <= hour < 13:
        return "London"
    if 13 <= hour < 16:
        return "London/New York Overlap"
    if 16 <= hour < 21:
        return "New York"
    return "Late New York/Sydney"


def display_pair(pair: str, now_utc: datetime | None = None) -> str:
    """Pair name as IQ Option would label it: plain during the week, "(OTC)"
    over the weekend when the live feed is unavailable and last-known data is
    being carried forward."""
    if is_forex_open(now_utc):
        return pair
    return f"{pair} (OTC)"
