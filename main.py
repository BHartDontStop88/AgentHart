import shutil
import shlex
from datetime import date, datetime, timedelta
from pathlib import Path

from ai import (
    ask_ai,
    extract_json_object,
    ollama_chat,
    ollama_health_check,
    plan_goal,
    suggest_action,
)
from memory_factory import create_memory_store
from tools import PolicyError, ToolRegistry


APP_NAME = "Agent Hart"


def main():
    """
    The CLI is the outer shell of the agent.

    Think of this file as the "conversation controller":
    1. It waits for a command from the human.
    2. It decides which handler function should receive that command.
    3. It asks memory.py to save or load information.
    4. It asks tools.py to run approved tools.

    Keeping this file focused on input/output makes the project easier to grow.
    Later, an API model or web dashboard can call the same memory and tool layers
    without rewriting the core behavior.
    """
    base_dir = Path(__file__).resolve().parent

    # These two objects are the agent's main building blocks:
    # - MemoryStore owns durable memory for notes, chats, and tool results.
    # - ToolRegistry owns the available tools and checks policy before execution.
    memory = create_memory_store(base_dir)
    tools = ToolRegistry(base_dir / "policy.json", base_dir / "reports")

    print(f"{APP_NAME} v1")
    print("Type 'help' to see commands.")
    check_due_reminders(memory)

    while True:
        try:
            raw = input("\nagent-hart> ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye.")
            break

        if not raw:
            continue

        # partition(" ") splits once:
        #   "add note hello" -> command="add", rest="note hello"
        # This is friendlier than split() because the rest of the user text keeps
        # its spaces instead of being chopped into many pieces.
        command, _, rest = raw.partition(" ")
        command = command.lower()
        rest = rest.strip()

        if command in {"exit", "quit"}:
            print("Goodbye.")
            break
        if command == "help":
            print_help(tools)
        elif command == "chat":
            handle_chat(rest, memory)
        elif command == "brief" and rest == "report":
            handle_brief_report(memory, base_dir / "reports")
        elif command == "brief":
            handle_brief(memory)
        elif command == "search":
            handle_search(rest, memory)
        elif command == "actions":
            handle_list_actions(memory)
        elif command == "inbox":
            handle_inbox(memory)
        elif command == "memory" and rest == "stats":
            handle_memory_stats(memory)
        elif command == "memory" and rest == "summaries":
            handle_list_memory_summaries(memory)
        elif command == "review" and rest == "memory":
            handle_review_memory(memory)
        elif command == "health" and rest == "check":
            handle_health_check(memory, tools, base_dir)
        elif command == "health" and rest == "report":
            handle_health_report(memory)
        elif command == "health" and rest == "history":
            handle_health_history(memory)
        elif command == "run" and rest.startswith("review "):
            handle_run_review(rest.removeprefix("review ").strip(), memory)
        elif command == "ollama" and rest == "health":
            handle_ollama_health()
        elif command == "agent" and rest == "status":
            handle_agent_status(memory)
        elif command == "agent" and rest.startswith("check-tool "):
            handle_agent_check_tool(rest.removeprefix("check-tool ").strip(), memory, tools)
        elif command == "plan-agent":
            handle_plan_agent(rest, memory, tools)
        elif command == "run-agent":
            handle_run_agent_placeholder(rest, memory)
        elif command == "stop-agent":
            handle_stop_agent_placeholder(rest, memory)
        elif command == "add" and rest.startswith("lesson "):
            handle_add_lesson(rest.removeprefix("lesson ").strip(), memory)
        elif command == "add" and rest.startswith("agent "):
            handle_add_agent(rest.removeprefix("agent ").strip(), memory)
        elif command == "add" and rest.startswith("goal "):
            handle_add_goal(rest.removeprefix("goal ").strip(), memory)
        elif command == "list" and rest == "lessons":
            handle_list_lessons(memory)
        elif command == "list" and rest == "agents":
            handle_list_agents(memory)
        elif command == "list" and rest == "goals":
            handle_list_goals(memory)
        elif command == "approvals":
            handle_list_approvals(memory)
        elif command == "approve":
            handle_approval_decision(rest, True, memory, tools)
        elif command == "reject":
            handle_approval_decision(rest, False, memory, tools)
        elif command == "plan":
            handle_plan(rest, memory)
        elif command == "remind" and rest.startswith("me in "):
            handle_add_reminder(rest, memory)
        elif command == "reminders":
            handle_list_reminders(memory)
        elif command == "add" and rest.startswith("note "):
            handle_add_note(rest.removeprefix("note ").strip(), memory)
        elif command == "add" and rest.startswith("task "):
            handle_add_task(rest.removeprefix("task ").strip(), memory)
        elif command == "list" and rest == "notes":
            handle_list_notes(memory)
        elif command == "list" and rest == "tasks":
            handle_list_tasks(memory)
        elif command == "list" and rest == "today":
            handle_today(memory)
        elif command == "today":
            handle_today(memory)
        elif command == "complete" and rest.startswith("task "):
            handle_complete_task(rest.removeprefix("task ").strip(), memory)
        elif command == "undo" and rest.startswith("action "):
            handle_undo_action(rest.removeprefix("action ").strip(), memory)
        elif command == "backup" and rest == "memory":
            handle_backup_memory(base_dir / "memory.json", base_dir / "backups")
        elif command == "restore" and rest.startswith("memory "):
            restored = handle_restore_memory(
                rest.removeprefix("memory ").strip(),
                base_dir / "memory.json",
                base_dir / "backups",
            )
            if restored:
                memory = create_memory_store(base_dir)
        elif command == "tools":
            print_tools(tools)
        elif command == "run":
            handle_run(rest, memory, tools)
        elif command == "report":
            handle_run(f"report {rest}", memory, tools)
        else:
            print("Unknown command. Type 'help' for options.")


def print_help(tools):
    """Show the user-facing command menu."""
    print(
        """
Commands:
  help                         Show this help menu
  chat <message>               Save a chat message and get a simple response
  brief                        Show today's briefing
  brief report                 Save today's briefing to reports/
  search <keyword>             Search memory
  actions                      Show action history
  inbox                        Show approvals, suggested actions, and warnings
  memory stats                 Show structured memory counts
  memory summaries             Show saved memory summaries
  review memory                Draft and save a memory review after approval
  health check                 Run and save system health checks
  health report                Show latest saved health report
  health history               Show saved health check history
  run review <run> <outcome> <summary>       Save a run outcome review
  ollama health                Check configured Ollama connection and model
  agent status                 Show automation runtime status
  agent check-tool <agent> <tool> <target>   Dry-run agent tool permission
  plan-agent <agent> <goal>    Create one supervised planner checkpoint
  run-agent <agent>            Reserved for explicit automation execution
  stop-agent <run-id>          Reserved for stopping automation runs
  approvals                    Show pending approval requests
  approve <approval-id>        Approve and run a pending tool request
  reject <approval-id>         Reject a pending approval request
  plan <goal>                  Create a plan and suggest tasks
  remind me in <minutes> minutes to <text>   Add a reminder
  reminders                                  Show reminders
  add note <text>              Save a note to memory.json
  add lesson <text>            Save a long-term lesson
  add agent <name>             Add an automation agent profile
  add goal <agent> <text>      Add a goal for an agent number or id
  add task <text>              Add a task
  list notes                   Show saved notes
  list lessons                 Show saved lessons
  list agents                  Show automation agent profiles
  list goals                   Show automation goals
  list tasks                   Show all tasks
  list today                   Show incomplete tasks due today
  today                        Show incomplete tasks due today
  complete task <number>       Mark a task as complete
  undo action <number>         Undo an approved action
  backup memory                Back up memory.json
  restore memory <filename>    Restore memory from backup
  tools                        List available tools
  run <tool> <target>          Run a registered tool with approval when needed
  report <title>               Generate a markdown report
  exit                         Quit Agent Hart

Task options:
  --due YYYY-MM-DD             Add a due date
  --due today                  Due today
  --priority low|normal|high   Add a priority label

Agent options:
  --role <text>                Describe the agent role
  --tools ping,report          Limit allowed tools
  --max-steps <number>         Set a step budget
  --autonomy supervised        Set autonomy label

Ollama environment:
  OLLAMA_BASE_URL              Default: http://localhost:11434
  OLLAMA_MODEL                 Default: gemma4
  OLLAMA_TIMEOUT_SECONDS       Default: 60
  OLLAMA_NUM_CTX               Default: 4096
  OLLAMA_TEMPERATURE           Default: 0.2
""".strip()
    )
    print("\nAvailable tools:")
    print_tools(tools)


