"""Orchestrates market analysis across all monitored pairs, runs the
continuous background scan loop, and handles auto-alert delivery.

Binary options never go silent: every cycle produces a best-available
HIGHER/LOWER setup, however low the confidence, and (when AUTO_ALERTS is on)
pushes it to Telegram."""
import logging
import time
from datetime import datetime, timezone

import config
import indicators
import market_data
import market_hours
import signal_engine
import storage
import telegram_bot

log = logging.getLogger("nuelz.scanner")

# In-memory state read by the dashboard. Written only from analyze_all()/run_scan()/the scan loop.
state = {
    "last_scan_at": None,
    "last_error": None,
    "evaluations": [],   # latest per-pair evaluation, best-confidence first
    "best": None,        # the strongest opportunity from the last scan
    "market_open": True,     # live interbank Forex feed available right now
    "market_session": "—",
    "stale": False,       # True when serving last-known data (weekend/API gap)
}

_htf_cache: dict[str, dict] = {}  # pair -> {"trend": "Bullish"/"Bearish"/"Neutral", "fetched_at": datetime}


def _get_htf_trend(pair: str) -> str:
    """Higher-timeframe EMA50/EMA200 trend, refreshed on its own slow cadence
    to keep API usage low (multi-timeframe confirmation shouldn't multiply
    request volume)."""
    now = datetime.now(timezone.utc)
    cached = _htf_cache.get(pair)
    if cached and (now - cached["fetched_at"]).total_seconds() < config.HIGHER_TIMEFRAME_REFRESH_SECONDS:
        return cached["trend"]

    trend = cached["trend"] if cached else "Neutral"
    try:
        df = market_data.fetch_candles(pair, interval=config.HIGHER_TIMEFRAME_INTERVAL, outputsize=210)
        df = indicators.compute_indicators(df)
        snap = indicators.latest_snapshot(df)
        if snap["ema50"] is not None and snap["ema200"] is not None:
            trend = "Bullish" if snap["ema50"] > snap["ema200"] else "Bearish"
    except Exception:
        log.warning("Higher-timeframe fetch failed for %s — reusing last known trend", pair)

    _htf_cache[pair] = {"trend": trend, "fetched_at": now}
    return trend


def analyze_all() -> tuple[list[dict], list[str]]:
    """Fetch + score every monitored pair. Pure computation — no messaging."""
    evaluations = []
    errors = []

    for i, pair in enumerate(config.PAIRS):
        try:
            if i > 0:
                time.sleep(2)  # stay comfortably under the free-tier per-minute rate limit
            df = market_data.fetch_candles(pair)
            df = indicators.compute_indicators(df)
            snap = indicators.latest_snapshot(df)
            snap["htf_trend"] = _get_htf_trend(pair)
            evaluations.append(signal_engine.evaluate_pair(pair, snap))
        except Exception as e:
            log.exception("Failed to analyze %s", pair)
            errors.append(f"{pair}: {e}")

    evaluations.sort(key=lambda e: e["confidence"], reverse=True)
    return evaluations, errors


def get_evaluations(max_age_seconds: int | None = None) -> tuple[list[dict], list[str]]:
    """Return a recent scan, reusing the cached one if it's fresh enough."""
    if max_age_seconds is not None and state["last_scan_at"]:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(state["last_scan_at"])).total_seconds()
        if age <= max_age_seconds and state["evaluations"]:
            return state["evaluations"], []
    return analyze_all()


def _should_send_auto_alert(scheduler_state: dict, pair: str, direction: str, confidence: int, now: datetime) -> bool:
    """De-dup rule: only suppress a literal repeat (same pair+direction with a
    near-identical confidence) within a short cooldown, so restarts/cycles
    don't spam identical messages. Never suppress based on confidence being
    "too low" — the AI must never go silent."""
    last_alerts = scheduler_state.setdefault("last_alerts", {})
    key = f"{pair}:{direction}"
    last = last_alerts.get(key)
    if not last:
        return True
    age_minutes = (now - datetime.fromisoformat(last["at"])).total_seconds() / 60
    if age_minutes >= config.ALERT_DEDUP_COOLDOWN_MINUTES:
        return True
    if abs(confidence - last["confidence"]) >= config.ALERT_DEDUP_CONFIDENCE_DELTA:
        return True
    return False


def _record_auto_alert(scheduler_state: dict, pair: str, direction: str, confidence: int, now: datetime) -> None:
    scheduler_state.setdefault("last_alerts", {})[f"{pair}:{direction}"] = {
        "confidence": confidence,
        "at": now.isoformat(),
    }


def run_scan() -> dict | None:
    """One analysis cycle. Always produces a best-available setup (binary
    options never go silent) and, when AUTO_ALERTS is on, pushes it to
    Telegram unless it's a literal repeat of the last push."""
    now = datetime.now(timezone.utc).astimezone()
    now_utc = datetime.now(timezone.utc)
    session = market_hours.get_market_session(now_utc)
    market_open = market_hours.is_forex_open(now_utc)

    evaluations, errors = analyze_all()
    stale = False
    if not evaluations and state["evaluations"]:
        # Live feed unavailable (typically the weekend gap) — keep serving the
        # last known analysis rather than going silent.
        evaluations = state["evaluations"]
        stale = True

    best = signal_engine.pick_best_opportunity(evaluations)
    alert = None
    if best is not None:
        display_name = market_hours.display_pair(best["pair"], now_utc)
        alert = signal_engine.build_alert(best, now, session, display_name)
        alert["stale"] = stale

    if config.AUTO_ALERTS and best is not None:
        scheduler_state = storage.load_scheduler_state()
        if _should_send_auto_alert(scheduler_state, best["pair"], best["direction"], best["confidence"], now):
            sent = telegram_bot.send_message(telegram_bot.format_signal_message(alert))
            alert["sent"] = sent
            alert["source"] = "auto"
            storage.append_history(alert)
            _record_auto_alert(scheduler_state, best["pair"], best["direction"], best["confidence"], now)
            storage.save_scheduler_state(scheduler_state)

    state["last_scan_at"] = now.isoformat()
    state["last_error"] = "; ".join(errors) if errors else None
    state["evaluations"] = evaluations
    state["best"] = alert
    state["market_open"] = market_open
    state["market_session"] = session
    state["stale"] = stale
    return alert


def continuous_scan_loop(stop_event) -> None:
    """Background loop: scans continuously, 24/7 — binary options (via IQ
    Option's OTC instruments) trade even when the live interbank Forex feed
    is closed on weekends. When the live feed is unavailable, cycles run less
    frequently (fetches would fail anyway) but still broadcast the last-known
    analysis, clearly marked, so the AI never goes silent. Auto-recovers from
    transient API/network errors by simply retrying next cycle."""
    log.info("Continuous market scan loop starting.")
    while not stop_event.is_set():
        try:
            open_now = market_hours.is_forex_open()
            if open_now != state.get("market_open"):
                log.info("Live Forex feed is now %s.", "AVAILABLE" if open_now else "UNAVAILABLE (weekend/OTC)")

            run_scan()
            sleep_for = config.SCAN_INTERVAL_SECONDS if open_now else config.OFFLINE_FEED_POLL_SECONDS
        except Exception:
            log.exception("Scan loop error — will retry automatically after backoff")
            sleep_for = config.SCAN_INTERVAL_SECONDS

        stop_event.wait(sleep_for)
