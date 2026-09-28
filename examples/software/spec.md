# Opportunity Scorer
> Ingest this file, carry out the Low-Level Tasks in order, and produce code that satisfies the High and Mid-Level Objectives.

## High-Level Objective
- Rank government contracting opportunities by fit for a small business so the best bids surface first.

## Mid-Level Objective
- Load SAM.gov-style opportunity JSON into typed `Opportunity` models.
- Score each opportunity 0-100 against a `CompanyProfile` with human-readable reasons.
- Rank opportunities: drop expired and low scores, best first, earliest deadline breaks ties.
- `tests/test_opportunity_scorer.py` passes.

## Implementation Notes
- Types already exist in `src/opportunity_types.py`; import them, never redefine them.
- Scoring rules: NAICS match +40; set-aside match +25, full and open (set_aside None) +10; value in [min_value, max_value] +20, unknown value +10; deadline 3 days or fewer -15 ("deadline too close"), otherwise +15.
- Expired (deadline before today) scores 0 with reasons exactly `["expired"]`.
- Clamp the score to 0-100.
- Standard library + pydantic only. One-line docstring per function.

## Context

### Beginning context
- src/opportunity_types.py (read-only)
- tests/test_opportunity_scorer.py (read-only)
- fixtures/opportunities.json (read-only)
- src/opportunity_scorer.py

### Ending context
- src/opportunity_types.py (read-only)
- tests/test_opportunity_scorer.py (read-only)
- fixtures/opportunities.json (read-only)
- src/opportunity_scorer.py

## Low-Level Tasks
> Ordered from start to finish.

1. Load opportunities
```
UPDATE src/opportunity_scorer.py:
    UPDATE def load_opportunities(path: Path) -> list[Opportunity]: json.loads the file, Opportunity.model_validate each item
```

2. Score one opportunity
```
UPDATE src/opportunity_scorer.py:
    UPDATE def score_opportunity(opp: Opportunity, profile: CompanyProfile, today: date) -> ScoredOpportunity:
        USE the scoring rules from Implementation Notes, APPEND one reason per rule applied
```

3. Rank opportunities
```
UPDATE src/opportunity_scorer.py:
    UPDATE def rank_opportunities(opps: list[Opportunity], profile: CompanyProfile, today: date, min_score: int = 0) -> list[ScoredOpportunity]:
        REMOVE expired and score < min_score, sort by -score then response_deadline
```
