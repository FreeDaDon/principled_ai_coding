# IAM Policy: <role or access model>
> Ingest this file. Generate least-privilege policies from a typed access model and audit them. Never attach policies.

## High-Level Objective
- Every role in `access_model.yaml` gets a least-privilege policy with zero high or critical audit findings.

## Mid-Level Objective
- Policies are generated from the pydantic schema in `src/iam_types.py`, never hand-written.
- ABAC conditions from the model appear as policy Conditions.
- The audit flags wildcards, write access on `*` resources, unconditioned `iam:PassRole`, and unused actions.

## Implementation Notes
- RBAC: roles map to permission sets. ABAC: conditions narrow them.
- Deny by default; no `*` actions.
- Output is JSON for review; humans attach policies.

## Context

### Beginning context
- src/iam_types.py (read-only)
- fixtures/access_model.yaml (read-only)
- src/iam_policy.py

### Ending context
- src/iam_types.py (read-only)
- fixtures/access_model.yaml (read-only)
- src/iam_policy.py

## Low-Level Tasks
> Ordered from start to finish.

1. Create the generator
```
UPDATE src/iam_policy.py:
    CREATE def generate_policy(role: Role) -> dict: one Allow statement per Permission, sorted actions and resources
```

2. Create the audit
```
UPDATE src/iam_policy.py:
    CREATE def audit_policy(policy: dict, used_actions: set[str] | None = None) -> list[AuditFinding]
```
