"""Rule-based AI confidence engine for Nuelz Binary AI (IQ Option binary
options — HIGHER/LOWER only).

Turns a pair's latest technical snapshot into a binary signal: a direction
(HIGHER or LOWER — binary options have no "no trade" state, so one side is
always favored), a 0-100 confidence score, a confidence tier, a recommended
expiry, and a plain-English explanation of what drove the score. This is a
transparent, deterministic scoring model (not a trained ML model, and not a
guarantee of outcome) — every point awarded is traceable to a specific
indicator reading.

There is no Stop Loss, Take Profit, Trailing Stop or Risk/Reward Ratio —
those concepts do not exist in IQ Option binary options.

Score budget (points sum to ~124, then clipped to 100):
  EMA Trend (20/50/200)            up to 20
  RSI                               up to 18
  MACD                              up to 16
  Bollinger Bands                   up to 12
  Price action (candle pattern)     up to 12
  Support/Resistance + breakouts    up to 14
  Trend strength (ADX)              up to 10
  Momentum (ROC)                    up to 10
  Multi-timeframe agreement         up to 12
"""
import config
from datetime import datetime, timedelta

HIGHER = "HIGHER"
LOWER = "LOWER"

# Max points available per scoring component — used both for the raw score
# and for the human-facing "AI Score" breakdown (earned/max per component).
_COMPONENT_MAX = {
    "EMA Trend": 20,
    "RSI": 18,
    "MACD": 16,
    "Bollinger Bands": 12,
    "Candlestick Pattern": 12,
    "Support/Resistance & Breakout": 14,
    "Trend Strength (ADX)": 10,
    "Momentum (ROC)": 10,
    "Multi-Timeframe Trend": 12,
}

# Trade duration (expiry label) -> seconds, used to calculate the Expiry Time
# from the Entry Time.
_DURATION_SECONDS = {
    "30 Seconds": 30,
    "1 Minute": 60,
    "2 Minutes": 120,
    "3 Minutes": 180,
    "5 Minutes": 300,
}


def _duration_seconds(label: str) -> int:
    return _DURATION_SECONDS.get(label, 120)


def _fmt_clock(dt: datetime) -> str:
    """12-hour clock without a leading zero, e.g. '4:56 PM'."""
    s = dt.strftime("%I:%M %p")
    return s.lstrip("0") or s


def _reliability(confidence: float) -> tuple[str, float]:
    """Returns (star_string, score_out_of_10)."""
    filled = max(0, min(5, round(confidence / 20)))
    stars = "★" * filled + "☆" * (5 - filled)
    return stars, round(confidence / 10, 1)


def _trend_component(snap: dict) -> tuple[str, float, list[str]]:
    """EMA20/EMA50/EMA200 stack — short and long-term trend alignment."""
    ema20, ema50, ema200, close = snap["ema20"], snap["ema50"], snap["ema200"], snap["close"]
    if ema20 is None or ema50 is None or ema200 is None:
        return "NEUTRAL", 0.0, []

    spread_pct = abs(ema50 - ema200) / ema200 * 100
    strength = min(spread_pct / 0.5, 1.0)

    if close > ema20 > ema50 > ema200:
        return HIGHER, 20.0, ["EMA 20/50/200 are fully stacked bullish and price is above all three"]
    if close < ema20 < ema50 < ema200:
        return LOWER, 20.0, ["EMA 20/50/200 are fully stacked bearish and price is below all three"]
    if ema50 > ema200 and close > ema50:
        return HIGHER, 12 + 6 * strength, ["EMA 50 is above EMA 200 and price is above EMA 50 — bullish trend confirmed"]
    if ema50 < ema200 and close < ema50:
        return LOWER, 12 + 6 * strength, ["EMA 50 is below EMA 200 and price is below EMA 50 — bearish trend confirmed"]
    if ema50 > ema200:
        return HIGHER, 6 * strength, ["EMA 50 is above EMA 200 but price has pulled back below it — trend weakening"]
    return LOWER, 6 * strength, ["EMA 50 is below EMA 200 but price has pushed back above it — trend weakening"]


