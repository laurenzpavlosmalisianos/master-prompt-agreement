#!/usr/bin/env python3

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import json
from pathlib import Path
import re
import socket
import sys
import unicodedata
from urllib import robotparser
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urlunparse
from urllib.request import Request

import source_chain_artifact_lint
import markdown_structure
import source_registry_files
from url_safety import blocked_external_url_reason, safe_redirect_target, safe_urlopen


REPO_ROOT = Path(__file__).resolve().parent.parent
PROJECT_SOURCE_REGISTRY_FILES = (Path("SOURCE_PACKS.md"), Path("SOURCE_UPDATE.md"))
URL_RE = re.compile(r"https?://\S+")
MONITOR_ROOT_LINE_RE = re.compile(r"^\s*Monitor root:\s*(https?://\S+)", re.IGNORECASE)
TRAILING_URL_PUNCTUATION = "`).,;:]>\"'"
DEFAULT_USER_AGENT = "master-prompt-agreement-source-registry-audit/1.0"
DEFAULT_ACCEPT = "text/html,application/xml,text/xml,application/json,text/plain,application/pdf,*/*;q=0.5"
REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
MAX_WORKERS = 64
MAX_READ_BYTES = 1_000_000
MAX_TIMEOUT_SECONDS = 300.0


@dataclass(frozen=True)
class UrlRef:
    path: str
    line: int
    monitor_root: bool


@dataclass(frozen=True)
class FetchResult:
    ok: bool
    status: int | None
    final_url: str
    content_type: str
    error: str

    def as_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "status": self.status,
            "final_url": self.final_url,
            "content_type": self.content_type,
            "error": self.error,
        }


@dataclass(frozen=True)
class AuditRow:
    url: str
    refs: tuple[UrlRef, ...]
    head: FetchResult
    get: FetchResult | None
    robots: str

    @property
    def ok(self) -> bool:
        return self.head.ok or (self.get is not None and self.get.ok)

    @property
    def monitor_root(self) -> bool:
        return any(ref.monitor_root for ref in self.refs)

    def as_dict(self) -> dict[str, object]:
        return {
            "url": self.url,
            "ok": self.ok,
            "monitor_root": self.monitor_root,
            "refs": [ref.__dict__ for ref in self.refs],
            "head": self.head.as_dict(),
            "get": None if self.get is None else self.get.as_dict(),
            "robots": self.robots,
        }


def bounded_positive_int(value: str, *, label: str, maximum: int) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{label} must be an integer") from exc
    if not 1 <= parsed <= maximum:
        raise argparse.ArgumentTypeError(f"{label} must be between 1 and {maximum}")
    return parsed


def bounded_positive_float(value: str, *, label: str, maximum: float) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{label} must be numeric") from exc
    if not 0 < parsed <= maximum:
        raise argparse.ArgumentTypeError(f"{label} must be greater than 0 and at most {maximum:g}")
    return parsed


def safe_user_agent(value: str) -> str:
    if not value.strip() or len(value) > 200 or CONTROL_RE.search(value):
        raise argparse.ArgumentTypeError("--user-agent must be 1-200 characters without controls")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a bounded live access audit over source registry URLs.",
        allow_abbrev=False,
    )
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help="Repository root.")
    parser.add_argument(
        "--reference-dir",
        action="append",
        type=Path,
        help=(
            "Reference directory relative to the root. Repeatable; when omitted, "
            "only root project source-registry files are considered."
        ),
    )
    parser.add_argument("--monitor-roots-only", action="store_true", help="Audit only explicit Monitor root lines.")
    parser.add_argument("--check-robots", action="store_true", help="Check robots.txt permission for monitor roots.")
    parser.add_argument(
        "--timeout",
        type=lambda value: bounded_positive_float(
            value,
            label="--timeout",
            maximum=MAX_TIMEOUT_SECONDS,
        ),
        default=10.0,
        help=(
            "Total network deadline per request attempt in seconds "
            f"(greater than 0, at most {MAX_TIMEOUT_SECONDS:g})."
        ),
    )
    parser.add_argument(
        "--workers",
        type=lambda value: bounded_positive_int(value, label="--workers", maximum=MAX_WORKERS),
        default=8,
        help=(
            f"Worker queue size (1-{MAX_WORKERS}); guarded network opens serialize while the "
            "process-wide DNS safety boundary is active."
        ),
    )
    parser.add_argument(
        "--max-read-bytes",
        type=lambda value: bounded_positive_int(
            value,
            label="--max-read-bytes",
            maximum=MAX_READ_BYTES,
        ),
        default=4096,
        help=f"Bounded GET read size in bytes (1-{MAX_READ_BYTES}).",
    )
    parser.add_argument("--user-agent", type=safe_user_agent, default=DEFAULT_USER_AGENT, help="HTTP User-Agent.")
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Audit report format (default: text).",
    )
    return parser


def clean_url(value: str) -> str:
    return value.rstrip(TRAILING_URL_PUNCTUATION)


