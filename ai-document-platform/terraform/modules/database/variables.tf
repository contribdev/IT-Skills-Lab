variable "namespace" {
  description = "PostgreSQL cluster namespace"
  type        = string
  default     = "database"
}

variable "operator_namespace" {
  description = "CloudNativePG namespace"
  type        = string
  default     = "cnpg-system"
}

variable "operator_chart_version" {
  type    = string
  default = "0.22.0"
}

variable "db_name" {
  type    = string
  default = "documents"
}

variable "db_user" {
  description = "Name of the application user"
  type        = string
  default     = "app"
}

variable "db_password" {
  description = "Password for the application user"
  type        = string
  sensitive   = true
}

variable "instances" {
  description = "Number of PostgreSQL instances (1 primary + N-1 replicas)"
  type        = number
  default     = 2
}

variable "storage_size" {
  description = "PVC size per PostgreSQL instance"
  type        = string
  default     = "10Gi"
}

variable "common_labels" {
  description = "Labels applied to all resources"
  type        = map(string)
  default     = {}
}