def print_tools(tools):
    """
    Print the tool registry with policy details.

    This is intentionally transparent. A safe agent should be able to explain
    what it can do, whether each action is enabled, and when approval is needed.
    """
    for tool in tools.list_tools():
        policy = tools.get_policy_for_tool(tool.name)
        approval = "approval" if tools.requires_approval(tool.name) else "no approval"
        risk = policy.get("risk_level", "unknown")
        enabled = "enabled" if policy.get("enabled", False) else "disabled"
        print(f"  {tool.name:8} {enabled:8} risk={risk:7} {approval} - {tool.description}")


def handle_chat(message, memory):
    """
    Save a chat message.

    Chat is intentionally conversational. Automation and memory-changing actions
    live behind explicit commands so a casual message cannot start a run.
    """
    if not message:
        print("Usage: chat <message>")
        return

    memory.add_chat("user", message)
    context = build_ai_context(memory)
    response = ask_ai(message, context=context)
    memory.add_chat("assistant", response)
    print(response)

    suggestion = suggest_action(message, context=context)
    handle_suggested_action(suggestion, memory)


def handle_add_note(text, memory):
    """Save a human-written note to memory.json."""
    if not text:
        print("Usage: add note <text>")
        return
    note = memory.add_note(text)
    print(f"Saved note at {note['created_at']}.")


def handle_list_notes(memory):
    """Read notes from memory.json and print them in order."""
    notes = memory.list_notes()
    if not notes:
        print("No notes yet.")
        return
    for index, note in enumerate(notes, start=1):
        print(f"{index}. [{note['created_at']}] {note['text']}")


def handle_add_task(text, memory):
    """Save a task to memory.json."""
    if not text:
        print("Usage: add task <text> [--due YYYY-MM-DD|today] [--priority low|normal|high]")
        return

    try:
        task_text, due_date, priority = parse_task_input(text)
    except ValueError as exc:
        print(exc)
        return

    if not task_text:
        print("Usage: add task <text> [--due YYYY-MM-DD|today] [--priority low|normal|high]")
        return

    task = memory.add_task(task_text, due_date=due_date, priority=priority)
    details = format_task_details(task)
    print(f"Saved task at {task['created_at']}{details}.")


def handle_list_tasks(memory):
    """Read tasks from memory.json and print them in order."""
    tasks = memory.list_tasks()
    if not tasks:
        print("No tasks yet.")
        return
    for index, task in enumerate(tasks, start=1):
        print(format_task_line(index, task))


def handle_add_reminder(rest, memory):
    """Parse 'remind me in X minutes to Y' and save a reminder."""
    try:
        minutes, reminder_text = parse_reminder_command(rest)
    except ValueError as exc:
        print(exc)
        return

    # Reminders are checked when Agent Hart starts, not in the background yet.
    due_at = (datetime.now() + timedelta(minutes=minutes)).isoformat(timespec="seconds")
    reminder = memory.add_reminder(reminder_text, due_at)
    print(f"Reminder saved for {reminder['due_at']}: {reminder['text']}")


def handle_list_reminders(memory):
    """Show all reminders with their due time and completion status."""
    reminders = memory.list_reminders()
    if not reminders:
        print("No reminders yet.")
        return

    for index, reminder in enumerate(reminders):
        status = "completed" if reminder["completed"] else "pending"
        print(
            f"{index}. [{status}] due {reminder['due_at']} - "
            f"{reminder['text']}"
        )


def check_due_reminders(memory):
    """Print reminders that are due when the app starts."""
    due = memory.due_reminders()
    if not due:
        return

    print("\nDue reminders:")
    for index, reminder in due:
        print(f"{index}. {reminder['text']} (due {reminder['due_at']})")


def parse_reminder_command(rest):
    """Return minutes and text from 'me in X minutes to Y'."""
    parts = rest.split(" ", 4)
    if len(parts) < 5 or parts[0] != "me" or parts[1] != "in":
        raise ValueError("Usage: remind me in <minutes> minutes to <text>")

    try:
        minutes = int(parts[2])
    except ValueError as exc:
        raise ValueError("Reminder minutes must be a whole number.") from exc

    if minutes < 0:
        raise ValueError("Reminder minutes must be 0 or higher.")
    if parts[3] != "minutes" or not parts[4].startswith("to "):
        raise ValueError("Usage: remind me in <minutes> minutes to <text>")

    reminder_text = parts[4].removeprefix("to ").strip()
    if not reminder_text:
        raise ValueError("Usage: remind me in <minutes> minutes to <text>")

    return minutes, reminder_text


def handle_today(memory):
    """Show a daily command center for the current state of the assistant."""
    command_center = build_daily_command_center(memory)
    print(f"Today ({date.today().isoformat()})")

    print("\nDue today:")
    print_numbered_task_group(command_center["due_today"])

    print("\nOverdue:")
    print_numbered_task_group(command_center["overdue"])

    print("\nPending approvals:")
    if command_center["pending_approvals"]:
        for approval in command_center["pending_approvals"]:
            print(
                f"- {approval['id'][:8]} [{approval['risk_level']}] "
                f"{approval['description']}"
            )
    else:
        print("- None.")

    print("\nOpen agent runs:")
    if command_center["open_runs"]:
        for run in command_center["open_runs"]:
            print(f"- {run['id'][:8]} [{run['status']}] agent={run.get('agent_id')}")
    else:
        print("- None.")

    print("\nLatest health:")
    if command_center["latest_health"]:
        health = command_center["latest_health"]
        print(f"- {health['overall_status']} at {health['created_at']}")
    else:
        print("- No health checks yet.")

    print("\nSuggested next actions:")
    for action in command_center["suggested_actions"]:
        print(f"- {action}")


def print_numbered_task_group(items):
    if not items:
        print("- None.")
        return
    for index, task in items:
        print(format_task_line(index, task))


def handle_brief(memory):
    """Print a simple daily briefing from saved memory."""
    print("Today's Briefing")

    brief = build_brief(memory)

    # Show every unfinished task so the user can see the full open list.
    print("\nIncomplete tasks:")
    if brief["incomplete_tasks"]:
        for index, task in brief["incomplete_tasks"]:
            print(format_task_line(index, task))
    else:
        print("No incomplete tasks.")

    # Due dates already exist in the task system, so reuse the today helper.
    print("\nTasks due today:")
    if brief["due_today"]:
        for index, task in brief["due_today"]:
            print(format_task_line(index, task))
    else:
        print("No tasks due today.")

    # Keep the briefing short by showing only the newest three notes.
    print("\nRecent notes:")
    if brief["recent_notes"]:
        for note in brief["recent_notes"]:
            print(f"- [{note['created_at']}] {note['text']}")
    else:
        print("No notes yet.")

    # Tool results are the agent's recent action log, newest three only.
    print("\nRecent tool results:")
    if brief["recent_results"]:
        for result in brief["recent_results"]:
            print(
                f"- [{result['created_at']}] {result['tool']} "
                f"{result['status']}: {result['target']}"
            )
    else:
        print("No tool results yet.")


def handle_brief_report(memory, reports_dir):
    """Save the daily briefing as a markdown file in reports/."""
    reports_dir.mkdir(exist_ok=True)
    today = date.today().isoformat()
    report_path = reports_dir / f"daily-briefing-{today}.md"

    # Build the markdown from the same memory sections used by the screen brief.
    report_path.write_text(build_brief_markdown(memory), encoding="utf-8")
    print(f"Briefing report saved: {report_path}")


def handle_backup_memory(memory_path, backups_dir):
    """Copy memory.json to backups/ so experiments can be reversed safely."""
    if not memory_path.exists():
        print("memory.json does not exist yet.")
        return None

    backups_dir.mkdir(exist_ok=True)
    timestamp_text = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    backup_path = backups_dir / f"memory-backup-{timestamp_text}.json"

    # copy2 keeps file metadata and makes a plain JSON backup you can inspect.
    shutil.copy2(memory_path, backup_path)
    print(f"Memory backup saved: {backup_path.name}")
    return backup_path


def handle_restore_memory(backup_filename, memory_path, backups_dir):
    """Restore memory.json from a named file in backups/."""
    if not backup_filename:
        print("Usage: restore memory <backup_filename>")
        return False

    # Only accept a filename, not a path, so restore stays inside backups/.
    backup_name = Path(backup_filename).name
    backup_path = backups_dir / backup_name

    if backup_name != backup_filename:
        print("Use only the backup filename, not a full path.")
        return False
    if not backup_path.exists():
        print(f"Backup not found: {backup_name}")
        return False

    # Restoring replaces memory.json with the selected backup copy.
    shutil.copy2(backup_path, memory_path)
    print(f"Memory restored from backup: {backup_name}")
    return True


def handle_plan(goal, memory):
    """Create an AI plan and optionally save each step as a task."""
    if not goal:
        print("Usage: plan <goal>")
        return

    # Memory context helps the plan fit current tasks, notes, and activity.
    context = build_ai_context(memory)
    plan = plan_goal(goal, context=context)

    print("Plan:")
    print(plan)

    steps = extract_plan_steps(plan)
    if not steps:
        print("No task-like steps found in the plan.")
        return

    answer = input("Would you like to add these as tasks? yes/no ").strip().lower()
    if answer != "yes":
        print("Plan tasks not added.")
        return

    # Keep this beginner-friendly: each non-empty plan line becomes one task.
    for step in steps:
        memory.add_task(step)
    print(f"Added {len(steps)} tasks from the plan.")


def handle_review_memory(memory):
    """Draft a memory review and save it as a summary after confirmation."""
    context = build_ai_context(memory)
    prompt = (
        "Review Agent Hart's recent memory.\n"
        "Summarize the important tasks, notes, tool results, lessons, and prior "
        "summaries.\n"
        "Keep it concise, factual, and useful for future context.\n"
        "Return plain text only."
    )
    review = ask_ai(prompt, context=context).strip()

    if not review:
        print("No memory review was generated.")
        return

    print("Memory review draft:")
    print(review)

    answer = input("Save this memory review? yes/no ").strip().lower()
    if answer != "yes":
        print("Memory review not saved.")
        return

    record = memory.add_memory_summary("memory_review", review)
    print(f"Saved memory review at {record['created_at']}.")


def handle_ollama_health():
    """Print the configured Ollama connection and model health."""
    result = ollama_health_check()
    status = "ok" if result["ok"] else "error"
    print(f"Ollama health: {status}")
    print(f"Base URL: {result['base_url']}")
    print(f"Model: {result['model']}")
    print(f"Timeout: {result['timeout_seconds']}s")
    print(f"Context window: {result['num_ctx']}")
    print(f"Temperature: {result['temperature']}")
    print(f"Message: {result['message']}")


def handle_health_check(memory, tools, base_dir):
    """Run local health checks and save the result."""
    checks = build_health_checks(memory, tools, base_dir)
    overall = overall_health_status(checks)
    record = memory.add_health_check(overall, checks)
    print_health_record(record)


def handle_health_report(memory):
    checks = memory.list_health_checks()
    if not checks:
        print("No health checks saved yet.")
        return
    print_health_record(checks[-1])


def handle_health_history(memory):
    checks = memory.list_health_checks()
    if not checks:
        print("No health checks saved yet.")
        return
    for index, check in enumerate(checks, start=1):
        print(f"{index}. [{check['created_at']}] {check['overall_status']}")


def build_health_checks(memory, tools, base_dir):
    """Collect health signals without changing anything except the saved report."""
    checks = []
    stats = memory.memory_stats()
    checks.append({"name": "memory_stats", "status": "ok", "detail": str(stats)})

    try:
        memory.save()
        checks.append({"name": "memory_writable", "status": "ok", "detail": "Memory saved."})
    except Exception as exc:
        checks.append({"name": "memory_writable", "status": "fail", "detail": str(exc)})

    policy_path = base_dir / "policy.json"
    if policy_path.exists():
        checks.append({"name": "policy_file", "status": "ok", "detail": str(policy_path)})
    else:
        checks.append({"name": "policy_file", "status": "fail", "detail": str(policy_path)})

    enabled_tools = [tool.name for tool in tools.list_tools() if tools.is_enabled(tool.name)]
    if enabled_tools:
        checks.append(
            {
                "name": "tools_registered",
                "status": "ok",
                "detail": ", ".join(enabled_tools),
            }
        )
    else:
        checks.append({"name": "tools_registered", "status": "fail", "detail": "none"})

    reports_dir = base_dir / "reports"
    try:
        reports_dir.mkdir(parents=True, exist_ok=True)
        probe = reports_dir / ".healthcheck"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        checks.append({"name": "reports_writable", "status": "ok", "detail": str(reports_dir)})
    except Exception as exc:
        checks.append({"name": "reports_writable", "status": "fail", "detail": str(exc)})

    ollama = ollama_health_check()
    checks.append(
        {
            "name": "ollama",
            "status": "ok" if ollama["ok"] else "warn",
            "detail": ollama["message"],
        }
    )

    pending_approvals = memory.list_approval_requests(status="pending")
    checks.append(
        {
            "name": "pending_approvals",
            "status": "warn" if pending_approvals else "ok",
            "detail": str(len(pending_approvals)),
        }
    )

    stuck_runs = [
        run
        for run in memory.list_task_runs()
        if run.get("status") in {"planning", "running", "waiting_for_review"}
    ]
    checks.append(
        {
            "name": "open_task_runs",
            "status": "warn" if stuck_runs else "ok",
            "detail": str(len(stuck_runs)),
        }
    )
    return checks


