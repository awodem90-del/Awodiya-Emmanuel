"""Fetches live/historical Forex OHLC data from the Twelve Data API."""
import logging
import pandas as pd
import requests

import config

log = logging.getLogger("nuelz.market_data")

TWELVE_DATA_URL = "https://api.twelvedata.com/time_series"


class MarketDataError(Exception):
    pass


def fetch_candles(pair: str, interval: str | None = None, outputsize: int | None = None) -> pd.DataFrame:
    """Fetch recent OHLC candles for a currency pair, oldest -> newest.

    Defaults to the primary analysis timeframe; pass `interval` to pull a
    different timeframe (e.g. the higher timeframe used for multi-timeframe
    confirmation).
    """
    if not config.TWELVE_DATA_API_KEY:
        raise MarketDataError("TWELVE_DATA_API_KEY is not configured")

    params = {
        "symbol": pair,
        "interval": interval or config.INTERVAL,
        "outputsize": outputsize or config.OUTPUT_SIZE,
        "apikey": config.TWELVE_DATA_API_KEY,
    }
    resp = requests.get(TWELVE_DATA_URL, params=params, timeout=15)
    resp.raise_for_status()
    payload = resp.json()

    if payload.get("status") == "error":
        raise MarketDataError(f"{pair}: {payload.get('message', 'unknown error')}")

    values = payload.get("values")
    if not values:
        raise MarketDataError(f"{pair}: no candle data returned")

    df = pd.DataFrame(values)
    for col in ("open", "high", "low", "close"):
        df[col] = df[col].astype(float)
    df["datetime"] = pd.to_datetime(df["datetime"])
    # Twelve Data returns newest-first; analysis needs oldest-first
    df = df.sort_values("datetime").reset_index(drop=True)
    return df
