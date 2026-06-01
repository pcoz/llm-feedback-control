"""LLM client for llm-feedback-control.

Two backends behind a tiny interface:
  * gen()         — a local Ollama model (default phi3:mini, the "small model")
  * gen_ceiling() — a stronger reference model: a larger Ollama model OR the
                    OpenAI API (used only as a quality CEILING in experiments)

Everything is configurable by environment variable so the same code runs
locally and on a remote box (e.g. EC2) without edits:

  OLLAMA_HOST      default http://localhost:11434
  LFC_MODEL        default phi3:mini            (the small model under test)
  LFC_CEILING      default llama3.1:8b          (a bigger local Ollama model)
  CEILING_BACKEND  "ollama" (default) or "openai"
  OPENAI_API_KEY   required iff CEILING_BACKEND=openai
  OPENAI_MODEL     default gpt-4o-mini

Only the standard library is used (urllib + json) — no SDK dependency, and the
whole package has **zero third-party runtime dependencies**.

You are never locked to Ollama: every high-level entry point in this package
(`run_audit`, `extract_iterative`, `regime_gate`, ...) accepts an injectable
``generate`` callable, so you can plug in OpenAI, Anthropic, a local server, or
any function ``f(prompt, fmt=None) -> str``. The functions in this module are
just the convenient defaults.
"""
import os
import json
import urllib.request
import urllib.error

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
MODEL = os.environ.get("LFC_MODEL", "phi3:mini")
CEILING_MODEL = os.environ.get("LFC_CEILING", "llama3.1:8b")
CEILING_BACKEND = os.environ.get("CEILING_BACKEND", "ollama")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")


class BackendError(RuntimeError):
    """No LLM backend was reachable. The message explains exactly what to do.

    Note: the high-level pipeline (`run_audit`, `extract_iterative`, ...) catches
    this internally and falls back to the deterministic path, so a missing model
    degrades gracefully rather than crashing. This is only raised to callers who
    invoke `gen` / `gen_ceiling` directly.
    """


def _ollama(prompt, fmt, model, timeout):
    """POST one prompt to the Ollama /api/generate endpoint and return the response
    text. Raises :class:`BackendError` (with guidance) if the server is unreachable."""
    body = {"model": model, "prompt": prompt, "stream": False,
            "options": {"temperature": 0.0}}
    if fmt:
        body["format"] = fmt
    req = urllib.request.Request(f"{OLLAMA_HOST}/api/generate",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read()).get("response", "")
    except urllib.error.URLError as e:
        raise BackendError(
            f"Could not reach an Ollama server at {OLLAMA_HOST} ({e}).\n"
            f"  - Install Ollama:  https://ollama.com\n"
            f"  - Start it and pull the small model:  ollama pull {MODEL}\n"
            f"  - Or point OLLAMA_HOST at a running server.\n"
            f"  - Or use OpenAI: set CEILING_BACKEND=openai and OPENAI_API_KEY,\n"
            f"    or pass your own generate=... callable.\n"
            f"  (The deterministic pipeline still works with NO model at all — "
            f"run_audit() falls back to a regex extractor + exact graph analysis.)"
        ) from e


def gen(prompt, fmt=None, model=None, timeout=600):
    """Generate from a local Ollama model. ``fmt="json"`` forces valid JSON.
    Greedy decode (temperature 0) for reproducibility.

    Raises :class:`BackendError` (with actionable guidance) if no server is
    reachable."""
    return _ollama(prompt, fmt, model or MODEL, timeout)


def _gen_openai(prompt, model=None, timeout=120):
    """Call the OpenAI chat-completions API (stdlib HTTP, no SDK), forcing a JSON
    response. Used as the "ceiling" backend when CEILING_BACKEND=openai."""
    try:
        key = os.environ["OPENAI_API_KEY"]
    except KeyError as e:
        raise BackendError(
            "CEILING_BACKEND=openai but OPENAI_API_KEY is not set in the "
            "environment."
        ) from e
    body = {"model": model or OPENAI_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0, "response_format": {"type": "json_object"}}
    req = urllib.request.Request("https://api.openai.com/v1/chat/completions",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json",
                                          "Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())["choices"][0]["message"]["content"]
    except urllib.error.URLError as e:
        raise BackendError(f"Could not reach the OpenAI API ({e}).") from e


def gen_ceiling(prompt, fmt="json", timeout=600):
    """Generate from the CEILING model (a stronger reference). Backend chosen by
    CEILING_BACKEND: a bigger local Ollama model, or the OpenAI API."""
    if CEILING_BACKEND == "openai":
        return _gen_openai(prompt, timeout=timeout)
    return gen(prompt, fmt=fmt, model=CEILING_MODEL, timeout=timeout)


def info():
    """One-line summary of the current backend configuration (for logs and
    ``lfc --check``)."""
    return (f"small={MODEL} @ {OLLAMA_HOST} | ceiling={CEILING_MODEL} "
            f"(backend={CEILING_BACKEND})")


def doctor():
    """Probe the configured backend and report what's available.

    Returns a status dict. Never raises — safe to call before anything is set
    up. Used by ``python -m llm_feedback_control --check``."""
    status = {
        "ollama_host": OLLAMA_HOST,
        "small_model": MODEL,
        "ceiling_backend": CEILING_BACKEND,
        "ceiling_model": CEILING_MODEL,
        "openai_key_set": bool(os.environ.get("OPENAI_API_KEY")),
    }
    try:
        req = urllib.request.Request(f"{OLLAMA_HOST}/api/tags")
        with urllib.request.urlopen(req, timeout=5) as r:
            models = json.loads(r.read()).get("models", [])
        names = [m.get("name") or m.get("model") for m in models]
        status["ollama_reachable"] = True
        status["models_available"] = names
        status["small_model_present"] = any(
            MODEL.split(":")[0] in (n or "") for n in names)
    except Exception as e:  # noqa: BLE001 — doctor must never raise
        status["ollama_reachable"] = False
        status["models_available"] = []
        status["small_model_present"] = False
        status["error"] = str(e)
    return status
