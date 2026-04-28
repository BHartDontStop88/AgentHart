"""
Agent Metrics Collector — wraps any agent run and records telemetry to DB.
Usage:
    with AgentRun("daily_briefing", memory) as run:
        text, meta = ollama_chat_with_meta(prompt)
        run.record_llm(meta)
        run.add_output(1)   # one report generated
"""
import time
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))


def _system_snapshot():
    """Best-effort CPU/RAM snapshot. Returns (cpu_pct, ram_pct) or (None, None)."""
    try:
        import time as _time

        def _cpu():
            with open("/proc/stat") as f:
                vals = list(map(int, f.readline().split()[1:8]))
            total, idle = sum(vals), vals[3]
            _time.sleep(0.2)
            with open("/proc/stat") as f:
                vals2 = list(map(int, f.readline().split()[1:8]))
            dt = sum(vals2) - total
            di = vals2[3] - idle
            return round(100.0 * (1 - di / dt), 1) if dt else 0.0

        def _ram():
            m = {}
            with open("/proc/meminfo") as f:
                for line in f:
                    k, _, v = line.partition(":")
                    m[k.strip()] = int(v.strip().split()[0])
            total = m.get("MemTotal", 1)
            avail = m.get("MemAvailable", 0)
            return round(100.0 * (total - avail) / total, 1)

        return _cpu(), _ram()
    except Exception:
        return None, None


class AgentRun:
    """Context manager that bookends an agent run with metrics recording."""

    def __init__(self, agent_name: str, memory):
        self.agent_name = agent_name
        self.memory = memory
        self._run_id = None
        self._start = None
        self._llm_calls = 0
        self._prompt_tokens = 0
        self._response_tokens = 0
        self._tps_samples = []
        self._model_load_ms = None
        self._ctx_pct = None
        self._output_items = 0
        self._status = "success"
        self._error = None

    def __enter__(self):
        cpu, ram = _system_snapshot()
        self._run_id = self.memory.start_agent_run(self.agent_name, cpu, ram)
        self._start = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self._status = "error"
            self._error = f"{exc_type.__name__}: {exc_val}"
        duration = round(time.time() - self._start, 2)
        avg_tps = round(sum(self._tps_samples) / len(self._tps_samples), 1) if self._tps_samples else None
        self.memory.finish_agent_run(
            run_id=self._run_id,
            status=self._status,
            duration_seconds=duration,
            llm_calls=self._llm_calls,
            prompt_tokens=self._prompt_tokens,
            response_tokens=self._response_tokens,
            tokens_per_second=avg_tps,
            model_load_ms=self._model_load_ms,
            context_window_pct=self._ctx_pct,
            output_items=self._output_items,
            error_message=self._error,
        )
        return False  # don't suppress exceptions

    def record_llm(self, meta: dict):
        """Call after each ollama_chat_with_meta() to accumulate LLM stats."""
        if not meta or "error" in meta:
            return
        self._llm_calls += 1
        self._prompt_tokens += meta.get("prompt_tokens", 0)
        self._response_tokens += meta.get("response_tokens", 0)
        if meta.get("tokens_per_second"):
            self._tps_samples.append(meta["tokens_per_second"])
        if self._model_load_ms is None:
            self._model_load_ms = meta.get("model_load_ms")
        if meta.get("context_window_pct"):
            self._ctx_pct = meta["context_window_pct"]

    def add_output(self, count: int = 1):
        """Increment the count of useful outputs produced this run."""
        self._output_items += count

    def set_error(self, message: str):
        self._status = "error"
        self._error = message
