output "app_alb_dns" { value = aws_lb.app.dns_name }
output "app_alb_zone_id" { value = aws_lb.app.zone_id }
output "preview_alb_dns" { value = aws_lb.preview.dns_name }
output "preview_alb_zone_id" { value = aws_lb.preview.zone_id }
output "api_security_group_id" { value = aws_security_group.api.id }
output "velaris_security_group_id" { value = aws_security_group.velaris.id }
output "cluster_name" { value = aws_ecs_cluster.this.name }
output "log_group_names" { value = { for k, g in aws_cloudwatch_log_group.svc : k => g.name } }
output "app_alb_arn_suffix" { value = aws_lb.app.arn_suffix }
output "preview_alb_arn_suffix" { value = aws_lb.preview.arn_suffix }
output "api_target_group_arn_suffix" { value = aws_lb_target_group.tg["api"].arn_suffix }
