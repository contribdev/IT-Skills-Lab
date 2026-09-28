locals {
  common_labels = {
    "app.kubernetes.io/part-of"    = var.project_name
    "app.kubernetes.io/managed-by" = "terraform"
    "environmet"                   = var.environment
  }

  namespaces = {
    storage  = "storage"
    database = "database"
    queue    = "queue"
  }
}

