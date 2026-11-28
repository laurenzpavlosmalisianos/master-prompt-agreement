# Contributing

## Commands

- Test: `uv run --no-project python -E -S -B -m unittest discover -s tests`
- Hygiene: `uv run --no-project python -E -S -B tools/hygiene.py`

Python 3.10 or newer, standard library only. Run Python with `-B`. Without `uv`, `python3 -B -m unittest discover -s tests` runs the tests too. Before a release, run the tests on Python 3.10 as well.

## Hygiene

`tools/hygiene.py` reports local paths, mail addresses, IP addresses, private key headers, and token shapes of common services. Samples use the values that it accepts: IPv4 addresses in 192.0.2.0/24, 198.51.100.0/24, or 203.0.113.0/24, and email addresses at `example.com`, `example.net`, `example.org`, or under `.test`, `.example`, or `.invalid`. Without an argument it scans the work tree; `--staged` suits a pre-commit hook and `--commit-msg FILE` a commit-msg hook.

## Skills

- A skill is `skills/<name>/SKILL.md` and nothing else in that directory. The frontmatter has exactly `name`, equal to the directory name, and `description`.
- `description` is a double-quoted, single-line string without `<` or `>`. It says what the skill covers and when to use it, because it is all an agent sees before it opens the skill. It stays short: every installed description loads in every session. It names another skill only where matching the wrong one would lead to a harmful step; it does not ask for a second skill alongside.
- A line is in a skill because it changes what an agent does. Sentences are plain imperatives, with the reason attached where it is not obvious.
- A rule lives in one skill. Another skill refers to it by skill name.
- A statement about a tool's behaviour is true for the versions it names.
- A stack skill carries release knowledge of named products and opens with a coverage line: `Current to <products and versions>, checked <date>. The entries are the changes that are easy to miss, not the full release notes: for a change they do not mention, and for anything newer than <version>, read the release notes (<official addresses>) before relying on this file.` For two products, `<version>` is `those versions`. Entries run newest first and give the version, the exact name of the setting or directive, and what breaks. Its versions and date move as the section on refreshing the stack skills says. Its addresses are the only links a skill holds.
- A new skill is added to the table in `skills/README.md`.
- A skill file stays within 7,000 bytes. A skill earns its own file only when its body holds enough distinct, non-obvious rules to outweigh its always-loaded description.

## Refreshing the stack skills

1. For each product on a coverage line, read the newest release of each branch named on the line (stable, and mainline where named) from the product's official release page or tag list on the day of the refresh. A version from memory or from the summary of a search result does not count, and neither does a pre-release.
2. For each product that is behind, read the release notes at the addresses in its coverage line, from the covered version to the newest one, and add, change, or remove entries. An entry names the first released version that contains the change, the exact setting or directive, and what breaks. Where notes disagree or name a version that was never released, the tagged artifact decides: the file at the tag, or the commits between two tags.
3. A version in a coverage line moves only after that product's notes were read. The date moves only on a day on which step 1 covered every product on the line, whether or not anything was refreshed, and the date in a security section moves with it. When a page cannot be read, the date stays.
4. A security section names the patched release of each supported branch with the check date, and a single fix only when it changes what an agent writes or what it asks a host.
5. A second reader checks every new or changed entry against the primary source before the release, and checks that the addresses in each coverage line are unchanged or were changed on purpose.

## The block

`README.md` and this repository's `AGENTS.md` each hold a copy of `templates/block.md`. After a change to that file, replace both copies with it.

## Releases

A change to the block or to a skill needs a minor release; a patch release leaves every installed file unchanged. The changelog names the versions each stack skill now covers. Removing or renaming a skill needs a major release, and the changelog names the directory to delete.

## Commits

- The subject is an imperative description of the change, and the body lists what changed.
- Commit messages hold no email addresses, so they carry no sign-off trailers.
- Changelog entries sit under Added, Changed, Removed, Fixed, and Security.
