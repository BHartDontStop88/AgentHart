"""
Weekly Review Agent — every Sunday generates a full week-in-review using gemma4.
Covers wins, slippage, and priorities for the coming week. No paid tokens.
"""
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv
load_dotenv(BASE_DIR / ".env")

from ai import ollama_chat_with_meta
from agents.metrics import AgentRun
from agents.notify import send_telegram
from memory_factory import create_memory_store


def _was_this_week(date_str):
    if not date_str:
        return False
    try:
        d = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
        return d >= date.today() - timedelta(days=7)
    except ValueError:
        return False


def run():
    memory = create_memory_store(BASE_DIR)
    today = date.today().isoformat()

    all_tasks = memory.list_tasks()
    completed_this_week = [
        t for t in all_tasks
        if t.get("completed") and _was_this_week(t.get("completed_at") or t.get("updated_at", ""))
    ]
    still_open = [t for t in all_tasks if not t.get("completed")]
    overdue = [
        t for t in still_open
        if t.get("due_date") and t["due_date"] < today
    ]

    summaries = memory.list_memory_summaries()
    recent_summaries = [s for s in summaries if _was_this_week(s.get("created_at", ""))]
    summary_block = "\n".join(
        f"[{s['scope']}] {s['summary'][:200]}" for s in recent_summaries[-5:]
    ) or "No summaries this week."

    completed_block = "\n".join(f"- {t['text']}" for t in completed_this_week) or "None"
    overdue_block = "\n".join(f"- {t['text']} (due {t['due_date']})" for t in overdue) or "None"
    open_block = "\n".join(
        f"- [{t.get('priority','normal')}] {t['text']}" for t in still_open[:15]
    ) or "None"

    prompt = (
        f"Today is {today} (Sunday — weekly review).\n"
        "Write a concise weekly review in plain text covering:\n"
        "1. WINS: What got done this week\n"
        "2. SLIPPAGE: What was overdue or missed\n"
        "3. NEXT WEEK: Top 3 priorities to focus on\n"
        "4. ONE LESSON: Something to carry forward\n\n"
        "Keep each section brief. No markdown.\n\n"
        f"Completed this week:\n{completed_block}\n\n"
        f"Overdue tasks:\n{overdue_block}\n\n"
        f"All open tasks:\n{open_block}\n\n"
        f"Agent summaries from this week:\n{summary_block}"
    )

    print("[weekly_review] Generating weekly review...")
    with AgentRun("weekly_review", memory) as run:
        review, meta = ollama_chat_with_meta(prompt)
        run.record_llm(meta)
        run.add_output(1)
    print(review)

    memory.add_memory_summary(scope="weekly_review", summary=review)
    memory.add_audit_event("agent_run", {
        "agent": "weekly_review",
        "date": today,
        "completed": len(completed_this_week),
        "overdue": len(overdue),
    })

    reports_dir = BASE_DIR / "reports" / "weekly"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / f"{today}.md").write_text(review, encoding="utf-8")

    send_telegram(f"Agent Hart Weekly Review:\n\n{review[:900]}")
    print(f"[weekly_review] Saved to reports/weekly/{today}.md")


if __name__ == "__main__":
    run()
