# CLI reference

`mpa.py` sets up, updates, and checks Master Prompt Agreement files in a project directory. It requires Python 3.10 or newer with the standard library only. Run it with `-B` so Python writes no bytecode inside the checkout.

```bash
python3 -B /path/to/master-prompt-agreement/mpa.py [--version] {init,update,check} ...
```

Exit codes: `0` on success, `1` on refusal, check error, or a skill directory that could not be removed, and `2` on invalid options or arguments. `init` and `update` print a plan and change nothing until `--write` is passed.

## init

```bash
python3 -B /path/to/master-prompt-agreement/mpa.py init PROJECT [--runtime LIST] [--skills SPEC] [--write]
```

Adds the managed working-agreement block, any required `CLAUDE.md` import, and the selected `mpa-*` skills where they are missing. A second run adds only missing files and prints `nothing to do` when nothing is pending.

### Options

| Option | Values | Default |
|---|---|---|
| `--runtime LIST` | Comma list of `agents`, `codex`, `antigravity`, `generic`, `claude`, `copilot`, `gemini` | Resolved from the project (see below) |
| `--skills SPEC` | `all`, `none`, or a comma list of skill names and installable bundles (`core`, `security`, `agents`, `data`, `infra`, `web`) | `core` |
| `--write` | Applies the plan | Off (dry run) |

### Runtime output matrix

`CLAUDE.md` is created or updated only when `claude` is in the selected runtimes.

| `--runtime` value | Files written | Notes |
|---|---|---|
| `agents` | `AGENTS.md`, `.agents/skills/mpa-*/SKILL.md` | Fresh-project default; single-copy Agent Skills layout (Codex, Antigravity, GitHub Copilot, Gemini CLI, other tools that load `.agents/skills/`) |
| `codex` | `AGENTS.md`, `.agents/skills/mpa-*/SKILL.md` | Alias for `.agents/skills/` |
| `antigravity` | `AGENTS.md`, `.agents/skills/mpa-*/SKILL.md` | Alias for `.agents/skills/` |
| `copilot`, `gemini` | `AGENTS.md`, `.agents/skills/mpa-*/SKILL.md` | Names for `agents` (GitHub Copilot and Gemini CLI load `.agents/skills/`); repeated with `agents`, they count once. With `gemini`, `init` notes that Gemini CLI reads `AGENTS.md` only when its `context.fileName` setting lists it |
| `generic` | `AGENTS.md` (with `## Guides`), `.agents/skills/mpa-*/SKILL.md` | Adds a `## Guides` pointer when `.agents/skills/` holds or receives an `mpa-*` skill |
| `claude` | `AGENTS.md`, `CLAUDE.md` (`@AGENTS.md`), `.claude/skills/mpa-*/SKILL.md` | Native Claude Code layout; uses `.claude/CLAUDE.md` (`@../AGENTS.md`) when only that file already exists |
| `claude,agents` (or `claude,codex`, `claude,antigravity`) | `AGENTS.md`, `CLAUDE.md`, `.claude/skills/mpa-*/`, `.agents/skills/mpa-*/` | Prints a note that holding skills in both directories doubles startup listings in tools that scan both |

### Omitted `--runtime` resolution

When `--runtime` is omitted, `init` resolves the target runtimes in order:

1. Existing non-symlink `mpa-*` skill directories under `.claude/skills/` and `.agents/skills/` (`claude`, `agents`, or both).
2. Otherwise, if `CLAUDE.md`, `.claude/CLAUDE.md`, or `.claude/settings.json` exists in the project root, `claude`. A `.claude/` directory without one of these files, such as one holding only `settings.local.json` or skills without the `mpa-` prefix, does not select `claude`.
3. Otherwise, `agents`.

### Skill selection

Skill names are accepted with or without the `mpa-` prefix. The six installable bundles (`core`, `security`, `agents`, `data`, `infra`, `web`) install their full category. Note that `agents` is both a `--runtime` value and a `--skills` bundle (`mpa-agent-inputs`, `mpa-agent-instructions`, and `mpa-delegation`); the flag selects which meaning applies.

`languages` and `platforms` are individual-only pick-lists in the [skill catalogue](../skills/README.md), not installable bundles. Passing `languages` or `platforms` as a bundle token exits with code `2` and prints the individual skill names in that category.

### Adopting existing instruction files

