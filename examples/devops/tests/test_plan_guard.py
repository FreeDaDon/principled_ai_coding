from pathlib import Path

from plan_guard import check_plan, exit_code, load_plan
from plan_types import Finding

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "plan.json"


def rc(address: str, rtype: str, actions: list[str], after: dict | None) -> dict:
    return {"resource_changes": [{"address": address, "type": rtype, "change": {"actions": actions, "after": after}}]}


def test_fixture_findings_sorted_by_severity_then_address():
    findings = check_plan(load_plan(FIXTURE))
    assert [(f.rule_id, f.severity, f.address) for f in findings] == [
        ("TF004", "critical", "aws_db_instance.legacy"),
        ("TF002", "critical", "aws_security_group.bastion"),
        ("TF001", "high", "aws_s3_bucket_acl.reports"),
        ("TF001", "high", "aws_s3_bucket_public_access_block.reports"),
        ("TF003", "medium", "aws_ebs_volume.scratch"),
    ]
    assert exit_code(findings) == 1


def test_clean_plan_passes():
    plan = rc("aws_ebs_volume.data", "aws_ebs_volume", ["create"], {"encrypted": True})
    assert check_plan(plan) == [] and exit_code([]) == 0


def test_private_ssh_rule_is_fine_but_world_is_not():
    assert check_plan(rc("r", "aws_security_group_rule", ["create"],
                         {"type": "ingress", "from_port": 22, "to_port": 22, "cidr_blocks": ["10.0.0.0/8"]})) == []
    world = check_plan(rc("r", "aws_security_group_rule", ["create"],
                          {"type": "ingress", "from_port": 22, "to_port": 22, "cidr_blocks": ["0.0.0.0/0"]}))
    assert [f.rule_id for f in world] == ["TF002"]


def test_unencrypted_rds_is_medium():
    f = check_plan(rc("aws_db_instance.app", "aws_db_instance", ["create"], {"storage_encrypted": False}))
    assert [(x.rule_id, x.severity) for x in f] == [("TF003", "medium")]
    assert exit_code(f) == 0


def test_custom_protected_types():
    plan = rc("aws_sqs_queue.jobs", "aws_sqs_queue", ["delete"], None)
    assert check_plan(plan) == []
    assert [f.rule_id for f in check_plan(plan, frozenset({"aws_sqs_queue"}))] == ["TF004"]


def test_findings_are_typed():
    assert all(isinstance(f, Finding) for f in check_plan(load_plan(FIXTURE)))
