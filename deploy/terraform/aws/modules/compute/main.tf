# Compute: ECS Fargate cluster with the AetherOS API, preview server, Velaris API and Velaris public app; two ALBs;
# a shared EFS for run state; and an isolated Auto Scaling group of Docker hosts for generated-app sandboxes.
terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.60" }
  }
}

data "aws_caller_identity" "me" {}

locals {
  secret_ref = { for k, arn in var.secret_arns : k => arn }
  # the key files the apps expect as paths are written from secrets into /keys at start (read-only root, tmp volume)
  write_keys = "umask 077; mkdir -p /keys; "
}

resource "aws_ecs_cluster" "this" {
  name = var.name
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_service_discovery_private_dns_namespace" "this" {
  name = "${var.name}.internal"
  vpc  = var.vpc_id
}

resource "aws_cloudwatch_log_group" "svc" {
  for_each          = toset(["api", "preview", "velaris-api", "velaris-public"])
  name              = "/${var.name}/${each.key}"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.kms_key_arn
}

# ── Security groups ─────────────────────────────────────────────────────────
resource "aws_security_group" "alb_app" {
  name        = "${var.name}-alb-app"
  description = "Public HTTPS to the app load balancer"
  vpc_id      = var.vpc_id
  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "alb_preview" {
  name        = "${var.name}-alb-preview"
  description = "Public HTTPS to the preview load balancer"
  vpc_id      = var.vpc_id
  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "api" {
  name        = "${var.name}-api"
  description = "AetherOS API tasks"
  vpc_id      = var.vpc_id
  ingress {
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb_app.id]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "preview" {
  name        = "${var.name}-preview"
  description = "Preview server tasks"
  vpc_id      = var.vpc_id
  ingress {
    from_port       = 8100
    to_port         = 8100
    protocol        = "tcp"
    security_groups = [aws_security_group.alb_preview.id]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = [data.aws_vpc.this.cidr_block]
  }
}

resource "aws_security_group" "velaris" {
  name        = "${var.name}-velaris"
  description = "Velaris: the API port only from the AetherOS tasks, the public port only from the load balancer"
  vpc_id      = var.vpc_id
  ingress {
    from_port       = 8730
    to_port         = 8730
    protocol        = "tcp"
    security_groups = [aws_security_group.api.id]
  }
  ingress {
    from_port       = 8731
    to_port         = 8731
    protocol        = "tcp"
    security_groups = [aws_security_group.alb_app.id]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "sandbox" {
  name        = "${var.name}-sandbox"
  description = "Sandbox Docker hosts: Docker TLS from the API tasks, published app ports from the preview tasks, no egress"
  vpc_id      = var.vpc_id
  ingress {
    from_port       = 2376
    to_port         = 2376
    protocol        = "tcp"
    security_groups = [aws_security_group.api.id]
  }
  ingress {
    from_port       = 20000
    to_port         = 29999
    protocol        = "tcp"
    security_groups = [aws_security_group.preview.id]
  }
  egress {
    description = "VPC only (EFS, endpoints); no internet route exists either"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = [data.aws_vpc.this.cidr_block]
  }
}

data "aws_vpc" "this" { id = var.vpc_id }

# ── Shared run state (EFS) ──────────────────────────────────────────────────
resource "aws_security_group" "efs" {
  name        = "${var.name}-efs"
  description = "NFS from the API, preview and sandbox hosts"
  vpc_id      = var.vpc_id
  ingress {
    from_port       = 2049
    to_port         = 2049
    protocol        = "tcp"
    security_groups = [aws_security_group.api.id, aws_security_group.preview.id, aws_security_group.sandbox.id, aws_security_group.velaris.id]
  }
}

resource "aws_efs_file_system" "state" {
  encrypted  = true
  kms_key_id = var.kms_key_arn
  tags       = { Name = "${var.name}-state" }
  lifecycle_policy { transition_to_ia = "AFTER_30_DAYS" }
}

resource "aws_efs_backup_policy" "state" {
  file_system_id = aws_efs_file_system.state.id
  backup_policy { status = "ENABLED" }
}

resource "aws_efs_mount_target" "state" {
  count           = length(var.app_subnet_ids)
  file_system_id  = aws_efs_file_system.state.id
  subnet_id       = var.app_subnet_ids[count.index]
  security_groups = [aws_security_group.efs.id]
}

# Sandbox hosts mount the same file system from their own subnets.
resource "aws_efs_mount_target" "sandbox" {
  count           = length(var.sandbox_subnet_ids)
  file_system_id  = aws_efs_file_system.state.id
  subnet_id       = var.sandbox_subnet_ids[count.index]
  security_groups = [aws_security_group.efs.id]
}

resource "aws_efs_access_point" "aether" {
  file_system_id = aws_efs_file_system.state.id
  posix_user {
    uid = 999
    gid = 999
  }
  root_directory {
    path = "/aether"
    creation_info {
      owner_uid   = 999
      owner_gid   = 999
      permissions = "0750"
    }
  }
}

resource "aws_efs_access_point" "velaris" {
  file_system_id = aws_efs_file_system.state.id
  posix_user {
    uid = 10001
    gid = 10001
  }
  root_directory {
    path = "/velaris"
    creation_info {
      owner_uid   = 10001
      owner_gid   = 10001
      permissions = "0700"
    }
  }
}

# ── IAM ─────────────────────────────────────────────────────────────────────
data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "execution" {
  name               = "${var.name}-ecs-exec"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "execution_secrets" {
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = values(var.secret_arns)
  }
  statement {
    actions   = ["kms:Decrypt"]
    resources = [var.kms_key_arn]
  }
}

resource "aws_iam_role_policy" "execution_secrets" {
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.execution_secrets.json
}

resource "aws_iam_role" "api" {
  name               = "${var.name}-api-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

data "aws_iam_policy_document" "api" {
  statement {
    actions   = ["sqs:SendMessage", "sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:ChangeMessageVisibility", "sqs:GetQueueAttributes"]
    resources = [var.queue_arn, var.dlq_arn]
  }
  statement {
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"]
    resources = [var.artifacts_bucket_arn, "${var.artifacts_bucket_arn}/*"]
  }
  statement {
    actions   = ["kms:Decrypt", "kms:GenerateDataKey"]
    resources = [var.kms_key_arn]
  }
}

resource "aws_iam_role_policy" "api" {
  role   = aws_iam_role.api.id
  policy = data.aws_iam_policy_document.api.json
}

# Preview and Velaris tasks get a role with no permissions at all.
resource "aws_iam_role" "bare" {
  name               = "${var.name}-bare-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

# ── Load balancers ──────────────────────────────────────────────────────────
resource "aws_lb" "app" {
  name                       = "${var.name}-app"
  load_balancer_type         = "application"
  subnets                    = var.public_subnet_ids
  security_groups            = [aws_security_group.alb_app.id]
  drop_invalid_header_fields = true
  idle_timeout               = 120
}

resource "aws_lb" "preview" {
  name                       = "${var.name}-preview"
  load_balancer_type         = "application"
  subnets                    = var.public_subnet_ids
  security_groups            = [aws_security_group.alb_preview.id]
  drop_invalid_header_fields = true
  idle_timeout               = 120
}

resource "aws_wafv2_web_acl_association" "this" {
  for_each     = var.waf_acl_arn == "" ? {} : { app = aws_lb.app.arn, preview = aws_lb.preview.arn }
  resource_arn = each.value
  web_acl_arn  = var.waf_acl_arn
}

resource "aws_lb_target_group" "tg" {
  for_each             = { api = 8000, preview = 8100, velaris-public = 8731 }
  name                 = "${var.name}-${each.key}"
  port                 = each.value
  protocol             = "HTTP"
  target_type          = "ip"
  vpc_id               = var.vpc_id
  deregistration_delay = 30
  health_check {
    path                = each.key == "api" ? "/healthz" : each.key == "preview" ? "/__preview/health" : "/health"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    interval            = 15
    timeout             = 5
    matcher             = "200"
  }
}

resource "aws_lb_listener" "app" {
  load_balancer_arn = aws_lb.app.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.app_certificate_arn
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.tg["api"].arn
  }
}

# Velaris public app on its own host name; everything else is the AetherOS API.
resource "aws_lb_listener_rule" "velaris_public" {
  listener_arn = aws_lb_listener.app.arn
  priority     = 10
  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.tg["velaris-public"].arn
  }
  condition {
    host_header { values = ["velaris.${var.app_domain}"] }
  }
}

resource "aws_lb_listener" "preview" {
  load_balancer_arn = aws_lb.preview.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.preview_certificate_arn
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.tg["preview"].arn
  }
}

# Plain HTTP only redirects.
resource "aws_lb_listener" "redirect" {
  for_each          = { app = aws_lb.app.arn, preview = aws_lb.preview.arn }
  load_balancer_arn = each.value
  port              = 80
  protocol          = "HTTP"
  default_action {
    type = "redirect"
    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}
