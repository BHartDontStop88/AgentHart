"""
Lesson Reviewer Agent — daily quiz on your oldest saved lessons using gemma4.
Sends quiz questions via Telegram to reinforce what you've learned. No paid tokens.
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

    lessons = memory.list_lessons()
    if not lessons:
        print("[lesson_reviewer] No lessons saved yet.")
        return

    # Review the oldest lessons (they need reinforcement most)
    batch = lessons[:5]
    lessons_block = "\n".join(
        f"[{i+1}] {l.get('text','')}" for i, l in enumerate(batch)
    )

    prompt = (
        "You are a study coach for Agent Hart.\n"
        "Based on these saved lessons, create 3 short quiz questions to test recall.\n"
        "Format:\n"
        "Q1: <question>\n"
        "Q2: <question>\n"
        "Q3: <question>\n\n"
        "Then on the next line write: ANSWERS:\n"
        "A1: <answer>\nA2: <answer>\nA3: <answer>\n\n"
        "Keep questions practical and specific to the lesson content.\n\n"
        f"Lessons to review:\n{lessons_block}"
    )

    print("[lesson_reviewer] Generating quiz from saved lessons...")
    with AgentRun("lesson_reviewer", memory) as run:
        quiz, meta = ollama_chat_with_meta(prompt)
        run.record_llm(meta)
        run.add_output(1)
    print(quiz)

    memory.add_memory_summary(scope="lesson_quiz", summary=quiz)
    memory.add_audit_event("agent_run", {"agent": "lesson_reviewer", "date": today, "lessons_reviewed": len(batch)})

    send_telegram(f"Agent Hart Daily Quiz:\n\n{quiz[:800]}\n\nReply /lessons to see all saved lessons.")
    print("[lesson_reviewer] Quiz sent via Telegram.")


if __name__ == "__main__":
    run()
