# PFIS Incident Response Evidence Template

This template is a release/incident evidence aid only. It does not claim that an
incident rehearsal has been performed.

Store completed evidence in the protected `RELEASE_EVIDENCE_DIR`. If it feeds a
promotion manifest, reference its digest from the applicable JSON artifact rather
than committing operational contact details.

## Ownership placeholders

- Incident owner: `<INCIDENT_OWNER supplied by incident-response owner>`
- Security owner: `<SECURITY_OWNER supplied by security owner>`
- Data recovery owner: `<DATA_RECOVERY_OWNER supplied by data-recovery owner>`
- Communications owner: `<COMMUNICATIONS_OWNER supplied by incident-response owner>`
- Escalation channel: `<ESCALATION_CHANNEL supplied by incident-response owner>`
- Hosted log store: `<LOG_STORE_ID supplied by observability owner>`
- Monitoring dashboard: `<MONITORING_DASHBOARD_ID supplied by observability owner>`

## Incident record

- Incident ID: `<INCIDENT_ID supplied by incident-response owner>`
- Environment: `<ENVIRONMENT supplied by deployment owner>`
- Start time (UTC): `<STARTED_AT supplied by incident commander>`
- Detection source: `<DETECTION_SOURCE supplied by incident commander>`
- Customer impact summary: `<IMPACT_SUMMARY supplied by incident commander>`
- Data exposure suspected: `<YES_NO_UNKNOWN supplied by security owner>`
- Current status: `<STATUS supplied by incident commander>`

## Timeline

| UTC time | Owner | Event | Evidence link |
| --- | --- | --- | --- |
| `<TIME>` | `<OWNER>` | `<EVENT>` | `<EVIDENCE_URI>` |

## Required checks

- Confirm `/api/health`, `/api/health/ready`, and `/api/health/ops` status:
  `<HEALTH_EVIDENCE supplied by incident-response owner>`.
- Confirm whether Gmail sync, parser failures, jobs, and API latency are
  affected: `<DOMAIN_IMPACT supplied by incident-response owner>`.
- Confirm whether rollback or restore criteria are met:
  `<ROLLBACK_OR_RESTORE_DECISION supplied by incident commander>`.
- Confirm user communication requirement:
  `<COMMUNICATION_DECISION supplied by communications owner>`.

## Closure

- Root cause summary: `<ROOT_CAUSE supplied by incident commander>`
- Corrective actions: `<ACTIONS supplied by incident commander>`
- Follow-up owner and due date: `<FOLLOW_UP supplied by incident-response owner>`
- Evidence retained at: `<EVIDENCE_LOCATION supplied by release owner>`
