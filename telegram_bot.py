"""Telegram Bot API client — sends binary options signals and answers
/start, /status, /signal for Nuelz Binary AI (IQ Option HIGHER/LOWER only).

Message formatting follows a consistent "premium AI trading assistant" style:
clean section dividers, emoji-led labels, and no plain unstructured text.
There is never a Stop Loss, Take Profit, Trailing Stop or Risk/Reward Ratio —
those don't exist in IQ Option binary options.
"""
import logging
import threading
import time
from datetime import datetime, timezone

import requests

import config

log = logging.getLogger("nuelz.telegram")

API_BASE = "https://api.telegram.org/bot{token}"
DIVIDER = "━━━━━━━━━━━━━━━━━━"

DIRECTION_DISPLAY = {
    "HIGHER": "🟢 HIGHER ⬆️",
    "LOWER": "🔴 LOWER ⬇️",
}


def _api_url(method: str) -> str:
    return f"{API_BASE.format(token=config.TELEGRAM_BOT_TOKEN)}/{method}"


def send_message(text: str, chat_id: str | None = None, reply_markup: dict | None = None) -> bool:
    """Send a message to the configured (or given) chat, optionally with an
    inline keyboard."""
    target = chat_id or config.TELEGRAM_CHAT_ID
    if not config.TELEGRAM_BOT_TOKEN or not target:
        log.warning("Telegram not configured — skipping send")
        return False
    payload = {"chat_id": target, "text": text, "parse_mode": "HTML"}
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    try:
        resp = requests.post(_api_url("sendMessage"), json=payload, timeout=10)
        if not resp.ok:
            log.error("Telegram send failed: %s", resp.text)
            return False
        return True
    except requests.RequestException as e:
        log.error("Telegram send error: %s", e)
        return False


def _answer_callback_query(callback_query_id: str, text: str = "") -> None:
    try:
        requests.post(
            _api_url("answerCallbackQuery"),
            json={"callback_query_id": callback_query_id, "text": text},
            timeout=10,
        )
    except requests.RequestException as e:
        log.error("Telegram answerCallbackQuery error: %s", e)


def _signal_menu_keyboard() -> dict:
    return {
        "inline_keyboard": [[
            {"text": "1 Signal", "callback_data": "signal_1"},
            {"text": "2 Signals", "callback_data": "signal_2"},
            {"text": "3 Signals", "callback_data": "signal_3"},
        ]]
    }


def _confirmation_lines(alert: dict) -> list[str]:
    lines = [f"✅ {name}" for name in alert.get("agreeing_indicators", [])]
    return lines or ["✅ Composite technical read"]


def format_signal_message(alert: dict) -> str:
    """The single canonical signal format — used for every tier. Confidence
    tiers change color/emoji and the closing recommendation, never whether
    the signal is shown."""
    pair = alert.get("display_pair") or alert["pair"]
    direction_line = DIRECTION_DISPLAY[alert["direction"]]
    lines = [
        "🤖 <b>Nuelz Binary AI</b>",
        DIVIDER,
        "",
        f"Pair:\n<b>{pair}</b>",
        "",
        f"Signal:\n{direction_line}",
        "",
        f"Confidence:\n<b>{alert['confidence']}%</b>",
        "",
        f"Level:\n{alert['tier_emoji']} {alert['tier_label']}",
        "",
        f"Expiry:\n⏱ {alert['expiry']}",
        "",
        f"Trend:\n{alert['trend']}",
        "",
        f"Market Structure:\n{alert.get('market_structure') or '—'}",
        "",
        f"Session:\n{alert.get('session', '—')}",
        "",
        DIVIDER,
        "Reason:",
        "",
        *_confirmation_lines(alert),
        "",
        DIVIDER,
        f"Recommendation:\n<b>{alert['recommendation']}</b>",
        "",
        f"Final Decision:\n<b>{alert['final_decision_display']}</b>",
    ]

    if alert.get("stale"):
        lines += [
            "",
            DIVIDER,
            "⚠️ Live feed is currently unavailable (weekend/OTC gap) — this is the last known "
            "market read, not a live tick.",
        ]

    lines += [
        "",
        DIVIDER,
        "<i>This is an AI market analysis, not a guaranteed outcome. Trade only what you can "
        "afford to lose — this assistant never places trades for you.</i>",
    ]
    return "\n".join(lines)


def format_market_overview(evaluations: list[dict], session: str) -> str:
    """Shown alongside a scan when the caller wants a quick read across every
    monitored pair, not just the best one."""
    rows = []
    for e in sorted(evaluations, key=lambda x: x["confidence"], reverse=True):
        rows.append(
            f"• {e['pair']} — {DIRECTION_DISPLAY[e['direction']]} · {e['confidence']}% "
            f"({e['tier_emoji']} {e['tier_label']})"
        )

    return "\n".join([
        "🤖 <b>Nuelz Binary AI — Market Overview</b>",
        DIVIDER,
        "",
        f"Session: {session}",
        "",
        "📊 <b>Every pair right now:</b>",
        "",
        *rows,
        "",
        DIVIDER,
        "🕒 I'm continuously scanning and will never go silent — the best available setup is "
        "always shown, even at low confidence.",
    ])


def format_scanning_message() -> str:
    return "\n".join([
        "🔍 <b>Nuelz Binary AI</b>",
        DIVIDER,
        "",
        "🤖 Analyzing the market for your request...",
        "",
        "⏳ Please wait a few seconds.",
        DIVIDER,
    ])