def terminal_safe_text(value: str) -> str:
    """Render untrusted text without terminal controls or line injection."""

    encoded: list[str] = []
    for character in value:
        codepoint = ord(character)
        category = unicodedata.category(character)
        if category not in {"Cc", "Cf", "Cs", "Zl", "Zp"}:
            encoded.append(character)
        elif codepoint <= 0xFF:
            encoded.append(f"\\x{codepoint:02x}")
        elif codepoint <= 0xFFFF:
            encoded.append(f"\\u{codepoint:04x}")
        else:
            encoded.append(f"\\U{codepoint:08x}")
    return "".join(encoded)


def non_fenced_lines(text: str) -> list[tuple[int, str]]:
    return list(markdown_structure.operative_lines(text))


def reference_files(root: Path, reference_dirs: Path | tuple[Path, ...] | list[Path]) -> list[Path]:
    return [
        snapshot.path
        for snapshot in registry_snapshots(root, reference_dirs)
    ]


def registry_snapshots(
    root: Path,
    reference_dirs: Path | tuple[Path, ...] | list[Path],
) -> tuple[source_registry_files.MarkdownSnapshot, ...]:
    return source_registry_files.registry_markdown_snapshots(
        root,
        reference_dirs,
        project_files=PROJECT_SOURCE_REGISTRY_FILES,
    )


def collect_urls(
    root: Path,
    reference_dir: Path | tuple[Path, ...] | list[Path],
    monitor_roots_only: bool,
    *,
    snapshots: tuple[source_registry_files.MarkdownSnapshot, ...] | None = None,
) -> dict[str, list[UrlRef]]:
    urls: dict[str, list[UrlRef]] = {}
    selected_snapshots = (
        registry_snapshots(root, reference_dir)
        if snapshots is None
        else snapshots
    )
    for snapshot in selected_snapshots:
        path = snapshot.path
        rel = path.relative_to(root).as_posix()
        text = snapshot.text
        for line_no, line in non_fenced_lines(text):
            monitor_match = MONITOR_ROOT_LINE_RE.match(line)
            if monitor_match:
                url = clean_url(monitor_match.group(1))
                urls.setdefault(url, []).append(UrlRef(rel, line_no, True))
                continue
            if monitor_roots_only:
                continue
            for match in URL_RE.finditer(line):
                url = clean_url(match.group(0))
                urls.setdefault(url, []).append(UrlRef(rel, line_no, False))
        if path.name == "SOURCE_UPDATE.md":
            for line_no, url in source_chain_artifact_lint.recurring_source_url_refs_from_text(text):
                urls.setdefault(clean_url(url), []).append(UrlRef(rel, line_no, True))
    return urls


def request_with_redirects(
    url: str,
    method: str,
    timeout: float,
    max_read_bytes: int,
    user_agent: str,
    max_redirects: int = 5,
) -> FetchResult:
    blocked = blocked_external_url_reason(url, resolve_hostname=False)
    if blocked:
        return FetchResult(False, None, url, "", blocked)
    current_url = url
    for _ in range(max_redirects + 1):
        request = Request(
            current_url,
            method=method,
            headers={"User-Agent": user_agent, "Accept": DEFAULT_ACCEPT},
        )
        try:
            with safe_urlopen(request, timeout=timeout, max_redirects=max_redirects) as response:
                if method == "GET":
                    response.read(max_read_bytes)
                return FetchResult(
                    True,
                    getattr(response, "status", None),
                    response.geturl(),
                    response.headers.get("content-type", "")[:80],
                    "",
                )
        except HTTPError as exc:
            try:
                location = exc.headers.get("Location") if exc.headers else None
                if exc.code in REDIRECT_STATUS_CODES and location:
                    candidate, blocked_redirect = safe_redirect_target(current_url, location)
                    return FetchResult(
                        False,
                        exc.code,
                        current_url if candidate is None else candidate,
                        exc.headers.get("content-type", "")[:80] if exc.headers else "",
                        (
                            f"redirect limit exceeded; redirect target rejected: {blocked_redirect}"
                            if blocked_redirect
                            else "redirect limit exceeded"
                        ),
                    )
                return FetchResult(
                    False,
                    exc.code,
                    exc.geturl(),
                    exc.headers.get("content-type", "")[:80] if exc.headers else "",
                    "HTTPError",
                )
            finally:
                exc.close()
        except (URLError, TimeoutError, socket.timeout) as exc:
            return FetchResult(False, None, current_url, "", f"{type(exc).__name__}: {str(exc)[:160]}")
        except Exception as exc:
            return FetchResult(False, None, current_url, "", f"{type(exc).__name__}: {str(exc)[:160]}")
    return FetchResult(False, None, current_url, "", "redirect limit exceeded")


