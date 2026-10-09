#!/usr/bin/env python3
"""Project-neutral validator, receipt preparer, and hashing contract for review packets.

This module does not authorize disclosure or invocation. It validates the
project-neutral lifecycle, runtime-class provenance, and canonical byte
identities shared by packet and source-chain checks without depending on a
provider, model, account, or private operator inventory.
"""

from __future__ import annotations

import argparse
import copy
from dataclasses import dataclass
from datetime import datetime
import errno
from functools import lru_cache
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import stat
import sys
from typing import Any

import resource_cleanup
import safe_paths


VALIDATOR_CONTRACT_ID = "mpa-bounded-review-packet-v4"
PACKET_BINDING_FIELDS = (
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
INVENTORY_FIELDS = (
    "item_id",
    "locator",
    "classification",
    "byte_count",
    "sha256",
    "retention_class",
)
RECEIPT_PHASES = ("packet_ready", "pre_submission")
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
SAFE_COMPONENT_RE = re.compile(r"^[A-Za-z0-9_.@%+=,~-]+$")
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
RFC3339_DATETIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})$"
)
ZERO_SHA256 = "0" * 64
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_ITEM_BYTES = 25 * 1024 * 1024
MAX_PACKET_BYTES = 50 * 1024 * 1024
MAX_EVIDENCE_BYTES = 50 * 1024 * 1024
MAX_JSON_NESTING_DEPTH = 256
MAX_JSON_NODES = 100_000
MAX_BUNDLE_ENTRIES = 20_000
MAX_BUNDLE_DEPTH = 64
MAX_BUNDLE_DIAGNOSTICS = 256
ACTIVE_STAGES = {"packet_ready", "approved", "invoked", "returned", "validated", "closed"}
INVOCATION_STATUSES = {"started", "returned", "failed"}
TERMINAL_INVOCATION_STATUSES = {"returned", "failed"}
PREINVOCATION_ABANDONMENT_STATUSES = {"not_started", "skipped"}
REVIEWER_RUNTIME_CLASSES = {"model", "human", "deterministic_tool", "hybrid"}
MODEL_BACKED_RUNTIME_CLASSES = {"model", "hybrid"}
MODEL_VERSION_KINDS = {
    "immutable_snapshot",
    "stable_alias",
    "moving_alias",
    "not_exposed",
}
LANE_CONTROL_FIELDS = (
    "independence_group",
    "fallback_or_abort_rule",
    "auth_session_policy",
    "timeout",
    "rate_or_cost_cap",
    "teardown_rule",
)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _string_choice(value: object, choices: set[str]) -> bool:
    """Test a JSON enum only after narrowing it to a hashable string."""

    return isinstance(value, str) and value in choices


def packet_binding_sha256(data: dict[str, Any]) -> str:
    binding: dict[str, Any] = {}
    for field in PACKET_BINDING_FIELDS:
        value = copy.deepcopy(data.get(field))
        if field == "packet" and isinstance(value, dict):
            value.pop("packet_sha256", None)
        binding[field] = value
    binding["invocation_runtime_class"] = as_dict(data.get("invocation")).get(
        "runtime_class"
    )
    return canonical_sha256(binding)


def packet_inventory(data: dict[str, Any]) -> list[dict[str, Any]]:
    packet = data.get("packet")
    raw_items = packet.get("items") if isinstance(packet, dict) else None
    items = raw_items if isinstance(raw_items, list) else []
    return [
        {field: item.get(field) for field in INVENTORY_FIELDS}
        for item in items
        if isinstance(item, dict)
    ]


def packet_inventory_sha256(data: dict[str, Any]) -> str:
    return canonical_sha256(packet_inventory(data))


def approval_sha256(data: dict[str, Any]) -> str:
    return canonical_sha256(data.get("approval"))


def preflight_sha256(data: dict[str, Any]) -> str:
    return canonical_sha256(data.get("preflight"))


def receipt_payload(data: dict[str, Any], phase: str, receipt: dict[str, Any]) -> dict[str, Any]:
    if phase not in RECEIPT_PHASES:
        raise ValueError(f"unsupported review-packet receipt phase: {phase}")
    return {
        "validator_contract_id": receipt.get("validator_contract_id"),
        "phase": receipt.get("phase"),
        "review_id": data.get("review_id"),
        "validated_at": receipt.get("validated_at"),
        "packet_sha256": receipt.get("packet_sha256"),
        "inventory_sha256": receipt.get("inventory_sha256"),
        "approval_sha256": receipt.get("approval_sha256"),
        "preflight_sha256": receipt.get("preflight_sha256"),
    }


def receipt_sha256(data: dict[str, Any], phase: str, receipt: dict[str, Any]) -> str:
    return canonical_sha256(receipt_payload(data, phase, receipt))


def expected_receipt_fields(data: dict[str, Any], phase: str) -> dict[str, Any]:
    if phase not in RECEIPT_PHASES:
        raise ValueError(f"unsupported review-packet receipt phase: {phase}")
    return {
        "validator_contract_id": VALIDATOR_CONTRACT_ID,
        "phase": phase,
        "packet_sha256": packet_binding_sha256(data),
        "inventory_sha256": packet_inventory_sha256(data),
        "approval_sha256": approval_sha256(data) if phase == "pre_submission" else None,
        "preflight_sha256": preflight_sha256(data) if phase == "pre_submission" else None,
    }


def build_receipt(data: dict[str, Any], phase: str, validated_at: str) -> dict[str, Any]:
    receipt = {
        **expected_receipt_fields(data, phase),
        "validated_at": validated_at,
        "receipt_sha256": None,
    }
    receipt["receipt_sha256"] = receipt_sha256(data, phase, receipt)
    return receipt


def receipt_mismatches(data: dict[str, Any], phase: str, receipt: Any) -> list[str]:
    if not isinstance(receipt, dict):
        return [f"{phase} receipt is missing"]
    mismatches: list[str] = []
    for field, expected in expected_receipt_fields(data, phase).items():
        if receipt.get(field) != expected:
            mismatches.append(f"{phase} receipt {field} does not match the current packet")
    if not isinstance(receipt.get("validated_at"), str) or not receipt["validated_at"]:
        mismatches.append(f"{phase} receipt validated_at is missing")
    expected_sha = receipt_sha256(data, phase, receipt)
    if receipt.get("receipt_sha256") != expected_sha:
        mismatches.append(f"{phase} receipt digest does not match its canonical payload")
    return mismatches


def safe_locator(value: Any) -> bool:
    if not isinstance(value, str) or not value or "\\" in value or CONTROL_RE.search(value):
        return False
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    return (
        not posix.is_absolute()
        and not windows.is_absolute()
        and not windows.drive
        and all(
            part not in {"", ".", ".."} and SAFE_COMPONENT_RE.fullmatch(part)
            for part in value.split("/")
        )
    )


def is_nonplaceholder_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(SHA256_RE.fullmatch(value))
        and value != ZERO_SHA256
    )


def _phase_passed(value: Any) -> bool:
    if not isinstance(value, dict) or value.get("status") != "passed":
        return False
    checks = value.get("checks")
    return (
        isinstance(checks, list)
        and bool(checks)
        and all(
            isinstance(item, dict) and item.get("outcome") == "pass"
            for item in checks
        )
    )


def _preinvocation_abandonment(stage: Any, invocation_status: Any) -> bool:
    return (
        _string_choice(stage, {"blocked", "declined"})
        and _string_choice(invocation_status, PREINVOCATION_ABANDONMENT_STATUSES)
    )


def _closeout_started(closeout: dict[str, Any]) -> bool:
    return (
        closeout.get("status") != "not_started"
        or closeout.get("performed_at") is not None
        or bool(closeout.get("checks"))
        or closeout.get("cleanup_status") != "pending"
    )


def _present_receipts_valid(data: dict[str, Any]) -> bool:
    receipts = as_dict(data.get("validation_receipts"))
    for phase in RECEIPT_PHASES:
        receipt = receipts.get(phase)
        if receipt is not None and receipt_mismatches(data, phase, receipt):
            return False
    return True


