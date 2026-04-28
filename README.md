# Agent Hart

A local-first AI project management and automation platform running entirely on your own hardware. No cloud AI calls, no paid tokens — everything runs through Ollama with Gemma4 on your local machine.

Built as a learning project by a WGU student exploring AI, automation, cybersecurity, and practical software engineering. Every feature is intentionally visible, safe, and understandable.

---

## What It Does

Agent Hart is three things in one:

**1. A web dashboard** (`dashboard.py`) — dark-themed, FastAPI-powered UI for tasks, projects, workflow management, agent monitoring, and reports. Accessible via SSH tunnel from anywhere.

**2. An autonomous agent fleet** (`agents/`) — 14 agents that run on systemd timers, monitor your system, summarize your work, review your tasks, and alert you via Telegram when something needs attention.

**3. A Telegram command center** (`telegram_bot.py`) — control everything from your phone: add tasks, trigger any agent, check project progress, chat with Gemma4, get daily briefings.

**Zero paid tokens.** Every AI call goes to Ollama running locally.

---

## Dashboard Pages

| Page | URL | Purpose |
|------|-----|---------|
| Dashboard | `/today` | KPIs, due tasks, system health, agent summaries |
| Projects | `/projects` | Per-project task boards with progress bars |
| Inbox | `/inbox` | Pending approvals, suggested actions |
| PM Lifecycle | `/lifecycle` | 5-phase PM workflow with AI suggestions |
| Data Analytics | `/analytics` | 6-phase data analysis workflow (Ask→Act) |
| Agent Builder | `/build` | Design and export CLAUDE.md agent files |
| Search | `/search` | Full-text search across tasks, notes, memories |
| Metrics | `/metrics` | Agent telemetry, token usage, success rates |
| Memory | `/memory` | Notes, lessons, memory summaries |
| Reports | `/reports` | Agent-generated reports with markdown rendering |
| Agents | `/agents` | Autonomous agent control panel with Run Now buttons |
| Health | `/health` | System health checks |

---

## Autonomous Agents

| Agent | Schedule | What It Does |
|-------|----------|-------------|
| `proxmox_monitor` | Every 15 min | CPU/RAM/disk monitoring — Telegram alert on threshold breach |
| `disk_watchdog` | Every hour | Disk space check — alert if over 85% |
| `daily_briefing` | 7:00 AM | Morning briefing pushed to Telegram |
| `task_review` | 9:00 AM + 2:00 PM | Reviews open tasks, flags overdue |
| `todo_harvester` | Daily | Scans code repos for TODO/FIXME comments |
| `git_activity` | Daily | Summarizes commits across local git repos |
| `github_issues` | 8:00 AM + 4:00 PM | Syncs GitHub issues into tasks (requires token) |
| `memory_digest` | 2:00 AM | Condenses old chat history into lessons |
| `note_organizer` | Daily | Groups and cleans up saved notes |
| `lesson_reviewer` | Daily | Reviews and surfaces relevant lessons |
| `goal_tracker` | Weekly | Reviews goals, flags stalled progress |
| `weekly_review` | Sunday | Week-in-review pushed to Telegram |
| `failed_login_watcher` | Daily | Scans auth.log for SSH brute-force attempts |
| `agent_watchdog` | Every 6 hours | Checks all agents ran on schedule — alerts on silence |

---

## Telegram Commands

```
Tasks & Notes:
/addtask [high|low] <text>  — add a task
/addnote <text>             — save a note
/tasks                      — list open tasks
/done <task-number>         — complete a task

Projects:
/project <name>             — AI breaks project into tasks
/projects                   — show all project progress

Agents:
/agents                     — list all runnable agents
/agent <name>               — trigger any agent right now

Learning:
/study <topic>              — generate a quiz on any topic
/quiz                       — quiz from your saved lessons
/addlesson <text>           — save a lesson
/lessons                    — list saved lessons

AI & Memory:
/chat <message>             — talk to Gemma4
/brief                      — today's summary
/memory                     — memory stats

Tools (approval-gated):
/tools                      — list available tools
/run <tool> <target>        — run a tool
/approvals                  — pending approvals
/approve <id>               — approve an action
/reject <id>                — reject an action
```

---

## JSON API

Agent Hart exposes a small read-only API for external integrations:

| Endpoint | Returns |
|----------|---------|
| `GET /api/status` | Task counts, agent count, overall success rate |
| `GET /api/tasks?status=open&project=name` | Task list with optional filters |
| `GET /api/metrics` | Per-agent metrics summary + recent runs |
| `GET /api/health` | Latest health check result |

