# IAM boundaries

The stack creates separate identities for separate responsibilities:

- **Cluster role:** permissions required by the EKS control plane.
- **Node role:** managed-node bootstrap, CNI, and ECR pull permissions.
- **Application role:** IRSA trust scoped to one namespace/service account and
  read access to only the application/RDS secrets.
- **Cluster Autoscaler role:** IRSA trust scoped to its service account and
  mutation restricted by autoscaler resource tags.
- **CI/CD role:** GitHub OIDC trust restricted to one repository and branch,
  ECR publishing, and target-cluster discovery.
- **Terraform role:** trusted only by explicitly supplied operator role ARNs and
  limited to the AWS service families managed by this stack.
- **Grafana and RDS monitoring roles:** service-specific monitoring access.

No long-lived IAM user keys are created. Review IAM Access Analyzer findings and
CloudTrail usage, then reduce the Terraform execution policy further after the
initial resource set stabilizes.

