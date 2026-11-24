---
name: mpa-shell
description: "Checks for shell scripts and command-line wrappers. Use when writing or changing bash or sh scripts, error handling with set -e, quoting across ssh, sudo, cron, or CI fields, or destructive commands driven by variables."
---

# Shell scripts and command-line tools

- Match the shell named in the shebang (POSIX `sh` and bash differ) and check utility flags against the target OS because GNU and BSD tools differ (`sed -i`, `date`, `readlink`, `xargs`).
- `set -e` does not do what it appears to: it is suspended inside conditions, `&&` and `||` lists, and functions called from them; it misses failed command substitutions in arguments or behind `local`, `export`, or `declare`, and without `pipefail` it misses failed pipeline stages. Test failure paths.
- Quoting does not protect arithmetic contexts: `$(( ))`, `[[ -eq ]]`, `declare -i`, and array subscripts evaluate data as code, including `a[$(cmd)]`. Validate that a value is a number first.
- Every nested parser reads the string again: `ssh host cmd`, `sudo sh -c`, `su -c`, cron lines, Makefile recipes, CI fields. Pass data as arguments, standard input, files, or environment variables instead of interpolating into command strings.
- Put `--` before operands from elsewhere; filenames can start with `-` and contain newlines, so use null-delimited output.
- Before `rm -rf`, `find -delete`, `rsync --delete`, or recursive `chown`, reject empty or root-like variables and globs that match nothing or too much; give reusable destructive scripts a dry-run mode.
- Secrets do not go in arguments (visible in process lists), and `set -x` stays off around them.
- A wrapper exiting zero has not shown that background processes it started finished.
