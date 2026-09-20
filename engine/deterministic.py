"""Deterministic core: normalization, evidence math, export. Zero LLM, zero network."""
from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from .models import CriterionState, CriterionVerdict, Evidence, LeadRecord, LeadState

LEGAL_SUFFIX = {"inc", "llc", "ltd", "corp", "co", "gmbh", "sarl", "pte", "pl", "llp", "pvt"}


def normalize_domain(raw: str) -> str:
    host = raw.strip().lower()
    host = re.sub(r"^[a-z][a-z0-9+.-]*://", "", host).split("/")[0].split("?")[0]
    return host[4:] if host.startswith("www.") else host


def normalize_name(raw: str) -> str:
    words = re.sub(r"[^a-z0-9 ]", "", raw.lower()).split()
    # ponytail: suffix-strip misfires on names like "Cook" (→"coo"+"k" is safe: only whole tokens); per-language suffixes need a locale table later
    words = [w for w in words if w not in LEGAL_SUFFIX]
    return re.sub(r"\s+", " ", " ".join(words)).strip()


def ensure_http_url(raw: str) -> str:
    parts = urlparse(raw.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("URL must use http(s) and include a host")
    return raw.strip()


def canonical_url(raw: str) -> str:
    url = raw.strip() if "://" in raw else "https://" + raw.strip()
    ensure_http_url(url)
    parts = urlparse(url)
    return parts.scheme + "://" + parts.hostname.lower() + parts.path.rstrip("/")  # noqa: query dropped — identity only


TIER_WEIGHT = {1: 1.0, 2: 0.8, 3: 0.6, 4: 0.4, 5: 0.0}


def age_days(ev: Evidence, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    observed = ev.observed_at if ev.observed_at.tzinfo else ev.observed_at.replace(tzinfo=timezone.utc)
    return max(0, (now - observed).days)


def _numeric(value: str) -> float | None:
    match = re.search(r"\d[\d,]*\.?\d*", value.replace(",", ""))
    try:
        return float(match.group()) if match else None
    except ValueError:
        return None


def _conflicts(values: list[str]) -> tuple[bool, list[str]]:
    distinct = sorted({v.strip().lower() for v in values})
    if len(distinct) < 2:
        return False, distinct
    numbers = [n for n in (_numeric(v) for v in distinct) if n is not None]
    if len(numbers) == len(distinct) and max(numbers) > 0:
        # ponytail: 10% spread tolerance; distribution-aware resolution needs Phase 3 verifier
        return (max(numbers) - min(numbers)) / max(numbers) > 0.10, distinct
    return True, distinct


def summarize_attribute(
    attribute: str, evidence: list[Evidence], ttl_days: int = 90, now: datetime | None = None
) -> dict:
    """Honesty gate: empty → unsupported, conflict → conflict, all-stale → stale. Never invents."""
    if not evidence:
        return {"attribute": attribute, "supported": False, "conflict": False,
                "stale": False, "reason": "no evidence", "evidence_count": 0}
    conflict, distinct = _conflicts([e.value for e in evidence])
    if conflict:
        return {"attribute": attribute, "supported": False, "conflict": True,
                "stale": False, "reason": "conflicting evidence: " + " vs ".join(distinct[:3]),
                "evidence_count": len(evidence)}
    stale = all(age_days(e, now) > ttl_days for e in evidence)
    return {"attribute": attribute, "supported": not stale, "conflict": False,
            "stale": stale, "reason": "stale evidence" if stale else "supported",
            "evidence_count": len(evidence)}


HUBSPOT_HEADERS = ["company", "domain", "website", "city", "country", "industry",
                   "employee_count", "contact_name", "contact_email", "email_status",
                   "lead_state", "confidence", "evidence_count", "sources"]


def _row(lead: LeadRecord) -> dict:
    return {"company": lead.name, "domain": lead.domain, "website": lead.website,
            "city": lead.city, "country": lead.country, "industry": lead.industry,
            "employee_count": lead.employee_count, "contact_name": lead.contact_name,
            "contact_email": lead.contact_email, "email_status": lead.email_status,
            "lead_state": lead.state.value, "confidence": lead.confidence,
            "evidence_count": lead.evidence_count, "sources": "; ".join(lead.sources)}


def to_csv(leads: list[LeadRecord]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=HUBSPOT_HEADERS)
    writer.writeheader()
    for lead in leads:
        writer.writerow(_row(lead))
    return buf.getvalue()


def to_json(leads: list[LeadRecord]) -> str:
    return json.dumps([_row(lead) for lead in leads], indent=2)


def merge_leads(leads: list[LeadRecord]) -> list[LeadRecord]:
    """Entity resolution: domain key first, name+country fallback. Merges, never silently drops."""
    merged: dict[str, LeadRecord] = {}
    for lead in leads:
        domain = normalize_domain(lead.domain) if lead.domain else ""
        key = "d:" + domain if domain else "n:" + normalize_name(lead.name) + "|" + lead.country.strip().lower()
        existing = merged.get(key)
        if existing is None:
            merged[key] = lead.model_copy()
            continue
        existing.sources = sorted(set(existing.sources) | set(lead.sources))
        existing.evidence_count += lead.evidence_count
        existing.confidence = max(existing.confidence, lead.confidence)
        states = {existing.state, lead.state}
        existing.state = (
            next(iter(states)) if len(states) == 1
            else existing.state.__class__.UNCERTAIN  # any disagreement → human reviews
        )
    return list(merged.values())
