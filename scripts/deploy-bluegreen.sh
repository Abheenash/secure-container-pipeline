#!/usr/bin/env bash
# Start a CodeDeploy blue/green deployment for a registered task definition and
# follow it to completion, exiting non-zero on rollback.
#   scripts/deploy-bluegreen.sh <task-definition-arn>
set -euo pipefail
TD=${1:?task definition arn}
APP=${APP:-secure-container-pipeline}
GROUP=${GROUP:-secure-container-pipeline-bg}
SPEC=$(sed "s|<TASK_DEFINITION>|$TD|" "$(dirname "$0")/../deploy/appspec.yaml")
ID=$(aws deploy create-deployment --application-name "$APP" --deployment-group-name "$GROUP" \
  --revision "revisionType=AppSpecContent,appSpecContent={content='$SPEC'}" --query deploymentId --output text)
echo "deployment $ID started for $TD"
T0=$(date +%s)
while :; do
  S=$(aws deploy get-deployment --deployment-id "$ID" --query 'deploymentInfo.status' --output text)
  printf '%s  %s (%ss)\n' "$(date -u +%H:%M:%S)" "$S" "$(( $(date +%s) - T0 ))"
  case "$S" in
    Succeeded) exit 0 ;;
    Failed|Stopped) aws deploy get-deployment --deployment-id "$ID" --query 'deploymentInfo.{reason:errorInformation.message,rollback:rollbackInfo}' --output json; exit 1 ;;
  esac
  sleep 15
done
