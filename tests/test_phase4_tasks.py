import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from main import handle_add_task, handle_complete_task, handle_list_tasks
from memory import MemoryStore
from structured_memory import SQLiteMemoryStore


class Phase4TaskCommandTests(unittest.TestCase):
    def test_json_task_commands_add_list_and_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = MemoryStore(Path(tmp) / "memory.json")

            with patch("builtins.print") as printed:
                handle_add_task("Review report --due 2026-04-30 --priority high", memory)
                handle_list_tasks(memory)
                handle_complete_task("1", memory)
                handle_list_tasks(memory)

            output = "\n".join(str(call.args[0]) for call in printed.call_args_list)
            self.assertIn("Saved task", output)
            self.assertIn("1. [ ] [high] [due: 2026-04-30] Review report", output)
            self.assertIn("Completed task 1.", output)
            self.assertIn("1. [x] [high] [due: 2026-04-30] Review report", output)
            self.assertTrue(memory.list_tasks()[0]["completed"])

    def test_sqlite_task_commands_add_list_and_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = SQLiteMemoryStore(Path(tmp) / "agent_hart.db")

            with patch("builtins.print") as printed:
                handle_add_task("Write phase notes --priority low", memory)
                handle_complete_task("1", memory)
                handle_list_tasks(memory)

            output = "\n".join(str(call.args[0]) for call in printed.call_args_list)
            self.assertIn("Saved task", output)
            self.assertIn("Completed task 1.", output)
            self.assertIn("1. [x] [low] [due: no due date] Write phase notes", output)
            self.assertTrue(memory.list_tasks()[0]["completed"])
            memory.close()

    def test_task_commands_report_invalid_numbers(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = MemoryStore(Path(tmp) / "memory.json")

            with patch("builtins.print") as printed:
                handle_complete_task("0", memory)
                handle_complete_task("nope", memory)

            output = "\n".join(str(call.args[0]) for call in printed.call_args_list)
            self.assertIn("Task number must be 1 or higher.", output)
            self.assertIn("Usage: complete task <number>", output)


if __name__ == "__main__":
    unittest.main()
