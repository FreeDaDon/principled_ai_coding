# IAM Policy Generator and Audit
> Ingest this file, carry out the Low-Level Tasks in order, and produce code that satisfies the High and Mid-Level Objectives.

## High-Level Objective
- Generate least-privilege IAM policies from a typed access model and flag over-privileged policies before a human attaches anything.

## Mid-Level Objective
- Load `access_model.yaml` into typed `AccessModel` roles (RBAC) with conditions (ABAC).
- Generate one AWS policy document per role; generated policies audit clean.
- Audit any policy document for wildcards, writes on `*`, unconditioned `iam:PassRole` and unused actions.
- `tests/test_iam_policy.py` passes.

## Implementation Notes
- generate_policy: Version `2012-10-17`; one Allow statement per Permission; Sid = role name in PascalCase + 1-based index (`report-reader` -> `ReportReader1`); Action = sorted `service:Action`; Resource sorted; Condition = `{operator: {key: value}}` merged by operator, omitted when empty.
- audit_policy: only Allow statements; Action/Resource may be a string or list; missing Sid becomes `stmt<index>`.
- IAM001: Action `*` critical, `service:*` high. IAM002 medium: Resource `*` with any concrete action whose verb does not start with Get/List/Describe/Head. IAM003 high: `iam:PassRole` with no Condition. IAM004 low: concrete actions not in used_actions (only when used_actions is given).
- Sort findings by SEVERITY_ORDER, then sid, then rule_id. Standard library + pydantic + pyyaml.

## Context

### Beginning context
- src/iam_types.py (read-only)
- tests/test_iam_policy.py (read-only)
- fixtures/access_model.yaml (read-only)
- fixtures/legacy_policy.json (read-only)
- fixtures/used_actions.json (read-only)
- src/iam_policy.py

### Ending context
- src/iam_types.py (read-only)
- tests/test_iam_policy.py (read-only)
- fixtures/access_model.yaml (read-only)
- fixtures/legacy_policy.json (read-only)
- fixtures/used_actions.json (read-only)
- src/iam_policy.py

## Low-Level Tasks
> Ordered from start to finish.

1. Load the access model
```
UPDATE src/iam_policy.py: UPDATE def load_access_model(path: Path) -> AccessModel: yaml.safe_load, AccessModel.model_validate
```

2. Generate policies
```
UPDATE src/iam_policy.py:
    CREATE def _sid_base(role_name: str) -> str
    UPDATE def generate_policy(role: Role) -> dict USE the generate_policy rules from Implementation Notes
```

3. Audit policies
```
UPDATE src/iam_policy.py:
    UPDATE def audit_policy(policy: dict, used_actions: set[str] | None = None) -> list[AuditFinding]: APPEND findings for IAM001-IAM004
```
