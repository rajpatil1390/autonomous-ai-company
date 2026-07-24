resource "aws_kms_key" "eks" {
  description             = "EKS Kubernetes Secret envelope encryption for ${local.name}"
  deletion_window_in_days = 30
  enable_key_rotation     = true
}

resource "aws_kms_alias" "eks" {
  name          = "alias/${local.name}-eks"
  target_key_id = aws_kms_key.eks.key_id
}

resource "aws_kms_key" "rds" {
  description             = "RDS storage encryption for ${local.name}"
  deletion_window_in_days = 30
  enable_key_rotation     = true
}

resource "aws_kms_alias" "rds" {
  name          = "alias/${local.name}-rds"
  target_key_id = aws_kms_key.rds.key_id
}

