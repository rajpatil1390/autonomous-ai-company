resource "aws_prometheus_workspace" "main" {
  alias = local.name
}

resource "aws_iam_role" "grafana" {
  name = "${local.name}-grafana"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "grafana.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_policy" "grafana_prometheus" {
  name = "${local.name}-grafana-prometheus"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "aps:GetLabels",
        "aps:GetMetricMetadata",
        "aps:GetSeries",
        "aps:QueryMetrics",
      ]
      Resource = aws_prometheus_workspace.main.arn
    }]
  })
}

resource "aws_iam_role_policy_attachment" "grafana_prometheus" {
  role       = aws_iam_role.grafana.name
  policy_arn = aws_iam_policy.grafana_prometheus.arn
}

resource "aws_grafana_workspace" "main" {
  name                     = local.name
  account_access_type      = "CURRENT_ACCOUNT"
  authentication_providers = ["AWS_SSO"]
  permission_type          = "SERVICE_MANAGED"
  role_arn                 = aws_iam_role.grafana.arn
  data_sources             = ["PROMETHEUS"]
}

resource "aws_cloudwatch_log_group" "otel_collector" {
  name              = "/${var.project_name}/${var.environment}/otel-collector"
  retention_in_days = 30

  tags = {
    OTLPPlaceholder = var.otlp_endpoint
  }
}

