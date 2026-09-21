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
# ponytail: free-tier model IDs rot without notice (defaults died twice already);
# env REAVER_PRIMARY_MODEL/_FALLBACK_MODEL overrides; live-list override below is the safety net
MODELS_TTL = 7 * 24 * 3600
JUNK_MODEL_HINTS = ("whisper", "guard", "tts", "embedding", "image", "moderation")


def refresh_models(force: bool = False) -> dict[str, list[str]]:
    """Live /models per keyed provider, cached 7d. Read-only, quota-trivial."""
    from data import cache
    out: dict[str, list[str]] = {}
    for provider, key_names in KEY_NAMES_LLM.items():
        if provider == "custom":
            continue
        keys_available = keys(*key_names)
        if not keys_available:
            continue
        key = cache.make_key("models", provider)
        hit = None if force else cache.get(key)
        if isinstance(hit, list):
            out[provider] = hit
            continue
        ids = _list_models(provider, keys_available[0])
        if ids is not None:
            cache.put(key, ids, MODELS_TTL)
            out[provider] = ids
    return out


def _list_models(provider: str, key: str) -> list[str] | None:
    urls = {
        "groq": "https://api.groq.com/openai/v1/models",
        "openrouter": "https://openrouter.ai/api/v1/models",
        "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/models",
        "openai": "https://api.openai.com/v1/models",
        "anthropic": "https://api.anthropic.com/v1/models",
    }
    headers = {"Authorization": "Bearer " + key}
    if provider == "anthropic":
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
    res = http.call(urls[provider], headers=headers)
    if res["http"] != 200:
        return None
    data = http.json_body(res) or {}
    ids = [m.get("id", "") for m in data.get("data", []) if m.get("id")]
    return ids or None


def resolve_model(provider: str) -> str:
    """Default model unless the live list proves it rotted — then best-effort pick, never a guess presented as fact."""
    default = DEFAULT_MODEL.get(provider, "")
    live = refresh_models().get(provider, [])
    if not live or default in live or default.split("/")[-1] in [i.split("/")[-1] for i in live]:
        return default
    candidates = [i for i in live if not any(h in i.lower() for h in JUNK_MODEL_HINTS)]
    preferred = [i for i in candidates if any(h in i.lower() for h in
                 ("flash", "mini", "instruct", "8b", "20b", "32b", "haiku"))]
    # ponytail: heuristic pick; wrong picks surface as honest provider errors, and env override always wins
    return (preferred or candidates or [default])[0]


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
        model = os.environ.get(prefix + "_MODEL", "").strip() or resolve_model(provider)
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
