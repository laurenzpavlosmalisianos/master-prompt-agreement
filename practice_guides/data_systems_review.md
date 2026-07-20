# Data Systems Review Practice Guide

Use this Practice Guide when designing, changing, or reviewing data-intensive behavior: storage choices, data models, queues, streams, caches, analytics, search or vector indexes, replication, sharding, managed data services, local-first sync, or distributed access control. For SQL-backed backend security, also use `backend_database_security.md`.

Before source-sensitive data-system recommendations, use project `SOURCE_PACKS.md` and `SOURCE_UPDATE.md` when present; check current official docs, release notes, changelogs, migration guides, security or advisory pages, and version-scoped implementation docs for the selected engine, driver, ORM, queue/stream, cache, search/vector store, object store, cloud service, and relevant privacy or security authority.

## Best Use Cases

- choosing or replacing a database, queue, cache, object store, search system, analytics store, or vector index
- changing data ownership, source-of-truth rules, replication, partitioning, or consistency behavior
- adding derived data such as projections, materialized views, search indexes, embeddings, or data frames
- designing multi-zone, multi-region, multi-provider, offline-capable, or local-first behavior
- reviewing data correctness, recovery, privacy, retention, or user-agency tradeoffs

## Workflow

1. Define the workload and invariants.

- List entities, data sources, sinks, readers, writers, administrators, trust boundaries, lifecycle, retention, and deletion rules.
- Capture read, write, update, scan, analytical, search, replication, export, and administrative paths, with the authorization boundary for each.
- State expected load, growth, latency, freshness, durability, availability, and recovery-point and recovery-time objectives.
- Name correctness invariants that must survive retries, crashes, concurrent writers, and partial failure.
- When authorization or business validity depends on mutable database state, evaluate the predicate and perform the write in one transaction at an isolation level that prevents the relevant anomaly. Test concurrent denial cases, lost updates, write skew, duplicate delivery, ambiguous commit, and retry after timeout.
- For database-backed services, include connection paths, roles, migration authority, backup/restore path, and tenant boundary when they affect the design.

2. Choose primitives by access path, not fashion.

- Compare the needed data primitive or model: relational, document, key-value, graph, search, vector, data frame, log, object, or file.
- Check indexes, sort keys, partition keys, row versus column layout, and read/write amplification.
- Separate application-level requirements from managed-service promises.
- For current service behavior, route through `source_grounded_research` or `source_freshness_review`; monitor the smallest useful official parent root or feed, not broad domains.

3. Make tradeoffs explicit.

- Evaluate reliability, scalability, maintainability, latency, throughput, cost, and human operational load.
- Consider scale-up, scale-out, and scale-down behavior; cheap idle operation may matter as much as peak throughput.
- State the consistency model and what anomalies users or downstream systems can observe.
- Treat multi-zone, multi-region, multi-provider, and decentralized designs as tradeoffs, not badges.

4. Check distributed failure assumptions.

- Consider crashes, network partitions, long message delays, retries, duplicate delivery, reordering, and partial writes.
- Do not rely on wall-clock ordering unless the project has proven clock and trust guarantees.
- Check leader election, quorum, failover, split-brain, backpressure, timeout, and replay behavior where relevant.
- For subtle protocols, access-control races, or state machines, also use `logical_spec_review`.

5. Review data movement and derived data.

- Identify the authoritative source for each data domain, every derived copy, the transformation or producer version that creates it, and the classification, tenant scope, and access policy each copy must preserve.
- Check idempotency, ordering, schema evolution, backfills, replay, compaction, and deletion propagation.
- For schema changes, data migrations, storage rewrites, compatibility breaks, or hard-to-reverse data changes, also use `migration_safety.md`.
- Verify cache invalidation, search/vector-index freshness, and analytical snapshot boundaries.
- For search or vector retrieval, verify query-time authorization and tenant partitioning where required, plus embedding, model, and chunking versioning where used, and a re-index or rollback path.
- Record how corruption, drift, or stale derived data is detected and repaired.

6. Review privacy, ethics, and agency.

- Record the project or legal owner's determination for purpose, lawful basis, residency, retention, and deletion obligations. Do not infer legal sufficiency.
- Check data classification, sensitive-data minimization, auditability, access logging, export, deletion, and deletion-propagation evidence.
- Keep public review output sanitized: do not include secrets, raw personal data, customer identifiers, private dataset samples, credential paths, or sensitive operational details unless the project explicitly authorizes that disclosure.
- Identify lock-in, portability, and user-data access consequences when they affect the decision.
- Surface societal, reputational, compliance, or user-harm risks as engineering tradeoffs, not afterthoughts.

7. Translate decisions into verification.

- Define acceptance checks for correctness invariants, migration safety, recovery, and observability.
- Prefer representative load, replay, backfill, restore, failover, and consistency tests over purely happy-path tests.
- For reviews, report checks actually run, artifacts observed, metrics inspected, and unverified gaps; do not replace evidence with a proposed plan.
- For each high-risk change, name the observable signal, stop or rollback threshold, responsible owner, and containment or recovery action. Do not require a dashboard when existing logs, queries, alerts, or monitoring provide equivalent evidence.

## Output

Provide:

1. workload and access-path summary
2. source-of-truth and derived-data map
3. chosen primitives and rejected alternatives
4. explicit tradeoff table
5. consistency, failure, and recovery assumptions
6. privacy, retention, and portability risks
7. verification plan, acceptance evidence or missing-evidence gaps, and stop conditions

## Guardrails

- Do not choose data technology by popularity, novelty, or vendor default.
- Do not treat a managed-service SLA as proof that the application-level design is reliable.
- Do not assume sharding, multi-region, multicloud, serverless, vector search, or local-first sync is needed without workload evidence.
- Do not hide operational cost or human maintenance cost behind architecture diagrams.
- Do not claim data safety without an appropriate tested recovery class—rollback/restore, forward recovery, rebuild/regeneration, containment, or an explicitly approved irreversible plan—plus corruption detection and replay or backfill evidence where those paths exist.
- Do not run destructive writes, deletes, migrations, backfills, compactions, re-indexes, or retention jobs without explicit approval, scoped preview or dry-run where possible, and evidence for the selected recovery class. An irreversible plan must state the owner, loss boundary, containment, stop conditions, and verification rather than inventing a rollback.
