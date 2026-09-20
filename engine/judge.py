"""Criterion rules. Code decides PASS/FAIL/UNKNOWN; the LLM never grades. Absence → UNKNOWN, never FAIL."""
from __future__ import annotations

from engine.deterministic import _conflicts, _numeric, normalize_name
from engine.models import CriterionState, CriterionVerdict, Evidence

STOPWORDS = {"the", "and", "with", "that", "have", "has", "are", "for", "from", "this", "which",
             "should", "must", "any", "all", "more", "than", "into", "your", "their"}

HARD_KINDS = {"location", "industry"}


def _kind(criterion: str) -> str:
    text = criterion.lower()
    if any(token in text for token in ("countr", "city", "cities", "located", "geograph", "based in", "region")):
        return "location"
    if any(token in text for token in ("industr", "sector", "vertical", "domain ", " field")):
        return "industry"
    if any(token in text for token in ("size", "employee", "headcount", "staff", "people", "team of")):
        return "size"
    if any(token in text for token in ("hir", "recruit", "job", "opening", "vacanc")):
        return "hiring"
    if any(token in text for token in ("email", "contact", "phone", "reach")):
        return "contact"
    return "keyword"


def _values(attrs: dict[str, list[Evidence]], *names: str) -> list[Evidence]:
    return [e for name in names for e in attrs.get(name, [])]


def _conflict_reason(used: list[Evidence]) -> str:
    """Any attribute judged from disagreeing sources is UNKNOWN — averaging lies."""
    bad, distinct = _conflicts([e.value for e in used])
    return ("conflicting evidence: " + " vs ".join(distinct[:3])) if bad else ""


def _confidence(used: list[Evidence]) -> float:
    if not used:
        return 0.0
    weights = {1: 1.0, 2: 0.8, 3: 0.6, 4: 0.4, 5: 0.0}
    return round(sum(e.confidence * weights[e.tier] for e in used) / len(used), 2)


