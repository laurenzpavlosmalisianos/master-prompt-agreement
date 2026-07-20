#!/usr/bin/env python3

from __future__ import annotations

import argparse
from collections.abc import Mapping
import hashlib
import json
from pathlib import Path
import sys
from typing import cast

import source_chain_artifact_lint
import source_chain_preflight


STAGES = source_chain_preflight.STAGE_ORDER
TERMINAL_STATUSES = source_chain_preflight.TERMINAL_STATUSES


def artifact_summary(
    artifacts_root: Path,
    stage: str,
    logical_date: str,
    run_slot: str,
    expected_scope_sha256: str,
    expected_model_route: str,
    expected_timezone: str | None = None,
    expected_model_label: str | None = None,
    expected_reasoning_effort: str | None = None,
    expected_execution_mode: str | None = None,
    *,
    project_root: Path,
    auto_apply_path_prefixes: tuple[str, ...] = (),
) -> dict[str, object]:
    path = source_chain_preflight.artifact_path(artifacts_root, stage, logical_date, run_slot)
    selected_path = path
    path = source_chain_artifact_lint.project_artifact_path(path, project_root)
    summary: dict[str, object] = {
        "stage": stage,
        "artifact": str(path),
        "exists": False,
        "lint_status": "missing",
        "terminal": False,
        "successful": False,
        "status": "missing",
        "attempt_id": "none",
        "sha256": "none",
        "errors": [],
    }
    path_errors = source_chain_artifact_lint.selected_project_root_errors(project_root)
    if not path_errors:
        path_errors = source_chain_artifact_lint.artifact_path_scope_errors(
            selected_path,
            project_root,
        )
    if path_errors:
        if any("must not use symlink aliases" in error for error in path_errors):
            summary["exists"] = True
        summary["lint_status"] = "fail"
        summary["status"] = "invalid"
        summary["errors"] = path_errors
        return summary
    try:
        path.lstat()
    except FileNotFoundError:
        return summary
    except OSError as exc:
        summary["lint_status"] = "fail"
        summary["status"] = "invalid"
        summary["errors"] = [f"cannot inspect artifact entry safely: {exc}"]
        return summary
    summary["exists"] = True

    try:
        artifact_bytes = source_chain_artifact_lint.read_artifact_bytes(
            path,
            description="source-chain status artifact",
        )
    except (OSError, ValueError) as exc:
        summary["lint_status"] = "fail"
        summary["status"] = "invalid"
        summary["errors"] = [f"cannot read artifact safely: {exc}"]
        return summary

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
    raw_errors = report.get("errors", [])
    errors = [str(error) for error in raw_errors] if isinstance(raw_errors, list) else [str(raw_errors)]
    summary["errors"] = errors
    if errors:
        summary["lint_status"] = "fail"
        summary["status"] = "invalid"
        return summary
    summary["sha256"] = hashlib.sha256(artifact_bytes).hexdigest()

    try:
        text = artifact_bytes.decode("utf-8")
    except UnicodeError as exc:
        summary["lint_status"] = "fail"
        summary["status"] = "invalid"
        summary["errors"] = [f"cannot decode artifact safely: {exc}"]
        return summary
    header, _header_end, header_errors = source_chain_artifact_lint.read_header(text)
    if header_errors:
        summary["lint_status"] = "fail"
        summary["status"] = "invalid"
        summary["errors"] = header_errors
        return summary

    status = header.get("status", "")
    if header.get("monitor_scope_sha256") != expected_scope_sha256:
        summary["lint_status"] = "fail"
        summary["status"] = "scope_mismatch"
        summary["errors"] = ["monitor_scope_sha256 does not match the requested scope"]
        return summary
    summary["lint_status"] = "pass"
    summary["status"] = status or "missing"
    summary["attempt_id"] = header.get("attempt_id", "none")
    summary["model_label"] = header.get("model_label", "missing")
    summary["reasoning_effort"] = header.get("reasoning_effort", "missing")
    summary["execution_mode"] = header.get("execution_mode", "missing")
    summary["terminal"] = status in TERMINAL_STATUSES[stage]
    if stage == "monitor":
        summary["source_status"] = header.get("source_status", "missing")
        summary["workspace_status"] = header.get("workspace_status", "missing")
    if stage in {"monitor", "review", "assurance"}:
        summary["unresolved_inaccessible_source_count"] = header.get(
            "unresolved_inaccessible_source_count",
            "missing",
        )
    if stage == "review":
        summary["accepted_findings"] = header.get("accepted_findings", "missing")
        summary["manual_findings"] = header.get("manual_findings", "missing")
        summary["rejected_findings"] = header.get("rejected_findings", "missing")
    if stage == "apply":
        summary["commit"] = header.get("commit", "missing")
        summary["input_review_state"] = header.get("input_review_state", "missing")
    if stage == "assurance":
        summary["latest_commit"] = header.get("latest_commit", "missing")
        summary["unresolved_findings"] = header.get("unresolved_findings", "missing")
    successful_statuses = {
        "monitor": {"pass", "no-findings"},
        "review": {"pass", "no-findings"},
        "apply": {"pass", "no-op"},
        "assurance": {"pass"},
    }
    summary["successful"] = status in successful_statuses[stage]
    if stage == "monitor":
        summary["successful"] = bool(summary["successful"]) and header.get(
            "source_status"
        ) in {"pass", "no-findings"}
    return summary


