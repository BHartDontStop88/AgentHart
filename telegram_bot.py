import os
import subprocess
from pathlib import Path

from ai import ask_ai, suggest_action
from memory_factory import create_memory_store
from main import (
    build_ai_context,
    build_brief,
    execute_approval,
    find_approval,
    format_task_line,
    normalize_suggested_due,
    normalize_suggested_priority,
)
from tools import PolicyError, ToolRegistry


def parse_allowed_user_ids(raw_value):
    """Parse TELEGRAM_ALLOWED_USER_IDS into a set of integer ids."""
    if not raw_value:
        return set()

    allowed = set()
    for item in raw_value.split(","):
        value = item.strip()
        if not value:
            continue
        try:
            allowed.add(int(value))
        except ValueError:
            raise ValueError(
                "TELEGRAM_ALLOWED_USER_IDS must be a comma-separated list of numbers."
            )
    return allowed


def is_authorized_user(user_id, allowed_user_ids, allow_all=False):
    """Return True only when this Telegram user may control the agent."""
    if allow_all:
        return True
    return user_id in allowed_user_ids


def build_runtime(base_dir=None):
    """Create the shared memory and tool registry used by Telegram handlers."""
    root = Path(base_dir or Path(__file__).resolve().parent)
    return {
        "base_dir": root,
        "memory": create_memory_store(root),
        "tools": ToolRegistry(root / "policy.json", root / "reports"),
    }


def queue_tool_request(rest, memory, tools):
    """
    Queue or execute a tool request from Telegram.

    Returns a small dict so Telegram handlers can decide how to present it.
    """
    tool_name, _, target = rest.partition(" ")
    tool_name = tool_name.strip().lower()
    target = target.strip()

    if not tool_name or not target:
        return {"status": "usage", "message": "Usage: /run <tool> <target>"}

    proposal = tools.request_proposal(tool_name, target)
    approval = memory.add_approval_request(
        proposal["action_type"],
        proposal["description"],
        proposal["payload"],
        risk_level=proposal["risk_level"],
        requires_approval=proposal["requires_approval"],
    )

    if proposal["requires_approval"]:
        return {
            "status": "pending",
            "approval": approval,
            "message": (
                f"Approval required: {approval['id'][:8]}\n"
                f"{approval['description']}\n"
                f"Risk: {approval['risk_level']}"
            ),
        }

    output = capture_execute_approval(approval, memory, tools)
    return {
        "status": "executed",
        "approval": approval,
        "message": output,
    }


def decide_approval_request(approval_id, approved, memory, tools):
    """Approve or reject a pending Telegram approval request."""
    approval = find_approval(memory, approval_id)
    if approval is None:
        return {"status": "missing", "message": f"No pending approval: {approval_id}"}

    if not approved:
        memory.decide_approval(approval["id"], False, reason="Rejected from Telegram.")
        return {
            "status": "rejected",
            "approval": approval,
            "message": f"Rejected approval {approval['id'][:8]}.",
        }

    memory.decide_approval(approval["id"], True, reason="Approved from Telegram.")
    output = capture_execute_approval(approval, memory, tools)
    return {
        "status": "executed",
        "approval": approval,
        "message": output,
    }


def capture_execute_approval(approval, memory, tools):
    """
    Execute a Phase 1 approval and return the newest tool output.

    execute_approval prints for the CLI, so Telegram reads the saved result.
    """
    before_count = len(memory.data["tool_results"])
    execute_approval(approval, memory, tools)
    if len(memory.data["tool_results"]) > before_count:
        return memory.data["tool_results"][-1]["output"]
    return "No tool output was recorded."


