# Terraform Plan Guard
> Ingest this file, carry out the Low-Level Tasks in order, and produce code that satisfies the High and Mid-Level Objectives.

## High-Level Objective
- Block risky infrastructure changes by checking the exported Terraform plan before any human runs `terraform apply`.

## Mid-Level Objective
- Load a plan exported with `terraform show -json plan.out`.
- Emit typed `Finding` objects for rules TF001-TF004, sorted by severity then address.
- Return exit code 1 when any critical or high finding exists, so CI blocks the change.
- `tests/test_plan_guard.py` passes.

## Implementation Notes
- Read `resource_changes[].type`, `.address`, `.change.actions` and `.change.after` (after may be null).
- TF001 high: `aws_s3_bucket_acl` with acl public-read or public-read-write; `aws_s3_bucket_public_access_block` without all four block flags true.
- TF002 critical: ingress allowing 0.0.0.0/0 on a port range containing 22, in `aws_security_group.ingress[]` or an `aws_security_group_rule` of type ingress.
- TF003 medium: `aws_ebs_volume` not encrypted; `aws_db_instance` (not being deleted) without storage_encrypted.
- TF004 critical: a delete action on a type in `protected_types`.
- Deterministic, standard library + pydantic only. Never run terraform.

## Context

### Beginning context
- src/plan_types.py (read-only)
- tests/test_plan_guard.py (read-only)
- fixtures/plan.json (read-only)
- src/plan_guard.py

### Ending context
- src/plan_types.py (read-only)
- tests/test_plan_guard.py (read-only)
- fixtures/plan.json (read-only)
- src/plan_guard.py

## Low-Level Tasks
> Ordered from start to finish.

1. Load the plan
```
UPDATE src/plan_guard.py: UPDATE def load_plan(path: Path) -> dict: json.loads the file
```

2. Check the plan
```
UPDATE src/plan_guard.py:
    CREATE def _opens_ssh_to_world(rule: dict) -> bool
    UPDATE def check_plan(plan: dict, protected_types: frozenset[str] = DEFAULT_PROTECTED) -> list[Finding]:
        APPEND a Finding per rule TF001-TF004, sort by SEVERITY_ORDER then address
```

3. Map findings to an exit code
```
UPDATE src/plan_guard.py: UPDATE def exit_code(findings: list[Finding]) -> int: 1 if any critical or high else 0
```
