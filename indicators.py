"""Technical indicator calculations used by the signal engine."""
import pandas as pd
from ta.momentum import RSIIndicator, ROCIndicator
from ta.trend import EMAIndicator, MACD, ADXIndicator
from ta.volatility import AverageTrueRange, BollingerBands

import config

SR_LOOKBACK = 40   # candles used to derive recent support/resistance
ROC_WINDOW = 10
ADX_WINDOW = 14
BB_WINDOW = 20
STRUCTURE_LOOKBACK = 20  # candles used to read market structure (trend slope)


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Attach every indicator column the AI needs to an OHLC dataframe:
    RSI, EMA20/50/200, MACD, ADX, ROC, ATR, Bollinger Bands and rolling
    support/resistance."""
    out = df.copy()

    out["rsi"] = RSIIndicator(close=out["close"], window=config.RSI_WINDOW).rsi()
    out["ema20"] = EMAIndicator(close=out["close"], window=20).ema_indicator()
    out["ema50"] = EMAIndicator(close=out["close"], window=50).ema_indicator()
    out["ema200"] = EMAIndicator(close=out["close"], window=200).ema_indicator()

    macd = MACD(close=out["close"], window_slow=26, window_fast=12, window_sign=9)
    out["macd"] = macd.macd()
    out["macd_signal"] = macd.macd_signal()
    out["macd_hist"] = macd.macd_diff()

    atr = AverageTrueRange(high=out["high"], low=out["low"], close=out["close"], window=14)
    out["atr"] = atr.average_true_range()
    out["atr_pct"] = (out["atr"] / out["close"]) * 100

    # Trend strength (ADX): <20 ranging, 20-40 developing trend, >40 strong trend.
    out["adx"] = ADXIndicator(high=out["high"], low=out["low"], close=out["close"], window=ADX_WINDOW).adx()

    # Price momentum: rate of change over the last N candles.
    out["roc"] = ROCIndicator(close=out["close"], window=ROC_WINDOW).roc()

    # Bollinger Bands: mean-reversion / squeeze read.
    bb = BollingerBands(close=out["close"], window=BB_WINDOW, window_dev=2)
    out["bb_high"] = bb.bollinger_hband()
    out["bb_low"] = bb.bollinger_lband()
    out["bb_mid"] = bb.bollinger_mavg()
    out["bb_width_pct"] = (out["bb_high"] - out["bb_low"]) / out["bb_mid"] * 100
    # Position of price within the band, 0 = lower band, 1 = upper band.
    out["bb_percent"] = (out["close"] - out["bb_low"]) / (out["bb_high"] - out["bb_low"])

    # Simple support/resistance: trailing rolling extremes.
    out["support"] = out["low"].rolling(SR_LOOKBACK).min()
    out["resistance"] = out["high"].rolling(SR_LOOKBACK).max()
    # Prior-bar S/R (excludes the forming candle) used for breakout detection.
    out["prev_support"] = out["support"].shift(1)
    out["prev_resistance"] = out["resistance"].shift(1)

    return out


def _candle_pattern(df: pd.DataFrame) -> str:
    """Detect a simple, well-known candlestick pattern on the last 1-2 candles."""
    if len(df) < 2:
        return "None"
    prev, curr = df.iloc[-2], df.iloc[-1]
    body = abs(curr["close"] - curr["open"])
    full_range = curr["high"] - curr["low"]
    upper_wick = curr["high"] - max(curr["close"], curr["open"])
    lower_wick = min(curr["close"], curr["open"]) - curr["low"]

    prev_bear = prev["close"] < prev["open"]
    prev_bull = prev["close"] > prev["open"]
    curr_bull = curr["close"] > curr["open"]
    curr_bear = curr["close"] < curr["open"]

    if prev_bear and curr_bull and curr["close"] >= prev["open"] and curr["open"] <= prev["close"]:
        return "Bullish Engulfing"
    if prev_bull and curr_bear and curr["open"] >= prev["close"] and curr["close"] <= prev["open"]:
        return "Bearish Engulfing"

    if full_range > 0 and body / full_range < 0.12:
        return "Doji (Indecision)"

    if full_range > 0 and lower_wick > body * 2 and upper_wick < body:
        return "Hammer / Bullish Pin Bar"
    if full_range > 0 and upper_wick > body * 2 and lower_wick < body:
        return "Shooting Star / Bearish Pin Bar"

    return "None"


def _market_structure(df: pd.DataFrame) -> str:
    """Reads recent swing structure via a simple linear trend of closes."""
    window = df["close"].tail(STRUCTURE_LOOKBACK)
    if len(window) < STRUCTURE_LOOKBACK:
        return "Insufficient Data"
    x = range(len(window))
    mean_x = sum(x) / len(x)
    mean_y = window.mean()
    cov = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, window))
    var_x = sum((xi - mean_x) ** 2 for xi in x)
    slope = cov / var_x if var_x else 0
    slope_pct = (slope / mean_y) * 100 if mean_y else 0

    if slope_pct > 0.03:
        return "Bullish Structure (Higher Highs)"
    if slope_pct < -0.03:
        return "Bearish Structure (Lower Lows)"
    return "Ranging / Choppy"


def _breakout_flags(df: pd.DataFrame) -> dict:
    """Real vs. fake breakout detection using the prior bar's support/resistance."""
    curr = df.iloc[-1]
    resistance = curr.get("prev_resistance")
    support = curr.get("prev_support")

    breakout_up = bool(pd.notna(resistance) and curr["close"] > resistance)
    breakout_down = bool(pd.notna(support) and curr["close"] < support)
    fake_breakout_up = bool(
        pd.notna(resistance) and curr["high"] > resistance and curr["close"] <= resistance
    )
    fake_breakout_down = bool(
        pd.notna(support) and curr["low"] < support and curr["close"] >= support
    )
    return {
        "breakout_up": breakout_up,
        "breakout_down": breakout_down,
        "fake_breakout_up": fake_breakout_up,
        "fake_breakout_down": fake_breakout_down,
    }


