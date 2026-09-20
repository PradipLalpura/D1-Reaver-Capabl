"""Key access. Process env wins; repo .env fills gaps (dev only, never committed). Values never leave this module."""
import os
from dataclasses import dataclass, field

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_dotenv() -> None:
    try:
        with open(os.path.join(ROOT, ".env"), encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    name, value = line.split("=", 1)
                    os.environ.setdefault(name.strip(), value.strip())
    except OSError:
        pass


_load_dotenv()


def keys(*names: str) -> list[str]:
    """Primary → fallback key values, empties dropped. Callers never log these."""
    return [value for name in names if (value := os.environ.get(name, "").strip())]


KEY_NAMES = {
    "tavily": ("TAVILY_PRIMARY_KEY", "TAVILY_FALLBACK_KEY"),
    "serper": ("SERPER_PRIMARY_KEY", "SERPER_FALLBACK_KEY"),
    "serpapi": ("SERP_PRIMARY_KEY", "SERP_FALLBACK_KEY"),
    "exa": ("EXA_PRIMARY_KEY", "EXA_FALLBACK_KEY"),
    "github": ("GITHUB_ACCESS_TOKEN",),
    "apollo": ("APOLLO_API_KEY",),
    "hunter": ("HUNTER_API_KEY",),
    "apify": ("APIFY_PRIMARY_KEY", "APIFY_FALLBACK_KEY", "APIFY_FALLBACK_KEY_2"),
    "groq": ("GROQ_API_KEY",),
    "openrouter": ("OPENROUTER_API_KEY",),
    "gemini": ("GEMINI_API_KEY",),
    "openai": ("OPENAI_API_KEY",),
    "anthropic": ("ANTHROPIC_API_KEY",),
}


@dataclass
class BackendResult:
    backend: str
    status: str  # OK | UNAVAILABLE | FAIL
    items: list[dict] = field(default_factory=list)
    latency_ms: int = 0
    note: str = ""
