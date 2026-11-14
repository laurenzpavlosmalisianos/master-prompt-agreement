# Changelog

## 7.1.0 - 2026-11-14

The block text changes. Run `mpa.py update` once in each installed project; until then `check` reports the block as older. In a project whose Approvals section lists only pushes to the default branch, a push of another branch now needs a yes; add a line under "No approval needed" to allow it.

### Changed

- The working agreement: an action that the Approvals section does not list needs a yes only when it takes effect outside the repository or is hard to reverse; a blocked action may be put to the user unless the user already said no; the report names what went unchecked; an absent `TODO.md` is not created.
- The Approvals template asks before every push, not only a push to the default branch, and allows commands that change nothing outside the repository in place of the commands listed under Commands. It also asks before discarding uncommitted changes, sending code or data to an external service, changing `.agents/` or `.mcp.json`, and committing when the request did not ask for a commit. Adoption adds a missing `## Code latitude` section.
- `.codex/rules/mpa.rules` is managed: `update` replaces it and `check` reports a difference. A file that is the one from 7.0.0, or that starts with the `# Managed by mpa.py` line, is replaced; any other content is refused until it moves to another `.rules` file in that directory or `--force` is passed.
- The presets ask before `git push --delete`, `-d`, and a `:branch` refspec (Claude Code), `pip uninstall`, `gh pr create`, `gh gist create`, `gh release delete`, `gh secret set`, and `gh workflow run`.
- The block carries its own version, so a release that leaves the block unchanged does not make `check` report it.
- git finds the project's repository itself, so its ownership check, `GIT_CEILING_DIRECTORIES`, and filesystem boundaries apply.
- The `## Guides` section describes where the guides are and how to choose one.
- `check` notes a missing `CLAUDE.md` where Claude Code is set up, and no longer notes a missing `## Guides` section.
- `init` notes each existing file it changes that git cannot restore.

### Fixed

- Skills, presets, and comparisons accept CRLF line endings; the repository sets LF line endings in `.gitattributes`.
- The `CLAUDE.md` import is found after a code fence or an HTML comment, and headings inside an HTML comment are not sections.
- The overlap between allow and ask rules covers a trailing ` *` that also matches the bare command.
- `claudeMdExcludes` is checked against the active Claude file only, with forward slashes.
- `mpa-php` compares secrets with `hash_equals()`; `mpa-database` keeps SQL keywords out of parameters.

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
