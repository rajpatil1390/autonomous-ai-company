# Cosign verification policy

Production images are verified by immutable digest. Tags alone are not accepted because a tag can be moved after review.

## Keyless verification

The security workflow installs Cosign and runs `cosign verify`; it never signs an image. The verifier requires:

- an image reference in `registry/repository@sha256:<digest>` form;
- a certificate issued by `https://token.actions.githubusercontent.com`;
- an identity matching the repository-owned workflow identity configured in `COSIGN_TRUSTED_IDENTITY_REGEXP`; and
- successful Rekor transparency-log verification under Cosign's default policy.

The image reference, AWS region, read-only AWS role ARN, and trusted identity expression are GitHub repository variables. The AWS role is assumed with GitHub OIDC and must grant only the ECR read operations needed to retrieve the image manifest.

## Trusted identities

Trust is limited to GitHub Actions identities for this repository. A recommended expression is:

```text
^https://github.com/<owner>/<repository>/.github/workflows/(deploy|security)\.yml@refs/(heads/main|tags/v.*)$
```

Replace the placeholders with the canonical repository owner and name. Do not use a wildcard that trusts every repository, workflow, branch, or tag in an organization.

## Verification process

1. Resolve the release image to its immutable SHA-256 digest.
2. Set `SECURITY_IMAGE_REFERENCE` to that digest-qualified reference.
3. Configure the read-only `AWS_SECURITY_READ_ROLE_ARN` repository variable.
4. Configure `COSIGN_TRUSTED_IDENTITY_REGEXP` to the narrow repository identity above.
5. Dispatch the security workflow and retain `cosign-verification.json` as evidence.

Verification failure blocks the security workflow. An unsigned image, an identity mismatch, an invalid certificate, or a transparency-log failure must not be bypassed.

## SLSA compatibility

A Cosign signature establishes artifact identity and signer provenance, but it is not by itself a SLSA provenance statement. This policy is compatible with future in-toto/SLSA attestations: generate provenance in the trusted build, attach it to the same digest, then extend verification with `cosign verify-attestation` and an explicit predicate policy.

