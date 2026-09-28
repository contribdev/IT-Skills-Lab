variable "name" {
  description = "Cluster name"
  type = string
}

variable "labels" {
    description = "Cluster labels"
    type = map(string)
}