def _ephemeral_cleanup_allowed(data: dict[str, Any]) -> bool:
    lifecycle = as_dict(data.get("lifecycle"))
    stage = lifecycle.get("stage")
    invocation_status = as_dict(data.get("invocation")).get("status")
    closeout = as_dict(data.get("closeout"))
    if not _phase_passed(closeout) or closeout.get("cleanup_status") != "complete":
        return False

    receipts = as_dict(data.get("validation_receipts"))
    terminal_cleanup = stage == "closed" or (
        stage == "blocked"
        and _string_choice(invocation_status, TERMINAL_INVOCATION_STATUSES)
    )
    if terminal_cleanup:
        return not receipt_mismatches(
            data, "packet_ready", receipts.get("packet_ready")
        ) and not receipt_mismatches(
            data, "pre_submission", receipts.get("pre_submission")
        )
    return (
        _preinvocation_abandonment(stage, invocation_status)
        and _present_receipts_valid(data)
    )


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("z", "Z").replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.utcoffset() is not None else None


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _model_identity_errors(value: Any, label: str) -> list[str]:
    if not isinstance(value, dict):
        return [f"{label} must be an object"]
    errors: list[str] = []
    version_kind = value.get("version_kind")
    model_identifier = value.get("model_identifier")
    if not _string_choice(version_kind, MODEL_VERSION_KINDS):
        errors.append(f"{label}.version_kind is invalid")
    elif version_kind == "not_exposed":
        if model_identifier is not None:
            errors.append(
                f"{label} with not_exposed version kind cannot claim a model identifier"
            )
    elif not _nonempty_string(model_identifier):
        errors.append(
            f"{label} requires a model identifier unless its version kind is not_exposed"
        )
    return errors


def invocation_provenance_errors(invocation: Any) -> list[str]:
    """Validate execution provenance without inventing model identity."""

    if not isinstance(invocation, dict):
        return ["invocation must be an object"]
    status_value = invocation.get("status")
    runtime_class = invocation.get("runtime_class")
    if not _string_choice(runtime_class, REVIEWER_RUNTIME_CLASSES):
        return ["invocation.runtime_class is invalid"]

    identity_fields = (
        "exact_runtime_label",
        "observed_model",
        "exact_mode",
        "reasoning_effort_status",
        "exact_reasoning_effort",
    )
    if _string_choice(status_value, {"not_started", "skipped"}):
        if any(invocation.get(field) is not None for field in identity_fields):
            return [
                "not-started or skipped invocation cannot claim exact execution provenance"
            ]
        return []
    if not _string_choice(status_value, INVOCATION_STATUSES):
        return []

    errors: list[str] = []
    if not _nonempty_string(invocation.get("exact_runtime_label")):
        errors.append("active invocation requires an exact runtime label")
    if not _nonempty_string(invocation.get("exact_mode")):
        errors.append("active invocation requires an exact execution mode")

    effort_status = invocation.get("reasoning_effort_status")
    exact_effort = invocation.get("exact_reasoning_effort")
    if _string_choice(runtime_class, MODEL_BACKED_RUNTIME_CLASSES):
        observed_model = invocation.get("observed_model")
        errors.extend(
            _model_identity_errors(
                observed_model,
                "model or hybrid invocation observed_model",
            )
        )
        if isinstance(observed_model, dict):
            if not isinstance(observed_model.get("matches_planned_policy"), bool):
                errors.append(
                    "model or hybrid invocation observed_model requires a planned-policy comparison result"
                )
            if not _nonempty_string(observed_model.get("comparison_basis")):
                errors.append(
                    "model or hybrid invocation observed_model requires a comparison basis"
                )
        if not _string_choice(effort_status, {"recorded", "not_exposed"}):
            errors.append(
                "model or hybrid invocation reasoning effort must be recorded or not_exposed"
            )
        elif effort_status == "recorded" and not _nonempty_string(exact_effort):
            errors.append(
                "recorded reasoning effort requires an exact reasoning-effort value"
            )
        elif effort_status == "not_exposed" and exact_effort is not None:
            errors.append(
                "not_exposed reasoning effort cannot claim an exact reasoning-effort value"
            )
    else:
        if invocation.get("observed_model") is not None:
            errors.append(
                "human or deterministic-tool invocation cannot claim an observed model"
            )
        if effort_status != "not_applicable" or exact_effort is not None:
            errors.append(
                "human or deterministic-tool invocation reasoning effort must be not_applicable with no exact value"
            )
    return errors


def _lane_control_errors(data: dict[str, Any]) -> list[str]:
    lane_controls = data.get("lane_controls")
    if not isinstance(lane_controls, dict):
        return []
    manifest_kind = lane_controls.get("manifest_kind")
    errors: list[str] = []
    if (
        as_dict(data.get("invocation")).get("runtime_class") == "human"
        and manifest_kind != "full"
    ):
        errors.append("human reviewer lane requires a full control manifest")
    for field in LANE_CONTROL_FIELDS:
        binding = lane_controls.get(field)
        if not isinstance(binding, dict):
            continue
        resolution = binding.get("resolution")
        value = binding.get("value")
        if not _nonempty_string(binding.get("basis")):
            errors.append(f"lane control {field} requires a nonempty basis")
        if manifest_kind == "full":
            if resolution != "explicit":
                errors.append(f"full lane control {field} must be explicit")
            if not _nonempty_string(value):
                errors.append(f"full lane control {field} requires an explicit value")
        elif manifest_kind == "compact_internal":
            if resolution == "not_applicable":
                if value is not None:
                    errors.append(
                        f"compact internal lane control {field} marked not_applicable must use a null value"
                    )
            elif not _nonempty_string(value):
                errors.append(
                    f"compact internal lane control {field} requires an explicit, inherited, or derived value"
                )
    return errors


def _planned_model_policy_errors(
    context: _PortableManifestContext,
) -> list[str]:
    runtime_class = context.invocation.get("runtime_class")
    planned_policy = context.data.get("planned_model_policy")
    errors: list[str] = []
    if _string_choice(runtime_class, MODEL_BACKED_RUNTIME_CLASSES):
        if not isinstance(planned_policy, dict):
            errors.append(
                "model or hybrid lane requires a planned_model_policy before approval"
            )
        else:
            errors.extend(
                _model_identity_errors(planned_policy, "planned_model_policy")
            )
            if not _nonempty_string(planned_policy.get("selection_basis")):
                errors.append("planned_model_policy requires a selection basis")
    elif (
        _string_choice(runtime_class, REVIEWER_RUNTIME_CLASSES)
        and planned_policy is not None
    ):
        errors.append(
            "human or deterministic-tool lane cannot claim a planned_model_policy"
        )

    observed_model = context.invocation.get("observed_model")
    if (
        isinstance(planned_policy, dict)
        and isinstance(observed_model, dict)
        and observed_model.get("matches_planned_policy") is True
    ):
        planned_kind = planned_policy.get("version_kind")
        observed_kind = observed_model.get("version_kind")
        planned_identifier = planned_policy.get("model_identifier")
        observed_identifier = observed_model.get("model_identifier")
        if planned_kind == "immutable_snapshot":
            if observed_kind != "immutable_snapshot":
                errors.append(
                    "matching an immutable planned snapshot requires an observed immutable snapshot"
                )
            elif planned_identifier != observed_identifier:
                errors.append(
                    "matching immutable planned and observed snapshots require the same identifier"
                )
        elif _string_choice(planned_kind, {"stable_alias", "moving_alias"}):
            if observed_kind == planned_kind:
                if planned_identifier != observed_identifier:
                    errors.append(
                        "matching planned and observed aliases require the same identifier"
                    )
            elif observed_kind != "immutable_snapshot":
                errors.append(
                    "matching a planned alias requires the same alias or its observed immutable snapshot"
                )
        elif planned_kind == "not_exposed":
            # The bound selection basis is the only approval-visible policy;
            # a later observation may therefore be more specific.
            pass
    if (
        isinstance(observed_model, dict)
        and observed_model.get("matches_planned_policy") is False
        and context.stage != "blocked"
    ):
        errors.append(
            "observed model that does not match planned policy requires blocked lifecycle"
        )
    return errors


