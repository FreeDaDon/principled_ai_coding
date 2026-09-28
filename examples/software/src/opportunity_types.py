"""Types first: the contract the scorer is built against (read-only context for the agent)."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class Opportunity(BaseModel):
    notice_id: str
    title: str
    agency: str
    naics_code: str
    set_aside: str | None = None          # e.g. "SBA", "WOSB", "SDVOSB"; None = full and open
    response_deadline: date
    estimated_value: float | None = None  # USD; None = not published


class CompanyProfile(BaseModel):
    naics_codes: list[str]
    set_asides: list[str] = Field(default_factory=list)
    min_value: float = 0
    max_value: float = float("inf")


class ScoredOpportunity(BaseModel):
    opportunity: Opportunity
    score: int = Field(ge=0, le=100)
    reasons: list[str]
