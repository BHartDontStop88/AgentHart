# Agent Hart — Learning Notes

A living document of how this project was built, what decisions were made, and why. Written for my own learning and for anyone trying to understand the code.

---

## Architecture Overview

Agent Hart has four main pieces that all share one memory layer:

```
dashboard.py     ← FastAPI web UI
telegram_bot.py  ← Telegram interface
agents/          ← Autonomous background workers
main.py          ← Shared data builders and CLI helpers
        ↓
structured_memory.py  ← SQLite backend (default)
memory.py             ← JSON backend (legacy/backup)
memory_factory.py     ← picks which backend to use
```

The key design principle: **every interface talks to the same memory**. The dashboard, Telegram bot, and autonomous agents all read and write to `agent_hart.db`. That means a task added from Telegram immediately appears on the dashboard. An agent that records a metric immediately shows up in the metrics page.

---

## How Memory Works

### Two Backends

Agent Hart started with a JSON file (`memory.json`) because it's the simplest possible durable storage — you can open it in a text editor and see exactly what the agent knows.

Later we moved to SQLite (`agent_hart.db`) because:
- Multiple agents running in parallel can write without corrupting each other
- SQL queries let you filter, sort, and count without loading everything into memory
- WAL (Write-Ahead Log) mode lets the dashboard read while agents write

The backend is selected by `memory_factory.py` based on `AGENT_HART_MEMORY_BACKEND` in `.env`. Default is `sqlite`.

### Why WAL Mode Matters

Without WAL, if `proxmox_monitor` is writing a metric at the same moment you load the metrics page, SQLite throws a "database is locked" error. WAL mode allows one writer and many readers simultaneously — the dashboard stays fast even when five agents fire at once.

We enable it with one pragma in `__init__`:
```python
self.connection.execute("PRAGMA journal_mode=WAL")
```

### Schema Migrations

Old databases don't have new columns. If we just `ALTER TABLE tasks ADD COLUMN project`, it works on fresh databases but crashes on existing ones (column already exists).

The `_run_migrations()` method wraps every migration in try/except so it's idempotent — safe to run on any database, any number of times:

```python
migrations = [
    "ALTER TABLE tasks ADD COLUMN project text",
    "CREATE INDEX IF NOT EXISTS idx_audit_log_created ON audit_log(created_at)",
]
for sql in migrations:
    try:
        self.connection.execute(sql)
        self.connection.commit()
    except sqlite3.OperationalError:
        pass  # column or index already exists
```

---

## How Agents Work

### The AgentRun Context Manager

Every agent wraps its work in an `AgentRun` context manager from `agents/metrics.py`:

```python
with AgentRun("daily_briefing", memory) as run:
    briefing, meta = ollama_chat_with_meta(prompt)
    run.record_llm(meta)
    run.add_output(1)
```

On `__enter__`: takes a CPU/RAM snapshot, opens a metrics record in `agent_metrics` with status `running`.

On `__exit__`: calculates duration, writes final status (`success` or `error`), saves all token counts and timing.

This gives you a real audit trail: every agent run has a start time, end time, duration, token usage, and success/error status. The Metrics dashboard reads directly from this table.

### Why Agents Don't Share Memory Connections

Each agent creates its own memory connection and closes it when done:

```python
memory = create_memory_store(BASE_DIR)
# ... do work ...
memory.close()  # or use: with create_memory_store(BASE_DIR) as memory:
```

This matters because agents run in separate processes (systemd forks a new Python process for each timer). Sharing a single SQLite connection across processes would cause corruption. Each process opens, uses, and closes its own connection.

### Saving Content Before Calling Ollama

Workflow phase submissions (PM Lifecycle, Analytics, Agent Builder) used to call Ollama first and then save the result. Problem: if Ollama takes 90 seconds and the user's browser times out, their work is lost.

The fix: save the user's text to the database immediately, then call Ollama in a separate try/except, then update with the AI suggestion if it arrives:

```python
# 1. Save immediately (user's content is safe now)
memory.save_workflow_phase(session_id, phase_key, phase_order, user_content, None)

# 2. Call Ollama — if it fails or times out, content is already saved
try:
    suggestion = _phase_ai_prompt(...)
except Exception:
    suggestion = None

# 3. Update with suggestion if we got one
if suggestion:
    memory.save_workflow_phase(session_id, phase_key, phase_order, user_content, suggestion)
```

---

## How Telegram Works

### The Allowlist Pattern

Telegram bots are public by default — anyone who finds your bot can send it messages. We restrict this with an allowlist:

```python
TELEGRAM_ALLOWED_USER_IDS=8648851945
```

Every command handler starts with `await guard(update)` which checks the sender's numeric user ID against the allowlist. Unauthorized users get a single "Unauthorized Telegram user." reply and nothing else.

Important: the allowlist uses **numeric user IDs**, not usernames. Usernames can be changed. Numeric IDs never change. Find yours with `@userinfobot` on Telegram.

### The /agent vs /run Distinction

`/run <tool> <target>` is for approval-gated system tools (ping, nslookup, report). These go through the full policy check and approval flow.

`/agent <name>` is for triggering autonomous agents (daily_briefing, task_review, etc.). These are pre-approved — they're the same scripts that run on timers, just triggered on demand.

This distinction keeps the safety model clean: system tools need approval, agent scripts don't.

### The /project AI Breakdown

When you send `/project Fix authentication flow in the API`:

1. A structured JSON prompt goes to Gemma4 asking for phases and tasks
2. Gemma4 returns JSON like `{"project":"Fix auth flow","phases":[{"name":"Analysis","tasks":["Review current auth code","Map token flow"]}]}`
3. We parse the JSON and create one task per item, all tagged with `project=name`
4. The tasks show up immediately on the Projects page and in `/tasks`

If Gemma4 returns malformed JSON, the user gets a friendly error asking them to rephrase.

---

## How the Dashboard Works

### Request Flow

Every page route follows the same pattern:

```python
@app.get("/today", response_class=HTMLResponse)
async def today_view(request: Request):
    with _mem() as memory:          # open SQLite connection
        data = build_daily_command_center(memory)
        summaries = memory.list_memory_summaries()
    # connection is closed here, before template rendering
    return templates.TemplateResponse(
        request, "today.html",
        _ctx(request, "today", "Dashboard", **data),
    )
```

Key decisions:
- `_mem()` is a context manager — connection opens and closes within each request
- Template rendering happens after the connection closes (reduces lock time)
- `_ctx()` injects the active nav item and flash messages into every template

### Flash Messages

After a form POST, we redirect with a message:

```python
return _flash("/today", "Task added")        # green flash
return _flash("/today", "Task not found", "error")  # red flash
```

The flash is carried in the URL query string (`?msg=Task+added&type=ok`) and displayed by `base.html` on the next page load. This is the standard Post-Redirect-Get (PRG) pattern — prevents the browser from resubmitting the form on refresh.

### Security: Build Save Sandboxing

The Agent Builder lets users save CLAUDE.md files. The original code accepted any filesystem path from a form field — a path like `../../../../etc/cron.d/evil` would write outside the project directory.

The fix strips any directory component from the user-supplied filename and forces all writes to `BASE_DIR/exports/`:

```python
exports_dir = BASE_DIR / "exports"
safe_name = Path(file_path.strip()).name   # strips /../.. traversal
path = exports_dir / safe_name
```

---

## AI Integration

### ollama_chat_with_meta()

The core AI function returns both the response text and a metrics dict:

```python
response_text, meta = ollama_chat_with_meta(prompt)
# meta: {prompt_tokens, response_tokens, tokens_per_second,
#         model_load_ms, context_window_pct, total_duration_ms}
```

The token counts come directly from Ollama's response object:
- `prompt_eval_count` — tokens in the prompt
- `eval_count` — tokens generated
- `eval_duration` (nanoseconds) — generation time
- `load_duration` (nanoseconds) — model load time (near zero if warm)

This is how the Metrics page shows real TPS (tokens per second) — it's the model's actual generation speed, not an estimate.

### Timeout Strategy

