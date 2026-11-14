# Security

## Supported versions

Version 7.x.

## Scope

This policy covers `mpa.py`, the templates, the skills, and the permission presets in this repository.

## What the script does to a project

`mpa.py` creates or changes only these paths inside the project directory it is given:

- `AGENTS.md`
- `CLAUDE.md` or `.claude/CLAUDE.md`
- `.claude/skills/mpa-*/SKILL.md` and `.agents/skills/mpa-*/SKILL.md`
- `.claude/settings.json`, `.codex/config.toml`, `.codex/rules/mpa.rules` (with `--preset`); `update` also replaces the last one
- `TODO.md` and `.gitignore` (depending on `--state`)

It creates the directories these paths need. While it replaces a file it writes a `.tmp-*` file next to it and renames that file into place.

`update` deletes the directory of an `mpa-*` skill that is removed, when the directory is empty or holds nothing but `SKILL.md`. A directory that holds any other file is kept, and `update` exits with 1. `--remove-skill` applies to every `mpa-*` directory under the two skill paths, including one whose name this repository does not ship.

`update --write` replaces or removes a file only when git tracks it and it has no unstaged changes. `update` without `--write` reports the same condition in its plan. `--force` switches that condition off. It also lifts the refusal to replace a `.codex/rules/mpa.rules` with project edits.

`update` keeps an `mpa-*` directory whose name this repository does not ship, and `check` reports it as an error until it is removed or renamed.

Without `--write` the script changes nothing. It makes no network connection and does not execute files from the project. `update`, including its dry run, and `check` run two git commands, `git ls-files` and `git rev-parse`; `init`, including its dry run, runs `git ls-files` when it changes an existing file. git finds the repository itself: it reads one only when the project root lies inside a work tree it accepts, which excludes a repository owned by another user, one above `GIT_CEILING_DIRECTORIES`, and one across a filesystem boundary. These commands read the index and no objects, and apply no clean or smudge filter, diff driver, or text conversion; `update` hashes the working files itself and compares the result with the blob IDs in the index. They run with the pager, the file-system monitor, hooks, and lazy fetching switched off. Git still reads the whole of the project's `.git/config`, and this script cannot rule out every setting that makes git start a program: do not run `init`, `update`, or `check` on a checkout whose `.git/config` is untrusted. The script refuses a target that is a symbolic link, that has a symbolic link in its path, that is not a regular file, or that resolves outside the project. It reads at most 1 MiB per file.

## What the installed files are

- The working agreement and the skills are instructions to an agent. Nothing enforces them.
- The presets are prompt and deny rules on common command forms. They are not a sandbox.
- Nothing installed defends against prompt injection.
- Text that a project already has in `AGENTS.md` or `CLAUDE.md` is kept and loads together with the working agreement. The script does not review it.
- A skill directory contains one Markdown file and no executable files.

## Protecting the files that direct agents

`AGENTS.md` at any depth, `CLAUDE.md`, `.claude/`, `.codex/`, `.agents/`, `.mcp.json`, and CI workflow files decide what an agent is told, which tools it reaches, and what it may do without asking. A change to them deserves the same review as a change to code. Protect them with branch protection or a code-owners rule.

## Reporting a vulnerability

Use GitHub private vulnerability reporting on this repository: the "Report a vulnerability" button under the Security tab. Do not open a public issue for a suspected vulnerability.
