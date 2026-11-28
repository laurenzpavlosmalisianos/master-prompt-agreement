# Security

## Supported versions

Version 9.x.

## Scope

This policy covers the templates and the skills in this repository, and the commands in `README.md` that copy them.

## What this repository does to a project

Nothing in this repository runs in a project. Setup and update are file copies that a person or an agent carries out from `README.md`, into these paths:

- `AGENTS.md`
- `CLAUDE.md` or `.claude/CLAUDE.md` (for Claude Code)
- `.claude/skills/mpa-*/SKILL.md` and `.agents/skills/mpa-*/SKILL.md`

The update commands overwrite the installed `mpa-*` skill files and replace the block in `AGENTS.md`, from its begin marker to its end marker. They delete nothing. Run them on a committed work tree and read `git diff` afterwards.

`tools/hygiene.py` is a maintainer tool and is not copied into projects. It reads this repository's files and commit messages, runs `git` in this repository, makes no network connection, and writes no file.

## What the installed files are

- The working agreement and the skills are plain-text instructions to an agent. Nothing enforces them.
- Enforcement of command and filesystem boundaries belongs to each runtime's native OS sandbox and permission modes; see [docs/runtimes.md](docs/runtimes.md).
- Nothing installed defends against prompt injection.
- Text that a project already has in `AGENTS.md` or `CLAUDE.md` is kept and loads together with the working agreement, unreviewed.
- A skill directory contains one Markdown file and no executable files. A stack skill holds one link: the official release-notes address, or addresses, in its coverage line. An agent that follows it reads that page, which is outside this repository's control.

## Protecting the files that direct agents

Agent instruction, skill, hook, or permission files, tool or MCP configs—such as `AGENTS.md` and `AGENTS.override.md` at any depth, `CLAUDE.md`, `GEMINI.md`, `REVIEW.md`, `.claude/`, `.codex/`, `.agents/`, `.gemini/`, `.mcp.json`, `.vscode/mcp.json`, GitHub Copilot's `.github/copilot-instructions.md`, `.github/instructions/`, `.github/skills/`, `.github/agents/`, `.github/hooks/`, and `.github/prompts/`, and Antigravity's alternative `.agent/`, `_agents/`, and `_agent/` folders—and CI workflow files decide what an agent is told, which tools it reaches, and what it may do without asking. A change to them deserves the same review as a change to code. Protect them with branch protection or a code-owners rule.

## Reporting a vulnerability

Use GitHub private vulnerability reporting on this repository: the "Report a vulnerability" button under the Security tab. Do not open a public issue for a suspected vulnerability.