def _duplicate_guard(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_nonfinite(token: str) -> None:
    raise ValueError(f"non-finite JSON number is forbidden: {token}")


def _enforce_json_shape_limits(text: str) -> None:
    """Bound parser recursion and aggregate JSON node work before decoding."""

    depth = 0
    nodes = 0
    in_string = False
    escaped = False
    in_primitive = False
    for index, character in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            nodes += 1
            in_string = True
            in_primitive = False
        elif character in "[{":
            nodes += 1
            depth += 1
            in_primitive = False
            if depth > MAX_JSON_NESTING_DEPTH:
                raise json.JSONDecodeError(
                    "JSON nesting exceeds the supported parser depth",
                    text,
                    index,
                )
        elif character in "]}":
            depth = max(0, depth - 1)
            in_primitive = False
        elif character in " \t\r\n,:":
            in_primitive = False
        elif not in_primitive:
            nodes += 1
            in_primitive = True
        if nodes > MAX_JSON_NODES:
            raise json.JSONDecodeError(
                "JSON node count exceeds the supported parser limit",
                text,
                index,
            )


def parse_manifest_bytes(raw: bytes) -> Any:
    text = raw.decode("utf-8")
    _enforce_json_shape_limits(text)
    try:
        return json.loads(
            text,
            object_pairs_hook=_duplicate_guard,
            parse_constant=_reject_nonfinite,
        )
    except RecursionError as exc:
        raise json.JSONDecodeError(
            "JSON nesting exceeds the supported parser depth",
            text,
            0,
        ) from exc


def _os_error_name(exc: OSError) -> str:
    return (
        errno.errorcode.get(exc.errno, "OSERROR")
        if isinstance(exc.errno, int)
        else "OSERROR"
    )


def _bundle_descriptor_capability_error() -> str | None:
    required_flags = ("O_DIRECTORY", "O_NOFOLLOW", "O_NONBLOCK")
    missing_flags = [
        name
        for name in required_flags
        if not isinstance(getattr(os, name, None), int)
        or getattr(os, name) == 0
    ]
    if missing_flags:
        return (
            "descriptor-safe lifecycle-bundle inspection requires platform "
            "flags: " + ", ".join(missing_flags)
        )
    if not safe_paths.OPEN_SUPPORTS_DIR_FD:
        return (
            "descriptor-safe lifecycle-bundle inspection requires os.open "
            "dir_fd support"
        )
    if os.scandir not in getattr(os, "supports_fd", set()):
        return (
            "descriptor-safe lifecycle-bundle inspection requires os.scandir "
            "file-descriptor support"
        )
    if (
        os.stat not in getattr(os, "supports_dir_fd", set())
        or os.stat not in getattr(os, "supports_follow_symlinks", set())
    ):
        return (
            "descriptor-safe lifecycle-bundle inspection requires os.stat "
            "dir_fd and no-follow support"
        )
    return None


def _bundle_directory_flags() -> int:
    return (
        os.O_RDONLY
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
    )


def _bundle_file_flags() -> int:
    return (
        os.O_RDONLY
        | os.O_NOFOLLOW
        | os.O_NONBLOCK
        | getattr(os, "O_CLOEXEC", 0)
    )


def _read_fd_snapshot(
    fd: int,
    *,
    maximum: int,
    label: str,
) -> tuple[bytes | None, str | None]:
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            return None, f"{label} is not a regular file"
        if before.st_nlink != 1:
            return None, f"{label} must have exactly one hard link"
        if before.st_size > maximum:
            return None, f"{label} exceeds the {maximum}-byte limit"
        chunks: list[bytes] = []
        remaining = maximum + 1
        while remaining > 0:
            chunk = os.read(fd, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(fd)
    except OSError as exc:
        return None, f"cannot read {label}: OS error {_os_error_name(exc)}"
    stable_fields = (
        "st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns", "st_nlink"
    )
    if len(raw) > maximum:
        return None, f"{label} exceeds the {maximum}-byte limit"
    if any(getattr(before, name) != getattr(after, name) for name in stable_fields):
        return None, f"{label} changed while being read"
    if len(raw) != before.st_size:
        return None, f"{label} changed while being read"
    return raw, None


@dataclass(frozen=True, slots=True)
class _BoundBundleFile:
    descriptor: int
    metadata: tuple[int, ...]
    raw: bytes
    label: str


def _read_bound_bundle_file(
    root_descriptor: int,
    locator: str,
    *,
    maximum: int,
    label: str,
    retained: resource_cleanup.OwnedFileDescriptors,
) -> tuple[_BoundBundleFile | None, str | None]:
    """Read a file below one caller-bound root and retain its identity fd."""

    if not safe_locator(locator):
        return None, f"{label} has an unsafe locator"
    parts = PurePosixPath(locator).parts
    traversed = resource_cleanup.OwnedFileDescriptors()
    bindings: list[tuple[int, str, int, tuple[int, ...]]] = []
    try:
        current_descriptor = root_descriptor
        for component in parts[:-1]:
            try:
                named = os.stat(
                    component,
                    dir_fd=current_descriptor,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                return None, f"{label} is missing"
            if not stat.S_ISDIR(named.st_mode):
                return None, f"{label} uses a non-directory path component"
            child_descriptor = os.open(
                component,
                _bundle_directory_flags(),
                dir_fd=current_descriptor,
            )
            traversed.adopt(
                child_descriptor,
                f"{label} traversed directory",
            )
            opened = os.fstat(child_descriptor)
            opened_metadata = safe_paths.stable_file_metadata(opened)
            if (
                not stat.S_ISDIR(opened.st_mode)
                or opened_metadata
                != safe_paths.stable_file_metadata(named)
            ):
                return None, f"{label} changed while its path was opened"
            bindings.append(
                (
                    current_descriptor,
                    component,
                    child_descriptor,
                    opened_metadata,
                )
            )
            current_descriptor = child_descriptor

        try:
            named_before = os.stat(
                parts[-1],
                dir_fd=current_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            return None, f"{label} is missing"
        file_descriptor = os.open(
            parts[-1],
            _bundle_file_flags(),
            dir_fd=current_descriptor,
        )
        retained.adopt(file_descriptor, label)
        opened_before = os.fstat(file_descriptor)
        opened_metadata = safe_paths.stable_file_metadata(opened_before)
        if opened_metadata != safe_paths.stable_file_metadata(named_before):
            return None, f"{label} changed before it was read"
        raw, read_error = _read_fd_snapshot(
            file_descriptor,
            maximum=maximum,
            label=label,
        )
        if read_error is not None or raw is None:
            return None, read_error or f"cannot read {label}"
        opened_after = os.fstat(file_descriptor)
        named_after = os.stat(
            parts[-1],
            dir_fd=current_descriptor,
            follow_symlinks=False,
        )
        after_metadata = safe_paths.stable_file_metadata(opened_after)
        if (
            after_metadata != opened_metadata
            or safe_paths.stable_file_metadata(named_after) != after_metadata
        ):
            return None, f"{label} changed while its pathname was read"

        for parent, component, child, expected in reversed(bindings):
            named_directory = os.stat(
                component,
                dir_fd=parent,
                follow_symlinks=False,
            )
            bound_directory = os.fstat(child)
            if (
                not stat.S_ISDIR(named_directory.st_mode)
                or not stat.S_ISDIR(bound_directory.st_mode)
                or safe_paths.stable_file_metadata(named_directory) != expected
                or safe_paths.stable_file_metadata(bound_directory) != expected
            ):
                return None, f"{label} path changed while it was read"
        return (
            _BoundBundleFile(
                descriptor=file_descriptor,
                metadata=after_metadata,
                raw=raw,
                label=label,
            ),
            None,
        )
    except FileNotFoundError:
        return None, f"{label} is missing"
    except OSError as exc:
        return None, f"cannot open {label}: OS error {_os_error_name(exc)}"
    finally:
        traversed.cleanup(primary=sys.exception())


def read_bundle_file(
    bundle_root: Path,
    locator: str,
    *,
    maximum: int,
    label: str,
) -> tuple[bytes | None, str | None]:
    """Read one file through a retained, no-follow bundle-root descriptor."""

    if not safe_locator(locator):
        return None, f"{label} has an unsafe locator"
    capability_error = _bundle_descriptor_capability_error()
    if capability_error is not None:
        return None, f"{label} cannot be inspected safely: {capability_error}"
    try:
        with safe_paths.open_output_directory(
            bundle_root,
            create_missing=False,
        ) as root_binding:
            retained = resource_cleanup.OwnedFileDescriptors()
            try:
                bound, read_error = _read_bound_bundle_file(
                    root_binding.descriptor,
                    locator,
                    maximum=maximum,
                    label=label,
                    retained=retained,
                )
                if read_error is not None or bound is None:
                    return None, read_error or f"cannot read {label}"
                root_binding.require_unchanged_chain(
                    description=f"{label} bundle root"
                )
                if (
                    safe_paths.stable_file_metadata(os.fstat(bound.descriptor))
                    != bound.metadata
                ):
                    return None, f"{label} changed before validation completed"
                return bound.raw, None
            finally:
                retained.cleanup(primary=sys.exception())
    except (OSError, RuntimeError, ValueError) as exc:
        suffix = (
            f": OS error {_os_error_name(exc)}"
            if isinstance(exc, OSError)
            else ""
        )
        return None, f"cannot inspect {label} safely{suffix}"


def load_manifest_file(path: Path) -> tuple[Any | None, bytes | None, list[str]]:
    if path.name in {"", ".", ".."}:
        return None, None, ["manifest path is invalid"]
    raw, error = read_bundle_file(
        path.parent,
        path.name,
        maximum=MAX_MANIFEST_BYTES,
        label="review-packet manifest",
    )
    if error is not None or raw is None:
        return None, None, [error or "cannot read review-packet manifest"]
    try:
        return parse_manifest_bytes(raw), raw, []
    except (UnicodeError, ValueError, json.JSONDecodeError) as exc:
        return None, raw, [f"manifest is invalid JSON: {exc}"]


def _json_type_matches(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
        )
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return False


@lru_cache(maxsize=1)
def _canonical_schema() -> dict[str, Any]:
    schema_path = Path(__file__).resolve().parents[1] / "runtime/review_packet.schema.json"
    loaded = parse_manifest_bytes(schema_path.read_bytes())
    if not isinstance(loaded, dict):
        raise ValueError("review-packet schema root must be an object")
    return loaded


def _resolve_local_ref(root: dict[str, Any], ref: str) -> Any:
    if not ref.startswith("#/"):
        raise ValueError(f"unsupported schema reference: {ref}")
    current: Any = root
    for token in ref[2:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or token not in current:
            raise ValueError(f"unresolved schema reference: {ref}")
        current = current[token]
    return current


def _schema_node_errors(
    value: Any,
    schema: Any,
    root: dict[str, Any],
    path: str,
) -> list[str]:
    if schema is True:
        return []
    if schema is False:
        return [f"{path} is forbidden by the review-packet schema"]
    if not isinstance(schema, dict):
        return [f"{path} has an invalid schema node"]
    if "$ref" in schema:
        try:
            target = _resolve_local_ref(root, schema["$ref"])
        except ValueError as exc:
            return [str(exc)]
        return _schema_node_errors(value, target, root, path)
    errors: list[str] = []
    expected_type = schema.get("type")
    if expected_type is not None:
        choices = expected_type if isinstance(expected_type, list) else [expected_type]
        if not any(isinstance(item, str) and _json_type_matches(value, item) for item in choices):
            return [f"{path} has the wrong JSON type"]
    if "const" in schema and canonical_bytes(value) != canonical_bytes(schema["const"]):
        errors.append(f"{path} does not equal the required constant")
    if "enum" in schema and all(
        canonical_bytes(value) != canonical_bytes(item) for item in schema["enum"]
    ):
        errors.append(f"{path} is not an allowed value")
    if isinstance(value, dict):
        required = schema.get("required", [])
        if isinstance(required, list):
            for key in required:
                if isinstance(key, str) and key not in value:
                    errors.append(f"{path}.{key} is required")
        properties = schema.get("properties", {})
        if isinstance(properties, dict):
            for key, item in value.items():
                if key in properties:
                    errors.extend(_schema_node_errors(item, properties[key], root, f"{path}.{key}"))
                elif schema.get("additionalProperties") is False:
                    errors.append(f"{path}.{key} is not allowed")
    if isinstance(value, list):
        minimum = schema.get("minItems")
        if isinstance(minimum, int) and len(value) < minimum:
            errors.append(f"{path} has fewer than {minimum} item(s)")
        if schema.get("uniqueItems") is True:
            identities = [canonical_bytes(item) for item in value]
            if len(identities) != len(set(identities)):
                errors.append(f"{path} contains duplicate items")
        item_schema = schema.get("items")
        if item_schema is not None:
            for index, item in enumerate(value):
                errors.extend(_schema_node_errors(item, item_schema, root, f"{path}[{index}]"))
    if isinstance(value, str):
        minimum = schema.get("minLength")
        if isinstance(minimum, int) and len(value) < minimum:
            errors.append(f"{path} is shorter than {minimum} character(s)")
        pattern = schema.get("pattern")
        if isinstance(pattern, str) and re.search(pattern, value) is None:
            errors.append(f"{path} does not match its required pattern")
        if schema.get("format") == "date-time" and (
            RFC3339_DATETIME_RE.fullmatch(value) is None
            or _parse_timestamp(value) is None
        ):
            errors.append(f"{path} must be a timezone-aware date-time")
    if (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and isinstance(schema.get("minimum"), (int, float))
        and value < schema["minimum"]
    ):
        errors.append(f"{path} is below its minimum")
    if "oneOf" in schema and isinstance(schema["oneOf"], list):
        matches = sum(
            not _schema_node_errors(value, branch, root, path)
            for branch in schema["oneOf"]
        )
        if matches != 1:
            errors.append(f"{path} must match exactly one allowed schema branch")
    return errors


def schema_errors(data: Any) -> list[str]:
    try:
        schema = _canonical_schema()
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        return [f"cannot load the canonical review-packet schema: {exc}"]
    return _schema_node_errors(data, schema, schema, "manifest")


def _phase_semantic_errors(value: Any, label: str) -> list[str]:
    if not isinstance(value, dict):
        return [f"{label} must be an object"]
    status_value = value.get("status")
    performed_at = value.get("performed_at")
    checks = value.get("checks")
    if not isinstance(checks, list):
        return [f"{label}.checks must be an array"]
    errors: list[str] = []
    check_ids = [
        item["check_id"] for item in checks
        if isinstance(item, dict) and isinstance(item.get("check_id"), str)
    ]
    if len(check_ids) != len(set(check_ids)):
        errors.append(f"{label} check IDs must be unique")
    if status_value == "not_started":
        if performed_at is not None or checks:
            errors.append(f"{label} not_started state cannot contain a time or checks")
        return errors
    if _parse_timestamp(performed_at) is None:
        errors.append(f"{label}.performed_at is required for a completed phase")
    if not checks:
        errors.append(f"{label} completed phase must contain at least one check")
        return errors
    outcomes = [item.get("outcome") for item in checks if isinstance(item, dict)]
    if status_value == "passed" and (
        len(outcomes) != len(checks) or any(outcome != "pass" for outcome in outcomes)
    ):
        errors.append(f"{label} passed state requires every declared check to pass")
    if status_value == "failed" and (
        len(outcomes) != len(checks) or "fail" not in outcomes
    ):
        errors.append(f"{label} failed state requires at least one failed check")
    return errors


def _artifact_maps(data: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    raw = data.get("evidence_artifacts")
    artifacts = [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []
    errors: list[str] = []
    ids = [item["artifact_id"] for item in artifacts if isinstance(item.get("artifact_id"), str)]
    locators = [item["locator"] for item in artifacts if isinstance(item.get("locator"), str)]
    if len(ids) != len(set(ids)):
        errors.append("evidence artifact IDs must be unique")
    if len(locators) != len(set(locators)):
        errors.append("evidence artifact locators must be unique")
    for index, artifact in enumerate(artifacts):
        if not is_nonplaceholder_sha256(artifact.get("sha256")):
            errors.append(f"evidence_artifacts[{index}].sha256 must be non-placeholder SHA-256")
        if not safe_locator(artifact.get("locator")):
            errors.append(f"evidence_artifacts[{index}].locator must be one safe bundle-relative path")
        status_value = artifact.get("retention_status")
        if status_value == "deleted" and not artifact.get("deletion_evidence_ref"):
            errors.append(f"evidence_artifacts[{index}] deleted state needs deletion evidence")
        if status_value != "deleted" and artifact.get("deletion_evidence_ref") is not None:
            errors.append(f"evidence_artifacts[{index}] non-deleted state cannot claim deletion evidence")
    return artifacts, errors


def _supporting_artifact(
    artifacts: list[dict[str, Any]],
    *,
    role: str,
    digest: Any | None = None,
) -> bool:
    return any(
        artifact.get("role") == role
        and artifact.get("retention_status") == "retained"
        and (digest is None or artifact.get("sha256") == digest)
        for artifact in artifacts
    )


def _safe_bundle_component(name: str) -> bool:
    return bool(SAFE_COMPONENT_RE.fullmatch(name)) and CONTROL_RE.search(name) is None


def _bundle_component_display(name: str) -> str:
    if _safe_bundle_component(name):
        return name
    return json.dumps(name, ensure_ascii=True)


def _bundle_locator_display(parts: tuple[str, ...]) -> str:
    return "/".join(_bundle_component_display(part) for part in parts)


def _fresh_bundle_directory_names(
    directory_descriptor: int,
    *,
    maximum: int,
) -> tuple[tuple[str, ...], bool]:
    """Return a bounded name set from a fresh descriptor for the same directory."""

    owned = resource_cleanup.OwnedFileDescriptors()
    try:
        scan_descriptor = os.open(
            ".",
            _bundle_directory_flags(),
            dir_fd=directory_descriptor,
        )
        owned.adopt(scan_descriptor, "review-packet bundle directory scan")
        if (
            safe_paths.stable_file_metadata(os.fstat(scan_descriptor))
            != safe_paths.stable_file_metadata(os.fstat(directory_descriptor))
        ):
            raise ValueError(
                "review-packet lifecycle bundle directory changed before enumeration"
            )
        names: list[str] = []
        exceeded = False
        with os.scandir(scan_descriptor) as entries:
            for entry in entries:
                if len(names) >= maximum:
                    exceeded = True
                    break
                names.append(entry.name)
        return tuple(sorted(names)), exceeded
    finally:
        owned.cleanup(primary=sys.exception())


@dataclass(frozen=True, slots=True)
class _BundleDirectoryRecord:
    descriptor: int
    parent_descriptor: int | None
    name: str | None
    locator_parts: tuple[str, ...]
    metadata: tuple[int, ...]
    names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _BundleFileNameRecord:
    parent_descriptor: int
    name: str
    metadata: tuple[int, ...]


def _bundle_inventory_errors(
    root_descriptor: int,
    manifest_name: str,
    allowed_locators: set[str],
    declared_files: dict[str, _BoundBundleFile],
    *,
    retained: resource_cleanup.OwnedFileDescriptors,
) -> tuple[list[str], set[str]]:
    """Inventory one bundle without reopening any path outside its bound root."""

    allowed_directories = {
        parent.as_posix()
        for locator in allowed_locators
        for parent in PurePosixPath(locator).parents
        if parent != PurePosixPath(".")
    }
    detail_budget = max(0, MAX_BUNDLE_DIAGNOSTICS - 1)
    details: list[str] = []
    omitted_diagnostics = 0
    entry_limit_exceeded = False
    depth_limit_exceeded = False
    visited = 0
    present_locators: set[str] = set()
    regular_metadata: dict[str, tuple[int, ...]] = {}
    file_names: dict[str, _BundleFileNameRecord] = {}
    directories: list[_BundleDirectoryRecord] = []

    def record(message: str) -> None:
        nonlocal omitted_diagnostics
        if len(details) < detail_budget:
            details.append(message)
        else:
            omitted_diagnostics += 1

    def visit(
        directory_descriptor: int,
        locator_parts: tuple[str, ...],
        depth: int,
        *,
        parent_descriptor: int | None,
        name: str | None,
    ) -> None:
        nonlocal entry_limit_exceeded, depth_limit_exceeded, visited
        directory_before = os.fstat(directory_descriptor)
        if not stat.S_ISDIR(directory_before.st_mode):
            record(
                "review-packet lifecycle bundle bound a non-directory during inventory"
            )
            return
        before_metadata = safe_paths.stable_file_metadata(directory_before)
        remaining = max(0, MAX_BUNDLE_ENTRIES - visited)
        names, exceeded = _fresh_bundle_directory_names(
            directory_descriptor,
            maximum=remaining,
        )
        directories.append(
            _BundleDirectoryRecord(
                descriptor=directory_descriptor,
                parent_descriptor=parent_descriptor,
                name=name,
                locator_parts=locator_parts,
                metadata=before_metadata,
                names=names,
            )
        )
        if exceeded:
            entry_limit_exceeded = True
            return
        visited += len(names)

        for entry_name in names:
            relative_parts = (*locator_parts, entry_name)
            relative = "/".join(relative_parts)
            display = _bundle_locator_display(relative_parts)
            present_locators.add(relative)
            child_depth = depth + 1
            if child_depth > MAX_BUNDLE_DEPTH:
                depth_limit_exceeded = True
                continue
            if not _safe_bundle_component(entry_name):
                record(
                    "review-packet lifecycle bundle contains an unsafe entry "
                    f"name: {display}"
                )
                continue
            try:
                named_before = os.stat(
                    entry_name,
                    dir_fd=directory_descriptor,
                    follow_symlinks=False,
                )
            except OSError as exc:
                record(
                    "review-packet lifecycle bundle entry changed before "
                    f"inspection: {display} (OS error {_os_error_name(exc)})"
                )
                continue
            named_metadata = safe_paths.stable_file_metadata(named_before)
            if stat.S_ISLNK(named_before.st_mode):
                record(
                    "review-packet lifecycle bundle contains a symlink: "
                    f"{display}"
                )
                continue
            if stat.S_ISDIR(named_before.st_mode):
                if relative not in allowed_directories:
                    record(
                        "review-packet lifecycle bundle contains an undeclared "
                        f"directory: {display}"
                    )
                try:
                    child_descriptor = os.open(
                        entry_name,
                        _bundle_directory_flags(),
                        dir_fd=directory_descriptor,
                    )
                    retained.adopt(
                        child_descriptor,
                        f"review-packet lifecycle bundle directory {display}",
                    )
                    child_metadata = os.fstat(child_descriptor)
                except OSError as exc:
                    record(
                        "review-packet lifecycle bundle directory changed "
                        f"before inspection: {display} "
                        f"(OS error {_os_error_name(exc)})"
                    )
                    continue
                if (
                    not stat.S_ISDIR(child_metadata.st_mode)
                    or safe_paths.stable_file_metadata(child_metadata)
                    != named_metadata
                ):
                    record(
                        "review-packet lifecycle bundle directory changed "
                        f"before inspection: {display}"
                    )
                    continue
                visit(
                    child_descriptor,
                    relative_parts,
                    child_depth,
                    parent_descriptor=directory_descriptor,
                    name=entry_name,
                )
                continue
            if stat.S_ISREG(named_before.st_mode):
                regular_metadata[relative] = named_metadata
                file_names[relative] = _BundleFileNameRecord(
                    parent_descriptor=directory_descriptor,
                    name=entry_name,
                    metadata=named_metadata,
                )
                if not locator_parts and relative == manifest_name:
                    continue
                if relative not in allowed_locators:
                    record(
                        "review-packet lifecycle bundle contains an unlisted "
                        f"file: {display}"
                    )
                continue
            if stat.S_ISFIFO(named_before.st_mode):
                kind = "FIFO"
            elif stat.S_ISSOCK(named_before.st_mode):
                kind = "socket"
            elif stat.S_ISCHR(named_before.st_mode):
                kind = "character-device"
            elif stat.S_ISBLK(named_before.st_mode):
                kind = "block-device"
            else:
                kind = "special-filesystem"
            record(
                "review-packet lifecycle bundle contains an unsupported "
                f"{kind} entry: {display}"
            )

    visit(
        root_descriptor,
        (),
        0,
        parent_descriptor=None,
        name=None,
    )

    for directory in reversed(directories):
        display = _bundle_locator_display(directory.locator_parts) or "."
        try:
            current_names, exceeded = _fresh_bundle_directory_names(
                directory.descriptor,
                maximum=len(directory.names),
            )
            current_metadata = safe_paths.stable_file_metadata(
                os.fstat(directory.descriptor)
            )
            if exceeded or current_names != directory.names:
                record(
                    "review-packet lifecycle bundle directory entries changed "
                    f"while inventoried: {display}"
                )
            if current_metadata != directory.metadata:
                record(
                    "review-packet lifecycle bundle directory changed while "
                    f"inventoried: {display}"
                )
            if directory.parent_descriptor is not None and directory.name is not None:
                named_after = os.stat(
                    directory.name,
                    dir_fd=directory.parent_descriptor,
                    follow_symlinks=False,
                )
                if (
                    not stat.S_ISDIR(named_after.st_mode)
                    or safe_paths.stable_file_metadata(named_after)
                    != current_metadata
                ):
                    record(
                        "review-packet lifecycle bundle directory name changed "
                        f"while inventoried: {display}"
                    )
        except OSError as exc:
            record(
                "review-packet lifecycle bundle directory changed while "
                f"inventoried: {display} (OS error {_os_error_name(exc)})"
            )

    for relative, file_name in sorted(file_names.items()):
        display = _bundle_locator_display(tuple(relative.split("/")))
        try:
            named_after = os.stat(
                file_name.name,
                dir_fd=file_name.parent_descriptor,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISREG(named_after.st_mode)
                or safe_paths.stable_file_metadata(named_after)
                != file_name.metadata
            ):
                record(
                    "review-packet lifecycle bundle file changed while "
                    f"inventoried: {display}"
                )
        except OSError as exc:
            record(
                "review-packet lifecycle bundle file changed while "
                f"inventoried: {display} (OS error {_os_error_name(exc)})"
            )

    for locator, declared in sorted(declared_files.items()):
        inventoried = regular_metadata.get(locator)
        current = safe_paths.stable_file_metadata(os.fstat(declared.descriptor))
        if inventoried is None:
            record(f"{declared.label} is not bound to a regular inventory entry")
        elif inventoried != declared.metadata:
            record(
                f"{declared.label} changed between byte validation and inventory"
            )
        if current != declared.metadata:
            record(f"{declared.label} changed before bundle validation completed")

    summary: list[str] = []
    if entry_limit_exceeded:
        summary.append(
            f"inventory exceeds the {MAX_BUNDLE_ENTRIES}-entry limit"
        )
    if depth_limit_exceeded:
        summary.append(f"depth limit of {MAX_BUNDLE_DEPTH} was exceeded")
    if omitted_diagnostics:
        summary.append(
            f"diagnostic limit of {MAX_BUNDLE_DIAGNOSTICS} was reached; "
            f"{omitted_diagnostics} additional details were omitted"
        )
    if summary:
        details.append("review-packet lifecycle bundle " + "; ".join(summary))
    return details, present_locators


def _bundle_errors(data: dict[str, Any], manifest_path: Path) -> list[str]:
    packet = as_dict(data.get("packet"))
    raw_items = packet.get("items")
    items = raw_items if isinstance(raw_items, list) else []
    artifacts, _artifact_errors = _artifact_maps(data)
    errors: list[str] = []
    capability_error = _bundle_descriptor_capability_error()
    if capability_error is not None:
        return [
            "review-packet lifecycle bundle cannot be inspected safely: "
            + capability_error
        ]
    final_cleanup_allowed = _ephemeral_cleanup_allowed(data)
    allowed_locators: set[str] = set()
    packet_locators: set[str] = set()
    forbidden_locators: dict[str, list[str]] = {}
    declared_files: dict[str, _BoundBundleFile] = {}
    total_packet_bytes = 0
    total_evidence_bytes = 0
    try:
        with safe_paths.open_output_directory(
            manifest_path.parent,
            create_missing=False,
        ) as root_binding:
            retained = resource_cleanup.OwnedFileDescriptors()
            try:
                for index, item in enumerate(items):
                    if (
                        not isinstance(item, dict)
                        or not safe_locator(item.get("locator"))
                    ):
                        continue
                    locator = str(item["locator"])
                    packet_locators.add(locator)
                    allowed_locators.add(locator)
                    label = f"packet.items[{index}] disclosed file"
                    if (
                        final_cleanup_allowed
                        and item.get("retention_class") == "ephemeral"
                    ):
                        forbidden_locators.setdefault(locator, []).append(
                            f"packet.items[{index}] ephemeral disclosed file remains "
                            "after completed cleanup"
                        )
                        continue
                    bound, read_error = _read_bound_bundle_file(
                        root_binding.descriptor,
                        locator,
                        maximum=MAX_ITEM_BYTES,
                        label=label,
                        retained=retained,
                    )
                    if read_error is not None or bound is None:
                        errors.append(read_error or f"{label} is missing")
                        continue
                    declared_files[locator] = bound
                    total_packet_bytes += len(bound.raw)
                    if item.get("byte_count") != len(bound.raw):
                        errors.append(
                            f"packet.items[{index}].byte_count does not match "
                            "disclosed bytes"
                        )
                    if item.get("sha256") != hashlib.sha256(bound.raw).hexdigest():
                        errors.append(
                            f"packet.items[{index}].sha256 does not match "
                            "disclosed bytes"
                        )
                if total_packet_bytes > MAX_PACKET_BYTES:
                    errors.append(
                        "packet disclosed bytes exceed the packet-size limit"
                    )

                for index, artifact in enumerate(artifacts):
                    locator_value = artifact.get("locator")
                    if not safe_locator(locator_value):
                        continue
                    locator = str(locator_value)
                    allowed_locators.add(locator)
                    if locator in packet_locators:
                        errors.append(
                            f"evidence_artifacts[{index}] locator collides with "
                            "disclosed packet bytes"
                        )
                        continue
                    status_value = artifact.get("retention_status")
                    label = f"evidence_artifacts[{index}] retained file"
                    if status_value != "retained":
                        forbidden_locators.setdefault(locator, []).append(
                            f"evidence_artifacts[{index}] {status_value} artifact "
                            "must not remain in the lifecycle bundle"
                        )
                        continue
                    bound, read_error = _read_bound_bundle_file(
                        root_binding.descriptor,
                        locator,
                        maximum=MAX_ITEM_BYTES,
                        label=label,
                        retained=retained,
                    )
                    if read_error is not None or bound is None:
                        errors.append(read_error or f"{label} is missing")
                        continue
                    declared_files[locator] = bound
                    total_evidence_bytes += len(bound.raw)
                    if artifact.get("sha256") != hashlib.sha256(bound.raw).hexdigest():
                        errors.append(
                            f"evidence_artifacts[{index}].sha256 does not match "
                            "retained bytes"
                        )
                if total_evidence_bytes > MAX_EVIDENCE_BYTES:
                    errors.append(
                        "retained review evidence exceeds the evidence-size limit"
                    )

                inventory_errors, present_locators = _bundle_inventory_errors(
                    root_binding.descriptor,
                    manifest_path.name,
                    allowed_locators,
                    declared_files,
                    retained=retained,
                )
                errors.extend(inventory_errors)
                for locator, messages in forbidden_locators.items():
                    if locator in present_locators:
                        errors.extend(messages)
                root_binding.require_unchanged_chain(
                    description="review-packet lifecycle bundle"
                )
            finally:
                retained.cleanup(primary=sys.exception())
    except (OSError, RuntimeError, ValueError) as exc:
        suffix = (
            f": OS error {_os_error_name(exc)}"
            if isinstance(exc, OSError)
            else ""
        )
        errors.append(
            "review-packet lifecycle bundle inspection failed closed" + suffix
        )
    return errors


@dataclass(frozen=True, slots=True)
class _PortableManifestContext:
    data: dict[str, Any]
    lifecycle: dict[str, Any]
    stage: Any
    approval: dict[str, Any]
    activation: dict[str, Any]
    destination: dict[str, Any]
    retention: dict[str, Any]
    packet: dict[str, Any]
    items: list[Any]
    invocation: dict[str, Any]
    invocation_status: Any
    invoked: bool
    terminal_invocation: bool
    approved: bool
    receipts: dict[str, Any]
    pre_submission_present: bool
    ready_required: bool
    approval_required: bool


def _portable_manifest_context(data: dict[str, Any]) -> _PortableManifestContext:
    lifecycle = as_dict(data.get("lifecycle"))
    approval = as_dict(data.get("approval"))
    packet = as_dict(data.get("packet"))
    items_value = packet.get("items")
    items = items_value if isinstance(items_value, list) else []
    invocation = as_dict(data.get("invocation"))
    invocation_status = invocation.get("status")
    invoked = _string_choice(invocation_status, INVOCATION_STATUSES)
    terminal_invocation = _string_choice(invocation_status, TERMINAL_INVOCATION_STATUSES)
    approved = approval.get("status") == "approved"
    receipts = as_dict(data.get("validation_receipts"))
    stage = lifecycle.get("stage")
    ready_present = isinstance(receipts.get("packet_ready"), dict)
    pre_submission_present = isinstance(receipts.get("pre_submission"), dict)
    ready_required = (
        _string_choice(stage, ACTIVE_STAGES)
        or approved
        or invoked
        or ready_present
        or pre_submission_present
    )
    approval_required = _string_choice(
        stage, {"approved", "invoked", "returned", "validated", "closed"}
    ) or (stage == "blocked" and invoked)
    return _PortableManifestContext(
        data=data,
        lifecycle=lifecycle,
        stage=stage,
        approval=approval,
        activation=as_dict(data.get("activation")),
        destination=as_dict(data.get("destination")),
        retention=as_dict(data.get("retention")),
        packet=packet,
        items=items,
        invocation=invocation,
        invocation_status=invocation_status,
        invoked=invoked,
        terminal_invocation=terminal_invocation,
        approved=approved,
        receipts=receipts,
        pre_submission_present=pre_submission_present,
        ready_required=ready_required,
        approval_required=approval_required,
    )


def _inventory_identity_errors(items: list[Any]) -> list[str]:
    errors: list[str] = []
    item_ids: list[str] = []
    locators: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        item_id = item.get("item_id")
        locator = item.get("locator")
        if isinstance(item_id, str):
            item_ids.append(item_id)
        if safe_locator(locator):
            locators.append(str(locator))
    if len(item_ids) != len(set(item_ids)):
        errors.append("packet item IDs must be unique")
    if len(locators) != len(set(locators)):
        errors.append("packet item locators must be unique")
    return errors


def _receipt_and_approval_errors(context: _PortableManifestContext) -> list[str]:
    errors: list[str] = []
    if context.ready_required:
        for index, item in enumerate(context.items):
            if isinstance(item, dict) and not is_nonplaceholder_sha256(item.get("sha256")):
                errors.append(f"packet.items[{index}].sha256 must be non-placeholder SHA-256")
    ready_mismatches: list[str] = []
    if context.ready_required:
        ready_mismatches = receipt_mismatches(
            context.data,
            "packet_ready",
            context.receipts.get("packet_ready"),
        )
        errors.extend(ready_mismatches)
    ready = as_dict(context.receipts.get("packet_ready"))
    if context.ready_required and (
        context.activation.get("status") != "confirmed"
        or _parse_timestamp(context.activation.get("confirmed_at")) is None
        or context.destination.get("destination_confirmed") is not True
        or context.retention.get("provider_policy_confirmed") is not True
        or not context.items
    ):
        errors.append(
            "packet-ready-or-later state requires confirmed activation, destination, retention policy, and packet items"
        )
    if context.ready_required and context.packet.get("packet_sha256") != packet_binding_sha256(context.data):
        errors.append("packet.packet_sha256 does not match the canonical disclosure binding")
    if context.approval_required and not context.approved:
        errors.append("approved-or-later lifecycle requires approved status")
    if context.approved and (
        context.approval.get("exact_packet_approved") is not True
        or _parse_timestamp(context.approval.get("approved_at")) is None
        or ready_mismatches
        or context.approval.get("packet_ready_receipt_sha256") != ready.get("receipt_sha256")
    ):
        errors.append("approval does not bind the exact packet-ready receipt")
    if not context.approved and (
        context.approval.get("exact_packet_approved") is not False
        or context.approval.get("approved_at") is not None
        or context.approval.get("packet_ready_receipt_sha256") is not None
    ):
        errors.append("non-approved state cannot claim exact packet approval")
    return errors


def _lifecycle_and_invocation_errors(context: _PortableManifestContext) -> list[str]:
    errors: list[str] = []
    stage = context.stage
    invocation = context.invocation
    invocation_status = context.invocation_status
    if stage == "declined" and context.approval.get("status") != "declined":
        errors.append("declined lifecycle must match declined approval")
    if context.approval.get("status") == "declined" and stage != "declined":
        errors.append("declined approval requires declined lifecycle")
    if context.approved and _string_choice(stage, {"planned", "packet_ready", "declined"}):
        errors.append("approved packet cannot remain in a pre-approval or declined lifecycle")
    if stage == "invoked" and not context.invoked:
        errors.append("invoked lifecycle requires a started, returned, or failed invocation")
    if invocation_status == "started" and stage != "invoked":
        errors.append("started invocation requires invoked lifecycle")
    if context.terminal_invocation and not _string_choice(
        stage, {"returned", "validated", "closed", "blocked"}
    ):
        errors.append("terminal invocation requires returned, validated, closed, or blocked lifecycle")
    if (
        _string_choice(stage, {"returned", "validated", "closed"})
        and not context.terminal_invocation
    ):
        errors.append("returned-or-later lifecycle requires a returned or failed invocation")
    if stage == "blocked" and invocation_status == "started":
        errors.append("blocked lifecycle cannot leave an invocation in nonterminal started state")
    if stage == "declined" and not _string_choice(
        invocation_status, {"not_started", "skipped"}
    ):
        errors.append("declined lifecycle cannot contain an invocation")
    if context.invoked and _parse_timestamp(invocation.get("started_at")) is None:
        errors.append("invocation requires a start timestamp")
    if context.terminal_invocation and _parse_timestamp(invocation.get("ended_at")) is None:
        errors.append("terminal invocation requires an end timestamp")
    errors.extend(invocation_provenance_errors(invocation))
    if invocation_status == "returned" and (
        not is_nonplaceholder_sha256(invocation.get("output_sha256"))
        or invocation.get("failure_class") is not None
    ):
        errors.append(
            "returned invocation requires a non-placeholder output digest and no failure class"
        )
    if invocation_status == "failed" and not invocation.get("failure_class"):
        errors.append("failed invocation requires a failure class")
    if _string_choice(invocation_status, {"not_started", "skipped"}) and any(
        invocation.get(field) is not None
        for field in (
            "started_at", "ended_at", "output_sha256", "failure_class",
            "observed_cost", "observed_latency_seconds",
        )
    ):
        errors.append(
            "not-started or skipped invocation cannot claim timestamps, output, failure, cost, or latency"
        )
    if invocation_status == "started" and any(
        invocation.get(field) is not None
        for field in ("ended_at", "output_sha256", "failure_class")
    ):
        errors.append("started invocation cannot contain terminal state")
    return errors


def _preflight_errors(context: _PortableManifestContext) -> list[str]:
    preflight = as_dict(context.data.get("preflight"))
    errors = _phase_semantic_errors(preflight, "preflight")
    if _string_choice(preflight.get("status"), {"passed", "failed"}) and not context.approved:
        errors.append("completed preflight requires prior exact packet approval")
    if context.invoked or context.pre_submission_present:
        if not _phase_passed(context.data.get("preflight")):
            errors.append("invoked or pre-submission-receipted packet must contain a passed preflight")
        errors.extend(
            receipt_mismatches(
                context.data,
                "pre_submission",
                context.receipts.get("pre_submission"),
            )
        )
    return errors


def _verification_and_artifact_errors(
    context: _PortableManifestContext,
) -> tuple[list[str], list[dict[str, Any]]]:
    errors: list[str] = []
    verification = as_dict(context.data.get("verification"))
    verification_required = _string_choice(context.stage, {"validated", "closed"}) or (
        context.stage == "blocked" and context.invocation_status == "returned"
    )
    if verification_required and (
        verification.get("findings_classified") is not True
        or _parse_timestamp(verification.get("performed_at")) is None
        or not is_nonplaceholder_sha256(verification.get("verification_record_sha256"))
    ):
        errors.append("validated or closed review requires classified verification evidence")
    if verification.get("findings_classified") is True and not _string_choice(
        context.stage, {"validated", "closed", "blocked"}
    ):
        errors.append("classified verification requires validated, closed, or blocked lifecycle")
    if not verification_required and verification.get("findings_classified") is False and (
        verification.get("performed_at") is not None
        or verification.get("verification_record_sha256") is not None
    ):
        errors.append("unperformed verification cannot claim a time or digest")
    artifacts, artifact_errors = _artifact_maps(context.data)
    errors.extend(artifact_errors)
    if any(
        artifact.get("retention_status") == "retained" for artifact in artifacts
    ) and context.retention.get("local_retention_class") != "project_evidence":
        errors.append("retained evidence requires local_retention_class project_evidence")
    terminal_stage = context.stage == "closed" or (
        context.stage == "blocked" and context.terminal_invocation
    )
    abandoned_closeout = _preinvocation_abandonment(
        context.stage,
        context.invocation_status,
    ) and _phase_passed(context.data.get("closeout"))
    planned_artifacts = any(
        artifact.get("retention_status") == "planned" for artifact in artifacts
    )
    if terminal_stage and planned_artifacts:
        errors.append(
            "closed or terminal-blocked lifecycle cannot contain planned evidence artifacts"
        )
    elif abandoned_closeout and planned_artifacts:
        errors.append(
            "completed pre-invocation abandonment cannot contain planned evidence artifacts"
        )
    if context.invocation_status == "returned" and not _supporting_artifact(
        artifacts,
        role="review_output",
        digest=context.invocation.get("output_sha256"),
    ):
        errors.append("returned output digest is not bound to retained review_output evidence bytes")
    if context.invocation_status == "failed" and not _supporting_artifact(
        artifacts,
        role="failure_record",
    ):
        errors.append("failed invocation is not bound to retained failure_record evidence bytes")
    if verification_required and not _supporting_artifact(
        artifacts,
        role="verification_record",
        digest=verification.get("verification_record_sha256"),
    ):
        errors.append("verification digest is not bound to retained verification_record evidence bytes")
    return errors, artifacts


def _external_status_errors(
    context: _PortableManifestContext,
    external_status: str | None,
) -> list[str]:
    errors: list[str] = []
    verification = as_dict(context.data.get("verification"))
    if (
        external_status in {"approved", "used"}
        and as_dict(context.data.get("lane_controls")).get("manifest_kind")
        != "full"
    ):
        errors.append("external reviewer status requires a full control manifest")
    if external_status == "used":
        if not _string_choice(context.stage, {"validated", "closed"}):
            errors.append("external reviewer status used requires validated or closed lifecycle")
        if (
            context.invocation_status != "returned"
            or not is_nonplaceholder_sha256(context.invocation.get("output_sha256"))
        ):
            errors.append("external reviewer status used requires a returned output digest")
        if (
            verification.get("findings_classified") is not True
            or not isinstance(verification.get("performed_at"), str)
            or not is_nonplaceholder_sha256(verification.get("verification_record_sha256"))
        ):
            errors.append("external reviewer status used requires classified verification evidence")
    elif external_status == "approved" and not _string_choice(
        context.stage, {"approved", "invoked", "returned", "validated", "closed"}
    ):
        errors.append("external reviewer status approved requires approved-or-later lifecycle")
    return errors


def _closeout_errors(context: _PortableManifestContext) -> list[str]:
    closeout = as_dict(context.data.get("closeout"))
    errors = _phase_semantic_errors(closeout, "closeout")
    terminal_closeout_required = context.stage == "closed" or (
        context.stage == "blocked" and context.terminal_invocation
    )
    abandonment = _preinvocation_abandonment(
        context.stage,
        context.invocation_status,
    )
    closeout_started = _closeout_started(closeout)
    closeout_must_complete = terminal_closeout_required or (
        abandonment and closeout_started
    )
    closeout_incomplete = closeout_must_complete and (
        not _phase_passed(closeout)
        or not _string_choice(closeout.get("cleanup_status"), {"complete", "not_applicable"})
        or _parse_timestamp(closeout.get("performed_at")) is None
        or (closeout.get("cleanup_status") == "complete" and not closeout.get("cleanup_evidence_ref"))
    )
    if terminal_closeout_required and closeout_incomplete:
        errors.append(
            "closed or terminal-blocked lifecycle requires passed closeout and cleanup evidence"
        )
    elif abandonment and closeout_incomplete:
        errors.append(
            "begun pre-invocation abandonment closeout requires passed checks "
            "and cleanup evidence"
        )
    if not terminal_closeout_required and not abandonment and closeout_started:
        errors.append(
            "closeout cannot begin before closed or terminal-blocked lifecycle"
        )
    return errors


def _chronology_errors(context: _PortableManifestContext) -> list[str]:
    ready = as_dict(context.receipts.get("packet_ready"))
    verification = as_dict(context.data.get("verification"))
    closeout = as_dict(context.data.get("closeout"))
    timestamp_fields = [
        ("created_at", context.data.get("created_at")),
        ("activation.confirmed_at", context.activation.get("confirmed_at")),
        (
            "validation_receipts.packet_ready.validated_at",
            ready.get("validated_at"),
        ),
        ("approval.approved_at", context.approval.get("approved_at")),
        (
            "preflight.performed_at",
            as_dict(context.data.get("preflight")).get("performed_at"),
        ),
        (
            "validation_receipts.pre_submission.validated_at",
            as_dict(context.receipts.get("pre_submission")).get("validated_at"),
        ),
        ("invocation.started_at", context.invocation.get("started_at")),
        ("invocation.ended_at", context.invocation.get("ended_at")),
        ("verification.performed_at", verification.get("performed_at")),
        ("closeout.performed_at", closeout.get("performed_at")),
    ]
    previous_name: str | None = None
    previous_value: datetime | None = None
    latest_value: datetime | None = None
    errors: list[str] = []
    for field_name, raw in timestamp_fields:
        if raw is None:
            continue
        parsed = _parse_timestamp(raw)
        if parsed is None:
            errors.append(f"{field_name} must be a timezone-aware timestamp")
            continue
        if previous_value is not None and parsed < previous_value:
            errors.append(f"{field_name} precedes {previous_name}")
        previous_name, previous_value = field_name, parsed
        latest_value = parsed if latest_value is None or parsed > latest_value else latest_value
    stage_updated = _parse_timestamp(context.lifecycle.get("stage_updated_at"))
    if stage_updated is None:
        errors.append("lifecycle.stage_updated_at must be a timezone-aware timestamp")
    elif latest_value is not None and stage_updated < latest_value:
        errors.append("lifecycle.stage_updated_at precedes the latest lifecycle event")
    return errors


def portable_manifest_errors(
    data: Any,
    manifest_path: Path,
    *,
    external_status: str | None = None,
) -> list[str]:
    """Validate the neutral lifecycle, receipts, and exact retained bytes.

    Provider-specific lane selection and account rules remain the owning
    runtime's responsibility. When supplied, `external_status` is the
    source-artifact claim (`approved` or `used`) that this evidence must support.
    """

    if not isinstance(data, dict):
        return ["manifest root must be an object"]
    context = _portable_manifest_context(data)
    errors = schema_errors(data)
    if not _string_choice(
        context.stage,
        {"planned", "packet_ready", "approved", "invoked", "returned",
         "validated", "closed", "blocked", "declined"},
    ):
        errors.append("lifecycle.stage is invalid")
    errors.extend(_lane_control_errors(data))
    errors.extend(_planned_model_policy_errors(context))
    errors.extend(_inventory_identity_errors(context.items))
    errors.extend(_receipt_and_approval_errors(context))
    errors.extend(_lifecycle_and_invocation_errors(context))
    errors.extend(_preflight_errors(context))
    verification_errors, artifacts = _verification_and_artifact_errors(context)
    errors.extend(verification_errors)
    errors.extend(_external_status_errors(context, external_status))
    errors.extend(_closeout_errors(context))
    errors.extend(_chronology_errors(context))
    if (
        context.ready_required
        or artifacts
        or _preinvocation_abandonment(
            context.stage,
            context.invocation_status,
        )
    ):
        errors.extend(_bundle_errors(data, manifest_path))
    return errors


def prepare_receipt(
    data: Any,
    manifest_path: Path,
    *,
    phase: str,
    validated_at: str,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Return validated receipt fields without changing the manifest or bundle."""

    if phase not in RECEIPT_PHASES:
        return None, [f"unsupported review-packet receipt phase: {phase}"]
    if (
        RFC3339_DATETIME_RE.fullmatch(validated_at) is None
        or _parse_timestamp(validated_at) is None
    ):
        return None, [
            "validated_at must be an explicit timezone-aware RFC 3339 timestamp"
        ]
    if not isinstance(data, dict):
        return None, ["manifest root must be an object"]

    candidate = copy.deepcopy(data)
    packet = candidate.get("packet")
    lifecycle = candidate.get("lifecycle")
    receipts = candidate.get("validation_receipts")
    if not isinstance(packet, dict):
        return None, ["packet must be an object before preparing a receipt"]
    if not isinstance(lifecycle, dict):
        return None, ["lifecycle must be an object before preparing a receipt"]
    if not isinstance(receipts, dict):
        return None, [
            "validation_receipts must be an object before preparing a receipt"
        ]

    if phase == "packet_ready":
        if as_dict(candidate.get("approval")).get("status") != "pending":
            return None, ["packet_ready receipt must be prepared before approval"]
        if (
            not _string_choice(lifecycle.get("stage"), {"planned", "packet_ready"})
            or as_dict(candidate.get("invocation")).get("status") != "not_started"
        ):
            return None, [
                "packet_ready receipt requires a pre-approval, uninvoked lifecycle"
            ]
        packet["packet_sha256"] = packet_binding_sha256(candidate)
        lifecycle.update({"stage": "packet_ready", "stage_updated_at": validated_at})
    else:
        if as_dict(candidate.get("approval")).get("status") != "approved":
            return None, ["pre_submission receipt requires exact approval"]
        if (
            lifecycle.get("stage") != "approved"
            or as_dict(candidate.get("invocation")).get("status") != "not_started"
        ):
            return None, [
                "pre_submission receipt requires an approved, uninvoked lifecycle"
            ]
        if not _phase_passed(candidate.get("preflight")):
            return None, ["pre_submission receipt requires passed preflight"]
        if _parse_timestamp(as_dict(candidate.get("preflight")).get("performed_at")) is None:
            return None, [
                "pre_submission receipt requires a timestamped preflight"
            ]
        lifecycle["stage_updated_at"] = validated_at

    receipt = build_receipt(candidate, phase, validated_at)
    receipts[phase] = receipt
    errors = portable_manifest_errors(candidate, manifest_path)
    if errors:
        return None, errors
    return {
        "phase": phase,
        "packet_sha256": packet.get("packet_sha256"),
        "lifecycle_stage": lifecycle.get("stage"),
        "stage_updated_at": lifecycle.get("stage_updated_at"),
        "receipt": receipt,
    }, []


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate one bounded review-packet lifecycle bundle, or prepare "
            "validated receipt fields without writing it."
        ),
        allow_abbrev=False,
    )
    parser.add_argument(
        "manifest",
        type=Path,
        help="Review-packet manifest whose bounded lifecycle bundle is validated.",
    )
    parser.add_argument(
        "--external-status",
        choices=("approved", "used"),
        help="Optionally require the lifecycle evidence for a matching source-artifact claim.",
    )
    parser.add_argument(
        "--prepare-receipt",
        choices=RECEIPT_PHASES,
        help=(
            "Prepare exact packet_ready or pre_submission receipt fields on stdout; "
            "the manifest and bundle are not modified."
        ),
    )
    parser.add_argument(
        "--validated-at",
        help=(
            "Explicit timezone-aware RFC 3339 validation time; required exactly "
            "when --prepare-receipt is used."
        ),
    )
    args = parser.parse_args()
    if (args.prepare_receipt is None) != (args.validated_at is None):
        parser.error(
            "--prepare-receipt and --validated-at must be supplied together"
        )
    if args.prepare_receipt is not None and args.external_status is not None:
        parser.error(
            "--external-status cannot be combined with --prepare-receipt"
        )
    data, _raw, errors = load_manifest_file(args.manifest)
    prepared: dict[str, Any] | None = None
    if data is not None:
        if args.prepare_receipt is not None:
            prepared, preparation_errors = prepare_receipt(
                data,
                args.manifest,
                phase=args.prepare_receipt,
                validated_at=args.validated_at,
            )
            errors.extend(preparation_errors)
        else:
            errors.extend(
                portable_manifest_errors(
                    data,
                    args.manifest,
                    external_status=args.external_status,
                )
            )
    result: dict[str, Any] = {
        "manifest": str(args.manifest),
        "errors": errors,
    }
    if args.prepare_receipt is not None:
        result["prepared"] = prepared
    print(
        json.dumps(
            result,
            indent=2,
            sort_keys=True,
        )
    )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
