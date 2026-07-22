#!/usr/bin/env python3

from __future__ import annotations

import argparse
import fnmatch
import json
import re
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import unquote
from urllib.request import Request

import markdown_structure
from url_safety import blocked_external_url_reason, safe_urlopen, safe_urlsplit


INLINE_LINK_RE = re.compile(r"!?\[[^\]\n]*\]\(([^)\n]+)\)")
REFERENCE_LINK_RE = re.compile(r"^\s*\[[^\]]+\]:\s*(\S+)")
BARE_URL_RE = re.compile(r"https?://[^\s<>)]+")
HEADER_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
HTML_ANCHOR_RE = re.compile(r"\b(?:id|name)=[\"']([^\"']+)[\"']")
LINE_SUFFIX_RE = re.compile(r":\d+$")
ROOT_IGNORED_DIR_RE = re.compile(r"^/?([A-Za-z0-9_.-]+)/$")
IGNORED_PATH_RE = re.compile(r"^/?([A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*)/$")
DEFAULT_EXCLUDED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
}
DEFAULT_ROOT_EXCLUDED_DIRS = {
    "captures",
    "external_review",
    "local",
    "notes",
    "private",
    "review_artifacts",
    "scratch",
    "session_logs",
    "source_dumps",
    "source_material",
    "tmp",
    "transcripts",
}
DEFAULT_ROOT_EXCLUDED_PATHS: set[tuple[str, ...]] = set()
DEFAULT_EXCLUDED_FILES = {
    "internal_*.md",
    "INTERNAL_*.md",
    "*_STATE*.md",
    "*_Commit.md",
}
NON_FILE_SCHEMES = {"data", "mailto", "tel", "urn"}


def repo_relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def root_ignored_dirs(root: Path) -> set[str]:
    return {parts[0] for parts in root_ignored_path_prefixes(root) if len(parts) == 1}


def root_ignored_path_prefixes(root: Path) -> set[tuple[str, ...]]:
    ignored_paths: set[tuple[str, ...]] = set()
    for ignore_file in (root / ".gitignore", root / ".git" / "info" / "exclude"):
        try:
            lines = ignore_file.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            continue
        for raw_line in lines:
            line = raw_line.strip()
            if not line or line.startswith("#") or line.startswith("!"):
                continue
            if any(marker in line for marker in "*?[]"):
                continue
            path_match = IGNORED_PATH_RE.match(line)
            if path_match:
                ignored_paths.add(tuple(part for part in path_match.group(1).split("/") if part))
                continue
            match = ROOT_IGNORED_DIR_RE.match(line)
            if match:
                ignored_paths.add((match.group(1),))
    return ignored_paths


def has_prefix(parts: tuple[str, ...], prefix: tuple[str, ...]) -> bool:
    return len(parts) >= len(prefix) and parts[: len(prefix)] == prefix


def parse_root_path(value: str) -> tuple[str, ...]:
    if (
        not value
        or Path(value).is_absolute()
        or "\\" in value
        or "://" in value
        or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", value)
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or any(marker in value for marker in "*?[]")
    ):
        raise ValueError("path must stay under --root, use POSIX separators, and contain no glob segments")
    return tuple(value.split("/"))


def included_root_path_error(root: Path, parts: tuple[str, ...]) -> str | None:
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink():
            return "path must not contain symlink components"
    if not current.exists():
        return "path does not exist"
    try:
        current.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, ValueError):
        return "path must resolve inside --root"
    return None


def is_skipped(
    path: Path,
    root: Path,
    excluded_dirs: set[str],
    root_excluded_dirs: set[str],
    root_excluded_paths: set[tuple[str, ...]] | None = None,
    included_root_paths: set[tuple[str, ...]] | None = None,
) -> bool:
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        parts = path.parts
    root_excluded_paths = set() if root_excluded_paths is None else root_excluded_paths
    included_root_paths = set() if included_root_paths is None else included_root_paths
    if any(part in excluded_dirs for part in parts):
        return True
    matching_exclusions = {
        prefix for prefix in root_excluded_paths if has_prefix(parts, prefix)
    }
    if parts and parts[0] in root_excluded_dirs:
        matching_exclusions.add((parts[0],))
    for exclusion in matching_exclusions:
        overridden = any(
            has_prefix(parts, included) and has_prefix(included, exclusion)
            for included in included_root_paths
        )
        if not overridden:
            return True
    return False


def is_excluded_file(path: Path, root: Path, patterns: set[str]) -> bool:
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        parts = path.parts
    return len(parts) == 1 and any(fnmatch.fnmatchcase(path.name, pattern) for pattern in patterns)