def format_brief(memory):
    """Return the daily brief as Telegram-friendly plain text."""
    brief = build_brief(memory)
    lines = ["Today's Briefing", ""]

    lines.append("Incomplete tasks:")
    if brief["incomplete_tasks"]:
        for index, task in brief["incomplete_tasks"]:
            lines.append(format_task_line(index, task))
    else:
        lines.append("No incomplete tasks.")

    lines.extend(["", "Tasks due today:"])
    if brief["due_today"]:
        for index, task in brief["due_today"]:
            lines.append(format_task_line(index, task))
    else:
        lines.append("No tasks due today.")

    lines.extend(["", "Recent tool results:"])
    if brief["recent_results"]:
        for result in brief["recent_results"]:
            lines.append(
                f"{result['created_at']} {result['tool']} "
                f"{result['status']}: {result['target']}"
            )
    else:
        lines.append("No tool results yet.")

    return "\n".join(lines)


def format_memory_stats(memory):
    stats = memory.memory_stats()
    return "\n".join(f"{key}: {stats[key]}" for key in sorted(stats))


def format_lessons(memory):
    lessons = memory.list_lessons()
    if not lessons:
        return "No lessons yet."
    return "\n".join(
        f"{index}. [{lesson['created_at']}] {lesson['text']}"
        for index, lesson in enumerate(lessons, 1)
    )


def format_tasks(memory):
    tasks = memory.list_tasks()
    if not tasks:
        return "No tasks yet."
    return "\n".join(format_task_line(index, task) for index, task in enumerate(tasks, 1))


def complete_task_request(task_number, memory):
    """Complete a task from Telegram's user-facing 1-based task number."""
    try:
        index = int(str(task_number).strip()) - 1
    except ValueError:
        return "Usage: /done <task-number>"

    if index < 0:
        return "Task number must be 1 or higher."

    if memory.complete_task(index):
        return f"Completed task {task_number}."
    return f"No task found at {task_number}."


def format_pending_approvals(memory):
    approvals = memory.list_approval_requests(status="pending")
    if not approvals:
        return "No pending approvals."

    lines = []
    for approval in approvals:
        lines.append(
            f"{approval['id'][:8]} [{approval['risk_level']}] "
            f"{approval['description']}"
        )
    return "\n".join(lines)


def format_tools(tools):
    lines = []
    for tool in tools.list_tools():
        policy = tools.get_policy_for_tool(tool.name)
        approval = "approval" if tools.requires_approval(tool.name) else "no approval"
        risk = policy.get("risk_level", "unknown")
        enabled = "enabled" if policy.get("enabled", False) else "disabled"
        lines.append(
            f"{tool.name}: {enabled}, risk={risk}, {approval} - {tool.description}"
        )
    return "\n".join(lines)


RUNNABLE_AGENTS = [
    "agent_watchdog", "daily_briefing", "disk_watchdog", "failed_login_watcher",
    "git_activity", "github_issues", "goal_tracker", "lesson_reviewer",
    "memory_digest", "note_organizer", "proxmox_monitor",
    "task_review", "todo_harvester", "weekly_review",
]

_BASE_DIR = Path(__file__).resolve().parent
_VENV_PYTHON = str(_BASE_DIR / "venv/bin/python")


def run_agent(agent_name: str) -> tuple[bool, str]:
    """Run an autonomous agent by name. Returns (success, output_or_error)."""
    if agent_name not in RUNNABLE_AGENTS:
        return False, f"Unknown agent '{agent_name}'. Try /agents to see available agents."
    script = str(_BASE_DIR / "agents" / f"{agent_name}.py")
    try:
        result = subprocess.run(
            [_VENV_PYTHON, script],
            capture_output=True, text=True, timeout=180,
            cwd=str(_BASE_DIR),
        )
        out = result.stdout.strip() or f"{agent_name} completed (no output)."
        if result.returncode == 0:
            return True, out
        stderr = (result.stderr or "").strip()[-300:]
        return False, f"Exit {result.returncode}:\n{stderr}"
    except subprocess.TimeoutExpired:
        return False, f"{agent_name} timed out after 3 minutes."
    except Exception as exc:
        return False, str(exc)


