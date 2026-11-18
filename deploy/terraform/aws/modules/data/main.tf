# Data tier: Postgres (RDS), Redis (ElastiCache), queue + dead-letter queue (SQS), object store (S3), secrets (Secrets Manager).
terraform {
  required_version = ">= 1.6"
  required_providers {
    aws    = { source = "hashicorp/aws", version = "~> 5.60" }
    random = { source = "hashicorp/random", version = "~> 3.6" }
  }
}

resource "aws_kms_key" "data" {
  description             = "${var.name} data at rest"
  enable_key_rotation     = true
  deletion_window_in_days = 30
}

# ── Postgres ────────────────────────────────────────────────────────────────
resource "aws_security_group" "db" {
  name        = "${var.name}-db"
  description = "Postgres from the application tier only"
  vpc_id      = var.vpc_id
}

resource "aws_security_group_rule" "db_in" {
  count                    = length(var.client_security_group_ids)
  type                     = "ingress"
  from_port                = 5432
  to_port                  = 5432
  protocol                 = "tcp"
  security_group_id        = aws_security_group.db.id
  source_security_group_id = var.client_security_group_ids[count.index]
}

resource "aws_db_subnet_group" "this" {
  name       = "${var.name}-db"
  subnet_ids = var.data_subnet_ids
}

resource "random_password" "db" {
  length  = 40
  special = false # goes into a URL
}

# The server refuses any connection that is not TLS. Clients (asyncpg, libpq) default to "prefer", so they
# negotiate TLS without a URL change; a client forced to plaintext is rejected instead of silently accepted.
resource "aws_db_parameter_group" "this" {
  name   = "${var.name}-pg15"
  family = "postgres15"

  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }
}

resource "aws_db_instance" "this" {
  identifier                   = "${var.name}-pg"
  parameter_group_name         = aws_db_parameter_group.this.name
  engine                       = "postgres"
  engine_version               = "15"
  instance_class               = var.db_instance_class
  allocated_storage            = var.db_allocated_gb
  max_allocated_storage        = var.db_allocated_gb * 4
  storage_type                 = "gp3"
  storage_encrypted            = true
  kms_key_id                   = aws_kms_key.data.arn
  db_name                      = "aether_os"
  username                     = "aether_user"
  password                     = random_password.db.result
  multi_az                     = var.db_multi_az
  db_subnet_group_name         = aws_db_subnet_group.this.name
  vpc_security_group_ids       = [aws_security_group.db.id]
  publicly_accessible          = false
  backup_retention_period      = var.db_backup_days
  backup_window                = "21:00-22:00" # 02:30-03:30 IST
  maintenance_window           = "sun:22:00-sun:23:00"
  auto_minor_version_upgrade   = true
  deletion_protection          = var.deletion_protection
  skip_final_snapshot          = !var.deletion_protection
  final_snapshot_identifier    = var.deletion_protection ? "${var.name}-pg-final" : null
  performance_insights_enabled = true
  copy_tags_to_snapshot        = true
}

# ── Redis ───────────────────────────────────────────────────────────────────
resource "aws_security_group" "redis" {
  name        = "${var.name}-redis"
  description = "Redis from the application tier only"
  vpc_id      = var.vpc_id
}

resource "aws_security_group_rule" "redis_in" {
  count                    = length(var.client_security_group_ids)
  type                     = "ingress"
  from_port                = 6379
  to_port                  = 6379
  protocol                 = "tcp"
  security_group_id        = aws_security_group.redis.id
  source_security_group_id = var.client_security_group_ids[count.index]
}

resource "aws_elasticache_subnet_group" "this" {
  name       = "${var.name}-redis"
  subnet_ids = var.data_subnet_ids
}

# noeviction: revocation and rate-limit keys must never be evicted (decision D5).
resource "aws_elasticache_parameter_group" "this" {
  name   = "${var.name}-redis7-noeviction"
  family = "redis7"
  parameter {
    name  = "maxmemory-policy"
    value = "noeviction"
  }
}

resource "random_password" "redis" {
  length  = 40
  special = false
}

