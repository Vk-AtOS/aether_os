# ECS services. Images are pinned by digest by the caller; no secret value appears here, only Secrets Manager references.

locals {
  sec = { for k, arn in var.secret_arns : k => { name = k, valueFrom = arn } }

  services = {
    api = {
      image   = var.api_image
      port    = 8000
      cpu     = var.api_cpu
      memory  = var.api_memory
      count   = var.api_count
      sg      = aws_security_group.api.id
      role    = aws_iam_role.api.arn
      efs_ap  = aws_efs_access_point.aether.id
      efs_dir = "/home/aether/.aether_os"
      command = ["uvicorn", "aether_os.gateway.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
      env = {
        ENVIRONMENT             = "production"
        REQUIRE_REDIS           = "true"
        CORS_ORIGINS            = "https://${var.app_domain}"
        FRONTEND_URL            = "https://${var.app_domain}/dashboard"
        AETHER_DASHBOARD_ORIGIN = "https://${var.app_domain}"
        AETHER_PREVIEW_ORIGIN   = "https://${var.preview_domain}"
        AETHER_SANDBOX          = "docker"
        AETHER_SANDBOX_IMAGE    = var.sandbox_image
        SQS_QUEUE_URL           = var.queue_url
        SQS_DLQ_URL             = var.dlq_url
        AWS_REGION              = var.region
        AWS_DEFAULT_REGION      = var.region
        S3_BUCKET               = var.artifacts_bucket
        PIPELINE_MAX_CONCURRENT = "2"
        VELARIS_API_URL         = "http://velaris-api.${var.name}.internal:8730"
      }
      secrets  = [for k in ["DATABASE_URL", "REDIS_URL", "AETHER_SECRET_KEY", "AETHER_FIELD_KEY", "AETHER_ONE_ZT_SECRET", "AETHER_PREVIEW_SECRET", "AETHER_ADMIN_PASS", "ANTHROPIC_API_KEY", "VELARIS_API_SECRET", "VELARIS_IDENTITY_PRIVATE_KEY_PEM"] : local.sec[k]]
      lb_tg    = "api"
      health   = "curl -fsS http://localhost:8000/healthz || exit 1"
      discover = false
    }
    preview = {
      image   = var.api_image
      port    = 8100
      cpu     = 512
      memory  = 1024
      count   = 2
      sg      = aws_security_group.preview.id
      role    = aws_iam_role.bare.arn
      efs_ap  = aws_efs_access_point.aether.id
      efs_dir = "/home/aether/.aether_os"
      command = ["uvicorn", "aether_os.gateway.preview_server:create_preview_app", "--factory", "--host", "0.0.0.0", "--port", "8100", "--workers", "1"]
      env = {
        ENVIRONMENT             = "production"
        AETHER_PREVIEW_ORIGIN   = "https://${var.preview_domain}"
        AETHER_DASHBOARD_ORIGIN = "https://${var.app_domain}"
        FRONTEND_URL            = "https://${var.app_domain}/dashboard"
      }
      secrets  = [local.sec["AETHER_PREVIEW_SECRET"]]
      lb_tg    = "preview"
      health   = "curl -fsS http://localhost:8100/__preview/health || exit 1"
      discover = false
    }
    velaris-api = {
      image   = var.velaris_image
      port    = 8730
      cpu     = 512
      memory  = 1024
      count   = 1 # one worker per deployment: replay cache and rate counters are per process
      sg      = aws_security_group.velaris.id
      role    = aws_iam_role.bare.arn
      efs_ap  = aws_efs_access_point.velaris.id
      efs_dir = "/data"
      command = ["python", "-m", "velaris.api"]
      env = {
        VELARIS_DATA     = "/data"
        VELARIS_ORG      = var.velaris_org
        VELARIS_API_HOST = "0.0.0.0"
      }
      secrets  = [for k in ["VELARIS_API_SECRET", "VELARIS_IDENTITY_PUBLIC_KEY_PEM", "VELARIS_DATA_KEY", "VELARIS_PRIME_API_KEY"] : local.sec[k]]
      lb_tg    = ""
      health   = "python /app/healthcheck.py 8730 /health || exit 1"
      discover = true
    }
    velaris-public = {
      image   = var.velaris_image
      port    = 8731
      cpu     = 256
      memory  = 512
      count   = 1
      sg      = aws_security_group.velaris.id
      role    = aws_iam_role.bare.arn
      efs_ap  = aws_efs_access_point.velaris.id
      efs_dir = "/data"
      command = ["python", "-m", "velaris.api.public"]
      env = {
        VELARIS_DATA               = "/data"
        VELARIS_ORG                = var.velaris_org
        VELARIS_PUBLIC_HOST        = "0.0.0.0"
        VELARIS_PUBLIC_TRUST_PROXY = "1"
      }
      secrets  = [local.sec["VELARIS_DATA_KEY"]]
      lb_tg    = "velaris-public"
      health   = "python /app/healthcheck.py 8731 || exit 1"
      discover = false
    }
  }
}

resource "aws_ecs_task_definition" "svc" {
  for_each                 = local.services
  family                   = "${var.name}-${each.key}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = each.value.cpu
  memory                   = each.value.memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = each.value.role

  volume {
    name = "state"
    efs_volume_configuration {
      file_system_id     = aws_efs_file_system.state.id
      transit_encryption = "ENABLED"
      authorization_config {
        access_point_id = each.value.efs_ap
        iam             = "DISABLED"
      }
    }
  }
  volume { name = "tmp" }

  container_definitions = jsonencode([{
    name                   = each.key
    image                  = each.value.image
    essential              = true
    command                = each.value.command
    readonlyRootFilesystem = true
    stopTimeout            = 60 # graceful shutdown: uvicorn drains in-flight requests
    portMappings           = [{ containerPort = each.value.port, protocol = "tcp" }]
    environment            = [for k, v in each.value.env : { name = k, value = v }]
    secrets                = each.value.secrets
    mountPoints = [
      { sourceVolume = "state", containerPath = each.value.efs_dir, readOnly = each.key == "preview" },
      { sourceVolume = "tmp", containerPath = "/tmp", readOnly = false },
    ]
    healthCheck = {
      command     = ["CMD-SHELL", each.value.health]
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 60
    }
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.svc[each.key].name
        awslogs-region        = var.region
        awslogs-stream-prefix = each.key
      }
    }
  }])
}

