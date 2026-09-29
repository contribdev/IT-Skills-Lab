module "storage" {
  source        = "../../modules/storage"
  bucket_name   = var.minio_bucket_name
  root_user     = var.minio_root_user
  root_password = var.minio_root_password
}