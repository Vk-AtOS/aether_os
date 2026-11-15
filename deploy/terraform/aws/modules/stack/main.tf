# One complete environment. `environments/<env>` call this with their own sizes; each has its own state.
terraform {
  required_version = ">= 1.6"
  required_providers {
    aws    = { source = "hashicorp/aws", version = "~> 5.60" }
    random = { source = "hashicorp/random", version = "~> 3.6" }
  }
}

variable "name" { type = string }
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
variable "production_sizing" {
  description = "true: Multi-AZ database and cache, one NAT per AZ, deletion protection"
  type        = bool
  default     = true
}
variable "waf_acl_arn" {
  type    = string
  default = ""
}

module "network" {
  source     = "../network"
  name       = var.name
  region     = var.region
  single_nat = !var.production_sizing
}

module "data" {
  source                    = "../data"
  name                      = var.name
  vpc_id                    = module.network.vpc_id
  data_subnet_ids           = module.network.data_subnet_ids
  client_security_group_ids = [module.compute.api_security_group_id]
  db_multi_az               = var.production_sizing
  deletion_protection       = var.production_sizing
  db_instance_class         = var.production_sizing ? "db.t4g.medium" : "db.t4g.small"
}

module "edge" {
  source              = "../edge"
  app_domain          = var.app_domain
  app_zone_id         = var.app_zone_id
  preview_domain      = var.preview_domain
  preview_zone_id     = var.preview_zone_id
  app_alb_dns         = module.compute.app_alb_dns
  app_alb_zone_id     = module.compute.app_alb_zone_id
  preview_alb_dns     = module.compute.preview_alb_dns
  preview_alb_zone_id = module.compute.preview_alb_zone_id
}

module "compute" {
  source                  = "../compute"
  name                    = var.name
  region                  = var.region
  vpc_id                  = module.network.vpc_id
  public_subnet_ids       = module.network.public_subnet_ids
  app_subnet_ids          = module.network.app_subnet_ids
  sandbox_subnet_ids      = module.network.sandbox_subnet_ids
  kms_key_arn             = module.data.kms_key_arn
  secret_arns             = module.data.secret_arns
  queue_url               = module.data.queue_url
  queue_arn               = module.data.queue_arn
  dlq_url                 = module.data.dlq_url
  dlq_arn                 = module.data.dlq_arn
  artifacts_bucket        = module.data.artifacts_bucket
  artifacts_bucket_arn    = module.data.artifacts_bucket_arn
  app_domain              = var.app_domain
  preview_domain          = var.preview_domain
  app_certificate_arn     = module.edge.app_certificate_arn
  preview_certificate_arn = module.edge.preview_certificate_arn
  api_image               = var.api_image
  velaris_image           = var.velaris_image
  sandbox_image           = var.sandbox_image
  velaris_org             = var.velaris_org
  api_count               = var.production_sizing ? 2 : 1
  waf_acl_arn             = var.waf_acl_arn
}

module "observability" {
  source                      = "../observability"
  name                        = var.name
  app_alb_arn_suffix          = module.compute.app_alb_arn_suffix
  preview_alb_arn_suffix      = module.compute.preview_alb_arn_suffix
  api_target_group_arn_suffix = module.compute.api_target_group_arn_suffix
  dlq_name                    = module.data.dlq_name
  queue_name                  = module.data.queue_name
  db_identifier               = module.data.db_identifier
  kms_key_arn                 = module.data.kms_key_arn
}

output "alerts_topic_arn" { value = module.observability.alerts_topic_arn }
output "backups_bucket" { value = module.data.backups_bucket }
output "secret_arns" { value = module.data.secret_arns }
