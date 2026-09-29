resource "kubernetes_namespace" "this" {
  metadata {
    name   = var.namespace
    labels = var.common_labels
  }
}

resource "kubernetes_secret" "credentials" {
  metadata {
    name      = "minio-credentials"
    namespace = kubernetes_namespace.this.metadata[0].name
    labels    = var.common_labels
  }

  data = {
    access-key = var.root_user
    secret-key = var.root_password
  }

  type = "Opaque"
}

resource "helm_release" "minio" {
  name       = "minio"
  namespace  = kubernetes_namespace.this.metadata[0].name
  repository = "oci://registry-1.docker.io/bitnamicharts"
  chart      = "minio"
  version    = "17.0.21"

  # ---------- Image ----------
  set {
    name  = "image.repository"
    value = "bitnamilegacy/minio"
  }
  set {
    name  = "image.tag"
    value = "2025.7.23-debian-12-r5"
  }

  # ---------- Console (disabled) ----------
  set {
    name  = "console.enabled"
    value = "false"
  }

  # ---------- Credentials ----------
  set {
    name  = "auth.rootUser"
    value = var.root_user
  }
  set_sensitive {
    name  = "auth.rootPassword"
    value = var.root_password
  }

  # ---------- Persistence ----------
  set {
    name  = "persistence.size"
    value = var.storage_size
  }

  # ---------- Mode ----------
  set {
    name  = "mode"
    value = "standalone"
  }

  # ---------- Buckets ----------
  set {
    name  = "defaultBuckets"
    value = var.bucket_name
  }

  # ---------- Resources ----------
  set {
    name  = "resources.requests.memory"
    value = "512Mi"
  }
  set {
    name  = "resources.requests.cpu"
    value = "250m"
  }
  set {
    name  = "resources.limits.memory"
    value = "1Gi"
  }

  timeout = 600
}