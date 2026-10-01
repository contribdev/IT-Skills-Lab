resource "kubernetes_namespace" "this" {
  metadata {
    name   = var.namespace
    labels = var.common_labels
  }
}

resource "kubernetes_secret" "credentials" {
  metadata {
    name      = "rabbitmq-credentials"
    namespace = kubernetes_namespace.this.metadata[0].name
    labels    = var.common_labels
  }

  data = {
    username       = var.username
    password       = var.password
    amqp-url       = "amqp://${var.username}:${var.password}@rabbitmq.${kubernetes_namespace.this.metadata[0].name}.svc.cluster.local:5672"
    management-url = "http://rabbitmq.${kubernetes_namespace.this.metadata[0].name}.svc.cluster.local:15672"
  }

  type = "Opaque"
}

resource "helm_release" "rabbitmq" {
  name       = "rabbitmq"
  namespace  = kubernetes_namespace.this.metadata[0].name
  repository = "oci://registry-1.docker.io/bitnamicharts"
  chart      = "rabbitmq"
  version    = "14.6.10"

  # ---------- Image (legacy) ----------
  set {
    name  = "image.repository"
    value = "bitnamilegacy/rabbitmq"
  }
  set {
    name  = "image.tag"
    value = "4.1.3-debian-12-r1"
  }

  # ---------- Credentials ----------
  set {
    name  = "auth.username"
    value = var.username
  }
  set_sensitive {
    name  = "auth.password"
    value = var.password
  }
  set_sensitive {
    name  = "auth.erlangCookie"
    value = var.erlang_cookie
  }

  # ---------- Persistence ----------
  set {
    name  = "persistence.size"
    value = var.storage_size
  }

  # ---------- Resources ----------
  set {
    name  = "resources.requests.memory"
    value = "256Mi"
  }
  set {
    name  = "resources.requests.cpu"
    value = "100m"
  }
  set {
    name  = "resources.limits.memory"
    value = "512Mi"
  }

  # ---------- Management plugin ----------
  set {
    name  = "plugins"
    value = "rabbitmq_management"
  }

  timeout = 600
}

resource "kubernetes_config_map" "create_queues_script" {
  metadata {
    name      = "rabbitmq-create-queues-script"
    namespace = kubernetes_namespace.this.metadata[0].name
    labels    = var.common_labels
  }

  data = {
    "create-queues.sh" = <<-EOT
      #!/bin/sh
      set -e
      MGMT_URL="http://rabbitmq.${kubernetes_namespace.this.metadata[0].name}.svc.cluster.local:15672"
      CREDS="${var.username}:${var.password}"

      echo "Waiting for RabbitMQ management API..."
      until curl -sf -u "$CREDS" "$MGMT_URL/api/overview" > /dev/null 2>&1; do
        sleep 3
      done
      echo "RabbitMQ ready."

      %{ for queue in var.queues ~}
      echo "Creating queue: ${queue}"
      curl -sf -u "$CREDS" -X PUT -H "content-type:application/json" -d '{"durable":true,"arguments":{}}' "$MGMT_URL/api/queues/%2F/${queue}"
      echo "  ok: ${queue}"
      %{ endfor ~}

      echo "All queues created."
    EOT
  }
}

resource "kubernetes_job" "create_queues" {
  metadata {
    name      = "rabbitmq-create-queues"
    namespace = kubernetes_namespace.this.metadata[0].name
    labels    = var.common_labels
  }
  spec {
    backoff_limit = 6
    completions = 1
    parallelism = 1

    template {
      metadata {
        labels = var.common_labels
      }
      spec {
        restart_policy = "OnFailure"

        volume {
          name = "script"
          config_map {
            name         = kubernetes_config_map.create_queues_script.metadata[0].name
            default_mode = "0755"
          }
        }

        container {
          name  = "create-queues"
          image = "curlimages/curl:8.10.1"

          command = ["/bin/sh", "/scripts/create-queues.sh"]

          volume_mount {
            name       = "script"
            mount_path = "/scripts"
          }
          
          resources {
            requests = {
              cpu    = "50m"
              memory = "64Mi"
            }
            limits = {
              cpu    = "100m"
              memory = "128Mi"
            }
          }
        }
      }
    }
  }
  wait_for_completion = true

  timeouts {
    create = "5m"
  }

  depends_on = [helm_release.rabbitmq]
}