resource "aws_elasticache_replication_group" "this" {
  replication_group_id       = "${var.name}-redis"
  description                = "AetherOS cache and security counters"
  engine                     = "redis"
  engine_version             = "7.1"
  node_type                  = var.redis_node_type
  num_cache_clusters         = var.db_multi_az ? 2 : 1
  automatic_failover_enabled = var.db_multi_az
  multi_az_enabled           = var.db_multi_az
  parameter_group_name       = aws_elasticache_parameter_group.this.name
  subnet_group_name          = aws_elasticache_subnet_group.this.name
  security_group_ids         = [aws_security_group.redis.id]
  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
  auth_token                 = random_password.redis.result
  kms_key_id                 = aws_kms_key.data.arn
  snapshot_retention_limit   = 3
}

# ── Queue ───────────────────────────────────────────────────────────────────
resource "aws_sqs_queue" "dlq" {
  name                      = "${var.name}-pipeline-dlq"
  message_retention_seconds = 1209600
  kms_master_key_id         = aws_kms_key.data.arn
}

resource "aws_sqs_queue" "pipeline" {
  name                       = "${var.name}-pipeline"
  visibility_timeout_seconds = 3600 # the consumer extends it while a run is alive (core/queue/pipeline_consumer.py)
  message_retention_seconds  = 345600
  kms_master_key_id          = aws_kms_key.data.arn
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = 5
  })
}

# ── Object storage ──────────────────────────────────────────────────────────
resource "aws_s3_bucket" "artifacts" {
  bucket_prefix = "${var.name}-artifacts-"
}

resource "aws_s3_bucket" "backups" {
  bucket_prefix = "${var.name}-backups-"
  # Ledger checkpoints and dumps: object lock needs the flag at creation. Prefer a second AWS account for this bucket.
  object_lock_enabled = true
}

resource "aws_s3_bucket_versioning" "this" {
  for_each = { artifacts = aws_s3_bucket.artifacts.id, backups = aws_s3_bucket.backups.id }
  bucket   = each.value
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  for_each = { artifacts = aws_s3_bucket.artifacts.id, backups = aws_s3_bucket.backups.id }
  bucket   = each.value
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.data.arn
    }
  }
}

resource "aws_s3_bucket_public_access_block" "this" {
  for_each                = { artifacts = aws_s3_bucket.artifacts.id, backups = aws_s3_bucket.backups.id }
  bucket                  = each.value
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_object_lock_configuration" "backups" {
  bucket = aws_s3_bucket.backups.id
  rule {
    default_retention {
      mode = "COMPLIANCE"
      days = 30
    }
  }
  depends_on = [aws_s3_bucket_versioning.this]
}

resource "aws_s3_bucket_lifecycle_configuration" "backups" {
  bucket = aws_s3_bucket.backups.id
  rule {
    id     = "expire-old-versions"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration { noncurrent_days = 90 }
    abort_incomplete_multipart_upload { days_after_initiation = 7 }
  }
  depends_on = [aws_s3_bucket_versioning.this]
}

# ── Secrets ─────────────────────────────────────────────────────────────────
# Generated values are written here; secrets that only the owner can supply are created EMPTY and filled by hand
# (aws secretsmanager put-secret-value). No secret value is in this repository.
locals {
  generated = {
    DATABASE_URL = "postgresql://aether_user:${random_password.db.result}@${aws_db_instance.this.address}:5432/aether_os"
    REDIS_URL    = "rediss://:${random_password.redis.result}@${aws_elasticache_replication_group.this.primary_endpoint_address}:6379/0"
  }
  owner_supplied = [
    "AETHER_SECRET_KEY", "AETHER_FIELD_KEY", "AETHER_ONE_ZT_SECRET", "AETHER_PREVIEW_SECRET", "AETHER_ADMIN_PASS",
    "ANTHROPIC_API_KEY", "VELARIS_API_SECRET", "VELARIS_IDENTITY_PRIVATE_KEY_PEM", "VELARIS_IDENTITY_PUBLIC_KEY_PEM",
    "VELARIS_PRIME_API_KEY", "VELARIS_DATA_KEY",
  ]
}

resource "aws_secretsmanager_secret" "generated" {
  for_each   = toset(keys(local.generated))
  name       = "${var.name}/${each.key}"
  kms_key_id = aws_kms_key.data.arn
}

resource "aws_secretsmanager_secret_version" "generated" {
  for_each      = toset(keys(local.generated))
  secret_id     = aws_secretsmanager_secret.generated[each.key].id
  secret_string = local.generated[each.key]
}

resource "aws_secretsmanager_secret" "owner" {
  for_each   = toset(local.owner_supplied)
  name       = "${var.name}/${each.key}"
  kms_key_id = aws_kms_key.data.arn
}
