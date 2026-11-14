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

- A skill is `skills/<name>/SKILL.md` and nothing else in that directory. The frontmatter has exactly `name`, equal to the directory name, and `description`.
- The description is in the third person and has at most 300 characters. It says what the skill covers, then "Use when" with the terms a matching request would contain.
- The body holds checks that are specific to the task. General advice and rules a linter enforces stay out.
- Sentences are plain imperatives, with the reason attached where it is not obvious. No capitals for emphasis.
- A rule lives in one skill. Another skill refers to it by skill name, not by file path.
- A statement about a tool's behaviour is true for the versions it names, or it is written as a requirement.
- A skill prescribes at most a short list of what a report contains.
- A new skill is added to `GROUPS` in `mpa.py` and to `skills/README.md`.

## Sizes

The tests cap the size of `templates/block.md`, `templates/AGENTS.template.md`, each skill, and the skills in total.

## Copies in the README

- The block in `README.md` is a copy of `templates/block.md`, and a test compares the two.
- The plan in `README.md` is the output of `mpa.py init <empty-dir> --runtime claude --skills mpa-review,mpa-research --preset`, and a test compares the two.

## Text

- Documentation is in the present tense and describes what the software does.
- Links go only to the official documentation of the tools covered, and only in `docs/runtimes.md`. Skills hold no links. `tools/hygiene.py` holds the list of accepted hosts.
- Diagrams are Mermaid blocks in Markdown, without custom colours.
- Notes, task lists, and logs are not committed.

## Commits

- The subject is an imperative description of the change, for example `Add --state option to init`.
- The body lists what changed.
- Commit messages hold no email addresses, so they carry no sign-off trailers.
- CHANGELOG entries sit under the headings Added, Changed, Removed, Fixed, and Security.
- Code comments state what the code does or a constraint it meets. Test names state the behaviour under test.