def chain_status(
    logical_date: str,
    run_slot: str,
    monitor_scope: str,
    model_route: str,
    artifacts_root: Path,
    expected_timezone: str | None = None,
    expected_stage_assignments: Mapping[str, Mapping[str, str]] | None = None,
    *,
    project_root: Path,
    auto_apply_path_prefixes: tuple[str, ...] = (),
) -> dict[str, object]:
    artifacts_root = source_chain_artifact_lint.project_artifact_path(
        artifacts_root,
        project_root,
    )
    canonical_scope = source_chain_artifact_lint.normalize_monitor_scope(monitor_scope)
    scope_hash = source_chain_artifact_lint.monitor_scope_sha256(canonical_scope)
    stages: list[dict[str, object]] = []
    for stage in STAGES:
        expected_model_label, expected_reasoning_effort, expected_execution_mode = (
            source_chain_preflight.expected_stage_settings(
                expected_stage_assignments,
                stage,
            )
        )
        stages.append(
            artifact_summary(
                artifacts_root,
                stage,
                logical_date,
                run_slot,
                scope_hash,
                model_route,
                expected_timezone,
                expected_model_label,
                expected_reasoning_effort,
                expected_execution_mode,
                project_root=project_root,
                auto_apply_path_prefixes=auto_apply_path_prefixes,
            )
        )
    return {
        "chain_id": f"source-{logical_date}-{run_slot}",
        "logical_date": logical_date,
        "run_slot": run_slot,
        "monitor_scope": canonical_scope,
        "monitor_scope_sha256": scope_hash,
        "model_route": model_route,
        "timezone": expected_timezone or "not_bound",
        "artifacts_root": str(artifacts_root),
        "all_terminal": all(bool(stage["terminal"]) for stage in stages),
        "successful": all(bool(stage["successful"]) for stage in stages),
        "has_lint_errors": any(stage["lint_status"] == "fail" for stage in stages),
        "missing_stages": [stage["stage"] for stage in stages if not stage["exists"]],
        "stages": stages,
    }


def render_markdown(status: dict[str, object]) -> str:
    lines = [
        f"# Source Chain Status - {status['logical_date']} {status['run_slot']}",
        "",
        f"- Chain: `{status['chain_id']}`",
        f"- Scope: `{status['monitor_scope']}`",
        f"- Scope SHA-256: `{status['monitor_scope_sha256']}`",
        f"- Model route: `{status['model_route']}`",
        f"- Timezone: `{status['timezone']}`",
        f"- All terminal: `{str(status['all_terminal']).lower()}`",
        f"- Successful: `{str(status['successful']).lower()}`",
        f"- Lint errors: `{str(status['has_lint_errors']).lower()}`",
        "",
        "| Stage | Exists | Lint | Status | Terminal | SHA-256 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    stages = cast(list[dict[str, object]], status["stages"])
    for stage in stages:
        sha = str(stage["sha256"])
        lines.append(
            "| {stage} | {exists} | {lint_status} | {status} | {terminal} | {sha} |".format(
                stage=stage["stage"],
                exists=str(stage["exists"]).lower(),
                lint_status=stage["lint_status"],
                status=stage["status"],
                terminal=str(stage["terminal"]).lower(),
                sha=sha[:12] if sha not in {"none", "unavailable"} else sha,
            )
        )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Summarize source-chain artifacts for one logical date and slot.",
        allow_abbrev=False,
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
        help="Lowercase model-route id expected on every stage artifact.",
    )
    parser.add_argument(
        "--expected-timezone",
        required=True,
        help="Normalized IANA timezone expected on every stage artifact.",
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
        help="Project root used to verify current source and policy bindings.",
    )
    parser.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="json",
        help="Status report format (default: json).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not source_chain_preflight.valid_logical_date(args.logical_date):
        raise SystemExit("--logical-date must be YYYY-MM-DD")
    if not source_chain_preflight.RUN_SLOT_RE.match(args.run_slot):
        raise SystemExit("--run-slot must be HHMM in 24-hour time")
    canonical_scope = source_chain_artifact_lint.normalize_monitor_scope(args.monitor_scope)
    if not canonical_scope:
        raise SystemExit("--monitor-scope must be non-empty")
    if not source_chain_artifact_lint.MONITOR_SCOPE_RE.fullmatch(canonical_scope):
        raise SystemExit("--monitor-scope must normalize to a lowercase scope id")
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
    status = chain_status(
        args.logical_date,
        args.run_slot,
        canonical_scope,
        model_route,
        args.artifacts_root,
        args.expected_timezone,
        project_root=args.project_root,
    )
    if args.format == "markdown":
        print(render_markdown(status))
    else:
        print(json.dumps(status, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
