import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from main import handle_plan_agent, parse_planner_response
from memory import MemoryStore
from structured_memory import SQLiteMemoryStore
from tools import ToolRegistry


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


class Phase10PlannerCheckpointTests(unittest.TestCase):
    def test_parse_planner_response_accepts_valid_json(self):
        parsed = parse_planner_response(
            '{"thought_summary":"Use report.","next_action":"propose_tool",'
            '"tool":"report","target":"Daily","reason":"Need summary."}'
        )

        self.assertTrue(parsed["valid"])
        self.assertEqual(parsed["next_action"], "propose_tool")
        self.assertEqual(parsed["tool"], "report")

    def test_parse_planner_response_rejects_invalid_json(self):
        self.assertFalse(parse_planner_response("not json")["valid"])
        self.assertFalse(
            parse_planner_response('{"next_action":"run_shell"}')["valid"]
        )

    def test_plan_agent_creates_checkpoint_without_tool_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            write_policy(base / "policy.json")
            tools = ToolRegistry(base / "policy.json", base / "reports")
            memory = MemoryStore(base / "memory.json")
            agent = memory.add_agent("Reporter", allowed_tools=["report"])
            memory.add_goal(agent["id"], "Create a report.")

            response = (
                '{"thought_summary":"A report is appropriate.",'
                '"next_action":"propose_tool","tool":"report","target":"Daily",'
                '"reason":"The goal asks for a report."}'
            )
            with patch("main.ollama_chat", return_value=response), patch(
                "builtins.print"
            ) as printed:
                handle_plan_agent("1 1", memory, tools)

            output = "\n".join(str(call.args[0]) for call in printed.call_args_list)
            self.assertEqual(len(memory.list_task_runs()), 1)
            self.assertEqual(memory.list_task_runs()[0]["status"], "waiting_for_review")
            self.assertEqual(len(memory.list_run_steps()), 1)
            self.assertEqual(memory.list_run_steps()[0]["status"], "proposed")
            self.assertEqual(memory.list_run_steps()[0]["tool_name"], "report")
            self.assertEqual(memory.list_tool_results(), [])
            self.assertIn("No tools were executed.", output)

    def test_plan_agent_records_blocked_tool_proposal(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            write_policy(base / "policy.json")
            tools = ToolRegistry(base / "policy.json", base / "reports")
            memory = MemoryStore(base / "memory.json")
            agent = memory.add_agent("Reporter", allowed_tools=["report"])
            memory.add_goal(agent["id"], "Check localhost.")

            response = (
                '{"thought_summary":"Try ping.","next_action":"propose_tool",'
                '"tool":"ping","target":"localhost","reason":"Network check."}'
            )
            with patch("main.ollama_chat", return_value=response), patch(
                "builtins.print"
            ) as printed:
                handle_plan_agent("1 1", memory, tools)

            output = "\n".join(str(call.args[0]) for call in printed.call_args_list)
            self.assertEqual(memory.list_run_steps()[0]["status"], "blocked_proposal")
            self.assertIn("Policy check: blocked", output)
            self.assertEqual(memory.list_tool_results(), [])

    def test_sqlite_checkpoint_persists(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            write_policy(base / "policy.json")
            tools = ToolRegistry(base / "policy.json", base / "reports")
            db_path = base / "agent_hart.db"
            memory = SQLiteMemoryStore(db_path)
            agent = memory.add_agent("Waiter", allowed_tools=["report"])
            memory.add_goal(agent["id"], "Wait for more detail.")

            response = (
                '{"thought_summary":"Need more detail.","next_action":"wait",'
                '"tool":null,"target":null,"reason":"Goal is vague."}'
            )
            with patch("main.ollama_chat", return_value=response), patch("builtins.print"):
                handle_plan_agent("1 1", memory, tools)
            memory.close()

            memory_again = SQLiteMemoryStore(db_path)
            self.assertEqual(memory_again.memory_stats()["task_runs"], 1)
            self.assertEqual(memory_again.memory_stats()["run_steps"], 1)
            self.assertEqual(memory_again.list_run_steps()[0]["status"], "proposed")
            memory_again.close()

    def test_planner_checkpoint_stress(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            write_policy(base / "policy.json")
            tools = ToolRegistry(base / "policy.json", base / "reports")
            memory = SQLiteMemoryStore(base / "agent_hart.db")

            response = (
                '{"thought_summary":"Wait.","next_action":"wait",'
                '"tool":null,"target":null,"reason":"Stress checkpoint."}'
            )
            with patch("main.ollama_chat", return_value=response), patch("builtins.print"):
                for index in range(80):
                    agent = memory.add_agent(f"Agent {index}", allowed_tools=["report"])
                    memory.add_goal(agent["id"], f"Goal {index}")
                    handle_plan_agent(str(index + 1) + " 1", memory, tools)

            self.assertEqual(memory.memory_stats()["task_runs"], 80)
            self.assertEqual(memory.memory_stats()["run_steps"], 80)
            self.assertEqual(memory.memory_stats()["tool_results"], 0)
            memory.close()


if __name__ == "__main__":
    unittest.main()
