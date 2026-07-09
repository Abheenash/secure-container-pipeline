# Stage 2 — Terraform the infrastructure

**Goal:** stand up the container service on AWS entirely from Terraform — VPC, Fargate, ALB, DynamoDB — with the app in **private subnets** and **no NAT gateway**.

## What was built (32 resources)

```
internet ──> ALB (public subnets, SG: 80) ──> Fargate task (private subnets)
                                                   │  SG: 8080 from ALB only
                                                   ├─ DynamoDB (via gateway endpoint)
                                                   └─ ECR/logs (via interface endpoints)
```

| Piece | Detail |
|---|---|
| VPC | `10.0.0.0/16`, 2 public + 2 private subnets across 2 AZs |
| ALB | public subnets; the only internet-facing component |
| ECS Fargate | task in **private subnets**, `assign_public_ip = false` |
| VPC endpoints | S3 + DynamoDB (gateway, free) · ECR api/dkr + logs (interface) |
| DynamoDB | `secure-container-pipeline-notes`, on-demand |
| IAM | task-execution role (ECR pull + logs) and task role (only its DynamoDB table) |

## Networking decision — endpoints, not a NAT gateway

The Fargate task has **no route to the internet** — the private route table has no default route. It reaches AWS services through **VPC endpoints**: free gateway endpoints for S3 (ECR layer storage) and DynamoDB, and interface endpoints for ECR (api + dkr) and CloudWatch Logs.

Honest note: for a *persistently running* service, ~3 interface endpoints (~$7/mo each) cost roughly the same as a NAT gateway (~$32/mo). The reason to prefer endpoints here is **security posture — zero egress to the open internet**, not raw cost. For a short-lived demo both are pennies.

## Security decisions

- **App is never internet-reachable** — only the ALB is public; the task SG accepts traffic **only from the ALB SG**, on port 8080.
- **No public egress** — private subnets + endpoints; the container can't call out to the internet.
- **Least-privilege task role** — the app can touch only its own DynamoDB table (`GetItem`/`PutItem`/`Scan`), nothing else.
- **DynamoDB is never public** — reached over the gateway endpoint, inside the VPC.

## Deploy / destroy

```bash
cd terraform
terraform apply    # ~5 min (endpoints + ALB); waits then reach the ALB URL output
terraform destroy  # tear it down — the ALB (~$16/mo) should not be left running
```

## Cost discipline

The **ALB bills ~$16/mo the moment it exists.** This stack is built to run for a demo/screenshot session and then be destroyed. Everything else (Fargate, DynamoDB on-demand, endpoints) is pay-per-use and near-free for short runs.

## Gotcha — image architecture

First deploy failed with `CannotPullContainerError: image Manifest does not contain
descriptor matching platform 'linux/amd64'`. The image was built on an Apple Silicon
Mac (**arm64**), but Fargate defaults to **amd64**. Fix: build for the target platform —
`docker buildx build --platform linux/amd64 ... --push`. (CI runners are amd64, so the
Stage 3 pipeline produces the right arch automatically; this only bites local Mac builds.)

## Next (Stage 3)

The DevSecOps pipeline: Checkov/tfsec on this Terraform, Trivy on the image, gitleaks for secrets — each a hard gate that blocks a bad PR before merge.