def overall_health_status(checks):
    statuses = {check["status"] for check in checks}
    if "fail" in statuses:
        return "fail"
    if "warn" in statuses:
        return "degraded"
    return "ok"


def print_health_record(record):
    print(f"Agent Hart Health: {record['overall_status']}")
    print(f"Created: {record['created_at']}")
    for check in record["checks"]:
        print(f"{check['status'].upper():5} {check['name']}: {check['detail']}")


def handle_run_review(rest, memory):
    """Save a learning review for a task run outcome."""
    run_ref, _, review_text = rest.partition(" ")
    outcome, _, summary = review_text.partition(" ")
    run_ref = run_ref.strip()
    outcome = outcome.strip()
    summary = summary.strip()
    allowed_outcomes = {
        "success",
        "partial_success",
        "blocked_by_policy",
        "failed_tool",
        "bad_plan",
        "user_rejected",
    }

    if not run_ref or not outcome or not summary:
        print("Usage: run review <run-number-or-id> <outcome> <summary>")
        return
    if outcome not in allowed_outcomes:
        print(
            "Outcome must be one of: "
            + ", ".join(sorted(allowed_outcomes))
        )
        return

    run = find_task_run(memory, run_ref)
    if run is None:
        print(f"No task run found for {run_ref}.")
        return

    review = memory.add_run_review(
        run["id"],
        run.get("agent_id"),
        outcome,
        summary,
        details={"run_status": run.get("status"), "goal_id": run.get("goal_id")},
    )
    print(f"Saved run review {review['id'][:8]} with outcome {outcome}.")


def handle_inbox(memory):
    """Show items that need human attention."""
    inbox = build_inbox(memory)
    print("Inbox")

    print("\nPending approvals:")
    if inbox["pending_approvals"]:
        for approval in inbox["pending_approvals"]:
            print(
                f"- {approval['id'][:8]} [{approval['risk_level']}] "
                f"{approval['description']}"
            )
    else:
        print("- None.")

    print("\nPending suggested actions:")
    if inbox["pending_actions"]:
        for index, action in inbox["pending_actions"]:
            print(f"- action {index}: {action['action']}")
    else:
        print("- None.")

    print("\nOpen agent runs:")
    if inbox["open_runs"]:
        for run in inbox["open_runs"]:
            print(f"- {run['id'][:8]} [{run['status']}] agent={run.get('agent_id')}")
    else:
        print("- None.")

    print("\nHealth warnings:")
    if inbox["health_warnings"]:
        for warning in inbox["health_warnings"]:
            print(f"- {warning['name']}: {warning['detail']}")
    else:
        print("- None.")


def build_inbox(memory):
    latest_health = latest_health_check(memory)
    health_warnings = []
    if latest_health:
        health_warnings = [
            check
            for check in latest_health["checks"]
            if check.get("status") in {"warn", "fail"}
        ]
    return {
        "pending_approvals": memory.list_approval_requests(status="pending"),
        "pending_actions": [
            (index, action)
            for index, action in enumerate(memory.list_actions(), start=1)
            if action.get("status") == "pending"
        ],
        "open_runs": open_task_runs(memory),
        "health_warnings": health_warnings,
    }


def build_daily_command_center(memory):
    inbox = build_inbox(memory)
    overdue = overdue_tasks(memory)
    due_today = memory.tasks_due_today()
    suggested_actions = []

    if due_today:
        suggested_actions.append("Work the first due-today task.")
    if overdue:
        suggested_actions.append("Review overdue tasks and reschedule or complete them.")
    if inbox["pending_approvals"]:
        suggested_actions.append("Review pending approvals in inbox.")
    if inbox["open_runs"]:
        suggested_actions.append("Review open agent runs.")
    if inbox["health_warnings"]:
        suggested_actions.append("Run health report and address warnings.")
    if not suggested_actions:
        suggested_actions.append("No urgent items. Add a task, run a health check, or review memory.")

    return {
        "due_today": due_today,
        "overdue": overdue,
        "pending_approvals": inbox["pending_approvals"],
        "open_runs": inbox["open_runs"],
        "latest_health": latest_health_check(memory),
        "suggested_actions": suggested_actions,
    }


def overdue_tasks(memory):
    today = date.today().isoformat()
    return [
        (index, task)
        for index, task in enumerate(memory.list_tasks(), start=1)
        if not task["completed"] and task.get("due_date") and task["due_date"] < today
    ]


def open_task_runs(memory):
    return [
        run
        for run in memory.list_task_runs()
        if run.get("status") in {"planning", "running", "waiting_for_review"}
    ]


def latest_health_check(memory):
    checks = memory.list_health_checks()
    if not checks:
        return None
    return checks[-1]


def extract_plan_steps(plan):
    """Split a plain-text numbered plan into task strings."""
    steps = []
    for line in plan.splitlines():
        step = line.strip()
        if not step:
            continue

        # Remove simple numbering like "1. " or "2) " before saving as a task.
        if len(step) > 2 and step[0].isdigit() and step[1] in {".", ")"}:
            step = step[2:].strip()

        if step:
            steps.append(step)
    return steps


def build_brief(memory):
    """Collect the pieces used by both the screen brief and markdown report."""
    return {
        "incomplete_tasks": [
            (index, task)
            for index, task in enumerate(memory.list_tasks(), start=1)
            if not task["completed"]
        ],
        "due_today": memory.tasks_due_today(),
        "recent_notes": memory.list_notes()[-3:],
        "recent_lessons": memory.list_lessons()[-5:],
        "recent_summaries": memory.list_memory_summaries()[-3:],
        "recent_results": memory.recent_tool_results(3),
    }


def build_ai_context(memory):
    """Build a short memory summary so AI chat can answer personal questions."""
    brief = build_brief(memory)
    lines = ["Agent Hart memory context:"]

    # Incomplete tasks help the AI answer questions like "what should I do next?"
    lines.append("\nIncomplete tasks:")
    if brief["incomplete_tasks"]:
        for index, task in brief["incomplete_tasks"]:
            lines.append(f"- {format_task_line(index, task)}")
    else:
        lines.append("- None.")

    # Tasks due today help the AI answer time-sensitive questions.
    lines.append("\nTasks due today:")
    if brief["due_today"]:
        for index, task in brief["due_today"]:
            lines.append(f"- {format_task_line(index, task)}")
    else:
        lines.append("- None.")

    lines.append("\nRecent notes:")
    if brief["recent_notes"]:
        for note in brief["recent_notes"]:
            lines.append(f"- [{note['created_at']}] {note['text']}")
    else:
        lines.append("- None.")

    lines.append("\nLong-term lessons:")
    if brief["recent_lessons"]:
        for lesson in brief["recent_lessons"]:
            lines.append(f"- [{lesson['created_at']}] {lesson['text']}")
    else:
        lines.append("- None.")

    lines.append("\nMemory summaries:")
    if brief["recent_summaries"]:
        for summary in brief["recent_summaries"]:
            lines.append(
                f"- [{summary['created_at']}] ({summary['scope']}) "
                f"{summary['summary']}"
            )
    else:
        lines.append("- None.")

    lines.append("\nRecent tool results:")
    if brief["recent_results"]:
        for result in brief["recent_results"]:
            lines.append(
                f"- [{result['created_at']}] {result['tool']} "
                f"{result['status']}: {result['target']}"
            )
    else:
        lines.append("- None.")

    return "\n".join(lines)


