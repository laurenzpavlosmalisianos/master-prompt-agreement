# Shell and CLI Coding Quality Practice Guide

Use this Practice Guide when a task authors or changes shell scripts, command wrappers, install or bootstrap scripts, cron or automation command strings, Makefile shell recipes, CI-like local scripts, CLI contracts, or shell-driven orchestration. Do not load it for a harmless one-off command invocation unless the command text itself is being designed, persisted, reviewed, or reused.

Before source-sensitive shell or CLI recommendations, use project `SOURCE_PACKS.md` and `SOURCE_UPDATE.md` when present, then check the target shell manual, POSIX Shell and Utilities when portability matters, target OS man pages, GNU or BSD utility docs as applicable, ShellCheck, shfmt, and CLI parser/library docs for the active shell or CLI contract. Consult non-shell parser or library docs only when the shell/CLI contract directly depends on them. Treat shell dialect, utility flags, platform behavior, and linter rules as source-sensitive.

## Workflow

1. Frame the shell and CLI contract.

- identify the target shell, shebang, execution environment, operating systems, required utilities, locale, working directory, environment variables, PATH policy, privileges, and whether portability to POSIX `sh` is required
- distinguish interactive convenience commands from persisted scripts, bootstrap logic, destructive maintenance scripts, and automation jobs
- define CLI inputs, outputs, exit codes, logging, help text, config files, dry-run behavior, and failure policy before editing
- inspect callers such as Makefiles, package scripts, schedulers, hooks, docs, and automations that depend on the script
- identify every parsing boundary: local shell, remote `ssh`, `sudo sh -c`, `su -c`, `env`, Makefile, cron, package script, CI command field, or nested shell
- before adopting copied snippets, downloaded installers, remote scripts, package recipes, or generated command text, verify provenance, version, integrity, usage rights, and execution authority
- do not convert a project-specific shell contract into universal doctrine

2. Handle expansion, quoting, and data safely.

- quote parameter expansions unless intentional word splitting or globbing is explicitly required and tested
- use arrays in shells that support them when passing argv lists; in POSIX `sh`, use functions, `set --`, and `"$@"` rather than string-built argv emulation
- avoid `eval`, untrusted command strings, unsafe `xargs`, unsafe `find -exec sh -c`, and command substitution over untrusted data unless the boundary is justified and tested
- at each shell boundary, prefer argv, stdin, files, or environment variables over interpolated shell text; quote for the receiving shell, not only the local shell
- treat whitespace, newlines, leading dashes, glob characters, Unicode, empty strings, and missing variables as normal input cases
- use `--` before path or user-supplied operands where supported
- avoid parsing `ls`; prefer structured command output, null-delimited data, or language-specific scripts for complex parsing

3. Make failure, cleanup, and destructive behavior explicit.

- use strict-mode fragments deliberately; understand how `set -e`, pipelines, subshells, conditionals, traps, and command substitutions behave in the target shell
- do not add `set -euo pipefail` mechanically; test expected failure paths, command substitutions, subshells, pipelines, traps, and cleanup paths in the target shell
- check command exit status where it matters and preserve the original failing command in diagnostics
- for a command or wrapper that owns or spawns descendants, do not infer complete process success from a zero exit status for the leader or from closed output streams alone; evaluate leader status, stream completion, quiescence of the owned containment, and cleanup separately, record any unverified state, and fail closed or narrow the success claim when descendant quiescence cannot be proved
- use `trap` for cleanup of temporary files, locks, background processes, mounts, and partial outputs
- create temporary files and directories atomically with safe APIs such as `mktemp` inside the project-approved OS temporary boundary; avoid predictable fixed names, unsafe permissions, symlink races, unapproved persistent paths, and missing cleanup. A securely created entry in an approved shared OS temporary directory is not itself an unsafe fixed global path
- for `rm -rf`, `find -delete`, `rsync --delete`, recursive `chmod` or `chown`, overwrites, truncating redirections, `dd`, package-manager actions, service changes, or remote writes, require non-empty variables, resolved path or prefix checks, root, home, and mount-boundary guards, and tests for globs matching nothing or too much
- require explicit approval or a project-recorded force flag for destructive operations, privilege changes, remote writes, package installs, system service changes, and external effects
- implement dry-run or propose mode for reusable destructive or broad-scope scripts when feasible

4. Keep CLI behavior predictable.

- separate stdout intended for machine consumption from stderr diagnostics
- keep exit codes stable and documented for success, usage errors, partial failure, and external dependency failure
- provide help text for reusable commands and verify examples stay synchronized with implementation
- validate config files, environment variables, paths, URLs, credentials, and command-line flags before use; use `getopts` or a documented parser for reusable POSIX shell CLIs
- test `--`, unknown flags, missing option arguments, empty option arguments, repeated flags, operands beginning with `-`, and supported mixed option or operand ordering
- do not enable xtrace around secrets; redact diagnostics, avoid secrets in argv when stdin, files, or environment variables are safer, and avoid logging credential-bearing URLs
- avoid hidden dependence on aliases, shell profiles, interactive prompts, terminal state, local usernames, host-specific paths, or global tools
- prefer a real programming language over shell when the task requires complex parsing, data structures, concurrency, HTTP, JSON transformation, cryptography, or security-sensitive logic

5. Verify with configured tools and representative cases.

- run static shell syntax checks for the target shell before execution
- run ShellCheck and shfmt when configured or appropriate; classify warnings rather than suppressing them mechanically
- test success, usage error, missing dependency, paths with spaces, empty input, failed subprocess, interrupted run, dry-run, and destructive-protection behavior where relevant
- do not execute install, bootstrap, migration, cleanup, remote-write, package-install, or destructive scripts unless the task authorizes it and the command is sandboxed, dry-run, or otherwise bounded
- verify shell scripts in the same runner, container, OS, and working directory that the project uses
- state clearly when portability, target shell, OS utilities, permissions, or external commands could not be verified

## Output

Provide applicable items. For persisted automation, destructive actions, privilege changes, remote writes, portability claims, or reusable CLI contracts, include all items:

1. target shell, OS, utilities, runner, CLI contract, and source facts used
2. affected argv, environment, file, stdout/stderr, exit-code, cleanup, and destructive-action contracts
3. quoting, expansion, parsing, portability, privilege, dependency, and cleanup risks
4. syntax, ShellCheck, shfmt, CLI, failure-path, dry-run, and destructive-protection checks run
5. unverified shell, platform, utility, permission, and environment states plus residual risk

## Guardrails

- Do not rely on shell profile state, aliases, current directory accidents, or global tools unless the project contract says so.
- Do not use `eval` or shell strings for untrusted data when structured argv or a safer language is available.
- Do not hide destructive behavior behind terse flags, implicit defaults, or "cleanup" wording.
- Do not silence ShellCheck or formatter output without explaining the invariant.
- Do not use shell for complex or security-sensitive parsing when a structured language is the safer, clearer tool.
