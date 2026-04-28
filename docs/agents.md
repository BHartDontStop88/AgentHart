# Agent Hart — Agent Reference

All 14 autonomous agents that ship with Agent Hart. Each runs as a systemd one-shot service on a timer.

---

## Agent Architecture

Every agent follows the same structure:

```python
def run():
    memory = create_memory_store(BASE_DIR)
    
    with AgentRun("agent_name", memory) as run:
        # ... do work ...
        result, meta = ollama_chat_with_meta(prompt)
        run.record_llm(meta)      # saves token counts + timing
        run.add_output(N)         # counts useful items produced
    
    memory.add_memory_summary(scope="agent_name", summary=result)
    memory.add_audit_event("agent_run", {...})

if __name__ == "__main__":
    run()
```

The `AgentRun` context manager automatically:
- Snapshots CPU and RAM usage at start
- Records start time, end time, duration
- Saves all telemetry to `agent_metrics` table
- Marks status as `success` or `error`

---

## Monitoring Agent

### proxmox_monitor

**Schedule:** Every 15 minutes  
**File:** `agents/proxmox_monitor.py`

Reads CPU usage from `/proc/stat`, RAM from `/proc/meminfo`, and disk from `shutil.disk_usage`. Sends a Telegram alert if any metric exceeds its threshold.

**Thresholds (configurable in the file):**
- CPU: 85%
- RAM: 90%
- Disk: 85%

**Outputs:** Audit log entry with CPU/RAM/disk readings. Telegram alert if thresholds exceeded.

---

### disk_watchdog

**Schedule:** Every hour  
**File:** `agents/disk_watchdog.py`

Checks disk usage across configured paths. More detailed than proxmox_monitor — can check multiple mount points and flag directories growing quickly.

---

### agent_watchdog

**Schedule:** Every 6 hours (00:05, 06:05, 12:05, 18:05)  
**File:** `agents/agent_watchdog.py`

Checks that every other agent has run within its expected time window. If any agent has gone silent, sends a Telegram alert listing which agents are overdue.

**Expected windows (configurable in `WATCHDOG_WINDOWS`):**
- `proxmox_monitor`: 1 hour
- `disk_watchdog`: 3 hours
- `daily_briefing`: 26 hours
- `task_review`: 10 hours
- `weekly_review`: 170 hours (weekly)
- etc.

**Use case:** If systemd timer breaks, power was off, or an agent is crashing silently, you'll know within 6 hours.

---

## Daily Workflow Agents

### daily_briefing

**Schedule:** 7:00 AM daily  
**File:** `agents/daily_briefing.py`

Reads open tasks, recent notes, and pending reminders. Asks Gemma4 to write a morning briefing covering:
1. Priority tasks for today
2. Overdue or urgent items
3. A motivational note

**Outputs:**
- Telegram message with the briefing
- Memory summary (scope: `daily_briefing`)
- Report file: `reports/briefings/YYYY-MM-DD.md`

---

### task_review

**Schedule:** 9:00 AM and 2:00 PM  
**File:** `agents/task_review.py`

Reads all open tasks and asks Gemma4 to:
1. Flag overdue tasks
2. Identify the top 3 tasks to tackle today
3. Flag vague tasks that need more detail

**Outputs:**
- Memory summary (scope: `task_review`) — shown on the Dashboard homepage
- Audit log entry

---

### weekly_review

**Schedule:** Sunday 8:00 PM  
**File:** `agents/weekly_review.py`

Reads completed tasks from the past 7 days, overdue tasks, all open tasks, and recent agent summaries. Asks Gemma4 to write a weekly review covering wins, slippage, next week's priorities, and one lesson.

**Outputs:**
- Telegram message with the review
- Memory summary (scope: `weekly_review`)
- Report file: `reports/weekly/YYYY-MM-DD.md`

---

## Memory and Learning Agents

### memory_digest

**Schedule:** 2:00 AM daily  
**File:** `agents/memory_digest.py`

Reads old chat history and condenses it into saved lessons. Keeps the chat_history table lean so future AI calls don't waste context on old conversations.

**Outputs:**
- New lessons added to the `lessons` table
- Memory summary (scope: `memory_digest`)

---

### note_organizer