resource "aws_service_discovery_service" "velaris_api" {
  name = "velaris-api"
  dns_config {
    namespace_id = aws_service_discovery_private_dns_namespace.this.id
    dns_records {
      ttl  = 10
      type = "A"
    }
  }
  health_check_custom_config { failure_threshold = 1 }
}

resource "aws_ecs_service" "svc" {
  for_each                           = local.services
  name                               = each.key
  cluster                            = aws_ecs_cluster.this.id
  task_definition                    = aws_ecs_task_definition.svc[each.key].arn
  desired_count                      = each.value.count
  launch_type                        = "FARGATE"
  deployment_minimum_healthy_percent = each.value.count > 1 ? 50 : 100
  deployment_maximum_percent         = 200
  health_check_grace_period_seconds  = each.value.lb_tg == "" ? null : 60
  enable_execute_command             = false

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = var.app_subnet_ids
    security_groups  = [each.value.sg]
    assign_public_ip = false
  }

  dynamic "load_balancer" {
    for_each = each.value.lb_tg == "" ? [] : [each.value.lb_tg]
    content {
      target_group_arn = aws_lb_target_group.tg[load_balancer.value].arn
      container_name   = each.key
      container_port   = each.value.port
    }
  }

  dynamic "service_registries" {
    for_each = each.value.discover ? [1] : []
    content {
      registry_arn = aws_service_discovery_service.velaris_api.arn
    }
  }

  depends_on = [aws_lb_listener.app, aws_lb_listener.preview, aws_efs_mount_target.state]
}

# API autoscaling on CPU. Queue-depth scaling of pipeline capacity is left to the owner once real load is known.
resource "aws_appautoscaling_target" "api" {
  max_capacity       = var.api_count * 4
  min_capacity       = var.api_count
  resource_id        = "service/${aws_ecs_cluster.this.name}/${aws_ecs_service.svc["api"].name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "api_cpu" {
  name               = "${var.name}-api-cpu"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.api.resource_id
  scalable_dimension = aws_appautoscaling_target.api.scalable_dimension
  service_namespace  = aws_appautoscaling_target.api.service_namespace
  target_tracking_scaling_policy_configuration {
    target_value = 60
    predefined_metric_specification { predefined_metric_type = "ECSServiceAverageCPUUtilization" }
  }
}
