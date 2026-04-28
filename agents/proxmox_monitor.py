"""
Proxmox Monitor Agent — checks CPU, RAM, and disk every 15 minutes.
Sends a Telegram alert if any metric is over threshold. No paid tokens.
"""
import shutil
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv
load_dotenv(BASE_DIR / ".env")

from agents.notify import send_telegram
from memory_factory import create_memory_store

CPU_THRESHOLD = 85      # percent
RAM_THRESHOLD = 90      # percent
DISK_THRESHOLD = 85     # percent


def cpu_percent():
    """Read CPU usage from /proc/stat over a 1-second window."""
    def read_stat():
        with open("/proc/stat") as f:
            line = f.readline()
        vals = list(map(int, line.split()[1:8]))
        total = sum(vals)
        idle = vals[3]
        return total, idle

    t1, i1 = read_stat()
    time.sleep(1)
    t2, i2 = read_stat()
    delta_total = t2 - t1
    delta_idle = i2 - i1
    if delta_total == 0:
        return 0.0
    return round(100.0 * (1 - delta_idle / delta_total), 1)


def ram_percent():
    meminfo = {}
    with open("/proc/meminfo") as f:
        for line in f:
            key, _, val = line.partition(":")
            meminfo[key.strip()] = int(val.strip().split()[0])
    total = meminfo.get("MemTotal", 1)
    available = meminfo.get("MemAvailable", 0)
    used = total - available
    return round(100.0 * used / total, 1)


def disk_percent(path="/"):
    usage = shutil.disk_usage(path)
    return round(100.0 * usage.used / usage.total, 1)


def run():
    memory = create_memory_store(BASE_DIR)

    cpu = cpu_percent()
    ram = ram_percent()
    disk = disk_percent("/")

    print(f"[proxmox_monitor] CPU={cpu}% RAM={ram}% Disk={disk}%")

    alerts = []
    if cpu >= CPU_THRESHOLD:
        alerts.append(f"CPU is at {cpu}% (threshold {CPU_THRESHOLD}%)")
    if ram >= RAM_THRESHOLD:
        alerts.append(f"RAM is at {ram}% (threshold {RAM_THRESHOLD}%)")
    if disk >= DISK_THRESHOLD:
        alerts.append(f"Disk is at {disk}% (threshold {DISK_THRESHOLD}%)")

    if alerts:
        msg = "Agent Hart ALERT:\n" + "\n".join(f"• {a}" for a in alerts)
        print(f"[proxmox_monitor] {msg}")
        send_telegram(msg)
        memory.add_audit_event("agent_alert", {"agent": "proxmox_monitor", "alerts": alerts})
    else:
        memory.add_audit_event("agent_run", {
            "agent": "proxmox_monitor",
            "cpu": cpu, "ram": ram, "disk": disk,
        })


if __name__ == "__main__":
    run()
