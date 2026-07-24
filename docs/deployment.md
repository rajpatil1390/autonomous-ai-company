# Production deployment

Production delivery is release-driven. Publishing a GitHub Release invokes
`.github/workflows/release.yml`, which calls the reusable deployment workflow in
`.github/workflows/deploy.yml`. The pipeline changes infrastructure state only;
it does not change application, Helm, Kubernetes, or Terraform code.

## Prerequisites

Configure a protected GitHub Environment named `production` with required
reviewers and deployment-branch/tag rules. Add these environment variables:

- `AWS_REGION`
- `AWS_DEPLOY_ROLE_ARN`
- `EKS_CLUSTER_NAME`
- `ECR_REPOSITORY`
- `PRODUCTION_BASE_URL`

Add `SMOKE_USERNAME` and `SMOKE_PASSWORD` as environment secrets. These values
must identify a dedicated, minimally privileged smoke-test account. They are
never printed or passed as workflow inputs.

The production runner must carry the labels `self-hosted`, `linux`, `x64`, and
`production-vpc`, have Docker, AWS CLI, kubectl, Helm, curl, and jq installed,
and have network access to the private EKS endpoint. Harden and isolate the
runner because it executes release source code.

The AWS role trust policy must accept GitHub's OIDC subject for the protected
production environment:

```text
repo:<organization>/<repository>:environment:production
```

This release subject differs from the branch-only trust example in the current
Terraform stack. Terraform is intentionally not modified by this CD step; update
and review that trust policy separately before enabling deployment. The role
must not use static AWS access keys.

Kubernetes authorization must map the deployment role to only the target
namespace and release operations needed by Helm. The role also needs the ECR
publish and target-cluster discovery permissions documented in `cloud/aws`.

## Release pipeline

The pipeline performs these gates in order:

1. Check out the immutable GitHub Release tag and validate all inputs.
2. Build the existing production Docker target.
3. Run the complete test suite with 100 percent coverage.
4. Run Ruff lint and formatting checks.
5. Scan the local image for unfixed HIGH and CRITICAL vulnerabilities with a
   full-SHA-pinned Trivy action.
6. Sign and verify the scanned Docker archive with keyless Cosign before it
   leaves the runner.
7. Obtain short-lived AWS credentials through GitHub OIDC and sign in to ECR.
8. Push the immutable release tag and capture its registry digest.
9. Sign and verify that digest with keyless Cosign and GitHub OIDC.
10. Configure kubectl for the private EKS cluster.
11. Run an idempotent `helm upgrade --install --atomic --wait`.
12. Run authenticated production smoke tests.
13. Invoke rollback protection only when Helm deployment or smoke verification
    fails, then fail the release job.

The pre-publication signature covers the exact Docker archive produced from the
scanned local image. Cosign then signs the durable OCI digest after ECR returns
it, because a registry digest does not exist before push. No deployment occurs
until both proofs have been verified.

## Idempotency and atomic deployment

`scripts/deploy.sh` validates immutable semantic release tags, records the last
deployed revision, and uses stable release/namespace names. Re-running the same
release converges through Helm rather than creating another application name.
The ECR repository is configured for immutable tags, so a conflicting rebuild
cannot replace production content. On a workflow rerun, the pipeline reuses the
existing registry digest, verifies/signs it again under the release identity,
and skips the rejected duplicate push.

`--atomic`, `--wait`, `--wait-for-jobs`, `--cleanup-on-fail`, and a bounded
timeout make a release succeed only when Kubernetes reaches readiness. Helm's
atomic behavior restores the prior state when an upgrade itself fails.

## Smoke tests

`scripts/smoke_test.sh` checks:

- `GET /health`
- `GET /version`
- `POST /auth/login`
- Authenticated `POST /workflow/run`
- `GET /metrics`
- Authenticated `POST /workflow/stream`, including real workflow start and
  completion events

Smoke tests run after Kubernetes readiness because probes demonstrate pod
health, while smoke tests demonstrate that ingress, authentication, graph
execution, provider connectivity, metrics, and SSE work together. The workflow
payload is deterministic, but it invokes the real production workflow and may
consume provider tokens.

## Rollback behavior

The workflow captures the previously deployed Helm revision before upgrading.
If Helm or smoke tests fail, `scripts/rollback.sh` runs `helm rollback` to that
revision and waits for the Deployment rollout. On a first installation there is
no prior revision; Helm's atomic cleanup is authoritative and the rollback
script exits safely without inventing a target.

Rollback is never executed after a successful Helm deployment and successful
smoke suite. Operators can perform a reviewed manual rollback with:

```text
bash scripts/rollback.sh autonomous-ai-company autonomous-ai-company <revision>
```

## Release procedure

1. Confirm CI passed for the commit being tagged.
2. Create an immutable semantic tag such as `v1.2.3`.
3. Publish the corresponding GitHub Release.
4. Approve the protected `production` environment deployment.
5. Monitor image scanning, signing, Helm status, and smoke-test output.
6. Record the deployed image digest and Helm revision from the job summary.

Do not rerun around failed security gates. Correct the source, publish a new
version, and preserve the failed release as an auditable event.