def robots_url_for(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse((parsed.scheme, parsed.netloc, "/robots.txt", "", "", ""))


def robots_status(url: str, timeout: float, user_agent: str) -> str:
    robots_url = robots_url_for(url)
    content_type = ""
    body = ""
    try:
        request = Request(robots_url, headers={"User-Agent": user_agent})
        with safe_urlopen(request, timeout=timeout) as response:
            content_type = response.headers.get("content-type", "")
            body = response.read(20000).decode("utf-8", "replace")
    except HTTPError as exc:
        exc.close()
        return "unknown"
    except Exception:
        return "unknown"
    if "text/plain" not in content_type and "user-agent" not in body.casefold():
        return "unknown"
    parser = robotparser.RobotFileParser()
    parser.parse(body.splitlines())
    return "allow" if parser.can_fetch(user_agent, url) else "disallow"


def audit_url(
    url: str,
    refs: list[UrlRef],
    timeout: float,
    max_read_bytes: int,
    user_agent: str,
    check_robots: bool,
) -> AuditRow:
    blocked = blocked_external_url_reason(url, resolve_hostname=False)
    if blocked:
        rejected = FetchResult(False, None, url, "", blocked)
        return AuditRow(url, tuple(refs), rejected, None, "not_checked")
    head = request_with_redirects(url, "HEAD", timeout, max_read_bytes, user_agent)
    get: FetchResult | None = None
    if not head.ok or (head.status is not None and head.status >= 400):
        get = request_with_redirects(url, "GET", timeout, max_read_bytes, user_agent)
    robots = "not_checked"
    if check_robots and any(ref.monitor_root for ref in refs):
        robots = robots_status(url, timeout, user_agent)
    return AuditRow(url, tuple(refs), head, get, robots)


def run_audit(
    args: argparse.Namespace,
    *,
    snapshots: tuple[source_registry_files.MarkdownSnapshot, ...] | None = None,
) -> list[AuditRow]:
    root = args.root.resolve()
    reference_dirs = tuple(args.reference_dir or ())
    urls = collect_urls(
        root,
        reference_dirs,
        args.monitor_roots_only,
        snapshots=snapshots,
    )
    workers = args.workers
    rows: list[AuditRow] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(
                audit_url,
                url,
                refs,
                args.timeout,
                args.max_read_bytes,
                args.user_agent,
                args.check_robots,
            )
            for url, refs in sorted(urls.items())
        ]
        for future in as_completed(futures):
            rows.append(future.result())
    return sorted(rows, key=lambda row: row.url)


def print_text(
    rows: list[AuditRow],
    source_file_count: int,
    input_errors: tuple[str, ...] = (),
) -> None:
    failures = [row for row in rows if not row.ok]
    get_fallbacks = [row for row in rows if row.get is not None and row.ok]
    robot_disallowed = [row for row in rows if row.monitor_root and row.robots == "disallow"]
    print(f"source_registry_files: {source_file_count}")
    print(f"unique_urls: {len(rows)}")
    print(f"failures: {len(failures)}")
    print(f"get_fallback_successes: {len(get_fallbacks)}")
    print(f"monitor_robots_disallowed: {len(robot_disallowed)}")
    for error in input_errors:
        print(f"input_error: {terminal_safe_text(error)}")
    for row in failures + robot_disallowed:
        print("---")
        print(terminal_safe_text(row.url))
        print(
            "refs: "
            + ", ".join(
                f"{terminal_safe_text(ref.path)}:{ref.line}" for ref in row.refs[:4]
            )
        )
        print(
            "HEAD ok={ok} status={status} final={final} error={error} content_type={ctype}".format(
                ok=row.head.ok,
                status=row.head.status,
                final=terminal_safe_text(row.head.final_url),
                error=terminal_safe_text(row.head.error),
                ctype=terminal_safe_text(row.head.content_type),
            )
        )
        if row.get is not None:
            print(
                "GET ok={ok} status={status} final={final} error={error} content_type={ctype}".format(
                    ok=row.get.ok,
                    status=row.get.status,
                    final=terminal_safe_text(row.get.final_url),
                    error=terminal_safe_text(row.get.error),
                    ctype=terminal_safe_text(row.get.content_type),
                )
            )
        if row.monitor_root:
            print(f"robots: {terminal_safe_text(row.robots)}")


def audit_errors(rows: list[AuditRow], source_file_count: int) -> list[str]:
    errors: list[str] = []
    if source_file_count == 0:
        errors.append("no source registry files were found")
    if not rows:
        errors.append("source registry access audit found no URLs to check")
    if any(not row.ok for row in rows):
        errors.append("one or more source registry URLs were inaccessible")
    if any(row.monitor_root and row.robots == "disallow" for row in rows):
        errors.append("one or more monitor roots are disallowed by robots.txt")
    return errors


def main() -> int:
    args = build_parser().parse_args()
    root = args.root.resolve()
    reference_dirs = tuple(args.reference_dir or ())
    rows: list[AuditRow] = []
    input_errors: list[str] = []
    try:
        snapshots = registry_snapshots(root, reference_dirs)
    except (OSError, UnicodeError, ValueError) as exc:
        snapshots = ()
        input_errors.append(f"source registry input rejected: {exc}")
    source_file_count = len(snapshots)
    if not input_errors:
        rows = run_audit(args, snapshots=snapshots)
    errors = input_errors or audit_errors(rows, source_file_count)
    if args.format == "json":
        print(
            json.dumps(
                {
                    "errors": errors,
                    "source_registry_files": source_file_count,
                    "rows": [row.as_dict() for row in rows],
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print_text(rows, source_file_count, tuple(input_errors))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