def build_brief_markdown(memory):
    """Create simple markdown text for today's briefing report."""
    brief = build_brief(memory)
    lines = ["# Today's Briefing", ""]

    lines.append("## Incomplete tasks")
    if brief["incomplete_tasks"]:
        for index, task in brief["incomplete_tasks"]:
            lines.append(f"- {format_task_line(index, task)}")
    else:
        lines.append("- No incomplete tasks.")

    lines.extend(["", "## Tasks due today"])
    if brief["due_today"]:
        for index, task in brief["due_today"]:
            lines.append(f"- {format_task_line(index, task)}")
    else:
        lines.append("- No tasks due today.")

    lines.extend(["", "## Recent notes"])
    if brief["recent_notes"]:
        for note in brief["recent_notes"]:
            lines.append(f"- [{note['created_at']}] {note['text']}")
    else:
        lines.append("- No notes yet.")

    lines.extend(["", "## Long-term lessons"])
    if brief["recent_lessons"]:
        for lesson in brief["recent_lessons"]:
            lines.append(f"- [{lesson['created_at']}] {lesson['text']}")
    else:
        lines.append("- No lessons yet.")

    lines.extend(["", "## Memory summaries"])
    if brief["recent_summaries"]:
        for summary in brief["recent_summaries"]:
            lines.append(
                f"- [{summary['created_at']}] ({summary['scope']}) "
                f"{summary['summary']}"
            )
    else:
        lines.append("- No memory summaries yet.")

    lines.extend(["", "## Recent tool results"])
    if brief["recent_results"]:
        for result in brief["recent_results"]:
            lines.append(
                f"- [{result['created_at']}] {result['tool']} "
                f"{result['status']}: {result['target']}"
            )
    else:
        lines.append("- No tool results yet.")

    return "\n".join(lines) + "\n"


def handle_search(keyword, memory):
    """Search saved memory sections for a case-insensitive keyword."""
    if not keyword:
        print("Usage: search <keyword>")
        return

    needle = keyword.lower()
    found_match = False

    # Tasks have several fields, so search the whole task dictionary as text.
    print("Matching tasks:")
    task_matches = [
        (index, task)
        for index, task in enumerate(memory.data["tasks"], start=1)
        if needle in str(task).lower()
    ]
    if task_matches:
        found_match = True
        for index, task in task_matches:
            print(format_task_line(index, task))
    else:
        print("None.")

    # Notes are simple text entries with timestamps.
    print("\nMatching notes:")
    note_matches = [
        note for note in memory.data["notes"] if needle in str(note).lower()
    ]
    if note_matches:
        found_match = True
        for note in note_matches:
            print(f"- [{note['created_at']}] {note['text']}")
    else:
        print("None.")

    # Chat history includes both user and assistant messages.
    print("\nMatching chats:")
    chat_matches = [
        chat for chat in memory.data["chat_history"] if needle in str(chat).lower()
    ]
    if chat_matches:
        found_match = True
        for chat in chat_matches:
            print(f"- [{chat['created_at']}] {chat['role']}: {chat['message']}")
    else:
        print("None.")

    print("\nMatching lessons:")
    lesson_matches = [
        lesson for lesson in memory.data.get("lessons", []) if needle in str(lesson).lower()
    ]
    if lesson_matches:
        found_match = True
        for lesson in lesson_matches:
            print(f"- [{lesson['created_at']}] {lesson['text']}")
    else:
        print("None.")

    print("\nMatching memory summaries:")
    summary_matches = [
        summary
        for summary in memory.data.get("memory_summaries", [])
        if needle in str(summary).lower()
    ]
    if summary_matches:
        found_match = True
        for summary in summary_matches:
            print(f"- [{summary['created_at']}] ({summary['scope']}) {summary['summary']}")
    else:
        print("None.")

    # Tool results include command targets, status, and output text.
    print("\nMatching tool results:")
    result_matches = [
        result for result in memory.data["tool_results"] if needle in str(result).lower()
    ]
    if result_matches:
        found_match = True
        for result in result_matches:
            print(
                f"- [{result['created_at']}] {result['tool']} "
                f"{result['status']}: {result['target']}"
            )
    else:
        print("None.")

    if not found_match:
        print("\nNo matches found.")


def handle_list_actions(memory):
    """Print the history of AI-suggested actions and their statuses."""
    actions = memory.list_actions()
    if not actions:
        print("No actions yet.")
        return

    for index, action_record in enumerate(actions):
        status = action_record["status"]
        created_at = action_record["created_at"]
        action = action_record["action"]
        print(f"{index}. [{status}] [{created_at}] {action}")


def handle_memory_stats(memory):
    """Show structured memory counts."""
    stats = memory.memory_stats()
    for key in sorted(stats):
        print(f"{key}: {stats[key]}")


def handle_add_lesson(text, memory):
    """Save a durable lesson for future context."""
    if not text:
        print("Usage: add lesson <text>")
        return
    lesson = memory.add_lesson(text, source="user")
    print(f"Saved lesson at {lesson['created_at']}.")


def handle_list_lessons(memory):
    """Show saved long-term lessons."""
    lessons = memory.list_lessons()
    if not lessons:
        print("No lessons yet.")
        return
    for index, lesson in enumerate(lessons, start=1):
        print(
            f"{index}. [{lesson['created_at']}] "
            f"({lesson.get('source', 'unknown')}) {lesson['text']}"
        )


def handle_list_memory_summaries(memory):
    """Show saved long-term memory summaries."""
    summaries = memory.list_memory_summaries()
    if not summaries:
        print("No memory summaries yet.")
        return
    for index, summary in enumerate(summaries, start=1):
        print(
            f"{index}. [{summary['created_at']}] "
            f"({summary['scope']}) {summary['summary']}"
        )


def handle_add_agent(text, memory):
    """Create an automation agent profile without starting any execution."""
    if not text:
        print(
            "Usage: add agent <name> "
            "[--role <role>] [--tools a,b] [--max-steps n] [--autonomy supervised]"
        )
        return

    try:
        name, options = parse_agent_input(text)
    except ValueError as exc:
        print(exc)
        return

    if not name:
        print(
            "Usage: add agent <name> "
            "[--role <role>] [--tools a,b] [--max-steps n] [--autonomy supervised]"
        )
        return

    agent = memory.add_agent(name, **options)
    print(f"Added agent {agent['name']} ({agent['id'][:8]}).")


def handle_list_agents(memory):
    agents = memory.list_agents()
    if not agents:
        print("No agents yet.")
        return

    for index, agent in enumerate(agents, start=1):
        tools = ", ".join(agent.get("allowed_tools", [])) or "none"
        print(
            f"{index}. [{agent['status']}] {agent['name']} "
            f"({agent['id'][:8]}) role={agent['role']} "
            f"autonomy={agent['autonomy_level']} max_steps={agent['max_steps']} "
            f"tools={tools}"
        )


def handle_add_goal(text, memory):
    """Create a pending automation goal for an existing agent."""
    agent_ref, _, goal_text = text.partition(" ")
    agent_ref = agent_ref.strip()
    goal_text = goal_text.strip()

    if not agent_ref or not goal_text:
        print("Usage: add goal <agent-number-or-id> <goal text>")
        return

    agent = find_agent(memory, agent_ref)
    if agent is None:
        print(f"No agent found for {agent_ref}.")
        return

    goal = memory.add_goal(agent["id"], goal_text)
    print(f"Added goal {goal['id'][:8]} for {agent['name']}.")


