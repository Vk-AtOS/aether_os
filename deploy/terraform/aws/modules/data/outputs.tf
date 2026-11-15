output "kms_key_arn" { value = aws_kms_key.data.arn }
output "db_address" { value = aws_db_instance.this.address }
output "queue_url" { value = aws_sqs_queue.pipeline.url }
output "queue_arn" { value = aws_sqs_queue.pipeline.arn }
output "dlq_url" { value = aws_sqs_queue.dlq.url }
output "dlq_arn" { value = aws_sqs_queue.dlq.arn }
output "artifacts_bucket" { value = aws_s3_bucket.artifacts.id }
output "artifacts_bucket_arn" { value = aws_s3_bucket.artifacts.arn }
output "backups_bucket" { value = aws_s3_bucket.backups.id }
output "secret_arns" {
  value = merge(
    { for k, s in aws_secretsmanager_secret.generated : k => s.arn },
    { for k, s in aws_secretsmanager_secret.owner : k => s.arn },
  )
}
output "queue_name" { value = aws_sqs_queue.pipeline.name }
output "dlq_name" { value = aws_sqs_queue.dlq.name }
output "db_identifier" { value = aws_db_instance.this.identifier }
