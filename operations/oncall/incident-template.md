# Incident Record Template

Use this template for an active incident. Store timestamps in UTC and link to
restricted evidence rather than copying secrets or sensitive payloads.

## Incident Metadata

- **Incident ID:** `INC-YYYY-NNN`
- **Title:**
- **Severity:** `SEV-1 | SEV-2 | SEV-3 | SEV-4`
- **Status:** `investigating | identified | monitoring | resolved`
- **Started at (UTC):**
- **Detected at (UTC):**
- **Resolved at (UTC):**
- **Incident commander:**
- **Operations lead:**
- **Communications lead:**
- **Scribe:**

## Impact

- Affected services and customer journeys:
- Confirmed customer impact:
- Geographic or tenant scope:
- Data integrity or security impact:
- Relevant SLO and error-budget impact:

## Detection

- Alert or report that detected the incident:
- Dashboard and metric evidence:
- Why earlier detection did or did not occur:

## Current Assessment

- Confirmed facts:
- Working hypothesis:
- Unknowns:
- Immediate risks:

## Timeline

| Time (UTC) | Event, evidence, or decision | Owner |
| --- | --- | --- |
| `YYYY-MM-DD HH:MM` | Incident declared | |

## Actions and Decisions

| Action or decision | Owner | Status | Result or evidence |
| --- | --- | --- | --- |
| | | `pending | active | complete` | |

## Recovery and Rollback

- Selected mitigation:
- Rollback trigger:
- Rollback procedure or runbook:
- Recovery verification:
- Monitoring period:

## Communication Template

> **[INCIDENT ID] [SEVERITY] — [STATUS]**  
> We are investigating an issue affecting [confirmed impact]. The team has
> [completed action] and is [current action]. The next update will be provided
> by [UTC time]. Do not include credentials or sensitive payloads.

## Escalations

| Time (UTC) | Role or team engaged | Reason | Acknowledged by |
| --- | --- | --- | --- |
| | | | |

## Closure Checklist

- [ ] Customer impact has ended.
- [ ] Health, workflow, and dependent-system checks pass.
- [ ] Data and audit integrity have been assessed.
- [ ] Temporary mitigations have owners and expiry dates.
- [ ] Final stakeholder communication has been sent.
- [ ] Error-budget impact has been recorded.
- [ ] Postmortem owner and due date have been assigned when required.
