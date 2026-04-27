# Agent Hart Learning Notes

This project is a small personal agent built in phases. The goal is not to make
it powerful first. The goal is to make it understandable, observable, and safe.

## Big Picture

Agent Hart currently has four main pieces:

1. `main.py` is the command-line interface.
2. `memory.py` saves and loads JSON memory.
3. `tools.py` registers safe tools and enforces policy.
4. `policy.json` controls what the agent is allowed to do.

The design idea is separation of concerns. Each file has one job. That makes it
easier to add features later without turning the whole app into one giant script.

## How A Command Flows

When you type:

```text
run ping localhost
```

the flow is:

1. `main.py` reads the text from `input()`.
2. `main.py` splits the first word as the command: `run`.
3. `handle_run()` extracts the tool name: `ping`.
4. `ToolRegistry.validate_request()` checks whether `ping` is known and enabled.
5. The network target is checked against `allowed_domains` in `policy.json`.
6. Because `ping` requires approval, the CLI asks you to type `yes`.
7. `tools.py` builds a safe command list and runs it with `subprocess.run()`.
8. The output is saved in `memory.json`.

That gives you an audit trail. The agent does not just act. It records what it
did.

## Why There Is No Arbitrary Shell

The policy contains:

```json
"allow_shell_commands": false
```

That is a core safety decision. The current app does not accept random commands
like:

```text
run shell some-command
```

Instead, every tool must be registered in Python. This means we can inspect the
tool, assign a risk level, require approval, and keep its behavior narrow.

## Why JSON Memory First

JSON is not the most powerful database, but it is excellent for learning.

You can open `memory.json` and see:

- saved notes
- chat history
- tool results
- timestamps

Later, this can become SQLite or a search index. The important lesson is that
the rest of the app talks to the `MemoryStore` class, not directly to the file.
That class is a boundary.

## Why Policy Is Separate

Rules live in `policy.json` instead of being hardcoded everywhere.

That gives you a clean mental model:

- Python code defines what the app can technically do.
- Policy defines what the app is allowed to do right now.

For example, `ping` exists in code, but it still has to be enabled in policy.

## Phase 1 Approval Spine

Agent Hart now records tool requests before it runs them. A request becomes an
approval record with:

- an id
- an action type
- a human-readable description
- the exact payload the agent wants to execute
- a risk level
- a status such as `pending`, `approved`, `rejected`, or `auto_approved`

This matters because approval is no longer just a temporary prompt on screen. It
is durable memory. Later, Telegram buttons can approve the same approval records
that the CLI approves today.

Useful commands:

```text
approvals
approve <approval-id>
reject <approval-id>
```

Low-risk tools can still be auto-approved by policy, but they are recorded too.
That gives the agent an audit trail even when it does not need to stop and ask.

## Phase 2 Telegram Interface

Telegram is now an interface over the same Phase 1 core. It does not bypass the
approval system. When you send `/run ping localhost`, the bot creates the same
approval record that the CLI creates.

Tool approval requests also get Approve and Reject buttons in Telegram. This is
the important safety pattern:

1. You ask Agent Hart to do something from Telegram.
2. Agent Hart validates the request against `policy.json`.
3. If approval is required, Agent Hart creates a pending approval record.
4. Telegram shows Approve and Reject buttons.
5. Agent Hart only runs the tool after approval.
6. The result is saved back to `memory.json`.

### Telegram Setup Guide

This section is written so a new user can set up the Telegram interface from
scratch.

#### 1. Create A Telegram Bot

Open Telegram and search for:

```text
@BotFather
```

Start a chat with BotFather, then send:

```text
/newbot
```

BotFather will ask for two things:

1. A display name, such as `Agent Hart`.
2. A username that must end in `bot`, such as `agent_hart_local_bot`.

When BotFather finishes, it will give you a bot token. The token looks something
like this:

```text
1234567890:AAExampleTokenTextHere
```

Keep that token private. Anyone with the token can control the bot.

#### 2. Find Your Numeric Telegram User ID

Agent Hart should only answer you, not every Telegram user who finds the bot.
For that, it needs your numeric Telegram user id.

The easiest method is to message Telegram's user info bot:

```text
@userinfobot
```

Start the bot and it should reply with your numeric id. It will look like:

```text
123456789
```

Save that number. It goes into `TELEGRAM_ALLOWED_USER_IDS`.

You can allow more than one Telegram account by separating ids with commas:

```text
123456789,987654321
```

#### 3. Install Python Dependencies

From the project folder, install the dependencies:

```powershell
cd D:\AgentHart
pip install -r requirements.txt
```

If `pip` points to the wrong Python install, use:

```powershell
python -m pip install -r requirements.txt
```

The important Telegram package is:

```text
python-telegram-bot
```

The project also uses:

```text
python-dotenv
ollama
```

#### 4. Create The `.env` File

Copy the example environment file:

```powershell
cd D:\AgentHart
copy .env.example .env
```

Open `.env` in a text editor:

```powershell
notepad .env
```

Fill it in:

```text
OLLAMA_MODEL=gemma4
TELEGRAM_BOT_TOKEN=your-token-from-botfather
TELEGRAM_ALLOWED_USER_IDS=your-numeric-telegram-user-id
```

Example:

```text
OLLAMA_MODEL=gemma4
TELEGRAM_BOT_TOKEN=replace-with-your-bot-token
TELEGRAM_ALLOWED_USER_IDS=123456789
```

Do not commit `.env` to GitHub or share it publicly.

#### 5. Optional: Test Without The Allowlist

For quick local experiments only, you can add:

```text
TELEGRAM_ALLOW_ALL=true
```

That lets any Telegram user who can reach the bot talk to it. Do not use this
for a real personal agent.

The safer default is:

```text
TELEGRAM_ALLOWED_USER_IDS=your-numeric-telegram-user-id
```

#### 6. Make Sure Ollama Is Running

Agent Hart uses Ollama for local AI chat.

On Windows, make sure the Ollama app/service is running. Then install or pull
the model:

```powershell
ollama pull gemma4
```

You can test Ollama with:

```powershell
ollama run gemma4
```

If your installed model has a different name, change `.env`:

```text
OLLAMA_MODEL=your-model-name
```

#### 7. Start The Telegram Bot

Run:

```powershell
cd D:\AgentHart
python telegram_bot.py
```

If startup works, the terminal prints:

```text
Agent Hart Telegram bot started.
```

Leave that terminal open. The bot runs while this Python process is running.

Stop it with:

```text
Ctrl+C
```

#### 8. Smoke Test In Telegram

Open your new bot in Telegram and send:

```text
/help
```

Expected result: the bot lists available commands.

Then send:

```text
/tools
```

Expected result: the bot lists registered tools such as `ping`, `nslookup`, and
`report`.

Then test the approval flow:

```text
/run ping localhost
```

Expected result: Telegram shows an approval request with Approve and Reject
buttons.

Tap:

```text
Approve
```

Expected result: Agent Hart runs the ping tool and sends the output back to
Telegram. It also records the approval and result in `memory.json`.

You can inspect pending approvals with:

```text
/approvals
```

You can also approve or reject by command:

```text
/approve abc12345
/reject abc12345
```

The short id is the first part of the approval id shown by the bot.

#### 9. Supported Telegram Commands

```text
/help
/brief
/tasks
/tools
/approvals
/run <tool> <target>
/approve <approval-id>
/reject <approval-id>
/chat <message>
```

Plain text messages are treated like chat messages too.

Examples:

```text
/chat what should I focus on today?
/brief
/tasks
/run report Daily Telegram Test
```

#### 10. How Telegram Maps To The Core Agent

Telegram does not own the agent logic. It is only an interface.

The main files involved are:

```text
telegram_bot.py   Telegram commands, buttons, allowlist, and message handling
main.py           Shared CLI helpers and approval execution
memory.py         Saved notes, tasks, approvals, audit log, and tool results
tools.py          Registered tools and policy validation
policy.json       What tools are enabled and which targets are allowed
```

This is why the CLI and Telegram can both approve the same type of action. They
share the same memory and policy layer.

#### 11. Troubleshooting

If you see:

```text
Set TELEGRAM_BOT_TOKEN before starting telegram_bot.py.
```

Check that `.env` exists and contains:

```text
TELEGRAM_BOT_TOKEN=your-token
```

If you see:

```text
Set TELEGRAM_ALLOWED_USER_IDS to your Telegram numeric user id.
```

Add your numeric id:

```text
TELEGRAM_ALLOWED_USER_IDS=123456789
```

If Telegram says you are unauthorized, your Telegram id does not match the id in
`.env`. Re-check it with `@userinfobot`.

If you see:

```text
Telegram dependency is not installed.
```

Run:

```powershell
python -m pip install -r requirements.txt
```

If AI chat says Ollama cannot be reached, make sure Ollama is running and the
model exists:

```powershell
ollama pull gemma4
ollama run gemma4
```

If `/run ping example.com` is blocked, that is expected. Network tools are
restricted by `allowed_domains` in `policy.json`. The current safe defaults are:

```json
"allowed_domains": [
  "localhost",
  "testlab.local"
]
```

To allow another host or domain, edit `policy.json` carefully. Prefer specific
domains over broad access.

#### 12. Security Checklist

Before using the Telegram bot as a real personal agent, verify:

- `.env` contains your real bot token.
- `.env` contains only trusted numeric Telegram user ids.
- `TELEGRAM_ALLOW_ALL=true` is not enabled.
- `policy.json` only enables tools you actually want.
- `allowed_domains` only includes targets you trust.
- Tool requests that touch the network still require approval.
- You can stop the bot quickly with `Ctrl+C`.

This keeps Phase 2 useful without making the agent too powerful too early.

## Phase 3 Structured Memory With SQLite

Phase 3 moves Agent Hart from plain JSON memory toward structured durable
memory. The old `memory.json` file is still useful because it is easy to read,
backup, and inspect. The running agent now defaults to SQLite through:

```text
agent_hart.db
```

SQLite gives the agent separate tables for different kinds of memory:

```text
notes
tasks
reminders
actions
approval_requests
tool_results
chat_history
audit_log
lessons
memory_summaries
user_preferences
```

This is a better long-term base than one large JSON file because the agent can
query, count, migrate, and eventually summarize memory by type.

### How Memory Backend Selection Works

The app now creates memory through `memory_factory.py`.

Default backend:

```text
AGENT_HART_MEMORY_BACKEND=sqlite
```

Optional old backend:

```text
AGENT_HART_MEMORY_BACKEND=json
```

If the environment variable is missing, Agent Hart uses SQLite.

### First SQLite Migration

The first time SQLite memory starts, it checks for:

```text
memory.json
```

If `agent_hart.db` has not imported legacy memory yet, it copies existing JSON
records into structured SQLite tables. It does not delete `memory.json`.

Run this command to initialize or verify SQLite memory:

```powershell
cd D:\AgentHart
python -c "from memory_factory import create_memory_store; m=create_memory_store(); print(m.memory_stats()); m.close()"
```

Expected result: a dictionary of memory counts, such as:

```text
{'notes': 3, 'tasks': 2, 'reminders': 0, ...}
```

### Phase 3 CLI Commands

Show structured memory counts:

```text
memory stats
```

Add a durable long-term lesson:

```text
add lesson Always ask before changing system settings.
```

List lessons:

```text
list lessons
```

List saved summaries:

```text
memory summaries
```

Lessons are included in AI context, so the local model can use them as stable
background information.

### Phase 3 Telegram Commands

Telegram can also inspect and add long-term memory:

```text
/memory
/lessons
/addlesson Always ask before changing system settings.
```

These commands use the same SQLite memory as the CLI.

### Why Lessons Are Separate From Notes

Notes are general facts or reminders.

Lessons are durable behavior guidance for the agent. Good lessons sound like:

```text
Prefer approval before system changes.
Use concise answers when reporting test results.
Never run broad network checks unless the target is explicitly approved.
```

This gives the agent a way to learn from your preferences without burying those
preferences in ordinary chat history.

### Why Summaries Exist

Long chat history gets noisy. Summaries are a place to store compressed memory
such as:

```text
This week Agent Hart added Telegram approval buttons and SQLite memory.
```

Right now summaries can be stored and listed. Later, the agent can generate
daily or weekly summaries automatically after approval.

### SQLite Troubleshooting

If Windows says the database is locked, make sure another `python main.py`,
`python telegram_bot.py`, or `python reminder_worker.py` process is not already
running.

If you want to temporarily return to JSON memory:

```powershell
$env:AGENT_HART_MEMORY_BACKEND="json"
python main.py
```

