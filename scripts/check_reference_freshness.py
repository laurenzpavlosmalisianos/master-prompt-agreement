#!/usr/bin/env python3

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, timedelta
import json
import math
from pathlib import Path
import re
import sys
import time
import unicodedata
from urllib.parse import ParseResult, urlparse

import markdown_structure
import safe_paths
import product_manifest
import source_registry_files
from url_safety import (
    DEFAULT_HOSTNAME_RESOLUTION_TIMEOUT_SECONDS,
    MAX_HOSTNAME_RESOLUTION_TIMEOUT_SECONDS,
    HostnameResolutionCache,
    blocked_external_url_reason,
    validated_hostname_resolution_timeout_seconds,
)


REPO_ROOT = Path(__file__).resolve().parent.parent
REFERENCE_DIRS: tuple[Path, ...] = ()
PROJECT_SOURCE_PACKS = Path("SOURCE_PACKS.md")
PROJECT_SOURCE_UPDATE = Path("SOURCE_UPDATE.md")
PRODUCT_ROOT_MARKDOWN_FILES = tuple(
    Path(relative)
    for relative in product_manifest.PRODUCT_REQUIRED_FILES
    if "/" not in relative and relative.endswith(".md")
)
PRODUCT_DOCUMENTATION_ROOTS = (
    Path(".agents/skills/master-prompt-new-project"),
    Path(".agents/skills/master-prompt-refresh-project"),
    Path("annexes"),
    Path("docs"),
    Path("examples"),
    Path("integrations"),
    Path("practice_guides"),
    Path("project_state_templates"),
    Path("runtime"),
    Path("scripts"),
    Path("task_orders"),
)
PRODUCT_DOCUMENTATION_MAX_ENTRIES = 16_384
PRODUCT_DOCUMENTATION_MAX_DEPTH = 32
DEFAULT_MAX_SOURCE_FILES = source_registry_files.DEFAULT_MAX_REGISTRY_FILES
DEFAULT_MAX_SOURCE_BYTES = source_registry_files.DEFAULT_MAX_REGISTRY_BYTES
DEFAULT_MAX_UNIQUE_HOSTS = 2_048
MAX_UNIQUE_HOSTS = 100_000
DEFAULT_MAX_HOSTNAME_RESOLUTION_REQUESTS = 4_096
MAX_HOSTNAME_RESOLUTION_REQUESTS = 100_000
DEFAULT_MAX_HOSTNAME_RESOLUTION_CACHE_ENTRIES = 4_097
MAX_HOSTNAME_RESOLUTION_CACHE_ENTRIES = 100_001
DEFAULT_RUN_DEADLINE_SECONDS = 300.0
MAX_RUN_DEADLINE_SECONDS = 3_600.0
MAX_SOURCE_INPUT_DIAGNOSTIC_CHARS = 512
REVIEWED_RE = re.compile(r"^Reviewed:\s*(\d{4}-\d{2}-\d{2})\s*$", re.MULTILINE)
ISO_DATE_RE = re.compile(r"\b20\d{2}-\d{2}-\d{2}\b")
URL_RE = re.compile(r"https?://\S+")
SOURCE_ROOT_SEGMENTS = {
    "advisories",
    "articles",
    "blog",
    "blogs",
    "case-studies",
    "categories",
    "category",
    "changelog",
    "directives",
    "docs",
    "documentation",
    "engineering",
    "feed",
    "feeds",
    "news",
    "posts",
    "publications",
    "release-notes",
    "releases",
    "research",
    "resources",
    "rss",
    "rss.xml",
    "security-alerts",
    "tag",
    "tags",
    "topic",
    "topics",
    "updates",
}
SOURCE_SELECTOR_SEGMENTS = {"category", "categories", "tag", "tags", "topic", "topics"}
CONTENT_ROOT_SEGMENTS = {"articles", "blog", "blogs", "engineering", "news", "posts", "research"}
EXACT_ITEM_PARENT_SEGMENTS = SOURCE_ROOT_SEGMENTS | {"abs", "html", "paper", "papers"}
REPOSITORY_ITEM_SEGMENTS = {"blob", "commit", "pull", "tree"}
FEED_FILENAME_RE = re.compile(r"^(?:atom|feed|rss)(?:\.(?:atom|rss|xml))?$", re.IGNORECASE)
LOCALE_SEGMENT_RE = re.compile(r"^[a-z]{2}(?:-[a-z]{2})?$", re.IGNORECASE)
VERSION_LIKE_SEGMENT_RE = re.compile(
    r"^(?:v?\d+(?:[._-]\d+)+(?:[._-][a-z0-9]+)*|\d+(?:-[a-z0-9]+){1,4})$",
    re.IGNORECASE,
)
MONITOR_ROOT_LINE_RE = re.compile(r"^\s*Monitor root:\s*(?P<decision>.+?)\s*$", re.IGNORECASE)
OBSOLETE_REFERENCE_ONLY_MARKER = "none" + "-one-off"
CANONICAL_EXACT_ROOT_REQUIRED = (
    "Canonical exact root reason",
    "Freshness mechanism kind",
    "Source authority",
    "Revalidation interval days",
    "Replacement discovery mode",
    "Replacement discovery reference",
)
RETIRED_CANONICAL_EXACT_ROOT_FIELDS = (
    "Freshness mechanism",
    "Revalidation interval",
    "Replacement discovery fallback",
)
FRESHNESS_MECHANISM_KINDS = {
    "content_digest",
    "http_validator",
    "item_cursor",
    "release_identifier",
    "revision_identifier",
}
REPLACEMENT_DISCOVERY_MODES = {
    "alternate_url",
    "manual_authority_review",
}
MONITOR_HOST_RELATIONS = {
    "approved_cross_host",
    "evidence_host",
}
REPOSITORY_REFERENCE_ANCHOR_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{1,127}$")
AUTHORITY_RECORD_HEADER_RE = re.compile(
    r"^[-*+] \d{4}-\d{2}-\d{2}, "
    r"(?:decision_id|directive_id):\s*"
    r"(?P<record_id>[^\s,;]+)\s*$"
)
AUTHORITY_RECORD_STATUS_RE = re.compile(r"^\s{2,}Status:\s*(?P<status>\S.*?)\s*$")
TOP_LEVEL_BULLET_RE = re.compile(r"^[-*+] ")
STATIC_ARTIFACT_URL_RE = re.compile(
    r"\.(?:pdf|docx?|pptx?|xlsx?|csv|tsv|zip|tar\.gz|tgz|gz)(?:[?#].*)?$",
    re.IGNORECASE,
)
CHECK_WORD_RE = re.compile(
    r"\b(as of|checked\s+(?:through|on|against|via|by|with)|last checked|reviewed\s+on|retrieved|"
    r"verified\s+on)\b",
    re.IGNORECASE,
)
SOURCE_STATE_RE = re.compile(
    r"\b(latest|current|currently|stable|deprecated|removed|available|default)\b",
    re.IGNORECASE,
)
VERSION_RE = re.compile(
    r"\b(?:v?\d+\.\d+(?:\.\d+){0,2}|ES20\d{2}|Python\s+\d|Rust\s+\d|TypeScript\s+\d|SLSA\s+v?\d|Kubernetes\s+\d)\b",
    re.IGNORECASE,
)
COMMIT_SHA_RE = re.compile(r"(?:\bcommit\s+`?[0-9a-f]{7,40}`?|\b[0-9a-f]{7,40}\b)", re.IGNORECASE)
PRERELEASE_URL_RE = re.compile(
    r"https?://\S*(?:[-./](?:rc\d*|alpha|beta|preview|nightly|draft)\b)",
    re.IGNORECASE,
)
PRERELEASE_TOKEN_RE = re.compile(
    r"\b(?:release candidate|pre-release|prerelease|alpha|beta|preview|nightly|draft)\b",
    re.IGNORECASE,
)
PRERELEASE_QUALIFIER_RE = re.compile(
    r"\b(?:not stable|unstable|not default|experimental|historical|supersede(?:s|d)?|"
    r"dated\b.{0,40}\bevidence|source-sensitive|verify|re-check|recheck|volatile|"
    r"do not (?:silently )?(?:treat|replace|adopt)|not doctrine|source limits)\b",
    re.IGNORECASE,
)
PLACEHOLDER_DATE_RE = re.compile(r"\[(?:YYYY-MM-DD|DATE)\]")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
TIER_PREFIX_RE = re.compile(r"^-\s+\[([a-z-]+)\]\s+")
TABLE_SEPARATOR_RE = re.compile(r"^\s*\|(?:\s*:?-+:?\s*\|)+\s*$")
SOURCE_PACK_REQUIRED_FIELDS = (
    "Evidence URL",
    "Role",
    "Allowed Use",
    "Version Anchor",
    "Access Policy",
    "Last Checked",
)
SOURCE_PACK_ROLES = {
    "authority root",
    "evidence URL".casefold(),
    "discovery filter",
}
SOURCE_PACK_ALLOWED_USES = {
    "normative after verification",
    "evidence-only",
    "source discovery only",
    "inspiration only",
    "prohibited",
    "approved copied material with license record",
}
SOURCE_UPDATE_TIER_CELL_RE = re.compile(r"^\[([a-z-]+)\]$")
SOURCE_UPDATE_MONITORING_MODES = {"one_off", "recurring"}
SOURCE_UPDATE_TABLE_HEADERS = {
    "Source Registry": (
        "Surface",
        "Source",
        "Kind",
        "Tier",
        "Scope",
        "Volatility",
        "Check Method",
        "Access Policy",
        "Monitoring Mode",
        "Cadence",
        "Last Checked",
        "Allowed Use",
        "Action Rule",
    ),
    "Feed Watchers": (
        "Surface",
        "Feed",
        "Tier",
        "Scope",
        "Check Method",
        "Access Policy",
        "Conditional State",
        "Dedupe Key",
        "Last Checked",
        "Last Seen",
        "Allowed Use",
        "Triage Rule",
        "Output",
    ),
}
ACCESS_POLICY_CHECK_RE = re.compile(r"^robots/terms checked on (?P<date>\d{4}-\d{2}-\d{2})$")
ACCESS_POLICY_VALUES = {
    "approved local source",
    "not applicable",
    "user-supplied",
}
ALLOWED_TIERS = {
    "standard",
    "official-doc",
    "vendor-doc",
    "official-implementation",
    "research",
    "case-study-root",
    "case-study",
    "commentary",
    "ai-summary",
}
LOWER_TIER_ALLOWED_USES = {
    "case-study-root": {"source discovery only"},
    "case-study": {"evidence-only"},
    "commentary": {"source discovery only"},
    "ai-summary": {"inspiration only"},
}
NON_SOURCE_SECTIONS = ("working rules", "current source notes", "current version anchors")

