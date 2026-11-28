# Changelog

## 9.0.1 - 2026-11-28

### Fixed

- The repository-clean test is skipped when the checkout is not its own git work tree, such as an unpacked release archive.

### Changed

- `docs/runtimes.md` no longer estimates the listing size of the catalogue against the 8,000-character fallback.

## 9.0.0 - 2026-11-28

Setup and update are file copies described in `README.md`. In a project set up with an earlier release, run the update commands once, delete the directories of the three retired skills (`mpa-release`, `mpa-containers`, `mpa-shell`), replace the cloud and pull request line in `## Approvals` by hand with the one in `templates/AGENTS.template.md` where it applies, and copy `mpa-delegation` if the project uses only `core`.

### Added

- `README.md` holds the commands that set up and update a project.
- `docs/runtimes.md` lists what keeps `AGENTS.md` or a skill from loading in each tool.
- `docs/runtimes.md` lists the user-level skill directory of each tool, for one copy of a stack skill per machine, with the limits of that route.
- `CONTRIBUTING.md` describes how the stack skills are refreshed.

### Changed

- `templates/block.md` holds the block with its two marker lines, and the marker names no version. `templates/AGENTS.template.md` starts at `## Approvals`.
- `tools/hygiene.py` reports local paths, mail addresses, IP addresses, private key headers, and token shapes, in files, staged content, and commit messages.
- The coverage line of each stack skill sends the agent to the release notes for a change the entries do not mention as well as for anything newer. `mpa-kubernetes` and `mpa-javascript-typescript` name addresses that list patch releases.
- `mpa-apache-httpd` and `mpa-nginx` name the patched release and the fixes that change what an agent writes or asks a host, in place of lists of single vulnerabilities.
- `mpa-delegation` moves from `agents` to `core`.
- `mpa-ci-pipeline` covers container image builds, `mpa-secure-coding` covers command strings built from data and secrets in command arguments, and `mpa-review` covers the test failures that block a release.
- Descriptions name only what their bodies cover, and name another skill only where matching the wrong one would lead to a harmful step.
- The Approvals template limits its cloud and pull request line to sessions that the user's request started and to replies about the session's own work.
- Tests cap each skill file at 7,000 bytes.
- `mpa-rust` is current to Rust 1.100.1.

### Removed

- `mpa.py` and `docs/cli.md`.
- `mpa-release`, `mpa-containers`, and `mpa-shell`. Their remaining lines are in `mpa-review`, `mpa-ci-pipeline`, and `mpa-secure-coding`.

### Fixed

- `mpa-php`: Laravel 13.44.0 is the first release that supports PHP 8.6. `mpa-infrastructure-as-code`: a Terraform variable used in a module `source` or `version` is declared with `const = true`.
- The 8.1.0 entry names Gateway API 1.5.

## 8.1.0 - 2026-11-27

Run `mpa.py update` once in each installed project. `update` leaves the `## Approvals` section alone, so add the new cloud and pull request line from `templates/AGENTS.template.md` by hand where it applies.

### Added

- `mpa-apache-httpd` (platforms): Apache HTTP Server releases 2.4.64 through 2.4.71, with the security fixes a site configuration can reach, how ETag, compression, and conditional requests behave, which directives `.htaccess` accepts, and when to ask the host.
- `mpa-nginx` (platforms): nginx release changes through stable 1.30.8 and mainline 1.31.10, with the changed proxy, header, and HTTP/2 defaults and the 2026 security fixes and the releases that hold them.
- `mpa-delegation` (agents bundle): what a helper agent may change, how to split and merge parallel work, checking a helper's result, not its summary, and the cap, check, and cleanup of an unattended run.
- A coverage line at the top of each stack skill: the versions it is current to, the date they were checked, and the official release notes to read for anything newer or not listed; the entries are the changes that are easy to miss, not the full release notes. The stack skills cover Python 3.15.2; TypeScript 7.0.2 and Node.js 26.13.1; Go 1.27.4; Rust 1.100.0 and Cargo 1.100; Swift 6.4.3; PHP 8.6.0 and Laravel 13.44.1; Hugo v0.170.1; WordPress 7.1.5; Apache HTTP Server 2.4.71; nginx stable 1.30.8 and mainline 1.31.10; Kubernetes 1.37.3 and Gateway API v1.7.0; Terraform 1.17.2 and OpenTofu 1.13.10; and Model Context Protocol revision 2026-07-28.
- Release entries in the stack skills: Model Context Protocol 2026-07-28; TypeScript 6.0 and 7.0; Node.js 25 and 26; Python 3.15; Go 1.27; Rust 1.99 and 1.100 with Cargo 1.99 and 1.100; Swift 6, 6.3, and 6.4; PHP 8.6 and Laravel 13; the Hugo security defaults and escaping changes and the releases that set them; WordPress 6.9 abilities; Kubernetes 1.33 to 1.37 with Gateway API 1.5, 1.6, and 1.7; Terraform 1.15 to 1.17 with OpenTofu 1.12 and 1.13; the security releases of Node.js, Python, Go, PHP, WordPress, Terraform, and OpenTofu up to 2026-11-27; the GitHub workflow dependency lockfile in `mpa-ci-pipeline`.
- `--runtime copilot` and `--runtime gemini` as names for `agents`. With `gemini`, `init` notes that Gemini CLI reads `AGENTS.md` only when its `context.fileName` setting lists it.

### Changed

- The working agreement has two rules, `Approvals` and `Checks`, in 1,045 bytes. The Approvals section outranks any skill; when a yes is needed, the work that stands without it is finished first and the exact action is asked for; a headless or scheduled run skips the action and what needs it and reports both. `Checks` asks for the checks that cover the change to run before work is reported done, forbids weakening, skipping, or working around a check, a hook, or a denial, and asks which checks ran, what they showed, what went unchecked, and what remains.
- The Approvals template names agent files by kind (instruction, skill, hook, permission, and tool or MCP configuration files), not by path, so files the list did not name, such as `REVIEW.md` and `.github/prompts/`, need a yes as well.
- The Approvals template lets a cloud or pull request session that the user started to deliver through its own branch or pull request commit, push that branch without rewriting its pushed history, and comment on that pull request without asking; every other push still needs a yes.
- The 29 skills of 8.0.0 are shorter and keep the release entries and the checks that change what an agent does. Descriptions no longer ask for a second skill alongside and name only what the body covers. `mpa-review` keeps how far to follow a change, whether its tests can fail, and refuting a finding before reporting it; `mpa-dependency-change` keeps the checks for package names that do not exist and for editor extensions and agent plugins.
- `mpa-hugo`, `mpa-infrastructure-as-code`, and `mpa-web-frontend` set no approval rule of their own; the Approvals section decides what needs a yes.
- `check` reports on the files this tool installs and on what stops them from loading. `docs/runtimes.md` is shorter and covers GitHub Copilot and Gemini CLI.

### Removed

- Skill lines that do not change what an agent does, and the paragraphs that told agents to check current official documentation, which the coverage line replaces.
- The notes of `check` about other tools' instruction files, rule folders, and settings, the combined size along a folder chain, and the count of skill directories without the `mpa-` prefix. The note for `AGENTS.md` files in subdirectories stays.
- `docs/external-skills.md`.

### Fixed

- `mpa-hugo`: on v0.166+ keep the default `security.http.urls`. `mpa-infrastructure-as-code`: `sensitive` values are stored in plain text in state and plans. `mpa-kubernetes`: attachment to a Gateway across namespaces uses `allowedRoutes`, not `ReferenceGrant`. `mpa-wordpress`: `wp-config.php` permissions match how PHP runs. `mpa-external-contribution`: a tag is an immutable version only where the host locks it.
- `mpa.py` recognizes section headings that are indented, separated by a tab, or closed with `#` characters; treats block markers inside code fences as text; keeps an `AGENTS.md` above 32 KiB that `init` does not change, with a note; reports files with index conflicts as conflicted; and stops at symbolic link loops with a message, not a traceback.
- `init --help` and the README name `CLAUDE.md`, `.claude/CLAUDE.md`, and `.claude/settings.json` as the files that select `claude`.

### Security

- `mpa.py` opens files without following a final symbolic link and refuses anything that is not a regular file.
- `SECURITY.md` adds `REVIEW.md`, `.vscode/mcp.json`, `.github/hooks/`, and `.github/prompts/` to the files that direct agents.

## 8.0.0 - 2026-11-24

The working-agreement block shrinks to three rules (`Approvals`, `Blocks`, `Evidence`), default `init` writes a single `.agents/skills/` copy unless Claude Code is selected or detected, and `--preset` and `--state` are removed. Run `mpa.py update` once in each installed project to update the managed block and installed `mpa-*` skills.

### Added

- Dedicated flat platform skills `mpa-hugo` and `mpa-wordpress`.
- `--runtime agents` (fresh-project default) and `--runtime antigravity` (alias for `.agents/skills/`).
- Separate browsing categories and installable bundles: `security` splits into `security`, `agents`, and `data`, while `languages` and `platforms` are individual-only pick-lists. `update --add-skill` and `--remove-skill` now accept installable bundle names as well as space-separated, comma-separated, and repeated flags.
- `docs/cli.md` as the single-home CLI reference, and `docs/external-skills.md` listing vetted first-party additive companion repositories (`GoogleChrome/modern-web-guidance-src` and `cloudflare/security-audit-skill`) with pinning and vetting guidance.
- `mpa.py check` runtime-aligned notes: root `GEMINI.md` and `.agents/rules`, missing `SKILL.md` errors, nested `AGENTS.md`/`AGENTS.override.md` ancestor-chain size notes, 24,000-byte single-file notes for `GEMINI.md` and nested `AGENTS.md`, per-directory 8,000-character `mpa-*` startup listing notes, dual-directory overlap and set-drift notes, and non-`mpa-*` skill directory counts.
- Skill guidance updates across `mpa-agent-instructions`, `mpa-review`, `mpa-root-cause`, `mpa-swift`, `mpa-php`, `mpa-secure-coding`, `mpa-agent-inputs`, `mpa-javascript-typescript`, `mpa-go`, `mpa-kubernetes`, and `mpa-database`.
- `CONTRIBUTING.md`: frontier-model non-redundancy bar, first-party vendor link admission rules, and a fresh-context diff-audit checklist.

