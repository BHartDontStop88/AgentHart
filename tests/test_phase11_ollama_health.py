import sys
import types
import unittest
from unittest.mock import patch

from ai import ollama_chat, ollama_config, ollama_health_check
from main import handle_ollama_health


class FakeOllamaClient:
    calls = []
    should_fail = False

    def __init__(self, host=None, timeout=None):
        self.host = host
        self.timeout = timeout

    def chat(self, model, messages, options=None):
        if self.should_fail:
            raise RuntimeError("connection refused")
        self.calls.append(
            {
                "host": self.host,
                "timeout": self.timeout,
                "model": model,
                "messages": messages,
                "options": options or {},
            }
        )
        return {"message": {"content": "OK"}}


def fake_ollama_module():
    module = types.SimpleNamespace()
    module.Client = FakeOllamaClient
    return module


class Phase11OllamaHealthTests(unittest.TestCase):
    def setUp(self):
        FakeOllamaClient.calls = []
        FakeOllamaClient.should_fail = False

    def test_ollama_config_reads_environment_with_defaults(self):
        with patch.dict(
            "os.environ",
            {
                "OLLAMA_MODEL": "gemma4",
                "OLLAMA_BASE_URL": "http://ollama.local:11434",
                "OLLAMA_TIMEOUT_SECONDS": "12",
                "OLLAMA_NUM_CTX": "8192",
                "OLLAMA_TEMPERATURE": "0.4",
            },
            clear=True,
        ):
            config = ollama_config()

        self.assertEqual(config["model"], "gemma4")
        self.assertEqual(config["base_url"], "http://ollama.local:11434")
        self.assertEqual(config["timeout_seconds"], 12)
        self.assertEqual(config["num_ctx"], 8192)
        self.assertEqual(config["temperature"], 0.4)

    def test_ollama_chat_uses_configured_client_and_options(self):
        with patch.dict(
            sys.modules, {"ollama": fake_ollama_module()}
        ), patch.dict(
            "os.environ",
            {
                "OLLAMA_MODEL": "gemma4",
                "OLLAMA_BASE_URL": "http://remote:11434",
                "OLLAMA_TIMEOUT_SECONDS": "9",
                "OLLAMA_NUM_CTX": "2048",
                "OLLAMA_TEMPERATURE": "0.1",
            },
            clear=True,
        ):
            response = ollama_chat("hello")

        self.assertEqual(response, "OK")
        self.assertEqual(FakeOllamaClient.calls[0]["host"], "http://remote:11434")
        self.assertEqual(FakeOllamaClient.calls[0]["timeout"], 9)
        self.assertEqual(FakeOllamaClient.calls[0]["model"], "gemma4")
        self.assertEqual(FakeOllamaClient.calls[0]["options"]["num_ctx"], 2048)
        self.assertEqual(FakeOllamaClient.calls[0]["options"]["temperature"], 0.1)

    def test_ollama_health_check_success(self):
        with patch.dict(sys.modules, {"ollama": fake_ollama_module()}):
            result = ollama_health_check()

        self.assertTrue(result["ok"])
        self.assertEqual(result["message"], "OK")

    def test_ollama_health_check_failure_is_structured(self):
        FakeOllamaClient.should_fail = True
        with patch.dict(sys.modules, {"ollama": fake_ollama_module()}):
            result = ollama_health_check()

        self.assertFalse(result["ok"])
        self.assertIn("Could not reach Ollama", result["message"])

    def test_cli_health_prints_status(self):
        with patch(
            "main.ollama_health_check",
            return_value={
                "ok": True,
                "base_url": "http://localhost:11434",
                "model": "gemma4",
                "timeout_seconds": 60,
                "num_ctx": 4096,
                "temperature": 0.2,
                "message": "OK",
            },
        ), patch("builtins.print") as printed:
            handle_ollama_health()

        output = "\n".join(str(call.args[0]) for call in printed.call_args_list)
        self.assertIn("Ollama health: ok", output)
        self.assertIn("Model: gemma4", output)

    def test_ollama_health_failure_stress(self):
        FakeOllamaClient.should_fail = True
        with patch.dict(sys.modules, {"ollama": fake_ollama_module()}):
            results = [ollama_health_check() for _ in range(50)]

        self.assertEqual(sum(1 for result in results if result["ok"]), 0)
        self.assertTrue(all("connection refused" in result["message"] for result in results))


if __name__ == "__main__":
    unittest.main()