---

## Requirements

- Python 3.11+
- Ubuntu/Linux (systemd for agent timers)
- Ollama with `gemma4:e2b` or any Gemma4 variant
- Optional: Telegram bot token for remote control
- Optional: GitHub personal access token for Issues sync

---

## Installation

### 1. Install Ollama and pull the model

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull gemma4:e2b
```

### 2. Clone the repo

```bash
git clone https://github.com/BHartDontStop88/AgentHart.git
cd AgentHart
```

### 3. Create virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

On Ubuntu, if `python3-venv` is missing:

```bash
sudo apt install python3.12-venv
```

### 4. Configure environment

```bash
cp .env.example .env
nano .env
```

Minimum required config:

```env
OLLAMA_MODEL=gemma4:e2b
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_TIMEOUT_SECONDS=120
OLLAMA_NUM_CTX=4096
OLLAMA_TEMPERATURE=0.2
AGENT_HART_MEMORY_BACKEND=sqlite

TELEGRAM_BOT_TOKEN=your-token-from-botfather
TELEGRAM_ALLOWED_USER_IDS=your-numeric-telegram-user-id

# Optional — for GitHub Issues sync
# GITHUB_TOKEN=ghp_your_token
# GITHUB_REPOS=owner/repo1,owner/repo2
```

### 5. Start the dashboard

```bash
venv/bin/python dashboard.py
```

Access at `http://127.0.0.1:8765` — use an SSH tunnel if on a remote machine:

```bash
ssh -L 8765:127.0.0.1:8765 youruser@your-server-ip
```

Then open `http://127.0.0.1:8765` in your browser.

### 6. Start the Telegram bot

```bash
venv/bin/python telegram_bot.py
```

Or run it as a systemd service — see `docs/setup.md`.

### 7. Install agent timers (requires sudo)

```bash
sudo bash scripts/install_timers.sh
```

This creates systemd service + timer units for all 14 agents and restarts the Telegram bot.

---

## Project Structure

```
dashboard.py           FastAPI web dashboard
telegram_bot.py        Telegram bot interface
ai.py                  Ollama integration with metrics
structured_memory.py   SQLite memory backend
memory.py              JSON memory backend (legacy/backup)
memory_factory.py      Backend selector
reminder_worker.py     Background reminder checker → Telegram
main.py                Shared CLI helpers and data builders
tools.py               Tool registry and policy enforcement
policy.json            Tool permission policy

agents/
  daily_briefing.py    Morning briefing → Telegram
  disk_watchdog.py     Disk space monitor + alerts
  failed_login_watcher.py  SSH brute-force detector
  git_activity.py      Git commit summarizer
  github_issues.py     GitHub Issues → tasks sync
  goal_tracker.py      Goal progress reviewer
  lesson_reviewer.py   Lesson surface agent
  memory_digest.py     Chat history compressor
  metrics.py           AgentRun context manager (telemetry)
  note_organizer.py    Note cleanup agent
  notify.py            Telegram send helper
  proxmox_monitor.py   System resource monitor + alerts
  task_review.py       Task priority reviewer
  todo_harvester.py    TODO/FIXME code scanner
  weekly_review.py     Weekly summary → Telegram
  agent_watchdog.py    Agent health monitor

scripts/
  install_timers.sh    Systemd unit installer

templates/             Jinja2 HTML templates
static/style.css       Dark theme CSS
reports/               Agent-generated markdown reports
exports/               Agent Builder CLAUDE.md exports
```

---

## Safety Design

- **Ollama stays on 127.0.0.1** — never exposed to the network
- **Dashboard stays on 127.0.0.1** — SSH tunnel only
- **File write sandboxing** — Agent Builder exports only to `exports/` directory
- **SQLite WAL mode** — concurrent agent writes won't lock the dashboard
- **Approval-gated tools** — all tool execution requires explicit approval
- **Telegram allowlist** — only your numeric user ID can control the bot
- **No shell=True** — all subprocess calls use list arguments

---

## Security Notes

Never commit:
- `.env` (contains Telegram token and GitHub token)
- `agent_hart.db` (your personal data)
- `memory.json` (legacy backup)
- `reports/` (may contain sensitive summaries)

Use `.env.example` as the public template.

---

## Feedback Welcome

This is an active learning project. If you're reviewing it, I'm especially interested in feedback on:

- safer automation patterns
- better Ollama prompt engineering
- memory architecture improvements
- dashboard usability
- what skills to learn next to become job-ready in AI/security engineering

Issues and pull requests welcome.
