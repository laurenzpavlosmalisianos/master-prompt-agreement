# Runtimes

How the installed files load in each tool, how startup budgets and OS sandboxes compare across runtimes, and how cloud sessions differ. For CLI flags, file ownership, and `mpa.py check` output, see [docs/cli.md](cli.md). Tool behaviour changes between releases; the linked official pages are the reference.

## How instructions load

**Claude Code** reads `CLAUDE.md`. When `--runtime claude` is selected, `mpa.py init` installs a one-line `CLAUDE.md` containing `@AGENTS.md` (or `@../AGENTS.md` in an existing `.claude/CLAUDE.md`) so Claude Code imports `AGENTS.md` in every case. From version 2.1.277 Claude Code also reads `AGENTS.md` directly when no `CLAUDE.md`, `.claude/CLAUDE.md`, or `CLAUDE.local.md` exists in the working directory or above it; keeping the import avoids silent drops when a parent directory holds a `CLAUDE.md`. `CLAUDE.local.md` and user-level files load in addition and hold personal instructions. See [memory and imports](https://code.claude.com/docs/en/memory).

**Codex** reads `AGENTS.md` files from the repository root down to the working directory, one file per directory, up to a combined default limit of 32 KiB. An `AGENTS.override.md` in a directory replaces the `AGENTS.md` in that directory. `mpa.py check` reports a root `AGENTS.override.md` and a root `AGENTS.md` above 32 KiB as errors, and notes both a root `AGENTS.md` above 16 KiB and any nested root-to-leaf ancestor chain exceeding 16 KiB or 32 KiB. See [AGENTS.md in Codex](https://learn.chatgpt.com/docs/agent-configuration/agents-md).

**Antigravity** (app, IDE, and `agy` CLI) reads `AGENTS.md` and `GEMINI.md` in the workspace folder and parent folders up to the repository root, plus nested directory rules when operating on files in subdirectories. It loads skills natively from `.agents/skills/`, so `--runtime antigravity` and `--runtime agents` map to the same single-copy layout. Antigravity truncates any single rule file above 24,000 bytes and keeps all rules within a 20,000-token budget, beyond which it replaces the largest files with pointers; `mpa.py check` notes root `GEMINI.md` and nested `AGENTS.md` or `GEMINI.md` files above 24,000 bytes. See [rules](https://antigravity.google/docs/rules), [customization discovery](https://antigravity.google/docs/customization-discovery), and [skills](https://antigravity.google/docs/skills).

**Other tools** that follow the [AGENTS.md convention](https://agents.md) read `AGENTS.md` as plain Markdown. Tools that also load `.agents/skills/` natively need only `--runtime agents`. For tools without native skill listing, `--runtime generic` installs skills under `.agents/skills/` and adds a `## Guides` pointer in `AGENTS.md`.

The managed block is project-level text. The tool's own system instructions outrank it. `AGENTS.md` is committed; keep private facts out of it.

## Skills and startup budgets

| Runtime | Skill directory | `CLAUDE.md` import |
|---|---|---|
| `agents` (fresh default), `codex`, `antigravity`, `generic` | `.agents/skills/mpa-*/SKILL.md` | Not written |
| `claude` | `.claude/skills/mpa-*/SKILL.md` | Written (`@AGENTS.md` or `@../AGENTS.md`) |

Tools with native skill support load each skill's `name` and `description` at session startup and read the full `SKILL.md` body on demand when a task matches. The format is the [Agent Skills](https://agentskills.io) format; see [skills in Claude Code](https://code.claude.com/docs/en/skills) and [skills in Codex](https://learn.chatgpt.com/docs/build-skills).

### Single vs. dual skill directories

- **Fresh repositories** default to single-copy `.agents/skills/` (`--runtime agents`), which covers Codex, Antigravity, and compatible Agent Skills tools without duplicating skill files.
- **Claude Code repositories** use `--runtime claude`, which installs `CLAUDE.md` and `.claude/skills/mpa-*/`. Omitting `--runtime` during `init` automatically selects `claude` when `CLAUDE.md`, `.claude/CLAUDE.md`, or `.claude/settings.json` already exists (and preserves existing `mpa-*` directories first).
- **Dual installs (`--runtime claude,agents`)** commit identical copies into both `.claude/skills/` and `.agents/skills/`. Tools that scan both directories list every installed skill twice at startup, doubling startup metadata; `mpa.py init` and `mpa.py check` emit a note when both directories hold `mpa-*` skills.

### Calibrated startup listing budgets

Because skill descriptions load on every turn, install only the bundles and individual `languages` / `platforms` skills the repository uses (see [docs/cli.md](cli.md#init) and the [skill catalogue](../skills/README.md)):

- **Codex** allocates roughly 2% of context (about 8 KB) for startup skill listings.
- **Claude Code** allocates roughly 1% of the context window for startup skill descriptions (roughly 8,000 characters on a 200K-token window); when over budget, skill names remain loaded while the least-used descriptions are trimmed.
- `mpa.py check` sums shipped `name` + `description` characters per skill directory (`.agents/skills/` and `.claude/skills/`) and emits a note above `8,000` characters. The default `core` bundle totals ~2.2 KB; all 29 shipped skills total ~8.2 KB.
- **Non-`mpa-*` skills** (custom workspace skills or pinned [external companions](external-skills.md)) share the same startup listing budget. `mpa.py check` counts non-`mpa-*` directories (including symlinked skill directories) per skill folder without opening or parsing their files.

## Sandboxes, permission modes, and starter snippets

MPA installs plain-text instructions and skills only; it does not generate or merge runtime permission files. Prefix-matched shell prompt rules are convenience friction rather than a security boundary—they miss alternative flags, shell redirections, and scripts that open files directly.

For real boundaries, enable each runtime's native OS sandbox (Seatbelt on macOS, seccomp / Linux sandboxing on Linux) and configure its permission mode (such as `default`, `auto`, or `dontAsk` in Claude Code, or Codex's sandbox mode and approval policy). The short starter snippets below can be copied and adapted by hand when a team also wants prompt or deny friction on `.env` files and destructive `git` commands.

### Claude Code starter snippet

Copy or merge into `.claude/settings.json` (committed) or `.claude/settings.local.json` (personal, git-ignored):

```json
{
  "permissions": {
    "deny": [
      "Read(./.env)",
      "Read(./.env.*)",
      "Edit(./.env)",
      "Edit(./.env.*)"
    ],
    "ask": [
      "Bash(git push --force*)",
      "Bash(git push * --force*)",
      "Bash(git push -f*)",
      "Bash(git push * -f*)",
      "Bash(git reset --hard*)",
      "Bash(git clean *)",
      "Bash(git branch -D *)",
      "Bash(git stash drop*)",
      "Bash(git stash clear*)"
    ]
  }
}
```

Claude Code evaluates `deny`, then `ask`, then `allow`; an `allow` in `.claude/settings.local.json` does not outrank a `deny` or `ask` in the committed file, and `deny` rules do not support `!` negation exceptions. The `./` patterns above match the repository root; in a monorepo with nested `.env` files, add `Read(**/.env)`, `Read(**/.env.*)`, `Edit(**/.env)`, and `Edit(**/.env.*)`. If a repository commits a sample env file that agents need to read, either name it without a leading dot (such as `env.example`) or replace `.env.*` with explicit secret env patterns (such as `Read(./.env.local)` and `Read(./.env.production)`). `Read` and `Edit` deny rules block built-in file tools rather than arbitrary shell scripts run via `Bash`; rely on OS sandboxing and keeping production secrets out of the work tree. If you add `Bash(git push *)` to the committed file, note that Claude Code cloud sessions deliver work by pushing a branch and pause at that prompt (teams whose cloud or headless sessions push branches also allow non-default branch pushes under `## Approvals` in `AGENTS.md`).

For OS sandboxing, permission modes (`default`, `auto`, `dontAsk`), and hard command blocks via hooks, see [permissions](https://code.claude.com/docs/en/permissions), [settings](https://code.claude.com/docs/en/settings), [sandboxing](https://code.claude.com/docs/en/sandboxing), and [hooks](https://code.claude.com/docs/en/hooks).

### Codex starter snippets

Codex loads `.codex/` only after the project is marked trusted. To keep default secret-like environment variables (`KEY`, `SECRET`, `TOKEN`) excluded from shell commands, add to `.codex/config.toml`:

```toml
[shell_environment_policy]
ignore_default_excludes = false
```

To prompt on common destructive `git` prefixes, add a project-owned rule file such as `.codex/rules/project.rules`:

```python
prefix_rule(
    pattern = ["git", "push", ["--force", "--force-with-lease", "-f"]],
    decision = "prompt",
)

prefix_rule(
    pattern = ["git", ["reset", "clean"]],
    decision = "prompt",
)
```

Codex rules match command prefixes and are marked experimental in Codex's documentation: reordered flags, shell redirections, variables, globs, and command substitutions are not split into matched commands. Rely on Codex's OS sandbox and approval policy for enforcement. See the [configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference) and [rules](https://learn.chatgpt.com/docs/agent-configuration/rules).

## Trust

- Claude Code applies `ask` and `deny` rules from project settings before the workspace is trusted. `allow` rules wait for trust.
- Codex loads the project's `.codex/` directory only after the project is marked trusted.

## Cloud sessions

A Claude Code cloud session starts from a clone of the repository.

- A session on a single repository reads the committed `CLAUDE.md`, `.claude/settings.json`, and `.claude/skills/`.
- Project threads read the instruction files at the repository root, but not the repository's permission rules, hooks, or `.claude/skills/`. A session on several repositories does not read the repositories' permission rules or hooks either.
- User-level files, `.claude/settings.local.json`, and files ignored by git are absent.

See [Claude Code on the web](https://code.claude.com/docs/en/claude-code-on-the-web).

## Where the checkout lives

Keep the checkout of this repository outside the project, and do not add it as a submodule. The installed files are the copy the agent reads; the checkout is needed only to run `init`, `update`, and `check`. See [docs/cli.md](cli.md#file-ownership-and-guard) for file ownership and the git cleanliness guard.
