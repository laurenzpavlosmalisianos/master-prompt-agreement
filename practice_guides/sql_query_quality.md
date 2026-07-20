# SQL Query Quality Practice Guide

Use this Practice Guide when a task touches handwritten SQL, schema DDL, views, functions, triggers, stored procedures, migrations' SQL text, ORM query shape, reporting queries, query performance, data correctness, transaction behavior, or SQL review. Pair it with `backend_database_security.md` for exposure, credentials, grants, tenant isolation, generated SQL authorization, backups, restores, and natural-language-to-query execution. Pair it with `data_systems_review.md` for storage selection, replication, consistency architecture, streams, search, vector, or derived-data design. Pair embedded or file-backed local stores with `secure_development.md` for filesystem identity, symlink, permission, lock-file, atomic-write, backup/export, and local-tool access checks.

Before source-sensitive SQL recommendations, use project `SOURCE_PACKS.md` and `SOURCE_UPDATE.md` when present, then check official docs, release notes, planner docs, migration guides, driver docs, ORM docs, and managed-service docs for the selected engine and version. Treat SQL dialect, isolation behavior, planner behavior, collations, JSON features, generated columns, indexes, extensions, and ORM translation as version- and engine-sensitive.

## Workflow

1. Frame the engine and query contract.

- identify the target database engine, version, service, schema, connection role, migration tool, driver, ORM, transaction boundary, isolation level, and production-like test surface
- distinguish PostgreSQL, SQLite, MySQL, MariaDB, SQL Server, cloud warehouse, embedded database, and ORM dialect behavior; do not treat generic SQL as executable truth
- for embedded database files, identify the database path, state directory, lock path, journal or WAL side files, backup and export paths, file permissions, filesystem trust boundary, and whether agents or helper tools read the store directly or only through a minimized interface
- inspect schema, constraints, indexes, views, triggers, functions, generated columns, partitions, collations, time zone policy, session settings, and representative data shape before changing queries
- capture behavior-changing connection state such as autocommit, connection-pool reset behavior, default schema or search path, engine modes, PRAGMAs, statement and lock timeouts, read/write routing, and session `SET` options where relevant
- map read, write, migration, reporting, and administrative paths to authorization and transaction boundaries
- state expected cardinality, ordering, null behavior, duplicate handling, freshness, latency, and lock sensitivity

2. Preserve correctness before optimizing.

- verify joins, predicates, grouping, aggregation, window functions, CTEs, set operations, pagination, stable ordering, and duplicate semantics against representative edge cases
- test nulls, empty sets, missing relations, duplicate keys, time zones, daylight-saving changes, collation, precision, rounding, and boundary timestamps where relevant
- check common correctness footguns such as `NOT IN` with `NULL`, `COUNT(*)` versus `COUNT(column)`, null-returning aggregates, `LEFT JOIN` predicates moved into `WHERE`, `DISTINCT` hiding bad joins, non-unique pagination order, default window frames, inclusive versus exclusive timestamp ranges, and non-sargable date or function predicates
- use constraints, foreign keys, unique indexes, checks, exclusion constraints, and `NOT NULL` where the database must enforce invariants
- keep application validation and database constraints aligned; do not rely on application-only validation for persisted invariants
- avoid depending on implicit row order, implicit casts, engine-specific truthiness, or ORM-generated query shape without verifying the generated SQL

3. Review transaction, migration, and concurrency behavior.

- identify which reads and writes must be atomic and which anomalies the isolation level permits
- test lost updates, write skew, duplicate inserts, stale reads, retry behavior, lock waits, deadlocks, idempotency, and partial failure where the change affects them
- retry whole transactions rather than isolated failed statements when the engine requires it, and account for idempotency plus external side effects before retrying
- for embedded stores, review application-level locks, database transaction mode, journal or WAL side files, crash recovery, concurrent readers and writers, and whether migrations preserve private permissions and path identity
- design migrations with forward path, rollback or fix-forward path, transaction mode, implicit commits, statements that must run outside a transaction, lock impact, backfill strategy, validation query, and deploy ordering
- separate schema changes, data migrations, and application rollout assumptions
- avoid destructive migrations, broad updates, or table rewrites without explicit approval, backup/restore confidence, and blast-radius review

4. Review performance with evidence.

- use `EXPLAIN`, `EXPLAIN ANALYZE`, query planner output, or engine-specific profiling only against appropriate environments and with side effects understood; label estimated versus actual execution evidence
- check indexes, selectivity, statistics, join order, scans, sorts, materialization, N+1 behavior, batching, connection pool effects, and parameter-sensitive plans
- include privacy-safe representative bind values or value classes, row-estimate versus actual gaps, statistics freshness, cache or warmup caveats, and mutating-statement rollback boundaries when presenting plan evidence
- do not add indexes mechanically; account for write cost, lock cost, storage, maintenance, and query mix
- verify pagination, limits, offsets, keyset pagination, and result streaming for large tables
- state when local or small-fixture performance evidence cannot predict production behavior

5. Handle security-relevant query boundaries.

- use parameterized queries or safe ORM binding for untrusted values; never build SQL by concatenating untrusted strings
- verify parameterization uses driver or ORM bind APIs rather than application string construction; note client-side prepare emulation where it affects security, logging, plan caching, or permissions
- when identifiers, sort directions, operators, collations, table names, function names, raw predicates, JSON paths, or `ORDER BY` choices must be dynamic, allowlist them separately from values and use engine or driver quoting APIs where available
- route credentials, grants, tenant isolation, generated-query authorization, destructive-query approval, admin access, and backup/restore concerns through `backend_database_security.md`
- for local embedded SQL engines, parameterization is necessary but not sufficient; verify private file permissions, symlink rejection, state-directory ownership, lock-file safety, and minimized read surfaces for agent or helper access
- do not defer query-local authorization predicates, row-level-security or tenant filter preservation, soft-delete filters, privacy filters, or parameterization review solely because a security guide also applies
- verify that query changes preserve tenant, row-level security, soft-delete, retention, privacy, and audit filters when applicable
- do not expose raw database errors to user-facing surfaces without review

6. Verify with the target engine.

- run project SQL tests, migration dry runs, rollback or fix-forward checks, representative fixtures, and ORM generated-SQL inspection where configured
- use the target engine for behavior-sensitive tests; do not substitute SQLite or an in-memory adapter unless that is the target or the difference is explicitly irrelevant
- verify result shape, column names, data types, ordering, and cardinality for consumers
- capture before/after plans or timings only when performance is part of the acceptance contract
- state clearly when database version, data volume, permissions, planner statistics, or managed-service behavior could not be verified

## Output

Provide:

1. database engine, version, schema, driver or ORM, migration tool, transaction, and exact non-sensitive official docs, release notes, planner docs, driver/ORM docs, and source facts used for behavior-sensitive claims
2. affected query, DDL, migration, result-shape, transaction, index, and consumer contracts
3. correctness, null, ordering, concurrency, lock, migration, parameterization, and performance risks
4. target-engine tests, migration checks, generated-SQL inspection, plan analysis, and security-boundary checks run
5. unverified engine, data-volume, permission, isolation, planner, and service states plus residual risk

## Guardrails

- Do not treat one SQL dialect as portable unless the project has tested the target engines.
- Do not use SQLite as a behavioral substitute for another database when transactions, typing, constraints, JSON, collation, locking, or planner behavior matters.
- Do not concatenate untrusted SQL values or identifiers.
- Do not claim performance improvement without target-engine plan or measurement evidence proportionate to the claim.
- Do not make destructive schema or data changes without explicit approval, rollback or fix-forward reasoning, and recovery evidence.
