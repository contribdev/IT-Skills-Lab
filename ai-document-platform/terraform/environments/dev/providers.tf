provider "kubernetes" {
  config_path    = pathexpand("~/.kube/config-lab")
  config_context = var.kube_context
}

provider "helm" {
  kubernetes {
    config_path    = pathexpand("~/.kube/config-lab")
    config_context = var.kube_context
  }
}

provider "kubectl" {
  config_path    = pathexpand("~/.kube/config-lab")
  config_context = var.kube_context
}