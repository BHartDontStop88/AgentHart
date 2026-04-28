import json
import os


DEFAULT_OLLAMA_MODEL = "gemma4"
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_OLLAMA_TIMEOUT_SECONDS = 60
DEFAULT_OLLAMA_NUM_CTX = 4096
DEFAULT_OLLAMA_TEMPERATURE = 0.2


def ask_ai(message, context=None):
    """Send one user message to local Ollama and return response text."""
    prompt = message
    if context:
        # Context lets the local model answer using Agent Hart's saved memory.
        prompt = (
            "Use this Agent Hart memory context as background information.\n"
            "If the answer depends on memory, use only what is listed here.\n\n"
            f"{context}\n\n"
            f"User message: {message}"
        )

    return ollama_chat(prompt)


def suggest_action(message, context=None):
    """Ask local Ollama for one safe action suggestion and return it as a dict."""
    prompt = (
        "Decide whether the user message implies exactly one simple memory action.\n"
        "Allowed action: add_task only.\n"
        "Do not suggest deleting, completing, editing tasks, or running tools.\n"
        "Return plain JSON only, with no markdown or explanation.\n\n"
        "If there is a task to add, return:\n"
        '{"action":"add_task","text":"clean my room","due":"tomorrow","priority":"normal"}\n'
        'Use due as "today", "tomorrow", a YYYY-MM-DD date, or null.\n'
        'Use priority as "low", "normal", or "high".\n\n'
        'If there is no action, return: {"action":"none"}\n\n'
    )

    if context:
        prompt += f"Memory context:\n{context}\n\n"
    prompt += f"User message: {message}"

    response_text = ollama_chat(prompt)
    try:
        suggestion = json.loads(extract_json_object(response_text))
    except json.JSONDecodeError:
        return {"action": "none"}

    if not isinstance(suggestion, dict):
        return {"action": "none"}
    if suggestion.get("action") != "add_task":
        return {"action": "none"}

    return suggestion


def extract_json_object(text):
    """Return the first JSON object from model text, if one is present."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return text
    return text[start : end + 1]


def plan_goal(goal, context=None):
    """Ask local Ollama to turn a goal into short numbered planning steps."""
    prompt = (
        "Create a simple plan for the user's goal.\n"
        "Return plain text only.\n"
        "Use numbered steps.\n"
        "Keep each step short and actionable.\n\n"
    )
    if context:
        prompt += f"Agent Hart memory context:\n{context}\n\n"
    prompt += f"Goal: {goal}"

    return ollama_chat(prompt)


def ollama_chat(prompt):
    """Call the local Ollama chat API and return response text."""
    text, _ = ollama_chat_with_meta(prompt)
    return text


def ollama_chat_with_meta(prompt):
    """Call Ollama and return (response_text, meta_dict) with timing and token counts."""
    config = ollama_config()
    try:
        import ollama
    except ImportError:
        return "Ollama Python package is not installed. Run: pip install ollama", {}

    try:
        client = ollama.Client(
            host=config["base_url"],
            timeout=config["timeout_seconds"],
        )
        response = client.chat(
            model=config["model"],
            messages=[{"role": "user", "content": prompt}],
            options={
                "num_ctx": config["num_ctx"],
                "temperature": config["temperature"],
            },
        )
    except Exception as exc:
        msg = (
            "Could not reach Ollama or load the model. Make sure Ollama is "
            f"running at {config['base_url']} and the model is installed with: "
            f"ollama pull {config['model']}. "
            f"Details: {exc}"
        )
        return msg, {"error": str(exc)}

    prompt_tokens = response.get("prompt_eval_count", 0)
    response_tokens = response.get("eval_count", 0)
    eval_duration_ns = response.get("eval_duration", 0)
    load_duration_ns = response.get("load_duration", 0)
    tps = round(response_tokens / (eval_duration_ns / 1e9), 1) if eval_duration_ns > 0 else None
    ctx_pct = round(100 * (prompt_tokens + response_tokens) / config["num_ctx"], 1) if config["num_ctx"] > 0 else None

    meta = {
        "prompt_tokens": prompt_tokens,
        "response_tokens": response_tokens,
        "tokens_per_second": tps,
        "model_load_ms": round(load_duration_ns / 1e6, 1),
        "context_window_pct": ctx_pct,
        "total_duration_ms": round(response.get("total_duration", 0) / 1e6, 1),
    }
    return response["message"]["content"], meta


def ollama_config():
    """Read Ollama settings from environment variables with safe defaults."""
    return {
        "model": os.getenv("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL).strip()
        or DEFAULT_OLLAMA_MODEL,
        "base_url": os.getenv("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL).strip()
        or DEFAULT_OLLAMA_BASE_URL,
        "timeout_seconds": parse_int_env(
            "OLLAMA_TIMEOUT_SECONDS", DEFAULT_OLLAMA_TIMEOUT_SECONDS, minimum=1
        ),
        "num_ctx": parse_int_env("OLLAMA_NUM_CTX", DEFAULT_OLLAMA_NUM_CTX, minimum=512),
        "temperature": parse_float_env(
            "OLLAMA_TEMPERATURE", DEFAULT_OLLAMA_TEMPERATURE, minimum=0.0
        ),
    }


def parse_int_env(name, default, minimum=None):
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    if minimum is not None and value < minimum:
        return default
    return value


def parse_float_env(name, default, minimum=None):
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    if minimum is not None and value < minimum:
        return default
    return value


def ollama_health_check():
    """Return a structured health check for the configured Ollama service."""
    config = ollama_config()
    result = {
        "ok": False,
        "model": config["model"],
        "base_url": config["base_url"],
        "timeout_seconds": config["timeout_seconds"],
        "num_ctx": config["num_ctx"],
        "temperature": config["temperature"],
        "message": "",
    }

    try:
        import ollama
    except ImportError:
        result["message"] = "Ollama Python package is not installed. Run: pip install ollama"
        return result

    try:
        client = ollama.Client(
            host=config["base_url"],
            timeout=config["timeout_seconds"],
        )
        response = client.chat(
            model=config["model"],
            messages=[{"role": "user", "content": "Reply with OK."}],
            options={
                "num_ctx": config["num_ctx"],
                "temperature": 0,
            },
        )
    except Exception as exc:
        result["message"] = (
            "Could not reach Ollama or load the model. Make sure Ollama is "
            f"running at {config['base_url']} and the model is installed with: "
            f"ollama pull {config['model']}. Details: {exc}"
        )
        return result

    content = response.get("message", {}).get("content", "").strip()
    result["ok"] = True
    result["message"] = content or "Ollama responded without message content."
    return result
