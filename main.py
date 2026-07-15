"""Entry point for the Nuelz Forex AI Assistant (web dashboard + Telegram bot)."""
from app import app

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
