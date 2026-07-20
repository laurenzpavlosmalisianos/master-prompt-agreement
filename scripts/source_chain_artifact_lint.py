#!/usr/bin/env python3

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
from typing import cast
import unicodedata
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import check_reference_freshness
import markdown_structure
import review_packet_contract
import safe_paths
import url_safety


ARTIFACT_SCHEMA_VERSION = "6"
COMMON_REQUIRED_FIELDS = {
    "artifact_schema_version",
    "chain_id",
    "stage",
    "stage_run_id",
    "attempt_id",
    "logical_date",
    "run_slot",
    "monitor_scope",
    "monitor_scope_sha256",
    "model_route",
    "model_label",
    "reasoning_effort",
    "execution_mode",
    "timezone",
    "started_at_utc",
    "completed_at_utc",
    "status",
}
STAGE_REQUIRED_FIELDS = {
    "monitor": COMMON_REQUIRED_FIELDS | {
        "source_status",
        "workspace_status",
        "external_reviewer_status",
        "external_reviewer_packet_scope",
        "inaccessible_source_count",
        "unresolved_inaccessible_source_count",
        "source_root_coverage_count",
        "source_registry_files",
        "policy_files",
    },
    "review": COMMON_REQUIRED_FIELDS | {
        "external_reviewer_status",
        "external_reviewer_packet_scope",
        "input_monitor_state",
        "input_monitor_artifact",
        "input_monitor_stage_run_id",
        "input_monitor_attempt_id",
        "input_monitor_sha256",
        "inaccessible_source_count",
        "unresolved_inaccessible_source_count",
        "accepted_findings",
        "manual_findings",
        "rejected_findings",
    },
    "apply": COMMON_REQUIRED_FIELDS | {
        "external_reviewer_status",
        "external_reviewer_packet_scope",
        "authority_grant",
        "authority_scope",
        "authority_source",
        "input_review_state",
        "input_review_artifact",
        "input_review_stage_run_id",
        "input_review_attempt_id",
        "input_review_sha256",
        "base_commit",
        "changed_files",
        "commit",
        "verification",
    },
    "assurance": COMMON_REQUIRED_FIELDS | {
        "input_monitor_state",
        "input_monitor_artifact",
        "input_monitor_stage_run_id",
        "input_monitor_attempt_id",
        "input_monitor_sha256",
        "input_review_state",
        "input_review_artifact",
        "input_review_stage_run_id",
        "input_review_attempt_id",
        "input_review_sha256",
        "input_apply_state",
        "input_apply_artifact",
        "input_apply_stage_run_id",
        "input_apply_attempt_id",
        "input_apply_sha256",
        "latest_commit",
        "unresolved_findings",
        "unresolved_inaccessible_source_count",
    },
}
EXTERNAL_REVIEWER_EVIDENCE_FIELDS = {
    "external_reviewer_approval_source",
    "external_reviewer_packet_manifest",
    "external_reviewer_packet_manifest_sha256",
    "external_reviewer_packet_sha256",
    "external_reviewer_redaction",
}
PUBLIC_CONTRACT_OPTIONAL_FIELDS = {
    "monitor": EXTERNAL_REVIEWER_EVIDENCE_FIELDS,
    "review": EXTERNAL_REVIEWER_EVIDENCE_FIELDS,
    "apply": EXTERNAL_REVIEWER_EVIDENCE_FIELDS,
    "assurance": set(),
}
PUBLIC_CONTRACT_STAGE_RE = re.compile(
    r"<!-- source-chain-stage:(?P<stage>[a-z]+) -->\s*"
    r"```yaml\n(?P<body>.*?)\n```\s*"
    r"<!-- /source-chain-stage:(?P=stage) -->",
    re.DOTALL,
)
PUBLIC_CONTRACT_PATH_RE = re.compile(
    r"<!-- source-chain-canonical-paths -->\s*"
    r"```text\n(?P<body>.*?)\n```\s*"
    r"<!-- /source-chain-canonical-paths -->",
    re.DOTALL,
)
DECISION_FIELDS = {
    "finding_id",
    "finding_hash",
    "classification",
    "apply_mode",
    "change_class",
    "source_tier",
    "source_role",
    "quality_gate",
    "durable_abstraction",
    "applicability",
    "rejected_source_specifics",
    "affected_files",
    "risk",
    "evidence_url",
    "monitor_root",
    "root_decision",
    "evidence",
    "required_verification",
}
DECISION_LIST_FIELDS = {"affected_files", "evidence", "required_verification"}
DECISION_ABSTRACTION_FIELDS = {
    "durable_abstraction",
    "applicability",
    "rejected_source_specifics",
}
DECISION_CLASSIFICATIONS = {
    "accept-source-entry",
    "accept-rule-update",
    "accept-test-or-validator-update",
}
DECISION_CHANGE_CLASSES = {
    "content-plane",
    "source-entry-content",
    "source-registry-authority",
    "control-plane",
    "validation",
    "public-private-boundary",
}
AUTO_APPLY_CHANGE_CLASSES = {"source-entry-content"}
DECISION_RISKS = {"low", "medium", "high"}
DECISION_ROOT_DECISIONS = {"monitor", "reference-only", "reject-monitor-root", "unresolved"}
DECISION_SOURCE_TIERS = {
    "[standard]",
    "[official-doc]",
    "[vendor-doc]",
    "[official-implementation]",
    "[research]",
    "[case-study]",
    "[case-study-root]",
    "[commentary]",
    "[ai-summary]",
}
DECISION_SOURCE_ROLES = {"authority-root", "evidence-url", "discovery-filter"}
SOURCE_ROOT_COVERAGE_SOURCE_ROLES = {"authority-root", "discovery-filter"}
DECISION_QUALITY_GATES = {"primary_verified", "non_normative_source_entry", "reject_low_tier"}
AUTO_APPLY_QUALITY_GATES = {"primary_verified", "non_normative_source_entry"}
LOW_AUTHORITY_DECISION_TIERS = {
    "[commentary]",
    "[ai-summary]",
    "[case-study]",
    "[case-study-root]",
}
LOW_AUTHORITY_UPDATE_CLASSIFICATIONS = {"accept-rule-update", "accept-test-or-validator-update"}
INACCESSIBLE_SOURCE_FIELDS = {
    "source_ref",
    "target_kind",
    "url",
    "failure_kind",
    "failure_detail",
    "coverage_status",
    "alternate_primary_url",
}
SOURCE_ROOT_COVERAGE_FIELDS = {
    "source_ref",
    "registry_path",
    "monitor_root",
    "source_role",
    "status",
    "cursor_kind",
    "latest_seen_key",
    "latest_seen_url",
    "reason",
}
ABSENT_DECISION_TEXT_VALUES = {"n/a", "na", "none", "todo", "tbd", "unavailable"}
INACCESSIBLE_TARGET_KINDS = {"root", "link"}
INACCESSIBLE_COVERAGE_STATUSES = {"unresolved", "primary_alternate_verified"}
SOURCE_ROOT_COVERAGE_STATUSES = {"checked", "skipped", "blocked", "inaccessible", "not_in_scope"}
SOURCE_ROOT_COVERAGE_CURSOR_KINDS = {
    "item",
    "validator",
    "no_item_list",
    "not_applicable",
}
SOURCE_UPDATE_MONITORING_MODES = {"one_off", "recurring"}
SCALAR_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):(?:\s*(.*))?$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
RFC3339_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)$")
LOGICAL_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
RUN_SLOT_RE = re.compile(r"^(?:[01]\d|2[0-3])[0-5]\d$")
IANA_TIMEZONE_RE = re.compile(r"^(?:UTC|[A-Za-z0-9._+-]+(?:/[A-Za-z0-9._+-]+)+)$")
MONITOR_SCOPE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
MODEL_ROUTE_RE = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
EXIT_CODE_RE = re.compile(r"^(?:0|[1-9][0-9]{0,9})$")
EXIT_CODE_MAX = (1 << 32) - 1
MODEL_SETTING_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+:-]{0,127}$")
MONITOR_ROOT_LINE_RE = re.compile(r"^\s*Monitor root:\s*(https?://\S+)\s*$", re.IGNORECASE)
URL_RE = re.compile(r"https?://\S+")
ATTEMPT_ID_RE = re.compile(
    r"^(?P<stage>[a-z]+)-(?P<timestamp>\d{4}-\d{2}-\d{2}T\d{6}Z)-[A-Za-z0-9][A-Za-z0-9._-]{5,}$"
)
SOURCE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
FAILURE_KIND_RE = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
EXTERNAL_REVIEWER_STATUSES = {"not_needed", "considered_skipped", "blocked", "approved", "used"}
INPUT_STATES = {"resolved", "missing", "invalid", "not_applicable"}
STAGE_STATUSES = {
    "monitor": {"pass", "no-findings", "blocked", "partial"},
    "review": {"pass", "no-findings", "blocked", "partial", "failed"},
    "apply": {"pass", "no-op", "blocked", "partial", "failed"},
    "assurance": {"pass", "blocked", "partial", "failed"},
}
MONITOR_SOURCE_STATUSES = {"pass", "no-findings", "partial", "blocked"}
MONITOR_SOURCE_STATUS_BY_STATUS = {
    "pass": {"pass", "no-findings"},
    "no-findings": {"no-findings"},
    "partial": {"partial"},
    "blocked": {"blocked"},
}
MONITOR_WORKSPACE_STATUSES = {"clean", "dirty", "concurrent_change", "unknown"}
HEADER_LIST_FIELDS = {"source_registry_files", "policy_files", "changed_files", "verification"}
VERIFICATION_FIELDS = {
    "command",
    "covers",
    "dirty_tree",
    "environment",
    "exit_code",
    "expected_assertion",
    "output_ref",
    "touched_files",
    "tree_or_artifact",
}
VERIFICATION_DIRTY_TREE_STATUSES = {
    "clean",
    "exported-artifact",
    "not_applicable-readonly",
    "tracked-diff-matches-changed_files",
}
PREDECESSORS = {
    "review": ("monitor",),
    "apply": ("review",),
    "assurance": ("monitor", "review", "apply"),
}
CANONICAL_ARTIFACT_SUFFIXES = {
    "monitor": "source_monitor/{logical_date}_{run_slot}.md",
    "review": "source_review/{logical_date}_{run_slot}.md",
    "apply": "source_apply/{logical_date}_{run_slot}.md",
    "assurance": "automation_assurance/{logical_date}_{run_slot}.md",
}
SUCCESS_STATUSES = {
    "review": {"pass", "no-findings"},
    "apply": {"pass", "no-op"},
    "assurance": {"pass"},
}
SUCCESS_PREDECESSOR_STATUSES = {
    "monitor": {"pass", "no-findings"},
    "review": {"pass", "no-findings"},
    "apply": {"pass", "no-op"},
}
SUCCESS_MONITOR_SOURCE_STATUSES = {"pass", "no-findings"}
ABSENT_AUTHORITY_VALUES = {
    "",
    "missing",
    "n/a",
    "none",
    "not applicable",
    "not_applicable",
    "tbd",
    "to be confirmed",
    "unavailable",
    "unknown",
}
NO_EXTERNAL_REVIEWER_VALUES = {"", "none", "not_applicable", "unavailable"}
PATH_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
URI_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
MONITOR_SCOPE_MAX_BYTES = 128
ARTIFACT_MAX_BYTES = 16 * 1024 * 1024
UNRESOLVED_IDENTITY_VALUES = {
    "",
    "missing",
    "none",
    "tbd",
    "unavailable",
    "unknown",
    "{monitor_scope}",
}


def normalize_monitor_scope(value: str) -> str:
    """Return the canonical representation used for source-chain scope identity."""

    return unicodedata.normalize("NFKC", value).strip().casefold()


def normalize_display_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split())


def monitor_scope_sha256(value: str) -> str:
    return hashlib.sha256(normalize_monitor_scope(value).encode("utf-8")).hexdigest()


@dataclass
class DecisionField:
    line_no: int
    value: str = ""
    list_items: list[str] = field(default_factory=list)


@dataclass
class HeaderListRecord:
    line_no: int
    values: dict[str, str] = field(default_factory=dict)


def _read_header(
    text: str,
) -> tuple[dict[str, str], int, list[str], set[str]]:
    errors: list[str] = []
    lines = text.splitlines()
    header: dict[str, str] = {}
    duplicate_fields: set[str] = set()
    current_key: str | None = None
    current_in_list = False
    current_field_is_ambiguous = False
    if not lines or not lines[0].strip():
        return (
            header,
            0,
            ["missing machine-readable header at top of file"],
            duplicate_fields,
        )
    if lines[0].startswith("#"):
        return (
            header,
            0,
            ["missing machine-readable header before prose"],
            duplicate_fields,
        )
    for index, line in enumerate(lines, start=1):
        if not line.strip():
            return header, index, errors, duplicate_fields
        match = SCALAR_RE.match(line)
        if match:
            key = match.group(1)
            if key in header or key in duplicate_fields:
                errors.append(f"duplicate header field at line {index}: {key}")
                duplicate_fields.add(key)
                header.pop(key, None)
                current_key = key
                current_in_list = False
                current_field_is_ambiguous = True
                continue
            header[key] = match.group(2) or ""
            current_key = key
            current_in_list = False
            current_field_is_ambiguous = False
        elif line.startswith("  - ") or line.startswith("- "):
            if current_key is None:
                errors.append(f"header list item without field at line {index}: {line}")
                continue
            if current_field_is_ambiguous:
                continue
            if current_key not in HEADER_LIST_FIELDS:
                errors.append(f"header field {current_key} does not accept list items at line {index}")
                continue
            if not header[current_key]:
                header[current_key] = "__list__"
            current_in_list = True
        elif line.startswith("    "):
            if current_field_is_ambiguous:
                continue
            if current_key is None or current_key not in HEADER_LIST_FIELDS or not current_in_list:
                errors.append(f"invalid nested header line {index}: {line}")
        else:
            errors.append(f"invalid header line {index}: {line}")
    return header, len(lines), errors, duplicate_fields


