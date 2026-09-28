terraform {
  required_version = ">= 1.6.0"

  required_providers {
    kubernetes = {
        source = "hashicorp/kubernetes"
        version = "~> 2.30"
    }
  }
}

provider "kubernetes" {
    config_path = "~/.kube/config-lab"
}

variable "namespace_name" {
      description = "Имя созданного namespace"
      type = string
      default = "terra-test"
}

resource "kubernetes_namespace" "terraform_test" {
  metadata {
    name = var.namespace_name
  }
}

resource "kubernetes_namespace" "manual-ns" {
    metadata {
      name = "manual-ns"
    }
}

output "created_namespace" {
    description = "Имя созданного namespace"
    value = kubernetes_namespace.terraform_test.metadata[0].name  
}

output "namespace_id" {
  description = "ID namespace в K8S"
  value = kubernetes_namespace.terraform_test.id
}


