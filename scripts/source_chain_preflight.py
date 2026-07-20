#!/usr/bin/env python3

from __future__ import annotations

import argparse
from collections.abc import Mapping
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import sys

import source_chain_artifact_lint
import safe_paths


STAGE_DIRS = {
    "monitor": "source_monitor",
    "review": "source_review",
    "apply": "source_apply",
    "assurance": "automation_assurance",
}
STAGE_ORDER = ("monitor", "review", "apply", "assurance")
EARLIER_STAGES = {
    "monitor": (),
    "review": ("monitor",),
    "apply": ("review", "monitor"),
    "assurance": ("apply", "review", "monitor"),
}
TERMINAL_STATUSES = {
    stage: statuses.copy()
    for stage, statuses in source_chain_artifact_lint.STAGE_STATUSES.items()
}
LOGICAL_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
RUN_SLOT_RE = re.compile(r"^(?:[01]\d|2[0-3])[0-5]\d$")


def expected_stage_settings(
    assignments: Mapping[str, Mapping[str, str]] | None,
    stage: str,
) -> tuple[str | None, str | None, str | None]:
    if assignments is None:
        return None, None, None
    assignment = assignments.get(stage)
    if assignment is None:
        return None, None, None
    return (
        assignment.get("model_label"),
        assignment.get("reasoning_effort"),
        assignment.get("execution_mode"),
    )


