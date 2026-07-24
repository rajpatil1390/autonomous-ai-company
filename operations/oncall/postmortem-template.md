# Blameless Postmortem Template

This template analyzes system conditions and decision context without assigning
personal blame. Complete it for every SEV-1 and SEV-2 incident and for lower
severity incidents with material learning value.

## Summary

- **Incident ID:**
- **Date:**
- **Severity:**
- **Authors and reviewers:**
- **One-sentence summary:**

## Impact

- Customer and business impact:
- Duration and scope:
- Data integrity or security impact:
- SLO breached:
- Error budget consumed:

## Detection

- How the incident was detected:
- Detection delay:
- Alerts that fired or failed to fire:
- Observability gaps:

## Timeline

| Time (UTC) | Event, evidence, or decision |
| --- | --- |
| `YYYY-MM-DD HH:MM` | |

## Root Cause and Contributing Factors

- Technical root cause:
- Trigger:
- Contributing system or process factors:
- Why safeguards did not prevent or contain the impact:

## Response and Recovery

- Mitigation performed:
- Rollback performed or considered:
- Recovery verification:
- Factors that increased or reduced recovery time:

## What Went Well

- Detection, coordination, tooling, or safeguards that helped:

## What Could Be Improved

- Detection, design, process, communication, or documentation gaps:

## Corrective Actions

| Priority | Action | Owner | Due date | Verification | Status |
| --- | --- | --- | --- | --- | --- |
| P0/P1/P2 | | | | | `open | complete` |

Actions must be specific, independently verifiable, and tracked to completion.
Avoid unactionable conclusions such as asking responders to be more careful.

## SLO and Error-Budget Decision

- Budget status after the incident:
- Release policy applied:
- Reliability work prioritized:
- SLO or SLI changes proposed, with rationale:

## Lessons and Follow-Up

- Reusable lessons:
- Runbooks or dashboards to update:
- Follow-up review date:
- Evidence that corrective actions worked:

## Approval

- Service owner:
- Reliability reviewer:
- Security or compliance reviewer, if applicable:
- Date closed:
