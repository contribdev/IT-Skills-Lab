output "host" {
  description = "RabbitMQ AMQP host"
  value       = "rabbitmq.${kubernetes_namespace.this.metadata[0].name}.svc.cluster.local"
}

output "amqp_port" {
  description = "AMQP port"
  value       = 5672
}

output "management_port" {
  description = "Management API port"
  value       = 15672
}

output "amqp_url" {
  description = "Ready-to-use AMQP URL with credentials"
  value       = "amqp://${var.username}:${var.password}@rabbitmq.${kubernetes_namespace.this.metadata[0].name}.svc.cluster.local:5672"
  sensitive   = true
}

output "username" {
  description = "RabbitMQ username"
  value       = var.username
  sensitive   = true
}

output "password" {
  description = "RabbitMQ password"
  value       = var.password
  sensitive   = true
}

output "credentials_secret_name" {
  description = "Name of the Kubernetes Secret with RabbitMQ credentials"
  value       = kubernetes_secret.credentials.metadata[0].name
}

output "queues" {
  description = "List of pre-created queues"
  value       = var.queues
}