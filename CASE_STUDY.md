# Secure Container Pipeline — Engineering Case Study

## Context

I built a small containerized notes API and shipped it to AWS through a CI/CD pipeline whose whole reason to exist is to *refuse to merge insecure code*. The application itself is deliberately boring — a FastAPI service with a `/health` check and CRUD endpoints (`POST /notes`, `GET /notes/{id}`, `GET /notes`) backed by DynamoDB. The point was never the app; it was to demonstrate a DevSecOps workflow end to end: least-privilege IAM, containers in private subnets, secrets kept out of code, and automated security gates that stop vulnerable code, insecure infrastructure, and leaked secrets *before* they ever reach `main`.

The thesis is one line: **build a container → ship it only if it passes secrets / IaC / CVE gates → run it on Fargate in private subnets with no path to the open internet.**

## My role

I did all of it — I'm the sole engineer. I designed and wrote the infrastructure as Terraform, containerized the app, authored the GitHub Actions security pipeline and its three gates, set up GitHub OIDC federation so CI never holds a long-lived AWS key, curated the reviewed scanner baseline, configured branch protection on `main`, and ran the proof: a pull request carrying a planted secret that the pipeline blocked. I also owned the honest security posture — deciding what to fix versus what to document-and-accept for a demo-scoped project.

## Architecture

The runtime is standard, hardened AWS container plumbing, all defined in `terraform/` (diagrammed in `docs/architecture.md`):

- **ECS Fargate service in private subnets.** The task runs with `assign_public_ip = false` and has no route to the internet — the private route table has no default route. The task security group accepts traffic on the container port (8080) *only from the ALB security group*.
- **Application Load Balancer in public subnets** — the only internet-facing component, fronted by WAF. It drops invalid header fields.
- **VPC endpoints instead of a NAT gateway** (`endpoints.tf`) — free gateway endpoints for S3 and DynamoDB, and interface endpoints for ECR (api + dkr), CloudWatch Logs, and Secrets Manager. This is how a private-subnet task pulls its image, ships logs, and reads its secret without any egress to the open internet.
- **DynamoDB** (`dynamodb.tf`) — on-demand (`PAY_PER_REQUEST`), reached over the gateway endpoint inside the VPC, never public.
- **ECR** — the image registry, which also scans images on push (so the image is scanned twice: once by Trivy in the pipeline, again on ECR push).
- **Secrets Manager** (`secrets.tf`) — a runtime secret whose value is *generated* by Terraform, stored in Secrets Manager, and injected into the task via the task definition's `secrets` block at start time. It never appears in the image, the repo, or an env file.
- **WAF** on the ALB (`waf.tf`) — AWS managed common rule set, known-bad-inputs (including Log4Shell / CVE-2021-44228 coverage), and an IP rate-based rule.
- **Least-privilege IAM** (`iam.tf`) — separate roles. The task-execution role pulls from ECR and writes logs (AWS-managed `AmazonECSTaskExecutionRolePolicy`) plus an inline policy to read *only the one app secret*. The task role can call only `GetItem`/`PutItem`/`Scan` on *its own* DynamoDB table — nothing else.

Hardening details worth calling out: the container runs as an unprivileged user (uid 10001) from a slim Python base, with a read-only root filesystem enforced at the task level (`readonlyRootFilesystem = true`, plus `PYTHONDONTWRITEBYTECODE`). CloudWatch collects logs (1-year retention), Container Insights is on, and alarms for ALB 5xx spikes and unhealthy hosts route to SNS.

## The DevSecOps pipeline

The pipeline lives in `.github/workflows/security-pipeline.yml` and runs on every pull request and on push to `main`. It is three independent hard gates — a finding in any of them fails that job:

1. **gitleaks** (`secrets-scan`) — hardcoded secrets / credentials.
2. **Checkov + tfsec** (`iac-scan`) — Terraform misconfigurations, run against `terraform/` with the reviewed baseline in `.checkov.yaml` and a matching tfsec `--exclude` list.
3. **Trivy** (`image-scan`) — builds the image, then scans for HIGH/CRITICAL image CVEs and vulnerable dependencies (SCA), with `--ignore-unfixed --exit-code 1`.

Two design choices matter here. First, **keyless CI**: the security gates need no AWS access at all — they only read code — and the deploy path assumes a role via **GitHub OIDC** (`iam/github-oidc-trust.json` scopes the trust to `repo:Abheenash/secure-container-pipeline`, and `iam/deploy-role-iam.json` scopes what it can manage to this project's roles). No long-lived access keys are stored anywhere.

Second, **the reviewed baseline is honest, not a mute button**. Scanners are noisy on a full VPC/ALB/ECS stack. Rather than blanket-silencing them, I fixed what was cheap and real (DynamoDB SSE + PITR, SNS encryption, log retention, Container Insights, dropped invalid headers, SG rule descriptions, WAF rules) and *documented-and-accepted* the rest, each with a written one-line reason in `.checkov.yaml` — public ALB (it's the entry point), HTTP-only (no domain/cert for the demo), AWS-managed keys instead of CMKs, egress needed to reach the VPC endpoints, no flow logs. Any *new* category of misconfiguration not on the baseline still fails the build.

Enforcement is the last piece: `main` is branch-protected in `strict` mode, requiring all three status checks to pass before a PR can merge. The gates aren't advisory — they're a wall.

## Proof it works

The headline proof (`docs/stage5.md`) is a pull request (`#1`) that added a file containing hardcoded AWS credentials (`AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`). The `security-pipeline` ran on the PR, and **two independent gates caught it**:

| Gate | Result |
|---|---|
| gitleaks (secrets) | FAILURE — secret detected |
| trivy (image + deps) | FAILURE — Trivy also secret-scans the built image |
| checkov + tfsec (IaC) | passed (no new misconfig) |

With branch protection requiring all three checks, the PR's merge state became `BLOCKED` — the credentials could not reach `main`. The PR was closed, not merged. The pipeline runs are public: the failing run and the green-on-`main` run are both linked from the README.

That's the whole project in one screenshot: insecure code doesn't get in — and it was two *different* tools catching the same leak, which is exactly the defense-in-depth the pipeline is supposed to provide.

## Debugging war stories

**arm64 Mac image failing on amd64 Fargate.** The first deploy failed with `CannotPullContainerError: image Manifest does not contain descriptor matching platform 'linux/amd64'`. I'd built the image on an Apple Silicon Mac, which produces an **arm64** image, but Fargate defaults to **amd64**. The fix was to build explicitly for the target platform: `docker buildx build --platform linux/amd64 ... --push`. A useful side effect of moving the build into CI is that GitHub's runners are amd64, so the pipeline produces the right architecture automatically — this bug only bites local Mac builds.

**Trivy catching a transitive supply-chain CVE.** The first attempt at a green `main` failed because Trivy found **3 HIGH CVEs in `starlette 0.40`** — a *transitive* FastAPI dependency I hadn't pulled in directly. The tempting move is to weaken the gate; the correct move is to patch the dependency. I bumped to `starlette 1.3.1` / `fastapi 0.139` (now pinned in `app/requirements.txt`) and re-scanned clean. That's the SCA gate doing exactly its job — catching a vulnerable dependency I never explicitly chose.

## Security & cost decisions

- **No NAT gateway → VPC endpoints.** The private-subnet task still needs ECR, Secrets Manager, CloudWatch, S3, and DynamoDB. I chose VPC endpoints over a NAT gateway. My honest note in `docs/stage2.md`: for a *persistently running* service, ~3 interface endpoints cost roughly the same as a NAT gateway, so the real reason to prefer endpoints here is **security posture — zero egress to the open internet** — not raw cost. For a short-lived demo, both are pennies.
- **WAF on the ALB** — managed common rules, known-bad-inputs (Log4Shell), and an IP rate-based rule, so the public entry point isn't naked.
- **SSE + PITR on DynamoDB**, SNS topic encryption, and a runtime secret pulled from Secrets Manager rather than baked anywhere.
- **Build → demo → destroy.** The ALB bills the moment it exists, and the WAF web ACL adds monthly cost too, so the stack is built to stand up for a demo/screenshot session and then `terraform destroy`. Everything else (Fargate, DynamoDB on-demand, endpoints) is pay-per-use and near-free for short runs. A budget alarm guards the account.

## Trade-offs

- **HTTP, not HTTPS.** The ALB listener is HTTP because the demo has no domain or ACM certificate. This is a knowingly-accepted finding (recorded in `.checkov.yaml`, CKV_AWS_2 / CKV_AWS_103 / CKV2_AWS_20); adding an ACM cert with an HTTP→HTTPS redirect is the documented follow-up.
- **AWS-managed keys instead of customer-managed KMS (CMKs)** for DynamoDB, CloudWatch Logs, Secrets Manager, and SNS — accepted for a demo, documented rather than silently ignored.
- **Deployment is manual** (`terraform apply`). The OIDC deploy role is pre-created so a future CD job can assume it on merge, but I didn't wire up automatic deploy — the security gates were the focus, not CD.
- **No secret rotation, no VPC flow logs, no ALB access-log bucket, no WAF logging** — each would add cost/scope beyond a demo, and each is a justified line in the reviewed baseline rather than an unexamined gap.

The through-line on every trade-off: nothing is silently suppressed. Each accepted risk has a written reason in `.checkov.yaml`, and any *new* category of issue still fails the build.

## What I would improve next

- **TLS at the edge** — an ACM cert plus an HTTP→HTTPS redirect, retiring the HTTP-only baseline entry.
- **Wire up CD** — a deploy job that assumes the existing OIDC role on merge to `main`, closing the loop from green pipeline to running service with no manual `terraform apply`.
- **Customer-managed KMS keys** for the data and logging services, replacing the AWS-managed keys.
- **Turn on the observability I deferred** — VPC flow logs, ALB access logs, and WAF logging — so the runtime is as auditable as the pipeline.
- **Secret rotation** — a rotation Lambda for the Secrets Manager secret.

## Evidence

- Pipeline definition & gates — `.github/workflows/security-pipeline.yml`
- Reviewed scanner baseline (accepted findings, each with a reason) — `.checkov.yaml`
- Infrastructure as code — `terraform/` (`ecs.tf`, `alb.tf`, `network.tf`, `endpoints.tf`, `iam.tf`, `secrets.tf`, `dynamodb.tf`, `waf.tf`, `monitoring.tf`)
- OIDC / least-privilege deploy role — `iam/github-oidc-trust.json`, `iam/deploy-role-iam.json`
- Architecture (pipeline + runtime diagrams) — `docs/architecture.md`
- Stage write-ups — `docs/stage2.md` (infra + the arm64/amd64 gotcha), `docs/stage3.md` (the pipeline + the starlette CVE catch), `docs/stage4.md` (hardening), `docs/stage5.md` (the blocked-PR demo)
- The app — `app/main.py`, `app/requirements.txt`, `Dockerfile`
- Public pipeline runs (failing blocked-PR run and green-on-`main` run) — linked from `README.md`