@dataclass(frozen=True)
class Issue:
    severity: str
    path: str
    line: int
    message: str

    def as_dict(self) -> dict[str, str | int]:
        return {
            "severity": self.severity,
            "path": self.path,
            "line": self.line,
            "message": self.message,
        }


class FreshnessLimitError(ValueError):
    """Fail-closed aggregate-work limit failure."""


def _bounded_source_input_diagnostic(prefix: str, exc: BaseException) -> str:
    """Return one control-safe, length-bounded CLI diagnostic line."""

    rendered: list[str] = []
    for character in f"{prefix}: {exc}":
        codepoint = ord(character)
        category = unicodedata.category(character)
        if category not in {"Cc", "Cf", "Cs", "Zl", "Zp"}:
            rendered.append(character)
        elif codepoint <= 0xFF:
            rendered.append(f"\\x{codepoint:02x}")
        elif codepoint <= 0xFFFF:
            rendered.append(f"\\u{codepoint:04x}")
        else:
            rendered.append(f"\\U{codepoint:08x}")
    detail = "".join(rendered)
    if len(detail) <= MAX_SOURCE_INPUT_DIAGNOSTIC_CHARS:
        return detail
    return detail[: MAX_SOURCE_INPUT_DIAGNOSTIC_CHARS - 1] + "…"


def _validate_positive_int(value: int, *, label: str, maximum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{label} must be an integer")
    if not 1 <= value <= maximum:
        raise ValueError(f"{label} must be between 1 and {maximum}")


def _validate_positive_float(
    value: int | float,
    *,
    label: str,
    maximum: float,
) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{label} must be numeric")
    if not math.isfinite(value) or not 0 < value <= maximum:
        raise ValueError(f"{label} must be greater than 0 and at most {maximum:g}")


@dataclass(frozen=True)
class FreshnessLimits:
    """Conservative whole-run limits shared by CLI and Python callers."""

    max_source_files: int = DEFAULT_MAX_SOURCE_FILES
    max_source_bytes: int = DEFAULT_MAX_SOURCE_BYTES
    max_unique_hosts: int = DEFAULT_MAX_UNIQUE_HOSTS
    max_hostname_resolution_requests: int = (
        DEFAULT_MAX_HOSTNAME_RESOLUTION_REQUESTS
    )
    max_hostname_resolution_cache_entries: int = (
        DEFAULT_MAX_HOSTNAME_RESOLUTION_CACHE_ENTRIES
    )
    run_deadline_seconds: float = DEFAULT_RUN_DEADLINE_SECONDS

    def __post_init__(self) -> None:
        source_registry_files.RegistryFileLimits(
            max_files=self.max_source_files,
            max_aggregate_bytes=self.max_source_bytes,
        )
        _validate_positive_int(
            self.max_unique_hosts,
            label="max_unique_hosts",
            maximum=MAX_UNIQUE_HOSTS,
        )
        _validate_positive_int(
            self.max_hostname_resolution_requests,
            label="max_hostname_resolution_requests",
            maximum=MAX_HOSTNAME_RESOLUTION_REQUESTS,
        )
        _validate_positive_int(
            self.max_hostname_resolution_cache_entries,
            label="max_hostname_resolution_cache_entries",
            maximum=MAX_HOSTNAME_RESOLUTION_CACHE_ENTRIES,
        )
        _validate_positive_float(
            self.run_deadline_seconds,
            label="run_deadline_seconds",
            maximum=MAX_RUN_DEADLINE_SECONDS,
        )

    @property
    def registry_file_limits(self) -> source_registry_files.RegistryFileLimits:
        return source_registry_files.RegistryFileLimits(
            max_files=self.max_source_files,
            max_aggregate_bytes=self.max_source_bytes,
        )


DEFAULT_FRESHNESS_LIMITS = FreshnessLimits()


class FreshnessDeadline:
    """One monotonic deadline shared by inventory, parsing, and DNS work."""

    def __init__(self, seconds: float) -> None:
        _validate_positive_float(
            seconds,
            label="deadline seconds",
            maximum=MAX_RUN_DEADLINE_SECONDS,
        )
        self.seconds = float(seconds)
        self._started_at = time.monotonic()
        self._expires_at = self._started_at + self.seconds

    def remaining(self, *, phase: str) -> float:
        now = time.monotonic()
        remaining = self._expires_at - now
        if remaining <= 0:
            elapsed = max(0.0, now - self._started_at)
            raise FreshnessLimitError(
                "whole-run monotonic deadline exceeded "
                f"during {phase} (limit={self.seconds:g}, "
                f"observed_at_least={elapsed:g})"
            )
        return remaining

    def check(self, *, phase: str) -> None:
        self.remaining(phase=phase)


class _BoundedHostnameResolutionCache(
    dict[tuple[str, int | None], tuple[str, ...]]
):
    """Dict-compatible DNS cache that rejects a new key before overgrowth."""

    def __init__(self, max_entries: int) -> None:
        super().__init__()
        self._max_entries = max_entries

    def __setitem__(
        self,
        key: tuple[str, int | None],
        value: tuple[str, ...],
    ) -> None:
        if key not in self and len(self) >= self._max_entries:
            raise FreshnessLimitError(
                "hostname resolution cache entry limit exceeded "
                f"(limit={self._max_entries}, observed_at_least={len(self) + 1})"
            )
        super().__setitem__(key, value)


class FreshnessWorkBudget:
    """Shared deadline and hostname-resolution accounting for one run."""

    def __init__(
        self,
        limits: FreshnessLimits,
        *,
        deadline: FreshnessDeadline | None = None,
    ) -> None:
        if not isinstance(limits, FreshnessLimits):
            raise TypeError("limits must be a FreshnessLimits instance")
        self.limits = limits
        self.deadline = (
            FreshnessDeadline(limits.run_deadline_seconds)
            if deadline is None
            else deadline
        )
        if not isinstance(self.deadline, FreshnessDeadline):
            raise TypeError("deadline must be a FreshnessDeadline")
        if self.deadline.seconds > limits.run_deadline_seconds:
            raise ValueError("deadline must not exceed the selected run deadline limit")
        self.hostname_resolution_cache: HostnameResolutionCache = (
            _BoundedHostnameResolutionCache(
                limits.max_hostname_resolution_cache_entries
            )
        )
        self._unique_hosts: set[str] = set()
        self._resolution_requests: set[tuple[str, int]] = set()

    def check(self, *, phase: str) -> None:
        self.deadline.check(phase=phase)

    def prepare_hostname_resolution(
        self,
        value: str,
        requested_timeout_seconds: float,
    ) -> float:
        """Reserve one potential uncached host/port lookup before resolving."""

        remaining = self.deadline.remaining(phase="hostname resolution")
        parsed = parse_clean_url(value)
        if parsed is None or parsed.hostname is None:
            return min(requested_timeout_seconds, remaining)
        hostname = parsed.hostname.casefold().rstrip(".")
        if hostname not in self._unique_hosts:
            observed_hosts = len(self._unique_hosts) + 1
            if observed_hosts > self.limits.max_unique_hosts:
                raise FreshnessLimitError(
                    "unique hostname limit exceeded "
                    f"(limit={self.limits.max_unique_hosts}, "
                    f"observed_at_least={observed_hosts})"
                )
            self._unique_hosts.add(hostname)
        try:
            port = parsed.port or 443
        except ValueError:
            return min(requested_timeout_seconds, remaining)
        request_key = (hostname, port)
        if (
            request_key not in self._resolution_requests
            and request_key not in self.hostname_resolution_cache
        ):
            observed_requests = len(self._resolution_requests) + 1
            if observed_requests > self.limits.max_hostname_resolution_requests:
                raise FreshnessLimitError(
                    "hostname resolution request limit exceeded "
                    f"(limit={self.limits.max_hostname_resolution_requests}, "
                    f"observed_at_least={observed_requests})"
                )
            self._resolution_requests.add(request_key)
        return min(requested_timeout_seconds, remaining)


def _bounded_positive_int_argument(
    value: str,
    *,
    label: str,
    maximum: int,
) -> int:
    try:
        parsed = int(value, 10)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{label} must be an integer") from exc
    try:
        _validate_positive_int(parsed, label=label, maximum=maximum)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    return parsed


def _bounded_positive_float_argument(
    value: str,
    *,
    label: str,
    maximum: float,
) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{label} must be numeric") from exc
    try:
        _validate_positive_float(parsed, label=label, maximum=maximum)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    return parsed


def parse_hostname_resolution_timeout_seconds(value: str) -> float:
    try:
        parsed = float(value)
        return validated_hostname_resolution_timeout_seconds(parsed)
    except (OverflowError, TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Fail when source-maintenance evidence is stale or when source-state claims lack "
            "review dates, stable-source qualifiers, or source-tier discipline."
        ),
        allow_abbrev=False,
    )
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help="Repository root to inspect.")
    parser.add_argument(
        "--max-age-days",
        type=int,
        default=180,
        help="Maximum allowed age in days for a reference file review date.",
    )
    parser.add_argument("--today", help="Override today's date for reproducible tests.")
    parser.add_argument(
        "--include-non-reference-docs",
        action="store_true",
        help="Warn on public non-reference Markdown source-state claims without review dates.",
    )
    parser.add_argument(
        "--audit-monitor-roots",
        action="store_true",
        help=(
            "Validate explicit Monitor root lines for durable recurring source surfaces."
        ),
    )
    parser.add_argument(
        "--resolve-hostnames",
        action="store_true",
        help="Resolve source URL hostnames and reject hosts that resolve to non-public addresses.",
    )
    parser.add_argument(
        "--hostname-resolution-timeout-seconds",
        type=parse_hostname_resolution_timeout_seconds,
        default=DEFAULT_HOSTNAME_RESOLUTION_TIMEOUT_SECONDS,
        help=(
            "Deadline for each uncached hostname resolution in seconds "
            f"(greater than 0, at most {MAX_HOSTNAME_RESOLUTION_TIMEOUT_SECONDS:g}; "
            f"default: {DEFAULT_HOSTNAME_RESOLUTION_TIMEOUT_SECONDS:g})."
        ),
    )
    parser.add_argument(
        "--max-source-files",
        type=lambda value: _bounded_positive_int_argument(
            value,
            label="--max-source-files",
            maximum=source_registry_files.MAX_REGISTRY_FILES,
        ),
        default=DEFAULT_MAX_SOURCE_FILES,
        help=(
            "Maximum aggregate Markdown inputs across registries and selected "
            f"public documentation (default: {DEFAULT_MAX_SOURCE_FILES})."
        ),
    )
    parser.add_argument(
        "--max-source-bytes",
        type=lambda value: _bounded_positive_int_argument(
            value,
            label="--max-source-bytes",
            maximum=source_registry_files.MAX_REGISTRY_BYTES,
        ),
        default=DEFAULT_MAX_SOURCE_BYTES,
        help=(
            "Maximum aggregate input bytes across registries and selected public "
            f"documentation (default: {DEFAULT_MAX_SOURCE_BYTES})."
        ),
    )
    parser.add_argument(
        "--max-unique-hosts",
        type=lambda value: _bounded_positive_int_argument(
            value,
            label="--max-unique-hosts",
            maximum=MAX_UNIQUE_HOSTS,
        ),
        default=DEFAULT_MAX_UNIQUE_HOSTS,
        help=(
            "Maximum unique hostnames considered when hostname resolution is enabled "
            f"(default: {DEFAULT_MAX_UNIQUE_HOSTS})."
        ),
    )
    parser.add_argument(
        "--max-hostname-resolution-requests",
        type=lambda value: _bounded_positive_int_argument(
            value,
            label="--max-hostname-resolution-requests",
            maximum=MAX_HOSTNAME_RESOLUTION_REQUESTS,
        ),
        default=DEFAULT_MAX_HOSTNAME_RESOLUTION_REQUESTS,
        help=(
            "Maximum distinct uncached hostname/port resolutions "
            f"(default: {DEFAULT_MAX_HOSTNAME_RESOLUTION_REQUESTS})."
        ),
    )
    parser.add_argument(
        "--max-hostname-resolution-cache-entries",
        type=lambda value: _bounded_positive_int_argument(
            value,
            label="--max-hostname-resolution-cache-entries",
            maximum=MAX_HOSTNAME_RESOLUTION_CACHE_ENTRIES,
        ),
        default=DEFAULT_MAX_HOSTNAME_RESOLUTION_CACHE_ENTRIES,
        help=(
            "Maximum retained hostname-resolution cache entries, including a "
            f"terminal timeout marker (default: {DEFAULT_MAX_HOSTNAME_RESOLUTION_CACHE_ENTRIES})."
        ),
    )
    parser.add_argument(
        "--run-deadline",
        type=lambda value: _bounded_positive_float_argument(
            value,
            label="--run-deadline",
            maximum=MAX_RUN_DEADLINE_SECONDS,
        ),
        default=DEFAULT_RUN_DEADLINE_SECONDS,
        help=(
            "Whole-run monotonic deadline in seconds "
            f"(default: {DEFAULT_RUN_DEADLINE_SECONDS:g}, "
            f"maximum: {MAX_RUN_DEADLINE_SECONDS:g})."
        ),
    )
    parser.add_argument(
        "--reference-dir",
        action="append",
        type=Path,
        help=(
            "Directory containing local source-maintenance Markdown. "
            "Repeat for each selected directory; no local reference directory "
            "is assumed by default."
        ),
    )
    parser.add_argument(
        "--warnings-as-errors",
        action="store_true",
        help="Promote warnings to failing errors.",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format.",
    )
    return parser