def _rsi_component(snap: dict) -> tuple[str, float, list[str]]:
    rsi = snap["rsi"]
    if rsi is None:
        return "NEUTRAL", 0.0, []

    if rsi <= 30:
        return HIGHER, 18.0, ["RSI is oversold — reversal to the upside favored"]
    if rsi < 45:
        pts = (45 - rsi) / 15 * 13
        return HIGHER, pts, ["RSI is below neutral, tilting oversold"]
    if rsi >= 70:
        return LOWER, 18.0, ["RSI is overbought — reversal to the downside favored"]
    if rsi > 60:
        return LOWER, 14.0, ["RSI is above 60, tilting overbought"]
    if rsi > 55:
        pts = (rsi - 55) / 15 * 13
        return LOWER, pts, ["RSI is above neutral, tilting overbought"]
    return "NEUTRAL", 0.0, []


def _macd_component(snap: dict) -> tuple[str, float, list[str]]:
    macd, sig, hist = snap["macd"], snap["macd_signal"], snap["macd_hist"]
    if macd is None or sig is None or hist is None:
        return "NEUTRAL", 0.0, []

    if macd > sig and hist > 0:
        return HIGHER, 16.0, ["MACD is bullish, tracking above the signal line"]
    if macd < sig and hist < 0:
        return LOWER, 16.0, ["MACD is bearish, tracking below the signal line"]
    if macd > sig:
        return HIGHER, 7.0, ["MACD has crossed above the signal line but momentum is still building"]
    if macd < sig:
        return LOWER, 7.0, ["MACD has crossed below the signal line but momentum is still building"]
    return "NEUTRAL", 0.0, []


def _bollinger_component(snap: dict) -> tuple[str, float, list[str]]:
    """Price position inside the Bollinger Bands — mean-reversion read."""
    pct = snap.get("bb_percent")
    if pct is None:
        return "NEUTRAL", 0.0, []

    if pct <= 0.02:
        return HIGHER, 12.0, ["Price has touched the lower Bollinger Band — stretched, favoring a bounce up"]
    if pct <= 0.15:
        return HIGHER, 6.0, ["Price is trading near the lower Bollinger Band"]
    if pct >= 0.98:
        return LOWER, 12.0, ["Price has touched the upper Bollinger Band — stretched, favoring a pullback down"]
    if pct >= 0.85:
        return LOWER, 6.0, ["Price is trading near the upper Bollinger Band"]
    return "NEUTRAL", 0.0, []


def _price_action_component(snap: dict) -> tuple[str, float, list[str]]:
    """Candlestick pattern recognition."""
    pattern = snap.get("candle_pattern")
    if pattern == "Bullish Engulfing":
        return HIGHER, 12.0, ["A strong bullish engulfing candle has formed"]
    if pattern == "Bearish Engulfing":
        return LOWER, 12.0, ["A strong bearish engulfing candle has formed"]
    if pattern == "Hammer / Bullish Pin Bar":
        return HIGHER, 9.0, ["A bullish pin bar / hammer has formed, rejecting lower prices"]
    if pattern == "Shooting Star / Bearish Pin Bar":
        return LOWER, 9.0, ["A bearish pin bar / shooting star has formed, rejecting higher prices"]
    return "NEUTRAL", 0.0, []


def _structure_and_breakout_component(snap: dict) -> tuple[str, float, list[str]]:
    """Support/Resistance proximity plus real vs. fake breakout detection."""
    buy_pts, sell_pts = 0.0, 0.0
    buy_reasons, sell_reasons = [], []

    if snap.get("breakout_up"):
        buy_pts += 14
        buy_reasons.append("Price has broken above resistance with a confirmed close — bullish breakout")
    elif snap.get("fake_breakout_down"):
        buy_pts += 10
        buy_reasons.append("Price wicked below support then closed back inside — fake breakdown, bullish rejection")
    elif snap.get("distance_to_support_pct") is not None and snap["distance_to_support_pct"] < 0.15:
        buy_pts += 8
        buy_reasons.append("Price is trading right at a recent support level")

    if snap.get("breakout_down"):
        sell_pts += 14
        sell_reasons.append("Price has broken below support with a confirmed close — bearish breakout")
    elif snap.get("fake_breakout_up"):
        sell_pts += 10
        sell_reasons.append("Price wicked above resistance then closed back inside — fake breakout, bearish rejection")
    elif snap.get("distance_to_resistance_pct") is not None and snap["distance_to_resistance_pct"] < 0.15:
        sell_pts += 8
        sell_reasons.append("Price is trading right at a recent resistance level")

    if buy_pts > sell_pts:
        return HIGHER, buy_pts, buy_reasons
    if sell_pts > buy_pts:
        return LOWER, sell_pts, sell_reasons
    return "NEUTRAL", 0.0, []


