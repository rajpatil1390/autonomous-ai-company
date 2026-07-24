# Alertmanager routing policy

## Purpose

This configuration defines routing behavior only. It does not deploy Alertmanager, create Prometheus alert rules, or contact a real receiver. Every receiver is intentionally empty until an approved secret-injection mechanism supplies an integration outside source control.

## Required alert labels

Every alert rule integrated later must provide:

- `alertname`: stable condition name;
- `severity`: `warning` or `critical`;
- `namespace`: workload namespace;
- `service`: affected service; and
- `runbook_url`: repository URL for the relevant runbook when the rule system supports annotations.

Do not use request IDs, workflow IDs, usernames, prompts, model output, tokens, or other high-cardinality or sensitive values as labels.

## Default route

Unclassified alerts go to `default-placeholder`. They group by alert name, namespace, and service after 30 seconds, regroup after 5 minutes, and repeat after 4 hours. The default receiver is a safety net, not a substitute for correct severity labeling.

## Warning route

`severity="warning"` routes to `warning-placeholder`. Warning notifications group for one minute, regroup every ten minutes, and repeat every four hours. Warnings should lead to investigation during the current support window before they consume the error budget rapidly.

## Critical route

`severity="critical"` routes to `critical-placeholder`. Critical notifications group for ten seconds, regroup every two minutes, and repeat every thirty minutes until resolved. The future receiver must page the primary on-call and integrate with the incident process.

## Inhibition

A critical alert suppresses a warning with the same alert name, namespace, and service. `APIUnavailable` at critical severity also suppresses symptom alerts for the same namespace and service, preventing a page storm while preserving the root condition.

Inhibition never resolves an alert. Operators must inspect the inhibited alerts after the source condition clears to detect independent failures.

## Receiver integration

Replace placeholders only through a separate reviewed deployment configuration. Email, Slack, PagerDuty, and webhook URLs or tokens must come from a secret manager or mounted secret, never this repository. Test routing in an isolated Alertmanager before production rollout and verify warning, critical, resolved, grouped, repeated, and inhibited behavior.

## Ownership and review

The SRE owner reviews routing monthly and after every missed, duplicate, or noisy page. Service owners review runbook links and alert ownership quarterly. Changes to receivers, inhibition, grouping, or repeat intervals require on-call review and a rollback plan.

