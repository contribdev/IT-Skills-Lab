output "endpoint" {
  description = "MinIO S3 API endpoint (in-cluster)"
  value       = "http://minio.${kubernetes_namespace.this.metadata[0].name}.svc.cluster.local:9000"
}

output "bucket" {
  description = "Name of the documents bucket"
  value       = var.bucket_name
}

output "access_key" {
  description = "S3 access key"
  value       = var.root_user
  sensitive   = true    
}

output "secret_key" {
  description = "S3 secret key"
  value       = var.root_password
  sensitive   = true
}

output "credentials_secret_name" {
  description = "Name of the Kubernetes Secret containing MinIO credentials"
  value       = kubernetes_secret.credentials.metadata[0].name
}