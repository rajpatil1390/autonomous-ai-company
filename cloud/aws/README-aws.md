# AWS production architecture

This directory documents the production AWS target created by the Terraform
configuration in `cloud/terraform`. Terraform generates infrastructure only;
running `terraform apply` is an explicit operator action and is not part of this
repository step.

## Architecture

The VPC spans at least two availability zones. Public subnets contain the
internet gateway path, NAT gateways, and future public load balancers. EKS
managed nodes and RDS PostgreSQL run only in private subnets. The EKS control
plane endpoint is private. Workloads reach AWS Secrets Manager through an
interface VPC endpoint and reach approved public APIs through NAT.

ECR stores immutable application images. EKS runs the existing Helm chart. RDS
stores append-only audit data with encryption, Multi-AZ failover, automated
backups, deletion protection, and an AWS-managed master credential. Amazon
Managed Service for Prometheus and Amazon Managed Grafana provide the monitoring
foundation. The OTLP value is explicitly a placeholder until a collector is
deployed.

See `architecture.drawio` for the editable architecture diagram.

## Deployment flow

1. Configure an encrypted, access-controlled S3 backend with locking outside
   this repository.
2. Copy `terraform.tfvars.example` to an untracked environment-specific file and
   replace identifiers, never secret values.
3. Run `terraform init -backend-config=...`, `terraform validate`, and
   `terraform plan` from `cloud/terraform`.
4. Review and approve the plan before an authorized operator runs apply.
5. Populate the created Secrets Manager entries through an audited out-of-band
   process.
6. Build the existing Docker image and push an immutable tag to the ECR output.
7. Connect to EKS from a VPC-connected runner and deploy
   `helm/autonomous-ai-company` with `values-prod.yaml` and AWS-specific values.

## CI/CD integration

GitHub Actions uses OIDC to assume the dedicated CI/CD role. No long-lived AWS
keys are stored in GitHub. The role can authenticate to ECR, publish only to the
application repository, and describe only the target EKS cluster. Kubernetes
authorization must separately grant the role narrowly scoped deployment access.
Because the EKS endpoint is private, the deployment job must run on a hardened
self-hosted runner in the VPC or another approved private network path.

CI should build, test, scan, and publish an immutable `sha-<commit>` image. A
separately approved deployment job updates the Helm image repository and tag,
runs `helm upgrade --install --atomic --wait`, and records the release revision.

## Helm deployment

Terraform outputs the cluster name, region, ECR repository URL, database
endpoint, and secret ARNs. Pass non-sensitive outputs through a generated,
untracked values file. Use External Secrets Operator or the Secrets Store CSI
Driver with the application IRSA role to materialize the values expected by the
existing chart. Do not commit rendered Kubernetes Secret objects.

## Secrets Manager integration

Terraform creates secret containers but never creates application secret
versions. Anthropic and JWT values are populated later by an authorized security
workflow. RDS creates and rotates its master password itself. The application
IAM role can read only these three secret ARNs and decrypt only the RDS KMS key.

## Disaster recovery

- Retain automated RDS backups for 30 days and test point-in-time recovery.
- Copy critical snapshots to a second region/account according to the recovery
  policy; this cross-region copy is intentionally not automated by this stack.
- Keep ECR image tags immutable and replicate release images when a secondary
  region is introduced.
- Store Terraform state remotely with encryption, versioning, access logging,
  and locking; back up the backend independently.
- Recreate EKS from Terraform, restore RDS, repopulate/replicate secret versions,
  and redeploy the pinned Helm release during a regional recovery exercise.
- Define and test RPO/RTO targets before production launch.

## Cost optimization

- Set `single_nat_gateway=true` only for non-production environments; production
  defaults to one NAT gateway per availability zone for resilience.
- Right-size EKS nodes and RDS from observed CPU, memory, connection, and I/O
  data. Consider Graviton node types after image compatibility testing.
- Add a separate Spot managed node group for interruption-tolerant workloads;
  keep critical pods on On-Demand capacity.
- Use Cluster Autoscaler limits and Kubernetes requests to avoid idle nodes.
- Review AMP sample ingestion, Grafana user licensing, CloudWatch retention, NAT
  data processing, and RDS storage autoscaling each month.
- Preserve Multi-AZ RDS, deletion protection, backups, and encryption when
  reducing cost.

