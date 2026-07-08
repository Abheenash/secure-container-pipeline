# Secure Container Pipeline — a hardened container service shipped through a security-gated CI/CD pipeline on AWS

A small containerized API on AWS Fargate, deployed entirely by Terraform, shipped through a **CI/CD pipeline that refuses to merge insecure code** — Terraform misconfig scanning, container CVE + dependency scanning, and secrets scanning all block the build on findings.

**Status:** 🚧 Building in public — **Stage 1 done** (containerized API on ECR). The roadmap below is the plan; boxes get checked only as each stage actually lands.

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
     │   ├─ public subnets  ── ALB (HTTPS)              │
     │   └─ private subnets ── ECS Fargate service      │
     │                              │                   │
     │                              ├── DynamoDB (data) │
     │                              └── Secrets Manager │
     │  VPC endpoints (ECR/Secrets/logs/S3/DynamoDB)    │
     │  CloudWatch logs + alarms · least-privilege IAM  │
     └─────────────────────────────────────────────────┘
```

## How it works

1. A push or PR triggers GitHub Actions, which assumes an AWS role via **OIDC** — no access keys stored anywhere.
2. Three security gates run: **Checkov/tfsec** on the Terraform, **Trivy** for image CVEs and dependency (SCA) issues, and **gitleaks** for secrets. Any high/critical finding fails the build, so insecure code can't reach `main`.
3. On success, the image is built and pushed to **ECR** (which re-scans on push), then **Terraform** deploys the service.
4. The API runs on **Fargate in private subnets**, reachable only through the ALB. Data lives in **DynamoDB**; secrets come from **Secrets Manager** at runtime — never from the image or an env file.
5. **CloudWatch** collects logs and alarms on errors.

## Networking / cost decision

Fargate tasks run in **private subnets** but still need to reach ECR, Secrets Manager, CloudWatch, S3, and DynamoDB. Rather than a **NAT Gateway (~$32/mo + data)**, this project uses **VPC endpoints** — free gateway endpoints for S3 and DynamoDB, and interface endpoints for ECR/Secrets/logs. Cheaper, and a cleaner security story (no egress to the open internet). The one unavoidable cost is the **ALB (~$16/mo)** — stand the stack up for demos, then `terraform destroy`.

## Services and why

| Service | Role here |
|---|---|
| ECS Fargate | Runs the container; no servers to manage |
| ECR | Image registry; scans images on push |
| ALB | HTTPS entry point in public subnets |
| DynamoDB | App data (on-demand, near-zero cost) |
| VPC + endpoints | Public/private isolation; private egress without a NAT gateway |
| Secrets Manager | Runtime secrets, kept out of code and images |
| IAM | Least-privilege task-execution + task roles; scoped OIDC deploy role |
| CloudWatch | Logs + alarms |
| Terraform | All infrastructure as code |
| GitHub Actions | CI/CD + the security gates |

## Security decisions

- **CI has no long-lived credentials** — GitHub Actions assumes a scoped role via OIDC federation.
- **Fail-the-build security gates:** Checkov/tfsec (IaC), Trivy (image CVEs + dependencies), gitleaks (secrets). Findings block the merge.
- **Defense in depth:** app tasks run in **private subnets**; only the ALB is public; the database is never internet-reachable.
- **Least privilege:** separate task-execution and task roles, each scoped to only what the container needs.
- **No secrets in code or images** — pulled from Secrets Manager at runtime.
- **Image scanned twice:** in the pipeline (Trivy) and again on ECR push.

## Roadmap

- [x] **Stage 0** — Repo, reuse account hygiene (IAM admin + MFA, budget alarm), **GitHub OIDC deploy role**, ECR repo, local tooling (Docker, Terraform, `gh`)
- [x] **Stage 1** — Containerize a minimal API (FastAPI + DynamoDB); run locally; push to ECR by hand
- [ ] **Stage 2** — Terraform the VPC, Fargate service, ALB, DynamoDB, and VPC endpoints; deploy manually
- [ ] **Stage 3** — The DevSecOps pipeline: Checkov/tfsec + Trivy + gitleaks as hard gates in GitHub Actions
- [ ] **Stage 4** — Hardening: Secrets Manager, private subnets / no public DB, least-privilege roles, CloudWatch alarms (optional WAF on the ALB)
- [ ] **Stage 5** — Clean Terraform, architecture diagram, and a demo of the pipeline blocking a deliberately bad PR

Screenshots are added as each stage actually lands — including the key one: **a PR blocked by a Trivy/Checkov finding before merge.**

## Cost

Built to stay cheap: DynamoDB on-demand and Fargate are pay-per-use and near-free at hobby volume. VPC endpoints replace a NAT gateway to avoid ~$32/mo. The **ALB (~$16/mo)** is the one real cost — stand the stack up for demos and screenshots, then `terraform destroy`. A budget alarm guards the account.

---

Built by Rajolu Abheenash — [github.com/Abheenash](https://github.com/Abheenash)
