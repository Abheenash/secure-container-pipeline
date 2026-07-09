# Stage 3 — the DevSecOps pipeline

**Goal:** make it impossible to merge insecure code. Three fail-the-build gates run on
every pull request; any finding blocks the merge.

## The gates (`.github/workflows/security-pipeline.yml`)

| Job | Tool | Catches |
|---|---|---|
| `secrets-scan` | **gitleaks** | hardcoded secrets / credentials |
| `iac-scan` | **checkov** + **tfsec** | Terraform misconfigurations |
| `image-scan` | **trivy** | image CVEs + vulnerable dependencies (SCA) |

All three are hard gates — a finding fails the job, which blocks the PR.

## The reviewed baseline

Real scanners are noisy on a full VPC/ALB/ECS stack. The honest approach isn't to
silence them — it's to **fix what's cheap and real, and document-and-accept the rest**:

- **Fixed** (see Stage 4): DynamoDB SSE + PITR, SNS encryption, 1-year log retention,
  container insights, ALB drops invalid headers, SG rule descriptions, WAF known-bad-inputs.
- **Accepted** ([`.checkov.yaml`](../.checkov.yaml) + tfsec `--exclude`): each with a
  written reason — public ALB (it's the entry point), HTTP-only (no domain/cert for the
  demo), AWS-managed keys instead of CMKs, egress for VPC endpoints, no flow logs.

Any *new* category of issue in a PR — not on the baseline — fails the build.

## A real catch, fixed properly

The first green-main attempt failed because trivy found **3 HIGH CVEs in `starlette 0.40`**
(a transitive FastAPI dependency). The right fix was to *patch the dependency*, not weaken
the gate: bumped to `starlette 1.3.1` / `fastapi 0.139`, re-scanned clean. That's the gate
doing exactly its job.

## No credentials in CI

The workflow's deploy path assumes an AWS role via **GitHub OIDC** (repo variable
`AWS_ROLE_ARN`) — no long-lived access keys are stored anywhere.

## Demo

See Stage 5 — a pull request that introduces a hardcoded secret is **blocked by gitleaks**
before it can merge.
