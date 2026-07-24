variable "aws_region" {
  description = "AWS region in which production infrastructure is provisioned."
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Stable prefix applied to resource names and tags."
  type        = string
  default     = "autonomous-ai-company"
}

variable "environment" {
  description = "Deployment environment represented by this Terraform state."
  type        = string
  default     = "production"

  validation {
    condition     = contains(["development", "staging", "production"], var.environment)
    error_message = "environment must be development, staging, or production."
  }
}

variable "vpc_cidr" {
  description = "IPv4 CIDR assigned to the application VPC."
  type        = string
  default     = "10.40.0.0/16"
}

variable "availability_zone_count" {
  description = "Number of availability zones used by public and private subnets."
  type        = number
  default     = 2

  validation {
    condition     = var.availability_zone_count >= 2 && var.availability_zone_count <= 3
    error_message = "availability_zone_count must be between two and three."
  }
}

variable "public_subnet_cidrs" {
  description = "Public subnet CIDRs; provide at least availability_zone_count entries."
  type        = list(string)
  default     = ["10.40.0.0/20", "10.40.16.0/20", "10.40.32.0/20"]
}

variable "private_subnet_cidrs" {
  description = "Private subnet CIDRs; provide at least availability_zone_count entries."
  type        = list(string)
  default     = ["10.40.128.0/20", "10.40.144.0/20", "10.40.160.0/20"]
}

variable "single_nat_gateway" {
  description = "Use one NAT gateway to reduce non-production cost; false preserves zone redundancy."
  type        = bool
  default     = false
}

variable "eks_version" {
  description = "Supported Amazon EKS Kubernetes minor version."
  type        = string
  default     = "1.33"
}

variable "node_instance_types" {
  description = "EC2 instance types available to the managed node group."
  type        = list(string)
  default     = ["m7i.large"]
}

variable "node_min_size" {
  description = "Managed node group minimum size and Cluster Autoscaler lower bound."
  type        = number
  default     = 2
}

variable "node_desired_size" {
  description = "Initial managed node group size."
  type        = number
  default     = 2
}

variable "node_max_size" {
  description = "Managed node group maximum size and Cluster Autoscaler upper bound."
  type        = number
  default     = 10
}

variable "node_disk_size_gib" {
  description = "Encrypted root volume size for EKS worker nodes."
  type        = number
  default     = 50
}

variable "rds_engine_version" {
  description = "PostgreSQL major version for the audit database."
  type        = string
  default     = "16"
}

variable "rds_instance_class" {
  description = "RDS database instance class."
  type        = string
  default     = "db.t4g.medium"
}

variable "rds_allocated_storage_gib" {
  description = "Initial encrypted RDS storage allocation."
  type        = number
  default     = 100
}

variable "rds_max_allocated_storage_gib" {
  description = "Maximum RDS autoscaled storage allocation."
  type        = number
  default     = 500
}

variable "rds_backup_retention_days" {
  description = "Retention period for automated RDS backups."
  type        = number
  default     = 30
}

variable "github_organization" {
  description = "GitHub organization allowed to assume the CI/CD role."
  type        = string
}

variable "github_repository" {
  description = "GitHub repository allowed to assume the CI/CD role."
  type        = string
}

variable "github_deployment_branch" {
  description = "Git branch allowed to perform production deployments."
  type        = string
  default     = "main"
}

variable "terraform_operator_principal_arns" {
  description = "Trusted operator roles allowed to assume the Terraform execution role."
  type        = list(string)

  validation {
    condition     = length(var.terraform_operator_principal_arns) > 0
    error_message = "At least one Terraform operator principal ARN is required."
  }
}

variable "kubernetes_namespace" {
  description = "Namespace used by the existing Helm chart."
  type        = string
  default     = "autonomous-ai-company"
}

variable "application_service_account" {
  description = "Kubernetes service account bound to the application IAM role."
  type        = string
  default     = "autonomous-ai-company"
}

variable "otlp_endpoint" {
  description = "Placeholder endpoint supplied to workloads when an OTLP collector is deployed."
  type        = string
  default     = "https://REPLACE_WITH_OTLP_COLLECTOR_ENDPOINT"
}

variable "additional_tags" {
  description = "Additional non-sensitive tags merged into every supported resource."
  type        = map(string)
  default     = {}
}

