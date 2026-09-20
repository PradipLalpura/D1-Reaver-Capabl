"""BYOK-capable LLM calls over OpenAI-compatible endpoints. stdlib HTTP, primary → fallback failover."""
from __future__ import annotations

import json
import os

from connectors import http
from connectors.keys import keys

PROVIDERS = {
    "groq": "https://api.groq.com/openai/v1/chat/completions",
    "openrouter": "https://openrouter.ai/api/v1/chat/completions",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
    "openai": "https://api.openai.com/v1/chat/completions",
}

KEY_NAMES = {
    "groq": ("GROQ_API_KEY",),
    "openrouter": ("OPENROUTER_API_KEY",),
    "gemini": ("GEMINI_API_KEY",),
    "openai": ("OPENAI_API_KEY",),
}

DEFAULT_MODEL = {
    "groq": "openai/gpt-oss-20b",
    "openrouter": "meta-llama/llama-3.1-8b-instruct",
    "gemini": "gemini-2.5-flash",
    "openai": "gpt-4o-mini",
}
# ponytail: free-tier model IDs rot without notice (both defaults died once already);
# env REAVER_PRIMARY_MODEL/_FALLBACK_MODEL overrides; a /models refresh belongs in Phase 7 doctor


class LLMError(Exception):
    pass


def _chain() -> list[tuple[str, str, str]]:
    """(provider, model, key) primary → fallback. Env overrides; built-ins are sane free-tier defaults."""
    out = []
    for prefix in ("REAVER_PRIMARY", "REAVER_FALLBACK"):
        provider = os.environ.get(prefix + "_PROVIDER", "").strip().lower()
        if not provider and prefix == "REAVER_PRIMARY":
            provider = "groq"
        if not provider and prefix == "REAVER_FALLBACK":
            provider = "gemini"
        if provider not in PROVIDERS:
            continue
        model = os.environ.get(prefix + "_MODEL", "").strip() or DEFAULT_MODEL[provider]
        key = os.environ.get(prefix + "_KEY", "").strip() or next(iter(keys(*KEY_NAMES[provider])), "")
        if key:
            out.append((provider, model, key))
    return out


def chat_json(system: str, user: str, *, temperature: float = 0.0) -> dict | list:
    """One JSON object back, or raise. Primary → fallback; every failure recorded in the message."""
    failures = []
    for provider, model, key in _chain():
        res = http.call(PROVIDERS[provider], method="POST", headers={"Authorization": "Bearer " + key},
                        payload={"model": model, "temperature": temperature,
                                 "messages": [{"role": "system", "content": system},
                                              {"role": "user", "content": user}]})
        if res["http"] != 200:
            failures.append("%s:%s http %s" % (provider, model, res["http"]))
            continue
        try:
            text = (http.json_body(res) or {}).get("choices", [{}])[0].get("message", {}).get("content", "")
            text = text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0]
            return json.loads(text)
        except (ValueError, IndexError, AttributeError) as exc:
            failures.append("%s:%s bad json (%s)" % (provider, model, type(exc).__name__))
    raise LLMError("all providers failed: " + "; ".join(failures) if failures else "no provider keys configured")
