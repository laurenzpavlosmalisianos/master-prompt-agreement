---
name: mpa-database
description: "Checks for database access and handwritten SQL. Use when changing credentials, roles, grants, row-level security, tenancy, connection pooling, backups, or replication, or when writing raw SQL, DDL, or queries built from input. Pair with mpa-migration for schema migrations or rollbacks."
---

# Database

Dialect, isolation, planner, and collation behaviour differ by engine and version. Test behaviour-sensitive changes on the engine in use; SQLite or an in-memory adapter is not a substitute.

## Identity, tenancy, and pooling

- Separate runtime, migration, reporting, admin, backup, replication, and CI roles; the runtime role is neither a superuser nor the schema owner. An ORM, managed service, private subnet, or container network is not evidence that the database is secured.
- Rotation and revocation must work while the deployment pipeline is down, and pooled connections holding a revoked credential must be closed.
- Derive tenant context from server-side state (`mpa-secure-coding`), fail closed when missing, and identify every role or path that bypasses row-level security (including table owners on PostgreSQL unless `FORCE ROW LEVEL SECURITY` is set).
- A pooled connection reused across roles or tenants carries state: role, search path, session variables, temporary objects, prepared statements. Reset it or do not share.
- Tenant isolation must hold in joins, subqueries, batch exports, caches, replicas, search indexes, and restored backups. Test cross-tenant denial through the real runtime role and connection path.
- Keep tenant, row-level-security, soft-delete, and privacy filters intact in every changed query.

## Queries

- Parameters cannot carry identifiers or SQL keywords. Choose any dynamic table, column, sort direction, operator, or JSON path from a server-side allowlist and quote identifiers with the engine's quoting.
- Model-generated SQL is untrusted input. Run it through a read-only, least-privilege path with statement-type allowlisting, no multi-statement input, and time and row limits; bind any write approval to the exact statement. A query that parses, plans, or executes is not shown to be authorized or correctly scoped.
- `EXPLAIN ANALYZE` executes the statement. Run it on mutating SQL only inside a rolled-back transaction or on a disposable database, and confirm whether a given `EXPLAIN` form executes on the engine in use.
- Correctness traps: `NOT IN` against a set containing `NULL` returns no rows; a `WHERE` filter on the right-hand table of a `LEFT JOIN` turns it into an inner join; `DISTINCT` can hide a broken join; pagination needs a unique sort key; small fixtures do not predict production query plans.

## Concurrency

- When validity or authorization depends on mutable rows, check and write in one transaction at an isolation level that prevents lost updates and write skew, and test concurrent denial.
- Retry whole transactions, not single statements, accounting for side effects first; after a timeout the commit may have happened.
- For queued or delayed work, re-check authorization at execution time. A local transaction does not make a remote side effect atomic.
- Do not rely on wall-clock order across nodes.

## Derived copies and recovery

- Caches, projections, search and vector indexes, and exports keep the classification, tenant scope, and access rules of their source; search and vector retrieval enforce authorization at query time.
- Preview or dry-run destructive writes, deletes, backfills, or re-indexes, and verify recovery (`mpa-migration`). Where loss of a whole account is in scope, keep an immutable backup copy isolated from the primary account.
- Production migrations, destructive statements, restores, failover, grants, and credential rotation need approval for the exact action (`mpa-migration`).
- Log query fingerprints, not bound literals (`mpa-data-privacy`).
