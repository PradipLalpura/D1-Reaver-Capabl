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


@dataclass
class BackendResult:
    backend: str
    status: str  # OK | UNAVAILABLE | FAIL
    items: list[dict] = field(default_factory=list)
    latency_ms: int = 0
    note: str = ""
