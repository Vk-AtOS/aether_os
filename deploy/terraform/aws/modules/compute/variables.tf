variable "name" { type = string }
variable "region" { type = string }
variable "vpc_id" { type = string }
variable "public_subnet_ids" { type = list(string) }
variable "app_subnet_ids" { type = list(string) }
variable "sandbox_subnet_ids" { type = list(string) }
variable "kms_key_arn" { type = string }
variable "secret_arns" { type = map(string) }
variable "queue_url" { type = string }
variable "queue_arn" { type = string }
variable "dlq_url" { type = string }
variable "dlq_arn" { type = string }
variable "artifacts_bucket" { type = string }
variable "artifacts_bucket_arn" { type = string }

variable "app_domain" {
  description = "Dashboard/API host, e.g. app.example.com"
  type        = string
}
variable "preview_domain" {
  description = "Preview apex; runs are served from <run-id>.<preview_domain>"
  type        = string
}
variable "app_certificate_arn" { type = string }
variable "preview_certificate_arn" { type = string }

variable "api_image" {
  description = "AetherOS image, pinned by digest (repo@sha256:...)"
  type        = string
}
variable "velaris_image" {
  description = "Velaris image, pinned by digest"
  type        = string
}
variable "sandbox_image" {
  description = "aether-sandbox image the sandbox hosts run, pinned by digest"
  type        = string
}
variable "velaris_org" {
  description = "VELARIS_ORG: the AetherOS organisation id this Velaris deployment serves"
  type        = string
}

variable "api_count" {
  type    = number
  default = 2
}
variable "api_cpu" {
  type    = number
  default = 1024
}
variable "api_memory" {
  type    = number
  default = 2048
}
variable "sandbox_instance_type" {
  type    = string
  default = "t3.large"
}
variable "sandbox_count" {
  type    = number
  default = 1
}
variable "log_retention_days" {
  type    = number
  default = 90
}
variable "waf_acl_arn" {
  description = "Optional WAFv2 web ACL (REGIONAL) to attach to both load balancers"
  type        = string
  default     = ""
}
