output "host" {
  description = "PostgreSQL read-write service host"
  value       = "postgres-rw.${kubernetes_namespace.database.metadata[0].name}.svc.cluster.local"
}

output "port" {
  description = "PostgreSQL port"
  value       = 5432
}

output "database" {
  description = "Database name"
  value       = var.db_name
}

output "username" {
  description = "Application user"
  value       = var.db_user
  sensitive   = true
}

output "password" {
  description = "Application password"
  value       = var.db_password
  sensitive   = true
}

output "credentials_secret_name" {
  description = "Name of the Kubernetes Secret containing PostgreSQL credentials"
  value       = kubernetes_secret.postgres_credentials.metadata[0].name
}