def valid_logical_date(value: str) -> bool:
    if not LOGICAL_DATE_RE.fullmatch(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def artifact_path(root: Path, stage: str, logical_date: str, run_slot: str) -> Path:
    return root / STAGE_DIRS[stage] / f"{logical_date}_{run_slot}.md"


def stage_from_path(path: Path) -> str | None:
    directory = path.parent.name
    for stage, stage_dir in STAGE_DIRS.items():
        if directory == stage_dir:
            return stage
    return None


def artifact_snapshot(
    path: Path,
) -> tuple[bytes | None, dict[str, str], list[str]]:
    try:
        artifact_bytes = source_chain_artifact_lint.read_artifact_bytes(
            path,
            description="source-chain preflight artifact",
        )
    except (OSError, UnicodeError, ValueError) as exc:
        return None, {}, [f"cannot read artifact: {exc}"]
    try:
        text = artifact_bytes.decode("utf-8")
    except UnicodeError as exc:
        return artifact_bytes, {}, [f"cannot decode artifact: {exc}"]
    header, _header_end, errors = source_chain_artifact_lint.read_header(text)
    return artifact_bytes, header, errors


def current_slot_decision(
    path: Path,
    stage: str,
    expected_scope_sha256: str | None = None,
    expected_model_route: str | None = None,
    expected_timezone: str | None = None,
    expected_model_label: str | None = None,
    expected_reasoning_effort: str | None = None,
    expected_execution_mode: str | None = None,
    *,
    project_root: Path,
    auto_apply_path_prefixes: tuple[str, ...] = (),
) -> dict[str, object] | None:
    path_errors = source_chain_artifact_lint.selected_project_root_errors(project_root)
    if not path_errors:
        path_errors = source_chain_artifact_lint.artifact_path_scope_errors(
            path,
            project_root,
        )
    if path_errors:
        return {
            "action": "stop_invalid_current_slot_artifact",
            "artifact": str(path),
            "errors": path_errors,
        }
    path = source_chain_artifact_lint.project_artifact_path(path, project_root)
    if not path.exists():
        if path.is_symlink():
            return {
                "action": "stop_invalid_current_slot_artifact",
                "artifact": str(path),
                "errors": ["current slot artifact is a broken or unsafe symlink"],
            }
        return None
    artifact_bytes, header, snapshot_errors = artifact_snapshot(path)
    if artifact_bytes is None or snapshot_errors:
        return {
            "action": "stop_invalid_current_slot_artifact",
            "artifact": str(path),
            "errors": snapshot_errors,
        }
    report = source_chain_artifact_lint.validate_artifact(
        path,
        stage,
        project_root=project_root,
        artifact_bytes=artifact_bytes,
        verify_current_input_hashes=False,
        verify_decision_hashes=stage == "review",
        expected_model_route=expected_model_route,
        expected_model_label=expected_model_label,
        expected_reasoning_effort=expected_reasoning_effort,
        expected_execution_mode=expected_execution_mode,
        expected_timezone=expected_timezone,
        auto_apply_path_prefixes=auto_apply_path_prefixes,
    )
    errors = report.get("errors", [])
    if errors:
        return {
            "action": "stop_invalid_current_slot_artifact",
            "artifact": str(path),
            "errors": errors,
        }
    recorded_scope_sha256 = header.get("monitor_scope_sha256", "")
    if (
        expected_scope_sha256 is not None
        and recorded_scope_sha256 != expected_scope_sha256
    ):
        return {
            "action": "stop_scope_slot_collision",
            "artifact": str(path),
            "reason": "this logical date and run slot already belongs to a different monitor scope",
            "existing_monitor_scope_sha256": recorded_scope_sha256,
            "requested_monitor_scope_sha256": expected_scope_sha256,
        }
    status = header.get("status", "")
    if status in TERMINAL_STATUSES[stage]:
        return {
            "action": "skip_current_slot_complete",
            "artifact": str(path),
            "status": status,
            "artifact_sha256": hashlib.sha256(artifact_bytes).hexdigest(),
            "chain_id": header.get("chain_id", ""),
            "stage_run_id": header.get("stage_run_id", ""),
            "attempt_id": header.get("attempt_id", ""),
        }
    return {
        "action": "stop_non_terminal_current_slot_artifact",
        "artifact": str(path),
        "status": status or "missing",
    }


def classify_timed_stage(
    root: Path,
    stage: str,
    logical_date: str,
    run_slot: str,
    monitor_scope_sha256: str,
    model_route: str,
    expected_timezone: str | None = None,
    expected_model_label: str | None = None,
    expected_reasoning_effort: str | None = None,
    expected_execution_mode: str | None = None,
    *,
    project_root: Path,
    auto_apply_path_prefixes: tuple[str, ...] = (),
) -> tuple[dict[str, object] | None, dict[str, object] | None]:
    """Return the first invalid and first complete same-scope candidate.

    Every candidate is captured and validated once. An invalid candidate retains
    priority over a complete candidate, matching the preflight stop policy.
    """

    first_complete: dict[str, object] | None = None
    for path in sorted((root / STAGE_DIRS[stage]).glob(f"{logical_date}_*.md")):
        if path.name == f"{logical_date}_{run_slot}.md":
            continue
        path_stage = stage_from_path(path)
        if path_stage != stage:
            continue
        path_errors = source_chain_artifact_lint.artifact_path_scope_errors(
            path,
            project_root,
        )
        if path_errors:
            return (
                {
                    "stage": stage,
                    "artifact": str(path),
                    "status": "invalid",
                    "run_slot": "unknown",
                    "monitor_scope": "unknown",
                    "monitor_scope_sha256": "unknown",
                    "errors": path_errors,
                },
                first_complete,
            )
        path = source_chain_artifact_lint.project_artifact_path(path, project_root)
        artifact_bytes, header, header_errors = artifact_snapshot(path)
        recorded_scope_sha256 = header.get("monitor_scope_sha256", "")
        if (
            not header_errors
            and source_chain_artifact_lint.SHA256_RE.fullmatch(recorded_scope_sha256)
            and recorded_scope_sha256 != monitor_scope_sha256
        ):
            continue
        if artifact_bytes is None:
            return (
                {
                    "stage": stage,
                    "artifact": str(path),
                    "status": "invalid",
                    "run_slot": "unknown",
                    "monitor_scope": "unknown",
                    "monitor_scope_sha256": "unknown",
                    "errors": header_errors,
                },
                first_complete,
            )
        report = source_chain_artifact_lint.validate_artifact(
            path,
            stage,
            project_root=project_root,
            artifact_bytes=artifact_bytes,
            verify_current_input_hashes=False,
            verify_decision_hashes=stage == "review",
            expected_model_route=model_route,
            expected_model_label=expected_model_label,
            expected_reasoning_effort=expected_reasoning_effort,
            expected_execution_mode=expected_execution_mode,
            expected_timezone=expected_timezone,
            auto_apply_path_prefixes=auto_apply_path_prefixes,
        )
        raw_errors = report.get("errors", [])
        errors = [*header_errors]
        errors.extend(
            str(error)
            for error in (raw_errors if isinstance(raw_errors, list) else [raw_errors])
        )
        if errors:
            return (
                {
                    "stage": stage,
                    "artifact": str(path),
                    "status": header.get("status", "invalid"),
                    "run_slot": header.get("run_slot", "unknown"),
                    "monitor_scope": header.get("monitor_scope", "unknown"),
                    "monitor_scope_sha256": recorded_scope_sha256 or "unknown",
                    "errors": errors,
                },
                first_complete,
            )
        if (
            first_complete is None
            and recorded_scope_sha256 == monitor_scope_sha256
            and header.get("status") in TERMINAL_STATUSES[stage]
        ):
            first_complete = {
                "stage": stage,
                "artifact": str(path),
                "status": header.get("status", ""),
                "artifact_schema_version": header.get("artifact_schema_version", ""),
                "chain_id": header.get("chain_id", ""),
                "stage_run_id": header.get("stage_run_id", ""),
                "run_slot": header.get("run_slot", ""),
                "monitor_scope": header.get("monitor_scope", ""),
                "monitor_scope_sha256": recorded_scope_sha256,
            }
    return None, first_complete


def later_or_equal_stages(stage: str) -> tuple[str, ...]:
    index = STAGE_ORDER.index(stage)
    return STAGE_ORDER[index:]


def preflight(
    stage: str,
    logical_date: str,
    run_slot: str,
    monitor_scope: str,
    model_route: str,
    artifacts_root: Path,
    expected_timezone: str | None = None,
    expected_stage_assignments: Mapping[str, Mapping[str, str]] | None = None,
    *,
    project_root: Path,
    repair_current_slot: bool = False,
    auto_apply_path_prefixes: tuple[str, ...] = (),
) -> dict[str, object]:
    project_root = source_chain_artifact_lint.artifact_snapshot_key(project_root)
    root_errors = source_chain_artifact_lint.selected_project_root_errors(project_root)
    if root_errors:
        return {
            "action": "stop_unsafe_output_path",
            "artifact": str(artifacts_root),
            "errors": root_errors,
        }
    artifacts_root = source_chain_artifact_lint.project_artifact_path(
        artifacts_root,
        project_root,
    )
    canonical_scope = source_chain_artifact_lint.normalize_monitor_scope(monitor_scope)
    if not source_chain_artifact_lint.MONITOR_SCOPE_RE.fullmatch(canonical_scope):
        raise ValueError("monitor_scope must normalize to a lowercase scope id")
    if not source_chain_artifact_lint.MODEL_ROUTE_RE.fullmatch(model_route):
        raise ValueError("model_route must be a valid lowercase route id")
    scope_hash = source_chain_artifact_lint.monitor_scope_sha256(canonical_scope)
    current_path = artifact_path(artifacts_root, stage, logical_date, run_slot)
    output_errors = safe_paths.output_path_errors(
        current_path,
        artifacts_root,
        "source-chain artifacts root",
    )
    if output_errors:
        return {
            "action": "stop_unsafe_output_path",
            "artifact": str(current_path),
            "errors": output_errors,
        }
    current_model_label, current_reasoning_effort, current_execution_mode = (
        expected_stage_settings(expected_stage_assignments, stage)
    )
    current = current_slot_decision(
        current_path,
        stage,
        scope_hash,
        model_route,
        expected_timezone,
        current_model_label,
        current_reasoning_effort,
        current_execution_mode,
        project_root=project_root,
        auto_apply_path_prefixes=auto_apply_path_prefixes,
    )
    repair_candidate: dict[str, object] | None = None
    if repair_current_slot:
        if current is None:
            return {
                "action": "stop_repair_current_slot_missing",
                "artifact": str(current_path),
                "reason": "explicit repair requires an existing terminal artifact in the requested stage, logical date, and run slot",
            }
        if current.get("action") != "skip_current_slot_complete":
            return current
        repair_candidate = current
        stage_index = STAGE_ORDER.index(stage)
        for successor_stage in STAGE_ORDER[stage_index + 1 :]:
            successor_path = artifact_path(
                artifacts_root,
                successor_stage,
                logical_date,
                run_slot,
            )
            successor_model_label, successor_reasoning_effort, successor_execution_mode = (
                expected_stage_settings(expected_stage_assignments, successor_stage)
            )
            successor = current_slot_decision(
                successor_path,
                successor_stage,
                scope_hash,
                model_route,
                expected_timezone,
                successor_model_label,
                successor_reasoning_effort,
                successor_execution_mode,
                project_root=project_root,
                auto_apply_path_prefixes=auto_apply_path_prefixes,
            )
            if successor is not None:
                return {
                    "action": "stop_repair_current_slot_successor_exists",
                    "artifact": str(current_path),
                    "reason": (
                        "explicit repair cannot replace an artifact while a "
                        "same-slot successor exists; preserve the bound chain "
                        "or obtain separate authority to supersede it"
                    ),
                    "successor_stage": successor_stage,
                    "existing": successor,
                }
    elif current is not None:
        return current
    for predecessor_stage in EARLIER_STAGES[stage]:
        predecessor_model_label, predecessor_reasoning_effort, predecessor_execution_mode = (
            expected_stage_settings(expected_stage_assignments, predecessor_stage)
        )
        invalid_predecessor, complete_predecessor = classify_timed_stage(
            artifacts_root,
            predecessor_stage,
            logical_date,
            run_slot,
            scope_hash,
            model_route,
            expected_timezone,
            predecessor_model_label,
            predecessor_reasoning_effort,
            predecessor_execution_mode,
            project_root=project_root,
            auto_apply_path_prefixes=auto_apply_path_prefixes,
        )
        if invalid_predecessor is not None:
            return {
                "action": "stop_invalid_predecessor_slot",
                "reason": "an invalid predecessor artifact for this scope exists in another run slot",
                "existing": invalid_predecessor,
            }
        if complete_predecessor is not None:
            return {
                "action": "stop_predecessor_slot_mismatch",
                "reason": "reuse the predecessor's run slot for every stage in this chain",
                "existing": complete_predecessor,
            }
    for candidate_stage in reversed(later_or_equal_stages(stage)):
        candidate_model_label, candidate_reasoning_effort, candidate_execution_mode = (
            expected_stage_settings(expected_stage_assignments, candidate_stage)
        )
        invalid, complete = classify_timed_stage(
            artifacts_root,
            candidate_stage,
            logical_date,
            run_slot,
            scope_hash,
            model_route,
            expected_timezone,
            candidate_model_label,
            candidate_reasoning_effort,
            candidate_execution_mode,
            project_root=project_root,
            auto_apply_path_prefixes=auto_apply_path_prefixes,
        )
        if invalid is not None:
            return {
                "action": "stop_invalid_same_scope_artifact",
                "reason": "invalid current-schema timed artifact exists for this monitor scope on the logical date in another run slot, or its scope identity is unreadable",
                "existing": invalid,
            }
        if complete is not None:
            return {
                "action": "skip_scope_already_processed",
                "reason": "terminal timed artifact exists for this monitor scope and logical date in another run slot",
                "existing": complete,
            }
    result: dict[str, object] = {
        "action": (
            "repair_current_slot_authorized"
            if repair_candidate is not None
            else "run_current_slot"
        ),
        "artifact": str(artifact_path(artifacts_root, stage, logical_date, run_slot)),
        "chain_id": f"source-{logical_date}-{run_slot}",
        "monitor_scope": canonical_scope,
        "monitor_scope_sha256": scope_hash,
        "model_route": model_route,
        "timezone": expected_timezone or "not_bound",
    }
    if repair_candidate is not None:
        result.update(
            {
                "existing_status": repair_candidate["status"],
                "repair_preimage_sha256": repair_candidate["artifact_sha256"],
                "repair_preimage_stage_run_id": repair_candidate["stage_run_id"],
                "repair_preimage_attempt_id": repair_candidate["attempt_id"],
                "repair_authorized": True,
                "repair_required": True,
                "worker_action": "compare_and_replace_the_bound_current_slot_preimage",
                "preflight_mutation": "none",
            }
        )
    if expected_stage_assignments is not None:
        result["model_label"] = current_model_label or "not_bound"
        result["reasoning_effort"] = current_reasoning_effort or "not_bound"
        result["execution_mode"] = current_execution_mode or "not_bound"
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Preflight a source-chain automation stage.",
        allow_abbrev=False,
    )
    parser.add_argument(
        "--stage",
        choices=STAGE_ORDER,
        required=True,
        help="Source-chain stage to preflight.",
    )
    parser.add_argument(
        "--logical-date",
        required=True,
        help="Artifact logical date in YYYY-MM-DD form.",
    )
    parser.add_argument(
        "--run-slot",
        required=True,
        help="Scheduled artifact slot in 24-hour HHMM form.",
    )
    parser.add_argument(
        "--monitor-scope",
        required=True,
        help="Canonical monitor scope bound to the artifact chain.",
    )
    parser.add_argument(
        "--expected-model-route",
        required=True,
        help="Lowercase model-route id required by the owning trigger authority.",
    )
    parser.add_argument(
        "--expected-timezone",
        required=True,
        help="Normalized IANA timezone required on the artifact chain.",
    )
    parser.add_argument(
        "--artifacts-root",
        type=Path,
        default=Path("review_artifacts"),
        help="Source-chain artifacts directory (default: review_artifacts).",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        required=True,
        help="Project root used to resolve and bind current source inputs.",
    )
    parser.add_argument(
        "--repair-current-slot",
        action="store_true",
        help=(
            "Authorize replacement of an existing valid terminal artifact in "
            "this exact stage and slot after all normal gates pass."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not valid_logical_date(args.logical_date):
        raise SystemExit("--logical-date must be YYYY-MM-DD")
    if not RUN_SLOT_RE.match(args.run_slot):
        raise SystemExit("--run-slot must be HHMM in 24-hour time")
    canonical_scope = source_chain_artifact_lint.normalize_monitor_scope(args.monitor_scope)
    if not canonical_scope:
        raise SystemExit("--monitor-scope must be non-empty")
    if not source_chain_artifact_lint.MONITOR_SCOPE_RE.fullmatch(canonical_scope):
        raise SystemExit("--monitor-scope must normalize to a lowercase scope id")
    if len(canonical_scope.encode("utf-8")) > source_chain_artifact_lint.MONITOR_SCOPE_MAX_BYTES:
        raise SystemExit(
            f"--monitor-scope must be at most {source_chain_artifact_lint.MONITOR_SCOPE_MAX_BYTES} UTF-8 bytes"
        )
    model_route = args.expected_model_route
    if not source_chain_artifact_lint.MODEL_ROUTE_RE.fullmatch(model_route):
        raise SystemExit("--expected-model-route must be a valid lowercase route id")
    timezone_errors: list[str] = []
    source_chain_artifact_lint.parse_artifact_timezone(
        {"timezone": args.expected_timezone},
        timezone_errors,
    )
    if timezone_errors:
        raise SystemExit("--expected-timezone must be a normalized IANA timezone name")
    print(
        json.dumps(
            preflight(
                args.stage,
                args.logical_date,
                args.run_slot,
                canonical_scope,
                model_route,
                args.artifacts_root,
                args.expected_timezone,
                project_root=args.project_root,
                repair_current_slot=args.repair_current_slot,
            ),
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
