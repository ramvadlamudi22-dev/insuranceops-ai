# Operational Runbooks

This directory contains operational runbooks for InsuranceOps AI.

Each runbook documents a specific operational procedure, its prerequisites, expected outcomes, and validation steps.

## Index

| Runbook | Purpose |
|---------|---------|
| [backup_restore.md](./backup_restore.md) | Postgres backup, restore, and drill procedures |

## Conventions

- Runbooks assume the operator is in the repository root directory.
- All commands reference the production Compose file at `compose/compose.yml` unless stated otherwise.
- Timestamps use UTC throughout.
- Each runbook carries a `Last verified` date at the top; a runbook not verified within two quarters is considered stale.
