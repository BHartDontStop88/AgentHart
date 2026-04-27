import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from memory import MemoryStore
from telegram_bot import (
    complete_task_request,
    decide_approval_request,
    format_pending_approvals,
    format_tasks,
    is_authorized_user,
    parse_allowed_user_ids,
    queue_tool_request,
    telegram_safe_text,
)
from tools import Tool, ToolRegistry


def write_policy(path):
    policy = {
        "allow_shell_commands": False,
        "require_approval_for_network_tools": True,
        "max_target_length": 80,
        "allowed_domains": ["localhost"],
        "blocked_actions": [],
        "tools": {
            "ping": {
                "enabled": True,
                "requires_approval": True,
                "risk_level": "low",
            },
            "report": {
                "enabled": True,
                "requires_approval": False,
                "risk_level": "low",
            },
        },
    }
    path.write_text(json.dumps(policy), encoding="utf-8")


class Phase2TelegramTests(unittest.TestCase):
    def test_allowed_user_ids_are_strict_numbers(self):
        self.assertEqual(parse_allowed_user_ids("123, 456"), {123, 456})
        self.assertEqual(parse_allowed_user_ids(""), set())
        with self.assertRaises(ValueError):
            parse_allowed_user_ids("123, nope")

    def test_authorization_requires_allowlist_unless_allow_all(self):
        self.assertTrue(is_authorized_user(123, {123}))
        self.assertFalse(is_authorized_user(999, {123}))
        self.assertTrue(is_authorized_user(999, set(), allow_all=True))

    def test_queue_tool_request_creates_pending_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            memory = MemoryStore(base / "memory.json")
            write_policy(base / "policy.json")
            tools = ToolRegistry(base / "policy.json", base / "reports")

            result = queue_tool_request("ping localhost", memory, tools)

            self.assertEqual(result["status"], "pending")
            self.assertIn("Approval required", result["message"])
            self.assertEqual(memory.data["approval_requests"][0]["status"], "pending")
            self.assertEqual(format_pending_approvals(memory).count("Run tool"), 1)

    def test_decide_approval_executes_tool_and_records_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            memory = MemoryStore(base / "memory.json")
            write_policy(base / "policy.json")
            tools = ToolRegistry(base / "policy.json", base / "reports")
            tools.register(
                Tool(
                    name="ping",
                    description="Fake ping.",
                    category="network",
                    action=lambda target, memory: f"telegram fake ok: {target}",
                )
            )
            queued = queue_tool_request("ping localhost", memory, tools)

            with patch("builtins.print"):
                result = decide_approval_request(
                    queued["approval"]["id"][:8], True, memory, tools
                )

            self.assertEqual(result["status"], "executed")
            self.assertIn("telegram fake ok", result["message"])
            self.assertEqual(memory.data["tool_results"][0]["tool"], "ping")
            self.assertEqual(
                memory.get_approval_request(queued["approval"]["id"])[
                    "execution_status"
                ],
                "ok",
            )

    def test_reject_approval_does_not_execute_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            memory = MemoryStore(base / "memory.json")
            write_policy(base / "policy.json")
            tools = ToolRegistry(base / "policy.json", base / "reports")
            tools.register(
                Tool(
                    name="ping",
                    description="Fake ping.",
                    category="network",
                    action=lambda target, memory: "should not run",
                )
            )
            queued = queue_tool_request("ping localhost", memory, tools)
            result = decide_approval_request(
                queued["approval"]["id"], False, memory, tools
            )

            self.assertEqual(result["status"], "rejected")
            self.assertEqual(memory.data["tool_results"], [])

    def test_auto_approved_report_runs_from_telegram_helper(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            memory = MemoryStore(base / "memory.json")
            write_policy(base / "policy.json")
            tools = ToolRegistry(base / "policy.json", base / "reports")

            with patch("builtins.print"):
                result = queue_tool_request("report Telegram Report", memory, tools)

            self.assertEqual(result["status"], "executed")
            self.assertEqual(memory.data["approval_requests"][0]["status"], "auto_approved")
            self.assertTrue((base / "reports" / "telegram-report.md").exists())

    def test_task_helpers_list_and_complete_tasks(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = MemoryStore(Path(tmp) / "memory.json")
            memory.add_task("Review Telegram phase", due_date="2026-04-30", priority="high")

            self.assertIn(
                "1. [ ] [high] [due: 2026-04-30] Review Telegram phase",
                format_tasks(memory),
            )
            self.assertEqual(complete_task_request("1", memory), "Completed task 1.")
            self.assertIn(
                "1. [x] [high] [due: 2026-04-30] Review Telegram phase",
                format_tasks(memory),
            )

    def test_done_helper_reports_invalid_task_numbers(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = MemoryStore(Path(tmp) / "memory.json")

            self.assertEqual(complete_task_request("0", memory), "Task number must be 1 or higher.")
            self.assertEqual(complete_task_request("nope", memory), "Usage: /done <task-number>")
            self.assertEqual(complete_task_request("1", memory), "No task found at 1.")

    def test_telegram_safe_text_truncates_long_output(self):
        text = telegram_safe_text("x" * 5000, limit=100)
        self.assertLessEqual(len(text), 100)
        self.assertIn("truncated", text)


if __name__ == "__main__":
    unittest.main()