def _trend_strength_component(snap: dict) -> tuple[str, float, list[str]]:
    """ADX confirms whether a trend has real conviction behind it."""
    adx, ema20, close = snap.get("adx"), snap.get("ema20"), snap.get("close")
    if adx is None or ema20 is None or adx < 20:
        return "NEUTRAL", 0.0, []  # ranging / no meaningful trend to confirm

    pts = min(adx / 40, 1.0) * 10
    direction = HIGHER if close > ema20 else LOWER
    return direction, pts, [f"ADX ({adx:.0f}) confirms a trending market with real conviction"]


def _momentum_component(snap: dict) -> tuple[str, float, list[str]]:
    roc = snap.get("roc")
    if roc is None or abs(roc) < 0.02:
        return "NEUTRAL", 0.0, []

    pts = min(abs(roc) / 1.0, 1.0) * 10
    if roc > 0:
        return HIGHER, pts, ["Momentum (rate of change) is increasing to the upside"]
    return LOWER, pts, ["Momentum (rate of change) is increasing to the downside"]


def _mtf_component(snap: dict) -> tuple[str, float, list[str]]:
    """Higher-timeframe trend agreement — extra conviction when both
    timeframes point the same way."""
    htf_trend = snap.get("htf_trend")
    if htf_trend == "Bullish":
        return HIGHER, 12.0, ["Higher timeframe trend is bullish, aligning with this setup"]
    if htf_trend == "Bearish":
        return LOWER, 12.0, ["Higher timeframe trend is bearish, aligning with this setup"]
    return "NEUTRAL", 0.0, []


_COMPONENT_FUNCS = [
    ("EMA Trend", _trend_component),
    ("RSI", _rsi_component),
    ("MACD", _macd_component),
    ("Bollinger Bands", _bollinger_component),
    ("Candlestick Pattern", _price_action_component),
    ("Support/Resistance & Breakout", _structure_and_breakout_component),
    ("Trend Strength (ADX)", _trend_strength_component),
    ("Momentum (ROC)", _momentum_component),
    ("Multi-Timeframe Trend", _mtf_component),
]


def _expiry_for_volatility(atr_pct: float | None) -> tuple[str, str]:
    """Returns (expiry_label, risk_level). Faster expiries for choppier/faster
    markets so the trade resolves before a fast move reverses; longer
    expiries for calmer markets so the move has time to develop."""
    if atr_pct is None:
        return "2 Minutes", "Medium"
    if atr_pct >= 0.5:
        return "30 Seconds", "High"
    if atr_pct >= 0.3:
        return "1 Minute", "High"
    if atr_pct >= 0.15:
        return "2 Minutes", "Medium"
    if atr_pct >= 0.08:
        return "3 Minutes", "Low"
    return "5 Minutes", "Low"


def _rsi_label(rsi: float | None) -> str:
    if rsi is None:
        return "Unavailable"
    if rsi <= 30:
        return "Oversold"
    if rsi >= 70:
        return "Overbought"
    return "Neutral"


def _macd_label(macd, sig, hist) -> str:
    if macd is None or sig is None or hist is None:
        return "Unavailable"
    if macd > sig and hist > 0:
        return "Bullish Crossover"
    if macd < sig and hist < 0:
        return "Bearish Crossover"
    return "Neutral"


def _trend_label(direction: str) -> str:
    return "Bullish" if direction == HIGHER else "Bearish"


def classify_tier(confidence: float) -> str:
    """Five-level confidence classification. Signals are never hidden — every
    tier, including VERY_LOW, is always shown."""
    if confidence >= config.VERY_HIGH_CONFIDENCE:
        return "VERY_HIGH"
    if confidence >= config.HIGH_CONFIDENCE:
        return "HIGH"
    if confidence >= config.MEDIUM_CONFIDENCE:
        return "MEDIUM"
    if confidence >= config.LOW_CONFIDENCE:
        return "LOW"
    return "VERY_LOW"


