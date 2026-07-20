#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import markdown_structure
import safe_paths
import url_safety


MARKER_RE = re.compile(
    r"^(REVIEWER_LANE_USED|REVIEWER_LANE_SKIPPED|REVIEWER_FINDING_ACCEPTED|REVIEWER_FINDING_REJECTED|LANE_FIT_OBSERVATION)\s+(\{.*\})$"
)
LANE_RE = re.compile(r"^## Lane: ([a-z0-9_./-]+)\s*$")
FIELD_RE = re.compile(r"^(Runtime Class|Evidence Basis|Confidence):\s*(.+)$")

LANE_CLASSES = {
    "bounded_wrapper",
    "deep_research",
    "deterministic_script",
    "external_chat",
    "human",
    "local_coordinator",
    "local_subagent",
    "other",
}
EVIDENCE_BASES = {
    "design-judgment",
    "public-source-backed",
    "repeated-across-projects",
    "repeated-in-project",
    "single-observation",
}
CONFIDENCE = {"low", "medium", "high"}
REASON_CATEGORIES = {
    "budget",
    "duplicate",
    "duplicative",
    "incorrect",
    "not_actionable",
    "not_needed",
    "other",
    "out_of_scope",
    "privacy_risk",
    "time",
    "too_broad",
    "unavailable",
    "unsafe",
    "unsupported",
}
CLAIM_TYPES = {
    "avoid_task",
    "failure_mode",
    "ideal_task",
    "limit",
    "orchestration",
    "prompt_quality",
    "routing_change",
    "source_monitoring",
    "strength",
}

REQUIRED_FIELDS = {
    "REVIEWER_LANE_USED": {
        "lane_id",
        "task_ref",
        "lane_class",
        "purpose",
        "output_ref",
        "evidence_refs",
    },
    "REVIEWER_LANE_SKIPPED": {"lane_id", "task_ref", "reason_category", "reason"},
    "REVIEWER_FINDING_ACCEPTED": {
        "finding_id",
        "source_lane_id",
        "evidence_ref",
        "action_ref",
        "reason",
    },
    "REVIEWER_FINDING_REJECTED": {
        "finding_id",
        "source_lane_id",
        "evidence_ref",
        "reason_category",
        "reason",
    },
    "LANE_FIT_OBSERVATION": {
        "lane_id",
        "task_ref",
        "claim_type",
        "claim",
        "evidence_refs",
        "routing_implication",
        "confidence",
    },
}

MAX_FIELD_LENGTHS = {
    "claim": 260,
    "purpose": 140,
    "reason": 220,
    "routing_implication": 260,
}
REVIEWER_FEEDBACK_MAX_BYTES = 1024 * 1024

REFERENCE_FIELDS = {"action_ref", "evidence_ref", "evidence_refs", "output_ref"}

