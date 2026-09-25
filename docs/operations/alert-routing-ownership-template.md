# PFIS Alert Routing And Ownership Evidence Template

This template documents deployment-owned alert routing. It does not claim that
alerts have fired or that a hosted rehearsal has been performed.

For promotion-manifest compatibility, store the completed machine-readable
provider-control evidence as `provider-contract.json` or `privacy-security.json`
in the protected `RELEASE_EVIDENCE_DIR` when those controls are part of a
release handoff. Do not commit secrets or personal contact details.

## Ownership placeholders

- Incident owner: `<INCIDENT_OWNER supplied by incident-response owner>`
- Data recovery owner: `<DATA_RECOVERY_OWNER supplied by data-recovery owner>`
- Security owner: `<SECURITY_OWNER supplied by security owner>`
- Observability owner: `<OBSERVABILITY_OWNER supplied by deployment owner>`
- Business owner: `<BUSINESS_OWNER supplied by release owner>`

## Provider controls

| Control | Placeholder to replace | Named owner |
| --- | --- | --- |
| Database resource | `<DATABASE_RESOURCE_ID>` | `<DATA_RECOVERY_OWNER>` |
| Backup policy | `<BACKUP_POLICY_ID>` | `<DATA_RECOVERY_OWNER>` |
| Monitoring dashboard | `<MONITORING_DASHBOARD_ID>` | `<OBSERVABILITY_OWNER>` |
| Alert policy | `<ALERT_POLICY_ID>` | `<OBSERVABILITY_OWNER>` |
| TLS policy | `<TLS_POLICY_ID>` | `<SECURITY_OWNER>` |
| Network policy | `<NETWORK_POLICY_ID>` | `<SECURITY_OWNER>` |
| Hosted log sink | `<LOG_SINK_ID>` | `<OBSERVABILITY_OWNER>` |

## Alert routes

| Signal | Threshold/source | Primary owner | Escalation | Evidence |
| --- | --- | --- | --- | --- |
| API error rate | `<ERROR_RATE_POLICY>` | `<INCIDENT_OWNER>` | `<ESCALATION_CHANNEL>` | `<ALERT_POLICY_ID>` |
| API p95 latency | `<LATENCY_POLICY>` | `<OBSERVABILITY_OWNER>` | `<ESCALATION_CHANNEL>` | `<ALERT_POLICY_ID>` |
| Readiness failure | `<READINESS_POLICY>` | `<INCIDENT_OWNER>` | `<ESCALATION_CHANNEL>` | `<ALERT_POLICY_ID>` |
| Gmail sync failures | `<GMAIL_SYNC_POLICY>` | `<INCIDENT_OWNER>` | `<ESCALATION_CHANNEL>` | `<ALERT_POLICY_ID>` |
| Parser failure drift | `<PARSER_POLICY>` | `<INCIDENT_OWNER>` | `<ESCALATION_CHANNEL>` | `<ALERT_POLICY_ID>` |
| Backup failure | `<BACKUP_POLICY>` | `<DATA_RECOVERY_OWNER>` | `<ESCALATION_CHANNEL>` | `<BACKUP_POLICY_ID>` |

## Machine-readable evidence shape

```json
{
  "status": "<configured|deferred supplied by release owner>",
  "observed_at": "<UTC timestamp supplied by release owner>",
  "owners": {
    "incident": "<INCIDENT_OWNER>",
    "data_recovery": "<DATA_RECOVERY_OWNER>",
    "security": "<SECURITY_OWNER>",
    "observability": "<OBSERVABILITY_OWNER>"
  },
  "controls": {
    "database_resource_id": "<DATABASE_RESOURCE_ID>",
    "backup_policy_id": "<BACKUP_POLICY_ID>",
    "monitoring_dashboard_id": "<MONITORING_DASHBOARD_ID>",
    "alert_policy_id": "<ALERT_POLICY_ID>",
    "tls_policy_id": "<TLS_POLICY_ID>",
    "network_policy_id": "<NETWORK_POLICY_ID>",
    "log_sink_id": "<LOG_SINK_ID>"
  }
}
```
