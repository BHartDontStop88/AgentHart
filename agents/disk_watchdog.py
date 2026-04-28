"""
Disk Watchdog Agent — runs hourly, alerts via Telegram if disk is critically full.
No paid tokens. Your disk is already at 81% — this is active immediately.
"""
import shutil
import sys
from datetime import date
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv
load_dotenv(BASE_DIR / ".env")

from agents.notify import send_telegram
from memory_factory import create_memory_store

WARN_THRESHOLD = 80     # percent — warn
CRITICAL_THRESHOLD = 90 # percent — urgent alert

PATHS_TO_CHECK = ["/", "/home"]


def check_path(path):
    try:
        usage = shutil.disk_usage(path)
        pct = round(100.0 * usage.used / usage.total, 1)
        free_gb = round(usage.free / (1024 ** 3), 1)
        return pct, free_gb
    except FileNotFoundError:
        return None, None


def run():
    memory = create_memory_store(BASE_DIR)
    today = date.today().isoformat()
    alerts = []
    status_lines = []

    for path in PATHS_TO_CHECK:
        pct, free_gb = check_path(path)
        if pct is None:
            continue
        status_lines.append(f"{path}: {pct}% used, {free_gb}GB free")
        if pct >= CRITICAL_THRESHOLD:
            alerts.append((path, pct, free_gb, "CRITICAL"))
        elif pct >= WARN_THRESHOLD:
            alerts.append((path, pct, free_gb, "WARNING"))

    for line in status_lines:
        print(f"[disk_watchdog] {line}")

    if alerts:
        lines = ["Agent Hart Disk Alert:"]
        for path, pct, free_gb, level in alerts:
            lines.append(f"• [{level}] {path} is {pct}% full ({free_gb}GB free)")
        lines.append("Consider cleaning up logs, temp files, or unused models.")
        msg = "\n".join(lines)
        send_telegram(msg)
        memory.add_audit_event("agent_alert", {"agent": "disk_watchdog", "date": today, "alerts": [
            {"path": p, "pct": pct, "level": lvl} for p, pct, _, lvl in alerts
        ]})
    else:
        memory.add_audit_event("agent_run", {"agent": "disk_watchdog", "date": today})


if __name__ == "__main__":
    run()
