# Security policy

## Supported versions

Security fixes are provided for the latest release on the `main` branch. Older releases and unmerged development branches are unsupported unless a separate support commitment is published with that release.

## Reporting a vulnerability

Do not open a public issue. Use the repository's **Security → Report a vulnerability** flow to create a private GitHub Security Advisory. Include the affected version, reproduction steps, impact, and any suggested remediation. If private reporting is unavailable, contact the maintainers through the private security contact configured in the repository organization; do not include exploit details in public channels.

Never include production credentials, personal data, access tokens, or customer records in a report. Use synthetic examples and revoke any credential that may have been exposed.

## Response timeline

- Acknowledgement: within 1 business day.
- Initial severity and reproducibility assessment: within 3 business days.
- Critical-issue mitigation plan: within 7 calendar days.
- Status updates: at least every 7 calendar days until resolution.
- Release timing: based on severity, exploitability, and safe coordination with affected parties.

These targets describe the response process, not a guarantee that every vulnerability can be safely fixed within the same period.

## Coordinated disclosure

The maintainers will validate the report, agree on a disclosure timeline with the reporter, prepare and test a fix, and publish an advisory when users can reasonably remediate. Reporters should keep details private until the coordinated publication date. Credit is offered when requested and legally permitted.

The project does not authorize destructive testing, privacy violations, denial-of-service testing, social engineering, or access beyond the minimum needed to demonstrate the issue.

## Security controls

Every proposed change is subject to dependency, source, filesystem, container, and semantic scanning. Release artifacts also receive SBOMs, while production image signatures are verified by digest and trusted keyless identity before deployment eligibility.

