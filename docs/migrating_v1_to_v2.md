# Migrating From v1 To v2

Use this page for a downstream project whose framework files came from the
public pre-v2 line: the `v1.0.0` tag or a later unreleased public branch
snapshot. It defines a compatibility boundary and a reviewed manual migration
path; it is not an automatic converter.

## Scope And Compatibility Boundary

The v2 architecture changes required project files, authority projection,
bootstrap semantics, state identity, and update verification. This document
defines the incompatible `v2.0.0` compatibility boundary.

Do not run current bootstrap or current-format refresh over a v1 project. The
current tools deliberately do not reverse-parse v1 prose, infer missing project
authority, or manufacture lifecycle receipts for files they did not generate.
Preserve the project and migrate its verified intent through reviewed,
project-specific work.

## What Changed

| v1 surface or workflow | v2 replacement | Required action |
|---|---|---|
| direct setup from shared templates | transactional bootstrap for a target with no framework-generated surfaces and no selected managed-output collision | use [Getting Started](../GETTING_STARTED.md) only for a genuinely new non-colliding target |
| project instruction text centered on `CLAUDE.md`, or the later pre-v2 `AGENTS.md` surface | canonical `STATEMENT_OF_WORK.md`, generated `AGENT_PROJECT.md`, and a thin runtime entrypoint | map current project facts and authority into their v2 owners |
| project files without a generated lifecycle identity pair | retained `PROJECT_INPUT.json` plus root `PROJECT_INSTANCE.json` receipt | create a reviewed v2 instance; do not fabricate a receipt around unchanged v1 files |
| ad hoc template replacement | exact-plan, transaction-guarded refresh for complete current-format instances | use [Updating](../UPDATING.md) only after the project is a verified v2 instance |
| unreceipted `TODO.md`, `DECISIONS.md`, and `FINDINGS.md` templates | receipt-declared active state plus durable decisions with explicit identity and status | preserve useful history separately and migrate only current state and durable decisions |

These are user-visible ownership changes, not a complete development history.
The `v1.0.0` tag and later public pre-v2 branch history remain the historical
authority for those old public packages.

## Choose The Correct Path

- **New project with no framework-generated surfaces and no collision at a
  selected managed output path:** follow
  [Getting Started](../GETTING_STARTED.md).
- **Complete, verified v2/current-format project:** follow
  [Updating](../UPDATING.md).
- **Existing public pre-v2 project:** preserve it and perform the reviewed
  manual migration below.
- **Partial, malformed, inconsistent, newer, or otherwise unrecognized
  project:** preserve it and use the generic unsupported-format route in
  [Updating](../UPDATING.md#unsupported-formats).
- **Replacing the framework checkout:** select the intended local checkout
  separately. Changing that checkout does not migrate downstream project files.

## Manual Migration Checklist

1. Preserve a recoverable project checkpoint and inspect the current worktree
   before changing framework-owned files.
2. Inventory the project's actual purpose, scope, exclusions, architecture,
   commands, deliverables, acceptance checks, approval boundaries, runtime
   entrypoints, active work, and durable decisions. Treat implemented code,
   configuration, and tests as the product truth for implemented behavior.
3. Classify each v1 file and statement as current project authority, active
   state, durable rationale, historical material, obsolete framework prose, or
   unsupported claim. Do not carry an item forward merely because it existed in
   v1.
4. Map the verified current facts into the v2 owning surfaces. Keep the
   Statement of Work canonical, the project contract generated, runtime
   entrypoints thin, active state current, and history outside the always-loaded
   path.
5. Prepare the complete candidate and review its authority, paths, commands,
   state, runtime selection, and acceptance evidence before any write. Use a
   project-specific preservation and transaction plan appropriate to the
   existing repository; v2 bootstrap and refresh do not authorize this manual
   migration.
6. Apply only the reviewed replacement, then run current structural checks and
   the project's own behavioral, rendered, semantic, and manual verification as
   applicable.
7. Inspect the resulting files as project authority, not only as a passing test
   fixture. Retain the original checkpoint until the migrated project is
   accepted.

## Acceptance And Limits

After migration, the project is acceptable as a current-format instance only
when all of the following are true:

- retained input and the root instance receipt form one valid current identity;
- the generated Statement of Work, project contract, and runtime entrypoints
  synchronize;
- declared mutable state passes current state validation;
- configured conformance profiles and project-specific verification pass; and
- a human has reviewed the resulting authority, unresolved manual acceptance,
  and preservation or backout status.

For a separately established current-format candidate, the ordinary aggregate
gate is below. `<framework-ref>` MUST be the exact selected framework checkout
path as visible inside `<runner>`, including when a wrapper or container maps a
different path from the host:

```bash
<runner> <framework-ref>/scripts/conformance_check.py --profile core-project --root <project-root> --project-kind <downstream|framework-authoring> --contract-root <contract-root> --strict-warnings
```

This check does not prove that a v1 migration was automatic, lossless, or
semantically correct. It verifies current-format invariants after the
project-specific mapping and review have occurred. No compatibility shim or
legacy runtime is retained by this migration policy.
