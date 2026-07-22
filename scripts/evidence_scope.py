#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
from pathlib import Path

import bounded_subprocess
import git_query
import recommend_stack
import safe_paths


SHARED_SURFACE_TERMS = (
    "auth",
    "cache",
    "user",
    "config",
    "core",
    "default",
    "flag",
    "helper",
    "middleware",
    "policy",
    "router",
    "schema",
    "setting",
    "shared",
    "util",
)
TOKEN_RE = re.compile(r"[a-z0-9]+")
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
SCOPE_ORDER = (
    "patch",
    "touched-files",
    "commit-series",
    "feature-slice",
    "trust-boundary",
    "repo-slice",
)
GIT_COMMAND_TIMEOUT_SECONDS = 10.0
GIT_COMMAND_MAX_OUTPUT_BYTES = 4 * 1024 * 1024
GIT_TERMINATION_GRACE_SECONDS = 0.1


def validate_diff_base(value: str) -> None:
    if not value.strip():
        raise SystemExit("--diff-base must be non-empty")
    if value.startswith("-") or CONTROL_RE.search(value):
        raise SystemExit("--diff-base must be a revision, not an option or control string")


def validate_root(value: Path) -> Path:
    try:
        root = value.resolve(strict=True)
    except OSError as exc:
        raise SystemExit(f"--root cannot be resolved: {value}: {exc}") from exc
    if not root.is_dir():
        raise SystemExit(f"--root must be a directory: {value}")
    return root


def validate_paths(paths: list[str], root: Path) -> list[str]:
    validated: list[str] = []
    for value in paths:
        try:
            validated.append(
                safe_paths.normalize_repo_relative_path(
                    value,
                    root,
                    description="evidence path",
                )
            )
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
    return validated


def _bounded_git(args: list[str], root: Path) -> tuple[int, bytes, bytes]:
    if os.name != "posix":
        raise SystemExit("Git path collection requires POSIX process-group pipes")
    try:
        result = bounded_subprocess.run_bounded_process(
            git_query.closed_git_query_command(args),
            cwd=root,
            env=git_query.closed_git_query_environment(root),
            timeout_seconds=GIT_COMMAND_TIMEOUT_SECONDS,
            max_output_bytes=GIT_COMMAND_MAX_OUTPUT_BYTES,
            maximum_timeout_seconds=GIT_COMMAND_TIMEOUT_SECONDS,
            maximum_output_bytes=GIT_COMMAND_MAX_OUTPUT_BYTES,
            termination_grace_seconds=GIT_TERMINATION_GRACE_SECONDS,
        )
    except bounded_subprocess.BoundedSubprocessStartError as exc:
        detail = exc.__cause__ if isinstance(exc.__cause__, OSError) else exc
        raise SystemExit(f"git {' '.join(args)} could not start: {detail}") from exc
    except bounded_subprocess.BoundedSubprocessError as exc:
        raise SystemExit(f"Git path collection failed: {exc}") from exc
    if result.timed_out:
        raise SystemExit(
            f"git {' '.join(args)} timed out after {GIT_COMMAND_TIMEOUT_SECONDS:g}s"
        )
    if result.output_exceeded:
        raise SystemExit(
            "Git path collection output exceeded the "
            f"{GIT_COMMAND_MAX_OUTPUT_BYTES}-byte limit"
        )
    return result.returncode, result.stdout, result.stderr


def run_git(args: list[str], root: Path) -> list[str]:
    returncode, stdout, stderr = _bounded_git(args, root)
    if returncode != 0:
        detail = stderr.decode("utf-8", errors="replace").strip()
        raise SystemExit(detail or f"git {' '.join(args)} failed")
    if stdout and not stdout.endswith(b"\0"):
        raise SystemExit("Git path collection did not return a terminal NUL delimiter")
    raw_paths = stdout[:-1].split(b"\0") if stdout else []
    if any(not value for value in raw_paths):
        raise SystemExit("Git path collection returned an empty NUL-delimited path")
    try:
        return [value.decode("utf-8") for value in raw_paths]
    except UnicodeDecodeError as exc:
        raise SystemExit(f"Git path collection returned a non-UTF-8 path: {exc}") from exc


def collect_paths(args: argparse.Namespace, root: Path) -> list[str]:
    if args.path:
        return sorted(dict.fromkeys(validate_paths(args.path, root)))
    if args.diff_base:
        validate_diff_base(args.diff_base)
        tracked = run_git(
            [
                "diff",
                "--no-ext-diff",
                "--no-textconv",
                "--name-only",
                "-z",
                args.diff_base,
                "--",
            ],
            root,
        )
        untracked = run_git(["ls-files", "--others", "--exclude-standard", "-z", "--"], root)
        return sorted(dict.fromkeys(validate_paths([*tracked, *untracked], root)))
    raise SystemExit("pass --path or --diff-base")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Recommend the smallest sufficient evidence scope for a task.",
        allow_abbrev=False,
    )
    for flag, help_text in recommend_stack.CLI_FLAGS:
        parser.add_argument(f"--{flag}", action="store_true", help=help_text)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--path", action="append", default=[], help="Repo-relative relevant file path.")
    source.add_argument(
        "--diff-base",
        help="Git revision to diff against when collecting changed files automatically.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Repository root for path validation and Git inspection. Defaults to the invocation working directory.",
    )
    return parser


def classify_path(path: str) -> dict[str, object]:
    lower = path.lower()
    tokens = set(TOKEN_RE.findall(lower))
    shared_terms = [term for term in SHARED_SURFACE_TERMS if term in tokens]
    stem = Path(path).stem
    return {
        "path": path,
        "consumer_query": f"rg -n -F -- {shlex.quote(stem)} .",
        "shared_surface_terms": shared_terms,
    }


def escalate_scope(
    base_scope: str,
    path_summaries: list[dict[str, object]],
    *,
    impact_review: bool = False,
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if impact_review and SCOPE_ORDER.index(base_scope) < SCOPE_ORDER.index("feature-slice"):
        reasons.append("Impact review requires following the changed invariant through its feature slice.")
        base_scope = "feature-slice"
    if any(summary["shared_surface_terms"] for summary in path_summaries):
        reasons.append("Shared-surface file names suggest unchanged consumers may depend on the old behavior.")
        if base_scope == "patch":
            base_scope = "touched-files"
        elif base_scope == "touched-files":
            base_scope = "feature-slice"
    return base_scope, reasons


def main() -> int:
    args = build_parser().parse_args()
    root = validate_root(args.root)
    paths = collect_paths(args, root)
    standard_of_care = recommend_stack.choose_standard_of_care(args)
    base_scope = recommend_stack.choose_evidentiary_scope(args, standard_of_care)
    path_summaries = [classify_path(path) for path in paths]
    recommended_scope, escalation_reasons = escalate_scope(
        base_scope,
        path_summaries,
        impact_review=args.impact_review,
    )

    result = {
        "evidence_files": paths,
        "path_collection": {
            "source": "explicit_paths" if args.path else "git_diff",
            "untracked_files_included": bool(args.diff_base),
        },
        "path_summaries": path_summaries,
        "recommended_scope": recommended_scope,
        "scope_reasons": escalation_reasons,
        "standard_of_care": standard_of_care,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
