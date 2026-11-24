# Contributing

## Commands

- Test: `uv run --no-project python -E -S -B -m unittest discover -s tests`
- Hygiene: `uv run --no-project python -E -S -B tools/hygiene.py`
- Check the repository's own `AGENTS.md`: `uv run --no-project python -E -S -B mpa.py check .`
- Try the tool: `uv run --no-project python -E -S -B mpa.py init <empty-dir>`

Python 3.10 or newer, standard library only. Run Python with `-B`. Without `uv`, `python3 -B -m unittest discover -s tests` runs the tests too. Before a release, run the tests on Python 3.10 as well: `uv run --no-project --python 3.10 python -E -S -B -m unittest discover -s tests`.

## Hygiene

`tools/hygiene.py` reports secrets, local paths and addresses, links outside the allowed places, and working files. It exits with 1 when it has findings and with 2 on a bad argument.

| Invocation | Scans |
|---|---|
| no argument | Every tracked and unignored file in the work tree |
| `PATH...` | Only the named files and directories |
| `--staged` | The staged content of the staged files, which suits a pre-commit hook |
| `--commit-msg FILE` | One commit message file, which suits a commit-msg hook. Comment lines are scanned too, up to a scissors line. |
| `--log RANGE` | The commit messages in a git revision range |

## Skills

- A skill is `skills/<name>/SKILL.md` and nothing else in that directory (no subdirectories, scripts, or external URLs). The YAML frontmatter has exactly `name`, equal to the directory name, and `description`, with no `disable-model-invocation`.
- `description` is a double-quoted, single-line, third-person string of at most 320 characters with zero `<` or `>` XML brackets and zero inline ALL-CAPS emphasis words (`MANDATORY`, `CRITICAL`, `MUST`, `NEVER`, `ALWAYS`, `DO NOT`). It says what the skill covers, then `Use when` with the terms a matching request contains.
- **Directional contrast redirects:** restrict description redirects to (1) one-way specialised -> general or core redirects (using complementary phrasing such as `Pair with ...` when two skills validly co-activate on the same task) and (2) co-installed intra-bundle siblings. General discipline skills (`mpa-web-frontend`, `mpa-seo`, `mpa-php`) never name downstream platform skills, and default `core` descriptions never name optional cross-bundle skills.
- **Frontier-model non-redundancy bar:** omit generic textbook basics and rules a linter enforces that frontier models already follow natively. Retain version-specific traps, breaking-change hazards, security edge cases, and explicit verification or approval invariants.
- Sentences are plain imperatives, with the reason attached where it is not obvious. No capitals for emphasis.
- A rule lives in one skill. Another skill refers to it by skill name (`mpa-*`), never by file path, and tests verify every `mpa-*` reference resolves in `CATALOG`. Cross-bundle body references inside `core` skills are phrased defensively (`if installed`).
- A statement about a tool's behaviour is true for the versions it names, or it is written as a requirement.
- Closing summary sections in workflow skills use `## Report` and prescribe at most a short list of what a report contains.
- A new skill is added to `CATALOG` (and `INDIVIDUAL_ONLY` when it is not part of an installable bundle) in `mpa.py` and to the matching `| Skill | Category | Install | Covers |` row in `skills/README.md`. `BUNDLES` derives from `CATALOG` and `INDIVIDUAL_ONLY`, and tests verify parity.

## Sizes

The tests cap `templates/block.md` (1,500 bytes), `templates/AGENTS.template.md` (1,700 bytes), each individual skill (`SKILL_CAP = 5,000` bytes), and each skill description (320 characters). There is no global repository-wide skill sum; per-project startup listing budgets are reported as notes by `mpa.py check`.

## Copies in the README

The working-agreement block in `README.md` is a verbatim copy of `templates/block.md`, and a test compares the two. After a change to `templates/block.md`, update `README.md`, bump `BLOCK_VERSION` in `mpa.py` and `BLOCK_SHA256` in `tests/test_mpa.py`, and run `mpa.py update . --write`.

## Text

- Documentation is in the present tense and describes what the software does.
- Links appear only in `docs/runtimes.md` (HTTPS to official runtime documentation hosts) and `docs/external-skills.md` (exact allowlisted first-party vendor repository root HTTPS URLs). `templates/` and `skills/` hold no links. `tools/hygiene.py` enforces full-token `urlsplit` allowlisting.
- Diagrams are Mermaid blocks in Markdown, without custom colours.
- Notes, task lists, and logs are not committed.

## External skill companions

`docs/external-skills.md` applies binary first-party vendor admission criteria:

- Admit only a repository published by an official first-party platform, browser, or security vendor that pairs with MPA as an additive companion. Do not list community directories, unverified mirrors, or personal repositories.
- Add the repository's exact root HTTPS URL (no subpath, query, or fragment) to `EXACT_REPOS` in `tools/hygiene.py`, document how it pairs with MPA without removing committed `mpa-*` skills, and include version/SHA pinning guidance with zero floating `@latest` or default-branch install one-liners.
- Keep `templates/` and `skills/` completely free of external URLs and third-party licences.

## Diff audit checklist

Before merging changes to templates, skills, or runtime documentation, run a fresh-context diff audit covering:

1. **Official-doc accuracy:** verify every version floor, breaking change, config default, and runtime limit against current official documentation.
2. **Cross-skill duplication:** confirm each rule has a single home and every `mpa-*` cross-reference resolves cleanly without duplicating bullets across skills.
3. **Directive contradictions:** verify no rule conflicts with `templates/block.md`, `## Approvals`, or a sibling skill that can co-activate on the same task.
4. **Originality and hygiene:** confirm all product text is original Apache-2.0 wording with zero copied structure, secrets, local paths, or unallowlisted links.
5. **Empirical model-era rule pruning:** remove generic instructions that current frontier models already satisfy reliably without prompting, retaining version traps, non-obvious failure modes, and approval/verification invariants.

## Commits

- The subject is an imperative description of the change, for example `Add --runtime antigravity alias to init`.
- The body lists what changed.
- Commit messages hold no email addresses, so they carry no sign-off trailers.
- CHANGELOG entries sit under the headings Added, Changed, Removed, Fixed, and Security.
- Code comments state what the code does or a constraint it meets. Test names state the behaviour under test.
