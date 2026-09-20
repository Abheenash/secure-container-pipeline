variable "region" {
  type    = string
  default = "us-east-1"
}

variable "name_prefix" {
  type    = string
  default = "secure-container-pipeline"
}

variable "image_tag" {
  description = "ECR image tag to deploy."
  type        = string
  default     = "v0.1.0"
}

variable "container_port" {
  type    = number
  default = 8080
}

variable "desired_count" {
  type    = number
  default = 1
}

variable "alarm_email" {
  description = "Email for CloudWatch alarms (empty = no subscription; confirmation is manual)."
  type        = string
  default     = ""
}

variable "certificate_arn" {
  description = "ACM certificate ARN. When set, the ALB serves HTTPS and redirects HTTP -> HTTPS; empty = HTTP-only demo."
  type        = string
  default     = ""
}

variable "min_count" {
  type    = number
  default = 1
}

variable "max_count" {
  type    = number
  default = 4
}

variable "deployment_strategy" {
  description = "rolling = ECS rolling update with circuit-breaker rollback (default). blue_green = CodeDeploy blue/green with traffic shifting and alarm-triggered rollback."
  type        = string
  default     = "rolling"
  validation {
    condition     = contains(["rolling", "blue_green"], var.deployment_strategy)
    error_message = "deployment_strategy must be rolling or blue_green."
  }
}

variable "traffic_shift" {
  description = "CodeDeploy traffic-shifting config for blue_green: canary (10% for 5 min, then all), linear (10% every minute), or all_at_once."
  type        = string
  default     = "canary"
  validation {
    condition     = contains(["canary", "linear", "all_at_once"], var.traffic_shift)
    error_message = "traffic_shift must be canary, linear or all_at_once."
  }
}