TIER_LABEL = {
    "VERY_HIGH": "Very High Confidence",
    "HIGH": "High Confidence",
    "MEDIUM": "Medium Confidence",
    "LOW": "Low Confidence",
    "VERY_LOW": "Very Low Confidence",
}

TIER_EMOJI = {
    "VERY_HIGH": "🟢",
    "HIGH": "🟢",
    "MEDIUM": "🟡",
    "LOW": "🔵",
    "VERY_LOW": "🔴",
}


def final_decision(tier: str) -> tuple[str, str]:
    """Returns (decision_code, recommendation_text)."""
    if tier in ("VERY_HIGH", "HIGH"):
        return "ENTER_NOW", "ENTER NOW"
    if tier in ("MEDIUM", "LOW"):
        return "WAIT_FOR_CONFIRMATION", "WATCHLIST ONLY — wait for confirmation before entering"
    return "DO_NOT_ENTER", "DO NOT ENTER — signals are too weak or conflicting"


FINAL_DECISION_DISPLAY = {
    "ENTER_NOW": "🟢 ENTER NOW",
    "WAIT_FOR_CONFIRMATION": "🟡 WAIT FOR CONFIRMATION",
    "DO_NOT_ENTER": "🔴 DO NOT ENTER",
}


def _continuation_probability(snap: dict, direction: str) -> int:
    """Heuristic 0-100: how likely the current trend continues rather than reverses."""
    score = 30
    adx = snap.get("adx")
    if adx is not None:
        score += min(adx, 45)
    roc = snap.get("roc")
    if roc is not None and ((roc > 0) == (direction == HIGHER)):
        score += min(abs(roc) * 8, 15)
    if snap.get("htf_trend") == ("Bullish" if direction == HIGHER else "Bearish"):
        score += 10
    return max(0, min(100, round(score)))


def _reversal_probability(snap: dict, direction: str) -> int:
    """Heuristic 0-100: how likely price reverses against the current move."""
    score = 20
    rsi = snap.get("rsi")
    if rsi is not None and (rsi >= 70 or rsi <= 30):
        score += 25
    bb_pct = snap.get("bb_percent")
    if bb_pct is not None and (bb_pct >= 0.95 or bb_pct <= 0.05):
        score += 25
    if snap.get("fake_breakout_up") or snap.get("fake_breakout_down"):
        score += 20
    if snap.get("candle_pattern") in ("Hammer / Bullish Pin Bar", "Shooting Star / Bearish Pin Bar", "Doji (Indecision)"):
        score += 10
    return max(0, min(100, round(score)))


def _summary(pair: str, direction: str, confidence: float, tier: str, agreeing: list[str]) -> str:
    verb = "bullish (HIGHER)" if direction == HIGHER else "bearish (LOWER)"
    if tier in ("VERY_HIGH", "HIGH"):
        return (
            f"Multiple confirmations line up for {pair} ({', '.join(agreeing)}), making this a strong "
            f"{verb} setup. This is a market analysis, not a guaranteed outcome."
        )
    if tier == "MEDIUM":
        return (
            f"{pair} shows {verb} momentum backed by {', '.join(agreeing) if agreeing else 'a partial read'}, "
            "but not every indicator agrees yet — a reasonable but not maximum-confidence setup."
        )
    if tier == "LOW":
        return (
            f"Early {verb} signs on {pair} from {', '.join(agreeing) if agreeing else 'limited indicators'}, "
            "but confirmation is thin. Worth watching, not yet worth entering."
        )
    return (
        f"{pair}'s indicators are mixed or conflicting right now — no reliable {verb} edge. "
        "Best to sit this one out until the picture clears up."
    )


