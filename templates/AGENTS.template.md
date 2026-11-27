# {name}

{block}

## Approvals

Ask first:
- pushing, or rewriting pushed history
- deleting files or data, or discarding uncommitted changes, that this task did not create
- adding, removing, or upgrading a dependency
- anything that takes effect outside this repository: deploying, publishing a package or release, posting to issue trackers, pull requests, or chat on the user's behalf, sending project code, secrets, or user data to an external service, changing accounts or paid services
- changing files that instruct or configure agents (instruction, skill, hook, permission, and tool or MCP configuration files), or CI workflows
- committing when the request did not ask for a commit

No approval needed:
- reading, creating, and editing other files in this repository, and running tests, linters, builds, and other commands that change nothing outside it except temporary and cache files
- despite the list above, in a cloud or pull request session that the user started to deliver through its own branch or pull request: committing, pushing that branch without rewriting its pushed history, and commenting on that pull request

## Project

<!-- One or two lines: what this is and who uses it. -->

## Commands

<!-- Exact commands (add a fast targeted test command if the full suite is slow). Delete unused lines. -->
- Test:
- Lint and format:
- Type check:
- Build:
- Run:

## Constraints

<!-- Working scope and one line per project fact the code does not show. -->
- Scope: change only what the task needs, match existing conventions, and report other problems instead of fixing them.
