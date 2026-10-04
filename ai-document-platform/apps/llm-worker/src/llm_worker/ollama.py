"""Async HTTP client for Ollama.

Sends prompts to /api/generate with format=json, parses the response,
and returns the extracted JSON object along with token usage.
"""

import json
import time
from dataclasses import dataclass
from typing import Any

import httpx

from llm_worker.config import get_settings
from llm_worker.logging import get_logger
from llm_worker.metrics import LLM_OLLAMA_REQUEST_SECONDS, LLM_TOKENS_TOTAL

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class OllamaError(Exception):
    """Base class for Ollama-related errors."""


class OllamaTimeoutError(OllamaError):
    """Ollama did not respond within the configured timeout."""


class OllamaInvalidJSONError(OllamaError):
    """Ollama returned a response that is not valid JSON."""


class OllamaHTTPError(OllamaError):
    """Ollama returned a non-2xx HTTP response or connection error."""


# ---------------------------------------------------------------------------
# Result object
# ---------------------------------------------------------------------------

@dataclass
class OllamaUsage:
    """Token usage returned by Ollama."""

    prompt_tokens: int
    completion_tokens: int
    total_duration_ms: int


@dataclass
class OllamaResult:
    """Result of a single generate call."""

    data: dict[str, Any]
    usage: OllamaUsage


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

async def generate_json(
    prompt: str,
    system_prompt: str | None = None,
) -> OllamaResult:
    """Send a prompt to Ollama and return parsed JSON.

    Args:
        prompt: the user prompt.
        system_prompt: optional system context prepended to the prompt.

    Raises:
        OllamaTimeoutError: request exceeded ollama_timeout_seconds.
        OllamaHTTPError: connection error or non-2xx response.
        OllamaInvalidJSONError: response is not valid JSON.
    """
    settings = get_settings()

    full_prompt = prompt
    if system_prompt:
        full_prompt = f"{system_prompt}\n\n{prompt}"

    payload = {
        "model": settings.ollama_model,
        "prompt": full_prompt,
        "stream": False,
        "format": "json",
        "options": {
            "temperature": settings.ollama_temperature,
            "num_predict": settings.ollama_num_predict,
        },
    }

    url = f"{settings.ollama_endpoint}/api/generate"

    log.debug(
        "ollama_request",
        model=settings.ollama_model,
        prompt_chars=len(full_prompt),
    )

    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=settings.ollama_timeout_seconds) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
    except httpx.TimeoutException as exc:
        log.error("ollama_timeout", timeout_seconds=settings.ollama_timeout_seconds)
        raise OllamaTimeoutError(
            f"Ollama request exceeded {settings.ollama_timeout_seconds}s"
        ) from exc
    except httpx.HTTPError as exc:
        log.error("ollama_http_error", error=str(exc))
        raise OllamaHTTPError(f"Ollama HTTP error: {exc}") from exc
    finally:
        LLM_OLLAMA_REQUEST_SECONDS.observe(time.perf_counter() - start)

    body = response.json()
    raw = body.get("response", "")

    if not raw:
        raise OllamaInvalidJSONError("Ollama returned empty response field")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        log.error("ollama_invalid_json", raw=raw[:200])
        raise OllamaInvalidJSONError(
            f"Ollama response is not valid JSON: {exc}"
        ) from exc

    # Token usage
    prompt_tokens = int(body.get("prompt_eval_count", 0) or 0)
    completion_tokens = int(body.get("eval_count", 0) or 0)
    total_duration_ns = int(body.get("total_duration", 0) or 0)

    usage = OllamaUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_duration_ms=total_duration_ns // 1_000_000,
    )

    LLM_TOKENS_TOTAL.labels(kind="prompt").inc(prompt_tokens)
    LLM_TOKENS_TOTAL.labels(kind="completion").inc(completion_tokens)

    log.info(
        "ollama_response",
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        duration_ms=usage.total_duration_ms,
    )

    return OllamaResult(data=data, usage=usage)


async def check_ollama() -> bool:
    """Health check: verify Ollama is reachable."""
    settings = get_settings()
    url = f"{settings.ollama_endpoint}/api/tags"
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(url)
            response.raise_for_status()
        return True
    except Exception as exc:
        log.error("ollama_health_check_failed", error=str(exc))
        return False