def markdown_files(
    root: Path,
    patterns: list[str],
    excluded_dirs: set[str],
    root_excluded_dirs: set[str] | None = None,
    root_excluded_paths: set[tuple[str, ...]] | None = None,
    included_root_paths: set[tuple[str, ...]] | None = None,
) -> list[Path]:
    if root.is_file():
        return [root] if root.suffix == ".md" else []
    root_excluded_dirs = set(DEFAULT_ROOT_EXCLUDED_DIRS) if root_excluded_dirs is None else root_excluded_dirs
    root_excluded_paths = set(DEFAULT_ROOT_EXCLUDED_PATHS) if root_excluded_paths is None else root_excluded_paths
    files: list[Path] = []
    seen: set[Path] = set()
    for pattern in patterns:
        for path in root.glob(pattern):
            if (
                path.is_file()
                and not path.is_symlink()
                and path.suffix == ".md"
                and not is_skipped(
                    path,
                    root,
                    excluded_dirs,
                    root_excluded_dirs,
                    root_excluded_paths,
                    included_root_paths,
                )
                and not is_excluded_file(path, root, DEFAULT_EXCLUDED_FILES)
            ):
                resolved = path.resolve()
                if resolved not in seen:
                    seen.add(resolved)
                    files.append(path)
    return sorted(files)


def normalize_target(raw: str) -> str:
    target = raw.strip()
    if target.startswith("<"):
        end = target.find(">")
        if end != -1:
            return target[1:end].strip()
    return target.split()[0].strip()


def links_in_file(path: Path) -> list[tuple[int, str]]:
    links: list[tuple[int, str]] = []
    text = path.read_text(encoding="utf-8")
    for line_number, line in markdown_structure.operative_lines(text):
        target_spans: list[tuple[int, int]] = []
        for match in INLINE_LINK_RE.finditer(line):
            target = normalize_target(match.group(1))
            if not target.startswith("["):
                target_spans.append(match.span(1))
                links.append((line_number, target))
        reference_match = REFERENCE_LINK_RE.match(line)
        if reference_match:
            target = normalize_target(reference_match.group(1))
            if not target.startswith("["):
                links.append((line_number, target))
        for match in BARE_URL_RE.finditer(line):
            if any(start <= match.start() < end for start, end in target_spans):
                continue
            links.append((line_number, match.group(0).rstrip("`.,;:")))
    return links