### Changed

- `templates/block.md` (`8.0.0`): trimmed to three rules (`Approvals`, `Blocks`, `Evidence`), folding unfinished-work handoff and one-line `Constraints` proposals into `Evidence`.
- `templates/AGENTS.template.md`: moved `## Approvals` directly beneath the managed block, narrowed external-disclosure wording to project code, secrets, or user data, grouped protected agent files by category with examples across supported harnesses, and folded scope latitude into `## Constraints`.
- `mpa.py init`: resolves omitted `--runtime` from existing `mpa-*` skill directories, then committed Claude files (`CLAUDE.md`, `.claude/CLAUDE.md`, `.claude/settings.json`), otherwise single-copy `agents` (with a note naming `--runtime claude`); writes `CLAUDE.md` only when `claude` is selected; inserts missing adopted sections directly after `<!-- mpa:end -->`.
- Skill catalogue and files: standardised all 29 YAML descriptions to double-quoted third-person strings up to 320 characters with directional contrast redirects, aligned workflow closing headings to `## Report`, replaced trailing `Related skill(s):` footers with inline citations, and updated `skills/README.md` to show category and install mode (`bundle` vs. `individual`).
- `docs/runtimes.md`: replaced managed `--preset` documentation with copy-paste starter snippets and native OS sandbox / permission-mode pointers, and moved CLI tables to `docs/cli.md`.
- Size caps: removed the repository-wide `SKILLS_CAP` total in favour of the per-skill 5,000-byte cap and per-project startup listing notes in `mpa.py check`.

### Removed

- `--preset` and `templates/presets/*` (`.claude/settings.json`, `.codex/rules/mpa.rules`, `.codex/config.toml`).
- `--state`, `templates/TODO.md`, `.gitignore` mutation, the `Notes` rule in `templates/block.md`, and `## Code latitude` as a standalone heading.
- Bulk `languages` install group, `docs/migrating-from-v6.md`, legacy v6/v7.0 compatibility checks, placeholder-comment and empty-command notes in `mpa.py check`, and deprecated Gemini CLI references.

### Fixed

- `mpa.py`: breadth-first nested instruction discovery (finding shallow files before the 2,000-directory limit), consistent dual `CLAUDE.md` and `.claude/CLAUDE.md` inspection, separate nested `GEMINI.md` reporting, skipping symlinked nested instruction files during size checks, leading UTF-8 BOM handling, segment-aware `claudeMdExcludes` matching, and per-item error isolation in `check`.
- Skill accuracy fixes across `mpa-python`, `mpa-php`, `mpa-kubernetes`, `mpa-secure-coding`, and `mpa-rust`.
- `tools/hygiene.py`: IPv4 detection after `=`, non-git `.git` pruning and POSIX paths, CRLF scissors lines, and CLI mode conflict validation.

### Security

- `mpa.py check` runs zero `git` subprocesses, removing `.git/config` exposure during read-only checks.
- `tools/hygiene.py`: upgraded link validation to full-token parsing with exact HTTPS repository root allowlisting for `docs/external-skills.md`, rejecting quote, backtick, userinfo, port, query, fragment, and path-traversal bypasses.

## 7.2.0 - 2026-11-16

The block is unchanged. Run `mpa.py update` to install the revised skills; until then `check` reports them as different from the shipped text.

### Added

- `mpa-agent-instructions`: check that a skill loaded before rewriting it; compare with a run without the skill or instruction and remove text that does not improve on it; measure a cost cut with task success and count helper and judge calls; enable only the tools and servers the project uses; promote a pattern from chats or traces only after it recurs across tasks; remove notes the repository no longer matches.
- `mpa-security-audit`: hardening notes, with no severity, for a missing extra safeguard behind a control that already stops the attack.

### Changed

- `mpa-security-audit`: weakening a control ranks below bypassing the same boundary; permitted actions affecting only the actor are not exploitability.
- `mpa-agent-instructions`: every grader, not only a model-based judge, is calibrated against known-good and known-bad outputs.
- `mpa-web-frontend`: a purely additive feature may drop out unsupported, and needed behaviour gets a tested fallback; origin trials, flagged features, and relying on a single-engine feature need approval; a clean automated audit is not conformance; shorter wording elsewhere.

### Removed

- `mpa-web-frontend`: the unversioned claim that `target="_blank"` implies `noopener`.

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