def parse_today(value: str | None) -> date:
    if not value:
        return date.today()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is None:
        raise ValueError("today must use extended ISO YYYY-MM-DD form")
    return date.fromisoformat(value)


def rel_path(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def is_declared_project_state_template(root: Path, path: Path) -> bool:
    """Return whether ``path`` is an exact public state-blueprint surface."""

    rel = rel_path(root, path)
    return (
        rel in product_manifest.PRODUCT_REQUIRED_FILE_SET
        and rel.startswith("project_state_templates/")
    )


def _snapshot_text(root: Path, path: Path, text: str | None) -> str:
    if text is not None:
        return text
    snapshot = source_registry_files.read_markdown_snapshot(
        root,
        path,
        description="source-maintenance Markdown input",
    )
    if snapshot is None:  # pragma: no cover - missing_ok is false above
        raise RuntimeError("required source-maintenance snapshot unexpectedly missing")
    return snapshot.text


def reference_markdown_files(root: Path, reference_dirs: tuple[Path, ...] = REFERENCE_DIRS) -> list[Path]:
    return source_registry_files.registry_markdown_files(
        root,
        reference_dirs,
        project_files=(PROJECT_SOURCE_PACKS,),
    )


def source_update_markdown_files(root: Path) -> list[Path]:
    return source_registry_files.project_registry_markdown_files(root, (PROJECT_SOURCE_UPDATE,))


def existing_product_markdown_files(
    root: Path,
    *,
    progress_check: source_registry_files.ProgressCheck | None = None,
) -> list[Path]:
    """Snapshot the closed optional documentation scope and return its paths."""

    try:
        snapshots = source_registry_files.documentation_markdown_snapshots(
            root,
            PRODUCT_ROOT_MARKDOWN_FILES,
            PRODUCT_DOCUMENTATION_ROOTS,
            limits=source_registry_files.RegistryFileLimits(
                max_visited_entries=PRODUCT_DOCUMENTATION_MAX_ENTRIES,
            ),
            progress_check=progress_check,
            max_depth=PRODUCT_DOCUMENTATION_MAX_DEPTH,
        )
    except source_registry_files.RegistryLimitError as exc:
        if exc.code != "source_registry_entry_limit_exceeded":
            raise
        raise ValueError(
            "product documentation inventory exceeds the "
            f"{exc.limit}-entry limit"
        ) from exc
    return [snapshot.path for snapshot in snapshots]


def iter_public_markdown_files(
    root: Path,
    include_non_reference_docs: bool,
    reference_dirs: tuple[Path, ...] = REFERENCE_DIRS,
) -> list[Path]:
    snapshots = source_registry_files.registry_markdown_snapshots(
        root,
        reference_dirs,
        project_files=(PROJECT_SOURCE_PACKS, PROJECT_SOURCE_UPDATE),
        documentation_files=(
            PRODUCT_ROOT_MARKDOWN_FILES if include_non_reference_docs else ()
        ),
        documentation_directories=(
            PRODUCT_DOCUMENTATION_ROOTS if include_non_reference_docs else ()
        ),
        documentation_max_depth=PRODUCT_DOCUMENTATION_MAX_DEPTH,
    )
    return [snapshot.path for snapshot in snapshots]


def strip_fenced_code(text: str) -> list[tuple[int, str]]:
    stripped: list[tuple[int, str]] = []
    visibility = markdown_structure.MarkdownVisibilityState()
    for line_no, line in enumerate(text.splitlines(), start=1):
        _fence_event, visible = visibility.consume(line)
        stripped.append((line_no, visible or ""))
    return stripped


def paragraph_blocks(text: str) -> list[tuple[int, str]]:
    blocks: list[tuple[int, str]] = []
    current: list[str] = []
    start_line = 1
    for line_no, line in strip_fenced_code(text):
        if not line.strip():
            if current:
                blocks.append((start_line, "\n".join(current)))
                current = []
            continue
        if current and LIST_ITEM_RE.match(line):
            blocks.append((start_line, "\n".join(current)))
            current = []
        if not current:
            start_line = line_no
        current.append(line)
    if current:
        blocks.append((start_line, "\n".join(current)))
    return blocks


def section_for_line(text: str, line_no: int) -> str:
    section = ""
    for current_line, line in strip_fenced_code(text):
        if current_line > line_no:
            break
        match = HEADING_RE.match(line)
        if match:
            section = match.group(2).strip().lower()
    return section


def reference_review_issues(
    root: Path,
    path: Path,
    today: date,
    max_age_days: int,
    text: str | None = None,
) -> list[Issue]:
    text = _snapshot_text(root, path, text)
    rel = rel_path(root, path)
    match = REVIEWED_RE.search(text)
    if not match:
        return [Issue("error", rel, 1, "missing Reviewed date")]
    try:
        reviewed = date.fromisoformat(match.group(1))
    except ValueError:
        return [Issue("error", rel, text[: match.start()].count("\n") + 1, f"invalid Reviewed date: {match.group(1)!r}")]
    latest_allowed = today + timedelta(days=1)
    age_days = (today - reviewed).days
    if reviewed > latest_allowed:
        return [Issue("error", rel, text[: match.start()].count("\n") + 1, f"future Reviewed date: {reviewed.isoformat()}")]
    if age_days > max_age_days:
        return [
            Issue(
                "error",
                rel,
                text[: match.start()].count("\n") + 1,
                f"stale reference reviewed {age_days} days ago on {reviewed.isoformat()}",
            )
        ]
    return []


def invalid_iso_dates(block: str) -> list[str]:
    invalid: list[str] = []
    for match in ISO_DATE_RE.finditer(block):
        value = match.group(0)
        try:
            date.fromisoformat(value)
        except ValueError:
            invalid.append(value)
    return invalid


def has_claim_date(block: str) -> bool:
    if PLACEHOLDER_DATE_RE.search(block):
        return True
    block_without_urls = URL_RE.sub("", block)
    for match in ISO_DATE_RE.finditer(block_without_urls):
        try:
            date.fromisoformat(match.group(0))
        except ValueError:
            continue
        return True
    return False


def concrete_source_state_claim(block: str) -> bool:
    source_state_text = re.sub(r"(?m)^\s*\d+(?:\.\d+)+\.?\s*", "", block)
    source_state_text = re.sub(r"\bArticle\s+\d+(?:\.\d+)+\b", "Article", source_state_text, flags=re.IGNORECASE)
    return bool(SOURCE_STATE_RE.search(source_state_text) and (VERSION_RE.search(source_state_text) or COMMIT_SHA_RE.search(source_state_text)))


def requires_same_block_date(block: str, reference_file: bool) -> bool:
    if not concrete_source_state_claim(block):
        return False
    if not reference_file:
        return bool(URL_RE.search(block))
    if COMMIT_SHA_RE.search(block):
        return True
    return bool(re.search(r"\b(latest|newly released|newly available|current hosted|current default)\b", block, re.IGNORECASE))


def check_claim_needs_date(block: str, reference_file: bool) -> bool:
    if not CHECK_WORD_RE.search(block):
        return False
    if reference_file:
        return True
    return bool(URL_RE.search(block) or concrete_source_state_claim(block))


def source_claim_issues(
    root: Path,
    path: Path,
    reference_file: bool,
    resolve_hostnames: bool = False,
    text: str | None = None,
    *,
    hostname_resolution_timeout_seconds: float = (
        DEFAULT_HOSTNAME_RESOLUTION_TIMEOUT_SECONDS
    ),
    hostname_resolution_cache: HostnameResolutionCache | None = None,
    work_budget: FreshnessWorkBudget | None = None,
) -> list[Issue]:
    text = _snapshot_text(root, path, text)
    rel = rel_path(root, path)
    declared_state_template = is_declared_project_state_template(root, path)
    issues: list[Issue] = []
    resolution_cache = hostname_resolution_cache
    if resolve_hostnames and resolution_cache is None:
        resolution_cache = {}
    for line_no, block in paragraph_blocks(text):
        if work_budget is not None:
            work_budget.check(phase="source-claim parsing")
        section = section_for_line(text, line_no)
        if section.startswith("working rules"):
            continue
        if PLACEHOLDER_DATE_RE.search(block):
            if (
                not declared_state_template
                and (CHECK_WORD_RE.search(block) or SOURCE_STATE_RE.search(block))
            ):
                issues.append(Issue("warning", rel, line_no, "source-state placeholder date must be replaced before use"))
            continue
        severity = "error" if reference_file else "warning"
        for match in URL_RE.finditer(block):
            issue = source_url_issue(
                match.group(0),
                resolve_hostname=resolve_hostnames,
                hostname_resolution_timeout_seconds=(
                    hostname_resolution_timeout_seconds
                ),
                hostname_resolution_cache=resolution_cache,
                work_budget=work_budget,
            )
            if issue:
                issues.append(Issue(severity, rel, line_no, issue))
        invalid_dates = invalid_iso_dates(block)
        for invalid_date in invalid_dates:
            issues.append(Issue(severity, rel, line_no, f"invalid ISO date in source-state claim: {invalid_date!r}"))
        missing_valid_date = not has_claim_date(block) and not invalid_dates
        if check_claim_needs_date(block, reference_file) and missing_valid_date:
            issues.append(Issue(severity, rel, line_no, "source check/review claim lacks an ISO date in the same block"))
        if requires_same_block_date(block, reference_file) and missing_valid_date:
            issues.append(Issue(severity, rel, line_no, "concrete external source-state claim lacks an ISO date in the same block"))
        prerelease_url = PRERELEASE_URL_RE.search(block)
        prerelease_source_state = (
            PRERELEASE_TOKEN_RE.search(block)
            and SOURCE_STATE_RE.search(block)
            and (reference_file or URL_RE.search(block) or concrete_source_state_claim(block))
        )
        if (prerelease_url or prerelease_source_state) and not PRERELEASE_QUALIFIER_RE.search(block):
            issues.append(Issue(severity, rel, line_no, "pre-release, preview, draft, alpha, beta, or rc source needs an explicit stability qualifier"))
    return issues


def reference_tier_issues(
    root: Path,
    path: Path,
    text: str | None = None,
) -> list[Issue]:
    text = _snapshot_text(root, path, text)
    rel = rel_path(root, path)
    issues: list[Issue] = []
    for line_no, block in paragraph_blocks(text):
        first_line = block.splitlines()[0]
        if not first_line.startswith("- "):
            continue
        section = section_for_line(text, line_no)
        if any(section.startswith(name) for name in NON_SOURCE_SECTIONS):
            continue
        tier_match = TIER_PREFIX_RE.match(first_line)
        if not tier_match:
            continue
        tier = tier_match.group(1)
        if tier not in ALLOWED_TIERS:
            issues.append(Issue("error", rel, line_no, f"unknown reference tier: {tier}"))
            continue
        if tier == "case-study":
            broad_source_roots = [url for url in bare_entry_urls(block) if is_broad_source_root(url)]
            if broad_source_roots:
                issues.append(
                    Issue(
                        "error",
                        rel,
                        line_no,
                        "case-study entry contains a broad source root as evidence URL; split the parent root into a separate entry or Monitor root line",
                    )
                )
    return issues


def placeholder_cell(value: str) -> bool:
    stripped = value.strip()
    return stripped.startswith("[") and stripped.endswith("]")


def split_table_row(line: str) -> list[str]:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return []
    return [cell.strip() for cell in stripped.strip("|").split("|")]


def source_update_table_rows(
    text: str,
) -> tuple[list[tuple[int, dict[str, str]]], list[tuple[int, str]]]:
    rows: list[tuple[int, dict[str, str]]] = []
    errors: list[tuple[int, str]] = []
    declared_section: str | None = None
    lines = list(markdown_structure.operative_lines(text))
    index = 0
    while index < len(lines):
        line_no, line = lines[index]
        if line.startswith("## "):
            heading = line.removeprefix("## ").strip()
            declared_section = (
                heading if heading in SOURCE_UPDATE_TABLE_HEADERS else None
            )
            index += 1
            continue
        cells = split_table_row(line)
        if not cells:
            index += 1
            continue
        normalized_cells = {cell.casefold() for cell in cells}
        if declared_section is not None:
            table_section = declared_section
        elif {"source", "monitoring mode"} & normalized_cells:
            table_section = "Source Registry"
        elif {"feed", "last seen", "dedupe key"} & normalized_cells:
            table_section = "Feed Watchers"
        else:
            index += 1
            continue

        expected_headers = SOURCE_UPDATE_TABLE_HEADERS[table_section]
        normalized_headers = tuple(cell.casefold() for cell in cells)
        normalized_expected = tuple(cell.casefold() for cell in expected_headers)
        duplicate_headers = sorted(
            {
                header
                for header in normalized_headers
                if normalized_headers.count(header) > 1
            }
        )
        missing_headers = [
            expected_headers[position]
            for position, header in enumerate(normalized_expected)
            if header not in normalized_headers
        ]
        unknown_headers = sorted(
            {
                cells[position]
                for position, header in enumerate(normalized_headers)
                if header not in normalized_expected
            }
        )
        header_errors: list[str] = []
        if duplicate_headers:
            header_errors.append(
                f"SOURCE_UPDATE {table_section} header repeats column(s): "
                + ", ".join(duplicate_headers)
            )
        if missing_headers:
            header_errors.append(
                f"SOURCE_UPDATE {table_section} header is missing exact column(s): "
                + ", ".join(missing_headers)
            )
        if unknown_headers:
            header_errors.append(
                f"SOURCE_UPDATE {table_section} header has unknown column(s): "
                + ", ".join(unknown_headers)
            )
        header_valid = tuple(cells) == expected_headers
        if not header_valid and not header_errors:
            header_errors.append(
                f"SOURCE_UPDATE {table_section} header must use the exact column order and spelling: "
                + " | ".join(expected_headers)
            )
        errors.extend((line_no, message) for message in header_errors)

        separator_index = index + 1
        if (
            separator_index >= len(lines)
            or lines[separator_index][0] != line_no + 1
            or not TABLE_SEPARATOR_RE.match(lines[separator_index][1])
        ):
            errors.append(
                (
                    line_no,
                    f"SOURCE_UPDATE {table_section} header must be followed by a Markdown separator row",
                )
            )
            index += 1
            continue
        separator_line_no, separator_line = lines[separator_index]
        separator_cells = split_table_row(separator_line)
        if len(separator_cells) != len(expected_headers):
            errors.append(
                (
                    separator_line_no,
                    f"SOURCE_UPDATE {table_section} separator has {len(separator_cells)} cells; "
                    f"expected {len(expected_headers)}",
                )
            )
        index += 2
        previous_row_line = separator_line_no
        while index < len(lines):
            row_line, row_text = lines[index]
            row_cells = split_table_row(row_text)
            if not row_cells or row_text.startswith("## "):
                break
            if row_line != previous_row_line + 1:
                errors.append(
                    (
                        row_line,
                        f"SOURCE_UPDATE {table_section} rows must be contiguous in the Markdown source",
                    )
                )
                break
            if TABLE_SEPARATOR_RE.match(row_text):
                errors.append(
                    (
                        row_line,
                        f"SOURCE_UPDATE {table_section} contains an unexpected Markdown separator row",
                    )
                )
            elif len(row_cells) != len(expected_headers):
                errors.append(
                    (
                        row_line,
                        f"SOURCE_UPDATE {table_section} row has {len(row_cells)} cells; "
                        f"expected {len(expected_headers)}",
                    )
                )
            elif header_valid:
                rows.append(
                    (
                        row_line,
                        dict(
                            zip(
                                (header.casefold() for header in expected_headers),
                                row_cells,
                                strict=True,
                            )
                        ),
                    )
                )
            previous_row_line = row_line
            index += 1
    return rows, errors


def checked_date_issue(
    rel: str,
    line_no: int,
    label: str,
    value: str,
    today: date,
    max_age_days: int,
) -> Issue | None:
    normalized = value.strip()
    if not normalized or placeholder_cell(normalized):
        return Issue("error", rel, line_no, f"{label} must be an ISO date")
    if normalized.casefold() == "never":
        return Issue("error", rel, line_no, f"{label} is never; check or remove the source row")
    date_match = re.fullmatch(r"\d{4}-\d{2}-\d{2}", normalized)
    if date_match is None:
        return Issue("error", rel, line_no, f"{label} must be an ISO date, not {normalized!r}")
    try:
        checked = date.fromisoformat(normalized)
    except ValueError:
        return Issue("error", rel, line_no, f"invalid {label}: {normalized!r}")
    if checked > today + timedelta(days=1):
        return Issue("error", rel, line_no, f"future {label}: {checked.isoformat()}")
    age_days = (today - checked).days
    if age_days > max_age_days:
        return Issue("error", rel, line_no, f"stale {label} {age_days} days ago on {checked.isoformat()}")
    return None


def last_seen_cursor_issue(
    rel: str,
    line_no: int,
    value: str,
) -> Issue | None:
    normalized = value.strip()
    if not normalized or placeholder_cell(normalized):
        return Issue("error", rel, line_no, "Last Seen must be an explicit cursor, ISO date, or none")
    if normalized.casefold() == "never":
        return Issue("error", rel, line_no, "Last Seen is never; check or remove the source row")
    if len(normalized.encode("utf-8")) > 512 or any(ord(char) < 32 or ord(char) == 127 for char in normalized):
        return Issue("error", rel, line_no, "Last Seen cursor must be a bounded printable value")
    if re.fullmatch(r"20\d{2}-\d{2}-\d{2}", normalized):
        try:
            date.fromisoformat(normalized)
        except ValueError:
            return Issue("error", rel, line_no, f"invalid Last Seen date: {normalized!r}")
    return None


def access_policy_issue(
    rel: str,
    line_no: int,
    value: str,
    today: date,
    max_age_days: int,
) -> Issue | None:
    normalized = value.strip()
    if not normalized or placeholder_cell(normalized):
        return Issue("error", rel, line_no, "Access Policy must be explicit before use")
    lowered = normalized.casefold()
    if lowered == "blocked":
        return Issue("error", rel, line_no, "blocked Access Policy belongs in open gaps, not a populated source row")
    if lowered in ACCESS_POLICY_VALUES:
        return None
    match = ACCESS_POLICY_CHECK_RE.fullmatch(lowered)
    if match is None:
        return Issue(
            "error",
            rel,
            line_no,
            "Access Policy must be robots/terms checked on YYYY-MM-DD, not applicable, user-supplied, or approved local source",
        )
    try:
        checked = date.fromisoformat(match.group("date"))
    except ValueError:
        return Issue("error", rel, line_no, f"invalid Access Policy date: {match.group('date')!r}")
    if checked > today + timedelta(days=1):
        return Issue("error", rel, line_no, f"future Access Policy date: {checked.isoformat()}")
    age_days = (today - checked).days
    if age_days > max_age_days:
        return Issue("error", rel, line_no, f"stale Access Policy {age_days} days ago on {checked.isoformat()}")
    return None


def source_update_state_issues(
    root: Path,
    path: Path,
    today: date,
    max_age_days: int,
    resolve_hostnames: bool = False,
    text: str | None = None,
    *,
    hostname_resolution_timeout_seconds: float = (
        DEFAULT_HOSTNAME_RESOLUTION_TIMEOUT_SECONDS
    ),
    hostname_resolution_cache: HostnameResolutionCache | None = None,
    work_budget: FreshnessWorkBudget | None = None,
) -> list[Issue]:
    text = _snapshot_text(root, path, text)
    rel = rel_path(root, path)
    issues: list[Issue] = []
    resolution_cache = hostname_resolution_cache
    if resolve_hostnames and resolution_cache is None:
        resolution_cache = {}
    table_rows, table_errors = source_update_table_rows(text)
    issues.extend(
        Issue("error", rel, line_no, message)
        for line_no, message in table_errors
    )
    for line_no, row in table_rows:
        if work_budget is not None:
            work_budget.check(phase="source-update parsing")
        source = row.get("source") or row.get("feed") or ""
        surface = row.get("surface") or ""
        if placeholder_cell(surface) or placeholder_cell(source):
            continue
        monitoring_mode: str | None = None
        if "source" in row:
            monitoring_mode = row.get("monitoring mode", "").strip()
            if not monitoring_mode or placeholder_cell(monitoring_mode):
                issues.append(Issue("error", rel, line_no, "source update Source Registry row missing Monitoring Mode"))
                monitoring_mode = None
            elif monitoring_mode not in SOURCE_UPDATE_MONITORING_MODES:
                issues.append(
                    Issue(
                        "error",
                        rel,
                        line_no,
                        "source update Monitoring Mode must be one of: "
                        + ", ".join(sorted(SOURCE_UPDATE_MONITORING_MODES)),
                    )
                )
                monitoring_mode = None
        if "access policy" not in row:
            issues.append(Issue("error", rel, line_no, "source update row missing Access Policy"))
        else:
            issue = access_policy_issue(rel, line_no, row["access policy"], today, max_age_days)
            if issue:
                issues.append(issue)
        tier = normalized_source_update_tier(row.get("tier", ""))
        if tier is None:
            issues.append(Issue("error", rel, line_no, "source update row Tier must be an allowed bracketed source tier"))
        else:
            allowed_use = row.get("allowed use", "").strip().casefold()
            if not allowed_use or placeholder_cell(allowed_use):
                issues.append(Issue("error", rel, line_no, "source update row missing explicit Allowed Use"))
            elif allowed_use not in SOURCE_PACK_ALLOWED_USES:
                issues.append(
                    Issue(
                        "error",
                        rel,
                        line_no,
                        "source update row Allowed Use must be one of: "
                        + ", ".join(sorted(SOURCE_PACK_ALLOWED_USES)),
                    )
                )
            elif tier in LOWER_TIER_ALLOWED_USES and allowed_use not in LOWER_TIER_ALLOWED_USES[tier]:
                issues.append(
                    Issue(
                        "error",
                        rel,
                        line_no,
                        f"{tier} source update row Allowed Use must be one of: "
                        + ", ".join(sorted(LOWER_TIER_ALLOWED_USES[tier])),
                    )
                )
        urls = [clean_url(match.group(0)) for match in URL_RE.finditer(source)]
        if not urls and row.get("access policy", "").strip().casefold() != "approved local source":
            issues.append(Issue("error", rel, line_no, "source update row Source or Feed must contain an https URL"))
        for url in urls:
            url_issue = source_url_issue(
                url,
                resolve_hostname=resolve_hostnames,
                hostname_resolution_timeout_seconds=(
                    hostname_resolution_timeout_seconds
                ),
                hostname_resolution_cache=resolution_cache,
                work_budget=work_budget,
            )
            if url_issue:
                issues.append(Issue("error", rel, line_no, url_issue))
                continue
            if is_pathless_host_root(url):
                issues.append(
                    Issue("error", rel, line_no, "source update row must use a specific durable parent surface, not a whole-domain URL")
                )
            if "feed" in row:
                if not is_recurring_monitor_root(url):
                    issues.append(
                        Issue(
                            "error",
                            rel,
                            line_no,
                            "Feed must be a durable recurring source root, feed, release page, tags page, or API endpoint",
                        )
                    )
            elif monitoring_mode == "recurring" and not is_recurring_monitor_root(url):
                issues.append(
                    Issue(
                        "error",
                        rel,
                        line_no,
                        "recurring source update row must use a durable parent root or feed",
                    )
                )
        if "last checked" not in row:
            issues.append(Issue("error", rel, line_no, "source update row missing Last Checked"))
        else:
            issue = checked_date_issue(rel, line_no, "Last Checked", row["last checked"], today, max_age_days)
            if issue:
                issues.append(issue)
        if "feed" in row and "last seen" not in row:
            issues.append(Issue("error", rel, line_no, "source update Feed Watcher row missing Last Seen"))
        elif "last seen" in row:
            issue = last_seen_cursor_issue(rel, line_no, row["last seen"])
            if issue:
                issues.append(issue)
    return issues


def normalized_source_update_tier(value: str) -> str | None:
    normalized = value.strip()
    if not normalized:
        return None
    match = SOURCE_UPDATE_TIER_CELL_RE.fullmatch(normalized)
    if match is None:
        return None
    tier = match.group(1)
    if tier not in ALLOWED_TIERS:
        return None
    return tier


def source_pack_entry_blocks(text: str) -> list[tuple[int, list[str]]]:
    blocks: list[tuple[int, list[str]]] = []
    current: list[str] = []
    start_line = 0
    in_sources_section = False
    for line_no, line in strip_fenced_code(text):
        if line == "## Sources":
            if current:
                blocks.append((start_line, current))
                current = []
                start_line = 0
            in_sources_section = True
            continue
        if line.startswith("## "):
            if current:
                blocks.append((start_line, current))
                current = []
                start_line = 0
            in_sources_section = False
            continue
        if not in_sources_section:
            continue
        if TIER_PREFIX_RE.match(line) or line.startswith("- "):
            if current:
                blocks.append((start_line, current))
            current = [line]
            start_line = line_no
            continue
        if current and (line.startswith("  ") or not line.strip()):
            current.append(line)
            continue
        if current:
            blocks.append((start_line, current))
            current = []
            start_line = 0
    if current:
        blocks.append((start_line, current))
    return blocks


def source_pack_metadata_issues(
    root: Path,
    path: Path,
    today: date,
    max_age_days: int,
    text: str | None = None,
) -> list[Issue]:
    text = _snapshot_text(root, path, text)
    rel = rel_path(root, path)
    issues: list[Issue] = []
    for line_no, lines in source_pack_entry_blocks(text):
        first_line = lines[0].strip()
        if "[source name]" in first_line.casefold():
            continue
        if not TIER_PREFIX_RE.match(first_line):
            issues.append(Issue("error", rel, line_no, "source-pack entry missing tier prefix"))
        block = "\n".join(lines)
        required_values: dict[str, str] = {}
        for field in SOURCE_PACK_REQUIRED_FIELDS:
            values = metadata_field_values(block, field)
            if not values:
                issues.append(Issue("error", rel, line_no, f"source-pack entry missing {field}"))
                continue
            if len(values) != 1:
                issues.append(
                    Issue(
                        "error",
                        rel,
                        line_no,
                        f"source-pack {field} must appear exactly once per entry",
                    )
                )
                continue
            if not values[0]:
                issues.append(Issue("error", rel, line_no, f"source-pack entry missing {field}"))
                continue
            required_values[field] = values[0]
        access_value = required_values.get("Access Policy")
        if access_value is not None:
            issue = access_policy_issue(rel, line_no, access_value, today, max_age_days)
            if issue:
                issues.append(issue)
        last_checked_value = required_values.get("Last Checked")
        if last_checked_value is not None:
            issue = checked_date_issue(
                rel,
                line_no,
                "Last Checked",
                last_checked_value,
                today,
                max_age_days,
            )
            if issue:
                issues.append(issue)
        evidence_value = required_values.get("Evidence URL")
        if evidence_value is not None:
            access_policy = access_value.casefold() if access_value is not None else ""
            if URL_RE.fullmatch(evidence_value):
                url_issue = source_url_issue(evidence_value)
                if url_issue:
                    issues.append(Issue("error", rel, line_no, f"source-pack Evidence URL {url_issue}"))
            elif access_policy == "approved local source":
                try:
                    normalized = safe_paths.normalize_repo_relative_path(
                        evidence_value,
                        root,
                        description="source-pack Evidence URL",
                    )
                    safe_paths.read_regular_file_bytes(
                        root / normalized,
                        description="source-pack Evidence URL",
                    )
                except (OSError, ValueError) as exc:
                    issues.append(
                        Issue(
                            "error",
                            rel,
                            line_no,
                            f"source-pack Evidence URL must resolve to a safe local source: {exc}",
                        )
                    )
            else:
                issues.append(
                    Issue(
                        "error",
                        rel,
                        line_no,
                        "source-pack Evidence URL must be exactly one safe https URL unless Access Policy is approved local source",
                    )
                )
        role_value = required_values.get("Role")
        if role_value is not None:
            value = role_value.casefold()
            if value not in SOURCE_PACK_ROLES:
                issues.append(Issue("error", rel, line_no, f"source-pack Role must be one of: {', '.join(sorted(SOURCE_PACK_ROLES))}"))
        allowed_use_value = required_values.get("Allowed Use")
        if allowed_use_value is not None:
            value = allowed_use_value.casefold()
            if value not in SOURCE_PACK_ALLOWED_USES:
                issues.append(
                    Issue(
                        "error",
                        rel,
                        line_no,
                        "source-pack Allowed Use must be one of: " + ", ".join(sorted(SOURCE_PACK_ALLOWED_USES)),
                    )
                )
            else:
                tier_match = TIER_PREFIX_RE.match(first_line)
                tier = tier_match.group(1) if tier_match else None
                if tier in LOWER_TIER_ALLOWED_USES and value not in LOWER_TIER_ALLOWED_USES[tier]:
                    issues.append(
                        Issue(
                            "error",
                            rel,
                            line_no,
                            f"{tier} source-pack Allowed Use must be one of: "
                            + ", ".join(sorted(LOWER_TIER_ALLOWED_USES[tier])),
                        )
                    )
    return issues


def clean_url(value: str) -> str:
    return value.rstrip("`).,;]>\"'")


def parse_clean_url(value: str) -> ParseResult | None:
    try:
        return urlparse(clean_url(value))
    except ValueError:
        return None


def source_url_issue(
    value: str,
    *,
    resolve_hostname: bool = False,
    hostname_resolution_timeout_seconds: float = (
        DEFAULT_HOSTNAME_RESOLUTION_TIMEOUT_SECONDS
    ),
    hostname_resolution_cache: HostnameResolutionCache | None = None,
    work_budget: FreshnessWorkBudget | None = None,
) -> str | None:
    selected_timeout = hostname_resolution_timeout_seconds
    selected_cache = hostname_resolution_cache
    if resolve_hostname and work_budget is not None:
        selected_timeout = work_budget.prepare_hostname_resolution(
            value,
            hostname_resolution_timeout_seconds,
        )
        selected_cache = work_budget.hostname_resolution_cache
    reason = blocked_external_url_reason(
        clean_url(value),
        resolve_hostname=resolve_hostname,
        hostname_resolution_timeout_seconds=selected_timeout,
        hostname_resolution_cache=selected_cache,
    )
    if work_budget is not None:
        work_budget.check(phase="hostname resolution result")
    if reason == "external URL must use https":
        return "external source URL must use https"
    return reason


def monitor_root_lines(block: str, start_line: int) -> list[tuple[int, str]]:
    lines: list[tuple[int, str]] = []
    for offset, line in enumerate(block.splitlines()):
        match = MONITOR_ROOT_LINE_RE.match(line)
        if match:
            lines.append((start_line + offset, match.group("decision").strip()))
    return lines


def is_obsolete_reference_only_monitor_decision(value: str) -> bool:
    return value.casefold().startswith(OBSOLETE_REFERENCE_ONLY_MARKER)


def is_static_artifact_url(value: str) -> bool:
    parsed = parse_clean_url(value)
    if parsed is None:
        return False
    return bool(STATIC_ARTIFACT_URL_RE.search(parsed.path))


def url_path_segments(value: str) -> list[str]:
    parsed = parse_clean_url(value)
    if parsed is None:
        return []
    return [segment.casefold() for segment in parsed.path.strip("/").split("/") if segment]


def is_repository_item_path(value: str) -> bool:
    segments = url_path_segments(value)
    return bool(
        any(
            segment in REPOSITORY_ITEM_SEGMENTS
            and 0 < index < len(segments) - 1
            and segments[index - 1] not in SOURCE_SELECTOR_SEGMENTS
            for index, segment in enumerate(segments)
        )
        or any(left == "releases" and right == "tag" for left, right in zip(segments, segments[1:]))
    )


def is_structural_collection_path(value: str) -> bool:
    segments = url_path_segments(value)
    if not segments or is_static_artifact_url(value) or is_repository_item_path(value):
        return False
    if FEED_FILENAME_RE.fullmatch(segments[-1]):
        return True
    if segments[-1] in SOURCE_ROOT_SEGMENTS or segments[-1].endswith("-advisories"):
        return True
    if len(segments) >= 2 and segments[-2] in SOURCE_SELECTOR_SEGMENTS:
        return True
    if len(segments) >= 3 and segments[-3:-1] == ["search", "label"]:
        return True
    if (
        len(segments) >= 3
        and segments[-2] == "products"
        and any(segment in CONTENT_ROOT_SEGMENTS for segment in segments[:-2])
    ):
        return True
    return bool(
        len(segments) >= 2
        and segments[-2] in {"docs", "documentation"}
        and LOCALE_SEGMENT_RE.fullmatch(segments[-1])
    )


def is_recurring_monitor_root(value: str) -> bool:
    cleaned = clean_url(value).rstrip("/")
    parsed = parse_clean_url(cleaned)
    if parsed is None:
        return False
    if parsed.scheme != "https" or not parsed.netloc:
        return False
    if is_pathless_host_root(cleaned):
        return False
    return is_structural_collection_path(cleaned)


def is_pathless_host_root(value: str) -> bool:
    parsed = parse_clean_url(value)
    if parsed is None:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc) and not parsed.path.strip("/")


