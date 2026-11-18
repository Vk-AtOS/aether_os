# Alarms that mirror deploy/observability/alerts.yml where CloudWatch has the metric. Notifications go to one SNS topic;
# the owner subscribes the on-call address/webhook (not in this repository).
terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.60" }
  }
}

variable "name" { type = string }
variable "app_alb_arn_suffix" { type = string }
variable "preview_alb_arn_suffix" { type = string }
variable "api_target_group_arn_suffix" { type = string }
variable "dlq_name" { type = string }
variable "queue_name" { type = string }
variable "db_identifier" { type = string }
variable "kms_key_arn" { type = string }

resource "aws_sns_topic" "alerts" {
  name              = "${var.name}-alerts"
  kms_master_key_id = var.kms_key_arn
}

locals {
  alarms = {
    alb-5xx = {
      ns   = "AWS/ApplicationELB", metric = "HTTPCode_Target_5XX_Count", stat = "Sum", threshold = 20, op = "GreaterThanThreshold",
      dims = { LoadBalancer = var.app_alb_arn_suffix }, desc = "API returning 5xx (error spike)"
    }
    api-unhealthy = {
      ns   = "AWS/ApplicationELB", metric = "UnHealthyHostCount", stat = "Maximum", threshold = 0, op = "GreaterThanThreshold",
      dims = { LoadBalancer = var.app_alb_arn_suffix, TargetGroup = var.api_target_group_arn_suffix }, desc = "an API task is failing /healthz (service down)"
    }
    dlq-not-empty = {
      ns   = "AWS/SQS", metric = "ApproximateNumberOfMessagesVisible", stat = "Maximum", threshold = 0, op = "GreaterThanThreshold",
      dims = { QueueName = var.dlq_name }, desc = "dead-lettered pipeline jobs"
    }
    queue-old = {
      ns   = "AWS/SQS", metric = "ApproximateAgeOfOldestMessage", stat = "Maximum", threshold = 1800, op = "GreaterThanThreshold",
      dims = { QueueName = var.queue_name }, desc = "pipeline jobs waiting more than 30 minutes"
    }
    db-cpu = {
      ns   = "AWS/RDS", metric = "CPUUtilization", stat = "Average", threshold = 85, op = "GreaterThanThreshold",
      dims = { DBInstanceIdentifier = var.db_identifier }, desc = "Postgres CPU high"
    }
    db-storage = {
      ns   = "AWS/RDS", metric = "FreeStorageSpace", stat = "Minimum", threshold = 10737418240, op = "LessThanThreshold",
      dims = { DBInstanceIdentifier = var.db_identifier }, desc = "Postgres has less than 10 GB free"
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "this" {
  for_each            = local.alarms
  alarm_name          = "${var.name}-${each.key}"
  alarm_description   = each.value.desc
  namespace           = each.value.ns
  metric_name         = each.value.metric
  statistic           = each.value.stat
  dimensions          = each.value.dims
  comparison_operator = each.value.op
  threshold           = each.value.threshold
  period              = 300
  evaluation_periods  = 2
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
}

output "alerts_topic_arn" { value = aws_sns_topic.alerts.arn }
