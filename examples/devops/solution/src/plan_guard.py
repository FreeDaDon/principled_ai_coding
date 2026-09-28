"""Policy checks over `terraform show -json` plan output."""

from __future__ import annotations

import json
from pathlib import Path

from plan_types import DEFAULT_PROTECTED, SEVERITY_ORDER, Finding

PUBLIC_ACLS = {"public-read", "public-read-write"}
BLOCK_FLAGS = ("block_public_acls", "block_public_policy", "ignore_public_acls", "restrict_public_buckets")


def load_plan(path: Path) -> dict:
    """Read a plan exported with `terraform show -json plan.out`."""
    return json.loads(Path(path).read_text())


def _opens_ssh_to_world(rule: dict) -> bool:
    """True if an ingress rule allows 0.0.0.0/0 on a port range containing 22."""
    cidrs = rule.get("cidr_blocks") or []
    return "0.0.0.0/0" in cidrs and int(rule.get("from_port", 0)) <= 22 <= int(rule.get("to_port", 0))


def check_plan(plan: dict, protected_types: frozenset[str] = DEFAULT_PROTECTED) -> list[Finding]:
    """Apply TF001-TF004 to every resource change; sorted by severity then address."""
    findings: list[Finding] = []
    for rc in plan.get("resource_changes", []):
        rtype, addr = rc.get("type", ""), rc.get("address", "")
        change = rc.get("change") or {}
        actions = change.get("actions") or []
        after = change.get("after") or {}

        if "delete" in actions and rtype in protected_types:
            findings.append(Finding(rule_id="TF004", severity="critical", address=addr,
                                    message=f"plan deletes protected {rtype}"))
        if rtype == "aws_s3_bucket_acl" and after.get("acl") in PUBLIC_ACLS:
            findings.append(Finding(rule_id="TF001", severity="high", address=addr,
                                    message=f"public S3 ACL {after['acl']}"))
        if rtype == "aws_s3_bucket_public_access_block" and not all(after.get(f) is True for f in BLOCK_FLAGS):
            findings.append(Finding(rule_id="TF001", severity="high", address=addr,
                                    message="public access block is not fully enabled"))
        ingress = (after.get("ingress") or []) if rtype == "aws_security_group" else []
        if rtype == "aws_security_group_rule" and after.get("type") == "ingress":
            ingress = [after]
        if any(_opens_ssh_to_world(r) for r in ingress):
            findings.append(Finding(rule_id="TF002", severity="critical", address=addr,
                                    message="SSH (22) open to 0.0.0.0/0"))
        if rtype == "aws_ebs_volume" and not after.get("encrypted"):
            findings.append(Finding(rule_id="TF003", severity="medium", address=addr, message="EBS volume unencrypted"))
        if rtype == "aws_db_instance" and "delete" not in actions and not after.get("storage_encrypted"):
            findings.append(Finding(rule_id="TF003", severity="medium", address=addr, message="RDS storage unencrypted"))
    return sorted(findings, key=lambda f: (SEVERITY_ORDER[f.severity], f.address, f.rule_id))


def exit_code(findings: list[Finding]) -> int:
    """1 if any critical or high finding (block the pipeline), else 0."""
    return 1 if any(f.severity in ("critical", "high") for f in findings) else 0
