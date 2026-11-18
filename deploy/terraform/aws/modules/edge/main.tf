# DNS and TLS: ACM certificates validated by DNS (auto-renewing) and the records for the app, the Velaris public host and
# the wildcard preview origin. The hosted zones must already exist (created by hand once; never destroyed by this stack).
terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.60" }
  }
}

variable "app_domain" { type = string }
variable "app_zone_id" { type = string }
variable "preview_domain" { type = string }
variable "preview_zone_id" { type = string }

# certificates are needed before the load balancers exist; records need the load balancers: two steps in one module
resource "aws_acm_certificate" "app" {
  domain_name               = var.app_domain
  subject_alternative_names = ["velaris.${var.app_domain}"]
  validation_method         = "DNS"
  lifecycle { create_before_destroy = true }
}

resource "aws_acm_certificate" "preview" {
  domain_name               = var.preview_domain
  subject_alternative_names = ["*.${var.preview_domain}"]
  validation_method         = "DNS"
  lifecycle { create_before_destroy = true }
}

resource "aws_route53_record" "app_validation" {
  for_each        = { for o in aws_acm_certificate.app.domain_validation_options : o.domain_name => o }
  zone_id         = var.app_zone_id
  name            = each.value.resource_record_name
  type            = each.value.resource_record_type
  records         = [each.value.resource_record_value]
  ttl             = 60
  allow_overwrite = true
}

# the bare name and the wildcard share one validation record, hence allow_overwrite
resource "aws_route53_record" "preview_validation" {
  for_each        = { for o in aws_acm_certificate.preview.domain_validation_options : o.domain_name => o }
  zone_id         = var.preview_zone_id
  name            = each.value.resource_record_name
  type            = each.value.resource_record_type
  records         = [each.value.resource_record_value]
  ttl             = 60
  allow_overwrite = true
}

resource "aws_acm_certificate_validation" "app" {
  certificate_arn         = aws_acm_certificate.app.arn
  validation_record_fqdns = [for r in aws_route53_record.app_validation : r.fqdn]
}

resource "aws_acm_certificate_validation" "preview" {
  certificate_arn         = aws_acm_certificate.preview.arn
  validation_record_fqdns = [for r in aws_route53_record.preview_validation : r.fqdn]
}

output "app_certificate_arn" { value = aws_acm_certificate_validation.app.certificate_arn }
output "preview_certificate_arn" { value = aws_acm_certificate_validation.preview.certificate_arn }
