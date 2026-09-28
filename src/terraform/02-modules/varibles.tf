variable "namespace_name" {
    type = string
    default="module-try"
}

variable "namespace_labels" {
    type = map(string)
    default = {
      "best_car" = "sky34"
      "try_module" = "true"
    }  
}
