#!/usr/bin/env python3

from __future__ import annotations

import argparse
import base64
import binascii
from datetime import date
from datetime import datetime
from datetime import timezone
import hashlib
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import urllib.parse
import urllib.request
from urllib.error import HTTPError, URLError

import safe_paths
from url_safety import blocked_external_url_reason, safe_urlopen

GITHUB_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
GIT_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
PROMPT_BOUNDARY_RE = re.compile(r"</?(?:system|developer|user|assistant|tool)\b", re.IGNORECASE)
MAX_SNAPSHOT_BYTES = 2_000_000


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Capture an external or local reference into a reproducible markdown snapshot.",
        allow_abbrev=False,
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--source-file", help="Local file to snapshot.")
    source.add_argument("--url", help="HTTP(S) URL to snapshot.")
    source.add_argument("--github-repo", help="GitHub repo in owner/repo form.")
    parser.add_argument("--github-path", help="Path inside the GitHub repo.")
    parser.add_argument("--ref", help="Immutable commit SHA for GitHub snapshots.")
    parser.add_argument("--retrieved-date", help="ISO date to record. Defaults to today or SOURCE_DATE_EPOCH.")
    parser.add_argument("--title", help="Override snapshot title.")
    parser.add_argument("--source-label", help="Source-safe label for local --source-file snapshots outside the working tree.")
    parser.add_argument("--output", required=True, help="Output markdown file.")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing output file.")
    return parser


def retrieved_date(value: str | None) -> str:
    if value:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is None:
            raise SystemExit("--retrieved-date must be YYYY-MM-DD")
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError as exc:
            raise SystemExit(f"--retrieved-date must be YYYY-MM-DD: {exc}") from exc
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch:
        try:
            return datetime.fromtimestamp(int(epoch), timezone.utc).date().isoformat()
        except (ValueError, OverflowError, OSError) as exc:
            raise SystemExit("SOURCE_DATE_EPOCH must be a supported integer Unix timestamp") from exc
    return date.today().isoformat()


def fetch_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise SystemExit("--url must use https")
    blocked = blocked_external_url_reason(url)
    if blocked:
        raise SystemExit(f"url fetch blocked: {blocked}")
    request = urllib.request.Request(url, headers={"User-Agent": "master-prompt-agreement"})
    try:
        with safe_urlopen(request, timeout=30) as response:
            payload = response.read(MAX_SNAPSHOT_BYTES + 1)
    except ValueError as exc:
        raise SystemExit(f"url fetch blocked: {exc}") from exc
    except HTTPError as exc:
        raise SystemExit(f"url fetch failed with HTTP {exc.code}: {url}") from exc
    except URLError as exc:
        raise SystemExit(f"url fetch failed: {exc.reason}") from exc
    if len(payload) > MAX_SNAPSHOT_BYTES:
        raise SystemExit(f"url fetch exceeded {MAX_SNAPSHOT_BYTES} byte snapshot limit")
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SystemExit(f"url response is not UTF-8 text: {exc}") from exc


