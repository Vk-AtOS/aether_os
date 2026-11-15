variable "name" { type = string }
variable "vpc_id" { type = string }
variable "data_subnet_ids" { type = list(string) }
variable "client_security_group_ids" {
  description = "Security groups of the containers allowed to reach Postgres and Redis."
  type        = list(string)
}
variable "db_instance_class" {
  type    = string
  default = "db.t4g.medium"
}
variable "db_allocated_gb" {
  type    = number
  default = 100
}
variable "db_multi_az" {
  type    = bool
  default = true
}
variable "db_backup_days" {
  type    = number
  default = 14
}
variable "redis_node_type" {
  type    = string
  default = "cache.t4g.small"
}
variable "deletion_protection" {
  type    = bool
  default = true
}