def is_exact_source_item_url(value: str) -> bool:
    cleaned = clean_url(value)
    parsed = parse_clean_url(cleaned)
    if parsed is None:
        return False
    if is_structural_collection_path(cleaned):
        return False
    segments = url_path_segments(cleaned)
    return bool(
        is_static_artifact_url(cleaned)
        or is_repository_item_path(cleaned)
        or (len(segments) >= 2 and segments[-2] in EXACT_ITEM_PARENT_SEGMENTS)
        or (segments and VERSION_LIKE_SEGMENT_RE.fullmatch(segments[-1]))
        or (bool(parsed.query) and not is_structural_collection_path(cleaned))
        or (
            len(segments) >= 4
            and re.fullmatch(r"20\d{2}", segments[0])
            and re.fullmatch(r"[A-Za-z]{3,9}|\d{1,2}", segments[1])
            and re.fullmatch(r"\d{1,2}", segments[2])
        )
    )


def metadata_field_values(block: str, label: str) -> list[str]:
    return [
        match.group("value").strip()
        for match in re.finditer(
            rf"^\s*{re.escape(label)}:\s*(?P<value>.*?)\s*$",
            block,
            re.IGNORECASE | re.MULTILINE,
        )
    ]


def authority_record_statuses(text: str, anchor: str) -> list[tuple[str, ...]]:
    """Return statuses only from exact, structured records named by ``anchor``."""

    matches: list[tuple[str, ...]] = []
    current_statuses: list[str] | None = None
    visibility = markdown_structure.MarkdownVisibilityState()

    def finish_record() -> None:
        nonlocal current_statuses
        if current_statuses is not None:
            matches.append(tuple(current_statuses))
            current_statuses = None

    for raw_line in text.splitlines():
        fence_event, visible_line = visibility.consume(raw_line)
        if fence_event is not None:
            if (
                current_statuses is not None
                and raw_line.strip()
                and not raw_line.startswith("  ")
            ):
                finish_record()
            continue
        if visible_line is None:
            continue
        if (
            current_statuses is not None
            and raw_line.strip()
            and not raw_line.startswith("  ")
        ):
            finish_record()
            # Canonical record fields and their continuations are indented;
            # any nonblank line with fewer than two literal spaces ends the
            # record before a later indented field can be borrowed.
        if TOP_LEVEL_BULLET_RE.match(visible_line):
            finish_record()
            header = AUTHORITY_RECORD_HEADER_RE.fullmatch(visible_line)
            if header is not None and header.group("record_id") == anchor:
                current_statuses = []
            continue
        if current_statuses is not None:
            status = AUTHORITY_RECORD_STATUS_RE.fullmatch(visible_line)
            if status is not None:
                current_statuses.append(status.group("status"))
    finish_record()
    return matches