def format_signal_prompt() -> str:
    return "\n".join([
        "📊 <b>Nuelz Binary AI — Signal Request</b>",
        DIVIDER,
        "",
        "How many signals would you like right now?",
        "",
        "I always show the best available setup for each pair — even low-confidence ones are "
        "labeled clearly as Watchlist, never hidden.",
    ])


def status_text() -> str:
    mode = "automatically pushing every scan cycle" if config.AUTO_ALERTS else "on-demand only (use /signal)"
    return "\n".join([
        "🤖 <b>Nuelz Binary AI</b> is online — scanning 24/7 for IQ Option HIGHER/LOWER signals.",
        "",
        "I continuously monitor EUR/USD, GBP/USD, AUD/USD and USD/CAD using EMA 20/50/200, RSI, "
        "MACD, Bollinger Bands, ADX, momentum, support/resistance, breakout/fake-breakout "
        "detection, candlestick patterns and multi-timeframe confirmation.",
        "",
        f"Delivery mode: <b>{mode}</b>.",
        "🔒 On weekends the live interbank feed pauses — I keep showing the last known read, "
        "labeled OTC, since IQ Option trades these pairs as OTC instruments then.",
        "",
        "Every signal is HIGHER or LOWER with a confidence level — there's no Stop Loss, Take "
        "Profit or Risk/Reward here, since those don't exist in binary options.",
        "",
        "Commands:",
        "• /signal — choose how many signals to receive right now",
        "• /status — show this message",
        "",
        "This assistant only analyzes the market — it never places trades for you, and never "
        "guarantees a win.",
    ])


def _run_signal_selection(chat_id, count: int) -> None:
    import scanner
    import signal_engine
    import storage
    import market_hours

    send_message(format_scanning_message(), chat_id=chat_id)
    try:
        evaluations, _errors = scanner.get_evaluations(max_age_seconds=config.SIGNAL_CACHE_MAX_AGE_SECONDS)
    except Exception:
        log.exception("On-demand /signal scan failed")
        send_message(
            "⚠️ The market scan hit an unexpected error. Please try /signal again shortly.",
            chat_id=chat_id,
        )
        return

    if not evaluations:
        send_message(
            "⚠️ No market data is available right now. I'll keep retrying in the background.",
            chat_id=chat_id,
        )
        return

    now = datetime.now(timezone.utc).astimezone()
    now_utc = datetime.now(timezone.utc)
    session = market_hours.get_market_session(now_utc)
    chosen = signal_engine.pick_top_opportunities(evaluations, count)

    for opp in chosen:
        display_name = market_hours.display_pair(opp["pair"], now_utc)
        alert = signal_engine.build_alert(opp, now, session, display_name)
        send_message(format_signal_message(alert), chat_id=chat_id)
        alert["sent"] = True
        alert["source"] = "manual"
        storage.append_history(alert)

    if len(chosen) > 1:
        send_message(format_market_overview(evaluations, session), chat_id=chat_id)


def _handle_signal_command(chat_id) -> None:
    send_message(format_signal_prompt(), chat_id=chat_id, reply_markup=_signal_menu_keyboard())


def poll_updates_forever(stop_event) -> None:
    """Long-poll getUpdates and answer /start, /status, /signal and its
    inline-keyboard callback presses.

    Runs in a background thread. Auto-pushed alerts always go to the fixed
    TELEGRAM_CHAT_ID; command replies go back to whoever asked.
    """
    if not config.TELEGRAM_BOT_TOKEN:
        log.warning("TELEGRAM_BOT_TOKEN not set — command polling disabled")
        return

    offset = None
    log.info("Telegram command polling loop starting.")
    while not stop_event.is_set():
        try:
            params = {"timeout": 20}
            if offset is not None:
                params["offset"] = offset
            resp = requests.get(_api_url("getUpdates"), params=params, timeout=25)
            resp.raise_for_status()
            data = resp.json()
            updates = data.get("result", [])
            if updates:
                log.info("Received %d Telegram update(s)", len(updates))
            for update in updates:
                offset = update["update_id"] + 1

                callback_query = update.get("callback_query")
                if callback_query:
                    data_str = callback_query.get("data", "")
                    chat_id = callback_query.get("message", {}).get("chat", {}).get("id")
                    log.info("Incoming callback_query %r from chat_id=%s", data_str, chat_id)
                    _answer_callback_query(callback_query.get("id", ""))
                    if data_str.startswith("signal_") and chat_id:
                        try:
                            count = int(data_str.split("_", 1)[1])
                        except ValueError:
                            count = 1
                        threading.Thread(
                            target=_run_signal_selection, args=(chat_id, count), daemon=True
                        ).start()
                    continue

                message = update.get("message") or {}
                text = (message.get("text") or "").strip().lower()
                chat_id = message.get("chat", {}).get("id")
                if not chat_id:
                    log.info(
                        "Update %s had no chat/message/callback — skipping (keys: %s)",
                        update.get("update_id"), list(update.keys()),
                    )
                    continue

                chat = message.get("chat", {})
                log.info(
                    "Incoming message %r from chat_id=%s (type=%s, name=%s)",
                    text, chat_id, chat.get("type"),
                    chat.get("username") or chat.get("first_name") or chat.get("title"),
                )
                if text.startswith("/start") or text.startswith("/status"):
                    send_message(status_text(), chat_id=chat_id)
                elif text.startswith("/signal"):
                    _handle_signal_command(chat_id)
        except requests.RequestException as e:
            log.error("Telegram polling error (network): %s", e)
            time.sleep(5)
        except Exception:
            log.exception("Telegram polling loop hit an unexpected error — retrying")
            time.sleep(5)
