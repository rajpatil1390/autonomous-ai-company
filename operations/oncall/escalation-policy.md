# On-Call Escalation Policy

## Purpose

This policy establishes consistent incident ownership, escalation timing, and
communication expectations for the Autonomous AI Company service. All times
and incident records use UTC.

## Incident Severity Matrix

| Severity | Customer or business impact | Examples | Acknowledge | Update cadence | Escalate after |
| --- | --- | --- | --- | --- | --- |
| SEV-1 Critical | Complete service outage, confirmed data loss, or active security incident | API unavailable across replicas; destructive audit corruption; credential compromise | 5 minutes | 15 minutes | 5 minutes |
| SEV-2 High | Major feature unavailable or severe degradation with no reliable workaround | Workflow execution broadly failing; authentication unavailable; database outage | 10 minutes | 30 minutes | 10 minutes |
| SEV-3 Medium | Limited degradation with a safe workaround and no data loss | One provider degraded; elevated latency within remaining error budget | 30 minutes | 60 minutes | 30 minutes |
| SEV-4 Low | Minor operational issue with negligible customer impact | Isolated alert, documentation defect, or non-urgent capacity warning | 1 business day | As agreed | 1 business day |

The incident commander may raise severity immediately as impact expands.
Severity may be lowered only after impact is contained and the decision is
recorded in the incident timeline.

## Escalation Flow

1. Alert the primary on-call engineer and create an incident record.
2. If the acknowledgement deadline expires, page the backup on-call engineer.
3. For SEV-1 or SEV-2, appoint an incident commander and engage the service
   owner as soon as the incident is acknowledged.
4. Engage the relevant specialist: platform for Kubernetes, data for
   PostgreSQL, security for suspected compromise, or provider owner for LLM
   degradation.
5. Engage executive and communications leads when customer impact, regulatory
   exposure, or the published update cadence requires it.
6. Continue escalation until an accountable responder explicitly accepts
   ownership. Never assume that sending a notification transfers ownership.

Receiver addresses and paging integrations are configured outside this
repository. The placeholder Alertmanager receivers contain no credentials.

## Incident Roles

- **Incident commander:** owns severity, coordination, decisions, and closure.
- **Operations lead:** performs diagnosis and recovery actions.
- **Communications lead:** publishes approved status updates and maintains the
  stakeholder record.
- **Scribe:** records UTC events, evidence, commands, decisions, and owners.
- **Subject-matter expert:** advises on a bounded subsystem without replacing
  incident command.

One person may hold multiple roles for a small incident, but SEV-1 incidents
should separate incident command from hands-on remediation.

## Communication

Every operational update must state:

- incident identifier, severity, and current status;
- confirmed customer impact and affected functions;
- actions completed, actions in progress, and known risks;
- next update time in UTC;
- incident commander and communication owner.

Do not place passwords, tokens, API keys, raw prompts, generated text, or
personal data in incident channels or tickets.

## Handoff

An on-call handoff is complete only when the incoming responder acknowledges:

- current impact and severity;
- the latest timeline and working hypothesis;
- actions already attempted and their results;
- active mitigations and rollback conditions;
- outstanding owners and the next communication deadline.

## Review and Maintenance

The service owner reviews this policy quarterly and after every SEV-1 or SEV-2
postmortem. Contact rosters and real receiver integrations are maintained in
the approved operational system, not in source control.
