"""
Failed Login Watcher — scans auth.log daily for SSH brute-force attempts.
Uses gemma4 to summarize patterns and saves to memory. No paid tokens.
Requires: sudo usermod -aG adm bhart (so the agent can read /var/log/auth.log)
"""
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv
load_dotenv(BASE_DIR / ".env")

from ai import ollama_chat_with_meta
from agents.metrics import AgentRun
from agents.notify import send_telegram
from memory_factory import create_memory_store

AUTH_LOG = Path("/var/log/auth.log")
ALERT_THRESHOLD = 20    # alert if more than this many failed attempts in 24h


def parse_failures(log_text, since: datetime):
    """Extract failed login lines from the last 24 hours."""
    pattern = re.compile(r"(\w{3}\s+\d+\s+\d+:\d+:\d+).*Failed password.*from\s+(\S+)")
    current_year = date.today().year
    failures = []

    for line in log_text.splitlines():
        m = pattern.search(line)
        if not m:
            continue
        try:
            ts = datetime.strptime(f"{current_year} {m.group(1)}", "%Y %b %d %H:%M:%S")
        except ValueError:
            continue
        if ts >= since:
            failures.append({"time": ts.isoformat(), "ip": m.group(2), "raw": line.strip()})

    return failures


def run():
    memory = create_memory_store(BASE_DIR)
    today = date.today().isoformat()

    if not AUTH_LOG.exists():
        print("[failed_login_watcher] /var/log/auth.log not found — is bhart in the adm group?")
        return

    try:
        log_text = AUTH_LOG.read_text(encoding="utf-8", errors="replace")
    except PermissionError:
        print("[failed_login_watcher] Permission denied reading auth.log.")
        print("Fix: sudo usermod -aG adm bhart && log out and back in")
        return

    since = datetime.now() - timedelta(hours=24)
    failures = parse_failures(log_text, since)

    print(f"[failed_login_watcher] {len(failures)} failed login attempts in the last 24h")

    if not failures:
        memory.add_audit_event("agent_run", {"agent": "failed_login_watcher", "date": today, "failures": 0})
        return

    # Count by IP
    ip_counts: dict[str, int] = {}
    for f in failures:
        ip_counts[f["ip"]] = ip_counts.get(f["ip"], 0) + 1

    top_ips = sorted(ip_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    ip_block = "\n".join(f"  {ip}: {count} attempts" for ip, count in top_ips)

    sample = "\n".join(f["raw"] for f in failures[:20])
    prompt = (
        f"Today is {today}. Analyze these SSH failed login attempts from the last 24 hours.\n"
        "Provide a brief security summary:\n"
        "1. Is this normal background noise or a targeted attack?\n"
        "2. Any IPs that appear especially aggressive?\n"
        "3. One recommended action if warranted\n"
        "Keep it under 10 lines, plain text.\n\n"
        f"Top IPs:\n{ip_block}\n\nSample log lines:\n{sample}"
    )

    with AgentRun("failed_login_watcher", memory) as run:
        summary, meta = ollama_chat_with_meta(prompt)
        run.record_llm(meta)
        run.add_output(1)
    print(summary)

    memory.add_memory_summary(scope="security_review", summary=summary)
    memory.add_audit_event("agent_run", {"agent": "failed_login_watcher", "date": today, "failures": len(failures)})

    if len(failures) >= ALERT_THRESHOLD:
        msg = (
            f"Agent Hart Security Alert — {len(failures)} failed SSH logins in 24h\n\n"
            f"Top offenders:\n{ip_block}\n\n"
            f"Gemma4 assessment:\n{summary[:400]}"
        )
        send_telegram(msg)


if __name__ == "__main__":
    run()
