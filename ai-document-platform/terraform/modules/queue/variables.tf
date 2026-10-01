variable "namespace" {
  description = "Namespace where RabbitMQ will be deployed"
  type        = string
  default     = "queue"
}

variable "username" {
  description = "RabbitMQ application username"
  type        = string
  default     = "app"
}

variable "password" {
  description = "RabbitMQ application password"
  type        = string
  sensitive   = true
}

variable "erlang_cookie" {
  description = "Erlang cookie for RabbitMQ cluster (dev: fixed, prod: random)"
  type        = string
  sensitive   = true
  default     = "SWQOKODSQALRPCLNMEQG"
}

variable "storage_size" {
  description = "PVC size for RabbitMQ data"
  type        = string
  default     = "10Gi"
}

variable "queues" {
  description = "List of queues to pre-create"
  type        = list(string)
  default     = ["ocr.queue", "llm.queue"]
}

variable "common_labels" {
  description = "Labels applied to all resources"
  type        = map(string)
  default     = {}
}
