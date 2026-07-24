# Amazon ECR

Terraform creates one private repository for the existing API image. Tags are
immutable, scanning on push is enabled, and AES-256 server-side encryption is
required. The lifecycle policy removes untagged images after seven days and
retains the newest fifty tagged release/commit images.

CI authenticates through GitHub OIDC, builds the unchanged Dockerfile, tags the
image with an immutable version or commit SHA, and pushes to the
`ecr_repository_url` output. Production Helm releases must pin an immutable tag;
they must not deploy `latest`.

