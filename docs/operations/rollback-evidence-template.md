# PFIS Rollback Evidence Template

This template records rollback readiness or an actual rollback decision. It does
not claim that a rollback rehearsal has been performed.

Store completed evidence in the protected `RELEASE_EVIDENCE_DIR`. If a rollback
readiness artifact is included in a promotion manifest, reference it from the
appropriate evidence JSON and keep provider credentials out of the repository.

## Owner-supplied placeholders

- Release owner: `<RELEASE_OWNER supplied by release owner>`
- Incident owner: `<INCIDENT_OWNER supplied by incident-response owner>`
- Data recovery owner: `<DATA_RECOVERY_OWNER supplied by data-recovery owner>`
- Security owner: `<SECURITY_OWNER supplied by security owner>`
- Deployment environment: `<ENVIRONMENT supplied by deployment owner>`
- Current release identifier: `<CURRENT_RELEASE_ID supplied by release owner>`
- Previous release identifier: `<PREVIOUS_RELEASE_ID supplied by release owner>`
- Backup policy: `<BACKUP_POLICY_ID supplied by data-recovery owner>`
- Restore evidence: `<RESTORE_EVIDENCE_PATH supplied by data-recovery owner>`

## Rollback readiness

| Gate | Owner | Evidence placeholder | Status |
| --- | --- | --- | --- |
| Previous app artifact available | `<RELEASE_OWNER>` | `<PREVIOUS_ARTIFACT_URI>` | `<STATUS>` |
| Database rollback strategy reviewed | `<DATA_RECOVERY_OWNER>` | `<DB_ROLLBACK_PLAN>` | `<STATUS>` |
| Latest backup available | `<DATA_RECOVERY_OWNER>` | `<BACKUP_POLICY_ID>` | `<STATUS>` |
| Restore path reviewed | `<DATA_RECOVERY_OWNER>` | `<RESTORE_EVIDENCE_PATH>` | `<STATUS>` |
| Emergency Google allowlist plan reviewed | `<SECURITY_OWNER>` | `<ALLOWLIST_DECISION>` | `<STATUS>` |
| Customer communication plan ready | `<INCIDENT_OWNER>` | `<COMMS_PLAN_URI>` | `<STATUS>` |

## Rollback execution record

- Decision time (UTC): `<DECISION_TIME supplied by incident commander>`
- Decision reason: `<DECISION_REASON supplied by incident commander>`
- Rollback type: `<APP_REVERT|RESTORE|CONFIG_RESTRICTION supplied by incident commander>`
- Commands or deployment actions:
  `<ACTIONS supplied by release owner; do not include secrets>`
- Health checks after rollback:
  `<HEALTH_EVIDENCE supplied by incident-response owner>`
- Data validation after rollback:
  `<DATA_VALIDATION supplied by data-recovery owner>`
- Follow-up actions:
  `<FOLLOW_UP supplied by incident commander>`
