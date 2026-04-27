import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from main import execute_approval, find_approval, handle_run
from memory import MemoryStore
from tools import PolicyError, Tool, ToolRegistry


def write_policy(path, require_network_approval=True):
    policy = {
        "allow_shell_commands": False,
        "require_approval_for_network_tools": require_network_approval,
        "max_target_length": 40,
        "allowed_domains": ["localhost", "testlab.local"],
        "blocked_actions": ["delete_files", "exfiltrate_data", "run_unknown_script"],
        "tools": {
            "ping": {
                "enabled": True,
                "requires_approval": True,
                "risk_level": "low",
            },
            "nslookup": {
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


class Phase1CoreTests(unittest.TestCase):
    def test_memory_migrates_old_schema_and_saves_repair(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory_path = Path(tmp) / "memory.json"
            memory_path.write_text(
                json.dumps(
                    {
                        "user_preferences": {},
                        "notes": [],
                        "tasks": [{"text": "legacy task", "completed": False}],
                        "tool_results": [],
                        "chat_history": [],
                    }
                ),
                encoding="utf-8",
            )

            memory = MemoryStore(memory_path)
            saved = json.loads(memory_path.read_text(encoding="utf-8"))

            self.assertIn("approval_requests", memory.data)
            self.assertIn("audit_log", memory.data)
            self.assertIn("id", memory.data["tasks"][0])
            self.assertIn("approval_requests", saved)
            self.assertIn("id", saved["tasks"][0])

    def test_policy_blocks_unknown_disabled_and_bad_network_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy_path = Path(tmp) / "policy.json"
            write_policy(policy_path)
            tools = ToolRegistry(policy_path, Path(tmp) / "reports")

            for target in [
                "example.com",
                "localhost;del",
                "localhost\nbad",
                "local..host",
                "a" * 41,
            ]:
                with self.subTest(target=target):
                    with self.assertRaises(PolicyError):
                        tools.request_proposal("ping", target)

            with self.assertRaises(PolicyError):
                tools.request_proposal("shell", "localhost")

    def test_approval_lifecycle_records_audit_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = MemoryStore(Path(tmp) / "memory.json")
            approval = memory.add_approval_request(
                "run_tool",
                "Run tool 'ping' against 'localhost'",
                {"tool": "ping", "target": "localhost"},
                risk_level="low",
                requires_approval=True,
            )

            self.assertEqual(approval["status"], "pending")
            decided = memory.decide_approval(
                approval["id"], False, reason="stress-test rejection"
            )

            self.assertEqual(decided["status"], "rejected")
            self.assertEqual(memory.list_approval_requests("pending"), [])
            self.assertGreaterEqual(len(memory.data["audit_log"]), 2)

    def test_execute_approved_tool_links_result_to_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = MemoryStore(Path(tmp) / "memory.json")
            policy_path = Path(tmp) / "policy.json"
            write_policy(policy_path)
            tools = ToolRegistry(policy_path, Path(tmp) / "reports")
            tools.register(
                Tool(
                    name="ping",
                    description="Fake ping for tests.",
                    category="network",
                    action=lambda target, memory: f"fake ping ok: {target}",
                )
            )

            approval = memory.add_approval_request(
                "run_tool",
                "Run tool 'ping' against 'localhost'",
                {"tool": "ping", "target": "localhost"},
                risk_level="low",
                requires_approval=True,
            )
            memory.decide_approval(approval["id"], True, reason="test approval")

            with patch("builtins.print"):
                execute_approval(approval, memory, tools)

            self.assertEqual(memory.data["tool_results"][0]["approval_id"], approval["id"])
            self.assertEqual(
                memory.get_approval_request(approval["id"])["execution_status"], "ok"
            )

    def test_handle_run_rejection_leaves_no_tool_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = MemoryStore(Path(tmp) / "memory.json")
            policy_path = Path(tmp) / "policy.json"
            write_policy(policy_path)
            tools = ToolRegistry(policy_path, Path(tmp) / "reports")
            tools.register(
                Tool(
                    name="ping",
                    description="Fake ping for tests.",
                    category="network",
                    action=lambda target, memory: "should not run",
                )
            )

            with patch("builtins.input", return_value="no"), patch("builtins.print"):
                handle_run("ping localhost", memory, tools)

            self.assertEqual(memory.data["approval_requests"][0]["status"], "rejected")
            self.assertEqual(memory.data["tool_results"], [])

    def test_handle_run_auto_approved_report_executes(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = MemoryStore(Path(tmp) / "memory.json")
            policy_path = Path(tmp) / "policy.json"
            reports_dir = Path(tmp) / "reports"
            write_policy(policy_path)
            tools = ToolRegistry(policy_path, reports_dir)

            with patch("builtins.print"):
                handle_run("report Stress Report", memory, tools)

            approval = memory.data["approval_requests"][0]
            self.assertEqual(approval["status"], "auto_approved")
            self.assertEqual(approval["execution_status"], "ok")
            self.assertEqual(memory.data["tool_results"][0]["approval_id"], approval["id"])
            self.assertTrue((reports_dir / "stress-report.md").exists())

    def test_find_approval_requires_unique_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = MemoryStore(Path(tmp) / "memory.json")
            first = memory.add_approval_request("run_tool", "first", {}, "low", True)
            second = memory.add_approval_request("run_tool", "second", {}, "low", True)
            first["id"] = "abc11111-0000-0000-0000-000000000000"
            second["id"] = "abc22222-0000-0000-0000-000000000000"
            memory.save()

            self.assertIsNone(find_approval(memory, "abc"))
            self.assertEqual(find_approval(memory, "abc111")["description"], "first")


if __name__ == "__main__":
    unittest.main()
