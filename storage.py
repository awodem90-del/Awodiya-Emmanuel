"""Simple JSON-file persistence for signal history (survives restarts)."""
import json
import os
import threading

import config

_lock = threading.Lock()


def _ensure_file():
    os.makedirs(config.DATA_DIR, exist_ok=True)
    if not os.path.exists(config.HISTORY_FILE):
        with open(config.HISTORY_FILE, "w") as f:
            json.dump([], f)


def load_history() -> list[dict]:
    _ensure_file()
    with _lock:
        with open(config.HISTORY_FILE, "r") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return []


def append_history(entry: dict) -> None:
    _ensure_file()
    with _lock:
        with open(config.HISTORY_FILE, "r") as f:
            try:
                history = json.load(f)
            except json.JSONDecodeError:
                history = []
        history.append(entry)
        history = history[-config.MAX_HISTORY:]
        with open(config.HISTORY_FILE, "w") as f:
            json.dump(history, f, indent=2)


def _ensure_state_file():
    os.makedirs(config.DATA_DIR, exist_ok=True)
    if not os.path.exists(config.STATE_FILE):
        with open(config.STATE_FILE, "w") as f:
            json.dump({}, f)


def load_scheduler_state() -> dict:
    """Persisted 'already sent' markers for greetings, celebrations and
    auto-alert de-duplication — survives restarts so nothing double-fires."""
    _ensure_state_file()
    with _lock:
        with open(config.STATE_FILE, "r") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}


def save_scheduler_state(state: dict) -> None:
    _ensure_state_file()
    with _lock:
        with open(config.STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
