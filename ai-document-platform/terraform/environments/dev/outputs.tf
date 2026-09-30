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