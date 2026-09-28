module "namespace" {
    source = "./modules/namespace"
    name = var.namespace_name
    labels = var.namespace_labels
}