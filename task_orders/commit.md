Task Order — Commit

Objective

Commit the exact approved change set with a message written for cross-session continuity.

Precondition

Use this Task Order only for Git-backed projects. If the project uses another VCS, stop and use a VCS-specific adapter that defines that system's status, staged snapshot, tree identity, commit, and rollback semantics.

Procedure

1. Read `AGENT_PROJECT.md` for Version Control Rule, Branch Rule, approval boundaries, commit disclosure, and project commit-message requirements. Consult `STATEMENT_OF_WORK.md` when those fields are omitted, unclear, or inconsistent.
2. Confirm that the current User request or standing grant authorizes this exact commit, not only the underlying edits, staging, or review.
3. Run `git status --short --branch` to identify staged, unstaged, untracked, and branch state.
4. Identify the exact approved change set. Preserve unrelated work and do not stage files merely because they are pending.
5. Review unstaged changes, intended untracked files, and any already staged changes. Use `git diff` for working-tree changes and `git diff --cached` for the staged snapshot.
6. Update `TODO.md` before staging when the TODO change belongs in this commit. Otherwise leave TODO edits for a separately authorized follow-up commit.
7. Stage only approved files or hunks. Do not stage files that contain secrets (.env, credentials, API keys), unrelated local work, or generated artifacts outside the approved scope.
8. Review `git diff --cached`, the staged file list, and the project secret or policy check when available. Run `git diff --cached --check`.
9. Record the final staged tree identity before committing when Git is the active VCS: `git write-tree`. Run or validate acceptance evidence against that staged tree, preferably through a temporary worktree or equivalent isolated materialization when partial staging, generated files, or hook side effects could matter. If staging changes after this point, repeat staged review and relevant checks.
10. Read recent `git log` to match the repository's commit message style.
11. Write a commit message that a future Agent session can use to understand:
   - What changed.
   - Why it changed.
   - What architectural decisions were made.
12. Commit. If a hook aborts the commit, no history repair is needed; review the hook output, changed files, and staged tree before retrying. If the commit succeeds but the committed tree differs from the reviewed staged tree, mark the commit nonconforming, do not amend, reset, revert, or create another commit automatically, and request authorization for the specific corrective operation. Do not add Co-Authored-By, co-author metadata, or AI-use disclosure unless the SOW requires it. If required, use the SOW-defined location and content.
13. Verify the committed tree matches the reviewed staged tree when Git is the active VCS. If it does not, report the expected tree, actual commit tree, suspected hook or staging cause, and the authorization needed for correction.
14. Run `git status --short` and report remaining changes, if any.
15. Report: files committed, commit hash, one-line summary.

Acceptance Criteria

- The exact approved change set is committed.
- The committed tree matches the reviewed and checked staged tree. If it does not, the nonconforming commit is reported and no history-changing correction is performed without separate authorization.
- No secrets or credentials were detected within the checked scope.
- Commit message is descriptive and explains the "why."
- `TODO.md` was reviewed when it exists or is required; any needed active-state update was included only when authorized and in scope, otherwise reported as a separate state-maintenance candidate.
