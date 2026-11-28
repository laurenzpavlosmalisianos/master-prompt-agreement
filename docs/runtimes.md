# Runtimes

How the installed files load in each tool, what limits the startup skill listing, and starter permission settings. Tool behaviour changes between releases; the linked official pages are the reference.

## What each tool reads

| Tool | Instruction file | Skill folder |
|---|---|---|
| Claude Code | `CLAUDE.md`, which imports `AGENTS.md` | `.claude/skills/` |
| Codex | `AGENTS.md` | `.agents/skills/` |
| Antigravity | `AGENTS.md` | `.agents/skills/` |
| GitHub Copilot | `AGENTS.md` | `.agents/skills/` (also reads `.claude/skills/` and `.github/skills/`) |
| Gemini CLI | `AGENTS.md`, once `context.fileName` lists it | `.agents/skills/` |
| Other tools that read `AGENTS.md` | `AGENTS.md` | `.agents/skills/`, through a `## Guides` section where the tool lists no skills |

- **Claude Code** reads `CLAUDE.md`. Setup gives it a `CLAUDE.md` whose one line is `@AGENTS.md` (in an existing `.claude/CLAUDE.md` the line is `@../AGENTS.md`). From version 2.1.277 Claude Code also reads `AGENTS.md` directly when no `CLAUDE.md`, `.claude/CLAUDE.md`, or `CLAUDE.local.md` exists in the working directory or a directory above it; keeping the import avoids silent drops when a parent directory holds a `CLAUDE.md`. See [memory and imports](https://code.claude.com/docs/en/memory).
- **Codex** reads `AGENTS.md` files from the repository root down to the working directory, one file per directory, up to a combined default limit of 32 KiB. An `AGENTS.override.md` in a directory replaces the `AGENTS.md` in that directory. See [AGENTS.md in Codex](https://learn.chatgpt.com/docs/agent-configuration/agents-md).
- **Antigravity** reads `AGENTS.md` in the workspace folder and in each parent folder up to the repository root, and truncates any single rule file above 24,000 bytes. See [rules](https://antigravity.google/docs/rules).
- **GitHub Copilot** reads `AGENTS.md` files anywhere in the repository in the features that support agent instructions, and the nearest `AGENTS.md` in the directory tree takes precedence, so a nested `AGENTS.md` can override the root file and its managed block. See [repository instructions](https://docs.github.com/en/copilot/how-tos/copilot-on-github/customize-copilot/add-custom-instructions/add-repository-instructions).
- **Gemini CLI** reads `GEMINI.md` by default and reads `AGENTS.md` only when the `context.fileName` setting (for example in the project's `.gemini/settings.json`) lists it. See [GEMINI.md files](https://geminicli.com/docs/cli/gemini-md/).
- **Other tools** that follow the [AGENTS.md convention](https://agents.md) read `AGENTS.md` as plain Markdown. Where a tool lists no skills, copy them into `.agents/skills/` and add this section to `AGENTS.md`:

  ```markdown
  ## Guides

  Task guides are the `SKILL.md` files in the `mpa-*` directories under `.agents/skills/`. Each has a `description` line at the top that says when it applies. Read a guide before work that its description matches.
  ```

The managed block is project-level text. The tool's own system instructions outrank it. `AGENTS.md` is committed; keep private facts out of it.

## Skills and the startup listing

Tools with native skill support load each skill's `name` and `description` at session startup and read the full `SKILL.md` body on demand when a task matches. The format is the [Agent Skills](https://agentskills.io) format. Because the descriptions load in every session, copy only the skills the repository uses.

- **Codex** by default limits the startup skill listing to 2% of the model's context window, or 8,000 characters when the window size is unknown. Over the budget it shortens descriptions first and can leave skills out with a warning.
- **Claude Code** sets the startup skill listing budget at 1% of the model's context window. Over the budget, every skill name stays listed and descriptions are dropped, starting with the least-invoked skills.
- The `core` skills stay far below 8,000 characters, and the whole catalogue comes close to it. Skills without the `mpa-` prefix share the same budget.
- Copies in both `.claude/skills/` and `.agents/skills/` serve a team that uses both kinds of tool. A tool that scans both directories lists every skill twice at startup.

## Permissions and starter snippets

MPA ships plain-text instructions and skills only; it does not generate or merge runtime permission files. For real boundaries, enable each runtime's native OS sandbox and configure its permission mode. Prefix-matched shell prompt rules are friction, not a security boundary: they miss alternative flags, shell redirections, and scripts that open files directly. The snippets below can be copied and adapted by hand.

From version 2.1.283 interactive terminal and VS Code sessions of Claude Code start in auto mode, where a classifier decides in place of prompts. In auto mode a push to the working repository, including its default branch, runs without a prompt. The classifier reads the `CLAUDE.md` content the session loads, so an Approvals list imported there steers it, but only a `permissions.ask` rule such as `Bash(git push *)` creates a prompt. A Claude Code cloud session delivers work by pushing a branch, so such a rule stops it there. See [permission modes](https://code.claude.com/docs/en/permission-modes).

### Claude Code

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

Claude Code evaluates `deny`, then `ask`, then `allow`; an `allow` in `.claude/settings.local.json` does not outrank a `deny` or `ask` in the committed file. The `./` patterns above resolve against the directory the session starts in, normally the repository root, and match only there. `Read` and `Edit` deny rules block built-in file tools rather than arbitrary shell scripts run via `Bash`. See [permissions](https://code.claude.com/docs/en/permissions) and [sandboxing](https://code.claude.com/docs/en/sandboxing).

### Codex

Codex loads `.codex/` only after the project is marked trusted. By default Codex passes environment variables whose names contain `KEY`, `SECRET`, or `TOKEN` to shell commands. To remove them before other filters run, add to `.codex/config.toml`:

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

Codex rules match command prefixes and are marked experimental in Codex's documentation. Rely on Codex's OS sandbox and approval policy for enforcement. See the [configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference).

## When the files do not load

What to look at, by hand or by handing this list to an agent:

- **Claude Code:** `CLAUDE.md` holds a line that is exactly `@AGENTS.md` (`@../AGENTS.md` in `.claude/CLAUDE.md`), outside code fences and HTML comments. Only one of `CLAUDE.md` and `.claude/CLAUDE.md` exists. No `claudeMdExcludes` entry in `.claude/settings.json` or `.claude/settings.local.json` matches `AGENTS.md` or the `CLAUDE.md` in use.
- **Codex:** no `AGENTS.override.md` sits beside `AGENTS.md`, and the `AGENTS.md` files from the repository root to the working directory stay under 32 KiB together.
- **Antigravity:** `AGENTS.md` stays under 24,000 bytes.
- **Gemini CLI:** `context.fileName` in `.gemini/settings.json` (or user-level settings) lists `AGENTS.md`.
- **A tool that reads the nearest file:** an `AGENTS.md` in a subdirectory replaces the root file there, and the working agreement with it.
- **Skills:** each installed `mpa-*` directory holds only `SKILL.md` and matches the checkout's directory (`diff -r` per installed `mpa-*` directory against `$mpa/skills/<name>`). The `name` and `description` lines of all skills in a folder stay within the listing budget above. The skills sit in one of `.agents/skills/` and `.claude/skills/`, or in both on purpose with matching skill sets.

## Cloud and pull request sessions

A cloud or pull request session exists to deliver through its own branch or pull request. When the user's request started it, the template's `## Approvals` lets it commit, push that branch without rewriting its pushed history, and reply on that pull request about its own work. A session that an automatic trigger or someone else started gets no exemption, and the rest of the list holds in every session. Remove that line where every push needs a yes.

## One copy for every project on a machine

Committed copies are what teammates, CI, and cloud sessions read. For local work on several projects that share a stack, a stack skill can also live once in a user-level skill directory:

| Tool | User-level skill directory |
|---|---|
| Claude Code | `~/.claude/skills/` |
| Codex | `~/.agents/skills/` |
| Gemini CLI | `~/.gemini/skills/` or `~/.agents/skills/` |
| GitHub Copilot | `~/.copilot/skills/` or `~/.agents/skills/` |
| Antigravity | `~/.gemini/config/skills/` |

Copy a skill directory from a checkout of a release tag into the directory of each tool in use, or link it: Claude Code and Codex follow a symbolic link to a skill directory, and Gemini CLI has `/skills link`. Moving the checkout to a newer tag then refreshes the linked skills in every project at once. GitHub CLI's `gh skill install` can place the same skills at user scope.

- In Claude Code a user-level skill takes precedence over a project skill of the same name, and Codex lists both, so keep a user-level copy current.
- Cloud sessions of Claude Code do not load user-level skills, and GitHub Copilot's cloud sandbox reads them from a dotfiles repository.
- `gh skill` writes source-tracking fields into each skill's frontmatter, so such a copy differs from the shipped text.

## Where the checkout lives

Keep the checkout of this repository outside the project, and do not add it as a submodule. The copied files are what the agent reads; the checkout is needed only to copy from.