def repository_record_reference_error(
    root: Path,
    value: str,
    *,
    label: str,
    require_anchor: bool,
    require_active_authority_record: bool = False,
    forbidden_path: Path | None = None,
) -> str | None:
    path_value, separator, anchor = value.partition("#")
    if "#" in anchor:
        return f"{label} must contain at most one anchor separator"
    if require_anchor and not separator:
        return f"{label} must identify a safe repo-relative record and approval anchor"
    if separator and not REPOSITORY_REFERENCE_ANCHOR_RE.fullmatch(anchor):
        return f"{label} anchor must be a simple stable identifier"
    try:
        normalized = safe_paths.normalize_repo_relative_path(
            path_value,
            root,
            description=label,
        )
        if forbidden_path is not None and (root / normalized).resolve(strict=False) == forbidden_path.resolve(strict=False):
            return f"{label} must resolve to a separate authority record, not the source registry itself"
        raw = safe_paths.read_regular_file_bytes(
            root / normalized,
            description=label,
        )
        text = raw.decode("utf-8")
    except (OSError, UnicodeError, ValueError) as exc:
        return f"{label} must resolve to a safe bounded repo-relative regular file: {exc}"
    if separator and require_active_authority_record:
        records = authority_record_statuses(text, anchor)
        if len(records) != 1:
            return (
                f"{label} anchor {anchor!r} must exactly match one structured "
                f"decision_id or directive_id record in {normalized}"
            )
        if records[0] != ("active",):
            return (
                f"{label} anchor {anchor!r} must identify a structured authority "
                "record with exactly one Status: active field"
            )
    elif separator and anchor not in text:
        return f"{label} anchor {anchor!r} was not found in {normalized}"
    return None


