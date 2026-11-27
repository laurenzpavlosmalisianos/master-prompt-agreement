---
name: mpa-shell
description: "Checks for shell scripts and command-line wrappers. Use when writing or changing bash or sh scripts, error handling with set -e, quoting across ssh, sudo, cron, or CI fields, or destructive commands driven by variables."
---

# Shell scripts and command-line tools

- Every nested parser reads the string again: `ssh host cmd`, `sudo sh -c`, `su -c`, cron lines, Makefile recipes, CI fields. Pass data as arguments, standard input, files, or environment variables instead of interpolating into command strings.
- Before `rm -rf`, `find -delete`, `rsync --delete`, or recursive `chown`, reject empty or root-like variables and globs that match nothing or too much; give reusable destructive scripts a dry-run mode.
- Secrets do not go in arguments (visible in process lists), and `set -x` stays off around them.
