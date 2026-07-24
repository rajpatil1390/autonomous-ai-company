# AWS Secrets Manager

Terraform provisions metadata-only secret containers for the Anthropic API key
and JWT signing key. It deliberately creates no `aws_secretsmanager_secret_version`
resources, variables containing payloads, or tfvars containing credentials. RDS
owns its generated master credential.

After apply, populate application values through an audited security workflow.
The output ARNs replace the placeholder references used during planning.
Kubernetes should consume them with External Secrets Operator or the Secrets
Store CSI Driver using the application IRSA role. This replaces committed or
manually maintained Kubernetes Secret values while preserving the Secret name
expected by Helm.

Enable rotation where the upstream credential supports it and alert on unusual
`GetSecretValue` activity. Never print secret values in CI logs.

