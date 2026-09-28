# Infra Change: <change title>
> Ingest this file. Change IaC only; validate with `terraform plan -out` exported as JSON and a policy check. Never apply.

## High-Level Objective
- <Infrastructure outcome, e.g. private S3 bucket for reports with KMS encryption.>

## Mid-Level Objective
- Terraform in `infra/<stack>.tf` declares the resources.
- The exported plan (`terraform show -json plan.out`) passes `plan_guard.py` with zero high or critical findings.
- No resource of a protected type is deleted.

## Implementation Notes
- Least privilege and encryption at rest by default.
- No `0.0.0.0/0` ingress on admin ports; no public ACLs.
- Tag every resource with `owner` and `env`.
- Humans run `terraform apply`; agents never do.

## Context

### Beginning context
- infra/variables.tf (read-only)
- infra/<stack>.tf

### Ending context
- infra/variables.tf (read-only)
- infra/<stack>.tf

## Low-Level Tasks
> Ordered from start to finish.

1. Declare the resources
```
UPDATE infra/<stack>.tf:
    ADD resource "aws_s3_bucket" "<name>", resource "aws_s3_bucket_public_access_block" "<name>" with all four blocks true
    ADD resource "aws_s3_bucket_server_side_encryption_configuration" "<name>" USE var.kms_key_arn
```

2. Tag the resources
```
UPDATE infra/<stack>.tf: ADD tags = { owner = var.owner, env = var.env } to every resource
```
