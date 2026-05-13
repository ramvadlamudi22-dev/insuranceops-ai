## What changed

<!-- One paragraph describing the change. -->

## Why

<!-- Reference a PRD line, ADR, phase commitment, or bug report. -->

## Migration safety

<!-- If this PR includes a migration, fill in the section below. Otherwise write "N/A". -->

- [ ] No migration in this PR
- [ ] Migration is additive only (new table, new nullable column, new index with CONCURRENTLY)
- [ ] Migration is destructive (drop/rename) — expand-migrate-contract phase: ______
- [ ] Data migration included — idempotent: yes/no
- [ ] Lock duration estimate for largest affected table: ______

## Tests

<!-- File path and test name that covers this change. -->

## Rollout notes

<!-- Anything non-obvious about deploy order or feature flags. Write "None" if straightforward. -->
