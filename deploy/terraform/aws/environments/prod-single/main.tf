# prod-single: the first production install (owner decision 22 Nov 2026): the proven testbed shape (one Docker host running
# the compose stack + RDS PostgreSQL + an off-site backup bucket) in Mumbai, reached on a fixed public IP (no domain yet).
# Differences from the testbed: Elastic IP, inbound 80/443 only, RDS with 7-day PITR, deletion protection and a final
# snapshot, backups bucket not force-destroyed. The multi-server reference stack (../staging) replaces it later.
# Admin access is SSM Session Manager only (no SSH). Never apply without owner approval.
terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.60" }
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = { Project = "aetheros", Environment = "production", ManagedBy = "terraform" }
  }
}

variable "region" {
  description = "Mumbai keeps customer data in India; the organization policy must allow ap-south-1 (KAN-48)"
  type        = string
  default     = "ap-south-1"
}
variable "name" {
  type    = string
  default = "aetheros-prod"
}
variable "instance_type" {
  # 2 vCPU / 8 GiB: the compose stack plus one sandbox build at a time. m7i-flex rather than t3.large because accounts on
  # the AWS free plan may only launch free-tier-eligible types (RunInstances: InvalidParameterCombination otherwise).
  type    = string
  default = "m7i-flex.large"
}
variable "budget_email" {
  description = "Where AWS sends the budget alerts. Empty: no budget is created"
  type        = string
  default     = ""
}
variable "budget_usd" {
  type    = number
  default = 200
}

data "aws_caller_identity" "current" {}

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
  filter {
    name   = "default-for-az"
    values = ["true"]
  }
}

data "aws_ssm_parameter" "al2023" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

# ── Host ─────────────────────────────────────────────────────────────────────
resource "aws_security_group" "host" {
  name        = "${var.name}-host"
  description = "Docker host: HTTP and HTTPS from anywhere (nginx), no SSH (SSM only)"
  vpc_id      = data.aws_vpc.default.id
  ingress {
    description = "nginx HTTP (redirects to HTTPS once a certificate is installed)"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  ingress {
    description = "nginx HTTPS"
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

data "aws_iam_policy_document" "ec2_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "host" {
  name               = "${var.name}-host"
  assume_role_policy = data.aws_iam_policy_document.ec2_trust.json
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.host.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

data "aws_iam_policy_document" "host" {
  # The host writes only under backups/ and can delete nothing: a compromised host cannot erase backups (the lifecycle rule
  # expires them) or replace the src/ archives it deploys from (those are uploaded by the operator, read-only here).
  statement {
    sid       = "BackupsWrite"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.backups.arn}/backups/*"]
  }
  statement {
    sid       = "BackupsAndSourceRead"
    actions   = ["s3:GetObject", "s3:ListBucket"]
    resources = [aws_s3_bucket.backups.arn, "${aws_s3_bucket.backups.arn}/*"]
  }
  statement {
    sid       = "DatabasePassword"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_db_instance.pg.master_user_secret[0].secret_arn]
  }
  statement {
    sid       = "AppSecrets"
    actions   = ["ssm:GetParameter", "ssm:GetParameters"]
    resources = ["arn:aws:ssm:${var.region}:${data.aws_caller_identity.current.account_id}:parameter/${var.name}/*"]
  }
  statement {
    sid       = "RestoreDrill"
    actions   = ["rds:DescribeDBInstances", "rds:DescribeDBSnapshots", "rds:CreateDBSnapshot"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "host" {
  name   = "${var.name}-host"
  role   = aws_iam_role.host.id
  policy = data.aws_iam_policy_document.host.json
}

resource "aws_iam_instance_profile" "host" {
  name = "${var.name}-host"
  role = aws_iam_role.host.name
}

resource "aws_instance" "host" {
  ami                    = data.aws_ssm_parameter.al2023.value
  instance_type          = var.instance_type
  subnet_id              = data.aws_subnets.default.ids[0]
  vpc_security_group_ids = [aws_security_group.host.id]
  iam_instance_profile   = aws_iam_instance_profile.host.name
  user_data              = file("${path.module}/host-userdata.sh")

  metadata_options {
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }
  root_block_device {
    volume_type = "gp3"
    volume_size = 60
    encrypted   = true
  }
  tags = { Name = "${var.name}-host" }

  lifecycle {
    ignore_changes = [ami]
  }
}

# A fixed address: users and the buyer reach the platform at this IP until a domain exists.
resource "aws_eip" "host" {
  domain   = "vpc"
  instance = aws_instance.host.id
  tags     = { Name = "${var.name}-ip" }
}

# ── PostgreSQL (pgvector is available on RDS PostgreSQL 15) ──────────────────
resource "aws_security_group" "db" {
  name        = "${var.name}-db"
  description = "PostgreSQL: only from the Docker host"
  vpc_id      = data.aws_vpc.default.id
  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.host.id]
  }
}

resource "aws_db_instance" "pg" {
  identifier                  = var.name
  engine                      = "postgres"
  engine_version              = "15"
  instance_class              = "db.t4g.small"
  allocated_storage           = 20
  storage_type                = "gp3"
  storage_encrypted           = true
  db_name                     = "aether_os"
  username                    = "aether_user"
  manage_master_user_password = true
  vpc_security_group_ids      = [aws_security_group.db.id]
  publicly_accessible         = false
  multi_az                    = false
  backup_retention_period     = 7
  skip_final_snapshot         = false
  final_snapshot_identifier   = "${var.name}-final"
  deletion_protection         = true
  apply_immediately           = true
}

# ── Off-site backups ─────────────────────────────────────────────────────────
resource "aws_s3_bucket" "backups" {
  bucket        = "${var.name}-backups-${data.aws_caller_identity.current.account_id}"
  force_destroy = false
}

resource "aws_s3_bucket_public_access_block" "backups" {
  bucket                  = aws_s3_bucket.backups.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "backups" {
  bucket = aws_s3_bucket.backups.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "backups" {
  bucket = aws_s3_bucket.backups.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "backups" {
  bucket = aws_s3_bucket.backups.id
  rule {
    id     = "expire"
    status = "Enabled"
    filter {}
    expiration {
      days = 30
    }
    noncurrent_version_expiration {
      noncurrent_days = 7
    }
  }
}

# ── Spending alert ───────────────────────────────────────────────────────────
resource "aws_budgets_budget" "monthly" {
  count        = var.budget_email == "" ? 0 : 1
  name         = "${var.name}-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  dynamic "notification" {
    for_each = [50, 80, 100]
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value
      threshold_type             = "PERCENTAGE"
      notification_type          = "ACTUAL"
      subscriber_email_addresses = [var.budget_email]
    }
  }
}

output "host_instance_id" { value = aws_instance.host.id }
output "public_ip" { value = aws_eip.host.public_ip }
output "connect" { value = "aws ssm start-session --region ${var.region} --target ${aws_instance.host.id}" }
output "db_endpoint" { value = aws_db_instance.pg.address }
output "db_password_secret_arn" { value = aws_db_instance.pg.master_user_secret[0].secret_arn }
output "backups_bucket" { value = aws_s3_bucket.backups.bucket }
