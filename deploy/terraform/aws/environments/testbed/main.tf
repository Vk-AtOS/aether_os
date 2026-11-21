# testbed: one throwaway Docker host + a small PostgreSQL + a backup bucket, for running the tests that need real
# infrastructure (compose up, kill test, restore drill, sandbox images, pgvector, Velaris smoke). Not production and not the
# reference stack (that is ../staging). No domain, no load balancer, no inbound port: reach the host with SSM Session Manager.
# Local state on purpose (one operator, destroyed after the run). Never apply without owner approval.
terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.60" }
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = { Project = "aetheros", Environment = "testbed", ManagedBy = "terraform" }
  }
}

variable "region" {
  description = "The owner's test account only allows ap-southeast-2 (organization policy), see KAN-48"
  type        = string
  default     = "ap-southeast-2"
}
variable "name" {
  type    = string
  default = "aetheros-testbed"
}
variable "instance_type" {
  description = "2 vCPU / 8 GiB: the compose stack plus one sandbox build at a time"
  type        = string
  default     = "t3.large"
}
variable "budget_email" {
  description = "Where AWS sends the budget alerts. Empty: no budget is created"
  type        = string
  default     = ""
}
variable "budget_usd" {
  type    = number
  default = 50
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
  description = "Docker host: no inbound rule (SSM only), outbound for packages, images and git"
  vpc_id      = data.aws_vpc.default.id
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
  statement {
    sid       = "Backups"
    actions   = ["s3:PutObject", "s3:GetObject", "s3:ListBucket", "s3:DeleteObject"]
    resources = [aws_s3_bucket.backups.arn, "${aws_s3_bucket.backups.arn}/*"]
  }
  statement {
    sid       = "DatabasePassword"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_db_instance.pg.master_user_secret[0].secret_arn]
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
    volume_size = 40
    encrypted   = true
  }
  tags = { Name = "${var.name}-host" }

  lifecycle {
    ignore_changes = [ami]
  }
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
  instance_class              = "db.t4g.micro"
  allocated_storage           = 20
  storage_type                = "gp3"
  storage_encrypted           = true
  db_name                     = "aether_os"
  username                    = "aether_user"
  manage_master_user_password = true
  vpc_security_group_ids      = [aws_security_group.db.id]
  publicly_accessible         = false
  multi_az                    = false
  backup_retention_period     = 1
  skip_final_snapshot         = true
  deletion_protection         = false
  apply_immediately           = true
}

# ── Off-site backups ─────────────────────────────────────────────────────────
resource "aws_s3_bucket" "backups" {
  bucket        = "${var.name}-backups-${data.aws_caller_identity.current.account_id}"
  force_destroy = true
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
output "connect" { value = "aws ssm start-session --region ${var.region} --target ${aws_instance.host.id}" }
output "db_endpoint" { value = aws_db_instance.pg.address }
output "db_password_secret_arn" { value = aws_db_instance.pg.master_user_secret[0].secret_arn }
output "backups_bucket" { value = aws_s3_bucket.backups.bucket }
