output "storage_endpoint" {
  value = module.storage.endpoint
}

output "storage_bucket" {
  value = module.storage.bucket
}

output "storage_access_key" {
  value     = module.storage.access_key
  sensitive = true
}

output "storage_secret_key" {
  value     = module.storage.secret_key
  sensitive = true
}

output "storage_credentials_secret" {
  value = module.storage.credentials_secret_name
}

output "db_host" {
  description = "PostgreSQL host"
  value       = module.database.host
}

output "db_port" {
  description = "PostgreSQL port"
  value       = module.database.port
}

output "db_name" {
  description = "Database name"
  value       = module.database.database
}

output "db_username" {
  description = "Database username"
  value       = module.database.username
  sensitive   = true
}

output "db_password" {
  description = "Database password"
  value       = module.database.password
  sensitive   = true
}

output "db_credentials_secret" {
  description = "Kubernetes Secret name for PostgreSQL credentials"
  value       = module.database.credentials_secret_name
}

output "queue_host" {
  description = "RabbitMQ AMQP host"
  value       = module.queue.host
}

output "queue_amqp_port" {
  description = "AMQP port"
  value       = module.queue.amqp_port
}

output "queue_management_port" {
  description = "Management API port"
  value       = module.queue.management_port
}

output "queue_amqp_url" {
  description = "Ready-to-use AMQP URL"
  value       = module.queue.amqp_url
  sensitive   = true
}

output "queue_username" {
  description = "RabbitMQ username"
  value       = module.queue.username
  sensitive   = true
}

output "queue_password" {
  description = "RabbitMQ password"
  value       = module.queue.password
  sensitive   = true
}

output "queue_credentials_secret" {
  description = "Kubernetes Secret name"
  value       = module.queue.credentials_secret_name
}

output "queue_queues" {
  description = "List of pre-created queues"
  value       = module.queue.queues
}