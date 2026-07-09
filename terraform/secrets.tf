# Runtime secret pulled from Secrets Manager — never baked into the image or env file.
# Value is generated (no literal secret in code) and injected into the task at runtime.

resource "random_password" "app" {
  length  = 24
  special = false
}

resource "aws_secretsmanager_secret" "app" {
  name        = "${var.name_prefix}/app"
  description = "Runtime secret for the notes API"
}

resource "aws_secretsmanager_secret_version" "app" {
  secret_id     = aws_secretsmanager_secret.app.id
  secret_string = jsonencode({ APP_SECRET = random_password.app.result })
}

# The task-execution role may read only this one secret.
data "aws_iam_policy_document" "read_secret" {
  statement {
    sid       = "ReadAppSecretOnly"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.app.arn]
  }
}

resource "aws_iam_role_policy" "task_exec_secret" {
  name   = "${var.name_prefix}-read-secret"
  role   = aws_iam_role.task_exec.id
  policy = data.aws_iam_policy_document.read_secret.json
}