To switch back:

```powershell
$env:AGENT_HART_MEMORY_BACKEND="sqlite"
python main.py
```

In `.env`, the setting looks like:

```text
AGENT_HART_MEMORY_BACKEND=sqlite
```

## Phase 4 Task Commands

Phase 4 gives Agent Hart a practical task loop:

```text
add task Review localhost report
list tasks
complete task 1
```

Tasks are stored through the same memory boundary as notes, approvals, and
lessons. That means the command-line interface does not need to know whether
memory is JSON or SQLite. It just asks memory to add, list, or complete tasks.

Task commands support a little structure without becoming complicated:

```text
add task Review report --due 2026-04-30 --priority high
add task Check logs --due today
```

Task lines show:

- whether the task is complete
- priority
- due date
- task text

This phase teaches:

- data modeling
- command parsing
- updating existing JSON records
- simple state transitions

It also reinforces the value of the SQLite migration from Phase 3. The same
task command helpers work with both `MemoryStore` and `SQLiteMemoryStore`.

## Phase 5 Telegram Task Commands

Phase 5 makes tasks useful from Telegram too:

```text
/tasks
/done 1
```

`/tasks` shows the same numbered task list as the CLI. `/done 1` completes the
first task using the same 1-based numbering as:

```text
complete task 1
```

This phase teaches:

- exposing the same core behavior through another interface
- keeping CLI and Telegram behavior consistent
- designing short mobile-friendly command output

## Phase 6 Memory Review

Phase 6 adds a simple review command:

```text
review memory
```

The command asks the AI to summarize recent tasks, notes, tool results, lessons,
and prior summaries. Agent Hart shows the draft first, then asks:

```text
Save this memory review? yes/no
```

If approved, the review is saved as a `memory_review` record in memory
summaries. This keeps summarization observable and human-controlled instead of
quietly rewriting long-term context.

This phase teaches:

- using existing memory as AI context
- creating durable summaries
- asking for approval before changing long-term memory

## Next Good Learning Step

## Phase 7 Agent Runtime Foundation

Phase 7 starts moving Agent Hart from assistant-shaped commands toward a
multi-automation runtime.

New storage sections:

```text
agents
goals
task_runs
run_steps
```

The first two are active now. The last two are schema foundation for the future
planner/executor loop.

New commands:

```text
add agent Recon --role researcher --tools ping,report --max-steps 7
list agents
add goal 1 Map localhost service posture
list goals
```

An agent profile records:

- name
- role
- allowed tools
- status
- autonomy level
- max step budget

A goal records:

- which agent owns it
- goal text
- status
- creation time

This phase does not let agents act autonomously yet. It gives the system a
durable place to describe who the agents are and what they are supposed to do
before later phases add execution.

Stress coverage creates 150 agents and 150 goals in both JSON and SQLite memory
to verify the runtime foundation persists cleanly.

## Next Good Learning Step

## Phase 8 Chat And Automation Separation

Phase 8 makes the boundary between conversation and automation explicit.

Chat is now conversational only:

```text
chat <message>
```

It records the user message, asks the model for a response, records the response,
and prints it. It does not create tasks, suggest actions, create automation runs,
or execute tools.

Automation has its own command surface:

```text
agent status
run-agent <agent-number-or-id>
stop-agent <run-id>
```

`agent status` is active now. It shows:

- agent count
- goal count
- pending goals
- task run count
- active run count
- run step count
- whether execution is enabled

`run-agent` and `stop-agent` are reserved placeholders. They refuse to execute
until the planner/executor phase exists. This keeps the interface honest: agents
and goals can be modeled, but autonomous execution cannot happen by accident.

Stress coverage sends 100 chat messages through SQLite memory and verifies chat
creates no tasks, actions, task runs, or run steps.

## Next Good Learning Step

## Phase 9 Per-Agent Tool Permissions

Phase 9 makes each agent's tool allowlist enforceable.

Global policy still lives in:

```text
policy.json
```

Agent policy now adds a second check before automation can request a tool:

```text
agent.allowed_tools
```

Both layers must pass:

1. The agent must be active.
2. The agent must list the requested tool in `allowed_tools`.
3. The tool must exist in `ToolRegistry`.
4. The tool must be enabled in `policy.json`.
5. The target must pass the normal global policy checks.

