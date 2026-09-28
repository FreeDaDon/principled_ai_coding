"""Score government contracting opportunities against a company profile. (Stub: the Director fills this in.)"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from opportunity_types import CompanyProfile, Opportunity, ScoredOpportunity


def load_opportunities(path: Path) -> list[Opportunity]:
    raise NotImplementedError


def score_opportunity(opp: Opportunity, profile: CompanyProfile, today: date) -> ScoredOpportunity:
    raise NotImplementedError


def rank_opportunities(
    opps: list[Opportunity], profile: CompanyProfile, today: date, min_score: int = 0
) -> list[ScoredOpportunity]:
    raise NotImplementedError
