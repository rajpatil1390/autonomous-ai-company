# Ransomware and destructive compromise runbook

## Detection

- Security tooling reports encryption, mass deletion, unusual backup access, credential abuse, malicious images, or unauthorized infrastructure changes.
- Database, object-storage, audit, or Kubernetes resources change outside approved identities and windows.
- Backup checksums, object-lock state, or retention policies differ from the protected baseline.

Treat uncertain destructive activity as a security incident. Preserve volatile evidence before routine recovery actions remove it.

## Immediate response

1. Activate security incident response and separate containment communications from potentially compromised systems.
2. Revoke or restrict compromised identities, sessions, CI roles, signing access, and network paths using clean administrative credentials.
3. Isolate affected clusters, databases, runners, and storage without deleting evidence.
4. Enable legal and forensic preservation holds on logs, snapshots, backups, IAM history, and audit trails.
5. Protect immutable backup vaults and verify that recovery credentials are independent of compromised production identity.
6. Stop automated deletion, retention expiry, deployment, and backup replication from compromised sources.

## Recovery steps

1. Establish a clean-room account, workstation, identity chain, and recovery environment.
2. Determine the compromise start time and select a checksum-valid, immutable backup from before that boundary.
3. Rebuild infrastructure from reviewed source and verified Terraform state; do not repair compromised hosts in place.
4. Verify image signatures and SBOMs, rotate all secrets and keys, and restore PostgreSQL into an isolated network.
5. Scan restored data and configuration, validate audit continuity, and obtain security approval before reconnecting dependencies.
6. Restore service gradually with enhanced monitoring and restricted privileges.

## Validation

- Forensics and security owners approve the selected clean recovery point.
- Backup checksum, decryption, archive catalog, and isolated restore checks pass.
- No compromised identity, image, secret, runner, node, or network path remains trusted.
- Database, audit, authentication, workflow, SSE, metrics, tracing, and signature verification pass in the clean environment.
- Immutable logging detects no continuing malicious activity during the observation period.

## Rollback

If compromise indicators reappear, disconnect the recovery environment, preserve evidence, revoke newly exposed credentials, and return to the last isolated clean-room checkpoint. Never route traffic back to the compromised environment merely to reduce downtime.

## Communication checklist

- Security incident commander, legal counsel, forensics lead, and executive sponsor
- Known scope, suspected entry time, affected identities/data, and containment status
- Law-enforcement, insurer, regulator, customer, and partner notification decisions
- RPO/RTO impact and evidence-based recovery confidence
- Approved internal and external wording through a trusted channel
- Credential rotation, clean-room validation, lessons learned, and remediation owners

