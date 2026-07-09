# Stage 4 — hardening

**Goal:** raise the security posture and quiet the scanners honestly — by fixing real
issues, not just suppressing them.

## What was added

| Area | Hardening |
|---|---|
| **Secrets** | Secrets Manager secret, value **generated** (no literal in code), injected into the task at runtime via `secrets` (not env/image). Task-execution role may read **only that one secret**. |
| **Edge** | **WAF** on the ALB — AWS managed common rule set + known-bad-inputs (Log4Shell). |
| **Data** | DynamoDB **SSE** + **point-in-time recovery**. |
| **Observability** | CloudWatch alarms (ALB 5xx, unhealthy hosts) → SNS; container insights; 1-year log retention. |
| **Network** | SG rules carry descriptions; ALB drops invalid header fields. |

## Secrets Manager — the pattern

```
Terraform generates a random value ─> Secrets Manager
                                          │  (task-exec role: GetSecretValue on this ARN only)
ECS task definition `secrets` block ─────┘─> APP_SECRET env in the container at runtime
```

The secret never appears in the image, the repo, or an env file — it's fetched by the ECS
agent (over the Secrets Manager **VPC interface endpoint**, from the private subnet) and
injected when the task starts.

## Still accepted (documented, not fixed)

Items that would add cost/scope beyond a demo remain on the reviewed baseline in
[`.checkov.yaml`](../.checkov.yaml): HTTPS (needs a domain + cert), customer-managed KMS
keys, ALB access-log bucket, VPC flow logs, secret rotation Lambda. Each is a one-line,
justified entry — the honest way to run security scanners in the real world.
