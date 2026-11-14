# Runtimes

How the installed files load in each tool, what the presets do, how cloud sessions differ, and what `check` reports. Tool behaviour changes between releases; the linked official pages are the reference.

## How instructions load

**Claude Code** reads `CLAUDE.md`. The installed file is one line, `@AGENTS.md`, which imports `AGENTS.md` from the same directory. A project that keeps its file at `.claude/CLAUDE.md` gets `@../AGENTS.md`. From version 2.1.277 Claude Code also reads `AGENTS.md` directly, but only when no `CLAUDE.md`, `.claude/CLAUDE.md`, or `CLAUDE.local.md` exists in the working directory or above it; the import keeps it loaded in every case. `CLAUDE.local.md` and user-level files load in addition and are the place for personal instructions. See [memory and imports](https://code.claude.com/docs/en/memory).

**Codex** reads `AGENTS.md` files from the repository root down to the working directory, one file per directory, up to a combined default limit of 32 KiB. An `AGENTS.override.md` in a directory is read in place of the `AGENTS.md` there. `check` reports an `AGENTS.override.md` in the project root and an `AGENTS.md` above 32 KiB as errors, and an `AGENTS.md` above 16 KiB as a note. `check` measures the root file; the limit applies to all loaded instruction files together. See [AGENTS.md in Codex](https://learn.chatgpt.com/docs/agent-configuration/agents-md).

**Other tools** that follow the [AGENTS.md convention](https://agents.md) read the file as plain Markdown. Tools that also load `.agents/skills/` themselves need only `--runtime codex`. For tools without skill support, `--runtime generic` installs the skills under `.agents/skills/` and adds a `## Guides` pointer to those `SKILL.md` files and their `description` lines; nothing lists the descriptions for them in `AGENTS.md`. `init --runtime generic` writes the section when `.agents/skills/` holds or receives an `mpa-*` skill and `AGENTS.md` lacks a `## Guides` heading, on the first run and on a later one. `update --runtime generic` adds it under the same condition.

**Antigravity** reads `AGENTS.md` and `GEMINI.md` in the workspace folder and in each folder above it up to the repository root. It does not read one in a folder below the workspace folder. It loads skills from `.agents/skills/` itself, so `--runtime codex` covers it. It truncates a rule file above 24,000 bytes and keeps all rules within a budget of 20,000 tokens, beyond which it replaces the largest files with pointers. See [rules](https://antigravity.google/docs/rules.md), [customization discovery](https://antigravity.google/docs/customization-discovery), and [skills](https://antigravity.google/docs/skills). **Gemini CLI** reads `GEMINI.md` unless `context.fileName` in its settings names `AGENTS.md`; see [context files](https://geminicli.com/docs/cli/gemini-md/).

The block is project-level text. The tool's own system instructions outrank it.

`AGENTS.md` is committed. Keep private facts out of it.

## Skills

| Runtime | Directory |
|---|---|
| `claude` | `.claude/skills/mpa-*/SKILL.md` |
| `codex`, `generic` | `.agents/skills/mpa-*/SKILL.md` |

Both tools list each skill's `name` and `description` at the start of a session and load the body when a task matches. The format is the [Agent Skills](https://agentskills.io) format; see [skills in Claude Code](https://code.claude.com/docs/en/skills) and [skills in Codex](https://learn.chatgpt.com/docs/build-skills).

`init --skills` takes `core` (default), `all`, `none`, a group (`security`, `infra`, `web`, `languages`), or a comma list of names and groups. A name is accepted with or without the `mpa-` prefix. With both `claude` and `codex` selected the project holds two copies of each skill. Tools that read both `.claude/skills/` and `.agents/skills/` list each skill twice; select one runtime for a project that uses only such a tool.

`update` changes the set later:

| Option | Effect |
|---|---|
| `--add-skill NAME...` | Installs the named skills in every skill directory that already holds an `mpa-*` skill. |
| `--runtime LIST` | Installs the added skills in the directories of the listed runtimes instead. It is required when the project holds no `mpa-*` skill. With `generic` in the list, `update` also adds a missing `## Guides` section. |
| `--remove-skill NAME...` | Deletes the named skills from both directories. A directory that holds a file other than `SKILL.md` is kept; `update` then prints `not removed` and exits with 1. |

Both skill options take skill names. A group name is refused with exit code 2; groups belong to `init --skills`.

`check` reports an installed `mpa-*` skill that differs from the shipped text.

## Presets

`--preset` installs the files below. `.claude/settings.json` and `.codex/config.toml` are created once and belong to the project afterwards; `update` does not touch them. `.codex/rules/mpa.rules` is managed: `update` replaces it and `check` reports a difference. `init --preset` also runs on a project that is already set up and adds only the files that are missing. Options that are left out take their defaults, so repeat the `--runtime`, `--skills`, and `--state` values of the first run.

### Claude Code

The Claude Code preset makes Claude Code ask before common forms of force-pushes, deleting remote branches or tags, hard resets, adding or removing a dependency, publishing, and GitHub write commands, and stops its file tools from reading `.env` files other than `.env.example`, `.env.sample`, and `.env.template`. A command that installs what the project already declares, such as `npm install` or `pip install -r requirements.txt`, does not prompt. `npm install <name>` and `pip install <name>` add a dependency, but a prefix rule cannot tell them apart from a plain install, so they do not prompt either; the Approvals section of `AGENTS.md` covers them. The preset is a prompt on usual command forms, not a security boundary: other spellings of the same command and programs that open files themselves are not covered. For a boundary, enable the Claude Code sandbox and restrict credentials there.

Rules in `.claude/settings.json`:

- `ask`: `git push` with a force or delete option or a `:branch` refspec, `git reset --hard`, and `git clean`; commands that add or remove a dependency, such as `pnpm add`, `uv add`, and `cargo add`; publish commands, such as `npm publish`, `twine upload`, and `docker push`; `gh` commands that write, such as `gh pr create`, `gh release create`, `gh secret set`, and `gh workflow run`. The installed file is the full list.
- `deny`: `Read(.env)` and `Read(.env.*)` at any depth, with exceptions for `.env.example`, `.env.sample`, and `.env.template`.

When `.claude/settings.json` exists and holds a JSON object, `init --preset` appends the missing rules, removes nothing, and writes the file back as formatted JSON. When the existing `deny` list is not empty, the three `.env` exceptions are printed for manual addition and not appended. When the file does not parse, it is kept and the plan prints the rules to add by hand.

Claude Code evaluates `deny`, then `ask`, then `allow`. An `allow` in `.claude/settings.local.json` does not outrank an `ask` in the committed file. Personal additions go in `.claude/settings.local.json`; to drop a prompt for everyone, delete the rule from the committed file. See [permissions](https://code.claude.com/docs/en/permissions), [settings](https://code.claude.com/docs/en/settings), and [sandboxing](https://code.claude.com/docs/en/sandboxing).

To prompt on every push, add this rule:

```json
{ "permissions": { "ask": ["Bash(git push *)"] } }
```

In `.claude/settings.local.json` it applies on that machine only. In the committed `.claude/settings.json` it also applies to cloud sessions, which deliver work by pushing a branch and then wait at the prompt.

The Approvals template asks before every push. A project whose cloud or headless sessions deliver work by pushing a branch adds `- pushing a branch other than the default branch` under "No approval needed".

Deploy commands are not in the preset, because the commands and the targets differ between projects. A project adds its own, for example:

```json
{ "permissions": { "ask": ["Bash(terraform apply *)"] } }
```

### Codex

The Codex preset takes effect only in a project that Codex trusts. It removes environment variables whose names contain KEY, SECRET, or TOKEN from the commands Codex runs, and adds prompt rules for the same categories as the Claude Code preset. Codex rules match command prefixes and are marked experimental in the Codex documentation; a command written in another order is not matched. A shell line that holds a redirection, a variable, a glob, or a substitution is not split into commands, so the rules do not match what runs inside it. The preset does not change the sandbox mode or the approval policy.

Each rule in `.codex/rules/mpa.rules` has the decision `prompt` and lists examples of commands it matches and does not match. The file is replaced by `update`; project rules go in another `.rules` file in the same directory. A file that is the one from 7.0.0, or that starts with the `# Managed by mpa.py` line, is replaced; any other content is refused until it is moved out or `--force` is passed.

`.codex/config.toml` sets `ignore_default_excludes = false` under `[shell_environment_policy]`. When it exists, `init --preset` keeps it and prints the content to add by hand. See the [configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference) and [rules](https://learn.chatgpt.com/docs/agent-configuration/rules).

### Hooks

No hooks are installed. A project that wants a hard block on a command adds its own; see [hooks](https://code.claude.com/docs/en/hooks).

## Trust

- Claude Code applies `ask` and `deny` rules from project settings before the workspace is trusted. `allow` rules wait for trust.
- Codex loads the project's `.codex/` directory only after the project is marked trusted.

## Cloud sessions

A Claude Code cloud session starts from a clone of the repository.

- A session on a single repository reads the committed `CLAUDE.md`, `.claude/settings.json`, and `.claude/skills/`.
- Project threads read the instruction files at the repository root, but not the repository's permission rules, hooks, or `.claude/skills/`. A session on several repositories does not read the repositories' permission rules or hooks either.
- User-level files, `.claude/settings.local.json`, and files ignored by git are absent.

See [Claude Code on the web](https://code.claude.com/docs/en/claude-code-on-the-web).

## The notes file

`--state` controls `TODO.md`:

| Mode | Effect |
|---|---|
| `local` (default) | Creates `TODO.md` if absent and adds `/TODO.md` to `.gitignore`. The file stays on one machine. Teammates and cloud sessions do not see it. |
| `tracked` | Creates `TODO.md` if absent and leaves `.gitignore` alone. The file is committed and visible to everyone with access to the repository. |
| `none` | Creates nothing. |

An existing `TODO.md` is never modified. To switch from `local` to `tracked`, delete the `/TODO.md` line from `.gitignore` and commit the file.

## Ownership

The marked block in `AGENTS.md`, the `mpa-*` skills that this repository ships, and `.codex/rules/mpa.rules` are managed, and `update` replaces them. Everything else belongs to the project. To customise a skill, copy it to a name without the `mpa-` prefix; that copy is never touched.

- `update` replaces everything between the block markers. A block that holds a `## ` heading the shipped block lacks is refused until the text is moved out or `--force` is passed.
- `update --write` replaces or removes a file only when git tracks it and it has no unstaged changes: the index holds the file, and the bytes of the working file hash to the blob ID in the index. A file that differs from the indexed blob only in CRLF line endings counts as unchanged; one that a clean filter alters counts as changed. The dry run makes the same test and prints the result as a `refuse` line under the plan. `--force` updates a project outside git and files that are untracked, ignored, or changed.
- `update --write` prints `review with: git status and git diff` when the project is in a git work tree.
- An `mpa-*` directory with a name this repository does not ship is kept; `update` prints a note and `check` reports an error until the directory is removed or renamed without the `mpa-` prefix. `--remove-skill` deletes it when it is empty or holds only `SKILL.md`.
- An empty directory with a shipped name gets its `SKILL.md` back.

## What check reports

`check` changes nothing. It prints errors and notes, and exits with 1 when there is an error.

| Subject | Error | Note |
|---|---|---|
| Block in `AGENTS.md` | Missing, malformed, or duplicated markers; text that differs from the shipped block; a version older or newer than the checkout; text other than one title line before the block | |
| `AGENTS.md` | Larger than 32 KiB | Larger than 16 KiB; no `## Approvals` heading; empty command lines under `## Commands`; placeholder comments from the template that are unedited |
| `CLAUDE.md` | No import line outside code fences and HTML comments | No `CLAUDE.md` while `CLAUDE.local.md`, `mpa-*` skills in `.claude/skills/`, or `.claude/settings.json` exist |
| Skills | An `mpa-*` skill that differs from the shipped text, holds other files, or has a name this repository does not ship | |
| Claude Code settings | A settings file that is not a JSON object; a `claudeMdExcludes` entry that covers `AGENTS.md` or `CLAUDE.md` | |
| Other instruction files | `AGENTS.override.md` in the project root; a `.codex/rules/mpa.rules` that differs from the shipped rules | `CLAUDE.local.md`; `.claude/rules`; a `.codex/config.toml` that differs from the preset; instruction files in subdirectories; a scan for them that stops at its limit of 2,000 directories |
| Notes file | | `TODO.md` tracked by git and also listed in `.gitignore` |

An older block is updated with `update`. A newer block needs a newer checkout of this repository; `update` refuses it and prints the block. After a release that changes the block or a skill, `check` reports the project until `update` runs; pin the checkout where `check` runs in CI.

## Where the checkout lives

Keep the checkout of this repository outside the project, and do not add it as a submodule. The installed files are the copy the agent reads; the checkout is needed only to run `init`, `update`, and `check`.
