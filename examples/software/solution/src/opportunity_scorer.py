"""Score government contracting opportunities against a company profile."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from opportunity_types import CompanyProfile, Opportunity, ScoredOpportunity


def load_opportunities(path: Path) -> list[Opportunity]:
    """Parse a JSON array of opportunities into typed models."""
    return [Opportunity.model_validate(item) for item in json.loads(Path(path).read_text())]


def score_opportunity(opp: Opportunity, profile: CompanyProfile, today: date) -> ScoredOpportunity:
    """Apply the scoring rules from the spec; expired opportunities score 0."""
    days_left = (opp.response_deadline - today).days
    if days_left < 0:
        return ScoredOpportunity(opportunity=opp, score=0, reasons=["expired"])

    score, reasons = 0, []
    if opp.naics_code in profile.naics_codes:
        score += 40
        reasons.append(f"NAICS {opp.naics_code} match")
    if opp.set_aside is None:
        score += 10
        reasons.append("full and open competition")
    elif opp.set_aside in profile.set_asides:
        score += 25
        reasons.append(f"{opp.set_aside} set-aside match")
    if opp.estimated_value is None:
        score += 10
        reasons.append("value not published")
    elif profile.min_value <= opp.estimated_value <= profile.max_value:
        score += 20
        reasons.append("value in range")
    if days_left <= 3:
        score -= 15
        reasons.append("deadline too close")
    else:
        score += 15
        reasons.append("enough time to respond")
    return ScoredOpportunity(opportunity=opp, score=max(0, min(100, score)), reasons=reasons)


def rank_opportunities(
    opps: list[Opportunity], profile: CompanyProfile, today: date, min_score: int = 0
) -> list[ScoredOpportunity]:
    """Score all, drop expired and below min_score, sort by score desc then deadline asc."""
    scored = [score_opportunity(o, profile, today) for o in opps]
    kept = [s for s in scored if "expired" not in s.reasons and s.score >= min_score]
    return sorted(kept, key=lambda s: (-s.score, s.opportunity.response_deadline))
