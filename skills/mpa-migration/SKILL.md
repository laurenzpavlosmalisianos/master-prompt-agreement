---
name: mpa-migration
description: Checks for changing a schema, data set, or interface so that it can be recovered, and for backing a change out. Use when writing a database migration or backfill, making a compatibility-breaking upgrade, porting code, or reverting a change.
---

# Migration and backout

## Recovery

- Do not assume a rollback exists. For every step that is hard to reverse, name how recovery works: restore, roll forward, rebuild from source, or contain. If there is none, say so plainly and state what would be lost.
- List every path to data loss: dropped or narrowed columns, type conversions that truncate, lossy transforms, deletion of old state.
- Before deleting or ignoring old state, show that the migrated state is complete with reconciliation counts or checksums. Keep the old state for a stated period.
- Prefer expand, migrate, contract over a one-shot rewrite, so each step can be undone separately.
- A backup that has never been restored is unproven.
- Ask for approval of the exact operation sequence, with stop conditions, before touching real data, deployments, or credentials.

## Compatibility

- Map every reader and writer. Old code must work against new state and new code against old state for as long as both run, and deployment order follows from that.
- Backfills and transforms get interrupted and retried. Make them idempotent and resumable.
- Check wire formats, serialization, exact output, and error behaviour, not only that the code compiles.
- Check lock impact, statements that commit implicitly, and statements that cannot run inside a transaction on the engine in use.

## Ports and rewrites

- A port that compiles and passes the inherited tests is not shown to be equivalent. Inherited tests can lock in old bugs and miss behaviour the port adds. Compare outputs, side effects, and error states at a stable external boundary over a representative input set.
- Generated translations often compile by weakening types, broadening catch blocks, widening permissions, or adding unsafe blocks. Treat each of those as a defect.
- For a live service, run old and new side by side and compare before shifting traffic, and keep an immediate fallback.
- While old and new paths coexist, label which one is active and state what retires the old one.

## Backing a change out

- Separate the target change from everything else before editing. Where unrelated changes share files, restore by patch. A checkout or reset of the whole file discards the other work.
- A forward fix is often smaller and clearer than reverting history. Compare both.
- Reverting code does not revert data, schema, caches, or anything already sent to an external system. List what stays changed and how it is reconciled.
- Regenerate generated files with the project's generator. Hand-editing them back drifts from the source.

## Report

- The operation sequence, the recovery method per step, reconciliation results, and what could not be verified.