LOCAL_AGENT_LOG_DIR_RE = r"\." + "codex"
PRIMARY_EVIDENCE_DENY = re.compile(
    rf"(^|/)(?:{LOCAL_AGENT_LOG_DIR_RE}|raw_logs?|transcripts?|browser_history)(?:/|$)",
    re.IGNORECASE,
)
LEAK_PATTERNS = (
    ("host path", safe_paths.LOCAL_ABSOLUTE_PATH_RE),
    ("email address", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)),
    (
        "private URL",
        re.compile(
            r"https?://(?:localhost|127\.0\.0\.1|10\.|192\.168\.|172\.(?:1[6-9]|2[0-9]|3[01])\.|[^/\s]+\.(?:local|internal|corp|lan)\b)",
            re.IGNORECASE,
        ),
    ),
    ("environment assignment", re.compile(r"\b[A-Z][A-Z0-9_]{2,}=")),
    ("long token", re.compile(r"\b[A-Za-z0-9_-]{40,}\b")),
)
ANTI_BENCHMARK_PATTERNS = (
    re.compile(r"\bbest model\b", re.IGNORECASE),
    re.compile(r"\bwinner\b", re.IGNORECASE),
    re.compile(r"\bbeats\b", re.IGNORECASE),
    re.compile(r"\branking\b", re.IGNORECASE),
    re.compile(r"\bsmarter than\b", re.IGNORECASE),
    re.compile(r"\balways use\b", re.IGNORECASE),
    re.compile(r"\bvotes?\b", re.IGNORECASE),
    re.compile(r"\bvoting\b", re.IGNORECASE),
    re.compile(r"\bmodel[- ]comparison\b", re.IGNORECASE),
    re.compile(r"\b\d+\s*[-:]\s*\d+\s+(?:majority|vote|split|tally)\b", re.IGNORECASE),
    re.compile(r"\b\d+\s+to\s+\d+\s+(?:majority|vote|split|tally)\b", re.IGNORECASE),
    re.compile(r"\b(?:majority|consensus|agreed|agreement)\b.{0,80}\b(?:model|agent|reviewer|lane|routing)\b", re.IGNORECASE),
    re.compile(r"\b(?:model|agent|reviewer|lane)\b.{0,80}\b(?:majority|consensus|agreed|agreement)\b", re.IGNORECASE),
    re.compile(r"\b[A-Z][A-Za-z0-9_. -]{1,40}\s+found\s+more\s+(?:issues|findings)\b", re.IGNORECASE),
    re.compile(r"\bmore\s+(?:issues|findings)\s+than\b", re.IGNORECASE),
)
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Lint optional REVIEWER_LANE_FEEDBACK.md files and marker ledgers.",
        allow_abbrev=False,
    )
    parser.add_argument(
        "--path",
        default="REVIEWER_LANE_FEEDBACK.md",
        help="Reviewer lane feedback file to lint. Missing files are accepted.",
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Root used to resolve relative evidence references.",
    )
    return parser


def non_fenced_lines(text: str) -> list[tuple[int, str]]:
    return list(markdown_structure.operative_lines(text))


def all_lines(text: str) -> list[tuple[int, str]]:
    return list(enumerate(text.splitlines(), start=1))


def scan_forbidden_text(line_number: int, text: str, errors: list[str]) -> None:
    stripped = text.strip()
    for label, pattern in LEAK_PATTERNS:
        if pattern.search(stripped):
            errors.append(f"line {line_number}: possible {label} in reviewer lane feedback")
    for pattern in ANTI_BENCHMARK_PATTERNS:
        if pattern.search(stripped):
            errors.append(f"line {line_number}: anti-benchmark wording is not allowed: {pattern.pattern}")


def as_str(value: Any) -> str:
    return value if isinstance(value, str) else ""


def validate_ref(ref: str, root: Path, line_number: int, errors: list[str]) -> None:
    if not ref:
        errors.append(f"line {line_number}: empty evidence reference")
        return
    if PRIMARY_EVIDENCE_DENY.search(ref):
        errors.append(f"line {line_number}: raw logs or transcripts cannot be primary evidence: {ref}")
        return
    if ref.startswith("http://"):
        errors.append(f"line {line_number}: external evidence reference must use https: {ref}")
        return
    if ref.startswith("https://"):
        blocked = url_safety.blocked_external_url_reason(ref, resolve_hostname=False)
        if blocked:
            errors.append(f"line {line_number}: unsafe external evidence reference: {blocked}: {ref}")
        return
    path_part = ref.split("#", 1)[0]
    if not path_part:
        errors.append(f"line {line_number}: evidence reference must include a path before any anchor")
        return
    try:
        normalized = safe_paths.normalize_repo_relative_path(
            path_part,
            root.resolve(strict=False),
            description="evidence reference",
        )
    except ValueError as exc:
        errors.append(f"line {line_number}: {exc}")
        return
    candidate = root.resolve(strict=False) / normalized
    try:
        safe_paths.read_regular_file_bytes(
            candidate,
            description="reviewer feedback evidence reference",
        )
    except FileNotFoundError:
        errors.append(f"line {line_number}: evidence reference does not exist: {ref}")
    except (OSError, ValueError) as exc:
        errors.append(
            f"line {line_number}: evidence reference must be a stable bounded regular file: {ref}: {exc}"
        )


def validate_single_ref(value: Any, root: Path, line_number: int, field_name: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"line {line_number}: {field_name} must be a non-empty string reference")
        return
    validate_ref(value, root, line_number, errors)


