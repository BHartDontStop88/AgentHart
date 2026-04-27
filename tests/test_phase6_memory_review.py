import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from main import handle_review_memory
from memory import MemoryStore
from structured_memory import SQLiteMemoryStore


class Phase6MemoryReviewTests(unittest.TestCase):
    def test_review_memory_saves_approved_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = MemoryStore(Path(tmp) / "memory.json")
            memory.add_task("Review memory feature", priority="high")
            memory.add_note("Memory reviews should be approved before saving.")

            with patch("main.ask_ai", return_value="Reviewed current memory."), patch(
                "builtins.input", return_value="yes"
            ), patch("builtins.print") as printed:
                handle_review_memory(memory)

            summaries = memory.list_memory_summaries()
            output = "\n".join(str(call.args[0]) for call in printed.call_args_list)
            self.assertEqual(len(summaries), 1)
            self.assertEqual(summaries[0]["scope"], "memory_review")
            self.assertEqual(summaries[0]["summary"], "Reviewed current memory.")
            self.assertIn("Memory review draft:", output)
            self.assertIn("Saved memory review", output)

    def test_review_memory_can_be_rejected_without_saving(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = MemoryStore(Path(tmp) / "memory.json")

            with patch("main.ask_ai", return_value="Do not save this."), patch(
                "builtins.input", return_value="no"
            ), patch("builtins.print") as printed:
                handle_review_memory(memory)

            output = "\n".join(str(call.args[0]) for call in printed.call_args_list)
            self.assertEqual(memory.list_memory_summaries(), [])
            self.assertIn("Memory review not saved.", output)

    def test_review_memory_works_with_sqlite_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = SQLiteMemoryStore(Path(tmp) / "agent_hart.db")

            with patch("main.ask_ai", return_value="SQLite review saved."), patch(
                "builtins.input", return_value="yes"
            ), patch("builtins.print"):
                handle_review_memory(memory)

            self.assertEqual(memory.list_memory_summaries()[0]["scope"], "memory_review")
            self.assertEqual(memory.memory_stats()["memory_summaries"], 1)
            memory.close()


if __name__ == "__main__":
    unittest.main()
