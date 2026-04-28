"""
Note Organizer Agent — uses gemma4 to categorize and surface actionable notes.
Runs nightly and saves an organized view to memory. No paid tokens.
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

    notes = memory.list_notes()
    if not notes:
        print("[note_organizer] No notes to organize.")
        return

    notes_block = "\n".join(
        f"[{i+1}] {n.get('text','')}" for i, n in enumerate(notes[-30:])
    )

    prompt = (
        f"Today is {today}. Organize these personal notes into categories.\n\n"
        "Group them under these headings (only include headings that have notes):\n"
        "ACTION NEEDED — notes that imply something to do\n"
        "LEARNING — notes about skills, tools, or knowledge\n"
        "IDEAS — future plans or brainstorms\n"
        "REFERENCE — facts or info to keep handy\n\n"
        "List each note under its group. Keep the original text. Plain text only.\n\n"
        f"Notes:\n{notes_block}"
    )

    print(f"[note_organizer] Organizing {len(notes)} notes...")
    with AgentRun("note_organizer", memory) as run:
        organized, meta = ollama_chat_with_meta(prompt)
        run.record_llm(meta)
        run.add_output(len(notes))
    print(organized)

    memory.add_memory_summary(scope="note_organization", summary=organized)
    memory.add_audit_event("agent_run", {"agent": "note_organizer", "date": today, "notes_count": len(notes)})
    print("[note_organizer] Organized notes saved to memory.")


if __name__ == "__main__":
    run()
