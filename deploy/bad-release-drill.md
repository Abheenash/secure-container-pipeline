# Drill: prove the rollback fires

The value of alarm-triggered rollback is only real if it has been *seen* to fire. This drill ships
a deliberately broken release and expects CodeDeploy to roll it back with no human involved.

**Prerequisite:** the stack applied with `deployment_strategy = "blue_green"`.

1. Build an image whose readiness fails on demand — the app honours `FAIL_READY=1`
   (`/ready` returns 503 while `/health` stays 200, exactly what a dependency outage looks like):
   ```bash
   aws ecs register-task-definition --cli-input-json "$(aws ecs describe-task-definition \
     --task-definition secure-container-pipeline --query taskDefinition \
     | jq '.containerDefinitions[0].environment += [{"name":"FAIL_READY","value":"1"}]
           | del(.taskDefinitionArn,.revision,.status,.requiresAttributes,.compatibilities,.registeredAt,.registeredBy)')"
   ```
2. Deploy it through CodeDeploy (`scripts/deploy-bluegreen.sh <task-def-arn>`).
3. Watch: green tasks start, the green target group never reports healthy, `*-unhealthy-hosts`
   (and `*-green-5xx` if the canary shifted) go to ALARM, and the deployment status becomes
   `Stopped` with `DEPLOYMENT_STOP_ON_ALARM` → rollback. Blue never lost a request.
4. Record: time from deployment start to rollback complete, requests served by green (should be
   0 with canary — the health check gates the shift), and the alarm that fired first.

A second drill flips the failure mid-shift: start a healthy release, then set `FAIL_READY` on the
green task set once 10% is shifted. The `green-5xx` alarm (1-minute period, threshold 1) should
stop the shift within ~2 minutes.
