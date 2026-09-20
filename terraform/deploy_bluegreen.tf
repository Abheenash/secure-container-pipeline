# Blue/green deployments with CodeDeploy — the strategy that lets a release be
# *tested* on the green target group before any user sees it, then shifted over
# canary/linear with an automatic rollback if the alarms trip during the shift.
#
# How a release flows (see deploy/appspec.yaml and the pipeline job):
#   1. CodeDeploy starts the new task set on the GREEN target group.
#   2. The test listener (:9001) points at green — a smoke test can hit it while
#      production traffic still goes to blue on :80.
#   3. Traffic shifts per var.traffic_shift (canary: 10% for 5 minutes, then 100%).
#   4. If sfs alb-5xx, green-5xx or unhealthy-hosts go to ALARM at any point, CodeDeploy
#      shifts everything back to blue and terminates green. Nobody is paged to do it.
#   5. Blue is kept for 30 minutes after cut-over so a late rollback is instant.

locals {
  bg = var.deployment_strategy == "blue_green"
  traffic_config = {
    canary      = "CodeDeployDefault.ECSCanary10Percent5Minutes"
    linear      = "CodeDeployDefault.ECSLinear10PercentEvery1Minutes"
    all_at_once = "CodeDeployDefault.ECSAllAtOnce"
  }
}

resource "aws_lb_target_group" "green" {
  count       = local.bg ? 1 : 0
  name        = "${var.name_prefix}-tg-green"
  port        = var.container_port
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "ip"
  health_check {
    path                = "/ready"
    matcher             = "200"
    interval            = 15
    healthy_threshold   = 2
    unhealthy_threshold = 2
  }
}

# Test listener: reaches whichever target group is currently "green" so a release
# can be validated before it takes production traffic.
resource "aws_lb_listener" "test" {
  count             = local.bg ? 1 : 0
  load_balancer_arn = aws_lb.main.arn
  port              = 9001
  protocol          = "HTTP"
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.green[0].arn
  }
}

resource "aws_security_group_rule" "alb_test_listener" {
  count             = local.bg ? 1 : 0
  type              = "ingress"
  security_group_id = aws_security_group.alb.id
  from_port         = 9001
  to_port           = 9001
  protocol          = "tcp"
  cidr_blocks       = [aws_vpc.main.cidr_block] # only reachable from inside the VPC (the smoke-test task)
  description       = "blue/green test listener, VPC-internal"
}

resource "aws_ecs_service" "app_bg" {
  count           = local.bg ? 1 : 0
  name            = var.name_prefix
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.app.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  deployment_controller {
    type = "CODE_DEPLOY"
  }

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.task.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.app.arn
    container_name   = "app"
    container_port   = var.container_port
  }

  health_check_grace_period_seconds = 60
  depends_on                        = [aws_lb_listener.http]

  # CodeDeploy owns the task definition and which target group is live.
  lifecycle {
    ignore_changes = [task_definition, load_balancer, desired_count]
  }
}

# 5xx on the GREEN target group specifically — the earliest signal that the new
# release is bad, before it has more than a canary's worth of traffic.
resource "aws_cloudwatch_metric_alarm" "green_5xx" {
  count               = local.bg ? 1 : 0
  alarm_name          = "${var.name_prefix}-green-5xx"
  alarm_description   = "5xx from the target group receiving the new release"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "HTTPCode_Target_5XX_Count"
  dimensions          = { LoadBalancer = aws_lb.main.arn_suffix, TargetGroup = aws_lb_target_group.green[0].arn_suffix }
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
}

data "aws_iam_policy_document" "codedeploy_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["codedeploy.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "codedeploy" {
  count              = local.bg ? 1 : 0
  name               = "${var.name_prefix}-codedeploy"
  assume_role_policy = data.aws_iam_policy_document.codedeploy_assume.json
}

resource "aws_iam_role_policy_attachment" "codedeploy_ecs" {
  count      = local.bg ? 1 : 0
  role       = aws_iam_role.codedeploy[0].name
  policy_arn = "arn:aws:iam::aws:policy/AWSCodeDeployRoleForECS"
}

resource "aws_codedeploy_app" "app" {
  count            = local.bg ? 1 : 0
  name             = var.name_prefix
  compute_platform = "ECS"
}

resource "aws_codedeploy_deployment_group" "app" {
  count                  = local.bg ? 1 : 0
  app_name               = aws_codedeploy_app.app[0].name
  deployment_group_name  = "${var.name_prefix}-bg"
  service_role_arn       = aws_iam_role.codedeploy[0].arn
  deployment_config_name = local.traffic_config[var.traffic_shift]

  deployment_style {
    deployment_type   = "BLUE_GREEN"
    deployment_option = "WITH_TRAFFIC_CONTROL"
  }

  ecs_service {
    cluster_name = aws_ecs_cluster.main.name
    service_name = aws_ecs_service.app_bg[0].name
  }

  load_balancer_info {
    target_group_pair_info {
      prod_traffic_route {
        listener_arns = [aws_lb_listener.http.arn]
      }
      test_traffic_route {
        listener_arns = [aws_lb_listener.test[0].arn]
      }
      target_group {
        name = aws_lb_target_group.app.name
      }
      target_group {
        name = aws_lb_target_group.green[0].name
      }
    }
  }

  blue_green_deployment_config {
    deployment_ready_option {
      action_on_timeout = "CONTINUE_DEPLOYMENT" # the pipeline's smoke test runs before this; failing it stops the deployment
    }
    terminate_blue_instances_on_deployment_success {
      action                           = "TERMINATE"
      termination_wait_time_in_minutes = 30 # blue stays warm: a late rollback is a listener flip, not a redeploy
    }
  }

  # The whole point: alarms roll it back without a human.
  alarm_configuration {
    enabled = true
    alarms  = [aws_cloudwatch_metric_alarm.alb_5xx.alarm_name, aws_cloudwatch_metric_alarm.unhealthy_hosts.alarm_name, aws_cloudwatch_metric_alarm.green_5xx[0].alarm_name]
  }
  auto_rollback_configuration {
    enabled = true
    events  = ["DEPLOYMENT_FAILURE", "DEPLOYMENT_STOP_ON_ALARM", "DEPLOYMENT_STOP_ON_REQUEST"]
  }
}

output "codedeploy" {
  value = local.bg ? { app = aws_codedeploy_app.app[0].name, group = aws_codedeploy_deployment_group.app[0].deployment_group_name, test_url = "http://${aws_lb.main.dns_name}:9001" } : null
}
