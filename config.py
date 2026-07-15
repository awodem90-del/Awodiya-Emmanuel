"""Central configuration for Nuelz Binary AI (IQ Option binary options)."""
import os

# Currency pairs monitored (Twelve Data symbol format). IQ Option trades these
# as live pairs on weekdays and as OTC (broker-generated) instruments on
# weekends — see market_hours.get_market_session() for the display label.
PAIRS = ["EUR/USD", "GBP/USD", "AUD/USD", "USD/CAD"]

# Analysis timeframe / scan cadence
INTERVAL = "1min"          # binary options need fast, short-horizon candles
OUTPUT_SIZE = 210          # bars fetched (needs 200+ for EMA200)
RSI_WINDOW = 7

# Higher timeframe used for multi-timeframe trend confirmation. Refreshed on
# its own slow cadence (not every scan) to keep API usage low.
HIGHER_TIMEFRAME_INTERVAL = "15min"
HIGHER_TIMEFRAME_REFRESH_SECONDS = 900  # re-check the higher-timeframe trend every 15 min

# --- Scan cadence -----------------------------------------------------------
# Twelve Data's free tier caps out around 800 requests/day (and ~8/min).
# Scanning 4 pairs every few seconds (as a paid plan could do) would blow
# through that in well under an hour. Default to a free-tier-safe cadence;
# lower this once TWELVE_DATA_API_KEY is on a paid plan with higher limits.
SCAN_INTERVAL_SECONDS = int(os.environ.get("SCAN_INTERVAL_SECONDS", 300))  # 5 min
# When the live Forex feed is unavailable (weekend gap — Twelve Data doesn't
# publish real OTC ticks), fetches will simply fail. Poll slower during that
# window to avoid burning API calls on requests that can't succeed; the last
# known analysis keeps being displayed/broadcast (never silent), clearly
# labeled as OTC/stale.
OFFLINE_FEED_POLL_SECONDS = 900  # 15 min

# --- Binary options confidence tiers -----------------------------------------
# Signals are NEVER hidden — every tier is always shown, down to Very Low.
VERY_HIGH_CONFIDENCE = 90   # 🟢 Very High Confidence
HIGH_CONFIDENCE = 80        # 🟢 High Confidence
MEDIUM_CONFIDENCE = 70      # 🟡 Medium Confidence
LOW_CONFIDENCE = 60         # 🔵 Low Confidence
# Below LOW_CONFIDENCE = 🔴 Very Low Confidence (still shown, marked "do not enter")

# --- Signal delivery modes ---------------------------------------------------
# The AI must never remain silent: the scanner runs continuously and, when
# AUTO_ALERTS is on, pushes the current best available setup to Telegram
# every scan cycle — regardless of confidence tier. /signal is always
# available on demand as well.
AUTO_ALERTS = True

# Auto-alert de-duplication: only suppress a literal repeat (unchanged pair +
# direction + confidence) within this window, so restarts/cycles don't spam
# identical messages back-to-back while conditions haven't actually changed.
ALERT_DEDUP_COOLDOWN_MINUTES = 8
ALERT_DEDUP_CONFIDENCE_DELTA = 3

# /signal reuses a scan this fresh instead of re-fetching from the API.
SIGNAL_CACHE_MAX_AGE_SECONDS = 45

# Secrets / credentials (never hardcode — read from environment)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
TWELVE_DATA_API_KEY = os.environ.get("TWELVE_DATA_API_KEY", "")

# Where signal history / scheduler state is persisted
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
HISTORY_FILE = os.path.join(DATA_DIR, "history.json")
STATE_FILE = os.path.join(DATA_DIR, "scheduler_state.json")
MAX_HISTORY = 200

# --- Owner personalization / scheduled messages -----------------------------
# Configurable so it can be changed later without touching code.
TIMEZONE = os.environ.get("APP_TIMEZONE", "Africa/Lagos")  # WAT, UTC+1
OWNER_NAME = "NuelzDigitalz"
OWNER_BIRTHDAY = (7, 19)  # (month, day)

# (hour, minute, key) in the configured TIMEZONE, 24h clock
GREETING_TIMES = [
    (8, 0, "morning"),
    (13, 0, "afternoon"),
    (19, 0, "evening"),
]
