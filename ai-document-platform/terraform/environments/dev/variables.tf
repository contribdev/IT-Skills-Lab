# kube connection

variable "kube_context" {
  description = "Kubecinfig context to use"
  type        = string
  default     = "default"
}

# env

variable "environment" {
  description = "Environment name"
  type        = string
  default     = "dev"
}

variable "project_name" {
  description = "Project name (labels` and resources` name)"
  type        = string
  default     = "ai-document-platform"
}

# MinIO

variable "minio_root_user" {
  description = "value"
  type        = string
  default     = "admin"
}

variable "minio_root_password" {
  description = "minio root password"
  type        = string
  sensitive   = true
}

variable "minio_storage_size" {
  description = "pvc size for minio"
  type        = string
  default     = "10Gi"
}

variable "minio_bucket_name" {
  description = "bucket name in Minio"
  type        = string
  default     = "documents"
}