variable "namespace" {
  description = "Nammespace where MinIO will be deployed"
  type = string
  default = "storage"
}

variable "root_user" {
    description = "MinIO root user"
    type = string  
}

variable "root_password" {
    description = "MinIO root password"
    type = string
    sensitive = true  
}

variable "storage_size" {
    description = "PVC size for MinIO"
    type = string
    default = "10Gi"  
}

variable "bucket_name" {
    description = "Name of the bucket to create"
    type=string
}

variable "common_labels" {
    description = "Labels applied to resorces"  
    type = map(string)
    default = {}
}

