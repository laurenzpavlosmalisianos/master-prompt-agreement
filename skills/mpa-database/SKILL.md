---
name: mpa-database
description: Checks for database access and handwritten SQL. Use when changing credentials, roles, grants, row-level security, tenancy, connection pooling, backups, or replication, or when writing raw SQL, DDL, or queries built from input.
---

# Database

Dialect, isolation, planner, and collation behaviour differ by engine and version. Test behaviour-sensitive changes on the engine in use. SQLite or an in-memory adapter is not a substitute for it.

## Identity and exposure

- Each service has its own runtime role, separate from the migration, reporting, admin, backup, replication, and CI roles. The runtime role is not a superuser or the schema owner.
- Rotation and revocation must work while the deployment pipeline is down, and pooled connections that hold a revoked credential must be closed.
- An ORM, a managed service, a private subnet, or a container network is not evidence that the database is secured.

## Tenancy and pooling

- Tenant context comes from authenticated server-side state and fails closed when missing. Identify every role or path that bypasses row-level security or tenant predicates.
- A pooled connection reused across roles or tenants carries state: role, search path, session variables, temporary objects, prepared statements. Reset it or do not share.
- Tenant isolation also has to hold in joins, subqueries, batch exports, caches, replicas, search indexes, and restored backups. Test cross-tenant denial through the real runtime role and connection path.
- Keep tenant, row-level-security, soft-delete, and privacy filters intact in every changed query.

## Queries

- Parameters cannot carry identifiers or SQL keywords. A dynamic table, column, sort direction, operator, or JSON path is chosen from a server-side allowlist; quote table and column names with the engine's identifier quoting.
- Model-generated SQL is untrusted input. Run it through a read-only, least-privilege path with an allowlist of statement types, no multi-statement input, and time and row limits. Bind any write approval to the exact statement.
- A query that parses, plans, or executes has not been shown to be authorized or correctly scoped.
- `EXPLAIN ANALYZE` executes the statement. Run it on mutating SQL only inside a transaction that is rolled back or on a disposable database, and confirm for the engine whether a given `EXPLAIN` form executes.
- Correctness traps: `NOT IN` against a set containing `NULL` returns no rows; a `WHERE` filter on the right-hand table of a `LEFT JOIN` turns it into an inner join; `DISTINCT` can hide a wrong join; pagination needs a unique sort key.
- Small fixtures do not predict production query plans.

## Concurrency

- When validity or authorization depends on mutable rows, check and write in one transaction at an isolation level that prevents the relevant anomaly. Check-then-act across transactions allows lost updates and write skew. Test concurrent denial, not only the single-caller path.
- Retry whole transactions, not single statements, and account for side effects before retrying. After a timeout the commit may have happened.
- For queued or delayed work, check authorization again at execution time. A local transaction does not make a remote side effect atomic.
- Do not rely on wall-clock order across nodes.

## Derived copies and recovery

- Caches, projections, search and vector indexes, and exports keep the classification, tenant scope, and access rules of their source. Search and vector retrieval enforce authorization at query time.
- Before a destructive write, delete, backfill, or re-index, preview the scope or do a dry run, and name how it would be recovered. If it cannot be, say so.
- A claim that data is safe needs a tested restore. Where loss of a whole account is in scope, keep an immutable copy isolated from the primary account.
- Production migrations, destructive statements, restores, failover, grants, and credential rotation need approval for the exact action. For migrations see the `mpa-migration` skill.
- Query logs, telemetry, and agent traces hold literals and personal data. Log query fingerprints, not bound values.
