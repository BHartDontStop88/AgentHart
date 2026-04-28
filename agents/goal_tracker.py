"""
Goal Tracker Agent — weekly review of your goals using gemma4.
Scores progress against completed tasks and suggests next steps. No paid tokens.
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


def run():
    memory = create_memory_store(BASE_DIR)
    today = date.today().isoformat()

    goals = memory.list_goals()
    if not goals:
        print("[goal_tracker] No goals saved yet. Add goals with: add goal <agent> <text>")
        return

    all_tasks = memory.list_tasks()
    completed = [t for t in all_tasks if t.get("completed")]
    open_tasks = [t for t in all_tasks if not t.get("completed")]

    goals_block = "\n".join(
        f"- {g.get('text', g.get('goal', str(g)))}" for g in goals
    )
    completed_block = "\n".join(f"- {t['text']}" for t in completed[-20:]) or "None"
    open_block = "\n".join(
        f"- [{t.get('priority','normal')}] {t['text']}" for t in open_tasks[:20]
    ) or "None"

    prompt = (
        f"Today is {today} (weekly review day).\n"
        "Review these goals and evaluate progress based on completed and open tasks.\n\n"
        "For each goal:\n"
        "1. Rate progress: On Track / Slipping / Stalled\n"
        "2. Point to 1-2 completed tasks that support it (if any)\n"
        "3. Suggest one concrete next action\n\n"
        "Keep it practical and plain text. No markdown.\n\n"
        f"Goals:\n{goals_block}\n\n"
        f"Completed tasks (recent):\n{completed_block}\n\n"
        f"Open tasks:\n{open_block}"
    )

    print("[goal_tracker] Running weekly goal review...")
    with AgentRun("goal_tracker", memory) as run:
        review, meta = ollama_chat_with_meta(prompt)
        run.record_llm(meta)
        run.add_output(1)
    print(review)

    memory.add_memory_summary(scope="goal_review", summary=review)
    memory.add_audit_event("agent_run", {"agent": "goal_tracker", "date": today})

    reports_dir = BASE_DIR / "reports" / "goals"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / f"{today}.md").write_text(review, encoding="utf-8")

    send_telegram(f"Agent Hart Weekly Goal Review:\n\n{review[:800]}")
    print(f"[goal_tracker] Saved to reports/goals/{today}.md")


if __name__ == "__main__":
    run()
