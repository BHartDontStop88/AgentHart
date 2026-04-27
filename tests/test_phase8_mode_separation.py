import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from main import (
    handle_agent_status,
    handle_chat,
    handle_run_agent_placeholder,
    handle_stop_agent_placeholder,
)
from memory import MemoryStore
from structured_memory import SQLiteMemoryStore


class Phase8ModeSeparationTests(unittest.TestCase):
    def test_chat_does_not_create_tasks_without_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = MemoryStore(Path(tmp) / "memory.json")
            suggestion = {
                "action": "add_task",
                "text": "inspect localhost",
                "due": None,
                "priority": "normal",
            }

            with patch("main.ask_ai", return_value="Use add task for that."), patch(
                "main.suggest_action", return_value=suggestion
            ) as suggest_action, patch("builtins.input", return_value="no"), patch(
                "builtins.print"
            ):
                handle_chat("remind me to inspect localhost", memory)

            suggest_action.assert_called_once()
            self.assertEqual(len(memory.list_chat_history()), 2)
            self.assertEqual(memory.list_tasks(), [])
            self.assertEqual(memory.list_actions()[0]["status"], "rejected")
            self.assertEqual(memory.list_task_runs(), [])
            self.assertEqual(memory.list_run_steps(), [])

    def test_agent_status_reports_runtime_without_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = MemoryStore(Path(tmp) / "memory.json")
            agent = memory.add_agent("Recon", role="researcher", allowed_tools=["report"])
            memory.add_goal(agent["id"], "Inspect available reports.")

            with patch("builtins.print") as printed:
                handle_agent_status(memory)

            output = "\n".join(str(call.args[0]) for call in printed.call_args_list)
            self.assertIn("Automation runtime status", output)
            self.assertIn("Agents: 1", output)
            self.assertIn("Pending goals: 1", output)
            self.assertIn("Execution: disabled", output)
            self.assertEqual(memory.list_task_runs(), [])

    def test_run_agent_placeholder_refuses_to_create_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = MemoryStore(Path(tmp) / "memory.json")
            memory.add_agent("Reporter", role="summarizer", allowed_tools=["report"])

            with patch("builtins.print") as printed:
                handle_run_agent_placeholder("1", memory)

            output = "\n".join(str(call.args[0]) for call in printed.call_args_list)
            self.assertIn("Automation execution is not enabled yet", output)
            self.assertEqual(memory.list_task_runs(), [])
            self.assertEqual(memory.list_run_steps(), [])

    def test_stop_agent_placeholder_handles_missing_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = SQLiteMemoryStore(Path(tmp) / "agent_hart.db")

            with patch("builtins.print") as printed:
                handle_stop_agent_placeholder("abc123", memory)

            output = "\n".join(str(call.args[0]) for call in printed.call_args_list)
            self.assertIn("No task run found for abc123.", output)
            self.assertEqual(memory.memory_stats()["task_runs"], 0)
            memory.close()

    def test_mode_separation_stress_chat_never_creates_runtime_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = SQLiteMemoryStore(Path(tmp) / "agent_hart.db")

            with patch("main.ask_ai", return_value="Chat response."), patch(
                "main.suggest_action", return_value={"action": "none"}
            ), patch(
                "builtins.print"
            ):
                for index in range(100):
                    handle_chat(f"chat-only message {index}", memory)

            self.assertEqual(len(memory.list_chat_history()), 200)
            self.assertEqual(memory.memory_stats()["tasks"], 0)
            self.assertEqual(memory.memory_stats()["actions"], 0)
            self.assertEqual(memory.memory_stats()["task_runs"], 0)
            self.assertEqual(memory.memory_stats()["run_steps"], 0)
            memory.close()


if __name__ == "__main__":
    unittest.main()
