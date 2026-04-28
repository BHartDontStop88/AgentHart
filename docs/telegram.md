# Agent Hart — Telegram Command Reference

Complete guide to controlling Agent Hart from Telegram.

---

## Setup

### 1. Create a Bot

1. Open Telegram → search `@BotFather`
2. Send `/newbot`
3. Choose a display name (e.g., `Agent Hart`)
4. Choose a username ending in `bot` (e.g., `my_agenthart_bot`)
5. BotFather gives you a token — copy it

### 2. Find Your Numeric User ID

Message `@userinfobot` on Telegram. It replies with your numeric ID, e.g., `123456789`.

**Use the number, not your username.** Usernames can change. Numeric IDs never do.

### 3. Configure `.env`

```env
TELEGRAM_BOT_TOKEN=1234567890:AAxxxxxx
TELEGRAM_ALLOWED_USER_IDS=123456789
```

Multiple users:
```env
TELEGRAM_ALLOWED_USER_IDS=123456789,9876543210
```

### 4. Start the Bot

The bot runs as a systemd service:
```bash
sudo systemctl start agenthart-telegram
sudo systemctl enable agenthart-telegram  # start on boot
```

Test it: send `/help` to your bot.

---

## All Commands

### Task Management

```
/addtask <text>
/addtask high <text>
/addtask low <text>
```
Add a task. Optional priority prefix: `high` or `low` (default: `normal`).

Examples:
```
/addtask Review the API security report
/addtask high Fix authentication bug before deploy
/addtask low Update README with new commands
```

---

```
/tasks
```
List all open tasks with their number, priority, and due date.

---

```
/done <task-number>
```
Complete a task by its number from `/tasks`.

Example: `/done 3` completes the 3rd task in the list.

---

### Notes

```
/addnote <text>
```
Save a quick note to memory.

Example: `/addnote Meeting with team moved to Thursday`

---

### Projects

```
/project <name or description>
```
Ask Gemma4 to break a project into phases and tasks. All tasks are created automatically and tagged with the project name.

Example:
```
/project Set up monitoring for the production API
```

Gemma4 returns phases like Analysis, Implementation, Testing, and creates specific tasks under each. Takes 30–60 seconds.

---

```
/projects
```
Show all projects with task completion progress.

Example output:
```
Projects:
• AgentHart: 5/12 tasks (41%)
• WGU Studies: 3/8 tasks (37%)
• Home Lab: 2/2 tasks (100%)
```

---

### Autonomous Agents

```
/agents
```
List all runnable agents.

---

```
/agent <name>
```
Trigger any agent immediately. Agent runs in the background (up to 3 minutes for LLM agents).

Examples:
```
/agent daily_briefing
/agent task_review
/agent proxmox_monitor
/agent git_activity
```

The bot sends a "Running..." message, then replies with the agent's output when it finishes.

---

### Learning

```
/study <topic>
```
Generate a 4-question quiz on any topic using Gemma4.

Examples:
```
/study Python decorators
/study SQL window functions
/study network security fundamentals
/study WGU C949 discrete math
```

---

```
/quiz
```
Generate a quiz from your saved lessons.

---

```
/addlesson <text>
```
Save a lesson to long-term memory. Good lessons are behavioral guidance, not just facts.

Examples:
```
/addlesson Always test auth flows in an isolated environment
/addlesson WAL mode prevents SQLite lock errors under concurrent writes
```

---

```
/lessons
```
List all saved lessons.

---

### AI Chat

```
/chat <message>
```
Talk to Gemma4 directly. The conversation is saved to memory.

Examples:
```
/chat What are the OWASP top 10?
/chat Explain SQL injection with a simple example
/chat What should I focus on to become a SOC analyst?
```

---

```
/brief
```
Show today's summary: open tasks, due today, and recent tool results.

---

```
/memory
```
Show memory statistics: count of tasks, notes, summaries, etc.

---

### Approval-Gated Tools

These require you to explicitly approve before Agent Hart executes them.

```
/tools
```
List all registered tools, their risk level, and whether approval is required.

---

```
/run <tool> <target>
```
Request a tool execution. If approval is required, the bot sends Approve/Reject buttons.

Examples:
```
/run ping localhost
/run report Daily
/run nslookup example.com
```

---

```
/approvals
```
List pending approval requests.

---

```
/approve <id>
```
Approve a pending request by its short ID (first 8 characters).

---

```
/reject <id>
```
Reject a pending request.

---

## Automatic Notifications

Agent Hart sends Telegram messages automatically in these cases:

| Event | When | Message |
|-------|------|---------|
| Morning briefing | 7:00 AM daily | Today's tasks, reminders, motivational note |
| Weekly review | Sunday 8:00 PM | Wins, slippage, next week priorities |
| High CPU/RAM/disk | Any proxmox_monitor run | Alert with current values |
| Many failed SSH logins | Daily security check | Top attacker IPs + Gemma4 assessment |
| Agent gone silent | Every 6 hours | Which agents haven't run on schedule |
| Reminder due | Checked every minute | The reminder text |

---

## Security Notes

- **Never share your bot token.** Anyone with the token can send commands as if they were you.
- **Use numeric IDs in the allowlist.** `TELEGRAM_ALLOWED_USER_IDS=123456789` — not usernames.
- **Don't use `TELEGRAM_ALLOW_ALL=true`** except in isolated test environments.
- **The approval system applies to Telegram too.** `/run ping` still requires you to tap Approve before the tool runs.
- **To revoke access**, remove the user's ID from `TELEGRAM_ALLOWED_USER_IDS` and restart the bot.

---

## Troubleshooting

**Bot doesn't respond:**
```bash
systemctl status agenthart-telegram
journalctl -u agenthart-telegram -n 30
```

**"Unauthorized Telegram user." message:**
Your numeric user ID isn't in `TELEGRAM_ALLOWED_USER_IDS`. Find it with `@userinfobot`.

**`/agent daily_briefing` times out:**
Gemma4 takes 60–120 seconds on CPU. The bot sends "Running..." first and then the result. Wait for it — don't retry immediately or you'll have two agents running.

**`/project` returns unexpected format:**
Gemma4 sometimes doesn't return valid JSON. Rephrase the project description more specifically and try again.