**Schedule:** Daily (10:00 PM)  
**File:** `agents/note_organizer.py`

Reviews saved notes and groups related ones, flags duplicates, and suggests which notes to promote to lessons.

**Outputs:**
- Memory summary (scope: `note_digest`)
- Audit log entry

---

### lesson_reviewer

**Schedule:** Daily (9:00 AM)  
**File:** `agents/lesson_reviewer.py`

Reviews saved lessons and surfaces the most relevant ones for the current context. Helps the user notice patterns in what they've learned.

**Outputs:**
- Memory summary (scope: `lesson_review`)

---

### goal_tracker

**Schedule:** Weekly (Sunday)  
**File:** `agents/goal_tracker.py`

Reviews goals defined in the Agents section and checks progress against associated tasks. Flags goals with no recent task activity as stalled.

**Outputs:**
- Memory summary (scope: `goal_review`)
- Audit log entry

---

## Integration Agents

### git_activity

**Schedule:** Daily (9:00 PM)  
**File:** `agents/git_activity.py`

Scans all git repositories found under `~` (up to 4 levels deep) for commits in the last 24 hours. Asks Gemma4 to summarize what was worked on.

**Outputs:**
- Memory summary (scope: `git_activity`) — shown on Dashboard homepage
- Audit log entry

---

### todo_harvester

**Schedule:** Daily (6:00 PM)  
**File:** `agents/todo_harvester.py`

Scans code files in configured directories for `TODO`, `FIXME`, `HACK`, and `XXX` comments. Creates tasks for any found items that aren't already in the task list.

**Outputs:**
- New tasks created with appropriate project tags
- Audit log entry with count of found items

---

### github_issues

**Schedule:** 8:00 AM and 4:00 PM  
**File:** `agents/github_issues.py`  
**Requires:** `GITHUB_TOKEN` and `GITHUB_REPOS` in `.env`

Fetches open GitHub issues from configured repositories and creates Agent Hart tasks for any issues not already in the task list. Deduplicates on re-run.

**Label → Priority mapping:**
- critical/urgent/p0/p1 → high
- low/p3/p4/nice-to-have → low
- everything else → normal

**Configuration:**
```env
GITHUB_TOKEN=ghp_your_personal_access_token
GITHUB_REPOS=owner/repo1,owner/repo2
```

If `GITHUB_TOKEN` is not set, the agent exits cleanly with a message. Safe to leave the timer enabled even without a token.

**Outputs:**
- New tasks with `project=owner/repo` tag
- Audit log entry with counts

---

## Security Agent

### failed_login_watcher

**Schedule:** Daily (6:00 AM)  
**File:** `agents/failed_login_watcher.py`  
**Requires:** your user in the `adm` group (`sudo usermod -aG adm youruser`)

Reads `/var/log/auth.log` and counts failed SSH login attempts in the last 24 hours. Groups by IP address and asks Gemma4 to assess whether it's background noise or a targeted attack.

**Alert threshold:** 20 failed attempts triggers a Telegram alert.

**Outputs:**
- Memory summary (scope: `security_review`)
- Telegram alert if threshold exceeded
- Audit log entry with failure count

---

## Adding a New Agent

1. Create `agents/your_agent.py`:

```python
"""Your agent description."""
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv
load_dotenv(BASE_DIR / ".env")

from ai import ollama_chat_with_meta
from agents.metrics import AgentRun
from memory_factory import create_memory_store


def run():
    memory = create_memory_store(BASE_DIR)
    
    # ... gather data ...
    
    prompt = "Your prompt here..."
    
    with AgentRun("your_agent", memory) as run:
        result, meta = ollama_chat_with_meta(prompt)
        run.record_llm(meta)
        run.add_output(1)
    
    memory.add_memory_summary(scope="your_agent", summary=result)
    memory.add_audit_event("agent_run", {"agent": "your_agent"})


if __name__ == "__main__":
    run()
```

2. Add to `RUNNABLE_AGENTS` in `dashboard.py` and `telegram_bot.py`

3. Add to `WATCHDOG_WINDOWS` in `agents/agent_watchdog.py`

4. Add service + timer units to `scripts/install_timers.sh`

5. Run `sudo bash scripts/install_timers.sh` to install
