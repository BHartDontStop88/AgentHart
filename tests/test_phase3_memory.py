import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from main import handle_add_lesson, handle_memory_stats
from memory_factory import create_memory_store
from structured_memory import SQLiteMemoryStore


class Phase3StructuredMemoryTests(unittest.TestCase):
    def test_sqlite_store_imports_legacy_json_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            legacy = base / "memory.json"
            legacy.write_text(
                json.dumps(
                    {
                        "user_preferences": {"tone": "direct"},
                        "notes": [
                            {
                                "text": "legacy note",
                                "created_at": "2026-04-24T10:00:00",
                            }
                        ],
                        "tasks": [
                            {
                                "id": "task-1",
                                "text": "legacy task",
                                "completed": False,
                                "created_at": "2026-04-24T10:01:00",
                                "due_date": None,
                                "priority": "high",
                            }
                        ],
                        "tool_results": [
                            {
                                "tool": "report",
                                "target": "Legacy",
                                "status": "ok",
                                "output": "legacy output",
                                "created_at": "2026-04-24T10:02:00",
                            }
                        ],
                        "chat_history": [
                            {
                                "role": "user",
                                "message": "hello",
                                "created_at": "2026-04-24T10:03:00",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            memory = SQLiteMemoryStore(base / "agent_hart.db", legacy_json_path=legacy)
            memory_again = SQLiteMemoryStore(base / "agent_hart.db", legacy_json_path=legacy)

            self.assertEqual(len(memory_again.list_notes()), 1)
            self.assertEqual(memory_again.list_notes()[0]["text"], "legacy note")
            self.assertEqual(memory_again.list_tasks()[0]["priority"], "high")
            self.assertEqual(memory_again.recent_tool_results(1)[0]["target"], "Legacy")
            self.assertEqual(memory_again.data["user_preferences"]["tone"], "direct")
            self.assertEqual(memory.memory_stats()["notes"], 1)
            memory.close()
            memory_again.close()

    def test_sqlite_lessons_summaries_and_stats(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = SQLiteMemoryStore(Path(tmp) / "agent_hart.db")

            lesson = memory.add_lesson("Prefer approval before system changes.")
            summary = memory.add_memory_summary("daily", "Built structured memory.")

            self.assertEqual(lesson["source"], "user")
            self.assertEqual(memory.list_lessons()[0]["text"], lesson["text"])
            self.assertEqual(memory.list_memory_summaries()[0]["summary"], summary["summary"])
            self.assertEqual(memory.memory_stats()["lessons"], 1)
            self.assertEqual(memory.data["memory_summaries"][0]["scope"], "daily")
            memory.close()

    def test_sqlite_approval_and_tool_result_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = SQLiteMemoryStore(Path(tmp) / "agent_hart.db")
            approval = memory.add_approval_request(
                "run_tool",
                "Run report",
                {"tool": "report", "target": "Phase 3"},
                risk_level="low",
                requires_approval=False,
            )
            memory.add_tool_result(
                "report",
                "Phase 3",
                "ok",
                "ok",
                approval_id=approval["id"],
            )
            memory.mark_approval_executed(approval["id"], "ok")

            self.assertEqual(memory.list_approval_requests()[0]["status"], "auto_approved")
            self.assertEqual(memory.list_tool_results()[0]["approval_id"], approval["id"])
            self.assertEqual(memory.list_audit_events()[-1]["event_type"], "approval_executed")
            memory.close()

    def test_factory_defaults_to_sqlite_and_can_use_json_backend(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            with patch.dict(os.environ, {}, clear=True):
                memory = create_memory_store(base)
                self.assertIsInstance(memory, SQLiteMemoryStore)
                self.assertTrue((base / "agent_hart.db").exists())
                memory.close()

            with patch.dict(os.environ, {"AGENT_HART_MEMORY_BACKEND": "json"}):
                json_memory = create_memory_store(base)
                self.assertTrue(str(json_memory.path).endswith("memory.json"))
                json_memory.close()

    def test_phase3_cli_helpers_work_with_sqlite(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = SQLiteMemoryStore(Path(tmp) / "agent_hart.db")

            with patch("builtins.print") as printed:
                handle_add_lesson("Remember that approvals are durable.", memory)
                handle_memory_stats(memory)

            output = "\n".join(str(call.args[0]) for call in printed.call_args_list)
            self.assertIn("Saved lesson", output)
            self.assertIn("lessons: 1", output)
            memory.close()


if __name__ == "__main__":
    unittest.main()