def read_header(text: str) -> tuple[dict[str, str], int, list[str]]:
    header, header_end, errors, _duplicate_fields = _read_header(text)
    return header, header_end, errors


def header_list_records(text: str, field_name: str) -> tuple[list[HeaderListRecord], list[str]]:
    records: list[HeaderListRecord] = []
    errors: list[str] = []
    current_field: str | None = None
    current: HeaderListRecord | None = None
    for line_no, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            break
        match = SCALAR_RE.match(line)
        if match and not line.startswith(" "):
            current_field = match.group(1)
            current = None
            continue
        if current_field != field_name:
            continue
        stripped = line.strip()
        if stripped.startswith("- "):
            current = HeaderListRecord(line_no=line_no)
            records.append(current)
            item = stripped[2:]
            item_match = SCALAR_RE.match(item)
            if item_match:
                current.values[item_match.group(1)] = item_match.group(2) or ""
            elif item:
                current.values["value"] = item
            continue
        if current is None:
            errors.append(f"{field_name} has nested line without list item at line {line_no}")
            continue
        nested_match = SCALAR_RE.match(stripped)
        if not nested_match:
            errors.append(f"{field_name} has invalid nested line at line {line_no}: {line}")
            continue
        nested_key = nested_match.group(1)
        if nested_key in current.values:
            errors.append(
                f"{field_name} list item at line {current.line_no} duplicates nested field: {nested_key}"
            )
        current.values[nested_key] = nested_match.group(2) or ""
    return records, errors


def header_list_values(text: str, field_name: str) -> tuple[list[str], list[str]]:
    records, errors = header_list_records(text, field_name)
    values: list[str] = []
    for record in records:
        if "value" in record.values:
            values.append(record.values["value"].strip())
        elif "path" in record.values:
            values.append(record.values["path"].strip())
        else:
            errors.append(f"{field_name} list item at line {record.line_no} must include a value or path")
    return values, errors


def parse_int_field(header: dict[str, str], key: str, errors: list[str]) -> int:
    raw = header.get(key, "")
    try:
        value = int(raw)
    except ValueError:
        errors.append(f"{key} must be an integer")
        return 0
    if value < 0:
        errors.append(f"{key} must be a non-negative integer")
        return 0
    return value


def validate_hash(header: dict[str, str], key: str, errors: list[str]) -> None:
    value = header.get(key, "")
    if value != "unavailable" and not SHA256_RE.match(value):
        errors.append(f"{key} must be a SHA-256 hex digest or unavailable")


def validate_hash_or_none(header: dict[str, str], key: str, errors: list[str]) -> None:
    value = header.get(key, "")
    if value not in {"none", "unavailable"} and not SHA256_RE.match(value):
        errors.append(f"{key} must be a SHA-256 hex digest, none, or unavailable")


def read_artifact_bytes(path: Path, *, description: str) -> bytes:
    return safe_paths.read_regular_file_bytes(
        path,
        description=description,
        max_bytes=ARTIFACT_MAX_BYTES,
    )


@dataclass(frozen=True, slots=True)
class ArtifactSnapshot:
    """One immutable read result retained for the full validation call graph."""

    raw: bytes | None
    read_error: str | None = None


ArtifactSnapshotCache = dict[Path, ArtifactSnapshot]


def artifact_snapshot_key(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path.expanduser())))


def project_artifact_path(path: Path, project_root: Path) -> Path:
    """Return ``path`` as an absolute path relative to the explicit project."""

    expanded = path.expanduser()
    if expanded.is_absolute():
        return artifact_snapshot_key(expanded)
    return artifact_snapshot_key(artifact_snapshot_key(project_root) / expanded)


def cached_artifact_bytes(
    path: Path,
    cache: ArtifactSnapshotCache,
    *,
    description: str,
) -> bytes:
    key = artifact_snapshot_key(path)
    snapshot = cache.get(key)
    if snapshot is None:
        try:
            raw = read_artifact_bytes(path, description=description)
        except (OSError, ValueError) as exc:
            snapshot = ArtifactSnapshot(raw=None, read_error=str(exc))
        else:
            snapshot = ArtifactSnapshot(raw=raw)
        cache[key] = snapshot
    if snapshot.read_error is not None:
        raise ValueError(snapshot.read_error)
    if snapshot.raw is None:
        raise ValueError("artifact snapshot contains neither bytes nor a read error")
    return snapshot.raw


def cached_artifact_text(
    path: Path,
    cache: ArtifactSnapshotCache,
    *,
    description: str,
) -> str:
    return cached_artifact_bytes(path, cache, description=description).decode("utf-8")


def file_sha256(path: Path) -> str:
    raw = read_artifact_bytes(path, description="source-chain artifact")
    return hashlib.sha256(raw).hexdigest()


def read_regular_text(path: Path, *, description: str) -> str:
    return read_artifact_bytes(path, description=description).decode("utf-8")


def public_contract_errors(path: Path) -> list[str]:
    """Check that the public artifact templates match the executable contract."""
    try:
        text = read_regular_text(path, description="public source-chain artifact contract")
    except (OSError, UnicodeError, ValueError) as exc:
        return [f"cannot read public source-chain artifact contract: {exc}"]

    templates: dict[str, str] = {}
    errors: list[str] = []
    for match in PUBLIC_CONTRACT_STAGE_RE.finditer(text):
        stage = match.group("stage")
        if stage in templates:
            errors.append(f"public source-chain artifact contract duplicates {stage} template")
            continue
        templates[stage] = match.group("body")

    expected_stages = set(STAGE_REQUIRED_FIELDS)
    missing_stages = sorted(expected_stages - set(templates))
    extra_stages = sorted(set(templates) - expected_stages)
    if missing_stages:
        errors.append(
            "public source-chain artifact contract is missing stage templates: "
            + ", ".join(missing_stages)
        )
    if extra_stages:
        errors.append(
            "public source-chain artifact contract has unknown stage templates: "
            + ", ".join(extra_stages)
        )

    for stage in sorted(expected_stages & set(templates)):
        fields: set[str] = set()
        duplicate_fields: set[str] = set()
        for line in templates[stage].splitlines():
            if not line or line[0].isspace():
                continue
            field_match = SCALAR_RE.match(line)
            if not field_match:
                continue
            field = field_match.group(1)
            if field in fields:
                duplicate_fields.add(field)
            fields.add(field)
        if duplicate_fields:
            errors.append(
                f"public {stage} template duplicates fields: {', '.join(sorted(duplicate_fields))}"
            )
        expected_fields = STAGE_REQUIRED_FIELDS[stage] | PUBLIC_CONTRACT_OPTIONAL_FIELDS[stage]
        missing_fields = sorted(expected_fields - fields)
        extra_fields = sorted(fields - expected_fields)
        if missing_fields:
            errors.append(
                f"public {stage} template is missing fields: {', '.join(missing_fields)}"
            )
        if extra_fields:
            errors.append(
                f"public {stage} template has fields outside the executable contract: "
                + ", ".join(extra_fields)
            )
        version_match = re.search(
            r"^artifact_schema_version:\s*(\S+)\s*$",
            templates[stage],
            re.MULTILINE,
        )
        if version_match is None or version_match.group(1) != ARTIFACT_SCHEMA_VERSION:
            errors.append(
                f"public {stage} template artifact_schema_version must be {ARTIFACT_SCHEMA_VERSION}"
            )

        status_match = re.search(
            r"^status:\s*(.+?)\s*$",
            templates[stage],
            re.MULTILINE,
        )
        documented_statuses = (
            {
                item.strip()
                for item in status_match.group(1).split("|")
                if item.strip()
            }
            if status_match is not None
            else set()
        )
        if documented_statuses != STAGE_STATUSES[stage]:
            errors.append(
                f"public {stage} template status values do not match the executable contract"
            )

    path_match = PUBLIC_CONTRACT_PATH_RE.search(text)
    documented_paths: dict[str, str] = {}
    if path_match is None:
        errors.append("public source-chain artifact contract is missing canonical path metadata")
    else:
        for raw_line in path_match.group("body").splitlines():
            stage, separator, value = raw_line.partition(":")
            if not separator or not stage.strip() or not value.strip():
                errors.append("public source-chain canonical path metadata has an invalid row")
                continue
            stage = stage.strip()
            if stage in documented_paths:
                errors.append(f"public source-chain canonical path metadata duplicates {stage}")
            documented_paths[stage] = value.strip()
        expected_paths = {
            stage: f"review_artifacts/{suffix}"
            for stage, suffix in CANONICAL_ARTIFACT_SUFFIXES.items()
        }
        if documented_paths != expected_paths:
            errors.append(
                "public source-chain canonical paths do not match the executable contract"
            )

    block_contracts = {
        "inaccessible": INACCESSIBLE_SOURCE_FIELDS,
        "source-root-coverage": SOURCE_ROOT_COVERAGE_FIELDS,
        "review-decision": DECISION_FIELDS,
    }
    for block_name, expected_fields in block_contracts.items():
        block_re = re.compile(
            rf"<!-- source-chain-block:{re.escape(block_name)} -->\s*"
            rf"```yaml\n(?P<body>.*?)\n```\s*"
            rf"<!-- /source-chain-block:{re.escape(block_name)} -->",
            re.DOTALL,
        )
        block_match = block_re.search(text)
        if block_match is None:
            errors.append(f"public source-chain contract is missing {block_name} block metadata")
            continue
        fields = {
            match.group(1)
            for line in block_match.group("body").splitlines()
            if (match := SCALAR_RE.match(line.strip())) is not None
        }
        if fields != expected_fields:
            errors.append(
                f"public source-chain {block_name} fields do not match the executable contract"
            )

    apply_template = templates.get("apply", "")
    verification_lines: list[str] = []
    in_verification = False
    for line in apply_template.splitlines():
        if line == "verification:":
            in_verification = True
            continue
        if in_verification and line and not line[0].isspace():
            break
        if in_verification:
            verification_lines.append(line)
    verification_fields = {
        match.group(1)
        for line in verification_lines
        if (match := SCALAR_RE.match(line.strip().removeprefix("- "))) is not None
    }
    if verification_fields != VERIFICATION_FIELDS:
        errors.append(
            "public source-chain apply verification fields do not match the executable contract"
        )
    return errors


def find_artifact_reference(
    project_root: Path,
    artifact_ref: str,
    *,
    artifact_cache: ArtifactSnapshotCache | None = None,
) -> Path | None:
    if artifact_ref in {"none", "unavailable"}:
        return None
    if artifact_reference_safety_error(project_root, artifact_ref) is not None:
        return None
    ref_path = Path(artifact_ref)
    candidate = project_root / ref_path
    if not safe_paths.path_within_root(candidate, project_root / "review_artifacts"):
        return None
    if artifact_cache is not None:
        # The cache owns the read outcome for this validation, including a
        # retained failure if the entry was absent or unreadable at capture.
        return candidate
    return candidate if candidate.exists() else None


def selected_project_root_errors(project_root: Path) -> list[str]:
    """Validate the explicit root that owns one source-chain artifact tree."""

    lexical_root = artifact_snapshot_key(project_root)
    errors = safe_paths.bounded_input_errors(
        lexical_root,
        lexical_root,
        description="selected source-chain project",
        expected_kind="directory",
    )
    if not lexical_root.exists():
        errors.append(f"selected source-chain project root does not exist: {lexical_root}")
    return errors


def artifact_path_scope_errors(path: Path, project_root: Path) -> list[str]:
    """Reject an artifact path outside the selected project's canonical tree.

    This check is intentionally lexical and runs before any artifact read.  It
    therefore retains traversal components for rejection, treats an unrelated
    ancestor named ``review_artifacts`` as irrelevant, and rejects symlink
    aliases without following them.
    """

    raw_path = os.fspath(path)
    windows_path = PureWindowsPath(raw_path)
    if (
        PATH_CONTROL_RE.search(raw_path)
        or "\\" in raw_path
        or "://" in raw_path
        or URI_SCHEME_RE.match(raw_path)
        or windows_path.is_absolute()
        or bool(windows_path.drive)
    ):
        return ["artifact path must be plain local filesystem path text"]
    if ".." in path.parts or ".." in windows_path.parts:
        return [
            "artifact path must stay under the selected project's top-level "
            "review_artifacts tree without traversal or nested artifact trees"
        ]

    lexical_path = project_artifact_path(path, project_root)
    lexical_root = artifact_snapshot_key(project_root)
    try:
        relative_path = lexical_path.relative_to(lexical_root)
    except ValueError:
        return ["artifact path must stay under the explicitly selected project root"]

    unsafe_symlink_components = [
        component
        for component in safe_paths.symlink_components(lexical_path)
        if not safe_paths.is_allowed_system_symlink(component)
    ]
    if unsafe_symlink_components:
        return [
            "artifact path must not use symlink aliases: "
            + ", ".join(str(component) for component in unsafe_symlink_components)
        ]

    if (
        not relative_path.parts
        or relative_path.parts[0] != "review_artifacts"
        or relative_path.parts.count("review_artifacts") != 1
    ):
        return [
            "artifact path must stay under one selected top-level review_artifacts "
            "root without nested artifact trees"
        ]

    try:
        safe_paths.safe_relative_child(
            lexical_root,
            relative_path,
            description="source-chain artifact path",
        )
    except ValueError as exc:
        return [str(exc)]
    return []


def artifact_reference_safety_error(project_root: Path, artifact_ref: str) -> str | None:
    if artifact_ref in {"none", "unavailable"}:
        return None
    ref_path = Path(artifact_ref)
    windows_path = PureWindowsPath(artifact_ref)
    if (
        not artifact_ref.strip()
        or PATH_CONTROL_RE.search(artifact_ref)
        or "\\" in artifact_ref
        or "://" in artifact_ref
        or URI_SCHEME_RE.match(artifact_ref)
    ):
        return "must be plain repo-relative path text"
    if ref_path.is_absolute() or windows_path.is_absolute() or windows_path.drive:
        return "must be a relative review_artifacts path, not an absolute path"
    if ".." in ref_path.parts or ".." in windows_path.parts:
        return "must not contain traversal components"
    if ref_path.parts.count("review_artifacts") != 1:
        return "must not contain nested review_artifacts trees"
    try:
        safe_paths.normalize_repo_relative_path(
            artifact_ref,
            project_root,
            description="source-chain artifact reference",
        )
    except ValueError as exc:
        return str(exc)
    if not safe_paths.path_within_root(
        project_root / ref_path,
        project_root / "review_artifacts",
    ):
        return "must stay under the same review_artifacts tree"
    return None


def validate_external_reviewer_status(header: dict[str, str], errors: list[str]) -> None:
    value = header.get("external_reviewer_status", "")
    if value and value not in EXTERNAL_REVIEWER_STATUSES:
        errors.append(f"external_reviewer_status must be one of {', '.join(sorted(EXTERNAL_REVIEWER_STATUSES))}")


def validate_external_reviewer_packet(
    project_root: Path,
    header: dict[str, str],
    errors: list[str],
) -> None:
    status = header.get("external_reviewer_status", "")
    if status not in {"approved", "used"}:
        scope = header.get("external_reviewer_packet_scope", "")
        if scope and scope not in NO_EXTERNAL_REVIEWER_VALUES:
            errors.append(
                "external_reviewer_packet_scope must be none when external_reviewer_status "
                f"is {status or 'missing'}"
            )
        for field in (
            "external_reviewer_approval_source",
            "external_reviewer_packet_manifest",
            "external_reviewer_packet_manifest_sha256",
            "external_reviewer_packet_sha256",
            "external_reviewer_redaction",
        ):
            if field not in header:
                continue
            if not header[field].strip():
                errors.append(f"{field} must not be empty when present")
            elif header[field] not in NO_EXTERNAL_REVIEWER_VALUES:
                errors.append(
                    f"{field} must be none or unavailable when external_reviewer_status "
                    f"is {status or 'missing'}"
                )
        return
    scope = header.get("external_reviewer_packet_scope", "")
    if scope in NO_EXTERNAL_REVIEWER_VALUES:
        errors.append(f"external_reviewer_packet_scope must name the approved packet scope when external_reviewer_status is {status}")
    approval_source = header.get("external_reviewer_approval_source", "")
    if absent_authority_value(approval_source):
        errors.append(
            f"external_reviewer_approval_source must record the active-thread approval or named standing grant when external_reviewer_status is {status}"
        )
    packet_sha = header.get("external_reviewer_packet_sha256", "")
    if not SHA256_RE.match(packet_sha) or packet_sha == "0" * 64:
        errors.append(f"external_reviewer_packet_sha256 must be a SHA-256 hex digest and non-placeholder when external_reviewer_status is {status}")
    packet_manifest = header.get("external_reviewer_packet_manifest", "")
    manifest_data: dict[str, object] | None = None
    if absent_authority_value(packet_manifest):
        errors.append(f"external_reviewer_packet_manifest must name the reviewed packet manifest when external_reviewer_status is {status}")
    else:
        manifest_safety_error = artifact_reference_safety_error(project_root, packet_manifest)
        if manifest_safety_error:
            errors.append(f"external_reviewer_packet_manifest {manifest_safety_error}")
        else:
            manifest_path = find_artifact_reference(project_root, packet_manifest)
            if manifest_path is None:
                errors.append("external_reviewer_packet_manifest must exist under the same review_artifacts tree")
            elif manifest_path.is_symlink() or not manifest_path.is_file():
                errors.append("external_reviewer_packet_manifest must be a regular non-symlink file")
            else:
                loaded, raw_manifest, load_errors = review_packet_contract.load_manifest_file(
                    manifest_path
                )
                errors.extend(
                    f"external_reviewer_packet_manifest {error}"
                    for error in load_errors
                )
                if (
                    raw_manifest is not None
                    and SHA256_RE.match(
                        header.get("external_reviewer_packet_manifest_sha256", "")
                    )
                ):
                    expected_manifest_sha = header["external_reviewer_packet_manifest_sha256"]
                    actual_manifest_sha = hashlib.sha256(raw_manifest).hexdigest()
                    if actual_manifest_sha != expected_manifest_sha:
                        errors.append("external_reviewer_packet_manifest_sha256 does not match external_reviewer_packet_manifest")
                if isinstance(loaded, dict):
                    manifest_data = loaded
                    for error in review_packet_contract.portable_manifest_errors(
                        manifest_data,
                        manifest_path,
                        external_status=status,
                    ):
                        errors.append(f"external_reviewer_packet_manifest {error}")
                elif loaded is not None:
                    errors.append("external_reviewer_packet_manifest root must be an object")
    manifest_sha = header.get("external_reviewer_packet_manifest_sha256", "")
    if not SHA256_RE.match(manifest_sha) or manifest_sha == "0" * 64:
        errors.append(f"external_reviewer_packet_manifest_sha256 must be a SHA-256 hex digest and non-placeholder when external_reviewer_status is {status}")
    redaction = header.get("external_reviewer_redaction", "")
    if redaction in NO_EXTERNAL_REVIEWER_VALUES:
        errors.append(f"external_reviewer_redaction must record the leak-scan or redaction boundary when external_reviewer_status is {status}")
    if manifest_data is not None:
        packet_record = manifest_data.get("packet")
        packet_record = packet_record if isinstance(packet_record, dict) else {}
        approval_record = manifest_data.get("approval")
        approval_record = approval_record if isinstance(approval_record, dict) else {}
        if packet_record.get("approved_scope") != scope:
            errors.append("external_reviewer_packet_scope does not match manifest packet.approved_scope")
        if packet_record.get("packet_sha256") != packet_sha:
            errors.append("external_reviewer_packet_sha256 does not match manifest packet.packet_sha256")
        if approval_record.get("source") != approval_source:
            errors.append("external_reviewer_approval_source does not match manifest approval.source")
        redactions = packet_record.get("redactions")
        if not isinstance(redactions, list) or redaction not in redactions:
            errors.append("external_reviewer_redaction is not bound in manifest packet.redactions")


def validate_enum_field(header: dict[str, str], key: str, allowed: set[str], errors: list[str]) -> None:
    value = header.get(key, "")
    if value and value not in allowed:
        errors.append(f"{key} must be one of {', '.join(sorted(allowed))}")


def parse_artifact_timezone(header: dict[str, str], errors: list[str]) -> ZoneInfo | None:
    value = header.get("timezone", "")
    if not value:
        errors.append("timezone must be a valid IANA timezone name")
        return None
    if PATH_CONTROL_RE.search(value):
        errors.append("timezone must be a valid IANA timezone name")
        return None
    if Path(value).is_absolute() or ".." in Path(value).parts:
        errors.append("timezone must be a normalized IANA timezone name, not an absolute or traversal path")
        return None
    if value != "UTC" and "/" not in value:
        errors.append("timezone must be a normalized IANA timezone name, not an abbreviation or alias")
        return None
    if not IANA_TIMEZONE_RE.fullmatch(value):
        errors.append("timezone must be a valid IANA timezone name")
        return None
    try:
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        errors.append("timezone must be a valid IANA timezone name")
        return None


def artifact_timezone_from_header(header: dict[str, str]) -> ZoneInfo | None:
    value = header.get("timezone", "")
    if (
        not value
        or bool(PATH_CONTROL_RE.search(value))
        or not IANA_TIMEZONE_RE.fullmatch(value)
        or Path(value).is_absolute()
        or ".." in Path(value).parts
    ):
        return None
    if value != "UTC" and "/" not in value:
        return None
    try:
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        return None


def attempt_id_local_date(value: str, artifact_timezone: ZoneInfo) -> str | None:
    attempt_match = ATTEMPT_ID_RE.match(value)
    if not attempt_match:
        return None
    timestamp = attempt_match.group("timestamp").removesuffix("Z")
    try:
        parsed = datetime.strptime(timestamp, "%Y-%m-%dT%H%M%S")
    except ValueError:
        return None
    return parsed.replace(tzinfo=ZoneInfo("UTC")).astimezone(artifact_timezone).date().isoformat()


def validate_attempt_id(
    value: str,
    *,
    expected_stage: str,
    logical_date: str,
    artifact_timezone: ZoneInfo,
    field_name: str,
    errors: list[str],
) -> None:
    attempt_match = ATTEMPT_ID_RE.match(value)
    if not attempt_match:
        errors.append(f"{field_name} must be <stage>-YYYY-MM-DDTHHMMSSZ-<unique-suffix>")
        return
    if attempt_match.group("stage") != expected_stage:
        errors.append(f"{field_name} must match the {expected_stage} stage")
        return
    local_date = attempt_id_local_date(value, artifact_timezone)
    if local_date != logical_date:
        errors.append(f"{field_name} UTC timestamp must map to logical_date in the declared timezone")


def parse_utc_timestamp(header: dict[str, str], key: str, errors: list[str]) -> datetime | None:
    value = header.get(key, "")
    if not value:
        return None
    if not RFC3339_UTC_RE.match(value):
        errors.append(f"{key} must be an RFC3339 UTC timestamp ending in Z or +00:00")
        return None
    normalized = value.removesuffix("Z") + "+00:00" if value.endswith("Z") else value
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        errors.append(f"{key} must be a valid RFC3339 UTC timestamp")
        return None


def validate_execution_identity(header: dict[str, str], errors: list[str]) -> str:
    scope = header.get("monitor_scope", "")
    canonical_scope = normalize_monitor_scope(scope)
    scope_bytes = len(scope.encode("utf-8"))
    if scope.casefold() in UNRESOLVED_IDENTITY_VALUES:
        errors.append("monitor_scope must be a concrete, non-placeholder scope")
    elif scope != canonical_scope or not MONITOR_SCOPE_RE.fullmatch(scope):
        errors.append(
            "monitor_scope must be a canonical lowercase scope id using letters, digits, dots, underscores, or hyphens"
        )
    elif scope_bytes > MONITOR_SCOPE_MAX_BYTES:
        errors.append(f"monitor_scope must be at most {MONITOR_SCOPE_MAX_BYTES} UTF-8 bytes")
    elif any(ord(character) < 32 or ord(character) == 127 for character in scope):
        errors.append("monitor_scope must not contain control characters")

    expected_scope_hash = monitor_scope_sha256(scope) if canonical_scope else ""
    recorded_scope_hash = header.get("monitor_scope_sha256", "")
    if not SHA256_RE.fullmatch(recorded_scope_hash):
        errors.append("monitor_scope_sha256 must be a SHA-256 hex digest")
    elif expected_scope_hash and recorded_scope_hash != expected_scope_hash:
        errors.append("monitor_scope_sha256 must match the canonical monitor_scope bytes")

    model_route = header.get("model_route", "")
    if not MODEL_ROUTE_RE.fullmatch(model_route):
        errors.append("model_route must be a lowercase route id using letters, digits, underscores, or hyphens")

    model_label = header.get("model_label", "")
    canonical_model_label = normalize_display_text(model_label)
    if model_label.casefold() in UNRESOLVED_IDENTITY_VALUES:
        errors.append("model_label must record the concrete visible runtime label")
    elif model_label != canonical_model_label:
        errors.append("model_label must use canonical NFKC text with collapsed whitespace")
    elif len(model_label.encode("utf-8")) > 256:
        errors.append("model_label must be at most 256 UTF-8 bytes")
    elif any(ord(character) < 32 or ord(character) == 127 for character in model_label):
        errors.append("model_label must not contain control characters")

    for field_name in ("reasoning_effort", "execution_mode"):
        value = header.get(field_name, "")
        if not MODEL_SETTING_RE.fullmatch(value):
            errors.append(
                f"{field_name} must record one concrete visible setting or the token not_exposed"
            )

    return recorded_scope_hash if SHA256_RE.fullmatch(recorded_scope_hash) else ""


def validate_common_header(header: dict[str, str], stage: str, errors: list[str]) -> None:
    if header.get("artifact_schema_version") != ARTIFACT_SCHEMA_VERSION:
        errors.append(f"artifact_schema_version must be {ARTIFACT_SCHEMA_VERSION}")
    validate_execution_identity(header, errors)
    artifact_timezone = parse_artifact_timezone(header, errors)
    logical_date = header.get("logical_date", "")
    logical_date_valid = bool(LOGICAL_DATE_RE.fullmatch(logical_date))
    if logical_date_valid:
        try:
            datetime.strptime(logical_date, "%Y-%m-%d")
        except ValueError:
            logical_date_valid = False
    if not logical_date_valid:
        errors.append("logical_date must be YYYY-MM-DD")
    run_slot = header.get("run_slot", "")
    if not RUN_SLOT_RE.match(run_slot):
        errors.append("run_slot must be HHMM in 24-hour local time for the declared timezone")
    if logical_date and run_slot:
        expected_chain_id = f"source-{logical_date}-{run_slot}"
        if header.get("chain_id") != expected_chain_id:
            errors.append(f"chain_id must be {expected_chain_id}")
        expected_stage_run_id = f"{stage}-{logical_date}-{run_slot}"
        if header.get("stage_run_id") != expected_stage_run_id:
            errors.append(f"stage_run_id must be {expected_stage_run_id}")
    if artifact_timezone is not None:
        validate_attempt_id(
            header.get("attempt_id", ""),
            expected_stage=stage,
            logical_date=logical_date,
            artifact_timezone=artifact_timezone,
            field_name="attempt_id",
            errors=errors,
        )
    validate_enum_field(header, "status", STAGE_STATUSES[stage], errors)
    started_at = parse_utc_timestamp(header, "started_at_utc", errors)
    completed_at = parse_utc_timestamp(header, "completed_at_utc", errors)
    if started_at and completed_at and completed_at < started_at:
        errors.append("completed_at_utc must not be earlier than started_at_utc")


def validate_predecessor_fields(
    project_root: Path,
    header: dict[str, str],
    stage: str,
    predecessor: str,
    errors: list[str],
    artifact_cache: ArtifactSnapshotCache,
    auto_apply_path_prefixes: tuple[str, ...],
) -> bool:
    logical_date = header.get("logical_date", "")
    run_slot = header.get("run_slot", "")
    state_key = f"input_{predecessor}_state"
    artifact_key = f"input_{predecessor}_artifact"
    run_id_key = f"input_{predecessor}_stage_run_id"
    attempt_key = f"input_{predecessor}_attempt_id"
    sha_key = f"input_{predecessor}_sha256"
    state = header.get(state_key, "")
    validate_enum_field(header, state_key, INPUT_STATES, errors)
    if predecessor != "apply" and state == "not_applicable":
        errors.append(f"{state_key} may not be not_applicable")
    if header.get("status") in SUCCESS_STATUSES.get(stage, set()) and state != "resolved":
        errors.append(f"{state_key} must be resolved when {stage} status is {header.get('status')}")
    canonical_artifact_suffix = CANONICAL_ARTIFACT_SUFFIXES[predecessor].format(
        logical_date=logical_date,
        run_slot=run_slot,
    )
    if state == "resolved":
        artifact_ref = header.get(artifact_key, "")
        expected_run_id = f"{predecessor}-{logical_date}-{run_slot}"
        if header.get(run_id_key) != expected_run_id:
            errors.append(f"{run_id_key} must be {expected_run_id} when resolved")
        if header.get(attempt_key) in {"", "none", "unavailable"}:
            errors.append(f"{attempt_key} must name the predecessor attempt when resolved")
        else:
            artifact_timezone = artifact_timezone_from_header(header)
            if artifact_timezone is not None:
                validate_attempt_id(
                    header.get(attempt_key, ""),
                    expected_stage=predecessor,
                    logical_date=logical_date,
                    artifact_timezone=artifact_timezone,
                    field_name=attempt_key,
                    errors=errors,
                )
        validate_hash(header, sha_key, errors)
        expected_hash = header.get(sha_key, "")
        safety_error = artifact_reference_safety_error(project_root, header.get(artifact_key, ""))
        if safety_error:
            errors.append(f"{artifact_key} {safety_error}")
            return False
        canonical_artifact_ref = f"review_artifacts/{canonical_artifact_suffix}"
        if artifact_ref != canonical_artifact_ref:
            errors.append(
                f"{artifact_key} must equal {canonical_artifact_ref} when resolved"
            )
            return False
        artifact_path = find_artifact_reference(
            project_root,
            header.get(artifact_key, ""),
            artifact_cache=artifact_cache,
        )
        if artifact_path is None:
            errors.append(f"{artifact_key} could not be read for resolved predecessor")
            return True
        try:
            predecessor_bytes = cached_artifact_bytes(
                artifact_path,
                artifact_cache,
                description=f"{artifact_key} predecessor artifact",
            )
        except (OSError, ValueError) as exc:
            errors.append(f"{artifact_key} could not be hashed safely: {exc}")
            return True
        actual_hash = hashlib.sha256(predecessor_bytes).hexdigest()
        if expected_hash != actual_hash:
            errors.append(f"{sha_key} does not match {header.get(artifact_key)}")
        predecessor_report = validate_artifact(
            artifact_path,
            predecessor,
            project_root=project_root,
            artifact_bytes=predecessor_bytes,
            verify_decision_hashes=predecessor == "review",
            expected_model_route=header.get("model_route", ""),
            expected_timezone=header.get("timezone", ""),
            auto_apply_path_prefixes=auto_apply_path_prefixes,
            _artifact_cache=artifact_cache,
        )
        predecessor_lint_errors = cast(list[object], predecessor_report.get("errors", []))
        if predecessor_lint_errors:
            errors.append(
                f"{artifact_key} must lint cleanly when {state_key} is resolved: "
                + "; ".join(str(error) for error in predecessor_lint_errors)
            )
        try:
            predecessor_text = predecessor_bytes.decode("utf-8")
        except UnicodeError as exc:
            errors.append(f"{artifact_key} could not be decoded safely: {exc}")
            return True
        predecessor_header, _header_end, predecessor_errors = read_header(predecessor_text)
        if predecessor_errors:
            errors.append(f"{artifact_key} has invalid machine-readable header")
            return True
        predecessor_status = predecessor_header.get("status", "")
        if predecessor_status not in STAGE_STATUSES[predecessor]:
            errors.append(
                f"{artifact_key} status must be terminal for {predecessor}: {predecessor_status or 'missing'}"
            )
        if header.get("status") in SUCCESS_STATUSES.get(stage, set()):
            expected_statuses = SUCCESS_PREDECESSOR_STATUSES[predecessor]
            if predecessor_status not in expected_statuses:
                errors.append(
                    f"{artifact_key} status must be successful for successful {stage}: "
                    f"{predecessor_status or 'missing'}"
                )
            if (
                predecessor == "monitor"
                and predecessor_header.get("source_status", "") not in SUCCESS_MONITOR_SOURCE_STATUSES
            ):
                errors.append(
                    f"{artifact_key} source_status must be successful for successful {stage}: "
                    f"{predecessor_header.get('source_status', '') or 'missing'}"
                )
        comparisons = {
            "stage": predecessor,
            "chain_id": header.get("chain_id", ""),
            "logical_date": logical_date,
            "run_slot": run_slot,
            "monitor_scope": header.get("monitor_scope", ""),
            "monitor_scope_sha256": header.get("monitor_scope_sha256", ""),
            "model_route": header.get("model_route", ""),
            "timezone": header.get("timezone", ""),
            "stage_run_id": header.get(run_id_key, ""),
            "attempt_id": header.get(attempt_key, ""),
        }
        for key, expected_value in comparisons.items():
            if predecessor_header.get(key) != expected_value:
                errors.append(
                    f"{artifact_key} header {key} does not match expected predecessor {key}"
                )
    elif state in {"missing", "invalid", "not_applicable"}:
        if state == "not_applicable" and header.get(sha_key) not in {"unavailable", "none"}:
            errors.append(f"{sha_key} must be unavailable or none when {state_key} is not_applicable")
        elif state in {"missing", "invalid"}:
            validate_hash_or_none(header, sha_key, errors)
    return True


def validate_predecessors(
    project_root: Path,
    header: dict[str, str],
    stage: str,
    errors: list[str],
    artifact_cache: ArtifactSnapshotCache,
    auto_apply_path_prefixes: tuple[str, ...],
) -> bool:
    references_are_canonical = True
    for predecessor in PREDECESSORS.get(stage, ()):
        predecessor_is_canonical = validate_predecessor_fields(
            project_root,
            header,
            stage,
            predecessor,
            errors,
            artifact_cache,
            auto_apply_path_prefixes,
        )
        references_are_canonical = references_are_canonical and predecessor_is_canonical
    return references_are_canonical


def validate_current_artifact_path(
    path: Path,
    project_root: Path,
    header: dict[str, str],
    stage: str,
    errors: list[str],
) -> bool:
    logical_date = header.get("logical_date", "")
    run_slot = header.get("run_slot", "")
    if not logical_date or not run_slot:
        return True
    expected_suffix = CANONICAL_ARTIFACT_SUFFIXES[stage].format(
        logical_date=logical_date,
        run_slot=run_slot,
    )
    if ".." in path.parts:
        errors.append(
            f"artifact path must end with {expected_suffix} directly under one selected "
            "top-level review_artifacts root without traversal or nested artifact trees"
        )
        return False
    lexical_path = artifact_snapshot_key(path)
    lexical_root = artifact_snapshot_key(project_root)
    try:
        relative_path = lexical_path.relative_to(lexical_root)
    except ValueError:
        errors.append("artifact path must stay under the explicitly selected project root")
        return False
    if "review_artifacts" not in relative_path.parts:
        return True
    if relative_path.parts.count("review_artifacts") != 1:
        errors.append(
            f"artifact path must end with {expected_suffix} directly under one selected "
            "top-level review_artifacts root without traversal or nested artifact trees"
        )
        return False
    unsafe_symlink_components = [
        component
        for component in safe_paths.symlink_components(lexical_path)
        if not safe_paths.is_allowed_system_symlink(component)
    ]
    if unsafe_symlink_components:
        errors.append(
            "artifact path must not use symlink aliases: "
            + ", ".join(str(component) for component in unsafe_symlink_components)
        )
        return False
    expected_path = lexical_root / "review_artifacts" / expected_suffix
    if lexical_path != artifact_snapshot_key(expected_path):
        errors.append(
            f"artifact path must end with {expected_suffix} directly under the selected "
            "top-level review_artifacts root"
        )
        return False
    return True


def decision_blocks_with_errors(
    text: str,
    *,
    require_section: bool = False,
    section_only: bool = False,
) -> tuple[list[dict[str, DecisionField]], list[str]]:
    blocks: list[dict[str, DecisionField]] = []
    errors: list[str] = []
    current: dict[str, DecisionField] | None = None
    current_field: str | None = None
    accepted_sections = [
        candidate
        for candidate in markdown_structure.markdown_sections(
            text,
            include_fenced_content=False,
        )
        if candidate.title == "Accepted Findings"
    ]
    accepted_heading_count = len(accepted_sections)
    if accepted_heading_count > 1:
        errors.append("review artifact duplicates section: Accepted Findings")
    if accepted_heading_count:
        source_lines = list(accepted_sections[0].lines)
    elif section_only:
        source_lines = []
        if require_section:
            errors.append("accepted finding blocks require an exact ## Accepted Findings section")
    else:
        source_lines = list(markdown_structure.operative_lines(text))
        if require_section:
            errors.append("accepted finding blocks require an exact ## Accepted Findings section")
    for line_no, line in source_lines:
        match = SCALAR_RE.match(line.strip())
        if not match:
            if (
                current is not None
                and current_field in DECISION_LIST_FIELDS
                and line.startswith("  - ")
            ):
                current[current_field].list_items.append(line[4:].strip())
            continue
        key = match.group(1)
        if key == "finding_id":
            if current:
                blocks.append(current)
            current = {key: DecisionField(line_no=line_no, value=match.group(2) or "")}
            current_field = key
        elif current is not None and key in DECISION_FIELDS:
            if key in current:
                errors.append(
                    f"finding block at line {current['finding_id'].line_no} "
                    f"duplicates field {key} at line {line_no}"
                )
            else:
                current[key] = DecisionField(line_no=line_no, value=match.group(2) or "")
            current_field = key
        elif current is not None:
            errors.append(
                f"finding block at line {current['finding_id'].line_no} "
                f"has unknown field {key} at line {line_no}"
            )
            current_field = None
        else:
            current_field = None
    if current:
        blocks.append(current)
    return blocks, errors


def decision_blocks(text: str) -> list[dict[str, DecisionField]]:
    blocks, _errors = decision_blocks_with_errors(text)
    return blocks


def markdown_section_lines(text: str, heading: str) -> list[tuple[int, str]]:
    return next(
        (
            list(section.lines)
            for section in markdown_structure.markdown_sections(
                text,
                include_fenced_content=False,
            )
            if section.title == heading
        ),
        [],
    )


def field_blocks(
    text: str,
    fields: set[str],
    *,
    section: str,
    errors: list[str] | None = None,
) -> list[dict[str, DecisionField]]:
    blocks: list[dict[str, DecisionField]] = []
    current: dict[str, DecisionField] | None = None
    heading_count = sum(
        candidate.title == section
        for candidate in markdown_structure.markdown_sections(
            text,
            include_fenced_content=False,
        )
    )
    if heading_count > 1 and errors is not None:
        errors.append(f"artifact duplicates section: {section}")
    for line_no, line in markdown_section_lines(text, section):
        match = SCALAR_RE.match(line.strip())
        if not match:
            continue
        key = match.group(1)
        if key == "source_ref":
            if current:
                blocks.append(current)
            current = {key: DecisionField(line_no=line_no, value=match.group(2) or "")}
        elif current is not None and key in fields:
            if key in current:
                if errors is not None:
                    errors.append(
                        f"{section} block at line {current['source_ref'].line_no} "
                        f"duplicates field {key} at line {line_no}"
                    )
            else:
                current[key] = DecisionField(line_no=line_no, value=match.group(2) or "")
        elif current is not None and errors is not None:
            errors.append(
                f"{section} block at line {current['source_ref'].line_no} "
                f"has unknown field {key} at line {line_no}"
            )
    if current:
        blocks.append(current)
    return blocks


def inaccessible_source_blocks(
    text: str,
    errors: list[str] | None = None,
) -> list[dict[str, DecisionField]]:
    return field_blocks(
        text,
        INACCESSIBLE_SOURCE_FIELDS,
        section="Inaccessible Sources",
        errors=errors,
    )


def source_root_coverage_blocks(
    text: str,
    errors: list[str] | None = None,
) -> list[dict[str, DecisionField]]:
    return field_blocks(
        text,
        SOURCE_ROOT_COVERAGE_FIELDS,
        section="Source Root Coverage",
        errors=errors,
    )


def unresolved_inaccessible_urls_from_text(text: str) -> set[str]:
    urls: set[str] = set()
    for block in inaccessible_source_blocks(text):
        coverage = block.get("coverage_status")
        url = block.get("url")
        if coverage and url and coverage.value.strip() == "unresolved":
            urls.add(url.value.strip())
    return urls


