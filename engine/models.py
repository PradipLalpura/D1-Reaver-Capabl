"""REAVER contracts. Pydantic is the law: anything crossing an MCP boundary validates here."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field


class OutputFormat(str, Enum):
    csv = "csv"
    json = "json"


class CriterionState(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


class LeadState(str, Enum):
    QUALIFIED = "QUALIFIED"
    DISQUALIFIED = "DISQUALIFIED"
    UNCERTAIN = "UNCERTAIN"


MAX_LEADS = 200


class Evidence(BaseModel):
    attribute: str = Field(min_length=1, max_length=120)
    value: str = Field(min_length=1, max_length=2000)
    source: str = Field(min_length=1, max_length=500)
    tier: Annotated[int, Field(ge=1, le=5)]
    observed_at: datetime
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]


class CriterionVerdict(BaseModel):
    criterion: str
    state: CriterionState
    reason: str
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    evidence: list[Evidence] = []


class LeadRecord(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    domain: str = Field(default="", max_length=300)
    website: str = Field(default="", max_length=500)
    city: str = ""
    country: str = ""
    industry: str = ""
    employee_count: str = ""
    contact_name: str = ""
    contact_email: str = ""
    email_status: str = ""
    state: LeadState = LeadState.UNCERTAIN
    confidence: Annotated[float, Field(ge=0.0, le=1.0)] = 0.0
    evidence_count: int = Field(default=0, ge=0)
    sources: list[str] = []


class TargetSpec(BaseModel):
    request: str = Field(min_length=3, max_length=4000)
    desired_count: Annotated[int, Field(ge=1, le=MAX_LEADS)] = 20
    output_format: OutputFormat = OutputFormat.csv
