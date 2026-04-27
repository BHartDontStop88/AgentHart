import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from main import handle_agent_check_tool
from memory import MemoryStore
from tools import PolicyError, ToolRegistry


def write_policy(path, report_enabled=True):
    policy = {
        "allow_shell_commands": False,
        "require_approval_for_network_tools": True,
        "max_target_length": 80,
        "allowed_domains": ["localhost", "testlab.local"],
        "blocked_actions": [],
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
                "enabled": report_enabled,
                "requires_approval": False,
                "risk_level": "low",
            },
        },
    }
    path.write_text(json.dumps(policy), encoding="utf-8")


class Phase9AgentPermissionTests(unittest.TestCase):
    def test_agent_allowed_tool_still_uses_global_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            write_policy(base / "policy.json")
            tools = ToolRegistry(base / "policy.json", base / "reports")
            agent = {
                "id": "agent-1",
                "name": "Recon",
                "status": "active",
                "allowed_tools": ["ping"],
            }

            proposal = tools.request_agent_proposal(agent, "ping", "localhost")

            self.assertEqual(proposal["payload"]["agent_id"], "agent-1")
            self.assertTrue(proposal["requires_approval"])
            self.assertIn("Recon", proposal["description"])

    def test_agent_blocked_when_tool_not_in_agent_allowlist(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            write_policy(base / "policy.json")
            tools = ToolRegistry(base / "policy.json", base / "reports")
            agent = {
                "id": "agent-1",
                "name": "Reporter",
                "status": "active",
                "allowed_tools": ["report"],
            }

            with self.assertRaisesRegex(PolicyError, "not allowed"):
                tools.request_agent_proposal(agent, "ping", "localhost")

    def test_global_policy_can_still_block_agent_allowed_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            write_policy(base / "policy.json", report_enabled=False)
            tools = ToolRegistry(base / "policy.json", base / "reports")
            agent = {
                "id": "agent-1",
                "name": "Reporter",
                "status": "active",
                "allowed_tools": ["report"],
            }

            with self.assertRaisesRegex(PolicyError, "disabled"):
                tools.request_agent_proposal(agent, "report", "Daily")

    def test_inactive_agent_cannot_request_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            write_policy(base / "policy.json")
            tools = ToolRegistry(base / "policy.json", base / "reports")
            agent = {
                "id": "agent-1",
                "name": "Dormant",
                "status": "paused",
                "allowed_tools": ["report"],
            }

            with self.assertRaisesRegex(PolicyError, "not active"):
                tools.request_agent_proposal(agent, "report", "Daily")

    def test_cli_agent_check_tool_is_dry_run_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            write_policy(base / "policy.json")
            tools = ToolRegistry(base / "policy.json", base / "reports")
            memory = MemoryStore(base / "memory.json")
            memory.add_agent("Reporter", allowed_tools=["report"])

            with patch("builtins.print") as printed:
                handle_agent_check_tool("1 report Daily", memory, tools)

            output = "\n".join(str(call.args[0]) for call in printed.call_args_list)
            self.assertIn("Allowed for Reporter", output)
            self.assertEqual(memory.list_approval_requests(), [])
            self.assertEqual(memory.list_tool_results(), [])

    def test_agent_permission_stress_matrix(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            write_policy(base / "policy.json")
            tools = ToolRegistry(base / "policy.json", base / "reports")
            allowed = 0
            blocked = 0

            for index in range(120):
                agent = {
                    "id": f"agent-{index}",
                    "name": f"Agent {index}",
                    "status": "active",
                    "allowed_tools": ["report"] if index % 2 == 0 else ["ping"],
                }
                tool_name = "report"
                target = f"Report {index}"
                try:
                    tools.request_agent_proposal(agent, tool_name, target)
                    allowed += 1
                except PolicyError:
                    blocked += 1

            self.assertEqual(allowed, 60)
            self.assertEqual(blocked, 60)


if __name__ == "__main__":
    unittest.main()