def canonical_exact_root_metadata_errors(
    root: Path,
    block: str,
    monitor_urls: list[str],
) -> tuple[bool, list[str]]:
    errors: list[str] = []
    class_values = metadata_field_values(block, "Monitor root class")
    if len(class_values) > 1:
        errors.append("Monitor root class must appear exactly once per source entry")
    canonical_exact_root = len(class_values) == 1 and class_values[0] == "canonical_exact_root"
    if class_values and not canonical_exact_root:
        errors.append("Monitor root class must be canonical_exact_root when present")

    for label in RETIRED_CANONICAL_EXACT_ROOT_FIELDS:
        if metadata_field_values(block, label):
            errors.append(f"retired canonical-exact-root field is not allowed: {label}")

    if not canonical_exact_root:
        for label in CANONICAL_EXACT_ROOT_REQUIRED:
            if metadata_field_values(block, label):
                errors.append(f"{label} requires Monitor root class: canonical_exact_root")
        return False, errors

    non_structural_roots = [
        value for value in monitor_urls if not is_recurring_monitor_root(value)
    ]
    if len(non_structural_roots) != 1:
        errors.append(
            "canonical_exact_root requires exactly one non-structural Monitor root per source entry"
        )

    values_by_label: dict[str, str] = {}
    for label in CANONICAL_EXACT_ROOT_REQUIRED:
        values = metadata_field_values(block, label)
        if not values or not values[0] or placeholder_cell(values[0]):
            errors.append(f"canonical_exact_root requires {label}")
            continue
        if len(values) > 1:
            errors.append(f"canonical_exact_root requires exactly one {label}")
            continue
        values_by_label[label] = values[0]

    freshness_kind = values_by_label.get("Freshness mechanism kind")
    if freshness_kind is not None and freshness_kind not in FRESHNESS_MECHANISM_KINDS:
        errors.append(
            "Freshness mechanism kind must be one of: "
            + ", ".join(sorted(FRESHNESS_MECHANISM_KINDS))
        )

    interval = values_by_label.get("Revalidation interval days")
    if interval is not None and re.fullmatch(r"[1-9]\d*", interval) is None:
        errors.append("Revalidation interval days must be a positive integer")

    discovery_mode = values_by_label.get("Replacement discovery mode")
    discovery_reference = values_by_label.get("Replacement discovery reference")
    if discovery_mode is not None and discovery_mode not in REPLACEMENT_DISCOVERY_MODES:
        errors.append(
            "Replacement discovery mode must be one of: "
            + ", ".join(sorted(REPLACEMENT_DISCOVERY_MODES))
        )
    elif discovery_mode == "alternate_url" and discovery_reference is not None:
        if URL_RE.fullmatch(discovery_reference) is None:
            errors.append("alternate_url Replacement discovery reference must be exactly one https URL")
        else:
            cleaned_reference = clean_url(discovery_reference)
            url_issue = source_url_issue(cleaned_reference)
            if url_issue:
                errors.append(f"Replacement discovery reference {url_issue}")
            elif cleaned_reference in {clean_url(value) for value in monitor_urls}:
                errors.append("alternate_url Replacement discovery reference must differ from every Monitor root")
    elif discovery_mode == "manual_authority_review" and discovery_reference is not None:
        issue = repository_record_reference_error(
            root,
            discovery_reference,
            label="Replacement discovery reference",
            require_anchor=False,
        )
        if issue:
            errors.append(issue)
    return True, errors


