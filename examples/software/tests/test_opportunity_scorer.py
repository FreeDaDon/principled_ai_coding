from datetime import date
from pathlib import Path

from opportunity_scorer import load_opportunities, rank_opportunities, score_opportunity
from opportunity_types import CompanyProfile, Opportunity

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "opportunities.json"
TODAY = date(2026, 9, 28)
PROFILE = CompanyProfile(naics_codes=["541512", "541519"], set_asides=["SBA", "WOSB"], min_value=50_000, max_value=1_000_000)


def opp(**kw) -> Opportunity:
    base = {"notice_id": "X", "title": "t", "agency": "a", "naics_code": "541512", "set_aside": "SBA",
            "response_deadline": date(2026, 10, 30), "estimated_value": 100_000}
    return Opportunity.model_validate(base | kw)


def test_load_opportunities_parses_fixture():
    opps = load_opportunities(FIXTURE)
    assert [o.notice_id for o in opps] == ["N-001", "N-002", "N-003", "N-004"]
    assert opps[2].estimated_value is None


def test_perfect_match_scores_100():
    s = score_opportunity(opp(), PROFILE, TODAY)
    assert s.score == 100
    assert "NAICS 541512 match" in s.reasons


def test_full_and_open_and_unknown_value():
    s = score_opportunity(opp(set_aside=None, estimated_value=None), PROFILE, TODAY)
    assert s.score == 40 + 10 + 10 + 15


def test_expired_scores_zero():
    s = score_opportunity(opp(response_deadline=date(2026, 9, 1)), PROFILE, TODAY)
    assert s.score == 0 and s.reasons == ["expired"]


def test_close_deadline_penalty_and_clamp():
    s = score_opportunity(opp(naics_code="999999", set_aside="8A", estimated_value=5, response_deadline=date(2026, 9, 30)), PROFILE, TODAY)
    assert s.score == 0
    assert "deadline too close" in s.reasons


def test_rank_orders_and_filters():
    opps = load_opportunities(FIXTURE)
    ranked = rank_opportunities(opps, PROFILE, TODAY, min_score=30)
    assert [(s.opportunity.notice_id, s.score) for s in ranked] == [("N-001", 100), ("N-003", 90), ("N-002", 45)]
    assert [s.opportunity.notice_id for s in rank_opportunities(opps, PROFILE, TODAY, min_score=50)] == ["N-001", "N-003"]


def test_rank_tiebreak_by_deadline():
    a, b = opp(notice_id="A", response_deadline=date(2026, 11, 5)), opp(notice_id="B", response_deadline=date(2026, 10, 10))
    assert [s.opportunity.notice_id for s in rank_opportunities([a, b], PROFILE, TODAY)] == ["B", "A"]
