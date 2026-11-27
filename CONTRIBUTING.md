# Contributing

## Commands

- Test: `uv run --no-project python -E -S -B -m unittest discover -s tests`
- Hygiene: `uv run --no-project python -E -S -B tools/hygiene.py`
- Check the repository's own `AGENTS.md`: `uv run --no-project python -E -S -B mpa.py check .`
- Try the tool: `uv run --no-project python -E -S -B mpa.py init <empty-dir>`

Python 3.10 or newer, standard library only. Run Python with `-B`. Without `uv`, `python3 -B -m unittest discover -s tests` runs the tests too. Before a release, run the tests on Python 3.10 as well.

## Hygiene

`tools/hygiene.py` reports secrets, local paths and addresses, links outside the allowed places, and working files. Samples use the reserved values that it accepts: IPv4 addresses in 192.0.2.0/24, 198.51.100.0/24, or 203.0.113.0/24, and email addresses at `example.com`, `example.net`, `example.org`, or under `.test`, `.example`, or `.invalid`. Without an argument it scans the work tree; `--staged` suits a pre-commit hook, `--commit-msg FILE` a commit-msg hook, and `--log RANGE` scans the messages of a revision range.

## Skills

- A skill is `skills/<name>/SKILL.md` and nothing else in that directory. The frontmatter has exactly `name`, equal to the directory name, and `description`.
- `description` is a double-quoted, single-line string without `<` or `>`. It says what the skill covers and when to use it, because it is all an agent sees before it opens the skill. It stays short: every installed description loads in every session. It may send a neighbouring topic to the skill that owns it; it does not ask for a second skill alongside.
- A line is in a skill because it changes what an agent does. Sentences are plain imperatives, with the reason attached where it is not obvious.
- A rule lives in one skill. Another skill refers to it by skill name.
- A statement about a tool's behaviour is true for the versions it names.
- A stack skill carries release knowledge of named products and opens with a coverage line: `Current to <products and versions>, checked <date>. For a newer <product> release, read what changed after <version> in the release notes (<official address>) before relying on this file; up to <version> no lookup is needed.` Entries run newest first and give the version, the exact name of the setting or directive, and what breaks. The line moves only when the release notes were read again. Its address is the only link a skill holds and is listed in `SKILL_SOURCES` in `tools/hygiene.py`.
- A new skill is added to `CATALOG` in `mpa.py` and to the table in `skills/README.md`.

## The block

The block in `README.md` is a copy of `templates/block.md`. After a change to `templates/block.md`, update `README.md`, raise `BLOCK_VERSION` in `mpa.py`, and run `mpa.py update . --write`.

## Releases

A change to the block or to a skill needs a minor release; a patch release leaves every installed file unchanged. The changelog names the versions each stack skill now covers.

## Commits

- The subject is an imperative description of the change, and the body lists what changed.
- Commit messages hold no email addresses, so they carry no sign-off trailers.
- Changelog entries sit under Added, Changed, Removed, Fixed, and Security.
