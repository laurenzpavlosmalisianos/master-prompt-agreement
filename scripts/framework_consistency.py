#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator

import conformance_check
import framework_contracts
import integration_registry
import markdown_structure
import routing_policy
import safe_paths
import source_chain_artifact_lint
import verification_registry


DEFAULT_REPO_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = DEFAULT_REPO_ROOT
WRAPPER_STATUSES = {"not-applicable", "candidate", "required"}
CLAUSE_ROW_FIELDS = {
    "dispositions",
    "notes",
    "operative_home",
    "projection_id",
    "source",
    "source_clause_ids",
    "target_markers",
}
PRACTICE_GUIDE_FIELDS = {"category", "name", "path", "trigger_flags", "wrapper_status"}
MSA_CLAUSE_ID_RE = re.compile(r"^(\d+(?:\.[0-9A-Za-z]+)+)\.\s")
MSA_ARTICLE_ID_RE = re.compile(r"^(Article \d+) — ")
WORKFLOW_EFFECT_ACTION_ID_RE = re.compile(
    r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$"
)
WORKFLOW_CATALOG_FIELDS = {
    "common_sequences",
    "schema_version",
    "task_orders",
    "workflow_selection",
}
WORKFLOW_SELECTION_FIELDS = {
    "ambiguous_workflow_route",
    "known_workflow_provenance",
}
WORKFLOW_AMBIGUOUS_ROUTE_FIELDS = {
    "conditions",
    "fallback_references",
    "forbidden_action",
    "required_action",
}
WORKFLOW_TASK_ORDER_FIELDS = {
    "accepted_evaluation_class_enum",
    "allowed_outcomes_by_mode",
    "category",
    "common_next_orders",
    "common_next_steps",
    "default_invocation_mode",
    "direct_full_when_flags",
    "effect_exclusions",
    "effect_owner",
    "effect_scope",
    "effect_state_by_outcome",
    "invocation_mode_enum",
    "mode_enum",
    "mode_next_steps",
    "name",
    "outcome_enum",
    "outcome_next_steps",
    "owned_effect_action_ids",
    "owned_effect_actions",
    "path",
    "primary_outputs",
    "produced_evaluation_class_enum",
    "runtime_task_module",
    "use_when",
    "vcs_precondition",
}
WORKFLOW_TASK_ORDER_REQUIRED_FIELDS = {
    "category",
    "common_next_orders",
    "name",
    "path",
    "primary_outputs",
    "runtime_task_module",
    "use_when",
}
WORKFLOW_RUNTIME_MODULE_FIELDS = {
    "canonical_task_order",
    "finding_schema",
    "name",
    "path",
    "use_full_when",
    "use_full_when_conditions",
}
WORKFLOW_RUNTIME_MODULE_REQUIRED_FIELDS = {
    "canonical_task_order",
    "name",
    "path",
    "use_full_when",
    "use_full_when_conditions",
}
WORKFLOW_ESCALATION_CONDITION_FIELDS = {
    "all_flags",
    "any_flags",
    "delegated_obligation_id",
    "description",
    "id",
}
WORKFLOW_COMMON_SEQUENCE_FIELDS = {
    "name",
    "outcome_branches",
    "ownership_scope",
    "steps",
    "when",
}
WORKFLOW_COMMON_SEQUENCE_REQUIRED_FIELDS = {"name", "steps", "when"}
WORKFLOW_STEP_FIELDS = {
    "action",
    "effect_action_id",
    "mode",
    "order",
    "outcome_branches",
    "requires",
    "requires_authorization",
    "scope",
}
MSA_DIGEST_ALGORITHM = (
    "sha256-v2-utf8-strict-crlf-cr-to-lf-line-rstrip-ascii-sp-htab-"
    "drop-terminal-empty-lines-single-final-lf"
)
FINDING_SCHEMA_FIELDS = {
    "category",
    "severity",
    "gate_effect",
    "evidence_status",
    "confidence",
    "verification_state",
    "disposition",
    "tool_output_classification",
}
FINDING_CATEGORY_VALUES = {
    "Bug",
    "Documentation",
    "Edge Case",
    "Performance",
    "Process",
    "Security",
    "Standards Violation",
    "Weakness",
}
FINDING_REPORT_FIELDS = FINDING_SCHEMA_FIELDS | {
    "actual_result",
    "expected_result",
    "file",
    "line",
    "probe_or_reproduction",
    "proposed_fix_or_test",
    "residual_risk",
}
WORKFLOW_CONTRACT_MARKER_RE = re.compile(
    r"^<!-- mpa-workflow-contract: (?P<payload>\{.*\}) -->$",
    re.MULTILINE,
)
WORKFLOW_CONTRACT_MARKER_PREFIX_RE = re.compile(
    r"^<!-- mpa-workflow-contract:",
    re.MULTILINE,
)
WORKFLOW_CONTRACT_ENUM_KEYS = (
    "outcome_enum",
    "mode_enum",
    "invocation_mode_enum",
)
FRAMEWORK_EVALUATION_CLASSES = [
    "objective-structural",
    "targeted-regression",
    "behavioral-matched",
    "rendered-semantic",
    "claim-grade",
]
FRAMEWORK_IMPROVEMENT_MODES = ["assess", "act"]
FRAMEWORK_IMPROVEMENT_OUTCOMES = [
    "ready-for-act",
    "retain",
    "revise",
    "revert",
    "needs-evidence",
    "no-action",
]
FRAMEWORK_IMPROVEMENT_OUTCOMES_BY_MODE = {
    "assess": ["ready-for-act", "needs-evidence", "no-action"],
    "act": ["retain", "revise", "revert", "needs-evidence", "no-action"],
}
FRAMEWORK_IMPROVEMENT_EFFECT_STATE_BY_OUTCOME = {
    "ready-for-act": "zero-effects",
    "retain": "accepted-effects-active",
    "revise": "authorized-effects-pending-revision",
    "revert": "restoration-required",
    "needs-evidence": "no-unaccepted-effects-active",
    "no-action": "zero-effects",
}
TASK_ORDER_EFFECT_SCOPE_BY_NAME = {
    "framework_improvement": "shared_or_reusable_framework_product",
    "source_update": "downstream_or_project_local",
    "backout": "authorized_restoration_scope",
}
IDEATE_OWNERSHIP_NEXT_STEPS = [
    {
        "action": "classify chosen direction ownership",
        "outcome_branches": {
            "downstream_or_project_local": [
                {
                    "order": "plan",
                    "requires": "planning is separately authorized",
                }
            ],
            "shared_or_reusable_framework": [
                {"order": "framework_semantic_audit"}
            ],
        },
    }
]
INDEPENDENT_ASSESSMENT_ACTIONABLE_NEXT_STEPS = [
    {
        "action": "classify validated assessment ownership",
        "outcome_branches": {
            "downstream_or_project_local": [
                {
                    "order": "plan",
                    "requires": (
                        "assessment validated and User or SOW authorization to proceed"
                    ),
                }
            ],
            "shared_or_reusable_framework": [
                {"order": "framework_semantic_audit"}
            ],
        },
    }
]
ARBITRATION_RATIFIED_NEXT_STEPS = [
    {
        "order": "commit",
        "scope": "decision_records_only",
        "requires_authorization": True,
        "requires": (
            "only the arbitration case file and ratified decision records are "
            "committed; no product implementation is implied"
        ),
    },
    {
        "action": "classify any implementation follow-up",
        "outcome_branches": {
            "no_implementation_follow_up": [],
            "active_framework_improvement": [
                {
                    "order": "framework_improvement",
                    "mode": "act",
                    "requires": (
                        "an accepted correction returns as revise within the bound "
                        "candidate and evaluation contract; a scope or class change "
                        "requires semantic re-audit"
                    ),
                }
            ],
            "shared_or_reusable_framework_outside_active_framework_improvement": [
                {"order": "framework_semantic_audit"}
            ],
            "downstream_or_project_local": [
                {
                    "action": "classify downstream or project-local implementation state",
                    "outcome_branches": {
                        "implementation_pending": [
                            {
                                "order": "plan",
                                "requires": "implementation planning is separately authorized",
                            }
                        ],
                        "verified_effect_ready_for_commit": [
                            {
                                "order": "commit",
                                "requires_authorization": True,
                                "requires": (
                                    "the exact downstream or project-local effect is "
                                    "already implemented, verified, reviewed, and audited "
                                    "under the project contract"
                                ),
                            }
                        ],
                    },
                }
            ],
        },
    },
]


def exact_schema_version(value: object, expected: int) -> bool:
    """Return true only for the exact JSON integer version requested."""

    return type(value) is int and value == expected


OBLIGATION_COVERAGE_STATUSES = {"delegates_to_full_order", "not_applicable", "satisfies"}
OBLIGATION_RISK_CLASSES = {"authority", "context", "cost", "quality", "security", "state", "verification"}
PROJECTION_ID_RE = re.compile(r"^msa-(?:article-[0-9]+|[0-9]+-[0-9]+)$")
FindingConstraint = tuple[
    tuple[tuple[str, tuple[str, ...]], ...],
    tuple[tuple[str, tuple[str, ...]], ...],
]


@dataclass(frozen=True)
class ConsistencyDocuments:
    contract: dict[str, Any]
    schedule: dict[str, Any]
    workflow_catalog: dict[str, Any]
    task_module_obligations: dict[str, Any]
    finding_schema: dict[str, Any]
    conformance_profiles: dict[str, Any]
    registry: dict[str, Any]
    clause_map: dict[str, Any]
    loaded: frozenset[str]


def marker(kind: str, marker_id: str) -> str:
    return f"<!-- {kind}: {marker_id} -->"


def bare_marker(marker_id: str) -> str:
    return f"<!-- {marker_id} -->"


def unknown_field_errors(label: str, value: dict[str, Any], allowed: set[str]) -> list[str]:
    unknown = sorted(set(value) - allowed)
    return [f"{label} has unknown fields: {', '.join(unknown)}"] if unknown else []


def string_list(
    value: object,
    label: str,
    errors: list[str],
    *,
    non_empty: bool = False,
) -> list[str]:
    if (
        not isinstance(value, list)
        or (non_empty and not value)
        or not all(isinstance(item, str) and item for item in value)
    ):
        qualifier = "non-empty " if non_empty else ""
        errors.append(f"{label} must be a {qualifier}string list")
        return []
    return value


def run_validation_phase(
    label: str,
    errors: list[str],
    validation: Callable[[], None],
) -> None:
    """Serialize malformed validator inputs instead of escaping the JSON protocol."""

    try:
        validation()
    except (
        AttributeError,
        KeyError,
        OSError,
        RecursionError,
        TypeError,
        ValueError,
    ) as exc:
        errors.append(f"{label} input shape is invalid: {exc}")


def operative_prose(text: str) -> str:
    """Return whitespace-normalized prose with non-operative HTML comments removed."""
    return " ".join(re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL).split())


def validate_operative_anchor(
    raw_anchor: Any,
    prose: str,
    label: str,
    errors: list[str],
    anchor_name: str = "operative_anchor",
) -> None:
    """Require one non-empty exact prose anchor, not a metadata-only marker."""
    if not isinstance(raw_anchor, str):
        errors.append(f"{label} must define {anchor_name}")
        return
    anchor = " ".join(raw_anchor.split())
    if not anchor or "<!--" in anchor or "-->" in anchor:
        errors.append(
            f"{label} {anchor_name} must be non-empty operative prose without HTML comments"
        )
        return
    occurrences = prose.count(anchor)
    if occurrences == 0:
        errors.append(f"{label} missing operative anchor from prose")
    elif occurrences > 1:
        errors.append(f"{label} operative anchor must identify exactly one prose location")


def projection_marker_exists(text: str, projection_id: str) -> bool:
    token = re.escape(projection_id)
    return bool(
        re.search(
            rf"<!--\s*mpa-clause-projections:\s*[^>]*(?<![A-Za-z0-9_-]){token}(?![A-Za-z0-9_-])[^>]*-->",
            text,
        )
        or marker("mpa-clause-projection", projection_id) in text
    )
ARBITRATION_OUTCOMES = {
    "validated_recommendation",
    "ratified_decision",
    "no_majority_no_decision",
    "insufficient_evidence_no_decision",
    "abstain_no_decision",
}
ARBITRATION_NO_DECISION_OUTCOMES = {
    "no_majority_no_decision",
    "insufficient_evidence_no_decision",
    "abstain_no_decision",
}
ARBITRATION_NO_DECISION_ACTIONS = {
    "collect missing evidence",
    "reconstitute panel",
    "request User or SOW owner decision",
}
REQUIRED_FINDING_CONSTRAINTS = (
    (
        {"evidence_status": "Unresolved hypothesis"},
        {"disposition": ["Open probe", "Candidate follow-up"]},
    ),
    (
        {"disposition": "Finding"},
        {
            "evidence_status": ["Confirmed", "Reproduced", "Source-backed"],
            "severity": ["Critical", "High", "Medium", "Low"],
            "gate_effect": ["Blocks acceptance", "Blocks release or deploy", "Follow-up required", "Advisory"],
        },
    ),
    (
        {"disposition": "Accepted exception"},
        {
            "evidence_status": ["Confirmed", "Reproduced", "Source-backed"],
            "severity": ["Critical", "High", "Medium", "Low"],
            "gate_effect": ["Accepted risk"],
        },
    ),
    (
        {"disposition": ["False positive", "Rejected"]},
        {"severity": ["Not applicable"], "gate_effect": ["No gate effect"]},
    ),
)


def resolve_repo_file(rel: object, errors: list[str], label: str) -> Path | None:
    if not isinstance(rel, str):
        errors.append(f"{label} path must be a string")
        return None
    try:
        normalized = safe_paths.normalize_repo_relative_path(
            rel,
            REPO_ROOT,
            description=f"{label} path",
        )
    except (OSError, RuntimeError, ValueError) as exc:
        errors.append(str(exc))
        return None
    return REPO_ROOT / normalized


