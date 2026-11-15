# staging. Separate state (see backend.tf), separate AWS account recommended. Never apply without owner approval.
terraform {
  required_version = ">= 1.6"
  required_providers {
    aws    = { source = "hashicorp/aws", version = "~> 5.60" }
    random = { source = "hashicorp/random", version = "~> 3.6" }
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = { Project = "aetheros", Environment = "staging", ManagedBy = "terraform" }
  }
}

variable "region" {
  type    = string
  default = "ap-south-1"
}
variable "app_domain" { type = string }
variable "app_zone_id" { type = string }
variable "preview_domain" { type = string }
variable "preview_zone_id" { type = string }
variable "api_image" { type = string }
variable "velaris_image" { type = string }
variable "sandbox_image" { type = string }
variable "velaris_org" { type = string }
variable "waf_acl_arn" {
  type    = string
  default = ""
}

module "stack" {
  source            = "../../modules/stack"
  name              = "aetheros-staging"
  region            = var.region
  app_domain        = var.app_domain
  app_zone_id       = var.app_zone_id
  preview_domain    = var.preview_domain
  preview_zone_id   = var.preview_zone_id
  api_image         = var.api_image
  velaris_image     = var.velaris_image
  sandbox_image     = var.sandbox_image
  velaris_org       = var.velaris_org
  production_sizing = false
  waf_acl_arn       = var.waf_acl_arn
}

output "alerts_topic_arn" { value = module.stack.alerts_topic_arn }
output "secret_arns" { value = module.stack.secret_arns }