def evaluate_pair(pair: str, snap: dict) -> dict:
    """Score a single pair's latest indicator snapshot across every component.

    Binary options have no "no trade" state — one side (HIGHER or LOWER) is
    always favored, even if only marginally. Confidence (not direction) is
    what tells you whether it's worth acting on, and it is always shown.
    """
    scored = [(name, *fn(snap)) for name, fn in _COMPONENT_FUNCS]

    higher_score = sum(pts for _, d, pts, _ in scored if d == HIGHER)
    lower_score = sum(pts for _, d, pts, _ in scored if d == LOWER)

    if higher_score == lower_score:
        # Tie-break deterministically: short-term EMA position, then last candle color.
        ema20 = snap.get("ema20")
        if ema20 is not None and snap["close"] != ema20:
            direction = HIGHER if snap["close"] > ema20 else LOWER
        else:
            direction = HIGHER if snap.get("roc", 0) is not None and snap.get("roc", 0) >= 0 else LOWER
        raw_score = max(higher_score, lower_score)
    elif higher_score > lower_score:
        direction = HIGHER
        raw_score = higher_score
    else:
        direction = LOWER
        raw_score = lower_score

    agreeing = [name for name, d, _, _ in scored if d == direction]
    missing = [name for name, d, _, _ in scored if d not in (direction, "NEUTRAL")]
    reasons = [r for _, d, _, rs in scored if d == direction for r in rs]

    expiry, risk_level = _expiry_for_volatility(snap.get("atr_pct"))
    confidence = round(min(raw_score, 100))
    tier = classify_tier(confidence)
    decision_code, recommendation = final_decision(tier)

    if risk_level == "High":
        reasons.append(f"Volatility is elevated (ATR {snap.get('atr_pct', 0):.2f}% of price) — fast, short-expiry conditions")
    elif risk_level == "Low":
        reasons.append(f"Volatility is subdued (ATR {snap.get('atr_pct', 0):.2f}% of price) — slower, longer-expiry conditions")

    macd_label = _macd_label(snap["macd"], snap["macd_signal"], snap.get("macd_hist"))
    summary = _summary(pair, direction, confidence, tier, agreeing)

    return {
        "pair": pair,
        "direction": direction,
        "confidence": confidence,
        "tier": tier,
        "tier_label": TIER_LABEL[tier],
        "tier_emoji": TIER_EMOJI[tier],
        "final_decision": decision_code,
        "final_decision_display": FINAL_DECISION_DISPLAY[decision_code],
        "recommendation": recommendation,
        "expiry": expiry,
        "risk_level": risk_level,
        "reasons": reasons,
        "agreeing_indicators": agreeing,
        "missing_indicators": missing,
        "price": snap["close"],
        "rsi": snap["rsi"],
        "rsi_label": _rsi_label(snap["rsi"]),
        "ema20": snap["ema20"],
        "ema50": snap["ema50"],
        "ema200": snap["ema200"],
        "macd": snap["macd"],
        "macd_signal": snap["macd_signal"],
        "macd_label": macd_label,
        "trend": _trend_label(direction),
        "market_structure": snap.get("market_structure"),
        "candle_pattern": snap.get("candle_pattern"),
        "htf_trend": snap.get("htf_trend"),
        "breakout_up": snap.get("breakout_up"),
        "breakout_down": snap.get("breakout_down"),
        "fake_breakout_up": snap.get("fake_breakout_up"),
        "fake_breakout_down": snap.get("fake_breakout_down"),
        "continuation_probability": _continuation_probability(snap, direction),
        "reversal_probability": _reversal_probability(snap, direction),
        "bb_percent": snap.get("bb_percent"),
        "summary": summary,
        "atr_pct": snap["atr_pct"],
        "candle_time": snap["datetime"],
    }


def pick_top_opportunities(evaluations: list[dict], limit: int) -> list[dict]:
    """Rank every setup strongest-to-weakest and return up to `limit`. Never
    filters by a minimum confidence — signals are never hidden."""
    ranked = sorted(evaluations, key=lambda e: e["confidence"], reverse=True)
    return ranked[:limit]


def pick_best_opportunity(evaluations: list[dict]) -> dict | None:
    """Select the single strongest setup right now, whatever its confidence."""
    top = pick_top_opportunities(evaluations, 1)
    return top[0] if top else None


def build_alert(evaluation: dict, now: datetime, session: str, display_pair_name: str | None = None) -> dict:
    """Attach timing/session metadata to a chosen opportunity, ready for messaging."""
    alert = dict(evaluation)
    alert["entry_time"] = now.strftime("%H:%M")
    alert["generated_at"] = now.isoformat()
    alert["session"] = session
    alert["display_pair"] = display_pair_name or evaluation["pair"]
    return alert