def handle_list_goals(memory):
    goals = memory.list_goals()
    if not goals:
        print("No goals yet.")
        return

    agents_by_id = {agent["id"]: agent for agent in memory.list_agents()}
    for index, goal in enumerate(goals, start=1):
        agent = agents_by_id.get(goal.get("agent_id"))
        agent_name = agent["name"] if agent else "unknown agent"
        print(
            f"{index}. [{goal['status']}] ({goal['id'][:8]}) "
            f"{agent_name}: {goal['text']}"
        )


def handle_agent_status(memory):
    """Show automation runtime state without executing anything."""
    stats = memory.memory_stats()
    agents = memory.list_agents()
    goals = memory.list_goals()
    runs = memory.list_task_runs()
    steps = memory.list_run_steps()
    pending_goals = [goal for goal in goals if goal.get("status") == "pending"]
    active_runs = [run for run in runs if run.get("status") in {"pending", "running"}]

    print("Automation runtime status")
    print(f"Agents: {stats.get('agents', len(agents))}")
    print(f"Goals: {stats.get('goals', len(goals))}")
    print(f"Pending goals: {len(pending_goals)}")
    print(f"Task runs: {stats.get('task_runs', len(runs))}")
    print(f"Active runs: {len(active_runs)}")
    print(f"Run steps: {stats.get('run_steps', len(steps))}")
    print("Execution: disabled until the planner/executor phase is implemented.")
    print("\nAgent performance:")
    performance = build_agent_performance(memory)
    if performance:
        for item in performance:
            print(
                f"- {item['agent_name']}: reviews={item['reviews']} "
                f"success_rate={item['success_rate']}% "
                f"common_outcome={item['common_outcome']}"
            )
    else:
        print("- No run reviews yet.")


def handle_run_agent_placeholder(agent_ref, memory):
    """Refuse autonomous execution until the execution loop exists."""
    if not agent_ref.strip():
        print("Usage: run-agent <agent-number-or-id>")
        return

    agent = find_agent(memory, agent_ref.strip())
    if agent is None:
        print(f"No agent found for {agent_ref.strip()}.")
        return

    print(
        f"Automation execution is not enabled yet for {agent['name']}. "
        "This command is reserved for the planner/executor phase."
    )


def handle_agent_check_tool(rest, memory, tools):
    """Dry-run an agent tool request against per-agent and global policy."""
    agent_ref, _, tool_and_target = rest.partition(" ")
    tool_name, _, target = tool_and_target.partition(" ")
    agent_ref = agent_ref.strip()
    tool_name = tool_name.strip().lower()
    target = target.strip()

    if not agent_ref or not tool_name or not target:
        print("Usage: agent check-tool <agent-number-or-id> <tool> <target>")
        return

    agent = find_agent(memory, agent_ref)
    if agent is None:
        print(f"No agent found for {agent_ref}.")
        return

    try:
        proposal = tools.request_agent_proposal(agent, tool_name, target)
    except PolicyError as exc:
        print(f"Agent policy blocked this action: {exc}")
        return

    approval = "approval required" if proposal["requires_approval"] else "no approval"
    print(
        f"Allowed for {agent['name']}: {tool_name} {target} "
        f"({approval}, risk={proposal['risk_level']})."
    )


def handle_plan_agent(rest, memory, tools):
    """Create one supervised planner checkpoint without executing tools."""
    agent_ref, _, goal_ref = rest.partition(" ")
    agent_ref = agent_ref.strip()
    goal_ref = goal_ref.strip()

    if not agent_ref or not goal_ref:
        print("Usage: plan-agent <agent-number-or-id> <goal-number-or-id>")
        return

    agent = find_agent(memory, agent_ref)
    if agent is None:
        print(f"No agent found for {agent_ref}.")
        return

    goal = find_goal(memory, goal_ref, agent_id=agent["id"])
    if goal is None:
        print(f"No goal found for {goal_ref}.")
        return

    run = memory.add_task_run(agent["id"], goal_id=goal["id"], status="planning")
    prompt = build_agent_planner_prompt(agent, goal, memory, tools)
    response = ollama_chat(prompt)
    parsed = parse_planner_response(response)
    step_status = "proposed" if parsed["valid"] else "invalid_response"
    tool_name = parsed.get("tool")
    tool_target = parsed.get("target")
    policy_error = None

    if parsed["valid"] and tool_name:
        try:
            tools.validate_agent_tool_request(agent, tool_name, tool_target)
        except PolicyError as exc:
            step_status = "blocked_proposal"
            policy_error = str(exc)

    memory.add_run_step(
        run["id"],
        1,
        step_status,
        prompt=prompt,
        response=response,
        tool_name=tool_name,
        tool_target=tool_target,
    )
    memory.update_task_run_status(run["id"], "waiting_for_review")

    print(f"Created planner checkpoint {run['id'][:8]} for {agent['name']}.")
    print(f"Step status: {step_status}")
    if parsed["valid"]:
        print(f"Proposed action: {parsed['next_action']}")
        if tool_name:
            print(f"Tool proposal: {tool_name} {tool_target}")
        if policy_error:
            print(f"Policy check: blocked - {policy_error}")
        else:
            print("Policy check: passed.")
        print("No tools were executed.")
    else:
        print("Planner response was not valid JSON. No tools were executed.")


def build_agent_planner_prompt(agent, goal, memory, tools):
    """Build a strict prompt for one supervised automation planning step."""
    allowed_tools = ", ".join(agent.get("allowed_tools", [])) or "none"
    available_tools = ", ".join(tool.name for tool in tools.list_tools())
    return (
        "You are planning one supervised automation step for Agent Hart.\n"
        "Do not claim that you executed anything.\n"
        "Return one JSON object only, with no markdown.\n"
        "Allowed next_action values: propose_tool, wait, stop.\n"
        "If next_action is propose_tool, include tool and target.\n"
        "If no useful tool is appropriate, use wait or stop.\n\n"
        "Required JSON shape:\n"
        '{\"thought_summary\":\"...\",\"next_action\":\"wait\",'
        '\"tool\":null,\"target\":null,\"reason\":\"...\"}\n\n'
        f"Agent name: {agent['name']}\n"
        f"Agent role: {agent['role']}\n"
        f"Agent allowed tools: {allowed_tools}\n"
        f"Registered tools: {available_tools}\n"
        f"Goal: {goal['text']}\n\n"
        f"Memory context:\n{build_ai_context(memory)}"
    )


def parse_planner_response(response):
    """Parse a planner response without trusting it to execute anything."""
    try:
        parsed = json_loads_object(extract_json_object(response))
    except ValueError:
        return {"valid": False}

    next_action = parsed.get("next_action")
    if next_action not in {"propose_tool", "wait", "stop"}:
        return {"valid": False}

    result = {
        "valid": True,
        "thought_summary": str(parsed.get("thought_summary", "")).strip(),
        "next_action": next_action,
        "reason": str(parsed.get("reason", "")).strip(),
        "tool": None,
        "target": None,
    }

    if next_action == "propose_tool":
        tool = str(parsed.get("tool", "")).strip().lower()
        target = str(parsed.get("target", "")).strip()
        if not tool or not target:
            return {"valid": False}
        result["tool"] = tool
        result["target"] = target

    return result


