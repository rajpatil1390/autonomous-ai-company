# Amazon EKS

The managed EKS cluster and managed node group use private subnets across at
least two availability zones. The Kubernetes API endpoint is private, control
plane audit logs are retained in CloudWatch, and Kubernetes Secret objects use
KMS envelope encryption.

The cluster has an IAM OIDC provider. IRSA roles isolate application secret
access and Cluster Autoscaler permissions from the worker-node role. Node group
autoscaling tags and an ignored desired-size field allow Cluster Autoscaler to
operate without Terraform continuously reverting its decisions.

Install the existing Helm chart from a VPC-connected operator or CI runner:

```text
aws eks update-kubeconfig --region <region> --name <cluster-name>
helm upgrade --install autonomous-ai-company ../../helm/autonomous-ai-company \
  --namespace autonomous-ai-company --create-namespace \
  -f ../../helm/autonomous-ai-company/values-prod.yaml \
  --set image.repository=<ecr-repository-url> \
  --set image.tag=<immutable-tag> --atomic --wait
```

Kubernetes access entries/RBAC and add-ons such as an ingress controller,
External Secrets, and Cluster Autoscaler should be installed through a separate
audited platform release. They are not application code and are not silently
created by this infrastructure step.

