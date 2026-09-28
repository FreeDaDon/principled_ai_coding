"""Types first: findings produced by the Terraform plan guard (read-only context)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

Severity = Literal["critical", "high", "medium", "low"]
SEVERITY_ORDER: dict[str, int] = {"critical": 0, "high": 1, "medium": 2, "low": 3}
DEFAULT_PROTECTED = frozenset({"aws_db_instance", "aws_s3_bucket", "aws_kms_key", "aws_dynamodb_table"})


class Finding(BaseModel):
    rule_id: str      # TF001..TF004
    severity: Severity
    address: str      # resource address, e.g. aws_s3_bucket_acl.reports
    message: str
