#!/usr/bin/env python3

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import time
from typing import Any, TypedDict

import bounded_subprocess
import git_query
import markdown_structure
import safe_paths
import url_safety


SCHEMA_VERSION = "4"
ARTIFACT_KIND = "browser_deep_research_digest"
REPO_ROOT = Path(__file__).resolve().parent.parent
REQUIRED_HEADER_FIELDS = {
    "schema_version",
    "artifact_kind",
    "provider",
    "browser_url",
    "started_at",
    "completed_at",
    "completion_status",
    "completion_evidence",
    "extraction_kind",
    "extraction_method",
    "stale_input_disposition",
}
COMPLETION_STATUSES = {"completed"}
EXTRACTION_KINDS = {"copy", "export", "snapshot"}
STALE_INPUT_DISPOSITIONS = {"none", "rejected", "retried"}
REQUIRED_SECTIONS = {
    "Prompt Digest",
    "Verification Records",
    "Rejected or Deferred",
}
RECORD_FIELDS = {
    "id",
    "candidate_abstraction",
    "claim_class",
    "verification_status",
    "verified_at",
    "verifier",
    "verifier_role",
    "method",
    "evidence",
    "framework_effect",
    "source_specific_material_rejected",
}
EVIDENCE_BASE_FIELDS = {
    "locator",
    "source_role",
    "checked_at",
    "identity",
    "supports",
    "evidence_limit",
}
LOCAL_EVIDENCE_FIELDS = {"revision", "content_sha256", "current_successor"}
EVIDENCE_FIELDS = EVIDENCE_BASE_FIELDS | LOCAL_EVIDENCE_FIELDS
CLAIM_CLASS_RULES = {
    "external_source": (
        "primary_source_verified",
        "direct_primary_source_inspection",
        "primary",
    ),
    "local_process": ("local_evidence_verified", "repository_inspection", "local"),
}
VERIFIER_ROLES = {"coordinator", "deterministic_verifier", "independent_reviewer"}
HEADER_RE = re.compile(r"^([a-z][a-z0-9_]*):\s*(.*)$")
RECORD_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
JSON_FENCE_RE = re.compile(r"^```json\s*\n(?P<payload>.*)\n```\s*$", re.DOTALL)
RFC3339_INSTANT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?"
    r"(?:[Zz]|[+-]\d{2}:\d{2})$"
)
TIMESTAMP_NOT_RECORDED = "not_recorded"
GIT_COMMAND_TIMEOUT_SECONDS = 10.0
GIT_COMMAND_MAX_OUTPUT_BYTES = safe_paths.DEFAULT_JSON_INPUT_MAX_BYTES + 64 * 1024
GIT_TERMINATION_GRACE_SECONDS = 0.1
DEFAULT_MAX_RECORDS = 256
MAX_RECORDS = 4_096
DEFAULT_MAX_EVIDENCE_ITEMS = 2_048
MAX_EVIDENCE_ITEMS = 32_768
DEFAULT_MAX_GIT_QUERIES = 4_096
MAX_GIT_QUERIES = 65_536
DEFAULT_RUN_DEADLINE_SECONDS = 120.0
MAX_RUN_DEADLINE_SECONDS = 3_600.0


class DeepResearchReport(TypedDict):
    path: str
    errors: list[str]


class DeepResearchLimitError(RuntimeError):
    """A stable aggregate-work failure raised before a limit is exceeded."""

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
            f"{label} limit exceeded "
            f"(limit={limit:g}, observed_at_least={observed:g}, phase={phase})"
        )


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
class DeepResearchLimits:
    """Conservative whole-run limits shared by CLI and Python callers."""

    max_records: int = DEFAULT_MAX_RECORDS
    max_evidence_items: int = DEFAULT_MAX_EVIDENCE_ITEMS
    max_git_queries: int = DEFAULT_MAX_GIT_QUERIES
    run_deadline_seconds: float = DEFAULT_RUN_DEADLINE_SECONDS

    def __post_init__(self) -> None:
        _validate_positive_int(
            self.max_records,
            label="max_records",
            maximum=MAX_RECORDS,
        )
        _validate_positive_int(
            self.max_evidence_items,
            label="max_evidence_items",
            maximum=MAX_EVIDENCE_ITEMS,
        )
        _validate_positive_int(
            self.max_git_queries,
            label="max_git_queries",
            maximum=MAX_GIT_QUERIES,
        )
        _validate_positive_float(
            self.run_deadline_seconds,
            label="run_deadline_seconds",
            maximum=MAX_RUN_DEADLINE_SECONDS,
        )


DEFAULT_DEEP_RESEARCH_LIMITS = DeepResearchLimits()


