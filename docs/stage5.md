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

> This happened as described, and [PR #1](https://github.com/Abheenash/secure-container-pipeline/pull/1)
> is still open in the repository so the gate output can be read. The branch-protection rule that
> produced the `BLOCKED` state has since been removed — see **Enforcement** below.

> That's the whole project's thesis in one screenshot: insecure code doesn't get in.

## Enforcement

**The gates are no longer a wall, and saying so is the point of this section.**

`main` used to carry branch protection requiring the status checks in `strict` mode, and that is
what blocked PR #1 above. That requirement has been removed, so the four gates now *report*
rather than *prevent*: they run on every push and pull request, they fail the build when they
find something, and nothing stops a merge over a red build.

The reason is honest rather than technical. I am the only person working on these repositories,
so every push was mine and every one of them bypassed the rule using admin rights — a required
check that its only user routinely overrides is a formality, not a control, and leaving it in
place would have implied an approval step that never happened. All sixteen repositories now
behave identically.

What a reviewer should take from this repo is therefore the gates themselves and what they
caught, not the presence of a setting: four scanners wired in, a planted credential stopped by
two of them independently, and an image that ships without a package installer — with a build
failure if that removal ever silently stops working.

## Wrap

- **Clean Terraform** — `terraform fmt`, `validate`, and a green checkov/tfsec baseline.
- **Architecture** — [docs/architecture.md](architecture.md) (pipeline + runtime diagrams).
- **Reproducible** — `terraform apply` stands the stack up; `terraform destroy` tears it down.

## What this project demonstrates

Build → ship → run, securely: a container built and scanned, shipped only through gates that
block secrets/misconfig/CVEs, running on Fargate in private subnets with no internet egress,
secrets from Secrets Manager, fronted by an ALB + WAF — all as Terraform, all through a
keyless (OIDC) pipeline.
