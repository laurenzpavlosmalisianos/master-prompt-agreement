#!/usr/bin/env python3

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
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


class DeepResearchReport(TypedDict):
    path: str
    errors: list[str]


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


def safe_repo_locator(locator: str, *, repo_root: Path | None = None) -> bool:
    path = repo_locator_path(locator)
    if path is None:
        return False
    root = REPO_ROOT if repo_root is None else repo_root
    try:
        candidate = safe_paths.safe_relative_child(
            root,
            Path(*path.parts),
            description="local evidence successor",
        )
        safe_paths.read_regular_file_bytes(
            candidate,
            description="local evidence successor",
        )
        returncode, _stdout, _stderr = _bounded_git(
            ["ls-files", "--error-unmatch", "--", path.as_posix()],
            max_output_bytes=64 * 1024,
            cwd=root,
        )
    except (FileNotFoundError, OSError, RuntimeError, ValueError):
        return False
    return returncode == 0


def _bounded_git(
    args: list[str],
    *,
    max_output_bytes: int,
    cwd: Path | None = None,
) -> tuple[int, bytes, bytes]:
    if max_output_bytes <= 0 or max_output_bytes > GIT_COMMAND_MAX_OUTPUT_BYTES:
        raise ValueError("Git output bound is outside the maintained range")
    if os.name != "posix":
        raise RuntimeError("bounded Git inspection requires POSIX process-group pipes")
    try:
        result = bounded_subprocess.run_bounded_process(
            git_query.closed_git_query_command(args),
            cwd=REPO_ROOT if cwd is None else cwd,
            env=git_query.closed_git_query_environment(
                REPO_ROOT if cwd is None else cwd
            ),
            timeout_seconds=GIT_COMMAND_TIMEOUT_SECONDS,
            max_output_bytes=max_output_bytes,
            maximum_timeout_seconds=GIT_COMMAND_TIMEOUT_SECONDS,
            maximum_output_bytes=GIT_COMMAND_MAX_OUTPUT_BYTES,
            termination_grace_seconds=GIT_TERMINATION_GRACE_SECONDS,
        )
    except bounded_subprocess.BoundedSubprocessStartError as exc:
        detail = exc.__cause__ if isinstance(exc.__cause__, OSError) else exc
        raise RuntimeError(f"Git inspection could not start: {detail}") from exc
    if result.timed_out:
        raise RuntimeError(
            f"Git inspection timed out after {GIT_COMMAND_TIMEOUT_SECONDS:g}s"
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
) -> list[str]:
    root = REPO_ROOT if repo_root is None else repo_root
    path = repo_locator_path(locator)
    if path is None:
        return ["locator must use a safe repo: path for local evidence"]
    if not isinstance(revision, str) or re.fullmatch(r"[0-9a-f]{40}", revision) is None:
        return ["revision must be one full lowercase Git commit ID"]
    if not isinstance(content_sha256, str) or re.fullmatch(r"[0-9a-f]{64}", content_sha256) is None:
        return ["content_sha256 must be one lowercase SHA-256 digest"]
    spec = f"{revision}:{path.as_posix()}"
    try:
        size_returncode, size_stdout, _size_stderr = _bounded_git(
            ["cat-file", "-s", spec],
            max_output_bytes=64 * 1024,
            cwd=root,
        )
    except (RuntimeError, ValueError) as exc:
        return [f"revision-bound Git size inspection failed: {exc}"]
    try:
        size_text = size_stdout.decode("ascii").strip()
    except UnicodeDecodeError:
        size_text = ""
    if size_returncode != 0 or not size_text.isdecimal():
        return ["revision/path does not resolve to a retained Git blob"]
    blob_size = int(size_text)
    if blob_size > safe_paths.DEFAULT_JSON_INPUT_MAX_BYTES:
        return [
            "revision-bound Git blob exceeds the maintained evidence byte limit "
            f"({blob_size} > {safe_paths.DEFAULT_JSON_INPUT_MAX_BYTES})"
        ]
    try:
        returncode, stdout, _stderr = _bounded_git(
            ["cat-file", "blob", spec],
            max_output_bytes=max(blob_size + 64 * 1024, 64 * 1024),
            cwd=root,
        )
    except (RuntimeError, ValueError) as exc:
        return [f"revision-bound Git blob inspection failed: {exc}"]
    if returncode != 0:
        return ["revision/path does not resolve to a retained Git blob"]
    if len(stdout) != blob_size:
        return ["revision-bound Git blob size changed during inspection"]
    actual = hashlib.sha256(stdout).hexdigest()
    if actual != content_sha256:
        return [f"content_sha256 must match the revision-bound Git blob ({actual})"]
    return []


def validate_evidence(
    evidence: object,
    *,
    record_index: int,
    required_role: str,
    repo_root: Path,
    errors: list[str],
) -> None:
    label = f"verification record {record_index} evidence"
    if not isinstance(evidence, list) or not evidence:
        errors.append(f"{label} must be a non-empty array")
        return
    has_required_locator = False
    for evidence_index, item in enumerate(evidence, start=1):
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
        if role not in {"primary", "local"}:
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
                )
                for error in historical_errors:
                    errors.append(f"{item_label}.{error}")
                successor = item.get("current_successor")
                if successor is not None and (
                    not isinstance(successor, str)
                    or not safe_repo_locator(successor, repo_root=repo_root)
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
) -> None:
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
    seen_ids: set[str] = set()
    for index, record in enumerate(records, start=1):
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
        if verifier_role not in VERIFIER_ROLES:
            errors.append(
                f"{label}.verifier_role must be one of: "
                f"{', '.join(sorted(VERIFIER_ROLES))}"
            )
        parse_iso_date(record.get("verified_at"), label=f"{label}.verified_at", errors=errors)
        claim_class = record.get("claim_class")
        if claim_class not in CLAIM_CLASS_RULES:
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
        validate_evidence(
            record.get("evidence"),
            record_index=index,
            required_role=required_role,
            repo_root=repo_root,
            errors=errors,
        )


def validate_digest(
    path: Path,
    *,
    project_root: Path | None = None,
) -> DeepResearchReport:
    errors: list[str] = []
    evidence_root = REPO_ROOT if project_root is None else project_root.resolve()
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
    )
    return {"path": str(path), "errors": errors}


def main() -> int:
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
        "artifact",
        nargs="+",
        type=Path,
        help="One or more browser Deep Research digest artifacts to lint.",
    )
    args = parser.parse_args()

    reports = [
        validate_digest(path, project_root=args.project_root)
        for path in args.artifact
    ]
    print(json.dumps({"artifacts": reports}, indent=2, sort_keys=True))
    return 1 if any(report["errors"] for report in reports) else 0


if __name__ == "__main__":
    raise SystemExit(main())