def judge_criterion(criterion: str, attrs: dict[str, list[Evidence]]) -> CriterionVerdict:
    """One testable requirement → verdict. Conflicting or missing evidence → UNKNOWN with reason."""
    kind = _kind(criterion)
    flat = [e for group in attrs.values() for e in group]
    if not flat:
        return CriterionVerdict(criterion=criterion, state=CriterionState.UNKNOWN,
                                reason="no evidence", confidence=0.0)

    if kind == "location":
        used = _values(attrs, "country", "city")
        if not used:
            return CriterionVerdict(criterion=criterion, state=CriterionState.UNKNOWN,
                                    reason="no location evidence", confidence=0.0)
        blocked = _conflict_reason(used)
        if blocked:
            return CriterionVerdict(criterion=criterion, state=CriterionState.UNKNOWN,
                                    reason=blocked, confidence=0.0, evidence=used)
        haystack = " ".join(e.value.lower() for e in used)
        wants = [w for w in normalize_name(criterion).split() if len(w) > 2 and w not in STOPWORDS]
        if any(w in haystack for w in wants):
            return CriterionVerdict(criterion=criterion, state=CriterionState.PASS,
                                    reason="location matched", confidence=_confidence(used), evidence=used)
        return CriterionVerdict(criterion=criterion, state=CriterionState.FAIL,
                                reason="location mismatch", confidence=_confidence(used), evidence=used)

    if kind == "industry":
        used = _values(attrs, "industry")
        if not used:
            return CriterionVerdict(criterion=criterion, state=CriterionState.UNKNOWN,
                                    reason="no industry evidence", confidence=0.0)
        blocked = _conflict_reason(used)
        if blocked:
            return CriterionVerdict(criterion=criterion, state=CriterionState.UNKNOWN,
                                    reason=blocked, confidence=0.0, evidence=used)
        haystack = " ".join(e.value.lower() for e in used)
        wants = [w for w in normalize_name(criterion).split() if len(w) > 2 and w not in STOPWORDS]
        if any(w in haystack for w in wants):
            return CriterionVerdict(criterion=criterion, state=CriterionState.PASS,
                                    reason="industry matched", confidence=_confidence(used), evidence=used)
        return CriterionVerdict(criterion=criterion, state=CriterionState.FAIL,
                                reason="industry mismatch", confidence=_confidence(used), evidence=used)

    if kind == "size":
        used = _values(attrs, "employee_count")
        blocked = _conflict_reason(used)
        if blocked:
            return CriterionVerdict(criterion=criterion, state=CriterionState.UNKNOWN,
                                    reason=blocked, confidence=0.0, evidence=used)
        numbers = [n for n in (_numeric(e.value) for e in used) if n is not None]
        bounds = [_numeric(t) for t in criterion.replace(",", "").split()]
        bounds = [b for b in bounds if b is not None]
        if not numbers or not bounds:
            return CriterionVerdict(criterion=criterion, state=CriterionState.UNKNOWN,
                                    reason="no comparable size evidence", confidence=_confidence(used),
                                    evidence=used)
        actual, lo, hi = numbers[0], min(bounds), max(bounds)
        if lo <= actual <= (hi if len(bounds) > 1 else float("inf")):
            return CriterionVerdict(criterion=criterion, state=CriterionState.PASS,
                                    reason="size in range", confidence=_confidence(used), evidence=used)
        return CriterionVerdict(criterion=criterion, state=CriterionState.FAIL,
                                reason="size out of range", confidence=_confidence(used), evidence=used)

    if kind == "hiring":
        used = _values(attrs, "hiring")
        if not used:
            return CriterionVerdict(criterion=criterion, state=CriterionState.UNKNOWN,
                                    reason="no hiring evidence", confidence=0.0)
        blocked = _conflict_reason(used)
        if blocked:
            return CriterionVerdict(criterion=criterion, state=CriterionState.UNKNOWN,
                                    reason=blocked, confidence=0.0, evidence=used)
        haystack = " ".join(e.value.lower() for e in used)
        if any(w in haystack for w in ("active", "open", "hiring", "yes")):
            state, reason = CriterionState.PASS, "hiring signal active"
        elif any(w in haystack for w in ("none", "closed", "no hiring", "freeze")):
            state, reason = CriterionState.FAIL, "no hiring signal"
        else:
            state, reason = CriterionState.UNKNOWN, "hiring signal unclear"
        return CriterionVerdict(criterion=criterion, state=state, reason=reason,
                                confidence=_confidence(used), evidence=used)

    if kind == "contact":
        used = _values(attrs, "contact_email", "contact_name")
        if not used:
            return CriterionVerdict(criterion=criterion, state=CriterionState.UNKNOWN,
                                    reason="no contact evidence", confidence=0.0)
        return CriterionVerdict(criterion=criterion, state=CriterionState.PASS,
                                reason="contact present", confidence=_confidence(used), evidence=used)

    wants = [w for w in normalize_name(criterion).split() if len(w) > 3 and w not in STOPWORDS]
    hit = [e for e in flat if any(w in e.value.lower() for w in wants)]
    if hit:
        return CriterionVerdict(criterion=criterion, state=CriterionState.PASS,
                                reason="keyword evidenced", confidence=_confidence(hit), evidence=hit)
    return CriterionVerdict(criterion=criterion, state=CriterionState.UNKNOWN,
                            reason="no supporting evidence", confidence=0.0)


def judge_lead(criteria: list[str], attrs: dict[str, list[Evidence]]) -> tuple[str, float, list[CriterionVerdict]]:
    """Lead state: hard-kind FAIL → DISQUALIFIED; soft FAIL → UNCERTAIN; no PASS → UNCERTAIN."""
    verdicts = [judge_criterion(c, attrs) for c in criteria]
    kinds = [_kind(c) for c in criteria]
    states = [v.state for v in verdicts]
    score = round(sum(1.0 if s == CriterionState.PASS else 0.5 if s == CriterionState.UNKNOWN else 0.0
                      for s in states) / max(len(states), 1), 2)
    state = "UNCERTAIN"
    if any(s == CriterionState.FAIL and k in HARD_KINDS for s, k in zip(states, kinds)):
        state = "DISQUALIFIED"
    elif all(s == CriterionState.FAIL for s in states):
        state = "DISQUALIFIED"
    elif CriterionState.PASS in states and CriterionState.FAIL not in states:
        state = "QUALIFIED"
    confidence = round(sum(v.confidence for v in verdicts) / max(len(verdicts), 1), 2)
    return state, confidence if state == "QUALIFIED" else round(min(confidence, score), 2), verdicts