class DeepResearchDeadline:
    """One monotonic deadline shared by parsing and every child query."""

    def __init__(
        self,
        seconds: float,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        _validate_positive_float(
            seconds,
            label="deadline seconds",
            maximum=MAX_RUN_DEADLINE_SECONDS,
        )
        self.seconds = float(seconds)
        self._clock = time.monotonic if clock is None else clock
        self._started_at = self._clock()
        self._expires_at = self._started_at + self.seconds

    def remaining(self, *, phase: str) -> float:
        now = self._clock()
        remaining = self._expires_at - now
        if remaining <= 0:
            raise DeepResearchLimitError(
                "run_deadline_exceeded",
                "whole-run monotonic deadline",
                self.seconds,
                max(self.seconds, now - self._started_at),
                phase=phase,
            )
        return remaining


class DeepResearchBudget:
    """Aggregate admission control for records, evidence, and Git queries."""

    def __init__(
        self,
        limits: DeepResearchLimits = DEFAULT_DEEP_RESEARCH_LIMITS,
        *,
        deadline: DeepResearchDeadline | None = None,
    ) -> None:
        if not isinstance(limits, DeepResearchLimits):
            raise TypeError("limits must be a DeepResearchLimits instance")
        if deadline is not None and not isinstance(deadline, DeepResearchDeadline):
            raise TypeError("deadline must be a DeepResearchDeadline")
        if deadline is not None and deadline.seconds > limits.run_deadline_seconds:
            raise ValueError("deadline must not exceed the selected run deadline limit")
        self.limits = limits
        self.deadline = (
            DeepResearchDeadline(limits.run_deadline_seconds)
            if deadline is None
            else deadline
        )
        self.records_used = 0
        self.evidence_items_used = 0
        self.git_queries_used = 0
        self._historical_cache: dict[
            tuple[str, str, str, str],
            tuple[str, ...],
        ] = {}
        self._terminal_error: DeepResearchLimitError | None = None

    def _raise_or_record(self, error: DeepResearchLimitError) -> None:
        if self._terminal_error is None:
            self._terminal_error = error
        raise self._terminal_error

    def remaining(self, *, phase: str) -> float:
        if self._terminal_error is not None:
            raise self._terminal_error
        try:
            return self.deadline.remaining(phase=phase)
        except DeepResearchLimitError as exc:
            self._raise_or_record(exc)
        raise AssertionError("unreachable")

    def check_deadline(self, *, phase: str) -> None:
        self.remaining(phase=phase)

    def _consume(
        self,
        count: int,
        *,
        attribute: str,
        limit: int,
        code: str,
        label: str,
        phase: str,
    ) -> None:
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError("budget consumption count must be a non-negative integer")
        self.check_deadline(phase=phase)
        used = getattr(self, attribute)
        observed = used + count
        if observed > limit:
            self._raise_or_record(
                DeepResearchLimitError(
                    code,
                    label,
                    limit,
                    observed,
                    phase=phase,
                )
            )
        setattr(self, attribute, observed)

    def consume_records(self, count: int, *, phase: str) -> None:
        self._consume(
            count,
            attribute="records_used",
            limit=self.limits.max_records,
            code="record_limit_exceeded",
            label="verification record count",
            phase=phase,
        )

    def consume_evidence_items(self, count: int, *, phase: str) -> None:
        self._consume(
            count,
            attribute="evidence_items_used",
            limit=self.limits.max_evidence_items,
            code="evidence_item_limit_exceeded",
            label="verification evidence item count",
            phase=phase,
        )

    def admit_git_query(self, *, phase: str) -> float:
        self._consume(
            1,
            attribute="git_queries_used",
            limit=self.limits.max_git_queries,
            code="git_query_limit_exceeded",
            label="Git query count",
            phase=phase,
        )
        return min(GIT_COMMAND_TIMEOUT_SECONDS, self.remaining(phase=phase))

    def historical_cache_get(
        self,
        key: tuple[str, str, str, str],
    ) -> list[str] | None:
        cached = self._historical_cache.get(key)
        return None if cached is None else list(cached)

    def historical_cache_put(
        self,
        key: tuple[str, str, str, str],
        errors: list[str],
    ) -> None:
        self._historical_cache[key] = tuple(errors)


def _select_budget(
    *,
    limits: DeepResearchLimits | None,
    budget: DeepResearchBudget | None,
) -> DeepResearchBudget:
    if limits is not None and not isinstance(limits, DeepResearchLimits):
        raise TypeError("limits must be a DeepResearchLimits instance")
    if budget is not None and not isinstance(budget, DeepResearchBudget):
        raise TypeError("budget must be a DeepResearchBudget")
    selected_limits = (
        budget.limits
        if limits is None and budget is not None
        else DEFAULT_DEEP_RESEARCH_LIMITS if limits is None else limits
    )
    if budget is not None:
        if budget.limits != selected_limits:
            raise ValueError("budget limits must match the selected limits")
        return budget
    return DeepResearchBudget(selected_limits)


def parse_header(lines: list[str], errors: list[str]) -> dict[str, str]:
    header: dict[str, str] = {}
    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            break
        match = HEADER_RE.match(stripped)
        if not match:
            errors.append(f"invalid header line {line_number}: {line}")
            continue
        key, value = match.groups()
        if key in header:
            errors.append(f"duplicate header field: {key}")
        header[key] = value.strip()
    return header


def markdown_h2_sections(text: str) -> tuple[list[str], dict[str, list[str]]]:
    parsed_sections = markdown_structure.markdown_sections(text)
    verification_sections = iter(
        section
        for section in markdown_structure.markdown_sections(
            text,
            include_fenced_content=True,
        )
        if section.title == "Verification Records"
    )
    headings = [section.title for section in parsed_sections]
    sections: dict[str, list[str]] = {}
    for section in parsed_sections:
        body = (
            next(verification_sections).lines
            if section.title == "Verification Records"
            else section.lines
        )
        sections.setdefault(section.title, []).extend(
            line for _line_number, line in body
        )
    return headings, sections


def parse_report_instant(
    value: str,
    *,
    label: str,
    errors: list[str],
) -> datetime | None:
    if value == TIMESTAMP_NOT_RECORDED:
        return None
    if RFC3339_INSTANT_RE.fullmatch(value) is None:
        errors.append(
            f"{label} must be {TIMESTAMP_NOT_RECORDED} or an RFC 3339 "
            "instant with an explicit Z or ±HH:MM offset"
        )
        return None
    normalized = value[:-1] + "+00:00" if value[-1].casefold() == "z" else value
    try:
        instant = datetime.fromisoformat(normalized)
    except ValueError:
        errors.append(f"{label} must be a valid RFC 3339 instant")
        return None
    if instant.utcoffset() is None:
        errors.append(
            f"{label} must be {TIMESTAMP_NOT_RECORDED} or an RFC 3339 "
            "instant with an explicit Z or ±HH:MM offset"
        )
        return None
    return instant.astimezone(timezone.utc)


def parse_iso_date(value: object, *, label: str, errors: list[str]) -> None:
    if not isinstance(value, str):
        errors.append(f"{label} must be an ISO date")
        return
    try:
        date.fromisoformat(value)
    except ValueError:
        errors.append(f"{label} must be an ISO date")


def validate_nonempty_string(value: object, *, label: str, errors: list[str]) -> bool:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{label} must be a non-empty string")
        return False
    return True


def repo_locator_path(locator: str) -> PurePosixPath | None:
    if not locator.startswith("repo:"):
        return None
    relative = locator.removeprefix("repo:").split("#", 1)[0]
    path = PurePosixPath(relative)
    if (
        not relative
        or safe_paths.PATH_CONTROL_RE.search(relative)
        or "\\" in relative
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in relative.split("/"))
    ):
        return None
    return path


