import json
import sqlite3
from datetime import date, datetime
from pathlib import Path
from uuid import uuid4

from memory import DEFAULT_MEMORY, make_id, timestamp


class SQLiteMemoryStore:
    """
    SQLite-backed memory with the same public methods as MemoryStore.

    The older JSON store is still useful for inspection and backups. This class
    is the Phase 3 structured memory layer used by the running agent.
    """

    def __init__(self, db_path="agent_hart.db", legacy_json_path=None):
        self.path = Path(db_path)
        self.legacy_json_path = Path(legacy_json_path) if legacy_json_path else None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.create_schema()
        self.import_legacy_json_once()

    def close(self):
        if getattr(self, "connection", None) is not None:
            self.connection.close()
            self.connection = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    @property
    def data(self):
        """Return a dictionary snapshot for older code paths."""
        preferences = {}
        for row in self.connection.execute("select key, value_json from user_preferences"):
            preferences[row["key"]] = json.loads(row["value_json"])

        return {
            "user_preferences": preferences,
            "notes": self.list_notes(),
            "tasks": self.list_tasks(),
            "reminders": self.list_reminders(),
            "actions": self.list_actions(),
            "approval_requests": self.list_approval_requests(),
            "audit_log": self.list_audit_events(),
            "tool_results": self.list_tool_results(),
            "chat_history": self.list_chat_history(),
            "lessons": self.list_lessons(),
            "memory_summaries": self.list_memory_summaries(),
            "agents": self.list_agents(),
            "goals": self.list_goals(),
            "task_runs": self.list_task_runs(),
            "run_steps": self.list_run_steps(),
            "health_checks": self.list_health_checks(),
            "run_reviews": self.list_run_reviews(),
        }

    def save(self):
        """Keep API compatibility with the JSON store."""
        self.connection.commit()

    def create_schema(self):
        self.connection.executescript(
            """
            create table if not exists metadata (
                key text primary key,
                value text not null
            );

            create table if not exists user_preferences (
                key text primary key,
                value_json text not null,
                updated_at text not null
            );

            create table if not exists notes (
                id text primary key,
                text text not null,
                created_at text not null
            );

            create table if not exists tasks (
                id text primary key,
                text text not null,
                completed integer not null,
                created_at text not null,
                due_date text,
                priority text not null
            );

            create table if not exists reminders (
                id text primary key,
                text text not null,
                due_at text not null,
                completed integer not null,
                created_at text not null
            );

            create table if not exists actions (
                id text primary key,
                action_json text not null,
                status text not null,
                created_at text not null,
                created_task_id text
            );

            create table if not exists approval_requests (
                id text primary key,
                action_type text not null,
                description text not null,
                payload_json text not null,
                risk_level text not null,
                requires_approval integer not null,
                status text not null,
                created_at text not null,
                decided_at text,
                decision_reason text,
                execution_status text,
                executed_at text
            );

            create table if not exists tool_results (
                id text primary key,
                tool text not null,
                target text not null,
                output text not null,
                status text not null,
                created_at text not null,
                approval_id text
            );

            create table if not exists chat_history (
                id text primary key,
                role text not null,
                message text not null,
                created_at text not null
            );

            create table if not exists audit_log (
                id text primary key,
                event_type text not null,
                details_json text not null,
                created_at text not null
            );

            create table if not exists lessons (
                id text primary key,
                text text not null,
                source text not null,
                created_at text not null
            );

            create table if not exists memory_summaries (
                id text primary key,
                scope text not null,
                summary text not null,
                created_at text not null
            );

            create table if not exists agents (
                id text primary key,
                name text not null,
                role text not null,
                allowed_tools_json text not null,
                status text not null,
                autonomy_level text not null,
                max_steps integer not null,
                created_at text not null
            );

            create table if not exists goals (
                id text primary key,
                agent_id text,
                text text not null,
                status text not null,
                created_at text not null
            );

            create table if not exists task_runs (
                id text primary key,
                agent_id text,
                goal_id text,
                status text not null,
                created_at text not null,
                completed_at text
            );

            create table if not exists run_steps (
                id text primary key,
                run_id text not null,
                step_number integer not null,
                status text not null,
                prompt text,
                response text,
                tool_name text,
                tool_target text,
                tool_result_id text,
                created_at text not null
            );

            create table if not exists health_checks (
                id text primary key,
                overall_status text not null,
                checks_json text not null,
                created_at text not null
            );

            create table if not exists run_reviews (
                id text primary key,
                run_id text,
                agent_id text,
                outcome text not null,
                summary text not null,
                details_json text not null,
                created_at text not null
            );

            create index if not exists idx_tasks_due_date on tasks(due_date);
            create index if not exists idx_reminders_due_at on reminders(due_at);
            create index if not exists idx_approvals_status on approval_requests(status);
            create index if not exists idx_tool_results_created on tool_results(created_at);
            create index if not exists idx_goals_agent_id on goals(agent_id);
            create index if not exists idx_task_runs_goal_id on task_runs(goal_id);
            create index if not exists idx_run_steps_run_id on run_steps(run_id);
            create index if not exists idx_health_checks_created on health_checks(created_at);
            create index if not exists idx_run_reviews_agent_id on run_reviews(agent_id);
            """
        )
        self.connection.commit()

    def import_legacy_json_once(self):
        row = self.connection.execute(
            "select value from metadata where key = 'legacy_json_imported'"
        ).fetchone()
        if row or not self.legacy_json_path or not self.legacy_json_path.exists():
            return

        try:
            data = json.loads(self.legacy_json_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return

        for key, value in DEFAULT_MEMORY.items():
            data.setdefault(key, [] if isinstance(value, list) else {})

        for key, value in data.get("user_preferences", {}).items():
            self.set_user_preference(key, value)

        for note in data.get("notes", []):
            self._insert_note(note.get("text", ""), note.get("created_at") or timestamp())

        for task in data.get("tasks", []):
            self._insert_task(
                task.get("text", ""),
                task.get("created_at") or timestamp(),
                task.get("id") or make_id(),
                bool(task.get("completed", False)),
                task.get("due_date"),
                task.get("priority", "normal"),
            )

        for reminder in data.get("reminders", []):
            self._insert_reminder(
                reminder.get("text", ""),
                reminder.get("due_at") or timestamp(),
                reminder.get("created_at") or timestamp(),
                reminder.get("id") or make_id(),
                bool(reminder.get("completed", False)),
            )

        for action in data.get("actions", []):
            self._insert_action(
                action.get("action", {}),
                action.get("status", "pending"),
                action.get("created_at") or timestamp(),
                action.get("id") or make_id(),
                action.get("created_task_id"),
            )

        for approval in data.get("approval_requests", []):
            self._insert_approval(approval)

        for result in data.get("tool_results", []):
            self._insert_tool_result(result)

        for chat in data.get("chat_history", []):
            self._insert_chat(
                chat.get("role", "user"),
                chat.get("message", ""),
                chat.get("created_at") or timestamp(),
                chat.get("id") or make_id(),
            )

        for event in data.get("audit_log", []):
            self._insert_audit_event(
                event.get("event_type", "legacy_event"),
                event.get("details", {}),
                event.get("created_at") or timestamp(),
                event.get("id") or make_id(),
            )

        for lesson in data.get("lessons", []):
            self._insert_lesson(
                lesson.get("text", ""),
                lesson.get("source", "legacy_json"),
                lesson.get("created_at") or timestamp(),
                lesson.get("id") or make_id(),
            )

        for agent in data.get("agents", []):
            self._insert_agent(
                agent.get("name", ""),
                agent.get("role", "general"),
                agent.get("allowed_tools", []),
                agent.get("max_steps", 5),
                agent.get("autonomy_level", "supervised"),
                agent.get("status", "active"),
                agent.get("created_at") or timestamp(),
                agent.get("id") or make_id(),
            )

        for goal in data.get("goals", []):
            self._insert_goal(
                goal.get("agent_id"),
                goal.get("text", ""),
                goal.get("status", "pending"),
                goal.get("created_at") or timestamp(),
                goal.get("id") or make_id(),
            )

        for health_check in data.get("health_checks", []):
            self._insert_health_check(
                health_check.get("overall_status", "unknown"),
                health_check.get("checks", []),
                health_check.get("created_at") or timestamp(),
                health_check.get("id") or make_id(),
            )

        for review in data.get("run_reviews", []):
            self._insert_run_review(
                review.get("run_id"),
                review.get("agent_id"),
                review.get("outcome", "unknown"),
                review.get("summary", ""),
                review.get("details", {}),
                review.get("created_at") or timestamp(),
                review.get("id") or make_id(),
            )

        self.connection.execute(
            "insert or replace into metadata(key, value) values (?, ?)",
            ("legacy_json_imported", timestamp()),
        )
        self.connection.commit()

    def set_user_preference(self, key, value):
        self.connection.execute(
            """
            insert or replace into user_preferences(key, value_json, updated_at)
            values (?, ?, ?)
            """,
            (key, json.dumps(value), timestamp()),
        )
        self.connection.commit()

    def add_note(self, text):
        note = self._insert_note(text, timestamp())
        self.connection.commit()
        return note

    def _insert_note(self, text, created_at):
        note = {"id": make_id(), "text": text, "created_at": created_at}
        self.connection.execute(
            "insert or ignore into notes(id, text, created_at) values (?, ?, ?)",
            (note["id"], note["text"], note["created_at"]),
        )
        return note

    def list_notes(self):
        rows = self.connection.execute(
            "select id, text, created_at from notes order by created_at, rowid"
        ).fetchall()
        return [dict(row) for row in rows]

    def add_task(self, text, due_date=None, priority="normal"):
        task = self._insert_task(text, timestamp(), make_id(), False, due_date, priority)
        self.connection.commit()
        return task

    def _insert_task(self, text, created_at, task_id, completed, due_date, priority):
        task = {
            "id": task_id,
            "text": text,
            "completed": completed,
            "created_at": created_at,
            "due_date": due_date,
            "priority": priority,
        }
        self.connection.execute(
            """
            insert or ignore into tasks(id, text, completed, created_at, due_date, priority)
            values (?, ?, ?, ?, ?, ?)
            """,
            (
                task["id"],
                task["text"],
                1 if task["completed"] else 0,
                task["created_at"],
                task["due_date"],
                task["priority"],
            ),
        )
        return task

    def list_tasks(self):
        rows = self.connection.execute(
            """
            select id, text, completed, created_at, due_date, priority
            from tasks order by created_at, rowid
            """
        ).fetchall()
        return [task_from_row(row) for row in rows]

    def delete_task_by_id(self, task_id):
        cursor = self.connection.execute("delete from tasks where id = ?", (task_id,))
        self.connection.commit()
        return cursor.rowcount > 0

    def tasks_due_today(self):
        today = date.today().isoformat()
        return [
            (index, task)
            for index, task in enumerate(self.list_tasks(), start=1)
            if not task["completed"] and task.get("due_date") == today
        ]

    def complete_task(self, index):
        tasks = self.list_tasks()
        if index < 0 or index >= len(tasks):
            return False
        self.connection.execute(
            "update tasks set completed = 1 where id = ?", (tasks[index]["id"],)
        )
        self.connection.commit()
        return True

    def add_reminder(self, text, due_at):
        reminder = self._insert_reminder(text, due_at, timestamp(), make_id(), False)
        self.connection.commit()
        return reminder

    def _insert_reminder(self, text, due_at, created_at, reminder_id, completed):
        reminder = {
            "id": reminder_id,
            "text": text,
            "due_at": due_at,
            "completed": completed,
            "created_at": created_at,
        }
        self.connection.execute(
            """
            insert or ignore into reminders(id, text, due_at, completed, created_at)
            values (?, ?, ?, ?, ?)
            """,
            (
                reminder["id"],
                reminder["text"],
                reminder["due_at"],
                1 if reminder["completed"] else 0,
                reminder["created_at"],
            ),
        )
        return reminder

    def list_reminders(self):
        rows = self.connection.execute(
            """
            select id, text, due_at, completed, created_at
            from reminders order by due_at, rowid
            """
        ).fetchall()
        return [reminder_from_row(row) for row in rows]

    def due_reminders(self):
        now = datetime.now()
        due = []
        for index, reminder in enumerate(self.list_reminders()):
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
        reminders = self.list_reminders()
        if index < 0 or index >= len(reminders):
            return False
        self.connection.execute(
            "update reminders set completed = 1 where id = ?", (reminders[index]["id"],)
        )
        self.connection.commit()
        return True

    def add_action(self, action):
        action_record = self._insert_action(action, "pending", timestamp(), make_id(), None)
        self.connection.commit()
        return action_record

    def _insert_action(self, action, status, created_at, action_id, created_task_id):
        record = {
            "id": action_id,
            "action": action,
            "status": status,
            "created_at": created_at,
        }
        if created_task_id:
            record["created_task_id"] = created_task_id
        self.connection.execute(
            """
            insert or ignore into actions(id, action_json, status, created_at, created_task_id)
            values (?, ?, ?, ?, ?)
            """,
            (action_id, json.dumps(action), status, created_at, created_task_id),
        )
        return record

    def update_action_status(self, index, status):
        actions = self.list_actions()
        if index < 0 or index >= len(actions):
            return False
        self.connection.execute(
            "update actions set status = ? where id = ?", (status, actions[index]["id"])
        )
        self.connection.commit()
        return True

    def set_action_created_task_id(self, index, task_id):
        actions = self.list_actions()
        if index < 0 or index >= len(actions):
            return False
        self.connection.execute(
            "update actions set created_task_id = ? where id = ?",
            (task_id, actions[index]["id"]),
        )
        self.connection.commit()
        return True

    def list_actions(self):
        rows = self.connection.execute(
            """
            select id, action_json, status, created_at, created_task_id
            from actions order by created_at, rowid
            """
        ).fetchall()
        actions = []
        for row in rows:
            record = {
                "id": row["id"],
                "action": json.loads(row["action_json"]),
                "status": row["status"],
                "created_at": row["created_at"],
            }
            if row["created_task_id"]:
                record["created_task_id"] = row["created_task_id"]
            actions.append(record)
        return actions

    def add_chat(self, role, message):
        self._insert_chat(role, message, timestamp(), make_id())
        self.connection.commit()

    def _insert_chat(self, role, message, created_at, chat_id):
        self.connection.execute(
            """
            insert or ignore into chat_history(id, role, message, created_at)
            values (?, ?, ?, ?)
            """,
            (chat_id, role, message, created_at),
        )

    def list_chat_history(self):
        rows = self.connection.execute(
            """
            select id, role, message, created_at
            from chat_history order by created_at, rowid
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def add_tool_result(self, tool_name, target, output, status, approval_id=None):
        result = {
            "id": make_id(),
            "tool": tool_name,
            "target": target,
            "status": status,
            "output": output,
            "created_at": timestamp(),
        }
        if approval_id:
            result["approval_id"] = approval_id
        self._insert_tool_result(result)
        self.connection.commit()
        return result

    def _insert_tool_result(self, result):
        result_id = result.get("id") or make_id()
        self.connection.execute(
            """
            insert or ignore into tool_results(id, tool, target, output, status, created_at, approval_id)
            values (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result_id,
                result.get("tool", ""),
                result.get("target", ""),
                result.get("output", ""),
                result.get("status", "unknown"),
                result.get("created_at") or timestamp(),
                result.get("approval_id"),
            ),
        )

    def list_tool_results(self):
        rows = self.connection.execute(
            """
            select id, tool, target, output, status, created_at, approval_id
            from tool_results order by created_at, rowid
            """
        ).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            if item.get("approval_id") is None:
                item.pop("approval_id", None)
            results.append(item)
        return results

    def recent_tool_results(self, limit=5):
        rows = self.connection.execute(
            """
            select id, tool, target, output, status, created_at, approval_id
            from tool_results order by created_at desc, rowid desc limit ?
            """,
            (limit,),
        ).fetchall()
        results = []
        for row in reversed(rows):
            item = dict(row)
            if item.get("approval_id") is None:
                item.pop("approval_id", None)
            results.append(item)
        return results

    def add_approval_request(
        self,
        action_type,
        description,
        payload,
        risk_level="unknown",
        requires_approval=True,
        status=None,
    ):
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
        self._insert_approval(approval)
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
        self.connection.commit()
        return approval

    def _insert_approval(self, approval):
        approval.setdefault("id", make_id())
        approval.setdefault("status", "pending")
        approval.setdefault("requires_approval", True)
        approval.setdefault("created_at", timestamp())
        approval.setdefault("decided_at", None)
        approval.setdefault("decision_reason", None)
        self.connection.execute(
            """
            insert or ignore into approval_requests(
                id, action_type, description, payload_json, risk_level,
                requires_approval, status, created_at, decided_at, decision_reason,
                execution_status, executed_at
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                approval["id"],
                approval.get("action_type", "unknown"),
                approval.get("description", ""),
                json.dumps(approval.get("payload", {})),
                approval.get("risk_level", "unknown"),
                1 if approval.get("requires_approval", True) else 0,
                approval.get("status", "pending"),
                approval.get("created_at") or timestamp(),
                approval.get("decided_at"),
                approval.get("decision_reason"),
                approval.get("execution_status"),
                approval.get("executed_at"),
            ),
        )

    def list_approval_requests(self, status=None):
        if status is None:
            rows = self.connection.execute(
                """
                select * from approval_requests order by created_at, rowid
                """
            ).fetchall()
        else:
            rows = self.connection.execute(
                """
                select * from approval_requests
                where status = ? order by created_at, rowid
                """,
                (status,),
            ).fetchall()
        return [approval_from_row(row) for row in rows]

    def get_approval_request(self, approval_id):
        row = self.connection.execute(
            "select * from approval_requests where id = ?", (approval_id,)
        ).fetchone()
        if row is None:
            return None
        return approval_from_row(row)

    def decide_approval(self, approval_id, approved, reason=None):
        approval = self.get_approval_request(approval_id)
        if approval is None:
            return None
        if approval.get("status") != "pending":
            return approval

        status = "approved" if approved else "rejected"
        decided_at = timestamp()
        self.connection.execute(
            """
            update approval_requests
            set status = ?, decided_at = ?, decision_reason = ?
            where id = ?
            """,
            (status, decided_at, reason, approval_id),
        )
        self.add_audit_event(
            "approval_decided",
            {"approval_id": approval_id, "status": status, "reason": reason},
            save=False,
        )
        self.connection.commit()
        return self.get_approval_request(approval_id)

    def mark_approval_executed(self, approval_id, status):
        executed_at = timestamp()
        self.connection.execute(
            """
            update approval_requests
            set execution_status = ?, executed_at = ?
            where id = ?
            """,
            (status, executed_at, approval_id),
        )
        self.add_audit_event(
            "approval_executed",
            {"approval_id": approval_id, "execution_status": status},
            save=False,
        )
        self.connection.commit()
        return self.get_approval_request(approval_id)

    def add_audit_event(self, event_type, details, save=True):
        event = self._insert_audit_event(event_type, details, timestamp(), make_id())
        if save:
            self.connection.commit()
        return event

    def _insert_audit_event(self, event_type, details, created_at, event_id):
        event = {
            "id": event_id,
            "event_type": event_type,
            "details": details,
            "created_at": created_at,
        }
        self.connection.execute(
            """
            insert or ignore into audit_log(id, event_type, details_json, created_at)
            values (?, ?, ?, ?)
            """,
            (event_id, event_type, json.dumps(details), created_at),
        )
        return event

    def list_audit_events(self):
        rows = self.connection.execute(
            """
            select id, event_type, details_json, created_at
            from audit_log order by created_at, rowid
            """
        ).fetchall()
        return [
            {
                "id": row["id"],
                "event_type": row["event_type"],
                "details": json.loads(row["details_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def add_lesson(self, text, source="user"):
        lesson = self._insert_lesson(text, source, timestamp(), make_id())
        self.connection.commit()
        return lesson

    def _insert_lesson(self, text, source, created_at, lesson_id):
        lesson = {
            "id": lesson_id,
            "text": text,
            "source": source,
            "created_at": created_at,
        }
        self.connection.execute(
            """
            insert or ignore into lessons(id, text, source, created_at)
            values (?, ?, ?, ?)
            """,
            (lesson_id, text, source, created_at),
        )
        return lesson

    def list_lessons(self):
        rows = self.connection.execute(
            "select id, text, source, created_at from lessons order by created_at, rowid"
        ).fetchall()
        return [dict(row) for row in rows]

    def add_memory_summary(self, scope, summary):
        record = {
            "id": make_id(),
            "scope": scope,
            "summary": summary,
            "created_at": timestamp(),
        }
        self.connection.execute(
            """
            insert into memory_summaries(id, scope, summary, created_at)
            values (?, ?, ?, ?)
            """,
            (record["id"], record["scope"], record["summary"], record["created_at"]),
        )
        self.connection.commit()
        return record

    def list_memory_summaries(self):
        rows = self.connection.execute(
            """
            select id, scope, summary, created_at
            from memory_summaries order by created_at, rowid
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def add_agent(
        self,
        name,
        role="general",
        allowed_tools=None,
        max_steps=5,
        autonomy_level="supervised",
    ):
        agent = self._insert_agent(
            name,
            role,
            allowed_tools or [],
            max_steps,
            autonomy_level,
            "active",
            timestamp(),
            make_id(),
        )
        self.connection.commit()
        return agent

    def _insert_agent(
        self,
        name,
        role,
        allowed_tools,
        max_steps,
        autonomy_level,
        status,
        created_at,
        agent_id,
    ):
        agent = {
            "id": agent_id,
            "name": name,
            "role": role,
            "allowed_tools": list(allowed_tools or []),
            "status": status,
            "autonomy_level": autonomy_level,
            "max_steps": int(max_steps),
            "created_at": created_at,
        }
        self.connection.execute(
            """
            insert or ignore into agents(
                id, name, role, allowed_tools_json, status,
                autonomy_level, max_steps, created_at
            )
            values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                agent["id"],
                agent["name"],
                agent["role"],
                json.dumps(agent["allowed_tools"]),
                agent["status"],
                agent["autonomy_level"],
                agent["max_steps"],
                agent["created_at"],
            ),
        )
        return agent

    def list_agents(self):
        rows = self.connection.execute(
            """
            select id, name, role, allowed_tools_json, status,
                   autonomy_level, max_steps, created_at
            from agents order by created_at, rowid
            """
        ).fetchall()
        return [agent_from_row(row) for row in rows]

    def get_agent(self, agent_id):
        row = self.connection.execute(
            """
            select id, name, role, allowed_tools_json, status,
                   autonomy_level, max_steps, created_at
            from agents where id = ?
            """,
            (agent_id,),
        ).fetchone()
        if row is None:
            return None
        return agent_from_row(row)

    def add_goal(self, agent_id, text, status="pending"):
        goal = self._insert_goal(agent_id, text, status, timestamp(), make_id())
        self.connection.commit()
        return goal

    def _insert_goal(self, agent_id, text, status, created_at, goal_id):
        goal = {
            "id": goal_id,
            "agent_id": agent_id,
            "text": text,
            "status": status,
            "created_at": created_at,
        }
        self.connection.execute(
            """
            insert or ignore into goals(id, agent_id, text, status, created_at)
            values (?, ?, ?, ?, ?)
            """,
            (goal["id"], goal["agent_id"], goal["text"], goal["status"], goal["created_at"]),
        )
        return goal

    def list_goals(self):
        rows = self.connection.execute(
            """
            select id, agent_id, text, status, created_at
            from goals order by created_at, rowid
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def list_task_runs(self):
        rows = self.connection.execute(
            """
            select id, agent_id, goal_id, status, created_at, completed_at
            from task_runs order by created_at, rowid
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def add_task_run(self, agent_id, goal_id=None, status="planning"):
        run = {
            "id": make_id(),
            "agent_id": agent_id,
            "goal_id": goal_id,
            "status": status,
            "created_at": timestamp(),
            "completed_at": None,
        }
        self.connection.execute(
            """
            insert into task_runs(id, agent_id, goal_id, status, created_at, completed_at)
            values (?, ?, ?, ?, ?, ?)
            """,
            (
                run["id"],
                run["agent_id"],
                run["goal_id"],
                run["status"],
                run["created_at"],
                run["completed_at"],
            ),
        )
        self.connection.commit()
        return run

    def update_task_run_status(self, run_id, status, completed_at=None):
        self.connection.execute(
            """
            update task_runs set status = ?, completed_at = ?
            where id = ?
            """,
            (status, completed_at, run_id),
        )
        self.connection.commit()
        for run in self.list_task_runs():
            if run["id"] == run_id:
                return run
        return None

    def list_run_steps(self):
        rows = self.connection.execute(
            """
            select id, run_id, step_number, status, prompt, response,
                   tool_name, tool_target, tool_result_id, created_at
            from run_steps order by created_at, rowid
            """
        ).fetchall()
        return [dict(row) for row in rows]

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
        self.connection.execute(
            """
            insert into run_steps(
                id, run_id, step_number, status, prompt, response,
                tool_name, tool_target, tool_result_id, created_at
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                step["id"],
                step["run_id"],
                step["step_number"],
                step["status"],
                step["prompt"],
                step["response"],
                step["tool_name"],
                step["tool_target"],
                step["tool_result_id"],
                step["created_at"],
            ),
        )
        self.connection.commit()
        return step

    def add_health_check(self, overall_status, checks):
        record = self._insert_health_check(
            overall_status, checks, timestamp(), make_id()
        )
        self.connection.commit()
        return record

    def _insert_health_check(self, overall_status, checks, created_at, health_id):
        record = {
            "id": health_id,
            "overall_status": overall_status,
            "checks": checks,
            "created_at": created_at,
        }
        self.connection.execute(
            """
            insert or ignore into health_checks(id, overall_status, checks_json, created_at)
            values (?, ?, ?, ?)
            """,
            (record["id"], record["overall_status"], json.dumps(checks), record["created_at"]),
        )
        return record

    def list_health_checks(self):
        rows = self.connection.execute(
            """
            select id, overall_status, checks_json, created_at
            from health_checks order by created_at, rowid
            """
        ).fetchall()
        return [
            {
                "id": row["id"],
                "overall_status": row["overall_status"],
                "checks": json.loads(row["checks_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def add_run_review(self, run_id, agent_id, outcome, summary, details=None):
        review = self._insert_run_review(
            run_id, agent_id, outcome, summary, details or {}, timestamp(), make_id()
        )
        self.connection.commit()
        return review

    def _insert_run_review(
        self, run_id, agent_id, outcome, summary, details, created_at, review_id
    ):
        review = {
            "id": review_id,
            "run_id": run_id,
            "agent_id": agent_id,
            "outcome": outcome,
            "summary": summary,
            "details": details,
            "created_at": created_at,
        }
        self.connection.execute(
            """
            insert or ignore into run_reviews(
                id, run_id, agent_id, outcome, summary, details_json, created_at
            )
            values (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                review["id"],
                review["run_id"],
                review["agent_id"],
                review["outcome"],
                review["summary"],
                json.dumps(review["details"]),
                review["created_at"],
            ),
        )
        return review

    def list_run_reviews(self):
        rows = self.connection.execute(
            """
            select id, run_id, agent_id, outcome, summary, details_json, created_at
            from run_reviews order by created_at, rowid
            """
        ).fetchall()
        return [
            {
                "id": row["id"],
                "run_id": row["run_id"],
                "agent_id": row["agent_id"],
                "outcome": row["outcome"],
                "summary": row["summary"],
                "details": json.loads(row["details_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def memory_stats(self):
        stats = {}
        for table in [
            "notes",
            "tasks",
            "reminders",
            "actions",
            "approval_requests",
            "tool_results",
            "chat_history",
            "audit_log",
            "lessons",
            "memory_summaries",
            "agents",
            "goals",
            "task_runs",
            "run_steps",
            "health_checks",
            "run_reviews",
        ]:
            row = self.connection.execute(f"select count(*) as count from {table}").fetchone()
            stats[table] = row["count"]
        return stats


def task_from_row(row):
    task = dict(row)
    task["completed"] = bool(task["completed"])
    return task


def reminder_from_row(row):
    reminder = dict(row)
    reminder["completed"] = bool(reminder["completed"])
    return reminder


def approval_from_row(row):
    approval = {
        "id": row["id"],
        "action_type": row["action_type"],
        "description": row["description"],
        "payload": json.loads(row["payload_json"]),
        "risk_level": row["risk_level"],
        "requires_approval": bool(row["requires_approval"]),
        "status": row["status"],
        "created_at": row["created_at"],
        "decided_at": row["decided_at"],
        "decision_reason": row["decision_reason"],
    }
    if row["execution_status"]:
        approval["execution_status"] = row["execution_status"]
    if row["executed_at"]:
        approval["executed_at"] = row["executed_at"]
    return approval


def agent_from_row(row):
    agent = dict(row)
    agent["allowed_tools"] = json.loads(agent.pop("allowed_tools_json"))
    return agent
