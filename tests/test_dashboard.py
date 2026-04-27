"""Tests for the Agent Hart web dashboard (dashboard.py)."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import dashboard
from structured_memory import SQLiteMemoryStore


POLICY = {
    "allow_shell_commands": False,
    "require_approval_for_network_tools": True,
    "max_target_length": 200,
    "allowed_domains": ["localhost"],
    "blocked_actions": [],
    "tools": {
        "ping": {"enabled": True, "requires_approval": True, "risk_level": "low"},
        "nslookup": {"enabled": True, "requires_approval": True, "risk_level": "low"},
        "report": {"enabled": True, "requires_approval": False, "risk_level": "low"},
    },
}


@pytest.fixture()
def tmp_env(tmp_path, monkeypatch):
    """Redirect BASE_DIR to a temp directory with a minimal policy.json."""
    (tmp_path / "policy.json").write_text(json.dumps(POLICY))
    (tmp_path / "reports").mkdir()
    monkeypatch.setattr(dashboard, "BASE_DIR", tmp_path)
    return tmp_path


@pytest.fixture()
def client(tmp_env):
    return TestClient(dashboard.app, follow_redirects=True)


@pytest.fixture()
def seeded_client(tmp_env):
    mem = SQLiteMemoryStore(tmp_env / "agent_hart.db")
    mem.add_task("Write tests", due_date="2026-01-01", priority="high")
    mem.add_task("Future task")
    mem.add_note("Test note")
    mem.add_lesson("Always test", source="user")
    agent = mem.add_agent("Recon", role="recon", allowed_tools=["ping"])
    mem.add_goal(agent["id"], "Map the lab")
    mem.add_approval_request(
        "run_tool", "Ping localhost", {"tool": "ping", "target": "localhost"},
        risk_level="low", requires_approval=True,
    )
    mem.close()
    return TestClient(dashboard.app, follow_redirects=True)


# ── Page routes return 200 ────────────────────────────────────────────────

def test_today_renders(client):
    r = client.get("/today")
    assert r.status_code == 200
    assert b"Today" in r.content
    assert b"Due Today" in r.content


def test_inbox_renders(client):
    r = client.get("/inbox")
    assert r.status_code == 200
    assert b"Inbox" in r.content
    assert b"Pending Approvals" in r.content


def test_agents_renders(client):
    r = client.get("/agents")
    assert r.status_code == 200
    assert b"Agents" in r.content


def test_health_renders(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert b"Health" in r.content
    assert b"Run Health Check" in r.content


def test_memory_renders(client):
    r = client.get("/memory")
    assert r.status_code == 200
    assert b"Memory" in r.content
    assert b"Notes" in r.content


def test_root_redirects_to_today(client):
    r = client.get("/")
    assert r.status_code == 200
    assert b"Today" in r.content


# ── Seeded data appears in views ──────────────────────────────────────────

def test_today_shows_overdue_task(seeded_client):
    r = seeded_client.get("/today")
    assert r.status_code == 200
    assert b"Write tests" in r.content


def test_inbox_shows_pending_approval(seeded_client):
    r = seeded_client.get("/inbox")
    assert r.status_code == 200
    assert b"Ping localhost" in r.content


def test_agents_shows_agent(seeded_client):
    r = seeded_client.get("/agents")
    assert r.status_code == 200
    assert b"Recon" in r.content
    assert b"Map the lab" in r.content


def test_memory_shows_note_and_lesson(seeded_client):
    r = seeded_client.get("/memory")
    assert r.status_code == 200
    assert b"Test note" in r.content
    assert b"Always test" in r.content


# ── Actions ───────────────────────────────────────────────────────────────

def test_add_task(client, tmp_env):
    r = client.post("/actions/tasks/add", data={"text": "New task", "priority": "normal"})
    assert r.status_code == 200
    mem = SQLiteMemoryStore(tmp_env / "agent_hart.db")
    tasks = mem.list_tasks()
    mem.close()
    assert any(t["text"] == "New task" for t in tasks)


def test_add_task_empty_text_redirects_with_error(client):
    r = client.post("/actions/tasks/add", data={"text": "  ", "priority": "normal"})
    assert r.status_code == 200
    assert b"error" in r.content.lower() or b"required" in r.content.lower()


def test_complete_task(client, tmp_env):
    mem = SQLiteMemoryStore(tmp_env / "agent_hart.db")
    task = mem.add_task("Complete me")
    mem.close()
    r = client.post(f"/actions/tasks/{task['id']}/complete")
    assert r.status_code == 200
    mem2 = SQLiteMemoryStore(tmp_env / "agent_hart.db")
    tasks = mem2.list_tasks()
    mem2.close()
    completed = next((t for t in tasks if t["id"] == task["id"]), None)
    assert completed is not None
    assert completed["completed"] is True


def test_complete_unknown_task(client):
    r = client.post("/actions/tasks/nonexistent-id/complete")
    assert r.status_code == 200
    assert b"not found" in r.content.lower()


def test_approve_approval(seeded_client, tmp_env):
    mem = SQLiteMemoryStore(tmp_env / "agent_hart.db")
    approvals = mem.list_approval_requests(status="pending")
    approval_id = approvals[0]["id"]
    mem.close()
    r = seeded_client.post(f"/actions/approvals/{approval_id}/approve")
    assert r.status_code == 200
    mem2 = SQLiteMemoryStore(tmp_env / "agent_hart.db")
    ap = mem2.get_approval_request(approval_id)
    mem2.close()
    assert ap["status"] == "approved"


def test_reject_approval(seeded_client, tmp_env):
    mem = SQLiteMemoryStore(tmp_env / "agent_hart.db")
    approvals = mem.list_approval_requests(status="pending")
    approval_id = approvals[0]["id"]
    mem.close()
    r = seeded_client.post(f"/actions/approvals/{approval_id}/reject")
    assert r.status_code == 200
    mem2 = SQLiteMemoryStore(tmp_env / "agent_hart.db")
    ap = mem2.get_approval_request(approval_id)
    mem2.close()
    assert ap["status"] == "rejected"


def test_add_note(client, tmp_env):
    r = client.post("/actions/notes/add", data={"text": "Dashboard note"})
    assert r.status_code == 200
    mem = SQLiteMemoryStore(tmp_env / "agent_hart.db")
    notes = mem.list_notes()
    mem.close()
    assert any(n["text"] == "Dashboard note" for n in notes)


def test_add_lesson(client, tmp_env):
    r = client.post("/actions/lessons/add", data={"text": "Test lesson", "source": "test"})
    assert r.status_code == 200
    mem = SQLiteMemoryStore(tmp_env / "agent_hart.db")
    lessons = mem.list_lessons()
    mem.close()
    assert any(l["text"] == "Test lesson" for l in lessons)


def test_add_agent(client, tmp_env):
    r = client.post(
        "/actions/agents/add",
        data={"name": "Scout", "role": "recon", "autonomy_level": "supervised", "max_steps": "3"},
    )
    assert r.status_code == 200
    mem = SQLiteMemoryStore(tmp_env / "agent_hart.db")
    agents = mem.list_agents()
    mem.close()
    assert any(a["name"] == "Scout" for a in agents)


def test_add_goal(client, tmp_env):
    mem = SQLiteMemoryStore(tmp_env / "agent_hart.db")
    agent = mem.add_agent("GoalBot", role="planner")
    mem.close()
    r = client.post(
        "/actions/goals/add",
        data={"agent_id": agent["id"], "text": "Achieve something"},
    )
    assert r.status_code == 200
    mem2 = SQLiteMemoryStore(tmp_env / "agent_hart.db")
    goals = mem2.list_goals()
    mem2.close()
    assert any(g["text"] == "Achieve something" for g in goals)


def test_add_checkpoint(client, tmp_env):
    mem = SQLiteMemoryStore(tmp_env / "agent_hart.db")
    agent = mem.add_agent("Planner")
    mem.close()
    r = client.post(
        "/actions/checkpoints/add",
        data={"agent_id": agent["id"], "goal_id": ""},
    )
    assert r.status_code == 200
    mem2 = SQLiteMemoryStore(tmp_env / "agent_hart.db")
    runs = mem2.list_task_runs()
    mem2.close()
    assert any(r["status"] == "planning" for r in runs)


def test_run_health_check(client, tmp_env):
    r = client.post("/actions/health/run")
    assert r.status_code == 200
    mem = SQLiteMemoryStore(tmp_env / "agent_hart.db")
    history = mem.list_health_checks()
    mem.close()
    assert len(history) >= 1
    assert history[-1]["overall_status"] in {"ok", "degraded", "fail"}


# ── Helper unit tests ─────────────────────────────────────────────────────

def test_complete_task_by_id_found(tmp_env):
    mem = SQLiteMemoryStore(tmp_env / "agent_hart.db")
    task = mem.add_task("Find me")
    result = dashboard._complete_task_by_id(mem, task["id"])
    assert result is True
    tasks = mem.list_tasks()
    assert any(t["id"] == task["id"] and t["completed"] for t in tasks)
    mem.close()


def test_complete_task_by_id_not_found(tmp_env):
    mem = SQLiteMemoryStore(tmp_env / "agent_hart.db")
    result = dashboard._complete_task_by_id(mem, "no-such-id")
    assert result is False
    mem.close()
