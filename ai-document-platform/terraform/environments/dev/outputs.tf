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