#!/usr/bin/env bash
# Install Agent Hart systemd timers.
# Run with: sudo bash scripts/install_timers.sh
set -e

# Detect the real user (works whether run as root directly or via sudo)
INSTALL_USER="${SUDO_USER:-$USER}"
INSTALL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${INSTALL_DIR}/venv/bin/python"

echo "Installing timers for user=${INSTALL_USER}, dir=${INSTALL_DIR}"

# ── daily_briefing: runs at 07:00 every day ──────────────────────────────────
cat > /etc/systemd/system/agenthart-daily-briefing.service <<EOF
[Unit]
Description=Agent Hart Daily Briefing
After=network-online.target

[Service]
Type=oneshot
User=${INSTALL_USER}
WorkingDirectory=${INSTALL_DIR}
ExecStart=${PYTHON} agents/daily_briefing.py
StandardOutput=journal
StandardError=journal
EOF

cat > /etc/systemd/system/agenthart-daily-briefing.timer <<'EOF'
[Unit]
Description=Run Agent Hart Daily Briefing at 7am

[Timer]
OnCalendar=*-*-* 07:00:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

# ── memory_digest: runs at 02:00 every day ───────────────────────────────────
cat > /etc/systemd/system/agenthart-memory-digest.service <<EOF
[Unit]
Description=Agent Hart Memory Digest
After=network-online.target

[Service]
Type=oneshot
User=${INSTALL_USER}
WorkingDirectory=${INSTALL_DIR}
ExecStart=${PYTHON} agents/memory_digest.py
StandardOutput=journal
StandardError=journal
EOF

cat > /etc/systemd/system/agenthart-memory-digest.timer <<'EOF'
[Unit]
Description=Run Agent Hart Memory Digest nightly at 2am

[Timer]
OnCalendar=*-*-* 02:00:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

# ── task_review: runs at 09:00 and 14:00 every day ───────────────────────────
cat > /etc/systemd/system/agenthart-task-review.service <<EOF
[Unit]
Description=Agent Hart Task Review
After=network-online.target

[Service]
Type=oneshot
User=${INSTALL_USER}
WorkingDirectory=${INSTALL_DIR}
ExecStart=${PYTHON} agents/task_review.py
StandardOutput=journal
StandardError=journal
EOF

cat > /etc/systemd/system/agenthart-task-review.timer <<'EOF'
[Unit]
Description=Run Agent Hart Task Review at 9am and 2pm

[Timer]
OnCalendar=*-*-* 09:00:00
OnCalendar=*-*-* 14:00:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

# ── github_issues: runs at 08:00 and 16:00 (skips if no GITHUB_TOKEN set) ────
cat > /etc/systemd/system/agenthart-github-issues.service <<EOF
[Unit]
Description=Agent Hart GitHub Issues Sync
After=network-online.target

[Service]
Type=oneshot
User=${INSTALL_USER}
WorkingDirectory=${INSTALL_DIR}
ExecStart=${PYTHON} agents/github_issues.py
StandardOutput=journal
StandardError=journal
EOF

cat > /etc/systemd/system/agenthart-github-issues.timer <<'EOF'
[Unit]
Description=Run Agent Hart GitHub Issues sync at 8am and 4pm

[Timer]
OnCalendar=*-*-* 08:00:00
OnCalendar=*-*-* 16:00:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

# ── agent_watchdog: runs every 6 hours ───────────────────────────────────────
cat > /etc/systemd/system/agenthart-watchdog.service <<EOF
[Unit]
Description=Agent Hart Agent Watchdog
After=network-online.target

[Service]
Type=oneshot
User=${INSTALL_USER}
WorkingDirectory=${INSTALL_DIR}
ExecStart=${PYTHON} agents/agent_watchdog.py
StandardOutput=journal
StandardError=journal
EOF

cat > /etc/systemd/system/agenthart-watchdog.timer <<'EOF'
[Unit]
Description=Run Agent Hart Agent Watchdog every 6 hours

[Timer]
OnCalendar=*-*-* 00,06,12,18:05:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

# ── reload and enable ─────────────────────────────────────────────────────────
systemctl daemon-reload
systemctl enable --now agenthart-daily-briefing.timer
systemctl enable --now agenthart-memory-digest.timer
systemctl enable --now agenthart-task-review.timer
systemctl enable --now agenthart-github-issues.timer
systemctl enable --now agenthart-watchdog.timer

# Restart Telegram bot to load new /agent and /agents commands
systemctl restart agenthart-telegram

echo "Timers installed:"
systemctl list-timers agenthart-daily-briefing.timer agenthart-memory-digest.timer agenthart-task-review.timer --no-pager
echo ""
echo "Telegram bot restarted with new /agent and /agents commands."
