import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from main import (
    build_daily_command_center,
    build_inbox,
    handle_chat,
    handle_inbox,
    handle_today,
)
from memory import MemoryStore
from structured_memory import SQLiteMemoryStore


class Phase13DailyAssistantTests(unittest.TestCase):
    def test_today_command_center_shows_due_overdue_and_health(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = MemoryStore(Path(tmp) / "memory.json")
            memory.add_task("Overdue task", due_date="2000-01-01", priority="high")
            memory.add_task("Today task", due_date=date.today().isoformat())
            memory.add_health_check("degraded", [{"name": "ollama", "status": "warn", "detail": "offline"}])

            with patch("builtins.print") as printed:
                handle_today(memory)

            output = "\n".join(str(call.args[0]) for call in printed.call_args_list)
            self.assertIn("Today (", output)
            self.assertIn("Due today:", output)
            self.assertIn("Today task", output)
            self.assertIn("Overdue:", output)
            self.assertIn("Overdue task", output)
            self.assertIn("Latest health:", output)
            self.assertIn("degraded", output)

    def test_inbox_collects_pending_attention_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = MemoryStore(Path(tmp) / "memory.json")
            agent = memory.add_agent("Reporter", allowed_tools=["report"])
            memory.add_task_run(agent["id"], status="waiting_for_review")
            memory.add_action({"action": "add_task", "text": "Review inbox"})
            memory.add_approval_request("run_tool", "Run report", {"tool": "report"}, "low", True)
            memory.add_health_check("degraded", [{"name": "ollama", "status": "warn", "detail": "offline"}])

            inbox = build_inbox(memory)
            with patch("builtins.print") as printed:
                handle_inbox(memory)

            output = "\n".join(str(call.args[0]) for call in printed.call_args_list)
            self.assertEqual(len(inbox["pending_approvals"]), 1)
            self.assertEqual(len(inbox["pending_actions"]), 1)
            self.assertEqual(len(inbox["open_runs"]), 1)
            self.assertEqual(len(inbox["health_warnings"]), 1)
            self.assertIn("Inbox", output)
            self.assertIn("Pending approvals:", output)
            self.assertIn("Health warnings:", output)

    def test_chat_intent_routing_adds_task_only_after_yes(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = MemoryStore(Path(tmp) / "memory.json")
            suggestion = {
                "action": "add_task",
                "text": "check dashboard",
                "due": "today",
                "priority": "high",
            }

            with patch("main.ask_ai", return_value="I can draft that."), patch(
                "main.suggest_action", return_value=suggestion
            ), patch("builtins.input", return_value="yes"), patch("builtins.print"):
                handle_chat("remind me to check dashboard today", memory)

            self.assertEqual(len(memory.list_tasks()), 1)
            self.assertEqual(memory.list_tasks()[0]["text"], "check dashboard")
            self.assertEqual(memory.list_tasks()[0]["priority"], "high")
            self.assertEqual(memory.list_actions()[0]["status"], "approved")

    def test_daily_assistant_stress_sqlite(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = SQLiteMemoryStore(Path(tmp) / "agent_hart.db")
            try:
                for index in range(60):
                    memory.add_task(f"Task {index}", due_date="2000-01-01")
                    memory.add_health_check(
                        "degraded",
                        [{"name": "check", "status": "warn", "detail": str(index)}],
                    )
                center = build_daily_command_center(memory)
                inbox = build_inbox(memory)

                self.assertEqual(len(center["overdue"]), 60)
                self.assertEqual(center["latest_health"]["overall_status"], "degraded")
                self.assertEqual(len(inbox["health_warnings"]), 1)
            finally:
                memory.close()


if __name__ == "__main__":
    unittest.main()