- **Existing `AGENTS.md` without a managed block:** `init` inserts the managed block after a leading H1 line (or at the top if there is none), places any missing adopted sections (`## Approvals`, `## Commands`, `## Constraints`, and `## Guides` for `generic` with skills) directly after `<!-- mpa:end -->`, and preserves all existing text, byte-order marks, and CRLF or CR line endings. It prints notes when existing `## Approvals` or `## Constraints` sections are kept, when block marker lines appear only inside code fences (a fence may be hiding the block), and reminds that existing text is not reviewed.
- **Existing `AGENTS.md` with a managed block:** keeps a block of the current version (or appends `## Guides` when `--runtime generic` is used with skills and the heading is missing). Refuses a block of another version with a prompt to run `update`.
- **Existing `CLAUDE.md` or `.claude/CLAUDE.md` (with `claude` selected):** keeps the setup if either file already symlinks to `AGENTS.md` or contains its exact import line (`@AGENTS.md` or `@../AGENTS.md`) outside code fences and HTML comments; otherwise inserts the import line into `CLAUDE.md` (or `.claude/CLAUDE.md` when only that file exists).
- **Existing skills and limits:** refuses if an existing `mpa-*` `SKILL.md` differs from the shipped copy, or if `AGENTS.md` would exceed 32 KiB once written. An `AGENTS.md` above 32 KiB that `init` leaves unchanged is kept with a note that Codex stops reading it, Antigravity truncates it at 24,000 bytes, and `check` reports it as an error. Notes when `AGENTS.md` exceeds 16 KiB but not 32 KiB, when a fresh or adoption run omits `--runtime` and defaults to `agents` (naming `--runtime claude` and `--runtime claude,agents`), when `AGENTS.override.md` or `CLAUDE.local.md` (with `claude`) exists, when an existing `CLAUDE.md` or `.claude/CLAUDE.md` has no `AGENTS.md` import while `claude` is not selected, and when an existing file that `init` modifies is not committed in git.

## update

```bash
python3 -B /path/to/master-prompt-agreement/mpa.py update PROJECT [--add-skill NAME ...] [--remove-skill NAME ...] [--runtime LIST] [--write] [--force]
```

Replaces the managed block in `AGENTS.md` and every installed shipped `mpa-*` `SKILL.md` that differs from the checkout. Everything outside the managed block in `AGENTS.md`, `CLAUDE.md`, and custom non-`mpa-*` skill directories is left untouched, including the `## Approvals` section.

`update` takes one project. To update several projects, run it once for each: `for p in site-a site-b; do python3 -B mpa.py update "$p" --write; done`.

### Options

| Option | Effect |
|---|---|
| `--add-skill NAME ...` | Installs additional skills by skill name or installable bundle (`core`, `security`, `agents`, `data`, `infra`, `web`). Accepts space-separated tokens, comma-separated lists, or repeated flags. |
| `--remove-skill NAME ...` | Removes matching `mpa-*` skill directories from both `.claude/skills/` and `.agents/skills/`, by skill name or installable bundle (space-separated, comma-separated, or repeated). |
| `--runtime LIST` | Selects which runtimes receive `--add-skill` names instead of the directories that already hold `mpa-*` skills. Required when no `mpa-*` skill directory exists yet. With `generic`, also adds a missing `## Guides` section when `.agents/skills/` holds or receives an `mpa-*` skill. |
| `--write` | Applies the plan. When inside a git work tree, prints `review with: git status and git diff`. |
| `--force` | Lifts the git cleanliness guard and lifts the refusal to replace a managed block that holds a `## ` heading the shipped block lacks. |

### Selection and edge cases

- `all`, `none`, `languages`, `platforms`, and overlapping `--add-skill` / `--remove-skill` names exit with code `2`.
- `--remove-skill` also removes an unshipped `mpa-*` directory when it is empty or holds only `SKILL.md`. A skill directory holding any file other than `SKILL.md` is kept, and `update` prints `not removed:` to stderr and exits with `1`. A named skill that is not installed produces a note.
- An empty `mpa-*` directory with a shipped name gets its `SKILL.md` recreated by `update` unless removed.
- An unshipped `mpa-*` directory is kept with a note (`check` reports it as an error until it is removed or renamed without the `mpa-` prefix). A non-directory or symlink `mpa-*` entry is kept with a note, or refused if named in `--add-skill` or `--remove-skill`.
- A managed block whose version is newer than the checkout is refused even with `--force`, and the existing block text is printed so nothing newer is overwritten silently.
- An `AGENTS.md` that `update` would write larger than 32 KiB is refused. One above 32 KiB that `update` leaves unchanged is kept with the same note as `init`, and one above 16 KiB but not 32 KiB, written or unchanged, produces the 16 KiB note.