def slugify_header(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("`", "")
    text = text.strip().casefold()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")


def anchors_for(path: Path) -> set[str]:
    anchors: set[str] = set()
    counts: dict[str, int] = {}
    text = path.read_text(encoding="utf-8")
    for _line_number, line in markdown_structure.operative_lines(text):
        header_match = HEADER_RE.match(line.strip())
        if header_match:
            base = slugify_header(header_match.group(2))
            count = counts.get(base, 0)
            anchors.add(base if count == 0 else f"{base}-{count}")
            counts[base] = count + 1
        for anchor in HTML_ANCHOR_RE.findall(line):
            anchors.add(anchor)
            anchors.add(unquote(anchor))
    return anchors


def strip_line_suffix(path_text: str) -> str:
    return LINE_SUFFIX_RE.sub("", path_text)


def resolve_local_target(root: Path, source: Path, target_path: str) -> Path:
    decoded = unquote(target_path)
    if decoded.startswith("/"):
        candidate = root / decoded.lstrip("/")
    else:
        candidate = source.parent / decoded
    if candidate.exists():
        return candidate
    stripped = strip_line_suffix(decoded)
    if stripped != decoded:
        if stripped.startswith("/"):
            candidate = root / stripped.lstrip("/")
        else:
            candidate = source.parent / stripped
    return candidate


def add_issue(
    issues: list[dict[str, object]],
    root: Path,
    source: Path,
    line_number: int,
    target: str,
    message: str,
) -> None:
    issues.append(
        {
            "file": repo_relative(source, root),
            "line": line_number,
            "target": target,
            "message": message,
        }
    )


def check_external_url(url: str, timeout: float) -> str | None:
    blocked = blocked_external_url_reason(url)
    if blocked:
        return blocked
    header_variants = (
        {"User-Agent": "master-prompt-agreement-link-check/1.0"},
        {},
    )
    last_error = "external URL check failed"
    for method in ("HEAD", "GET"):
        for headers in header_variants:
            request = Request(url, method=method, headers=headers)
            try:
                with safe_urlopen(request, timeout=timeout) as response:
                    if response.status >= 400:
                        last_error = f"HTTP {response.status}"
                        continue
                    return None
            except ValueError as exc:
                return str(exc)
            except HTTPError as exc:
                last_error = f"HTTP {exc.code}"
                if exc.code in {405, 501} and method == "HEAD":
                    break
                continue
            except URLError as exc:
                last_error = str(exc.reason)
                continue
            except TimeoutError:
                return f"timed out after {timeout:g}s"
    return last_error


def check_links(
    root: Path,
    files: list[Path],
    check_external: bool,
    check_anchors: bool,
    timeout: float,
) -> dict[str, object]:
    errors: list[dict[str, object]] = []
    warnings: list[dict[str, object]] = []
    anchor_cache: dict[Path, set[str]] = {}
    local_links = 0
    external_links = 0
    skipped_external = 0

    for source in files:
        if source.is_symlink():
            add_issue(errors, root, source, 0, repo_relative(source, root), "refusing to read symlinked Markdown source")
            continue
        for line_number, target in links_in_file(source):
            if not target:
                add_issue(errors, root, source, line_number, target, "empty link target")
                continue
            parsed, parse_error = safe_urlsplit(target)
            if parse_error:
                add_issue(errors, root, source, line_number, target, parse_error)
                continue
            if parsed is None:
                add_issue(
                    errors,
                    root,
                    source,
                    line_number,
                    target,
                    "URL parser returned no result",
                )
                continue
            scheme = parsed.scheme.casefold()
            if scheme in {"http", "https"}:
                external_links += 1
                if check_external:
                    error = check_external_url(target, timeout)
                    if error:
                        add_issue(errors, root, source, line_number, target, error)
                else:
                    skipped_external += 1
                continue
            if scheme and scheme not in NON_FILE_SCHEMES:
                add_issue(errors, root, source, line_number, target, f"unsupported link scheme: {scheme}")
                continue
            if scheme in NON_FILE_SCHEMES:
                continue

            local_links += 1
            target_file = resolve_local_target(root, source, parsed.path or source.as_posix())
            resolved = target_file.resolve(strict=False)
            if not resolved.is_relative_to(root.resolve()):
                add_issue(errors, root, source, line_number, target, "local link escapes the checked root")
                continue
            if not target_file.exists():
                add_issue(
                    errors,
                    root,
                    source,
                    line_number,
                    target,
                    f"local target does not exist: {repo_relative(target_file, root)}",
                )
                continue
            if parsed.fragment and check_anchors:
                if target_file.is_dir():
                    add_issue(errors, root, source, line_number, target, "anchor target is a directory")
                    continue
                anchors = anchor_cache.setdefault(target_file, anchors_for(target_file))
                fragment = unquote(parsed.fragment).strip()
                candidates = {fragment, fragment.casefold(), slugify_header(fragment)}
                if not anchors.intersection(candidates):
                    add_issue(errors, root, source, line_number, target, f"anchor not found: {fragment}")

    return {
        "checked_files": [repo_relative(path, root) for path in files],
        "local_links": local_links,
        "external_links": external_links,
        "skipped_external": skipped_external,
        "warnings": warnings,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check Markdown links in a repository or directory.",
        allow_abbrev=False,
    )
    parser.add_argument("--root", default=".", help="Root directory or Markdown file to scan.")
    parser.add_argument(
        "--include",
        action="append",
        default=None,
        help="Glob pattern to include. Repeatable. Defaults to **/*.md.",
    )
    parser.add_argument(
        "--exclude-dir",
        action="append",
        default=None,
        help="Directory name to exclude. Repeatable. Defaults cover common build and cache dirs.",
    )
    parser.add_argument(
        "--include-root-path",
        action="append",
        default=None,
        help="Explicitly include a normally excluded root-relative path. Repeatable; does not change external-link policy.",
    )
    parser.add_argument("--external", action="store_true", help="Also check HTTP(S) links over the network.")
    parser.add_argument("--no-anchors", action="store_true", help="Skip local Markdown anchor validation.")
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="Total network deadline for each external request attempt.",
    )
    args = parser.parse_args()

    raw_root = Path(args.root).expanduser()
    if raw_root.is_symlink():
        parser.error("--root must not be a symlink")
    try:
        requested_root = raw_root.resolve(strict=True)
    except OSError as exc:
        parser.error(f"--root cannot be resolved: {exc}")
    if not requested_root.is_file() and not requested_root.is_dir():
        parser.error("--root must be a Markdown file or directory")
    if requested_root.is_file() and requested_root.suffix != ".md":
        parser.error("a file --root must be a Markdown file")
    root = requested_root.parent if requested_root.is_file() else requested_root
    patterns = args.include or ["**/*.md"]
    for pattern in patterns:
        pattern_path = Path(pattern)
        if (
            pattern_path.is_absolute()
            or "\\" in pattern
            or "://" in pattern
            or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", pattern)
            or any(part in {"", ".", ".."} for part in pattern.split("/"))
        ):
            parser.error(f"--include must stay under --root and use POSIX separators: {pattern}")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    included_root_paths: set[tuple[str, ...]] = set()
    for value in args.include_root_path or []:
        try:
            parsed_path = parse_root_path(value)
        except ValueError as exc:
            parser.error(f"--include-root-path {value!r}: {exc}")
        path_error = included_root_path_error(root, parsed_path)
        if path_error:
            parser.error(f"--include-root-path {value!r}: {path_error}")
        included_root_paths.add(parsed_path)
    excluded_dirs = set(DEFAULT_EXCLUDED_DIRS)
    root_excluded_dirs = set(DEFAULT_ROOT_EXCLUDED_DIRS) | root_ignored_dirs(root)
    root_excluded_paths = set(DEFAULT_ROOT_EXCLUDED_PATHS) | root_ignored_path_prefixes(root)
    if args.exclude_dir:
        excluded_dirs.update(args.exclude_dir)
    files = (
        [requested_root]
        if requested_root.is_file()
        else markdown_files(
            root,
            patterns,
            excluded_dirs,
            root_excluded_dirs,
            root_excluded_paths,
            included_root_paths,
        )
    )
    report = check_links(root, files, args.external, not args.no_anchors, args.timeout)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
