import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from main import handle_add_agent, handle_add_goal, handle_list_agents, handle_list_goals
from memory import MemoryStore
from structured_memory import SQLiteMemoryStore


class Phase7AgentRuntimeTests(unittest.TestCase):
    def test_json_agent_and_goal_cli_flow(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = MemoryStore(Path(tmp) / "memory.json")

            with patch("builtins.print") as printed:
                handle_add_agent(
                    "Recon --role researcher --tools ping,report --max-steps 7",
                    memory,
                )
                handle_add_goal("1 Map localhost service posture", memory)
                handle_list_agents(memory)
                handle_list_goals(memory)

            output = "\n".join(str(call.args[0]) for call in printed.call_args_list)
            agent = memory.list_agents()[0]
            goal = memory.list_goals()[0]

            self.assertEqual(agent["name"], "Recon")
            self.assertEqual(agent["role"], "researcher")
            self.assertEqual(agent["allowed_tools"], ["ping", "report"])
            self.assertEqual(agent["max_steps"], 7)
            self.assertEqual(goal["agent_id"], agent["id"])
            self.assertIn("Added agent Recon", output)
            self.assertIn("Added goal", output)
            self.assertIn("Recon: Map localhost service posture", output)

    def test_sqlite_agent_and_goal_persist(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "agent_hart.db"
            memory = SQLiteMemoryStore(db_path)
            agent = memory.add_agent(
                "Reporter",
                role="summarizer",
                allowed_tools=["report"],
                max_steps=3,
            )
            memory.add_goal(agent["id"], "Write a daily automation report.")
            memory.close()

            memory_again = SQLiteMemoryStore(db_path)
            self.assertEqual(memory_again.list_agents()[0]["name"], "Reporter")
            self.assertEqual(memory_again.list_agents()[0]["allowed_tools"], ["report"])
            self.assertEqual(memory_again.list_goals()[0]["status"], "pending")
            self.assertEqual(memory_again.memory_stats()["agents"], 1)
            self.assertEqual(memory_again.memory_stats()["goals"], 1)
            memory_again.close()

    def test_agent_runtime_stress_both_backends(self):
        for store_factory in (self.json_store, self.sqlite_store):
            with self.subTest(store=store_factory.__name__):
                memory = store_factory()
                try:
                    for index in range(150):
                        agent = memory.add_agent(
                            f"Agent {index}",
                            role="worker",
                            allowed_tools=["report"],
                            max_steps=5,
                        )
                        memory.add_goal(agent["id"], f"Goal {index}")

                    self.assertEqual(len(memory.list_agents()), 150)
                    self.assertEqual(len(memory.list_goals()), 150)
                    self.assertEqual(memory.memory_stats()["agents"], 150)
                    self.assertEqual(memory.memory_stats()["goals"], 150)
                    self.assertEqual(memory.memory_stats()["task_runs"], 0)
                    self.assertEqual(memory.memory_stats()["run_steps"], 0)
                finally:
                    memory.close()

    def json_store(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return MemoryStore(Path(tmp.name) / "memory.json")

    def sqlite_store(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return SQLiteMemoryStore(Path(tmp.name) / "agent_hart.db")


if __name__ == "__main__":
    unittest.main()
