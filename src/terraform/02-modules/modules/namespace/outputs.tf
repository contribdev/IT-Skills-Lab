output "name" {
  description = "Created cluster name"
  value = kubernetes_namespace.this.metadata[0].name
}