def fetch_github(repo: str, path: str, ref: str) -> str:
    if not GITHUB_REPO_RE.match(repo) or any(part in {".", ".."} for part in repo.split("/")):
        raise SystemExit("--github-repo must be in owner/repo form")
    path_parts = PurePosixPath(path).parts
    if (
        not path.strip()
        or path.startswith("/")
        or "\\" in path
        or any(part in {"", ".", ".."} for part in path.split("/"))
        or ".." in path_parts
    ):
        raise SystemExit("--github-path must be a relative repository path")
    if not ref or not GIT_SHA_RE.match(ref):
        raise SystemExit("--ref must be an immutable 40-character commit SHA for GitHub snapshots")
    encoded_path = "/".join(urllib.parse.quote(part, safe="") for part in path_parts)
    encoded_ref = urllib.parse.quote(ref, safe="")
    api_url = f"https://api.github.com/repos/{repo}/contents/{encoded_path}?ref={encoded_ref}"
    request = urllib.request.Request(
        api_url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "master-prompt-agreement",
        },
    )
    try:
        with safe_urlopen(request, timeout=30) as response:
            content_type = response.headers.get("content-type", "")
            if "json" not in content_type.casefold():
                raise SystemExit("github API response must use a JSON content type")
            raw_payload = response.read((MAX_SNAPSHOT_BYTES * 2) + 1)
    except ValueError as exc:
        raise SystemExit(f"github fetch blocked: {exc}") from exc
    except HTTPError as exc:
        raise SystemExit(f"github fetch failed with HTTP {exc.code}: {api_url}") from exc
    except URLError as exc:
        raise SystemExit(f"github fetch failed: {exc.reason}") from exc
    if len(raw_payload) > MAX_SNAPSHOT_BYTES * 2:
        raise SystemExit(f"github API response exceeded {MAX_SNAPSHOT_BYTES * 2} byte snapshot limit")
    try:
        payload = safe_paths.loads_json_no_duplicates(raw_payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise SystemExit(f"github API response is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(payload, dict) or "content" not in payload:
        raise SystemExit("--github-path must point to a file, not a directory or unsupported object")
    encoded_content = payload.get("content")
    if not isinstance(encoded_content, str):
        raise SystemExit("github API file content must be a base64 string")
    try:
        content = base64.b64decode("".join(encoded_content.split()), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SystemExit(f"github API file content is not valid base64: {exc}") from exc
    if len(content) > MAX_SNAPSHOT_BYTES:
        raise SystemExit(f"github snapshot exceeded {MAX_SNAPSHOT_BYTES} byte snapshot limit")
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SystemExit(f"github file is not UTF-8 text: {exc}") from exc


def markdown_fence(content: str) -> str:
    longest = max((len(match.group(0)) for match in re.finditer(r"`+", content)), default=0)
    return "`" * max(3, longest + 1)


def render_snapshot(title: str, source: str, content: str, retrieved: str) -> str:
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    fence = markdown_fence(content)
    return "\n".join(
        [
            f"# {title}",
            "",
            f"Source: {source}",
            f"Retrieved: {retrieved}",
            f"Reviewed: {retrieved}",
            f"Content SHA256: {digest}",
            "",
            "## Summary Stub",
            "",
            "- Fill in the evidence-backed summary here.",
            "",
            "## Snapshot",
            "",
            f"{fence}text",
            content.rstrip(),
            fence,
            "",
        ]
    )


def validate_plain_label(label_name: str, label: str, *, allow_url: bool = False, allow_absolute_path: bool = False) -> str:
    value = label.strip()
    if not value:
        raise SystemExit(f"{label_name} must not be empty")
    if any(char in value for char in "\r\n\x00<>`"):
        raise SystemExit(f"{label_name} must be plain single-line text")
    if PROMPT_BOUNDARY_RE.search(value):
        raise SystemExit(f"{label_name} must not contain prompt-boundary markup")
    if not allow_absolute_path and (value.startswith("/") or re.match(r"^[A-Za-z]:[\\/]", value)):
        raise SystemExit(f"{label_name} must not be an absolute path")
    if not allow_url and "://" in value:
        raise SystemExit(f"{label_name} must not be a URL")
    return value


def main() -> int:
    args = build_parser().parse_args()
    if args.github_repo and not args.github_path:
        raise SystemExit("--github-path is required with --github-repo")
    if args.github_repo and not args.ref:
        raise SystemExit("--ref is required with --github-repo and must be an immutable commit SHA")

    if args.source_file:
        raw_source = Path(args.source_file).expanduser()
        if raw_source.is_symlink():
            raise SystemExit("--source-file must not be a symlink")
        source = Path(os.path.abspath(os.fspath(raw_source)))
        try:
            raw_content = safe_paths.read_regular_file_bytes(
                source,
                description="local reference snapshot source",
                max_bytes=MAX_SNAPSHOT_BYTES,
                require_single_link=True,
            )
        except (OSError, ValueError) as exc:
            raise SystemExit(f"--source-file cannot be read safely: {exc}") from exc
        try:
            content = raw_content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SystemExit(f"--source-file must be readable UTF-8 text: {exc}") from exc
        if args.source_label:
            source_label = validate_plain_label("--source-label", args.source_label)
        else:
            try:
                working_root = Path(os.path.abspath(os.fspath(Path.cwd())))
                source_label = str(source.relative_to(working_root))
            except ValueError as exc:
                raise SystemExit("--source-label is required when --source-file is outside the working tree") from exc
        default_title = source.name
    elif args.url:
        content = fetch_url(args.url)
        source_label = validate_plain_label("URL source label", args.url, allow_url=True)
        default_title = Path(urllib.parse.urlparse(args.url).path).name or "snapshot"
    else:
        content = fetch_github(args.github_repo, args.github_path, args.ref)
        source_label = validate_plain_label(
            "GitHub source label",
            f"https://github.com/{args.github_repo}/blob/{args.ref}/{args.github_path}",
            allow_url=True,
        )
        default_title = Path(args.github_path).name

    output = Path(args.output)
    title = validate_plain_label("--title" if args.title else "default title", args.title or default_title)
    try:
        safe_paths.write_text(
            output,
            render_snapshot(title, source_label, content, retrieved_date(args.retrieved_date)),
            force=args.force,
        )
    except (FileExistsError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps({"output": str(output.resolve()), "source": source_label}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