New dry-run command:

```text
agent check-tool 1 report Daily
agent check-tool 1 ping localhost
```

This command does not create an approval, run a tool, or save a tool result. It
only answers whether the selected agent would be allowed to request the tool.

Example response:

```text
Allowed for Reporter: report Daily (no approval, risk=low).
```

If blocked:

```text
Agent policy blocked this action: Agent 'Reporter' is not allowed to use tool: ping
```

Stress coverage checks 120 agent/tool combinations and verifies exactly the
agents with matching allowlists pass.

## Next Good Learning Step

## Phase 10 Supervised Planner Checkpoints

Phase 10 adds the first planner/executor shape, but keeps execution supervised.

New command:

```text
plan-agent <agent-number-or-id> <goal-number-or-id>
```

This command:

1. Finds the selected agent.
2. Finds one of that agent's goals.
3. Creates a durable task run.
4. Builds a strict JSON planning prompt.
5. Sends that prompt to Ollama.
6. Saves the model response as run step 1.
7. Checks any proposed tool against agent and global policy.
8. Stops before execution.

The planner response is expected to look like:

```json
{
  "thought_summary": "A report is appropriate.",
  "next_action": "propose_tool",
  "tool": "report",
  "target": "Daily",
  "reason": "The goal asks for a report."
}
```

Allowed `next_action` values:

```text
propose_tool
wait
stop
```

Run steps can be saved as:

```text
proposed
blocked_proposal
invalid_response
```

No tools are executed in this phase. The point is checkpointing: every planner
prompt, model response, proposed tool, and status is saved before future phases
allow controlled execution.

Stress coverage creates 80 supervised planner checkpoints in SQLite and verifies
that no tool results are created.

## Next Good Learning Step

## Phase 11 Ollama And Gemma Health Checks

Phase 11 hardens the local model connection before moving Agent Hart onto the
system where Ollama is running.

New command:

```text
ollama health
```

It prints:

- configured Ollama base URL
- model name
- timeout
- context window
- temperature
- whether the model answered a test prompt

Supported environment variables:

```text
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=gemma4
OLLAMA_TIMEOUT_SECONDS=60
OLLAMA_NUM_CTX=4096
OLLAMA_TEMPERATURE=0.2
```

The model call now uses an explicit Ollama client with the configured base URL
and timeout. Chat requests also pass `num_ctx` and `temperature` options, which
will matter when running Gemma on a separate Ollama host.

Failure handling is structured and beginner-friendly. If Ollama is down, the
model is missing, or the Python package is not installed, the health check says
what failed and what to try next.

Stress coverage runs 50 repeated failed health checks and verifies every failure
returns a clean structured error instead of crashing.

## Next Good Learning Step

## Phase 12 Health Monitoring And Outcome Learning

Phase 12 gives Agent Hart two self-improvement foundations:

```text
health check
health report
health history
run review <run> <outcome> <summary>
```

Health checks inspect:

- memory stats and writability
- policy file presence
- enabled registered tools
- reports directory writability
- Ollama health
- pending approvals
- open task runs

Each health check is saved as durable memory:

```text
health_checks
```

Overall health can be:

```text
ok
degraded
fail
```

Run reviews are the first explicit learning record. After a planner run, the
human can save an outcome:

```text
run review 1 success Report looked good.
run review 1 bad_plan Proposed the wrong tool.
run review 1 blocked_by_policy Ping was not allowed for this agent.
```

Allowed outcomes:

```text
success
partial_success
blocked_by_policy
failed_tool
bad_plan
user_rejected
```

Run reviews are stored in:

```text
run_reviews
```

`agent status` now includes basic performance learning:

```text
Reporter: reviews=4 success_rate=75% common_outcome=success
```

This phase does not let the model rewrite its own behavior. It creates auditable
learning data that later phases can use to improve prompts, policies, and agent
defaults with human oversight.

Stress coverage runs 40 health checks and 40 run reviews in SQLite, then verifies
the saved health history, review count, and calculated success rate.

## Next Good Learning Step

## Phase 13 Daily Assistant Command Center

Phase 13 makes Agent Hart more useful as a day-to-day assistant.

`today` is now a command center instead of only a due-today task list:

```text
today
```

It shows:

