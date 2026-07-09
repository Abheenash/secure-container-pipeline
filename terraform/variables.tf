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