def json_loads_object(text):
    import json

    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("Expected a JSON object.")
    return parsed


def handle_stop_agent_placeholder(run_id, memory):
    """Explain that stop controls arrive with actual task runs."""
    if not run_id.strip():
        print("Usage: stop-agent <run-id>")
        return

    matching_runs = [
        run for run in memory.list_task_runs() if run.get("id", "").startswith(run_id.strip())
    ]
    if not matching_runs:
        print(f"No task run found for {run_id.strip()}.")
        return

    print("Stop controls are reserved for the planner/executor phase.")


def parse_agent_input(raw_text):
    """Parse agent profile flags while preserving a readable name."""
    try:
        parts = shlex.split(raw_text)
    except ValueError as exc:
        raise ValueError(f"Could not parse agent: {exc}") from exc

    name_parts = []
    options = {
        "role": "general",
        "allowed_tools": [],
        "max_steps": 5,
        "autonomy_level": "supervised",
    }
    index = 0

    while index < len(parts):
        part = parts[index]
        if part == "--role":
            index += 1
            if index >= len(parts):
                raise ValueError("Usage: --role needs a value.")
            options["role"] = parts[index]
        elif part == "--tools":
            index += 1
            if index >= len(parts):
                raise ValueError("Usage: --tools needs comma-separated tool names.")
            options["allowed_tools"] = parse_tool_list(parts[index])
        elif part == "--max-steps":
            index += 1
            if index >= len(parts):
                raise ValueError("Usage: --max-steps needs a number.")
            options["max_steps"] = parse_max_steps(parts[index])
        elif part == "--autonomy":
            index += 1
            if index >= len(parts):
                raise ValueError("Usage: --autonomy needs a value.")
            options["autonomy_level"] = parts[index]
        else:
            name_parts.append(part)
        index += 1

    return " ".join(name_parts), options


def parse_tool_list(value):
    tools = [tool.strip().lower() for tool in value.split(",") if tool.strip()]
    return tools


def parse_max_steps(value):
    try:
        max_steps = int(value)
    except ValueError as exc:
        raise ValueError("Max steps must be a whole number.") from exc
    if max_steps < 1:
        raise ValueError("Max steps must be 1 or higher.")
    return max_steps


def find_agent(memory, reference):
    agents = memory.list_agents()
    try:
        index = int(reference) - 1
    except ValueError:
        index = None

    if index is not None:
        if 0 <= index < len(agents):
            return agents[index]

    matches = [agent for agent in agents if agent["id"].startswith(reference)]
    if len(matches) == 1:
        return matches[0]
    return None


def find_goal(memory, reference, agent_id=None):
    goals = memory.list_goals()
    if agent_id:
        goals = [goal for goal in goals if goal.get("agent_id") == agent_id]

    try:
        index = int(reference) - 1
    except ValueError:
        index = None

    if index is not None:
        if 0 <= index < len(goals):
            return goals[index]

    matches = [goal for goal in goals if goal["id"].startswith(reference)]
    if len(matches) == 1:
        return matches[0]
    return None


def find_task_run(memory, reference):
    runs = memory.list_task_runs()
    try:
        index = int(reference) - 1
    except ValueError:
        index = None

    if index is not None:
        if 0 <= index < len(runs):
            return runs[index]

    matches = [run for run in runs if run["id"].startswith(reference)]
    if len(matches) == 1:
        return matches[0]
    return None


def build_agent_performance(memory):
    agents_by_id = {agent["id"]: agent for agent in memory.list_agents()}
    reviews_by_agent = {}
    for review in memory.list_run_reviews():
        agent_id = review.get("agent_id")
        if agent_id:
            reviews_by_agent.setdefault(agent_id, []).append(review)

    performance = []
    for agent_id, reviews in sorted(reviews_by_agent.items()):
        agent = agents_by_id.get(agent_id, {"name": "unknown agent"})
        successes = sum(1 for review in reviews if review.get("outcome") == "success")
        outcome_counts = {}
        for review in reviews:
            outcome = review.get("outcome", "unknown")
            outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1
        common_outcome = sorted(
            outcome_counts.items(), key=lambda item: (-item[1], item[0])
        )[0][0]
        performance.append(
            {
                "agent_id": agent_id,
                "agent_name": agent["name"],
                "reviews": len(reviews),
                "success_rate": round((successes / len(reviews)) * 100),
                "common_outcome": common_outcome,
            }
        )
    return performance


def handle_list_approvals(memory):
    """Print pending approval requests with enough context to decide."""
    approvals = memory.list_approval_requests(status="pending")
    if not approvals:
        print("No pending approvals.")
        return

    for approval in approvals:
        short_id = approval["id"][:8]
        print(
            f"{short_id} [{approval['risk_level']}] "
            f"{approval['description']} (created {approval['created_at']})"
        )


def handle_approval_decision(rest, approved, memory, tools):
    """Approve or reject a queued request from the CLI."""
    approval_id = rest.strip()
    if not approval_id:
        action = "approve" if approved else "reject"
        print(f"Usage: {action} <approval-id>")
        return

    approval = find_approval(memory, approval_id)
    if approval is None:
        print(f"No pending approval found for: {approval_id}")
        return
    if approval.get("status") != "pending":
        print(f"Approval {approval['id'][:8]} is already {approval.get('status')}.")
        return

    if not approved:
        memory.decide_approval(approval["id"], False, reason="Rejected from CLI.")
        print(f"Rejected approval {approval['id'][:8]}.")
        return

    memory.decide_approval(approval["id"], True, reason="Approved from CLI.")
    try:
        execute_approval(approval, memory, tools)
    except PolicyError as exc:
        print(f"Policy blocked this action: {exc}")
    except Exception as exc:
        print(f"Tool failed: {exc}")


def find_approval(memory, approval_id):
    """Resolve an approval by full id or unique short prefix."""
    pending = memory.list_approval_requests(status="pending")
    exact = [approval for approval in pending if approval.get("id") == approval_id]
    if exact:
        return exact[0]

    matches = [
        approval
        for approval in pending
        if approval.get("id", "").startswith(approval_id)
    ]
    if len(matches) == 1:
        return matches[0]
    return None


def handle_suggested_action(suggestion, memory):
    """Ask approval before applying an AI-suggested memory action."""
    if suggestion.get("action") != "add_task":
        return

    task_text = str(suggestion.get("text", "")).strip()
    if not task_text:
        return

    due_date = normalize_suggested_due(suggestion.get("due"))
    priority = normalize_suggested_priority(suggestion.get("priority"))
    action_record = memory.add_action(suggestion)
    action_index = len(memory.list_actions()) - 1

    # Only add_task is supported here. The AI never runs tools or changes memory
    # directly; this prompt keeps the human in control.
    print("\nSuggested task:")
    print(f"Text: {task_text}")
    print(f"Due: {due_date or 'none'}")
    print(f"Priority: {priority}")
    answer = input("Approve suggested task? Type yes to continue: ").strip().lower()
    if answer != "yes":
        memory.update_action_status(action_index, "rejected")
        print("Suggested task not added.")
        return

    task = memory.add_task(task_text, due_date=due_date, priority=priority)
    memory.set_action_created_task_id(action_index, task["id"])
    memory.update_action_status(action_index, "approved")
    print(f"Added task: {task_text} (due: {due_date or 'none'})")


