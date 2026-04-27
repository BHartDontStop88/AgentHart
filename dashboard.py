"""Agent Hart — local web dashboard."""
import sys
from datetime import date
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

sys.path.insert(0, str(BASE_DIR))

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
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


# ── Page routes ───────────────────────────────────────────────────────────

@app.get("/", response_class=RedirectResponse)
async def root():
    return "/today"


@app.get("/today", response_class=HTMLResponse)
async def today_view(request: Request):
    with _mem() as memory:
        data = build_daily_command_center(memory)
    return templates.TemplateResponse(
        request, "today.html",
        _ctx(request, "today", "Today", today=date.today().isoformat(), **data),
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

    return templates.TemplateResponse(
        request, "agents.html",
        _ctx(
            request, "agents", "Agents",
            agents=agents,
            goals=goals,
            task_runs=task_runs[-20:],
            run_reviews=run_reviews[-10:],
            agent_stats=agent_stats,
        ),
    )


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
async def action_complete_task(task_id: str):
    with _mem() as memory:
        ok = _complete_task_by_id(memory, task_id)
    if ok:
        return _flash("/today", "Task completed")
    return _flash("/today", "Task not found", "error")


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
