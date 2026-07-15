# Nuelz Binary AI

## Overview
An AI-assisted market analysis system built for **IQ Option binary options**
(HIGHER/LOWER only — no Stop Loss, Take Profit, Trailing Stop, or
Risk/Reward, since those don't exist in binary options). It continuously
scans EUR/USD, GBP/USD, AUD/USD and USD/CAD, scores each pair with a
transparent rule-based confidence engine, and never stays silent — the
current best available setup is always shown, from Very High confidence down
to Very Low. Delivered via a password-protected web dashboard and a Telegram
bot.

This is an **analysis and signal assistant only** — it never places trades.
Every signal ends with a plain decision: 🟢 ENTER NOW, 🟡 WAIT FOR
CONFIRMATION, or 🔴 DO NOT ENTER, plus a confidence percentage. Nothing here
is a guaranteed outcome.

## Architecture
- `app.py` — Flask app; requires a master password (`session`-based login,
  see below) before serving the dashboard or API. Boots three daemon
  threads: continuous scanner, Telegram command listener, greeting scheduler.
- `market_hours.py` — `is_forex_open()` tells the scanner when the live
  interbank Forex feed is available; `get_market_session()` gives the
  human-facing session label (Asian/London/New York/Overlap/Weekend OTC);
  `display_pair()` appends "(OTC)" on weekends to match how IQ Option labels
  these instruments when the interbank market is shut.
- `market_data.py` — fetches OHLC candles from the Twelve Data API for any
  interval (primary 1-minute analysis timeframe or the 15-min higher
  timeframe used for confirmation).
- `indicators.py` — RSI(7), EMA 20/50/200, MACD(12,26,9), ATR, ADX, ROC,
  Bollinger Bands, rolling support/resistance with breakout/fake-breakout
  detection, simple candlestick pattern recognition (engulfing/doji/pin
  bar), and a linear-trend market-structure read, all via the `ta` library.
- `signal_engine.py` — rule-based confidence scoring (0-100) across 9
  weighted components. Binary options have no "no trade" state, so one
  direction (HIGHER or LOWER) is always favored — confidence, not direction,
  tells you whether it's worth acting on. Classifies every setup into one of
  5 tiers (`config.VERY_HIGH_CONFIDENCE` down through Very Low, never
  hidden), picks an expiry (30s-5min) based on volatility, and maps the tier
  to a final decision (ENTER NOW / WAIT FOR CONFIRMATION / DO NOT ENTER).
  Deterministic and traceable, not a trained ML model.
- `telegram_bot.py` — one canonical signal message format
  (`format_signal_message`) used for every tier; `/start`/`/status` reply
  with bot status; `/signal` shows an inline keyboard (1/2/3 signals) and
  always returns that many setups — never hidden or padded, since the AI
  must never go silent. Auto-alerts push the current best setup to
  `TELEGRAM_CHAT_ID` every scan cycle (de-duplicated only against literal
  repeats).
- `scanner.py` — `analyze_all()` is the pure fetch+score pipeline;
  `run_scan()` always produces a best-available result even when the live
  feed is down (falls back to the last-known scan, marked `stale`);
  `continuous_scan_loop()` runs 24/7 — binary options trade via IQ Option's
  OTC instruments on weekends even though the real interbank feed pauses, so
  scanning never truly stops, just slows down when fetches can't succeed.
- `greetings.py` — sends the 8am/1pm/7pm daily greetings, "Happy New Month"
  (1st of the month), and the owner's birthday message (July 19), each
  guaranteed to fire once per period even across restarts.
- `storage.py` — persists signal history (`data/history.json`) and
  scheduler state / auto-alert de-dup markers (`data/scheduler_state.json`).
- `templates/`, `static/` — dark, IQ Option-style dashboard UI (vanilla
  HTML/CSS/JS, polls `/api/state` and `/api/history` every 15s) plus a
  standalone `login.html` for the master-password gate.

## Access control
The dashboard and all API routes require a master password before anything
is served (`app.py`'s `before_request` hook + `/login`). Session cookies are
signed with the `SESSION_SECRET` secret; the password itself is the
`MASTER_PASSWORD` secret. If `MASTER_PASSWORD` isn't set, the app fails
closed (503) rather than silently exposing signals.

## Running it
The "Start application" workflow runs `python main.py`, serving on port 5000.
All background threads (scanning, Telegram polling, greetings) start
automatically with the app — no separate process to launch.

## Required secrets
- `TELEGRAM_BOT_TOKEN` — bot token from @BotFather.
- `TELEGRAM_CHAT_ID` — the chat that receives alerts. Must be a chat the bot
  can message (e.g. the numeric ID of a user who has messaged the bot, or a
  group it has joined) — not the bot's own ID.
- `TWELVE_DATA_API_KEY` — free API key from twelvedata.com for live Forex OHLC data.
- `MASTER_PASSWORD` — the password required to unlock the dashboard.
- `SESSION_SECRET` — signs the login session cookie.

## Known constraints
- **Twelve Data free tier caps out around 800 requests/day.** Scanning 4
  pairs on a 1-minute analysis timeframe every few seconds would exceed that
  quickly. `config.SCAN_INTERVAL_SECONDS` defaults to 300s (5 min) to stay
  within the free tier; lower it once the API key is upgraded.
- **True IQ Option OTC price feeds are not available from Twelve Data** (OTC
  prices are broker-generated on weekends, not real interbank ticks). When
  the live Forex feed is closed, the app keeps serving/broadcasting the last
  known real-market analysis, clearly labeled "(OTC)" and `stale: true`,
  rather than fabricating live OTC prices it doesn't actually have.
- Confidence tiers (`config.py`): Very High ≥90%, High ≥80%, Medium ≥70%,
  Low ≥60%, Very Low below that — all five are always shown, never
  suppressed.
- `config.AUTO_ALERTS = True` by default — pushes the current best setup to
  Telegram every scan cycle, any confidence tier. Set to `False` for
  on-demand-only delivery via `/signal`; scanning continues either way.
- Scheduled messages (greetings, monthly, birthday) use `config.TIMEZONE`
  (default `Africa/Lagos`, WAT/UTC+1).

## User preferences
(none recorded yet)
