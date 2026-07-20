Task Order — Backout and Rollback

Objective

Safely unwind an unwanted change, update, migration, deployment, generated artifact, or partial implementation while preserving unrelated work and keeping destructive actions behind explicit User approval.

Procedure

1. Read `AGENT_PROJECT.md` for active stack, commands, version-control policy, branch policy, backout policy, approval boundaries, verification profiles, and critical surfaces. Consult `STATEMENT_OF_WORK.md` only when canonical project terms or omitted details matter.
2. Identify the backout target:
   - commit, branch, patch, file set, dependency update, config change, generated artifact, migration, deployment, or mixed change
   - requested end state and last known good behavior
   - whether the User wants restoration only, a forward fix, or an investigation first
3. Inspect current repository state before editing:
   - current branch and default branch if Git is available
   - staged, unstaged, untracked, and ignored relevant files
   - files changed by the target and files changed by others
   - generated artifacts, lockfiles, migrations, data stores, deploy state, and critical surfaces
4. Classify the backout:
   - code-only
   - configuration or environment
   - dependency or lockfile
   - generated artifact
   - data, schema, or migration
   - deployment or release
   - mixed or unclear
5. Choose the least risky restoration method. Prefer a forward fix when it is smaller, clearer, and safer than reverting history. Use patch-based restoration when unrelated local changes share the same files. Do not use destructive VCS commands, data rollback, migration rollback, deploy rollback, branch deletion, reset, clean, or force push without explicit User approval.
6. Present a short backout plan before editing when Git is unavailable, the repository is not clean, the target is unclear, the branch policy is missing, or the backout touches data, schema, deployment, credentials, external systems, or other hard-to-reverse state. Include affected files or systems, unrelated changes to preserve, exact target state, recovery point or explicit declaration that none exists, tested restore or forward-recovery method, reconciliation checks, stop metrics, preservation window for old state, exact operation sequence, approvals needed, verification commands, and expected residual risk.
7. Apply only the approved restoration. Preserve unrelated user changes. Do not overwrite local work to make the backout easier.
8. Rebuild or regenerate artifacts only when the backout affects generated outputs and the project has an approved build-all or generator command.
9. Run the relevant verification profile or commands. For visual/user-facing work, also use `practice_guides/visual_verification.md` when screenshots, rendering, layout, or browser behavior are material.
10. Update `TODO.md` only for unresolved follow-up work. Record durable backout choices in `DECISIONS.md` when the project selects a rollback strategy, keeps a pin, reverses a migration path, or changes branch policy.

Acceptance Criteria

- The target change and desired end state were identified.
- Current worktree and branch state were inspected before restoration.
- Unrelated changes were preserved or explicitly called out before any risky edit.
- Destructive VCS, data, migration, deploy, or reset operations were not run without explicit User approval.
- Data, schema, deploy, credential, or external-state backouts used an approved exact recovery or containment plan.
- The applied restoration matches the approved scope.
- Relevant generated artifacts, lockfiles, docs, and tests were updated when necessary.
- Verification ran, or blockers and residual risk were reported.

Notes

- Backout is not the same as "reset to old". In shared or dirty worktrees, a minimal forward fix or patch restore is often safer than history manipulation.
- The names `main` and `master` are project facts, not assumptions. Inspect the repository or ask.
- If the backout affects production data, external systems, credentials, or deployments, route through `practice_guides/migration_safety.md` and stop for approval that references the exact plan before acting.
- Same-author tests are useful evidence but not independent proof. Inspect the behavior or assertions relevant to the backout.
- A retained restoration may proceed through `review` and `audit`; any commit is
  a separate authorized version-control effect.
