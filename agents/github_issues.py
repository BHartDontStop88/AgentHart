"""
GitHub Issues Agent — syncs open GitHub issues from configured repos into Agent Hart tasks.
Requires GITHUB_TOKEN and GITHUB_REPOS in .env. No paid LLM tokens.

.env config:
  GITHUB_TOKEN=ghp_...
  GITHUB_REPOS=owner/repo1,owner/repo2
"""
import json
import sys
import urllib.request
import urllib.error
from datetime import date
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv
load_dotenv(BASE_DIR / ".env")

import os
from agents.metrics import AgentRun
from memory_factory import create_memory_store

GITHUB_API = "https://api.github.com"
GITHUB_TAG = "github_issue"


def _api_get(path: str, token: str) -> list | dict:
    url = f"{GITHUB_API}{path}?per_page=50&state=open"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode())


def _issue_task_text(repo: str, issue: dict) -> str:
    return f"[{repo}#{issue['number']}] {issue['title']}"


def run():
    token = os.getenv("GITHUB_TOKEN", "").strip()
    repos_raw = os.getenv("GITHUB_REPOS", "").strip()

    if not token:
        print("[github_issues] GITHUB_TOKEN not set — skipping.")
        return
    if not repos_raw:
        print("[github_issues] GITHUB_REPOS not set — skipping.")
        return

    repos = [r.strip() for r in repos_raw.split(",") if r.strip()]
    memory = create_memory_store(BASE_DIR)
    today = date.today().isoformat()

    # Build set of issue identifiers already in tasks to avoid duplicates
    existing_tasks = memory.list_tasks()
    existing_texts = {t["text"] for t in existing_tasks}

    imported = 0
    skipped = 0
    errors = []

    with AgentRun("github_issues", memory) as run:
        for repo in repos:
            print(f"[github_issues] Fetching open issues from {repo}...")
            try:
                issues = _api_get(f"/repos/{repo}/issues", token)
            except urllib.error.HTTPError as exc:
                msg = f"{repo}: HTTP {exc.code}"
                errors.append(msg)
                print(f"[github_issues] {msg}")
                continue
            except Exception as exc:
                msg = f"{repo}: {exc}"
                errors.append(msg)
                print(f"[github_issues] {msg}")
                continue

            # GitHub issues endpoint includes PRs; filter those out
            real_issues = [i for i in issues if "pull_request" not in i]
            print(f"[github_issues]   {len(real_issues)} open issues")

            for issue in real_issues:
                text = _issue_task_text(repo, issue)
                if text in existing_texts:
                    skipped += 1
                    continue
                due = None
                if issue.get("milestone") and issue["milestone"].get("due_on"):
                    due = issue["milestone"]["due_on"][:10]
                # Map GitHub labels to priority
                labels = [lb["name"].lower() for lb in issue.get("labels", [])]
                if any(l in ("critical", "urgent", "p0", "p1") for l in labels):
                    priority = "high"
                elif any(l in ("low", "p3", "p4", "nice-to-have") for l in labels):
                    priority = "low"
                else:
                    priority = "normal"

                memory.add_task(text, due_date=due, priority=priority, project=repo)
                existing_texts.add(text)
                imported += 1
                run.add_output(1)

        if errors:
            run.set_error("; ".join(errors))

    print(f"[github_issues] Done. Imported: {imported} | Skipped (existing): {skipped}")
    if errors:
        print(f"[github_issues] Errors: {errors}")

    memory.add_audit_event("agent_run", {
        "agent": "github_issues",
        "date": today,
        "imported": imported,
        "skipped": skipped,
    })


if __name__ == "__main__":
    run()
