"""
Agent Watchdog — checks that scheduled agents have run within their expected window.
Sends a Telegram alert for any agent that has gone silent. No paid LLM tokens.

Expected run frequency is configured in WATCHDOG_WINDOWS below (hours).
Run this agent every 6 hours via its systemd timer.
"""
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv
load_dotenv(BASE_DIR / ".env")

from agents.metrics import AgentRun
from agents.notify import send_telegram
from memory_factory import create_memory_store

# Agent name → expected max hours between runs (0 = skip check)
WATCHDOG_WINDOWS = {
    "proxmox_monitor":     1,    # runs every 15 min — alert if silent 1h
    "disk_watchdog":       3,    # runs hourly — alert if silent 3h
    "daily_briefing":      26,   # runs at 7am — alert if silent 26h
    "task_review":         10,   # runs at 9am + 2pm — alert if silent 10h
    "todo_harvester":      26,   # runs daily — alert if silent 26h
    "git_activity":        26,   # runs daily — alert if silent 26h
    "github_issues":       20,   # runs at 8am + 4pm — alert if silent 20h
    "memory_digest":       26,   # runs at 2am — alert if silent 26h
    "note_organizer":      26,   # runs daily — alert if silent 26h
    "lesson_reviewer":     26,   # runs daily — alert if silent 26h
    "goal_tracker":        170,  # runs weekly — alert if silent 170h
    "weekly_review":       170,  # runs weekly — alert if silent 170h
}


def run():
    memory = create_memory_store(BASE_DIR)
    today = date.today().isoformat()
    now = datetime.now()

    metrics = memory.agent_metrics_summary()
    last_run_map = {m["agent_name"]: m["last_run"] for m in metrics if m.get("last_run")}

    silent = []
    for agent_name, max_hours in WATCHDOG_WINDOWS.items():
        if max_hours == 0:
            continue
        last = last_run_map.get(agent_name)
        if last is None:
            # Never run — only flag if it's been more than max_hours since install
            # (skip first-run noise by checking if the agent script exists)
            script = BASE_DIR / "agents" / f"{agent_name}.py"
            if script.exists():
                silent.append(f"{agent_name}: never run (expected every {max_hours}h)")
            continue
        try:
            last_dt = datetime.fromisoformat(last[:19])
        except ValueError:
            continue
        hours_ago = (now - last_dt).total_seconds() / 3600
        if hours_ago > max_hours:
            silent.append(
                f"{agent_name}: last ran {hours_ago:.0f}h ago (expected every {max_hours}h)"
            )

    print(f"[agent_watchdog] Checked {len(WATCHDOG_WINDOWS)} agents — {len(silent)} silent")

    with AgentRun("agent_watchdog", memory) as run:
        run.add_output(len(WATCHDOG_WINDOWS) - len(silent))
        if silent:
            run.set_error(f"{len(silent)} agents silent")

    if silent:
        msg = (
            f"Agent Hart Watchdog Alert — {today}\n"
            f"{len(silent)} agent(s) have not run in expected window:\n\n"
            + "\n".join(f"• {s}" for s in silent)
        )
        print(f"[agent_watchdog] ALERT:\n{msg}")
        send_telegram(msg)
        memory.add_audit_event("agent_alert", {
            "agent": "agent_watchdog",
            "date": today,
            "silent_agents": silent,
        })
    else:
        memory.add_audit_event("agent_run", {
            "agent": "agent_watchdog",
            "date": today,
            "all_healthy": True,
        })
        print("[agent_watchdog] All agents running on schedule.")


if __name__ == "__main__":
    run()
