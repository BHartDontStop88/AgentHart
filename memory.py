import json
from copy import deepcopy
from datetime import date, datetime
from pathlib import Path
from uuid import uuid4


DEFAULT_MEMORY = {
    "user_preferences": {},
    "notes": [],
    "tasks": [],
    "reminders": [],
    "actions": [],
    "approval_requests": [],
    "audit_log": [],
    "tool_results": [],
    "chat_history": [],
    "lessons": [],
    "memory_summaries": [],
    "agents": [],
    "goals": [],
    "task_runs": [],
    "run_steps": [],
    "health_checks": [],
    "run_reviews": [],
}


class MemoryStore:
    """
    Small JSON-backed memory layer.

    A real agent needs somewhere to put durable state. For Phase 1, JSON is a
    good teaching format because you can open memory.json and see exactly what
    changed after each command. Later, this class can be swapped for SQLite or a
    vector database without changing the CLI much.
    """

    def __init__(self, path="memory.json"):
        self.path = Path(path)
        self.data = self.load()

    def load(self):
        """
        Load memory from disk and repair missing top-level keys.

        This lets the schema evolve gently. If we add "tasks" or "preferences"
        later, older memory files still load because missing sections are filled
        from DEFAULT_MEMORY.
        """
        if not self.path.exists():
            memory = deepcopy(DEFAULT_MEMORY)
            self.path.write_text(json.dumps(memory, indent=2), encoding="utf-8")
            return memory

        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            # If memory.json is manually edited and broken, preserve the bad file
            # for inspection instead of overwriting it silently.
            backup_path = self.path.with_suffix(".broken.json")
            self.path.replace(backup_path)
            memory = deepcopy(DEFAULT_MEMORY)
            self.path.write_text(json.dumps(memory, indent=2), encoding="utf-8")
            print(f"Memory file was invalid JSON. Backed it up to {backup_path}.")
            return memory

        repaired = False
        for key, value in DEFAULT_MEMORY.items():
            if key not in data:
                repaired = True
            data.setdefault(key, deepcopy(value))
        for task in data["tasks"]:
            if "id" not in task:
                repaired = True
                task["id"] = make_id()
            task.setdefault("due_date", None)
            task.setdefault("priority", "normal")
        for reminder in data["reminders"]:
            reminder.setdefault("completed", False)
        for approval in data["approval_requests"]:
            if "id" not in approval:
                repaired = True
                approval["id"] = make_id()
            approval.setdefault("status", "pending")
            approval.setdefault("requires_approval", True)
            approval.setdefault("created_at", timestamp())
            approval.setdefault("decided_at", None)
            approval.setdefault("decision_reason", None)
        for agent in data["agents"]:
            if "id" not in agent:
                repaired = True
                agent["id"] = make_id()
            agent.setdefault("role", "general")
            agent.setdefault("allowed_tools", [])
            agent.setdefault("status", "active")
            agent.setdefault("autonomy_level", "supervised")
            agent.setdefault("max_steps", 5)
            agent.setdefault("created_at", timestamp())
        for goal in data["goals"]:
            if "id" not in goal:
                repaired = True
                goal["id"] = make_id()
            goal.setdefault("agent_id", None)
            goal.setdefault("status", "pending")
            goal.setdefault("created_at", timestamp())
        for health_check in data["health_checks"]:
            if "id" not in health_check:
                repaired = True
                health_check["id"] = make_id()
            health_check.setdefault("overall_status", "unknown")
            health_check.setdefault("checks", [])
            health_check.setdefault("created_at", timestamp())
        for review in data["run_reviews"]:
            if "id" not in review:
                repaired = True
                review["id"] = make_id()
            review.setdefault("run_id", None)
            review.setdefault("agent_id", None)
            review.setdefault("outcome", "unknown")
            review.setdefault("summary", "")
            review.setdefault("created_at", timestamp())
        if repaired:
            self.data = data
            self.save()
        return data

    def save(self):
        """Write the current in-memory dictionary back to memory.json."""
        self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")

    def close(self):
        """Compatibility with SQLiteMemoryStore."""
        return None

    def add_note(self, text):
        """Append one note and immediately persist it."""
        note = {"text": text, "created_at": timestamp()}
        self.data["notes"].append(note)
        self.save()
        return note

    def list_notes(self):
        return self.data["notes"]

    def add_task(self, text, due_date=None, priority="normal"):
        """Append one task and immediately persist it."""
        task = {
            "id": make_id(),
            "text": text,
            "completed": False,
            "created_at": timestamp(),
            "due_date": due_date,
            "priority": priority,
        }
        self.data["tasks"].append(task)
        self.save()
        return task

    def list_tasks(self):
        return self.data["tasks"]

    def delete_task_by_id(self, task_id):
        """Delete only the task with the matching id."""
        for index, task in enumerate(self.data["tasks"]):
            if task.get("id") == task_id:
                del self.data["tasks"][index]
                self.save()
                return True
        return False

    def tasks_due_today(self):
        today = date.today().isoformat()
        return [
            (index, task)
            for index, task in enumerate(self.data["tasks"], start=1)
            if not task["completed"] and task.get("due_date") == today
        ]

    def complete_task(self, index):
        try:
            if index < 0:
                return False
            self.data["tasks"][index]["completed"] = True
            self.save()
            return True
        except IndexError:
            return False

    def add_reminder(self, text, due_at):
        """Save a reminder with the exact time it should be shown."""
        reminder = {
            "text": text,
            "due_at": due_at,
            "completed": False,
            "created_at": timestamp(),
        }
        self.data["reminders"].append(reminder)
        self.save()
        return reminder

    def list_reminders(self):
        return self.data["reminders"]

    def due_reminders(self):
        """Return reminders due now or earlier that are not completed yet."""
        now = datetime.now()
        due = []
        for index, reminder in enumerate(self.data["reminders"]):
            if reminder["completed"]:
                continue
            try:
                due_at = datetime.fromisoformat(reminder["due_at"])
            except ValueError:
                continue
            if due_at <= now:
                due.append((index, reminder))
        return due

    def complete_reminder(self, index):
        try:
            if index < 0:
                return False
            self.data["reminders"][index]["completed"] = True
            self.save()
            return True
        except IndexError:
            return False

    def add_action(self, action):
        """Save an AI-suggested action before the human approves or rejects it."""
        action_record = {
            "action": action,
            "status": "pending",
            "created_at": timestamp(),
        }
        self.data["actions"].append(action_record)
        self.save()
        return action_record

    def update_action_status(self, index, status):
        try:
            self.data["actions"][index]["status"] = status
            self.save()
            return True
        except IndexError:
            return False

    def set_action_created_task_id(self, index, task_id):
        try:
            self.data["actions"][index]["created_task_id"] = task_id
            self.save()
            return True
        except IndexError:
            return False

    def list_actions(self):
        return self.data["actions"]

    def add_chat(self, role, message):
        """Store one chat turn with a role, message, and timestamp."""
        self.data["chat_history"].append(
            {"role": role, "message": message, "created_at": timestamp()}
        )
        self.save()

    def add_tool_result(self, tool_name, target, output, status, approval_id=None):
        """
        Store tool output as an audit trail.

        This is important because agent actions should be reviewable after the
        fact. Reports are built from these saved results.
        """
        result = {
            "tool": tool_name,
            "target": target,
            "status": status,
            "output": output,
            "created_at": timestamp(),
        }
        if approval_id:
            result["approval_id"] = approval_id
        self.data["tool_results"].append(result)
        self.save()
        return result

    def recent_tool_results(self, limit=5):
        return self.data["tool_results"][-limit:]

    def list_tool_results(self):
        return self.data["tool_results"]

    def list_chat_history(self):
        return self.data["chat_history"]

    def add_approval_request(
        self,
        action_type,
        description,
        payload,
        risk_level="unknown",
        requires_approval=True,
        status=None,
    ):
        """Record a proposed action before it runs."""
        approval = {
            "id": make_id(),
            "action_type": action_type,
            "description": description,
            "payload": payload,
            "risk_level": risk_level,
            "requires_approval": requires_approval,
            "status": status or ("pending" if requires_approval else "auto_approved"),
            "created_at": timestamp(),
            "decided_at": None if requires_approval else timestamp(),
            "decision_reason": None,
        }
        self.data["approval_requests"].append(approval)
        self.add_audit_event(
            "approval_created",
            {
                "approval_id": approval["id"],
                "action_type": action_type,
                "status": approval["status"],
                "risk_level": risk_level,
            },
            save=False,
        )
        self.save()
        return approval

    def list_approval_requests(self, status=None):
        approvals = self.data["approval_requests"]
        if status is None:
            return approvals
        return [approval for approval in approvals if approval.get("status") == status]

    def get_approval_request(self, approval_id):
        for approval in self.data["approval_requests"]:
            if approval.get("id") == approval_id:
                return approval
        return None

    def decide_approval(self, approval_id, approved, reason=None):
        """Mark a pending approval request as approved or rejected."""
        approval = self.get_approval_request(approval_id)
        if approval is None:
            return None
        if approval.get("status") != "pending":
            return approval

        approval["status"] = "approved" if approved else "rejected"
        approval["decided_at"] = timestamp()
        approval["decision_reason"] = reason
        self.add_audit_event(
            "approval_decided",
            {
                "approval_id": approval_id,
                "status": approval["status"],
                "reason": reason,
            },
            save=False,
        )
        self.save()
        return approval

    def mark_approval_executed(self, approval_id, status):
        approval = self.get_approval_request(approval_id)
        if approval is None:
            return None
        approval["execution_status"] = status
        approval["executed_at"] = timestamp()
        self.add_audit_event(
            "approval_executed",
            {"approval_id": approval_id, "execution_status": status},
            save=False,
        )
        self.save()
        return approval

    def add_audit_event(self, event_type, details, save=True):
        """Append a compact audit event for later review."""
        event = {
            "id": make_id(),
            "event_type": event_type,
            "details": details,
            "created_at": timestamp(),
        }
        self.data["audit_log"].append(event)
        if save:
            self.save()
        return event

    def list_audit_events(self):
        return self.data["audit_log"]

    def add_lesson(self, text, source="user"):
        lesson = {
            "id": make_id(),
            "text": text,
            "source": source,
            "created_at": timestamp(),
        }
        self.data["lessons"].append(lesson)
        self.save()
        return lesson

    def list_lessons(self):
        return self.data["lessons"]

    def add_memory_summary(self, scope, summary):
        record = {
            "id": make_id(),
            "scope": scope,
            "summary": summary,
            "created_at": timestamp(),
        }
        self.data["memory_summaries"].append(record)
        self.save()
        return record

    def list_memory_summaries(self):
        return self.data["memory_summaries"]

    def add_agent(
        self,
        name,
        role="general",
        allowed_tools=None,
        max_steps=5,
        autonomy_level="supervised",
    ):
        agent = {
            "id": make_id(),
            "name": name,
            "role": role,
            "allowed_tools": allowed_tools or [],
            "status": "active",
            "autonomy_level": autonomy_level,
            "max_steps": max_steps,
            "created_at": timestamp(),
        }
        self.data["agents"].append(agent)
        self.save()
        return agent

    def list_agents(self):
        return self.data["agents"]

    def get_agent(self, agent_id):
        for agent in self.data["agents"]:
            if agent.get("id") == agent_id:
                return agent
        return None

    def add_goal(self, agent_id, text, status="pending"):
        goal = {
            "id": make_id(),
            "agent_id": agent_id,
            "text": text,
            "status": status,
            "created_at": timestamp(),
        }
        self.data["goals"].append(goal)
        self.save()
        return goal

    def list_goals(self):
        return self.data["goals"]

    def list_task_runs(self):
        return self.data["task_runs"]

    def add_task_run(self, agent_id, goal_id=None, status="planning"):
        run = {
            "id": make_id(),
            "agent_id": agent_id,
            "goal_id": goal_id,
            "status": status,
            "created_at": timestamp(),
            "completed_at": None,
        }
        self.data["task_runs"].append(run)
        self.save()
        return run

    def update_task_run_status(self, run_id, status, completed_at=None):
        for run in self.data["task_runs"]:
            if run.get("id") == run_id:
                run["status"] = status
                run["completed_at"] = completed_at
                self.save()
                return run
        return None

    def list_run_steps(self):
        return self.data["run_steps"]

    def add_run_step(
        self,
        run_id,
        step_number,
        status,
        prompt=None,
        response=None,
        tool_name=None,
        tool_target=None,
        tool_result_id=None,
    ):
        step = {
            "id": make_id(),
            "run_id": run_id,
            "step_number": step_number,
            "status": status,
            "prompt": prompt,
            "response": response,
            "tool_name": tool_name,
            "tool_target": tool_target,
            "tool_result_id": tool_result_id,
            "created_at": timestamp(),
        }
        self.data["run_steps"].append(step)
        self.save()
        return step

    def add_health_check(self, overall_status, checks):
        record = {
            "id": make_id(),
            "overall_status": overall_status,
            "checks": checks,
            "created_at": timestamp(),
        }
        self.data["health_checks"].append(record)
        self.save()
        return record

    def list_health_checks(self):
        return self.data["health_checks"]

    def add_run_review(self, run_id, agent_id, outcome, summary, details=None):
        review = {
            "id": make_id(),
            "run_id": run_id,
            "agent_id": agent_id,
            "outcome": outcome,
            "summary": summary,
            "details": details or {},
            "created_at": timestamp(),
        }
        self.data["run_reviews"].append(review)
        self.save()
        return review

    def list_run_reviews(self):
        return self.data["run_reviews"]

    def memory_stats(self):
        return {
            "notes": len(self.data["notes"]),
            "tasks": len(self.data["tasks"]),
            "reminders": len(self.data["reminders"]),
            "actions": len(self.data["actions"]),
            "approval_requests": len(self.data["approval_requests"]),
            "tool_results": len(self.data["tool_results"]),
            "chat_history": len(self.data["chat_history"]),
            "audit_log": len(self.data["audit_log"]),
            "lessons": len(self.data["lessons"]),
            "memory_summaries": len(self.data["memory_summaries"]),
            "agents": len(self.data["agents"]),
            "goals": len(self.data["goals"]),
            "task_runs": len(self.data["task_runs"]),
            "run_steps": len(self.data["run_steps"]),
            "health_checks": len(self.data["health_checks"]),
            "run_reviews": len(self.data["run_reviews"]),
        }


def timestamp():
    """Return a compact local timestamp for notes, chats, and tool results."""
    return datetime.now().isoformat(timespec="seconds")


def make_id():
    """Return a simple unique id for records that need exact undo tracking."""
    return str(uuid4())
