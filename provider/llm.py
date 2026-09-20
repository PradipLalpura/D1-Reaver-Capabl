"""BYOK-capable LLM calls over OpenAI-compatible endpoints. stdlib HTTP, primary → fallback failover."""
from __future__ import annotations

import json
import os

from connectors import http
from connectors.keys import KEY_NAMES, keys

PROVIDERS = {
    "groq": "https://api.groq.com/openai/v1/chat/completions",
    "openrouter": "https://openrouter.ai/api/v1/chat/completions",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
    "openai": "https://api.openai.com/v1/chat/completions",
    "anthropic": "https://api.anthropic.com/v1/messages",
    "custom": "",  # user-supplied https base URL, OpenAI-compatible path appended
}

KEY_NAMES_LLM = {
    "groq": KEY_NAMES["groq"],
    "openrouter": KEY_NAMES["openrouter"],
    "gemini": KEY_NAMES["gemini"],
    "openai": KEY_NAMES["openai"],
    "anthropic": KEY_NAMES["anthropic"],
    "custom": (),
}

DEFAULT_MODEL = {
    "groq": "openai/gpt-oss-20b",
    "openrouter": "qwen/qwen3.8-27b:free",
    "gemini": "gemini-2.5-flash",
    "openai": "gpt-4o-mini",
    "anthropic": "claude-haiku-4-5",
    "custom": "",
}
# ponytail: free-tier model IDs rot without notice (both defaults died once already);
# env REAVER_PRIMARY_MODEL/_FALLBACK_MODEL overrides; a /models refresh belongs in Phase 7 doctor


class LLMError(Exception):
    pass


def _chain(explicit: list[tuple] | None = None) -> list[tuple]:
    """(provider, model, key[, base]) primary → fallback. Explicit session chain wins; else env; else free-tier defaults."""
    if explicit:
        out = []
        for item in explicit:
            if len(item) == 3:
                p, m, k, base = (*item, "")
            elif len(item) == 4:
                p, m, k, base = item
            else:
                continue
            if p not in PROVIDERS or not m or not k:
                continue
            if p == "custom" and not base.startswith("https://"):
                continue
            out.append((p, m, k, base))
        return out
    out = []
    # ponytail: 3-deep default chain (groq → gemini → openrouter) because free tiers exhaust mid-run;
    # 4th+ providers only via explicit session/env config
    for prefix in ("REAVER_PRIMARY", "REAVER_FALLBACK", "REAVER_TERTIARY"):
        provider = os.environ.get(prefix + "_PROVIDER", "").strip().lower()
        if not provider and prefix == "REAVER_PRIMARY":
            provider = "groq"
        if not provider and prefix == "REAVER_FALLBACK":
            provider = "gemini"
        if not provider and prefix == "REAVER_TERTIARY":
            provider = "openrouter"
        if provider not in PROVIDERS:
            continue
        model = os.environ.get(prefix + "_MODEL", "").strip() or DEFAULT_MODEL[provider]
        key = os.environ.get(prefix + "_KEY", "").strip() or next(iter(keys(*KEY_NAMES_LLM[provider])), "")
        if key:
            out.append((provider, model, key, ""))
    return out


def _ask(provider: str, model: str, key: str, system: str, user: str, temperature: float,
         base: str = "") -> str:
    if provider == "custom":
        url = base.rstrip("/") + "/chat/completions"  # any OpenAI-compatible endpoint
    else:
        url = PROVIDERS[provider]
    if provider == "anthropic":
        res = http.call(PROVIDERS[provider], method="POST",
                        headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                        payload={"model": model, "max_tokens": 2000, "temperature": temperature,
                                 "system": system, "messages": [{"role": "user", "content": user}]})
        if res["http"] != 200:
            raise LLMError("http %s" % res["http"])
        blocks = (http.json_body(res) or {}).get("content", [])
        return "".join(b.get("text", "") for b in blocks if isinstance(b, dict))
    res = http.call(url, method="POST", headers={"Authorization": "Bearer " + key},
                    payload={"model": model, "temperature": temperature,
                             "messages": [{"role": "system", "content": system},
                                          {"role": "user", "content": user}]})
    if res["http"] != 200:
        raise LLMError("http %s" % res["http"])
    return (http.json_body(res) or {}).get("choices", [{}])[0].get("message", {}).get("content", "")


def chat_json(system: str, user: str, *, temperature: float = 0.0,
              chain: list[tuple] | None = None) -> dict | list:
    """One JSON object back, or raise. Primary → fallback; every failure recorded in the message."""
    failures = []
    for provider, model, key, *rest in _chain(chain):
        base = rest[0] if rest else ""
        try:
            text = _ask(provider, model, key, system, user, temperature, base).strip()
        except LLMError as exc:
            failures.append("%s:%s %s" % (provider, model, exc))
            continue
        try:
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0]
            return json.loads(text)
        except (ValueError, IndexError, AttributeError):
            pass
        try:  # salvage: parse the outermost {...} or [...] span, reject everything else
            start = min([i for i in (text.find("{"), text.find("[")) if i >= 0])
            end = max(text.rfind("}"), text.rfind("]"))
            return json.loads(text[start:end + 1])
        except (ValueError, IndexError, AttributeError) as exc:
            failures.append("%s:%s bad json (%s)" % (provider, model, type(exc).__name__))
    raise LLMError("all providers failed: " + "; ".join(failures) if failures else "no provider keys configured")
