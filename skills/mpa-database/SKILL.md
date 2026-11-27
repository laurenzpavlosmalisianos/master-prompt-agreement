---
name: mpa-database
description: "Checks for database access and handwritten SQL. Use when changing credentials, roles, grants, connection pooling, transactions, or backups, or when writing raw SQL, DDL, or queries built from input. For schema migrations or rollbacks, use mpa-migration."
---

# Database

Dialect, isolation, planner, and collation behaviour differ by engine and version. Test behaviour-sensitive changes on the engine in use; SQLite or an in-memory adapter is not a substitute.

## Identity, tenancy, and pooling

- Rotation and revocation must work while the deployment pipeline is down, and pooled connections holding a revoked credential must be closed.

## Queries

- Model-generated SQL is untrusted input. Run it through a read-only, least-privilege path with statement-type allowlisting, no multi-statement input, and time and row limits; bind any write approval to the exact statement. A query that parses, plans, or executes is not shown to be authorized or correctly scoped.

## Concurrency

- When validity or authorization depends on mutable rows, check and write in one transaction at an isolation level that prevents lost updates and write skew, and test concurrent denial.
- Do not rely on wall-clock order across nodes.

## Derived copies and recovery

- Preview or dry-run destructive writes, deletes, backfills, or re-indexes, and verify recovery. Where loss of a whole account is in scope, keep an immutable backup copy isolated from the primary account.
- Production migrations, destructive statements, restores, failover, grants, and credential rotation need approval for the exact action.