def normalize_suggested_due(value):
    """Convert the AI's simple due value into our YYYY-MM-DD task date."""
    if value is None:
        return None

    due_text = str(value).strip().lower()
    if not due_text or due_text == "none":
        return None
    if due_text == "today":
        return date.today().isoformat()
    if due_text == "tomorrow":
        return (date.today() + timedelta(days=1)).isoformat()

    try:
        return datetime.strptime(due_text, "%Y-%m-%d").date().isoformat()
    except ValueError:
        return None


def normalize_suggested_priority(value):
    """Keep only supported priority labels from the AI suggestion."""
    if value is None:
        return "normal"

    priority = str(value).strip().lower()
    if priority in {"low", "normal", "high"}:
        return priority
    return "normal"


def handle_undo_action(action_number, memory):
    """Undo an approved add_task action by deleting only its created task."""
    try:
        action_index = int(action_number)
    except ValueError:
        print("Usage: undo action <number>")
        return

    actions = memory.list_actions()
    if action_index < 0 or action_index >= len(actions):
        print(f"No action found at {action_number}.")
        return

    action_record = actions[action_index]
    if action_record.get("status") != "approved":
        print("Only approved actions can be undone.")
        return

    action = action_record.get("action", {})
    if action.get("action") != "add_task":
        print("Only approved add_task actions can be undone.")
        return

    task_id = action_record.get("created_task_id")
    if not task_id:
        print("This action does not have a created task id to undo.")
        return

    # The id makes undo precise: it deletes only the task created by this action.
    if not memory.delete_task_by_id(task_id):
        print("Could not find the task created by this action.")
        return

    memory.update_action_status(action_index, "undone")
    print(f"Undid action {action_number}.")


def handle_complete_task(task_number, memory):
    """Mark a task complete using the user-facing 1-based task number."""
    try:
        index = int(task_number) - 1
    except ValueError:
        print("Usage: complete task <number>")
        return

    if index < 0:
        print("Task number must be 1 or higher.")
        return

    if memory.complete_task(index):
        print(f"Completed task {task_number}.")
    else:
        print(f"No task found at {task_number}.")


def parse_task_input(raw_text):
    """Parse optional task flags while preserving normal task text."""
    try:
        parts = shlex.split(raw_text)
    except ValueError as exc:
        raise ValueError(f"Could not parse task: {exc}") from exc

    task_parts = []
    due_date = None
    priority = "normal"
    index = 0

    while index < len(parts):
        part = parts[index]
        if part == "--due":
            index += 1
            if index >= len(parts):
                raise ValueError("Usage: --due needs YYYY-MM-DD or today.")
            due_date = parse_due_date(parts[index])
        elif part == "--priority":
            index += 1
            if index >= len(parts):
                raise ValueError("Usage: --priority needs low, normal, or high.")
            priority = parse_priority(parts[index])
        else:
            task_parts.append(part)
        index += 1

    return " ".join(task_parts), due_date, priority


def detect_simple_due_date(text):
    """Find a simple due date inside natural-language task text."""
    words = text.lower().split()

    # Plain date words are the easiest path for beginners to read and extend.
    if "today" in words:
        return date.today().isoformat()
    if "tomorrow" in words:
        return (date.today() + timedelta(days=1)).isoformat()

    # Accept an exact ISO date anywhere in the sentence, like 2026-04-30.
    for word in words:
        cleaned_word = word.strip(".,!?;:")
        try:
            return datetime.strptime(cleaned_word, "%Y-%m-%d").date().isoformat()
        except ValueError:
            pass

    # If the user only gives a time, keep this simple and treat it as today.
    for index, word in enumerate(words[:-1]):
        if word == "at":
            time_text = words[index + 1].strip(".,!?;:")
            try:
                datetime.strptime(time_text, "%H:%M")
                return date.today().isoformat()
            except ValueError:
                pass

    return None


def parse_due_date(value):
    """Return a YYYY-MM-DD date string from supported due-date input."""
    if value.lower() == "today":
        return date.today().isoformat()

    try:
        return datetime.strptime(value, "%Y-%m-%d").date().isoformat()
    except ValueError as exc:
        raise ValueError("Due date must be YYYY-MM-DD or today.") from exc


def parse_priority(value):
    priority = value.lower()
    if priority not in {"low", "normal", "high"}:
        raise ValueError("Priority must be low, normal, or high.")
    return priority


def format_task_details(task):
    details = []
    if task.get("due_date"):
        details.append(f"due {task['due_date']}")
    details.append(f"priority {task.get('priority', 'normal')}")
    return f" ({', '.join(details)})"


def format_task_line(index, task):
    marker = "x" if task["completed"] else " "
    due_date = task.get("due_date") or "no due date"
    priority = task.get("priority", "normal")
    return f"{index}. [{marker}] [{priority}] [due: {due_date}] {task['text']}"


def handle_run(rest, memory, tools):
    """
    Run a tool through the safe execution flow.

    The important security pattern is:
    1. Parse the requested tool and target.
    2. Validate the request against policy.
    3. Ask for human approval when policy says approval is required.
    4. Execute the tool.
    5. Save the result to memory for auditability and reports.
    """
    tool_name, _, target = rest.partition(" ")
    tool_name = tool_name.strip().lower()
    target = target.strip()

    if not tool_name or not target:
        print("Usage: run <tool> <target>")
        return

    try:
        proposal = tools.request_proposal(tool_name, target)
        approval = memory.add_approval_request(
            proposal["action_type"],
            proposal["description"],
            proposal["payload"],
            risk_level=proposal["risk_level"],
            requires_approval=proposal["requires_approval"],
        )
        if proposal["requires_approval"]:
            print(f"Queued approval {approval['id'][:8]}: {proposal['description']}")
            if not prompt_approval(tool_name, target):
                memory.decide_approval(
                    approval["id"], False, reason="Rejected from inline prompt."
                )
                print("Action cancelled.")
                return
            memory.decide_approval(
                approval["id"], True, reason="Approved from inline prompt."
            )
        execute_approval(approval, memory, tools)
    except PolicyError as exc:
        print(f"Policy blocked this action: {exc}")
        return
    except Exception as exc:
        print(f"Tool failed: {exc}")
        return


def execute_approval(approval, memory, tools):
    """Run the approved action and store both result and execution status."""
    payload = approval.get("payload", {})
    if approval.get("action_type") != "run_tool":
        print(f"Unsupported approval action: {approval.get('action_type')}")
        return

    tool_name = payload.get("tool", "")
    target = payload.get("target", "")
    if approval.get("requires_approval") and approval.get("status") != "approved":
        print("This action has not been approved.")
        return

    output = tools.run(tool_name, target, memory)
    status = "ok" if not output.startswith("Command exited") else "error"
    memory.add_tool_result(tool_name, target, output, status, approval_id=approval["id"])
    memory.mark_approval_executed(approval["id"], status)
    print(output)


def prompt_approval(tool_name, target):
    """
    Human-in-the-loop approval gate.

    For now this is a simple "type yes" prompt. Later, the same idea can become
    a web approval button or a signed approval record in a database.
    """
    print(f"Approval required: run '{tool_name}' against '{target}'")
    answer = input("Approve? Type yes to continue: ").strip().lower()
    return answer == "yes"


if __name__ == "__main__":
    main()
