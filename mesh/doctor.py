"""Static source registry. Phase 1: declared, not probed. Real probes land in Phase 2."""
SOURCES = [
    {"name": "tavily", "role": "primary discovery + research content", "status": "PLANNED"},
    {"name": "serper", "role": "bulk discovery volume", "status": "PLANNED"},
    {"name": "serpapi", "role": "recurring fallback discovery", "status": "PLANNED"},
    {"name": "exa", "role": "entity search + cross-check", "status": "PLANNED"},
    {"name": "github", "role": "tech/activity signals", "status": "PLANNED"},
    {"name": "apollo", "role": "firmographic + people enrichment", "status": "PLANNED"},
    {"name": "hunter", "role": "email verification", "status": "PLANNED"},
    {"name": "apify", "role": "structured actors (maps, company pages)", "status": "PLANNED"},
    {"name": "yt-dlp", "role": "zero-key video captions/search", "status": "PLANNED"},
    {"name": "jina", "role": "page-text extraction fallback", "status": "PLANNED"},
    {"name": "osm", "role": "zero-cost local/maps entities", "status": "PLANNED"},
    {"name": "deterministic-core", "role": "normalize/verify/dedup/export", "status": "WIRED"},
]


def registry() -> list[dict]:
    return [dict(source) for source in SOURCES]
