"""
TODO Harvester Agent — scans your code for TODO/FIXME comments and adds them
as tasks in Agent Hart memory. Skips duplicates. No paid tokens.
"""
import re
import sys
from datetime import date
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv
load_dotenv(BASE_DIR / ".env")

from memory_factory import create_memory_store

SCAN_ROOTS = [Path("/home/bhart")]
EXTENSIONS = {".py", ".js", ".ts", ".sh", ".md"}
SKIP_DIRS = {"venv", ".git", "__pycache__", "node_modules", ".mypy_cache"}
TODO_PATTERN = re.compile(r"#\s*(TODO|FIXME|HACK|XXX)[:\s]+(.+)", re.IGNORECASE)


def scan_file(path: Path):
    found = []
    try:
        for i, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            m = TODO_PATTERN.search(line)
            if m:
                tag = m.group(1).upper()
                text = m.group(2).strip()
                found.append(f"[{tag}] {path.name}:{i} — {text}")
    except Exception:
        pass
    return found


def scan_all(roots, extensions, skip_dirs):
    items = []
    for root in roots:
        for path in root.rglob("*"):
            if any(part in skip_dirs for part in path.parts):
                continue
            if path.suffix in extensions and path.is_file():
                items.extend(scan_file(path))
    return items


def run():
    memory = create_memory_store(BASE_DIR)
    today = date.today().isoformat()

    print("[todo_harvester] Scanning for TODO/FIXME comments...")
    found = scan_all(SCAN_ROOTS, EXTENSIONS, SKIP_DIRS)

    if not found:
        print("[todo_harvester] No TODOs found.")
        memory.add_audit_event("agent_run", {"agent": "todo_harvester", "date": today, "found": 0})
        return

    existing_tasks = {t["text"] for t in memory.list_tasks()}
    added = 0
    for item in found:
        if item not in existing_tasks:
            memory.add_task(item, due_date=None, priority="low")
            print(f"[todo_harvester] Added: {item}")
            added += 1
        else:
            print(f"[todo_harvester] Already tracked: {item}")

    memory.add_audit_event("agent_run", {
        "agent": "todo_harvester",
        "date": today,
        "found": len(found),
        "added": added,
    })
    print(f"[todo_harvester] Done — {added} new tasks added from {len(found)} TODOs found.")


if __name__ == "__main__":
    run()