def predecessor_unresolved_inaccessible_urls(
    project_root: Path,
    header: dict[str, str],
    predecessor: str,
    artifact_cache: ArtifactSnapshotCache,
) -> set[str]:
    if header.get(f"input_{predecessor}_state") != "resolved":
        return set()
    artifact_path = find_artifact_reference(
        project_root,
        header.get(f"input_{predecessor}_artifact", ""),
        artifact_cache=artifact_cache,
    )
    if artifact_path is None:
        return set()
    try:
        return unresolved_inaccessible_urls_from_text(
            cached_artifact_text(
                artifact_path,
                artifact_cache,
                description="predecessor artifact",
            )
        )
    except (OSError, UnicodeError, ValueError):
        return set()


def predecessor_header(
    project_root: Path,
    header: dict[str, str],
    predecessor: str,
    artifact_cache: ArtifactSnapshotCache,
) -> dict[str, str]:
    if header.get(f"input_{predecessor}_state") != "resolved":
        return {}
    artifact_path = find_artifact_reference(
        project_root,
        header.get(f"input_{predecessor}_artifact", ""),
        artifact_cache=artifact_cache,
    )
    if artifact_path is None:
        return {}
    try:
        predecessor_text = cached_artifact_text(
            artifact_path,
            artifact_cache,
            description="predecessor artifact",
        )
    except (OSError, UnicodeError, ValueError):
        return {}
    parsed_header, _header_end, errors = read_header(predecessor_text)
    if errors:
        return {}
    return parsed_header


def latest_commit_from_apply_field(value: str) -> str:
    commits = [item.strip() for item in value.split(";") if item.strip()]
    return commits[-1] if commits else ""


def validate_http_url(
    value: str,
    line_no: int,
    field_name: str,
    errors: list[str],
    *,
    allow_none: bool = False,
    subject: str = "inaccessible source",
) -> None:
    if allow_none and value == "none":
        return
    reason = url_safety.blocked_external_url_reason(value, resolve_hostname=False)
    if reason == "external URL must use https":
        errors.append(
            f"{subject} at line {line_no} has invalid {field_name}: expected https URL; {reason}"
        )
        return
    if reason == "external URL must not contain credentials":
        errors.append(
            f"{subject} at line {line_no} has unsafe {field_name}: credentials are not allowed; {reason}"
        )
        return
    if reason:
        errors.append(f"{subject} at line {line_no} has unsafe {field_name}: {reason}")


def validate_external_or_local_evidence(
    value: str,
    line_no: int,
    field_name: str,
    errors: list[str],
) -> None:
    parsed, parse_error = url_safety.safe_urlsplit(value)
    if parse_error:
        errors.append(f"finding block at line {line_no} has unsafe {field_name}: {parse_error}")
        return
    if parsed is None:
        errors.append(f"finding block at line {line_no} has unsafe {field_name}: URL parser returned no result")
        return
    if parsed.scheme or parsed.netloc:
        reason = url_safety.blocked_external_url_reason(value, resolve_hostname=False)
        if reason:
            errors.append(f"finding block at line {line_no} has unsafe {field_name}: {reason}")
        return
    if not safe_relative_path_text(value):
        errors.append(f"finding block at line {line_no} has invalid {field_name}: expected safe https URL or repo-relative evidence path")


def is_pathless_host_root(value: str) -> bool:
    parsed, parse_error = url_safety.safe_urlsplit(value)
    if parse_error or parsed is None:
        return False
    return parsed.scheme == "https" and bool(parsed.netloc) and not parsed.path.strip("/")


def is_static_or_exact_monitor_root(value: str) -> bool:
    return (
        check_reference_freshness.is_exact_source_item_url(value)
        and not check_reference_freshness.is_recurring_monitor_root(value)
    )


def validate_monitor_root(value: str, line_no: int, root_decision: str, errors: list[str]) -> None:
    if value == "reference-only":
        if root_decision != "reference-only":
            errors.append(
                f"finding block at line {line_no} uses monitor_root reference-only without root_decision reference-only"
            )
        return
    parsed, parse_error = url_safety.safe_urlsplit(value)
    if parse_error:
        errors.append(f"finding block at line {line_no} has unsafe monitor_root: {parse_error}")
        return
    if parsed is None:
        errors.append(f"finding block at line {line_no} has unsafe monitor_root: URL parser returned no result")
        return
    if not parsed.scheme and not parsed.netloc:
        errors.append(f"finding block at line {line_no} has invalid monitor_root: expected https URL or reference-only")
        return
    reason = url_safety.blocked_external_url_reason(value, resolve_hostname=False)
    if reason:
        errors.append(f"finding block at line {line_no} has unsafe monitor_root: {reason}")
        return
    if is_pathless_host_root(value):
        errors.append(
            f"finding block at line {line_no} has overbroad monitor_root: use the smallest durable parent path, feed, releases page, or reference-only"
        )
    if is_static_or_exact_monitor_root(value):
        errors.append(
            f"finding block at line {line_no} has exact/static monitor_root: use a durable parent root, feed, releases page, tags page, or reference-only"
        )


def safe_relative_path_text(value: str) -> bool:
    posix_path = PurePosixPath(value)
    windows_path = PureWindowsPath(value)
    return bool(
        value.strip()
        and not PATH_CONTROL_RE.search(value)
        and "\\" not in value
        and "://" not in value
        and URI_SCHEME_RE.match(value) is None
        and not posix_path.is_absolute()
        and not windows_path.is_absolute()
        and not windows_path.drive
        and ".." not in posix_path.parts
        and ".." not in windows_path.parts
        and all(part not in {"", ".", ".."} for part in value.split("/"))
    )


def auto_apply_path_prefix_errors(prefixes: tuple[str, ...]) -> list[str]:
    """Validate configured repository-relative directory containment prefixes."""

    errors: list[str] = []
    for prefix in prefixes:
        if (
            not isinstance(prefix, str)
            or prefix != prefix.strip()
            or not prefix.endswith("/")
            or not safe_relative_path_text(prefix[:-1])
        ):
            errors.append(
                "auto_apply_path_prefixes must contain safe repository-relative "
                f"directory prefixes ending in '/': {prefix!r}"
            )
    return errors


def validate_relative_paths(values: list[str], line_no: int, label: str, errors: list[str]) -> None:
    for value in values:
        if not safe_relative_path_text(value):
            errors.append(f"finding block at line {line_no} has invalid {label}: {value}")


def validate_decision_abstraction_fields(block: dict[str, DecisionField], errors: list[str]) -> None:
    line_no = block["finding_id"].line_no
    for field_name in sorted(DECISION_ABSTRACTION_FIELDS):
        field = block[field_name]
        value = field.value.strip()
        if value.startswith("<") and value.endswith(">"):
            errors.append(f"finding block at line {line_no} has placeholder field: {field_name}")
        if value.casefold() in ABSENT_DECISION_TEXT_VALUES:
            errors.append(f"finding block at line {line_no} has non-substantive field: {field_name}")


def decision_payload(block: dict[str, DecisionField]) -> dict[str, object]:
    payload: dict[str, object] = {}
    for key in sorted(DECISION_FIELDS - {"finding_hash"}):
        field = block[key]
        if key in DECISION_LIST_FIELDS:
            payload[key] = [item.strip() for item in field.list_items if item.strip()]
        else:
            payload[key] = field.value.strip()
    return payload


