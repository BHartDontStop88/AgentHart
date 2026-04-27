import os
from pathlib import Path

from memory import MemoryStore
from structured_memory import SQLiteMemoryStore


def create_memory_store(base_dir=None):
    """
    Create the configured memory backend.

    Phase 3 defaults to SQLite. Set AGENT_HART_MEMORY_BACKEND=json if you need
    to run against the older memory.json backend for debugging.
    """
    root = Path(base_dir or Path(__file__).resolve().parent)
    backend = os.getenv("AGENT_HART_MEMORY_BACKEND", "sqlite").strip().lower()

    if backend == "json":
        return MemoryStore(root / "memory.json")
    if backend != "sqlite":
        raise ValueError("AGENT_HART_MEMORY_BACKEND must be 'sqlite' or 'json'.")

    return SQLiteMemoryStore(root / "agent_hart.db", legacy_json_path=root / "memory.json")