def _read_repo_text_optional(
    rel: object,
    errors: list[str],
    label: str,
) -> str | None:
    path = resolve_repo_file(rel, errors, label)
    if path is None:
        return None
    try:
        raw = safe_paths.read_regular_file_bytes(path, description=f"{label} input")
    except FileNotFoundError:
        errors.append(f"{label} is missing: {rel}")
        return None
    except ValueError as exc:
        errors.append(f"{label} input is unsafe: {exc}")
        return None
    except OSError as exc:
        errors.append(f"{label} could not be read: {exc}")
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        errors.append(f"{label} must be valid UTF-8: {exc}")
        return None


def load_json(
    rel: str,
    errors: list[str],
    label: str | None = None,
) -> dict[str, Any] | None:
    document_label = label or rel
    text = _read_repo_text_optional(rel, errors, document_label)
    if text is None:
        return None
    try:
        data = safe_paths.loads_json_no_duplicates(text)
    except (RecursionError, ValueError) as exc:
        errors.append(f"{document_label} is invalid JSON: {exc}")
        return None
    if not isinstance(data, dict):
        errors.append(f"{document_label} must be a JSON object")
        return None
    return data


def load_integration_registry(errors: list[str]) -> dict[str, Any] | None:
    registry = load_json(
        "integrations/registry.json",
        errors,
        "integration registry",
    )
    if registry is None:
        return None
    try:
        return integration_registry.validate_registry(registry, REPO_ROOT)
    except (
        AttributeError,
        KeyError,
        OSError,
        RecursionError,
        TypeError,
        ValueError,
    ) as exc:
        errors.append(f"integration registry is invalid: {exc}")
        return None


def read_repo_text(rel: object, errors: list[str], label: str) -> str:
    return _read_repo_text_optional(rel, errors, label) or ""


def msa_version(errors: list[str]) -> str:
    text = _read_repo_text_optional(
        "master_service_agreement.md",
        errors,
        "MSA version",
    )
    if text is None:
        return ""
    match = re.search(r"^Version:\s*([0-9]+\.[0-9]+\.[0-9]+)\b", text, re.MULTILINE)
    if not match:
        errors.append("MSA version header missing or malformed")
        return ""
    return match.group(1)


def normalize_msa_digest_input(raw: bytes) -> bytes:
    """Return the byte-exact canonical MSA digest input."""

    text = raw.decode("utf-8", errors="strict")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip(" \t") for line in normalized.split("\n")]
    while lines and lines[-1] == "":
        lines.pop()
    return ("\n".join(lines) + "\n").encode("utf-8", errors="strict")


def normalized_bytes_digest(raw: bytes) -> str:
    return hashlib.sha256(normalize_msa_digest_input(raw)).hexdigest()


def normalized_text_digest(text: str) -> str:
    return normalized_bytes_digest(text.encode("utf-8", errors="strict"))


def normalized_file_digest(path: Path) -> str:
    raw = safe_paths.read_regular_file_bytes(
        path,
        description=f"normalized digest input {path.name}",
    )
    return normalized_bytes_digest(raw)


def msa_clause_ids(errors: list[str] | None = None) -> list[str]:
    diagnostics = [] if errors is None else errors
    text = _read_repo_text_optional(
        "master_service_agreement.md",
        diagnostics,
        "MSA clause inventory",
    )
    if text is None:
        return []
    ids: list[str] = []
    for _line_number, line in markdown_structure.operative_lines(text):
        article_match = MSA_ARTICLE_ID_RE.match(line)
        if article_match:
            ids.append(article_match.group(1))
            continue
        clause_match = MSA_CLAUSE_ID_RE.match(line)
        if clause_match:
            ids.append(clause_match.group(1))
    return ids


def validate_msa_digest(clause_map: dict[str, Any], errors: list[str]) -> None:
    if clause_map.get("msa_digest_algorithm") != MSA_DIGEST_ALGORITHM:
        errors.append(
            "clause map msa_digest_algorithm is unsupported; expected "
            f"{MSA_DIGEST_ALGORITHM}"
        )
        return
    expected = clause_map.get("msa_digest_sha256")
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
        errors.append("clause map msa_digest_sha256 is required")
        return
    text = _read_repo_text_optional(
        "master_service_agreement.md",
        errors,
        "MSA digest source",
    )
    if text is None:
        return
    actual = normalized_text_digest(text)
    if expected != actual:
        errors.append("clause map msa_digest_sha256 does not match master_service_agreement.md")


def validate_clause_id_coverage(clause_rows: list[dict[str, Any]], errors: list[str]) -> None:
    expected = set(msa_clause_ids(errors))
    observed: dict[str, str] = {}
    duplicates: dict[str, list[str]] = {}
    for row in clause_rows:
        source = row.get("source", "<unknown>")
        ids = row.get("source_clause_ids")
        if not isinstance(ids, list) or not ids or not all(isinstance(item, str) and item for item in ids):
            errors.append(f"clause map {source} must define non-empty source_clause_ids")
            continue
        for clause_id in ids:
            if clause_id in observed:
                duplicates.setdefault(clause_id, [observed[clause_id]]).append(str(source))
            observed[clause_id] = str(source)
    missing = sorted(expected - set(observed))
    extra = sorted(set(observed) - expected)
    if missing:
        errors.append(f"clause map missing MSA clause ids: {', '.join(missing)}")
    if extra:
        errors.append(f"clause map references unknown MSA clause ids: {', '.join(extra)}")
    for clause_id, sources in sorted(duplicates.items()):
        errors.append(f"clause map duplicates MSA clause id {clause_id}: {', '.join(sources)}")


