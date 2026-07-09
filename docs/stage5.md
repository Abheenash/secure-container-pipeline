# Stage 5 — polish + the blocked-PR demo

**Goal:** tie it together — clean Terraform, an architecture diagram, and the headline
proof: the pipeline stopping a bad change from merging.

## The demo — a secret blocked before merge

A pull request (`#1`) added a file with hardcoded AWS credentials:

```python
AWS_ACCESS_KEY_ID = "AKIA...."
AWS_SECRET_ACCESS_KEY = "...."
```

The `security-pipeline` ran on the PR and **two independent gates caught it**:

| Gate | Result |
|---|---|
| gitleaks (secrets) | ❌ FAILURE — secret detected |
| trivy (image + deps) | ❌ FAILURE — trivy also secret-scans the built image |
| checkov + tfsec (IaC) | ✅ passed (no new misconfig) |

With **branch protection** requiring all three checks, the PR merge state became
**`BLOCKED`** — the credentials could not reach `main`. The PR was closed, not merged.

> That's the whole project's thesis in one screenshot: insecure code doesn't get in.

## Enforcement

`main` has branch protection requiring the three status checks (`strict` mode). A PR can't
merge until secrets, IaC, and image scans all pass — the gates aren't advisory, they're a wall.

## Wrap

- **Clean Terraform** — `terraform fmt`, `validate`, and a green checkov/tfsec baseline.
- **Architecture** — [docs/architecture.md](architecture.md) (pipeline + runtime diagrams).
- **Reproducible** — `terraform apply` stands the stack up; `terraform destroy` tears it down.

## What this project demonstrates

Build → ship → run, securely: a container built and scanned, shipped only through gates that
block secrets/misconfig/CVEs, running on Fargate in private subnets with no internet egress,
secrets from Secrets Manager, fronted by an ALB + WAF — all as Terraform, all through a
keyless (OIDC) pipeline.
