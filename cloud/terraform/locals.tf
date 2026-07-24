data "aws_availability_zones" "available" {
  state = "available"
}

data "aws_caller_identity" "current" {}

data "aws_partition" "current" {}

locals {
  name               = "${var.project_name}-${var.environment}"
  availability_zones = slice(data.aws_availability_zones.available.names, 0, var.availability_zone_count)
  public_subnets      = slice(var.public_subnet_cidrs, 0, var.availability_zone_count)
  private_subnets     = slice(var.private_subnet_cidrs, 0, var.availability_zone_count)
  nat_gateway_count   = var.single_nat_gateway ? 1 : var.availability_zone_count
  oidc_provider       = replace(aws_eks_cluster.main.identity[0].oidc[0].issuer, "https://", "")

  common_tags = merge(
    {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "Terraform"
      Repository  = "Autonomous-AI-Company"
    },
    var.additional_tags,
  )
}

