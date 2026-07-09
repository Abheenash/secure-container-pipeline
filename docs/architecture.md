# Architecture

## Pipeline (the DevSecOps gates)

```mermaid
flowchart LR
    dev([Developer]) -->|push / PR| gh[GitHub]
    gh --> pipe{{security-pipeline}}
    subgraph gates[Hard gates — all must pass]
        g1[gitleaks<br/>secrets]
        g2[checkov + tfsec<br/>IaC misconfig]
        g3[trivy<br/>image + deps CVEs]
    end
    pipe --> g1 & g2 & g3
    g1 & g2 & g3 -->|all green| merge[(merge to main)]
    g1 -. any finding .-> block[/blocked/]
    g2 -. any finding .-> block
    g3 -. any finding .-> block
    merge -->|OIDC, no static keys| tf[terraform apply]
    tf --> aws[AWS]
```

## Runtime (what Terraform deploys)

```mermaid
flowchart TB
    user([Internet]) -->|HTTP| waf[WAF]
    waf --> alb[ALB<br/>public subnets]
    subgraph vpc[VPC — no NAT gateway]
        alb -->|SG: 8080 from ALB only| task[Fargate task<br/>private subnets]
        task -->|gateway endpoint| ddb[(DynamoDB<br/>SSE + PITR)]
        task -->|interface endpoint| sm[Secrets Manager]
        task -->|interface endpoints| ecr[ECR / Logs]
    end
    task -.-> cw[CloudWatch<br/>logs + alarms] --> sns[SNS]

    classDef store fill:#1a3a5c,stroke:#5b8cff,color:#fff
    class ddb,sm store
```

## The story in one line

**Build** a container → **ship** it only if it passes secrets/IaC/CVE gates → **run** it on Fargate in private subnets, secrets from Secrets Manager, fronted by an ALB + WAF, with no path to the open internet.

## Security posture

- **Nothing insecure merges** — three fail-the-build gates on every PR.
- **No long-lived credentials** — CI authenticates to AWS via GitHub OIDC.
- **No public egress** — private subnets + VPC endpoints (no NAT).
- **App is never internet-reachable** — only the ALB (behind WAF) is public.
- **Least privilege** — the task role can touch only its own DynamoDB table and secret.
- **Secrets never in code or image** — generated and injected from Secrets Manager at runtime.

See [stage2](stage2.md) (infra), and the reviewed scanner baseline in [`.checkov.yaml`](../.checkov.yaml).
