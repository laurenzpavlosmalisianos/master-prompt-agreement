# Migrating from version 6

Version 7 has no compatibility layer, alias, or converter. A project set up with 6.x is migrated by hand, once. `mpa.py init` refuses a project that still holds the 6.x entrypoint text.

1. Commit or stash everything so the work tree is clean.
2. Copy the facts still in use from `AGENT_PROJECT.md` or `STATEMENT_OF_WORK.md` into a scratch file outside the repository: commands, constraints, approval rules, security rules. Add the entries of `DECISIONS.md` that still apply.
3. Delete the generated files: `STATEMENT_OF_WORK.md`, `AGENT_PROJECT.md`, `AGENT_ENTRYPOINT.md`, `PROJECT_INPUT.json`, `PROJECT_INSTANCE.json`, `COMMUNICATION.md`, `CAPABILITIES.md`, `AUTHORITY.md`, a generated `SECURITY.md` annex, `FINDINGS.md`, `PRECEDENTS.md`, `*_FEEDBACK.md`, `SOURCE_*.md`, `SECURITY_VERIFICATION.md`, `DELEGATED_COMMUNICATIONS_COVERAGE.md`, `VIDEO_DELIVERABLE_QA.md`, `VISUAL_ASSET_QA.md`, `AUTOMATION_ORDERS.json`, and any `.mpa-bootstrap*` file.
4. In `AGENTS.md` and `CLAUDE.md`, delete the generated sections (recovery guard, inlined charter, "Project Contract and Workflows") and keep text written for the project. Delete the file if nothing remains.
5. Delete generated wrappers: `.agents/skills/master-prompt-*`, `.codex/skills/` entries, and `.claude/agents/` files that version 6 generated.
6. In `TODO.md`, delete the header lines above the title (`state_schema_version`, counters, origin comment). Version 7 does not read `DECISIONS.md`; keep it as a project file or delete it.
7. Run `python3 -B /path/to/master-prompt-agreement/mpa.py init . --preset`, read the plan, and run it again with `--write`. Pass `--state tracked` if `TODO.md` is committed.
8. Move the facts from step 2 into `## Commands`, `## Approvals`, and `## Constraints` in `AGENTS.md`. A lasting choice is one line under `## Constraints`.
9. Remove references to the version 6 scripts from CI, cron, and task runners, and drop any `--add-dir` argument that pointed at the version 6 checkout.
10. Run `python3 -B /path/to/master-prompt-agreement/mpa.py check .` and commit.

## Where things are in version 7

| Version 6 | Version 7 |
|---|---|
| Statement of Work, `AGENT_PROJECT.md` | Project facts in `AGENTS.md` |
| Operative Charter, Master Service Agreement | The "Working agreement" block in `AGENTS.md` |
| Task Orders and Practice Guides | Skills under `.claude/skills/mpa-*` and `.agents/skills/mpa-*` |
| Standing Grants, approval tables | `## Approvals` in `AGENTS.md` |
| Security annex | Lines under `## Constraints` |
| `scripts/project_bootstrap.py`, `scripts/project_refresh.py` | `mpa.py init`, `mpa.py update`, `mpa.py check` |
| Refresh backout bundles | `git diff` and `git revert` |
