"""
Task Review Agent — runs several times a day, uses gemma4 to flag overdue tasks
and surface what needs attention. Saves recommendations to memory. No paid tokens.
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
from memory_factory import create_memory_store


def run():
    memory = create_memory_store(BASE_DIR)
    today = date.today().isoformat()

    open_tasks = [t for t in memory.list_tasks() if not t.get("completed")]
    if not open_tasks:
        print("[task_review] No open tasks. Nothing to do.")
        return

    task_block = "\n".join(
        f"- ID:{t['id'][:8]} [{t.get('priority','normal')}] due:{t.get('due_date','none')} | {t['text']}"
        for t in open_tasks
    )

    prompt = (
        f"Today is {today}. Review these open tasks and provide a short plain-text report:\n"
        "1. List any OVERDUE tasks (due date is before today)\n"
        "2. List the top 3 tasks to tackle today based on priority and due date\n"
        "3. Flag any tasks that look vague or need more detail\n"
        "Keep each point brief. No markdown formatting.\n\n"
        f"Open tasks:\n{task_block}"
    )

    print(f"[task_review] Reviewing {len(open_tasks)} open tasks...")
    with AgentRun("task_review", memory) as run:
        review, meta = ollama_chat_with_meta(prompt)
        run.record_llm(meta)
        run.add_output(len(open_tasks))
    print(review)

    memory.add_memory_summary(scope="task_review", summary=review)
    memory.add_audit_event("agent_run", {"agent": "task_review", "date": today, "tasks_reviewed": len(open_tasks)})
    print("[task_review] Saved review to memory.")


if __name__ == "__main__":
    run()