def parse_human_clause_table(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    in_table = False
    previous_table_line: int | None = None
    for line_number, line in markdown_structure.operative_lines(text):
        if line.startswith("| Source | Disposition | Operative Home | Notes |"):
            in_table = True
            previous_table_line = line_number
            continue
        if not in_table:
            continue
        if previous_table_line is None or line_number != previous_table_line + 1:
            break
        previous_table_line = line_number
        if line.startswith("|---"):
            continue
        if not line.startswith("|"):
            break
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 3:
            continue
        rows.append(
            {
                "source": cells[0],
                "dispositions": sorted(part.strip() for part in cells[1].split("+")),
                "operative_home": re.findall(r"`([^`]+)`", cells[2]),
            }
        )
    return rows


def validate_human_clause_table(
    clause_rows: list[dict[str, Any]],
    human_text: str,
    errors: list[str],
) -> None:
    human_rows = parse_human_clause_table(human_text)
    machine = {row["source"]: row for row in clause_rows if isinstance(row.get("source"), str)}
    human = {row["source"]: row for row in human_rows if isinstance(row.get("source"), str)}
    missing = sorted(set(machine) - set(human))
    extra = sorted(set(human) - set(machine))
    if missing:
        errors.append(f"human-readable clause classification missing sources: {', '.join(missing)}")
    if extra:
        errors.append(f"human-readable clause classification has unknown sources: {', '.join(extra)}")
    for source in sorted(set(machine) & set(human)):
        machine_dispositions = sorted(machine[source].get("dispositions", []))
        if human[source]["dispositions"] != machine_dispositions:
            errors.append(f"human-readable clause classification disposition drift: {source}")
        machine_home = machine[source].get("operative_home", [])
        if human[source]["operative_home"] != machine_home:
            errors.append(f"human-readable clause classification operative_home drift: {source}")


def validate_clause_projection_markers(row: dict[str, Any], errors: list[str]) -> None:
    source = row.get("source", "<unknown>")
    dispositions = row.get("dispositions")
    if not isinstance(dispositions, list) or "projected" not in dispositions:
        return
    operative_home = row.get("operative_home")
    if not isinstance(operative_home, list):
        errors.append(f"projected clause lacks operative_home before marker check: {source}")
        return
    homes = {home for home in operative_home if isinstance(home, str)}
    projection_id = row.get("projection_id")
    if not isinstance(projection_id, str) or not PROJECTION_ID_RE.match(projection_id):
        errors.append(f"projected clause lacks valid projection_id: {source}")
        return
    target_markers = row.get("target_markers")
    if not isinstance(target_markers, dict) or not target_markers:
        errors.append(f"projected clause lacks target_markers: {source}")
        return
    for rel, marker_ids in target_markers.items():
        if rel not in homes:
            errors.append(f"projected clause {source} marker path is outside operative_home: {rel}")
            continue
        text = read_repo_text(rel, errors, f"clause projection marker {source} {rel}")
        if not isinstance(marker_ids, list) or not marker_ids:
            errors.append(f"projected clause {source} target_markers for {rel} must be a non-empty list")
            continue
        if projection_id not in marker_ids:
            errors.append(f"projected clause {source} target_markers for {rel} must include projection_id")
        for marker_id in marker_ids:
            if not isinstance(marker_id, str) or not PROJECTION_ID_RE.match(marker_id):
                errors.append(f"projected clause {source} target marker for {rel} must be a projection id")
            elif not projection_marker_exists(text, marker_id):
                errors.append(f"projected clause {source} target marker missing from {rel}: {marker_id}")


def _validate_workflow_object_fields(
    value: dict[Any, Any],
    label: str,
    allowed: set[str],
    required: set[str],
    errors: list[str],
) -> None:
    unknown = sorted(
        field if isinstance(field, str) else repr(field)
        for field in value
        if not isinstance(field, str) or field not in allowed
    )
    if unknown:
        errors.append(f"{label} has unknown fields: {', '.join(unknown)}")
    missing = sorted(required - {field for field in value if isinstance(field, str)})
    if missing:
        errors.append(f"{label} is missing required fields: {', '.join(missing)}")


def _validate_workflow_string(value: object, label: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{label} must be a non-empty string")


def _validate_workflow_string_list(
    value: object,
    label: str,
    errors: list[str],
    *,
    non_empty: bool,
    unique: bool = False,
) -> None:
    if (
        not isinstance(value, list)
        or (non_empty and not value)
        or not all(isinstance(item, str) and item.strip() for item in value)
    ):
        qualifier = "non-empty " if non_empty else ""
        errors.append(f"{label} must be a {qualifier}list of non-empty strings")
        return
    if unique and len(value) != len(set(value)):
        errors.append(f"{label} must not contain duplicate values")


def _workflow_condition_identity_pairs(
    value: object,
) -> list[tuple[str, str]]:
    if not isinstance(value, list):
        return []
    pairs: list[tuple[str, str]] = []
    for condition in value:
        if not isinstance(condition, dict):
            continue
        condition_id = condition.get("id")
        description = condition.get("description")
        if (
            isinstance(condition_id, str)
            and condition_id.strip()
            and isinstance(description, str)
            and description.strip()
        ):
            pairs.append((condition_id, description))
    return pairs


def _workflow_condition_delegation_pairs(
    value: object,
) -> list[tuple[str, str]]:
    if not isinstance(value, list):
        return []
    pairs: list[tuple[str, str]] = []
    for condition in value:
        if not isinstance(condition, dict):
            continue
        condition_id = condition.get("id")
        obligation_id = condition.get("delegated_obligation_id")
        if (
            isinstance(condition_id, str)
            and condition_id.strip()
            and isinstance(obligation_id, str)
            and obligation_id.strip()
        ):
            pairs.append((condition_id, obligation_id))
    return pairs


def _validate_workflow_string_map(
    value: object,
    label: str,
    errors: list[str],
) -> None:
    if not isinstance(value, dict):
        errors.append(f"{label} must be an object of non-empty string values")
        return
    for key, item in value.items():
        if not isinstance(key, str) or not key.strip():
            errors.append(f"{label} keys must be non-empty strings: {key!r}")
        if not isinstance(item, str) or not item.strip():
            errors.append(f"{label}.{key} must be a non-empty string")


def _validate_workflow_string_list_map(
    value: object,
    label: str,
    errors: list[str],
) -> None:
    if not isinstance(value, dict):
        errors.append(f"{label} must be an object of string lists")
        return
    for key, item in value.items():
        if not isinstance(key, str) or not key.strip():
            errors.append(f"{label} keys must be non-empty strings: {key!r}")
        _validate_workflow_string_list(
            item,
            f"{label}.{key}",
            errors,
            non_empty=True,
        )


def _validate_workflow_step_list(
    value: object,
    label: str,
    errors: list[str],
    *,
    non_empty: bool = False,
) -> None:
    if not isinstance(value, list):
        errors.append(f"{label} must be a workflow-step list")
        return
    if non_empty and not value:
        errors.append(f"{label} must be a non-empty workflow-step list")
    for index, step in enumerate(value):
        _validate_workflow_step(step, f"{label}[{index}]", errors)


def _validate_workflow_branches(
    value: object,
    label: str,
    errors: list[str],
) -> None:
    if not isinstance(value, dict):
        errors.append(f"{label} must be an object of workflow-step lists")
        return
    for branch, steps in value.items():
        if not isinstance(branch, str) or not branch.strip():
            errors.append(f"{label} keys must be non-empty strings: {branch!r}")
        _validate_workflow_step_list(steps, f"{label}.{branch}", errors)


def _validate_workflow_step(
    value: object,
    label: str,
    errors: list[str],
) -> None:
    if isinstance(value, str):
        if not value.strip():
            errors.append(f"{label} string step must be non-empty")
        return
    if not isinstance(value, dict):
        errors.append(f"{label} must be a non-empty order string or step object")
        return
    _validate_workflow_object_fields(
        value,
        label,
        WORKFLOW_STEP_FIELDS,
        set(),
        errors,
    )
    selectors = [field for field in ("order", "action") if field in value]
    if len(selectors) != 1:
        errors.append(f"{label} must define exactly one of order or action")
    for field in (
        "action",
        "effect_action_id",
        "mode",
        "order",
        "requires",
        "scope",
    ):
        if field in value:
            _validate_workflow_string(value[field], f"{label}.{field}", errors)
    if (
        "requires_authorization" in value
        and type(value["requires_authorization"]) is not bool
    ):
        errors.append(f"{label}.requires_authorization must be a boolean")
    if "outcome_branches" in value:
        _validate_workflow_branches(
            value["outcome_branches"],
            f"{label}.outcome_branches",
            errors,
        )


def _validate_workflow_escalation_condition(
    value: object,
    label: str,
    errors: list[str],
) -> None:
    if not isinstance(value, dict):
        errors.append(f"{label} must be an object")
        return
    _validate_workflow_object_fields(
        value,
        label,
        WORKFLOW_ESCALATION_CONDITION_FIELDS,
        {"description", "id"},
        errors,
    )
    for field in ("delegated_obligation_id", "description", "id"):
        if field in value:
            _validate_workflow_string(value[field], f"{label}.{field}", errors)
    for field in ("all_flags", "any_flags"):
        if field in value:
            _validate_workflow_string_list(
                value[field],
                f"{label}.{field}",
                errors,
                non_empty=False,
                unique=True,
            )
            flags = value[field]
            if isinstance(flags, list):
                unknown_flags = sorted(
                    {
                        flag
                        for flag in flags
                        if isinstance(flag, str)
                        and flag not in routing_policy.runtime_condition_flags()
                    }
                )
                if unknown_flags:
                    errors.append(
                        f"{label}.{field} uses unknown runtime condition flags: "
                        + ", ".join(unknown_flags)
                    )
    if not any(
        isinstance(value.get(field), list) and bool(value[field])
        for field in ("all_flags", "any_flags")
    ):
        errors.append(f"{label} must define at least one any_flags or all_flags predicate")


def _validate_workflow_runtime_module(
    value: object,
    label: str,
    errors: list[str],
) -> None:
    if not isinstance(value, dict):
        errors.append(f"{label} must be null or an object")
        return
    _validate_workflow_object_fields(
        value,
        label,
        WORKFLOW_RUNTIME_MODULE_FIELDS,
        WORKFLOW_RUNTIME_MODULE_REQUIRED_FIELDS,
        errors,
    )
    for field in ("canonical_task_order", "finding_schema", "name", "path"):
        if field in value:
            _validate_workflow_string(value[field], f"{label}.{field}", errors)
    if "use_full_when" in value:
        _validate_workflow_string_list(
            value["use_full_when"],
            f"{label}.use_full_when",
            errors,
            non_empty=True,
            unique=True,
        )
    conditions = value.get("use_full_when_conditions")
    if "use_full_when_conditions" in value:
        if not isinstance(conditions, list) or not conditions:
            errors.append(
                f"{label}.use_full_when_conditions must be a non-empty object list"
            )
        else:
            for index, condition in enumerate(conditions):
                _validate_workflow_escalation_condition(
                    condition,
                    f"{label}.use_full_when_conditions[{index}]",
                    errors,
                )
    identity_pairs = _workflow_condition_identity_pairs(conditions)
    condition_identity_shape_valid = (
        isinstance(conditions, list)
        and bool(conditions)
        and len(identity_pairs) == len(conditions)
    )
    condition_ids = [condition_id for condition_id, _description in identity_pairs]
    condition_descriptions = [description for _condition_id, description in identity_pairs]
    condition_ids_unique = len(condition_ids) == len(set(condition_ids))
    condition_descriptions_unique = len(condition_descriptions) == len(
        set(condition_descriptions)
    )
    if condition_identity_shape_valid and not condition_ids_unique:
        errors.append(f"{label}.use_full_when_conditions must define unique condition IDs")
    if condition_identity_shape_valid and not condition_descriptions_unique:
        errors.append(
            f"{label}.use_full_when_conditions must define unique condition descriptions"
        )
    use_full_when = value.get("use_full_when")
    use_full_when_descriptions = (
        [item for item in use_full_when if isinstance(item, str)]
        if isinstance(use_full_when, list)
        else []
    )
    use_full_when_valid = (
        isinstance(use_full_when, list)
        and bool(use_full_when)
        and len(use_full_when_descriptions) == len(use_full_when)
        and all(item.strip() for item in use_full_when_descriptions)
    )
    if (
        use_full_when_valid
        and condition_identity_shape_valid
        and condition_descriptions_unique
        and set(use_full_when_descriptions) != set(condition_descriptions)
    ):
        errors.append(
            f"{label}.use_full_when descriptions must exactly match "
            "use_full_when_conditions descriptions"
        )


def _validate_workflow_task_order(
    value: object,
    position: int,
    errors: list[str],
) -> None:
    label = f"workflow catalog task_orders[{position}]"
    if not isinstance(value, dict):
        errors.append(f"{label} must be an object")
        return
    _validate_workflow_object_fields(
        value,
        label,
        WORKFLOW_TASK_ORDER_FIELDS,
        WORKFLOW_TASK_ORDER_REQUIRED_FIELDS,
        errors,
    )
    for field in (
        "category",
        "default_invocation_mode",
        "effect_owner",
        "effect_scope",
        "name",
        "path",
        "use_when",
        "vcs_precondition",
    ):
        if field in value:
            _validate_workflow_string(value[field], f"{label}.{field}", errors)
    list_fields = {
        "accepted_evaluation_class_enum": True,
        "common_next_orders": False,
        "direct_full_when_flags": True,
        "effect_exclusions": True,
        "invocation_mode_enum": True,
        "mode_enum": True,
        "outcome_enum": True,
        "owned_effect_action_ids": True,
        "owned_effect_actions": True,
        "primary_outputs": True,
        "produced_evaluation_class_enum": True,
    }
    for field, non_empty in list_fields.items():
        if field in value:
            _validate_workflow_string_list(
                value[field],
                f"{label}.{field}",
                errors,
                non_empty=non_empty,
            )
    if "common_next_steps" in value:
        _validate_workflow_step_list(
            value["common_next_steps"],
            f"{label}.common_next_steps",
            errors,
        )
    for field in ("mode_next_steps", "outcome_next_steps"):
        if field in value:
            _validate_workflow_branches(value[field], f"{label}.{field}", errors)
    if "allowed_outcomes_by_mode" in value:
        _validate_workflow_string_list_map(
            value["allowed_outcomes_by_mode"],
            f"{label}.allowed_outcomes_by_mode",
            errors,
        )
    if "effect_state_by_outcome" in value:
        _validate_workflow_string_map(
            value["effect_state_by_outcome"],
            f"{label}.effect_state_by_outcome",
            errors,
        )
    module = value.get("runtime_task_module")
    if "runtime_task_module" in value and module is not None:
        _validate_workflow_runtime_module(
            module,
            f"{label}.runtime_task_module",
            errors,
        )


def _validate_workflow_common_sequence(
    value: object,
    position: int,
    errors: list[str],
) -> None:
    label = f"workflow catalog common_sequences[{position}]"
    if not isinstance(value, dict):
        errors.append(f"{label} must be an object")
        return
    _validate_workflow_object_fields(
        value,
        label,
        WORKFLOW_COMMON_SEQUENCE_FIELDS,
        WORKFLOW_COMMON_SEQUENCE_REQUIRED_FIELDS,
        errors,
    )
    for field in ("name", "ownership_scope", "when"):
        if field in value:
            _validate_workflow_string(value[field], f"{label}.{field}", errors)
    if "steps" in value:
        _validate_workflow_step_list(
            value["steps"],
            f"{label}.steps",
            errors,
            non_empty=True,
        )
    if "outcome_branches" in value:
        _validate_workflow_branches(
            value["outcome_branches"],
            f"{label}.outcome_branches",
            errors,
        )


def validate_workflow_catalog_schema(
    workflow_catalog: dict[str, Any],
    errors: list[str],
) -> None:
    """Validate the complete closed workflow-catalog shape before semantics."""

    _validate_workflow_object_fields(
        workflow_catalog,
        "workflow catalog",
        WORKFLOW_CATALOG_FIELDS,
        WORKFLOW_CATALOG_FIELDS,
        errors,
    )
    if "schema_version" in workflow_catalog and type(
        workflow_catalog["schema_version"]
    ) is not int:
        errors.append("workflow catalog schema_version must be an integer")

    selection = workflow_catalog.get("workflow_selection")
    if "workflow_selection" in workflow_catalog:
        if not isinstance(selection, dict):
            errors.append("workflow catalog workflow_selection must be an object")
        else:
            _validate_workflow_object_fields(
                selection,
                "workflow catalog workflow_selection",
                WORKFLOW_SELECTION_FIELDS,
                WORKFLOW_SELECTION_FIELDS,
                errors,
            )
            if "known_workflow_provenance" in selection:
                _validate_workflow_string_list(
                    selection["known_workflow_provenance"],
                    "workflow catalog workflow_selection.known_workflow_provenance",
                    errors,
                    non_empty=True,
                    unique=True,
                )
            route = selection.get("ambiguous_workflow_route")
            if "ambiguous_workflow_route" in selection:
                if not isinstance(route, dict):
                    errors.append(
                        "workflow catalog workflow_selection.ambiguous_workflow_route "
                        "must be an object"
                    )
                else:
                    route_label = (
                        "workflow catalog workflow_selection.ambiguous_workflow_route"
                    )
                    _validate_workflow_object_fields(
                        route,
                        route_label,
                        WORKFLOW_AMBIGUOUS_ROUTE_FIELDS,
                        WORKFLOW_AMBIGUOUS_ROUTE_FIELDS,
                        errors,
                    )
                    for field in ("forbidden_action", "required_action"):
                        if field in route:
                            _validate_workflow_string(
                                route[field],
                                f"{route_label}.{field}",
                                errors,
                            )
                    for field in ("conditions", "fallback_references"):
                        if field in route:
                            _validate_workflow_string_list(
                                route[field],
                                f"{route_label}.{field}",
                                errors,
                                non_empty=True,
                                unique=True,
                            )

    task_orders = workflow_catalog.get("task_orders")
    if "task_orders" in workflow_catalog:
        if not isinstance(task_orders, list):
            errors.append("workflow catalog task_orders must be a list")
        else:
            for position, entry in enumerate(task_orders):
                _validate_workflow_task_order(entry, position, errors)

    common_sequences = workflow_catalog.get("common_sequences")
    if "common_sequences" in workflow_catalog:
        if not isinstance(common_sequences, list):
            errors.append("workflow catalog common_sequences must be a list")
        else:
            for position, sequence in enumerate(common_sequences):
                _validate_workflow_common_sequence(sequence, position, errors)


def direct_unguarded_step_orders(value: object) -> list[str]:
    steps = value if isinstance(value, list) else [value]
    orders: list[str] = []
    for step in steps:
        if isinstance(step, str):
            orders.append(step)
        elif (
            isinstance(step, dict)
            and isinstance(step.get("order"), str)
            and step.get("requires_authorization") is not True
            and not step.get("requires")
        ):
            orders.append(step["order"])
    return orders


def iter_step_orders(value: object, errors: list[str], label: str) -> Iterator[str]:
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            yield from iter_step_orders(item, errors, f"{label}[{index}]")
        return
    if isinstance(value, dict):
        order = value.get("order")
        if isinstance(order, str):
            yield order
        action = value.get("action")
        if order is None and action is None:
            errors.append(f"workflow step {label} must contain order or action: {value}")
        for branch_steps in value.get("outcome_branches", {}).values() if isinstance(value.get("outcome_branches"), dict) else []:
            yield from iter_step_orders(branch_steps, errors, f"{label}.outcome_branches")
        return
    errors.append(f"workflow step {label} has unsupported type: {type(value).__name__}")


def iter_step_effect_action_ids(
    value: object,
    errors: list[str],
    label: str,
) -> Iterator[str]:
    if isinstance(value, list):
        for index, item in enumerate(value):
            yield from iter_step_effect_action_ids(
                item,
                errors,
                f"{label}[{index}]",
            )
    elif isinstance(value, dict):
        if "effect_action_id" in value:
            effect_action_id = value["effect_action_id"]
            if not isinstance(effect_action_id, str) or not WORKFLOW_EFFECT_ACTION_ID_RE.fullmatch(
                effect_action_id
            ):
                errors.append(
                    f"workflow step {label} has invalid effect_action_id: "
                    f"{effect_action_id!r}"
                )
            else:
                yield effect_action_id
        branches = value.get("outcome_branches")
        if isinstance(branches, dict):
            for branch_name, steps in branches.items():
                yield from iter_step_effect_action_ids(
                    steps,
                    errors,
                    f"{label}.outcome_branches.{branch_name}",
                )


def first_sequence_order(value: object) -> str | None:
    if not isinstance(value, list):
        return None
    for step in value:
        if isinstance(step, str):
            return step
        if isinstance(step, dict) and isinstance(step.get("order"), str):
            return step["order"]
    return None


def parse_workflow_contract_marker(
    task_text: str,
    label: str,
    errors: list[str],
) -> dict[str, Any] | None:
    prefix_matches = list(WORKFLOW_CONTRACT_MARKER_PREFIX_RE.finditer(task_text))
    if len(prefix_matches) != 1:
        errors.append(
            f"{label} must contain exactly one mpa-workflow-contract marker; "
            f"found {len(prefix_matches)}"
        )
        return None
    matches = list(WORKFLOW_CONTRACT_MARKER_RE.finditer(task_text))
    if len(matches) != 1:
        errors.append(
            f"{label} mpa-workflow-contract marker is invalid JSON object syntax"
        )
        return None
    payload_text = matches[0].group("payload")
    try:
        payload = safe_paths.loads_json_no_duplicates(payload_text)
    except json.JSONDecodeError as exc:
        errors.append(f"{label} mpa-workflow-contract marker is invalid JSON: {exc.msg}")
        return None
    if not isinstance(payload, dict):
        errors.append(f"{label} mpa-workflow-contract payload must be an object")
        return None
    unknown = sorted(set(payload) - set(WORKFLOW_CONTRACT_ENUM_KEYS))
    if unknown:
        errors.append(
            f"{label} mpa-workflow-contract marker has unknown fields: "
            + ", ".join(unknown)
        )
    return payload


def validate_framework_improvement_interface(
    catalog_entries: list[dict[str, Any]],
    errors: list[str],
) -> None:
    entries = {
        entry.get("name"): entry
        for entry in catalog_entries
        if isinstance(entry, dict) and isinstance(entry.get("name"), str)
    }
    semantic_audit = entries.get("framework_semantic_audit")
    improvement = entries.get("framework_improvement")
    if not isinstance(semantic_audit, dict):
        errors.append("workflow catalog missing framework_semantic_audit interface producer")
        return
    if not isinstance(improvement, dict):
        errors.append("workflow catalog missing framework_improvement interface consumer")
        return

    produced = semantic_audit.get("produced_evaluation_class_enum")
    if produced != FRAMEWORK_EVALUATION_CLASSES:
        errors.append(
            "workflow catalog framework_semantic_audit "
            "produced_evaluation_class_enum must match the closed evaluation-class set"
        )
    accepted = improvement.get("accepted_evaluation_class_enum")
    if accepted != FRAMEWORK_EVALUATION_CLASSES:
        errors.append(
            "workflow catalog framework_improvement accepted_evaluation_class_enum "
            "must match the closed evaluation-class set"
        )
    if produced != accepted:
        errors.append(
            "workflow catalog framework semantic-audit producer and improvement "
            "consumer evaluation classes must match exactly"
        )

    modes = improvement.get("invocation_mode_enum")
    if modes != FRAMEWORK_IMPROVEMENT_MODES:
        errors.append(
            "workflow catalog framework_improvement invocation_mode_enum must be "
            "exactly assess, act"
        )
    if improvement.get("default_invocation_mode") != "assess":
        errors.append(
            "workflow catalog framework_improvement default_invocation_mode must be assess"
        )
    if improvement.get("outcome_enum") != FRAMEWORK_IMPROVEMENT_OUTCOMES:
        errors.append(
            "workflow catalog framework_improvement outcome_enum must match the closed "
            "improvement-outcome set"
        )
    if (
        improvement.get("allowed_outcomes_by_mode")
        != FRAMEWORK_IMPROVEMENT_OUTCOMES_BY_MODE
    ):
        errors.append(
            "workflow catalog framework_improvement allowed_outcomes_by_mode contains "
            "an illegal mode/outcome pairing or misses a required pairing"
        )
    if (
        improvement.get("effect_state_by_outcome")
        != FRAMEWORK_IMPROVEMENT_EFFECT_STATE_BY_OUTCOME
    ):
        errors.append(
            "workflow catalog framework_improvement effect_state_by_outcome must match "
            "the closed effect-state contract"
        )


def validate_workflow_branch_contracts(
    catalog_entries: list[dict[str, Any]],
    common_sequences: list[dict[str, Any]],
    errors: list[str],
) -> None:
    entries = {
        entry["name"]: entry
        for entry in catalog_entries
        if isinstance(entry.get("name"), str)
    }
    for name, entry in entries.items():
        expected_marker = {
            key: entry[key]
            for key in WORKFLOW_CONTRACT_ENUM_KEYS
            if key in entry
        }
        task_path = entry.get("path")
        if expected_marker and isinstance(task_path, str):
            task_text = read_repo_text(
                task_path,
                errors,
                f"workflow task order {name}",
            )
            marker_payload = parse_workflow_contract_marker(
                task_text,
                f"workflow task order {name}",
                errors,
            )
            if marker_payload is not None and marker_payload != expected_marker:
                errors.append(
                    f"workflow task order {name} mpa-workflow-contract marker must "
                    "match its catalog enum contract exactly"
                )
        for enum_key, steps_key in (
            ("outcome_enum", "outcome_next_steps"),
            ("mode_enum", "mode_next_steps"),
        ):
            steps = entry.get(steps_key)
            enum = entry.get(enum_key)
            if steps is None and enum is None:
                continue
            if not isinstance(enum, list) or not enum or not all(
                isinstance(item, str) and item for item in enum
            ):
                errors.append(f"workflow catalog {name} {enum_key} must be a non-empty string list")
                continue
            if len(enum) != len(set(enum)):
                errors.append(f"workflow catalog {name} {enum_key} contains duplicates")
            if not isinstance(steps, dict):
                errors.append(f"workflow catalog {name} {steps_key} must be an object")
                continue
            if set(steps) != set(enum):
                errors.append(f"workflow catalog {name} {steps_key} keys must match {enum_key}")
    validate_framework_improvement_interface(catalog_entries, errors)

    for sequence in common_sequences:
        name = sequence.get("name")
        branches = sequence.get("outcome_branches")
        if not isinstance(name, str) or not isinstance(branches, dict):
            continue
        owner_name = first_sequence_order(sequence.get("steps"))
        owner = entries.get(owner_name or "")
        if owner is None:
            continue
        expected = owner.get("outcome_next_steps")
        if expected is None:
            expected = owner.get("mode_next_steps")
        if not isinstance(expected, dict):
            errors.append(
                f"workflow sequence {name} has outcome_branches but owner {owner_name} has no branch contract"
            )
        elif branches != expected:
            errors.append(
                f"workflow sequence {name} outcome branches must match {owner_name} branch contract"
            )

    feature_hardening = next(
        (
            sequence
            for sequence in common_sequences
            if sequence.get("name") == "feature_hardening"
        ),
        None,
    )
    if not isinstance(feature_hardening, dict) or (
        feature_hardening.get("ownership_scope") != "downstream_or_project_local"
    ):
        errors.append(
            "workflow sequence feature_hardening ownership_scope must be "
            "downstream_or_project_local"
        )

    effect_owner_by_id: dict[str, str] = {}
    for name, entry in entries.items():
        if entry.get("effect_owner") != "task_order":
            continue
        owned = entry.get("owned_effect_actions")
        if not isinstance(owned, list) or not owned or not all(
            isinstance(item, str) and item for item in owned
        ):
            errors.append(
                f"workflow catalog {name} task-order effect owner must declare owned_effect_actions"
            )
            continue
        owned_ids = entry.get("owned_effect_action_ids")
        if not isinstance(owned_ids, list) or not owned_ids or not all(
            isinstance(item, str) and WORKFLOW_EFFECT_ACTION_ID_RE.fullmatch(item)
            for item in owned_ids
        ):
            errors.append(
                f"workflow catalog {name} task-order effect owner must declare valid "
                "owned_effect_action_ids"
            )
            continue
        if len(owned_ids) != len(set(owned_ids)):
            errors.append(
                f"workflow catalog {name} owned_effect_action_ids contains duplicates"
            )
        if len(owned_ids) != len(owned):
            errors.append(
                f"workflow catalog {name} owned effect ids and descriptions must have "
                "the same cardinality"
            )
        expected_scope = TASK_ORDER_EFFECT_SCOPE_BY_NAME.get(name)
        if expected_scope is None:
            errors.append(
                f"workflow catalog {name} has no registered task-order effect scope"
            )
        elif entry.get("effect_scope") != expected_scope:
            errors.append(
                f"workflow catalog {name} effect_scope must be {expected_scope}"
            )
        for effect_action_id in owned_ids:
            existing_owner = effect_owner_by_id.get(effect_action_id)
            if existing_owner is not None and existing_owner != name:
                errors.append(
                    f"workflow effect_action_id {effect_action_id} has multiple task-order "
                    f"owners: {existing_owner}, {name}"
                )
            else:
                effect_owner_by_id[effect_action_id] = name

    transition_effect_ids: list[str] = []
    for name, entry in entries.items():
        transition_effect_ids.extend(
            iter_step_effect_action_ids(
                entry.get("common_next_steps", []),
                errors,
                f"workflow catalog {name}.common_next_steps",
            )
        )
        for key in ("outcome_next_steps", "mode_next_steps"):
            branches = entry.get(key)
            if isinstance(branches, dict):
                for branch_name, steps in branches.items():
                    transition_effect_ids.extend(
                        iter_step_effect_action_ids(
                            steps,
                            errors,
                            f"workflow catalog {name}.{key}.{branch_name}",
                        )
                    )
    for sequence in common_sequences:
        sequence_name = sequence.get("name", "<unnamed>")
        transition_effect_ids.extend(
            iter_step_effect_action_ids(
                sequence.get("steps", []),
                errors,
                f"workflow sequence {sequence_name}.steps",
            )
        )
        branches = sequence.get("outcome_branches")
        if isinstance(branches, dict):
            for branch_name, steps in branches.items():
                transition_effect_ids.extend(
                    iter_step_effect_action_ids(
                        steps,
                        errors,
                        f"workflow sequence {sequence_name}.outcome_branches.{branch_name}",
                    )
                )
    for effect_action_id in sorted(set(transition_effect_ids)):
        owner = effect_owner_by_id.get(effect_action_id)
        if owner is None:
            errors.append(
                f"workflow transition uses unowned effect_action_id: {effect_action_id}"
            )
        else:
            errors.append(
                f"workflow catalog {owner} repeats task-order-owned effect id in "
                f"transitions: {effect_action_id}"
            )


def validate_minimum_evidence_by_risk(schedule: dict[str, Any], errors: list[str]) -> None:
    risk_names: set[str] = set()
    for item in schedule.get("standards_of_care", []):
        if isinstance(item, dict):
            name = item.get("name")
            if isinstance(name, str):
                risk_names.add(name)
    evidence_scopes: set[str] = set()
    for item in schedule.get("evidentiary_scopes", []):
        if isinstance(item, dict):
            name = item.get("name")
            if isinstance(name, str):
                evidence_scopes.add(name)
    matrix = schedule.get("minimum_evidence_by_risk")
    if not isinstance(matrix, dict):
        errors.append("operative schedule minimum_evidence_by_risk must be an object")
        return
    matrix_keys: set[str] = set()
    for key in matrix:
        if isinstance(key, str):
            matrix_keys.add(key)
        else:
            errors.append("minimum_evidence_by_risk keys must be strings")
    missing = sorted(risk_names - matrix_keys)
    extra = sorted(matrix_keys - risk_names)
    if missing:
        errors.append(f"minimum_evidence_by_risk missing risks: {', '.join(missing)}")
    if extra:
        errors.append(f"minimum_evidence_by_risk has unknown risks: {', '.join(extra)}")
    for risk in sorted(matrix_keys):
        entry = matrix[risk]
        if not isinstance(entry, dict):
            errors.append(f"minimum_evidence_by_risk {risk} must be an object")
            continue
        minimum_scope = entry.get("minimum_scope")
        if minimum_scope not in evidence_scopes:
            errors.append(f"minimum_evidence_by_risk {risk} uses unknown minimum_scope: {minimum_scope}")
        required_checks = entry.get("required_checks")
        if not isinstance(required_checks, list) or not required_checks or not all(
            isinstance(item, str) and item for item in required_checks
        ):
            errors.append(f"minimum_evidence_by_risk {risk} must define non-empty required_checks")
            continue
        for check_id in required_checks:
            if check_id not in verification_registry.CHECKS_BY_ID:
                errors.append(
                    f"minimum_evidence_by_risk {risk} references unknown "
                    f"verification check: {check_id}"
                )


def validate_guarded_workflow_transitions(
    catalog_entries: list[dict[str, Any]], errors: list[str]
) -> None:
    entries = {
        entry.get("name"): entry
        for entry in catalog_entries
        if isinstance(entry, dict) and isinstance(entry.get("name"), str)
    }
    ideate = entries.get("ideate")
    if ideate is None:
        errors.append("workflow catalog missing guarded transition entry: ideate")
    else:
        if ideate.get("common_next_orders"):
            errors.append(
                "workflow catalog ideate must not use unconditional common_next_orders"
            )
        if ideate.get("common_next_steps") != IDEATE_OWNERSHIP_NEXT_STEPS:
            errors.append(
                "workflow catalog ideate must route a chosen direction by ownership"
            )

    independent = entries.get("independent_assessment")
    if independent is None:
        errors.append(
            "workflow catalog missing guarded transition entry: independent_assessment"
        )
    else:
        if independent.get("common_next_orders"):
            errors.append(
                "workflow catalog independent_assessment must not use unconditional "
                "common_next_orders"
            )
        outcome_steps = independent.get("outcome_next_steps")
        if not isinstance(outcome_steps, dict):
            errors.append(
                "workflow catalog independent_assessment must define outcome_next_steps"
            )
        elif (
            outcome_steps.get("actionable_assessment")
            != INDEPENDENT_ASSESSMENT_ACTIONABLE_NEXT_STEPS
        ):
            errors.append(
                "workflow catalog independent_assessment actionable_assessment must "
                "route by ownership with guarded downstream planning"
            )
    arbitrate = entries.get("arbitrate")
    if isinstance(arbitrate, dict):
        outcome_enum = arbitrate.get("outcome_enum")
        if not isinstance(outcome_enum, list) or set(outcome_enum) != ARBITRATION_OUTCOMES:
            errors.append("workflow catalog arbitrate outcome_enum must match task_orders/arbitrate.md outcomes")
        outcome_steps = arbitrate.get("outcome_next_steps")
        if isinstance(outcome_steps, dict):
            if set(outcome_steps) != ARBITRATION_OUTCOMES:
                errors.append("workflow catalog arbitrate outcome_next_steps keys must match outcome_enum")
            if outcome_steps.get("ratified_decision") != ARBITRATION_RATIFIED_NEXT_STEPS:
                errors.append(
                    "workflow catalog arbitrate ratified_decision must separate "
                    "decision-record commit from ownership-routed implementation follow-up"
                )
            for outcome in sorted(ARBITRATION_NO_DECISION_OUTCOMES):
                steps = outcome_steps.get(outcome)
                if not isinstance(steps, list) or not steps:
                    errors.append(f"workflow catalog arbitrate {outcome} must define no-decision control actions")
                    continue
                for step_index, step in enumerate(steps, start=1):
                    if not isinstance(step, dict):
                        errors.append(f"workflow catalog arbitrate {outcome} step {step_index} must be an object")
                        continue
                    if "order" in step:
                        errors.append(
                            f"workflow catalog arbitrate {outcome} step {step_index} must not route to operative order {step.get('order')}"
                        )
                    action = step.get("action")
                    if action not in ARBITRATION_NO_DECISION_ACTIONS:
                        errors.append(
                            f"workflow catalog arbitrate {outcome} step {step_index} has unsupported no-decision action: {action}"
                        )
                    if (
                        action in ARBITRATION_NO_DECISION_ACTIONS
                        and step.get("requires_authorization") is not True
                    ):
                        errors.append(
                            f"workflow catalog arbitrate {outcome} no-decision action {action} lacks requires_authorization"
                        )
        else:
            errors.append("workflow catalog arbitrate must define outcome_next_steps")
    commit = entries.get("commit")
    if isinstance(commit, dict) and commit.get("vcs_precondition") != "Git":
        errors.append("workflow catalog commit must declare vcs_precondition Git")


def validate_finding_schema(schema: dict[str, Any], errors: list[str]) -> None:
    if not exact_schema_version(schema.get("schema_version"), 1):
        errors.append("finding schema schema_version must be exactly 1")
    fields = schema.get("fields")
    if not isinstance(fields, dict):
        errors.append("finding schema fields must be an object")
        return
    missing_fields = sorted(FINDING_SCHEMA_FIELDS - set(fields))
    extra_fields = sorted(set(fields) - FINDING_SCHEMA_FIELDS)
    if missing_fields:
        errors.append(f"finding schema missing fields: {', '.join(missing_fields)}")
    if extra_fields:
        errors.append(f"finding schema has unknown fields: {', '.join(extra_fields)}")
    for field, values in fields.items():
        if not isinstance(values, list) or not values or not all(
            isinstance(item, str) and item for item in values
        ):
            errors.append(f"finding schema field {field} must define non-empty string values")
    categories = fields.get("category")
    if isinstance(categories, list) and all(
        isinstance(item, str) for item in categories
    ):
        missing_categories = sorted(FINDING_CATEGORY_VALUES - set(categories))
        extra_categories = sorted(set(categories) - FINDING_CATEGORY_VALUES)
        if missing_categories:
            errors.append(
                "finding schema category missing values: "
                + ", ".join(missing_categories)
            )
        if extra_categories:
            errors.append(
                "finding schema category has unknown values: "
                + ", ".join(extra_categories)
            )
    report_fields = schema.get("required_report_fields")
    if not isinstance(report_fields, list) or not all(isinstance(item, str) and item for item in report_fields):
        errors.append("finding schema required_report_fields must be a string list")
    else:
        missing_report_fields = sorted(FINDING_REPORT_FIELDS - set(report_fields))
        if missing_report_fields:
            errors.append(f"finding schema required_report_fields missing: {', '.join(missing_report_fields)}")
    constraints = schema.get("conditional_constraints")
    if not isinstance(constraints, list) or not constraints:
        errors.append("finding schema conditional_constraints must be a non-empty list")
        return
    typed_fields = {
        field: set(values)
        for field, values in fields.items()
        if isinstance(field, str) and isinstance(values, list) and all(isinstance(item, str) for item in values)
    }

    def normalized_mapping(value: object, label: str) -> tuple[tuple[str, tuple[str, ...]], ...] | None:
        if not isinstance(value, dict) or not value:
            errors.append(f"finding schema constraint {label} must be a non-empty object")
            return None
        items: list[tuple[str, tuple[str, ...]]] = []
        for field, raw_values in value.items():
            if not isinstance(field, str) or field not in typed_fields:
                errors.append(f"finding schema constraint {label} references unknown field: {field}")
                continue
            values = raw_values if isinstance(raw_values, list) else [raw_values]
            if not values or not all(isinstance(item, str) and item for item in values):
                errors.append(f"finding schema constraint {label}.{field} must be a string or non-empty string list")
                continue
            unknown_values = sorted(set(values) - typed_fields[field])
            if unknown_values:
                errors.append(
                    f"finding schema constraint {label}.{field} uses unknown values: {', '.join(unknown_values)}"
                )
                continue
            items.append((field, tuple(sorted(values))))
        return tuple(sorted(items))

    actual_constraints: set[FindingConstraint] = set()
    expected_constraints: set[FindingConstraint] = set()
    seen_when: dict[tuple[tuple[str, tuple[str, ...]], ...], int] = {}
    for index, constraint in enumerate(constraints):
        if not isinstance(constraint, dict):
            errors.append(f"finding schema constraint {index} must be an object")
            continue
        when = normalized_mapping(constraint.get("when"), f"{index}.when")
        then = normalized_mapping(constraint.get("then"), f"{index}.then")
        if when is not None and then is not None:
            if when in seen_when:
                errors.append(
                    f"finding schema constraint {index} duplicates condition from constraint {seen_when[when]}"
                )
            seen_when[when] = index
            actual_constraints.add((when, then))

    for when, then in REQUIRED_FINDING_CONSTRAINTS:
        normalized_when = normalized_mapping(when, "required.when")
        normalized_then = normalized_mapping(then, "required.then")
        if normalized_when is None or normalized_then is None:
            continue
        expected_constraints.add((normalized_when, normalized_then))
        if (normalized_when, normalized_then) not in actual_constraints:
            errors.append(f"finding schema missing conditional constraint: when={when} then={then}")
    for when, then in sorted(actual_constraints - expected_constraints):
        errors.append(f"finding schema has unsupported conditional constraint: when={when} then={then}")


def validate_conformance_profiles(registry: dict[str, Any], errors: list[str]) -> None:
    """Use the conformance runner's canonical metadata validator verbatim."""

    errors.extend(conformance_check.validate_profile_metadata(registry))


def load_order_phase_blocks(text: str) -> dict[str, str]:
    blocks: dict[str, list[str]] = {}
    current: str | None = None
    for _line_number, line in markdown_structure.operative_lines(text):
        match = re.match(r"^\s*\d+\.\s+`?(?P<title>[^`\n]+?)`?\s*$", line)
        if match:
            title = match.group("title")
            if title is None:
                continue
            phase_key = title.strip()
            current = phase_key
            blocks[phase_key] = [line]
        elif current is not None:
            blocks[current].append(line)
    return {title: "\n".join(lines) for title, lines in blocks.items()}


def validate_runtime_load_order(text: str, contract: object, errors: list[str]) -> None:
    framework_contracts.validate_load_order_contract(
        contract,
        errors,
        known_project_state_files=framework_contracts.PROJECT_LOCAL_STATE_FILES,
    )
    if not isinstance(contract, dict):
        return
    phase_order = framework_contracts.string_list(contract.get("phase_order"))
    phase_titles = contract.get("phase_titles")
    if not phase_order or not isinstance(phase_titles, dict):
        return
    expected = [phase_titles.get(key) for key in phase_order]
    if not all(isinstance(title, str) and title for title in expected):
        return
    blocks = load_order_phase_blocks(text)
    actual = list(blocks)
    if actual[: len(expected)] != expected:
        errors.append(f"runtime/load_order.md phase order drift: {actual[:len(expected)]}")
        return
    validate_runtime_startup_state(blocks, contract, errors)


def validate_runtime_startup_state(blocks: dict[str, str], contract: dict[str, Any], errors: list[str]) -> None:
    phase_titles = contract.get("phase_titles", {})
    startup_title = phase_titles.get("startup_state") if isinstance(phase_titles, dict) else None
    if not isinstance(startup_title, str) or not startup_title:
        errors.append("load_order_contract.phase_titles.startup_state must be non-empty")
        return
    startup = blocks.get(startup_title, "")
    if not startup:
        errors.append(f"runtime/load_order.md missing startup-state phase: {startup_title}")
        return
    startup_folded = startup.casefold()
    startup_contract = contract.get("startup_state")
    if not isinstance(startup_contract, dict):
        return
    if "header" not in startup_folded:
        errors.append("runtime/load_order.md Startup state must name header-gated state loading")
    for filename in framework_contracts.string_list(startup_contract.get("header_files")):
        if f"`{filename}`" not in startup and filename not in startup:
            errors.append(f"runtime/load_order.md Startup state missing header-gated file: {filename}")
    empty_count_markers = startup_contract.get("empty_count_markers")
    if isinstance(empty_count_markers, dict):
        for markers in empty_count_markers.values():
            for marker in framework_contracts.string_list(markers):
                if marker not in startup:
                    errors.append(f"runtime/load_order.md Startup state missing empty-count marker: {marker}")
    for marker in framework_contracts.string_list(startup_contract.get("empty_markers")):
        if marker not in startup:
            errors.append(f"runtime/load_order.md Startup state missing empty-state marker: {marker}")
    for gate in framework_contracts.string_list(startup_contract.get("full_record_gate")):
        if gate.casefold() not in startup_folded:
            errors.append(f"runtime/load_order.md Startup state missing full-record gate: {gate}")
    for boundary in framework_contracts.string_list(startup_contract.get("barred_by")):
        if boundary.casefold() not in startup_folded:
            errors.append(f"runtime/load_order.md Startup state missing load boundary: {boundary}")
    conditional_files = startup_contract.get("conditional_files")
    if isinstance(conditional_files, dict):
        for filename, triggers in conditional_files.items():
            if not isinstance(filename, str):
                continue
            if f"`{filename}`" not in startup and filename not in startup:
                errors.append(f"runtime/load_order.md Startup state missing conditional file: {filename}")
            for trigger in framework_contracts.string_list(triggers):
                if trigger.casefold() not in startup_folded:
                    errors.append(f"runtime/load_order.md Startup state missing trigger {trigger!r} for {filename}")
            if not conditional_state_line_is_bounded(startup, filename):
                errors.append(f"runtime/load_order.md Startup state must conditionally bound {filename}")
    if re.search(r"\b(?:always|unconditionally)\s+load\b", startup_folded) or re.search(
        r"\bload\s+(?:all|every)\s+state\b", startup_folded
    ):
        errors.append("runtime/load_order.md Startup state must not require unconditional state loading")
    if re.search(r"\b(?:grant|create|expand)s?\s+(?:permission|authority|scope)\b", startup_folded):
        errors.append("runtime/load_order.md Startup state must not grant permission, authority, or scope")


def conditional_state_line_is_bounded(text: str, filename: str) -> bool:
    for _line_number, line in markdown_structure.operative_lines(text):
        if filename not in line:
            continue
        folded = line.casefold()
        if "only" in folded or "when" in folded or "unless" in folded:
            return True
    return False


def validate_workflow_selection_policy(workflow_catalog: dict[str, Any], errors: list[str]) -> None:
    policy = workflow_catalog.get("workflow_selection")
    if not isinstance(policy, dict):
        errors.append("workflow catalog must define workflow_selection policy")
        return
    provenance = policy.get("known_workflow_provenance")
    required_provenance = {
        "explicit task-order metadata",
        "command argument",
        "bootstrap field",
        "issue or ticket label",
        "project contract entry",
        "named workflow sequence",
        "single unambiguous natural-language match to one catalog workflow",
    }
    if not (
        isinstance(provenance, list)
        and len(provenance) == len(required_provenance)
        and all(isinstance(item, str) and item.strip() for item in provenance)
        and set(provenance) == required_provenance
    ):
        errors.append(
            "workflow_selection known_workflow_provenance must match supported selection evidence"
        )
    ambiguous_route = policy.get("ambiguous_workflow_route")
    if not isinstance(ambiguous_route, dict):
        errors.append("workflow_selection ambiguous_workflow_route must be a structural route object")
        return
    conditions = ambiguous_route.get("conditions")
    required_conditions = {
        "unknown_or_no_matching_workflow",
        "ambiguous_task_intent",
        "multiple_matching_workflows",
    }
    if not (
        isinstance(conditions, list)
        and len(conditions) == len(required_conditions)
        and all(isinstance(item, str) for item in conditions)
        and set(conditions) == required_conditions
    ):
        errors.append("workflow_selection ambiguous_workflow_route conditions drift")
    if ambiguous_route.get("required_action") != "load_router_or_full_candidate_task_order":
        errors.append("workflow_selection ambiguous_workflow_route required_action drift")
    fallback_references = ambiguous_route.get("fallback_references")
    required_fallback_references = {
        "task_orders/README.md",
        "runtime/workflow_catalog.json",
    }
    if not (
        isinstance(fallback_references, list)
        and len(fallback_references) == len(required_fallback_references)
        and all(isinstance(item, str) for item in fallback_references)
        and set(fallback_references) == required_fallback_references
    ):
        errors.append("workflow_selection ambiguous_workflow_route fallback_references drift")
    if ambiguous_route.get("forbidden_action") != "choose_compact_runtime_task_module_by_guesswork":
        errors.append("workflow_selection ambiguous_workflow_route forbidden_action drift")


def catalog_task_module_bindings(
    catalog_entries: list[dict[str, Any]],
) -> tuple[
    dict[str, str],
    dict[str, dict[str, str]],
    dict[str, dict[str, str]],
]:
    catalog_by_module: dict[str, str] = {}
    catalog_condition_identities: dict[str, dict[str, str]] = {}
    catalog_condition_delegations: dict[str, dict[str, str]] = {}
    for entry in catalog_entries:
        module = entry.get("runtime_task_module")
        if not isinstance(module, dict):
            continue
        module_path = module.get("path")
        canonical = module.get("canonical_task_order")
        if isinstance(module_path, str) and isinstance(canonical, str):
            catalog_by_module.setdefault(module_path, canonical)
            condition_identities: dict[str, str] = {}
            identity_pairs = _workflow_condition_identity_pairs(
                module.get("use_full_when_conditions")
            )
            condition_id_counts: dict[str, int] = {}
            condition_description_counts: dict[str, int] = {}
            for condition_id, description in identity_pairs:
                condition_id_counts[condition_id] = (
                    condition_id_counts.get(condition_id, 0) + 1
                )
                condition_description_counts[description] = (
                    condition_description_counts.get(description, 0) + 1
                )
            for condition_id, description in identity_pairs:
                if (
                    condition_id_counts[condition_id] == 1
                    and condition_description_counts[description] == 1
                ):
                    condition_identities[condition_id] = description
            condition_delegations = {
                condition_id: obligation_id
                for condition_id, obligation_id in _workflow_condition_delegation_pairs(
                    module.get("use_full_when_conditions")
                )
                if condition_id in condition_identities
            }
            catalog_condition_identities.setdefault(module_path, condition_identities)
            catalog_condition_delegations.setdefault(module_path, condition_delegations)
    return (
        catalog_by_module,
        catalog_condition_identities,
        catalog_condition_delegations,
    )


def validate_task_module_obligation(
    module_rel: str,
    obligation_id: str,
    obligation: object,
    coverage_record: object,
    module_text: str,
    module_prose: str,
    task_order_text: str,
    task_order_prose: str,
    catalog_condition_ids: dict[str, str],
    errors: list[str],
) -> None:
    if not isinstance(obligation, dict):
        errors.append(f"task module obligation {module_rel} {obligation_id} must be an object")
        return
    if obligation.get("risk_class") not in OBLIGATION_RISK_CLASSES:
        errors.append(f"task module obligation {module_rel} {obligation_id} has invalid risk_class")
    summary = obligation.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        errors.append(f"task module obligation {module_rel} {obligation_id} must define summary")
    if not isinstance(coverage_record, dict):
        return
    status = coverage_record.get("status")
    if status not in OBLIGATION_COVERAGE_STATUSES:
        errors.append(f"task module obligation {module_rel} {obligation_id} has invalid coverage status")
        return

    module_marker = coverage_record.get("module_marker")
    catalog_condition_id = coverage_record.get("catalog_condition_id")
    full_order_marker = coverage_record.get("full_order_marker")
    reason = coverage_record.get("reason")
    expected_module_marker = marker("mpa-obligation", obligation_id)
    validate_operative_anchor(
        coverage_record.get("operative_anchor"),
        module_prose,
        f"task module obligation {module_rel} {obligation_id}",
        errors,
    )
    if status == "satisfies":
        if (
            module_marker != f"mpa-obligation: {obligation_id}"
            or expected_module_marker not in module_text
        ):
            errors.append(
                f"task module obligation {module_rel} {obligation_id} satisfies without module marker"
            )
        return
    if status == "delegates_to_full_order":
        if (
            module_marker != f"mpa-obligation: {obligation_id}"
            or expected_module_marker not in module_text
        ):
            errors.append(
                f"task module obligation {module_rel} {obligation_id} delegates without module marker"
            )
        if not isinstance(catalog_condition_id, str) or catalog_condition_id not in catalog_condition_ids:
            errors.append(
                f"task module obligation {module_rel} {obligation_id} delegates without catalog condition id"
            )
        if (
            full_order_marker != f"mpa-full-order-obligation: {obligation_id}"
            or marker("mpa-full-order-obligation", obligation_id) not in task_order_text
        ):
            errors.append(
                f"task module obligation {module_rel} {obligation_id} delegates without full-order marker"
            )
        validate_operative_anchor(
            coverage_record.get("full_order_anchor"),
            task_order_prose,
            f"task module obligation {module_rel} {obligation_id} full order",
            errors,
            "full_order_anchor",
        )
        return
    if (
        module_marker != f"mpa-obligation: {obligation_id}"
        or expected_module_marker not in module_text
    ):
        errors.append(
            f"task module obligation {module_rel} {obligation_id} not_applicable without module marker"
        )
    if not isinstance(reason, str) or not reason.strip():
        errors.append(f"task module obligation {module_rel} {obligation_id} not_applicable needs reason")


def validate_task_module_obligation_rule(
    module_rel: str,
    raw_rule: object,
    common_marker: str,
    catalog_by_module: dict[str, str],
    catalog_condition_identities: dict[str, dict[str, str]],
    catalog_condition_delegations: dict[str, dict[str, str]],
    errors: list[str],
) -> None:
    if not isinstance(raw_rule, dict):
        errors.append(f"task module obligations {module_rel} must be an object")
        return
    source_task_order = raw_rule.get("source_task_order")
    if source_task_order != catalog_by_module.get(module_rel):
        errors.append(
            f"task module obligations {module_rel} source_task_order must match workflow catalog canonical_task_order"
        )
    critical = raw_rule.get("critical_obligations")
    coverage = raw_rule.get("runtime_coverage")
    if not isinstance(critical, dict) or not critical:
        errors.append(f"task module obligations {module_rel} must define critical_obligations")
        return
    if not isinstance(coverage, dict):
        errors.append(f"task module obligations {module_rel} must define runtime_coverage")
        return
    if set(critical) != set(coverage):
        missing = sorted(set(critical) - set(coverage))
        extra = sorted(set(coverage) - set(critical))
        if missing:
            errors.append(f"task module obligations {module_rel} missing coverage for: {', '.join(missing)}")
        if extra:
            errors.append(f"task module obligations {module_rel} has unknown coverage for: {', '.join(extra)}")

    module_text = read_repo_text(
        module_rel,
        errors,
        f"task module obligations module {module_rel}",
    )
    module_prose = operative_prose(module_text)
    if bare_marker(common_marker) not in module_text:
        errors.append(f"task module {module_rel} missing common project-contract precondition")
    task_order_text = read_repo_text(
        source_task_order,
        errors,
        f"task module obligations task order {source_task_order}",
    )
    task_order_prose = operative_prose(task_order_text)
    catalog_condition_ids = catalog_condition_identities.get(module_rel, {})
    for obligation_id, obligation in sorted(critical.items()):
        validate_task_module_obligation(
            module_rel,
            obligation_id,
            obligation,
            coverage.get(obligation_id),
            module_text,
            module_prose,
            task_order_text,
            task_order_prose,
            catalog_condition_ids,
            errors,
        )

    manifest_delegation_owners: dict[str, list[str]] = {}
    for obligation_id, coverage_record in coverage.items():
        if not (
            isinstance(obligation_id, str)
            and isinstance(coverage_record, dict)
            and coverage_record.get("status") == "delegates_to_full_order"
        ):
            continue
        condition_id = coverage_record.get("catalog_condition_id")
        if isinstance(condition_id, str) and condition_id.strip():
            manifest_delegation_owners.setdefault(condition_id, []).append(
                obligation_id
            )

    manifest_delegations: dict[str, str] = {}
    for condition_id, owners in sorted(manifest_delegation_owners.items()):
        if len(owners) != 1:
            errors.append(
                f"task module obligations {module_rel} delegated catalog condition "
                f"{condition_id} has multiple obligation owners: {', '.join(sorted(owners))}"
            )
            continue
        manifest_delegations[condition_id] = owners[0]

    catalog_delegations = catalog_condition_delegations.get(module_rel, {})
    for condition_id in sorted(set(catalog_delegations) | set(manifest_delegations)):
        expected_obligation = catalog_delegations.get(condition_id)
        actual_obligation = manifest_delegations.get(condition_id)
        if expected_obligation != actual_obligation:
            errors.append(
                f"task module obligations {module_rel} delegated condition-obligation "
                f"identity mismatch for {condition_id}: catalog={expected_obligation!r}, "
                f"manifest={actual_obligation!r}"
            )


def validate_runtime_task_module_obligations(
    manifest: dict[str, Any],
    catalog_entries: list[dict[str, Any]],
    errors: list[str],
) -> None:
    """Validate critical-obligation markers and their bound operative prose."""
    if not exact_schema_version(manifest.get("schema_version"), 2):
        errors.append("task module obligations schema_version must be 2")
    statuses = manifest.get("coverage_statuses")
    if not isinstance(statuses, list) or not all(isinstance(item, str) for item in statuses):
        errors.append("task module obligations coverage_statuses must be a string list")
    elif sorted(statuses) != sorted(OBLIGATION_COVERAGE_STATUSES):
        errors.append("task module obligations coverage_statuses drift")
    common_precondition = manifest.get("common_precondition")
    common_marker = "mpa-common-precondition"
    if not isinstance(common_precondition, dict):
        errors.append("task module obligations common_precondition must be an object")
    else:
        common_summary = common_precondition.get("summary")
        if not isinstance(common_summary, str) or not common_summary.strip():
            errors.append("task module obligations common_precondition must define summary")
        if common_precondition.get("module_marker") != common_marker:
            errors.append("task module obligations common_precondition module_marker drift")

    (
        catalog_by_module,
        catalog_condition_identities,
        catalog_condition_delegations,
    ) = catalog_task_module_bindings(catalog_entries)
    modules = manifest.get("modules")
    if not isinstance(modules, dict):
        errors.append("task module obligations modules must be an object")
        return
    runtime_module_paths = {
        path.relative_to(REPO_ROOT).as_posix()
        for path in (REPO_ROOT / "runtime" / "task_modules").glob("*.md")
    }
    if set(modules) != runtime_module_paths:
        missing = sorted(runtime_module_paths - set(modules))
        extra = sorted(set(modules) - runtime_module_paths)
        if missing:
            errors.append(f"task module obligations missing modules: {', '.join(missing)}")
        if extra:
            errors.append(f"task module obligations has unknown modules: {', '.join(extra)}")

    for module_rel, raw_rule in sorted(modules.items()):
        validate_task_module_obligation_rule(
            module_rel,
            raw_rule,
            common_marker,
            catalog_by_module,
            catalog_condition_identities,
            catalog_condition_delegations,
            errors,
        )


def load_consistency_documents(errors: list[str]) -> ConsistencyDocuments:
    loaded: set[str] = set()

    def load_document(name: str, rel: str, label: str) -> dict[str, Any]:
        document = load_json(rel, errors, label)
        if document is None:
            return {}
        loaded.add(name)
        return document

    contract = load_document(
        "contract",
        "runtime/consistency_contract.json",
        "consistency contract",
    )
    schedule = load_document(
        "schedule",
        "runtime/operative_schedule.json",
        "operative schedule",
    )
    workflow_catalog = load_document(
        "workflow_catalog",
        "runtime/workflow_catalog.json",
        "workflow catalog",
    )
    task_module_obligations = load_document(
        "task_module_obligations",
        "runtime/task_module_obligations.json",
        "task module obligations",
    )
    finding_schema = load_document(
        "finding_schema",
        "runtime/finding_schema.json",
        "finding schema",
    )
    conformance_profiles = load_document(
        "conformance_profiles",
        "conformance/profiles.json",
        "conformance profiles",
    )
    registry = load_integration_registry(errors)
    if registry is None:
        registry = {}
    else:
        loaded.add("registry")
    clause_map = load_document(
        "clause_map",
        "runtime/msa_clause_map.json",
        "MSA clause map",
    )
    return ConsistencyDocuments(
        contract=contract,
        schedule=schedule,
        workflow_catalog=workflow_catalog,
        task_module_obligations=task_module_obligations,
        finding_schema=finding_schema,
        conformance_profiles=conformance_profiles,
        registry=registry,
        clause_map=clause_map,
        loaded=frozenset(loaded),
    )


def validate_clause_map_contract(
    contract: dict[str, Any], clause_map: dict[str, Any], errors: list[str]
) -> None:
    clause_contract = contract.get("clause_map")
    if not isinstance(clause_contract, dict):
        errors.append("consistency contract clause_map must be an object")
        return
    expected_schema_version = clause_contract.get("schema_version")
    if type(expected_schema_version) is not int:
        errors.append("consistency contract clause_map.schema_version must be an integer")
        expected_schema_version = -1
    if not exact_schema_version(
        clause_map.get("schema_version"), expected_schema_version
    ):
        errors.append("clause map schema_version does not match consistency contract")
    if clause_map.get("msa_version") != msa_version(errors):
        errors.append("clause map msa_version does not match master_service_agreement.md")
    if not clause_map.get("reviewed_on"):
        errors.append("clause map reviewed_on is required")
    validate_msa_digest(clause_map, errors)
    allowed_disposition_values = string_list(
        clause_contract.get("allowed_dispositions"),
        "consistency contract clause_map.allowed_dispositions",
        errors,
        non_empty=True,
    )
    allowed_dispositions = set(allowed_disposition_values)
    human_clause_map = read_repo_text(
        "runtime/clause_classification.md",
        errors,
        "human-readable clause classification",
    )
    clause_rows = clause_map.get("clauses")
    if not isinstance(clause_rows, list) or not clause_rows:
        errors.append("clause map clauses must be a non-empty list")
        clause_rows = []
    typed_clause_rows = [row for row in clause_rows if isinstance(row, dict)]
    validate_clause_id_coverage(typed_clause_rows, errors)
    validate_human_clause_table(typed_clause_rows, human_clause_map, errors)
    for row in clause_rows:
        if not isinstance(row, dict):
            errors.append("clause map row must be an object")
            continue
        source = row.get("source", "<unknown>")
        errors.extend(unknown_field_errors(f"clause map {source}", row, CLAUSE_ROW_FIELDS))
        dispositions = row.get("dispositions")
        if not isinstance(dispositions, list) or not dispositions:
            errors.append(f"clause map {source} must have non-empty dispositions")
            continue
        unknown_dispositions = sorted(set(dispositions) - allowed_dispositions)
        if unknown_dispositions:
            errors.append(f"clause map {source} has unknown dispositions: {', '.join(unknown_dispositions)}")
        if isinstance(source, str) and source not in human_clause_map:
            errors.append(f"human-readable clause classification missing source: {source}")
        operative_home = row.get("operative_home")
        if not isinstance(operative_home, list) or not operative_home:
            errors.append(f"clause map {source} must have non-empty operative_home")
        elif "projected" in dispositions and not any(
            isinstance(home, str) and home.startswith("runtime/") for home in operative_home
        ):
            errors.append(f"projected clause lacks runtime projection: {source}")
        validate_clause_projection_markers(row, errors)


def validate_practice_guide_contract(
    schedule: dict[str, Any], registry: dict[str, Any], errors: list[str]
) -> None:
    families = registry.get("families")
    if not isinstance(families, dict):
        errors.append("integration registry families must be an object")
        return
    practice_guides = schedule.get("practice_guides")
    if not isinstance(practice_guides, list):
        errors.append("operative schedule practice_guides must be a list")
        practice_guides = []
    for index, guide in enumerate(practice_guides):
        if not isinstance(guide, dict):
            errors.append(f"operative schedule practice_guides[{index}] must be an object")
            continue
        errors.extend(
            unknown_field_errors(
                f"operative schedule {guide.get('name', index)}",
                guide,
                PRACTICE_GUIDE_FIELDS,
            )
        )
        wrapper_status = guide.get("wrapper_status")
        if wrapper_status not in WRAPPER_STATUSES:
            errors.append(
                f"operative schedule {guide.get('name', index)} has invalid wrapper_status: {wrapper_status}"
            )
        if wrapper_status not in {"candidate", "required"}:
            continue
        name = guide.get("name")
        for family, config in families.items():
            if not isinstance(config, dict):
                errors.append(f"integration registry family {family} must be an object")
                continue
            wrappers = config.get("wrappers", {})
            if not isinstance(wrappers, dict):
                errors.append(f"integration registry family {family} wrappers must be an object")
                continue
            if family == "generic" and not wrappers:
                continue
            wrapper = wrappers.get(name) if isinstance(name, str) else None
            if wrapper is not None and not isinstance(wrapper, dict):
                errors.append(
                    f"integration registry {family} wrapper {name} must be an object"
                )
                continue
            rel = wrapper.get("path") if isinstance(wrapper, dict) else None
            if rel is not None and not (REPO_ROOT / rel).is_file():
                errors.append(
                    f"registered {family} wrapper path missing for "
                    f"{guide.get('name', index)}: {rel}"
                )
            if wrapper_status == "required" and rel is None:
                errors.append(
                    f"missing {family} wrapper for required native wrapper "
                    f"{guide.get('name', index)}"
                )


def validate_schedule_contract(documents: ConsistencyDocuments, errors: list[str]) -> None:
    if "schedule" in documents.loaded:
        run_validation_phase(
            "operative schedule minimum evidence",
            errors,
            lambda: validate_minimum_evidence_by_risk(documents.schedule, errors),
        )
        run_validation_phase(
            "operative schedule authority scope",
            errors,
            lambda: framework_contracts.validate_operative_schedule_authority_scope(
                documents.schedule,
                errors,
            ),
        )
    if "finding_schema" in documents.loaded:
        run_validation_phase(
            "finding schema",
            errors,
            lambda: validate_finding_schema(documents.finding_schema, errors),
        )
    if "conformance_profiles" in documents.loaded:
        run_validation_phase(
            "conformance profiles",
            errors,
            lambda: validate_conformance_profiles(
                documents.conformance_profiles,
                errors,
            ),
        )
    if {"schedule", "registry"}.issubset(documents.loaded):
        run_validation_phase(
            "practice guide registry",
            errors,
            lambda: validate_practice_guide_contract(
                documents.schedule,
                documents.registry,
                errors,
            ),
        )
    if "schedule" in documents.loaded:
        raw_guides = documents.schedule.get("practice_guides", [])
        if not isinstance(raw_guides, list):
            raw_guides = []
        guides = {
            guide["name"]
            for guide in raw_guides
            if isinstance(guide, dict) and isinstance(guide.get("name"), str)
        }
        run_validation_phase(
            "verification registry",
            errors,
            lambda: errors.extend(
                verification_registry.registry_errors(
                    allowed_flags=routing_policy.allowed_trigger_flags(),
                    known_guides=guides,
                )
            ),
        )


def integration_entrypoint_specs(
    registry: dict[str, Any],
    errors: list[str],
) -> list[tuple[str, str]]:
    families = registry.get("families")
    if not isinstance(families, dict):
        errors.append("integration registry families must be an object")
        return []
    specs: list[tuple[str, str]] = []
    for family, config in families.items():
        if not isinstance(config, dict):
            errors.append(f"integration registry family {family} must be an object")
            continue
        entrypoint = config.get("entrypoint")
        if not isinstance(entrypoint, dict):
            errors.append(
                f"integration registry family {family} entrypoint must be an object"
            )
            continue
        path = entrypoint.get("path")
        if not isinstance(path, str) or not path:
            errors.append(
                f"integration registry family {family} entrypoint.path must be a non-empty string"
            )
            continue
        output = entrypoint.get("output")
        if not isinstance(output, str) or not output:
            errors.append(
                f"integration registry family {family} entrypoint.output must be a non-empty string"
            )
            continue
        specs.append((path, output))
    return specs


def validate_entrypoint_contract(
    contract: dict[str, Any],
    errors: list[str],
    warnings: list[str],
    *,
    registry: dict[str, Any] | None = None,
) -> None:
    entrypoint_rules = contract.get("entrypoints")
    if not isinstance(entrypoint_rules, dict):
        errors.append("entrypoint consistency contract must be an object")
        return
    errors.extend(
        unknown_field_errors(
            "entrypoint consistency contract",
            entrypoint_rules,
            {
                "forbid_eager_practice_guide_imports",
                "forbidden_state_loading_fragments",
            },
        )
    )
    forbidden_state_loading_fragments = string_list(
        entrypoint_rules.get("forbidden_state_loading_fragments"),
        "entrypoint consistency contract forbidden_state_loading_fragments",
        errors,
    )
    forbid_eager_imports = entrypoint_rules.get(
        "forbid_eager_practice_guide_imports"
    )
    if not isinstance(forbid_eager_imports, bool):
        errors.append(
            "entrypoint consistency contract forbid_eager_practice_guide_imports "
            "must be a boolean"
        )
        forbid_eager_imports = False
    if registry is None:
        registry = load_integration_registry(errors)
    entrypoint_specs = (
        integration_entrypoint_specs(registry, errors)
        if registry is not None
        else []
    )
    framework_reference_probe = "/__mpa_framework_reference_probe__"
    contract_root_probe = ".mpa-contract-probe"
    for rel, output in entrypoint_specs:
        text = read_repo_text(rel, errors, f"entrypoint {rel}")
        try:
            rendered = integration_registry.render_template_text(
                text,
                framework_reference_probe,
                contract_root_probe,
                template_label=rel,
            )
        except ValueError as exc:
            errors.append(f"entrypoint consistency failure: {rel}: {exc}")
            rendered = ""
        if rendered:
            reference, structural_errors = (
                integration_registry.entrypoint_authority_load_references(
                    output,
                    rendered,
                    contract_root_ref=contract_root_probe,
                    repo_root=REPO_ROOT,
                )
            )
            errors.extend(
                f"entrypoint consistency failure: {rel}: {error}"
                for error in structural_errors
            )
            if (
                reference is not None
                and reference != framework_reference_probe
            ):
                errors.append(
                    f"entrypoint consistency failure: {rel} marker-owned framework "
                    "reference does not preserve the registry-rendered framework token"
                )
        for fragment in forbidden_state_loading_fragments:
            if fragment in text:
                errors.append(
                    f"entrypoint consistency failure: {rel} duplicates state-loading detail {fragment!r}"
                )
        if forbid_eager_imports:
            for _line_number, line in markdown_structure.operative_lines(text):
                stripped = line.strip()
                if stripped.startswith("@") and "practice_guides/" in stripped:
                    warnings.append(f"entrypoint should stay thin: {rel} eagerly imports {stripped}")


def validate_project_contract_first(contract: dict[str, Any], errors: list[str]) -> None:
    contract_first = contract.get("project_contract_first")
    if not isinstance(contract_first, dict):
        errors.append("project_contract_first consistency contract must be an object")
        return
    task_orders = string_list(
        contract_first.get("task_orders"),
        "project_contract_first task_orders",
        errors,
    )
    required_references = string_list(
        contract_first.get("required_references"),
        "project_contract_first required_references",
        errors,
    )
    forbidden_phrases = string_list(
        contract_first.get("forbidden_phrases"),
        "project_contract_first forbidden_phrases",
        errors,
    )
    for rel in task_orders:
        text = read_repo_text(rel, errors, f"project_contract_first task order {rel}")
        for reference in required_references:
            if reference not in text:
                errors.append(f"task-order consistency failure: {rel} missing reference {reference}")
        for phrase in forbidden_phrases:
            if phrase in text:
                errors.append(f"task-order consistency failure: {rel} still contains {phrase!r}")


def validate_setup_docs(contract: dict[str, Any], errors: list[str]) -> None:
    setup_docs = contract.get("setup_docs")
    if not isinstance(setup_docs, dict):
        errors.append("setup_docs consistency contract must be an object")
        return
    for rel, raw_references in setup_docs.items():
        if not isinstance(rel, str) or not rel:
            errors.append("setup_docs paths must be non-empty strings")
            continue
        references = string_list(
            raw_references,
            f"setup_docs references for {rel}",
            errors,
        )
        text = read_repo_text(rel, errors, f"setup doc {rel}")
        for reference in references:
            if reference not in text:
                errors.append(f"setup consistency failure: {rel} missing reference {reference}")


def validate_load_order_consistency(contract: dict[str, Any], errors: list[str]) -> None:
    load_order_contract = contract.get("load_order_contract")
    load_order_rel = "runtime/load_order.md"
    load_order_text = read_repo_text(
        load_order_rel,
        errors,
        f"load-order contract {load_order_rel}",
    )
    validate_runtime_load_order(load_order_text, load_order_contract, errors)


def validate_orchestration_handoff(contract: dict[str, Any], errors: list[str]) -> None:
    orchestration_contract = contract.get("orchestration_handoff")
    if not orchestration_contract:
        return
    if not isinstance(orchestration_contract, dict):
        errors.append("orchestration_handoff consistency contract must be an object")
        return
    rel = orchestration_contract.get("path")
    if not isinstance(rel, str) or not rel:
        errors.append("orchestration_handoff path must be a non-empty string")
        return
    required_markers = string_list(
        orchestration_contract.get("required_markers"),
        "orchestration_handoff required_markers",
        errors,
    )
    required_references = string_list(
        orchestration_contract.get("required_references"),
        "orchestration_handoff required_references",
        errors,
    )
    text = read_repo_text(rel, errors, f"orchestration handoff {rel}")
    for marker_id in required_markers:
        if marker("mpa-orchestration-contract", marker_id) not in text:
            errors.append(f"orchestration handoff consistency failure: {rel} missing marker {marker_id}")
    for reference in required_references:
        if reference not in text:
            errors.append(f"orchestration handoff consistency failure: {rel} missing reference {reference}")


def validate_integration_readme(contract: dict[str, Any], errors: list[str]) -> None:
    integration_readme = contract.get("integration_readme", {})
    if not isinstance(integration_readme, dict):
        errors.append("integration_readme consistency contract must be an object")
        return
    required_options = string_list(
        integration_readme.get("required_options"),
        "integration_readme required_options",
        errors,
    )
    integration_text = read_repo_text("integrations/README.md", errors, "integration README")
    for option in required_options:
        if option not in integration_text:
            errors.append(f"integration README missing option: {option}")


def validate_runtime_module_contract(
    contract: dict[str, Any], task_module_obligations: dict[str, Any], errors: list[str]
) -> None:
    runtime_module_contract = contract.get("runtime_module_contract", {})
    if not isinstance(runtime_module_contract, dict):
        errors.append("runtime_module_contract must be an object")
        return
    runtime_module_paths = {
        path.relative_to(REPO_ROOT).as_posix()
        for path in (REPO_ROOT / "runtime" / "task_modules").glob("*.md")
    }
    if not exact_schema_version(runtime_module_contract.get("schema_version"), 1):
        errors.append("runtime_module_contract.schema_version must be 1")
    if runtime_module_contract.get("module_dir") != "runtime/task_modules":
        errors.append("runtime_module_contract.module_dir must be runtime/task_modules")
    if runtime_module_contract.get("obligation_manifest") != "runtime/task_module_obligations.json":
        errors.append("runtime_module_contract.obligation_manifest must be runtime/task_module_obligations.json")
    modules = task_module_obligations.get("modules")
    if not isinstance(modules, dict):
        errors.append("task module obligations modules must be an object")
    elif set(modules) != runtime_module_paths:
        errors.append("runtime_module_contract module coverage must match task_module_obligations modules")


def validate_documentation_contract(contract: dict[str, Any], errors: list[str]) -> None:
    docs_contract = contract.get("documentation_consistency")
    if not isinstance(docs_contract, dict):
        errors.append("documentation_consistency contract must be an object")
        return
    docs = docs_contract.get("docs")
    if not isinstance(docs, dict):
        errors.append("documentation_consistency docs must be an object")
        return
    for rel, raw_references in docs.items():
        if not isinstance(rel, str) or not rel:
            errors.append("documentation_consistency paths must be non-empty strings")
            continue
        references = string_list(
            raw_references,
            f"documentation_consistency references for {rel}",
            errors,
        )
        text = read_repo_text(rel, errors, f"documentation consistency {rel}")
        for reference in references:
            if reference not in text:
                errors.append(f"documentation consistency failure: {rel} missing reference {reference}")


def validated_catalog_entries(
    workflow_catalog: dict[str, Any], errors: list[str]
) -> list[dict[str, Any]]:
    task_order_paths = sorted(
        path.relative_to(REPO_ROOT).as_posix()
        for path in (REPO_ROOT / "task_orders").glob("*.md")
        if path.name != "README.md"
    )
    if not exact_schema_version(workflow_catalog.get("schema_version"), 1):
        errors.append("workflow catalog schema_version must be exactly integer 1")
    validate_workflow_selection_policy(workflow_catalog, errors)
    catalog_entries_raw = workflow_catalog.get("task_orders", [])
    if not isinstance(catalog_entries_raw, list):
        errors.append("workflow catalog task_orders must be a list")
        catalog_entries_raw = []
    catalog_entries: list[dict[str, Any]] = []
    for index, entry in enumerate(catalog_entries_raw):
        if not isinstance(entry, dict):
            errors.append(f"workflow catalog task_orders[{index}] must be an object")
            continue
        catalog_entries.append(entry)
    catalog_paths = sorted(
        entry["path"] for entry in catalog_entries if isinstance(entry.get("path"), str)
    )
    path_owners: dict[str, str] = {}
    for position, entry in enumerate(catalog_entries):
        task_order_path = entry.get("path")
        if not isinstance(task_order_path, str):
            continue
        raw_name = entry.get("name")
        owner = raw_name if isinstance(raw_name, str) and raw_name else f"entry {position}"
        prior_owner = path_owners.get(task_order_path)
        if prior_owner is not None:
            errors.append(
                f"workflow catalog task order path {task_order_path} has multiple owners: "
                f"{prior_owner}, {owner}"
            )
        else:
            path_owners[task_order_path] = owner
    if task_order_paths != catalog_paths:
        if len(task_order_paths) != len(catalog_paths):
            errors.append(
                "workflow catalog task order path cardinality must match the task_orders inventory"
            )
        missing = sorted(set(task_order_paths) - set(catalog_paths))
        extra = sorted(set(catalog_paths) - set(task_order_paths))
        if missing:
            errors.append(f"workflow catalog missing task orders: {', '.join(missing)}")
        if extra:
            errors.append(f"workflow catalog has unknown task orders: {', '.join(extra)}")
    return catalog_entries


def validate_direct_full_routing_flags(
    name: str,
    module: object,
    direct_flags: object,
    direct_full_flag_owners: dict[str, str],
    errors: list[str],
) -> None:
    if direct_flags is None:
        return
    if module is not None:
        errors.append(
            f"workflow catalog {name} direct_full_when_flags cannot coexist with a runtime task module"
        )
    if not isinstance(direct_flags, list) or not direct_flags or not all(
        isinstance(flag, str) and flag for flag in direct_flags
    ):
        errors.append(
            f"workflow catalog {name} direct_full_when_flags must be a non-empty string list"
        )
        return
    for flag in direct_flags:
        if flag not in routing_policy.allowed_trigger_flags():
            errors.append(
                f"workflow catalog {name} direct_full_when_flags uses unknown routing flag: {flag}"
            )
        prior = direct_full_flag_owners.get(flag)
        if prior is not None:
            errors.append(
                f"workflow catalog direct full routing flag {flag} has multiple owners: {prior}, {name}"
            )
        else:
            direct_full_flag_owners[flag] = name


def validate_catalog_runtime_module(
    name: str,
    task_order_path: str,
    module: object,
    catalog_module_names: list[str],
    catalog_module_paths: list[str],
    module_name_owners: dict[str, str],
    module_path_owners: dict[str, str],
    errors: list[str],
) -> bool:
    if module is None:
        return True
    if not isinstance(module, dict):
        errors.append(f"workflow catalog {name} runtime_task_module must be an object")
        return False
    module_name = module.get("name")
    if not isinstance(module_name, str) or not module_name:
        errors.append(f"workflow catalog {name} runtime module must define name")
        return False
    catalog_module_names.append(module_name)
    prior_name_owner = module_name_owners.get(module_name)
    if prior_name_owner is not None:
        errors.append(
            f"workflow catalog runtime module name {module_name} has multiple owners: "
            f"{prior_name_owner}, {name}"
        )
    else:
        module_name_owners[module_name] = name
    if module.get("canonical_task_order") != task_order_path:
        errors.append(
            f"workflow catalog {name} runtime module canonical_task_order must be {task_order_path}"
        )
    use_full_when = module.get("use_full_when")
    if not isinstance(use_full_when, list) or not use_full_when or not all(
        isinstance(item, str) and item for item in use_full_when
    ):
        errors.append(f"workflow catalog {name} runtime module must define use_full_when")
    finding_schema_ref = module.get("finding_schema")
    if name in {"review", "audit"}:
        if finding_schema_ref != "runtime/finding_schema.json":
            errors.append(f"workflow catalog {name} runtime module must reference finding schema")
    elif finding_schema_ref is not None:
        errors.append(f"workflow catalog {name} runtime module has unexpected finding_schema")
    module_path_value = module.get("path")
    if not isinstance(module_path_value, str) or not module_path_value:
        errors.append(f"workflow catalog {name} runtime module must define path")
        return False
    catalog_module_paths.append(module_path_value)
    prior_path_owner = module_path_owners.get(module_path_value)
    if prior_path_owner is not None:
        errors.append(
            f"workflow catalog runtime module path {module_path_value} has multiple owners: "
            f"{prior_path_owner}, {name}"
        )
    else:
        module_path_owners[module_path_value] = name
    expected_module_path = f"runtime/task_modules/{module_name}.md"
    if module_path_value != expected_module_path:
        errors.append(
            f"workflow catalog {name} runtime module path must be {expected_module_path}"
        )
    module_path = resolve_repo_file(
        module_path_value,
        errors,
        f"workflow catalog module path {module_path_value}",
    )
    if module_path is not None and not module_path.exists():
        errors.append(f"workflow catalog task module path missing for {name}: {module_path_value}")
    return True


def validate_catalog_transitions(
    entry: dict[str, Any], name: str, catalog_names: list[str], errors: list[str]
) -> None:
    common_next_orders = entry.get("common_next_orders", [])
    for next_name in common_next_orders:
        if next_name not in catalog_names:
            errors.append(f"workflow catalog {name} references unknown next order: {next_name}")
    common_next_steps = entry.get("common_next_steps")
    if common_next_steps is not None:
        projected_orders = direct_unguarded_step_orders(common_next_steps)
        if common_next_orders != projected_orders:
            errors.append(
                f"workflow catalog {name} common_next_orders must match unguarded "
                f"direct common_next_steps orders: {projected_orders}"
            )
    for next_name in iter_step_orders(
        common_next_steps or [],
        errors,
        f"{name}.common_next_steps",
    ):
        if next_name not in catalog_names:
            errors.append(f"workflow catalog {name} references unknown next order: {next_name}")
    for steps_key, branch_label in (
        ("outcome_next_steps", "outcome"),
        ("mode_next_steps", "mode"),
    ):
        branches = entry.get(steps_key, {})
        if not isinstance(branches, dict):
            continue
        for branch, steps in branches.items():
            for next_name in iter_step_orders(
                steps,
                errors,
                f"{name}.{steps_key}.{branch}",
            ):
                if next_name not in catalog_names:
                    errors.append(
                        f"workflow catalog {name} {branch_label} {branch} references "
                        f"unknown next order: {next_name}"
                    )


def validate_catalog_entry(
    entry: dict[str, Any],
    position: int,
    catalog_names: list[str],
    catalog_module_names: list[str],
    catalog_module_paths: list[str],
    module_name_owners: dict[str, str],
    module_path_owners: dict[str, str],
    direct_full_flag_owners: dict[str, str],
    errors: list[str],
) -> None:
    name = entry.get("name")
    task_order_path = entry.get("path")
    if not isinstance(name, str) or not name:
        errors.append(f"workflow catalog entry {position} must define name")
        return
    if not isinstance(task_order_path, str) or not task_order_path:
        errors.append(f"workflow catalog {name} must define path")
        return
    expected_task_order_path = f"task_orders/{name}.md"
    if task_order_path != expected_task_order_path:
        errors.append(
            f"workflow catalog {name} path must be {expected_task_order_path}"
        )
    path = resolve_repo_file(task_order_path, errors, f"workflow catalog path {task_order_path}")
    if path is not None and not path.exists():
        errors.append(f"workflow catalog path missing: {task_order_path}")
    module = entry.get("runtime_task_module")
    validate_direct_full_routing_flags(
        name,
        module,
        entry.get("direct_full_when_flags"),
        direct_full_flag_owners,
        errors,
    )
    if not validate_catalog_runtime_module(
        name,
        task_order_path,
        module,
        catalog_module_names,
        catalog_module_paths,
        module_name_owners,
        module_path_owners,
        errors,
    ):
        return
    validate_catalog_transitions(entry, name, catalog_names, errors)


def validate_catalog_entries(
    catalog_entries: list[dict[str, Any]],
    task_module_obligations: dict[str, Any],
    errors: list[str],
) -> list[str]:
    catalog_names = [
        entry["name"] for entry in catalog_entries if isinstance(entry.get("name"), str)
    ]
    if len(catalog_names) != len(set(catalog_names)):
        errors.append("workflow catalog contains duplicate task order names")
    validate_guarded_workflow_transitions(catalog_entries, errors)

    runtime_module_names = sorted(
        path.stem for path in (REPO_ROOT / "runtime" / "task_modules").glob("*.md")
    )
    runtime_module_paths = sorted(
        path.relative_to(REPO_ROOT).as_posix()
        for path in (REPO_ROOT / "runtime" / "task_modules").glob("*.md")
    )
    catalog_module_names: list[str] = []
    catalog_module_paths: list[str] = []
    module_name_owners: dict[str, str] = {}
    module_path_owners: dict[str, str] = {}
    direct_full_flag_owners: dict[str, str] = {}
    for position, entry in enumerate(catalog_entries):
        validate_catalog_entry(
            entry,
            position,
            catalog_names,
            catalog_module_names,
            catalog_module_paths,
            module_name_owners,
            module_path_owners,
            direct_full_flag_owners,
            errors,
        )
    if sorted(catalog_module_names) != runtime_module_names:
        if len(catalog_module_names) != len(runtime_module_names):
            errors.append(
                "workflow catalog runtime module name cardinality must match the runtime module inventory"
            )
        missing = sorted(set(runtime_module_names) - set(catalog_module_names))
        extra = sorted(set(catalog_module_names) - set(runtime_module_names))
        if missing:
            errors.append(f"workflow catalog missing runtime task modules: {', '.join(missing)}")
        if extra:
            errors.append(f"workflow catalog references unknown runtime task modules: {', '.join(extra)}")
    if sorted(catalog_module_paths) != runtime_module_paths:
        if len(catalog_module_paths) != len(runtime_module_paths):
            errors.append(
                "workflow catalog runtime module path cardinality must match the runtime module inventory"
            )
        missing_paths = sorted(set(runtime_module_paths) - set(catalog_module_paths))
        extra_paths = sorted(set(catalog_module_paths) - set(runtime_module_paths))
        if missing_paths:
            errors.append(
                "workflow catalog missing runtime task module paths: "
                + ", ".join(missing_paths)
            )
        if extra_paths:
            errors.append(
                "workflow catalog references unknown runtime task module paths: "
                + ", ".join(extra_paths)
            )
    validate_runtime_task_module_obligations(task_module_obligations, catalog_entries, errors)
    return catalog_names


def validated_common_sequences(
    workflow_catalog: dict[str, Any], catalog_names: list[str], errors: list[str]
) -> list[dict[str, Any]]:
    common_sequences_raw = workflow_catalog.get("common_sequences", [])
    if not isinstance(common_sequences_raw, list):
        errors.append("workflow catalog common_sequences must be a list")
        common_sequences_raw = []
    common_sequences: list[dict[str, Any]] = []
    sequence_name_owners: dict[str, int] = {}
    for position, sequence in enumerate(common_sequences_raw):
        if not isinstance(sequence, dict):
            errors.append(f"workflow catalog common_sequences[{position}] must be an object")
            continue
        common_sequences.append(sequence)
        sequence_name = sequence.get("name")
        if not isinstance(sequence_name, str) or not sequence_name:
            errors.append(f"workflow catalog common sequence {position} must define name")
            sequence_name = str(position)
        else:
            prior_position = sequence_name_owners.get(sequence_name)
            if prior_position is not None:
                errors.append(
                    f"workflow catalog common sequence name {sequence_name} has multiple owners: "
                    f"positions {prior_position}, {position}"
                )
            else:
                sequence_name_owners[sequence_name] = position
        for step in iter_step_orders(
            sequence.get("steps", []),
            errors,
            f"{sequence_name}.steps",
        ):
            if step not in catalog_names:
                errors.append(f"workflow sequence {sequence_name} references unknown task order: {step}")
        outcome_branches = sequence.get("outcome_branches", {})
        if not isinstance(outcome_branches, dict):
            continue
        for outcome, steps in outcome_branches.items():
            for step in iter_step_orders(
                steps,
                errors,
                f"{sequence_name}.outcome_branches.{outcome}",
            ):
                if step not in catalog_names:
                    errors.append(
                        f"workflow sequence {sequence_name} outcome {outcome} references unknown task order: {step}"
                    )
    return common_sequences


def validate_workflow_catalog_contract(
    workflow_catalog: dict[str, Any],
    task_module_obligations: dict[str, Any],
    errors: list[str],
) -> None:
    validate_workflow_catalog_schema(workflow_catalog, errors)
    catalog_entries = validated_catalog_entries(workflow_catalog, errors)
    catalog_names = validate_catalog_entries(catalog_entries, task_module_obligations, errors)
    common_sequences = validated_common_sequences(workflow_catalog, catalog_names, errors)
    validate_workflow_branch_contracts(catalog_entries, common_sequences, errors)


def collect_consistency_issues() -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    documents = load_consistency_documents(errors)
    run_validation_phase(
        "source-chain artifact contract",
        errors,
        lambda: errors.extend(
            source_chain_artifact_lint.public_contract_errors(
                REPO_ROOT / "docs" / "source_chain_artifacts.md"
            )
        ),
    )
    validate_schedule_contract(documents, errors)
    if {"contract", "clause_map"}.issubset(documents.loaded):
        run_validation_phase(
            "clause map contract",
            errors,
            lambda: validate_clause_map_contract(
                documents.contract,
                documents.clause_map,
                errors,
            ),
        )
    if "contract" in documents.loaded:
        contract_phases: tuple[tuple[str, Callable[[], None]], ...] = (
            (
                "entrypoint contract",
                lambda: validate_entrypoint_contract(
                    documents.contract,
                    errors,
                    warnings,
                    registry=(
                        documents.registry
                        if "registry" in documents.loaded
                        else {"families": {}}
                    ),
                ),
            ),
            (
                "project-contract-first contract",
                lambda: validate_project_contract_first(documents.contract, errors),
            ),
            (
                "setup documentation contract",
                lambda: validate_setup_docs(documents.contract, errors),
            ),
            (
                "load-order contract",
                lambda: validate_load_order_consistency(documents.contract, errors),
            ),
            (
                "orchestration handoff contract",
                lambda: validate_orchestration_handoff(documents.contract, errors),
            ),
            (
                "integration README contract",
                lambda: validate_integration_readme(documents.contract, errors),
            ),
            (
                "documentation contract",
                lambda: validate_documentation_contract(documents.contract, errors),
            ),
        )
        for label, validation in contract_phases:
            run_validation_phase(label, errors, validation)
        if "task_module_obligations" in documents.loaded:
            run_validation_phase(
                "runtime module contract",
                errors,
                lambda: validate_runtime_module_contract(
                    documents.contract,
                    documents.task_module_obligations,
                    errors,
                ),
            )
    if {"workflow_catalog", "task_module_obligations"}.issubset(
        documents.loaded
    ):
        run_validation_phase(
            "workflow catalog contract",
            errors,
            lambda: validate_workflow_catalog_contract(
                documents.workflow_catalog,
                documents.task_module_obligations,
                errors,
            ),
        )
    return errors, warnings


def main(argv: list[str] | None = None) -> int:
    global REPO_ROOT

    parser = argparse.ArgumentParser(
        description=(
            "Validate declared structural and cross-file contract consistency "
            "across one framework tree."
        ),
        allow_abbrev=False,
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_REPO_ROOT,
        help="Framework tree to inspect.",
    )
    args = parser.parse_args(argv)
    original_repo_root = REPO_ROOT
    REPO_ROOT = args.root.resolve()
    try:
        errors, warnings = collect_consistency_issues()
        print(
            json.dumps(
                {"errors": errors, "warnings": warnings},
                indent=2,
                sort_keys=True,
            )
        )
        return 1 if errors else 0
    finally:
        REPO_ROOT = original_repo_root


if __name__ == "__main__":
    raise SystemExit(main())