def entry_evidence_urls(block: str) -> list[str]:
    urls: list[str] = []
    for index, line in enumerate(block.splitlines()):
        stripped = line.strip()
        lowered = stripped.casefold()
        if MONITOR_ROOT_LINE_RE.match(line):
            continue
        if lowered.startswith(("replacement discovery reference:", "approval reference:")):
            continue
        if index == 0 or lowered.startswith("evidence url:") or re.fullmatch(r"https?://\S+", stripped):
            urls.extend(clean_url(match.group(0)) for match in URL_RE.finditer(stripped))
    return urls


def bare_entry_urls(block: str) -> list[str]:
    urls: list[str] = []
    for line in block.splitlines()[1:]:
        stripped = line.strip()
        if stripped.lower().startswith("monitor root:"):
            continue
        match = re.fullmatch(r"https?://\S+", stripped)
        if match:
            urls.append(clean_url(match.group(0)))
    return urls


def is_broad_source_root(value: str) -> bool:
    parsed = parse_clean_url(value)
    if parsed is None:
        return False
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    if not parsed.path.strip("/"):
        return True
    return is_structural_collection_path(value)


def normalized_host(value: str) -> str:
    parsed = parse_clean_url(value)
    if parsed is None or parsed.hostname is None:
        return ""
    return parsed.hostname.casefold().rstrip(".")


def host_matches_evidence_host(left: str, right: str) -> bool:
    left_host = normalized_host(left)
    right_host = normalized_host(right)
    return bool(left_host and right_host and left_host == right_host)


