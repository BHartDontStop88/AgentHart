"""
Daily Briefing Agent — runs each morning, writes a plain-language summary of
your day using the local gemma4 model. No paid API tokens used.
"""
import sys
from datetime import date
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv
load_dotenv(BASE_DIR / ".env")

from ai import ollama_chat_with_meta
from agents.metrics import AgentRun
from agents.notify import send_telegram
from memory_factory import create_memory_store


def _task_lines(tasks):
    open_tasks = [t for t in tasks if not t.get("completed")]
    if not open_tasks:
        return ["No open tasks."]
    lines = []
    for t in open_tasks:
        due = t.get("due_date") or "no due date"
        pri = t.get("priority", "normal")
        lines.append(f"- [{pri}] {t['text']} (due: {due})")
    return lines


def _note_lines(notes):
    recent = notes[-5:] if len(notes) > 5 else notes
    if not recent:
        return ["No notes saved."]
    return [f"- {n['text']}" for n in recent]


def _reminder_lines(reminders):
    pending = [r for r in reminders if not r.get("completed")]
    if not pending:
        return ["No pending reminders."]
    return [f"- {r['text']} (due: {r.get('due_date', 'unset')})" for r in pending]


def run():
    memory = create_memory_store(BASE_DIR)
    today = date.today().isoformat()

    tasks = _task_lines(memory.list_tasks())
    notes = _note_lines(memory.list_notes())
    reminders = _reminder_lines(memory.list_reminders())

    prompt = (
        f"Today is {today}. You are Agent Hart, a personal AI assistant.\n"
        "Write a concise morning briefing (plain text, no markdown headers) covering:\n"
        "1. Priority tasks to focus on today\n"
        "2. Any overdue or urgent items\n"
        "3. A one-sentence motivational note\n\n"
        "Open tasks:\n" + "\n".join(tasks) + "\n\n"
        "Recent notes:\n" + "\n".join(notes) + "\n\n"
        "Pending reminders:\n" + "\n".join(reminders)
    )

    print(f"[daily_briefing] Generating briefing for {today}...")
    with AgentRun("daily_briefing", memory) as run:
        briefing, meta = ollama_chat_with_meta(prompt)
        run.record_llm(meta)
        run.add_output(1)
    print(briefing)

    memory.add_memory_summary(scope="daily_briefing", summary=briefing)
    memory.add_audit_event("agent_run", {"agent": "daily_briefing", "date": today})

    send_telegram(f"Agent Hart Morning Briefing — {today}\n\n{briefing}")

    reports_dir = BASE_DIR / "reports" / "briefings"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / f"{today}.md").write_text(briefing, encoding="utf-8")
    print(f"[daily_briefing] Saved to reports/briefings/{today}.md")


if __name__ == "__main__":
    run()