def latest_snapshot(df: pd.DataFrame) -> dict:
    """Return the most recent row of indicators (plus derived price-action
    fields) as a plain dict, dropping NaNs."""
    row = df.iloc[-1]
    close = float(row["close"])
    support = float(row["support"]) if pd.notna(row["support"]) else None
    resistance = float(row["resistance"]) if pd.notna(row["resistance"]) else None

    snap = {
        "close": close,
        "rsi": float(row["rsi"]) if pd.notna(row["rsi"]) else None,
        "ema20": float(row["ema20"]) if pd.notna(row["ema20"]) else None,
        "ema50": float(row["ema50"]) if pd.notna(row["ema50"]) else None,
        "ema200": float(row["ema200"]) if pd.notna(row["ema200"]) else None,
        "macd": float(row["macd"]) if pd.notna(row["macd"]) else None,
        "macd_signal": float(row["macd_signal"]) if pd.notna(row["macd_signal"]) else None,
        "macd_hist": float(row["macd_hist"]) if pd.notna(row["macd_hist"]) else None,
        "atr_pct": float(row["atr_pct"]) if pd.notna(row["atr_pct"]) else None,
        "adx": float(row["adx"]) if pd.notna(row["adx"]) else None,
        "roc": float(row["roc"]) if pd.notna(row["roc"]) else None,
        "bb_high": float(row["bb_high"]) if pd.notna(row["bb_high"]) else None,
        "bb_low": float(row["bb_low"]) if pd.notna(row["bb_low"]) else None,
        "bb_percent": float(row["bb_percent"]) if pd.notna(row["bb_percent"]) else None,
        "bb_width_pct": float(row["bb_width_pct"]) if pd.notna(row["bb_width_pct"]) else None,
        "support": support,
        "resistance": resistance,
        "distance_to_support_pct": abs(close - support) / close * 100 if support else None,
        "distance_to_resistance_pct": abs(resistance - close) / close * 100 if resistance else None,
        "candle_pattern": _candle_pattern(df),
        "market_structure": _market_structure(df),
        "datetime": str(row["datetime"]),
    }
    snap.update(_breakout_flags(df))
    return snap
