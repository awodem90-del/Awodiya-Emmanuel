"""Flask app for Nuelz Binary AI: serves the live IQ Option HIGHER/LOWER
signals dashboard and runs the background scanner + Telegram command
listener + greeting/celebration scheduler in daemon threads."""
import logging
import os
import threading

from flask import Flask, jsonify, redirect, render_template, request, session, url_for

import config
import greetings
import scanner
import storage
import telegram_bot

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("nuelz.app")

app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "")
MASTER_PASSWORD = os.environ.get("MASTER_PASSWORD", "")

_stop_event = threading.Event()
_started = False


@app.before_request
def _require_login():
    if request.endpoint in ("login", "static"):
        return None
    if not MASTER_PASSWORD:
        # No password configured yet — fail closed with a clear message rather
        # than silently exposing the dashboard.
        return "Master password is not configured yet. Set the MASTER_PASSWORD secret to enable access.", 503
    if not session.get("authenticated"):
        return redirect(url_for("login"))
    return None


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        if MASTER_PASSWORD and request.form.get("password") == MASTER_PASSWORD:
            session["authenticated"] = True
            return redirect(url_for("dashboard"))
        error = "Incorrect password."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


def _bootstrap_background_jobs():
    global _started
    if _started:
        return
    _started = True

    # Continuous market-hours-aware scan loop (replaces a fixed-interval job so
    # scanning can pause on weekends and auto-recover from API/network errors).
    threading.Thread(target=scanner.continuous_scan_loop, args=(_stop_event,), daemon=True).start()

    # Telegram command listener (/start, /status, /signal + inline keyboard).
    threading.Thread(target=telegram_bot.poll_updates_forever, args=(_stop_event,), daemon=True).start()

    # Daily greetings + monthly/birthday celebration messages.
    threading.Thread(target=greetings.scheduler_loop, args=(_stop_event,), daemon=True).start()

    log.info("Background scanner, Telegram listener and greeting scheduler started.")


@app.route("/")
def dashboard():
    return render_template(
        "index.html",
        pairs=config.PAIRS,
        interval=config.INTERVAL,
        very_high_confidence=config.VERY_HIGH_CONFIDENCE,
        high_confidence=config.HIGH_CONFIDENCE,
        medium_confidence=config.MEDIUM_CONFIDENCE,
        low_confidence=config.LOW_CONFIDENCE,
        auto_alerts=config.AUTO_ALERTS,
    )


@app.route("/api/state")
def api_state():
    return jsonify({
        "last_scan_at": scanner.state["last_scan_at"],
        "last_error": scanner.state["last_error"],
        "evaluations": scanner.state["evaluations"],
        "best": scanner.state["best"],
        "market_open": scanner.state["market_open"],
        "market_session": scanner.state["market_session"],
        "stale": scanner.state["stale"],
        "very_high_confidence": config.VERY_HIGH_CONFIDENCE,
        "high_confidence": config.HIGH_CONFIDENCE,
        "medium_confidence": config.MEDIUM_CONFIDENCE,
        "low_confidence": config.LOW_CONFIDENCE,
        "auto_alerts": config.AUTO_ALERTS,
        "scan_interval_seconds": config.SCAN_INTERVAL_SECONDS,
        "telegram_configured": bool(config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID),
        "data_configured": bool(config.TWELVE_DATA_API_KEY),
    })


@app.route("/api/history")
def api_history():
    return jsonify(storage.load_history())


_bootstrap_background_jobs()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
