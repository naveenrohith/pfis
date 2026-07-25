# PFIS Production Release Record

Complete this record in the deployment system for every production release.
Do not commit real credentials, private endpoints, or personal contact details.

## Release

- Commit SHA:
- Deployment version:
- Environment:
- Change owner:
- Started at:
- Completed at:

## Operational ownership

- Incident owner:
- Data-recovery owner:
- Security owner:
- Rollback decision owner:

## Provider controls

- Managed PostgreSQL resource ID:
- Production database name:
- Backup policy ID and retention:
- Monitoring dashboard ID:
- Alert policy/routing ID:
- TLS policy/certificate ID:
- Network/firewall policy ID:
- Log destination ID:

## Evidence

- `restore-evidence.json` artifact:
- `release-evidence.json` artifact:
- Migration output:
- Frontend artifact/version:
- CI run:
- Load/soak result:
- Alert delivery test:
- Restore duration:

## Rollback

- Previous known-good commit:
- Database recovery point:
- Rollback command/runbook:
- Rollback verification:

## Approval

- Application approval:
- Operations approval:
- Security approval:
- Go-live decision and timestamp:
