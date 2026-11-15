variable "name" { type = string }
variable "region" { type = string }
variable "vpc_cidr" {
  type    = string
  default = "10.20.0.0/16"
}
variable "single_nat" {
  description = "One NAT gateway (staging, cheaper) instead of one per AZ (production)."
  type        = bool
  default     = false
}
variable "log_retention_days" {
  type    = number
  default = 90
}