- tasks due today
- overdue tasks
- pending approvals
- open agent runs
- latest health status
- suggested next actions

New inbox command:

```text
inbox
```

The inbox groups items that need human attention:

- pending approvals
- pending suggested actions
- open agent runs
- health warnings

Chat also gets safer natural-language intent routing. The model can suggest a
task from a chat message, but Agent Hart shows the draft and asks for approval
before saving anything:

```text
Suggested task:
Text: check dashboard
Due: 2026-04-27
Priority: high
Approve suggested task? Type yes to continue:
```

If the answer is not `yes`, no task is created and the suggested action is
marked rejected. This keeps chat convenient without making memory changes
silently.

Stress coverage creates 60 overdue tasks and 60 health checks in SQLite, then
verifies the command center and inbox still report the right state.

## Next Good Learning Step

A strong next phase would be making memory review available from Telegram:

```text
/review
```

That would reuse the same review-and-save behavior from a mobile interface.

## Interactive App vs Background Worker

`main.py` is the interactive agent. It waits for commands, prints responses, and
lets the human decide what should happen next.

`reminder_worker.py` is a background helper. It does one narrow job: every 60
seconds, it checks `memory.json` for reminders that are due, prints them, and
marks them completed.

Real apps often split work this way. The main app handles user interaction, while
background workers handle repeated jobs like reminders, scheduled reports, email
queues, cleanup tasks, and syncing data. Keeping those jobs separate makes the
system easier to understand and safer to change.

## Local AI With Ollama On Ubuntu

Agent Hart can use Ollama so AI chat runs locally instead of calling a cloud API.
That avoids token costs and keeps the project easier to run on an Ubuntu machine.

Setup:

```bash
sudo apt update
curl -fsSL https://ollama.com/install.sh | sh
pip install ollama
ollama pull gemma4
export OLLAMA_MODEL=gemma4
python main.py
```

`OLLAMA_MODEL` lets you switch models without editing Python code. If it is not
set, Agent Hart uses `gemma4`.

---

## Phase 14 — Local Web Dashboard

A minimal FastAPI dashboard at `dashboard.py` provides a browser UI over the same
SQLite memory layer used by the CLI and Telegram interfaces.

### Starting the dashboard

```bash
pip install fastapi uvicorn jinja2 python-multipart
python dashboard.py
# Open http://127.0.0.1:8765
```

Runs with hot-reload enabled in dev mode. One process, no external services needed.

### Views

| View | URL | Shows |
|------|-----|-------|
| Today | `/today` | Due-today tasks, overdue tasks, pending approvals summary, open runs, health badge, suggested next actions |
| Inbox | `/inbox` | Full pending approvals with approve/reject buttons, pending suggested actions, open runs, health warnings |
| Agents | `/agents` | Agent list with stats, goals, recent task runs, run reviews, add-agent and add-goal forms |
| Health | `/health` | Latest status badge, per-check table, history, run-health-check button |
| Memory | `/memory` | Notes, lessons, memory summaries, recent tool results with add forms |

### Actions available from the UI

- Add task (with due date and priority)
- Complete task
- Approve or reject a pending approval (goes through `decide_approval` — same path as CLI)
- Add note
- Add lesson
- Run health check (calls `build_health_checks` and saves result to SQLite)
- Create agent
- Add goal
- Create planning checkpoint (creates a `task_runs` record with `status=planning`)

### Safety guarantees

The dashboard does **not** bypass `policy.json` or the approval flow. Every approve
action calls `memory.decide_approval()` just as the CLI does. Tool execution still
requires CLI or Telegram interaction. The dashboard is read-and-plan only for agent
execution; no autonomous tool calls originate from it.

### Architecture

`dashboard.py` imports `build_daily_command_center`, `build_inbox`,
`build_health_checks`, and `overall_health_status` from `main.py` so there is one
source of truth for those data-assembly functions. Memory access uses
`create_memory_store(BASE_DIR)` — whichever backend is configured via
`AGENT_HART_MEMORY_BACKEND` works transparently.

Each request opens a fresh `SQLiteMemoryStore` context manager and closes it on
exit. No shared mutable state between requests.

### Tests

`tests/test_dashboard.py` — 24 tests covering all page routes, seeded-data
rendering, every action endpoint, and the `_complete_task_by_id` helper.
