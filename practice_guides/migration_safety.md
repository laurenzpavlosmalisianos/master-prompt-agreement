# Migration Safety Practice Guide

Use this Practice Guide for schema changes, data migrations, storage rewrites, protocol changes, credential moves, deployment migrations, compatibility breaks, and other changes whose compatibility or recovery behavior must be controlled.

When compatibility, deprecation, migration behavior, protocol, ABI, runtime, framework, compiler, database, or hardware claims are version-sensitive, inspect project pins and approved source packs first, then verify the decisive claims against current version-matched primary sources. Record the affected versions and source anchors in the output, or state that the evidence is unavailable.

For large AI-assisted ports, framework rewrites, language migrations, generated refactors, or compatibility-preserving reimplementations, also load the relevant language guide, `testing_strategy_quality.md`, `source_originality_review.md`, and `secure_development.md`. A passing inherited test suite is evidence, not proof that the migrated system preserves architecture, security, performance, or undocumented compatibility behavior.

## Workflow

For a large language, runtime, framework, or generated-code port or compatibility-preserving reimplementation, apply this feasibility gate before entering the workflow:

- identify the observed project pain, expected benefit, and evidence for both
- distinguish a structure-preserving migration from a redesign
- for structure-preserving or compatibility-preserving work, establish whether a viable parity oracle exists at a stable external boundary and whether relevant tests can survive independently of source internals
- for a redesign, define independently approved acceptance and transition oracles; do not use drop-in parity as its sole acceptance basis
- assess recovery posture and the expected verification burden before committing to broad translation
- record a migrate-now, migrate-later, or no-action verdict with its decisive evidence; no action is a valid result

Continue with the numbered workflow only when the feasibility evidence supports migration now.

1. Define the migration class.
- schema only
- schema plus data
- protocol or API compatibility
- one-way state transform
- credential, deployment, or external-state migration
- language, runtime, framework, or generated-code port
- compatibility-preserving reimplementation

2. Map the blast radius.
- affected readers and writers
- backward and forward compatibility
- deployment ordering constraints
- rollback feasibility
- recovery class: rollback/restore, forward recovery/rebuild/regeneration, containment, or explicitly accepted irreversible plan
- data-loss paths
- source-of-truth, source-trust, and private-data exposure paths for inputs, generated mappings, backups, exports, logs, fixtures, staging, and rollback artifacts
- security boundary changes, memory-safety boundary changes, unsafe escape hatches, and privileged behavior
- exact-output, wire-format, compression, serialization, parser, linking, ABI, namespacing, and caller-compatibility assumptions
- inherited test coverage versus behavior newly introduced by the migration
- for language, runtime, framework, or generated-code ports, a source-to-target inventory: source module, API, behavior, fixture, or test; target owner and location; compatibility oracle; status; and intentional divergence
- when target-semantic gap sites are mechanically enumerable, reconcile every enumerated site to the source-to-target inventory, keep unresolved sites explicitly unknown and conservative, and do not treat lexical discovery as proof of semantic completeness
- when dependencies are mechanically discoverable for a large port and sequencing, partitioning, or ownership materially depends on their topology, derive the dependency graph and strongly connected components at both source-unit and target-package or target-module boundaries; validate the extraction against bounded source samples, keep dynamic or unknown dependencies explicit, and stop dependency-based sequencing when extraction remains unreliable
- ownership, lifetime, aliasing, allocation, drop/free, thread-transfer, and FFI or resource-boundary map when source and target resource models differ
- when old and new implementations coexist, label which path is active, which path is reference or oracle material, the divergence policy, mismatch authority, and retirement or retention criteria

3. Define the safe sequence.
- preconditions
- rollout order
- dual-write or compatibility window if needed
- verification steps at each phase
- proof that migrated state is complete before deleting, disabling, or ignoring old state
- rollback, restore, forward-recovery, rebuild, regeneration, or containment plan
- reconciliation checks and stop metrics
- preservation window for old state
- differential testing, fixture replay, reference-output corpora, compatibility tests, security regression tests, performance baselines, and canary comparison when available
- architecture-specific correctness and performance checks when CPU, compiler, SIMD, platform library, or hardware behavior could affect results
- diagnostic work queue for compiler, type-checker, linter, sanitizer, or verifier failures: deduplicate by root cause, preserve representative failing output, start with the earliest unique diagnostic, and stop or escalate when iterations repeat without shrinking the error class

4. Check failure modes.
- partial migration
- old binaries against new state
- new binaries against old state
- retries and idempotency
- long-running or interrupted jobs
- bug-for-bug translation that preserves latent defects
- generated code that compiles by weakening types, widening permissions, adding unsafe blocks, broadening catches, or bypassing framework primitives
- tests that assert old behavior without checking whether the behavior is still intended
- memory-safe replacement that removes one exploit class but changes exact bytes, timing, resource use, hardware instruction selection, or compatibility expectations

5. Recommend the smallest safe plan.
- exact change order
- exact checks
- stop conditions
- exact operation sequence that needs approval when the migration is hard to reverse
- irreversible plan owner, loss boundary, containment, verification, and stop conditions when no recovery path exists

## Output

Provide:

1. feasibility verdict for an applicable large port, including structure-preserving or redesign intent and the oracle and verification basis
2. migration class
3. blast radius, affected engine/runtime/protocol/tool versions, and decisive primary-source anchors when source-sensitive
4. safe sequence
5. recovery class and recovery or containment plan
6. verification steps
7. residual risks

## Guardrails

- Do not assume rollback exists.
- Do not recommend a data, schema, deploy, credential, or external-state migration as ready without a recovery class, reconciliation checks, verification, and approval tied to the exact operation sequence.
- Do not treat destructive transforms as routine refactors.
- Do not treat a large generated port as safe because it compiles or passes inherited tests.
- Do not claim a memory-safe target language eliminates security review when the migration includes unsafe blocks, FFI, process, filesystem, parser, concurrency, or privilege-boundary code.
- Do not treat a memory-safe or faster drop-in replacement as safe without compatibility, architecture, and performance evidence for the project workload.
- Prefer additive and reversible steps over one-shot rewrites.
