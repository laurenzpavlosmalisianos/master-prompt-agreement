---
name: mpa-migration
description: "Checks for schema or data migrations, code ports and rewrites, and backing changes out safely. Use when writing a database migration or backfill, making a compatibility-breaking upgrade, porting or rewriting code, or reverting a change."
---

# Migration and backout

## Recovery

- Before deleting or ignoring old state, show that the migrated state is complete with reconciliation counts or checksums. Keep the old state for a stated period.
- Prefer expand, migrate, contract over a one-shot rewrite, so each step can be undone separately.

## Compatibility

- Backfills and transforms get interrupted and retried. Make them idempotent and resumable, and run them in bounded batches while watching lock waits and replica lag; one large transaction holds its locks until it ends and delays cleanup of old row versions.
- Check lock impact, statements that commit implicitly, and statements that cannot run inside a transaction on the engine in use. Run DDL with a short lock timeout and retry, because without one a PostgreSQL lock request waits indefinitely for conflicting locks; a failed `CREATE INDEX CONCURRENTLY` leaves an invalid index to drop before retrying.

## Ports and rewrites

- While old and new paths coexist, label which one is active and state what retires the old one.

## Report

- The operation sequence, the recovery method per step, reconciliation results, and what could not be verified.
