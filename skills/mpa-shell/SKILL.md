---
name: mpa-shell
description: Checks for shell scripts and command-line wrappers kept in the repository. Use when writing or changing bash or sh scripts, error handling with set -e, quoting across ssh, sudo, cron, or CI fields, or destructive commands driven by variables.
---

# Shell scripts and command-line tools

- Write for the shell named in the shebang; POSIX `sh` and bash differ. Check utility flags against the target operating system, because GNU and BSD tools differ (`sed -i`, `date`, `readlink`, `xargs`).
- `set -e` does not do what it appears to. It is suspended inside conditions, `&&` and `||` lists, and functions called from them. It misses a failed command substitution in an argument or behind `local`, `export`, or `declare`, and without `pipefail` it misses a failed pipeline stage. Test the failure paths.
- Quoting does not protect arithmetic contexts. `$(( ))`, `[[ -eq ]]`, `declare -i`, and array subscripts evaluate data as code, including `a[$(cmd)]`. Validate that a value is a number first.
- Every nested parser reads the string again: `ssh host cmd`, `sudo sh -c`, `su -c`, cron lines, Makefile recipes, CI fields. Pass data as arguments, standard input, files, or environment variables, not by interpolation into the command string.
- Put `--` before operands that come from elsewhere. Filenames can begin with `-` and contain newlines; use null-delimited output.
- Before `rm -rf`, `find -delete`, `rsync --delete`, or a recursive `chown`, reject an empty or root-like variable and a glob that matches nothing or too much. A reusable destructive script gets a dry-run mode.
- Secrets do not go in arguments, where the process list shows them, and `set -x` stays off around them.
- A wrapper that exits zero has not shown that the background processes it started finished.
