import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from main import (
    build_agent_performance,
    handle_agent_status,
    handle_health_check,
    handle_health_history,
    handle_health_report,
    handle_run_review,
)
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
            "ping": {"enabled": True, "requires_approval": True, "risk_level": "low"},
            "nslookup": {"enabled": True, "requires_approval": True, "risk_level": "low"},
            "report": {"enabled": True, "requires_approval": False, "risk_level": "low"},
        },
    }
    path.write_text(json.dumps(policy), encoding="utf-8")


def fake_ollama(ok=True):
    return {
        "ok": ok,
        "base_url": "http://localhost:11434",
        "model": "gemma4",
        "timeout_seconds": 60,
        "num_ctx": 4096,
        "temperature": 0.2,
        "message": "OK" if ok else "offline",
    }


class Phase12LearningHealthTests(unittest.TestCase):
    def test_health_check_saves_report_and_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            write_policy(base / "policy.json")
            memory = MemoryStore(base / "memory.json")
            tools = ToolRegistry(base / "policy.json", base / "reports")

            with patch("main.ollama_health_check", return_value=fake_ollama()), patch(
                "builtins.print"
            ) as printed:
                handle_health_check(memory, tools, base)
                handle_health_report(memory)
                handle_health_history(memory)

            output = "\n".join(str(call.args[0]) for call in printed.call_args_list)
            self.assertEqual(len(memory.list_health_checks()), 1)
            self.assertEqual(memory.list_health_checks()[0]["overall_status"], "ok")
            self.assertIn("Agent Hart Health: ok", output)
            self.assertIn("memory_writable", output)

    def test_health_check_degrades_when_ollama_warns(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            write_policy(base / "policy.json")
            memory = MemoryStore(base / "memory.json")
            tools = ToolRegistry(base / "policy.json", base / "reports")

            with patch("main.ollama_health_check", return_value=fake_ollama(ok=False)), patch(
                "builtins.print"
            ):
                handle_health_check(memory, tools, base)

            self.assertEqual(memory.list_health_checks()[0]["overall_status"], "degraded")

    def test_run_review_saves_learning_outcome_and_agent_stats(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = MemoryStore(Path(tmp) / "memory.json")
            agent = memory.add_agent("Reporter", allowed_tools=["report"])
            goal = memory.add_goal(agent["id"], "Write report.")
            memory.add_task_run(agent["id"], goal["id"], status="waiting_for_review")

            with patch("builtins.print") as printed:
                handle_run_review("1 success Report looked good.", memory)
                handle_agent_status(memory)

            output = "\n".join(str(call.args[0]) for call in printed.call_args_list)
            self.assertEqual(memory.list_run_reviews()[0]["outcome"], "success")
            self.assertIn("Saved run review", output)
            self.assertIn("Reporter: reviews=1 success_rate=100%", output)

    def test_run_review_rejects_unknown_outcomes(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = MemoryStore(Path(tmp) / "memory.json")
            agent = memory.add_agent("Reporter", allowed_tools=["report"])
            run = memory.add_task_run(agent["id"], status="waiting_for_review")

            with patch("builtins.print") as printed:
                handle_run_review(f"{run['id'][:8]} weird Nope", memory)

            output = "\n".join(str(call.args[0]) for call in printed.call_args_list)
            self.assertIn("Outcome must be one of", output)
            self.assertEqual(memory.list_run_reviews(), [])

    def test_sqlite_health_and_reviews_persist(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            write_policy(base / "policy.json")
            db_path = base / "agent_hart.db"
            memory = SQLiteMemoryStore(db_path)
            tools = ToolRegistry(base / "policy.json", base / "reports")
            agent = memory.add_agent("Recon", allowed_tools=["ping"])
            run = memory.add_task_run(agent["id"], status="waiting_for_review")

            with patch("main.ollama_health_check", return_value=fake_ollama()), patch(
                "builtins.print"
            ):
                handle_health_check(memory, tools, base)
                handle_run_review(f"{run['id'][:8]} blocked_by_policy Ping blocked.", memory)
            memory.close()

            memory_again = SQLiteMemoryStore(db_path)
            self.assertEqual(memory_again.memory_stats()["health_checks"], 1)
            self.assertEqual(memory_again.memory_stats()["run_reviews"], 1)
            self.assertEqual(
                build_agent_performance(memory_again)[0]["common_outcome"],
                "blocked_by_policy",
            )
            memory_again.close()

    def test_learning_health_stress(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            write_policy(base / "policy.json")
            memory = SQLiteMemoryStore(base / "agent_hart.db")
            tools = ToolRegistry(base / "policy.json", base / "reports")
            agent = memory.add_agent("Stress Agent", allowed_tools=["report"])

            with patch("main.ollama_health_check", return_value=fake_ollama()), patch(
                "builtins.print"
            ):
                try:
                    for index in range(40):
                        handle_health_check(memory, tools, base)
                        run = memory.add_task_run(agent["id"], status="waiting_for_review")
                        outcome = "success" if index % 2 == 0 else "bad_plan"
                        handle_run_review(
                            f"{run['id'][:8]} {outcome} Stress review {index}", memory
                        )

                    performance = build_agent_performance(memory)[0]
                    self.assertEqual(memory.memory_stats()["health_checks"], 40)
                    self.assertEqual(memory.memory_stats()["run_reviews"], 40)
                    self.assertEqual(performance["success_rate"], 50)
                finally:
                    memory.close()


if __name__ == "__main__":
    unittest.main()
