output "cluster_name" {
  description = "Amazon EKS cluster name used by kubectl and Helm."
  value       = aws_eks_cluster.main.name
}

output "region" {
  description = "AWS region containing the production infrastructure."
  value       = var.aws_region
}

output "ecr_repository_url" {
  description = "Repository URL used to publish the application image."
  value       = aws_ecr_repository.application.repository_url
}

output "rds_endpoint" {
  description = "Private PostgreSQL endpoint; no database password is exposed."
  value       = aws_db_instance.audit.address
}

output "secret_arns" {
  description = "Secrets Manager metadata ARNs consumed through External Secrets or CSI."
  value = {
    anthropic_api_key = aws_secretsmanager_secret.anthropic_api_key.arn
    jwt_secret_key    = aws_secretsmanager_secret.jwt_secret_key.arn
    postgres_master   = aws_db_instance.audit.master_user_secret[0].secret_arn
  }
}

output "prometheus_workspace_endpoint" {
  description = "Amazon Managed Service for Prometheus remote-write endpoint."
  value       = aws_prometheus_workspace.main.prometheus_endpoint
}

output "grafana_workspace_endpoint" {
  description = "Amazon Managed Grafana workspace endpoint."
  value       = aws_grafana_workspace.main.endpoint
}

output "otlp_endpoint" {
  description = "Configured placeholder for a future OTLP collector endpoint."
  value       = var.otlp_endpoint
}

