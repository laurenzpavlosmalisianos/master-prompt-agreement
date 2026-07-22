"""Shared constants and fixture builders for validation test domains."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import py_compile
import shutil
import subprocess
import sys
from typing import Any, Sequence, cast


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
TEST_FRAMEWORK_RUNNER = "uv run python -E -S -B"
DEFERRED_VALUE_CLASSIFICATION_CASES = (
    ("TBD", True),
    (" tBd after inspection ", True),
    ("To be confirmed", True),
    ("To be confirmed by the owner", True),
    ("To be confirmed after repository inspection", True),
    ("replace with the approved value", True),
    ("replace-with approved value", True),
    ("none", False),
    ("confirmed by the owner", False),
    ("run the TBD check", False),
    ("replacement value", False),
)
TEST_SUBPROCESS_TIMEOUT_SECONDS = 60.0
TEST_SUBPROCESS_MAX_TIMEOUT_SECONDS = 300.0
TEST_SUBPROCESS_MAX_OUTPUT_BYTES = 4 * 1024 * 1024
TEST_SUBPROCESS_MAX_OUTPUT_LIMIT_BYTES = 16 * 1024 * 1024
TEST_SUBPROCESS_TERMINATION_GRACE_SECONDS = 0.25
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import bounded_subprocess  # noqa: E402
import review_packet_contract  # noqa: E402


def dict_items(value: object) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], value)


def string_items(value: object) -> list[str]:
    return cast(list[str], value)


class TestSubprocessOutputLimit(RuntimeError):
    """Raised when a test child exceeds the shared aggregate output bound."""


TestSubprocessCleanupError = bounded_subprocess.BoundedSubprocessCleanupError


def compile_adjacent_bytecode(
    source: Path,
    *,
    unchecked_hash: bool = False,
) -> Path:
    """Compile a fixture beside its source, independent of ambient cache policy."""

    if not source.is_absolute() or source.suffix != ".py" or not source.is_file():
        raise ValueError("bytecode fixture source must be an absolute regular .py file")
    cache_tag = sys.implementation.cache_tag
    if not cache_tag or any(character in cache_tag for character in "/\\"):
        raise RuntimeError("bytecode fixture requires a safe interpreter cache tag")
    cache = source.parent / "__pycache__" / f"{source.stem}.{cache_tag}.pyc"
    mode = (
        py_compile.PycInvalidationMode.UNCHECKED_HASH
        if unchecked_hash
        else py_compile.PycInvalidationMode.TIMESTAMP
    )
    compiled = py_compile.compile(
        str(source),
        cfile=str(cache),
        doraise=True,
        invalidation_mode=mode,
    )
    if compiled != str(cache) or not cache.is_file():
        raise RuntimeError("bytecode fixture compilation produced an unexpected output")
    return cache


def run_bounded(
    args: Sequence[str],
    *,
    cwd: Path,
    check: bool = False,
    capture_output: bool = True,
    text: bool = True,
    timeout_seconds: float = TEST_SUBPROCESS_TIMEOUT_SECONDS,
    max_output_bytes: int = TEST_SUBPROCESS_MAX_OUTPUT_BYTES,
) -> subprocess.CompletedProcess[str]:
    """Run one test child through the shared bounded subprocess primitive."""

    if capture_output is not True or text is not True:
        raise ValueError("bounded test subprocesses require captured text output")
    result = bounded_subprocess.run_bounded_process(
        args,
        cwd=cwd,
        timeout_seconds=timeout_seconds,
        max_output_bytes=max_output_bytes,
        maximum_timeout_seconds=TEST_SUBPROCESS_MAX_TIMEOUT_SECONDS,
        maximum_output_bytes=TEST_SUBPROCESS_MAX_OUTPUT_LIMIT_BYTES,
        termination_grace_seconds=TEST_SUBPROCESS_TERMINATION_GRACE_SECONDS,
    )
    command = list(result.args)
    stdout_text = result.stdout.decode("utf-8", errors="replace")
    stderr_text = result.stderr.decode("utf-8", errors="replace")
    if result.timed_out:
        raise subprocess.TimeoutExpired(
            command,
            timeout_seconds,
            output=stdout_text,
            stderr=stderr_text,
        )
    if result.output_exceeded:
        raise TestSubprocessOutputLimit(
            f"test subprocess output exceeded {max_output_bytes} bytes: {command!r}"
        )
    completed = subprocess.CompletedProcess(
        command,
        result.returncode,
        stdout_text,
        stderr_text,
    )
    if check and completed.returncode != 0:
        raise subprocess.CalledProcessError(
            completed.returncode,
            command,
            output=completed.stdout,
            stderr=completed.stderr,
        )
    return completed


def valid_automation_job() -> dict[str, object]:
    return {
        "approval_mode": "standing_order",
        "authority": {
            "allowed_actions": ["generate_report"],
            "basis": "standing_project_grant",
            "effect_class": "observe",
            "failure_action": "record_and_continue",
            "resource_refs": ["project"],
            "source_ref": "automation_orders_grant",
            "validity": {
                "expires_on": None,
                "mode": "until_revoked",
                "revocation_events": [
                    "repeated_failure",
                    "schedule_disabled",
                    "user_revocation",
                ],
            },
            "verification": {
                "evidence_refs": ["weekly_report_validation"],
                "kind": "deterministic",
                "on_failure": "block",
            },
        },
        "autonomy_level": "observe",
        "command": "printf 'weekly report fixture'",
        "concurrency": "forbid",
        "cwd": ".",
        "enabled": True,
        "execution_sources": [],
        "failure_policy": "log",
        "id": "weekly_report",
        "idempotency": {"key": "weekly_report", "mode": "replace"},
        "instruction_sources": [
            {"path": "task_orders/automation.md", "root": "framework"},
            {
                "path": "practice_guides/scheduled_automation.md",
                "root": "framework",
            },
        ],
        "scheduler_artifacts": {
            "root": ".automation",
            "log_file": "logs/weekly_report.log",
            "lock_file": "locks/weekly_report.lock",
            "max_log_bytes": 1024 * 1024,
            "retention": {
                "days": None,
                "manual_owner": "project_operator",
                "manual_trigger": (
                    "when the scheduler log lacks capacity for another complete run record"
                ),
                "mode": "manual_archive_or_truncate",
            },
            "redaction": {"mode": "retain_verbatim"},
        },
        "objective": "Generate the weekly report",
        "outputs": ["review_" + "artifacts/weekly_report.md"],
        "schedule": "0 9 * * 1",
        "scheduler_context_mode": "fresh_run",
        "state_policy": {
            "checkpoint": "none",
            "persistence": "none",
            "reference": None,
            "resume": "restart",
        },
        "standard_of_care": "careful",
        "timeout_minutes": 30,
        "timezone": "Europe/Paris",
        "workload_class": "general",
        "write_scope": "artifacts",
    }


def write_valid_review_packet_bundle(
    bundle_dir: Path,
    *,
    scope: str,
    approval_source: str,
    redaction: str,
    retain_ephemeral_item: bool = False,
) -> tuple[Path, str]:
    """Write one closed synthetic packet bundle with bound receipts and evidence."""

    bundle_dir.mkdir(parents=True)
    item_path = bundle_dir / "packet" / "context.md"
    item_path.parent.mkdir()
    item_bytes = b"# Bounded source-review context\n"
    item_path.write_bytes(item_bytes)
    evidence_dir = bundle_dir / "evidence"
    evidence_dir.mkdir()
    output_path = evidence_dir / "review-output.json"
    output_bytes = b'{"findings":[]}\n'
    output_path.write_bytes(output_bytes)
    verification_path = evidence_dir / "verification.json"
    verification_bytes = b'{"classified":true}\n'
    verification_path.write_bytes(verification_bytes)
    output_sha = hashlib.sha256(output_bytes).hexdigest()
    verification_sha = hashlib.sha256(verification_bytes).hexdigest()
    data: dict[str, Any] = {
        "$schema": "runtime/review_packet.schema.json",
        "schema_version": 5,
        "review_id": "source-review-fixture",
        "created_at": "2026-06-19T08:00:00Z",
        "lane_id": "project-neutral-external-reviewer",
        "invocation_owner": "user_manual",
        "effect_mode": "observe",
        "purpose": "Review one bounded source-chain finding.",
        "lane_controls": {
            "manifest_kind": "full",
            "independence_group": {
                "resolution": "explicit",
                "value": "fixture-independent-review",
                "basis": "Synthetic external-lane fixture.",
            },
            "fallback_or_abort_rule": {
                "resolution": "explicit",
                "value": "Abort without replacement on invalid output.",
                "basis": "Synthetic external-lane fixture.",
            },
            "auth_session_policy": {
                "resolution": "explicit",
                "value": "No authenticated session; synthetic fixture only.",
                "basis": "Synthetic external-lane fixture.",
            },
            "timeout": {
                "resolution": "explicit",
                "value": "600 seconds",
                "basis": "Synthetic external-lane fixture.",
            },
            "rate_or_cost_cap": {
                "resolution": "explicit",
                "value": "One invocation with zero paid spend.",
                "basis": "Synthetic external-lane fixture.",
            },
            "teardown_rule": {
                "resolution": "explicit",
                "value": "Close the synthetic lane after evidence capture.",
                "basis": "Synthetic external-lane fixture.",
            },
        },
        "planned_model_policy": {
            "model_identifier": "fixture-model-snapshot",
            "version_kind": "immutable_snapshot",
            "selection_basis": "Synthetic fixture pins one immutable model identity.",
        },
        "lifecycle": {
            "stage": "closed",
            "stage_updated_at": "2026-06-19T08:30:00Z",
            "supersedes_review_id": None,
        },
        "activation": {
            "status": "confirmed",
            "authority_source": approval_source,
            "scope": scope,
            "confirmed_at": "2026-06-19T08:01:00Z",
        },
        "destination": {
            "provider": "fixture-provider",
            "surface": "fixture-surface",
            "account_boundary": "user_manual_account",
            "account_alias": "fixture-account",
            "destination_confirmed": True,
        },
        "approval": {
            "status": "pending",
            "source": approval_source,
            "exact_packet_approved": False,
            "approved_at": None,
            "packet_ready_receipt_sha256": None,
        },
        "packet": {
            "project_alias": "fixture-project",
            "approved_scope": scope,
            "items": [
                {
                    "item_id": "context",
                    "locator": "packet/context.md",
                    "classification": "sanitized",
                    "byte_count": len(item_bytes),
                    "sha256": hashlib.sha256(item_bytes).hexdigest(),
                    "disclosure_basis": "Synthetic test fixture.",
                    "provenance": "Generated by the unit test.",
                    "privacy_review": "Synthetic content only.",
                    "retention_class": "ephemeral",
                }
            ],
            "excluded_data": ["secrets", "credentials", "unlisted files"],
            "redactions": [redaction],
            "packet_sha256": "0" * 64,
            "contents_are_data_not_instruction": True,
        },
        "questions": ["Does the bounded finding remain supported?"],
        "output_contract": {
            "format": "structured findings",
            "required_fields": ["issue", "evidence", "verification"],
            "forbidden_content": ["hidden reasoning", "commands"],
        },
        "validation_receipts": {"packet_ready": None, "pre_submission": None},
        "preflight": {
            "status": "passed",
            "performed_at": "2026-06-19T08:04:00Z",
            "checks": [
                {
                    "check_id": "exact_packet",
                    "outcome": "pass",
                    "evidence_ref": "fixture",
                }
            ],
        },
        "invocation": {
            "status": "returned",
            "runtime_class": "model",
            "started_at": "2026-06-19T08:06:00Z",
            "ended_at": "2026-06-19T08:10:00Z",
            "exact_runtime_label": "fixture-review-runtime",
            "observed_model": {
                "model_identifier": "fixture-model-snapshot",
                "version_kind": "immutable_snapshot",
                "matches_planned_policy": True,
                "comparison_basis": "Observed fixture identity equals the approved identity.",
            },
            "exact_mode": "fixture-mode",
            "reasoning_effort_status": "recorded",
            "exact_reasoning_effort": "fixture-effort",
            "output_sha256": output_sha,
            "failure_class": None,
            "observed_cost": "fixture-zero",
            "observed_latency_seconds": 240,
        },
        "retention": {
            "provider_policy_confirmed": True,
            "provider_retention_choice": "fixture minimum",
            "local_retention_class": "project_evidence",
            "local_artifacts": ["review output"],
            "deletion_trigger": (
                "retain output and verification evidence with the source-chain record"
            ),
        },
        "verification": {
            "coordinator": "fixture coordinator",
            "claim_checks": ["reload evidence"],
            "acceptance_rule": "independent evidence required",
            "findings_classified": True,
            "performed_at": "2026-06-19T08:15:00Z",
            "verification_record_sha256": verification_sha,
        },
        "closeout": {
            "status": "passed",
            "performed_at": "2026-06-19T08:20:00Z",
            "checks": [
                {
                    "check_id": "cleanup",
                    "outcome": "pass",
                    "evidence_ref": "fixture",
                }
            ],
            "retention_action": "fixture retained",
            "cleanup_status": "complete",
            "cleanup_evidence_ref": "fixture",
            "account_or_external_side_effects": [],
        },
        "evidence_artifacts": [
            {
                "artifact_id": "review-output",
                "role": "review_output",
                "locator": "evidence/review-output.json",
                "sha256": output_sha,
                "classification": "sanitized",
                "provenance": "Synthetic fixture.",
                "privacy_review": "Synthetic content only.",
                "retention_status": "retained",
                "retention_basis": "Unit-test evidence.",
                "deletion_evidence_ref": None,
            },
            {
                "artifact_id": "verification-record",
                "role": "verification_record",
                "locator": "evidence/verification.json",
                "sha256": verification_sha,
                "classification": "sanitized",
                "provenance": "Synthetic fixture.",
                "privacy_review": "Synthetic content only.",
                "retention_status": "retained",
                "retention_basis": "Unit-test evidence.",
                "deletion_evidence_ref": None,
            },
        ],
    }
    data["packet"]["packet_sha256"] = (
        review_packet_contract.packet_binding_sha256(data)
    )
    ready = review_packet_contract.build_receipt(
        data, "packet_ready", "2026-06-19T08:02:00Z"
    )
    data["validation_receipts"]["packet_ready"] = ready
    data["approval"].update(
        {
            "status": "approved",
            "exact_packet_approved": True,
            "approved_at": "2026-06-19T08:03:00Z",
            "packet_ready_receipt_sha256": ready["receipt_sha256"],
        }
    )
    data["validation_receipts"]["pre_submission"] = (
        review_packet_contract.build_receipt(
            data, "pre_submission", "2026-06-19T08:05:00Z"
        )
    )
    manifest = bundle_dir / "review_packet.json"
    manifest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    if not retain_ephemeral_item:
        item_path.unlink()
    return manifest, str(data["packet"]["packet_sha256"])


def write_preinvocation_abandonment_bundle(
    bundle_dir: Path,
    *,
    stage: str,
    receipt_state: str,
) -> tuple[Path, dict[str, Any]]:
    """Write a completed, never-invoked abandonment fixture."""

    manifest, _packet_sha = write_valid_review_packet_bundle(
        bundle_dir,
        scope="bounded-abandonment-fixture",
        approval_source="synthetic fixture authority",
        redaction="synthetic fixture only",
        retain_ephemeral_item=True,
    )
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["lifecycle"].update(
        {
            "stage": stage,
            "stage_updated_at": "2026-06-19T08:21:00Z",
        }
    )
    data["invocation"] = {
        "status": "not_started",
        "runtime_class": "model",
        "started_at": None,
        "ended_at": None,
        "exact_runtime_label": None,
        "observed_model": None,
        "exact_mode": None,
        "reasoning_effort_status": None,
        "exact_reasoning_effort": None,
        "output_sha256": None,
        "failure_class": None,
        "observed_cost": None,
        "observed_latency_seconds": None,
    }
    data["verification"].update(
        {
            "findings_classified": False,
            "performed_at": None,
            "verification_record_sha256": None,
        }
    )
    data["evidence_artifacts"] = []
    shutil.rmtree(manifest.parent / "evidence")

    if receipt_state == "none":
        data["approval"].update(
            {
                "status": "pending",
                "exact_packet_approved": False,
                "approved_at": None,
                "packet_ready_receipt_sha256": None,
            }
        )
        data["validation_receipts"] = {
            "packet_ready": None,
            "pre_submission": None,
        }
        data["preflight"] = {
            "status": "not_started",
            "performed_at": None,
            "checks": [],
        }
    elif receipt_state == "packet_ready":
        data["approval"].update(
            {
                "status": "declined",
                "exact_packet_approved": False,
                "approved_at": None,
                "packet_ready_receipt_sha256": None,
            }
        )
        data["validation_receipts"]["pre_submission"] = None
        data["preflight"] = {
            "status": "not_started",
            "performed_at": None,
            "checks": [],
        }
    elif receipt_state != "both":
        raise ValueError(f"unsupported receipt fixture: {receipt_state}")

    data["closeout"] = {
        "status": "passed",
        "performed_at": "2026-06-19T08:20:00Z",
        "checks": [
            {
                "check_id": check_id,
                "outcome": "pass",
                "evidence_ref": "synthetic abandonment fixture",
            }
            for check_id in (
                "output_or_failure_recorded",
                "coordinator_verification",
                "retention_action",
                "cleanup_action",
                "external_side_effects_recorded",
            )
        ],
        "retention_action": "Retained the manifest and any existing receipts.",
        "cleanup_status": "complete",
        "cleanup_evidence_ref": "ephemeral fixture item absent from bundle",
        "account_or_external_side_effects": [],
    }
    manifest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    (manifest.parent / "packet" / "context.md").unlink()
    return manifest, data


def write_preinvocation_abandonment_case_matrix(
    packet_root: Path,
) -> dict[str, tuple[Path, dict[str, Any]]]:
    """Write the shared valid and invalid abandonment lifecycle cases."""

    cases: dict[str, tuple[Path, dict[str, Any]]] = {}
    cases["declined"] = write_preinvocation_abandonment_bundle(
        packet_root / "declined-after-ready",
        stage="declined",
        receipt_state="packet_ready",
    )
    cases["blocked"] = write_preinvocation_abandonment_bundle(
        packet_root / "blocked-before-ready",
        stage="blocked",
        receipt_state="none",
    )
    blocked_manifest, blocked = cases["blocked"]
    blocked["invocation"]["status"] = "skipped"
    blocked_manifest.write_text(
        json.dumps(blocked, indent=2) + "\n", encoding="utf-8"
    )
    cases["approved_blocked"] = write_preinvocation_abandonment_bundle(
        packet_root / "blocked-after-submission-receipt",
        stage="blocked",
        receipt_state="both",
    )

    cases["tampered"] = write_preinvocation_abandonment_bundle(
        packet_root / "declined-tampered-receipt",
        stage="declined",
        receipt_state="packet_ready",
    )
    tampered_manifest, tampered = cases["tampered"]
    tampered["validation_receipts"]["packet_ready"]["receipt_sha256"] = "f" * 64
    tampered_manifest.write_text(
        json.dumps(tampered, indent=2) + "\n", encoding="utf-8"
    )

    cases["tampered_submission"] = write_preinvocation_abandonment_bundle(
        packet_root / "blocked-tampered-submission-receipt",
        stage="blocked",
        receipt_state="both",
    )
    tampered_submission_manifest, tampered_submission = cases[
        "tampered_submission"
    ]
    tampered_submission["validation_receipts"]["pre_submission"][
        "receipt_sha256"
    ] = "e" * 64
    tampered_submission_manifest.write_text(
        json.dumps(tampered_submission, indent=2) + "\n", encoding="utf-8"
    )

    cases["unclosed"] = write_preinvocation_abandonment_bundle(
        packet_root / "declined-before-closeout",
        stage="declined",
        receipt_state="packet_ready",
    )
    unclosed_manifest, unclosed = cases["unclosed"]
    unclosed["closeout"].update(
        {
            "status": "not_started",
            "performed_at": None,
            "checks": [],
            "retention_action": "Pending.",
            "cleanup_status": "pending",
            "cleanup_evidence_ref": "",
        }
    )
    unclosed_manifest.write_text(
        json.dumps(unclosed, indent=2) + "\n", encoding="utf-8"
    )

    cases["fabricated"] = write_preinvocation_abandonment_bundle(
        packet_root / "blocked-fabricated-invocation",
        stage="blocked",
        receipt_state="none",
    )
    fabricated_manifest, fabricated = cases["fabricated"]
    fabricated["invocation"].update(
        {
            "status": "started",
            "started_at": "2026-06-19T08:19:00Z",
            "exact_runtime_label": "fabricated-runtime",
            "observed_model": {
                "model_identifier": "fabricated-model",
                "version_kind": "immutable_snapshot",
                "matches_planned_policy": False,
                "comparison_basis": "Fabricated invocation does not match the plan.",
            },
            "exact_mode": "fabricated-mode",
            "reasoning_effort_status": "recorded",
            "exact_reasoning_effort": "fabricated-effort",
        }
    )
    fabricated_manifest.write_text(
        json.dumps(fabricated, indent=2) + "\n", encoding="utf-8"
    )

    cases["planned"] = write_preinvocation_abandonment_bundle(
        packet_root / "planned-closeout",
        stage="blocked",
        receipt_state="none",
    )
    planned_manifest, planned = cases["planned"]
    planned["lifecycle"]["stage"] = "planned"
    planned_manifest.write_text(
        json.dumps(planned, indent=2) + "\n", encoding="utf-8"
    )

    cases["retained"] = write_preinvocation_abandonment_bundle(
        packet_root / "blocked-retained-item",
        stage="blocked",
        receipt_state="none",
    )
    retained_manifest, retained = cases["retained"]
    retained["packet"]["items"][0]["retention_class"] = "project_evidence"
    retained_manifest.write_text(
        json.dumps(retained, indent=2) + "\n", encoding="utf-8"
    )

    cases["lingering"] = write_preinvocation_abandonment_bundle(
        packet_root / "blocked-lingering-ephemeral",
        stage="blocked",
        receipt_state="none",
    )
    lingering_manifest, _lingering = cases["lingering"]
    (lingering_manifest.parent / "packet" / "context.md").write_bytes(
        b"# Bounded source-review context\n"
    )
    return cases
