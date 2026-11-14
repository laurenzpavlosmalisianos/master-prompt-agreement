# {name}

{block}

## Project

<!-- What this is and who uses it. -->

## Commands

<!-- Exact commands. Delete unused lines. -->
- Test:
- Lint and format:
- Type check:
- Build:
- Run:

## Approvals

Ask first:
- pushing, or rewriting pushed history
- deleting files or data, or discarding uncommitted changes, that this task did not create
- adding, removing, or upgrading a dependency
- anything that takes effect outside this repository: deploying, publishing a package or release, posting to issue trackers, pull requests, or chat on the user's behalf, sending code or data to an external service, changing accounts or paid services
- changing agent instruction or permission files (such as `AGENTS.md`, `CLAUDE.md`, `.claude/`, `.codex/`, `.agents/`, `.mcp.json`) or CI workflows
- committing when the request did not ask for a commit

No approval needed:
- reading, creating, and editing other files in this repository, and running tests, linters, builds, and other commands that change nothing outside it except temporary and cache files

## Code latitude

Change only what the task needs. Match the existing structure, and report other problems you notice instead of fixing them.

## Constraints

<!-- One line per fact the code does not show. -->
