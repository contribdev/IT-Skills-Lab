resource "kubernetes_namespace" "cnpg_system" {
  metadata {
    name   = var.operator_namespace
    labels = var.common_labels
  }
}

resource "kubernetes_namespace" "database" {
  metadata {
    name   = var.namespace
    labels = var.common_labels
  }
}

resource "helm_release" "cnpg_operator" {
  name       = "cnpg"
  namespace  = kubernetes_namespace.cnpg_system.metadata[0].name
  repository = "https://cloudnative-pg.github.io/charts"
  chart      = "cloudnative-pg"
  version    = var.operator_chart_version

  set {
    name  = "crds.create"
    value = "true"
  }

  wait = false

  timeout = 300
}

resource "kubernetes_secret" "postgres_credentials" {
  metadata {
    name      = "postgres-app-credentials"
    namespace = kubernetes_namespace.database.metadata[0].name
    labels    = var.common_labels
  }
  data = {
    username = var.db_user
    password = var.db_password
  }
  type = "Opaque"
}

resource "kubectl_manifest" "postgres_cluster" {
  yaml_body = yamlencode({
    apiVersion = "postgresql.cnpg.io/v1"
    kind       = "Cluster"
    metadata = {
      name      = "postgres"
      namespace = kubernetes_namespace.database.metadata[0].name
      labels    = var.common_labels
    }
    spec = {
      instances = var.instances

      storage = {
        size = var.storage_size
      }

      bootstrap = {
        initdb = {
          database = var.db_name
          owner    = var.db_user
          secret = {
            name = kubernetes_secret.postgres_credentials.metadata[0].name
          }
        }
      }

      resources = {
        requests = {
          memory = "256Mi"
          cpu    = "100m"
        }
        limits = {
          memory = "512Mi"
          cpu    = "500m"
        }
      }

      postgresql = {
        parameters = {
          max_connections = "100"
        }
      }
    }
  })
  depends_on = [
    helm_release.cnpg_operator,
    kubernetes_secret.postgres_credentials,
  ]
}