def validate_refs(value: Any, root: Path, line_number: int, errors: list[str]) -> None:
    if isinstance(value, list) and value:
        for ref in value:
            if not isinstance(ref, str):
                errors.append(f"line {line_number}: evidence_refs entries must be strings")
                continue
            validate_ref(ref, root, line_number, errors)
        return
    errors.append(f"line {line_number}: evidence_refs must be a non-empty list")


def validate_marker(
    marker: str,
    payload: dict[str, Any],
    root: Path,
    line_number: int,
    used_or_skipped: dict[str, str],
    accepted: set[str],
    rejected: set[str],
    errors: list[str],
) -> None:
    allowed = REQUIRED_FIELDS[marker]
    unknown = sorted(set(payload) - allowed)
    if unknown:
        errors.append(f"line {line_number}: {marker} has unknown fields: {', '.join(unknown)}")

    missing = sorted(REQUIRED_FIELDS[marker] - set(payload))
    if missing:
        errors.append(f"line {line_number}: {marker} missing fields: {', '.join(missing)}")

    for field_name in sorted(REQUIRED_FIELDS[marker] - REFERENCE_FIELDS):
        value = payload.get(field_name)
        if not isinstance(value, str) or not value.strip():
            errors.append(
                f"line {line_number}: {marker} field {field_name} must be a non-empty string"
            )

    lane_id = as_str(payload.get("lane_id") or payload.get("source_lane_id"))
    if lane_id and not re.fullmatch(r"[a-z0-9_./-]{2,80}", lane_id):
        errors.append(f"line {line_number}: invalid lane id: {lane_id}")

    for key, limit in MAX_FIELD_LENGTHS.items():
        value = payload.get(key)
        if isinstance(value, str) and len(value) > limit:
            errors.append(f"line {line_number}: field {key!r} exceeds {limit} characters")

    if marker == "REVIEWER_LANE_USED":
        if payload.get("lane_class") not in LANE_CLASSES:
            errors.append(f"line {line_number}: invalid lane_class: {payload.get('lane_class')}")
        if lane_id in used_or_skipped:
            errors.append(f"line {line_number}: duplicate used/skipped marker for lane {lane_id}")
        used_or_skipped[lane_id] = marker
        validate_single_ref(payload.get("output_ref"), root, line_number, "output_ref", errors)
        validate_refs(payload.get("evidence_refs"), root, line_number, errors)
    elif marker == "REVIEWER_LANE_SKIPPED":
        if payload.get("reason_category") not in REASON_CATEGORIES:
            errors.append(f"line {line_number}: invalid reason_category: {payload.get('reason_category')}")
        if lane_id in used_or_skipped:
            errors.append(f"line {line_number}: duplicate used/skipped marker for lane {lane_id}")
        used_or_skipped[lane_id] = marker
    elif marker == "REVIEWER_FINDING_ACCEPTED":
        finding_id = as_str(payload.get("finding_id"))
        if finding_id in accepted:
            errors.append(f"line {line_number}: duplicate accepted finding id: {finding_id}")
        if finding_id in rejected:
            errors.append(f"line {line_number}: finding is both accepted and rejected: {finding_id}")
        accepted.add(finding_id)
        validate_single_ref(payload.get("evidence_ref"), root, line_number, "evidence_ref", errors)
        validate_single_ref(payload.get("action_ref"), root, line_number, "action_ref", errors)
    elif marker == "REVIEWER_FINDING_REJECTED":
        if payload.get("reason_category") not in REASON_CATEGORIES:
            errors.append(f"line {line_number}: invalid reason_category: {payload.get('reason_category')}")
        finding_id = as_str(payload.get("finding_id"))
        if finding_id in rejected:
            errors.append(f"line {line_number}: duplicate rejected finding id: {finding_id}")
        if finding_id in accepted:
            errors.append(f"line {line_number}: finding is both accepted and rejected: {finding_id}")
        rejected.add(finding_id)
        validate_single_ref(payload.get("evidence_ref"), root, line_number, "evidence_ref", errors)
    elif marker == "LANE_FIT_OBSERVATION":
        if payload.get("claim_type") not in CLAIM_TYPES:
            errors.append(f"line {line_number}: invalid claim_type: {payload.get('claim_type')}")
        if payload.get("confidence") not in CONFIDENCE:
            errors.append(f"line {line_number}: invalid confidence: {payload.get('confidence')}")
        validate_refs(payload.get("evidence_refs"), root, line_number, errors)


