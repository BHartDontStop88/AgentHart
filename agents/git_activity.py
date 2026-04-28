"""
Git Activity Agent — summarizes recent commits across all local git repos using gemma4.
Saves a daily digest to memory. No paid tokens.
"""
import subprocess
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

SEARCH_ROOTS = [Path("/home/bhart")]
MAX_DEPTH = 4


def find_git_repos(roots, max_depth):
    repos = []
    for root in roots:
        for git_dir in root.rglob(".git"):
            if git_dir.is_dir():
                depth = len(git_dir.relative_to(root).parts)
                if depth <= max_depth:
                    repos.append(git_dir.parent)
    return repos


def recent_commits(repo_path, hours=24):
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", f"--since={hours} hours ago", "--all"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def run():
    memory = create_memory_store(BASE_DIR)
    today = date.today().isoformat()

    repos = find_git_repos(SEARCH_ROOTS, MAX_DEPTH)
    print(f"[git_activity] Found {len(repos)} git repo(s)")

    activity_blocks = []
    for repo in repos:
        commits = recent_commits(repo)
        if commits:
            activity_blocks.append(f"Repo: {repo.name}\n{commits}")

    if not activity_blocks:
        print("[git_activity] No commits in the last 24 hours.")
        memory.add_audit_event("agent_run", {"agent": "git_activity", "date": today, "commits": 0})
        return

    activity_text = "\n\n".join(activity_blocks)
    prompt = (
        f"Today is {today}. Summarize this git activity from the last 24 hours.\n"
        "For each repo:\n"
        "1. What was the main focus of work?\n"
        "2. Any noteworthy patterns or concerns?\n"
        "Keep it brief and plain text.\n\n"
        f"Activity:\n{activity_text}"
    )

    print("[git_activity] Summarizing commits...")
    with AgentRun("git_activity", memory) as run:
        summary, meta = ollama_chat_with_meta(prompt)
        run.record_llm(meta)
        run.add_output(1)
    print(summary)

    memory.add_memory_summary(scope="git_activity", summary=summary)
    memory.add_audit_event("agent_run", {"agent": "git_activity", "date": today})
    print("[git_activity] Digest saved to memory.")


if __name__ == "__main__":
    run()
