# Amazon RDS PostgreSQL

The audit database is deployed only in private subnets and accepts PostgreSQL
traffic only from the EKS cluster security group. It is Multi-AZ, encrypted with
a rotating KMS key, deletion-protected, monitored, and configured for automated
backups and a final snapshot.

RDS generates and stores the master password in AWS Secrets Manager through
`manage_master_user_password`. Terraform never receives the password. Production
operations should create a least-privileged application database role after
provisioning and rotate away from direct master-user access.

Recovery procedures must regularly test point-in-time restore into an isolated
subnet group. Snapshot-copy policy, cross-region recovery, and RPO/RTO are
organization-level decisions and remain explicit follow-up work.

