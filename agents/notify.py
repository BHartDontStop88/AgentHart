"""Shared Telegram notification utility for autonomous agents."""
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv
load_dotenv(BASE_DIR / ".env")


def send_telegram(message: str) -> bool:
    """Send a message to the authorized Telegram user. Returns True on success."""
    try:
        import httpx
    except ImportError:
        print("[notify] httpx not available — skipping Telegram notification")
        return False

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    raw_ids = os.getenv("TELEGRAM_ALLOWED_USER_IDS", "").strip()
    if not token or not raw_ids:
        print("[notify] Telegram not configured — skipping notification")
        return False

    chat_id = raw_ids.split(",")[0].strip()
    try:
        resp = httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message},
            timeout=10,
        )
        return resp.status_code == 200
    except Exception as exc:
        print(f"[notify] Telegram send failed: {exc}")
        return False
