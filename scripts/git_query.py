#!/usr/bin/env python3

"""Closed Git query policy for caller-selected repositories."""

from __future__ import annotations

from collections.abc import Sequence
import os
from pathlib import Path
import shutil


def default_path_git_executable() -> str:
    """Resolve Git without consulting the caller's ambient PATH."""

    candidate = shutil.which("git", path=os.defpath)
    if candidate is None:
        raise RuntimeError(
            "Git executable was not found on the platform default executable path"
        )
    candidate_path = Path(candidate)
    if not candidate_path.is_absolute():
        raise RuntimeError(
            "platform default executable path returned a non-absolute Git executable"
        )
    try:
        resolved = candidate_path.resolve(strict=True)
    except OSError as exc:
        raise RuntimeError(f"Git executable cannot be resolved: {candidate}: {exc}") from exc
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        raise RuntimeError(f"Git executable is not a regular executable file: {resolved}")
    return str(resolved)


def closed_git_query_environment(repo_root: Path) -> dict[str, str]:
    """Return a minimal environment that excludes ambient Git configuration."""

    root = repo_root.resolve()
    return {
        "GIT_ATTR_NOSYSTEM": "1",
        "GIT_CONFIG_COUNT": "0",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_DISCOVERY_ACROSS_FILESYSTEM": "0",
        "GIT_DIR": str(root / ".git"),
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_PAGER": "cat",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_WORK_TREE": str(root),
        "LC_ALL": "C",
        "PATH": os.defpath,
    }


def closed_git_query_command(
    arguments: Sequence[str],
    *,
    executable: str | None = None,
) -> list[str]:
    """Return a closed argv for one maintained read-only Git query shape."""

    selected = list(arguments)
    if not selected:
        raise ValueError("Git query arguments must not be empty")
    subcommand = selected[0]
    if subcommand == "diff":
        required = {"--no-ext-diff", "--no-textconv", "--name-only", "-z"}
        if not required.issubset(selected) or "--" not in selected:
            raise ValueError(
                "Git diff query must disable external diff and text conversion "
                "and request NUL-delimited names only"
            )
    elif subcommand == "ls-files":
        if "--" not in selected:
            raise ValueError("Git ls-files query must terminate options with --")
    elif subcommand == "cat-file":
        if len(selected) != 3 or selected[1] not in {"-s", "blob"}:
            raise ValueError("Git cat-file query must request one blob or blob size")
    elif subcommand == "check-ignore":
        if selected[1:4] != ["--no-index", "-q", "--"] or len(selected) != 5:
            raise ValueError("Git check-ignore query must use the maintained exact form")
    else:
        raise ValueError(f"unsupported Git metadata query: {subcommand}")

    if executable is None:
        qualified_executable = default_path_git_executable()
    else:
        candidate = Path(executable)
        if not candidate.is_absolute():
            raise ValueError("explicit Git executable must be an absolute path")
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as exc:
            raise ValueError(
                f"explicit Git executable cannot be resolved: {candidate}: {exc}"
            ) from exc
        if not resolved.is_file() or not os.access(resolved, os.X_OK):
            raise ValueError(
                f"explicit Git executable is not a regular executable file: {resolved}"
            )
        qualified_executable = str(resolved)

    return [
        qualified_executable,
        "--no-optional-locks",
        "-c",
        "core.attributesFile=/dev/null",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "core.excludesFile=/dev/null",
        "-c",
        "credential.helper=",
        "-c",
        "http.emptyAuth=false",
        *selected,
    ]
