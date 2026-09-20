#!/usr/bin/env python3

from __future__ import annotations

import argparse
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
import socket
import sys
import threading
import time
import unicodedata
from urllib import robotparser
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urlunparse
from urllib.request import Request

import source_chain_artifact_lint
import markdown_structure
import safe_paths
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
MAX_REDIRECTS = 20
MAX_USER_AGENT_CHARS = 200
DEFAULT_MAX_SOURCE_ENTRIES = source_registry_files.DEFAULT_MAX_REGISTRY_ENTRIES
DEFAULT_MAX_SOURCE_FILES = source_registry_files.DEFAULT_MAX_REGISTRY_FILES
DEFAULT_MAX_SOURCE_BYTES = source_registry_files.DEFAULT_MAX_REGISTRY_BYTES
DEFAULT_MAX_UNIQUE_URLS = 2_048
MAX_UNIQUE_URLS = 100_000
DEFAULT_MAX_URL_REFERENCES = 16_384
MAX_URL_REFERENCES = 1_000_000
DEFAULT_MAX_TRANSPORT_REQUESTS = 8_192
MAX_TRANSPORT_REQUESTS = 1_000_000
DEFAULT_RUN_DEADLINE_SECONDS = 300.0
MAX_RUN_DEADLINE_SECONDS = 3_600.0
PENDING_FUTURES_PER_WORKER = 2
MAX_INPUT_DIAGNOSTIC_CHARS = 512


class AuditLimitError(RuntimeError):
    """A structured aggregate-work failure raised before exceeding a bound."""

    def __init__(
        self,
        code: str,
        label: str,
        limit: int | float,
        observed: int | float,
        *,
        phase: str,
    ) -> None:
        self.code = code
        self.limit = limit
        self.observed = observed
        self.phase = phase
        super().__init__(
            f"{label} limit exceeded (limit={limit:g}, observed_at_least={observed:g})"
        )


@dataclass(frozen=True)
class AuditLimits:
    """Conservative whole-audit defaults, shared by CLI and Python callers."""

    max_source_entries: int = DEFAULT_MAX_SOURCE_ENTRIES
    max_source_files: int = DEFAULT_MAX_SOURCE_FILES
    max_source_bytes: int = DEFAULT_MAX_SOURCE_BYTES
    max_unique_urls: int = DEFAULT_MAX_UNIQUE_URLS
    max_url_references: int = DEFAULT_MAX_URL_REFERENCES
    max_transport_requests: int = DEFAULT_MAX_TRANSPORT_REQUESTS
    run_deadline_seconds: float = DEFAULT_RUN_DEADLINE_SECONDS

    def __post_init__(self) -> None:
        source_registry_files.RegistryFileLimits(
            max_visited_entries=self.max_source_entries,
            max_files=self.max_source_files,
            max_aggregate_bytes=self.max_source_bytes,
        )
        _validate_api_positive_int(
            self.max_unique_urls,
            label="max_unique_urls",
            maximum=MAX_UNIQUE_URLS,
        )
        _validate_api_positive_int(
            self.max_url_references,
            label="max_url_references",
            maximum=MAX_URL_REFERENCES,
        )
        _validate_api_positive_int(
            self.max_transport_requests,
            label="max_transport_requests",
            maximum=MAX_TRANSPORT_REQUESTS,
        )
        _validate_api_positive_float(
            self.run_deadline_seconds,
            label="run_deadline_seconds",
            maximum=MAX_RUN_DEADLINE_SECONDS,
        )

    @property
    def registry_file_limits(self) -> source_registry_files.RegistryFileLimits:
        return source_registry_files.RegistryFileLimits(
            max_visited_entries=self.max_source_entries,
            max_files=self.max_source_files,
            max_aggregate_bytes=self.max_source_bytes,
        )

    def as_dict(self) -> dict[str, int | float]:
        return {
            "max_source_entries": self.max_source_entries,
            "max_source_files": self.max_source_files,
            "max_source_bytes": self.max_source_bytes,
            "max_unique_urls": self.max_unique_urls,
            "max_url_references": self.max_url_references,
            "max_transport_requests": self.max_transport_requests,
            "run_deadline_seconds": self.run_deadline_seconds,
        }