def _read_bound_successor(
    descriptor: int,
    *,
    description: str,
) -> tuple[bytes, tuple[int, ...]]:
    before = os.fstat(descriptor)
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise ValueError(f"{description} must be a single-link regular file")
    if before.st_size > safe_paths.DEFAULT_JSON_INPUT_MAX_BYTES:
        raise ValueError(
            f"{description} exceeds the "
            f"{safe_paths.DEFAULT_JSON_INPUT_MAX_BYTES}-byte input limit"
        )
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    remaining = safe_paths.DEFAULT_JSON_INPUT_MAX_BYTES + 1
    while remaining:
        chunk = os.read(descriptor, min(1024 * 1024, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    raw = b"".join(chunks)
    after = os.fstat(descriptor)
    signature = safe_paths.stable_file_metadata(before)
    if (
        len(raw) > safe_paths.DEFAULT_JSON_INPUT_MAX_BYTES
        or len(raw) != after.st_size
        or signature != safe_paths.stable_file_metadata(after)
    ):
        raise ValueError(f"{description} changed while it was read")
    return raw, signature


def _require_bound_successor_current(
    parent: safe_paths.OutputDirectoryBinding,
    name: str,
    descriptor: int,
    *,
    expected_raw: bytes,
    expected_signature: tuple[int, ...],
) -> None:
    description = "local evidence successor"
    parent.require_lexical_binding(description=f"{description} parent")
    named = os.stat(name, dir_fd=parent.descriptor, follow_symlinks=False)
    current = os.fstat(descriptor)
    if (
        not stat.S_ISREG(named.st_mode)
        or not stat.S_ISREG(current.st_mode)
        or named.st_nlink != 1
        or current.st_nlink != 1
        or safe_paths.stable_file_metadata(named) != expected_signature
        or safe_paths.stable_file_metadata(current) != expected_signature
    ):
        raise ValueError(f"{description} pathname no longer identifies its bound file")
    current_raw, current_signature = _read_bound_successor(
        descriptor,
        description=description,
    )
    if current_signature != expected_signature or current_raw != expected_raw:
        raise ValueError(f"{description} changed after its Git query")


def safe_repo_locator(
    locator: str,
    *,
    repo_root: Path | None = None,
    budget: DeepResearchBudget | None = None,
) -> bool:
    selected_budget = _select_budget(limits=None, budget=budget)
    path = repo_locator_path(locator)
    if path is None:
        return False
    root = REPO_ROOT if repo_root is None else repo_root
    if not isinstance(root, Path):
        raise TypeError("repo_root must be a pathlib.Path")
    try:
        candidate = safe_paths.safe_relative_child(
            root,
            Path(*path.parts),
            description="local evidence successor",
        )
        with safe_paths.open_output_directory(
            candidate.parent,
            create_missing=False,
        ) as parent:
            nofollow = getattr(os, "O_NOFOLLOW", 0)
            nonblock = getattr(os, "O_NONBLOCK", 0)
            if not nofollow or not nonblock:
                raise RuntimeError(
                    "local evidence successor binding requires O_NOFOLLOW and O_NONBLOCK"
                )
            parent.require_lexical_binding(
                description="local evidence successor parent"
            )
            descriptor = os.open(
                candidate.name,
                os.O_RDONLY
                | nofollow
                | nonblock
                | getattr(os, "O_CLOEXEC", 0),
                dir_fd=parent.descriptor,
            )
            try:
                expected_raw, expected_signature = _read_bound_successor(
                    descriptor,
                    description="local evidence successor",
                )
                _require_bound_successor_current(
                    parent,
                    candidate.name,
                    descriptor,
                    expected_raw=expected_raw,
                    expected_signature=expected_signature,
                )
                literal_pathspec = f":(literal){path.as_posix()}"
                returncode, _stdout, _stderr = _bounded_git(
                    ["ls-files", "--error-unmatch", "--", literal_pathspec],
                    max_output_bytes=64 * 1024,
                    cwd=root,
                    budget=selected_budget,
                )
                _require_bound_successor_current(
                    parent,
                    candidate.name,
                    descriptor,
                    expected_raw=expected_raw,
                    expected_signature=expected_signature,
                )
            finally:
                os.close(descriptor)
    except DeepResearchLimitError:
        raise
    except (FileNotFoundError, OSError, RuntimeError, ValueError):
        return False
    return returncode == 0


def _bounded_git(
    args: list[str],
    *,
    max_output_bytes: int,
    cwd: Path | None = None,
    budget: DeepResearchBudget | None = None,
) -> tuple[int, bytes, bytes]:
    selected_budget = _select_budget(limits=None, budget=budget)
    if max_output_bytes <= 0 or max_output_bytes > GIT_COMMAND_MAX_OUTPUT_BYTES:
        raise ValueError("Git output bound is outside the maintained range")
    if os.name != "posix":
        raise RuntimeError("bounded Git inspection requires POSIX process-group pipes")
    root = REPO_ROOT if cwd is None else cwd
    if not isinstance(root, Path):
        raise TypeError("cwd must be a pathlib.Path")
    query_timeout = selected_budget.admit_git_query(phase="Git inspection")
    try:
        with git_query.bind_git_repository(root) as binding:
            result = bounded_subprocess.run_bounded_process(
                git_query.closed_git_query_command(
                    args,
                    executable=binding.child_git_executable(),
                ),
                cwd=Path(binding.child_worktree()),
                env=git_query.closed_git_query_environment(binding),
                pass_fds=binding.pass_fds,
                timeout_seconds=query_timeout,
                max_output_bytes=max_output_bytes,
                maximum_timeout_seconds=GIT_COMMAND_TIMEOUT_SECONDS,
                maximum_output_bytes=GIT_COMMAND_MAX_OUTPUT_BYTES,
                termination_grace_seconds=GIT_TERMINATION_GRACE_SECONDS,
            )
    except bounded_subprocess.BoundedSubprocessPreconditionError:
        raise
    except bounded_subprocess.BoundedSubprocessStartError as exc:
        detail = exc.__cause__ if isinstance(exc.__cause__, OSError) else exc
        raise RuntimeError(f"Git inspection could not start: {detail}") from exc
    except bounded_subprocess.BoundedSubprocessError as exc:
        raise RuntimeError(f"Git inspection failed: {exc}") from exc
    except (OSError, RuntimeError, ValueError) as exc:
        raise RuntimeError(f"Git repository boundary rejected inspection: {exc}") from exc
    selected_budget.check_deadline(phase="Git inspection completion")
    if result.timed_out:
        raise RuntimeError(
            f"Git inspection timed out after {query_timeout:g}s"
        )
    if result.output_exceeded:
        raise RuntimeError(
            f"Git inspection output exceeded the {max_output_bytes}-byte limit"
        )
    return result.returncode, result.stdout, result.stderr


def historical_repo_evidence_errors(
    locator: str,
    revision: object,
    content_sha256: object,
    *,
    repo_root: Path | None = None,
    budget: DeepResearchBudget | None = None,
) -> list[str]:
    selected_budget = _select_budget(limits=None, budget=budget)
    root = REPO_ROOT if repo_root is None else repo_root
    if not isinstance(root, Path):
        raise TypeError("repo_root must be a pathlib.Path")
    path = repo_locator_path(locator)
    if path is None:
        return ["locator must use a safe repo: path for local evidence"]
    if not isinstance(revision, str) or re.fullmatch(r"[0-9a-f]{40}", revision) is None:
        return ["revision must be one full lowercase Git commit ID"]
    if not isinstance(content_sha256, str) or re.fullmatch(r"[0-9a-f]{64}", content_sha256) is None:
        return ["content_sha256 must be one lowercase SHA-256 digest"]
    cache_key = (
        os.path.abspath(os.fspath(root)),
        path.as_posix(),
        revision,
        content_sha256,
    )
    cached = selected_budget.historical_cache_get(cache_key)
    if cached is not None:
        selected_budget.check_deadline(phase="revision-bound Git cache lookup")
        return cached
    spec = f"{revision}:{path.as_posix()}"
    try:
        size_returncode, size_stdout, _size_stderr = _bounded_git(
            ["cat-file", "-s", spec],
            max_output_bytes=64 * 1024,
            cwd=root,
            budget=selected_budget,
        )
    except DeepResearchLimitError:
        raise
    except (RuntimeError, ValueError) as exc:
        errors = [f"revision-bound Git size inspection failed: {exc}"]
        selected_budget.historical_cache_put(cache_key, errors)
        return errors
    try:
        size_text = size_stdout.decode("ascii").strip()
    except UnicodeDecodeError:
        size_text = ""
    if size_returncode != 0 or not size_text.isdecimal():
        errors = ["revision/path does not resolve to a retained Git blob"]
        selected_budget.historical_cache_put(cache_key, errors)
        return errors
    blob_size = int(size_text)
    if blob_size > safe_paths.DEFAULT_JSON_INPUT_MAX_BYTES:
        errors = [
            "revision-bound Git blob exceeds the maintained evidence byte limit "
            f"({blob_size} > {safe_paths.DEFAULT_JSON_INPUT_MAX_BYTES})"
        ]
        selected_budget.historical_cache_put(cache_key, errors)
        return errors
    try:
        returncode, stdout, _stderr = _bounded_git(
            ["cat-file", "blob", spec],
            max_output_bytes=max(blob_size + 64 * 1024, 64 * 1024),
            cwd=root,
            budget=selected_budget,
        )
    except DeepResearchLimitError:
        raise
    except (RuntimeError, ValueError) as exc:
        errors = [f"revision-bound Git blob inspection failed: {exc}"]
        selected_budget.historical_cache_put(cache_key, errors)
        return errors
    if returncode != 0:
        errors = ["revision/path does not resolve to a retained Git blob"]
        selected_budget.historical_cache_put(cache_key, errors)
        return errors
    if len(stdout) != blob_size:
        errors = ["revision-bound Git blob size changed during inspection"]
        selected_budget.historical_cache_put(cache_key, errors)
        return errors
    actual = hashlib.sha256(stdout).hexdigest()
    if actual != content_sha256:
        errors = [f"content_sha256 must match the revision-bound Git blob ({actual})"]
        selected_budget.historical_cache_put(cache_key, errors)
        return errors
    selected_budget.historical_cache_put(cache_key, [])
    return []


def validate_evidence(
    evidence: object,
    *,
    record_index: int,
    required_role: str,
    repo_root: Path,
    errors: list[str],
    budget: DeepResearchBudget | None = None,
) -> None:
    selected_budget = _select_budget(limits=None, budget=budget)
    label = f"verification record {record_index} evidence"
    if not isinstance(evidence, list) or not evidence:
        errors.append(f"{label} must be a non-empty array")
        return
    selected_budget.consume_evidence_items(len(evidence), phase=label)
    has_required_locator = False
    for evidence_index, item in enumerate(evidence, start=1):
        selected_budget.check_deadline(phase=f"{label} validation")
        item_label = f"{label} {evidence_index}"
        if not isinstance(item, dict):
            errors.append(f"{item_label} must be an object")
            continue
        keys = set(item)
        missing = EVIDENCE_BASE_FIELDS - keys
        unknown = keys - EVIDENCE_FIELDS
        if missing:
            errors.append(f"{item_label} missing fields: {', '.join(sorted(missing))}")
        if unknown:
            errors.append(f"{item_label} has unknown fields: {', '.join(sorted(unknown))}")
        for field in ("locator", "source_role", "identity", "supports", "evidence_limit"):
            validate_nonempty_string(item.get(field), label=f"{item_label}.{field}", errors=errors)
        parse_iso_date(item.get("checked_at"), label=f"{item_label}.checked_at", errors=errors)
        locator = item.get("locator")
        role = item.get("source_role")
        if not isinstance(role, str) or role not in {"primary", "local"}:
            errors.append(f"{item_label}.source_role must be primary or local")
        if isinstance(locator, str):
            if role == "primary":
                blocked = url_safety.blocked_external_url_reason(locator, resolve_hostname=False)
                if blocked is not None:
                    errors.append(f"{item_label}.locator is not a safe primary URL: {blocked}")
                else:
                    has_required_locator = has_required_locator or required_role == "primary"
            elif role == "local":
                local_missing = LOCAL_EVIDENCE_FIELDS - keys
                if local_missing:
                    errors.append(
                        f"{item_label} missing local revision fields: {', '.join(sorted(local_missing))}"
                    )
                historical_errors = historical_repo_evidence_errors(
                    locator,
                    item.get("revision"),
                    item.get("content_sha256"),
                    repo_root=repo_root,
                    budget=selected_budget,
                )
                for error in historical_errors:
                    errors.append(f"{item_label}.{error}")
                successor = item.get("current_successor")
                if successor is not None and (
                    not isinstance(successor, str)
                    or not safe_repo_locator(
                        successor,
                        repo_root=repo_root,
                        budget=selected_budget,
                    )
                ):
                    errors.append(
                        f"{item_label}.current_successor must be null or a safe tracked current repo: path"
                    )
                if not historical_errors:
                    has_required_locator = has_required_locator or required_role == "local"
            if role == "primary" and keys & LOCAL_EVIDENCE_FIELDS:
                errors.append(
                    f"{item_label} primary evidence must not claim local revision fields"
                )
    if not has_required_locator:
        errors.append(f"{label} must include at least one {required_role} locator")


def validate_verification_records(
    body: str,
    errors: list[str],
    *,
    repo_root: Path,
    limits: DeepResearchLimits | None = None,
    budget: DeepResearchBudget | None = None,
) -> None:
    selected_budget = _select_budget(limits=limits, budget=budget)
    if not body:
        errors.append("Verification Records must contain one JSON array fence")
        return
    fence = JSON_FENCE_RE.fullmatch(body)
    if fence is None:
        errors.append("Verification Records must contain only one ```json fenced array")
        return
    try:
        records: Any = safe_paths.loads_json_no_duplicates(fence.group("payload"))
    except (json.JSONDecodeError, ValueError) as exc:
        errors.append(f"Verification Records JSON is invalid: {exc}")
        return
    if not isinstance(records, list):
        errors.append("Verification Records JSON must be an array")
        return
    try:
        selected_budget.consume_records(
            len(records),
            phase="Verification Records",
        )
    except DeepResearchLimitError as exc:
        errors.append(str(exc))
        return
    seen_ids: set[str] = set()
    for index, record in enumerate(records, start=1):
        try:
            selected_budget.check_deadline(phase="verification record validation")
        except DeepResearchLimitError as exc:
            errors.append(str(exc))
            return
        label = f"verification record {index}"
        if not isinstance(record, dict):
            errors.append(f"{label} must be an object")
            continue
        keys = set(record)
        missing = RECORD_FIELDS - keys
        unknown = keys - RECORD_FIELDS
        if missing:
            errors.append(f"{label} missing fields: {', '.join(sorted(missing))}")
        if unknown:
            errors.append(f"{label} has unknown fields: {', '.join(sorted(unknown))}")
        record_id = record.get("id")
        if not isinstance(record_id, str) or RECORD_ID_RE.fullmatch(record_id) is None:
            errors.append(f"{label}.id must be a lowercase hyphenated identifier")
        elif record_id in seen_ids:
            errors.append(f"duplicate verification record id: {record_id}")
        else:
            seen_ids.add(record_id)
        for field in (
            "candidate_abstraction",
            "verification_status",
            "verifier",
            "method",
            "framework_effect",
        ):
            validate_nonempty_string(
                record.get(field),
                label=f"{label}.{field}",
                errors=errors,
            )
        verifier_role = record.get("verifier_role")
        if not isinstance(verifier_role, str) or verifier_role not in VERIFIER_ROLES:
            errors.append(
                f"{label}.verifier_role must be one of: "
                f"{', '.join(sorted(VERIFIER_ROLES))}"
            )
        parse_iso_date(record.get("verified_at"), label=f"{label}.verified_at", errors=errors)
        claim_class = record.get("claim_class")
        if not isinstance(claim_class, str) or claim_class not in CLAIM_CLASS_RULES:
            errors.append(f"{label}.claim_class must be external_source or local_process")
            continue
        required_status, required_method, required_role = CLAIM_CLASS_RULES[claim_class]
        if record.get("verification_status") != required_status:
            errors.append(f"{label}.verification_status must be {required_status} for {claim_class}")
        if record.get("method") != required_method:
            errors.append(f"{label}.method must be {required_method} for {claim_class}")
        rejected = record.get("source_specific_material_rejected")
        if (
            not isinstance(rejected, list)
            or not rejected
            or not all(isinstance(item, str) and item.strip() for item in rejected)
        ):
            errors.append(
                f"{label}.source_specific_material_rejected must be a non-empty string array"
            )
        try:
            validate_evidence(
                record.get("evidence"),
                record_index=index,
                required_role=required_role,
                repo_root=repo_root,
                errors=errors,
                budget=selected_budget,
            )
        except DeepResearchLimitError as exc:
            errors.append(str(exc))
            return


def validate_digest(
    path: Path,
    *,
    project_root: Path | None = None,
    limits: DeepResearchLimits | None = None,
    budget: DeepResearchBudget | None = None,
) -> DeepResearchReport:
    if not isinstance(path, Path):
        raise TypeError("path must be a pathlib.Path")
    if project_root is not None and not isinstance(project_root, Path):
        raise TypeError("project_root must be a pathlib.Path or None")
    selected_budget = _select_budget(limits=limits, budget=budget)
    errors: list[str] = []
    evidence_root = REPO_ROOT if project_root is None else project_root.resolve()
    try:
        selected_budget.check_deadline(phase="artifact input")
    except DeepResearchLimitError as exc:
        return {"path": str(path), "errors": [str(exc)]}
    try:
        raw = safe_paths.read_regular_file_bytes(
            path,
            description="Deep Research digest artifact",
        )
    except FileNotFoundError:
        return {"path": str(path), "errors": [f"missing artifact: {path}"]}
    except (OSError, ValueError) as exc:
        return {"path": str(path), "errors": [f"artifact input rejected: {exc}"]}
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        return {"path": str(path), "errors": [f"artifact must be valid UTF-8: {exc}"]}
    try:
        selected_budget.check_deadline(phase="artifact parsing")
    except DeepResearchLimitError as exc:
        return {"path": str(path), "errors": [str(exc)]}
    lines = text.splitlines()
    header = parse_header(lines, errors)
    unknown_header_fields = set(header) - REQUIRED_HEADER_FIELDS
    if unknown_header_fields:
        errors.append(f"unknown header fields: {', '.join(sorted(unknown_header_fields))}")
    for field in sorted(REQUIRED_HEADER_FIELDS):
        if not header.get(field):
            errors.append(f"missing header field: {field}")
    if header.get("schema_version") and header["schema_version"] != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    if header.get("artifact_kind") and header["artifact_kind"] != ARTIFACT_KIND:
        errors.append(f"artifact_kind must be {ARTIFACT_KIND}")
    completion_status = header.get("completion_status")
    if completion_status and completion_status not in COMPLETION_STATUSES:
        errors.append(
            "completion_status must be one of: "
            f"{', '.join(sorted(COMPLETION_STATUSES))}"
        )
    extraction_kind = header.get("extraction_kind")
    if extraction_kind and extraction_kind not in EXTRACTION_KINDS:
        errors.append(
            f"extraction_kind must be one of: {', '.join(sorted(EXTRACTION_KINDS))}"
        )
    stale_input_disposition = header.get("stale_input_disposition")
    if (
        stale_input_disposition
        and stale_input_disposition not in STALE_INPUT_DISPOSITIONS
    ):
        errors.append(
            "stale_input_disposition must be one of: "
            f"{', '.join(sorted(STALE_INPUT_DISPOSITIONS))}"
        )
    browser_url = header.get("browser_url", "")
    if browser_url:
        blocked = url_safety.blocked_external_url_reason(browser_url, resolve_hostname=False)
        if blocked is not None:
            errors.append(f"unsafe browser_url: {blocked}")
    header_instants = {
        field: parse_report_instant(header[field], label=field, errors=errors)
        for field in ("started_at", "completed_at")
        if header.get(field)
    }
    started_at = header_instants.get("started_at")
    completed_at = header_instants.get("completed_at")
    if started_at is not None and completed_at is not None and completed_at < started_at:
        errors.append("completed_at instant must not be earlier than started_at instant")
    headings, sections = markdown_h2_sections(text)
    for heading in sorted(REQUIRED_SECTIONS):
        if heading not in headings:
            errors.append(f"missing section: {heading}")
        elif headings.count(heading) != 1:
            errors.append(f"duplicate section: {heading}")
    for heading in ("Prompt Digest", "Rejected or Deferred"):
        if headings.count(heading) == 1 and not "\n".join(sections.get(heading, [])).strip():
            errors.append(f"{heading} must not be empty")
    verification_body = "\n".join(sections.get("Verification Records", [])).strip()
    validate_verification_records(
        verification_body,
        errors,
        repo_root=evidence_root,
        limits=selected_budget.limits,
        budget=selected_budget,
    )
    try:
        selected_budget.check_deadline(phase="artifact completion")
    except DeepResearchLimitError as exc:
        if str(exc) not in errors:
            errors.append(str(exc))
    return {"path": str(path), "errors": errors}


def bounded_positive_int(value: str, *, label: str, maximum: int) -> int:
    try:
        parsed = int(value)
        _validate_positive_int(parsed, label=label, maximum=maximum)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    return parsed


def bounded_positive_float(value: str, *, label: str, maximum: float) -> float:
    try:
        parsed = float(value)
        _validate_positive_float(parsed, label=label, maximum=maximum)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Lint browser Deep Research digest artifacts.",
        allow_abbrev=False,
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="Project repository root used to resolve repo: evidence (default: current directory).",
    )
    parser.add_argument(
        "--max-records",
        type=lambda value: bounded_positive_int(
            value,
            label="--max-records",
            maximum=MAX_RECORDS,
        ),
        default=DEFAULT_MAX_RECORDS,
        help=(
            "Maximum verification records across all artifacts "
            f"(default: {DEFAULT_MAX_RECORDS}, maximum: {MAX_RECORDS})."
        ),
    )
    parser.add_argument(
        "--max-evidence-items",
        type=lambda value: bounded_positive_int(
            value,
            label="--max-evidence-items",
            maximum=MAX_EVIDENCE_ITEMS,
        ),
        default=DEFAULT_MAX_EVIDENCE_ITEMS,
        help=(
            "Maximum evidence items across all records and artifacts "
            f"(default: {DEFAULT_MAX_EVIDENCE_ITEMS}, "
            f"maximum: {MAX_EVIDENCE_ITEMS})."
        ),
    )
    parser.add_argument(
        "--max-git-queries",
        type=lambda value: bounded_positive_int(
            value,
            label="--max-git-queries",
            maximum=MAX_GIT_QUERIES,
        ),
        default=DEFAULT_MAX_GIT_QUERIES,
        help=(
            "Maximum actual Git queries across all artifacts "
            f"(default: {DEFAULT_MAX_GIT_QUERIES}, maximum: {MAX_GIT_QUERIES})."
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
            f"(default: {DEFAULT_RUN_DEADLINE_SECONDS:g}, "
            f"maximum: {MAX_RUN_DEADLINE_SECONDS:g})."
        ),
    )
    parser.add_argument(
        "artifact",
        nargs="+",
        type=Path,
        help="One or more browser Deep Research digest artifacts to lint.",
    )
    return parser


def limits_from_args(args: argparse.Namespace) -> DeepResearchLimits:
    return DeepResearchLimits(
        max_records=getattr(args, "max_records", DEFAULT_MAX_RECORDS),
        max_evidence_items=getattr(
            args,
            "max_evidence_items",
            DEFAULT_MAX_EVIDENCE_ITEMS,
        ),
        max_git_queries=getattr(
            args,
            "max_git_queries",
            DEFAULT_MAX_GIT_QUERIES,
        ),
        run_deadline_seconds=getattr(
            args,
            "run_deadline",
            DEFAULT_RUN_DEADLINE_SECONDS,
        ),
    )


def main() -> int:
    args = build_parser().parse_args()
    limits = limits_from_args(args)
    budget = DeepResearchBudget(limits)

    reports = [
        validate_digest(
            path,
            project_root=args.project_root,
            limits=limits,
            budget=budget,
        )
        for path in args.artifact
    ]
    print(json.dumps({"artifacts": reports}, indent=2, sort_keys=True))
    return 1 if any(report["errors"] for report in reports) else 0


if __name__ == "__main__":
    raise SystemExit(main())
