module "storage" {
  source        = "../../modules/storage"
  bucket_name   = var.minio_bucket_name
  root_user     = var.minio_root_user
  root_password = var.minio_root_password
}

module "database" {
  source = "../../modules/database"

  namespace     = local.namespaces.database
  db_name       = var.db_name
  db_user       = var.db_user
  db_password   = var.db_password
  instances     = var.db_instances
  storage_size  = var.db_storage_size
  common_labels = local.common_labels
}

