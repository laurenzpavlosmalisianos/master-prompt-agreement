#!/usr/bin/env python3

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
import hashlib
from pathlib import Path
import sys
import time

import safe_paths
import source_chain_artifact_lint


TERMINAL_STATUSES = {
    stage: statuses.copy()
    for stage, statuses in source_chain_artifact_lint.STAGE_STATUSES.items()
}


@dataclass(frozen=True)
class ArtifactObservation:
    ready: bool
    state: str
    fingerprint: tuple[str, int] | None


def valid_logical_date(value: str) -> bool:
    if not source_chain_artifact_lint.LOGICAL_DATE_RE.fullmatch(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def read_header(
    path: Path,
    *,
    artifact_bytes: bytes | None = None,
) -> tuple[dict[str, str], list[str]]:
    raw = (
        safe_paths.read_regular_file_bytes(
            path,
            description="source-chain wait artifact",
            max_bytes=source_chain_artifact_lint.ARTIFACT_MAX_BYTES,
        )
        if artifact_bytes is None
        else artifact_bytes
    )
    text = raw.decode("utf-8")
    header, _header_end, errors = source_chain_artifact_lint.read_header(text)
    return header, errors


def observe_artifact(
    path: Path,
    stage: str,
    *,
    project_root: Path,
    expected_logical_date: str | None = None,
    expected_run_slot: str | None = None,
    expected_monitor_scope_sha256: str | None = None,
    expected_model_route: str | None = None,
    expected_model_label: str | None = None,
    expected_reasoning_effort: str | None = None,
    expected_execution_mode: str | None = None,
    expected_timezone: str | None = None,
    verify_current_input_hashes: bool = False,
    auto_apply_path_prefixes: tuple[str, ...] = (),
) -> ArtifactObservation:
    path_errors = source_chain_artifact_lint.selected_project_root_errors(project_root)
    if not path_errors:
        path_errors = source_chain_artifact_lint.artifact_path_scope_errors(
            path,
            project_root,
        )
    if path_errors:
        return ArtifactObservation(
            False,
            "invalid artifact path: " + "; ".join(path_errors),
            None,
        )
    path = source_chain_artifact_lint.project_artifact_path(path, project_root)
    try:
        raw = safe_paths.read_regular_file_bytes(
            path,
            description="source-chain wait artifact",
            max_bytes=source_chain_artifact_lint.ARTIFACT_MAX_BYTES,
        )
    except FileNotFoundError:
        return ArtifactObservation(False, "missing", None)
    except (OSError, ValueError) as exc:
        return ArtifactObservation(False, f"invalid artifact read: {exc}", None)
    fingerprint = (hashlib.sha256(raw).hexdigest(), len(raw))
    report = source_chain_artifact_lint.validate_artifact(
        path,
        stage,
        project_root=project_root,
        artifact_bytes=raw,
        verify_current_input_hashes=verify_current_input_hashes and stage == "monitor",
        verify_decision_hashes=stage == "review",
        expected_model_route=expected_model_route,
        expected_model_label=expected_model_label,
        expected_reasoning_effort=expected_reasoning_effort,
        expected_execution_mode=expected_execution_mode,
        expected_timezone=expected_timezone,
        auto_apply_path_prefixes=auto_apply_path_prefixes,
    )
    raw_errors = report.get("errors", [])
    errors = raw_errors if isinstance(raw_errors, list) else [raw_errors]
    if errors:
        return ArtifactObservation(
            False,
            "invalid: " + "; ".join(str(error) for error in errors),
            fingerprint,
        )
    try:
        header, header_errors = read_header(path, artifact_bytes=raw)
    except (OSError, UnicodeError) as exc:
        return ArtifactObservation(False, f"invalid header read: {exc}", fingerprint)
    if header_errors:
        return ArtifactObservation(
            False,
            "invalid header: " + "; ".join(header_errors),
            fingerprint,
        )
    logical_date = header.get("logical_date", "")
    run_slot = header.get("run_slot", "")
    if expected_logical_date is not None and logical_date != expected_logical_date:
        return ArtifactObservation(
            False,
            f"wrong logical_date: expected {expected_logical_date}, got {logical_date or 'missing'}",
            fingerprint,
        )
    if expected_run_slot is not None and run_slot != expected_run_slot:
        return ArtifactObservation(
            False,
            f"wrong run_slot: expected {expected_run_slot}, got {run_slot or 'missing'}",
            fingerprint,
        )
    monitor_scope_sha256 = header.get("monitor_scope_sha256", "")
    if (
        expected_monitor_scope_sha256 is not None
        and monitor_scope_sha256 != expected_monitor_scope_sha256
    ):
        return ArtifactObservation(
            False,
            "wrong monitor_scope_sha256: expected "
            f"{expected_monitor_scope_sha256}, got {monitor_scope_sha256 or 'missing'}",
            fingerprint,
        )
    status = header.get("status")
    if status in TERMINAL_STATUSES[stage]:
        return ArtifactObservation(True, f"ready: {status}", fingerprint)
    return ArtifactObservation(
        False,
        f"non-terminal status: {status or 'missing'}",
        fingerprint,
    )


def artifact_ready(
    path: Path,
    stage: str,
    *,
    project_root: Path,
    expected_logical_date: str | None = None,
    expected_run_slot: str | None = None,
    expected_monitor_scope_sha256: str | None = None,
    expected_model_route: str | None = None,
    expected_model_label: str | None = None,
    expected_reasoning_effort: str | None = None,
    expected_execution_mode: str | None = None,
    expected_timezone: str | None = None,
    verify_current_input_hashes: bool = False,
    auto_apply_path_prefixes: tuple[str, ...] = (),
) -> tuple[bool, str]:
    observation = observe_artifact(
        path,
        stage,
        project_root=project_root,
        expected_logical_date=expected_logical_date,
        expected_run_slot=expected_run_slot,
        expected_monitor_scope_sha256=expected_monitor_scope_sha256,
        expected_model_route=expected_model_route,
        expected_model_label=expected_model_label,
        expected_reasoning_effort=expected_reasoning_effort,
        expected_execution_mode=expected_execution_mode,
        expected_timezone=expected_timezone,
        verify_current_input_hashes=verify_current_input_hashes,
        auto_apply_path_prefixes=auto_apply_path_prefixes,
    )
    return observation.ready, observation.state


def wait_for_artifact(
    path: Path,
    stage: str,
    timeout_seconds: int,
    poll_seconds: int,
    *,
    project_root: Path,
    expected_logical_date: str | None = None,
    expected_run_slot: str | None = None,
    expected_monitor_scope_sha256: str | None = None,
    expected_model_route: str | None = None,
    expected_model_label: str | None = None,
    expected_reasoning_effort: str | None = None,
    expected_execution_mode: str | None = None,
    expected_timezone: str | None = None,
    verify_current_input_hashes: bool = False,
    auto_apply_path_prefixes: tuple[str, ...] = (),
) -> tuple[bool, str]:
    deadline = time.monotonic() + timeout_seconds
    last_state = "not checked"
    while True:
        observation = observe_artifact(
            path,
            stage,
            project_root=project_root,
            expected_logical_date=expected_logical_date,
            expected_run_slot=expected_run_slot,
            expected_monitor_scope_sha256=expected_monitor_scope_sha256,
            expected_model_route=expected_model_route,
            expected_model_label=expected_model_label,
            expected_reasoning_effort=expected_reasoning_effort,
            expected_execution_mode=expected_execution_mode,
            expected_timezone=expected_timezone,
            verify_current_input_hashes=verify_current_input_hashes,
            auto_apply_path_prefixes=auto_apply_path_prefixes,
        )
        if observation.ready:
            state = observation.state
            if timeout_seconds <= 0:
                return True, state
            first_fingerprint = observation.fingerprint
            if first_fingerprint is None:
                last_state = "unstable artifact could not be fingerprinted"
                if time.monotonic() >= deadline:
                    return False, last_state
                time.sleep(min(poll_seconds, max(0.0, deadline - time.monotonic())))
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False, f"ready but not stable before timeout: {state}"
            time.sleep(min(poll_seconds, remaining))
            stable_observation = observe_artifact(
                path,
                stage,
                project_root=project_root,
                expected_logical_date=expected_logical_date,
                expected_run_slot=expected_run_slot,
                expected_monitor_scope_sha256=expected_monitor_scope_sha256,
                expected_model_route=expected_model_route,
                expected_model_label=expected_model_label,
                expected_reasoning_effort=expected_reasoning_effort,
                expected_execution_mode=expected_execution_mode,
                expected_timezone=expected_timezone,
                verify_current_input_hashes=verify_current_input_hashes,
                auto_apply_path_prefixes=auto_apply_path_prefixes,
            )
            if stable_observation.ready:
                if stable_observation.fingerprint == first_fingerprint:
                    return True, f"{stable_observation.state}; stable"
                last_state = "unstable artifact changed while waiting for stable digest"
            else:
                last_state = stable_observation.state
            if time.monotonic() >= deadline:
                return False, last_state
            continue
        last_state = observation.state
        if timeout_seconds <= 0 or time.monotonic() >= deadline:
            return False, last_state
        time.sleep(min(poll_seconds, max(0.0, deadline - time.monotonic())))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Wait for a source-chain artifact to exist, lint, and reach terminal status.",
        allow_abbrev=False,
    )
    parser.add_argument(
        "--stage",
        choices=sorted(TERMINAL_STATUSES),
        required=True,
        help="Expected artifact stage whose terminal status is awaited.",
    )
    parser.add_argument(
        "--artifact",
        type=Path,
        required=True,
        help="Exact source-chain artifact path to observe and validate.",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        required=True,
        help="Project root used to resolve and verify bounded artifact inputs.",
    )
    parser.add_argument("--logical-date", help="Expected artifact logical_date.")
    parser.add_argument("--run-slot", help="Expected artifact run_slot.")
    parser.add_argument("--monitor-scope", required=True, help="Expected canonical monitor scope.")
    parser.add_argument(
        "--expected-model-route",
        required=True,
        help="Lowercase model-route id required on the artifact.",
    )
    parser.add_argument(
        "--expected-model-label",
        help="Optional exact runtime model label required on the artifact.",
    )
    parser.add_argument(
        "--expected-reasoning-effort",
        help="Optional exact reasoning-effort value required on the artifact.",
    )
    parser.add_argument(
        "--expected-execution-mode",
        help="Optional exact execution-mode value required on the artifact.",
    )
    parser.add_argument(
        "--expected-timezone",
        required=True,
        help="Normalized IANA timezone required on the artifact.",
    )
    parser.add_argument(
        "--verify-current-input-hashes",
        action="store_true",
        help=(
            "For a monitor-to-review handoff, compare the monitor's recorded "
            "source and policy hashes with the current files."
        ),
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=0,
        help="Maximum wait in seconds; zero performs one observation (default: 0).",
    )
    parser.add_argument(
        "--poll-seconds",
        type=int,
        default=300,
        help="Positive interval between observations in seconds (default: 300).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.timeout_seconds < 0:
        raise SystemExit("--timeout-seconds must be non-negative")
    if args.poll_seconds <= 0:
        raise SystemExit("--poll-seconds must be positive")
    if args.verify_current_input_hashes and args.stage != "monitor":
        raise SystemExit("--verify-current-input-hashes is valid only for stage monitor")
    if args.logical_date and not valid_logical_date(args.logical_date):
        raise SystemExit("--logical-date must be YYYY-MM-DD")
    if args.run_slot and not source_chain_artifact_lint.RUN_SLOT_RE.match(args.run_slot):
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
    ready, state = wait_for_artifact(
        args.artifact,
        args.stage,
        args.timeout_seconds,
        args.poll_seconds,
        project_root=args.project_root,
        expected_logical_date=args.logical_date,
        expected_run_slot=args.run_slot,
        expected_monitor_scope_sha256=source_chain_artifact_lint.monitor_scope_sha256(
            canonical_scope
        ),
        expected_model_route=model_route,
        expected_model_label=args.expected_model_label,
        expected_reasoning_effort=args.expected_reasoning_effort,
        expected_execution_mode=args.expected_execution_mode,
        expected_timezone=args.expected_timezone,
        verify_current_input_hashes=args.verify_current_input_hashes,
    )
    print(state)
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