Gemma4:e2b on CPU takes 60–120 seconds for a typical agent prompt. We set `OLLAMA_TIMEOUT_SECONDS=120` in `.env`. All workflow phase submissions wrap the Ollama call in try/except so a timeout doesn't lose the user's work.

### Prompt Philosophy

Every agent prompt ends with "plain text" or "no markdown" — this matters because Gemma4 loves to add markdown headers and bullet asterisks. For content going into Telegram or `<pre>` blocks, markdown formatting breaks the output. For reports rendered in the browser, we use `python-markdown` to properly render the output.

---

## Systemd Integration

### Service + Timer Pattern

Each agent needs two unit files:

**Service** (`agenthart-daily-briefing.service`) — describes what to run:
```ini
[Service]
Type=oneshot
User=bhart
WorkingDirectory=/home/bhart/AgentHart
ExecStart=/home/bhart/AgentHart/venv/bin/python agents/daily_briefing.py
```

**Timer** (`agenthart-daily-briefing.timer`) — describes when to run it:
```ini
[Timer]
OnCalendar=*-*-* 07:00:00
Persistent=true
```

`Persistent=true` is important: if the machine was off at 7am, it runs the briefing on the next boot rather than skipping it.

### Why Not Cron?

Systemd timers are better than cron for this project because:
- `journalctl -u agenthart-daily-briefing` shows all output from every run
- Failed runs are visible in `systemctl list-timers`
- `Persistent=true` handles missed runs automatically
- Each agent runs in an isolated process with clean environment

---

## GitHub Issues Integration

The `github_issues` agent uses Python's built-in `urllib.request` instead of the `requests` library — no extra dependency needed for a simple GET call.

Deduplication works by building a set of existing task texts before the import loop. If `[owner/repo#42] Fix login timeout` is already a task, it's skipped. This means you can run the agent multiple times without creating duplicates.

Label-to-priority mapping:
- Labels containing "critical", "urgent", "p0", "p1" → `high`
- Labels containing "low", "p3", "p4", "nice-to-have" → `low`
- Everything else → `normal`

---

## Common Patterns to Remember

**Adding a new agent:**
1. Create `agents/your_agent.py` with a `run()` function and `if __name__ == "__main__": run()`
2. Wrap the main work in `with AgentRun("your_agent", memory) as run:`
3. Add it to `RUNNABLE_AGENTS` in `dashboard.py` and `RUNNABLE_AGENTS` in `telegram_bot.py`
4. Add it to `WATCHDOG_WINDOWS` in `agents/agent_watchdog.py`
5. Add a service + timer unit to `scripts/install_timers.sh`

**Adding a new dashboard page:**
1. Add a GET route in `dashboard.py` returning `TemplateResponse`
2. Create `templates/your_page.html` extending `base.html`
3. Add a nav link in `templates/base.html`

**Adding a new Telegram command:**
1. Add an `async def your_command(update, context)` handler inside `main()`
2. Register it: `app.add_handler(CommandHandler("yourcommand", your_command))`
3. Add it to `telegram_help_text()`
4. Restart the Telegram bot service

---

## What I Learned Building This

**Start simple, migrate deliberately.** The project started as a JSON file. Adding SQLite mid-project taught me how to write idempotent migrations, how to handle schema evolution without breaking existing installs, and why WAL mode exists.

**Interfaces should be thin.** Telegram doesn't own the agent logic. The dashboard doesn't own the agent logic. They both call the same functions from `main.py` and `structured_memory.py`. This means adding a new interface (hypothetically: a CLI, a REST client, a webhook receiver) costs very little because the logic is already in one place.

**Observability before features.** The AgentRun metrics context manager was added early and now makes every agent's behavior inspectable from the dashboard. Without it, you'd have no idea if daily_briefing was running, how fast it was, or whether it was using 10% or 90% of the context window.

**Security is design, not afterthought.** The file write sandboxing, the Telegram allowlist, the `PRAGMA journal_mode=WAL`, the `no shell=True` subprocess calls — these weren't added as a security audit. They were designed in because I thought through what could go wrong at each decision point.
