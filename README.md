# Secure Container Pipeline — a hardened container service shipped through a security-gated CI/CD pipeline on AWS

> **Sep 2026:** fourth gate (pytest + mocked DynamoDB), SBOM, keyless cosign signing in a gated CD job, `/ready` vs `/health`, circuit-breaker rollback, autoscaling, optional TLS, and CodeDeploy blue/green with alarm-triggered rollback (validated, not applied).

A small containerized API on AWS Fargate, deployed entirely by Terraform, shipped through a **CI/CD pipeline that refuses to merge insecure code** — Terraform misconfig scanning, container CVE + dependency scanning, and secrets scanning all block the build on findings.

**Status:** ✅ All stages complete — DevSecOps pipeline **enforced on `main`**, a bad PR proven blocked ([docs/stage5.md](docs/stage5.md)). See the [architecture diagram](docs/architecture.md).

## v2 — what changed (Sep 2026)

| Area | Before | Now |
| --- | --- | --- |
| Gates | 3 (gitleaks, checkov + tfsec, trivy) | **4** — plus the app's own **pytest suite against a moto-mocked DynamoDB** (9 tests: readiness vs liveness, CRUD, validation, pagination bounds, security headers, JSON request logs, docs disabled). Terraform `fmt`/`validate` also gate. |
| Supply chain | CVE scan | CVE scan **+ secret scan of the image layers + CycloneDX SBOM** uploaded as a build artifact **+ non-root assertion** (the pipeline fails if the container doesn't run as uid 10001) |
| Delivery | manual `terraform apply` | a **CD job** on `main` (gated by a `DEPLOY_ENABLED` repo variable so the torn-down demo doesn't fail): OIDC → ECR push (amd64) → **keyless cosign signature by digest** → verify → `ecs update-service`. Dependabot for pip, Docker, Actions and Terraform. |
| App | `/health` used for everything | `/health` = liveness (never touches AWS); **`/ready` = DynamoDB reachable** and is what the ALB target group checks. Input bounds (1–4000 chars), cursor pagination with a 100-item cap, `DELETE`, security headers, one JSON log line per request with the ALB trace id. OpenAPI/docs endpoints disabled. |
| Image | single stage | **two-stage build**, `HEALTHCHECK`, `--no-server-header`, `.dockerignore`, `PYTHONUNBUFFERED`. Trivy: 0 HIGH/CRITICAL. |
| Runtime | fixed desired count | **deployment circuit breaker with automatic rollback**, 100/200 rollout, **CPU target-tracking autoscaling** (1–4 tasks), and **optional TLS**: set `certificate_arn` and the ALB serves HTTPS (TLS 1.3 policy) with an HTTP→HTTPS 301 — the HTTP-only baseline entries in `.checkov.yaml` only apply when no cert is configured. |

| Deployment strategy | rolling only | **`deployment_strategy = "blue_green"`** switches the service to **CodeDeploy blue/green**: a green target group, a VPC-internal **test listener (:9001)** to validate a release before it takes traffic, **canary / linear / all-at-once** traffic shifting, and **automatic rollback when `alb-5xx`, `unhealthy-hosts` or a green-only `green-5xx` alarm trips** during the shift — blue stays warm for 30 minutes so a late rollback is a listener flip. `deploy/appspec.yaml`, `scripts/deploy-bluegreen.sh`, and a written **bad-release drill** (`deploy/bad-release-drill.md`) using the app's `FAIL_READY=1` switch, which makes readiness fail while liveness stays up — the shape of a dependency outage. |

Validated with `terraform validate` (both strategies), `checkov` (104 passed, 0 failed against the reviewed baseline), a local `docker build` + Trivy scan, and the test suite. The infrastructure changes are **not applied** — the stack is torn down between demos by design; `terraform plan` shows them. The blue/green rollback drill is written, not yet run.

## See it in action

The pipeline runs are public — click straight through to the real thing:

- 🎯 **A hardcoded secret, blocked before merge** — [PR #1](https://github.com/Abheenash/secure-container-pipeline/pull/1) and its [failing run](https://github.com/Abheenash/secure-container-pipeline/actions/runs/28985635630): the **gitleaks** and **trivy** gates both fail, so the credentials can't reach `main`.
- ✅ **The pipeline passing on `main`** — [green run](https://github.com/Abheenash/secure-container-pipeline/actions/runs/28985555459) (all three gates pass).
- 🗺️ **[Architecture diagram](docs/architecture.md)** — the pipeline gates and the runtime.

`main` is branch-protected: a PR can't merge until all four gates pass.

## Why this project

The app is deliberately boring — the point is the **pipeline and the infrastructure**. This demonstrates a DevSecOps workflow end to end: least-privilege IAM, containers on private subnets, secrets kept out of code, and automated security gates that stop vulnerable code, insecure infrastructure, and leaked secrets *before* they ever reach `main`. Everything is infrastructure-as-code, and CI authenticates to AWS with short-lived **OIDC** credentials — no long-lived keys anywhere.

## Target architecture

```
Developer ──push/PR──> GitHub
                          │
                          ▼
             GitHub Actions  (OIDC → AWS role, no static keys)
                          │
      ┌───────────────────┼──────────────────────────────┐
      ▼                   ▼                              ▼
   IaC scan          image + dep scan               secrets scan
 (Checkov/tfsec)     (Trivy: CVEs + SCA)              (gitleaks)
      │                   │                              │
      └─────────── all gates must pass ─────────────────┘
                          │  build + push image
                          ▼
                    Amazon ECR  ──(scan on push)──
                          │
                          ▼  terraform apply
     ┌─────────────────────────────────────────────────┐
     │  VPC                                             │
     │   ├─ public subnets  ── ALB (HTTP) + WAF         │
     │   └─ private subnets ── ECS Fargate service      │
     │                              │                   │
     │                              ├── DynamoDB (data) │
     │                              └── Secrets Manager │
     │  VPC endpoints (ECR/Secrets/logs/S3/DynamoDB)    │
     │  CloudWatch logs + alarms · least-privilege IAM  │
     └─────────────────────────────────────────────────┘
```

## How it works

1. A push or PR triggers GitHub Actions, which runs three security gates — **no AWS credentials needed** (the gates only read code).
2. The gates: **Checkov/tfsec** on the Terraform, **Trivy** for image CVEs and dependency (SCA) issues, and **gitleaks** for secrets. Any HIGH/CRITICAL finding fails the build; `main` is branch-protected, so nothing merges until all three pass.
3. Deployment is **manual** in this project (`terraform apply`). A future CD job can assume the pre-created **OIDC** role to deploy on merge — no static keys anywhere.
4. The API runs on **Fargate in private subnets**, reachable only through the ALB. Data lives in **DynamoDB**; secrets come from **Secrets Manager** at runtime — never from the image or an env file.
5. **CloudWatch** collects logs and alarms on errors.

> **Note on TLS:** the ALB listener is **HTTP** in this demo (no domain/cert provisioned). Adding an ACM cert + HTTP→HTTPS redirect is a documented follow-up; the accepted-for-now finding is recorded in [`.checkov.yaml`](.checkov.yaml).

## Networking / cost decision

Fargate tasks run in **private subnets** but still need to reach ECR, Secrets Manager, CloudWatch, S3, and DynamoDB. Rather than a **NAT Gateway (~$32/mo + data)**, this project uses **VPC endpoints** — free gateway endpoints for S3 and DynamoDB, and interface endpoints for ECR/Secrets/logs. Cheaper, and a cleaner security story (no egress to the open internet). The one unavoidable cost is the **ALB (~$16/mo)** — stand the stack up for demos, then `terraform destroy`.

## Services and why

| Service | Role here |
|---|---|
| ECS Fargate | Runs the container; no servers to manage |
| ECR | Image registry; scans images on push |
| ALB | HTTP entry point in public subnets, fronted by WAF (HTTPS is a documented follow-up) |
| DynamoDB | App data (on-demand, near-zero cost) |
| VPC + endpoints | Public/private isolation; private egress without a NAT gateway |
| Secrets Manager | Runtime secrets, kept out of code and images |
| IAM | Least-privilege task-execution + task roles; scoped OIDC deploy role |
| CloudWatch | Logs + alarms |
| Terraform | All infrastructure as code |
| GitHub Actions | CI/CD + the security gates |

## Security decisions

- **CI has no long-lived credentials** — the security gates need no AWS access at all; the pre-created deploy role uses OIDC federation (scoped to this repo), so a future CD job never needs static keys.
- **Fail-the-build security gates:** Checkov/tfsec (IaC), Trivy (image CVEs + dependencies), gitleaks (secrets). Findings block the merge.
- **Defense in depth:** app tasks run in **private subnets**; only the ALB is public; the database is never internet-reachable.
- **Least privilege:** separate task-execution and task roles, each scoped to only what the container needs.
- **No secrets in code or images** — pulled from Secrets Manager at runtime.
- **Image scanned twice:** in the pipeline (Trivy) and again on ECR push.

## Roadmap

- [x] **Stage 0** — Repo, reuse account hygiene (IAM admin + MFA, budget alarm), **GitHub OIDC deploy role**, ECR repo, local tooling (Docker, Terraform, `gh`)
- [x] **Stage 1** — Containerize a minimal API (FastAPI + DynamoDB); run locally; push to ECR by hand
- [x] **Stage 2** — Terraform the VPC, Fargate service, ALB, DynamoDB, and VPC endpoints; deploy manually
- [x] **Stage 3** — The DevSecOps pipeline: Checkov/tfsec + Trivy + gitleaks as hard gates in GitHub Actions
- [x] **Stage 4** — Hardening: Secrets Manager, private subnets / no public DB, least-privilege roles, CloudWatch alarms, WAF on the ALB
- [x] **Stage 5** — Clean Terraform, [architecture diagram](docs/architecture.md), and a demo of the pipeline [blocking a bad PR](docs/stage5.md)

## Cost

Built to stay cheap: DynamoDB on-demand and Fargate are pay-per-use and near-free at hobby volume. VPC endpoints replace a NAT gateway to avoid ~$32/mo. The real running costs are the **ALB (~$16/mo)** and the **WAF web ACL (~$5/mo + ~$1/managed rule group)** — so stand the stack up for a demo, then `terraform destroy`. A budget alarm guards the account.

---

Built by Rajolu Abheenash — [github.com/Abheenash](https://github.com/Abheenash)