## check

```bash
python3 -B /path/to/master-prompt-agreement/mpa.py check PROJECT
```

Inspects an installed setup, prints errors and notes, and exits with `1` when there is at least one error (`0` otherwise). `check` changes nothing and runs zero `git` subprocesses.

After an MPA release that changes the managed block or a shipped skill, `check` reports the difference until `update` runs; pin the MPA checkout where `check` runs in CI.

## File ownership and guard

- **Managed by MPA (`update` replaces them):** the text between `<!-- mpa:begin ... -->` and `<!-- mpa:end -->` in `AGENTS.md`, and shipped `mpa-*` `SKILL.md` files under `.claude/skills/` and `.agents/skills/`.
- **Owned by the project (never overwritten by `update`):** all text outside the block in `AGENTS.md`, `CLAUDE.md` and `.claude/CLAUDE.md`, and any skill directory whose name does not start with `mpa-`. To customise a skill, copy it to a directory name without the `mpa-` prefix.
- **Git cleanliness guard:** `update --write` replaces, appends to, or removes an existing file only when the project is inside a git work tree, git tracks the file once in the index (not untracked, ignored, or conflicted), and the file's bytes (or LF-normalised bytes) hash to the indexed blob ID. `mpa.py` hashes the working file directly, so git runs no clean filter; a file altered only by CRLF conversion counts as unchanged, while one altered by a clean filter counts as changed. Dry-run `update` runs the same check and prints a `refuse` line under the plan (`dry run: nothing changed; --write refuses this plan`).
- **`--force` boundaries:** `--force` bypasses the git cleanliness guard and allows replacing a managed block that contains headings absent from the shipped block. It does not bypass newer block versions, malformed markers, symbolic links, unwritable targets, or the 32 KiB `AGENTS.md` cap.
- **Write safety:** `mpa.py` checks write permissions before making changes, refuses symbolic links in targets or parent paths, refuses non-regular files and paths escaping the project root, reads at most 1 MiB per file, writes new files exclusively or replaces existing files atomically via a sibling `.tmp-*` file, and writes `AGENTS.md` last. See [SECURITY.md](../SECURITY.md) for git invocation details.

## What check reports

| Subject | Error | Note |
|---|---|---|
| Managed block in `AGENTS.md` | Missing `AGENTS.md`, missing/malformed/duplicated markers (naming a possibly hidden block when marker lines appear only inside code fences), a marker inside a code fence left open to the end of the file, text other than one H1 line before the block, block version older or newer than the checkout, block text differing from the shipped block | |
| Root `AGENTS.md` | Larger than 32 KiB (Codex default limit, and above Antigravity's 24,000-byte single-file cap) | Larger than 16 KiB (early warning before Antigravity's 24,000-byte single-file cap and Codex's 32 KiB limit); missing `## Approvals` heading |
| `CLAUDE.md` and `.claude/CLAUDE.md` | Invalid symlink, wrong file type, unreadable, or neither existing file symlinks to `AGENTS.md` nor contains its exact import line (`@AGENTS.md` / `@../AGENTS.md`) outside code fences and HTML comments | No `CLAUDE.md` / `.claude/CLAUDE.md` while `CLAUDE.local.md`, `.claude/skills/mpa-*`, or `.claude/settings.json` exists; both `CLAUDE.md` and `.claude/CLAUDE.md` exist |
| Skills | Symlinked skill path, non-directory `mpa-*` entry, unshipped `mpa-*` directory, extra files beside `SKILL.md`, missing `SKILL.md`, or `SKILL.md` differing from the shipped copy | Shipped `mpa-*` startup listing total (`name` + `description`) exceeding 8,000 characters in `.agents/skills` or `.claude/skills`; both `.claude/skills` and `.agents/skills` holding `mpa-*` skills (double listing); different `mpa-*` skill sets between the two directories |
| Claude Code settings | `.claude/settings.json` or `.claude/settings.local.json` unreadable or not a JSON object; a `claudeMdExcludes` glob matching `AGENTS.md` or an existing `CLAUDE.md` / `.claude/CLAUDE.md` | |
| Other instruction files | `AGENTS.override.md` in the project root | `AGENTS.md` files in subdirectories, found by a breadth-first scan that skips hidden directories, `node_modules`, and symbolic links; the scan stopping after 2,000 directories |

For how each runtime loads these files and enforces sandboxes and permissions, see [docs/runtimes.md](runtimes.md).
