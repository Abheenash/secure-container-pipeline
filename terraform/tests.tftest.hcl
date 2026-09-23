# Native terraform tests (`terraform test`), run against a mocked provider so they
# need no AWS account and cost nothing.
#
# These assert the specific promises this repo's README makes. checkov asks
# "is this generally safe?"; these ask "does THIS pipeline still enforce the
# things it advertises?" — which a generic scanner cannot know.

mock_provider "aws" {
  # A mocked data source returns a placeholder string that the AWS provider then
  # rejects as invalid JSON. A minimal valid document keeps the mock usable
  # without pretending to assert IAM semantics.
  # The config slices the first two AZs; a mocked data source returns an empty
  # list, so slice() fails before any assertion runs.
  override_data {
    target = data.aws_availability_zones.available
    values = { names = ["us-east-1a", "us-east-1b"] }
  }
  override_data {
    target = data.aws_iam_policy_document.ecs_assume
    values = { json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}" }
  }
  override_data {
    target = data.aws_iam_policy_document.task
    values = { json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}" }
  }
  override_data {
    target = data.aws_iam_policy_document.read_secret
    values = { json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}" }
  }
  override_data {
    target = data.aws_iam_policy_document.codedeploy_assume
    values = { json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}" }
  }
  # container_definitions interpolates these, and a mocked value is unknown at
  # plan time — which makes jsondecode() on it unknown too, so no assertion about
  # the container can run. override_during = plan makes them concrete early.
  override_data {
    target = data.aws_ecr_repository.app
    values = { repository_url = "111122223333.dkr.ecr.us-east-1.amazonaws.com/scp" }
  }
  override_resource {
    target          = aws_secretsmanager_secret.app
    override_during = plan
    values          = { arn = "arn:aws:secretsmanager:us-east-1:111122223333:secret:scp-test" }
  }
}
mock_provider "random" {}

run "container_does_not_run_as_root" {
  command = plan

  # The pipeline asserts the IMAGE's uid with `docker inspect`. That check passes
  # even if the task definition overrides the user back to root. This asserts the
  # infrastructure side of the same promise, and CKV_SCP_1 asserts it again from
  # the policy direction — the gap that motivated both.
  assert {
    condition = alltrue([
      for c in jsondecode(aws_ecs_task_definition.app.container_definitions) :
      tostring(lookup(c, "user", "")) != "" &&
      !contains(["0", "root", "0:0"], tostring(lookup(c, "user", "")))
    ])
    error_message = "Every container in the task definition must pin a non-root user. An image USER directive is only a default; a task definition can override it."
  }
}

run "container_filesystem_is_read_only" {
  command = plan

  assert {
    condition = alltrue([
      for c in jsondecode(aws_ecs_task_definition.app.container_definitions) :
      lookup(c, "readonlyRootFilesystem", false) == true
    ])
    error_message = "Containers must run with a read-only root filesystem. If a write is genuinely needed, mount a volume for it deliberately."
  }
}

run "tasks_have_no_public_ip" {
  command = plan

  assert {
    # Both services are behind a count (rolling vs blue/green), so iterate rather
    # than index — the assertion then holds whichever strategy is selected.
    condition = alltrue(concat(
      [for s in aws_ecs_service.app : !s.network_configuration[0].assign_public_ip],
      [for s in aws_ecs_service.app_bg : !s.network_configuration[0].assign_public_ip],
    ))
    error_message = "Tasks run in private subnets and reach AWS through VPC endpoints. A public IP here would both cost money and widen the attack surface."
  }
}

run "alb_drops_malformed_headers" {
  command = plan

  # Without this, a client can smuggle a request past the load balancer's own
  # parsing. AWS defaults it to false, so it has to be set on purpose.
  assert {
    condition     = aws_lb.main.drop_invalid_header_fields
    error_message = "The ALB must drop invalid HTTP headers (also enforced by CKV_SCP_2)."
  }
}

run "bad_deploys_roll_themselves_back" {
  command = plan

  assert {
    # Only the rolling service has a circuit breaker; blue/green rolls back via
    # CodeDeploy alarms instead. Iterating means this passes for either strategy
    # and still fails if the rolling service loses its rollback.
    condition = alltrue([
      for s in aws_ecs_service.app :
      s.deployment_circuit_breaker[0].enable && s.deployment_circuit_breaker[0].rollback
    ])
    error_message = "The deployment circuit breaker must both trip AND roll back. Enabling it without rollback just fails the deploy and leaves the bad revision running."
  }
}
