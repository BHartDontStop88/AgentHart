"""Agent Hart — local web dashboard."""
import subprocess
import sys
from datetime import date
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

sys.path.insert(0, str(BASE_DIR))

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from main import (
    build_daily_command_center,
    build_health_checks,
    build_inbox,
    overall_health_status,
)
from memory_factory import create_memory_store

app = FastAPI(title="Agent Hart Dashboard", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _mem():
    return create_memory_store(BASE_DIR)


def _flash(url: str, msg: str, t: str = "ok") -> RedirectResponse:
    return RedirectResponse(f"{url}?msg={quote_plus(msg)}&type={t}", status_code=303)


def _ctx(request: Request, active: str, title: str, **kw) -> dict:
    return {
        "active": active,
        "title": title,
        "msg": request.query_params.get("msg"),
        "msg_type": request.query_params.get("type", "ok"),
        **kw,
    }


# ── Runnable agents whitelist ─────────────────────────────────────────────

RUNNABLE_AGENTS = {
    "agent_watchdog":      "agents/agent_watchdog.py",
    "daily_briefing":      "agents/daily_briefing.py",
    "disk_watchdog":       "agents/disk_watchdog.py",
    "failed_login_watcher": "agents/failed_login_watcher.py",
    "git_activity":        "agents/git_activity.py",
    "github_issues":       "agents/github_issues.py",
    "goal_tracker":        "agents/goal_tracker.py",
    "lesson_reviewer":     "agents/lesson_reviewer.py",
    "memory_digest":       "agents/memory_digest.py",
    "note_organizer":      "agents/note_organizer.py",
    "proxmox_monitor":     "agents/proxmox_monitor.py",
    "task_review":         "agents/task_review.py",
    "todo_harvester":      "agents/todo_harvester.py",
    "weekly_review":       "agents/weekly_review.py",
}

_VENV_PYTHON = str(BASE_DIR / "venv/bin/python")


def _run_agent_subprocess(agent_name: str) -> tuple[bool, str]:
    """Run an agent by name. Returns (success, message)."""
    if agent_name not in RUNNABLE_AGENTS:
        return False, f"Unknown agent: {agent_name}"
    script = str(BASE_DIR / RUNNABLE_AGENTS[agent_name])
    try:
        result = subprocess.run(
            [_VENV_PYTHON, script],
            capture_output=True, text=True, timeout=180,
            cwd=str(BASE_DIR),
        )
        if result.returncode == 0:
            return True, result.stdout.strip() or f"{agent_name} completed."
        stderr = (result.stderr or "").strip()[-300:]
        return False, f"Exit {result.returncode}: {stderr}"
    except subprocess.TimeoutExpired:
        return False, f"{agent_name} timed out after 3 minutes."
    except Exception as exc:
        return False, str(exc)


# ── Page routes ───────────────────────────────────────────────────────────

@app.get("/", response_class=RedirectResponse)
async def root():
    return "/today"


@app.get("/today", response_class=HTMLResponse)
async def today_view(request: Request):
    with _mem() as memory:
        data = build_daily_command_center(memory)
        summaries = memory.list_memory_summaries()
        audit = memory.list_audit_events()
        all_tasks = memory.list_tasks()

    latest_briefing = next(
        (s for s in reversed(summaries) if s.get("scope") == "daily_briefing"), None
    )
    latest_task_review = next(
        (s for s in reversed(summaries) if s.get("scope") == "task_review"), None
    )
    latest_git_activity = next(
        (s for s in reversed(summaries) if s.get("scope") == "git_activity"), None
    )
    system_status = next(
        (
            {**e.get("details", {}), "checked_at": e.get("created_at", "")}
            for e in reversed(audit)
            if e.get("event_type") == "agent_run"
            and e.get("details", {}).get("agent") == "proxmox_monitor"
        ),
        None,
    )
    # Project progress summary
    proj_map: dict[str, dict] = {}
    for t in all_tasks:
        p = t.get("project") or None
        if not p:
            continue
        if p not in proj_map:
            proj_map[p] = {"name": p, "total": 0, "done": 0}
        proj_map[p]["total"] += 1
        if t.get("completed"):
            proj_map[p]["done"] += 1
    for v in proj_map.values():
        v["pct"] = int(100 * v["done"] / v["total"]) if v["total"] else 0
    projects_summary = list(proj_map.values())
    open_tasks_count = sum(1 for t in all_tasks if not t.get("completed"))

    return templates.TemplateResponse(
        request, "today.html",
        _ctx(
            request, "today", "Dashboard",
            today=date.today().isoformat(),
            latest_briefing=latest_briefing,
            latest_task_review=latest_task_review,
            latest_git_activity=latest_git_activity,
            system_status=system_status,
            projects_summary=projects_summary,
            active_projects=len(proj_map),
            open_tasks_count=open_tasks_count,
            autorefresh=True,
            **data,
        ),
    )


@app.get("/inbox", response_class=HTMLResponse)
async def inbox_view(request: Request):
    with _mem() as memory:
        data = build_inbox(memory)
    return templates.TemplateResponse(
        request, "inbox.html",
        _ctx(request, "inbox", "Inbox", **data),
    )


@app.get("/agents", response_class=HTMLResponse)
async def agents_view(request: Request):
    with _mem() as memory:
        agents = memory.list_agents()
        goals = memory.list_goals()
        task_runs = memory.list_task_runs()
        run_reviews = memory.list_run_reviews()
        metrics_summary = memory.agent_metrics_summary()
        summaries = memory.list_memory_summaries()

    agent_stats = {}
    for agent in agents:
        aid = agent["id"]
        reviews = [r for r in run_reviews if r.get("agent_id") == aid]
        success = sum(
            1 for r in reviews if r["outcome"] in {"success", "partial_success"}
        )
        agent_stats[aid] = {
            "goals": sum(1 for g in goals if g.get("agent_id") == aid),
            "runs": sum(1 for r in task_runs if r.get("agent_id") == aid),
            "reviews": len(reviews),
            "success": success,
        }

    # Build per-agent metrics lookup keyed by agent_name
    metrics_by_name = {m["agent_name"]: m for m in metrics_summary}

    # Last meaningful output per agent (from memory_summaries)
    SCOPE_MAP = {
        "daily_briefing": "daily_briefing",
        "git_activity": "git_activity",
        "task_review": "task_review",
        "weekly_review": "weekly_review",
        "lesson_reviewer": "lesson_review",
        "goal_tracker": "goal_review",
        "note_organizer": "note_digest",
        "memory_digest": "memory_digest",
        "failed_login_watcher": "security_review",
    }
    last_output: dict[str, str] = {}
    for agent_name, scope in SCOPE_MAP.items():
        entry = next(
            (s["summary"] for s in reversed(summaries) if s.get("scope") == scope), None
        )
        if entry:
            last_output[agent_name] = entry[:300]

    return templates.TemplateResponse(
        request, "agents.html",
        _ctx(
            request, "agents", "Agents",
            agents=agents,
            goals=goals,
            task_runs=task_runs[-20:],
            run_reviews=run_reviews[-10:],
            agent_stats=agent_stats,
            runnable_agents=RUNNABLE_AGENTS,
            metrics_by_name=metrics_by_name,
            last_output=last_output,
        ),
    )


@app.post("/actions/agents/run/{agent_name}")
async def action_run_agent(agent_name: str):
    ok, msg = _run_agent_subprocess(agent_name)
    if ok:
        return _flash("/agents", f"{agent_name} completed")
    return _flash("/agents", f"{agent_name} failed: {msg[:200]}", "error")


@app.get("/health", response_class=HTMLResponse)
async def health_view(request: Request):
    with _mem() as memory:
        history = memory.list_health_checks()
    latest = history[-1] if history else None
    return templates.TemplateResponse(
        request, "health.html",
        _ctx(
            request, "health", "Health",
            latest=latest,
            history=list(reversed(history))[:20],
        ),
    )


@app.get("/memory", response_class=HTMLResponse)
async def memory_view(request: Request):
    with _mem() as memory:
        notes = list(reversed(memory.list_notes()))[:50]
        lessons = list(reversed(memory.list_lessons()))[:50]
        summaries = list(reversed(memory.list_memory_summaries()))[:20]
        tool_results = list(reversed(memory.list_tool_results()))[:20]
    return templates.TemplateResponse(
        request, "memory.html",
        _ctx(
            request, "memory", "Memory",
            notes=notes,
            lessons=lessons,
            summaries=summaries,
            tool_results=tool_results,
        ),
    )


# ── Action routes ─────────────────────────────────────────────────────────

@app.post("/actions/tasks/add")
async def action_add_task(
    text: str = Form(...),
    due_date: str = Form(""),
    priority: str = Form("normal"),
):
    text = text.strip()
    if not text:
        return _flash("/today", "Task text is required", "error")
    with _mem() as memory:
        memory.add_task(text, due_date=due_date.strip() or None, priority=priority)
    return _flash("/today", "Task added")


@app.post("/actions/tasks/{task_id}/complete")
async def action_complete_task(task_id: str, back: str = Form("")):
    with _mem() as memory:
        ok = _complete_task_by_id(memory, task_id)
    dest = back.strip() or "/today"
    if ok:
        return _flash(dest, "Task completed")
    return _flash(dest, "Task not found", "error")


@app.get("/tasks/{task_id}/edit", response_class=HTMLResponse)
async def task_edit_view(request: Request, task_id: str):
    with _mem() as memory:
        task = memory.get_task_by_id(task_id)
    if not task:
        return _flash("/today", "Task not found", "error")
    return templates.TemplateResponse(
        request, "task_edit.html",
        _ctx(request, "today", "Edit Task", task=task),
    )


@app.post("/actions/tasks/{task_id}/edit")
async def action_edit_task(
    task_id: str,
    text: str = Form(...),
    due_date: str = Form(""),
    priority: str = Form("normal"),
    project: str = Form(""),
    back: str = Form(""),
):
    text = text.strip()
    if not text:
        return _flash(f"/tasks/{task_id}/edit", "Task text is required", "error")
    with _mem() as memory:
        ok = memory.update_task(
            task_id,
            text=text,
            due_date=due_date.strip() or None,
            priority=priority,
            project=project.strip() or None,
        )
    dest = back.strip() or "/today"
    if ok:
        return _flash(dest, "Task updated")
    return _flash(dest, "Task not found", "error")


@app.post("/actions/tasks/{task_id}/delete")
async def action_delete_task(task_id: str, back: str = Form("")):
    with _mem() as memory:
        ok = memory.delete_task_by_id(task_id)
    dest = back.strip() or "/today"
    if ok:
        return _flash(dest, "Task deleted")
    return _flash(dest, "Task not found", "error")


@app.post("/actions/approvals/{approval_id}/approve")
async def action_approve(approval_id: str, reason: str = Form("")):
    with _mem() as memory:
        result = memory.decide_approval(approval_id, approved=True, reason=reason or None)
    if result:
        return _flash("/inbox", "Approved")
    return _flash("/inbox", "Approval not found", "error")


@app.post("/actions/approvals/{approval_id}/reject")
async def action_reject(approval_id: str, reason: str = Form("")):
    with _mem() as memory:
        result = memory.decide_approval(approval_id, approved=False, reason=reason or None)
    if result:
        return _flash("/inbox", "Rejected")
    return _flash("/inbox", "Approval not found", "error")


@app.post("/actions/notes/add")
async def action_add_note(text: str = Form(...)):
    text = text.strip()
    if not text:
        return _flash("/memory", "Note text is required", "error")
    with _mem() as memory:
        memory.add_note(text)
    return _flash("/memory", "Note saved")


@app.post("/actions/lessons/add")
async def action_add_lesson(
    text: str = Form(...),
    source: str = Form("user"),
):
    text = text.strip()
    if not text:
        return _flash("/memory", "Lesson text is required", "error")
    with _mem() as memory:
        memory.add_lesson(text, source=source.strip() or "user")
    return _flash("/memory", "Lesson saved")


@app.post("/actions/health/run")
async def action_run_health():
    from tools import ToolRegistry
    tools = ToolRegistry(
        policy_path=str(BASE_DIR / "policy.json"),
        reports_dir=str(BASE_DIR / "reports"),
    )
    with _mem() as memory:
        checks = build_health_checks(memory, tools, BASE_DIR)
        overall = overall_health_status(checks)
        memory.add_health_check(overall, checks)
    return _flash("/health", f"Health check complete: {overall}")


@app.post("/actions/agents/add")
async def action_add_agent(
    name: str = Form(...),
    role: str = Form("general"),
    autonomy_level: str = Form("supervised"),
    max_steps: str = Form("5"),
):
    name = name.strip()
    if not name:
        return _flash("/agents", "Agent name is required", "error")
    try:
        steps = max(1, int(max_steps))
    except (ValueError, TypeError):
        steps = 5
    with _mem() as memory:
        memory.add_agent(
            name,
            role=role.strip() or "general",
            autonomy_level=autonomy_level.strip() or "supervised",
            max_steps=steps,
        )
    return _flash("/agents", f"Agent '{name}' created")


@app.post("/actions/goals/add")
async def action_add_goal(
    agent_id: str = Form(""),
    text: str = Form(...),
):
    text = text.strip()
    if not text:
        return _flash("/agents", "Goal text is required", "error")
    with _mem() as memory:
        memory.add_goal(agent_id=agent_id.strip() or None, text=text)
    return _flash("/agents", "Goal added")


@app.post("/actions/checkpoints/add")
async def action_add_checkpoint(
    agent_id: str = Form(...),
    goal_id: str = Form(""),
):
    if not agent_id.strip():
        return _flash("/agents", "Agent is required for checkpoint", "error")
    with _mem() as memory:
        run = memory.add_task_run(
            agent_id=agent_id.strip(),
            goal_id=goal_id.strip() or None,
            status="planning",
        )
    return _flash("/agents", f"Checkpoint created: {run['id'][:8]}")


# ── Helpers ───────────────────────────────────────────────────────────────

def _complete_task_by_id(memory, task_id: str) -> bool:
    tasks = memory.list_tasks()
    for i, task in enumerate(tasks):
        if task["id"] == task_id:
            return memory.complete_task(i)
    return False


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("dashboard:app", host="127.0.0.1", port=8765, reload=True)


# ── Metrics page ──────────────────────────────────────────────────────────

@app.get("/metrics", response_class=HTMLResponse)
async def metrics_view(request: Request):
    with _mem() as memory:
        summary = memory.agent_metrics_summary()
        recent = memory.recent_agent_runs(limit=60)

    # System-wide aggregates
    total_runs = sum(a["total_runs"] for a in summary)
    total_tokens = sum((a["total_tokens"] or 0) for a in summary)
    total_errors = sum(a["error_runs"] for a in summary)
    overall_success = round(100 * (total_runs - total_errors) / total_runs, 1) if total_runs else 0
    runs_today = sum(
        1 for r in recent
        if r["run_started_at"] and r["run_started_at"][:10] == date.today().isoformat()
    )
    tokens_today = sum(
        (r.get("prompt_tokens") or 0) + (r.get("response_tokens") or 0)
        for r in recent
        if r["run_started_at"] and r["run_started_at"][:10] == date.today().isoformat()
    )

    return templates.TemplateResponse(
        request, "metrics.html",
        _ctx(
            request, "metrics", "Agent Metrics",
            summary=summary,
            recent=recent,
            total_runs=total_runs,
            total_tokens=total_tokens,
            total_errors=total_errors,
            overall_success=overall_success,
            runs_today=runs_today,
            tokens_today=tokens_today,
            autorefresh=True,
        ),
    )


# ── Workflow phase definitions ─────────────────────────────────────────────

PM_PHASES = [
    {"key": "initiation", "title": "Initiation",
     "prompt": "Define the project. What problem are you solving, who are the stakeholders, and what does success look like?",
     "placeholder": "e.g. We need to assess the security posture of our external API. Stakeholders: security team, dev team, CTO. Success = full pentest report with remediation steps by end of quarter."},
    {"key": "planning", "title": "Planning",
     "prompt": "Define scope, timeline, resources, and risks. What will you do, when, with what, and what could go wrong?",
     "placeholder": "e.g. Scope: 3 external API endpoints. Timeline: 2 weeks. Team: 2 analysts. Risks: Limited test window, possible rate limiting..."},
    {"key": "execution", "title": "Execution",
     "prompt": "Describe the work being done. What tasks are in progress, what findings have emerged so far?",
     "placeholder": "e.g. Completed endpoint enumeration. Found 2 unauthenticated endpoints. Currently testing auth bypass scenarios..."},
    {"key": "monitoring", "title": "Monitoring & Control",
     "prompt": "How is progress tracking against the plan? Any blockers, scope changes, or risks that materialized?",
     "placeholder": "e.g. On track for timeline. Discovered additional endpoints not in original scope. Added 3 days to schedule with stakeholder approval..."},
    {"key": "closure", "title": "Closure",
     "prompt": "Summarize outcomes, deliverables completed, lessons learned, and any open items for follow-up.",
     "placeholder": "e.g. Delivered 12-page pentest report. Found 3 critical, 5 medium issues. Lessons: need better test environment isolation..."},
]

ANALYTICS_PHASES = [
    {"key": "ask", "title": "Ask",
     "prompt": "Define the business question. What problem are you trying to solve with data? What decisions will this analysis inform?",
     "placeholder": "e.g. Why is customer churn increasing in Q1? We need to understand if it's price, UX, or support issues to decide where to invest next quarter."},
    {"key": "prepare", "title": "Prepare",
     "prompt": "Describe your data sources. What data do you have, where does it come from, and what are its limitations?",
     "placeholder": "e.g. CRM export (12 months), support ticket data, billing logs. Limitations: missing data for customers who churned before 2025, no NPS scores."},
    {"key": "process", "title": "Process",
     "prompt": "How will you clean and transform the data? What steps are needed before analysis?",
     "placeholder": "e.g. Remove duplicate records, fill missing tenure values with median, convert timestamps to UTC, join CRM and billing tables on customer_id..."},
    {"key": "analyze", "title": "Analyze",
     "prompt": "What analysis did you run? What patterns, correlations, or anomalies did you find?",
     "placeholder": "e.g. Churn rate 3x higher in customers with 2+ support tickets in first 30 days. No correlation with pricing tier. Strong signal in onboarding completion rate..."},
    {"key": "share", "title": "Share",
     "prompt": "How will you communicate findings? Who is the audience, what format, and what are the key takeaways?",
     "placeholder": "e.g. Presenting to product and CX teams. Dashboard in Looker + exec summary slide. Key message: fix onboarding flow = estimated 18% churn reduction..."},
    {"key": "act", "title": "Act",
     "prompt": "What actions will be taken based on the analysis? Define specific next steps, owners, and timelines.",
     "placeholder": "e.g. Product: redesign onboarding checklist by May 1 (owner: Sarah). CX: flag high-risk accounts at day 14 (owner: Marcus). Reanalyze in 60 days..."},
]

BUILD_PHASES = [
    {"key": "role", "title": "Role & Identity",
     "prompt": "Define who this agent is. What is its purpose, personality, and primary responsibility?",
     "placeholder": "e.g. You are a security recon assistant. Your primary job is to enumerate attack surface, identify vulnerabilities, and produce structured findings reports. You are methodical, precise, and never take action without explicit approval."},
    {"key": "commands", "title": "Core Commands",
     "prompt": "List the key commands and capabilities this agent should know about. What can it do?",
     "placeholder": "e.g. /recon <target> — run passive recon\n/scan <host> — enumerate open ports\n/report — generate findings report\n/approve — confirm before running any tool\nKnows: nmap, nslookup, whois, curl"},
    {"key": "boundaries", "title": "Boundaries",
     "prompt": "What must this agent NEVER do? Define hard limits, off-limits actions, and escalation rules.",
     "placeholder": "e.g. NEVER run active exploits without written approval. NEVER exfiltrate data outside the test environment. NEVER modify files outside /reports. Always ask before running any tool with network access. Escalate to human if uncertain."},
    {"key": "style", "title": "Code Style",
     "prompt": "How should this agent write code? Language preferences, formatting rules, documentation standards.",
     "placeholder": "e.g. Python 3.11+. No shell=True. Always use subprocess with list args. Type hints on all functions. No comments unless non-obvious. Prefer pathlib over os.path. Tests in pytest."},
    {"key": "security", "title": "Security Guard Rails",
     "prompt": "Define the security rules this agent must enforce. Input validation, output sanitization, safe defaults.",
     "placeholder": "e.g. Validate all user input against allowlist. Never log credentials or tokens. Sanitize all shell arguments. Reject targets outside approved domain list. Rate-limit outbound requests. Log all tool invocations to audit trail."},
]


def _build_phase_states(phase_defs, saved_phases):
    saved = {p["phase_key"]: p for p in saved_phases}
    result = []
    unlocked = True
    for i, pdef in enumerate(phase_defs):
        key = pdef["key"]
        if key in saved and saved[key]["status"] == "complete":
            result.append({**pdef, "state": "complete",
                           "user_content": saved[key]["user_content"],
                           "ai_suggestion": saved[key].get("ai_suggestion")})
        elif unlocked:
            result.append({**pdef, "state": "active", "user_content": "", "ai_suggestion": None})
            unlocked = False
        else:
            result.append({**pdef, "state": "locked", "user_content": "", "ai_suggestion": None})
    return result


def _phase_ai_prompt(phase_defs, phase_key, user_content, session_name, next_phase=None):
    from ai import ollama_chat
    current = next((p for p in phase_defs if p["key"] == phase_key), None)
    if not current:
        return ""
    prompt = (
        f"Project/Analysis: {session_name}\n"
        f"Phase completed: {current['title']}\n"
        f"User's input:\n{user_content}\n\n"
    )
    if next_phase:
        prompt += (
            f"The next phase is: {next_phase['title']}\n"
            f"Briefly (3-5 bullet points) review what was just submitted and suggest "
            f"what to focus on in the next phase. Be specific and actionable. Plain text."
        )
    else:
        prompt += (
            "This was the final phase. Write a 3-5 sentence summary of the entire "
            "project/analysis based on what was completed. Plain text."
        )
    return ollama_chat(prompt)


# ── PM Lifecycle routes ────────────────────────────────────────────────────

@app.get("/lifecycle", response_class=HTMLResponse)
async def lifecycle_list(request: Request):
    with _mem() as memory:
        sessions = memory.list_workflow_sessions("pm_lifecycle")
    return templates.TemplateResponse(
        request, "lifecycle.html",
        _ctx(request, "lifecycle", "PM Lifecycle", sessions=sessions, session=None, phases=[]),
    )

@app.post("/lifecycle/new")
async def lifecycle_new(name: str = Form(...)):
    with _mem() as memory:
        s = memory.create_workflow_session(name.strip(), "pm_lifecycle")
    return RedirectResponse(f"/lifecycle/{s['id']}", status_code=303)

@app.get("/lifecycle/{session_id}", response_class=HTMLResponse)
async def lifecycle_session(request: Request, session_id: str):
    with _mem() as memory:
        session = memory.get_workflow_session(session_id)
        saved = memory.get_workflow_phases(session_id)
    if not session:
        return RedirectResponse("/lifecycle")
    phases = _build_phase_states(PM_PHASES, saved)
    return templates.TemplateResponse(
        request, "lifecycle.html",
        _ctx(request, "lifecycle", session["name"], session=session, phases=phases, sessions=[]),
    )

@app.post("/lifecycle/{session_id}/phase")
async def lifecycle_submit_phase(
    session_id: str,
    phase_key: str = Form(...),
    phase_order: int = Form(...),
    user_content: str = Form(...),
):
    with _mem() as memory:
        session = memory.get_workflow_session(session_id)
        if not session:
            return RedirectResponse("/lifecycle")
        # Save content immediately so it's never lost to an Ollama timeout
        memory.save_workflow_phase(session_id, phase_key, phase_order, user_content.strip(), None)

    try:
        next_phase = next((p for p in PM_PHASES if PM_PHASES.index(p) == phase_order), None)
        suggestion = _phase_ai_prompt(PM_PHASES, phase_key, user_content, session["name"], next_phase)
    except Exception:
        suggestion = None

    with _mem() as memory:
        if suggestion:
            memory.save_workflow_phase(session_id, phase_key, phase_order, user_content.strip(), suggestion)
        saved = memory.get_workflow_phases(session_id)
        if len(saved) == len(PM_PHASES):
            memory.complete_workflow_session(session_id)
            memory.add_memory_summary(scope="pm_lifecycle_complete", summary=f"Project: {session['name']}")
    return RedirectResponse(f"/lifecycle/{session_id}", status_code=303)


# ── Data Analytics routes ──────────────────────────────────────────────────

@app.get("/analytics", response_class=HTMLResponse)
async def analytics_list(request: Request):
    with _mem() as memory:
        sessions = memory.list_workflow_sessions("data_analytics")
    return templates.TemplateResponse(
        request, "analytics.html",
        _ctx(request, "analytics", "Data Analytics", sessions=sessions, session=None, phases=[]),
    )

@app.post("/analytics/new")
async def analytics_new(name: str = Form(...)):
    with _mem() as memory:
        s = memory.create_workflow_session(name.strip(), "data_analytics")
    return RedirectResponse(f"/analytics/{s['id']}", status_code=303)

@app.get("/analytics/{session_id}", response_class=HTMLResponse)
async def analytics_session(request: Request, session_id: str):
    with _mem() as memory:
        session = memory.get_workflow_session(session_id)
        saved = memory.get_workflow_phases(session_id)
    if not session:
        return RedirectResponse("/analytics")
    phases = _build_phase_states(ANALYTICS_PHASES, saved)
    return templates.TemplateResponse(
        request, "analytics.html",
        _ctx(request, "analytics", session["name"], session=session, phases=phases, sessions=[]),
    )

@app.post("/analytics/{session_id}/phase")
async def analytics_submit_phase(
    session_id: str,
    phase_key: str = Form(...),
    phase_order: int = Form(...),
    user_content: str = Form(...),
):
    with _mem() as memory:
        session = memory.get_workflow_session(session_id)
        if not session:
            return RedirectResponse("/analytics")
        memory.save_workflow_phase(session_id, phase_key, phase_order, user_content.strip(), None)

    try:
        next_phase = next((p for p in ANALYTICS_PHASES if ANALYTICS_PHASES.index(p) == phase_order), None)
        suggestion = _phase_ai_prompt(ANALYTICS_PHASES, phase_key, user_content, session["name"], next_phase)
    except Exception:
        suggestion = None

    with _mem() as memory:
        if suggestion:
            memory.save_workflow_phase(session_id, phase_key, phase_order, user_content.strip(), suggestion)
        saved = memory.get_workflow_phases(session_id)
        if len(saved) == len(ANALYTICS_PHASES):
            memory.complete_workflow_session(session_id)
    return RedirectResponse(f"/analytics/{session_id}", status_code=303)


# ── Agent Builder routes ───────────────────────────────────────────────────

@app.get("/build", response_class=HTMLResponse)
async def build_list(request: Request):
    with _mem() as memory:
        sessions = memory.list_workflow_sessions("agent_build")
    return templates.TemplateResponse(
        request, "build.html",
        _ctx(request, "build", "Agent Builder", sessions=sessions, session=None, phases=[], exported_md=None, all_complete=False),
    )

@app.post("/build/new")
async def build_new(name: str = Form(...)):
    with _mem() as memory:
        s = memory.create_workflow_session(name.strip(), "agent_build")
    return RedirectResponse(f"/build/{s['id']}", status_code=303)

@app.get("/build/{session_id}", response_class=HTMLResponse)
async def build_session(request: Request, session_id: str):
    with _mem() as memory:
        session = memory.get_workflow_session(session_id)
        saved = memory.get_workflow_phases(session_id)
    if not session:
        return RedirectResponse("/build")
    phases = _build_phase_states(BUILD_PHASES, saved)
    all_complete = all(p["state"] == "complete" for p in phases)
    with _mem() as memory:
        summaries = memory.list_memory_summaries()
    exported_md = next(
        (s["summary"] for s in reversed(summaries)
         if s.get("scope") == f"agent_build_md_{session_id}"), None
    )
    return templates.TemplateResponse(
        request, "build.html",
        _ctx(request, "build", session["name"], session=session, phases=phases,
             sessions=[], exported_md=exported_md, all_complete=all_complete),
    )

@app.post("/build/{session_id}/phase")
async def build_submit_phase(
    session_id: str,
    phase_key: str = Form(...),
    phase_order: int = Form(...),
    user_content: str = Form(...),
):
    with _mem() as memory:
        session = memory.get_workflow_session(session_id)
        if not session:
            return RedirectResponse("/build")
        memory.save_workflow_phase(session_id, phase_key, phase_order, user_content.strip(), None)

    try:
        next_phase = next((p for p in BUILD_PHASES if BUILD_PHASES.index(p) == phase_order), None)
        suggestion = _phase_ai_prompt(BUILD_PHASES, phase_key, user_content, session["name"], next_phase)
    except Exception:
        suggestion = None

    if suggestion:
        with _mem() as memory:
            memory.save_workflow_phase(session_id, phase_key, phase_order, user_content.strip(), suggestion)
    return RedirectResponse(f"/build/{session_id}", status_code=303)

@app.post("/build/{session_id}/generate")
async def build_generate(session_id: str):
    with _mem() as memory:
        session = memory.get_workflow_session(session_id)
        saved = memory.get_workflow_phases(session_id)
    if not session:
        return RedirectResponse("/build")
    data = {p["phase_key"]: p["user_content"] for p in saved}
    md = _generate_claude_md(session["name"], data)
    with _mem() as memory:
        memory.add_memory_summary(scope=f"agent_build_md_{session_id}", summary=md)
        memory.complete_workflow_session(session_id)
    return RedirectResponse(f"/build/{session_id}", status_code=303)

@app.post("/build/{session_id}/save")
async def build_save_file(session_id: str, file_path: str = Form(...)):
    with _mem() as memory:
        summaries = memory.list_memory_summaries()
    md = next(
        (s["summary"] for s in reversed(summaries)
         if s.get("scope") == f"agent_build_md_{session_id}"), None
    )
    if not md:
        return _flash(f"/build/{session_id}", "Generate the MD file first", "error")
    # Sandbox: strip any directory component — writes go to BASE_DIR/exports/ only
    exports_dir = BASE_DIR / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(file_path.strip()).name
    if not safe_name or safe_name.startswith("."):
        return _flash(f"/build/{session_id}", "Invalid filename", "error")
    path = exports_dir / safe_name
    try:
        path.write_text(md, encoding="utf-8")
    except Exception as exc:
        return _flash(f"/build/{session_id}", f"Could not save: {exc}", "error")
    return _flash(f"/build/{session_id}", f"Saved to exports/{safe_name}")


def _generate_claude_md(agent_name: str, data: dict) -> str:
    from ai import ollama_chat
    sections = "\n\n".join(
        f"## {k.upper()}\n{v}" for k, v in data.items() if v
    )
    prompt = (
        f"Generate a complete CLAUDE.md file for an AI agent named: {agent_name}\n\n"
        "Use the sections below as source material. Format as a proper CLAUDE.md with these headings:\n"
        "# <Agent Name>\n"
        "## Role\n## Core Commands\n## Boundaries\n## Code Style\n## Security Guard Rails\n\n"
        "Write clearly and precisely. This file will be read by Claude Code to configure agent behavior.\n\n"
        f"Source material:\n{sections}"
    )
    return ollama_chat(prompt)


# ── Projects page ─────────────────────────────────────────────────────────

@app.get("/projects", response_class=HTMLResponse)
async def projects_view(request: Request):
    with _mem() as memory:
        all_tasks = memory.list_tasks()

    projects: dict[str, dict] = {}
    for task in all_tasks:
        p = task.get("project") or "General"
        if p not in projects:
            projects[p] = {"tasks": [], "done": 0, "open": 0}
        projects[p]["tasks"].append(task)
        if task.get("completed"):
            projects[p]["done"] += 1
        else:
            projects[p]["open"] += 1

    return templates.TemplateResponse(
        request, "projects.html",
        _ctx(request, "projects", "Projects", projects=projects, autorefresh=True),
    )


@app.post("/actions/projects/add-task")
async def action_project_add_task(
    project: str = Form(...),
    text: str = Form(...),
    priority: str = Form("normal"),
    due_date: str = Form(""),
):
    with _mem() as memory:
        memory.add_task(
            text.strip(),
            due_date=due_date.strip() or None,
            priority=priority,
            project=project.strip() or None,
        )
    return _flash("/projects", f"Task added to {project}")


# ── JSON API ──────────────────────────────────────────────────────────────

@app.get("/api/status", response_class=JSONResponse)
async def api_status():
    with _mem() as memory:
        tasks = memory.list_tasks()
        metrics = memory.agent_metrics_summary()
    open_t = [t for t in tasks if not t.get("completed")]
    overdue = [t for t in open_t if t.get("due_date") and t["due_date"] < date.today().isoformat()]
    return {
        "ok": True,
        "date": date.today().isoformat(),
        "tasks": {"open": len(open_t), "overdue": len(overdue), "total": len(tasks)},
        "agents": len(metrics),
        "total_runs": sum(m["total_runs"] for m in metrics),
        "overall_success_pct": round(
            sum(m["success_rate"] * m["total_runs"] for m in metrics) /
            max(sum(m["total_runs"] for m in metrics), 1), 1
        ),
    }


@app.get("/api/tasks", response_class=JSONResponse)
async def api_tasks(project: str = "", status: str = ""):
    with _mem() as memory:
        tasks = memory.list_tasks()
    if project:
        tasks = [t for t in tasks if (t.get("project") or "") == project]
    if status == "open":
        tasks = [t for t in tasks if not t.get("completed")]
    elif status == "done":
        tasks = [t for t in tasks if t.get("completed")]
    return tasks


@app.get("/api/metrics", response_class=JSONResponse)
async def api_metrics():
    with _mem() as memory:
        summary = memory.agent_metrics_summary()
        recent = memory.recent_agent_runs(limit=20)
    return {"summary": summary, "recent": recent}


@app.get("/api/health", response_class=JSONResponse)
async def api_health():
    with _mem() as memory:
        checks = memory.list_health_checks()
    latest = checks[-1] if checks else None
    return {
        "overall": latest["overall_status"] if latest else "unknown",
        "checked_at": latest["created_at"] if latest else None,
        "checks": latest["checks"] if latest else [],
    }


# ── Search ────────────────────────────────────────────────────────────────

@app.get("/search", response_class=HTMLResponse)
async def search_view(request: Request, q: str = ""):
    results = {"tasks": [], "notes": [], "summaries": []}
    q = q.strip()
    if q:
        with _mem() as memory:
            results = memory.search(q)
    total = sum(len(v) for v in results.values())
    return templates.TemplateResponse(
        request, "search.html",
        _ctx(request, "", "Search", q=q, results=results, total=total),
    )


# ── Reports page ───────────────────────────────────────────────────────────

@app.get("/reports", response_class=HTMLResponse)
async def reports_view(request: Request):
    categories = {}
    reports_root = BASE_DIR / "reports"
    if reports_root.exists():
        for category_dir in sorted(reports_root.iterdir()):
            if category_dir.is_dir():
                files = sorted(category_dir.glob("*.md"), reverse=True)
                categories[category_dir.name] = [
                    {"name": f.stem, "path": f"reports/{category_dir.name}/{f.name}"}
                    for f in files
                ]
    with _mem() as memory:
        summaries = memory.list_memory_summaries()
        audit = memory.list_audit_events()

    agent_runs = [
        e for e in reversed(audit)
        if e.get("event_type") == "agent_run"
    ][:20]
    agent_alerts = [
        e for e in reversed(audit)
        if e.get("event_type") == "agent_alert"
    ][:10]

    return templates.TemplateResponse(
        request, "reports.html",
        _ctx(
            request, "reports", "Reports",
            categories=categories,
            summaries=list(reversed(summaries))[:30],
            agent_runs=agent_runs,
            agent_alerts=agent_alerts,
        ),
    )


@app.get("/reports/{category}/{filename}", response_class=HTMLResponse)
async def report_file_view(request: Request, category: str, filename: str):
    import re
    import markdown as _md
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", category) or not re.fullmatch(r"[a-zA-Z0-9_.-]+", filename):
        return HTMLResponse("Invalid path", status_code=400)
    path = BASE_DIR / "reports" / category / filename
    if not path.exists() or path.suffix != ".md":
        return HTMLResponse("Report not found", status_code=404)
    raw = path.read_text(encoding="utf-8")
    content_html = _md.markdown(raw, extensions=["fenced_code", "tables", "nl2br"])
    return templates.TemplateResponse(
        request, "report_detail.html",
        _ctx(request, "reports", filename, content_html=content_html, back_category=category),
    )
