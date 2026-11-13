# Changelog

## 7.0.0 - 2026-11-13

Projects set up with 6.x follow `docs/migrating-from-v6.md`. There is no automatic conversion.

### Added

- `mpa.py` with `init`, `update`, and `check`. Without `--write` it prints its plan and changes nothing.
- A marked "Working agreement" block in `AGENTS.md` that carries the version.
- Project facts in `AGENTS.md`: Project, Commands, Approvals, Code latitude, Constraints.
- A `CLAUDE.md` that imports `AGENTS.md`.
- Task guides as Agent Skills under `.claude/skills/mpa-*` and `.agents/skills/mpa-*`, in the groups core, security, infra, web, and languages.
- Permission presets for Claude Code (`.claude/settings.json`) and Codex (`.codex/config.toml`, `.codex/rules/mpa.rules`).
- `--state local|tracked|none` for `TODO.md`. The default keeps it out of git.
- `tools/hygiene.py`, which checks repository files, staged content, and commit messages for secrets, local data, links, and working files.

### Changed

- Python 3.10 or newer is required. Only the standard library is used.
- Setup in a project with an existing `AGENTS.md`, `CLAUDE.md`, or `.claude/settings.json` adds to those files and keeps their content.
- A project needs no access to a checkout of this repository at run time.
- `TODO.md` has no header fields or counters.
- There is one version number.

### Removed

- `STATEMENT_OF_WORK.md`, `AGENT_PROJECT.md`, `AGENT_ENTRYPOINT.md`, `PROJECT_INPUT.json`, `PROJECT_INSTANCE.json`, and the annex files.
- `master_service_agreement.md`, `runtime/`, `task_orders/`, `practice_guides/`, `conformance/`, `integrations/`, `examples/`, and `scripts/`.
- Transactional setup, refresh, recovery, backout bundles, and the `.mpa-bootstrap*` files.
- Source and review state templates and their scripts.
- Runtime wrapper skills and `.claude/agents` templates.
- The `DECISIONS.md` template. Lasting choices are lines under `## Constraints` in `AGENTS.md`.
