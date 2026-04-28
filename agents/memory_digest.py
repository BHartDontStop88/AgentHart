"""
Memory Digest Agent — condenses old chat history into saved lessons using gemma4.
Keeps Agent Hart's context window lean so future AI calls stay fast and accurate.
No paid tokens used.
"""
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv
load_dotenv(BASE_DIR / ".env")

from ai import ollama_chat_with_meta
from agents.metrics import AgentRun
from memory_factory import create_memory_store

BATCH_SIZE = 15      # digest this many old chat entries at a time
KEEP_RECENT = 10     # always preserve the most recent N chat entries


def run():
    memory = create_memory_store(BASE_DIR)
    history = memory.list_chat_history()

    if len(history) <= KEEP_RECENT:
        print(f"[memory_digest] Only {len(history)} chat entries — nothing to digest yet.")
        return

    to_digest = history[: len(history) - KEEP_RECENT]
    batch = to_digest[:BATCH_SIZE]

    chat_block = "\n".join(
        f"{entry.get('role','?').upper()}: {entry.get('message','')}"
        for entry in batch
    )

    prompt = (
        "You are a memory compression assistant for Agent Hart.\n"
        "Read the chat history below and extract:\n"
        "1. Key facts the user shared about themselves or their goals\n"
        "2. Decisions or preferences the user expressed\n"
        "3. Any lessons or patterns worth remembering\n"
        "Write a concise plain-text summary (5-10 bullet points max). No preamble.\n\n"
        f"Chat history:\n{chat_block}"
    )

    print(f"[memory_digest] Digesting {len(batch)} chat entries into lessons...")
    with AgentRun("memory_digest", memory) as run:
        digest, meta = ollama_chat_with_meta(prompt)
        run.record_llm(meta)
        run.add_output(1)
    print(digest)

    memory.add_memory_summary(scope="chat_digest", summary=digest)
    memory.add_lesson(text=digest, source="memory_digest_agent")
    memory.add_audit_event("agent_run", {
        "agent": "memory_digest",
        "entries_digested": len(batch),
    })
    print("[memory_digest] Digest saved as lesson and memory summary.")


if __name__ == "__main__":
    run()
