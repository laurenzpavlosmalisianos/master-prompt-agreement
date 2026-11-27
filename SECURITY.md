# Security

## Supported versions

Version 8.x.

## Scope

This policy covers `mpa.py`, the templates, and the skills in this repository.

## What the script does to a project

`mpa.py` creates or changes only these paths inside the project directory it is given:

- `AGENTS.md`
- `CLAUDE.md` or `.claude/CLAUDE.md` (when `claude` is selected)
- `.claude/skills/mpa-*/SKILL.md` and `.agents/skills/mpa-*/SKILL.md`

It creates the directories these paths need. While it replaces a file it writes a sibling `.tmp-*` file and renames that file into place.

`update` deletes the directory of an `mpa-*` skill that is removed, when the directory is empty or holds nothing but `SKILL.md`. A directory that holds any other file is kept, and `update` exits with 1. `--remove-skill` applies to every `mpa-*` directory under the two skill paths, including one whose name this repository does not ship.

`update --write` replaces or removes a file only when git tracks it and it has no unstaged changes. `update` without `--write` reports the same condition in its plan. `--force` lifts that git cleanliness guard and lifts the refusal to replace a managed block holding headings absent from the shipped block. See [docs/cli.md](docs/cli.md#file-ownership-and-guard) for full CLI ownership and guard rules.

`update` keeps an `mpa-*` directory whose name this repository does not ship, and `check` reports it as an error until it is removed or renamed.

Without `--write` the script changes nothing. It makes no network connection and does not execute files from the project.

- **`mpa.py check` runs zero `git` subprocesses.** Read-only inspection never reads `.git/config`, eliminating `.git/config` execution exposure when checking an untrusted checkout.
- **`init` and `update` invoke git with restricted flags.** `update` (including its dry run) runs `git ls-files` to preview and enforce `guard()` refusals, and on `--write` runs `git rev-parse --is-inside-work-tree`; `init` (including its dry run) runs `git ls-files` when it changes an existing file. Git finds the repository itself: it reads one only when the project root lies inside a work tree it accepts, which excludes a repository owned by another user, one above `GIT_CEILING_DIRECTORIES`, and one across a filesystem boundary. These commands read the index and no objects, and apply no clean or smudge filter, diff driver, or text conversion; `update` hashes the working files itself and compares the result with the blob IDs in the index. They run with `--no-pager`, `--no-optional-locks`, `--literal-pathspecs`, `core.fsmonitor=false`, `safe.bareRepository=explicit`, `core.hooksPath` disabled, `GIT_NO_LAZY_FETCH=1`, and `GIT_TERMINAL_PROMPT=0`. Git still reads the whole of the project's `.git/config`, and this script cannot rule out every setting that makes git start a program: do not run `init` or `update` on a checkout whose `.git/config` is untrusted.

The script refuses a target that is a symbolic link, that has a symbolic link in its path, that is not a regular file, or that resolves outside the project. It reads at most 1 MiB per file.

## What the installed files are

- The working agreement and the skills are plain-text instructions to an agent. Nothing enforces them.
- Enforcement of command and filesystem boundaries belongs to each runtime's native OS sandbox and permission modes; see [docs/runtimes.md](docs/runtimes.md).
- Nothing installed defends against prompt injection.
- Text that a project already has in `AGENTS.md` or `CLAUDE.md` is kept and loads together with the working agreement. The script does not review it.
- A skill directory contains one Markdown file and no executable files. A stack skill holds one link: the official release-notes address, or addresses, in its coverage line. An agent that follows it reads that page, which is outside this repository's control.

## Protecting the files that direct agents

Agent instruction, skill, hook, or permission files, tool or MCP configs—such as `AGENTS.md` and `AGENTS.override.md` at any depth, `CLAUDE.md`, `GEMINI.md`, `REVIEW.md`, `.claude/`, `.codex/`, `.agents/`, `.gemini/`, `.mcp.json`, `.vscode/mcp.json`, GitHub Copilot's `.github/copilot-instructions.md`, `.github/instructions/`, `.github/skills/`, `.github/agents/`, `.github/hooks/`, and `.github/prompts/`, and Antigravity's alternative `.agent/`, `_agents/`, and `_agent/` folders—and CI workflow files decide what an agent is told, which tools it reaches, and what it may do without asking. A change to them deserves the same review as a change to code. Protect them with branch protection or a code-owners rule.

## Reporting a vulnerability

Use GitHub private vulnerability reporting on this repository: the "Report a vulnerability" button under the Security tab. Do not open a public issue for a suspected vulnerability.