def decision_hash(block: dict[str, DecisionField]) -> str:
    payload = json.dumps(decision_payload(block), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def prepare_decision_hashes(path: Path) -> dict[str, object]:
    try:
        raw = safe_paths.read_regular_file_bytes(
            path,
            description="source-chain review artifact",
            max_bytes=ARTIFACT_MAX_BYTES,
        )
        text = raw.decode("utf-8")
    except (OSError, UnicodeError, ValueError) as exc:
        return {
            "path": str(path),
            "stage": "review",
            "prepared_decision_hashes": [],
            "errors": [f"cannot read artifact: {exc}"],
        }

    blocks = decision_blocks(text)
    errors: list[str] = []
    if not blocks:
        errors.append("review artifact contains no machine-readable finding blocks")
    manual_count = sum(
        1
        for block in blocks
        if block.get("apply_mode") is not None
        and block["apply_mode"].value.strip() == "manual"
    )
    validate_review_decisions(
        text,
        len(blocks),
        manual_count,
        errors,
        allow_uncomputed_hashes=True,
        require_section=True,
        section_only=True,
    )
    if errors:
        return {
            "path": str(path),
            "stage": "review",
            "prepared_decision_hashes": [],
            "errors": errors,
        }

    prepared = []
    for block in blocks:
        payload = decision_payload(block)
        prepared.append(
            {
                "finding_id": block["finding_id"].value.strip(),
                "finding_line": block["finding_id"].line_no,
                "canonical_payload": payload,
                "finding_hash": decision_hash(block),
            }
        )
    return {
        "path": str(path),
        "stage": "review",
        "prepared_decision_hashes": prepared,
        "errors": [],
    }


def auto_eligible_decision_files(text: str, errors: list[str] | None = None) -> set[str]:
    files: set[str] = set()
    for block in decision_blocks(text):
        if not (DECISION_FIELDS <= set(block)):
            continue
        apply_mode = block["apply_mode"].value.strip()
        change_class = block["change_class"].value.strip()
        finding_hash = block["finding_hash"].value.strip()
        quality_gate = block["quality_gate"].value.strip()
        if (
            apply_mode == "auto"
            and change_class in AUTO_APPLY_CHANGE_CLASSES
            and quality_gate in AUTO_APPLY_QUALITY_GATES
            and SHA256_RE.match(finding_hash)
        ):
            files.update(item.strip() for item in block["affected_files"].list_items if item.strip())
        elif apply_mode == "auto" and errors is not None:
            if change_class not in AUTO_APPLY_CHANGE_CLASSES:
                errors.append(
                    f"finding block at line {block['finding_id'].line_no} uses apply_mode auto with non-auto change_class: {change_class}"
                )
            if quality_gate not in AUTO_APPLY_QUALITY_GATES:
                errors.append(
                    f"finding block at line {block['finding_id'].line_no} uses apply_mode auto with non-auto quality_gate: {quality_gate}"
                )
            if not SHA256_RE.match(finding_hash):
                errors.append(
                    f"finding block at line {block['finding_id'].line_no} uses apply_mode auto without a valid finding_hash"
                )
    return files


def validate_inaccessible_sources(
    text: str,
    header: dict[str, str],
    stage: str,
    errors: list[str],
) -> set[str]:
    if stage not in {"monitor", "review", "assurance"}:
        return set()
    blocks = inaccessible_source_blocks(text, errors)
    unresolved_urls: set[str] = set()
    if stage in {"monitor", "review"}:
        inaccessible_count = parse_int_field(header, "inaccessible_source_count", errors)
        if len(blocks) != inaccessible_count:
            errors.append(
                f"inaccessible_source_count is {inaccessible_count}, but {len(blocks)} "
                "machine-readable inaccessible source block(s) were found"
            )
    unresolved_count = parse_int_field(header, "unresolved_inaccessible_source_count", errors)
    duplicate_keys: set[tuple[str, str]] = set()
    actual_unresolved = 0
    for block in blocks:
        missing = sorted(INACCESSIBLE_SOURCE_FIELDS - set(block))
        line_no = block["source_ref"].line_no
        if missing:
            errors.append(
                f"inaccessible source block at line {line_no} missing fields: {', '.join(missing)}"
            )
            continue
        for field_name, field_value in block.items():
            if not field_value.value.strip():
                errors.append(
                    f"inaccessible source block at line {line_no} has empty field: {field_name}"
                )
        source_ref = block["source_ref"].value.strip()
        if source_ref and not SOURCE_REF_RE.match(source_ref):
            errors.append(f"inaccessible source block at line {line_no} has invalid source_ref")
        target_kind = block["target_kind"].value.strip()
        if target_kind not in INACCESSIBLE_TARGET_KINDS:
            errors.append(
                f"inaccessible source block at line {line_no} has invalid target_kind: {target_kind}"
            )
        failure_kind = block["failure_kind"].value.strip()
        if failure_kind and not FAILURE_KIND_RE.match(failure_kind):
            errors.append(f"inaccessible source block at line {line_no} has invalid failure_kind")
        url = block["url"].value.strip()
        if url:
            validate_http_url(url, line_no, "url", errors)
        coverage_status = block["coverage_status"].value.strip()
        if coverage_status not in INACCESSIBLE_COVERAGE_STATUSES:
            errors.append(
                f"inaccessible source block at line {line_no} has invalid coverage_status: {coverage_status}"
            )
        alternate_url = block["alternate_primary_url"].value.strip()
        if coverage_status == "primary_alternate_verified":
            if alternate_url == "none":
                errors.append(
                    "inaccessible source block at line "
                    f"{line_no} requires alternate_primary_url for primary_alternate_verified"
                )
            elif alternate_url:
                validate_http_url(alternate_url, line_no, "alternate_primary_url", errors)
        elif alternate_url:
            validate_http_url(alternate_url, line_no, "alternate_primary_url", errors, allow_none=True)
        if coverage_status == "unresolved":
            actual_unresolved += 1
            unresolved_urls.add(url)
        if source_ref and url:
            duplicate_key = (source_ref, url)
            if duplicate_key in duplicate_keys:
                errors.append(f"duplicate inaccessible source block at line {line_no}: {source_ref} {url}")
            duplicate_keys.add(duplicate_key)
        if stage == "assurance" and coverage_status != "unresolved":
            errors.append(
                f"assurance inaccessible source block at line {line_no} must reconcile an unresolved source"
            )
    if actual_unresolved != unresolved_count:
        errors.append(
            f"unresolved_inaccessible_source_count is {unresolved_count}, but {actual_unresolved} "
            "unresolved inaccessible source block(s) were found"
        )
    if stage == "assurance" and len(blocks) != unresolved_count:
        errors.append(
            f"assurance unresolved_inaccessible_source_count is {unresolved_count}, but {len(blocks)} "
            "reconciliation block(s) were found"
        )
    if unresolved_count > 0:
        if stage == "monitor" and header.get("source_status") == "no-findings":
            errors.append("source_status no-findings is invalid with unresolved inaccessible sources")
        if stage == "review" and header.get("status") == "no-findings":
            errors.append("review status no-findings is invalid with unresolved inaccessible sources")
    return unresolved_urls


def placeholder_table_value(value: str) -> bool:
    stripped = value.strip()
    return not stripped or (stripped.startswith("[") and stripped.endswith("]"))


def first_url(value: str) -> str | None:
    match = URL_RE.search(value)
    if not match:
        return None
    return match.group(0).rstrip("`).,;]>\"'")


def recurring_source_url_refs_from_text(
    text: str,
    *,
    errors: list[str] | None = None,
) -> list[tuple[int, str]]:
    refs: list[tuple[int, str]] = []
    table_rows, table_errors = check_reference_freshness.source_update_table_rows(text)
    if errors is not None:
        errors.extend(
            f"{message} (line {line_no})"
            for line_no, message in table_errors
        )
    for line_no, row in table_rows:
        if "feed" in row:
            feed = row["feed"]
            url = first_url(feed)
            if url is None and not placeholder_table_value(feed) and errors is not None:
                errors.append(
                    f"SOURCE_UPDATE Feed Watchers row at line {line_no} must contain an http(s) Feed URL"
                )
        else:
            mode = row["monitoring mode"].strip()
            if placeholder_table_value(mode):
                continue
            if mode not in SOURCE_UPDATE_MONITORING_MODES:
                if errors is not None:
                    errors.append(
                        f"SOURCE_UPDATE Source Registry row at line {line_no} Monitoring Mode must be one of: "
                        + ", ".join(sorted(SOURCE_UPDATE_MONITORING_MODES))
                    )
                continue
            if mode != "recurring":
                continue
            source = row["source"]
            url = first_url(source)
            if url is None and not placeholder_table_value(source) and errors is not None:
                errors.append(
                    f"SOURCE_UPDATE recurring Source Registry row at line {line_no} must contain an http(s) Source URL"
                )
        if url:
            refs.append((line_no, url))
    return refs


def recurring_source_urls_from_text(
    text: str,
    *,
    errors: list[str] | None = None,
) -> set[str]:
    return {
        url
        for _line_no, url in recurring_source_url_refs_from_text(text, errors=errors)
    }


def same_url_ignoring_terminal_slash(first: str, second: str) -> bool:
    """Compare already-validated URLs without treating a terminal slash as an item."""

    return first.rstrip("/") == second.rstrip("/")


def expected_monitor_roots_from_registry_files(
    project_root: Path,
    text: str,
    errors: list[str],
) -> tuple[dict[str, set[str]], set[str]]:
    expected_root_registry_paths: dict[str, set[str]] = {}
    canonical_exact_roots: set[str] = set()
    records, record_errors = header_list_records(text, "source_registry_files")
    errors.extend(record_errors)
    for record in records:
        path_value = record.values.get("path", "").strip()
        rel_path = Path(path_value)
        if not safe_relative_path_text(path_value):
            continue
        target = project_root / rel_path
        if not safe_paths.path_within_root(target, project_root) or not target.exists():
            continue
        try:
            registry_text = read_regular_text(target, description="source registry input")
        except (OSError, UnicodeError, ValueError):
            continue
        for _line_no, block in check_reference_freshness.paragraph_blocks(registry_text):
            monitor_urls = [
                check_reference_freshness.clean_url(match.group(0))
                for _monitor_line_no, decision in check_reference_freshness.monitor_root_lines(
                    block,
                    1,
                )
                for match in URL_RE.finditer(decision)
            ]
            for monitor_url in monitor_urls:
                expected_root_registry_paths.setdefault(monitor_url, set()).add(
                    path_value
                )
            if check_reference_freshness.metadata_field_values(
                block,
                "Monitor root class",
            ) == ["canonical_exact_root"]:
                canonical_exact_roots.update(monitor_urls)
        if target.name == "SOURCE_UPDATE.md":
            for monitor_url in recurring_source_urls_from_text(
                registry_text,
                errors=errors,
            ):
                expected_root_registry_paths.setdefault(monitor_url, set()).add(
                    path_value
                )
    return expected_root_registry_paths, canonical_exact_roots


def validate_source_root_coverage(
    project_root: Path,
    text: str,
    header: dict[str, str],
    stage: str,
    errors: list[str],
    *,
    verify_current_input_hashes: bool = False,
) -> None:
    if stage != "monitor":
        return
    coverage_count = parse_int_field(header, "source_root_coverage_count", errors)
    blocks = source_root_coverage_blocks(text, errors)
    expected_root_registry_paths: dict[str, set[str]] = {}
    canonical_exact_roots: set[str] = set()
    if verify_current_input_hashes:
        expected_root_registry_paths, canonical_exact_roots = (
            expected_monitor_roots_from_registry_files(
                project_root,
                text,
                errors,
            )
        )
    inaccessible_urls = {
        block["url"].value.strip()
        for block in inaccessible_source_blocks(text)
        if INACCESSIBLE_SOURCE_FIELDS <= set(block)
    }
    if len(blocks) != coverage_count:
        errors.append(
            f"source_root_coverage_count is {coverage_count}, but {len(blocks)} "
            "machine-readable source root coverage block(s) were found"
        )
    duplicate_keys: set[tuple[str, str, str]] = set()
    for block in blocks:
        missing = sorted(SOURCE_ROOT_COVERAGE_FIELDS - set(block))
        line_no = block["source_ref"].line_no
        if missing:
            errors.append(
                f"source root coverage block at line {line_no} missing fields: {', '.join(missing)}"
            )
            continue
        for field_name, field_value in block.items():
            if not field_value.value.strip():
                errors.append(
                    f"source root coverage block at line {line_no} has empty field: {field_name}"
                )
        source_ref = block["source_ref"].value.strip()
        if source_ref and not SOURCE_REF_RE.match(source_ref):
            errors.append(f"source root coverage block at line {line_no} has invalid source_ref")
        registry_path = block["registry_path"].value.strip()
        if not safe_relative_path_text(registry_path):
            errors.append(f"source root coverage block at line {line_no} has invalid registry_path")
        monitor_root = block["monitor_root"].value.strip()
        if monitor_root:
            validate_http_url(monitor_root, line_no, "monitor_root", errors, subject="source root coverage block")
            if is_pathless_host_root(monitor_root):
                errors.append(
                    f"source root coverage block at line {line_no} has overbroad monitor_root: use the smallest durable parent path, feed, releases page, tags page, or reference-only"
                )
            if (
                verify_current_input_hashes
                and is_static_or_exact_monitor_root(monitor_root)
                and monitor_root not in canonical_exact_roots
            ):
                errors.append(
                    f"source root coverage block at line {line_no} has exact/static monitor_root: use a durable parent root, feed, releases page, tags page, or reference-only"
                )
            if verify_current_input_hashes:
                allowed_registry_paths = expected_root_registry_paths.get(monitor_root)
                if allowed_registry_paths is None:
                    errors.append(
                        f"source root coverage block at line {line_no} has monitor_root not declared by the recorded source registries: {monitor_root}"
                    )
                elif registry_path not in allowed_registry_paths:
                    errors.append(
                        f"source root coverage block at line {line_no} registry_path does not declare monitor_root {monitor_root}; expected one of: "
                        + ", ".join(sorted(allowed_registry_paths))
                    )
        source_role = block["source_role"].value.strip()
        if source_role not in SOURCE_ROOT_COVERAGE_SOURCE_ROLES:
            errors.append(
                f"source root coverage block at line {line_no} has invalid source_role: {source_role}"
            )
        status = block["status"].value.strip()
        if status not in SOURCE_ROOT_COVERAGE_STATUSES:
            errors.append(
                f"source root coverage block at line {line_no} has invalid status: {status}"
            )
        cursor_kind = block["cursor_kind"].value.strip()
        if cursor_kind not in SOURCE_ROOT_COVERAGE_CURSOR_KINDS:
            errors.append(
                f"source root coverage block at line {line_no} has invalid cursor_kind: {cursor_kind}"
            )
        latest_seen_key = block["latest_seen_key"].value.strip()
        latest_seen_url = block["latest_seen_url"].value.strip()
        if latest_seen_url and latest_seen_url != "none":
            validate_http_url(latest_seen_url, line_no, "latest_seen_url", errors, subject="source root coverage block")
        if status == "checked" and cursor_kind in SOURCE_ROOT_COVERAGE_CURSOR_KINDS:
            if cursor_kind == "item":
                if latest_seen_key in {"", "none", "unavailable"}:
                    errors.append(
                        f"source root coverage block at line {line_no} uses cursor_kind item without a latest_seen_key"
                    )
                if latest_seen_url in {"", "none"}:
                    errors.append(
                        f"source root coverage block at line {line_no} uses cursor_kind item without a latest_seen_url"
                    )
                elif same_url_ignoring_terminal_slash(latest_seen_url, monitor_root):
                    errors.append(
                        f"source root coverage block at line {line_no} uses cursor_kind item without an item URL distinct from monitor_root"
                    )
            elif cursor_kind == "validator":
                if latest_seen_key in {"", "none", "unavailable"}:
                    errors.append(
                        f"source root coverage block at line {line_no} uses cursor_kind validator without a latest_seen_key"
                    )
                if latest_seen_url in {"", "none"}:
                    errors.append(
                        f"source root coverage block at line {line_no} uses cursor_kind validator without a latest_seen_url"
                    )
            elif cursor_kind == "no_item_list":
                if latest_seen_key != "none":
                    errors.append(
                        f"source root coverage block at line {line_no} uses cursor_kind no_item_list unless latest_seen_key is none"
                    )
                if not same_url_ignoring_terminal_slash(latest_seen_url, monitor_root):
                    errors.append(
                        f"source root coverage block at line {line_no} uses cursor_kind no_item_list unless latest_seen_url equals monitor_root"
                    )
            else:
                errors.append(
                    f"source root coverage block at line {line_no} uses status checked with cursor_kind not_applicable"
                )
        elif status in SOURCE_ROOT_COVERAGE_STATUSES and status != "checked":
            if cursor_kind != "not_applicable":
                errors.append(
                    f"source root coverage block at line {line_no} uses status {status} without cursor_kind not_applicable"
                )
            if latest_seen_key != "none":
                errors.append(
                    f"source root coverage block at line {line_no} uses status {status} unless latest_seen_key is none"
                )
            if latest_seen_url != "none":
                errors.append(
                    f"source root coverage block at line {line_no} uses status {status} unless latest_seen_url is none"
                )
        if status in {"blocked", "inaccessible"} and monitor_root not in inaccessible_urls:
            errors.append(
                f"source root coverage block at line {line_no} uses status {status} without a matching Inaccessible Sources block"
            )
        duplicate_key = (source_ref, registry_path, monitor_root)
        if duplicate_key in duplicate_keys:
            errors.append(f"duplicate source root coverage block at line {line_no}: {source_ref} {monitor_root}")
        duplicate_keys.add(duplicate_key)
    if verify_current_input_hashes:
        covered_roots = {
            block["monitor_root"].value.strip()
            for block in blocks
            if SOURCE_ROOT_COVERAGE_FIELDS <= set(block)
        }
        missing_roots = sorted(set(expected_root_registry_paths) - covered_roots)
        if missing_roots:
            errors.append(
                "source root coverage is missing registry monitor roots: "
                + ", ".join(missing_roots)
            )


def validate_review_decisions(
    text: str,
    accepted_count: int,
    manual_count: int,
    errors: list[str],
    unresolved_access_urls: set[str] | None = None,
    *,
    verify_decision_hashes: bool = False,
    allow_uncomputed_hashes: bool = False,
    require_section: bool = False,
    section_only: bool = False,
    auto_apply_path_prefixes: tuple[str, ...] = (),
) -> None:
    errors.extend(auto_apply_path_prefix_errors(auto_apply_path_prefixes))
    blocks, block_errors = decision_blocks_with_errors(
        text,
        require_section=require_section,
        section_only=section_only,
    )
    errors.extend(block_errors)
    unresolved_access_urls = unresolved_access_urls or set()
    if len(blocks) != accepted_count:
        errors.append(
            f"accepted_findings is {accepted_count}, but {len(blocks)} machine-readable finding block(s) were found"
        )
    actual_manual_count = 0
    seen_finding_ids: set[str] = set()
    for block in blocks[:accepted_count]:
        missing = sorted(DECISION_FIELDS - set(block))
        if missing:
            errors.append(
                f"finding block at line {block['finding_id'].line_no} missing fields: {', '.join(missing)}"
            )
            continue
        for field_name, field_value in block.items():
            if field_name in DECISION_LIST_FIELDS:
                if not field_value.value.strip() and not any(item.strip() for item in field_value.list_items):
                    errors.append(f"finding block at line {block['finding_id'].line_no} has empty field: {field_name}")
            elif not field_value.value.strip():
                errors.append(f"finding block at line {block['finding_id'].line_no} has empty field: {field_name}")
        apply_mode = block["apply_mode"].value.strip()
        classification = block["classification"].value.strip()
        change_class = block["change_class"].value.strip()
        source_tier = block["source_tier"].value.strip()
        source_role = block["source_role"].value.strip()
        quality_gate = block["quality_gate"].value.strip()
        risk = block["risk"].value.strip()
        root_decision = block["root_decision"].value.strip()
        finding_id = block["finding_id"].value.strip()
        if finding_id in seen_finding_ids:
            errors.append(
                f"finding block at line {block['finding_id'].line_no} duplicates finding_id: {finding_id}"
            )
        seen_finding_ids.add(finding_id)
        validate_decision_abstraction_fields(block, errors)
        if classification not in DECISION_CLASSIFICATIONS:
            errors.append(
                f"finding block at line {block['finding_id'].line_no} has invalid classification: {classification}"
            )
        if change_class not in DECISION_CHANGE_CLASSES:
            errors.append(
                f"finding block at line {block['finding_id'].line_no} has invalid change_class: {change_class}"
            )
        if source_tier not in DECISION_SOURCE_TIERS:
            errors.append(
                f"finding block at line {block['finding_id'].line_no} has invalid source_tier: {source_tier}"
            )
        if source_role not in DECISION_SOURCE_ROLES:
            errors.append(
                f"finding block at line {block['finding_id'].line_no} has invalid source_role: {source_role}"
            )
        if quality_gate not in DECISION_QUALITY_GATES:
            errors.append(
                f"finding block at line {block['finding_id'].line_no} has invalid quality_gate: {quality_gate}"
            )
        if risk not in DECISION_RISKS:
            errors.append(f"finding block at line {block['finding_id'].line_no} has invalid risk: {risk}")
        if root_decision not in DECISION_ROOT_DECISIONS:
            errors.append(
                f"finding block at line {block['finding_id'].line_no} has invalid root_decision: {root_decision}"
            )
        if source_tier in LOW_AUTHORITY_DECISION_TIERS:
            if classification in LOW_AUTHORITY_UPDATE_CLASSIFICATIONS:
                errors.append(
                    f"finding block at line {block['finding_id'].line_no} uses low-authority source_tier {source_tier} for {classification}"
                )
            if source_role == "authority-root":
                errors.append(
                    f"finding block at line {block['finding_id'].line_no} uses low-authority source_tier {source_tier} as authority-root"
                )
            if quality_gate == "primary_verified":
                errors.append(
                    f"finding block at line {block['finding_id'].line_no} uses low-authority source_tier {source_tier} with primary_verified quality_gate"
                )
        if apply_mode not in {"auto", "manual"}:
            errors.append(f"finding block at line {block['finding_id'].line_no} has invalid apply_mode: {apply_mode}")
        elif apply_mode == "manual":
            actual_manual_count += 1
        elif change_class not in AUTO_APPLY_CHANGE_CLASSES:
            errors.append(
                f"finding block at line {block['finding_id'].line_no} uses apply_mode auto with non-auto change_class: {change_class}"
            )
        elif quality_gate not in AUTO_APPLY_QUALITY_GATES:
            errors.append(
                f"finding block at line {block['finding_id'].line_no} uses apply_mode auto with non-auto quality_gate: {quality_gate}"
            )
        finding_hash = block["finding_hash"].value.strip()
        if finding_hash != "unavailable" and not SHA256_RE.match(finding_hash):
            errors.append(f"finding block at line {block['finding_id'].line_no} has invalid finding_hash")
        if (
            apply_mode == "auto"
            and not allow_uncomputed_hashes
            and not SHA256_RE.match(finding_hash)
        ):
            errors.append(
                f"finding block at line {block['finding_id'].line_no} uses apply_mode auto without a valid finding_hash"
            )
        if verify_decision_hashes and finding_hash != "unavailable":
            expected_hash = decision_hash(block)
            if finding_hash != expected_hash:
                errors.append(
                    f"finding block at line {block['finding_id'].line_no} finding_hash does not match canonical decision hash"
                )
        affected_files = [item.strip() for item in block["affected_files"].list_items if item.strip()]
        validate_relative_paths(affected_files, block["finding_id"].line_no, "affected_files", errors)
        if apply_mode == "auto" and auto_apply_path_prefixes:
            for affected_file in affected_files:
                if not safe_relative_path_text(affected_file):
                    continue
                if not any(affected_file.startswith(prefix) for prefix in auto_apply_path_prefixes):
                    errors.append(
                        f"finding block at line {block['finding_id'].line_no} uses "
                        "apply_mode auto with affected_files item outside the "
                        f"allowed path prefixes: {affected_file}"
                    )
        evidence_url = block["evidence_url"].value.strip()
        validate_external_or_local_evidence(evidence_url, block["finding_id"].line_no, "evidence_url", errors)
        if evidence_url in unresolved_access_urls:
            errors.append(
                f"finding block at line {block['finding_id'].line_no} uses unresolved inaccessible evidence_url"
            )
        validate_monitor_root(block["monitor_root"].value.strip(), block["finding_id"].line_no, root_decision, errors)
    if manual_count > accepted_count:
        errors.append("manual_findings must be less than or equal to accepted_findings")
    elif len(blocks) == accepted_count and actual_manual_count != manual_count:
        errors.append(
            f"manual_findings is {manual_count}, but {actual_manual_count} accepted finding block(s) use apply_mode: manual"
        )


def validate_apply_verification(text: str, errors: list[str], *, require_successful: bool) -> None:
    records, record_errors = header_list_records(text, "verification")
    errors.extend(record_errors)
    if not records:
        if require_successful:
            errors.append("apply verification must list at least one command record")
        return
    for record in records:
        missing = sorted(VERIFICATION_FIELDS - set(record.values))
        if missing:
            errors.append(
                f"verification item at line {record.line_no} missing fields: {', '.join(missing)}"
            )
            continue
        command = record.values["command"].strip()
        covers = record.values["covers"].strip()
        dirty_tree = record.values["dirty_tree"].strip()
        environment = record.values["environment"].strip()
        exit_code = record.values["exit_code"].strip()
        expected_assertion = record.values["expected_assertion"].strip()
        output_ref = record.values["output_ref"].strip()
        touched_files = record.values["touched_files"].strip()
        tree_or_artifact = record.values["tree_or_artifact"].strip()
        if not command:
            errors.append(f"verification item at line {record.line_no} has empty command")
        if not covers:
            errors.append(f"verification item at line {record.line_no} has empty covers")
        if dirty_tree not in VERIFICATION_DIRTY_TREE_STATUSES:
            errors.append(
                f"verification item at line {record.line_no} dirty_tree must be one of {', '.join(sorted(VERIFICATION_DIRTY_TREE_STATUSES))}"
            )
        if not environment:
            errors.append(f"verification item at line {record.line_no} has empty environment")
        if not expected_assertion:
            errors.append(f"verification item at line {record.line_no} has empty expected_assertion")
        if not output_ref:
            errors.append(f"verification item at line {record.line_no} has empty output_ref")
        elif not (
            SHA256_RE.fullmatch(output_ref)
            or re.fullmatch(r"sha256:[0-9a-f]{64}", output_ref)
            or re.fullmatch(r"(?:log|artifact):\S+", output_ref)
        ):
            errors.append(
                f"verification item at line {record.line_no} output_ref must be a digest or log/artifact reference"
            )
        if not touched_files:
            errors.append(f"verification item at line {record.line_no} has empty touched_files")
        if not tree_or_artifact:
            errors.append(f"verification item at line {record.line_no} has empty tree_or_artifact")
        elif not (
            SHA256_RE.fullmatch(tree_or_artifact)
            or re.fullmatch(r"[0-9a-f]{7,64}", tree_or_artifact)
            or re.fullmatch(r"commit:[0-9a-f]{7,64}", tree_or_artifact)
            or re.fullmatch(r"(?:tree|artifact|export):\S+", tree_or_artifact)
        ):
            errors.append(
                f"verification item at line {record.line_no} tree_or_artifact must identify the tested tree or artifact"
            )
        if not EXIT_CODE_RE.fullmatch(exit_code):
            errors.append(
                f"verification item at line {record.line_no} exit_code must be a canonical unsigned 32-bit decimal integer"
            )
        else:
            parsed_exit_code = int(exit_code)
            if parsed_exit_code > EXIT_CODE_MAX:
                errors.append(
                    f"verification item at line {record.line_no} exit_code must be at most {EXIT_CODE_MAX}"
                )
            elif require_successful and parsed_exit_code != 0:
                errors.append(
                    f"verification item at line {record.line_no} exit_code must be 0 for successful apply verification"
                )


def validate_apply_verification_coverage(
    project_root: Path,
    text: str,
    header: dict[str, str],
    errors: list[str],
    artifact_cache: ArtifactSnapshotCache,
) -> None:
    if header.get("status") != "pass" or header.get("input_review_state") != "resolved":
        return
    review_path = find_artifact_reference(
        project_root,
        header.get("input_review_artifact", ""),
        artifact_cache=artifact_cache,
    )
    if review_path is None:
        return
    try:
        review_text = cached_artifact_text(
            review_path,
            artifact_cache,
            description="review predecessor artifact",
        )
    except (OSError, UnicodeError, ValueError):
        return
    auto_finding_ids = {
        block["finding_id"].value.strip()
        for block in decision_blocks(review_text)
        if DECISION_FIELDS <= set(block)
        and block["apply_mode"].value.strip() == "auto"
        and block["change_class"].value.strip() in AUTO_APPLY_CHANGE_CLASSES
        and block["quality_gate"].value.strip() in AUTO_APPLY_QUALITY_GATES
        and SHA256_RE.match(block["finding_hash"].value.strip())
        and block["finding_hash"].value.strip() == decision_hash(block)
    }
    if not auto_finding_ids:
        return
    records, record_errors = header_list_records(text, "verification")
    errors.extend(record_errors)
    covered: set[str] = set()
    for record in records:
        if record.values.get("exit_code", "").strip() != "0":
            continue
        covers = record.values.get("covers", "")
        covered.update(item.strip() for item in re.split(r"[,;]", covers) if item.strip())
    missing = sorted(auto_finding_ids - covered)
    if missing:
        errors.append("apply verification does not cover auto-applied finding(s): " + ", ".join(missing))


def absent_authority_value(value: str) -> bool:
    return value.strip().casefold() in ABSENT_AUTHORITY_VALUES


def validate_apply_authority(header: dict[str, str], errors: list[str]) -> None:
    status = header.get("status", "")
    if status not in SUCCESS_STATUSES["apply"]:
        return
    for field in ("authority_grant", "authority_scope", "authority_source"):
        if absent_authority_value(header.get(field, "")):
            errors.append(f"{field} must record an actual authority value when apply status is {status}")
    if status == "pass":
        if absent_authority_value(header.get("commit", "")):
            errors.append("commit must record the created commit when apply status is pass")
        if header.get("changed_files") != "__list__":
            errors.append("changed_files must list at least one changed file when apply status is pass")


def validate_monitor_input_hashes(
    project_root: Path,
    text: str,
    header: dict[str, str],
    errors: list[str],
    *,
    verify_current_hashes: bool = False,
    required_policy_files: tuple[str, ...] = (),
) -> None:
    policy_paths: set[str] = set()
    unavailable_inputs = 0
    for field_name in ("source_registry_files", "policy_files"):
        records, record_errors = header_list_records(text, field_name)
        errors.extend(record_errors)
        if not records:
            errors.append(f"{field_name} must list at least one path and sha256 record")
            continue
        for record in records:
            path_value = record.values.get("path", "").strip()
            if field_name == "policy_files" and path_value:
                policy_paths.add(path_value)
            digest = record.values.get("sha256", "").strip()
            if not path_value:
                errors.append(f"{field_name} item at line {record.line_no} missing path")
                continue
            rel_path = Path(path_value)
            if not safe_relative_path_text(path_value):
                errors.append(f"{field_name} item at line {record.line_no} has invalid path: {path_value}")
            if digest == "unavailable":
                unavailable_inputs += 1
                if not record.values.get("reason", "").strip():
                    errors.append(f"{field_name} item at line {record.line_no} uses unavailable sha256 without reason")
                continue
            if not SHA256_RE.match(digest):
                errors.append(f"{field_name} item at line {record.line_no} has invalid sha256")
                continue
            if verify_current_hashes and safe_relative_path_text(path_value):
                target = project_root / rel_path
                if not safe_paths.path_within_root(target, project_root):
                    errors.append(f"{field_name} item at line {record.line_no} escapes repository root")
                elif not target.exists():
                    errors.append(f"{field_name} item at line {record.line_no} does not exist: {path_value}")
                else:
                    try:
                        actual_digest = file_sha256(target)
                    except (OSError, ValueError) as exc:
                        errors.append(
                            f"{field_name} item at line {record.line_no} cannot be hashed safely: {exc}"
                        )
                    else:
                        if actual_digest != digest:
                            errors.append(
                                f"{field_name} item at line {record.line_no} sha256 does not match current file"
                            )
    if unavailable_inputs and header.get("status") in {"pass", "no-findings"}:
        errors.append(
            "successful monitor artifacts cannot use unavailable source or policy input hashes"
        )
    if verify_current_hashes and required_policy_files:
        required_local_policy_files: set[str] = set()
        for policy_file in required_policy_files:
            if not safe_relative_path_text(policy_file):
                errors.append(
                    "required local monitor policy input must be a safe repo-relative "
                    f"path: {policy_file}"
                )
                continue
            required_local_policy_files.add(policy_file)
        missing_policy_files = sorted(required_local_policy_files - policy_paths)
        if missing_policy_files:
            errors.append(
                "policy_files is missing required local monitor policy inputs: "
                + ", ".join(missing_policy_files)
            )
        for policy_file in missing_policy_files:
            try:
                read_artifact_bytes(
                    project_root / policy_file,
                    description="required local monitor policy input",
                )
            except (OSError, ValueError) as exc:
                errors.append(
                    f"required local monitor policy input cannot be read safely: {policy_file}: {exc}"
                )


def validate_apply_changed_files(
    project_root: Path,
    text: str,
    header: dict[str, str],
    errors: list[str],
    artifact_cache: ArtifactSnapshotCache,
) -> None:
    if header.get("status") != "pass" or header.get("input_review_state") != "resolved":
        return
    changed_files, changed_errors = header_list_values(text, "changed_files")
    errors.extend(changed_errors)
    review_path = find_artifact_reference(
        project_root,
        header.get("input_review_artifact", ""),
        artifact_cache=artifact_cache,
    )
    if review_path is None:
        return
    try:
        review_text = cached_artifact_text(
            review_path,
            artifact_cache,
            description="review predecessor artifact",
        )
    except (OSError, UnicodeError, ValueError):
        return
    auto_files = auto_eligible_decision_files(review_text)
    for changed_file in changed_files:
        if not safe_relative_path_text(changed_file):
            errors.append(f"changed_files contains invalid path: {changed_file}")
            continue
        if changed_file not in auto_files:
            errors.append(f"changed_files item is not covered by an auto-eligible review finding: {changed_file}")


def artifact_validation_option_errors(
    stage: str | None,
    *,
    verify_current_input_hashes: bool,
    verify_decision_hashes: bool,
    required_policy_files: tuple[str, ...],
) -> list[str]:
    """Reject validation options that cannot perform their advertised proof."""

    errors: list[str] = []
    if verify_current_input_hashes and stage is not None and stage != "monitor":
        errors.append("--verify-current-input-hashes is valid only for stage monitor")
    if verify_decision_hashes and stage is not None and stage != "review":
        errors.append("--verify-decision-hashes is valid only for stage review")
    if required_policy_files and stage is not None and stage != "monitor":
        errors.append("--required-policy-file is valid only for stage monitor")
    if required_policy_files and not verify_current_input_hashes:
        errors.append(
            "--required-policy-file requires --verify-current-input-hashes"
        )
    return errors


def validate_artifact(
    path: Path,
    expected_stage: str | None = None,
    *,
    project_root: Path,
    artifact_bytes: bytes | None = None,
    verify_current_input_hashes: bool = False,
    verify_decision_hashes: bool = False,
    required_policy_files: tuple[str, ...] = (),
    expected_model_route: str | None = None,
    expected_model_label: str | None = None,
    expected_reasoning_effort: str | None = None,
    expected_execution_mode: str | None = None,
    expected_timezone: str | None = None,
    auto_apply_path_prefixes: tuple[str, ...] = (),
    _artifact_cache: ArtifactSnapshotCache | None = None,
) -> dict[str, object]:
    project_root = artifact_snapshot_key(project_root)
    root_errors = selected_project_root_errors(project_root)
    if root_errors:
        return {"path": str(path), "stage": expected_stage, "errors": root_errors}
    prefix_errors = auto_apply_path_prefix_errors(auto_apply_path_prefixes)
    if prefix_errors:
        return {"path": str(path), "stage": expected_stage, "errors": prefix_errors}
    path_scope_errors = artifact_path_scope_errors(path, project_root)
    if path_scope_errors:
        return {
            "path": str(path),
            "stage": expected_stage,
            "errors": path_scope_errors,
        }
    path = project_artifact_path(path, project_root)
    artifact_cache = {} if _artifact_cache is None else _artifact_cache
    try:
        if artifact_bytes is None:
            raw = cached_artifact_bytes(
                path,
                artifact_cache,
                description="source-chain artifact",
            )
        elif not isinstance(artifact_bytes, bytes):
            raise ValueError("preloaded source-chain artifact must be immutable bytes")
        else:
            raw = bytes(artifact_bytes)
            cache_key = artifact_snapshot_key(path)
            cached = artifact_cache.get(cache_key)
            if cached is not None:
                if cached.read_error is not None or cached.raw != raw:
                    raise ValueError(
                        "preloaded source-chain artifact disagrees with its validation snapshot"
                    )
            else:
                artifact_cache[cache_key] = ArtifactSnapshot(raw=raw)
        if len(raw) > ARTIFACT_MAX_BYTES:
            raise ValueError(
                "preloaded source-chain artifact exceeds the "
                f"{ARTIFACT_MAX_BYTES}-byte input limit"
            )
        text = raw.decode("utf-8")
    except (OSError, UnicodeError, ValueError) as exc:
        return {"path": str(path), "stage": expected_stage, "errors": [f"cannot read artifact: {exc}"]}
    header, _header_end, errors, duplicate_fields = _read_header(text)
    if "stage" in duplicate_fields and expected_stage is None:
        return {"path": str(path), "stage": None, "errors": errors}
    stage = expected_stage or header.get("stage", "")
    if stage not in STAGE_REQUIRED_FIELDS:
        errors.append(f"stage must be one of {', '.join(sorted(STAGE_REQUIRED_FIELDS))}")
        return {"path": str(path), "stage": stage or None, "errors": errors}
    errors.extend(
        artifact_validation_option_errors(
            stage,
            verify_current_input_hashes=verify_current_input_hashes,
            verify_decision_hashes=verify_decision_hashes,
            required_policy_files=required_policy_files,
        )
    )
    if "stage" not in duplicate_fields and header.get("stage") and header["stage"] != stage:
        errors.append(f"stage mismatch: expected {stage}, header has {header['stage']}")
    allowed_header_fields = (
        STAGE_REQUIRED_FIELDS[stage] | PUBLIC_CONTRACT_OPTIONAL_FIELDS[stage]
    )
    present_header_fields = set(header) | duplicate_fields
    unknown = sorted(present_header_fields - allowed_header_fields)
    if unknown:
        errors.append(f"unknown header fields: {', '.join(unknown)}")
    missing = sorted(STAGE_REQUIRED_FIELDS[stage] - present_header_fields)
    if missing:
        errors.append(f"missing header fields: {', '.join(missing)}")
    for field in STAGE_REQUIRED_FIELDS[stage]:
        if field in header and field not in duplicate_fields and not header[field].strip():
            errors.append(f"header field {field} must not be empty")
    if duplicate_fields:
        return {"path": str(path), "stage": stage, "errors": errors}
    validate_common_header(header, stage, errors)
    if expected_model_route is not None and header.get("model_route") != expected_model_route:
        errors.append(
            f"model_route must match the expected route {expected_model_route}"
        )
    expected_execution_identity = {
        "model_label": expected_model_label,
        "reasoning_effort": expected_reasoning_effort,
        "execution_mode": expected_execution_mode,
    }
    for field_name, expected_value in expected_execution_identity.items():
        if expected_value is not None and header.get(field_name) != expected_value:
            errors.append(f"{field_name} must match the expected value {expected_value}")
    if expected_timezone is not None and header.get("timezone") != expected_timezone:
        errors.append(f"timezone must match the expected timezone {expected_timezone}")
    if not validate_current_artifact_path(path, project_root, header, stage, errors):
        return {"path": str(path), "stage": stage, "errors": errors}
    validate_external_reviewer_status(header, errors)
    validate_external_reviewer_packet(project_root, header, errors)
    if not validate_predecessors(
        project_root,
        header,
        stage,
        errors,
        artifact_cache,
        auto_apply_path_prefixes,
    ):
        return {"path": str(path), "stage": stage, "errors": errors}
    unresolved_access_urls = validate_inaccessible_sources(text, header, stage, errors)
    validate_source_root_coverage(
        project_root,
        text,
        header,
        stage,
        errors,
        verify_current_input_hashes=verify_current_input_hashes,
    )
    if stage == "review":
        unresolved_access_urls |= predecessor_unresolved_inaccessible_urls(
            project_root,
            header,
            "monitor",
            artifact_cache,
        )
        if header.get("status") == "no-findings" and unresolved_access_urls:
            errors.append("review status no-findings is invalid with unresolved inaccessible sources")
    if stage == "assurance":
        predecessor_unresolved_access_urls = (
            predecessor_unresolved_inaccessible_urls(
                project_root,
                header,
                "monitor",
                artifact_cache,
            )
            | predecessor_unresolved_inaccessible_urls(
                project_root,
                header,
                "review",
                artifact_cache,
            )
        )
        if unresolved_access_urls != predecessor_unresolved_access_urls:
            errors.append(
                "assurance unresolved inaccessible source blocks must exactly reconcile "
                "resolved monitor and review predecessor gaps"
            )
    if stage == "review":
        accepted_count = parse_int_field(header, "accepted_findings", errors)
        manual_count = parse_int_field(header, "manual_findings", errors)
        validate_review_decisions(
            text,
            accepted_count,
            manual_count,
            errors,
            unresolved_access_urls,
            verify_decision_hashes=verify_decision_hashes,
            require_section=accepted_count > 0,
            section_only=True,
            auto_apply_path_prefixes=auto_apply_path_prefixes,
        )
        parse_int_field(header, "rejected_findings", errors)
    elif stage == "apply":
        validate_apply_authority(header, errors)
        validate_apply_verification(text, errors, require_successful=header.get("status") in SUCCESS_STATUSES["apply"])
        validate_apply_verification_coverage(
            project_root,
            text,
            header,
            errors,
            artifact_cache,
        )
        validate_apply_changed_files(
            project_root,
            text,
            header,
            errors,
            artifact_cache,
        )
    elif stage == "assurance":
        parse_int_field(header, "unresolved_findings", errors)
        apply_header = predecessor_header(project_root, header, "apply", artifact_cache)
        apply_commit = apply_header.get("commit", "")
        if apply_commit and apply_commit not in {"none", "unavailable"}:
            latest_commit = header.get("latest_commit", "")
            expected_latest_commit = latest_commit_from_apply_field(apply_commit)
            if latest_commit != expected_latest_commit:
                errors.append("latest_commit must match resolved apply commit when apply recorded a commit")
    elif stage == "monitor":
        validate_enum_field(header, "source_status", MONITOR_SOURCE_STATUSES, errors)
        source_status = header.get("source_status", "")
        expected_source_statuses = MONITOR_SOURCE_STATUS_BY_STATUS.get(header.get("status", ""), set())
        if source_status in MONITOR_SOURCE_STATUSES and expected_source_statuses and source_status not in expected_source_statuses:
            errors.append(
                f"source_status {source_status} is inconsistent with monitor status {header.get('status')}: "
                + ", ".join(sorted(expected_source_statuses))
            )
        validate_enum_field(header, "workspace_status", MONITOR_WORKSPACE_STATUSES, errors)
        validate_monitor_input_hashes(
            project_root,
            text,
            header,
            errors,
            verify_current_hashes=verify_current_input_hashes,
            required_policy_files=required_policy_files,
        )
    return {"path": str(path), "stage": stage, "errors": errors}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Lint source-monitor/review/apply/assurance chain artifacts.",
        allow_abbrev=False,
    )
    parser.add_argument("artifact", type=Path, nargs="+", help="Artifact file to lint.")
    parser.add_argument(
        "--project-root",
        type=Path,
        help="Explicit project root that owns the selected review_artifacts tree.",
    )
    parser.add_argument("--stage", choices=sorted(STAGE_REQUIRED_FIELDS), help="Expected stage for all artifacts.")
    parser.add_argument(
        "--verify-current-input-hashes",
        action="store_true",
        help="For monitor artifacts, compare recorded source/policy hashes against current files.",
    )
    parser.add_argument(
        "--verify-decision-hashes",
        action="store_true",
        help="For review artifacts, compare finding_hash values against canonical decision hashes.",
    )
    parser.add_argument(
        "--prepare-decision-hashes",
        action="store_true",
        help=(
            "Emit canonical review-decision payloads and proposed finding hashes without "
            "validating the surrounding chain artifact or modifying files."
        ),
    )
    parser.add_argument(
        "--required-policy-file",
        action="append",
        default=[],
        help="For monitor artifacts with --verify-current-input-hashes, require this policy path in policy_files.",
    )
    parser.add_argument(
        "--expected-model-route",
        help="Expected route id supplied by the owning trigger authority.",
    )
    parser.add_argument(
        "--expected-model-label",
        help="Optional exact runtime model label supplied by the owning trigger authority.",
    )
    parser.add_argument(
        "--expected-reasoning-effort",
        help="Optional exact reasoning-effort setting supplied by the owning trigger authority.",
    )
    parser.add_argument(
        "--expected-execution-mode",
        help="Optional exact execution-mode setting supplied by the owning trigger authority.",
    )
    parser.add_argument(
        "--expected-timezone",
        help="Expected IANA timezone supplied by the owning trigger authority.",
    )
    args = parser.parse_args(argv)

    if args.prepare_decision_hashes:
        if args.stage not in {None, "review"}:
            parser.error("--prepare-decision-hashes accepts only --stage review")
        incompatible = (
            args.verify_current_input_hashes
            or args.verify_decision_hashes
            or bool(args.required_policy_file)
            or any(
                value is not None
                for value in (
                    args.expected_model_route,
                    args.expected_model_label,
                    args.expected_reasoning_effort,
                    args.expected_execution_mode,
                    args.expected_timezone,
                )
            )
        )
        if incompatible:
            parser.error(
                "--prepare-decision-hashes cannot be combined with chain-validation or expected-identity options"
            )
        prepared_reports = [prepare_decision_hashes(path) for path in args.artifact]
        print(
            json.dumps(
                {"artifacts": prepared_reports, "mode": "prepare_decision_hashes"},
                indent=2,
                sort_keys=True,
            )
        )
        return 1 if any(report["errors"] for report in prepared_reports) else 0

    option_errors = artifact_validation_option_errors(
        args.stage,
        verify_current_input_hashes=args.verify_current_input_hashes,
        verify_decision_hashes=args.verify_decision_hashes,
        required_policy_files=tuple(args.required_policy_file),
    )
    if option_errors:
        parser.error("; ".join(option_errors))

    if args.expected_model_route is None:
        parser.error("--expected-model-route is required for artifact validation")
    if args.expected_timezone is None:
        parser.error("--expected-timezone is required for artifact validation")
    if args.project_root is None:
        parser.error("--project-root is required for artifact validation")

    reports = [
        validate_artifact(
            path,
            args.stage,
            project_root=args.project_root,
            verify_current_input_hashes=args.verify_current_input_hashes,
            verify_decision_hashes=args.verify_decision_hashes,
            required_policy_files=tuple(args.required_policy_file),
            expected_model_route=args.expected_model_route,
            expected_model_label=args.expected_model_label,
            expected_reasoning_effort=args.expected_reasoning_effort,
            expected_execution_mode=args.expected_execution_mode,
            expected_timezone=args.expected_timezone,
        )
        for path in args.artifact
    ]
    print(json.dumps({"artifacts": reports}, indent=2, sort_keys=True))
    return 1 if any(report["errors"] for report in reports) else 0


if __name__ == "__main__":
    raise SystemExit(main())
