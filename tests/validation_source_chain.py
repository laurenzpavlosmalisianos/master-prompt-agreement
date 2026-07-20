"""Source-chain artifact, reviewer-packet, status, and wait validation tests."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock
from typing import Any, Mapping, cast

from tests.validation_test_support import (
    REPO_ROOT,
    dict_items,
    string_items,
    write_preinvocation_abandonment_case_matrix,
    write_valid_review_packet_bundle,
)
import review_packet_contract  # noqa: E402
import source_chain_artifact_lint  # noqa: E402
import source_chain_preflight  # noqa: E402
import source_chain_status  # noqa: E402
import source_chain_wait  # noqa: E402


_FIXTURE_DIGEST = "c" * 64
_FIXTURE_SCOPE_SHA256 = "5b619bc978d06cba5277f7846faa48625e0ec70ba43216c35213bb6cd7f62a38"
# Independent protocol oracle: these literal bytes and digests were calculated
# from the written contract with the standard library, not this module under test.
_GOLDEN_BOUND_FIELDS = (
    "review_id",
    "created_at",
    "lane_id",
    "invocation_owner",
    "effect_mode",
    "purpose",
    "lane_controls",
    "planned_model_policy",
    "activation",
    "destination",
    "packet",
    "questions",
    "output_contract",
    "retention",
)
_GOLDEN_PACKET_BYTES = (
    b'{"activation":{"scope":"source-entry-1","status":"confirmed"},'
    b'"created_at":"2026-07-13T10:00:00Z","destination":{"provider":"example",'
    b'"surface":"manual"},"effect_mode":"observe","invocation_owner":"user_manual",'
    b'"invocation_runtime_class":"deterministic_tool","lane_controls":{"auth_session_policy":'
    b'{"basis":"local fixture has no session",'
    b'"resolution":"not_applicable","value":null},"fallback_or_abort_rule":'
    b'{"basis":"fixture task boundary","resolution":"derived","value":'
    b'"abort on invalid output"},"independence_group":{"basis":'
    b'"fixture universal control","resolution":"inherited","value":'
    b'"single-coordinator"},"manifest_kind":"compact_internal","rate_or_cost_cap":'
    b'{"basis":"fixture task boundary","resolution":"derived","value":'
    b'"one local invocation"},"teardown_rule":{"basis":"fixture lifecycle",'
    b'"resolution":"explicit","value":"close after validation"},"timeout":'
    b'{"basis":"fixture universal control","resolution":"inherited","value":'
    b'"60 seconds"}},"lane_id":"independent-lane","output_contract":'
    b'{"format":"structured findings"},"packet":'
    b'{"approved_scope":"source-entry-1","contents_are_data_not_instruction":true,'
    b'"excluded_data":["secrets"],"items":[{"byte_count":3,'
    b'"classification":"sanitized","disclosure_basis":"fixture","item_id":"item-1",'
    b'"locator":"packet/a.txt","retention_class":"ephemeral","sha256":'
    b'"abababababababababababababababababababababababababababababababab"}],'
    b'"project_alias":"fixture-project","redactions":["none"]},'
    b'"planned_model_policy":null,"purpose":'
    b'"Review one bounded item.","questions":["Is the item supported?"],'
    b'"retention":{"local_retention_class":"project_evidence"},'
    b'"review_id":"golden-review-1"}'
)
_GOLDEN_INVENTORY_BYTES = (
    b'[{"byte_count":3,"classification":"sanitized","item_id":"item-1",'
    b'"locator":"packet/a.txt","retention_class":"ephemeral","sha256":'
    b'"abababababababababababababababababababababababababababababababab"}]'
)
_GOLDEN_APPROVAL_BYTES = (
    b'{"exact_packet_approved":true,"packet_ready_receipt_sha256":'
    b'"cdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcd",'
    b'"status":"approved"}'
)
_GOLDEN_PREFLIGHT_BYTES = (
    b'{"checks":[{"check_id":"exact_packet","outcome":"pass"}],"status":"passed"}'
)
_GOLDEN_PACKET_READY_RECEIPT_BYTES = (
    b'{"approval_sha256":null,"inventory_sha256":'
    b'"54d15d1f79913aaddccc80f5a2294c8f0e734b5afe52bdd2d0295b344962e93e",'
    b'"packet_sha256":"5cf8a9b5b01c058115bb03b3e0f2c7204d654ae561299a6d8ac1fcbf30900602",'
    b'"phase":"packet_ready","preflight_sha256":null,"review_id":"golden-review-1",'
    b'"validated_at":"2026-07-13T10:01:00Z",'
    b'"validator_contract_id":"mpa-bounded-review-packet-v4"}'
)
_GOLDEN_PRE_SUBMISSION_RECEIPT_BYTES = (
    b'{"approval_sha256":'
    b'"2e3713c4b6e76585dc5c014e411f9ab1dc8543b1e78ec3dcec90ff5980e50097",'
    b'"inventory_sha256":"54d15d1f79913aaddccc80f5a2294c8f0e734b5afe52bdd2d0295b344962e93e",'
    b'"packet_sha256":"5cf8a9b5b01c058115bb03b3e0f2c7204d654ae561299a6d8ac1fcbf30900602",'
    b'"phase":"pre_submission","preflight_sha256":'
    b'"47de29e4ef82514d485de7af12112536eebb89e878a9179b73373c925d7b69ba",'
    b'"review_id":"golden-review-1","validated_at":"2026-07-13T10:04:00Z",'
    b'"validator_contract_id":"mpa-bounded-review-packet-v4"}'
)
_GOLDEN_DIGESTS = {
    "packet": "5cf8a9b5b01c058115bb03b3e0f2c7204d654ae561299a6d8ac1fcbf30900602",
    "inventory": "54d15d1f79913aaddccc80f5a2294c8f0e734b5afe52bdd2d0295b344962e93e",
    "approval": "2e3713c4b6e76585dc5c014e411f9ab1dc8543b1e78ec3dcec90ff5980e50097",
    "preflight": "47de29e4ef82514d485de7af12112536eebb89e878a9179b73373c925d7b69ba",
    "packet_ready_receipt": "f10bdac5b50d53c570b7a5b1b7eb1eaca41b7e87132573b2900402fd95060dc4",
    "pre_submission_receipt": "1e1b4232ddcac778dd3aea1be2df4af98a7be8669597c365c493ee565c12c438",
}


def _fixture_project_root(path: Path) -> Path:
    """Select the explicit project root for one isolated test fixture."""

    lexical_path = source_chain_artifact_lint.artifact_snapshot_key(path)
    artifact_roots = [
        parent for parent in lexical_path.parents if parent.name == "review_artifacts"
    ]
    return artifact_roots[-1].parent if artifact_roots else lexical_path.parent


def validate_artifact(
    path: Path,
    expected_stage: str | None = None,
    *,
    project_root: Path | None = None,
    **kwargs: Any,
) -> dict[str, object]:
    """Call the production validator with an explicit fixture root."""

    selected_root = project_root or _fixture_project_root(path)
    selected_path = path
    if project_root is None and "review_artifacts" not in path.parts:
        # Older content-focused fixtures intentionally use several sibling
        # filenames for the same logical slot. Present their immutable bytes at
        # the canonical virtual path so those tests exercise artifact semantics
        # without weakening the production tree boundary.
        raw = kwargs.get("artifact_bytes")
        if raw is None:
            try:
                raw = path.read_bytes()
            except OSError:
                raw = None
            else:
                kwargs["artifact_bytes"] = raw
        header: dict[str, str] = {}
        if isinstance(raw, bytes):
            try:
                header, _header_end, _header_errors = (
                    source_chain_artifact_lint.read_header(raw.decode("utf-8"))
                )
            except UnicodeError:
                header = {}
        stage = expected_stage or header.get("stage", "")
        logical_date = header.get("logical_date", "")
        run_slot = header.get("run_slot", "")
        suffix_template = source_chain_artifact_lint.CANONICAL_ARTIFACT_SUFFIXES.get(
            stage
        )
        if suffix_template is not None and logical_date and run_slot:
            suffix = suffix_template.format(
                logical_date=logical_date,
                run_slot=run_slot,
            )
        else:
            stage_dir = source_chain_preflight.STAGE_DIRS.get(stage, "source_review")
            suffix = f"{stage_dir}/{path.name}"
        selected_path = selected_root / "review_artifacts" / suffix

    return source_chain_artifact_lint.validate_artifact(
        selected_path,
        expected_stage,
        project_root=selected_root,
        **kwargs,
    )


def artifact_ready(path: Path, stage: str, **kwargs: Any) -> tuple[bool, str]:
    return source_chain_wait.artifact_ready(
        path,
        stage,
        project_root=_fixture_project_root(path),
        **kwargs,
    )


def observe_artifact(
    path: Path,
    stage: str,
    **kwargs: Any,
) -> source_chain_wait.ArtifactObservation:
    return source_chain_wait.observe_artifact(
        path,
        stage,
        project_root=_fixture_project_root(path),
        **kwargs,
    )


def wait_for_artifact(
    path: Path,
    stage: str,
    timeout_seconds: int,
    poll_seconds: int,
    **kwargs: Any,
) -> tuple[bool, str]:
    return source_chain_wait.wait_for_artifact(
        path,
        stage,
        timeout_seconds,
        poll_seconds,
        project_root=_fixture_project_root(path),
        **kwargs,
    )


def artifact_summary(
    artifacts_root: Path,
    stage: str,
    logical_date: str,
    run_slot: str,
    expected_scope_sha256: str,
    expected_model_route: str,
    *args: Any,
    **kwargs: Any,
) -> dict[str, object]:
    return source_chain_status.artifact_summary(
        artifacts_root,
        stage,
        logical_date,
        run_slot,
        expected_scope_sha256,
        expected_model_route,
        *args,
        project_root=artifacts_root.parent,
        **kwargs,
    )


def current_slot_decision(
    path: Path,
    stage: str,
    *args: Any,
    **kwargs: Any,
) -> dict[str, object] | None:
    return source_chain_preflight.current_slot_decision(
        path,
        stage,
        *args,
        project_root=_fixture_project_root(path),
        **kwargs,
    )


def preflight(
    stage: str,
    logical_date: str,
    run_slot: str,
    monitor_scope: str,
    model_route: str,
    artifacts_root: Path,
    *args: Any,
    **kwargs: Any,
) -> dict[str, object]:
    return source_chain_preflight.preflight(
        stage,
        logical_date,
        run_slot,
        monitor_scope,
        model_route,
        artifacts_root,
        *args,
        project_root=artifacts_root.parent,
        **kwargs,
    )


def chain_status(
    logical_date: str,
    run_slot: str,
    monitor_scope: str,
    model_route: str,
    artifacts_root: Path,
    *args: Any,
    **kwargs: Any,
) -> dict[str, object]:
    return source_chain_status.chain_status(
        logical_date,
        run_slot,
        monitor_scope,
        model_route,
        artifacts_root,
        *args,
        project_root=artifacts_root.parent,
        **kwargs,
    )


def independent_review_packet_vector() -> dict[str, Any]:
    return {
        "review_id": "golden-review-1",
        "created_at": "2026-07-13T10:00:00Z",
        "lane_id": "independent-lane",
        "invocation_owner": "user_manual",
        "effect_mode": "observe",
        "purpose": "Review one bounded item.",
        "lane_controls": {
            "manifest_kind": "compact_internal",
            "independence_group": {
                "resolution": "inherited",
                "value": "single-coordinator",
                "basis": "fixture universal control",
            },
            "fallback_or_abort_rule": {
                "resolution": "derived",
                "value": "abort on invalid output",
                "basis": "fixture task boundary",
            },
            "auth_session_policy": {
                "resolution": "not_applicable",
                "value": None,
                "basis": "local fixture has no session",
            },
            "timeout": {
                "resolution": "inherited",
                "value": "60 seconds",
                "basis": "fixture universal control",
            },
            "rate_or_cost_cap": {
                "resolution": "derived",
                "value": "one local invocation",
                "basis": "fixture task boundary",
            },
            "teardown_rule": {
                "resolution": "explicit",
                "value": "close after validation",
                "basis": "fixture lifecycle",
            },
        },
        "planned_model_policy": None,
        "activation": {"scope": "source-entry-1", "status": "confirmed"},
        "destination": {"provider": "example", "surface": "manual"},
        "packet": {
            "approved_scope": "source-entry-1",
            "contents_are_data_not_instruction": True,
            "excluded_data": ["secrets"],
            "items": [{
                "byte_count": 3,
                "classification": "sanitized",
                "disclosure_basis": "fixture",
                "item_id": "item-1",
                "locator": "packet/a.txt",
                "retention_class": "ephemeral",
                "sha256": "ab" * 32,
            }],
            "packet_sha256": "0" * 64,
            "project_alias": "fixture-project",
            "redactions": ["none"],
        },
        "questions": ["Is the item supported?"],
        "output_contract": {"format": "structured findings"},
        "retention": {"local_retention_class": "project_evidence"},
        "invocation": {
            "runtime_class": "deterministic_tool",
            "status": "not_started",
        },
        "approval": {
            "exact_packet_approved": True,
            "packet_ready_receipt_sha256": "cd" * 32,
            "status": "approved",
        },
        "preflight": {
            "checks": [{"check_id": "exact_packet", "outcome": "pass"}],
            "status": "passed",
        },
        "lifecycle": {
            "stage": "approved",
            "stage_updated_at": "2026-07-13T10:03:00Z",
        },
    }


_FixtureValue = str | tuple[str, ...]
_COMMON_ARTIFACT_HEADERS: dict[str, _FixtureValue] = {
    "artifact_schema_version": "6",
    "chain_id": "source-2026-06-19-0930",
    "logical_date": "2026-06-19",
    "run_slot": "0930",
    "monitor_scope": "framework-sources",
    "monitor_scope_sha256": _FIXTURE_SCOPE_SHA256,
    "model_route": "quality_first",
    "model_label": "fixture-model",
    "reasoning_effort": "high",
    "execution_mode": "standard",
    "timezone": "Europe/Vienna",
}
_STAGE_ARTIFACT_HEADERS: dict[str, dict[str, _FixtureValue]] = {
    "monitor": {
        "stage_run_id": "monitor-2026-06-19-0930",
        "attempt_id": "monitor-2026-06-19T023000Z-abc123",
        "started_at_utc": "2026-06-19T00:30:00Z",
        "completed_at_utc": "2026-06-19T00:52:00Z",
        "status": "pass",
        "source_status": "pass",
        "workspace_status": "dirty",
        "external_reviewer_status": "considered_skipped",
        "external_reviewer_packet_scope": "none",
        "inaccessible_source_count": "0",
        "unresolved_inaccessible_source_count": "0",
        "source_root_coverage_count": "0",
        "source_registry_files": (
            "  - path: local_overlays/references/security_sources.md",
            f"    sha256: {_FIXTURE_DIGEST}",
        ),
        "policy_files": (
            "  - path: local_overlays/source_monitor_policy.md",
            f"    sha256: {_FIXTURE_DIGEST}",
        ),
    },
    "review": {
        "stage_run_id": "review-2026-06-19-0930",
        "attempt_id": "review-2026-06-19T043000Z-abc123",
        "started_at_utc": "2026-06-19T02:30:00Z",
        "completed_at_utc": "2026-06-19T02:45:00Z",
        "status": "pass",
        "external_reviewer_status": "not_needed",
        "external_reviewer_packet_scope": "none",
        "input_monitor_state": "resolved",
        "input_monitor_artifact": "review_artifacts/source_monitor/2026-06-19_0930.md",
        "input_monitor_stage_run_id": "monitor-2026-06-19-0930",
        "input_monitor_attempt_id": "monitor-2026-06-19T023000Z-abc123",
        "input_monitor_sha256": _FIXTURE_DIGEST,
        "inaccessible_source_count": "0",
        "unresolved_inaccessible_source_count": "0",
        "accepted_findings": "1",
        "manual_findings": "0",
        "rejected_findings": "0",
    },
    "apply": {
        "stage_run_id": "apply-2026-06-19-0930",
        "attempt_id": "apply-2026-06-19T063000Z-abc123",
        "started_at_utc": "2026-06-19T04:30:00Z",
        "completed_at_utc": "2026-06-19T04:47:00Z",
        "status": "pass",
        "external_reviewer_status": "not_needed",
        "external_reviewer_packet_scope": "none",
        "external_reviewer_approval_source": "none",
        "external_reviewer_packet_sha256": "unavailable",
        "external_reviewer_packet_manifest": "none",
        "external_reviewer_packet_manifest_sha256": "unavailable",
        "external_reviewer_redaction": "none",
        "authority_grant": "active-thread",
        "authority_scope": "exact accepted files",
        "authority_source": "active thread",
        "input_review_state": "resolved",
        "input_review_artifact": "review_artifacts/source_review/2026-06-19_0930.md",
        "input_review_stage_run_id": "review-2026-06-19-0930",
        "input_review_attempt_id": "review-2026-06-19T043000Z-abc123",
        "input_review_sha256": _FIXTURE_DIGEST,
        "base_commit": "abc1234",
        "changed_files": ("  - local_overlays/references/security_sources.md",),
        "commit": "def5678",
        "verification": (
            "  - command: uv run python -B scripts/check_reference_freshness.py",
            "    covers: accepted-source-entry-1",
            "    tree_or_artifact: commit:def5678",
            "    dirty_tree: tracked-diff-matches-changed_files",
            "    touched_files: local_overlays/references/security_sources.md",
            "    expected_assertion: source freshness metadata and monitor-root discipline pass for accepted-source-entry-1",
            f"    output_ref: sha256:{_FIXTURE_DIGEST}",
            "    environment: approved-container",
            "    exit_code: 0",
        ),
    },
    "assurance": {
        "stage_run_id": "assurance-2026-06-19-0930",
        "attempt_id": "assurance-2026-06-19T073000Z-abc123",
        "started_at_utc": "2026-06-19T05:30:00Z",
        "completed_at_utc": "2026-06-19T05:38:00Z",
        "status": "pass",
        "input_monitor_state": "resolved",
        "input_monitor_artifact": "review_artifacts/source_monitor/2026-06-19_0930.md",
        "input_monitor_stage_run_id": "monitor-2026-06-19-0930",
        "input_monitor_attempt_id": "monitor-2026-06-19T023000Z-abc123",
        "input_monitor_sha256": _FIXTURE_DIGEST,
        "input_review_state": "resolved",
        "input_review_artifact": "review_artifacts/source_review/2026-06-19_0930.md",
        "input_review_stage_run_id": "review-2026-06-19-0930",
        "input_review_attempt_id": "review-2026-06-19T043000Z-abc123",
        "input_review_sha256": _FIXTURE_DIGEST,
        "input_apply_state": "resolved",
        "input_apply_artifact": "review_artifacts/source_apply/2026-06-19_0930.md",
        "input_apply_stage_run_id": "apply-2026-06-19-0930",
        "input_apply_attempt_id": "apply-2026-06-19T063000Z-abc123",
        "input_apply_sha256": _FIXTURE_DIGEST,
        "latest_commit": "def5678",
        "unresolved_findings": "0",
        "unresolved_inaccessible_source_count": "0",
    },
}
_STAGE_ARTIFACT_BODIES = {
    "monitor": ("# Monitor",),
    "review": (
        "## Accepted Findings",
        "",
        "finding_id: accepted-source-entry-1",
        "finding_hash: auto",
        "classification: accept-source-entry",
        "apply_mode: auto",
        "change_class: source-entry-content",
        "source_tier: [official-doc]",
        "source_role: evidence-url",
        "quality_gate: primary_verified",
        "durable_abstraction: Existing source metadata changed and should update the private source entry.",
        "applicability: Applies only to the checked source family and its approved monitor root.",
        "rejected_source_specifics: No tool commands, implementation details, or doctrine changes are adopted.",
        "affected_files:",
        "  - local_overlays/references/security_sources.md",
        "risk: low",
        "evidence:",
        "  - https://example.com/security/advisory",
        "evidence_url: https://example.com/security/advisory",
        "monitor_root: https://example.com/security/",
        "root_decision: monitor",
        "required_verification:",
        "  - uv run python -B scripts/check_reference_freshness.py",
        "",
        "# Review",
    ),
    "apply": ("# Apply",),
    "assurance": ("# Assurance",),
}


def _source_chain_artifact_fixture(stage: str, overrides: Mapping[str, str]) -> str:
    stage_headers = _STAGE_ARTIFACT_HEADERS.get(stage)
    if stage_headers is None:
        raise AssertionError(f"unknown test fixture stage: {stage}")
    headers: dict[str, _FixtureValue] = {
        "artifact_schema_version": _COMMON_ARTIFACT_HEADERS["artifact_schema_version"],
        "chain_id": _COMMON_ARTIFACT_HEADERS["chain_id"],
        "stage": stage,
        "stage_run_id": stage_headers["stage_run_id"],
        "attempt_id": stage_headers["attempt_id"],
        **{
            key: value
            for key, value in _COMMON_ARTIFACT_HEADERS.items()
            if key not in {"artifact_schema_version", "chain_id"}
        },
        **{
            key: value
            for key, value in stage_headers.items()
            if key not in {"stage_run_id", "attempt_id"}
        },
    }
    unknown = set(overrides) - set(headers)
    if unknown:
        raise AssertionError(f"unknown {stage} fixture override fields: {sorted(unknown)}")
    headers.update(overrides)
    lines: list[str] = []
    for key, value in headers.items():
        if isinstance(value, tuple):
            lines.append(f"{key}:")
            lines.extend(value)
        else:
            lines.append(f"{key}: {value}")
    text = "\n".join([*lines, "", *_STAGE_ARTIFACT_BODIES[stage]])
    if stage == "review":
        blocks = source_chain_artifact_lint.decision_blocks(text)
        if len(blocks) != 1:
            raise AssertionError("review fixture must contain exactly one decision block")
        text = text.replace(
            "finding_hash: auto",
            f"finding_hash: {source_chain_artifact_lint.decision_hash(blocks[0])}",
            1,
        )
    return text


def monitor_artifact_fixture(**overrides: str) -> str:
    return _source_chain_artifact_fixture("monitor", overrides)


def review_artifact_fixture(**overrides: str) -> str:
    return _source_chain_artifact_fixture("review", overrides)


def apply_artifact_fixture(**overrides: str) -> str:
    return _source_chain_artifact_fixture("apply", overrides)


def assurance_artifact_fixture(**overrides: str) -> str:
    return _source_chain_artifact_fixture("assurance", overrides)


class SourceChainTests(unittest.TestCase):
    def test_review_packet_digest_contract_matches_independent_golden_vector(self) -> None:
        data = independent_review_packet_vector()
        self.assertEqual(_GOLDEN_BOUND_FIELDS, review_packet_contract.PACKET_BINDING_FIELDS)

        packet_binding = {
            field: copy.deepcopy(data[field])
            for field in _GOLDEN_BOUND_FIELDS
        }
        cast(dict[str, Any], packet_binding["packet"]).pop("packet_sha256")
        packet_binding["invocation_runtime_class"] = data["invocation"][
            "runtime_class"
        ]
        inventory = [{
            "item_id": "item-1",
            "locator": "packet/a.txt",
            "classification": "sanitized",
            "byte_count": 3,
            "sha256": "ab" * 32,
            "retention_class": "ephemeral",
        }]
        canonical_cases = {
            "packet": (packet_binding, _GOLDEN_PACKET_BYTES),
            "inventory": (inventory, _GOLDEN_INVENTORY_BYTES),
            "approval": (data["approval"], _GOLDEN_APPROVAL_BYTES),
            "preflight": (data["preflight"], _GOLDEN_PREFLIGHT_BYTES),
        }
        for name, (payload, literal_bytes) in canonical_cases.items():
            with self.subTest(payload=name):
                self.assertEqual(literal_bytes, review_packet_contract.canonical_bytes(payload))
                self.assertEqual(
                    _GOLDEN_DIGESTS[name],
                    hashlib.sha256(literal_bytes).hexdigest(),
                )

        self.assertEqual(
            _GOLDEN_DIGESTS["packet"],
            review_packet_contract.packet_binding_sha256(data),
        )
        self.assertEqual(inventory, review_packet_contract.packet_inventory(data))
        self.assertEqual(
            _GOLDEN_DIGESTS["inventory"],
            review_packet_contract.packet_inventory_sha256(data),
        )
        self.assertEqual(
            _GOLDEN_DIGESTS["approval"],
            review_packet_contract.approval_sha256(data),
        )
        self.assertEqual(
            _GOLDEN_DIGESTS["preflight"],
            review_packet_contract.preflight_sha256(data),
        )

        ready_receipt = {
            "validator_contract_id": "mpa-bounded-review-packet-v4",
            "phase": "packet_ready",
            "packet_sha256": _GOLDEN_DIGESTS["packet"],
            "inventory_sha256": _GOLDEN_DIGESTS["inventory"],
            "approval_sha256": None,
            "preflight_sha256": None,
            "validated_at": "2026-07-13T10:01:00Z",
            "receipt_sha256": _GOLDEN_DIGESTS["packet_ready_receipt"],
        }
        pre_submission_receipt = {
            "validator_contract_id": "mpa-bounded-review-packet-v4",
            "phase": "pre_submission",
            "packet_sha256": _GOLDEN_DIGESTS["packet"],
            "inventory_sha256": _GOLDEN_DIGESTS["inventory"],
            "approval_sha256": _GOLDEN_DIGESTS["approval"],
            "preflight_sha256": _GOLDEN_DIGESTS["preflight"],
            "validated_at": "2026-07-13T10:04:00Z",
            "receipt_sha256": _GOLDEN_DIGESTS["pre_submission_receipt"],
        }
        receipt_cases = (
            (
                "packet_ready",
                ready_receipt,
                _GOLDEN_PACKET_READY_RECEIPT_BYTES,
                _GOLDEN_DIGESTS["packet_ready_receipt"],
            ),
            (
                "pre_submission",
                pre_submission_receipt,
                _GOLDEN_PRE_SUBMISSION_RECEIPT_BYTES,
                _GOLDEN_DIGESTS["pre_submission_receipt"],
            ),
        )
        for phase, receipt, literal_bytes, literal_digest in receipt_cases:
            with self.subTest(receipt=phase):
                payload = review_packet_contract.receipt_payload(data, phase, receipt)
                self.assertEqual(literal_bytes, review_packet_contract.canonical_bytes(payload))
                self.assertEqual(literal_digest, hashlib.sha256(literal_bytes).hexdigest())
                self.assertEqual(
                    literal_digest,
                    review_packet_contract.receipt_sha256(data, phase, receipt),
                )
                self.assertEqual(
                    receipt,
                    review_packet_contract.build_receipt(
                        data,
                        phase,
                        cast(str, receipt["validated_at"]),
                    ),
                )

        for field in _GOLDEN_BOUND_FIELDS:
            candidate = copy.deepcopy(data)
            candidate[field] = {"mutated": field}
            with self.subTest(packet_bound_field=field):
                self.assertNotEqual(
                    _GOLDEN_DIGESTS["packet"],
                    review_packet_contract.packet_binding_sha256(candidate),
                )
        runtime_mutation = copy.deepcopy(data)
        runtime_mutation["invocation"]["runtime_class"] = "model"
        self.assertNotEqual(
            _GOLDEN_DIGESTS["packet"],
            review_packet_contract.packet_binding_sha256(runtime_mutation),
        )

        lifecycle_only_mutation = copy.deepcopy(data)
        lifecycle_only_mutation["lifecycle"] = {
            "stage": "closed",
            "stage_updated_at": "2026-07-13T11:00:00Z",
        }
        lifecycle_only_mutation["invocation"]["status"] = "returned"
        lifecycle_only_mutation["validation_receipts"] = {"packet_ready": "changed"}
        lifecycle_only_mutation["verification"] = {"findings_classified": True}
        lifecycle_only_mutation["closeout"] = {"status": "passed"}
        self.assertEqual(
            _GOLDEN_DIGESTS["packet"],
            review_packet_contract.packet_binding_sha256(lifecycle_only_mutation),
        )

        for field in ("item_id", "locator", "classification", "byte_count", "sha256", "retention_class"):
            candidate = copy.deepcopy(data)
            candidate["packet"]["items"][0][field] = f"mutated-{field}"
            with self.subTest(inventory_bound_field=field):
                self.assertNotEqual(
                    _GOLDEN_DIGESTS["inventory"],
                    review_packet_contract.packet_inventory_sha256(candidate),
                )
        non_inventory_mutation = copy.deepcopy(data)
        non_inventory_mutation["packet"]["items"][0]["disclosure_basis"] = "changed"
        self.assertEqual(
            _GOLDEN_DIGESTS["inventory"],
            review_packet_contract.packet_inventory_sha256(non_inventory_mutation),
        )
        self.assertNotEqual(
            _GOLDEN_DIGESTS["packet"],
            review_packet_contract.packet_binding_sha256(non_inventory_mutation),
        )

        approval_mutation = copy.deepcopy(data)
        approval_mutation["approval"]["status"] = "pending"
        self.assertNotEqual(
            _GOLDEN_DIGESTS["approval"],
            review_packet_contract.approval_sha256(approval_mutation),
        )
        self.assertEqual(
            _GOLDEN_DIGESTS["packet_ready_receipt"],
            review_packet_contract.build_receipt(
                approval_mutation,
                "packet_ready",
                "2026-07-13T10:01:00Z",
            )["receipt_sha256"],
        )
        self.assertNotEqual(
            _GOLDEN_DIGESTS["pre_submission_receipt"],
            review_packet_contract.build_receipt(
                approval_mutation,
                "pre_submission",
                "2026-07-13T10:04:00Z",
            )["receipt_sha256"],
        )

        preflight_mutation = copy.deepcopy(data)
        preflight_mutation["preflight"]["status"] = "failed"
        self.assertNotEqual(
            _GOLDEN_DIGESTS["preflight"],
            review_packet_contract.preflight_sha256(preflight_mutation),
        )
        self.assertNotEqual(
            _GOLDEN_DIGESTS["pre_submission_receipt"],
            review_packet_contract.build_receipt(
                preflight_mutation,
                "pre_submission",
                "2026-07-13T10:04:00Z",
            )["receipt_sha256"],
        )

        receipt_time_mutation = dict(ready_receipt)
        receipt_time_mutation["validated_at"] = "2026-07-13T10:01:01Z"
        self.assertNotEqual(
            _GOLDEN_DIGESTS["packet_ready_receipt"],
            review_packet_contract.receipt_sha256(
                data,
                "packet_ready",
                receipt_time_mutation,
            ),
        )

    def test_public_source_chain_contract_matches_executable_stage_fields(self) -> None:
        contract = REPO_ROOT / "docs" / "source_chain_artifacts.md"
        self.assertEqual([], source_chain_artifact_lint.public_contract_errors(contract))

        with tempfile.TemporaryDirectory() as temp_dir:
            original = contract.read_text(encoding="utf-8")
            artifact_root = "review_artifacts" + "/"
            cases = {
                "schema": (
                    "artifact_schema_version: 6",
                    "artifact_schema_version: 4",
                    "monitor template artifact_schema_version",
                ),
                "path": (
                    f"assurance: {artifact_root}automation_assurance/{{logical_date}}_{{run_slot}}.md",
                    f"assurance: {artifact_root}source_automation/{{logical_date}}_{{run_slot}}.md",
                    "canonical paths do not match",
                ),
                "status": (
                    "status: pass | no-findings | blocked | partial",
                    "status: pass | no-findings | blocked",
                    "monitor template status values",
                ),
                "decision": (
                    "applicability: <where-and-when-it-improves-the-project>",
                    "applicability_typo: <where-and-when-it-improves-the-project>",
                    "review-decision fields",
                ),
                "inaccessible": (
                    "failure_detail: <bounded-evidence>",
                    "failure_details: <bounded-evidence>",
                    "inaccessible fields",
                ),
                "coverage": (
                    "latest_seen_key: <release-tag-feed-guid-commit-etag-or-none>",
                    "latest_seen_cursor: <release-tag-feed-guid-commit-etag-or-none>",
                    "source-root-coverage fields",
                ),
                "verification": (
                    "    expected_assertion: <objective-invariant-tested>",
                    "    expected_assertions: <objective-invariant-tested>",
                    "apply verification fields",
                ),
            }
            reports: dict[str, list[str]] = {}
            for case_id, (old, new, _expected) in cases.items():
                with self.subTest(case_id=case_id):
                    self.assertIn(old, original)
                    drifted = Path(temp_dir) / f"{case_id}.md"
                    drifted.write_text(original.replace(old, new, 1), encoding="utf-8")
                    reports[case_id] = source_chain_artifact_lint.public_contract_errors(
                        drifted
                    )

        for case_id, (_old, _new, expected) in cases.items():
            self.assertTrue(
                any(expected in error for error in reports[case_id]),
                reports[case_id],
            )

    def test_source_chain_artifact_lint_rejects_unknown_header_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            monitor = (
                Path(temp_dir)
                / "review_artifacts"
                / "source_monitor"
                / "2026-06-19_0930.md"
            )
            monitor.parent.mkdir(parents=True)
            monitor.write_text(
                monitor_artifact_fixture().replace(
                    "\n\n# Monitor",
                    "\nproject_extension: ignored-state\n\n# Monitor",
                    1,
                ),
                encoding="utf-8",
            )

            report = validate_artifact(
                monitor,
                "monitor",
            )

        self.assertIn(
            "unknown header fields: project_extension",
            string_items(report["errors"]),
        )

    def test_source_chain_artifact_lint_rejects_duplicate_headers_without_semantic_reads(self) -> None:
        canonical_monitor = "review_artifacts/source_monitor/2026-06-19_0930.md"
        alternate_monitor = (
            "review_artifacts/alternate/review_artifacts/"
            "source_monitor/2026-06-19_0930.md"
        )
        base_text = review_artifact_fixture()
        cases = {
            "stage": (
                base_text.replace(
                    "stage: review",
                    "stage: review\nstage: apply",
                    1,
                ),
                base_text.replace(
                    "stage: review",
                    "stage: apply\nstage: review",
                    1,
                ),
            ),
            "input_monitor_artifact": (
                base_text.replace(
                    f"input_monitor_artifact: {canonical_monitor}",
                    "\n".join(
                        (
                            f"input_monitor_artifact: {canonical_monitor}",
                            f"input_monitor_artifact: {alternate_monitor}",
                        )
                    ),
                    1,
                ),
                base_text.replace(
                    f"input_monitor_artifact: {canonical_monitor}",
                    "\n".join(
                        (
                            f"input_monitor_artifact: {alternate_monitor}",
                            f"input_monitor_artifact: {canonical_monitor}",
                        )
                    ),
                    1,
                ),
            ),
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            path = (
                Path(temp_dir)
                / "review_artifacts"
                / "source_review"
                / "2026-06-19_0930.md"
            )
            with mock.patch.object(
                source_chain_artifact_lint,
                "read_artifact_bytes",
                side_effect=AssertionError("ambiguous headers must gate referenced-file reads"),
            ) as artifact_read:
                reports = {
                    field_name: tuple(
                        validate_artifact(
                            path,
                            "review",
                            artifact_bytes=text.encode("utf-8"),
                        )
                        for text in ordered_texts
                    )
                    for field_name, ordered_texts in cases.items()
                }
                implicit_stage_reports = tuple(
                    validate_artifact(
                        path,
                        artifact_bytes=text.encode("utf-8"),
                    )
                    for text in cases["stage"]
                )

        artifact_read.assert_not_called()
        self.assertEqual(
            implicit_stage_reports[0]["errors"],
            implicit_stage_reports[1]["errors"],
        )
        self.assertIsNone(implicit_stage_reports[0]["stage"])
        self.assertIsNone(implicit_stage_reports[1]["stage"])
        for field_name, ordered_reports in reports.items():
            with self.subTest(field_name=field_name):
                first, second = ordered_reports
                self.assertEqual(first["errors"], second["errors"])
                self.assertEqual("review", first["stage"])
                self.assertEqual("review", second["stage"])
                self.assertTrue(
                    any(
                        f"duplicate header field" in error and field_name in error
                        for error in string_items(first["errors"])
                    ),
                    first,
                )
                first_header, _first_end, _first_errors = (
                    source_chain_artifact_lint.read_header(cases[field_name][0])
                )
                second_header, _second_end, _second_errors = (
                    source_chain_artifact_lint.read_header(cases[field_name][1])
                )
                self.assertNotIn(field_name, first_header)
                self.assertNotIn(field_name, second_header)

    def test_source_chain_artifact_lint_requires_headers_and_decision_fields(self) -> None:
        digest = "a" * 64
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            monitor_ref = root / "review_artifacts" / "source_monitor" / "2026-06-19_0930.md"
            monitor_ref.parent.mkdir(parents=True)
            monitor_ref.write_text(
                "\n".join(
                    [
                        "artifact_schema_version: 6",
                        "chain_id: source-2026-06-19-0930",
                        "stage: monitor",
                        "stage_run_id: monitor-2026-06-19-0930",
                        "attempt_id: monitor-2026-06-19T023000Z-abc123",
                        "logical_date: 2026-06-19",
                        "run_slot: 0930",
                        "monitor_scope: framework-sources",
                        "monitor_scope_sha256: 5b619bc978d06cba5277f7846faa48625e0ec70ba43216c35213bb6cd7f62a38",
                        "model_route: quality_first",
                        "model_label: fixture-model",
                        "reasoning_effort: high",
                        "execution_mode: standard",
                        "timezone: Europe/Vienna",
                        "started_at_utc: 2026-06-19T00:30:00Z",
                        "completed_at_utc: 2026-06-19T00:45:00Z",
                        "status: pass",
                        "source_status: pass",
                        "workspace_status: clean",
                        "external_reviewer_status: not_needed",
                        "external_reviewer_packet_scope: none",
                        "inaccessible_source_count: 0",
                        "unresolved_inaccessible_source_count: 0",
                        "source_root_coverage_count: 0",
                        "source_registry_files:",
                        "  - path: local_overlays/references/security_sources.md",
                        f"    sha256: {digest}",
                        "policy_files:",
                        "  - path: local_overlays/source_monitor_policy.md",
                        f"    sha256: {digest}",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            monitor_hash = source_chain_artifact_lint.file_sha256(monitor_ref)
            prose_review = root / "prose-review.md"
            prose_review.write_text("# Source Review\n\nNo machine header.\n", encoding="utf-8")
            incomplete_review = root / "incomplete-review.md"
            incomplete_review.write_text(
                "\n".join(
                    [
                        "artifact_schema_version: 6",
                        "chain_id: source-2026-06-19-0930",
                        "stage: review",
                        "stage_run_id: review-2026-06-19-0930",
                        "attempt_id: review-2026-06-19T043000Z-abc123",
                        "logical_date: 2026-06-19",
                        "run_slot: 0930",
                        "monitor_scope: framework-sources",
                        "monitor_scope_sha256: 5b619bc978d06cba5277f7846faa48625e0ec70ba43216c35213bb6cd7f62a38",
                        "model_route: quality_first",
                        "model_label: fixture-model",
                        "reasoning_effort: high",
                        "execution_mode: standard",
                        "timezone: Europe/Vienna",
                        "started_at_utc: 2026-06-19T02:30:00Z",
                        "completed_at_utc: 2026-06-19T02:45:00Z",
                        "status: pass",
                        "external_reviewer_status: not_needed",
                        "external_reviewer_packet_scope: none",
                        "input_monitor_artifact: review_artifacts/source_monitor/2026-06-19_0930.md",
                        "input_monitor_stage_run_id: monitor-2026-06-19-0930",
                        "input_monitor_attempt_id: monitor-2026-06-19T023000Z-abc123",
                        f"input_monitor_sha256: {digest}",
                        "accepted_findings: 1",
                        "manual_findings: 0",
                        "rejected_findings: 0",
                        "",
                        "## Accepted Findings",
                        "",
                        "finding_id: accepted-1",
                        "apply_mode: auto",
                    ]
                ),
                encoding="utf-8",
            )
            duplicate_header_review = root / "duplicate-header-review.md"
            duplicate_header_review.write_text(
                "\n".join(
                    [
                        "chain_id: source-2026-06-19-0930",
                        "stage: review",
                        "stage: review",
                        "stage_run_id: review-2026-06-19-0930",
                        "logical_date: 2026-06-19",
                        "run_slot: 0930",
                        "monitor_scope: framework-sources",
                        "monitor_scope_sha256: 5b619bc978d06cba5277f7846faa48625e0ec70ba43216c35213bb6cd7f62a38",
                        "model_route: quality_first",
                        "model_label: fixture-model",
                        "reasoning_effort: high",
                        "execution_mode: standard",
                        "timezone: Europe/Vienna",
                        "status: pass",
                        "external_reviewer_status: not_needed",
                        "external_reviewer_packet_scope: none",
                        f"input_monitor_sha256: {digest}",
                        "accepted_findings: 0",
                        "manual_findings: 0",
                        "rejected_findings: 0",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            valid_review = root / "valid-review.md"
            valid_review.write_text(
                "\n".join(
                    [
                        "artifact_schema_version: 6",
                        "chain_id: source-2026-06-19-0930",
                        "stage: review",
                        "stage_run_id: review-2026-06-19-0930",
                        "attempt_id: review-2026-06-19T043000Z-abc123",
                        "logical_date: 2026-06-19",
                        "run_slot: 0930",
                        "monitor_scope: framework-sources",
                        "monitor_scope_sha256: 5b619bc978d06cba5277f7846faa48625e0ec70ba43216c35213bb6cd7f62a38",
                        "model_route: quality_first",
                        "model_label: fixture-model",
                        "reasoning_effort: high",
                        "execution_mode: standard",
                        "timezone: Europe/Vienna",
                        "started_at_utc: 2026-06-19T02:30:00Z",
                        "completed_at_utc: 2026-06-19T02:45:00Z",
                        "status: pass",
                        "external_reviewer_status: not_needed",
                        "external_reviewer_packet_scope: none",
                        "input_monitor_state: resolved",
                        "input_monitor_artifact: review_artifacts/source_monitor/2026-06-19_0930.md",
                        "input_monitor_stage_run_id: monitor-2026-06-19-0930",
                        "input_monitor_attempt_id: monitor-2026-06-19T023000Z-abc123",
                        f"input_monitor_sha256: {monitor_hash}",
                        "inaccessible_source_count: 0",
                        "unresolved_inaccessible_source_count: 0",
                        "accepted_findings: 1",
                        "manual_findings: 0",
                        "rejected_findings: 0",
                        "",
                        "## Accepted Findings",
                        "",
                        "finding_id: accepted-1",
                        f"finding_hash: {digest}",
                        "classification: accept-source-entry",
                        "apply_mode: auto",
                        "change_class: source-entry-content",
                        "source_tier: [official-doc]",
                        "source_role: evidence-url",
                        "quality_gate: primary_verified",
                        "durable_abstraction: Existing source metadata changed and should update the private source entry.",
                        "applicability: Applies only to the checked source family and its approved monitor root.",
                        "rejected_source_specifics: No tool commands, implementation details, or doctrine changes are adopted.",
                        "affected_files:",
                        "  - local_overlays/references/security_sources.md",
                        "risk: low",
                        "evidence:",
                        "  - official source checked 2026-06-19",
                        "evidence_url: https://example.com/security/advisory",
                        "monitor_root: https://example.com/security/",
                        "root_decision: monitor",
                        "required_verification:",
                        "  - uv run python -B scripts/check_reference_freshness.py",
                    ]
                ),
                encoding="utf-8",
            )

            prose = validate_artifact(prose_review, "review")
            incomplete = validate_artifact(incomplete_review, "review")
            duplicate_header = validate_artifact(duplicate_header_review, "review")
            valid = validate_artifact(valid_review, "review")
            wrong_route = validate_artifact(
                valid_review,
                "review",
                expected_model_route="economy",
            )
            wrong_model_label = validate_artifact(
                valid_review,
                "review",
                expected_model_label="expected-model",
            )
            wrong_reasoning_effort = validate_artifact(
                valid_review,
                "review",
                expected_reasoning_effort="xhigh",
            )
            wrong_execution_mode = validate_artifact(
                valid_review,
                "review",
                expected_execution_mode="pro",
            )
            wrong_timezone = validate_artifact(
                valid_review,
                "review",
                expected_timezone="UTC",
            )

            other_scope_hash = source_chain_artifact_lint.monitor_scope_sha256("other-scope")
            monitor_ref.write_text(
                monitor_ref.read_text(encoding="utf-8")
                .replace("monitor_scope: framework-sources", "monitor_scope: other-scope")
                .replace(
                    "monitor_scope_sha256: 5b619bc978d06cba5277f7846faa48625e0ec70ba43216c35213bb6cd7f62a38",
                    f"monitor_scope_sha256: {other_scope_hash}",
                )
                .replace("model_route: quality_first", "model_route: alternate_route")
                .replace("timezone: Europe/Vienna", "timezone: UTC"),
                encoding="utf-8",
            )
            changed_monitor_hash = source_chain_artifact_lint.file_sha256(monitor_ref)
            valid_review.write_text(
                valid_review.read_text(encoding="utf-8").replace(
                    f"input_monitor_sha256: {monitor_hash}",
                    f"input_monitor_sha256: {changed_monitor_hash}",
                ),
                encoding="utf-8",
            )
            continuity = validate_artifact(valid_review, "review")

        self.assertTrue(any("missing machine-readable header" in error for error in string_items(prose["errors"])))
        self.assertTrue(any("missing fields" in error for error in string_items(incomplete["errors"])))
        self.assertTrue(any("duplicate header field" in error for error in string_items(duplicate_header["errors"])))
        self.assertEqual([], valid["errors"])
        self.assertTrue(
            any("model_route must match the expected route economy" in error for error in string_items(wrong_route["errors"]))
        )
        self.assertTrue(
            any(
                "model_label must match the expected value expected-model" in error
                for error in string_items(wrong_model_label["errors"])
            )
        )
        self.assertTrue(
            any(
                "reasoning_effort must match the expected value xhigh" in error
                for error in string_items(wrong_reasoning_effort["errors"])
            )
        )
        self.assertTrue(
            any(
                "execution_mode must match the expected value pro" in error
                for error in string_items(wrong_execution_mode["errors"])
            )
        )
        self.assertTrue(
            any("timezone must match the expected timezone UTC" in error for error in string_items(wrong_timezone["errors"]))
        )
        continuity_errors = string_items(continuity["errors"])
        for field_name in (
            "monitor_scope",
            "monitor_scope_sha256",
            "model_route",
            "timezone",
        ):
            self.assertTrue(
                any(f"header {field_name} does not match" in error for error in continuity_errors),
                continuity_errors,
            )

    def test_source_chain_artifact_lint_rejects_count_mismatch_negative_and_empty_fields(self) -> None:
        digest = "b" * 64

        def full_block(
            evidence_url: str = "https://example.com/security/advisory",
            apply_mode: str = "auto",
            durable_abstraction: str = "Existing source metadata changed and should update the private source entry.",
            applicability: str = "Applies only to the checked source family and its approved monitor root.",
            rejected_source_specifics: str = "No tool commands, implementation details, or doctrine changes are adopted.",
        ) -> list[str]:
            return [
                "finding_id: accepted-1",
                f"finding_hash: {digest}",
                "classification: accept-source-entry",
                f"apply_mode: {apply_mode}",
                "change_class: source-entry-content",
                "source_tier: [official-doc]",
                "source_role: evidence-url",
                "quality_gate: primary_verified",
                f"durable_abstraction: {durable_abstraction}",
                f"applicability: {applicability}",
                f"rejected_source_specifics: {rejected_source_specifics}",
                "affected_files:",
                "  - local_overlays/references/security_sources.md",
                "risk: low",
                "evidence:",
                "  - official source checked 2026-06-19",
                f"evidence_url: {evidence_url}",
                "monitor_root: https://example.com/security/",
                "root_decision: monitor",
                "required_verification:",
                "  - uv run python -B scripts/check_reference_freshness.py",
            ]

        def review_header(accepted: int) -> list[str]:
            return [
                "chain_id: source-2026-06-19-0930",
                "stage: review",
                "stage_run_id: review-2026-06-19-0930",
                "logical_date: 2026-06-19",
                "run_slot: 0930",
                "monitor_scope: framework-sources",
                "monitor_scope_sha256: 5b619bc978d06cba5277f7846faa48625e0ec70ba43216c35213bb6cd7f62a38",
                "model_route: quality_first",
                "model_label: fixture-model",
                "reasoning_effort: high",
                "execution_mode: standard",
                "timezone: Europe/Vienna",
                "status: pass",
                "external_reviewer_status: not_needed",
                "external_reviewer_packet_scope: none",
                f"input_monitor_sha256: {digest}",
                f"accepted_findings: {accepted}",
                "manual_findings: 0",
                "rejected_findings: 0",
                "",
                "## Accepted Findings",
                "",
            ]

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            negative = root / "negative.md"
            extra = root / "extra.md"
            empty = root / "empty.md"
            malformed = root / "malformed.md"
            manual_mismatch = root / "manual-mismatch.md"
            negative.write_text("\n".join(review_header(-1)), encoding="utf-8")
            extra.write_text("\n".join(review_header(0) + full_block()), encoding="utf-8")
            empty.write_text("\n".join(review_header(1) + full_block("")), encoding="utf-8")
            malformed.write_text(
                "\n".join(review_header(1) + full_block("https://example.com:abc/security")),
                encoding="utf-8",
            )
            manual_mismatch.write_text(
                "\n".join(
                    [
                        "chain_id: source-2026-06-19-0930",
                        "stage: review",
                        "stage_run_id: review-2026-06-19-0930",
                        "logical_date: 2026-06-19",
                        "run_slot: 0930",
                        "monitor_scope: framework-sources",
                        "monitor_scope_sha256: 5b619bc978d06cba5277f7846faa48625e0ec70ba43216c35213bb6cd7f62a38",
                        "model_route: quality_first",
                        "model_label: fixture-model",
                        "reasoning_effort: high",
                        "execution_mode: standard",
                        "timezone: Europe/Vienna",
                        "status: pass",
                        "external_reviewer_status: not_needed",
                        "external_reviewer_packet_scope: none",
                        f"input_monitor_sha256: {digest}",
                        "accepted_findings: 1",
                        "manual_findings: 0",
                        "rejected_findings: 0",
                        "",
                        "## Accepted Findings",
                        "",
                        *full_block(apply_mode="manual"),
                    ]
                ),
                encoding="utf-8",
            )

            negative_report = validate_artifact(negative, "review")
            extra_report = validate_artifact(extra, "review")
            empty_report = validate_artifact(empty, "review")
            malformed_report = validate_artifact(malformed, "review")
            manual_report = validate_artifact(manual_mismatch, "review")

        self.assertTrue(
            any("accepted_findings must be a non-negative integer" in error for error in string_items(negative_report["errors"]))
        )
        self.assertTrue(
            any(
                "accepted_findings is 0, but 1 machine-readable finding block" in error
                for error in string_items(extra_report["errors"])
            )
        )
        self.assertTrue(
            any("empty field: evidence_url" in error for error in string_items(empty_report["errors"]))
        )
        self.assertTrue(
            any("malformed external URL" in error for error in string_items(malformed_report["errors"]))
        )
        self.assertTrue(
            any(
                "manual_findings is 0, but 1 accepted finding block" in error
                for error in string_items(manual_report["errors"])
            )
        )

    def test_source_chain_artifact_lint_prepares_decision_hashes_without_writing(self) -> None:
        decision_text = "\n".join(
            [
                "## Accepted Findings",
                "",
                "finding_id: source-entry-1",
                "finding_hash: unavailable",
                "classification: accept-source-entry",
                "apply_mode: auto",
                "change_class: source-entry-content",
                "source_tier: [official-doc]",
                "source_role: evidence-url",
                "quality_gate: primary_verified",
                "durable_abstraction: A verified source change should update the bounded source record.",
                "applicability: Applies only to the checked source family and approved registry entry.",
                "rejected_source_specifics: Product wording and source workflow details are not adopted.",
                "affected_files:",
                "  - docs/source-record.md",
                "risk: low",
                "evidence_url: https://example.com/releases/item-1",
                "monitor_root: https://example.com/releases/",
                "root_decision: monitor",
                "evidence:",
                "  - Primary release record verified for the bounded claim.",
                "required_verification:",
                "  - Re-run the source-record semantic check.",
                "",
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            valid = root / "review.md"
            valid.write_text(decision_text, encoding="utf-8")
            original_bytes = valid.read_bytes()

            report = source_chain_artifact_lint.prepare_decision_hashes(valid)
            first_stdout = io.StringIO()
            with mock.patch("sys.stdout", first_stdout):
                first_exit = source_chain_artifact_lint.main(
                    ["--prepare-decision-hashes", str(valid)]
                )
            second_stdout = io.StringIO()
            with mock.patch("sys.stdout", second_stdout):
                second_exit = source_chain_artifact_lint.main(
                    ["--prepare-decision-hashes", "--stage", "review", str(valid)]
                )

            incomplete = root / "incomplete.md"
            incomplete.write_text(
                decision_text.replace(
                    "applicability: Applies only to the checked source family and approved registry entry.\n",
                    "",
                ),
                encoding="utf-8",
            )
            empty = root / "empty.md"
            empty.write_text(
                decision_text.replace(
                    "durable_abstraction: A verified source change should update the bounded source record.",
                    "durable_abstraction:",
                ),
                encoding="utf-8",
            )
            duplicate = root / "duplicate.md"
            duplicate.write_text(
                decision_text.replace("risk: low", "risk: low\nrisk: high"),
                encoding="utf-8",
            )
            incomplete_report = source_chain_artifact_lint.prepare_decision_hashes(incomplete)
            empty_report = source_chain_artifact_lint.prepare_decision_hashes(empty)
            duplicate_report = source_chain_artifact_lint.prepare_decision_hashes(duplicate)
            after_bytes = valid.read_bytes()

        prepared = dict_items(report["prepared_decision_hashes"])
        self.assertEqual([], report["errors"])
        self.assertEqual(1, len(prepared))
        self.assertEqual("source-entry-1", prepared[0]["finding_id"])
        self.assertRegex(str(prepared[0]["finding_hash"]), r"^[0-9a-f]{64}$")
        self.assertNotIn(
            "finding_hash",
            cast(dict[str, object], prepared[0]["canonical_payload"]),
        )
        self.assertEqual(original_bytes, after_bytes)
        self.assertEqual(0, first_exit)
        self.assertEqual(0, second_exit)
        self.assertEqual(first_stdout.getvalue(), second_stdout.getvalue())
        self.assertIn('"mode": "prepare_decision_hashes"', first_stdout.getvalue())
        self.assertTrue(
            any(
                "missing fields: applicability" in error
                for error in string_items(incomplete_report["errors"])
            )
        )
        self.assertTrue(
            any(
                "has empty field: durable_abstraction" in error
                for error in string_items(empty_report["errors"])
            )
        )
        self.assertTrue(
            any(
                "duplicates field risk" in error
                for error in string_items(duplicate_report["errors"])
            )
        )

    def test_source_chain_artifact_lint_rejects_missing_empty_or_placeholder_abstraction_fields(self) -> None:
        digest = "b" * 64
        abstraction_defaults = {
            "durable_abstraction": "Existing source metadata changed and should update the private source entry.",
            "applicability": "Applies only to the checked source family and its approved monitor root.",
            "rejected_source_specifics": "No tool commands, implementation details, or doctrine changes are adopted.",
        }

        def full_block(**overrides: str) -> list[str]:
            values = abstraction_defaults | overrides
            return [
                "finding_id: accepted-1",
                f"finding_hash: {digest}",
                "classification: accept-source-entry",
                "apply_mode: auto",
                "change_class: source-entry-content",
                "source_tier: [official-doc]",
                "source_role: evidence-url",
                "quality_gate: primary_verified",
                f"durable_abstraction: {values['durable_abstraction']}",
                f"applicability: {values['applicability']}",
                f"rejected_source_specifics: {values['rejected_source_specifics']}",
                "affected_files:",
                "  - local_overlays/references/security_sources.md",
                "risk: low",
                "evidence:",
                "  - official source checked 2026-06-19",
                "evidence_url: https://example.com/security/advisory",
                "monitor_root: https://example.com/security/",
                "root_decision: monitor",
                "required_verification:",
                "  - uv run python -B scripts/check_reference_freshness.py",
            ]

        def review_header() -> list[str]:
            return [
                "chain_id: source-2026-06-19-0930",
                "stage: review",
                "stage_run_id: review-2026-06-19-0930",
                "logical_date: 2026-06-19",
                "run_slot: 0930",
                "monitor_scope: framework-sources",
                "monitor_scope_sha256: 5b619bc978d06cba5277f7846faa48625e0ec70ba43216c35213bb6cd7f62a38",
                "model_route: quality_first",
                "model_label: fixture-model",
                "reasoning_effort: high",
                "execution_mode: standard",
                "timezone: Europe/Vienna",
                "status: pass",
                "external_reviewer_status: not_needed",
                "external_reviewer_packet_scope: none",
                f"input_monitor_sha256: {digest}",
                "accepted_findings: 1",
                "manual_findings: 0",
                "rejected_findings: 0",
                "",
                "## Accepted Findings",
                "",
            ]

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            reports: dict[tuple[str, str], dict[str, object]] = {}
            for field_name in abstraction_defaults:
                missing_path = root / f"missing-{field_name}.md"
                empty_path = root / f"empty-{field_name}.md"
                placeholder_path = root / f"placeholder-{field_name}.md"
                missing_lines = [
                    line for line in full_block() if not line.startswith(f"{field_name}:")
                ]
                missing_path.write_text("\n".join(review_header() + missing_lines), encoding="utf-8")
                empty_path.write_text(
                    "\n".join(review_header() + full_block(**{field_name: ""})),
                    encoding="utf-8",
                )
                placeholder_path.write_text(
                    "\n".join(review_header() + full_block(**{field_name: f"<{field_name}>"})),
                    encoding="utf-8",
                )
                reports[(field_name, "missing")] = validate_artifact(missing_path, "review")
                reports[(field_name, "empty")] = validate_artifact(empty_path, "review")
                reports[(field_name, "placeholder")] = validate_artifact(
                    placeholder_path, "review"
                )

        for field_name in ("durable_abstraction", "applicability", "rejected_source_specifics"):
            with self.subTest(field_name=field_name, mutation="missing"):
                self.assertTrue(
                    any(
                        f"missing fields: {field_name}" in error
                        for error in string_items(reports[(field_name, "missing")]["errors"])
                    )
                )
            with self.subTest(field_name=field_name, mutation="empty"):
                self.assertTrue(
                    any(
                        f"empty field: {field_name}" in error
                        for error in string_items(reports[(field_name, "empty")]["errors"])
                    )
                )
            with self.subTest(field_name=field_name, mutation="placeholder"):
                self.assertTrue(
                    any(
                        f"placeholder field: {field_name}" in error
                        for error in string_items(reports[(field_name, "placeholder")]["errors"])
                    )
                )

    def test_source_chain_artifact_lint_accepts_nested_monitor_apply_and_assurance_headers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            monitor = root / "review_artifacts" / "source_monitor" / "2026-06-19_0930.md"
            review = root / "review_artifacts" / "source_review" / "2026-06-19_0930.md"
            apply = root / "review_artifacts" / "source_apply" / "2026-06-19_0930.md"
            assurance = root / "review_artifacts" / "automation_assurance" / "2026-06-19_0930.md"
            packet_bundle = root / "review_artifacts" / "external_review_packets" / "source-2026-06-19-0930"
            for artifact in (monitor, review, apply, assurance):
                artifact.parent.mkdir(parents=True, exist_ok=True)
            packet_manifest, packet_sha = write_valid_review_packet_bundle(
                packet_bundle,
                scope="accepted-source-entry-1",
                approval_source="active-thread approval",
                redaction="leak scan passed; public source metadata only",
            )
            packet_manifest_ref = packet_manifest.relative_to(root).as_posix()
            packet_manifest_hash = source_chain_artifact_lint.file_sha256(packet_manifest)
            monitor.write_text(
                monitor_artifact_fixture(),
                encoding="utf-8",
            )
            monitor_hash = source_chain_artifact_lint.file_sha256(monitor)
            review.write_text(
                review_artifact_fixture(input_monitor_sha256=monitor_hash),
                encoding="utf-8",
            )
            review_hash = source_chain_artifact_lint.file_sha256(review)
            apply.write_text(
                apply_artifact_fixture(
                    external_reviewer_status="used",
                    external_reviewer_packet_scope="accepted-source-entry-1",
                    external_reviewer_approval_source="active-thread approval",
                    external_reviewer_packet_sha256=packet_sha,
                    external_reviewer_packet_manifest=packet_manifest_ref,
                    external_reviewer_packet_manifest_sha256=packet_manifest_hash,
                    external_reviewer_redaction="leak scan passed; public source metadata only",
                    input_review_sha256=review_hash,
                ),
                encoding="utf-8",
            )
            apply_hash = source_chain_artifact_lint.file_sha256(apply)
            assurance.write_text(
                assurance_artifact_fixture(
                    input_monitor_sha256=monitor_hash,
                    input_review_sha256=review_hash,
                    input_apply_sha256=apply_hash,
                ),
                encoding="utf-8",
            )

            monitor_report = validate_artifact(monitor, "monitor")
            review_report = validate_artifact(review, "review")
            apply_report = validate_artifact(apply, "apply")
            assurance_report = validate_artifact(assurance, "assurance")
            apply.write_text(
                apply.read_text(encoding="utf-8").replace(
                    "commit: def5678",
                    "commit: def5678; fed9012",
                ),
                encoding="utf-8",
            )
            multi_commit_apply_hash = source_chain_artifact_lint.file_sha256(apply)
            assurance.write_text(
                assurance.read_text(encoding="utf-8").replace(
                    f"input_apply_sha256: {apply_hash}",
                    f"input_apply_sha256: {multi_commit_apply_hash}",
                ).replace(
                    "latest_commit: def5678",
                    "latest_commit: fed9012",
                ),
                encoding="utf-8",
            )
            multi_commit_assurance_report = validate_artifact(assurance, "assurance")
            assurance.write_text(
                assurance.read_text(encoding="utf-8").replace(
                    "latest_commit: fed9012",
                    "latest_commit: none",
                ),
                encoding="utf-8",
            )
            assurance_mismatch_report = validate_artifact(assurance, "assurance")

        self.assertEqual([], monitor_report["errors"])
        self.assertEqual([], review_report["errors"])
        self.assertEqual([], apply_report["errors"])
        self.assertEqual([], assurance_report["errors"])
        self.assertEqual([], multi_commit_assurance_report["errors"])
        self.assertTrue(
            any(
                "latest_commit must match resolved apply commit" in error
                for error in string_items(assurance_mismatch_report["errors"])
            )
        )

    def test_source_chain_artifact_lint_accepts_attempt_id_utc_previous_day_for_local_date(self) -> None:
        digest = "d" * 64
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            monitor = root / "review_artifacts" / "source_monitor" / "2026-06-19_0030.md"
            monitor.parent.mkdir(parents=True)
            monitor.write_text(
                "\n".join(
                    [
                        "artifact_schema_version: 6",
                        "chain_id: source-2026-06-19-0030",
                        "stage: monitor",
                        "stage_run_id: monitor-2026-06-19-0030",
                        "attempt_id: monitor-2026-06-18T223000Z-abc123",
                        "logical_date: 2026-06-19",
                        "run_slot: 0030",
                        "monitor_scope: framework-sources",
                        "monitor_scope_sha256: 5b619bc978d06cba5277f7846faa48625e0ec70ba43216c35213bb6cd7f62a38",
                        "model_route: quality_first",
                        "model_label: fixture-model",
                        "reasoning_effort: high",
                        "execution_mode: standard",
                        "timezone: Europe/Vienna",
                        "started_at_utc: 2026-06-18T22:30:00Z",
                        "completed_at_utc: 2026-06-18T22:45:00Z",
                        "status: pass",
                        "source_status: pass",
                        "workspace_status: clean",
                        "external_reviewer_status: not_needed",
                        "external_reviewer_packet_scope: none",
                        "inaccessible_source_count: 0",
                        "unresolved_inaccessible_source_count: 0",
                        "source_root_coverage_count: 0",
                        "source_registry_files:",
                        "  - path: local_overlays/references/security_sources.md",
                        f"    sha256: {digest}",
                        "policy_files:",
                        "  - path: runtime/operative_charter.md",
                        f"    sha256: {digest}",
                        "",
                        "# Monitor",
                    ]
                ),
                encoding="utf-8",
            )

            report = validate_artifact(monitor, "monitor")
            nested = (
                root
                / "review_artifacts"
                / "alternate"
                / "source_monitor"
                / "2026-06-19_0030.md"
            )
            nested.parent.mkdir(parents=True)
            nested.write_text(monitor.read_text(encoding="utf-8"), encoding="utf-8")
            nested_report = validate_artifact(nested, "monitor")

        self.assertEqual([], report["errors"])
        self.assertTrue(
            any(
                "artifact path must end with source_monitor/2026-06-19_0030.md"
                in error
                for error in string_items(nested_report["errors"])
            ),
            nested_report,
        )

    def test_source_chain_artifact_lint_rejects_nested_artifact_tree_forks(self) -> None:
        monitor_suffix = source_chain_artifact_lint.CANONICAL_ARTIFACT_SUFFIXES[
            "monitor"
        ].format(logical_date="2026-06-19", run_slot="0930")
        nested_monitor_ref = "/".join(
            ("review_artifacts", "alternate", "review_artifacts", monitor_suffix)
        )
        traversal_monitor_ref = "/".join(
            ("review_artifacts", "alternate", "..", monitor_suffix)
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            nested_monitor = root / nested_monitor_ref
            nested_monitor.parent.mkdir(parents=True)
            nested_monitor_text = monitor_artifact_fixture()
            nested_monitor.write_text(nested_monitor_text, encoding="utf-8")
            nested_monitor_report = validate_artifact(
                nested_monitor,
                "monitor",
                artifact_bytes=nested_monitor_text.encode("utf-8"),
            )
            traversal_monitor = root / traversal_monitor_ref
            traversal_monitor_report = validate_artifact(
                traversal_monitor,
                "monitor",
                artifact_bytes=nested_monitor_text.encode("utf-8"),
            )
            alias_root = root / "artifact-alias"
            alias_root.symlink_to(root, target_is_directory=True)
            symlink_monitor = (
                alias_root
                / "review_artifacts"
                / "source_monitor"
                / "2026-06-19_0930.md"
            )
            symlink_monitor_report = validate_artifact(
                symlink_monitor,
                "monitor",
                project_root=root,
                artifact_bytes=nested_monitor_text.encode("utf-8"),
            )

            review = (
                root
                / "review_artifacts"
                / "source_review"
                / "2026-06-19_0930.md"
            )
            nested_reference_text = review_artifact_fixture(
                input_monitor_artifact=nested_monitor_ref,
                input_monitor_sha256=source_chain_artifact_lint.file_sha256(
                    nested_monitor
                ),
            )
            traversal_reference_text = review_artifact_fixture(
                input_monitor_artifact=traversal_monitor_ref,
            )
            symlink_target = root / "alternate-monitor"
            symlink_target.mkdir()
            (symlink_target / "2026-06-19_0930.md").write_text(
                nested_monitor_text,
                encoding="utf-8",
            )
            (root / "review_artifacts" / "source_monitor").symlink_to(
                symlink_target,
                target_is_directory=True,
            )
            symlink_reference_text = review_artifact_fixture()
            with mock.patch.object(
                source_chain_artifact_lint,
                "read_artifact_bytes",
                side_effect=AssertionError("noncanonical predecessor must not be read"),
            ) as artifact_read:
                predecessor_reports = {
                    "nested": validate_artifact(
                        review,
                        "review",
                        artifact_bytes=nested_reference_text.encode("utf-8"),
                    ),
                    "traversal": validate_artifact(
                        review,
                        "review",
                        artifact_bytes=traversal_reference_text.encode("utf-8"),
                    ),
                    "symlink": validate_artifact(
                        review,
                        "review",
                        artifact_bytes=symlink_reference_text.encode("utf-8"),
                    ),
                }

        artifact_read.assert_not_called()
        self.assertTrue(
            any(
                "selected top-level review_artifacts root" in error
                for error in string_items(nested_monitor_report["errors"])
            ),
            nested_monitor_report,
        )
        self.assertTrue(
            any(
                "without traversal or nested artifact trees" in error
                for error in string_items(traversal_monitor_report["errors"])
            ),
            traversal_monitor_report,
        )
        self.assertTrue(
            any(
                "artifact path must not use symlink aliases" in error
                for error in string_items(symlink_monitor_report["errors"])
            ),
            symlink_monitor_report,
        )
        self.assertIn(
            "input_monitor_artifact must not contain nested review_artifacts trees",
            string_items(predecessor_reports["nested"]["errors"]),
        )
        self.assertTrue(
            any(
                "must not contain traversal components" in error
                for error in string_items(predecessor_reports["traversal"]["errors"])
            ),
            predecessor_reports["traversal"],
        )
        self.assertTrue(
            any(
                "must not include symlink components" in error
                for error in string_items(predecessor_reports["symlink"]["errors"])
            ),
            predecessor_reports["symlink"],
        )

    def test_source_chain_artifact_path_is_relative_to_explicit_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            unrelated_named_ancestor = Path(temp_dir) / "review_artifacts"
            project_root = unrelated_named_ancestor / "selected-project"
            artifact = (
                project_root
                / "review_artifacts"
                / "source_monitor"
                / "2026-06-19_0930.md"
            )
            artifact.parent.mkdir(parents=True)
            artifact.write_text(monitor_artifact_fixture(), encoding="utf-8")

            report = validate_artifact(
                artifact,
                "monitor",
                project_root=project_root,
            )
            relative_report = source_chain_artifact_lint.validate_artifact(
                Path("review_artifacts/source_monitor/2026-06-19_0930.md"),
                "monitor",
                project_root=project_root,
            )

        self.assertEqual([], report["errors"])
        self.assertEqual([], relative_report["errors"])

    def test_source_chain_artifact_scope_rejects_before_any_artifact_read(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            project_root = temp_root / "selected-project"
            artifacts_root = project_root / "review_artifacts"
            artifacts_root.mkdir(parents=True)
            outside = temp_root / "outside.md"
            traversal = (
                artifacts_root
                / "alternate"
                / ".."
                / "source_monitor"
                / "2026-06-19_0930.md"
            )
            outside_alias_target = temp_root / "outside-artifacts"
            outside_alias_target.mkdir()
            (artifacts_root / "alias").symlink_to(
                outside_alias_target,
                target_is_directory=True,
            )
            symlinked = artifacts_root / "alias" / "2026-06-19_0930.md"

            with mock.patch.object(
                source_chain_artifact_lint,
                "read_artifact_bytes",
                side_effect=AssertionError("out-of-scope artifact must not be read"),
            ) as artifact_read:
                reports = {
                    "outside": source_chain_artifact_lint.validate_artifact(
                        outside,
                        "monitor",
                        project_root=project_root,
                    ),
                    "traversal": source_chain_artifact_lint.validate_artifact(
                        traversal,
                        "monitor",
                        project_root=project_root,
                    ),
                    "symlink": source_chain_artifact_lint.validate_artifact(
                        symlinked,
                        "monitor",
                        project_root=project_root,
                    ),
                }

        artifact_read.assert_not_called()
        self.assertTrue(
            any(
                "explicitly selected project root" in error
                for error in string_items(reports["outside"]["errors"])
            ),
            reports["outside"],
        )
        self.assertTrue(
            any(
                "without traversal" in error
                for error in string_items(reports["traversal"]["errors"])
            ),
            reports["traversal"],
        )
        self.assertTrue(
            any(
                "must not use symlink aliases" in error
                for error in string_items(reports["symlink"]["errors"])
            ),
            reports["symlink"],
        )

    def test_source_chain_artifact_lint_rejects_success_after_blocked_predecessor(self) -> None:
        digest = "b" * 64
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            monitor = root / "review_artifacts" / "source_monitor" / "2026-06-19_0930.md"
            review = root / "review_artifacts" / "source_review" / "2026-06-19_0930.md"
            monitor.parent.mkdir(parents=True)
            review.parent.mkdir(parents=True)
            monitor.write_text(
                "\n".join(
                    [
                        "artifact_schema_version: 6",
                        "chain_id: source-2026-06-19-0930",
                        "stage: monitor",
                        "stage_run_id: monitor-2026-06-19-0930",
                        "attempt_id: monitor-2026-06-19T073000Z-abc123",
                        "logical_date: 2026-06-19",
                        "run_slot: 0930",
                        "monitor_scope: framework-sources",
                        "monitor_scope_sha256: 5b619bc978d06cba5277f7846faa48625e0ec70ba43216c35213bb6cd7f62a38",
                        "model_route: quality_first",
                        "model_label: fixture-model",
                        "reasoning_effort: high",
                        "execution_mode: standard",
                        "timezone: Europe/Vienna",
                        "started_at_utc: 2026-06-19T07:30:00Z",
                        "completed_at_utc: 2026-06-19T07:45:00Z",
                        "status: blocked",
                        "source_status: blocked",
                        "workspace_status: clean",
                        "external_reviewer_status: blocked",
                        "external_reviewer_packet_scope: none",
                        "inaccessible_source_count: 0",
                        "unresolved_inaccessible_source_count: 0",
                        "source_root_coverage_count: 0",
                        "source_registry_files:",
                        "  - path: local_overlays/references/security_sources.md",
                        f"    sha256: {digest}",
                        "policy_files:",
                        "  - path: runtime/operative_charter.md",
                        f"    sha256: {digest}",
                        "",
                        "# Monitor",
                    ]
                ),
                encoding="utf-8",
            )
            monitor_hash = source_chain_artifact_lint.file_sha256(monitor)
            review.write_text(
                "\n".join(
                    [
                        "artifact_schema_version: 6",
                        "chain_id: source-2026-06-19-0930",
                        "stage: review",
                        "stage_run_id: review-2026-06-19-0930",
                        "attempt_id: review-2026-06-19T083000Z-abc123",
                        "logical_date: 2026-06-19",
                        "run_slot: 0930",
                        "monitor_scope: framework-sources",
                        "monitor_scope_sha256: 5b619bc978d06cba5277f7846faa48625e0ec70ba43216c35213bb6cd7f62a38",
                        "model_route: quality_first",
                        "model_label: fixture-model",
                        "reasoning_effort: high",
                        "execution_mode: standard",
                        "timezone: Europe/Vienna",
                        "started_at_utc: 2026-06-19T08:30:00Z",
                        "completed_at_utc: 2026-06-19T08:45:00Z",
                        "status: pass",
                        "external_reviewer_status: not_needed",
                        "external_reviewer_packet_scope: none",
                        "input_monitor_state: resolved",
                        "input_monitor_artifact: review_artifacts/source_monitor/2026-06-19_0930.md",
                        "input_monitor_stage_run_id: monitor-2026-06-19-0930",
                        "input_monitor_attempt_id: monitor-2026-06-19T073000Z-abc123",
                        f"input_monitor_sha256: {monitor_hash}",
                        "inaccessible_source_count: 0",
                        "unresolved_inaccessible_source_count: 0",
                        "accepted_findings: 0",
                        "manual_findings: 0",
                        "rejected_findings: 0",
                        "",
                        "# Review",
                    ]
                ),
                encoding="utf-8",
            )

            report = validate_artifact(review, "review")

        errors = string_items(report["errors"])
        self.assertTrue(any("status must be successful for successful review" in error for error in errors))
        self.assertTrue(any("source_status must be successful for successful review" in error for error in errors))

    def test_source_chain_artifact_lint_rejects_placeholder_apply_authority_on_success(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            apply = root / "review_artifacts" / "source_apply" / "2026-06-19_0930.md"
            apply.parent.mkdir(parents=True)
            apply.write_text(
                apply_artifact_fixture(
                    authority_grant="none",
                    authority_scope="unavailable",
                    authority_source="to be confirmed",
                    input_review_state="missing",
                    input_review_artifact="unavailable",
                    input_review_stage_run_id="unavailable",
                    input_review_attempt_id="unavailable",
                    input_review_sha256="unavailable",
                    changed_files="none",
                    commit="none",
                ),
                encoding="utf-8",
            )

            report = validate_artifact(apply, "apply")

        errors = string_items(report["errors"])
        self.assertTrue(any("authority_grant must record an actual authority value" in error for error in errors))
        self.assertTrue(any("authority_scope must record an actual authority value" in error for error in errors))
        self.assertTrue(any("authority_source must record an actual authority value" in error for error in errors))
        self.assertTrue(any("commit must record the created commit" in error for error in errors))
        self.assertTrue(any("changed_files must list at least one changed file" in error for error in errors))

    def test_source_chain_artifact_lint_requires_external_reviewer_packet_evidence_when_used(self) -> None:
        errors: list[str] = []
        source_chain_artifact_lint.validate_external_reviewer_packet(
            Path("."),
            {
                "external_reviewer_status": "used",
                "external_reviewer_packet_scope": "none",
                "external_reviewer_approval_source": "none",
                "external_reviewer_packet_sha256": "unavailable",
                "external_reviewer_packet_manifest": "none",
                "external_reviewer_packet_manifest_sha256": "unavailable",
                "external_reviewer_redaction": "none",
            },
            errors,
        )

        self.assertTrue(any("external_reviewer_packet_scope must name" in error for error in errors), errors)
        self.assertTrue(any("external_reviewer_approval_source must record" in error for error in errors), errors)
        self.assertTrue(any("external_reviewer_packet_sha256 must be a SHA-256" in error for error in errors), errors)
        self.assertTrue(any("external_reviewer_packet_manifest must name" in error for error in errors), errors)
        self.assertTrue(any("external_reviewer_packet_manifest_sha256 must be a SHA-256" in error for error in errors), errors)
        self.assertTrue(any("external_reviewer_redaction must record" in error for error in errors), errors)

        skipped_scope_errors: list[str] = []
        source_chain_artifact_lint.validate_external_reviewer_packet(
            Path("."),
            {
                "external_reviewer_status": "not_needed",
                "external_reviewer_packet_scope": "private diff packet",
                "external_reviewer_packet_manifest": "review_artifacts/external_review_packets/stale.json",
            },
            skipped_scope_errors,
        )
        self.assertTrue(
            any("external_reviewer_packet_scope must be none" in error for error in skipped_scope_errors),
            skipped_scope_errors,
        )
        self.assertTrue(
            any("external_reviewer_packet_manifest must be none or unavailable" in error for error in skipped_scope_errors),
            skipped_scope_errors,
        )

    def test_source_chain_artifact_lint_verifies_external_reviewer_packet_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            current = root / "review_artifacts" / "source_review" / "2026-06-19_0930.md"
            current.parent.mkdir(parents=True)
            current.write_text("# Review\n", encoding="utf-8")
            manifest, packet_sha = write_valid_review_packet_bundle(
                root / "review_artifacts" / "external_review_packets" / "source-2026-06-19-0930",
                scope="accepted-source-entry-1",
                approval_source="active-thread approval",
                redaction="leak scan passed; approved packet only",
                retain_ephemeral_item=True,
            )
            manifest_ref = manifest.relative_to(root).as_posix()
            manifest_sha = source_chain_artifact_lint.file_sha256(manifest)
            base_header = {
                "external_reviewer_status": "used",
                "external_reviewer_packet_scope": "accepted-source-entry-1",
                "external_reviewer_approval_source": "active-thread approval",
                "external_reviewer_packet_sha256": packet_sha,
                "external_reviewer_packet_manifest": manifest_ref,
                "external_reviewer_packet_manifest_sha256": manifest_sha,
                "external_reviewer_redaction": "leak scan passed; approved packet only",
            }

            uncleaned_errors: list[str] = []
            source_chain_artifact_lint.validate_external_reviewer_packet(
                root,
                base_header,
                uncleaned_errors,
            )

            missing_header = dict(base_header)
            missing_header["external_reviewer_packet_manifest"] = (
                "review_artifacts/external_review_packets/missing.json"
            )
            missing_errors: list[str] = []
            source_chain_artifact_lint.validate_external_reviewer_packet(root, missing_header, missing_errors)

            mismatch_header = dict(base_header)
            mismatch_header["external_reviewer_packet_manifest_sha256"] = "5" * 64
            mismatch_errors: list[str] = []
            source_chain_artifact_lint.validate_external_reviewer_packet(root, mismatch_header, mismatch_errors)

            unsafe_header = dict(base_header)
            unsafe_header["external_reviewer_packet_manifest"] = "../external_review_packets/source-2026-06-19-0930.json"
            unsafe_errors: list[str] = []
            source_chain_artifact_lint.validate_external_reviewer_packet(root, unsafe_header, unsafe_errors)

            item_path = manifest.parent / "packet" / "context.md"
            item_bytes = item_path.read_bytes()
            item_path.unlink()
            cleaned_errors: list[str] = []
            source_chain_artifact_lint.validate_external_reviewer_packet(
                root, base_header, cleaned_errors
            )
            item_path.write_text("changed after validation\n", encoding="utf-8")
            lingering_cleanup_errors: list[str] = []
            source_chain_artifact_lint.validate_external_reviewer_packet(
                root, base_header, lingering_cleanup_errors
            )
            output_path = manifest.parent / "evidence" / "review-output.json"
            output_bytes = output_path.read_bytes()
            output_path.unlink()
            missing_output_errors: list[str] = []
            source_chain_artifact_lint.validate_external_reviewer_packet(
                root, base_header, missing_output_errors
            )
            output_path.write_bytes(output_bytes)

            duplicate_manifest, duplicate_packet_sha = write_valid_review_packet_bundle(
                root / "review_artifacts" / "external_review_packets" / "duplicate",
                scope="accepted-source-entry-1",
                approval_source="active-thread approval",
                redaction="leak scan passed; approved packet only",
            )
            duplicate_text = duplicate_manifest.read_text(encoding="utf-8")
            duplicate_manifest.write_text(
                '{"schema_version":2,' + duplicate_text.lstrip()[1:],
                encoding="utf-8",
            )
            duplicate_header = dict(base_header)
            duplicate_header.update({
                "external_reviewer_packet_sha256": duplicate_packet_sha,
                "external_reviewer_packet_manifest": duplicate_manifest.relative_to(root).as_posix(),
                "external_reviewer_packet_manifest_sha256": source_chain_artifact_lint.file_sha256(duplicate_manifest),
            })
            duplicate_errors: list[str] = []
            source_chain_artifact_lint.validate_external_reviewer_packet(
                root, duplicate_header, duplicate_errors
            )

            nonfinite_manifest, nonfinite_packet_sha = write_valid_review_packet_bundle(
                root / "review_artifacts" / "external_review_packets" / "nonfinite",
                scope="accepted-source-entry-1",
                approval_source="active-thread approval",
                redaction="leak scan passed; approved packet only",
            )
            nonfinite_manifest.write_text(
                nonfinite_manifest.read_text(encoding="utf-8").replace(
                    '"observed_latency_seconds": 240',
                    '"observed_latency_seconds": NaN',
                ),
                encoding="utf-8",
            )
            nonfinite_header = dict(base_header)
            nonfinite_header.update({
                "external_reviewer_packet_sha256": nonfinite_packet_sha,
                "external_reviewer_packet_manifest": nonfinite_manifest.relative_to(root).as_posix(),
                "external_reviewer_packet_manifest_sha256": source_chain_artifact_lint.file_sha256(nonfinite_manifest),
            })
            nonfinite_errors: list[str] = []
            source_chain_artifact_lint.validate_external_reviewer_packet(
                root, nonfinite_header, nonfinite_errors
            )

            receipt_manifest, receipt_packet_sha = write_valid_review_packet_bundle(
                root / "review_artifacts" / "external_review_packets" / "receipt-tamper",
                scope="accepted-source-entry-1",
                approval_source="active-thread approval",
                redaction="leak scan passed; approved packet only",
            )
            receipt_data = json.loads(receipt_manifest.read_text(encoding="utf-8"))
            receipt_data["validation_receipts"]["pre_submission"]["inventory_sha256"] = "0" * 64
            receipt_manifest.write_text(json.dumps(receipt_data, indent=2) + "\n", encoding="utf-8")
            receipt_header = dict(base_header)
            receipt_header.update({
                "external_reviewer_packet_sha256": receipt_packet_sha,
                "external_reviewer_packet_manifest": receipt_manifest.relative_to(root).as_posix(),
                "external_reviewer_packet_manifest_sha256": source_chain_artifact_lint.file_sha256(receipt_manifest),
            })
            receipt_errors: list[str] = []
            source_chain_artifact_lint.validate_external_reviewer_packet(
                root, receipt_header, receipt_errors
            )

            returned_manifest, returned_packet_sha = write_valid_review_packet_bundle(
                root / "review_artifacts" / "external_review_packets" / "returned-cleanup",
                scope="accepted-source-entry-1",
                approval_source="active-thread approval",
                redaction="leak scan passed; approved packet only",
            )
            returned_data = json.loads(returned_manifest.read_text(encoding="utf-8"))
            returned_data["lifecycle"]["stage"] = "returned"
            returned_data["closeout"].update({
                "status": "not_started",
                "performed_at": None,
                "checks": [],
                "cleanup_status": "pending",
            })
            returned_manifest.write_text(json.dumps(returned_data, indent=2) + "\n", encoding="utf-8")
            returned_header = dict(base_header)
            returned_header.update({
                "external_reviewer_packet_sha256": returned_packet_sha,
                "external_reviewer_packet_manifest": returned_manifest.relative_to(root).as_posix(),
                "external_reviewer_packet_manifest_sha256": source_chain_artifact_lint.file_sha256(returned_manifest),
            })
            returned_errors: list[str] = []
            source_chain_artifact_lint.validate_external_reviewer_packet(
                root, returned_header, returned_errors
            )

            live_manifest, _live_packet_sha = write_valid_review_packet_bundle(
                root / "review_artifacts" / "external_review_packets" / "live-byte-mutation",
                scope="accepted-source-entry-1",
                approval_source="active-thread approval",
                redaction="leak scan passed; approved packet only",
                retain_ephemeral_item=True,
            )
            live_data = json.loads(live_manifest.read_text(encoding="utf-8"))
            live_data["lifecycle"]["stage"] = "returned"
            live_data["verification"].update({
                "findings_classified": False,
                "performed_at": None,
                "verification_record_sha256": None,
            })
            live_data["closeout"].update({
                "status": "not_started",
                "performed_at": None,
                "checks": [],
                "cleanup_status": "pending",
            })
            live_manifest.write_text(
                json.dumps(live_data, indent=2) + "\n",
                encoding="utf-8",
            )
            (live_manifest.parent / "packet" / "context.md").write_text(
                "changed before cleanup\n",
                encoding="utf-8",
            )
            live_digest_errors = review_packet_contract.portable_manifest_errors(
                live_data,
                live_manifest,
            )

            item_path.unlink()

        self.assertTrue(
            any(
                "ephemeral disclosed file remains after completed cleanup" in error
                for error in uncleaned_errors
            ),
            uncleaned_errors,
        )
        self.assertIn("external_reviewer_packet_manifest must exist under the same review_artifacts tree", missing_errors)
        self.assertIn("external_reviewer_packet_manifest_sha256 does not match external_reviewer_packet_manifest", mismatch_errors)
        self.assertTrue(any("must not contain traversal components" in error for error in unsafe_errors), unsafe_errors)
        self.assertEqual([], cleaned_errors)
        self.assertTrue(
            any(
                "ephemeral disclosed file remains after completed cleanup" in error
                for error in lingering_cleanup_errors
            ),
            lingering_cleanup_errors,
        )
        self.assertTrue(any("retained file is missing" in error for error in missing_output_errors), missing_output_errors)
        self.assertTrue(any("duplicate JSON key" in error for error in duplicate_errors), duplicate_errors)
        self.assertTrue(any("non-finite JSON number" in error for error in nonfinite_errors), nonfinite_errors)
        self.assertTrue(any("pre_submission receipt inventory_sha256" in error for error in receipt_errors), receipt_errors)
        self.assertTrue(any("requires validated or closed lifecycle" in error for error in returned_errors), returned_errors)
        self.assertTrue(any("disclosed file is missing" in error for error in returned_errors), returned_errors)
        self.assertTrue(
            any("sha256 does not match disclosed bytes" in error for error in live_digest_errors),
            live_digest_errors,
        )

    def test_review_packet_contract_rejects_structural_lifecycle_and_retained_byte_forgery(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest, _packet_sha = write_valid_review_packet_bundle(
                root / "review_artifacts" / "external_review_packets" / "contract",
                scope="bounded-scope",
                approval_source="active-thread approval",
                redaction="leak scan passed",
            )
            valid_data = json.loads(manifest.read_text(encoding="utf-8"))
            valid_errors = review_packet_contract.portable_manifest_errors(
                valid_data,
                manifest,
                external_status="used",
            )

            forged = json.loads(json.dumps(valid_data))
            for field in (
                "purpose", "lane_id", "invocation_owner", "questions",
                "output_contract", "retention",
            ):
                forged.pop(field)
            forged["packet"]["packet_sha256"] = review_packet_contract.packet_binding_sha256(forged)
            ready = review_packet_contract.build_receipt(
                forged, "packet_ready", "2026-06-19T08:02:00Z"
            )
            forged["validation_receipts"]["packet_ready"] = ready
            forged["approval"]["packet_ready_receipt_sha256"] = ready["receipt_sha256"]
            forged["validation_receipts"]["pre_submission"] = review_packet_contract.build_receipt(
                forged, "pre_submission", "2026-06-19T08:05:00Z"
            )
            forged_errors = review_packet_contract.portable_manifest_errors(
                forged,
                manifest,
                external_status="used",
            )

            pending_closed = json.loads(json.dumps(valid_data))
            pending_closed["approval"].update({
                "status": "pending",
                "exact_packet_approved": False,
                "approved_at": None,
                "packet_ready_receipt_sha256": None,
            })
            pending_closed["validation_receipts"] = {
                "packet_ready": None,
                "pre_submission": None,
            }
            pending_closed["preflight"] = {
                "status": "not_started", "performed_at": None, "checks": [],
            }
            pending_closed["invocation"] = {
                "status": "not_started", "runtime_class": "model",
                "started_at": None, "ended_at": None,
                "exact_runtime_label": None, "observed_model": None,
                "exact_mode": None, "reasoning_effort_status": None,
                "exact_reasoning_effort": None, "output_sha256": None,
                "failure_class": None, "observed_cost": None,
                "observed_latency_seconds": None,
            }
            pending_closed["verification"].update({
                "findings_classified": False,
                "performed_at": None,
                "verification_record_sha256": None,
            })
            pending_closed["closeout"] = {
                "status": "not_started", "performed_at": None, "checks": [],
                "retention_action": "Pending.", "cleanup_status": "pending",
                "cleanup_evidence_ref": "", "account_or_external_side_effects": [],
            }
            pending_closed["evidence_artifacts"] = []
            pending_closed["packet"]["packet_sha256"] = review_packet_contract.packet_binding_sha256(
                pending_closed
            )
            pending_errors = review_packet_contract.portable_manifest_errors(
                pending_closed,
                manifest,
            )

            output_path = manifest.parent / "evidence" / "review-output.json"
            output_path.unlink()
            missing_output_errors = review_packet_contract.portable_manifest_errors(
                valid_data,
                manifest,
                external_status="used",
            )

        self.assertEqual([], valid_errors)
        self.assertTrue(any("manifest.purpose is required" in error for error in forged_errors), forged_errors)
        self.assertTrue(any("approved-or-later lifecycle requires approved status" in error for error in pending_errors), pending_errors)
        self.assertTrue(any("retained file is missing" in error for error in missing_output_errors), missing_output_errors)

    def test_review_packet_contract_bounds_preinvocation_abandonment_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            packet_root = root / "review_artifacts" / "external_review_packets"
            cases = write_preinvocation_abandonment_case_matrix(packet_root)
            declined_manifest, declined = cases["declined"]
            blocked_manifest, blocked = cases["blocked"]
            approved_blocked_manifest, approved_blocked = cases["approved_blocked"]
            tampered_manifest, tampered_receipt = cases["tampered"]
            tampered_submission_manifest, tampered_submission = cases[
                "tampered_submission"
            ]
            unclosed_manifest, unclosed = cases["unclosed"]
            fabricated_manifest, fabricated_invocation = cases["fabricated"]
            planned_manifest, planned_closeout = cases["planned"]
            retained_manifest, retained_item = cases["retained"]
            lingering_manifest, lingering_ephemeral = cases["lingering"]

            declined_errors = review_packet_contract.portable_manifest_errors(
                declined,
                declined_manifest,
            )
            declined_manifest_retained = declined_manifest.is_file()
            blocked_errors = review_packet_contract.portable_manifest_errors(
                blocked,
                blocked_manifest,
            )
            approved_blocked_errors = (
                review_packet_contract.portable_manifest_errors(
                    approved_blocked,
                    approved_blocked_manifest,
                )
            )
            tampered_receipt_errors = (
                review_packet_contract.portable_manifest_errors(
                    tampered_receipt,
                    tampered_manifest,
                )
            )
            tampered_submission_errors = (
                review_packet_contract.portable_manifest_errors(
                    tampered_submission,
                    tampered_submission_manifest,
                )
            )
            unclosed_errors = review_packet_contract.portable_manifest_errors(
                unclosed,
                unclosed_manifest,
            )
            fabricated_invocation_errors = (
                review_packet_contract.portable_manifest_errors(
                    fabricated_invocation,
                    fabricated_manifest,
                )
            )
            planned_closeout_errors = (
                review_packet_contract.portable_manifest_errors(
                    planned_closeout,
                    planned_manifest,
                )
            )
            retained_item_errors = review_packet_contract.portable_manifest_errors(
                retained_item,
                retained_manifest,
            )
            lingering_ephemeral_errors = (
                review_packet_contract.portable_manifest_errors(
                    lingering_ephemeral,
                    lingering_manifest,
                )
            )

        self.assertEqual([], declined_errors)
        self.assertEqual([], blocked_errors)
        self.assertEqual([], approved_blocked_errors)
        self.assertTrue(declined_manifest_retained)
        self.assertIsInstance(
            declined["validation_receipts"]["packet_ready"],
            dict,
        )
        self.assertEqual("not_started", declined["invocation"]["status"])
        self.assertEqual("skipped", blocked["invocation"]["status"])
        self.assertEqual("not_started", approved_blocked["invocation"]["status"])
        self.assertTrue(
            any(
                "packet_ready receipt digest" in error
                for error in tampered_receipt_errors
            ),
            tampered_receipt_errors,
        )
        self.assertTrue(
            any(
                "disclosed file is missing" in error
                for error in tampered_receipt_errors
            ),
            tampered_receipt_errors,
        )
        self.assertTrue(
            any(
                "pre_submission receipt digest" in error
                for error in tampered_submission_errors
            ),
            tampered_submission_errors,
        )
        self.assertTrue(
            any(
                "disclosed file is missing" in error
                for error in tampered_submission_errors
            ),
            tampered_submission_errors,
        )
        self.assertTrue(
            any("disclosed file is missing" in error for error in unclosed_errors),
            unclosed_errors,
        )
        self.assertIn(
            "started invocation requires invoked lifecycle",
            fabricated_invocation_errors,
        )
        self.assertTrue(
            any(
                "disclosed file is missing" in error
                for error in fabricated_invocation_errors
            ),
            fabricated_invocation_errors,
        )
        self.assertIn(
            "closeout cannot begin before closed or terminal-blocked lifecycle",
            planned_closeout_errors,
        )
        self.assertTrue(
            any("disclosed file is missing" in error for error in retained_item_errors),
            retained_item_errors,
        )
        self.assertTrue(
            any(
                "ephemeral disclosed file remains after completed cleanup" in error
                for error in lingering_ephemeral_errors
            ),
            lingering_ephemeral_errors,
        )
    def test_review_packet_contract_runtime_provenance_is_class_conditional(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest, _packet_sha = write_valid_review_packet_bundle(
                root / "review_artifacts" / "external_review_packets" / "runtime-classes",
                scope="bounded-scope",
                approval_source="active-thread approval",
                redaction="leak scan passed",
            )
            base = json.loads(manifest.read_text(encoding="utf-8"))
            valid_variants = (
                (
                    "moving-alias",
                    "model",
                    {
                        "model_identifier": "fixture-model-latest",
                        "version_kind": "moving_alias",
                        "selection_basis": "Fixture intentionally permits a moving alias.",
                    },
                    {
                        "model_identifier": "fixture-model-latest",
                        "version_kind": "moving_alias",
                        "matches_planned_policy": True,
                        "comparison_basis": "Observed alias equals the approved alias.",
                    },
                    "not_exposed",
                    None,
                ),
                (
                    "immutable-hybrid",
                    "hybrid",
                    {
                        "model_identifier": "fixture-model-snapshot",
                        "version_kind": "immutable_snapshot",
                        "selection_basis": "Fixture pins one immutable model identity.",
                    },
                    {
                        "model_identifier": "fixture-model-snapshot",
                        "version_kind": "immutable_snapshot",
                        "matches_planned_policy": True,
                        "comparison_basis": "Observed identity equals the approved identity.",
                    },
                    "recorded",
                    "fixture-effort",
                ),
                (
                    "stable-alias-resolved-snapshot",
                    "model",
                    {
                        "model_identifier": "fixture-model-stable",
                        "version_kind": "stable_alias",
                        "selection_basis": "Fixture approves one stable alias.",
                    },
                    {
                        "model_identifier": "fixture-resolved-snapshot",
                        "version_kind": "immutable_snapshot",
                        "matches_planned_policy": True,
                        "comparison_basis": "Provider evidence resolves the approved alias to this snapshot.",
                    },
                    "not_exposed",
                    None,
                ),
                (
                    "unexposed-plan-observed-snapshot",
                    "model",
                    {
                        "model_identifier": None,
                        "version_kind": "not_exposed",
                        "selection_basis": "Fixture approves a provider-selected model policy without an exposed identity.",
                    },
                    {
                        "model_identifier": "fixture-observed-snapshot",
                        "version_kind": "immutable_snapshot",
                        "matches_planned_policy": True,
                        "comparison_basis": "Runtime evidence confirms the observed snapshot satisfied the approved selection basis.",
                    },
                    "not_exposed",
                    None,
                ),
                ("human", "human", None, None, "not_applicable", None),
                (
                    "deterministic-tool",
                    "deterministic_tool",
                    None,
                    None,
                    "not_applicable",
                    None,
                ),
            )
            valid_errors: dict[str, list[str]] = {}
            for (
                case_name,
                runtime_class,
                planned_policy,
                observed_model,
                effort_status,
                exact_effort,
            ) in valid_variants:
                candidate = copy.deepcopy(base)
                candidate["planned_model_policy"] = planned_policy
                candidate["invocation"].update({
                    "runtime_class": runtime_class,
                    "exact_runtime_label": f"fixture-{runtime_class}-runtime",
                    "observed_model": observed_model,
                    "exact_mode": "fixture-review-mode",
                    "reasoning_effort_status": effort_status,
                    "exact_reasoning_effort": exact_effort,
                })
                candidate["packet"]["packet_sha256"] = (
                    review_packet_contract.packet_binding_sha256(candidate)
                )
                ready_receipt = review_packet_contract.build_receipt(
                    candidate,
                    "packet_ready",
                    "2026-06-19T08:02:00Z",
                )
                candidate["validation_receipts"]["packet_ready"] = ready_receipt
                candidate["approval"]["packet_ready_receipt_sha256"] = ready_receipt[
                    "receipt_sha256"
                ]
                candidate["validation_receipts"]["pre_submission"] = (
                    review_packet_contract.build_receipt(
                        candidate,
                        "pre_submission",
                        "2026-06-19T08:05:00Z",
                    )
                )
                valid_errors[case_name] = review_packet_contract.portable_manifest_errors(
                    candidate,
                    manifest,
                    external_status="used",
                )

            missing_observation = copy.deepcopy(base)
            missing_observation["invocation"]["observed_model"] = None
            missing_observation_errors = review_packet_contract.portable_manifest_errors(
                missing_observation,
                manifest,
            )
            missing_planned_policy = copy.deepcopy(base)
            missing_planned_policy["planned_model_policy"] = None
            missing_planned_policy_errors = (
                review_packet_contract.portable_manifest_errors(
                    missing_planned_policy,
                    manifest,
                )
            )

            switched_runtime = copy.deepcopy(base)
            switched_runtime["planned_model_policy"] = None
            switched_runtime["invocation"].update({
                "runtime_class": "human",
                "exact_runtime_label": "fixture-human-runtime",
                "observed_model": None,
                "exact_mode": "blind-manual-review",
                "reasoning_effort_status": "not_applicable",
                "exact_reasoning_effort": None,
            })
            switched_runtime_errors = review_packet_contract.portable_manifest_errors(
                switched_runtime,
                manifest,
            )

            switched_effect = copy.deepcopy(base)
            switched_effect["effect_mode"] = "propose"
            switched_effect_errors = review_packet_contract.portable_manifest_errors(
                switched_effect,
                manifest,
            )

            fake_human_model = copy.deepcopy(base)
            fake_human_model["invocation"].update({
                "runtime_class": "human",
                "reasoning_effort_status": "not_applicable",
                "exact_reasoning_effort": None,
            })
            fake_human_model_errors = review_packet_contract.portable_manifest_errors(
                fake_human_model,
                manifest,
            )

            missing_effort = copy.deepcopy(base)
            missing_effort["invocation"]["exact_reasoning_effort"] = None
            missing_effort_errors = review_packet_contract.portable_manifest_errors(
                missing_effort,
                manifest,
            )
            mismatched_model = copy.deepcopy(base)
            mismatched_model["invocation"]["observed_model"][
                "matches_planned_policy"
            ] = False
            mismatched_model_errors = review_packet_contract.portable_manifest_errors(
                mismatched_model,
                manifest,
            )
            contradictory_match = copy.deepcopy(base)
            contradictory_match["invocation"]["observed_model"][
                "model_identifier"
            ] = "different-fixture-model-snapshot"
            contradictory_match_errors = (
                review_packet_contract.portable_manifest_errors(
                    contradictory_match,
                    manifest,
                )
            )
            immutable_to_alias = copy.deepcopy(base)
            immutable_to_alias["invocation"]["observed_model"].update({
                "model_identifier": "fixture-model-latest",
                "version_kind": "moving_alias",
            })
            immutable_to_alias_errors = (
                review_packet_contract.portable_manifest_errors(
                    immutable_to_alias,
                    manifest,
                )
            )
            immutable_to_not_exposed = copy.deepcopy(base)
            immutable_to_not_exposed["invocation"]["observed_model"].update({
                "model_identifier": None,
                "version_kind": "not_exposed",
            })
            immutable_to_not_exposed_errors = (
                review_packet_contract.portable_manifest_errors(
                    immutable_to_not_exposed,
                    manifest,
                )
            )
            not_exposed_with_identifier = copy.deepcopy(base)
            not_exposed_with_identifier["invocation"]["observed_model"].update({
                "version_kind": "not_exposed",
                "model_identifier": "invented-model-identity",
            })
            not_exposed_errors = review_packet_contract.portable_manifest_errors(
                not_exposed_with_identifier,
                manifest,
            )
            planned_policy_mutation = copy.deepcopy(base)
            planned_policy_mutation["planned_model_policy"][
                "selection_basis"
            ] = "Changed after approval."
            planned_policy_mutation_errors = (
                review_packet_contract.portable_manifest_errors(
                    planned_policy_mutation,
                    manifest,
                )
            )
            legacy_exact_label = copy.deepcopy(base)
            legacy_exact_label["invocation"]["exact_model_label"] = "legacy-label"
            legacy_exact_label_errors = review_packet_contract.portable_manifest_errors(
                legacy_exact_label,
                manifest,
            )
            obsolete_schema = copy.deepcopy(base)
            obsolete_schema["schema_version"] = 4
            obsolete_schema_errors = review_packet_contract.portable_manifest_errors(
                obsolete_schema,
                manifest,
            )
            started_human_errors = review_packet_contract.invocation_provenance_errors({
                "status": "started",
                "runtime_class": "human",
                "exact_runtime_label": "fixture-human-reviewer",
                "observed_model": None,
                "exact_mode": "blind-manual-review",
                "reasoning_effort_status": "not_applicable",
                "exact_reasoning_effort": None,
            })
            failed_tool_errors = review_packet_contract.invocation_provenance_errors({
                "status": "failed",
                "runtime_class": "deterministic_tool",
                "exact_runtime_label": "fixture-validator-v1",
                "observed_model": None,
                "exact_mode": "read-only-check",
                "reasoning_effort_status": "not_applicable",
                "exact_reasoning_effort": None,
            })

        self.assertEqual(
            {case_name: [] for case_name, *_rest in valid_variants},
            valid_errors,
        )
        self.assertTrue(
            any("observed_model must be an object" in error for error in missing_observation_errors),
            missing_observation_errors,
        )
        self.assertIn(
            "model or hybrid lane requires a planned_model_policy before approval",
            missing_planned_policy_errors,
        )
        self.assertTrue(
            any(
                "packet.packet_sha256 does not match" in error
                for error in switched_runtime_errors
            ),
            switched_runtime_errors,
        )
        self.assertTrue(
            any(
                "packet_ready receipt packet_sha256" in error
                for error in switched_runtime_errors
            ),
            switched_runtime_errors,
        )
        self.assertTrue(
            any(
                "pre_submission receipt packet_sha256" in error
                for error in switched_runtime_errors
            ),
            switched_runtime_errors,
        )
        self.assertTrue(
            any(
                "packet.packet_sha256 does not match" in error
                for error in switched_effect_errors
            ),
            switched_effect_errors,
        )
        self.assertTrue(
            any(
                "packet_ready receipt packet_sha256" in error
                for error in switched_effect_errors
            ),
            switched_effect_errors,
        )
        self.assertTrue(
            any(
                "pre_submission receipt packet_sha256" in error
                for error in switched_effect_errors
            ),
            switched_effect_errors,
        )
        self.assertTrue(
            any("cannot claim an observed model" in error for error in fake_human_model_errors),
            fake_human_model_errors,
        )
        self.assertTrue(
            any("requires an exact reasoning-effort value" in error for error in missing_effort_errors),
            missing_effort_errors,
        )
        self.assertIn(
            "observed model that does not match planned policy requires blocked lifecycle",
            mismatched_model_errors,
        )
        self.assertIn(
            "matching immutable planned and observed snapshots require the same identifier",
            contradictory_match_errors,
        )
        self.assertIn(
            "matching an immutable planned snapshot requires an observed immutable snapshot",
            immutable_to_alias_errors,
        )
        self.assertIn(
            "matching an immutable planned snapshot requires an observed immutable snapshot",
            immutable_to_not_exposed_errors,
        )
        self.assertTrue(
            any("cannot claim a model identifier" in error for error in not_exposed_errors),
            not_exposed_errors,
        )
        self.assertTrue(
            any("packet.packet_sha256 does not match" in error for error in planned_policy_mutation_errors),
            planned_policy_mutation_errors,
        )
        self.assertTrue(
            any(
                "packet_ready receipt packet_sha256" in error
                for error in planned_policy_mutation_errors
            ),
            planned_policy_mutation_errors,
        )
        self.assertTrue(
            any(
                "pre_submission receipt packet_sha256" in error
                for error in planned_policy_mutation_errors
            ),
            planned_policy_mutation_errors,
        )
        self.assertTrue(
            any("manifest.invocation.exact_model_label is not allowed" in error for error in legacy_exact_label_errors),
            legacy_exact_label_errors,
        )
        self.assertTrue(
            any("manifest.schema_version" in error for error in obsolete_schema_errors),
            obsolete_schema_errors,
        )
        self.assertEqual([], started_human_errors)
        self.assertEqual([], failed_tool_errors)

    def test_review_packet_contract_binds_typed_lane_controls(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest, _packet_sha = write_valid_review_packet_bundle(
                root / "review_artifacts" / "external_review_packets" / "lane-controls",
                scope="bounded-scope",
                approval_source="active-thread approval",
                redaction="leak scan passed",
            )
            base = json.loads(manifest.read_text(encoding="utf-8"))
            valid_errors = review_packet_contract.portable_manifest_errors(
                base,
                manifest,
                external_status="used",
            )

            missing_control_errors: dict[str, list[str]] = {}
            for field in review_packet_contract.LANE_CONTROL_FIELDS:
                missing_control = copy.deepcopy(base)
                missing_control["lane_controls"].pop(field)
                missing_control_errors[field] = (
                    review_packet_contract.portable_manifest_errors(
                        missing_control,
                        manifest,
                    )
                )

            inherited_full = copy.deepcopy(base)
            inherited_full["lane_controls"]["independence_group"][
                "resolution"
            ] = "inherited"
            inherited_full_errors = (
                review_packet_contract.portable_manifest_errors(
                    inherited_full,
                    manifest,
                )
            )

            compact_internal = copy.deepcopy(base)
            compact_internal["lane_controls"]["manifest_kind"] = "compact_internal"
            for field in review_packet_contract.LANE_CONTROL_FIELDS:
                compact_internal["lane_controls"][field].update({
                    "resolution": "inherited",
                    "value": f"universal {field}",
                    "basis": "Named fixture universal control.",
                })
            compact_internal["lane_controls"]["auth_session_policy"].update({
                "resolution": "not_applicable",
                "value": None,
                "basis": "Local deterministic fixture has no authenticated session.",
            })
            compact_internal["lane_controls"]["fallback_or_abort_rule"].update({
                "resolution": "derived",
                "value": "Abort on an invalid deterministic result.",
                "basis": "Derived from the bounded fixture stop rule.",
            })
            compact_internal["lane_controls"]["teardown_rule"].update({
                "resolution": "explicit",
                "value": "Close after local validation.",
                "basis": "Explicit fixture lifecycle rule.",
            })
            compact_internal["packet"]["packet_sha256"] = (
                review_packet_contract.packet_binding_sha256(compact_internal)
            )
            compact_ready = review_packet_contract.build_receipt(
                compact_internal,
                "packet_ready",
                "2026-06-19T08:02:00Z",
            )
            compact_internal["validation_receipts"]["packet_ready"] = compact_ready
            compact_internal["approval"]["packet_ready_receipt_sha256"] = (
                compact_ready["receipt_sha256"]
            )
            compact_internal["validation_receipts"]["pre_submission"] = (
                review_packet_contract.build_receipt(
                    compact_internal,
                    "pre_submission",
                    "2026-06-19T08:05:00Z",
                )
            )
            compact_errors = review_packet_contract.portable_manifest_errors(
                compact_internal,
                manifest,
            )
            compact_external_errors = (
                review_packet_contract.portable_manifest_errors(
                    compact_internal,
                    manifest,
                    external_status="used",
                )
            )

            human_compact = copy.deepcopy(compact_internal)
            human_compact["planned_model_policy"] = None
            human_compact["invocation"].update({
                "runtime_class": "human",
                "exact_runtime_label": "fixture-human-runtime",
                "observed_model": None,
                "exact_mode": "blind-manual-review",
                "reasoning_effort_status": "not_applicable",
                "exact_reasoning_effort": None,
            })
            human_compact["packet"]["packet_sha256"] = (
                review_packet_contract.packet_binding_sha256(human_compact)
            )
            human_compact_ready = review_packet_contract.build_receipt(
                human_compact,
                "packet_ready",
                "2026-06-19T08:02:00Z",
            )
            human_compact["validation_receipts"][
                "packet_ready"
            ] = human_compact_ready
            human_compact["approval"]["packet_ready_receipt_sha256"] = (
                human_compact_ready["receipt_sha256"]
            )
            human_compact["validation_receipts"]["pre_submission"] = (
                review_packet_contract.build_receipt(
                    human_compact,
                    "pre_submission",
                    "2026-06-19T08:05:00Z",
                )
            )
            human_compact_errors = review_packet_contract.portable_manifest_errors(
                human_compact,
                manifest,
            )

            invalid_compact = copy.deepcopy(compact_internal)
            invalid_compact["lane_controls"]["timeout"].update({
                "resolution": "derived",
                "value": None,
            })
            invalid_compact_errors = review_packet_contract.portable_manifest_errors(
                invalid_compact,
                manifest,
            )
            blank_basis = copy.deepcopy(compact_internal)
            blank_basis["lane_controls"]["teardown_rule"]["basis"] = "   "
            blank_basis_errors = review_packet_contract.portable_manifest_errors(
                blank_basis,
                manifest,
            )

            post_approval_mutation = copy.deepcopy(base)
            post_approval_mutation["lane_controls"]["timeout"][
                "value"
            ] = "1200 seconds"
            post_approval_mutation_errors = (
                review_packet_contract.portable_manifest_errors(
                    post_approval_mutation,
                    manifest,
                )
            )

        self.assertEqual([], valid_errors)
        for field, field_errors in missing_control_errors.items():
            with self.subTest(missing_lane_control=field):
                self.assertTrue(
                    any(
                        f"manifest.lane_controls.{field} is required" in error
                        for error in field_errors
                    ),
                    field_errors,
                )
        self.assertIn(
            "full lane control independence_group must be explicit",
            inherited_full_errors,
        )
        self.assertEqual([], compact_errors)
        self.assertIn(
            "external reviewer status requires a full control manifest",
            compact_external_errors,
        )
        self.assertIn(
            "human reviewer lane requires a full control manifest",
            human_compact_errors,
        )
        self.assertIn(
            "compact internal lane control timeout requires an explicit, inherited, or derived value",
            invalid_compact_errors,
        )
        self.assertIn(
            "lane control teardown_rule requires a nonempty basis",
            blank_basis_errors,
        )
        self.assertTrue(
            any("packet.packet_sha256 does not match" in error for error in post_approval_mutation_errors),
            post_approval_mutation_errors,
        )
        self.assertTrue(
            any(
                "packet_ready receipt packet_sha256" in error
                for error in post_approval_mutation_errors
            ),
            post_approval_mutation_errors,
        )
        self.assertTrue(
            any(
                "pre_submission receipt packet_sha256" in error
                for error in post_approval_mutation_errors
            ),
            post_approval_mutation_errors,
        )

    def test_review_packet_contract_prepares_receipts_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest, _packet_sha = write_valid_review_packet_bundle(
                root / "review_artifacts" / "external_review_packets" / "receipt-preparation",
                scope="bounded-scope",
                approval_source="active-thread approval",
                redaction="leak scan passed",
                retain_ephemeral_item=True,
            )
            planned = json.loads(manifest.read_text(encoding="utf-8"))
            planned["lifecycle"].update({
                "stage": "planned",
                "stage_updated_at": "2026-06-19T08:01:00Z",
            })
            planned["approval"].update({
                "status": "pending",
                "exact_packet_approved": False,
                "approved_at": None,
                "packet_ready_receipt_sha256": None,
            })
            planned["packet"]["packet_sha256"] = "0" * 64
            planned["validation_receipts"] = {
                "packet_ready": None,
                "pre_submission": None,
            }
            planned["preflight"] = {
                "status": "not_started", "performed_at": None, "checks": [],
            }
            planned["invocation"] = {
                "status": "not_started", "runtime_class": "model",
                "started_at": None, "ended_at": None,
                "exact_runtime_label": None, "observed_model": None,
                "exact_mode": None, "reasoning_effort_status": None,
                "exact_reasoning_effort": None, "output_sha256": None,
                "failure_class": None, "observed_cost": None,
                "observed_latency_seconds": None,
            }
            planned["verification"].update({
                "findings_classified": False,
                "performed_at": None,
                "verification_record_sha256": None,
            })
            planned["closeout"] = {
                "status": "not_started", "performed_at": None, "checks": [],
                "retention_action": "Pending.", "cleanup_status": "pending",
                "cleanup_evidence_ref": "", "account_or_external_side_effects": [],
            }
            planned["evidence_artifacts"] = []
            shutil.rmtree(manifest.parent / "evidence")
            manifest.write_text(json.dumps(planned, indent=2) + "\n", encoding="utf-8")
            before_ready = manifest.read_bytes()

            ready_payload, ready_errors = review_packet_contract.prepare_receipt(
                planned,
                manifest,
                phase="packet_ready",
                validated_at="2026-06-19T08:02:00Z",
            )
            after_ready = manifest.read_bytes()
            self.assertIsNotNone(ready_payload)
            ready = cast(dict[str, Any], ready_payload)
            ready_candidate = copy.deepcopy(planned)
            ready_candidate["packet"]["packet_sha256"] = ready["packet_sha256"]
            ready_candidate["lifecycle"].update({
                "stage": ready["lifecycle_stage"],
                "stage_updated_at": ready["stage_updated_at"],
            })
            ready_candidate["validation_receipts"]["packet_ready"] = ready["receipt"]
            declined_after_ready = copy.deepcopy(ready_candidate)
            declined_after_ready["approval"]["status"] = "declined"
            declined_after_ready["lifecycle"].update({
                "stage": "declined",
                "stage_updated_at": "2026-06-19T08:03:00Z",
            })
            declined_after_ready_errors = review_packet_contract.portable_manifest_errors(
                declined_after_ready,
                manifest,
            )
            ready_candidate["lifecycle"].update({
                "stage": "approved",
                "stage_updated_at": "2026-06-19T08:04:00Z",
            })
            ready_candidate["approval"].update({
                "status": "approved",
                "exact_packet_approved": True,
                "approved_at": "2026-06-19T08:03:00Z",
                "packet_ready_receipt_sha256": ready["receipt"]["receipt_sha256"],
            })
            ready_candidate["preflight"] = {
                "status": "passed",
                "performed_at": "2026-06-19T08:04:00Z",
                "checks": [{
                    "check_id": "exact_packet",
                    "outcome": "pass",
                    "evidence_ref": "fixture",
                }],
            }
            manifest.write_text(
                json.dumps(ready_candidate, indent=2) + "\n",
                encoding="utf-8",
            )
            before_submission = manifest.read_bytes()

            with (
                mock.patch(
                    "sys.argv",
                    [
                        "review_packet_contract.py",
                        str(manifest),
                        "--prepare-receipt",
                        "pre_submission",
                        "--validated-at",
                        "2026-06-19T08:05:00Z",
                    ],
                ),
                mock.patch("sys.stdout", new_callable=io.StringIO) as stdout,
            ):
                exit_code = review_packet_contract.main()
            result = json.loads(stdout.getvalue())
            after_submission = manifest.read_bytes()
            with (
                mock.patch(
                    "sys.argv",
                    [
                        "review_packet_contract.py",
                        str(manifest),
                        "--validated-at",
                        "2026-06-19T08:05:00Z",
                    ],
                ),
                mock.patch("sys.stderr", new_callable=io.StringIO),
                self.assertRaises(SystemExit) as argument_exit,
            ):
                review_packet_contract.main()
            submission = cast(dict[str, Any], result["prepared"])
            submission_candidate = copy.deepcopy(ready_candidate)
            submission_candidate["lifecycle"]["stage_updated_at"] = submission[
                "stage_updated_at"
            ]
            submission_candidate["validation_receipts"]["pre_submission"] = submission[
                "receipt"
            ]
            submission_errors = review_packet_contract.portable_manifest_errors(
                submission_candidate,
                manifest,
            )
            declined = copy.deepcopy(planned)
            declined["approval"]["status"] = "declined"
            declined["lifecycle"].update({
                "stage": "declined",
                "stage_updated_at": "2026-06-19T08:02:00Z",
            })
            declined_errors = review_packet_contract.portable_manifest_errors(
                declined,
                manifest,
            )
            declined["lifecycle"]["stage"] = "planned"
            incoherent_decline_errors = review_packet_contract.portable_manifest_errors(
                declined,
                manifest,
            )
            retrospective = copy.deepcopy(ready_candidate)
            retrospective["lifecycle"]["stage"] = "invoked"
            retrospective["invocation"]["status"] = "started"
            _retrospective_payload, retrospective_errors = (
                review_packet_contract.prepare_receipt(
                    retrospective,
                    manifest,
                    phase="pre_submission",
                    validated_at="2026-06-19T08:05:00Z",
                )
            )
            _invalid_payload, invalid_time_errors = review_packet_contract.prepare_receipt(
                planned,
                manifest,
                phase="packet_ready",
                validated_at="2026-06-19T08:02:00",
            )

        self.assertEqual([], ready_errors)
        self.assertEqual(before_ready, after_ready)
        self.assertEqual(0, exit_code)
        self.assertEqual(2, argument_exit.exception.code)
        self.assertEqual([], result["errors"])
        self.assertEqual(before_submission, after_submission)
        self.assertEqual([], submission_errors)
        self.assertEqual([], declined_errors)
        self.assertEqual([], declined_after_ready_errors)
        self.assertIn(
            "declined approval requires declined lifecycle",
            incoherent_decline_errors,
        )
        self.assertIn(
            "pre_submission receipt requires an approved, uninvoked lifecycle",
            retrospective_errors,
        )
        self.assertIn(
            "validated_at must be an explicit timezone-aware RFC 3339 timestamp",
            invalid_time_errors,
        )

    def test_source_chain_artifact_lint_parses_apply_verification_records(self) -> None:
        good_errors: list[str] = []
        bad_errors: list[str] = []
        source_chain_artifact_lint.validate_apply_verification(
            "\n".join(
                [
                    "verification:",
                    "  - command: uv run python -B scripts/framework_compliance.py --tree-role authoring-source",
                    "    covers: framework-compliance",
                    "    tree_or_artifact: commit:abcdef1",
                    "    dirty_tree: clean",
                    "    touched_files: scripts/source_chain_artifact_lint.py",
                    "    expected_assertion: framework compliance gate covers source-chain lint behavior",
                    "    output_ref: sha256:" + "a" * 64,
                    "    environment: approved-container",
                    "    exit_code: 0",
                ]
            ),
            good_errors,
            require_successful=True,
        )
        source_chain_artifact_lint.validate_apply_verification(
            "\n".join(
                [
                    "verification:",
                    "  - command: uv run python -B scripts/framework_compliance.py --tree-role authoring-source",
                    "    covers: framework-compliance",
                    "    tree_or_artifact: commit:abcdef1",
                    "    dirty_tree: clean",
                    "    touched_files: scripts/source_chain_artifact_lint.py",
                    "    expected_assertion: framework compliance gate covers source-chain lint behavior",
                    "    output_ref: sha256:" + "a" * 64,
                    "    environment: approved-container",
                    "    exit_code: 1",
                ]
            ),
            bad_errors,
            require_successful=True,
        )
        diagnostic_errors: list[str] = []
        source_chain_artifact_lint.validate_apply_verification(
            "\n".join(
                [
                    "verification:",
                    "  - command: uv run python -B scripts/framework_compliance.py --tree-role authoring-source",
                    "    covers: blocked preflight diagnostic",
                    "    tree_or_artifact: artifact:preflight",
                    "    dirty_tree: tracked-diff-matches-changed_files",
                    "    touched_files: none",
                    "    expected_assertion: command failed before an approved apply could run",
                    "    output_ref: log:preflight",
                    "    environment: approved-container",
                    "    exit_code: 1",
                ]
            ),
            diagnostic_errors,
            require_successful=False,
        )

        self.assertEqual([], good_errors)
        self.assertTrue(any("exit_code must be 0" in error for error in bad_errors), bad_errors)
        self.assertEqual([], diagnostic_errors)

    def test_source_chain_artifact_lint_rejects_unbounded_or_noncanonical_exit_codes(
        self,
    ) -> None:
        def verification_text(exit_code: str) -> str:
            return "\n".join(
                [
                    "verification:",
                    "  - command: uv run python -B scripts/framework_compliance.py --tree-role authoring-source",
                    "    covers: framework-compliance",
                    "    tree_or_artifact: commit:abcdef1",
                    "    dirty_tree: clean",
                    "    touched_files: scripts/source_chain_artifact_lint.py",
                    "    expected_assertion: framework compliance gate covers source-chain lint behavior",
                    "    output_ref: sha256:" + "a" * 64,
                    "    environment: approved-container",
                    f"    exit_code: {exit_code}",
                ]
            )

        cases = (
            ("01", "canonical unsigned 32-bit decimal integer"),
            ("4294967296", "exit_code must be at most 4294967295"),
            ("9" * 5000, "canonical unsigned 32-bit decimal integer"),
        )
        for exit_code, expected_error in cases:
            with self.subTest(exit_code_length=len(exit_code)):
                errors: list[str] = []
                source_chain_artifact_lint.validate_apply_verification(
                    verification_text(exit_code),
                    errors,
                    require_successful=False,
                )
                self.assertTrue(
                    any(expected_error in error for error in errors),
                    errors,
                )

    def test_source_chain_artifact_lint_rejects_duplicate_and_malformed_verification_fields(self) -> None:
        errors: list[str] = []
        source_chain_artifact_lint.validate_apply_verification(
            "\n".join(
                [
                    "verification:",
                    "  - command: check",
                    "    command: duplicate",
                    "    covers: F1",
                    "    tree_or_artifact: artifact:",
                    "    dirty_tree: clean",
                    "    touched_files: scripts/check.py",
                    "    expected_assertion: invariant holds",
                    "    output_ref: sha256:abc",
                    "    environment: local",
                    "    exit_code: 0",
                ]
            ),
            errors,
            require_successful=True,
        )

        self.assertTrue(any("duplicates nested field: command" in error for error in errors), errors)
        self.assertTrue(any("output_ref must be a digest" in error for error in errors), errors)
        self.assertTrue(any("tree_or_artifact must identify" in error for error in errors), errors)

    def test_source_chain_wait_requires_linted_terminal_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_file = root / "local_overlays" / "references" / "security_sources.md"
            policy_file = root / "local_overlays" / "source_monitor_policy.md"
            monitor = root / "review_artifacts" / "source_monitor" / "2026-06-19_0930.md"
            source_file.parent.mkdir(parents=True)
            policy_file.parent.mkdir(parents=True, exist_ok=True)
            monitor.parent.mkdir(parents=True)
            source_file.write_text("# Sources\n", encoding="utf-8")
            policy_file.write_text("# Policy\n", encoding="utf-8")
            source_hash = source_chain_artifact_lint.file_sha256(source_file)
            policy_hash = source_chain_artifact_lint.file_sha256(policy_file)

            ready, state = artifact_ready(monitor, "monitor")
            self.assertFalse(ready)
            self.assertEqual("missing", state)

            monitor.write_text("status: pass\n\n# Broken\n", encoding="utf-8")
            ready, state = artifact_ready(monitor, "monitor")
            self.assertFalse(ready)
            self.assertIn("invalid", state)

            monitor.write_text(
                "\n".join(
                    [
                        "artifact_schema_version: 6",
                        "chain_id: source-2026-06-19-0930",
                        "stage: monitor",
                        "stage_run_id: monitor-2026-06-19-0930",
                        "attempt_id: monitor-2026-06-19T023000Z-abc123",
                        "logical_date: 2026-06-19",
                        "run_slot: 0930",
                        "monitor_scope: framework-sources",
                        "monitor_scope_sha256: 5b619bc978d06cba5277f7846faa48625e0ec70ba43216c35213bb6cd7f62a38",
                        "model_route: quality_first",
                        "model_label: fixture-model",
                        "reasoning_effort: high",
                        "execution_mode: standard",
                        "timezone: Europe/Vienna",
                        "started_at_utc: 2026-06-19T00:30:00Z",
                        "completed_at_utc: 2026-06-19T00:52:00Z",
                        "status: partial",
                        "source_status: partial",
                        "workspace_status: dirty",
                        "external_reviewer_status: considered_skipped",
                        "external_reviewer_packet_scope: none",
                        "inaccessible_source_count: 0",
                        "unresolved_inaccessible_source_count: 0",
                        "source_root_coverage_count: 0",
                        "source_registry_files:",
                        "  - path: local_overlays/references/security_sources.md",
                        f"    sha256: {source_hash}",
                        "policy_files:",
                        "  - path: local_overlays/source_monitor_policy.md",
                        f"    sha256: {policy_hash}",
                        "",
                        "# Monitor",
                    ]
                ),
                encoding="utf-8",
            )
            ready, state = artifact_ready(monitor, "monitor")
            wrong_date_ready, wrong_date_state = artifact_ready(
                monitor,
                "monitor",
                expected_logical_date="2026-06-20",
                expected_run_slot="0930",
            )
            wrong_slot_ready, wrong_slot_state = artifact_ready(
                monitor,
                "monitor",
                expected_logical_date="2026-06-19",
                expected_run_slot="1330",
            )

        self.assertTrue(ready)
        self.assertEqual("ready: partial", state)
        self.assertFalse(wrong_date_ready)
        self.assertEqual("wrong logical_date: expected 2026-06-20, got 2026-06-19", wrong_date_state)
        self.assertFalse(wrong_slot_ready)
        self.assertEqual("wrong run_slot: expected 1330, got 0930", wrong_slot_state)

    def test_source_chain_wait_requires_stable_digest_for_timed_wait(self) -> None:
        artifact = Path("source-chain-stable-test.md")
        with (
            mock.patch.object(
                source_chain_wait,
                "observe_artifact",
                side_effect=[
                    source_chain_wait.ArtifactObservation(
                        True, "ready: pass", ("a" * 64, 1)
                    ),
                    source_chain_wait.ArtifactObservation(
                        True, "ready: pass", ("b" * 64, 1)
                    ),
                    source_chain_wait.ArtifactObservation(
                        True, "ready: pass", ("b" * 64, 1)
                    ),
                    source_chain_wait.ArtifactObservation(
                        True, "ready: pass", ("b" * 64, 1)
                    ),
                ],
            ),
            mock.patch.object(source_chain_wait.time, "sleep", return_value=None) as sleep,
            mock.patch.object(source_chain_wait.time, "monotonic", return_value=0.0),
        ):
            ready, state = wait_for_artifact(
                artifact,
                "monitor",
                timeout_seconds=10,
                poll_seconds=1,
            )

        self.assertTrue(ready)
        self.assertEqual("ready: pass; stable", state)
        self.assertEqual(2, sleep.call_count)

    def test_source_chain_wait_handles_fingerprint_and_header_read_races(self) -> None:
        artifact = Path("source-chain-race-test.md")
        with (
            mock.patch.object(
                source_chain_wait,
                "observe_artifact",
                return_value=source_chain_wait.ArtifactObservation(
                    True,
                    "ready: pass",
                    None,
                ),
            ),
            mock.patch.object(source_chain_wait.time, "sleep", return_value=None),
            mock.patch.object(
                source_chain_wait.time,
                "monotonic",
                side_effect=[0.0, 0.5, 0.6, 1.1],
            ),
        ):
            ready, state = wait_for_artifact(
                artifact,
                "monitor",
                timeout_seconds=1,
                poll_seconds=1,
            )

        self.assertFalse(ready)
        self.assertIn("could not be fingerprinted", state)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            existing = (
                root
                / "review_artifacts"
                / "source_monitor"
                / "2026-06-19_0930.md"
            )
            existing.parent.mkdir(parents=True)
            existing.write_text("status: pass\n", encoding="utf-8")
            with (
                mock.patch.object(
                    source_chain_artifact_lint,
                    "validate_artifact",
                    return_value={"errors": []},
                ),
                mock.patch.object(
                    source_chain_wait,
                    "read_header",
                    side_effect=FileNotFoundError("artifact replaced"),
                ),
            ):
                read_ready, read_state = artifact_ready(existing, "monitor")

        self.assertFalse(read_ready)
        self.assertIn("invalid header read", read_state)

    def test_source_chain_wait_uses_one_snapshot_for_validation_header_and_digest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            artifact = (
                root
                / "review_artifacts"
                / "source_monitor"
                / "2026-06-19_0930.md"
            )
            artifact.parent.mkdir(parents=True)
            initial = b"status: pass\n"
            artifact.write_bytes(initial)
            observed_bytes: list[bytes] = []

            def validate(
                _path: Path,
                _stage: str,
                **kwargs: object,
            ) -> dict[str, object]:
                payload = kwargs.get("artifact_bytes")
                self.assertIsInstance(payload, bytes)
                observed_bytes.append(cast(bytes, payload))
                artifact.write_text("status: pending\n", encoding="utf-8")
                return {"errors": []}

            with mock.patch.object(
                source_chain_artifact_lint,
                "validate_artifact",
                side_effect=validate,
            ):
                observation = observe_artifact(artifact, "monitor")

        self.assertTrue(observation.ready)
        self.assertEqual("ready: pass", observation.state)
        self.assertEqual([initial], observed_bytes)
        self.assertEqual((hashlib.sha256(initial).hexdigest(), len(initial)), observation.fingerprint)

    def test_source_chain_wait_rejects_unsafe_artifact_inputs(self) -> None:
        cases = ("invalid-utf8", "oversize", "hardlink", "fifo")
        for case_id in cases:
            with self.subTest(case_id=case_id), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                artifact = (
                    root
                    / "review_artifacts"
                    / "source_monitor"
                    / "2026-06-19_0930.md"
                )
                artifact.parent.mkdir(parents=True)
                if case_id == "invalid-utf8":
                    artifact.write_bytes(b"\xff")
                elif case_id == "oversize":
                    artifact.write_bytes(
                        b"x" * (source_chain_artifact_lint.ARTIFACT_MAX_BYTES + 1)
                    )
                elif case_id == "hardlink":
                    seed = root / "seed.md"
                    seed.write_text("status: pass\n", encoding="utf-8")
                    os.link(seed, artifact)
                else:
                    if not hasattr(os, "mkfifo"):
                        self.skipTest("FIFO creation is unavailable")
                    os.mkfifo(artifact)

                ready, state = artifact_ready(artifact, "monitor")

            self.assertFalse(ready)
            self.assertTrue(
                "invalid artifact read" in state or "cannot read artifact" in state,
                state,
            )

    def test_source_chain_wait_rejects_impossible_calendar_date(self) -> None:
        with self.assertRaisesRegex(SystemExit, "logical-date must be YYYY-MM-DD"):
            source_chain_wait.main(
                [
                    "--stage",
                    "monitor",
                    "--artifact",
                    "artifact.md",
                    "--project-root",
                    ".",
                    "--logical-date",
                    "2026-02-30",
                    "--monitor-scope",
                    "framework-sources",
                    "--expected-model-route",
                    "quality_first",
                    "--expected-timezone",
                    "Europe/Vienna",
                ]
            )

    def test_monitor_current_input_gate_is_handoff_only_after_apply_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            artifacts_root = root / "review_artifacts"
            monitor = artifacts_root / "source_monitor" / "2026-06-19_0930.md"
            monitor.parent.mkdir(parents=True)
            registry = root / "local_overlays" / "references" / "security_sources.md"
            policy = root / "local_overlays" / "source_monitor_policy.md"
            registry.parent.mkdir(parents=True)
            input_bytes = b"# Current monitor input\n"
            registry.write_bytes(input_bytes)
            policy.write_bytes(input_bytes)
            input_digest = hashlib.sha256(input_bytes).hexdigest()
            monitor.write_text(
                monitor_artifact_fixture().replace(_FIXTURE_DIGEST, input_digest),
                encoding="utf-8",
            )

            handoff_ready, handoff_state = wait_for_artifact(
                monitor,
                "monitor",
                0,
                1,
                expected_logical_date="2026-06-19",
                expected_run_slot="0930",
                expected_monitor_scope_sha256=_FIXTURE_SCOPE_SHA256,
                expected_model_route="quality_first",
                expected_model_label="fixture-model",
                expected_reasoning_effort="high",
                expected_execution_mode="standard",
                expected_timezone="Europe/Vienna",
                verify_current_input_hashes=True,
            )
            self.assertTrue(handoff_ready, handoff_state)

            # A legitimate apply stage can update a monitored registry after the
            # monitor artifact captured its input identity.
            registry.write_text("# Updated by the accepted apply decision\n", encoding="utf-8")

            historical_ready, historical_state = wait_for_artifact(
                monitor,
                "monitor",
                0,
                1,
                expected_logical_date="2026-06-19",
                expected_run_slot="0930",
                expected_monitor_scope_sha256=_FIXTURE_SCOPE_SHA256,
                expected_model_route="quality_first",
                expected_model_label="fixture-model",
                expected_reasoning_effort="high",
                expected_execution_mode="standard",
                expected_timezone="Europe/Vienna",
            )
            summary = artifact_summary(
                artifacts_root,
                "monitor",
                "2026-06-19",
                "0930",
                _FIXTURE_SCOPE_SHA256,
                "quality_first",
                expected_timezone="Europe/Vienna",
                expected_model_label="fixture-model",
                expected_reasoning_effort="high",
                expected_execution_mode="standard",
            )
            decision = current_slot_decision(
                monitor,
                "monitor",
                expected_scope_sha256=_FIXTURE_SCOPE_SHA256,
                expected_model_route="quality_first",
                expected_timezone="Europe/Vienna",
                expected_model_label="fixture-model",
                expected_reasoning_effort="high",
                expected_execution_mode="standard",
            )
            stale_ready, stale_state = wait_for_artifact(
                monitor,
                "monitor",
                0,
                1,
                expected_logical_date="2026-06-19",
                expected_run_slot="0930",
                expected_monitor_scope_sha256=_FIXTURE_SCOPE_SHA256,
                expected_model_route="quality_first",
                expected_model_label="fixture-model",
                expected_reasoning_effort="high",
                expected_execution_mode="standard",
                expected_timezone="Europe/Vienna",
                verify_current_input_hashes=True,
            )

        self.assertTrue(historical_ready, historical_state)
        self.assertEqual("pass", summary["lint_status"])
        self.assertEqual("skip_current_slot_complete", decision["action"] if decision else None)
        self.assertFalse(stale_ready)
        self.assertIn("sha256 does not match current file", stale_state)

    def test_source_chain_wait_restricts_current_input_gate_to_monitor(self) -> None:
        with self.assertRaisesRegex(SystemExit, "valid only for stage monitor"):
            source_chain_wait.main(
                [
                    "--stage",
                    "review",
                    "--artifact",
                    "artifact.md",
                    "--project-root",
                    ".",
                    "--monitor-scope",
                    "framework-sources",
                    "--expected-model-route",
                    "quality_first",
                    "--expected-timezone",
                    "Europe/Vienna",
                    "--verify-current-input-hashes",
                ]
            )

    def test_source_chain_lint_rejects_stage_incompatible_or_noop_options(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            monitor = (
                root
                / "review_artifacts"
                / "source_monitor"
                / "2026-06-19_0930.md"
            )
            monitor.parent.mkdir(parents=True)
            monitor.write_text(monitor_artifact_fixture(), encoding="utf-8")

            wrong_core_stage = validate_artifact(
                monitor,
                "monitor",
                verify_decision_hashes=True,
            )
            missing_core_gate = validate_artifact(
                monitor,
                "monitor",
                required_policy_files=("policy.md",),
            )

        self.assertIn(
            "--verify-decision-hashes is valid only for stage review",
            string_items(wrong_core_stage["errors"]),
        )
        self.assertIn(
            "--required-policy-file requires --verify-current-input-hashes",
            string_items(missing_core_gate["errors"]),
        )

        invalid_public_args = (
            ["--stage", "review", "--verify-current-input-hashes", "artifact.md"],
            ["--stage", "monitor", "--verify-decision-hashes", "artifact.md"],
            [
                "--stage",
                "monitor",
                "--required-policy-file",
                "policy.md",
                "artifact.md",
            ],
        )
        for argv in invalid_public_args:
            with self.subTest(cli="public", argv=argv), mock.patch(
                "sys.stderr",
                new=io.StringIO(),
            ):
                with self.assertRaises(SystemExit) as exit_context:
                    source_chain_artifact_lint.main(argv)
                self.assertEqual(2, exit_context.exception.code)

    def test_status_and_preflight_use_one_artifact_snapshot(self) -> None:
        scope_hash = source_chain_artifact_lint.monitor_scope_sha256(
            "framework-sources"
        )
        initial = (
            "\n".join(
                [
                    "artifact_schema_version: 6",
                    "chain_id: source-2026-06-19-0930",
                    "stage: monitor",
                    "stage_run_id: monitor-2026-06-19-0930",
                    "attempt_id: monitor-2026-06-19T073000Z-abc123",
                    "logical_date: 2026-06-19",
                    "run_slot: 0930",
                    "monitor_scope: framework-sources",
                    f"monitor_scope_sha256: {scope_hash}",
                    "model_route: quality_first",
                    "model_label: fixture-model",
                    "reasoning_effort: high",
                    "execution_mode: standard",
                    "timezone: Europe/Vienna",
                    "started_at_utc: 2026-06-19T07:30:00Z",
                    "completed_at_utc: 2026-06-19T07:45:00Z",
                    "status: pass",
                    "source_status: pass",
                    "workspace_status: clean",
                    "external_reviewer_status: not_needed",
                    "external_reviewer_packet_scope: none",
                    "inaccessible_source_count: 0",
                    "unresolved_inaccessible_source_count: 0",
                    "source_root_coverage_count: 0",
                    "",
                    "# Monitor",
                ]
            )
            + "\n"
        ).encode("utf-8")
        changed = initial.replace(b"status: pass", b"status: pending")

        with tempfile.TemporaryDirectory() as temp_dir:
            artifacts_root = Path(temp_dir) / "review_artifacts"
            monitor = artifacts_root / "source_monitor" / "2026-06-19_0930.md"
            monitor.parent.mkdir(parents=True)
            monitor.write_bytes(initial)
            observed: list[bytes] = []

            def validate(
                _path: Path,
                _stage: str,
                **kwargs: object,
            ) -> dict[str, object]:
                artifact_bytes = kwargs.get("artifact_bytes")
                self.assertIsInstance(artifact_bytes, bytes)
                observed.append(cast(bytes, artifact_bytes))
                monitor.write_bytes(changed)
                return {"errors": []}

            with mock.patch.object(
                source_chain_artifact_lint,
                "validate_artifact",
                side_effect=validate,
            ):
                summary = artifact_summary(
                    artifacts_root,
                    "monitor",
                    "2026-06-19",
                    "0930",
                    scope_hash,
                    "quality_first",
                )

            self.assertEqual("pass", summary["status"])
            self.assertEqual(hashlib.sha256(initial).hexdigest(), summary["sha256"])

            monitor.write_bytes(initial)
            with mock.patch.object(
                source_chain_artifact_lint,
                "validate_artifact",
                side_effect=validate,
            ):
                decision = current_slot_decision(
                    monitor,
                    "monitor",
                    expected_scope_sha256=scope_hash,
                    expected_model_route="quality_first",
                )

        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertEqual("skip_current_slot_complete", decision["action"])
        self.assertEqual([initial, initial], observed)

    def test_artifact_validation_reuses_one_predecessor_snapshot(self) -> None:
        decision = "\n".join(
            [
                "finding_id: accepted-source-entry-1",
                f"finding_hash: {'a' * 64}",
                "classification: accept-source-entry",
                "apply_mode: auto",
                "change_class: source-entry-content",
                "source_tier: [official-doc]",
                "source_role: evidence-url",
                "quality_gate: primary_verified",
                "durable_abstraction: Verified source metadata should update the bounded source record.",
                "applicability: Applies to the checked source family and approved monitor root.",
                "rejected_source_specifics: Product commands and source-specific workflow details are rejected.",
                "affected_files:",
                "  - local_overlays/references/security_sources.md",
                "risk: low",
                "evidence:",
                "  - official source checked 2026-06-19",
                "evidence_url: https://example.com/security/advisory",
                "monitor_root: https://example.com/security/",
                "root_decision: monitor",
                "required_verification:",
                "  - uv run python -B scripts/check_reference_freshness.py",
            ]
        )
        review_text = (
            "\n".join(
                [
                    "stage: review",
                    "status: pass",
                    "input_monitor_state: missing",
                    "inaccessible_source_count: 0",
                    "unresolved_inaccessible_source_count: 0",
                    "accepted_findings: 1",
                    "manual_findings: 0",
                    "rejected_findings: 0",
                    "",
                    decision,
                ]
            )
            + "\n"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            review = (
                root
                / "review_artifacts"
                / "source_review"
                / "2026-06-19_0930.md"
            )
            apply = (
                root
                / "review_artifacts"
                / "source_apply"
                / "2026-06-19_0930.md"
            )
            review.parent.mkdir(parents=True)
            apply.parent.mkdir(parents=True)
            review.write_text(review_text, encoding="utf-8")
            review_hash = hashlib.sha256(review_text.encode("utf-8")).hexdigest()
            apply.write_text(
                "\n".join(
                    [
                        "stage: apply",
                        "chain_id: source-2026-06-19-0930",
                        "stage_run_id: apply-2026-06-19-0930",
                        "logical_date: 2026-06-19",
                        "run_slot: 0930",
                        "model_route: quality_first",
                        "timezone: Europe/Vienna",
                        "status: pass",
                        "input_review_state: resolved",
                        "input_review_artifact: review_artifacts/source_review/2026-06-19_0930.md",
                        "input_review_stage_run_id: review-2026-06-19-0930",
                        "input_review_attempt_id: review-2026-06-19T043000Z-abc123",
                        f"input_review_sha256: {review_hash}",
                        "changed_files:",
                        "  - private/references/prompt_engineering_sources.md",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            real_read = source_chain_artifact_lint.read_artifact_bytes
            review_key = source_chain_artifact_lint.artifact_snapshot_key(review)
            review_reads = 0

            def read_then_remove(path: Path, *, description: str) -> bytes:
                nonlocal review_reads
                if source_chain_artifact_lint.artifact_snapshot_key(path) == review_key:
                    review_reads += 1
                raw = real_read(path, description=description)
                if review_reads == 1 and review.exists():
                    review.unlink()
                return raw

            with mock.patch.object(
                source_chain_artifact_lint,
                "read_artifact_bytes",
                side_effect=read_then_remove,
            ):
                report = validate_artifact(apply, "apply")

        self.assertEqual(1, review_reads)
        self.assertTrue(
            any(
                "changed_files item is not covered" in error
                for error in string_items(report["errors"])
            ),
            report,
        )

    def test_preflight_classifies_other_slot_from_one_snapshot(self) -> None:
        scope = "framework-sources"
        scope_hash = source_chain_artifact_lint.monitor_scope_sha256(scope)
        initial = b"initial snapshot"
        changed = b"changed snapshot"
        header = {
            "artifact_schema_version": "6",
            "chain_id": "source-2026-06-19-0900",
            "stage_run_id": "monitor-2026-06-19-0900",
            "run_slot": "0900",
            "monitor_scope": scope,
            "monitor_scope_sha256": scope_hash,
            "status": "pass",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            artifacts_root = Path(temp_dir) / "review_artifacts"
            other_slot = (
                artifacts_root / "source_monitor" / "2026-06-19_0900.md"
            )
            other_slot.parent.mkdir(parents=True)
            other_slot.write_bytes(initial)
            snapshot_calls = 0

            def changing_snapshot(path: Path) -> tuple[bytes, dict[str, str], list[str]]:
                nonlocal snapshot_calls
                snapshot_calls += 1
                if snapshot_calls == 1:
                    path.write_bytes(changed)
                    return initial, header, []
                return changed, header, []

            def validate_snapshot(
                _path: Path,
                _stage: str,
                **kwargs: object,
            ) -> dict[str, object]:
                artifact_bytes = kwargs.get("artifact_bytes")
                return {
                    "errors": [] if artifact_bytes == initial else ["snapshot changed"]
                }

            with (
                mock.patch.object(
                    source_chain_preflight,
                    "artifact_snapshot",
                    side_effect=changing_snapshot,
                ),
                mock.patch.object(
                    source_chain_artifact_lint,
                    "validate_artifact",
                    side_effect=validate_snapshot,
                ),
            ):
                result = preflight(
                    "monitor",
                    "2026-06-19",
                    "0930",
                    scope,
                    "quality_first",
                    artifacts_root,
                )

        self.assertEqual(1, snapshot_calls)
        self.assertEqual("skip_scope_already_processed", result["action"])

    def test_source_chain_status_rejects_dangling_artifact_symlink(self) -> None:
        scope = "framework-sources"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            artifacts_root = root / "review_artifacts"
            monitor = (
                artifacts_root / "source_monitor" / "2026-06-19_0930.md"
            )
            monitor.parent.mkdir(parents=True)
            monitor.symlink_to(root / "missing-monitor.md")
            status = chain_status(
                "2026-06-19",
                "0930",
                scope,
                "quality_first",
                artifacts_root,
                "Europe/Vienna",
            )

        monitor_status = cast(list[dict[str, object]], status["stages"])[0]
        self.assertTrue(monitor_status["exists"])
        self.assertEqual("fail", monitor_status["lint_status"])
        self.assertEqual("invalid", monitor_status["status"])
        self.assertTrue(status["has_lint_errors"])
        self.assertNotIn("monitor", cast(list[object], status["missing_stages"]))

    def test_source_chain_status_summarizes_linted_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_file = root / "private" / "references" / "prompt_engineering_sources.md"
            policy_file = root / "runtime" / "operative_charter.md"
            artifacts_root = root / "review_artifacts"
            monitor = artifacts_root / "source_monitor" / "2026-06-19_0930.md"
            source_file.parent.mkdir(parents=True)
            policy_file.parent.mkdir(parents=True, exist_ok=True)
            monitor.parent.mkdir(parents=True)
            source_file.write_text("# Sources\n", encoding="utf-8")
            policy_file.write_text("# Charter\n", encoding="utf-8")
            source_hash = source_chain_artifact_lint.file_sha256(source_file)
            policy_hash = source_chain_artifact_lint.file_sha256(policy_file)
            monitor.write_text(
                "\n".join(
                    [
                        "artifact_schema_version: 6",
                        "chain_id: source-2026-06-19-0930",
                        "stage: monitor",
                        "stage_run_id: monitor-2026-06-19-0930",
                        "attempt_id: monitor-2026-06-19T090000Z-status01",
                        "logical_date: 2026-06-19",
                        "run_slot: 0930",
                        "monitor_scope: framework-sources",
                        "monitor_scope_sha256: 5b619bc978d06cba5277f7846faa48625e0ec70ba43216c35213bb6cd7f62a38",
                        "model_route: quality_first",
                        "model_label: fixture-model",
                        "reasoning_effort: high",
                        "execution_mode: standard",
                        "timezone: Europe/Vienna",
                        "started_at_utc: 2026-06-19T09:00:00Z",
                        "completed_at_utc: 2026-06-19T09:01:00Z",
                        "status: pass",
                        "source_status: pass",
                        "workspace_status: clean",
                        "external_reviewer_status: not_needed",
                        "external_reviewer_packet_scope: none",
                        "inaccessible_source_count: 0",
                        "unresolved_inaccessible_source_count: 0",
                        "source_root_coverage_count: 0",
                        "source_registry_files:",
                        "  - path: private/references/prompt_engineering_sources.md",
                        f"    sha256: {source_hash}",
                        "policy_files:",
                        "  - path: runtime/operative_charter.md",
                        f"    sha256: {policy_hash}",
                        "",
                        "# Monitor",
                    ]
                ),
                encoding="utf-8",
            )

            status = chain_status(
                "2026-06-19",
                "0930",
                "framework-sources",
                "quality_first",
                artifacts_root,
            )

        self.assertFalse(status["all_terminal"])
        self.assertFalse(status["successful"])
        self.assertEqual(["review", "apply", "assurance"], status["missing_stages"])
        stages = dict_items(status["stages"])
        self.assertEqual("pass", stages[0]["lint_status"])
        self.assertEqual("pass", stages[0]["status"])
        self.assertTrue(stages[0]["terminal"])
        self.assertEqual("missing", stages[1]["lint_status"])

    def test_source_chain_artifact_lint_rejects_run_slot_path_mismatch(self) -> None:
        digest = "d" * 64
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            monitor = root / "review_artifacts" / "source_monitor" / "2026-06-19.md"
            monitor.parent.mkdir(parents=True)
            monitor.write_text(
                "\n".join(
                    [
                        "artifact_schema_version: 6",
                        "chain_id: source-2026-06-19-0930",
                        "stage: monitor",
                        "stage_run_id: monitor-2026-06-19-0930",
                        "attempt_id: monitor-2026-06-19T023000Z-abc123",
                        "logical_date: 2026-06-19",
                        "run_slot: 0930",
                        "monitor_scope: framework-sources",
                        "monitor_scope_sha256: 5b619bc978d06cba5277f7846faa48625e0ec70ba43216c35213bb6cd7f62a38",
                        "model_route: quality_first",
                        "model_label: fixture-model",
                        "reasoning_effort: high",
                        "execution_mode: standard",
                        "timezone: Europe/Vienna",
                        "started_at_utc: 2026-06-19T00:30:00Z",
                        "completed_at_utc: 2026-06-19T00:52:00Z",
                        "status: pass",
                        "source_status: pass",
                        "workspace_status: clean",
                        "external_reviewer_status: considered_skipped",
                        "external_reviewer_packet_scope: none",
                        "inaccessible_source_count: 0",
                        "unresolved_inaccessible_source_count: 0",
                        "source_root_coverage_count: 0",
                        "source_registry_files:",
                        "  - path: local_overlays/references/security_sources.md",
                        f"    sha256: {digest}",
                        "policy_files:",
                        "  - path: local_overlays/source_monitor_policy.md",
                        f"    sha256: {digest}",
                        "",
                        "# Monitor",
                    ]
                ),
                encoding="utf-8",
            )

            report = validate_artifact(monitor, "monitor")

        self.assertTrue(
            any(
                "artifact path must end with source_monitor/2026-06-19_0930.md" in error
                for error in string_items(report["errors"])
            )
        )

    def test_source_chain_preflight_skips_current_slot_and_ignores_date_only_filename(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_file = root / "local_overlays" / "references" / "security_sources.md"
            policy_file = root / "local_overlays" / "source_monitor_policy.md"
            artifacts_root = root / "review_artifacts"
            current_monitor = artifacts_root / "source_monitor" / "2026-06-19_0930.md"
            source_file.parent.mkdir(parents=True)
            policy_file.parent.mkdir(parents=True, exist_ok=True)
            current_monitor.parent.mkdir(parents=True)
            source_file.write_text("# Sources\n", encoding="utf-8")
            policy_file.write_text("# Policy\n", encoding="utf-8")
            source_hash = source_chain_artifact_lint.file_sha256(source_file)
            policy_hash = source_chain_artifact_lint.file_sha256(policy_file)
            current_monitor.write_text(
                "\n".join(
                    [
                        "artifact_schema_version: 6",
                        "chain_id: source-2026-06-19-0930",
                        "stage: monitor",
                        "stage_run_id: monitor-2026-06-19-0930",
                        "attempt_id: monitor-2026-06-19T073000Z-abc123",
                        "logical_date: 2026-06-19",
                        "run_slot: 0930",
                        "monitor_scope: framework-sources",
                        "monitor_scope_sha256: 5b619bc978d06cba5277f7846faa48625e0ec70ba43216c35213bb6cd7f62a38",
                        "model_route: quality_first",
                        "model_label: fixture-model",
                        "reasoning_effort: high",
                        "execution_mode: standard",
                        "timezone: Europe/Vienna",
                        "started_at_utc: 2026-06-19T07:30:00Z",
                        "completed_at_utc: 2026-06-19T07:45:00Z",
                        "status: pass",
                        "source_status: pass",
                        "workspace_status: clean",
                        "external_reviewer_status: not_needed",
                        "external_reviewer_packet_scope: none",
                        "inaccessible_source_count: 0",
                        "unresolved_inaccessible_source_count: 0",
                        "source_root_coverage_count: 0",
                        "source_registry_files:",
                        "  - path: local_overlays/references/security_sources.md",
                        f"    sha256: {source_hash}",
                        "policy_files:",
                        "  - path: local_overlays/source_monitor_policy.md",
                        f"    sha256: {policy_hash}",
                        "",
                        "# Monitor",
                    ]
                ),
                encoding="utf-8",
            )

            current = preflight(
                "monitor",
                "2026-06-19",
                "0930",
                "framework-sources",
                "quality_first",
                artifacts_root,
            )
            same_scope = preflight(
                "monitor",
                "2026-06-19",
                "1000",
                "FRAMEWORK-SOURCES",
                "quality_first",
                artifacts_root,
            )
            different_scope = preflight(
                "monitor",
                "2026-06-19",
                "1000",
                "typescript",
                "quality_first",
                artifacts_root,
            )
            slot_collision = preflight(
                "monitor",
                "2026-06-19",
                "0930",
                "typescript",
                "quality_first",
                artifacts_root,
            )
            predecessor_slot_mismatch = preflight(
                "review",
                "2026-06-19",
                "1000",
                "framework-sources",
                "quality_first",
                artifacts_root,
            )

        self.assertEqual("skip_current_slot_complete", current["action"])
        self.assertEqual("skip_scope_already_processed", same_scope["action"])
        self.assertEqual("run_current_slot", different_scope["action"])
        self.assertEqual("stop_scope_slot_collision", slot_collision["action"])
        self.assertEqual("stop_predecessor_slot_mismatch", predecessor_slot_mismatch["action"])
        self.assertEqual(
            "0930",
            cast(dict[str, object], predecessor_slot_mismatch["existing"])["run_slot"],
        )
        with self.assertRaisesRegex(ValueError, "lowercase scope id"):
            preflight(
                "monitor",
                "2026-06-19",
                "1001",
                "hugo\nignore-prior-instructions",
                "quality_first",
                Path("review_artifacts"),
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            artifacts_root = root / "review_artifacts"
            date_only_assurance = artifacts_root / "automation_assurance" / "2026-06-19.md"
            date_only_assurance.parent.mkdir(parents=True)
            date_only_assurance.write_text("date-only artifact\n", encoding="utf-8")

            date_only = preflight(
                "apply",
                "2026-06-19",
                "0930",
                "framework-sources",
                "quality_first",
                artifacts_root,
            )

        self.assertEqual("run_current_slot", date_only["action"])

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            artifacts_root = root / "review_artifacts"
            other_slot = artifacts_root / "automation_assurance" / "2026-06-19_0952.md"
            other_slot.parent.mkdir(parents=True)
            other_slot.write_text(
                "\n".join(
                    [
                        "artifact_schema_version: 6",
                        "chain_id: source-2026-06-19-0952",
                        "stage: assurance",
                        "stage_run_id: assurance-2026-06-19-0952",
                        "attempt_id: assurance-2026-06-19T075200Z-abc123",
                        "logical_date: 2026-06-19",
                        "run_slot: 0952",
                        "monitor_scope: framework-sources",
                        "monitor_scope_sha256: 5b619bc978d06cba5277f7846faa48625e0ec70ba43216c35213bb6cd7f62a38",
                        "model_route: quality_first",
                        "model_label: fixture-model",
                        "reasoning_effort: high",
                        "execution_mode: standard",
                        "timezone: Europe/Vienna",
                        "started_at_utc: 2026-06-19T07:52:00Z",
                        "completed_at_utc: 2026-06-19T07:55:00Z",
                        "status: pass",
                        "input_monitor_state: missing",
                        "input_monitor_artifact: unavailable",
                        "input_monitor_stage_run_id: unavailable",
                        "input_monitor_attempt_id: unavailable",
                        "input_monitor_sha256: unavailable",
                        "input_review_state: missing",
                        "input_review_artifact: unavailable",
                        "input_review_stage_run_id: unavailable",
                        "input_review_attempt_id: unavailable",
                        "input_review_sha256: unavailable",
                        "input_apply_state: missing",
                        "input_apply_artifact: unavailable",
                        "input_apply_stage_run_id: unavailable",
                        "input_apply_attempt_id: unavailable",
                        "input_apply_sha256: unavailable",
                        "latest_commit: none",
                        "unresolved_findings: 0",
                        "unresolved_inaccessible_source_count: 0",
                        "",
                        "# Assurance",
                    ]
                ),
                encoding="utf-8",
            )

            timed = preflight(
                "review",
                "2026-06-19",
                "0930",
                "framework-sources",
                "quality_first",
                artifacts_root,
            )

        self.assertEqual("stop_invalid_same_scope_artifact", timed["action"])
        timed_artifact = cast(dict[str, object], timed["existing"])
        self.assertEqual("assurance", timed_artifact["stage"])
        self.assertEqual("0952", timed_artifact["run_slot"])
        self.assertTrue(
            any(
                "input_monitor_state must be resolved when assurance status is pass" in error
                for error in string_items(timed_artifact["errors"])
            )
        )

    def test_source_chain_preflight_requires_explicit_repair_and_preserves_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            artifacts_root = root / "review_artifacts"
            current_monitor = (
                artifacts_root / "source_monitor" / "2026-06-19_0930.md"
            )
            current_monitor.parent.mkdir(parents=True)
            current_monitor.write_text(monitor_artifact_fixture(), encoding="utf-8")
            original_bytes = current_monitor.read_bytes()

            ordinary = preflight(
                "monitor",
                "2026-06-19",
                "0930",
                "framework-sources",
                "quality_first",
                artifacts_root,
            )
            repair = preflight(
                "monitor",
                "2026-06-19",
                "0930",
                "framework-sources",
                "quality_first",
                artifacts_root,
                repair_current_slot=True,
            )

            self.assertEqual(original_bytes, current_monitor.read_bytes())

        self.assertEqual("skip_current_slot_complete", ordinary["action"])
        self.assertEqual("repair_current_slot_authorized", repair["action"])
        self.assertIs(repair["repair_authorized"], True)
        self.assertIs(repair["repair_required"], True)
        self.assertEqual("pass", repair["existing_status"])
        self.assertEqual(
            hashlib.sha256(original_bytes).hexdigest(),
            repair["repair_preimage_sha256"],
        )
        self.assertEqual(
            "monitor-2026-06-19-0930",
            repair["repair_preimage_stage_run_id"],
        )
        self.assertEqual(
            "monitor-2026-06-19T023000Z-abc123",
            repair["repair_preimage_attempt_id"],
        )
        self.assertEqual("none", repair["preflight_mutation"])
        self.assertEqual(
            "compare_and_replace_the_bound_current_slot_preimage",
            repair["worker_action"],
        )

    def test_source_chain_preflight_repair_fails_closed_for_missing_invalid_and_wrong_scope(self) -> None:
        scope = "framework-sources"
        other_scope = "typescript"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            artifacts_root = root / "review_artifacts"
            current_monitor = (
                artifacts_root / "source_monitor" / "2026-06-19_0930.md"
            )
            current_monitor.parent.mkdir(parents=True)

            missing = preflight(
                "monitor",
                "2026-06-19",
                "0930",
                scope,
                "quality_first",
                artifacts_root,
                repair_current_slot=True,
            )

            current_monitor.write_text(
                monitor_artifact_fixture(status="pending"),
                encoding="utf-8",
            )
            invalid_bytes = current_monitor.read_bytes()
            invalid = preflight(
                "monitor",
                "2026-06-19",
                "0930",
                scope,
                "quality_first",
                artifacts_root,
                repair_current_slot=True,
            )
            self.assertEqual(invalid_bytes, current_monitor.read_bytes())

            current_monitor.write_text(
                monitor_artifact_fixture(
                    monitor_scope=other_scope,
                    monitor_scope_sha256=(
                        source_chain_artifact_lint.monitor_scope_sha256(other_scope)
                    ),
                ),
                encoding="utf-8",
            )
            collision_bytes = current_monitor.read_bytes()
            collision = preflight(
                "monitor",
                "2026-06-19",
                "0930",
                scope,
                "quality_first",
                artifacts_root,
                repair_current_slot=True,
            )
            self.assertEqual(collision_bytes, current_monitor.read_bytes())

        self.assertEqual("stop_repair_current_slot_missing", missing["action"])
        self.assertEqual("stop_invalid_current_slot_artifact", invalid["action"])
        self.assertEqual("stop_scope_slot_collision", collision["action"])

    def test_source_chain_preflight_repair_keeps_predecessor_slot_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            artifacts_root = root / "review_artifacts"
            current_monitor = (
                artifacts_root / "source_monitor" / "2026-06-19_0930.md"
            )
            other_monitor = (
                artifacts_root / "source_monitor" / "2026-06-19_0900.md"
            )
            current_review = (
                artifacts_root / "source_review" / "2026-06-19_0930.md"
            )
            current_monitor.parent.mkdir(parents=True)
            current_review.parent.mkdir(parents=True)
            current_monitor.write_text(monitor_artifact_fixture(), encoding="utf-8")
            current_review.write_text(
                review_artifact_fixture(
                    input_monitor_sha256=hashlib.sha256(
                        current_monitor.read_bytes()
                    ).hexdigest()
                ),
                encoding="utf-8",
            )
            other_monitor.write_text(
                monitor_artifact_fixture(
                    chain_id="source-2026-06-19-0900",
                    stage_run_id="monitor-2026-06-19-0900",
                    attempt_id="monitor-2026-06-19T020000Z-abc123",
                    run_slot="0900",
                ),
                encoding="utf-8",
            )
            review_bytes = current_review.read_bytes()

            result = preflight(
                "review",
                "2026-06-19",
                "0930",
                "framework-sources",
                "quality_first",
                artifacts_root,
                repair_current_slot=True,
            )
            self.assertEqual(review_bytes, current_review.read_bytes())

        self.assertEqual("stop_predecessor_slot_mismatch", result["action"])
        existing = cast(dict[str, object], result["existing"])
        self.assertEqual("monitor", existing["stage"])
        self.assertEqual("0900", existing["run_slot"])

    def test_source_chain_preflight_repair_rejects_same_slot_successor(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            artifacts_root = root / "review_artifacts"
            current_monitor = (
                artifacts_root / "source_monitor" / "2026-06-19_0930.md"
            )
            current_review = (
                artifacts_root / "source_review" / "2026-06-19_0930.md"
            )
            current_monitor.parent.mkdir(parents=True)
            current_review.parent.mkdir(parents=True)
            current_monitor.write_text(monitor_artifact_fixture(), encoding="utf-8")
            current_review.write_text(
                review_artifact_fixture(
                    input_monitor_sha256=hashlib.sha256(
                        current_monitor.read_bytes()
                    ).hexdigest()
                ),
                encoding="utf-8",
            )
            monitor_bytes = current_monitor.read_bytes()
            review_bytes = current_review.read_bytes()

            result = preflight(
                "monitor",
                "2026-06-19",
                "0930",
                "framework-sources",
                "quality_first",
                artifacts_root,
                repair_current_slot=True,
            )

            self.assertEqual(monitor_bytes, current_monitor.read_bytes())
            self.assertEqual(review_bytes, current_review.read_bytes())

        self.assertEqual(
            "stop_repair_current_slot_successor_exists",
            result["action"],
        )
        self.assertEqual("review", result["successor_stage"])
        existing = cast(dict[str, object], result["existing"])
        self.assertEqual("skip_current_slot_complete", existing["action"])

    def test_source_chain_preflight_rejects_unsafe_output_and_invalid_scope_claim(self) -> None:
        route = "quality_first"
        scope = "framework-sources"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            artifacts_root = root / "review_artifacts"
            outside = root / "outside"
            artifacts_root.mkdir()
            outside.mkdir()
            (artifacts_root / "source_monitor").symlink_to(
                outside,
                target_is_directory=True,
            )
            stage_symlink = preflight(
                "monitor",
                "2026-06-19",
                "0930",
                scope,
                route,
                artifacts_root,
                "Europe/Vienna",
            )

        self.assertEqual("stop_unsafe_output_path", stage_symlink["action"])

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            artifacts_root = root / "review_artifacts"
            stage_root = artifacts_root / "source_monitor"
            stage_root.mkdir(parents=True)
            (stage_root / "2026-06-19_0930.md").symlink_to(root / "missing.md")
            broken_final = preflight(
                "monitor",
                "2026-06-19",
                "0930",
                scope,
                route,
                artifacts_root,
                "Europe/Vienna",
            )

        self.assertEqual("stop_unsafe_output_path", broken_final["action"])

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            artifacts_root = root / "review_artifacts"
            stage_root = artifacts_root / "source_monitor"
            stage_root.mkdir(parents=True)
            outside = root / "outside.md"
            outside.write_text("outside bytes\n", encoding="utf-8")
            (stage_root / "2026-06-19_0930.md").symlink_to(outside)
            with mock.patch.object(
                source_chain_artifact_lint,
                "file_sha256",
                side_effect=AssertionError("unsafe target must not be hashed"),
            ) as hash_call:
                symlink_status = artifact_summary(
                    artifacts_root,
                    "monitor",
                    "2026-06-19",
                    "0930",
                    source_chain_artifact_lint.monitor_scope_sha256(scope),
                    route,
                    "Europe/Vienna",
                )

        self.assertEqual("fail", symlink_status["lint_status"])
        self.assertEqual("invalid", symlink_status["status"])
        hash_call.assert_not_called()

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            artifact = (
                root
                / "review_artifacts"
                / "source_monitor"
                / "2026-06-19_0930.md"
            )
            artifact.parent.mkdir(parents=True)
            artifact.write_text(
                "monitor_scope_sha256: " + "f" * 64 + "\n",
                encoding="utf-8",
            )
            invalid_claim = preflight(
                "monitor",
                "2026-06-19",
                "0930",
                scope,
                route,
                root / "review_artifacts",
                "Europe/Vienna",
            )

        self.assertEqual("stop_invalid_current_slot_artifact", invalid_claim["action"])

    def test_source_chain_artifact_lint_rejects_bad_monitor_status_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            monitor = root / "bad-monitor.md"
            monitor.write_text(
                monitor_artifact_fixture(
                    source_status="dirty",
                    workspace_status="pass",
                ),
                encoding="utf-8",
            )

            report = validate_artifact(monitor, "monitor")

        errors = string_items(report["errors"])
        self.assertTrue(any("source_status must be one of" in error for error in errors))
        self.assertTrue(any("workspace_status must be one of" in error for error in errors))

    def test_source_chain_artifact_lint_rejects_inconsistent_monitor_source_status(self) -> None:
        digest = "f" * 64
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            monitor = root / "bad-monitor.md"
            monitor.write_text(
                "\n".join(
                    [
                        "artifact_schema_version: 6",
                        "chain_id: source-2026-06-19-0930",
                        "stage: monitor",
                        "stage_run_id: monitor-2026-06-19-0930",
                        "attempt_id: monitor-2026-06-19T023000Z-abc123",
                        "logical_date: 2026-06-19",
                        "run_slot: 0930",
                        "monitor_scope: framework-sources",
                        "monitor_scope_sha256: 5b619bc978d06cba5277f7846faa48625e0ec70ba43216c35213bb6cd7f62a38",
                        "model_route: quality_first",
                        "model_label: fixture-model",
                        "reasoning_effort: high",
                        "execution_mode: standard",
                        "timezone: Europe/Vienna",
                        "started_at_utc: 2026-06-19T00:30:00Z",
                        "completed_at_utc: 2026-06-19T00:52:00Z",
                        "status: pass",
                        "source_status: partial",
                        "workspace_status: clean",
                        "external_reviewer_status: considered_skipped",
                        "external_reviewer_packet_scope: none",
                        "inaccessible_source_count: 0",
                        "unresolved_inaccessible_source_count: 0",
                        "source_root_coverage_count: 0",
                        "source_registry_files:",
                        "  - path: local_overlays/references/security_sources.md",
                        f"    sha256: {digest}",
                        "policy_files:",
                        "  - path: local_overlays/source_monitor_policy.md",
                        f"    sha256: {digest}",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            report = validate_artifact(monitor, "monitor")

        errors = string_items(report["errors"])
        self.assertTrue(any("source_status partial is inconsistent with monitor status pass" in error for error in errors))

    def test_source_chain_artifact_lint_tracks_inaccessible_sources(self) -> None:
        digest = "9" * 64

        def monitor_text(
            *,
            source_status: str,
            inaccessible_count: int,
            unresolved_count: int,
            coverage_status: str,
            url: str = "https://agency.example/news/directives",
            alternate_primary_url: str = "none",
        ) -> str:
            return "\n".join(
                [
                    "artifact_schema_version: 6",
                    "chain_id: source-2026-06-19-0930",
                    "stage: monitor",
                    "stage_run_id: monitor-2026-06-19-0930",
                    "attempt_id: monitor-2026-06-19T023000Z-abc123",
                    "logical_date: 2026-06-19",
                        "run_slot: 0930",
                        "monitor_scope: framework-sources",
                        "monitor_scope_sha256: 5b619bc978d06cba5277f7846faa48625e0ec70ba43216c35213bb6cd7f62a38",
                        "model_route: quality_first",
                        "model_label: fixture-model",
                        "reasoning_effort: high",
                        "execution_mode: standard",
                    "timezone: Europe/Vienna",
                    "started_at_utc: 2026-06-19T00:30:00Z",
                    "completed_at_utc: 2026-06-19T00:52:00Z",
                    "status: pass",
                    f"source_status: {source_status}",
                    "workspace_status: clean",
                    "external_reviewer_status: considered_skipped",
                    "external_reviewer_packet_scope: none",
                    f"inaccessible_source_count: {inaccessible_count}",
                    f"unresolved_inaccessible_source_count: {unresolved_count}",
                    "source_root_coverage_count: 0",
                    "source_registry_files:",
                    "  - path: local_overlays/references/security_sources.md",
                    f"    sha256: {digest}",
                    "policy_files:",
                    "  - path: local_overlays/source_monitor_policy.md",
                    f"    sha256: {digest}",
                    "",
                    "## Inaccessible Sources",
                    "source_ref: agency-directives",
                    "target_kind: root",
                    f"url: {url}",
                    "failure_kind: http_error",
                    "failure_detail: HTTP 403",
                    f"coverage_status: {coverage_status}",
                    f"alternate_primary_url: {alternate_primary_url}",
                ]
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            alternate = root / "alternate.md"
            unresolved = root / "unresolved.md"
            insecure = root / "insecure.md"
            unsafe = root / "unsafe.md"
            localhost = root / "localhost.md"
            linklocal = root / "linklocal.md"
            legacy_ipv4 = root / "legacy_ipv4.md"
            alternate.write_text(
                monitor_text(
                    source_status="no-findings",
                    inaccessible_count=1,
                    unresolved_count=0,
                    coverage_status="primary_alternate_verified",
                    alternate_primary_url="https://agency.example/resources/software-guidance",
                ),
                encoding="utf-8",
            )
            unresolved.write_text(
                monitor_text(
                    source_status="no-findings",
                    inaccessible_count=1,
                    unresolved_count=1,
                    coverage_status="unresolved",
                ),
                encoding="utf-8",
            )
            insecure.write_text(
                monitor_text(
                    source_status="pass",
                    inaccessible_count=1,
                    unresolved_count=1,
                    coverage_status="unresolved",
                    url="http://example.com/blocked",
                ),
                encoding="utf-8",
            )
            unsafe.write_text(
                monitor_text(
                    source_status="pass",
                    inaccessible_count=1,
                    unresolved_count=1,
                    coverage_status="unresolved",
                    url="https://user:" + "token@example.com/blocked",
                ),
                encoding="utf-8",
            )
            localhost.write_text(
                monitor_text(
                    source_status="pass",
                    inaccessible_count=1,
                    unresolved_count=1,
                    coverage_status="unresolved",
                    url="https://localhost/status",
                ),
                encoding="utf-8",
            )
            linklocal.write_text(
                monitor_text(
                    source_status="pass",
                    inaccessible_count=1,
                    unresolved_count=1,
                    coverage_status="unresolved",
                    url="https://169.254.169.254/latest/meta-data",
                ),
                encoding="utf-8",
            )
            legacy_ipv4.write_text(
                monitor_text(
                    source_status="pass",
                    inaccessible_count=1,
                    unresolved_count=1,
                    coverage_status="unresolved",
                    url="https://2130706433/latest/meta-data",
                ),
                encoding="utf-8",
            )

            alternate_report = validate_artifact(alternate, "monitor")
            unresolved_report = validate_artifact(unresolved, "monitor")
            insecure_report = validate_artifact(insecure, "monitor")
            unsafe_report = validate_artifact(unsafe, "monitor")
            localhost_report = validate_artifact(localhost, "monitor")
            linklocal_report = validate_artifact(linklocal, "monitor")
            legacy_ipv4_report = validate_artifact(legacy_ipv4, "monitor")

        self.assertEqual([], alternate_report["errors"])
        self.assertTrue(
            any("source_status no-findings is invalid" in error for error in string_items(unresolved_report["errors"]))
        )
        self.assertTrue(any("expected https URL" in error for error in string_items(insecure_report["errors"])))
        self.assertTrue(any("credentials are not allowed" in error for error in string_items(unsafe_report["errors"])))
        self.assertTrue(any("localhost" in error for error in string_items(localhost_report["errors"])))
        self.assertTrue(any("non-public address" in error for error in string_items(linklocal_report["errors"])))
        self.assertTrue(any("non-public address" in error for error in string_items(legacy_ipv4_report["errors"])))

    def test_source_chain_artifact_lint_rejects_review_evidence_from_unresolved_source(self) -> None:
        digest = "8" * 64
        evidence_url = "https://agency.example/news/directives/bulletin-26-04"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            monitor = root / "review_artifacts" / "source_monitor" / "2026-06-19_0930.md"
            no_findings_monitor = root / "review_artifacts" / "source_monitor" / "2026-06-19_1000.md"
            review = root / "review_artifacts" / "source_review" / "2026-06-19_0930.md"
            no_findings_review = root / "review_artifacts" / "source_review" / "2026-06-19_1000.md"
            monitor.parent.mkdir(parents=True)
            review.parent.mkdir(parents=True)
            monitor.write_text(
                "\n".join(
                    [
                        "artifact_schema_version: 6",
                        "chain_id: source-2026-06-19-0930",
                        "stage: monitor",
                        "stage_run_id: monitor-2026-06-19-0930",
                        "attempt_id: monitor-2026-06-19T023000Z-abc123",
                        "logical_date: 2026-06-19",
                        "run_slot: 0930",
                        "monitor_scope: framework-sources",
                        "monitor_scope_sha256: 5b619bc978d06cba5277f7846faa48625e0ec70ba43216c35213bb6cd7f62a38",
                        "model_route: quality_first",
                        "model_label: fixture-model",
                        "reasoning_effort: high",
                        "execution_mode: standard",
                        "timezone: Europe/Vienna",
                        "started_at_utc: 2026-06-19T00:30:00Z",
                        "completed_at_utc: 2026-06-19T00:52:00Z",
                        "status: pass",
                        "source_status: pass",
                        "workspace_status: clean",
                        "external_reviewer_status: not_needed",
                        "external_reviewer_packet_scope: none",
                        "inaccessible_source_count: 1",
                        "unresolved_inaccessible_source_count: 1",
                        "source_root_coverage_count: 0",
                        "source_registry_files:",
                        "  - path: local_overlays/references/security_sources.md",
                        f"    sha256: {digest}",
                        "policy_files:",
                        "  - path: local_overlays/source_monitor_policy.md",
                        f"    sha256: {digest}",
                        "",
                        "## Inaccessible Sources",
                        "source_ref: agency-bulletin-26-04",
                        "target_kind: link",
                        f"url: {evidence_url}",
                        "failure_kind: http_error",
                        "failure_detail: HTTP 403",
                        "coverage_status: unresolved",
                        "alternate_primary_url: none",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            no_findings_monitor.write_text(
                monitor.read_text(encoding="utf-8")
                .replace("source-2026-06-19-0930", "source-2026-06-19-1000")
                .replace("monitor-2026-06-19-0930", "monitor-2026-06-19-1000")
                .replace("monitor-2026-06-19T023000Z-abc123", "monitor-2026-06-19T033000Z-abc123")
                .replace("run_slot: 0930", "run_slot: 1000"),
                encoding="utf-8",
            )
            monitor_hash = source_chain_artifact_lint.file_sha256(monitor)
            no_findings_monitor_hash = source_chain_artifact_lint.file_sha256(no_findings_monitor)
            no_findings_review.write_text(
                "\n".join(
                    [
                        "artifact_schema_version: 6",
                        "chain_id: source-2026-06-19-1000",
                        "stage: review",
                        "stage_run_id: review-2026-06-19-1000",
                        "attempt_id: review-2026-06-19T053000Z-abc123",
                        "logical_date: 2026-06-19",
                        "run_slot: 1000",
                        "monitor_scope: framework-sources",
                        "monitor_scope_sha256: 5b619bc978d06cba5277f7846faa48625e0ec70ba43216c35213bb6cd7f62a38",
                        "model_route: quality_first",
                        "model_label: fixture-model",
                        "reasoning_effort: high",
                        "execution_mode: standard",
                        "timezone: Europe/Vienna",
                        "started_at_utc: 2026-06-19T03:30:00Z",
                        "completed_at_utc: 2026-06-19T03:45:00Z",
                        "status: no-findings",
                        "external_reviewer_status: not_needed",
                        "external_reviewer_packet_scope: none",
                        "input_monitor_state: resolved",
                        "input_monitor_artifact: review_artifacts/source_monitor/2026-06-19_1000.md",
                        "input_monitor_stage_run_id: monitor-2026-06-19-1000",
                        "input_monitor_attempt_id: monitor-2026-06-19T033000Z-abc123",
                        f"input_monitor_sha256: {no_findings_monitor_hash}",
                        "inaccessible_source_count: 0",
                        "unresolved_inaccessible_source_count: 0",
                        "accepted_findings: 0",
                        "manual_findings: 0",
                        "rejected_findings: 0",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            review.write_text(
                "\n".join(
                    [
                        "artifact_schema_version: 6",
                        "chain_id: source-2026-06-19-0930",
                        "stage: review",
                        "stage_run_id: review-2026-06-19-0930",
                        "attempt_id: review-2026-06-19T043000Z-abc123",
                        "logical_date: 2026-06-19",
                        "run_slot: 0930",
                        "monitor_scope: framework-sources",
                        "monitor_scope_sha256: 5b619bc978d06cba5277f7846faa48625e0ec70ba43216c35213bb6cd7f62a38",
                        "model_route: quality_first",
                        "model_label: fixture-model",
                        "reasoning_effort: high",
                        "execution_mode: standard",
                        "timezone: Europe/Vienna",
                        "started_at_utc: 2026-06-19T02:30:00Z",
                        "completed_at_utc: 2026-06-19T02:45:00Z",
                        "status: pass",
                        "external_reviewer_status: not_needed",
                        "external_reviewer_packet_scope: none",
                        "input_monitor_state: resolved",
                        "input_monitor_artifact: review_artifacts/source_monitor/2026-06-19_0930.md",
                        "input_monitor_stage_run_id: monitor-2026-06-19-0930",
                        "input_monitor_attempt_id: monitor-2026-06-19T023000Z-abc123",
                        f"input_monitor_sha256: {monitor_hash}",
                        "inaccessible_source_count: 0",
                        "unresolved_inaccessible_source_count: 0",
                        "accepted_findings: 1",
                        "manual_findings: 0",
                        "rejected_findings: 0",
                        "",
                        "## Accepted Findings",
                        "finding_id: accepted-1",
                        f"finding_hash: {digest}",
                        "classification: accept-source-entry",
                        "apply_mode: auto",
                        "change_class: source-entry-content",
                        "source_tier: [official-doc]",
                        "source_role: evidence-url",
                        "quality_gate: primary_verified",
                        "durable_abstraction: The blocked source cannot support a finding without independent source evidence.",
                        "applicability: Applies to accepted review findings whose evidence URL had an unresolved access gap.",
                        "rejected_source_specifics: The unresolved source text is not used as authority.",
                        "affected_files:",
                        "  - local_overlays/references/security_sources.md",
                        "risk: low",
                        "evidence:",
                        "  - blocked source was not independently verified",
                        f"evidence_url: {evidence_url}",
                        "monitor_root: https://agency.example/news/directives",
                        "root_decision: monitor",
                        "required_verification:",
                        "  - uv run python -B scripts/check_reference_freshness.py",
                    ]
                ),
                encoding="utf-8",
            )

            report = validate_artifact(review, "review")
            no_findings_report = validate_artifact(no_findings_review, "review")

        self.assertTrue(
            any("uses unresolved inaccessible evidence_url" in error for error in string_items(report["errors"]))
        )
        self.assertTrue(
            any(
                "review status no-findings is invalid with unresolved inaccessible sources" in error
                for error in string_items(no_findings_report["errors"])
            )
        )

    def test_source_chain_artifact_lint_rejects_unsafe_decision_urls_and_auto_classes(self) -> None:
        digest = "7" * 64

        def block(
            *,
            evidence_url: str = "https://example.com/security/advisory",
            monitor_root: str = "https://example.com/security/",
            change_class: str = "source-entry-content",
            root_decision: str = "monitor",
            classification: str = "accept-source-entry",
            source_tier: str = "[official-doc]",
        ) -> str:
            return "\n".join(
                [
                    "finding_id: accepted-1",
                    f"finding_hash: {digest}",
                    f"classification: {classification}",
                    "apply_mode: auto",
                    f"change_class: {change_class}",
                    f"source_tier: {source_tier}",
                    "source_role: evidence-url",
                    "quality_gate: primary_verified",
                    "durable_abstraction: Existing source metadata changed and should update the private source entry.",
                    "applicability: Applies only to the checked source family and its approved monitor root.",
                    "rejected_source_specifics: No tool commands, implementation details, or doctrine changes are adopted.",
                    "affected_files:",
                    "  - local_overlays/references/security_sources.md",
                    "risk: low",
                    "evidence:",
                    "  - official source checked 2026-06-19",
                    f"evidence_url: {evidence_url}",
                    f"monitor_root: {monitor_root}",
                    f"root_decision: {root_decision}",
                    "required_verification:",
                    "  - uv run python -B scripts/check_reference_freshness.py",
                ]
            )

        cases = [
            (block(evidence_url="http://169.254.169.254/latest/meta-data"), "external URL must use https"),
            (block(evidence_url="https://localhost/status"), "external URL points to localhost"),
            (block(evidence_url="//[bad"), "unsafe evidence_url"),
            (block(monitor_root="not a url"), "invalid monitor_root"),
            (block(monitor_root="https://example.com/"), "overbroad monitor_root"),
            (
                block(monitor_root="reference-only", root_decision="monitor"),
                "uses monitor_root reference-only without root_decision reference-only",
            ),
            (block(root_decision="none" + "-one-off"), "invalid root_decision"),
            (block(change_class="control-plane"), "non-auto change_class"),
            (
                block(source_tier="[commentary]", classification="accept-rule-update"),
                "uses low-authority source_tier [commentary]",
            ),
            (
                block(source_tier="[case-study]", classification="accept-test-or-validator-update"),
                "uses low-authority source_tier [case-study]",
            ),
        ]
        for text, expected in cases:
            with self.subTest(expected=expected):
                errors: list[str] = []
                source_chain_artifact_lint.validate_review_decisions(text, 1, 0, errors, set())

                self.assertTrue(any(expected in error for error in errors), errors)

        unsafe_path_text = block().replace(
            "  - local_overlays/references/security_sources.md",
            "  - https://example.com/not-a-project-path",
        )
        unsafe_path_errors: list[str] = []
        source_chain_artifact_lint.validate_review_decisions(
            unsafe_path_text,
            1,
            0,
            unsafe_path_errors,
            set(),
        )
        self.assertTrue(any("invalid affected_files" in error for error in unsafe_path_errors), unsafe_path_errors)

        allowed_path_text = block().replace(
            "  - local_overlays/references/security_sources.md",
            "  - workspace_overlays/references/security_sources.md",
        )
        allowed_path_errors: list[str] = []
        source_chain_artifact_lint.validate_review_decisions(
            allowed_path_text,
            1,
            0,
            allowed_path_errors,
            set(),
            auto_apply_path_prefixes=("workspace_overlays/references/",),
        )
        self.assertEqual([], allowed_path_errors)

        for affected_file in (
            "local_overlays/references/security_sources.md",
            "workspace_overlays/references-archive/security_sources.md",
            "workspace_overlays/references",
        ):
            with self.subTest(auto_affected_file=affected_file):
                path_text = block().replace(
                    "local_overlays/references/security_sources.md",
                    affected_file,
                )
                path_errors: list[str] = []
                source_chain_artifact_lint.validate_review_decisions(
                    path_text,
                    1,
                    0,
                    path_errors,
                    set(),
                    auto_apply_path_prefixes=("workspace_overlays/references/",),
                )
                self.assertTrue(
                    any("outside the allowed path prefixes" in error for error in path_errors),
                    path_errors,
                )

        manual_outside_errors: list[str] = []
        source_chain_artifact_lint.validate_review_decisions(
            block().replace("apply_mode: auto", "apply_mode: manual"),
            1,
            1,
            manual_outside_errors,
            set(),
            auto_apply_path_prefixes=("workspace_overlays/references/",),
        )
        self.assertFalse(
            any("outside the allowed path prefixes" in error for error in manual_outside_errors),
            manual_outside_errors,
        )

        for unsafe_prefix in (
            "workspace_overlays/references",
            "../workspace_overlays/references/",
            "/workspace_overlays/references/",
            "workspace_overlays//references/",
            " workspace_overlays/references/",
        ):
            with self.subTest(unsafe_prefix=unsafe_prefix):
                prefix_errors: list[str] = []
                source_chain_artifact_lint.validate_review_decisions(
                    allowed_path_text,
                    1,
                    0,
                    prefix_errors,
                    set(),
                    auto_apply_path_prefixes=(unsafe_prefix,),
                )
                self.assertTrue(
                    any("safe repository-relative directory prefixes" in error for error in prefix_errors),
                    prefix_errors,
                )

        duplicate_id_errors: list[str] = []
        source_chain_artifact_lint.validate_review_decisions(
            block() + "\n" + block(),
            2,
            0,
            duplicate_id_errors,
            set(),
        )
        self.assertTrue(any("duplicates finding_id" in error for error in duplicate_id_errors), duplicate_id_errors)

        valid_text = block()
        expected_hash = source_chain_artifact_lint.decision_hash(
            source_chain_artifact_lint.decision_blocks(valid_text)[0]
        )
        valid_hashed_text = valid_text.replace(f"finding_hash: {digest}", f"finding_hash: {expected_hash}")
        good_hash_errors: list[str] = []
        bad_hash_errors: list[str] = []
        source_chain_artifact_lint.validate_review_decisions(
            valid_hashed_text,
            1,
            0,
            good_hash_errors,
            set(),
            verify_decision_hashes=True,
        )
        source_chain_artifact_lint.validate_review_decisions(
            valid_text,
            1,
            0,
            bad_hash_errors,
            set(),
            verify_decision_hashes=True,
        )

        self.assertFalse(any("finding_hash does not match" in error for error in good_hash_errors))
        self.assertTrue(any("finding_hash does not match" in error for error in bad_hash_errors))

        reference_only_errors: list[str] = []
        source_chain_artifact_lint.validate_review_decisions(
            block(monitor_root="reference-only", root_decision="reference-only"),
            1,
            0,
            reference_only_errors,
            set(),
        )
        self.assertEqual([], reference_only_errors)

    def test_source_chain_artifact_lint_propagates_auto_apply_path_prefixes_to_predecessors(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            monitor = root / "review_artifacts" / "source_monitor" / "2026-06-19_0930.md"
            review = root / "review_artifacts" / "source_review" / "2026-06-19_0930.md"
            apply = root / "review_artifacts" / "source_apply" / "2026-06-19_0930.md"
            monitor.parent.mkdir(parents=True)
            review.parent.mkdir(parents=True)
            apply.parent.mkdir(parents=True)

            monitor.write_text(monitor_artifact_fixture(), encoding="utf-8")
            review.write_text(
                review_artifact_fixture(
                    input_monitor_sha256=source_chain_artifact_lint.file_sha256(monitor)
                ),
                encoding="utf-8",
            )
            apply.write_text(
                apply_artifact_fixture(
                    input_review_sha256=source_chain_artifact_lint.file_sha256(review)
                ),
                encoding="utf-8",
            )

            report = validate_artifact(
                apply,
                "apply",
                project_root=root,
                auto_apply_path_prefixes=("workspace_overlays/references/",),
            )

        self.assertTrue(
            any(
                "input_review_artifact must lint cleanly" in error
                and "outside the allowed path prefixes" in error
                for error in string_items(report["errors"])
            ),
            report["errors"],
        )

    def test_source_chain_artifact_lint_rejects_unsafe_auto_apply_prefix_before_artifact_reads(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            absent = root / "review_artifacts" / "source_monitor" / "2026-06-19_0930.md"
            report = source_chain_artifact_lint.validate_artifact(
                absent,
                "monitor",
                project_root=root,
                auto_apply_path_prefixes=("workspace_overlays/references",),
            )

        self.assertEqual(
            [
                "auto_apply_path_prefixes must contain safe repository-relative "
                "directory prefixes ending in '/': 'workspace_overlays/references'"
            ],
            report["errors"],
        )

    def test_source_chain_artifact_lint_rejects_absolute_predecessor_reference(self) -> None:
        digest = "6" * 64
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            other = root / "other"
            review_root = root / "repo"
            monitor = other / "review_artifacts" / "source_monitor" / "2026-06-19_0930.md"
            review = review_root / "review_artifacts" / "source_review" / "2026-06-19_0930.md"
            monitor.parent.mkdir(parents=True)
            review.parent.mkdir(parents=True)
            monitor.write_text(
                "\n".join(
                    [
                        "artifact_schema_version: 6",
                        "chain_id: source-2026-06-19-0930",
                        "stage: monitor",
                        "stage_run_id: monitor-2026-06-19-0930",
                        "attempt_id: monitor-2026-06-19T023000Z-abc123",
                        "logical_date: 2026-06-19",
                        "run_slot: 0930",
                        "monitor_scope: framework-sources",
                        "monitor_scope_sha256: 5b619bc978d06cba5277f7846faa48625e0ec70ba43216c35213bb6cd7f62a38",
                        "model_route: quality_first",
                        "model_label: fixture-model",
                        "reasoning_effort: high",
                        "execution_mode: standard",
                        "timezone: Europe/Vienna",
                        "started_at_utc: 2026-06-19T00:30:00Z",
                        "completed_at_utc: 2026-06-19T00:52:00Z",
                        "status: pass",
                        "source_status: pass",
                        "workspace_status: clean",
                        "external_reviewer_status: not_needed",
                        "external_reviewer_packet_scope: none",
                        "inaccessible_source_count: 0",
                        "unresolved_inaccessible_source_count: 0",
                        "source_root_coverage_count: 0",
                        "source_registry_files:",
                        "  - path: local_overlays/references/security_sources.md",
                        f"    sha256: {digest}",
                        "policy_files:",
                        "  - path: local_overlays/source_monitor_policy.md",
                        f"    sha256: {digest}",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            monitor_hash = source_chain_artifact_lint.file_sha256(monitor)
            review.write_text(
                "\n".join(
                    [
                        "artifact_schema_version: 6",
                        "chain_id: source-2026-06-19-0930",
                        "stage: review",
                        "stage_run_id: review-2026-06-19-0930",
                        "attempt_id: review-2026-06-19T043000Z-abc123",
                        "logical_date: 2026-06-19",
                        "run_slot: 0930",
                        "monitor_scope: framework-sources",
                        "monitor_scope_sha256: 5b619bc978d06cba5277f7846faa48625e0ec70ba43216c35213bb6cd7f62a38",
                        "model_route: quality_first",
                        "model_label: fixture-model",
                        "reasoning_effort: high",
                        "execution_mode: standard",
                        "timezone: Europe/Vienna",
                        "started_at_utc: 2026-06-19T02:30:00Z",
                        "completed_at_utc: 2026-06-19T02:45:00Z",
                        "status: pass",
                        "external_reviewer_status: not_needed",
                        "external_reviewer_packet_scope: none",
                        "input_monitor_state: resolved",
                        f"input_monitor_artifact: {monitor}",
                        "input_monitor_stage_run_id: monitor-2026-06-19-0930",
                        "input_monitor_attempt_id: monitor-2026-06-19T023000Z-abc123",
                        f"input_monitor_sha256: {monitor_hash}",
                        "inaccessible_source_count: 0",
                        "unresolved_inaccessible_source_count: 0",
                        "accepted_findings: 0",
                        "manual_findings: 0",
                        "rejected_findings: 0",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            report = validate_artifact(review, "review")

        self.assertTrue(
            any("must be a relative review_artifacts path" in error for error in string_items(report["errors"])),
            report["errors"],
        )

    def test_source_chain_artifact_lint_rejects_apply_changes_outside_auto_findings(self) -> None:
        digest = "5" * 64
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            review = root / "review_artifacts" / "source_review" / "2026-06-19_0930.md"
            apply = root / "review_artifacts" / "source_apply" / "2026-06-19_0930.md"
            review.parent.mkdir(parents=True)
            apply.parent.mkdir(parents=True)
            review.write_text(
                "\n".join(
                    [
                        "finding_id: accepted-1",
                        f"finding_hash: {digest}",
                        "classification: accept-source-entry",
                        "apply_mode: auto",
                        "change_class: source-entry-content",
                        "source_tier: [official-doc]",
                        "source_role: evidence-url",
                        "quality_gate: primary_verified",
                        "durable_abstraction: Existing source metadata changed and should update the private source entry.",
                        "applicability: Applies only to the checked source family and its approved monitor root.",
                        "rejected_source_specifics: No tool commands, implementation details, or doctrine changes are adopted.",
                        "affected_files:",
                        "  - local_overlays/references/security_sources.md",
                        "risk: low",
                        "evidence:",
                        "  - official source checked 2026-06-19",
                        "evidence_url: https://example.com/security/advisory",
                        "monitor_root: https://example.com/security/",
                        "root_decision: monitor",
                        "required_verification:",
                        "  - uv run python -B scripts/check_reference_freshness.py",
                    ]
                ),
                encoding="utf-8",
            )
            apply_text = "\n".join(
                [
                    "changed_files:",
                    "  - private/references/prompt_engineering_sources.md",
                    "",
                ]
            )
            header = {
                "status": "pass",
                "input_review_state": "resolved",
                "input_review_artifact": "review_artifacts/source_review/2026-06-19_0930.md",
            }
            errors: list[str] = []
            artifact_cache: source_chain_artifact_lint.ArtifactSnapshotCache = {}

            source_chain_artifact_lint.validate_apply_changed_files(
                root,
                apply_text,
                header,
                errors,
                artifact_cache,
            )

        self.assertTrue(
            any("not covered by an auto-eligible review finding" in error for error in errors),
            errors,
        )

    def test_source_chain_artifact_lint_validates_monitor_input_hash_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_file = root / "local_overlays" / "references" / "security_sources.md"
            policy_file = root / "local_overlays" / "source_monitor_policy.md"
            monitor = root / "review_artifacts" / "source_monitor" / "2026-06-19_0930.md"
            source_file.parent.mkdir(parents=True)
            policy_file.parent.mkdir(parents=True, exist_ok=True)
            monitor.parent.mkdir(parents=True)
            source_file.write_text("# Sources\n", encoding="utf-8")
            policy_file.write_text("# Policy\n", encoding="utf-8")
            source_hash = source_chain_artifact_lint.file_sha256(source_file)
            policy_hash = source_chain_artifact_lint.file_sha256(policy_file)
            text = "\n".join(
                [
                    "source_registry_files:",
                    "  - path: local_overlays/references/security_sources.md",
                    f"    sha256: {source_hash}",
                    "policy_files:",
                    "  - path: local_overlays/source_monitor_policy.md",
                    f"    sha256: {policy_hash}",
                    "",
                ]
            )
            good_errors: list[str] = []
            mismatch_errors: list[str] = []
            unavailable_pass_errors: list[str] = []
            unavailable_partial_errors: list[str] = []

            source_chain_artifact_lint.validate_monitor_input_hashes(
                root,
                text,
                {"status": "pass"},
                good_errors,
                verify_current_hashes=True,
            )
            source_file.write_text("# Changed\n", encoding="utf-8")
            source_chain_artifact_lint.validate_monitor_input_hashes(
                root,
                text,
                {"status": "pass"},
                mismatch_errors,
                verify_current_hashes=True,
            )
            unavailable_text = text.replace(
                f"    sha256: {source_hash}",
                "    sha256: unavailable\n    reason: approved source input was inaccessible",
                1,
            )
            source_chain_artifact_lint.validate_monitor_input_hashes(
                root,
                unavailable_text,
                {"status": "pass"},
                unavailable_pass_errors,
                verify_current_hashes=True,
            )
            source_chain_artifact_lint.validate_monitor_input_hashes(
                root,
                unavailable_text,
                {"status": "partial"},
                unavailable_partial_errors,
                verify_current_hashes=True,
            )

        self.assertEqual([], good_errors)
        self.assertTrue(any("sha256 does not match current file" in error for error in mismatch_errors))
        self.assertIn(
            "successful monitor artifacts cannot use unavailable source or policy input hashes",
            unavailable_pass_errors,
        )
        self.assertEqual([], unavailable_partial_errors)

    def test_source_chain_artifact_lint_fails_closed_for_required_policy_arguments(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_file = root / "local_overlays" / "references" / "sources.md"
            declared_policy = root / "local_overlays" / "declared_policy.md"
            required_policy = root / "local_overlays" / "required_policy.md"
            source_file.parent.mkdir(parents=True)
            declared_policy.parent.mkdir(parents=True, exist_ok=True)
            source_file.write_text("# Sources\n", encoding="utf-8")
            declared_policy.write_text("# Declared policy\n", encoding="utf-8")
            required_policy.write_text("# Required policy\n", encoding="utf-8")
            source_hash = source_chain_artifact_lint.file_sha256(source_file)
            declared_policy_hash = source_chain_artifact_lint.file_sha256(
                declared_policy
            )
            required_policy_hash = source_chain_artifact_lint.file_sha256(
                required_policy
            )
            omitted_text = "\n".join(
                [
                    "source_registry_files:",
                    "  - path: local_overlays/references/sources.md",
                    f"    sha256: {source_hash}",
                    "policy_files:",
                    "  - path: local_overlays/declared_policy.md",
                    f"    sha256: {declared_policy_hash}",
                    "",
                ]
            )
            included_text = omitted_text.replace(
                f"    sha256: {declared_policy_hash}\n",
                f"    sha256: {declared_policy_hash}\n"
                "  - path: local_overlays/required_policy.md\n"
                f"    sha256: {required_policy_hash}\n",
            )

            included_errors: list[str] = []
            omitted_errors: list[str] = []
            missing_errors: list[str] = []
            unsafe_errors: list[str] = []
            source_chain_artifact_lint.validate_monitor_input_hashes(
                root,
                included_text,
                {"status": "pass"},
                included_errors,
                verify_current_hashes=True,
                required_policy_files=("local_overlays/required_policy.md",),
            )
            source_chain_artifact_lint.validate_monitor_input_hashes(
                root,
                omitted_text,
                {"status": "pass"},
                omitted_errors,
                verify_current_hashes=True,
                required_policy_files=("local_overlays/required_policy.md",),
            )
            required_policy.unlink()
            source_chain_artifact_lint.validate_monitor_input_hashes(
                root,
                omitted_text,
                {"status": "pass"},
                missing_errors,
                verify_current_hashes=True,
                required_policy_files=("local_overlays/required_policy.md",),
            )
            source_chain_artifact_lint.validate_monitor_input_hashes(
                root,
                omitted_text,
                {"status": "pass"},
                unsafe_errors,
                verify_current_hashes=True,
                required_policy_files=("../outside.md",),
            )

        self.assertEqual([], included_errors)
        self.assertTrue(
            any("policy_files is missing required" in error for error in omitted_errors),
            omitted_errors,
        )
        self.assertTrue(
            any("policy_files is missing required" in error for error in missing_errors),
            missing_errors,
        )
        self.assertTrue(
            any("cannot be read safely" in error for error in missing_errors),
            missing_errors,
        )
        self.assertTrue(
            any("must be a safe repo-relative path" in error for error in unsafe_errors),
            unsafe_errors,
        )

    def test_source_chain_artifact_lint_requires_strict_source_root_coverage(self) -> None:
        digest = "7" * 64
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_file = root / "local_overlays" / "references" / "security_sources.md"
            policy_file = root / "local_overlays" / "source_monitor_policy.md"
            monitor = root / "review_artifacts" / "source_monitor" / "2026-06-19_0930.md"
            source_file.parent.mkdir(parents=True)
            policy_file.parent.mkdir(parents=True, exist_ok=True)
            monitor.parent.mkdir(parents=True)
            source_file.write_text(
                "# Sources\n\n- Example\n  Monitor root: https://example.com/security/\n",
                encoding="utf-8",
            )
            policy_file.write_text("# Policy\n", encoding="utf-8")
            source_hash = source_chain_artifact_lint.file_sha256(source_file)
            policy_hash = source_chain_artifact_lint.file_sha256(policy_file)

            def monitor_text(coverage_count: int, coverage_block: list[str] | None = None) -> str:
                return "\n".join(
                    [
                        "artifact_schema_version: 6",
                        "chain_id: source-2026-06-19-0930",
                        "stage: monitor",
                        "stage_run_id: monitor-2026-06-19-0930",
                        "attempt_id: monitor-2026-06-19T023000Z-abc123",
                        "logical_date: 2026-06-19",
                        "run_slot: 0930",
                        "monitor_scope: framework-sources",
                        "monitor_scope_sha256: 5b619bc978d06cba5277f7846faa48625e0ec70ba43216c35213bb6cd7f62a38",
                        "model_route: quality_first",
                        "model_label: fixture-model",
                        "reasoning_effort: high",
                        "execution_mode: standard",
                        "timezone: Europe/Vienna",
                        "started_at_utc: 2026-06-19T00:30:00Z",
                        "completed_at_utc: 2026-06-19T00:52:00Z",
                        "status: pass",
                        "source_status: pass",
                        "workspace_status: clean",
                        "external_reviewer_status: not_needed",
                        "external_reviewer_packet_scope: none",
                        "inaccessible_source_count: 0",
                        "unresolved_inaccessible_source_count: 0",
                        f"source_root_coverage_count: {coverage_count}",
                        "source_registry_files:",
                        "  - path: local_overlays/references/security_sources.md",
                        f"    sha256: {source_hash}",
                        "policy_files:",
                        "  - path: local_overlays/source_monitor_policy.md",
                        f"    sha256: {policy_hash}",
                        "",
                        *(coverage_block or []),
                    ]
                )

            monitor.write_text(monitor_text(0), encoding="utf-8")
            missing_report = validate_artifact(
                monitor,
                "monitor",
                verify_current_input_hashes=True,
            )
            missing_report_without_hash_mode = validate_artifact(
                monitor,
                "monitor",
                verify_current_input_hashes=False,
            )
            monitor.write_text(
                monitor_text(
                    1,
                    [
                        "## Source Root Coverage",
                        "source_ref: example-security",
                        "registry_path: local_overlays/references/security_sources.md",
                        "monitor_root: https://example.com/security/",
                        "source_role: authority-root",
                        "status: checked",
                        "cursor_kind: item",
                        "latest_seen_key: advisory-1",
                        "latest_seen_url: https://example.com/security/advisory-1",
                        "reason: fixture root checked",
                    ],
                ),
                encoding="utf-8",
            )
            covered_report = validate_artifact(
                monitor,
                "monitor",
                verify_current_input_hashes=True,
            )
            monitor.write_text(
                monitor_text(
                    1,
                    [
                        "## Source Root Coverage",
                        "source_ref: example-security",
                        "registry_path: local_overlays/references/security_sources.md",
                        "monitor_root: https://example.com/releases/v_01",
                        "source_role: authority-root",
                        "status: checked",
                        "cursor_kind: no_item_list",
                        "latest_seen_key: none",
                        "latest_seen_url: https://example.com/releases/v_01",
                        "reason: fixture exact source URL checked",
                    ],
                ),
                encoding="utf-8",
            )
            exact_report = validate_artifact(
                monitor,
                "monitor",
                verify_current_input_hashes=False,
            )
            strict_unclassified_exact_report = validate_artifact(
                monitor,
                "monitor",
                verify_current_input_hashes=True,
            )
            source_file.write_text(
                "\n".join(
                    [
                        "# Sources",
                        "",
                        "- Example version index",
                        "  https://example.com/releases/v_01",
                        "  Monitor root: https://example.com/releases/v_01",
                        "  Monitor host relation: evidence_host",
                        "  Monitor root class: canonical_exact_root",
                        "  Canonical exact root reason: This endpoint is the bounded update surface.",
                        "  Freshness mechanism kind: revision_identifier",
                        "  Source authority: publisher-owned update endpoint",
                        "  Revalidation interval days: 30",
                        "  Replacement discovery mode: alternate_url",
                        "  Replacement discovery reference: https://example.com/releases",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            source_hash = source_chain_artifact_lint.file_sha256(source_file)
            monitor.write_text(
                monitor_text(
                    1,
                    [
                        "## Source Root Coverage",
                        "source_ref: example-version-index",
                        "registry_path: local_overlays/references/security_sources.md",
                        "monitor_root: https://example.com/releases/v_01",
                        "source_role: authority-root",
                        "status: checked",
                        "cursor_kind: validator",
                        "latest_seen_key: content-digest-1",
                        "latest_seen_url: https://example.com/releases/v_01",
                        "reason: classified exact update surface checked",
                    ],
                ),
                encoding="utf-8",
            )
            canonical_exact_report = validate_artifact(
                monitor,
                "monitor",
                verify_current_input_hashes=True,
            )
            review = root / "review_artifacts" / "source_review" / "2026-06-19_0930.md"
            review.parent.mkdir(parents=True)
            review.write_text(
                review_artifact_fixture(
                    input_monitor_sha256=source_chain_artifact_lint.file_sha256(monitor),
                ),
                encoding="utf-8",
            )
            historical_predecessor_report = validate_artifact(review, "review")

        self.assertTrue(
            any("source root coverage is missing registry monitor roots" in error for error in string_items(missing_report["errors"])),
            missing_report["errors"],
        )
        self.assertFalse(
            any(
                "source root coverage is missing registry monitor roots" in error
                for error in string_items(missing_report_without_hash_mode["errors"])
            ),
            missing_report_without_hash_mode["errors"],
        )
        self.assertEqual([], covered_report["errors"])
        self.assertFalse(
            any("exact/static monitor_root" in error for error in string_items(exact_report["errors"])),
            exact_report["errors"],
        )
        self.assertTrue(
            any(
                "exact/static monitor_root" in error
                for error in string_items(strict_unclassified_exact_report["errors"])
            ),
            strict_unclassified_exact_report["errors"],
        )
        self.assertEqual([], canonical_exact_report["errors"])
        self.assertEqual([], historical_predecessor_report["errors"])

    def test_source_chain_artifact_lint_binds_roots_to_declaring_registry_paths(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first_registry = root / "source_registry" / "first.md"
            second_registry = root / "source_registry" / "second.md"
            first_registry.parent.mkdir(parents=True)
            registry_text = (
                "# Sources\n\n"
                "- Releases\n"
                "  Monitor root: https://example.com/releases/\n"
            )
            first_registry.write_text(registry_text, encoding="utf-8")
            second_registry.write_text(registry_text, encoding="utf-8")
            source_header = "\n".join(
                [
                    "source_registry_files:",
                    "  - path: source_registry/first.md",
                    "  - path: source_registry/second.md",
                    "",
                ]
            )

            def coverage_text(registry_path: str, monitor_root: str) -> str:
                return source_header + "\n" + "\n".join(
                    [
                        "## Source Root Coverage",
                        "source_ref: example-releases",
                        f"registry_path: {registry_path}",
                        f"monitor_root: {monitor_root}",
                        "source_role: authority-root",
                        "status: checked",
                        "cursor_kind: item",
                        "latest_seen_key: release-1",
                        "latest_seen_url: https://example.com/releases/release-1",
                        "reason: release index checked",
                    ]
                )

            duplicate_owner_errors: list[str] = []
            mismatched_owner_errors: list[str] = []
            unexpected_root_errors: list[str] = []
            source_chain_artifact_lint.validate_source_root_coverage(
                root,
                coverage_text(
                    "source_registry/second.md",
                    "https://example.com/releases/",
                ),
                {"source_root_coverage_count": "1"},
                "monitor",
                duplicate_owner_errors,
                verify_current_input_hashes=True,
            )
            source_chain_artifact_lint.validate_source_root_coverage(
                root,
                coverage_text(
                    "source_registry/unrelated.md",
                    "https://example.com/releases/",
                ),
                {"source_root_coverage_count": "1"},
                "monitor",
                mismatched_owner_errors,
                verify_current_input_hashes=True,
            )
            source_chain_artifact_lint.validate_source_root_coverage(
                root,
                coverage_text(
                    "source_registry/first.md",
                    "https://example.com/other-releases/",
                ),
                {"source_root_coverage_count": "1"},
                "monitor",
                unexpected_root_errors,
                verify_current_input_hashes=True,
            )

        self.assertEqual([], duplicate_owner_errors)
        self.assertTrue(
            any(
                "registry_path does not declare monitor_root" in error
                for error in mismatched_owner_errors
            ),
            mismatched_owner_errors,
        )
        self.assertTrue(
            any(
                "monitor_root not declared by the recorded source registries" in error
                for error in unexpected_root_errors
            ),
            unexpected_root_errors,
        )

    def test_source_chain_artifact_lint_includes_source_update_table_roots_in_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_file = root / "local_overlays" / "SOURCE_UPDATE.md"
            policy_file = root / "local_overlays" / "source_monitor_policy.md"
            monitor = root / "review_artifacts" / "source_monitor" / "2026-06-19_0930.md"
            source_file.parent.mkdir(parents=True)
            policy_file.parent.mkdir(parents=True, exist_ok=True)
            monitor.parent.mkdir(parents=True)
            source_file.write_text(
                "\n".join(
                    [
                        "# Source Update Plan",
                        "",
                        "## Source Registry",
                        "",
                        "| Surface | Source | Kind | Tier | Scope | Volatility | Check Method | Access Policy | Monitoring Mode | Cadence | Last Checked | Allowed Use | Action Rule |",
                        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
                        "| security | https://example.com/releases | release notes | [vendor-doc] | current | high-volatility | publisher releases | not applicable | recurring | release-triggered | 2026-06-19 | normative after verification | review |",
                        "| reference | https://example.com/paper-v1 | paper | [research] | fixed | stable | manual | not applicable | one_off | manual | 2026-06-19 | evidence-only | keep |",
                        "",
                        "## Feed Watchers",
                        "",
                        "| Surface | Feed | Tier | Scope | Check Method | Access Policy | Conditional State | Dedupe Key | Last Checked | Last Seen | Allowed Use | Triage Rule | Output |",
                        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
                        "| security | https://example.com/feed.xml | [vendor-doc] | current | RSS | not applicable | ETag | GUID | 2026-06-19 | none | source discovery only | triage | report |",
                    ]
                ),
                encoding="utf-8",
            )
            policy_file.write_text("# Policy\n", encoding="utf-8")
            source_hash = source_chain_artifact_lint.file_sha256(source_file)
            policy_hash = source_chain_artifact_lint.file_sha256(policy_file)

            def monitor_text(coverage_count: int, coverage_block: list[str] | None = None) -> str:
                return "\n".join(
                    [
                        "artifact_schema_version: 6",
                        "chain_id: source-2026-06-19-0930",
                        "stage: monitor",
                        "stage_run_id: monitor-2026-06-19-0930",
                        "attempt_id: monitor-2026-06-19T023000Z-abc123",
                        "logical_date: 2026-06-19",
                        "run_slot: 0930",
                        "monitor_scope: framework-sources",
                        "monitor_scope_sha256: 5b619bc978d06cba5277f7846faa48625e0ec70ba43216c35213bb6cd7f62a38",
                        "model_route: quality_first",
                        "model_label: fixture-model",
                        "reasoning_effort: high",
                        "execution_mode: standard",
                        "timezone: Europe/Vienna",
                        "started_at_utc: 2026-06-19T00:30:00Z",
                        "completed_at_utc: 2026-06-19T00:52:00Z",
                        "status: pass",
                        "source_status: pass",
                        "workspace_status: clean",
                        "external_reviewer_status: not_needed",
                        "external_reviewer_packet_scope: none",
                        "inaccessible_source_count: 0",
                        "unresolved_inaccessible_source_count: 0",
                        f"source_root_coverage_count: {coverage_count}",
                        "source_registry_files:",
                        "  - path: local_overlays/SOURCE_UPDATE.md",
                        f"    sha256: {source_hash}",
                        "policy_files:",
                        "  - path: local_overlays/source_monitor_policy.md",
                        f"    sha256: {policy_hash}",
                        "",
                        *(coverage_block or []),
                    ]
                )

            monitor.write_text(monitor_text(0), encoding="utf-8")
            missing_report = validate_artifact(
                monitor,
                "monitor",
                verify_current_input_hashes=True,
            )
            monitor.write_text(
                monitor_text(
                    2,
                    [
                        "## Source Root Coverage",
                        "source_ref: example-releases",
                        "registry_path: local_overlays/SOURCE_UPDATE.md",
                        "monitor_root: https://example.com/releases",
                        "source_role: authority-root",
                        "status: checked",
                        "cursor_kind: item",
                        "latest_seen_key: release-1",
                        "latest_seen_url: https://example.com/releases/release-1",
                        "reason: fixture releases table root checked",
                        "",
                        "source_ref: example-feed",
                        "registry_path: local_overlays/SOURCE_UPDATE.md",
                        "monitor_root: https://example.com/feed.xml",
                        "source_role: discovery-filter",
                        "status: checked",
                        "cursor_kind: item",
                        "latest_seen_key: feed-guid-1",
                        "latest_seen_url: https://example.com/news/item-1",
                        "reason: fixture feed watcher checked",
                    ],
                ),
                encoding="utf-8",
            )
            covered_report = validate_artifact(
                monitor,
                "monitor",
                verify_current_input_hashes=True,
            )

        self.assertTrue(
            any("source root coverage is missing registry monitor roots" in error for error in string_items(missing_report["errors"])),
            missing_report["errors"],
        )
        self.assertEqual([], covered_report["errors"])

    def test_source_chain_artifact_lint_requires_exact_source_update_monitoring_mode(self) -> None:
        cases = (
            (
                "missing-column",
                "| Surface | Source | Cadence |",
                "|---|---|---|",
                "| security | https://example.com/releases | release-triggered |",
                "missing exact column(s):",
            ),
            (
                "legacy-manual-value",
                "| Surface | Source | Kind | Tier | Scope | Volatility | Check Method | Access Policy | Monitoring Mode | Cadence | Last Checked | Allowed Use | Action Rule |",
                "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
                "| security | https://example.com/releases | release notes | [vendor-doc] | current | high-volatility | publisher releases | not applicable | manual | release-triggered | 2026-07-13 | normative after verification | review |",
                "Monitoring Mode must be one of: one_off, recurring",
            ),
        )
        for case_id, header, separator, row, expected in cases:
            with self.subTest(case_id=case_id):
                errors: list[str] = []
                refs = source_chain_artifact_lint.recurring_source_url_refs_from_text(
                    "\n".join(
                        [
                            "# Source Update Plan",
                            "",
                            "## Source Registry",
                            "",
                            header,
                            separator,
                            row,
                        ]
                    ),
                    errors=errors,
                )

                self.assertEqual([], refs)
                self.assertTrue(any(expected in error for error in errors), errors)

    def test_source_chain_artifact_lint_rejects_evidence_url_source_root_coverage_role(self) -> None:
        text = "\n".join(
            [
                "## Source Root Coverage",
                "source_ref: example-releases",
                "registry_path: source_registry/security_sources.md",
                "monitor_root: https://example.com/releases",
                "source_role: evidence-url",
                "status: checked",
                "cursor_kind: item",
                "latest_seen_key: release-1",
                "latest_seen_url: https://example.com/releases/release-1",
                "reason: release checked",
            ]
        )
        errors: list[str] = []

        source_chain_artifact_lint.validate_source_root_coverage(
            Path("monitor.md"),
            text,
            {"source_root_coverage_count": "1"},
            "monitor",
            errors,
        )

        self.assertTrue(any("invalid source_role: evidence-url" in error for error in errors), errors)

    def test_source_chain_block_parsers_enforce_owned_sections_and_unique_fields(self) -> None:
        rejected_only = "\n".join(
            [
                "## Rejected Findings",
                "finding_id: rejected-1",
                "reason: insufficient evidence",
            ]
        )
        rejected_errors: list[str] = []
        source_chain_artifact_lint.validate_review_decisions(
            rejected_only,
            0,
            0,
            rejected_errors,
            section_only=True,
        )

        accepted_errors: list[str] = []
        source_chain_artifact_lint.validate_review_decisions(
            "\n".join(
                [
                    "## Accepted Findings",
                    "finding_id: accepted-1",
                    "unknown_field: must-not-be-silently-accepted",
                ]
            ),
            1,
            0,
            accepted_errors,
            require_section=True,
            section_only=True,
        )

        coverage_errors: list[str] = []
        source_chain_artifact_lint.source_root_coverage_blocks(
            "\n".join(
                [
                    "## Source Root Coverage",
                    "source_ref: example-root",
                    "monitor_root: https://example.com/releases",
                    "status: checked",
                    "status: skipped",
                ]
            ),
            coverage_errors,
        )

        self.assertEqual([], rejected_errors)
        self.assertTrue(any("unknown field unknown_field" in error for error in accepted_errors), accepted_errors)
        self.assertTrue(any("duplicates field status" in error for error in coverage_errors), coverage_errors)

    def test_source_chain_artifact_lint_requires_access_gap_for_blocked_root_coverage(self) -> None:
        text = "\n".join(
            [
                "## Source Root Coverage",
                "source_ref: agency-directives",
                "registry_path: local_overlays/references/security_sources.md",
                "monitor_root: https://agency.example/news/directives",
                "source_role: authority-root",
                "status: inaccessible",
                "cursor_kind: not_applicable",
                "latest_seen_key: none",
                "latest_seen_url: none",
                "reason: GET returned access failure",
            ]
        )
        errors: list[str] = []

        source_chain_artifact_lint.validate_source_root_coverage(
            Path("monitor.md"),
            text,
            {"source_root_coverage_count": "1"},
            "monitor",
            errors,
        )

        self.assertTrue(any("without a matching Inaccessible Sources block" in error for error in errors), errors)

    def test_source_chain_artifact_lint_accepts_blocked_root_with_access_gap_record(self) -> None:
        text = "\n".join(
            [
                "## Inaccessible Sources",
                "source_ref: agency-directives",
                "target_kind: root",
                "url: https://agency.example/news/directives",
                "failure_kind: access_denied",
                "failure_detail: GET returned 403",
                "coverage_status: unresolved",
                "alternate_primary_url: none",
                "",
                "## Source Root Coverage",
                "source_ref: agency-directives",
                "registry_path: source_registry/security_sources.md",
                "monitor_root: https://agency.example/news/directives",
                "source_role: authority-root",
                "status: inaccessible",
                "cursor_kind: not_applicable",
                "latest_seen_key: none",
                "latest_seen_url: none",
                "reason: GET returned access failure",
            ]
        )
        errors: list[str] = []

        source_chain_artifact_lint.validate_source_root_coverage(
            Path("monitor.md"),
            text,
            {"source_root_coverage_count": "1"},
            "monitor",
            errors,
        )

        self.assertEqual([], errors)

    def test_source_chain_artifact_lint_accepts_structured_cursor_kinds(self) -> None:
        text = "\n".join(
            [
                "## Source Root Coverage",
                "source_ref: example-feed",
                "registry_path: source_registry/prompt_sources.md",
                "monitor_root: https://example.com/feed.xml",
                "source_role: authority-root",
                "status: checked",
                "cursor_kind: validator",
                'latest_seen_key: W/"fixture-etag"',
                "latest_seen_url: https://example.com/feed.xml",
                "reason: bounded retrieval completed",
                "",
                "source_ref: example-changelog",
                "registry_path: source_registry/prompt_sources.md",
                "monitor_root: https://example.com/changelog/",
                "source_role: authority-root",
                "status: checked",
                "cursor_kind: no_item_list",
                "latest_seen_key: none",
                "latest_seen_url: https://example.com/changelog/",
                "reason: bounded retrieval completed",
                "",
                "source_ref: example-research",
                "registry_path: source_registry/prompt_sources.md",
                "monitor_root: https://example.com/research/",
                "source_role: discovery-filter",
                "status: skipped",
                "cursor_kind: not_applicable",
                "latest_seen_key: none",
                "latest_seen_url: none",
                "reason: outside the declared run scope",
            ]
        )
        errors: list[str] = []

        source_chain_artifact_lint.validate_source_root_coverage(
            Path("monitor.md"),
            text,
            {"source_root_coverage_count": "3"},
            "monitor",
            errors,
        )

        self.assertEqual([], errors)

    def test_source_chain_artifact_lint_rejects_cursor_kind_mismatches(self) -> None:
        monitor_root = "https://example.com/changelog/"
        cases = (
            (
                "validator-without-key",
                "checked",
                "validator",
                "none",
                monitor_root,
                "cursor_kind validator without a latest_seen_key",
            ),
            (
                "no-item-list-with-item",
                "checked",
                "no_item_list",
                "item-1",
                f"{monitor_root}item-1",
                "cursor_kind no_item_list unless latest_seen_key is none",
            ),
            (
                "checked-not-applicable",
                "checked",
                "not_applicable",
                "none",
                "none",
                "status checked with cursor_kind not_applicable",
            ),
            (
                "skipped-item",
                "skipped",
                "item",
                "item-1",
                f"{monitor_root}item-1",
                "status skipped without cursor_kind not_applicable",
            ),
            (
                "unknown-kind",
                "checked",
                "root_page",
                "item-1",
                f"{monitor_root}item-1",
                "invalid cursor_kind: root_page",
            ),
        )
        for case_id, status, cursor_kind, key, url, expected in cases:
            with self.subTest(case_id=case_id):
                text = "\n".join(
                    [
                        "## Source Root Coverage",
                        "source_ref: example-changelog",
                        "registry_path: source_registry/prompt_sources.md",
                        f"monitor_root: {monitor_root}",
                        "source_role: authority-root",
                        f"status: {status}",
                        f"cursor_kind: {cursor_kind}",
                        f"latest_seen_key: {key}",
                        f"latest_seen_url: {url}",
                        "reason: explanatory prose is not a cursor classifier",
                    ]
                )
                errors: list[str] = []

                source_chain_artifact_lint.validate_source_root_coverage(
                    Path("monitor.md"),
                    text,
                    {"source_root_coverage_count": "1"},
                    "monitor",
                    errors,
                )

                self.assertTrue(any(expected in error for error in errors), errors)

    def test_source_chain_artifact_lint_rejects_repository_tree_monitor_root(self) -> None:
        text = "\n".join(
            [
                "## Source Root Coverage",
                "source_ref: example-implementation",
                "registry_path: source_registry/security_sources.md",
                "monitor_root: https://code.example/team/project/tree/main",
                "source_role: authority-root",
                "status: checked",
                "cursor_kind: no_item_list",
                "latest_seen_key: none",
                "latest_seen_url: https://code.example/team/project/tree/main",
                "reason: repository page opened",
            ]
        )
        errors: list[str] = []

        source_chain_artifact_lint.validate_source_root_coverage(
            Path("monitor.md"),
            text,
            {"source_root_coverage_count": "1"},
            "monitor",
            errors,
            verify_current_input_hashes=True,
        )

        self.assertTrue(any("exact/static monitor_root" in error for error in errors), errors)

    def test_source_chain_artifact_lint_rejects_item_cursor_at_monitor_root(self) -> None:
        text = "\n".join(
            [
                "## Source Root Coverage",
                "source_ref: example-blog",
                "registry_path: source_registry/prompt_sources.md",
                "monitor_root: https://example.com/blog/",
                "source_role: authority-root",
                "status: checked",
                "cursor_kind: item",
                "latest_seen_key: blog-root",
                "latest_seen_url: https://example.com/blog/",
                "reason: explanatory prose is not a cursor classifier",
            ]
        )
        errors: list[str] = []

        source_chain_artifact_lint.validate_source_root_coverage(
            Path("monitor.md"),
            text,
            {"source_root_coverage_count": "1"},
            "monitor",
            errors,
        )

        self.assertTrue(
            any("item URL distinct from monitor_root" in error for error in errors),
            errors,
        )

    def test_source_chain_artifact_lint_rejects_bad_common_chain_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            review = root / "bad-common.md"
            review.write_text(
                review_artifact_fixture(
                    artifact_schema_version="1",
                    attempt_id="review-2026-06-19T043000Z",
                    timezone="EST",
                    started_at_utc="2026-06-19T02:45:00Z",
                    completed_at_utc="2026-06-19T02:30:00Z",
                    status="done",
                ),
                encoding="utf-8",
            )

            report = validate_artifact(review, "review")

        errors = string_items(report["errors"])
        self.assertTrue(any("artifact_schema_version must be 6" in error for error in errors))
        self.assertTrue(any("timezone must be a normalized IANA timezone name, not an abbreviation or alias" in error for error in errors))
        self.assertTrue(any("status must be one of" in error for error in errors))
        self.assertTrue(any("completed_at_utc must not be earlier" in error for error in errors))

    def test_source_chain_artifact_lint_rejects_path_shaped_timezone(self) -> None:
        errors: list[str] = []
        nul_errors: list[str] = []

        source_chain_artifact_lint.parse_artifact_timezone({"timezone": "../UTC"}, errors)
        source_chain_artifact_lint.parse_artifact_timezone({"timezone": "Europe/Vienna\x00"}, nul_errors)

        self.assertIn("timezone must be a normalized IANA timezone name, not an absolute or traversal path", errors)
        self.assertIn("timezone must be a valid IANA timezone name", nul_errors)

    def test_source_chain_artifact_lint_rejects_mismatched_predecessor_lineage(self) -> None:
        digest = "2" * 64
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            monitor = root / "review_artifacts" / "source_monitor" / "2026-06-19_0930.md"
            monitor.parent.mkdir(parents=True)
            monitor.write_text(
                "\n".join(
                    [
                        "artifact_schema_version: 6",
                        "chain_id: source-2026-06-18-0930",
                        "stage: monitor",
                        "stage_run_id: monitor-2026-06-18-0930",
                        "attempt_id: monitor-2026-06-18T023000Z-abc123",
                        "logical_date: 2026-06-18",
                        "run_slot: 0930",
                        "monitor_scope: framework-sources",
                        "monitor_scope_sha256: 5b619bc978d06cba5277f7846faa48625e0ec70ba43216c35213bb6cd7f62a38",
                        "model_route: quality_first",
                        "model_label: fixture-model",
                        "reasoning_effort: high",
                        "execution_mode: standard",
                        "timezone: Europe/Vienna",
                        "started_at_utc: 2026-06-18T00:30:00Z",
                        "completed_at_utc: 2026-06-18T00:52:00Z",
                        "status: pass",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            monitor_hash = source_chain_artifact_lint.file_sha256(monitor)
            review = root / "review_artifacts" / "source_review" / "2026-06-19_0930.md"
            review.parent.mkdir(parents=True)
            review.write_text(
                "\n".join(
                    [
                        "artifact_schema_version: 6",
                        "chain_id: source-2026-06-19-0930",
                        "stage: review",
                        "stage_run_id: review-2026-06-19-0930",
                        "attempt_id: review-2026-06-19T043000Z-abc123",
                        "logical_date: 2026-06-19",
                        "run_slot: 0930",
                        "monitor_scope: framework-sources",
                        "monitor_scope_sha256: 5b619bc978d06cba5277f7846faa48625e0ec70ba43216c35213bb6cd7f62a38",
                        "model_route: quality_first",
                        "model_label: fixture-model",
                        "reasoning_effort: high",
                        "execution_mode: standard",
                        "timezone: Europe/Vienna",
                        "started_at_utc: 2026-06-19T02:30:00Z",
                        "completed_at_utc: 2026-06-19T02:45:00Z",
                        "status: no-findings",
                        "external_reviewer_status: not_needed",
                        "external_reviewer_packet_scope: none",
                        "input_monitor_state: resolved",
                        "input_monitor_artifact: review_artifacts/source_monitor/2026-06-19_0930.md",
                        "input_monitor_stage_run_id: monitor-2026-06-19-0930",
                        "input_monitor_attempt_id: monitor-2026-06-19T023000Z-abc123",
                        f"input_monitor_sha256: {monitor_hash}",
                        "accepted_findings: 0",
                        "manual_findings: 0",
                        "rejected_findings: 0",
                        "",
                        f"finding_hash: {digest}",
                    ]
                ),
                encoding="utf-8",
            )

            report = validate_artifact(review, "review")

        errors = string_items(report["errors"])
        self.assertTrue(any("input_monitor_artifact must lint cleanly" in error for error in errors))
        self.assertTrue(any("header chain_id does not match expected predecessor chain_id" in error for error in errors))
        self.assertTrue(any("header logical_date does not match expected predecessor logical_date" in error for error in errors))

    def test_source_chain_artifact_lint_rejects_bad_assurance_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            assurance = root / "bad-assurance.md"
            assurance.write_text(
                assurance_artifact_fixture(
                    input_apply_sha256="not-a-hash",
                    unresolved_findings="many",
                ),
                encoding="utf-8",
            )

            report = validate_artifact(assurance, "assurance")

        errors = string_items(report["errors"])
        self.assertTrue(
            any(
                "input_apply_sha256 must be a SHA-256 hex digest or unavailable" in error
                for error in errors
            )
        )
        self.assertTrue(any("unresolved_findings must be an integer" in error for error in errors))

    def test_source_chain_artifact_lint_rejects_list_items_under_scalar_header_fields(self) -> None:
        digest = "d" * 64
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            review = root / "review.md"
            review.write_text(
                "\n".join(
                    [
                        "chain_id: source-2026-06-19-0930",
                        "stage: review",
                        "stage_run_id: review-2026-06-19-0930",
                        "logical_date: 2026-06-19",
                        "run_slot: 0930",
                        "monitor_scope: framework-sources",
                        "monitor_scope_sha256: 5b619bc978d06cba5277f7846faa48625e0ec70ba43216c35213bb6cd7f62a38",
                        "model_route: quality_first",
                        "model_label: fixture-model",
                        "reasoning_effort: high",
                        "execution_mode: standard",
                        "timezone: Europe/Vienna",
                        "status: pass",
                        "  - unexpected",
                        "external_reviewer_status: not_needed",
                        "external_reviewer_packet_scope: none",
                        f"input_monitor_sha256: {digest}",
                        "accepted_findings: 0",
                        "manual_findings: 0",
                        "rejected_findings: 0",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            report = validate_artifact(review, "review")

        self.assertTrue(
            any("header field status does not accept list items" in error for error in string_items(report["errors"]))
        )

    def test_source_chain_artifact_lint_reports_missing_file_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = Path(temp_dir) / "missing-source-chain.md"
            report = validate_artifact(missing, "review")

        self.assertTrue(any("cannot read artifact" in error for error in string_items(report["errors"])))