def lint(
    path: Path,
    root: Path,
    *,
    text: str | None = None,
) -> dict[str, list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    resolved_root = root.resolve(strict=False)
    absolute_path = path.expanduser().absolute()
    try:
        absolute_path.relative_to(resolved_root)
    except ValueError:
        return {
            "errors": [f"{path.name}: reviewer feedback path must stay under the selected root"],
            "warnings": warnings,
        }
    if text is None:
        if path.is_symlink():
            return {
                "errors": [f"{path.name}: reviewer feedback file must not be a symlink"],
                "warnings": warnings,
            }
        try:
            raw = safe_paths.read_regular_file_bytes(
                path,
                description="reviewer feedback input",
                max_bytes=REVIEWER_FEEDBACK_MAX_BYTES,
            )
        except FileNotFoundError:
            return {"errors": errors, "warnings": warnings}
        except (OSError, ValueError) as exc:
            return {
                "errors": [f"{path.name}: reviewer feedback input rejected: {exc}"],
                "warnings": warnings,
            }
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            return {
                "errors": [f"{path.name}: reviewer feedback file must be valid UTF-8: {exc}"],
                "warnings": warnings,
            }

    try:
        byte_count = len(text.encode("utf-8"))
    except UnicodeEncodeError as exc:
        return {
            "errors": [f"{path.name}: reviewer feedback text is not valid UTF-8: {exc}"],
            "warnings": warnings,
        }
    if byte_count > REVIEWER_FEEDBACK_MAX_BYTES:
        return {
            "errors": [
                f"{path.name}: reviewer feedback input exceeds "
                f"{REVIEWER_FEEDBACK_MAX_BYTES} UTF-8 bytes"
            ],
            "warnings": warnings,
        }

    used_or_skipped: dict[str, str] = {}
    accepted: set[str] = set()
    rejected: set[str] = set()
    lanes: dict[str, dict[str, str]] = {}
    current_lane: str | None = None

    for line_number, raw in all_lines(text):
        scan_forbidden_text(line_number, raw, errors)

    for line_number, raw in non_fenced_lines(text):
        stripped = raw.strip()
        lane_match = LANE_RE.match(stripped)
        if lane_match:
            lane_id = lane_match.group(1)
            if lane_id is None:
                continue
            current_lane = lane_id
            if lane_id in lanes:
                errors.append(f"line {line_number}: duplicate lane section: {lane_id}")
            lanes[lane_id] = {}
            continue

        if current_lane is not None:
            field_match = FIELD_RE.match(stripped)
            if field_match:
                lanes[current_lane][field_match.group(1)] = field_match.group(2).strip()

        marker_match = MARKER_RE.match(stripped)
        if not marker_match:
            continue
        marker = marker_match.group(1)
        try:
            payload = safe_paths.loads_json_no_duplicates(marker_match.group(2))
        except (json.JSONDecodeError, ValueError) as exc:
            errors.append(f"line {line_number}: invalid marker JSON: {exc}")
            continue
        if not isinstance(payload, dict):
            errors.append(f"line {line_number}: marker payload must be a JSON object")
            continue
        validate_marker(
            marker,
            payload,
            root,
            line_number,
            used_or_skipped,
            accepted,
            rejected,
            errors,
        )

    for lane_id, fields in lanes.items():
        runtime_class = fields.get("Runtime Class")
        if runtime_class not in LANE_CLASSES:
            errors.append(f"lane {lane_id}: invalid or missing Runtime Class: {runtime_class}")
        evidence_basis = fields.get("Evidence Basis")
        if evidence_basis not in EVIDENCE_BASES:
            errors.append(f"lane {lane_id}: invalid or missing Evidence Basis: {evidence_basis}")
        confidence = fields.get("Confidence")
        if confidence not in CONFIDENCE:
            errors.append(f"lane {lane_id}: invalid or missing Confidence: {confidence}")

    return {"errors": errors, "warnings": warnings}


def main() -> int:
    args = build_parser().parse_args()
    root = Path(args.root).resolve()
    path = Path(args.path)
    if not path.is_absolute():
        path = root / path
    result = lint(path, root)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
