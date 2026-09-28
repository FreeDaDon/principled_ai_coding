import json
from pathlib import Path

from iam_policy import audit_policy, generate_policy, load_access_model
from iam_types import AccessModel

FIX = Path(__file__).resolve().parents[1] / "fixtures"


def model() -> AccessModel:
    return load_access_model(FIX / "access_model.yaml")


def test_generate_rbac_with_abac_conditions():
    reader = generate_policy(model().roles[0])
    assert reader == {
        "Version": "2012-10-17",
        "Statement": [{
            "Sid": "ReportReader1",
            "Effect": "Allow",
            "Action": ["s3:GetObject", "s3:ListBucket"],
            "Resource": ["arn:aws:s3:::govopp-reports", "arn:aws:s3:::govopp-reports/*"],
            "Condition": {"IpAddress": {"aws:SourceIp": "10.0.0.0/8"}},
        }],
    }


def test_generated_policies_audit_clean():
    for role in model().roles:
        assert audit_policy(generate_policy(role)) == [], role.name


def test_deployer_has_one_statement_per_permission():
    stmts = generate_policy(model().roles[1])["Statement"]
    assert [s["Sid"] for s in stmts] == ["Deployer1", "Deployer2"]
    assert stmts[1]["Condition"] == {"StringEquals": {"iam:PassedToService": "ecs-tasks.amazonaws.com"}}


def test_audit_legacy_policy():
    policy = json.loads((FIX / "legacy_policy.json").read_text())
    used = set(json.loads((FIX / "used_actions.json").read_text()))
    got = [(f.rule_id, f.severity, f.sid) for f in audit_policy(policy, used)]
    assert got == [
        ("IAM001", "critical", "AdminBreakGlass"),
        ("IAM003", "high", "Pass"),
        ("IAM001", "high", "Reports"),
        ("IAM002", "medium", "Ops"),
        ("IAM004", "low", "Ops"),
    ]


def test_unused_actions_only_when_usage_given():
    policy = {"Statement": [{"Effect": "Allow", "Action": ["s3:GetObject"], "Resource": ["arn:aws:s3:::b/*"]}]}
    assert audit_policy(policy) == []
    [f] = audit_policy(policy, set())
    assert (f.rule_id, f.sid) == ("IAM004", "stmt1")