def monitor_root_issues(
    root: Path,
    path: Path,
    text: str | None = None,
) -> list[Issue]:
    text = _snapshot_text(root, path, text)
    rel = rel_path(root, path)
    issues: list[Issue] = []
    for line_no, block in paragraph_blocks(text):
        evidence_urls = entry_evidence_urls(block)
        monitor_decisions = monitor_root_lines(block, line_no)
        monitor_url_lines = [
            (monitor_line_no, clean_url(match.group(0)))
            for monitor_line_no, decision in monitor_decisions
            if not is_obsolete_reference_only_monitor_decision(decision)
            for match in URL_RE.finditer(decision)
        ]
        monitor_urls = [url for _, url in monitor_url_lines]
        canonical_exact_root, canonical_errors = canonical_exact_root_metadata_errors(
            root,
            block,
            monitor_urls,
        )
        if canonical_errors:
            metadata_line = monitor_decisions[0][0] if monitor_decisions else line_no
            for error in canonical_errors:
                issues.append(Issue("error", rel, metadata_line, error))

        relation_values = metadata_field_values(block, "Monitor host relation")
        approval_values = metadata_field_values(block, "Approval reference")
        if monitor_urls:
            if not relation_values or not relation_values[0] or placeholder_cell(relation_values[0]):
                issues.append(Issue("error", rel, monitor_url_lines[0][0], "Monitor root requires Monitor host relation"))
                relation = None
            elif len(relation_values) > 1:
                issues.append(Issue("error", rel, monitor_url_lines[0][0], "Monitor host relation must appear exactly once per source entry"))
                relation = None
            else:
                relation = relation_values[0]
                if relation not in MONITOR_HOST_RELATIONS:
                    issues.append(
                        Issue(
                            "error",
                            rel,
                            monitor_url_lines[0][0],
                            "Monitor host relation must be one of: "
                            + ", ".join(sorted(MONITOR_HOST_RELATIONS)),
                        )
                    )
                    relation = None

            cross_host_urls = [
                monitor_url
                for monitor_url in monitor_urls
                if evidence_urls
                and not any(host_matches_evidence_host(monitor_url, source_url) for source_url in evidence_urls)
            ]
            if relation == "evidence_host":
                if approval_values:
                    issues.append(
                        Issue(
                            "error",
                            rel,
                            monitor_url_lines[0][0],
                            "Approval reference is forbidden when Monitor host relation is evidence_host",
                        )
                    )
                if not evidence_urls:
                    issues.append(
                        Issue(
                            "error",
                            rel,
                            monitor_url_lines[0][0],
                            "evidence_host Monitor root requires at least one explicit entry evidence URL",
                        )
                    )
                elif cross_host_urls:
                    issues.append(
                        Issue(
                            "error",
                            rel,
                            monitor_url_lines[0][0],
                            "evidence_host Monitor root must match an entry evidence host",
                        )
                    )
            elif relation == "approved_cross_host":
                if not evidence_urls or not cross_host_urls:
                    issues.append(
                        Issue(
                            "error",
                            rel,
                            monitor_url_lines[0][0],
                            "approved_cross_host requires at least one Monitor root outside the entry evidence hosts",
                        )
                    )
                if not approval_values or not approval_values[0] or placeholder_cell(approval_values[0]):
                    issues.append(
                        Issue(
                            "error",
                            rel,
                            monitor_url_lines[0][0],
                            "approved_cross_host requires Approval reference",
                        )
                    )
                elif len(approval_values) > 1:
                    issues.append(
                        Issue(
                            "error",
                            rel,
                            monitor_url_lines[0][0],
                            "Approval reference must appear exactly once per source entry",
                        )
                    )
                else:
                    approval_issue = repository_record_reference_error(
                        root,
                        approval_values[0],
                        label="Approval reference",
                        require_anchor=True,
                        require_active_authority_record=True,
                        forbidden_path=path,
                    )
                    if approval_issue:
                        issues.append(Issue("error", rel, monitor_url_lines[0][0], approval_issue))
        elif relation_values or approval_values:
            issues.append(
                Issue(
                    "error",
                    rel,
                    line_no,
                    "Monitor host relation and Approval reference require a Monitor root with an https URL",
                )
            )
        for monitor_line_no, decision in monitor_decisions:
            if is_obsolete_reference_only_monitor_decision(decision):
                issues.append(
                    Issue(
                        "warning",
                        rel,
                        monitor_line_no,
                        "omit Monitor root for reference-only entries instead of using a synthetic placeholder",
                    )
                )
                continue
            monitor_urls = [clean_url(match.group(0)) for match in URL_RE.finditer(decision)]
            if not monitor_urls:
                issues.append(
                    Issue(
                        "warning",
                        rel,
                        monitor_line_no,
                        "Monitor root must include an https URL; omit the line for reference-only entries",
                    )
                )
                continue
            for monitor_url in monitor_urls:
                if is_pathless_host_root(monitor_url):
                    issues.append(
                        Issue(
                            "error",
                            rel,
                            monitor_line_no,
                            "Monitor root must use the smallest durable parent surface, not a whole-domain URL",
                        )
                    )
                    continue
                if not is_recurring_monitor_root(monitor_url):
                    if canonical_exact_root:
                        continue
                    issues.append(
                        Issue(
                            "error",
                            rel,
                            monitor_line_no,
                            "Monitor root must be a durable discovery root, not an exact/static source URL",
                        )
                    )
    return issues


def collect_issues(
    root: Path,
    today: date,
    max_age_days: int,
    include_non_reference_docs: bool,
    reference_dirs: tuple[Path, ...] = REFERENCE_DIRS,
    audit_monitor_roots: bool = False,
    resolve_hostnames: bool = False,
    hostname_resolution_timeout_seconds: float = (
        DEFAULT_HOSTNAME_RESOLUTION_TIMEOUT_SECONDS
    ),
    limits: FreshnessLimits = DEFAULT_FRESHNESS_LIMITS,
    deadline: FreshnessDeadline | None = None,
) -> list[Issue]:
    if not isinstance(limits, FreshnessLimits):
        raise TypeError("limits must be a FreshnessLimits instance")
    work_budget = FreshnessWorkBudget(limits, deadline=deadline)
    resolution_timeout = DEFAULT_HOSTNAME_RESOLUTION_TIMEOUT_SECONDS
    resolution_cache: HostnameResolutionCache | None = None
    if resolve_hostnames:
        resolution_timeout = validated_hostname_resolution_timeout_seconds(
            hostname_resolution_timeout_seconds
        )
        resolution_cache = work_budget.hostname_resolution_cache
    all_snapshots = source_registry_files.registry_markdown_snapshots(
        root,
        reference_dirs,
        project_files=(PROJECT_SOURCE_PACKS, PROJECT_SOURCE_UPDATE),
        limits=limits.registry_file_limits,
        progress_check=lambda: work_budget.check(phase="Markdown input inventory"),
        documentation_files=(
            PRODUCT_ROOT_MARKDOWN_FILES if include_non_reference_docs else ()
        ),
        documentation_directories=(
            PRODUCT_DOCUMENTATION_ROOTS if include_non_reference_docs else ()
        ),
        documentation_max_depth=PRODUCT_DOCUMENTATION_MAX_DEPTH,
        documentation_progress_check=lambda: work_budget.check(
            phase="public documentation inventory"
        ),
    )
    snapshots = {
        snapshot.path: snapshot
        for snapshot in all_snapshots
    }
    reference_roots = tuple(root / relative for relative in reference_dirs)
    reference_paths = {
        snapshot.path
        for snapshot in all_snapshots
        if any(
            snapshot.path == reference_root
            or snapshot.path.is_relative_to(reference_root)
            for reference_root in reference_roots
        )
    }
    source_update_paths = {
        snapshot.path
        for snapshot in all_snapshots
        if snapshot.path == root / PROJECT_SOURCE_UPDATE
    }

    issues: list[Issue] = []
    for path in sorted(snapshots):
        work_budget.check(phase="freshness issue collection")
        text = snapshots[path].text
        reference_file = path in reference_paths
        if path == root / PROJECT_SOURCE_PACKS:
            issues.extend(source_pack_metadata_issues(root, path, today, max_age_days, text))
            if audit_monitor_roots:
                issues.extend(monitor_root_issues(root, path, text))
        if path in source_update_paths:
            issues.extend(
                source_update_state_issues(
                    root,
                    path,
                    today,
                    max_age_days,
                    resolve_hostnames,
                    text,
                    hostname_resolution_timeout_seconds=resolution_timeout,
                    hostname_resolution_cache=resolution_cache,
                    work_budget=work_budget,
                )
            )
        if reference_file:
            issues.extend(reference_review_issues(root, path, today, max_age_days, text))
            issues.extend(reference_tier_issues(root, path, text))
            if audit_monitor_roots:
                issues.extend(monitor_root_issues(root, path, text))
        issues.extend(
            source_claim_issues(
                root,
                path,
                reference_file,
                resolve_hostnames,
                text,
                hostname_resolution_timeout_seconds=resolution_timeout,
                hostname_resolution_cache=resolution_cache,
                work_budget=work_budget,
            )
        )
    work_budget.check(phase="freshness completion")
    return sorted(issues, key=lambda item: (item.severity != "error", item.path, item.line, item.message))


def print_text(issues: list[Issue], warnings_as_errors: bool) -> None:
    errors = [item for item in issues if item.severity == "error"]
    warnings = [item for item in issues if item.severity == "warning"]
    if errors or (warnings_as_errors and warnings):
        print("FAIL")
    else:
        print("PASS")
    for item in errors + warnings:
        print(f"- {item.severity.upper()} {item.path}:{item.line}: {item.message}")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.max_age_days < 0:
        print("FAIL")
        print("- --max-age-days must be zero or greater")
        return 1
    try:
        today = parse_today(args.today)
    except ValueError:
        print("FAIL")
        print("- --today must be YYYY-MM-DD")
        return 1
    reference_dirs = tuple(args.reference_dir) if args.reference_dir else REFERENCE_DIRS
    try:
        root = args.root.resolve()
        issues = collect_issues(
            root,
            today,
            args.max_age_days,
            args.include_non_reference_docs,
            reference_dirs=reference_dirs,
            audit_monitor_roots=args.audit_monitor_roots,
            resolve_hostnames=args.resolve_hostnames,
            hostname_resolution_timeout_seconds=(
                args.hostname_resolution_timeout_seconds
            ),
            limits=FreshnessLimits(
                max_source_files=args.max_source_files,
                max_source_bytes=args.max_source_bytes,
                max_unique_hosts=args.max_unique_hosts,
                max_hostname_resolution_requests=(
                    args.max_hostname_resolution_requests
                ),
                max_hostname_resolution_cache_entries=(
                    args.max_hostname_resolution_cache_entries
                ),
                run_deadline_seconds=args.run_deadline,
            ),
        )
    except safe_paths.OutputDirectoryBindingError as exc:
        issues = [
            Issue(
                "error",
                "<source-input>",
                1,
                _bounded_source_input_diagnostic(
                    "source path binding rejected",
                    exc,
                ),
            )
        ]
    except (OSError, UnicodeError, ValueError) as exc:
        issues = [
            Issue(
                "error",
                "<source-input>",
                1,
                _bounded_source_input_diagnostic("source input rejected", exc),
            )
        ]
    errors = [item for item in issues if item.severity == "error"]
    warnings = [item for item in issues if item.severity == "warning"]
    if args.format == "json":
        print(
            json.dumps(
                {
                    "errors": [item.as_dict() for item in errors],
                    "warnings": [item.as_dict() for item in warnings],
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print_text(issues, args.warnings_as_errors)
    return 1 if errors or (args.warnings_as_errors and warnings) else 0


if __name__ == "__main__":
    sys.exit(main())
