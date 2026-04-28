# Agent Hart — Full Setup Guide

This guide covers everything from a fresh Ubuntu server to a fully running Agent Hart installation.

---

## Prerequisites

- Ubuntu 22.04+ (or any systemd-based Linux)
- Python 3.11+
- 4 GB+ RAM recommended (Gemma4:e2b needs ~4 GB for model weights)
- A Telegram account (optional but recommended)

---

## Step 1: Install Ollama

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

Verify it's running:

```bash
systemctl status ollama
```

Pull the model Agent Hart uses:

```bash
ollama pull gemma4:e2b
```

Test that the model loads:

```bash
ollama run gemma4:e2b
# Type: hello
# Type: /bye to exit
```

Ollama binds to `127.0.0.1:11434` by default. **Do not change this** — Agent Hart is designed to keep Ollama off the network.

---

## Step 2: Install Python Dependencies

```bash
sudo apt update
sudo apt install -y python3.12-venv python3-pip
```

---

## Step 3: Clone the Repository

```bash
git clone https://github.com/BHartDontStop88/AgentHart.git
cd AgentHart
```

---

## Step 4: Create the Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

## Step 5: Configure Environment

```bash
cp .env.example .env
nano .env
```

### Required settings

```env
OLLAMA_MODEL=gemma4:e2b
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_TIMEOUT_SECONDS=120
OLLAMA_NUM_CTX=4096
OLLAMA_TEMPERATURE=0.2
AGENT_HART_MEMORY_BACKEND=sqlite
```

### Telegram settings (required for notifications and remote control)

First, create a bot:
1. Open Telegram → search `@BotFather` → send `/newbot`
2. Follow prompts. BotFather gives you a token like `1234567890:AAxxxxxx`

Find your numeric Telegram user ID:
1. Message `@userinfobot` on Telegram
2. It replies with your numeric ID (e.g., `8648851945`)

Add to `.env`:

```env
TELEGRAM_BOT_TOKEN=1234567890:AAxxxxxx
TELEGRAM_ALLOWED_USER_IDS=8648851945
```

### GitHub Issues sync (optional)

Create a GitHub personal access token with `repo` scope at `github.com/settings/tokens`.

```env
GITHUB_TOKEN=ghp_your_token_here
GITHUB_REPOS=BHartDontStop88/AgentHart,owner/other-repo
```

---

## Step 6: Initialize the Database

The database creates itself on first use. Verify it works:

```bash
venv/bin/python -c "
from memory_factory import create_memory_store
from pathlib import Path
m = create_memory_store(Path('.'))
print('Memory stats:', m.memory_stats())
m.close()
"
```

---

## Step 7: Set Up the Dashboard as a Systemd Service

```bash
sudo nano /etc/systemd/system/agent-hart-dashboard.service
```

```ini
[Unit]
Description=Agent Hart Dashboard
After=network-online.target

[Service]
Type=simple
User=bhart
WorkingDirectory=/home/bhart/AgentHart
ExecStart=/home/bhart/AgentHart/venv/bin/python dashboard.py
Restart=on-failure
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now agent-hart-dashboard
```

Verify it's running:

```bash
systemctl status agent-hart-dashboard
curl -s http://127.0.0.1:8765/api/status
```

---

## Step 8: Set Up the Telegram Bot as a Systemd Service

```bash
sudo nano /etc/systemd/system/agenthart-telegram.service
```

```ini
[Unit]
Description=Agent Hart Telegram Bot
After=network-online.target

[Service]
Type=simple
User=bhart
WorkingDirectory=/home/bhart/AgentHart
ExecStart=/home/bhart/AgentHart/venv/bin/python telegram_bot.py
Restart=on-failure
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now agenthart-telegram
```

Test it: send `/help` to your bot in Telegram.

---

## Step 9: Install All Agent Timers

```bash
sudo bash scripts/install_timers.sh
```

This creates service and timer units for all 14 agents, reloads systemd, enables all timers, and restarts the Telegram bot.

Verify timers are active:

```bash
systemctl list-timers | grep agenthart
```

---

## Step 10: Access the Dashboard

The dashboard only listens on `127.0.0.1`. Access it from your local machine via SSH tunnel:

```bash
ssh -L 8765:127.0.0.1:8765 bhart@your-server-ip
```

Then open `http://127.0.0.1:8765` in your browser.

For a permanent tunnel on macOS/Linux, add to `~/.ssh/config`:

```
Host agenthart
  HostName your-server-ip
  User bhart
  LocalForward 8765 127.0.0.1:8765
```

Then just `ssh agenthart` and the tunnel is always up.

---

## Step 11: Set Up auth.log Access (for failed_login_watcher)

The `failed_login_watcher` agent reads `/var/log/auth.log`. By default, only root can read it. Add your user to the `adm` group:

```bash
sudo usermod -aG adm bhart
```

Log out and back in for the group change to take effect.

---

## Maintenance

### View agent logs

```bash
journalctl -u agenthart-daily-briefing -n 50
journalctl -u agenthart-proxmox-monitor -n 20 --since "1 hour ago"
```

### Manually trigger an agent

```bash
venv/bin/python agents/daily_briefing.py
```

Or from Telegram: `/agent daily_briefing`

Or from the dashboard: Agents page → Run Now button.

### Restart all services after a code update

```bash
sudo systemctl restart agent-hart-dashboard
sudo systemctl restart agenthart-telegram
```

Agents run as one-shot services so they don't need restarting — they pick up code changes on the next timer fire.

### Backup the database

```bash
cp agent_hart.db agent_hart.db.backup.$(date +%Y%m%d)
```

### Update the code

```bash
git pull
venv/bin/pip install -r requirements.txt
sudo systemctl restart agent-hart-dashboard agenthart-telegram
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Dashboard shows 500 errors | `journalctl -u agent-hart-dashboard -n 50` |
| Telegram bot not responding | `systemctl status agenthart-telegram` |
| Ollama timeout in agents | Increase `OLLAMA_TIMEOUT_SECONDS` in `.env` |
| Database locked errors | Should not happen with WAL mode enabled. If it does, restart the dashboard. |
| `auth.log` permission denied | `sudo usermod -aG adm bhart` then log out/in |
| Model not found | `ollama pull gemma4:e2b` |
| Agent never ran (watchdog alert) | Check `journalctl -u agenthart-<name>` for errors |
