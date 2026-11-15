variable "app_alb_dns" { type = string }
variable "app_alb_zone_id" { type = string }
variable "preview_alb_dns" { type = string }
variable "preview_alb_zone_id" { type = string }

resource "aws_route53_record" "app" {
  for_each = toset([var.app_domain, "velaris.${var.app_domain}"])
  zone_id  = var.app_zone_id
  name     = each.value
  type     = "A"
  alias {
    name                   = var.app_alb_dns
    zone_id                = var.app_alb_zone_id
    evaluate_target_health = true
  }
}

# The preview apex and the wildcard (every <run-id>.<preview domain>) point at the preview load balancer.
resource "aws_route53_record" "preview" {
  for_each = toset([var.preview_domain, "*.${var.preview_domain}"])
  zone_id  = var.preview_zone_id
  name     = each.value
  type     = "A"
  alias {
    name                   = var.preview_alb_dns
    zone_id                = var.preview_alb_zone_id
    evaluate_target_health = true
  }
}
