resource "aws_db_subnet_group" "audit" {
  name       = "${local.name}-audit"
  subnet_ids = [for subnet in aws_subnet.private : subnet.id]

  tags = {
    Name = "${local.name}-audit"
  }
}

resource "aws_security_group" "rds" {
  name_prefix = "${local.name}-rds-"
  description = "PostgreSQL access from the EKS control plane security group"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "PostgreSQL from EKS workloads"
    protocol        = "tcp"
    from_port       = 5432
    to_port         = 5432
    security_groups = [aws_eks_cluster.main.vpc_config[0].cluster_security_group_id]
  }

  egress {
    description = "Return traffic inside the VPC"
    protocol    = "-1"
    from_port   = 0
    to_port     = 0
    cidr_blocks = [var.vpc_cidr]
  }

  tags = {
    Name = "${local.name}-rds"
  }
}

resource "aws_iam_role" "rds_monitoring" {
  name = "${local.name}-rds-monitoring"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "monitoring.rds.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "rds_monitoring" {
  role       = aws_iam_role.rds_monitoring.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AmazonRDSEnhancedMonitoringRole"
}

resource "aws_db_instance" "audit" {
  identifier = "${local.name}-audit"

  engine         = "postgres"
  engine_version = var.rds_engine_version
  instance_class = var.rds_instance_class

  db_name  = "autonomous_ai_company"
  username = "database_admin"
  port     = 5432

  manage_master_user_password   = true
  master_user_secret_kms_key_id = aws_kms_key.rds.key_id

  allocated_storage     = var.rds_allocated_storage_gib
  max_allocated_storage = var.rds_max_allocated_storage_gib
  storage_type          = "gp3"
  storage_encrypted     = true
  kms_key_id            = aws_kms_key.rds.arn

  db_subnet_group_name   = aws_db_subnet_group.audit.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  publicly_accessible    = false
  multi_az               = true

  backup_retention_period = var.rds_backup_retention_days
  backup_window           = "02:00-03:00"
  maintenance_window      = "sun:04:00-sun:05:00"
  copy_tags_to_snapshot   = true

  deletion_protection       = true
  skip_final_snapshot       = false
  final_snapshot_identifier = "${local.name}-audit-final"

  auto_minor_version_upgrade      = true
  performance_insights_enabled    = true
  performance_insights_kms_key_id = aws_kms_key.rds.arn
  monitoring_interval             = 60
  monitoring_role_arn             = aws_iam_role.rds_monitoring.arn

  enabled_cloudwatch_logs_exports = ["postgresql", "upgrade"]

  depends_on = [aws_iam_role_policy_attachment.rds_monitoring]
}

