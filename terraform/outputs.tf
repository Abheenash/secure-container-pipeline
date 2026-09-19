output "alb_url" {
  description = "Public URL of the service."
  value       = "${var.certificate_arn == "" ? "http" : "https"}://${aws_lb.main.dns_name}"
}

output "notes_table" {
  value = aws_dynamodb_table.notes.name
}