def telegram_help_text():
    return "\n".join(
        [
            "Agent Hart commands:",
            "",
            "Tasks & Notes:",
            "/addtask [high|low] <text>  — add a task directly",
            "/addnote <text>             — save a note",
            "/tasks                      — list open tasks",
            "/done <task-number>         — complete a task",
            "",
            "Projects:",
            "/project <name>             — AI breaks project into tasks",
            "/projects                   — show all project progress",
            "",
            "Autonomous Agents:",
            "/agents                     — list all runnable agents",
            "/agent <name>               — trigger an agent right now",
            "",
            "Learning:",
            "/study <topic>              — generate a quiz on any topic",
            "/quiz                       — quiz from your saved lessons",
            "/addlesson <text>           — save a lesson",
            "/lessons                    — list saved lessons",
            "",
            "AI & Memory:",
            "/chat <message>             — talk to Gemma4",
            "/brief                      — today's summary",
            "/memory                     — memory stats",
            "",
            "Tools (approval-gated):",
            "/tools                      — list available tools",
            "/run <tool> <target>        — run a tool",
            "/approvals                  — pending approvals",
            "/approve <id>               — approve an action",
            "/reject <id>                — reject an action",
        ]
    )


def telegram_safe_text(text, limit=3900):
    """Keep replies inside Telegram's message length limit."""
    text = str(text)
    if len(text) <= limit:
        return text
    return text[: limit - 40].rstrip() + "\n\n[Output truncated for Telegram.]"


def load_dotenv_if_available():
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv()


def main():
    """Start Agent Hart's Telegram interface."""
    load_dotenv_if_available()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN before starting telegram_bot.py.")

    allow_all = os.getenv("TELEGRAM_ALLOW_ALL", "").strip().lower() == "true"
    allowed_user_ids = parse_allowed_user_ids(os.getenv("TELEGRAM_ALLOWED_USER_IDS", ""))
    if not allow_all and not allowed_user_ids:
        raise SystemExit(
            "Set TELEGRAM_ALLOWED_USER_IDS to your Telegram numeric user id. "
            "For local experiments only, TELEGRAM_ALLOW_ALL=true bypasses this."
        )

    try:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
        from telegram.ext import (
            Application,
            CallbackQueryHandler,
            CommandHandler,
            ContextTypes,
            MessageHandler,
            filters,
        )
    except ImportError as exc:
        raise SystemExit(
            "Telegram dependency is not installed. Run: pip install python-telegram-bot"
        ) from exc

    runtime = build_runtime()

    def authorized(update):
        user = update.effective_user
        return bool(user) and is_authorized_user(
            user.id, allowed_user_ids, allow_all=allow_all
        )

    async def guard(update):
        if authorized(update):
            return True
        if update.effective_message:
            await update.effective_message.reply_text("Unauthorized Telegram user.")
        return False

    async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await guard(update):
            return
        await update.message.reply_text(telegram_help_text())

    async def brief_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await guard(update):
            return
        await update.message.reply_text(telegram_safe_text(format_brief(runtime["memory"])))

    async def tasks_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await guard(update):
            return
        await update.message.reply_text(telegram_safe_text(format_tasks(runtime["memory"])))

    async def done_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await guard(update):
            return
        if not context.args:
            await update.message.reply_text("Usage: /done <task-number>")
            return
        await update.message.reply_text(
            complete_task_request(context.args[0], runtime["memory"])
        )

    async def tools_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await guard(update):
            return
        await update.message.reply_text(telegram_safe_text(format_tools(runtime["tools"])))

    async def approvals_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await guard(update):
            return
        await update.message.reply_text(
            telegram_safe_text(format_pending_approvals(runtime["memory"]))
        )

    async def memory_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await guard(update):
            return
        await update.message.reply_text(
            telegram_safe_text(format_memory_stats(runtime["memory"]))
        )

    async def lessons_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await guard(update):
            return
        await update.message.reply_text(telegram_safe_text(format_lessons(runtime["memory"])))

    async def add_lesson_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await guard(update):
            return
        text = " ".join(context.args).strip()
        if not text:
            await update.message.reply_text("Usage: /addlesson <text>")
            return
        lesson = runtime["memory"].add_lesson(text, source="telegram")
        await update.message.reply_text(f"Saved lesson at {lesson['created_at']}.")

    async def run_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await guard(update):
            return
        rest = " ".join(context.args)
        try:
            result = queue_tool_request(rest, runtime["memory"], runtime["tools"])
        except PolicyError as exc:
            await update.message.reply_text(f"Policy blocked this action: {exc}")
            return

        if result["status"] == "pending":
            approval = result["approval"]
            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "Approve", callback_data=f"approve:{approval['id']}"
                        ),
                        InlineKeyboardButton(
                            "Reject", callback_data=f"reject:{approval['id']}"
                        ),
                    ]
                ]
            )
            await update.message.reply_text(result["message"], reply_markup=keyboard)
            return

        await update.message.reply_text(telegram_safe_text(result["message"]))

    async def approve_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await guard(update):
            return
        if not context.args:
            await update.message.reply_text("Usage: /approve <approval-id>")
            return
        result = decide_approval_request(
            context.args[0], True, runtime["memory"], runtime["tools"]
        )
        await update.message.reply_text(telegram_safe_text(result["message"]))

    async def reject_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await guard(update):
            return
        if not context.args:
            await update.message.reply_text("Usage: /reject <approval-id>")
            return
        result = decide_approval_request(
            context.args[0], False, runtime["memory"], runtime["tools"]
        )
        await update.message.reply_text(result["message"])

    async def addtask_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await guard(update):
            return
        if not context.args:
            await update.message.reply_text("Usage: /addtask [high|low] <task text>")
            return
        args = list(context.args)
        priority = "normal"
        if args[0].lower() in ("high", "low", "normal"):
            priority = args.pop(0).lower()
        text = " ".join(args).strip()
        if not text:
            await update.message.reply_text("Task text cannot be empty.")
            return
        task = runtime["memory"].add_task(text, priority=priority)
        runtime["memory"].add_audit_event("task_added", {"source": "telegram", "task": text})
        await update.message.reply_text(f"Task added: {text}")

    async def addnote_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await guard(update):
            return
        text = " ".join(context.args).strip()
        if not text:
            await update.message.reply_text("Usage: /addnote <text>")
            return
        runtime["memory"].add_note(text)
        await update.message.reply_text(f"Note saved.")

    async def project_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await guard(update):
            return
        name = " ".join(context.args).strip()
        if not name:
            await update.message.reply_text("Usage: /project <project name or description>")
            return
        await update.message.reply_text(f"Breaking down project: {name}...\n(Gemma4 is thinking)")
        from ai import ollama_chat, extract_json_object
        import json
        prompt = (
            f"Break this project into phases and tasks. Project: {name}\n\n"
            "Return ONLY valid JSON in this exact format, no other text:\n"
            '{"project":"<name>","phases":[{"name":"<phase>","tasks":["<task>","<task>"]}]}\n\n'
            "Use 2-4 phases. Each phase should have 2-4 specific actionable tasks.\n"
            "Keep task text under 60 characters."
        )
        raw = ollama_chat(prompt)
        try:
            data = json.loads(extract_json_object(raw))
            phases = data.get("phases", [])
            project_name = data.get("project", name)
        except (json.JSONDecodeError, AttributeError):
            await update.message.reply_text(
                "Gemma4 returned an unexpected format. Try rephrasing the project name."
            )
            return

        memory = runtime["memory"]
        lines = [f"Project: {project_name}", ""]
        total = 0
        for phase in phases:
            phase_name = phase.get("name", "")
            lines.append(f"[{phase_name}]")
            for task_text in phase.get("tasks", []):
                full_text = f"[{phase_name}] {task_text}"
                memory.add_task(full_text, priority="normal", project=project_name)
                lines.append(f"  + {task_text}")
                total += 1
        lines.append(f"\n{total} tasks created. View on dashboard or /tasks")
        memory.add_memory_summary(scope="project_created", summary=f"Project: {project_name}\n" + "\n".join(lines))
        memory.add_audit_event("project_created", {"name": project_name, "tasks": total})
        await update.message.reply_text("\n".join(lines))

    async def projects_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await guard(update):
            return
        tasks = runtime["memory"].list_tasks()
        projects: dict[str, dict] = {}
        for t in tasks:
            p = t.get("project") or "General"
            if p not in projects:
                projects[p] = {"total": 0, "done": 0}
            projects[p]["total"] += 1
            if t.get("completed"):
                projects[p]["done"] += 1
        if not projects:
            await update.message.reply_text("No projects yet. Use /project <name> to create one.")
            return
        lines = ["Projects:"]
        for p, stats in projects.items():
            pct = int(100 * stats["done"] / stats["total"]) if stats["total"] else 0
            lines.append(f"• {p}: {stats['done']}/{stats['total']} tasks ({pct}%)")
        await update.message.reply_text("\n".join(lines))

    async def study_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await guard(update):
            return
        topic = " ".join(context.args).strip()
        if not topic:
            await update.message.reply_text("Usage: /study <topic>\nExample: /study Python decorators")
            return
        await update.message.reply_text(f"Generating quiz on: {topic}...")
        from ai import ollama_chat
        quiz = ollama_chat(
            f"You are a study coach. Create 4 quiz questions about: {topic}\n"
            "Format:\nQ1: <question>\nQ2: <question>\nQ3: <question>\nQ4: <question>\n\n"
            "ANSWERS:\nA1: <answer>\nA2: <answer>\nA3: <answer>\nA4: <answer>\n"
            "Keep questions practical and specific."
        )
        runtime["memory"].add_memory_summary(scope="study_quiz", summary=f"Topic: {topic}\n{quiz}")
        await update.message.reply_text(telegram_safe_text(quiz))

    async def quiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await guard(update):
            return
        lessons = runtime["memory"].list_lessons()
        if not lessons:
            await update.message.reply_text("No lessons saved yet. Use /addlesson to save lessons.")
            return
        await update.message.reply_text("Generating quiz from your saved lessons...")
        from ai import ollama_chat
        batch = lessons[:5]
        lessons_block = "\n".join(f"[{i+1}] {l.get('text','')}" for i, l in enumerate(batch))
        quiz = ollama_chat(
            "Create 3 quiz questions from these lessons:\n\n"
            f"{lessons_block}\n\n"
            "Format:\nQ1: <question>\nQ2: <question>\nQ3: <question>\n\n"
            "ANSWERS:\nA1: <answer>\nA2: <answer>\nA3: <answer>"
        )
        await update.message.reply_text(telegram_safe_text(quiz))

    async def agents_list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await guard(update):
            return
        lines = ["Available agents (use /agent <name> to trigger):"]
        for name in RUNNABLE_AGENTS:
            lines.append(f"  • {name}")
        await update.message.reply_text("\n".join(lines))

    async def agent_run_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await guard(update):
            return
        name = " ".join(context.args).strip().lower()
        if not name:
            await update.message.reply_text("Usage: /agent <name>\nSee /agents for the list.")
            return
        await update.message.reply_text(f"Running {name}... (may take up to 3 min)")
        ok, output = run_agent(name)
        prefix = f"[{name}] " + ("Done" if ok else "FAILED")
        await update.message.reply_text(telegram_safe_text(f"{prefix}\n\n{output}"))

    async def chat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await guard(update):
            return
        message = " ".join(context.args).strip()
        if not message:
            await update.message.reply_text("Usage: /chat <message>")
            return

        memory = runtime["memory"]
        memory.add_chat("user", message)
        response = ask_ai(message, context=build_ai_context(memory))
        memory.add_chat("assistant", response)
        await update.message.reply_text(telegram_safe_text(response))

        suggestion = suggest_action(message, context=build_ai_context(memory))
        if suggestion.get("action") == "add_task":
            approval = memory.add_approval_request(
                "add_task",
                f"Add task: {suggestion.get('text', '')}",
                {
                    "action": "add_task",
                    "text": str(suggestion.get("text", "")).strip(),
                    "due": normalize_suggested_due(suggestion.get("due")),
                    "priority": normalize_suggested_priority(
                        suggestion.get("priority")
                    ),
                },
                risk_level="low",
                requires_approval=True,
            )
            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "Approve", callback_data=f"task_approve:{approval['id']}"
                        ),
                        InlineKeyboardButton(
                            "Reject", callback_data=f"task_reject:{approval['id']}"
                        ),
                    ]
                ]
            )
            await update.message.reply_text(
                f"Suggested task approval: {approval['id'][:8]}",
                reply_markup=keyboard,
            )

    async def text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await guard(update):
            return
        message = update.message.text.strip()
        if not message:
            return

        memory = runtime["memory"]
        memory.add_chat("user", message)
        response = ask_ai(message, context=build_ai_context(memory))
        memory.add_chat("assistant", response)
        await update.message.reply_text(telegram_safe_text(response))

    async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if not await guard(update):
            return
        await query.answer()

        action, _, approval_id = query.data.partition(":")
        if action in {"approve", "reject"}:
            result = decide_approval_request(
                approval_id,
                action == "approve",
                runtime["memory"],
                runtime["tools"],
            )
            await query.edit_message_text(telegram_safe_text(result["message"]))
            return

        if action in {"task_approve", "task_reject"}:
            approval = find_approval(runtime["memory"], approval_id)
            if approval is None:
                await query.edit_message_text(f"No pending approval: {approval_id[:8]}")
                return
            if action == "task_reject":
                runtime["memory"].decide_approval(
                    approval["id"], False, reason="Rejected from Telegram."
                )
                await query.edit_message_text(f"Rejected approval {approval['id'][:8]}.")
                return

            payload = approval.get("payload", {})
            task = runtime["memory"].add_task(
                str(payload.get("text", "")).strip(),
                due_date=payload.get("due"),
                priority=payload.get("priority", "normal"),
            )
            runtime["memory"].decide_approval(
                approval["id"], True, reason="Approved from Telegram."
            )
            runtime["memory"].mark_approval_executed(approval["id"], "ok")
            await query.edit_message_text(f"Added task: {task['text']}")

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler(["start", "help"], help_command))
    app.add_handler(CommandHandler("brief", brief_command))
    app.add_handler(CommandHandler("tasks", tasks_command))
    app.add_handler(CommandHandler("done", done_command))
    app.add_handler(CommandHandler("tools", tools_command))
    app.add_handler(CommandHandler("memory", memory_command))
    app.add_handler(CommandHandler("lessons", lessons_command))
    app.add_handler(CommandHandler("addlesson", add_lesson_command))
    app.add_handler(CommandHandler("approvals", approvals_command))
    app.add_handler(CommandHandler("run", run_command))
    app.add_handler(CommandHandler("approve", approve_command))
    app.add_handler(CommandHandler("reject", reject_command))
    app.add_handler(CommandHandler("chat", chat_command))
    app.add_handler(CommandHandler("addtask", addtask_command))
    app.add_handler(CommandHandler("addnote", addnote_command))
    app.add_handler(CommandHandler("project", project_command))
    app.add_handler(CommandHandler("projects", projects_command))
    app.add_handler(CommandHandler("study", study_command))
    app.add_handler(CommandHandler("quiz", quiz_command))
    app.add_handler(CommandHandler("agents", agents_list_command))
    app.add_handler(CommandHandler("agent", agent_run_command))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message))

    print("Agent Hart Telegram bot started.")
    app.run_polling()


if __name__ == "__main__":
    main()
