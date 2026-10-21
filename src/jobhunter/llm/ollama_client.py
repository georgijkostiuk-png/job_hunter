"""Structured JSON generation against a local Ollama server.

Replaces the old "forced Claude tool call" pattern: Ollama's `format` field
takes a raw JSON Schema and grammar-constrains decoding to it, so the model
is *structurally* incapable of returning malformed JSON. A small model like
qwen2.5:1.5b can still fill that structure with wrong or nonsensical values,
so `generate_structured` layers a validate-and-retry loop on top — failures
(bad JSON, or a schema-valid-but-semantically-invalid payload) are fed back
to the model as a correction turn, up to `max_attempts` times.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, TypeVar

import requests

logger = logging.getLogger(__name__)

DEFAULT_HOST = "http://localhost:11434"
DEFAULT_MODEL = "qwen2.5:1.5b"
DEFAULT_NUM_CTX = 8192  # qwen2.5:1.5b supports up to 32768; 8192 covers long CVs/postings with headroom
MAX_ATTEMPTS = 3
CONNECT_TIMEOUT = 5.0

T = TypeVar("T")


class OllamaError(RuntimeError):
    """Base error for anything that goes wrong talking to Ollama."""


class OllamaNotRunning(OllamaError):
    pass


class OllamaModelMissing(OllamaError):
    pass


def _install_hint(host: str, model: str) -> str:
    return (
        f"Could not reach Ollama at {host}. Install it from https://ollama.com, "
        f"make sure it's running (it starts automatically on Windows, or run "
        f"`ollama serve`), and pull the model with `ollama pull {model}`."
    )


def check_available(host: str = DEFAULT_HOST, model: str = DEFAULT_MODEL, timeout: float = CONNECT_TIMEOUT) -> tuple[bool, str]:
    """Non-raising health check used by `jobhunter check`. Returns (ok, message)."""
    try:
        resp = requests.get(f"{host.rstrip('/')}/api/tags", timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        return False, f"not reachable at {host} ({e.__class__.__name__}) — {_install_hint(host, model)}"

    names = {m.get("name", "") for m in data.get("models", [])}
    base = model.split(":")[0]
    if model in names or any(n.startswith(base + ":") for n in names):
        return True, f"running at {host}, model '{model}' present"
    return False, f"running at {host}, but model '{model}' is not pulled — run `ollama pull {model}`"


def _chat(host: str, model: str, messages: list[dict], schema: dict, temperature: float, num_ctx: int, timeout: float) -> str:
    payload = {
        "model": model,
        "messages": messages,
        "format": schema,
        "stream": False,
        "options": {"temperature": temperature, "num_ctx": num_ctx},
    }
    try:
        resp = requests.post(f"{host.rstrip('/')}/api/chat", json=payload, timeout=timeout)
    except requests.ConnectionError as e:
        raise OllamaNotRunning(_install_hint(host, model)) from e
    except requests.Timeout as e:
        raise OllamaError(f"Ollama at {host} timed out after {timeout}s generating a response.") from e

    if resp.status_code == 404:
        raise OllamaModelMissing(f"Model '{model}' is not pulled. Run `ollama pull {model}`.")
    try:
        resp.raise_for_status()
    except requests.HTTPError as e:
        raise OllamaError(f"Ollama returned an error: {e}") from e

    body = resp.json()
    if "error" in body:
        err = str(body["error"])
        if "not found" in err.lower():
            raise OllamaModelMissing(f"Model '{model}' is not pulled. Run `ollama pull {model}`. ({err})")
        raise OllamaError(err)

    return body.get("message", {}).get("content", "")


def generate_structured(
    *,
    system: str,
    prompt: str,
    schema: dict,
    validate: Callable[[dict], T],
    host: str = DEFAULT_HOST,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.2,
    num_ctx: int = DEFAULT_NUM_CTX,
    max_attempts: int = MAX_ATTEMPTS,
    timeout: float = 180.0,
) -> T:
    """Chat completion grammar-constrained to `schema`, validated by `validate`.

    `validate` receives the parsed JSON dict and should return the final typed
    object (e.g. a pydantic `.model_validate(data)` call) or raise on
    semantically invalid data (wrong enum value, failed field constraint,
    etc.) — that exception's message is fed back to the model as a repair
    instruction for the next attempt.
    """
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]

    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        content = _chat(host, model, messages, schema, temperature, num_ctx, timeout)

        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            last_error = e
            logger.warning("Ollama attempt %d/%d: invalid JSON (%s), retrying", attempt, max_attempts, e)
            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content": f"That was not valid JSON ({e}). Reply again with valid JSON only."})
            continue

        try:
            return validate(data)
        except Exception as e:  # pydantic ValidationError or any caller-defined check
            last_error = e
            logger.warning("Ollama attempt %d/%d: schema-valid but failed validation (%s), retrying", attempt, max_attempts, e)
            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content": f"That JSON failed validation: {e}. Correct it and reply with valid JSON only."})
            continue

    raise OllamaError(f"Model '{model}' never produced valid output after {max_attempts} attempts: {last_error}")