def _validate_api_positive_int(value: int, *, label: str, maximum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{label} must be an integer")
    if not 1 <= value <= maximum:
        raise ValueError(f"{label} must be between 1 and {maximum}")


def _validate_api_positive_float(
    value: int | float,
    *,
    label: str,
    maximum: float,
) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{label} must be numeric")
    if not math.isfinite(value) or not 0 < value <= maximum:
        raise ValueError(f"{label} must be greater than 0 and at most {maximum:g}")


def _validate_api_user_agent(value: str) -> None:
    if not isinstance(value, str):
        raise TypeError("user_agent must be a string")
    if (
        not value.strip()
        or len(value) > MAX_USER_AGENT_CHARS
        or CONTROL_RE.search(value)
    ):
        raise ValueError(
            f"user_agent must be 1-{MAX_USER_AGENT_CHARS} characters without controls"
        )


def _validate_api_redirects(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("max_redirects must be an integer")
    if not 0 <= value <= MAX_REDIRECTS:
        raise ValueError(f"max_redirects must be between 0 and {MAX_REDIRECTS}")


def _validated_http_status(value: object) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 100 <= value <= 599
    ):
        raise ValueError("transport returned an invalid HTTP status")
    return value


DEFAULT_AUDIT_LIMITS = AuditLimits()


class MonotonicDeadline:
    """One monotonic deadline shared by inventory, scheduling, and transport."""

    def __init__(
        self,
        seconds: float,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        _validate_api_positive_float(
            seconds,
            label="deadline seconds",
            maximum=MAX_RUN_DEADLINE_SECONDS,
        )
        self.seconds = float(seconds)
        self._clock = time.monotonic if clock is None else clock
        self._lock = threading.Lock()
        self._started_at = self._clock()
        self._expires_at = self._started_at + self.seconds

    def remaining(self, *, phase: str) -> float:
        with self._lock:
            now = self._clock()
        remaining = self._expires_at - now
        if remaining <= 0:
            raise AuditLimitError(
                "run_deadline_exceeded",
                "whole-run monotonic deadline",
                self.seconds,
                max(0.0, now - self._started_at),
                phase=phase,
            )
        return remaining

    def check(self, *, phase: str) -> None:
        self.remaining(phase=phase)

    def exceeded(self, *, phase: str) -> AuditLimitError:
        with self._lock:
            now = self._clock()
        return AuditLimitError(
            "run_deadline_exceeded",
            "whole-run monotonic deadline",
            self.seconds,
            max(self.seconds, now - self._started_at),
            phase=phase,
        )


class TransportRequestBudget:
    """Thread-safe admission control for every actual transport attempt."""

    def __init__(self, limit: int) -> None:
        _validate_api_positive_int(
            limit,
            label="transport request budget",
            maximum=MAX_TRANSPORT_REQUESTS,
        )
        self.limit = limit
        self._used = 0
        self._lock = threading.Lock()

    @property
    def used(self) -> int:
        with self._lock:
            return self._used

    def consume(self, *, phase: str) -> None:
        with self._lock:
            observed = self._used + 1
            if observed > self.limit:
                raise AuditLimitError(
                    "transport_request_limit_exceeded",
                    "transport request count",
                    self.limit,
                    observed,
                    phase=phase,
                )
            self._used = observed


@dataclass(frozen=True)
class AuditDiagnostic:
    code: str
    phase: str
    message: str
    limit: int | float | None = None
    observed: int | float | None = None

    def as_dict(self) -> dict[str, str | int | float | None]:
        return {
            "code": self.code,
            "phase": self.phase,
            "message": self.message,
            "limit": self.limit,
            "observed": self.observed,
        }


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

    def __post_init__(self) -> None:
        if self.status is not None:
            _validated_http_status(self.status)

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
    try:
        _validate_api_positive_int(parsed, label=label, maximum=maximum)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    return parsed


def bounded_positive_float(value: str, *, label: str, maximum: float) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{label} must be numeric") from exc
    try:
        _validate_api_positive_float(parsed, label=label, maximum=maximum)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    return parsed


def safe_user_agent(value: str) -> str:
    try:
        _validate_api_user_agent(value)
    except (TypeError, ValueError) as exc:
        message = str(exc).replace("user_agent", "--user-agent")
        raise argparse.ArgumentTypeError(message) from exc
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
    parser.add_argument(
        "--max-source-entries",
        type=lambda value: bounded_positive_int(
            value,
            label="--max-source-entries",
            maximum=source_registry_files.MAX_REGISTRY_ENTRIES,
        ),
        default=DEFAULT_MAX_SOURCE_ENTRIES,
        help=(
            "Maximum filesystem candidates examined while discovering source registries "
            f"(default: {DEFAULT_MAX_SOURCE_ENTRIES})."
        ),
    )
    parser.add_argument(
        "--max-source-files",
        type=lambda value: bounded_positive_int(
            value,
            label="--max-source-files",
            maximum=source_registry_files.MAX_REGISTRY_FILES,
        ),
        default=DEFAULT_MAX_SOURCE_FILES,
        help=(
            "Maximum retained source-registry Markdown files "
            f"(default: {DEFAULT_MAX_SOURCE_FILES})."
        ),
    )
    parser.add_argument(
        "--max-source-bytes",
        type=lambda value: bounded_positive_int(
            value,
            label="--max-source-bytes",
            maximum=source_registry_files.MAX_REGISTRY_BYTES,
        ),
        default=DEFAULT_MAX_SOURCE_BYTES,
        help=(
            "Maximum aggregate UTF-8 input bytes across source registries "
            f"(default: {DEFAULT_MAX_SOURCE_BYTES})."
        ),
    )
    parser.add_argument(
        "--max-unique-urls",
        type=lambda value: bounded_positive_int(
            value,
            label="--max-unique-urls",
            maximum=MAX_UNIQUE_URLS,
        ),
        default=DEFAULT_MAX_UNIQUE_URLS,
        help=f"Maximum unique URLs retained for audit (default: {DEFAULT_MAX_UNIQUE_URLS}).",
    )
    parser.add_argument(
        "--max-url-references",
        type=lambda value: bounded_positive_int(
            value,
            label="--max-url-references",
            maximum=MAX_URL_REFERENCES,
        ),
        default=DEFAULT_MAX_URL_REFERENCES,
        help=(
            "Maximum total URL references retained across source registries "
            f"(default: {DEFAULT_MAX_URL_REFERENCES})."
        ),
    )
    parser.add_argument(
        "--max-transport-requests",
        type=lambda value: bounded_positive_int(
            value,
            label="--max-transport-requests",
            maximum=MAX_TRANSPORT_REQUESTS,
        ),
        default=DEFAULT_MAX_TRANSPORT_REQUESTS,
        help=(
            "Maximum HEAD, GET, robots, and redirect transport attempts "
            f"(default: {DEFAULT_MAX_TRANSPORT_REQUESTS})."
        ),
    )
    parser.add_argument(
        "--run-deadline",
        type=lambda value: bounded_positive_float(
            value,
            label="--run-deadline",
            maximum=MAX_RUN_DEADLINE_SECONDS,
        ),
        default=DEFAULT_RUN_DEADLINE_SECONDS,
        help=(
            "Whole-run monotonic deadline in seconds "
            f"(default: {DEFAULT_RUN_DEADLINE_SECONDS:g}, maximum: {MAX_RUN_DEADLINE_SECONDS:g})."
        ),
    )
    parser.add_argument("--user-agent", type=safe_user_agent, default=DEFAULT_USER_AGENT, help="HTTP User-Agent.")
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Audit report format (default: text).",
    )
    return parser


def audit_limits_from_args(args: argparse.Namespace) -> AuditLimits:
    """Build typed limits while preserving Namespaces made by older API callers."""

    return AuditLimits(
        max_source_entries=getattr(
            args,
            "max_source_entries",
            DEFAULT_MAX_SOURCE_ENTRIES,
        ),
        max_source_files=getattr(args, "max_source_files", DEFAULT_MAX_SOURCE_FILES),
        max_source_bytes=getattr(args, "max_source_bytes", DEFAULT_MAX_SOURCE_BYTES),
        max_unique_urls=getattr(args, "max_unique_urls", DEFAULT_MAX_UNIQUE_URLS),
        max_url_references=getattr(
            args,
            "max_url_references",
            DEFAULT_MAX_URL_REFERENCES,
        ),
        max_transport_requests=getattr(
            args,
            "max_transport_requests",
            DEFAULT_MAX_TRANSPORT_REQUESTS,
        ),
        run_deadline_seconds=getattr(
            args,
            "run_deadline",
            DEFAULT_RUN_DEADLINE_SECONDS,
        ),
    )


def validate_programmatic_args(args: argparse.Namespace) -> None:
    """Apply the CLI's scalar contract to direct ``run_audit`` callers."""

    if not isinstance(args.root, Path):
        raise TypeError("root must be a pathlib.Path")
    reference_dirs = args.reference_dir
    if reference_dirs is not None and (
        not isinstance(reference_dirs, (list, tuple))
        or any(not isinstance(item, Path) for item in reference_dirs)
    ):
        raise TypeError("reference_dir must be None or a sequence of pathlib.Path values")
    if not isinstance(args.monitor_roots_only, bool):
        raise TypeError("monitor_roots_only must be boolean")
    if not isinstance(args.check_robots, bool):
        raise TypeError("check_robots must be boolean")
    _validate_api_positive_float(
        args.timeout,
        label="timeout",
        maximum=MAX_TIMEOUT_SECONDS,
    )
    _validate_api_positive_int(
        args.workers,
        label="workers",
        maximum=MAX_WORKERS,
    )
    _validate_api_positive_int(
        args.max_read_bytes,
        label="max_read_bytes",
        maximum=MAX_READ_BYTES,
    )
    _validate_api_user_agent(args.user_agent)


def validate_network_call(
    *,
    timeout: int | float,
    max_read_bytes: int | None,
    user_agent: str,
    max_redirects: int,
    request_budget: TransportRequestBudget | None,
    deadline: MonotonicDeadline | None,
) -> None:
    """Validate a direct network-helper call before any observable work."""

    _validate_api_positive_float(
        timeout,
        label="timeout",
        maximum=MAX_TIMEOUT_SECONDS,
    )
    if max_read_bytes is not None:
        _validate_api_positive_int(
            max_read_bytes,
            label="max_read_bytes",
            maximum=MAX_READ_BYTES,
        )
    _validate_api_user_agent(user_agent)
    _validate_api_redirects(max_redirects)
    if request_budget is not None and not isinstance(
        request_budget,
        TransportRequestBudget,
    ):
        raise TypeError("request_budget must be a TransportRequestBudget")
    if deadline is not None and not isinstance(deadline, MonotonicDeadline):
        raise TypeError("deadline must be a MonotonicDeadline")


def validate_audit_context(
    limits: AuditLimits,
    deadline: MonotonicDeadline | None,
) -> None:
    if not isinstance(limits, AuditLimits):
        raise TypeError("limits must be an AuditLimits instance")
    if deadline is not None and not isinstance(deadline, MonotonicDeadline):
        raise TypeError("deadline must be a MonotonicDeadline")
    if deadline is not None and deadline.seconds > limits.run_deadline_seconds:
        raise ValueError("deadline must not exceed the selected run deadline limit")


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


def bounded_input_diagnostic(prefix: str, exc: BaseException) -> str:
    """Normalize one maintained input-boundary failure for CLI output."""

    detail = terminal_safe_text(f"{prefix}: {exc}")
    if len(detail) <= MAX_INPUT_DIAGNOSTIC_CHARS:
        return detail
    return detail[: MAX_INPUT_DIAGNOSTIC_CHARS - 1] + "…"


def non_fenced_lines(text: str) -> list[tuple[int, str]]:
    return list(markdown_structure.operative_lines(text))


def reference_files(
    root: Path,
    reference_dirs: Path | tuple[Path, ...] | list[Path],
    *,
    limits: AuditLimits = DEFAULT_AUDIT_LIMITS,
    deadline: MonotonicDeadline | None = None,
) -> list[Path]:
    return [
        snapshot.path
        for snapshot in registry_snapshots(
            root,
            reference_dirs,
            limits=limits,
            deadline=deadline,
        )
    ]


def registry_snapshots(
    root: Path,
    reference_dirs: Path | tuple[Path, ...] | list[Path],
    *,
    limits: AuditLimits = DEFAULT_AUDIT_LIMITS,
    deadline: MonotonicDeadline | None = None,
) -> tuple[source_registry_files.MarkdownSnapshot, ...]:
    validate_audit_context(limits, deadline)
    if deadline is not None:
        deadline.check(phase="source registry inventory")
    snapshots = source_registry_files.registry_markdown_snapshots(
        root,
        reference_dirs,
        project_files=PROJECT_SOURCE_REGISTRY_FILES,
        limits=limits.registry_file_limits,
        progress_check=(
            None
            if deadline is None
            else lambda: deadline.check(phase="source registry inventory")
        ),
    )
    if deadline is not None:
        deadline.check(phase="source registry inventory")
    return snapshots


def collect_urls(
    root: Path,
    reference_dir: Path | tuple[Path, ...] | list[Path],
    monitor_roots_only: bool,
    *,
    snapshots: tuple[source_registry_files.MarkdownSnapshot, ...] | None = None,
    limits: AuditLimits = DEFAULT_AUDIT_LIMITS,
    deadline: MonotonicDeadline | None = None,
) -> dict[str, list[UrlRef]]:
    validate_audit_context(limits, deadline)
    if not isinstance(monitor_roots_only, bool):
        raise TypeError("monitor_roots_only must be boolean")
    urls: dict[str, list[UrlRef]] = {}
    retained_url_references = 0
    selected_snapshots = (
        registry_snapshots(
            root,
            reference_dir,
            limits=limits,
            deadline=deadline,
        )
        if snapshots is None
        else snapshots
    )
    if snapshots is not None:
        if any(
            not isinstance(snapshot, source_registry_files.MarkdownSnapshot)
            for snapshot in selected_snapshots
        ):
            raise TypeError("snapshots must contain only MarkdownSnapshot values")
        observed_files = len(selected_snapshots)
        if observed_files > limits.max_source_entries:
            raise AuditLimitError(
                "source_registry_entry_limit_exceeded",
                "source registry inventory entry count",
                limits.max_source_entries,
                observed_files,
                phase="source registry inventory",
            )
        if observed_files > limits.max_source_files:
            raise AuditLimitError(
                "source_registry_file_limit_exceeded",
                "source registry file count",
                limits.max_source_files,
                observed_files,
                phase="source registry inventory",
            )
        aggregate_bytes = 0
        for snapshot in selected_snapshots:
            if deadline is not None:
                deadline.check(phase="source registry inventory")
            if not isinstance(snapshot.path, Path) or not isinstance(
                snapshot.text,
                str,
            ):
                raise TypeError(
                    "MarkdownSnapshot path and text must be pathlib.Path and str values"
                )
            character_count = len(snapshot.text)
            if character_count > limits.max_source_bytes:
                raise AuditLimitError(
                    "source_registry_byte_limit_exceeded",
                    "source registry aggregate bytes",
                    limits.max_source_bytes,
                    character_count,
                    phase="source registry inventory",
                )
            if character_count > safe_paths.DEFAULT_JSON_INPUT_MAX_BYTES:
                raise AuditLimitError(
                    "source_registry_byte_limit_exceeded",
                    "source registry file bytes",
                    safe_paths.DEFAULT_JSON_INPUT_MAX_BYTES,
                    character_count,
                    phase="source registry inventory",
                )
            snapshot_bytes = len(snapshot.text.encode("utf-8"))
            if snapshot_bytes > safe_paths.DEFAULT_JSON_INPUT_MAX_BYTES:
                raise AuditLimitError(
                    "source_registry_byte_limit_exceeded",
                    "source registry file bytes",
                    safe_paths.DEFAULT_JSON_INPUT_MAX_BYTES,
                    snapshot_bytes,
                    phase="source registry inventory",
                )
            aggregate_bytes += snapshot_bytes
            if aggregate_bytes > limits.max_source_bytes:
                raise AuditLimitError(
                    "source_registry_byte_limit_exceeded",
                    "source registry aggregate bytes",
                    limits.max_source_bytes,
                    aggregate_bytes,
                    phase="source registry inventory",
                )

    def retain_url(url: str, ref: UrlRef) -> None:
        nonlocal retained_url_references
        observed_references = retained_url_references + 1
        if observed_references > limits.max_url_references:
            raise AuditLimitError(
                "url_reference_limit_exceeded",
                "source registry URL reference count",
                limits.max_url_references,
                observed_references,
                phase="URL inventory",
            )
        if url not in urls:
            observed = len(urls) + 1
            if observed > limits.max_unique_urls:
                raise AuditLimitError(
                    "unique_url_limit_exceeded",
                    "unique source registry URL count",
                    limits.max_unique_urls,
                    observed,
                    phase="URL inventory",
                )
            urls[url] = []
        urls[url].append(ref)
        retained_url_references = observed_references

    for snapshot in selected_snapshots:
        if deadline is not None:
            deadline.check(phase="URL inventory")
        path = snapshot.path
        rel = path.relative_to(root).as_posix()
        text = snapshot.text
        for line_no, line in non_fenced_lines(text):
            if deadline is not None:
                deadline.check(phase="URL inventory")
            monitor_match = MONITOR_ROOT_LINE_RE.match(line)
            if monitor_match:
                url = clean_url(monitor_match.group(1))
                retain_url(url, UrlRef(rel, line_no, True))
                continue
            if monitor_roots_only:
                continue
            for match in URL_RE.finditer(line):
                url = clean_url(match.group(0))
                retain_url(url, UrlRef(rel, line_no, False))
        if path.name == "SOURCE_UPDATE.md":
            for line_no, url in source_chain_artifact_lint.recurring_source_url_refs_from_text(text):
                if deadline is not None:
                    deadline.check(phase="URL inventory")
                retain_url(clean_url(url), UrlRef(rel, line_no, True))
    return urls


def request_with_redirects(
    url: str,
    method: str,
    timeout: float,
    max_read_bytes: int,
    user_agent: str,
    max_redirects: int = 5,
    *,
    request_budget: TransportRequestBudget | None = None,
    deadline: MonotonicDeadline | None = None,
) -> FetchResult:
    validate_network_call(
        timeout=timeout,
        max_read_bytes=max_read_bytes,
        user_agent=user_agent,
        max_redirects=max_redirects,
        request_budget=request_budget,
        deadline=deadline,
    )
    if method not in {"GET", "HEAD"}:
        raise ValueError("method must be GET or HEAD")
    blocked = blocked_external_url_reason(url, resolve_hostname=False)
    if blocked:
        return FetchResult(False, None, url, "", blocked)
    current_url = url
    for redirect_count in range(max_redirects + 1):
        request = Request(
            current_url,
            method=method,
            headers={"User-Agent": user_agent, "Accept": DEFAULT_ACCEPT},
        )
        try:
            request_timeout = timeout
            if deadline is not None:
                request_timeout = min(
                    timeout,
                    deadline.remaining(phase=f"{method} transport"),
                )
            if request_budget is not None:
                request_budget.consume(phase=f"{method} transport")
            with safe_urlopen(request, timeout=request_timeout, max_redirects=0) as response:
                status = _validated_http_status(getattr(response, "status", None))
                final_url = response.geturl()
                if not isinstance(final_url, str):
                    raise ValueError("transport returned an invalid final URL")
                content_type = response.headers.get("content-type", "")
                if not isinstance(content_type, str):
                    raise ValueError("transport returned an invalid content-type header")
                if method == "GET":
                    response.read(max_read_bytes)
                return FetchResult(
                    True,
                    status,
                    final_url,
                    content_type[:80],
                    "",
                )
        except HTTPError as exc:
            try:
                try:
                    status = _validated_http_status(exc.code)
                except ValueError:
                    return FetchResult(
                        False,
                        None,
                        current_url,
                        "",
                        "transport returned an invalid HTTP error status",
                    )
                location = exc.headers.get("Location") if exc.headers else None
                if status in REDIRECT_STATUS_CODES and location:
                    candidate, blocked_redirect = safe_redirect_target(current_url, location)
                    if blocked_redirect or candidate is None:
                        return FetchResult(
                            False,
                            status,
                            current_url,
                            exc.headers.get("content-type", "")[:80] if exc.headers else "",
                            f"redirect target rejected: {blocked_redirect}",
                        )
                    if redirect_count >= max_redirects:
                        return FetchResult(
                            False,
                            status,
                            candidate,
                            exc.headers.get("content-type", "")[:80] if exc.headers else "",
                            "redirect limit exceeded",
                        )
                    current_url = candidate
                    continue
                return FetchResult(
                    False,
                    status,
                    exc.geturl() if isinstance(exc.geturl(), str) else current_url,
                    exc.headers.get("content-type", "")[:80] if exc.headers else "",
                    "HTTPError",
                )
            finally:
                exc.close()
        except AuditLimitError:
            raise
        except (URLError, TimeoutError, socket.timeout) as exc:
            return FetchResult(False, None, current_url, "", f"{type(exc).__name__}: {str(exc)[:160]}")
        except Exception as exc:
            return FetchResult(False, None, current_url, "", f"{type(exc).__name__}: {str(exc)[:160]}")
    return FetchResult(False, None, current_url, "", "redirect limit exceeded")


def robots_url_for(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse((parsed.scheme, parsed.netloc, "/robots.txt", "", "", ""))


def robots_status(
    url: str,
    timeout: float,
    user_agent: str,
    *,
    max_redirects: int = 5,
    request_budget: TransportRequestBudget | None = None,
    deadline: MonotonicDeadline | None = None,
) -> str:
    validate_network_call(
        timeout=timeout,
        max_read_bytes=None,
        user_agent=user_agent,
        max_redirects=max_redirects,
        request_budget=request_budget,
        deadline=deadline,
    )
    current_url = robots_url_for(url)
    content_type = ""
    body = ""
    for redirect_count in range(max_redirects + 1):
        try:
            request_timeout = timeout
            if deadline is not None:
                request_timeout = min(
                    timeout,
                    deadline.remaining(phase="robots transport"),
                )
            if request_budget is not None:
                request_budget.consume(phase="robots transport")
            request = Request(current_url, headers={"User-Agent": user_agent})
            with safe_urlopen(request, timeout=request_timeout, max_redirects=0) as response:
                _validated_http_status(getattr(response, "status", None))
                content_type = response.headers.get("content-type", "")
                if not isinstance(content_type, str):
                    return "unknown"
                body = response.read(20000).decode("utf-8", "replace")
            break
        except HTTPError as exc:
            try:
                location = exc.headers.get("Location") if exc.headers else None
                if exc.code not in REDIRECT_STATUS_CODES or not location:
                    return "unknown"
                candidate, blocked_redirect = safe_redirect_target(current_url, location)
                if blocked_redirect or candidate is None or redirect_count >= max_redirects:
                    return "unknown"
                current_url = candidate
            finally:
                exc.close()
        except AuditLimitError:
            raise
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
    *,
    request_budget: TransportRequestBudget | None = None,
    deadline: MonotonicDeadline | None = None,
) -> AuditRow:
    validate_network_call(
        timeout=timeout,
        max_read_bytes=max_read_bytes,
        user_agent=user_agent,
        max_redirects=5,
        request_budget=request_budget,
        deadline=deadline,
    )
    if not isinstance(check_robots, bool):
        raise TypeError("check_robots must be boolean")
    if len(refs) > MAX_URL_REFERENCES:
        raise ValueError(
            f"refs must contain at most {MAX_URL_REFERENCES} URL references"
        )
    if any(not isinstance(ref, UrlRef) for ref in refs):
        raise TypeError("refs must contain only UrlRef values")
    blocked = blocked_external_url_reason(url, resolve_hostname=False)
    if blocked:
        rejected = FetchResult(False, None, url, "", blocked)
        return AuditRow(url, tuple(refs), rejected, None, "not_checked")
    head = request_with_redirects(
        url,
        "HEAD",
        timeout,
        max_read_bytes,
        user_agent,
        request_budget=request_budget,
        deadline=deadline,
    )
    get: FetchResult | None = None
    if not head.ok or (head.status is not None and head.status >= 400):
        get = request_with_redirects(
            url,
            "GET",
            timeout,
            max_read_bytes,
            user_agent,
            request_budget=request_budget,
            deadline=deadline,
        )
    robots = "not_checked"
    if check_robots and any(ref.monitor_root for ref in refs):
        robots = robots_status(
            url,
            timeout,
            user_agent,
            request_budget=request_budget,
            deadline=deadline,
        )
    return AuditRow(url, tuple(refs), head, get, robots)


def run_audit(
    args: argparse.Namespace,
    *,
    snapshots: tuple[source_registry_files.MarkdownSnapshot, ...] | None = None,
    limits: AuditLimits | None = None,
    deadline: MonotonicDeadline | None = None,
    request_budget: TransportRequestBudget | None = None,
) -> list[AuditRow]:
    validate_programmatic_args(args)
    namespace_limits = audit_limits_from_args(args)
    selected_limits = namespace_limits if limits is None else limits
    validate_audit_context(selected_limits, deadline)
    if request_budget is not None and not isinstance(
        request_budget,
        TransportRequestBudget,
    ):
        raise TypeError("request_budget must be a TransportRequestBudget")
    if (
        request_budget is not None
        and request_budget.limit > selected_limits.max_transport_requests
    ):
        raise ValueError(
            "request_budget must not exceed the selected transport request limit"
        )
    selected_deadline = (
        MonotonicDeadline(selected_limits.run_deadline_seconds)
        if deadline is None
        else deadline
    )
    selected_budget = (
        TransportRequestBudget(selected_limits.max_transport_requests)
        if request_budget is None
        else request_budget
    )
    root = args.root.resolve()
    reference_dirs = tuple(args.reference_dir or ())
    urls = collect_urls(
        root,
        reference_dirs,
        args.monitor_roots_only,
        snapshots=snapshots,
        limits=selected_limits,
        deadline=selected_deadline,
    )
    workers = args.workers
    rows: list[AuditRow] = []
    pending_limit = PENDING_FUTURES_PER_WORKER * workers
    work_items = iter(sorted(urls.items()))
    work_exhausted = False
    executor = ThreadPoolExecutor(max_workers=workers)
    pending: set[Future[AuditRow]] = set()
    try:
        while pending or not work_exhausted:
            while not work_exhausted and len(pending) < pending_limit:
                selected_deadline.check(phase="audit work submission")
                try:
                    url, refs = next(work_items)
                except StopIteration:
                    work_exhausted = True
                    break
                pending.add(
                    executor.submit(
                        audit_url,
                        url,
                        refs,
                        args.timeout,
                        args.max_read_bytes,
                        args.user_agent,
                        args.check_robots,
                        request_budget=selected_budget,
                        deadline=selected_deadline,
                    )
                )
            if not pending:
                continue
            remaining = selected_deadline.remaining(phase="audit work wait")
            completed, still_pending = wait(
                pending,
                timeout=remaining,
                return_when=FIRST_COMPLETED,
            )
            pending = set(still_pending)
            if not completed:
                raise selected_deadline.exceeded(phase="audit work wait")
            for future in completed:
                rows.append(future.result())
    except BaseException:
        for future in pending:
            future.cancel()
        raise
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
    selected_deadline.check(phase="audit completion")
    return sorted(rows, key=lambda row: row.url)


def print_text(
    rows: list[AuditRow],
    source_file_count: int,
    input_errors: tuple[str, ...] = (),
    *,
    source_byte_count: int = 0,
    transport_request_count: int = 0,
    diagnostics: tuple[AuditDiagnostic, ...] = (),
) -> None:
    failures = [row for row in rows if not row.ok]
    get_fallbacks = [row for row in rows if row.get is not None and row.ok]
    robot_disallowed = [row for row in rows if row.monitor_root and row.robots == "disallow"]
    print(f"source_registry_files: {source_file_count}")
    print(f"source_registry_bytes: {source_byte_count}")
    print(f"unique_urls: {len(rows)}")
    print(f"url_references: {sum(len(row.refs) for row in rows)}")
    print(f"transport_requests: {transport_request_count}")
    print(f"failures: {len(failures)}")
    print(f"get_fallback_successes: {len(get_fallbacks)}")
    print(f"monitor_robots_disallowed: {len(robot_disallowed)}")
    for error in input_errors:
        print(f"input_error: {terminal_safe_text(error)}")
    for diagnostic in diagnostics:
        print(
            "diagnostic: "
            + terminal_safe_text(
                json.dumps(
                    diagnostic.as_dict(),
                    sort_keys=True,
                    ensure_ascii=True,
                )
            )
        )
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
    limits = audit_limits_from_args(args)
    deadline = MonotonicDeadline(limits.run_deadline_seconds)
    request_budget = TransportRequestBudget(limits.max_transport_requests)
    reference_dirs = tuple(args.reference_dir or ())
    rows: list[AuditRow] = []
    input_errors: list[str] = []
    diagnostics: list[AuditDiagnostic] = []
    try:
        root = args.root.resolve()
        snapshots = registry_snapshots(
            root,
            reference_dirs,
            limits=limits,
            deadline=deadline,
        )
    except source_registry_files.RegistryLimitError as exc:
        snapshots = ()
        message = bounded_input_diagnostic("source registry input rejected", exc)
        input_errors.append(message)
        diagnostics.append(
            AuditDiagnostic(
                code=exc.code,
                phase="source registry inventory",
                message=message,
                limit=exc.limit,
                observed=exc.observed,
            )
        )
    except AuditLimitError as exc:
        snapshots = ()
        message = bounded_input_diagnostic("source registry input rejected", exc)
        input_errors.append(message)
        diagnostics.append(
            AuditDiagnostic(
                code=exc.code,
                phase=exc.phase,
                message=message,
                limit=exc.limit,
                observed=exc.observed,
            )
        )
    except safe_paths.OutputDirectoryBindingError as exc:
        snapshots = ()
        message = bounded_input_diagnostic(
            "source registry path binding rejected",
            exc,
        )
        input_errors.append(message)
        diagnostics.append(
            AuditDiagnostic(
                code="source_registry_path_binding_rejected",
                phase="source registry inventory",
                message=message,
            )
        )
    except (OSError, UnicodeError, ValueError) as exc:
        snapshots = ()
        message = bounded_input_diagnostic("source registry input rejected", exc)
        input_errors.append(message)
        diagnostics.append(
            AuditDiagnostic(
                code="source_registry_input_rejected",
                phase="source registry inventory",
                message=message,
            )
        )
    source_file_count = len(snapshots)
    source_byte_count = sum(len(snapshot.text.encode("utf-8")) for snapshot in snapshots)
    if not input_errors:
        try:
            rows = run_audit(
                args,
                snapshots=snapshots,
                limits=limits,
                deadline=deadline,
                request_budget=request_budget,
            )
        except AuditLimitError as exc:
            message = bounded_input_diagnostic(
                "source registry access audit stopped",
                exc,
            )
            input_errors.append(message)
            diagnostics.append(
                AuditDiagnostic(
                    code=exc.code,
                    phase=exc.phase,
                    message=message,
                    limit=exc.limit,
                    observed=exc.observed,
                )
            )
        except safe_paths.OutputDirectoryBindingError as exc:
            message = bounded_input_diagnostic(
                "source registry path binding rejected",
                exc,
            )
            input_errors.append(message)
            diagnostics.append(
                AuditDiagnostic(
                    code="source_registry_path_binding_rejected",
                    phase="source registry audit setup",
                    message=message,
                )
            )
        except (OSError, UnicodeError, ValueError) as exc:
            message = bounded_input_diagnostic(
                "source registry audit input rejected",
                exc,
            )
            input_errors.append(message)
            diagnostics.append(
                AuditDiagnostic(
                    code="source_registry_input_rejected",
                    phase="source registry audit setup",
                    message=message,
                )
            )
    errors = input_errors or audit_errors(rows, source_file_count)
    if args.format == "json":
        print(
            json.dumps(
                {
                    "errors": errors,
                    "diagnostics": [diagnostic.as_dict() for diagnostic in diagnostics],
                    "limits": limits.as_dict(),
                    "source_registry_files": source_file_count,
                    "source_registry_bytes": source_byte_count,
                    "url_references": sum(len(row.refs) for row in rows),
                    "transport_requests": request_budget.used,
                    "rows": [row.as_dict() for row in rows],
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print_text(
            rows,
            source_file_count,
            tuple(input_errors),
            source_byte_count=source_byte_count,
            transport_request_count=request_budget.used,
            diagnostics=tuple(diagnostics),
        )
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
