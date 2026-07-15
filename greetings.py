"""Scheduled personal messages: daily greetings, monthly kickoff, and the
owner's birthday. Each fires exactly once per period, tracked in a persisted
state file so restarts never cause a duplicate or a missed send."""
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import config
import storage
import telegram_bot

log = logging.getLogger("nuelz.greetings")

DIVIDER = telegram_bot.DIVIDER

GREETING_MESSAGES = {
    "morning": "\n".join([
        "🌅 <b>Good Morning, NuelzDigitalz!</b>",
        DIVIDER,
        "",
        "Hope you slept well. I've been watching the IQ Option markets overnight and I'm ready "
        "whenever you want a HIGHER/LOWER signal — just send /signal.",
        "",
        "Wishing you a focused and profitable day ahead.",
    ]),
    "afternoon": "\n".join([
        "☀️ <b>Good Afternoon, NuelzDigitalz!</b>",
        DIVIDER,
        "",
        "Halfway through the day — the market's still under close watch. Send /signal "
        "anytime you want the latest read.",
    ]),
    "evening": "\n".join([
        "🌙 <b>Good Evening, NuelzDigitalz!</b>",
        DIVIDER,
        "",
        "Wrapping up the day. I'll keep scanning through the night and reach out the "
        "moment a strong HIGHER/LOWER setup appears.",
        "",
        "Rest well!",
    ]),
}


def _new_month_message(now_local: datetime) -> str:
    return "\n".join([
        "🎉 <b>Happy New Month, NuelzDigitalz!</b>",
        DIVIDER,
        "",
        f"Welcome to {now_local.strftime('%B %Y')}! A fresh month of markets ahead — "
        "wishing you clarity, discipline, and great opportunities this month.",
    ])


BIRTHDAY_MESSAGE = "\n".join([
    "🎂 <b>Happy Birthday, NuelzDigitalz!</b>",
    DIVIDER,
    "",
    "Wishing you an amazing day filled with joy and success — today and always. "
    "Thank you for building me! 🎈",
])


def _tz() -> ZoneInfo:
    return ZoneInfo(config.TIMEZONE)


def check_and_send_scheduled_messages() -> None:
    now_local = datetime.now(_tz())
    state = storage.load_scheduler_state()
    today_str = now_local.strftime("%Y-%m-%d")
    sent_today = set(state.get("greetings", {}).get(today_str, []))
    changed = False

    for hour, minute, key in config.GREETING_TIMES:
        if key in sent_today:
            continue
        target = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        # 5-minute grace window covers the scheduler's polling granularity.
        if target <= now_local < target + timedelta(minutes=5):
            if telegram_bot.send_message(GREETING_MESSAGES[key]):
                sent_today.add(key)
                state.setdefault("greetings", {})[today_str] = sorted(sent_today)
                changed = True
                log.info("Sent %s greeting", key)

    if now_local.day == 1 and now_local.hour == 0 and 1 <= now_local.minute < 6:
        month_key = now_local.strftime("%Y-%m")
        if state.get("new_month") != month_key:
            if telegram_bot.send_message(_new_month_message(now_local)):
                state["new_month"] = month_key
                changed = True
                log.info("Sent Happy New Month message for %s", month_key)

    if (now_local.month, now_local.day) == config.OWNER_BIRTHDAY and now_local.hour == 0 and 1 <= now_local.minute < 6:
        year_key = str(now_local.year)
        if state.get("birthday") != year_key:
            if telegram_bot.send_message(BIRTHDAY_MESSAGE):
                state["birthday"] = year_key
                changed = True
                log.info("Sent birthday message for %s", year_key)

    # Prune old day-keys so the greetings dict doesn't grow forever.
    greetings = state.get("greetings", {})
    if len(greetings) > 3:
        for old_day in sorted(greetings)[:-3]:
            del greetings[old_day]
        state["greetings"] = greetings
        changed = True

    if changed:
        storage.save_scheduler_state(state)


def scheduler_loop(stop_event) -> None:
    log.info("Greeting/celebration scheduler loop starting.")
    while not stop_event.is_set():
        try:
            check_and_send_scheduled_messages()
        except Exception:
            log.exception("Greeting/celebration scheduler error — will retry next cycle")
        stop_event.wait(30)
