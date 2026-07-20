#!/usr/bin/env python3

"""Inspect, plan, apply, restore, and recover one retained project instance.

The refresh lifecycle is deliberately separate from bootstrap.  It consumes the
retained ``PROJECT_INPUT.json`` and ``PROJECT_INSTANCE.json`` written by the
bootstrap renderer, but it delegates all rendering, conformance, and filesystem
transaction mechanics to their existing owners.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import difflib
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any, Mapping, TypeGuard, cast

import bootstrap_transaction
import conformance_check
import integration_registry
import project_bootstrap
import project_contract_model as contract_model
import project_contract_sync
import project_input
import project_instance_lint
import project_state_lint
import safe_paths


FRAMEWORK_ROOT = Path(__file__).resolve().parent.parent
PLAN_SCHEMA_VERSION = 4
PLAN_KIND = "master-prompt-agreement-project-refresh"
EXIT_BLOCKED = 1
EXIT_INVOCATION = 2
EXIT_ROLLED_BACK = 3
EXIT_RECOVERY_REQUIRED = 4
CURRENT_ONLY_MANUAL_UPDATE_PREFIX = "current-only project update required:"
NEWER_FRAMEWORK_REQUIRED_PREFIX = "newer framework checkout required:"

PLAN_KEYS = frozenset(
    {
        "schema_version",
        "kind",
        "project_root",
        "current_contract_root",
        "target_contract_root",
        "mode",
        "framework_content_sha256",
        "framework_distribution_sha256",
        "framework_effective_changes",
        "current_input_sha256",
        "current_instance_sha256",
        "target_input",
        "target_input_sha256",
        "current_files",
        "target_files",
        "operations",
        "absent_parent_directories",
        "creation_modes",
        "required_actions",
        "warnings",
        "active_profiles",
        "post_apply_backout",
        "refresh_transaction_id",
        "plan_sha256",
    }
)
OPERATION_KEYS = frozenset(
    {
        "action",
        "category",
        "path",
        "current_sha256",
        "target_sha256",
        "current_mode",
        "target_mode",
        "approval_id",
    }
)
WARNING_KEYS = frozenset({"id", "message"})
BACKOUT_BUNDLE_SCHEMA_VERSION = 3
BACKOUT_BUNDLE_KIND = "master-prompt-agreement-refresh-backout-bundle"
BACKOUT_BUNDLE_MANIFEST = "BACKOUT_BUNDLE.json"
BACKOUT_BUNDLE_KEYS = frozenset(
    {
        "schema_version",
        "kind",
        "plan_sha256",
        "refresh_transaction_id",
        "project_root",
        "current_contract_root",
        "absent_parent_directories",
        "entries",
    }
)
BACKOUT_ENTRY_KEYS = frozenset({"path", "state", "sha256", "mode", "blob"})
CREATION_MODE_KEYS = frozenset({"file", "directory"})
EFFECTIVE_CHANGE_KEYS = frozenset(
    {"exact_delta_available", "added", "removed", "changed"}
)
OPERATION_ACTIONS = frozenset({"create", "replace", "preserve", "remove"})
OPERATION_CATEGORIES = frozenset({"immutable", "mutable", "metadata"})


@dataclass(frozen=True, slots=True)
class CurrentInstance:
    project_root: Path
    contract_root_ref: str
    contract_root: Path
    manifest: dict[str, Any]
    manifest_raw: bytes
    retained_input: dict[str, object]
    input_raw: bytes
    current_files: dict[str, str]


@dataclass(frozen=True, slots=True)
class PlanBuild:
    payload: dict[str, object] | None
    target_outputs: dict[str, str]
    remove_outputs: list[str]
    errors: list[str]


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _is_posix_rwx_mode(value: object) -> bool:
    return type(value) is int and 0 <= value <= 0o777


def _is_numbered_approval_id(value: object, prefix: str) -> bool:
    return (
        isinstance(value, str)
        and value.startswith(prefix)
        and len(value) == len(prefix) + 4
        and value[len(prefix) :].isdigit()
        and value[len(prefix) :] != "0000"
    )


def _warning_id(message: str) -> str:
    """Bind a warning approval to its exact, stable diagnostic text."""

    return "REFRESH-W-" + _sha256(message.encode("utf-8"))


def _warning_records(messages: list[str]) -> list[dict[str, str]]:
    """Return canonical, content-addressed warning records without duplicates."""

    records = [
        {"id": _warning_id(message), "message": message}
        for message in set(messages)
        if message
    ]
    return sorted(records, key=lambda item: (item["id"], item["message"]))


def _optional_state_retirement_warning(path: str, category: str) -> str:
    """Describe one exact partition-specific optional-state retirement effect."""

    if category == "mutable":
        return (
            "optional mutable-state retirement removes receipt-owned project state from "
            f"the active project tree: {path}. The reviewed plan binds its exact preimage "
            "bytes and POSIX rwx mode, and apply requires a verified exact-preimage "
            "backout bundle before removal"
        )
    if category == "immutable":
        return (
            "optional immutable-state retirement removes a receipt-owned generated "
            f"surface from the active project tree: {path}. The reviewed plan binds "
            "its exact current-byte digest and POSIX rwx mode, and removal follows "
            "the plan's selected and approved post-apply backout basis"
        )
    raise ValueError(f"optional-state retirement category is invalid: {category}")


def _manual_update_error(message: str) -> str:
    return f"{CURRENT_ONLY_MANUAL_UPDATE_PREFIX} {message}"


def _manual_update_required(errors: list[str]) -> bool:
    return any(error.startswith(CURRENT_ONLY_MANUAL_UPDATE_PREFIX) for error in errors)


def _newer_framework_error(message: str) -> str:
    return f"{NEWER_FRAMEWORK_REQUIRED_PREFIX} {message}"


def _newer_framework_required(errors: list[str]) -> bool:
    return any(error.startswith(NEWER_FRAMEWORK_REQUIRED_PREFIX) for error in errors)


def _error_status(default: str, errors: list[str]) -> str:
    if _newer_framework_required(errors):
        return "newer-framework-required"
    return "manual-update-required" if _manual_update_required(errors) else default


def _effective_framework_changes(
    recorded: object,
    selected: Mapping[str, str] | None = None,
) -> dict[str, object]:
    selected_map = (
        project_bootstrap.framework_effective_file_digests(FRAMEWORK_ROOT)
        if selected is None
        else dict(selected)
    )
    def valid_digest_map(value: object) -> TypeGuard[dict[str, str]]:
        if not isinstance(value, dict):
            return False
        for path, digest in value.items():
            if not isinstance(path, str) or not _is_sha256(digest):
                return False
            try:
                safe_paths.normalize_repo_relative_path(
                    path,
                    FRAMEWORK_ROOT,
                    description="framework effective-file path",
                )
            except ValueError:
                return False
        return True

    if not valid_digest_map(recorded) or not valid_digest_map(selected_map):
        raise ValueError(
            "exact framework-change reporting requires valid recorded and selected digest maps"
        )
    recorded_map = {str(path): str(digest) for path, digest in recorded.items()}
    return {
        "exact_delta_available": True,
        "added": sorted(set(selected_map) - set(recorded_map)),
        "removed": sorted(set(recorded_map) - set(selected_map)),
        "changed": sorted(
            path
            for path in set(selected_map).intersection(recorded_map)
            if selected_map[path] != recorded_map[path]
        ),
    }


def _plan_digest(payload: Mapping[str, object]) -> str:
    unsigned = dict(payload)
    unsigned.pop("plan_sha256", None)
    return _sha256(_canonical_json_bytes(unsigned))


def _refresh_transaction_id(payload: Mapping[str, object]) -> str:
    unsigned = dict(payload)
    unsigned.pop("plan_sha256", None)
    unsigned.pop("refresh_transaction_id", None)
    return _sha256(
        b"master-prompt-agreement-refresh-transaction-v1\0"
        + _canonical_json_bytes(unsigned)
    )[:32]


def _finalize_plan(payload: dict[str, object]) -> None:
    payload["refresh_transaction_id"] = _refresh_transaction_id(payload)
    payload["plan_sha256"] = _plan_digest(payload)


def _print(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False))


def _contract_root(
    project_root: Path,
    contract_root_ref: str,
) -> tuple[Path, list[str]]:
    contract_root, error = project_instance_lint.contract_root_path(
        project_root,
        contract_root_ref,
    )
    return contract_root, ([error] if error is not None else [])


def _resolve_contract_root_selection(
    project_root: Path,
    supplied_contract_root: str | None,
) -> tuple[str | None, list[str]]:
    """Resolve the sole current layout from the complete current-format root receipt."""

    manifest_path = project_root / project_bootstrap.INSTANCE_MANIFEST
    manifest_present = os.path.lexists(manifest_path)
    if not manifest_present:
        return None, [
            _manual_update_error(
                f"root-scoped {project_bootstrap.INSTANCE_MANIFEST} is absent. The "
                "refresh lifecycle requires a complete current-format root receipt and retained "
                "input; an explicit --contract-root cannot replace that evidence. "
                "Perform a reviewed project-specific manual update first"
            )
        ]

    manifest, manifest_errors = project_instance_lint.load_manifest(manifest_path)
    if manifest is None or manifest_errors:
        return None, [
            _manual_update_error(
                "root-scoped project instance receipt cannot supply verified current "
                "identity: "
                + "; ".join(manifest_errors or ["receipt payload is unavailable"])
                + ". Perform a reviewed project-specific manual update first"
            )
        ]
    schema_error = project_instance_lint.schema_version_preflight_error(manifest)
    if schema_error is not None:
        version = manifest.get("schema_version")
        if (
            type(version) is int
            and version > project_bootstrap.PROJECT_INSTANCE_SCHEMA_VERSION
        ):
            return None, [_newer_framework_error(schema_error)]
        return None, [_manual_update_error(schema_error)]
    recorded_contract_root = manifest.get("contract_root")
    if not isinstance(recorded_contract_root, str):
        return None, [
            _manual_update_error(
                "root-scoped project instance receipt contract_root is malformed; "
                "perform a reviewed project-specific manual update first"
            )
        ]
    _selected_root, selection_errors = _contract_root(
        project_root,
        recorded_contract_root,
    )
    if selection_errors:
        return None, [
            _manual_update_error(
                "root-scoped project instance receipt has an invalid contract_root "
                "placement: "
                + "; ".join(selection_errors)
                + ". Perform a reviewed project-specific manual update first"
            )
        ]
    if (
        supplied_contract_root is not None
        and supplied_contract_root != recorded_contract_root
    ):
        return None, [
            "explicit --contract-root does not match the root-scoped project "
            "instance receipt: "
            f"expected {recorded_contract_root!r}, found {supplied_contract_root!r}"
        ]
    return recorded_contract_root, []


def _project_file_digest(project_root: Path, name: str) -> tuple[str | None, str | None]:
    try:
        normalized = safe_paths.normalize_repo_relative_path(
            name,
            project_root,
            description=f"managed project file {name}",
        )
        raw = safe_paths.read_regular_file_bytes(
            project_root / normalized,
            description=f"managed project file {name}",
        )
    except FileNotFoundError:
        return None, f"managed project file is missing: {name}"
    except (OSError, ValueError) as exc:
        return None, f"managed project file is not a bounded regular input: {name}: {exc}"
    return _sha256(raw), None


def _existing_project_file_evidence(
    project_root: Path,
    name: str,
) -> tuple[str | None, int | None, str | None]:
    try:
        normalized = safe_paths.normalize_repo_relative_path(
            name,
            project_root,
            description=f"candidate project file {name}",
        )
        path = project_root / normalized
        before = path.lstat()
        raw = safe_paths.read_regular_file_bytes(
            path,
            description=f"candidate project file {name}",
        )
        after = path.lstat()
    except FileNotFoundError:
        return None, None, None
    except (OSError, ValueError) as exc:
        return (
            None,
            None,
            f"candidate project file is not a bounded regular input: {name}: {exc}",
        )
    if (
        safe_paths.stable_file_metadata(before)
        != safe_paths.stable_file_metadata(after)
    ):
        return None, None, f"candidate project file changed while inspected: {name}"
    mode = stat.S_IMODE(after.st_mode)
    if mode & ~0o777:
        return (
            None,
            None,
            "candidate project file uses unsupported special permission bits: " + name,
        )
    return _sha256(raw), mode, None


def _existing_project_file_digest(
    project_root: Path,
    name: str,
) -> tuple[str | None, str | None]:
    digest, _mode, error = _existing_project_file_evidence(project_root, name)
    return digest, error


def _creation_modes_from_umask() -> tuple[int, int]:
    """Derive the existing creation-mode contract without filesystem writes.

    Refresh is a single-threaded CLI. Reading POSIX umask requires replacing it,
    so restore it immediately before returning the modes that the former file and
    directory probes observed.
    """

    current_umask = os.umask(0)
    try:
        return 0o666 & ~current_umask, 0o755 & ~current_umask
    finally:
        os.umask(current_umask)


def _absent_parent_directories(
    project_root: Path,
    operations: list[dict[str, object]],
) -> tuple[list[str], list[str]]:
    """Bind every absent strict parent created for planned file additions.

    These paths are not removed during apply. They are retained in the signed
    plan so an exact post-apply restore can retire only directories that the
    forward transition introduced. Existing directories are never eligible.
    """

    candidates: set[str] = set()
    for operation in operations:
        if operation.get("action") != "create":
            continue
        raw_path = operation.get("path")
        if not isinstance(raw_path, str):
            continue
        parts = raw_path.split("/")
        for stop in range(1, len(parts)):
            candidates.add("/".join(parts[:stop]))

    absent: list[str] = []
    errors: list[str] = []
    for relative in sorted(candidates, key=lambda value: (value.count("/"), value)):
        path = project_root / relative
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            absent.append(relative)
            continue
        except OSError as exc:
            errors.append(
                f"planned output parent could not be inspected without following links: "
                f"{relative}: {exc}"
            )
            continue
        if path.is_symlink() or not stat.S_ISDIR(metadata.st_mode):
            errors.append(
                "planned output parent must be an existing non-symlink directory or "
                f"be absent: {relative}"
            )
    return sorted(absent), errors


def _generated_contract_format_errors(
    project_root: Path,
    contract_root_ref: str,
) -> list[str]:
    """Classify readable generated-contract identity before digest drift.

    Missing, unreadable, or non-UTF-8 managed files remain ordinary current-instance
    integrity failures.  When both generated contracts are readable, however, a
    noncurrent or misplaced format marker identifies an unsupported generated format
    rather than repairable managed-byte drift.
    """

    texts: list[str] = []
    for name in ("STATEMENT_OF_WORK.md", "AGENT_PROJECT.md"):
        relative = project_bootstrap.project_relative_output(
            contract_root_ref,
            name,
        )
        try:
            raw = safe_paths.read_regular_file_bytes(
                project_root / relative,
                description=f"generated contract format identity {relative}",
            )
            texts.append(raw.decode("utf-8"))
        except (FileNotFoundError, OSError, UnicodeDecodeError, ValueError):
            return []
    observations = (
        project_contract_sync.contract_format_observation(texts[0]),
        project_contract_sync.contract_format_observation(texts[1]),
    )
    expected = project_bootstrap.contract_model.CONTRACT_FORMAT_VERSION
    if all(
        state == "present" and version == expected
        for state, version in observations
    ):
        return []

    def label(observation: tuple[str, int | None]) -> str:
        state, version = observation
        return f"present format {version}" if state == "present" else state

    return [
        "generated contract format identity does not use supported current format "
        f"{expected}: STATEMENT_OF_WORK.md marker is {label(observations[0])}; "
        f"AGENT_PROJECT.md marker is {label(observations[1])}"
    ]


def _load_current_instance(
    project_root: Path,
    contract_root_ref: str,
    *,
    preimage: dict[str, object] | None = None,
) -> tuple[CurrentInstance | None, list[str]]:
    if preimage is None:
        preimage = project_instance_lint.validate_recorded_preimage(
            project_root,
            contract_root_ref,
        )
    errors = list(cast(list[str], preimage["errors"]))
    if errors:
        preimage_manifest = preimage.get("manifest")
        preimage_input = preimage.get("retained_input")
        receipt_version = (
            preimage_manifest.get("schema_version")
            if isinstance(preimage_manifest, dict)
            else None
        )
        recorded_input_version = (
            preimage_manifest.get("project_input_schema_version")
            if isinstance(preimage_manifest, dict)
            else None
        )
        retained_input_version = (
            preimage_input.get("schema_version")
            if isinstance(preimage_input, dict)
            else None
        )
        contract_format = (
            preimage_manifest.get("project_contract_format")
            if isinstance(preimage_manifest, dict)
            else None
        )
        if (
            type(receipt_version) is int
            and receipt_version > project_bootstrap.PROJECT_INSTANCE_SCHEMA_VERSION
        ) or (
            type(recorded_input_version) is int
            and recorded_input_version > project_input.SCHEMA_VERSION
        ) or (
            type(retained_input_version) is int
            and retained_input_version > project_input.SCHEMA_VERSION
        ) or (
            type(contract_format) is int
            and contract_format > project_bootstrap.contract_model.CONTRACT_FORMAT_VERSION
        ):
            return None, [_newer_framework_error(errors[0])]
    format_errors = _generated_contract_format_errors(
        project_root,
        contract_root_ref,
    )
    if format_errors:
        return None, [
            _manual_update_error(
                format_errors[0]
                + "; perform a reviewed project-specific manual update first"
            )
        ]
    if errors:
        return None, [
            _manual_update_error(
                "recorded project instance is inconsistent: "
                + errors[0]
                + "; perform a reviewed project-specific manual update first"
            )
        ]
    context = preimage.get("context")
    manifest = preimage.get("manifest")
    retained_input = preimage.get("retained_input")
    input_raw = preimage.get("input_raw")
    managed_files = preimage.get("managed_files")
    if (
        not isinstance(context, project_instance_lint.LintContext)
        or not isinstance(manifest, dict)
        or not isinstance(retained_input, dict)
        or not isinstance(input_raw, bytes)
        or not isinstance(managed_files, list)
        or not all(isinstance(item, str) for item in managed_files)
    ):
        return None, ["recorded-preimage validator returned an incomplete current instance"]

    input_name = project_bootstrap.project_relative_output(
        contract_root_ref,
        project_input.INPUT_NAME,
    )
    manifest_name = project_bootstrap.INSTANCE_MANIFEST
    current_files: dict[str, str] = {}
    # The recorded preimage above already classified every stable inconsistency.
    # A failure in this second, plan-snapshot read therefore means the project
    # changed or became unreadable after validation. Keep that attempt a generic
    # no-write abort; a persistent condition is classified for manual update by
    # the next recorded-preimage validation.
    for name in sorted({*managed_files, input_name, manifest_name}):
        digest, file_error = _project_file_digest(project_root, name)
        if file_error is not None:
            errors.append(file_error)
        elif digest is not None:
            current_files[name] = digest
    contract_local_manifest_name = project_bootstrap.project_relative_output(
        contract_root_ref,
        project_bootstrap.INSTANCE_MANIFEST,
    )
    if (
        contract_local_manifest_name != manifest_name
        and os.path.lexists(project_root / contract_local_manifest_name)
    ):
        errors.append(
            _manual_update_error(
                "a contract-local project instance receipt remains alongside the "
                "root-scoped receipt. The current lifecycle permits only the root-scoped "
                "receipt; perform a reviewed project-specific manual update to retire "
                f"the extra file: {contract_local_manifest_name}"
            )
        )
    manifest_path = project_root / manifest_name
    try:
        manifest_raw = safe_paths.read_regular_file_bytes(
            manifest_path,
            description="project instance manifest",
        )
    except (OSError, ValueError) as exc:
        errors.append(f"project instance manifest could not be reread safely: {exc}")
        return None, errors
    if errors:
        return None, errors
    return (
        CurrentInstance(
            project_root=project_root,
            contract_root_ref=contract_root_ref,
            contract_root=context.contract_root,
            manifest=manifest,
            manifest_raw=manifest_raw,
            retained_input=retained_input,
            input_raw=input_raw,
            current_files=current_files,
        ),
        [],
    )


def _transaction_blocker(project_root: Path) -> tuple[object, list[str]]:
    try:
        status = bootstrap_transaction.transaction_recovery_status(project_root)
    except (OSError, ValueError) as exc:
        return None, [f"transaction recovery state could not be inspected: {exc}"]
    errors = list(status.errors)
    if status.state == "active":
        errors.append(
            "another project transaction is active; wait for its owner to finish and "
            "then inspect again instead of attempting recovery"
        )
    elif status.state != "clean":
        errors.append(
            "an interrupted project transaction requires explicit recovery before refresh: "
            f"state {status.state}, transaction {status.transaction_id or 'unknown'}, "
            f"phase {status.phase or 'unknown'}"
        )
    return status, errors


def _clean_project_preflight(
    project_root: Path,
) -> tuple[Path, dict[str, object] | None]:
    """Fail before governed project reads unless transaction controls are clean."""

    project_root = project_root.expanduser().resolve(strict=False)
    status, errors = _transaction_blocker(project_root)
    if not errors:
        return project_root, None
    return project_root, {
        "status": "recovery-required",
        "project_root": str(project_root),
        "transaction_state": getattr(status, "state", None),
        "transaction_id": getattr(status, "transaction_id", None),
        "phase": getattr(status, "phase", None),
        "can_rollback": getattr(status, "can_rollback", False),
        "can_finalize": getattr(status, "can_finalize", False),
        "errors": errors,
    }


def inspect_project(
    project_root: Path,
    contract_root_ref: str | None = None,
) -> dict[str, object]:
    project_root = project_root.expanduser().resolve(strict=False)
    status, recovery_errors = _transaction_blocker(project_root)
    if recovery_errors:
        transaction_state = getattr(status, "state", None)
        report_status = (
            "transaction-active"
            if transaction_state == "active"
            else "recovery-required"
            if transaction_state in {"recovery-required", "verified"}
            else "invalid"
        )
        return {
            "status": report_status,
            "project_root": str(project_root),
            "contract_root": contract_root_ref,
            "errors": recovery_errors,
            "transaction_id": getattr(status, "transaction_id", None),
            "phase": getattr(status, "phase", None),
            "can_rollback": getattr(status, "can_rollback", False),
            "can_finalize": getattr(status, "can_finalize", False),
        }
    selected_contract_root, selection_errors = _resolve_contract_root_selection(
        project_root,
        contract_root_ref,
    )
    if selection_errors or selected_contract_root is None:
        return {
            "status": _error_status("invalid", selection_errors),
            "project_root": str(project_root),
            "contract_root": contract_root_ref,
            "errors": selection_errors,
        }
    contract_root_ref = selected_contract_root
    contract_root, contract_errors = _contract_root(project_root, contract_root_ref)
    if contract_errors:
        return {
            "status": "invalid",
            "project_root": str(project_root),
            "contract_root": contract_root_ref,
            "errors": contract_errors,
        }
    preimage = project_instance_lint.validate_recorded_preimage(
        project_root,
        contract_root_ref,
    )
    instance, errors = _load_current_instance(
        project_root,
        contract_root_ref,
        preimage=preimage,
    )
    if instance is None:
        return {
            "status": _error_status("invalid", errors),
            "project_root": str(project_root),
            "contract_root": contract_root_ref,
            "errors": errors,
        }
    selected_identity = project_bootstrap.capture_framework_identity(FRAMEWORK_ROOT)
    current_framework_digest = selected_identity.content_sha256
    current_distribution_digest = selected_identity.distribution_sha256
    effective_changes = _effective_framework_changes(
        instance.manifest.get("framework_effective_file_digests"),
        selected_identity.effective_file_digest_map(),
    )
    effective_current = bool(effective_changes["exact_delta_available"]) and not any(
        effective_changes[key] for key in ("added", "removed", "changed")
    )
    distribution_drift = (
        instance.manifest.get("framework_distribution_sha256")
        != current_distribution_digest
    )
    selected_warnings = list(cast(list[str], preimage.get("warnings", [])))
    recorded_runtime = instance.retained_input.get("runtime")
    runtime_revision_required = (
        instance.retained_input.get("project_kind") == "downstream"
        and isinstance(recorded_runtime, str)
        and recorded_runtime not in project_bootstrap.ENTRYPOINT_TEMPLATES
    )
    if runtime_revision_required:
        return {
            "status": "runtime-revision-required",
            "project_root": str(project_root),
            "contract_root": contract_root_ref,
            "recorded_runtime": recorded_runtime,
            "available_runtimes": sorted(project_bootstrap.ENTRYPOINT_TEMPLATES),
            "framework_content_sha256": current_framework_digest,
            "framework_distribution_sha256": current_distribution_digest,
            "framework_effective_changes": effective_changes,
            "distribution_drift": distribution_drift,
            "errors": [],
            "warnings": selected_warnings,
        }
    if effective_current:
        selected_result = project_instance_lint.validate_selected_checkout(
            preimage,
            framework_root=FRAMEWORK_ROOT,
        )
        if selected_result["errors"]:
            return {
                "status": "invalid",
                "project_root": str(project_root),
                "contract_root": contract_root_ref,
                "errors": selected_result["errors"],
                "warnings": selected_result["warnings"],
            }
        selected_warnings.extend(selected_result["warnings"])
    report_status = (
        "refresh-available"
        if not effective_current
        else "distribution-only-drift"
        if distribution_drift
        else "current"
    )
    return {
        "status": report_status,
        "project_root": str(project_root),
        "contract_root": contract_root_ref,
        "framework_content_sha256": current_framework_digest,
        "recorded_framework_content_sha256": instance.manifest.get(
            "framework_content_sha256"
        ),
        "framework_distribution_sha256": current_distribution_digest,
        "recorded_framework_distribution_sha256": instance.manifest.get(
            "framework_distribution_sha256"
        ),
        "distribution_drift": distribution_drift,
        "framework_effective_changes": effective_changes,
        "active_profiles": instance.manifest.get("active_profiles", []),
        "errors": [],
        "warnings": selected_warnings,
    }


def render_candidate_input(
    *,
    answers_path: Path,
    project_root: Path,
    project_kind: str,
    contract_root_ref: str | None,
    runtime: str | None,
    runtime_wrappers: tuple[str, ...] | None = None,
    framework_reference: str,
    framework_revision_policy: str,
) -> tuple[dict[str, object] | None, list[str]]:
    project_root = project_root.expanduser().resolve(strict=False)
    _status, recovery_errors = _transaction_blocker(project_root)
    if recovery_errors:
        return None, recovery_errors
    selected_contract_root, selection_errors = _resolve_contract_root_selection(
        project_root,
        contract_root_ref,
    )
    if selection_errors or selected_contract_root is None:
        return None, selection_errors
    contract_root_ref = selected_contract_root
    current, current_errors = _load_current_instance(
        project_root,
        contract_root_ref,
    )
    if current is None:
        return None, current_errors
    if project_kind != current.retained_input.get("project_kind"):
        return None, [
            "candidate project_kind must match the verified current retained input"
        ]
    recorded_runtime = current.retained_input.get("runtime")
    if (
        project_kind == "downstream"
        and runtime != recorded_runtime
        and runtime_wrappers is None
    ):
        return None, [
            "changing the runtime family requires an explicit complete runtime-wrapper "
            "selection: repeat --runtime-wrapper for every target wrapper or use "
            "--clear-runtime-wrappers for an empty set"
        ]
    selected_runtime_wrappers: tuple[str, ...]
    if project_kind == "framework-authoring":
        if runtime_wrappers not in {None, ()}:
            return None, [
                "framework-authoring candidate creation does not support runtime wrappers"
            ]
        selected_runtime_wrappers = ()
    elif runtime_wrappers is None:
        retained_wrappers = current.retained_input.get("runtime_wrappers")
        if not isinstance(retained_wrappers, list) or any(
            not isinstance(item, str) for item in retained_wrappers
        ):
            return None, [
                "verified current retained input runtime_wrappers must be a list of strings"
            ]
        selected_runtime_wrappers = tuple(sorted(retained_wrappers))
    else:
        selected_runtime_wrappers = tuple(sorted(runtime_wrappers))
    _path, _raw, answers, errors = project_bootstrap.load_json_input(
        str(answers_path),
        "candidate bootstrap answers",
    )
    if not isinstance(answers, dict):
        if not errors:
            errors.append("candidate bootstrap answers must be a JSON object")
        return None, errors
    errors.extend(
        project_bootstrap.validate_answers(
            answers,
            automation_project_root=project_root,
            automation_manifest_path=(
                project_root
                / project_bootstrap.project_relative_output(
                    contract_root_ref,
                    "AUTOMATION_ORDERS.json",
                )
            ),
            require_existing_automation_project_root=False,
        )
    )
    if not isinstance(answers.get("date"), str):
        errors.append(
            "candidate bootstrap answers must explicitly retain or deliberately revise answers.date; candidate creation never substitutes today's date"
        )
    try:
        canonical_reference = safe_paths.canonical_framework_reference(
            framework_reference
        )
    except ValueError as exc:
        errors.append(str(exc))
        canonical_reference = framework_reference
    reference_status, reference_errors, _reference_warnings = (
        project_bootstrap.framework_reference_binding(
            canonical_reference,
            project_root,
            FRAMEWORK_ROOT,
        )
    )
    errors.extend(reference_errors)
    if reference_status != "verified":
        errors.append(
            "candidate framework reference must resolve to the checkout creating it"
        )
    try:
        text = project_input.render_project_input(
            project_kind=project_kind,
            contract_root=contract_root_ref,
            runtime=runtime,
            framework_reference=canonical_reference,
            framework_revision_policy=framework_revision_policy,
            answers=answers,
            runtime_wrappers=selected_runtime_wrappers,
        )
    except ValueError as exc:
        errors.append(str(exc))
        text = ""
    if errors:
        return None, errors
    payload = json.loads(text)
    assert isinstance(payload, dict)
    return payload, []


def _load_candidate_input(path: Path) -> tuple[dict[str, object] | None, list[str]]:
    payload, _raw, errors = project_input.load_project_input(path)
    return payload, errors


def _validated_private_backout_root(
    value: object,
    *,
    project_root: Path,
    require_current: bool,
) -> tuple[Path | None, list[str]]:
    if not isinstance(value, str) or not value:
        return None, ["exact-preimage backout root must be a non-empty string"]
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        return None, ["exact-preimage backout root must be an explicit absolute path"]
    if not require_current:
        return candidate.resolve(strict=False), []
    ancestor_errors: list[str] = []
    current = Path(candidate.anchor)
    for part in candidate.parts[1:]:
        current /= part
        try:
            current_metadata = current.lstat()
        except OSError as exc:
            ancestor_errors.append(
                f"exact-preimage backout root component is unavailable: {current}: {exc}"
            )
            break
        if stat.S_ISLNK(current_metadata.st_mode):
            ancestor_errors.append(
                f"exact-preimage backout root must not traverse symlinks: {current}"
            )
            break
    try:
        metadata = candidate.lstat()
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        return None, [f"exact-preimage backout root is unavailable: {exc}"]
    errors: list[str] = list(ancestor_errors)
    if candidate.is_symlink() or not stat.S_ISDIR(metadata.st_mode):
        errors.append("exact-preimage backout root must be a regular non-symlink directory")
    owner = getattr(os, "geteuid", lambda: metadata.st_uid)()
    if metadata.st_uid != owner:
        errors.append("exact-preimage backout root must be owned by the current user")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        errors.append(
            "exact-preimage backout root must not grant group or world permissions"
        )
    project_root = project_root.expanduser().resolve(strict=False)
    if resolved == project_root or safe_paths.path_within_root(resolved, project_root):
        errors.append("exact-preimage backout root must be outside the project root")
    return (resolved if not errors else None), errors


def _private_artifact_errors(
    path: Path,
    *,
    description: str,
    directory: bool,
) -> list[str]:
    try:
        metadata = path.lstat()
    except OSError as exc:
        return [f"{description} is unavailable: {exc}"]
    errors: list[str] = []
    expected_kind = stat.S_ISDIR if directory else stat.S_ISREG
    if path.is_symlink() or not expected_kind(metadata.st_mode):
        errors.append(
            f"{description} must be a regular non-symlink "
            + ("directory" if directory else "file")
        )
    owner = getattr(os, "geteuid", lambda: metadata.st_uid)()
    if metadata.st_uid != owner:
        errors.append(f"{description} must be owned by the current user")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        errors.append(f"{description} must not grant group or world permissions")
    return errors


def _backout_basis(
    *,
    project_root: Path,
    backout_root: str | None,
    accept_none: bool,
) -> tuple[dict[str, object] | None, list[str]]:
    if backout_root is not None and accept_none:
        return None, [
            "--backout-root and --accept-no-post-apply-backout are mutually exclusive"
        ]
    if backout_root is not None:
        root, errors = _validated_private_backout_root(
            backout_root,
            project_root=project_root,
            require_current=True,
        )
        if root is None:
            return None, errors
        return {"kind": "exact-preimage-bundle", "root": str(root)}, []
    if accept_none:
        return {"kind": "none"}, []
    return None, []


def _validate_backout_basis(
    value: object,
    *,
    require_current: bool,
    project_root: Path | None = None,
) -> list[str]:
    if not isinstance(value, dict):
        return ["post_apply_backout must use a closed object schema"]
    kind = value.get("kind")
    if kind in {"not-required", "none"}:
        if set(value) != {"kind"}:
            return [f"post_apply_backout kind {kind} permits only the kind field"]
        return []
    if kind == "exact-preimage-bundle":
        if set(value) != {"kind", "root"}:
            return [
                "exact-preimage post_apply_backout must use the exact kind/root schema"
            ]
        if project_root is None:
            root_value = value.get("root")
            if not isinstance(root_value, str) or not Path(root_value).is_absolute():
                return ["exact-preimage backout root must be an absolute path string"]
            return []
        _root, errors = _validated_private_backout_root(
            value.get("root"),
            project_root=project_root,
            require_current=require_current,
        )
        return errors
    return [
        "post_apply_backout kind must be exact-preimage-bundle, none, or not-required"
    ]


def _target_for_input(
    project_root: Path,
    retained_input: dict[str, object],
) -> tuple[dict[str, str], list[str], list[dict[str, str]], list[str]]:
    schema_error = project_input.schema_version_preflight_error(retained_input)
    if schema_error is not None:
        version = retained_input.get("schema_version")
        lifecycle_error = (
            _newer_framework_error(schema_error)
            if type(version) is int and version > project_input.SCHEMA_VERSION
            else _manual_update_error(schema_error)
        )
        return {}, [lifecycle_error], [], []
    errors = project_input.validate_project_input(retained_input, project_root=project_root)
    answers = retained_input.get("answers")
    runtime = retained_input.get("runtime")
    runtime_wrappers = retained_input.get("runtime_wrappers")
    project_kind = retained_input.get("project_kind")
    contract_root_ref = retained_input.get("contract_root")
    framework_reference = retained_input.get("framework_reference")
    revision_policy = retained_input.get("framework_revision_policy")
    if not isinstance(answers, dict):
        errors.append("target project input answers must be an object")
    if project_kind == "downstream" and not isinstance(runtime, str):
        errors.append("target downstream project input runtime must be a string")
    if project_kind == "framework-authoring" and runtime is not None:
        errors.append("target framework-authoring project input runtime must be null")
    if not isinstance(runtime_wrappers, list) or any(
        not isinstance(item, str) for item in runtime_wrappers
    ):
        errors.append("target project input runtime_wrappers must be a list of strings")
    if not isinstance(contract_root_ref, str):
        errors.append("target project input contract_root must be a string")
    if not isinstance(framework_reference, str):
        errors.append("target project input framework_reference must be a string")
    if not isinstance(revision_policy, str):
        errors.append("target project input framework_revision_policy must be a string")
    if errors:
        return {}, errors, [], []
    assert isinstance(answers, dict)
    assert project_kind in {"downstream", "framework-authoring"}
    assert isinstance(contract_root_ref, str)
    assert isinstance(framework_reference, str)
    assert isinstance(revision_policy, str)
    assert isinstance(runtime_wrappers, list)
    graph_errors = project_bootstrap.planned_output_graph_errors(
        project_bootstrap.planned_output_names(
            answers,
            runtime if isinstance(runtime, str) else None,
            project_kind=str(project_kind),
            contract_root_ref=contract_root_ref,
            runtime_wrappers=runtime_wrappers,
        )
    )
    if graph_errors:
        return {}, graph_errors, [], []
    if project_kind == "framework-authoring":
        actual_contract_root = (
            project_root
            if contract_root_ref == "."
            else project_root / contract_root_ref
        )
        errors.extend(
            project_bootstrap.project_layout_errors(
                project_root,
                actual_contract_root,
                contract_root_ref,
                FRAMEWORK_ROOT,
                "framework-authoring",
            )
        )
        if errors:
            return {}, errors, [], []
    errors.extend(
        project_bootstrap.validate_answers(
            answers,
            automation_project_root=project_root,
            automation_manifest_path=(
                project_root
                / project_bootstrap.project_relative_output(
                    contract_root_ref,
                    "AUTOMATION_ORDERS.json",
                )
            ),
            require_existing_automation_project_root=False,
        )
    )
    reference_status, reference_errors, reference_warnings = (
        project_bootstrap.framework_reference_binding(
            framework_reference,
            project_root,
            FRAMEWORK_ROOT,
        )
    )
    errors.extend(reference_errors)
    if reference_status != "verified":
        errors.append(
            "refresh requires framework_reference to resolve to the checkout executing project_refresh.py"
        )
    if errors:
        return {}, errors, [], []
    try:
        framework_identity = project_bootstrap.capture_framework_identity(
            FRAMEWORK_ROOT
        )
    except (OSError, ValueError) as exc:
        return {}, [f"selected framework identity could not be captured: {exc}"], [], []
    effective_date = str(answers.get("date"))
    rendered = project_bootstrap.render_output_files(
        answers,
        runtime if isinstance(runtime, str) else None,
        framework_reference,
        project_kind=str(project_kind),
        contract_root_ref=contract_root_ref,
        effective_date=effective_date,
        runtime_wrappers=runtime_wrappers,
    )
    input_text = project_input.render_project_input(
        project_kind=str(project_kind),
        contract_root=contract_root_ref,
        runtime=runtime if isinstance(runtime, str) else None,
        framework_reference=framework_reference,
        framework_revision_policy=revision_policy,
        answers=answers,
        runtime_wrappers=runtime_wrappers,
    )
    input_name = project_bootstrap.project_relative_output(
        contract_root_ref,
        project_input.INPUT_NAME,
    )
    rendered[input_name] = input_text
    managed, immutable, mutable = project_bootstrap.project_instance_file_sets(
        answers=answers,
        runtime=runtime if isinstance(runtime, str) else None,
        project_kind=str(project_kind),
        contract_root_ref=contract_root_ref,
        runtime_wrappers=runtime_wrappers,
    )
    profiles = project_bootstrap.active_project_profiles(
        answers,
        project_kind=str(project_kind),
    )
    manifest_name = project_bootstrap.INSTANCE_MANIFEST
    rendered[manifest_name] = project_bootstrap.render_instance_manifest(
        input_bytes=input_text.encode("utf-8"),
        project_kind=str(project_kind),
        contract_root_ref=contract_root_ref,
        runtime=runtime if isinstance(runtime, str) else None,
        framework_reference=framework_reference,
        framework_revision_policy=revision_policy,
        framework_reference_status=reference_status,
        managed_files=managed,
        immutable_files=immutable,
        mutable_files=mutable,
        runtime_wrapper_outputs=(
            integration_registry.wrapper_output_map(
                runtime,
                runtime_wrappers,
                FRAMEWORK_ROOT,
            )
            if project_kind == "downstream" and isinstance(runtime, str)
            else {}
        ),
        rendered_outputs=rendered,
        active_profiles=profiles,
        effective_date=effective_date,
        framework_identity=framework_identity,
    )
    warnings = _warning_records(
        [
            *reference_warnings,
            *project_bootstrap.rendered_output_warnings(
                answers,
                runtime if isinstance(runtime, str) else None,
                framework_reference,
                project_kind=str(project_kind),
                contract_root_ref=contract_root_ref,
                effective_date=effective_date,
                runtime_wrappers=runtime_wrappers,
            ),
        ]
    )
    try:
        identity_after_render = project_bootstrap.capture_framework_identity(
            FRAMEWORK_ROOT
        )
    except (OSError, ValueError) as exc:
        errors.append(f"selected framework identity could not be rechecked: {exc}")
    else:
        if identity_after_render != framework_identity:
            errors.append("selected framework bytes changed during refresh rendering")
    return (rendered if not errors else {}), errors, warnings, profiles


def _warnings_for_transaction_outputs(
    warnings: list[dict[str, str]],
    transactional_outputs: Mapping[str, str],
) -> list[dict[str, str]]:
    """Drop rendered-output warnings for files absent from the write set."""

    rendered_prefix = "rendered output warning: "
    output_prefixes = tuple(
        f"{rendered_prefix}{name} " for name in sorted(transactional_outputs)
    )
    messages = [
        warning["message"]
        for warning in warnings
        if not warning["message"].startswith(rendered_prefix)
        or warning["message"].startswith(output_prefixes)
    ]
    return _warning_records(messages)


def build_plan(
    project_root: Path,
    contract_root_ref: str | None = None,
    *,
    candidate_input: dict[str, object] | None = None,
    post_apply_backout: dict[str, object] | None = None,
) -> PlanBuild:
    project_root = project_root.expanduser().resolve(strict=False)
    _status, recovery_errors = _transaction_blocker(project_root)
    if recovery_errors:
        return PlanBuild(None, {}, [], recovery_errors)
    selected_contract_root, selection_errors = _resolve_contract_root_selection(
        project_root,
        contract_root_ref,
    )
    if selection_errors or selected_contract_root is None:
        return PlanBuild(None, {}, [], selection_errors)
    contract_root_ref = selected_contract_root
    current, errors = _load_current_instance(project_root, contract_root_ref)
    if current is None:
        return PlanBuild(None, {}, [], errors)
    target_input = dict(
        current.retained_input if candidate_input is None else candidate_input
    )
    if target_input.get("project_kind") != current.retained_input.get("project_kind"):
        errors.append("refresh target project_kind must match the retained project instance")
    target_contract_root = target_input.get("contract_root")
    if target_contract_root != contract_root_ref:
        errors.append(
            "contract-root relocation is not supported by this refresh phase; retain the current "
            "contract_root or perform a separately reviewed project-specific update"
        )
    target_outputs, target_errors, warnings, profiles = _target_for_input(
        project_root,
        target_input,
    )
    errors.extend(target_errors)
    if errors:
        return PlanBuild(None, {}, [], errors)
    assert isinstance(target_contract_root, str)
    answers = target_input.get("answers")
    runtime = target_input.get("runtime")
    runtime_wrappers = target_input.get("runtime_wrappers")
    project_kind = target_input.get("project_kind")
    assert isinstance(answers, dict)
    assert isinstance(runtime_wrappers, list)
    assert project_kind in {"downstream", "framework-authoring"}
    target_managed, target_immutable, target_mutable = (
        project_bootstrap.project_instance_file_sets(
            answers=answers,
            runtime=runtime if isinstance(runtime, str) else None,
            project_kind=str(project_kind),
            contract_root_ref=target_contract_root,
            runtime_wrappers=runtime_wrappers,
        )
    )
    target_identity_names = {
        project_bootstrap.project_relative_output(
            target_contract_root,
            project_input.INPUT_NAME,
        ),
        project_bootstrap.INSTANCE_MANIFEST,
    }
    for name in sorted({*target_managed, *target_identity_names}):
        if name in current.current_files:
            continue
        digest, unmanaged_error = _existing_project_file_digest(project_root, name)
        if unmanaged_error is not None:
            errors.append(unmanaged_error)
        elif digest is not None:
            errors.append(
                "target path already exists outside the retained managed-file set; "
                "the generic refresh route will not overwrite it. Perform a reviewed "
                "project-specific update first: "
                f"{name}"
            )
    if errors:
        return PlanBuild(None, {}, [], errors)
    current_mutable = set(current.manifest["mutable_files"])
    retired_mutable = sorted(current_mutable - set(target_mutable))
    current_immutable = set(current.manifest["immutable_files"])
    retired_immutable = sorted(current_immutable - set(target_immutable))
    immutable_optional_paths = {
        project_bootstrap.project_relative_output(contract_root_ref, name)
        for name in contract_model.optional_state_filenames("immutable")
    }
    retired_immutable_optional = sorted(
        set(retired_immutable).intersection(immutable_optional_paths)
    )

    # Retained mutable state is never rendered over. New enabled state receives
    # the canonical template and becomes part of the atomic candidate. Candidate-
    # disabled optional state is handled below as an explicit plan-bound removal.
    for name in sorted(set(target_mutable).intersection(current_mutable)):
        target_outputs.pop(name, None)
    warnings = _warnings_for_transaction_outputs(warnings, target_outputs)

    target_input_text = project_input.render_project_input(
        project_kind=str(project_kind),
        contract_root=target_contract_root,
        runtime=runtime if isinstance(runtime, str) else None,
        framework_reference=str(target_input["framework_reference"]),
        framework_revision_policy=str(target_input["framework_revision_policy"]),
        answers=answers,
        runtime_wrappers=runtime_wrappers,
    )
    target_input_digest = _sha256(target_input_text.encode("utf-8"))
    target_files = {
        name: _sha256(content.encode("utf-8"))
        for name, content in sorted(target_outputs.items())
    }
    # Preserved mutable files remain target managed state and bind the plan even
    # though they are intentionally absent from the transaction write set.
    preserved_mutable = sorted(set(target_mutable).intersection(current_mutable))
    for name in preserved_mutable:
        target_files[name] = current.current_files[name]
    warnings = _warning_records(
        [
            *(warning["message"] for warning in warnings),
            *(
                _optional_state_retirement_warning(name, "mutable")
                for name in retired_mutable
            ),
            *(
                _optional_state_retirement_warning(name, "immutable")
                for name in retired_immutable_optional
            ),
        ]
    )

    remove_outputs = sorted([*retired_immutable, *retired_mutable])
    operations: list[dict[str, object]] = []
    required_actions: list[str] = []
    all_target_names = sorted(
        {
            *target_managed,
            project_bootstrap.project_relative_output(
                target_contract_root,
                project_input.INPUT_NAME,
            ),
            project_bootstrap.INSTANCE_MANIFEST,
        }
    )
    metadata_names = {
        project_bootstrap.project_relative_output(
            target_contract_root,
            project_input.INPUT_NAME,
        ),
        project_bootstrap.INSTANCE_MANIFEST,
    }
    needs_file_creation = any(
        name not in current.current_files for name in all_target_names
    )
    creation_file_mode: int | None = None
    derived_directory_mode: int | None = None
    if needs_file_creation:
        try:
            creation_file_mode, derived_directory_mode = _creation_modes_from_umask()
        except OSError as exc:
            return PlanBuild(
                None,
                {},
                [],
                [f"refresh creation modes could not be established: {exc}"],
            )
    for name in all_target_names:
        current_digest = current.current_files.get(name)
        current_mode: int | None = None
        if current_digest is not None:
            observed_digest, current_mode, evidence_error = (
                _existing_project_file_evidence(project_root, name)
            )
            if evidence_error is not None:
                errors.append(evidence_error)
            elif observed_digest != current_digest:
                errors.append(
                    f"current project file changed during refresh planning: {name}"
                )
        target_digest = target_files.get(name)
        if target_digest is None:
            errors.append(f"target plan lacks a digest for managed file: {name}")
            continue
        category = (
            "metadata"
            if name in metadata_names
            else "mutable"
            if name in target_mutable
            else "immutable"
        )
        action = (
            "create"
            if current_digest is None
            else "preserve"
            if current_digest == target_digest
            else "replace"
        )
        target_mode = (
            creation_file_mode if action == "create" else current_mode
        )
        operations.append(
            {
                "action": action,
                "category": category,
                "path": name,
                "current_sha256": current_digest,
                "target_sha256": target_digest,
                "current_mode": current_mode,
                "target_mode": target_mode,
                "approval_id": None,
            }
        )
    for index, name in enumerate(retired_immutable, start=1):
        observed_digest, current_mode, evidence_error = (
            _existing_project_file_evidence(project_root, name)
        )
        if evidence_error is not None:
            errors.append(evidence_error)
        elif observed_digest != current.current_files[name]:
            errors.append(
                f"current project file changed during refresh planning: {name}"
            )
        approval_id = f"RETIRE-IMMUTABLE-{index:04d}"
        required_actions.append(approval_id)
        operations.append(
            {
                "action": "remove",
                "category": "immutable",
                "path": name,
                "current_sha256": current.current_files[name],
                "target_sha256": None,
                "current_mode": current_mode,
                "target_mode": None,
                "approval_id": approval_id,
            }
        )
    for index, name in enumerate(retired_mutable, start=1):
        observed_digest, current_mode, evidence_error = (
            _existing_project_file_evidence(project_root, name)
        )
        if evidence_error is not None:
            errors.append(evidence_error)
        elif observed_digest != current.current_files[name]:
            errors.append(
                f"current project file changed during refresh planning: {name}"
            )
        approval_id = f"RETIRE-MUTABLE-{index:04d}"
        required_actions.append(approval_id)
        operations.append(
            {
                "action": "remove",
                "category": "mutable",
                "path": name,
                "current_sha256": current.current_files[name],
                "target_sha256": None,
                "current_mode": current_mode,
                "target_mode": None,
                "approval_id": approval_id,
            }
        )
    target_manifest_name = project_bootstrap.INSTANCE_MANIFEST
    try:
        target_manifest = safe_paths.loads_json_no_duplicates(
            target_outputs[target_manifest_name]
        )
    except (KeyError, json.JSONDecodeError, ValueError) as exc:
        return PlanBuild(
            None,
            {},
            [],
            [f"rendered target project receipt is invalid: {exc}"],
        )
    if not isinstance(target_manifest, dict):
        return PlanBuild(None, {}, [], ["rendered target project receipt must be an object"])
    selected_framework_digest = target_manifest.get("framework_content_sha256")
    selected_distribution_digest = target_manifest.get(
        "framework_distribution_sha256"
    )
    selected_effective_map = target_manifest.get("framework_effective_file_digests")
    current_wrapper_outputs = current.manifest.get("runtime_wrapper_outputs")
    target_wrapper_outputs = target_manifest.get("runtime_wrapper_outputs")
    if (
        not _is_sha256(selected_framework_digest)
        or not _is_sha256(selected_distribution_digest)
        or not isinstance(selected_effective_map, dict)
        or not isinstance(current_wrapper_outputs, dict)
        or not isinstance(target_wrapper_outputs, dict)
    ):
        return PlanBuild(
            None,
            {},
            [],
            [
                "current or rendered target project receipt lacks a valid selected "
                "framework or runtime-wrapper identity"
            ],
        )
    current_wrapper_identity = (
        current.retained_input.get("runtime"),
        dict(sorted(current_wrapper_outputs.items())),
    )
    target_wrapper_identity = (
        runtime,
        dict(sorted(target_wrapper_outputs.items())),
    )
    if current_wrapper_identity != target_wrapper_identity:
        required_actions.append("REVISE-RUNTIME-WRAPPERS")
    effective_changes = _effective_framework_changes(
        current.manifest.get("framework_effective_file_digests"),
        selected_effective_map,
    )
    if effective_changes["exact_delta_available"] is not True:
        return PlanBuild(
            None,
            {},
            [],
            ["current and selected framework identities must provide an exact file delta"],
        )
    effective_changed = any(
        effective_changes[key] for key in ("added", "removed", "changed")
    )
    if effective_changed:
        required_actions.append("ACCEPT-SELECTED-FRAMEWORK-CHANGE")
    if (
        current.retained_input.get("framework_revision_policy") == "pinned"
        and (
            current.manifest.get("framework_content_sha256")
            != selected_framework_digest
            or current.manifest.get("framework_distribution_sha256")
            != selected_distribution_digest
        )
    ):
        required_actions.append("ADVANCE-PINNED-FRAMEWORK")
    if errors:
        return PlanBuild(None, {}, [], errors)
    operations.sort(key=lambda item: (str(item["path"]), str(item["action"])))
    absent_parent_directories, topology_errors = _absent_parent_directories(
        project_root,
        operations,
    )
    if topology_errors:
        return PlanBuild(None, {}, [], topology_errors)
    creation_directory_mode = (
        derived_directory_mode if absent_parent_directories else None
    )
    changed = any(item["action"] != "preserve" for item in operations)
    if changed:
        if post_apply_backout is None:
            return PlanBuild(
                None,
                {},
                [],
                [
                    "a mutating refresh requires either --backout-root for a verified exact-"
                    "preimage bundle or explicit --accept-no-post-apply-backout approval"
                ],
            )
        backout_errors = _validate_backout_basis(
            post_apply_backout,
            require_current=True,
            project_root=project_root,
        )
        if backout_errors:
            return PlanBuild(None, {}, [], backout_errors)
        if retired_mutable and post_apply_backout.get("kind") != "exact-preimage-bundle":
            return PlanBuild(
                None,
                {},
                [],
                [
                    "optional mutable-state retirement requires a verified exact-preimage "
                    "backout bundle; --accept-no-post-apply-backout cannot authorize removal "
                    "of receipt-owned project state: "
                    + ", ".join(retired_mutable)
                ],
            )
        if post_apply_backout.get("kind") == "none":
            required_actions.append("ACCEPT-NO-POST-APPLY-BACKOUT")
        elif post_apply_backout.get("kind") == "exact-preimage-bundle":
            required_actions.append("USE-EXACT-PREIMAGE-BUNDLE")
    else:
        post_apply_backout = {"kind": "not-required"}
    input_changed = target_input_digest != _sha256(current.input_raw)
    mode = "revise" if input_changed else "refresh" if changed else "no-op"
    payload: dict[str, object] = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "kind": PLAN_KIND,
        "project_root": str(project_root),
        "current_contract_root": contract_root_ref,
        "target_contract_root": target_contract_root,
        "mode": mode,
        "framework_content_sha256": selected_framework_digest,
        "framework_distribution_sha256": selected_distribution_digest,
        "framework_effective_changes": effective_changes,
        "current_input_sha256": _sha256(current.input_raw),
        "current_instance_sha256": _sha256(current.manifest_raw),
        "target_input": json.loads(target_input_text),
        "target_input_sha256": target_input_digest,
        "current_files": dict(sorted(current.current_files.items())),
        "target_files": dict(sorted(target_files.items())),
        "operations": operations,
        "absent_parent_directories": absent_parent_directories,
        "creation_modes": {
            "file": creation_file_mode,
            "directory": creation_directory_mode,
        },
        "required_actions": sorted(required_actions),
        "warnings": warnings,
        "active_profiles": profiles,
        "post_apply_backout": post_apply_backout,
    }
    _finalize_plan(payload)
    return PlanBuild(payload, target_outputs, remove_outputs, [])


def _plan_path_digest_map(
    value: object,
    label: str,
    project_root: Path | None,
    errors: list[str],
) -> dict[str, str]:
    """Validate one closed project-relative path-to-digest plan map."""

    if not isinstance(value, dict):
        errors.append(f"refresh plan {label} must be an object")
        return {}
    result: dict[str, str] = {}
    for raw_path, digest in value.items():
        entry_label = f"refresh plan {label}[{raw_path!r}]"
        if not isinstance(raw_path, str):
            errors.append(f"{entry_label} path must be a string")
            continue
        path_valid = True
        try:
            safe_paths.normalize_repo_relative_path(
                raw_path,
                project_root or Path("/__mpa_refresh_plan__"),
                description=f"{entry_label} path",
            )
        except ValueError as exc:
            errors.append(str(exc))
            path_valid = False
        if not _is_sha256(digest):
            errors.append(f"{entry_label} value must be a lowercase SHA-256 digest")
            continue
        if path_valid:
            result[raw_path] = cast(str, digest)
    return result


def _plan_contract_root(
    value: object,
    label: str,
    project_root: Path | None,
    errors: list[str],
) -> str | None:
    """Validate a current-plan contract root without inferring any prior layout."""

    if not isinstance(value, str):
        errors.append(f"refresh plan {label} must be a string")
        return None
    if value == ".":
        return value
    try:
        safe_paths.normalize_repo_relative_path(
            value,
            project_root or Path("/__mpa_refresh_plan__"),
            description=f"refresh plan {label}",
        )
    except ValueError as exc:
        errors.append(str(exc))
        return None
    return value


def _validate_plan(payload: object) -> list[str]:
    if not isinstance(payload, dict):
        return ["refresh plan must be a JSON object"]
    version = payload.get("schema_version")
    if type(version) is not int or version != PLAN_SCHEMA_VERSION:
        if type(version) is int and version > PLAN_SCHEMA_VERSION:
            return [
                _newer_framework_error(
                    f"refresh plan schema_version {version} is newer than the supported "
                    f"schema_version {PLAN_SCHEMA_VERSION}; use a framework checkout that "
                    f"supports schema_version {version} before applying the plan"
                )
            ]
        issue = "missing or malformed" if type(version) is not int else str(version)
        return [
            f"refresh plan schema_version is {issue}; the current plan parser accepts "
            f"exactly schema_version {PLAN_SCHEMA_VERSION}. Regenerate and review the "
            "temporary plan with the selected current framework before applying it"
        ]
    target_input_schema_error = project_input.schema_version_preflight_error(
        payload.get("target_input")
    )
    if target_input_schema_error is not None:
        target_input_value = payload.get("target_input")
        target_input_version = (
            target_input_value.get("schema_version")
            if isinstance(target_input_value, dict)
            else None
        )
        lifecycle_error = (
            _newer_framework_error(
                "refresh plan target_input requires a newer framework: "
                + target_input_schema_error
            )
            if type(target_input_version) is int
            and target_input_version > project_input.SCHEMA_VERSION
            else (
                "refresh plan target_input is invalid for the current plan format; "
                "regenerate and review the temporary candidate and plan: "
                + target_input_schema_error
            )
        )
        return [
            lifecycle_error
        ]
    errors: list[str] = []
    if set(payload) != PLAN_KEYS:
        errors.append(
            "refresh plan keys must be exactly: " + ", ".join(sorted(PLAN_KEYS))
        )
    if payload.get("kind") != PLAN_KIND:
        errors.append(f"refresh plan kind must be exactly {PLAN_KIND!r}")
    if payload.get("mode") not in {"no-op", "refresh", "revise"}:
        errors.append("refresh plan mode must be one of: no-op, refresh, revise")

    project_root_value = payload.get("project_root")
    project_root: Path | None = None
    if not isinstance(project_root_value, str) or not project_root_value:
        errors.append("refresh plan project_root must be a non-empty absolute path string")
    else:
        try:
            candidate_root = Path(project_root_value).expanduser()
            if not candidate_root.is_absolute():
                errors.append("refresh plan project_root must be an absolute path")
            else:
                project_root = candidate_root.resolve(strict=False)
                if str(project_root) != project_root_value:
                    errors.append("refresh plan project_root must use canonical resolved form")
        except (OSError, ValueError) as exc:
            errors.append(f"refresh plan project_root is invalid: {exc}")

    current_contract_root = _plan_contract_root(
        payload.get("current_contract_root"),
        "current_contract_root",
        project_root,
        errors,
    )
    target_contract_root = _plan_contract_root(
        payload.get("target_contract_root"),
        "target_contract_root",
        project_root,
        errors,
    )
    if (
        current_contract_root is not None
        and target_contract_root is not None
        and current_contract_root != target_contract_root
    ):
        errors.append(
            "refresh plan current_contract_root and target_contract_root must match"
        )
    for key in ("framework_content_sha256", "framework_distribution_sha256"):
        if not _is_sha256(payload.get(key)):
            errors.append(f"refresh plan {key} must be a lowercase SHA-256 digest")

    current_files = _plan_path_digest_map(
        payload.get("current_files"),
        "current_files",
        project_root,
        errors,
    )
    target_files = _plan_path_digest_map(
        payload.get("target_files"),
        "target_files",
        project_root,
        errors,
    )
    creation_modes = payload.get("creation_modes")
    creation_file_mode: int | None = None
    creation_directory_mode: int | None = None
    if not isinstance(creation_modes, dict) or set(creation_modes) != CREATION_MODE_KEYS:
        errors.append("refresh plan creation_modes must use the exact file/directory schema")
    else:
        raw_file_mode = creation_modes.get("file")
        raw_directory_mode = creation_modes.get("directory")
        if raw_file_mode is not None and not _is_posix_rwx_mode(raw_file_mode):
            errors.append("refresh plan creation_modes.file must be null or a POSIX rwx mode")
        else:
            creation_file_mode = cast(int | None, raw_file_mode)
        if raw_directory_mode is not None and not _is_posix_rwx_mode(
            raw_directory_mode
        ):
            errors.append(
                "refresh plan creation_modes.directory must be null or a POSIX rwx mode"
            )
        else:
            creation_directory_mode = cast(int | None, raw_directory_mode)

    target_input = payload.get("target_input")
    target_answers: dict[str, object] | None = None
    if not isinstance(target_input, dict):
        errors.append("refresh plan target_input must be an object")
    else:
        errors.extend(
            "refresh plan target_input: " + error
            for error in project_input.validate_project_input(
                target_input,
                project_root=project_root,
            )
        )
        if (
            target_contract_root is not None
            and target_input.get("contract_root") != target_contract_root
        ):
            errors.append(
                "refresh plan target_input contract_root must match target_contract_root"
            )
        try:
            canonical_target_input = project_input.canonical_project_input_bytes(
                target_input
            )
        except (TypeError, ValueError) as exc:
            errors.append(f"refresh plan target_input is not canonical JSON data: {exc}")
        else:
            expected_target_input_digest = project_input.project_input_sha256(
                canonical_target_input
            )
            if payload.get("target_input_sha256") != expected_target_input_digest:
                errors.append(
                    "refresh plan target_input_sha256 does not bind canonical target_input bytes"
                )
        answers = target_input.get("answers")
        if isinstance(answers, dict):
            target_answers = cast(dict[str, object], answers)
            automation_manifest_path = None
            if target_contract_root is not None and project_root is not None:
                automation_manifest_path = (
                    project_root
                    / project_bootstrap.project_relative_output(
                        target_contract_root,
                        "AUTOMATION_ORDERS.json",
                    )
                )
            errors.extend(
                "refresh plan target_input answers: " + error
                for error in project_bootstrap.validate_answers(
                    target_answers,
                    automation_project_root=project_root,
                    automation_manifest_path=automation_manifest_path,
                    require_existing_automation_project_root=False,
                )
            )
    if not _is_sha256(payload.get("target_input_sha256")):
        errors.append(
            "refresh plan target_input_sha256 must be a lowercase SHA-256 digest"
        )

    for key in ("current_input_sha256", "current_instance_sha256"):
        value = payload.get(key)
        if not _is_sha256(value):
            errors.append(f"refresh plan {key} must be a lowercase SHA-256 digest")

    operations = payload.get("operations")
    changed_operations = False
    operation_by_path: dict[str, dict[str, object]] = {}
    valid_operations: list[dict[str, object]] = []
    approval_ids: set[str] = set()
    if not isinstance(operations, list):
        errors.append("refresh plan operations must be a list")
    else:
        seen_paths: set[str] = set()
        for index, operation in enumerate(operations):
            label = f"refresh plan operations[{index}]"
            if not isinstance(operation, dict) or set(operation) != OPERATION_KEYS:
                errors.append(f"{label} must use the exact operation schema")
                continue
            valid_operations.append(operation)
            if operation.get("action") not in OPERATION_ACTIONS:
                errors.append(f"{label}.action is invalid")
            elif operation.get("action") != "preserve":
                changed_operations = True
            category = operation.get("category")
            if category not in OPERATION_CATEGORIES:
                errors.append(f"{label}.category is invalid")
            path = operation.get("path")
            if not isinstance(path, str) or path in seen_paths:
                errors.append(f"{label}.path must be a unique string")
            else:
                seen_paths.add(path)
                operation_by_path[path] = operation
                try:
                    safe_paths.normalize_repo_relative_path(
                        path,
                        project_root or Path("/__mpa_refresh_plan__"),
                        description=f"{label}.path",
                    )
                except ValueError as exc:
                    errors.append(str(exc))
            action = operation.get("action")
            current_digest = operation.get("current_sha256")
            target_digest = operation.get("target_sha256")
            current_mode = operation.get("current_mode")
            target_mode = operation.get("target_mode")
            if action == "create":
                if (
                    current_digest is not None
                    or current_mode is not None
                    or not _is_sha256(target_digest)
                    or not _is_posix_rwx_mode(target_mode)
                ):
                    errors.append(
                        f"{label} create must bind absent current evidence and target digest/mode"
                    )
            elif action == "replace":
                if (
                    not _is_sha256(current_digest)
                    or not _is_posix_rwx_mode(current_mode)
                    or not _is_sha256(target_digest)
                    or target_mode != current_mode
                ):
                    errors.append(
                        f"{label} replace must bind current/target digests and preserve the current mode"
                    )
            elif action == "preserve":
                if (
                    not _is_sha256(current_digest)
                    or current_digest != target_digest
                    or not _is_posix_rwx_mode(current_mode)
                    or current_mode != target_mode
                ):
                    errors.append(
                        f"{label} preserve must bind one unchanged digest and mode"
                    )
            elif action == "remove":
                if (
                    not _is_sha256(current_digest)
                    or not _is_posix_rwx_mode(current_mode)
                    or target_digest is not None
                    or target_mode is not None
                ):
                    errors.append(
                        f"{label} remove must bind current digest/mode and absent target evidence"
                    )
            approval_id = operation.get("approval_id")
            if operation.get("action") == "remove":
                if not isinstance(approval_id, str) or not approval_id:
                    errors.append(f"{label}.approval_id is required for removal")
                elif category == "mutable" and not _is_numbered_approval_id(
                    approval_id,
                    "RETIRE-MUTABLE-",
                ):
                    errors.append(
                        f"{label}.approval_id must use the numbered RETIRE-MUTABLE-#### form"
                    )
                elif category == "immutable" and not _is_numbered_approval_id(
                    approval_id,
                    "RETIRE-IMMUTABLE-",
                ):
                    errors.append(
                        f"{label}.approval_id must use the numbered RETIRE-IMMUTABLE-#### form"
                    )
            elif operation.get("action") == "replace":
                if approval_id is not None and (
                    not isinstance(approval_id, str) or not approval_id
                ):
                    errors.append(f"{label}.approval_id must be a non-empty string or null")
            elif approval_id is not None:
                errors.append(f"{label}.approval_id is allowed only for replace or remove")
            if isinstance(approval_id, str) and approval_id:
                if approval_id in approval_ids:
                    errors.append(f"{label}.approval_id must be unique")
                approval_ids.add(approval_id)
        if valid_operations != sorted(
            valid_operations,
            key=lambda item: (str(item["path"]), str(item["action"])),
        ):
            errors.append("refresh plan operations must be in canonical path/action order")

    raw_absent_parents = payload.get("absent_parent_directories")
    absent_parent_parts: set[tuple[str, ...]] = set()
    if not isinstance(raw_absent_parents, list) or any(
        not isinstance(item, str) for item in raw_absent_parents
    ):
        errors.append("refresh plan absent_parent_directories must be a string list")
    else:
        if raw_absent_parents != sorted(raw_absent_parents):
            errors.append("refresh plan absent_parent_directories must be sorted")
        if len(raw_absent_parents) != len(set(raw_absent_parents)):
            errors.append(
                "refresh plan absent_parent_directories must not contain duplicates"
            )
        for index, relative in enumerate(raw_absent_parents):
            try:
                normalized = safe_paths.normalize_repo_relative_path(
                    relative,
                    project_root or Path("/__mpa_refresh_plan__"),
                    description=(
                        "refresh plan "
                        f"absent_parent_directories[{index}]"
                    ),
                )
            except ValueError as exc:
                errors.append(str(exc))
                continue
            absent_parent_parts.add(tuple(normalized.split("/")))
        create_parts = {
            tuple(str(operation["path"]).split("/"))
            for operation in valid_operations
            if operation.get("action") == "create"
            and isinstance(operation.get("path"), str)
        }
        if bool(create_parts) != (creation_file_mode is not None):
            errors.append(
                "refresh plan creation_modes.file must be present exactly when files are created"
            )
        for operation in valid_operations:
            if (
                operation.get("action") == "create"
                and operation.get("target_mode") != creation_file_mode
            ):
                errors.append(
                    "refresh plan created-file target_mode must match creation_modes.file: "
                    + str(operation.get("path"))
                )
        for parent in sorted(absent_parent_parts):
            descendants = [
                path
                for path in create_parts
                if len(parent) < len(path) and path[: len(parent)] == parent
            ]
            if not descendants:
                errors.append(
                    "refresh plan absent parent is not a strict ancestor of a created "
                    f"file: {'/'.join(parent)}"
                )
                continue
            for path in descendants:
                for stop in range(len(parent) + 1, len(path)):
                    intermediate = path[:stop]
                    if intermediate not in absent_parent_parts:
                        errors.append(
                            "refresh plan absent-parent topology must name every "
                            f"intervening directory: {'/'.join(intermediate)}"
                        )
        if bool(absent_parent_parts) != (creation_directory_mode is not None):
            errors.append(
                "refresh plan creation_modes.directory must be present exactly when parent directories are created"
            )

    expected_operation_paths = set(current_files).union(target_files)
    if set(operation_by_path) != expected_operation_paths:
        errors.append(
            "refresh plan operation paths must exactly equal current_files union target_files"
        )
    for path, operation in operation_by_path.items():
        current_present = path in current_files
        target_present = path in target_files
        current_digest = current_files.get(path)
        target_digest = target_files.get(path)
        expected_action = (
            "create"
            if not current_present and target_present
            else "remove"
            if current_present and not target_present
            else "preserve"
            if current_digest == target_digest
            else "replace"
        )
        if operation.get("action") != expected_action:
            errors.append(
                f"refresh plan operation action does not match file maps for {path}: "
                f"expected {expected_action}"
            )
        if operation.get("current_sha256") != current_digest:
            errors.append(
                f"refresh plan operation current_sha256 does not match current_files: {path}"
            )
        if operation.get("target_sha256") != target_digest:
            errors.append(
                f"refresh plan operation target_sha256 does not match target_files: {path}"
            )
    warnings = payload.get("warnings")
    if not isinstance(warnings, list):
        errors.append("refresh plan warnings must be a list")
    else:
        seen_warning_ids: set[str] = set()
        valid_warnings: list[dict[str, str]] = []
        for index, warning in enumerate(warnings):
            label = f"refresh plan warnings[{index}]"
            if not isinstance(warning, dict) or set(warning) != WARNING_KEYS:
                errors.append(f"{label} must use the exact warning schema")
                continue
            warning_id = warning.get("id")
            message = warning.get("message")
            if not isinstance(warning_id, str) or not warning_id:
                errors.append(f"{label}.id must be a non-empty string")
            elif warning_id in seen_warning_ids:
                errors.append(f"{label}.id must be unique")
            else:
                seen_warning_ids.add(warning_id)
            if not isinstance(message, str) or not message:
                errors.append(f"{label}.message must be a non-empty string")
            elif isinstance(warning_id, str) and warning_id != _warning_id(message):
                errors.append(f"{label}.id does not bind its exact warning message")
            if isinstance(warning_id, str) and isinstance(message, str):
                valid_warnings.append({"id": warning_id, "message": message})
        if valid_warnings != sorted(
            valid_warnings,
            key=lambda item: (item["id"], item["message"]),
        ):
            errors.append("refresh plan warnings must be in canonical id/message order")
    for key in ("required_actions", "active_profiles"):
        value = payload.get(key)
        if not isinstance(value, list) or not all(
            isinstance(item, str) and bool(item) for item in value
        ):
            errors.append(f"refresh plan {key} must be a string list")
        elif len(value) != len(set(value)):
            errors.append(f"refresh plan {key} must not contain duplicates")
        elif key == "required_actions" and value != sorted(value):
            errors.append("refresh plan required_actions must be sorted")
    active_profiles = payload.get("active_profiles")
    if target_answers is not None and isinstance(target_input, dict):
        project_kind = target_input.get("project_kind")
        if project_kind in {"downstream", "framework-authoring"}:
            expected_profiles = project_bootstrap.active_project_profiles(
                target_answers,
                project_kind=str(project_kind),
            )
            if active_profiles != expected_profiles:
                errors.append(
                    "refresh plan active_profiles must exactly match target_input answers"
                )
    effective_changes = payload.get("framework_effective_changes")
    if not isinstance(effective_changes, dict) or set(effective_changes) != EFFECTIVE_CHANGE_KEYS:
        errors.append("refresh plan framework_effective_changes uses an invalid schema")
    else:
        exact_delta_available = effective_changes.get("exact_delta_available")
        if exact_delta_available is not True:
            errors.append(
                "framework_effective_changes exact_delta_available must be exactly true"
            )
        delta_sets: dict[str, set[str]] = {}
        for key in ("added", "removed", "changed"):
            value = effective_changes.get(key)
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                errors.append(f"framework_effective_changes {key} must be a string list")
                continue
            if len(value) != len(set(value)) or value != sorted(value):
                errors.append(
                    f"framework_effective_changes {key} must be sorted and unique"
                )
            delta_sets[key] = set(value)
            for path in value:
                try:
                    safe_paths.normalize_repo_relative_path(
                        path,
                        FRAMEWORK_ROOT,
                        description=f"framework_effective_changes {key} path",
                    )
                except ValueError as exc:
                    errors.append(str(exc))
        if any(
            delta_sets.get(left, set()).intersection(delta_sets.get(right, set()))
            for left, right in (
                ("added", "removed"),
                ("added", "changed"),
                ("removed", "changed"),
            )
        ):
            errors.append("framework_effective_changes path classes must be disjoint")
    if current_contract_root is not None:
        current_input_path = project_bootstrap.project_relative_output(
            current_contract_root,
            project_input.INPUT_NAME,
        )
        current_instance_path = project_bootstrap.INSTANCE_MANIFEST
        if payload.get("current_input_sha256") != current_files.get(current_input_path):
            errors.append(
                "refresh plan current_input_sha256 does not match current_files retained input"
            )
        if payload.get("current_instance_sha256") != current_files.get(
            current_instance_path
        ):
            errors.append(
                "refresh plan current_instance_sha256 does not match current_files receipt"
            )
    if target_contract_root is not None:
        target_input_path = project_bootstrap.project_relative_output(
            target_contract_root,
            project_input.INPUT_NAME,
        )
        target_instance_path = project_bootstrap.INSTANCE_MANIFEST
        if payload.get("target_input_sha256") != target_files.get(target_input_path):
            errors.append(
                "refresh plan target_input_sha256 does not match target_files retained input"
            )
        if target_instance_path not in target_files:
            errors.append("refresh plan target_files must contain the target instance receipt")
    errors.extend(
        _validate_backout_basis(
            payload.get("post_apply_backout"),
            require_current=False,
        )
    )
    backout = payload.get("post_apply_backout")
    backout_kind = backout.get("kind") if isinstance(backout, dict) else None
    required_actions = payload.get("required_actions")
    required_action_set = (
        {item for item in required_actions if isinstance(item, str)}
        if isinstance(required_actions, list)
        else set()
    )
    missing_operation_approvals = sorted(approval_ids - required_action_set)
    if missing_operation_approvals:
        errors.append(
            "refresh plan required_actions omits operation approval ids: "
            + ", ".join(missing_operation_approvals)
        )
    mutable_retirement_operations = [
        operation
        for operation in valid_operations
        if operation.get("action") == "remove"
        and operation.get("category") == "mutable"
    ]
    immutable_optional_paths = (
        {
            project_bootstrap.project_relative_output(current_contract_root, name)
            for name in contract_model.optional_state_filenames("immutable")
        }
        if current_contract_root is not None
        else set()
    )
    immutable_retirement_operations = [
        operation
        for operation in valid_operations
        if operation.get("action") == "remove"
        and operation.get("category") == "immutable"
        and operation.get("path") in immutable_optional_paths
    ]
    warning_pairs = {
        (item.get("id"), item.get("message"))
        for item in warnings
        if isinstance(item, dict)
    } if isinstance(warnings, list) else set()
    for operation in [
        *mutable_retirement_operations,
        *immutable_retirement_operations,
    ]:
        retirement_path = operation.get("path")
        retirement_category = operation.get("category")
        if not isinstance(retirement_path, str) or retirement_category not in {
            "immutable",
            "mutable",
        }:
            continue
        retirement_message = _optional_state_retirement_warning(
            retirement_path,
            str(retirement_category),
        )
        if (_warning_id(retirement_message), retirement_message) not in warning_pairs:
            errors.append(
                "refresh plan warnings must include the exact optional "
                f"{retirement_category}-state "
                f"retirement warning for {retirement_path}"
            )
    if mutable_retirement_operations and backout_kind != "exact-preimage-bundle":
        errors.append(
            "optional mutable-state retirement requires an exact-preimage backout bundle"
        )
    if changed_operations:
        if backout_kind == "not-required":
            errors.append("mutating refresh plan cannot mark post-success backout not-required")
        if backout_kind == "none" and "ACCEPT-NO-POST-APPLY-BACKOUT" not in required_action_set:
            errors.append("no-backout refresh plan must require its exceptional approval")
        if (
            backout_kind == "exact-preimage-bundle"
            and "USE-EXACT-PREIMAGE-BUNDLE" not in required_action_set
        ):
            errors.append("exact-preimage refresh plan must require bundle use approval")
    elif backout_kind != "not-required":
        errors.append("no-op refresh plan must mark post-success backout not-required")
    input_changed = payload.get("target_input_sha256") != payload.get(
        "current_input_sha256"
    )
    expected_mode = (
        "revise" if input_changed else "refresh" if changed_operations else "no-op"
    )
    if payload.get("mode") != expected_mode:
        errors.append(
            f"refresh plan mode does not match bound input and file deltas: expected {expected_mode}"
        )
    transaction_id = payload.get("refresh_transaction_id")
    try:
        expected_transaction_id = _refresh_transaction_id(payload)
        expected_plan_digest = _plan_digest(payload)
    except (TypeError, ValueError) as exc:
        expected_transaction_id = None
        expected_plan_digest = None
        errors.append(f"refresh plan contains non-canonical JSON data: {exc}")
    if not (
        isinstance(transaction_id, str)
        and len(transaction_id) == 32
        and transaction_id == expected_transaction_id
    ):
        errors.append("refresh_transaction_id does not match the canonical plan content")
    digest = payload.get("plan_sha256")
    if not _is_sha256(digest) or digest != expected_plan_digest:
        errors.append("refresh plan digest does not match its canonical content")
    return errors


def _load_plan(path: Path) -> tuple[dict[str, object] | None, list[str]]:
    try:
        raw = safe_paths.read_regular_file_bytes(path, description="refresh plan")
    except (FileNotFoundError, OSError, ValueError) as exc:
        return None, [f"refresh plan could not be read safely: {exc}"]
    try:
        payload = safe_paths.loads_json_no_duplicates(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        return None, [f"refresh plan is invalid JSON: {exc}"]
    errors = _validate_plan(payload)
    return (payload if isinstance(payload, dict) else None), errors


def _rebuild_plan(project_root: Path, plan: dict[str, object]) -> PlanBuild:
    target_input = plan.get("target_input")
    backout = plan.get("post_apply_backout")
    if not isinstance(target_input, dict):
        return PlanBuild(None, {}, [], ["refresh plan target_input must be an object"])
    return build_plan(
        project_root,
        str(plan["current_contract_root"]),
        candidate_input=target_input,
        post_apply_backout=backout if isinstance(backout, dict) else None,
    )


def preview_plan(
    project_root: Path,
    plan: dict[str, object],
) -> tuple[int, dict[str, object]]:
    """Return exact regenerated text and diffs without writing project paths."""

    project_root, recovery_blocker = _clean_project_preflight(project_root)
    if recovery_blocker is not None:
        return EXIT_RECOVERY_REQUIRED, recovery_blocker
    errors = _validate_plan(plan)
    if errors:
        return EXIT_INVOCATION, {
            "status": _error_status("invalid-plan", errors),
            "errors": errors,
        }
    if str(project_root) != plan.get("project_root"):
        return EXIT_BLOCKED, {
            "status": "stale-plan",
            "errors": ["refresh plan is bound to a different project root"],
        }
    rebuilt = _rebuild_plan(project_root, plan)
    if rebuilt.payload is None:
        return EXIT_BLOCKED, {"status": "stale-plan", "errors": rebuilt.errors}
    if rebuilt.payload.get("plan_sha256") != plan.get("plan_sha256"):
        return EXIT_BLOCKED, {
            "status": "stale-plan",
            "errors": [
                "project or framework preimages changed after planning; create a new plan"
            ],
        }

    target_files = plan.get("target_files")
    operations = plan.get("operations")
    if not isinstance(target_files, dict) or not isinstance(operations, list):
        return EXIT_INVOCATION, {
            "status": _error_status("invalid-plan", errors),
            "errors": ["refresh plan target_files and operations are malformed"],
        }
    previews: list[dict[str, object]] = []
    preview_errors: list[str] = []
    for operation in operations:
        if not isinstance(operation, dict):
            preview_errors.append("refresh plan operation is malformed")
            continue
        action = operation.get("action")
        if action == "preserve":
            continue
        path = operation.get("path")
        if not isinstance(path, str) or action not in {"create", "replace", "remove"}:
            preview_errors.append("refresh plan operation cannot be previewed safely")
            continue
        current_text = ""
        target_text = ""
        if action in {"replace", "remove"}:
            try:
                current_raw = safe_paths.read_regular_file_bytes(
                    project_root / path,
                    description=f"refresh preview current file {path}",
                )
                current_text = current_raw.decode("utf-8")
            except (FileNotFoundError, OSError, UnicodeError, ValueError) as exc:
                preview_errors.append(f"refresh preview could not read {path}: {exc}")
                continue
            if _sha256(current_raw) != operation.get("current_sha256"):
                preview_errors.append(
                    f"refresh preview current bytes do not match the plan: {path}"
                )
                continue
        if action in {"create", "replace"}:
            rendered = rebuilt.target_outputs.get(path)
            if not isinstance(rendered, str):
                preview_errors.append(
                    f"refresh preview lacks regenerated target text: {path}"
                )
                continue
            target_text = rendered
            target_digest = _sha256(target_text.encode("utf-8"))
            if (
                target_digest != operation.get("target_sha256")
                or target_digest != target_files.get(path)
            ):
                preview_errors.append(
                    f"refresh preview target bytes do not match the plan: {path}"
                )
                continue
        unified_diff = "".join(
            difflib.unified_diff(
                current_text.splitlines(keepends=True),
                target_text.splitlines(keepends=True),
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
            )
        )
        previews.append(
            {
                "path": path,
                "action": action,
                "category": operation.get("category"),
                "current_sha256": operation.get("current_sha256"),
                "target_sha256": operation.get("target_sha256"),
                "current_mode": operation.get("current_mode"),
                "target_mode": operation.get("target_mode"),
                "current_text": current_text,
                "target_text": target_text,
                "unified_diff": unified_diff,
            }
        )
    if preview_errors:
        return EXIT_BLOCKED, {
            "status": "stale-plan",
            "plan_sha256": plan.get("plan_sha256"),
            "errors": preview_errors,
        }
    return 0, {
        "status": "plan-preview",
        "plan_sha256": plan["plan_sha256"],
        "refresh_transaction_id": plan["refresh_transaction_id"],
        "target_files_verified": True,
        "changed_files": sorted(previews, key=lambda item: str(item["path"])),
        "errors": [],
    }


def _expected_backout_entries(plan: Mapping[str, object]) -> list[dict[str, object]]:
    operations = plan.get("operations")
    assert isinstance(operations, list)
    changed = sorted(
        (
            operation
            for operation in operations
            if isinstance(operation, dict) and operation.get("action") != "preserve"
        ),
        key=lambda operation: str(operation["path"]),
    )
    entries: list[dict[str, object]] = []
    blob_index = 0
    for operation in changed:
        current_digest = operation.get("current_sha256")
        if current_digest is None:
            state = "absent"
            blob = None
        else:
            state = "file"
            blob_index += 1
            blob = f"files/{blob_index:04d}.bin"
        entries.append(
            {
                "path": str(operation["path"]),
                "state": state,
                "sha256": current_digest,
                "mode": operation.get("current_mode"),
                "blob": blob,
            }
        )
    return entries


def _expected_backout_manifest(plan: Mapping[str, object]) -> dict[str, object]:
    return {
        "schema_version": BACKOUT_BUNDLE_SCHEMA_VERSION,
        "kind": BACKOUT_BUNDLE_KIND,
        "plan_sha256": plan["plan_sha256"],
        "refresh_transaction_id": plan["refresh_transaction_id"],
        "project_root": plan["project_root"],
        "current_contract_root": plan["current_contract_root"],
        "absent_parent_directories": plan["absent_parent_directories"],
        "entries": _expected_backout_entries(plan),
    }


def _expected_backout_transaction_paths(
    plan: Mapping[str, object],
    bundle_ref: str,
) -> tuple[str, ...]:
    paths = {f"{bundle_ref}/{BACKOUT_BUNDLE_MANIFEST}"}
    paths.update(
        f"{bundle_ref}/{entry['blob']}"
        for entry in _expected_backout_entries(plan)
        if isinstance(entry.get("blob"), str)
    )
    return tuple(sorted(paths))


def _backout_recovery_binding_errors(
    status: bootstrap_transaction.BootstrapRecoveryStatus,
    expected_paths: tuple[str, ...],
) -> list[str]:
    if status.state == "clean":
        return []
    actual_paths = tuple(status.operation_paths)
    if len(actual_paths) == len(expected_paths) and set(actual_paths) == set(
        expected_paths
    ):
        return []
    return [
        "private backout-root recovery operations do not match the exact plan-bound "
        "bundle paths; do not recover this transaction through the supplied refresh plan"
    ]


def _permitted_backout_recovery_action(
    status: bootstrap_transaction.BootstrapRecoveryStatus,
) -> str | None:
    """Return one unambiguous currently permitted recovery action."""

    if status.state == "active" or status.errors:
        return None
    actions = [
        action
        for action, permitted in (
            ("rollback", status.can_rollback),
            ("finalize", status.can_finalize),
        )
        if permitted
    ]
    return actions[0] if len(actions) == 1 else None


def _backout_bundle_location(
    plan: Mapping[str, object],
    supplied_root: Path,
    *,
    require_current: bool,
) -> tuple[Path | None, str | None, list[str]]:
    project_root_value = plan.get("project_root")
    backout = plan.get("post_apply_backout")
    if not isinstance(project_root_value, str) or not isinstance(backout, dict):
        return None, None, ["refresh plan lacks a valid project/backout binding"]
    if backout.get("kind") != "exact-preimage-bundle":
        return None, None, ["refresh plan does not select an exact-preimage bundle"]
    project_root = Path(project_root_value).expanduser().resolve(strict=False)
    root, errors = _validated_private_backout_root(
        str(supplied_root),
        project_root=project_root,
        require_current=require_current,
    )
    if root is None:
        return None, None, errors
    recorded_root = Path(str(backout.get("root"))).expanduser().resolve(strict=False)
    if root != recorded_root:
        return None, None, ["supplied backout root does not match the plan-bound root"]
    transaction_id = plan.get("refresh_transaction_id")
    plan_digest = plan.get("plan_sha256")
    if not isinstance(transaction_id, str) or not isinstance(plan_digest, str):
        return None, None, ["refresh plan lacks its canonical transaction identity"]
    relative = f"mpa-refresh-{transaction_id}-{plan_digest[:16]}"
    return root, relative, []


def _backout_root_lifecycle_blocker(
    project_root: Path,
    plan: Mapping[str, object],
    root: Path,
    bundle_ref: str,
) -> tuple[int, dict[str, object]] | None:
    """Fail closed when the private backout root has any live transaction state."""

    try:
        recovery = bootstrap_transaction.transaction_recovery_status(root)
    except (OSError, ValueError) as exc:
        return EXIT_RECOVERY_REQUIRED, {
            "status": "backout-bundle-recovery-required",
            "recovery_root": str(root),
            "transaction_id": None,
            "errors": [f"private backout-root transaction state is unproved: {exc}"],
        }
    clean = (
        recovery.state == "clean"
        and not recovery.errors
        and recovery.transaction_id is None
        and recovery.phase is None
        and not recovery.operation_paths
        and not recovery.can_rollback
        and not recovery.can_finalize
    )
    if clean:
        return None
    binding_errors = _backout_recovery_binding_errors(
        recovery,
        _expected_backout_transaction_paths(plan, bundle_ref),
    )
    errors = [
        *recovery.errors,
        *binding_errors,
        (
            "another private backout-root transaction is active; wait for its owner "
            "instead of starting or inspecting a bundle operation"
            if recovery.state == "active"
            else "the private backout root requires exact-ID recovery before any "
            "non-recovery bundle operation"
        ),
    ]
    report: dict[str, object] = {
        "status": (
            "backout-root-transaction-active"
            if recovery.state == "active"
            else "backout-bundle-recovery-required"
        ),
        "recovery_root": str(root),
        "transaction_id": recovery.transaction_id,
        "phase": recovery.phase,
        "operation_paths": list(recovery.operation_paths),
        "can_rollback": recovery.can_rollback,
        "can_finalize": recovery.can_finalize,
        "errors": errors,
    }
    recovery_action = _permitted_backout_recovery_action(recovery)
    if (
        recovery.transaction_id is not None
        and not binding_errors
        and recovery_action is not None
    ):
        report["recovery_route"] = {
            "command": "backout-recover",
            "action": recovery_action,
            "project_root": str(project_root),
            "plan_sha256": plan.get("plan_sha256"),
            "backout_root": str(root),
            "approve_transaction_id": recovery.transaction_id,
        }
    return (
        EXIT_BLOCKED if recovery.state == "active" else EXIT_RECOVERY_REQUIRED,
        report,
    )


def _read_verified_backout_bundle(
    project_root: Path,
    plan: dict[str, object],
    supplied_root: Path,
    *,
    require_project_preimage: bool,
    allow_transaction_artifacts: bool = False,
) -> tuple[dict[str, bytes], dict[str, object], list[str]]:
    errors = _validate_plan(plan)
    if str(project_root.expanduser().resolve(strict=False)) != plan.get("project_root"):
        errors.append("refresh plan is bound to a different project root")
    root, bundle_ref, root_errors = _backout_bundle_location(
        plan,
        supplied_root,
        require_current=True,
    )
    errors.extend(root_errors)
    if root is None or bundle_ref is None:
        return {}, {}, errors
    bundle_dir = root / bundle_ref
    try:
        bundle_metadata = bundle_dir.lstat()
    except OSError as exc:
        errors.append(f"exact-preimage bundle is unavailable: {exc}")
        return {}, {}, errors
    if bundle_dir.is_symlink() or not stat.S_ISDIR(bundle_metadata.st_mode):
        errors.append("exact-preimage bundle must be a regular non-symlink directory")
        return {}, {}, errors
    errors.extend(
        _private_artifact_errors(
            bundle_dir,
            description="exact-preimage bundle directory",
            directory=True,
        )
    )

    manifest_path = bundle_dir / BACKOUT_BUNDLE_MANIFEST
    errors.extend(
        _private_artifact_errors(
            manifest_path,
            description="exact-preimage bundle manifest",
            directory=False,
        )
    )
    try:
        manifest_raw = safe_paths.read_regular_file_bytes(
            manifest_path,
            description="exact-preimage bundle manifest",
        )
        manifest = safe_paths.loads_json_no_duplicates(manifest_raw.decode("utf-8"))
    except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        errors.append(f"exact-preimage bundle manifest is invalid: {exc}")
        return {}, {}, errors
    expected_manifest = _expected_backout_manifest(plan)
    if not isinstance(manifest, dict) or set(manifest) != BACKOUT_BUNDLE_KEYS:
        errors.append("exact-preimage bundle manifest uses an invalid closed schema")
    elif manifest != expected_manifest:
        errors.append("exact-preimage bundle manifest does not match the exact refresh plan")
    if manifest_raw != _canonical_json_bytes(expected_manifest):
        errors.append("exact-preimage bundle manifest bytes are not canonical")

    expected_entries = _expected_backout_entries(plan)
    expected_blobs = {
        str(entry["blob"])
        for entry in expected_entries
        if isinstance(entry.get("blob"), str)
    }
    expected_top = {BACKOUT_BUNDLE_MANIFEST}
    if expected_blobs:
        expected_top.add("files")
    try:
        actual_top = {
            child.name
            for child in bundle_dir.iterdir()
            if not (
                allow_transaction_artifacts
                and child.name.startswith(".mpa-bootstrap-transaction-")
            )
        }
    except OSError as exc:
        errors.append(f"exact-preimage bundle could not be enumerated: {exc}")
        actual_top = set()
    if actual_top != expected_top:
        errors.append("exact-preimage bundle contains missing or unrecognized top-level data")
    files_dir = bundle_dir / "files"
    if expected_blobs:
        try:
            files_metadata = files_dir.lstat()
            if files_dir.is_symlink() or not stat.S_ISDIR(files_metadata.st_mode):
                errors.append("exact-preimage bundle files path must be a non-symlink directory")
                actual_blob_names: set[str] = set()
            else:
                errors.extend(
                    _private_artifact_errors(
                        files_dir,
                        description="exact-preimage bundle files directory",
                        directory=True,
                    )
                )
                actual_blob_names = {
                    f"files/{child.name}"
                    for child in files_dir.iterdir()
                    if not (
                        allow_transaction_artifacts
                        and child.name.startswith(".mpa-bootstrap-transaction-")
                    )
                }
        except OSError as exc:
            errors.append(f"exact-preimage bundle files are unavailable: {exc}")
            actual_blob_names = set()
        if actual_blob_names != expected_blobs:
            errors.append("exact-preimage bundle blob inventory is not exact")

    blobs: dict[str, bytes] = {}
    for entry in expected_entries:
        path = str(entry["path"])
        if set(entry) != BACKOUT_ENTRY_KEYS:
            errors.append(f"exact-preimage bundle entry schema is invalid: {path}")
            continue
        blob = entry.get("blob")
        if entry["state"] == "absent":
            if (
                entry["sha256"] is not None
                or entry["mode"] is not None
                or blob is not None
            ):
                errors.append(f"absent backout entry contains file evidence: {path}")
        elif (
            entry["state"] == "file"
            and isinstance(blob, str)
            and _is_posix_rwx_mode(entry.get("mode"))
        ):
            errors.extend(
                _private_artifact_errors(
                    bundle_dir / blob,
                    description=f"exact-preimage bundle blob for {path}",
                    directory=False,
                )
            )
            try:
                raw = safe_paths.read_regular_file_bytes(
                    bundle_dir / blob,
                    description=f"exact-preimage bundle blob for {path}",
                )
            except (FileNotFoundError, OSError, ValueError) as exc:
                errors.append(f"exact-preimage bundle blob is invalid for {path}: {exc}")
                continue
            if _sha256(raw) != entry["sha256"]:
                errors.append(f"exact-preimage bundle blob digest mismatch: {path}")
            blobs[path] = raw
        else:
            errors.append(f"exact-preimage bundle entry state is invalid: {path}")

        if require_project_preimage:
            digest, mode, evidence_error = _existing_project_file_evidence(
                project_root,
                path,
            )
            if evidence_error is not None:
                errors.append(evidence_error)
            elif digest != entry["sha256"] or mode != entry["mode"]:
                errors.append(f"project preimage changed after bundle creation: {path}")
    return blobs, expected_manifest, errors


def create_backout_bundle(
    project_root: Path,
    plan: dict[str, object],
    supplied_root: Path,
) -> tuple[int, dict[str, object]]:
    project_root, recovery_blocker = _clean_project_preflight(project_root)
    if recovery_blocker is not None:
        return EXIT_RECOVERY_REQUIRED, recovery_blocker
    errors = _validate_plan(plan)
    if errors:
        return EXIT_INVOCATION, {
            "status": _error_status("invalid-plan", errors),
            "errors": errors,
        }
    root, bundle_ref, location_errors = _backout_bundle_location(
        plan,
        supplied_root,
        require_current=True,
    )
    if root is None or bundle_ref is None:
        return EXIT_BLOCKED, {"status": "invalid-backout-root", "errors": location_errors}
    lifecycle_blocker = _backout_root_lifecycle_blocker(
        project_root,
        plan,
        root,
        bundle_ref,
    )
    if lifecycle_blocker is not None:
        return lifecycle_blocker
    rebuilt = _rebuild_plan(project_root, plan)
    if rebuilt.payload is None or rebuilt.payload.get("plan_sha256") != plan.get("plan_sha256"):
        return EXIT_BLOCKED, {
            "status": "stale-plan",
            "errors": rebuilt.errors or ["project or framework preimages changed after planning"],
        }
    manifest = _expected_backout_manifest(plan)
    outputs = {
        f"{bundle_ref}/{BACKOUT_BUNDLE_MANIFEST}": _canonical_json_bytes(manifest).decode(
            "utf-8"
        )
    }
    for entry in _expected_backout_entries(plan):
        if entry["state"] != "file":
            continue
        path = str(entry["path"])
        try:
            raw = safe_paths.read_regular_file_bytes(
                project_root / path,
                description=f"refresh backout preimage {path}",
            )
            text = raw.decode("utf-8")
        except (FileNotFoundError, OSError, UnicodeError, ValueError) as exc:
            return EXIT_BLOCKED, {
                "status": "stale-plan",
                "errors": [f"could not capture exact text preimage for {path}: {exc}"],
            }
        _digest, mode, evidence_error = _existing_project_file_evidence(
            project_root,
            path,
        )
        if evidence_error is not None:
            return EXIT_BLOCKED, {
                "status": "stale-plan",
                "errors": [evidence_error],
            }
        if _sha256(raw) != entry["sha256"] or mode != entry["mode"]:
            return EXIT_BLOCKED, {
                "status": "stale-plan",
                "errors": [
                    f"project preimage bytes or mode changed before bundle creation: {path}"
                ],
            }
        outputs[f"{bundle_ref}/{entry['blob']}"] = text

    existing_manifest = root / bundle_ref / BACKOUT_BUNDLE_MANIFEST
    if existing_manifest.exists():
        _blobs, verified_manifest, verify_errors = _read_verified_backout_bundle(
            project_root,
            plan,
            root,
            require_project_preimage=True,
        )
        if verify_errors:
            return EXIT_BLOCKED, {"status": "invalid-backout-bundle", "errors": verify_errors}
        return 0, {
            "status": "backout-bundle-current",
            "bundle": str(root / bundle_ref),
            "manifest": verified_manifest,
            "errors": [],
        }

    def verify() -> None:
        _blobs, _manifest, verify_errors = _read_verified_backout_bundle(
            project_root,
            plan,
            root,
            require_project_preimage=True,
            allow_transaction_artifacts=True,
        )
        if verify_errors:
            raise ValueError("; ".join(verify_errors))

    expected_preimages: dict[str, str | None] = {name: None for name in outputs}
    expected_recovery_paths = _expected_backout_transaction_paths(plan, bundle_ref)
    try:
        result = bootstrap_transaction.transactional_write_outputs(
            root,
            sorted(outputs.items()),
            force=False,
            post_install_verifier=verify,
            expected_preimages=expected_preimages,
            create_file_mode=0o600,
            create_directory_mode=0o700,
        )
    except (bootstrap_transaction.BootstrapTransactionError, OSError, ValueError) as exc:
        try:
            recovery = bootstrap_transaction.transaction_recovery_status(root)
        except (OSError, ValueError) as status_exc:
            return EXIT_RECOVERY_REQUIRED, {
                "status": "backout-bundle-recovery-required",
                "bundle": str(root / bundle_ref),
                "recovery_root": str(root),
                "transaction_id": None,
                "errors": [str(exc), str(status_exc)],
            }
        binding_errors = _backout_recovery_binding_errors(
            recovery,
            expected_recovery_paths,
        )
        recovery_required = (
            recovery.state != "clean" or bool(recovery.errors) or bool(binding_errors)
        )
        report = {
            "status": (
                "backout-bundle-recovery-required"
                if recovery_required
                else "backout-bundle-create-rolled-back"
            ),
            "bundle": str(root / bundle_ref),
            "recovery_root": str(root),
            "transaction_id": recovery.transaction_id,
            "can_rollback": recovery.can_rollback,
            "can_finalize": recovery.can_finalize,
            "errors": [str(exc), *recovery.errors, *binding_errors],
        }
        recovery_action = _permitted_backout_recovery_action(recovery)
        if (
            recovery.transaction_id is not None
            and not binding_errors
            and recovery_action is not None
        ):
            report["recovery_route"] = {
                "command": "backout-recover",
                "action": recovery_action,
                "project_root": str(project_root),
                "plan_sha256": plan["plan_sha256"],
                "backout_root": str(root),
                "approve_transaction_id": recovery.transaction_id,
            }
        return (
            EXIT_RECOVERY_REQUIRED if recovery_required else EXIT_ROLLED_BACK,
            report,
        )
    _blobs, verified_manifest, verify_errors = _read_verified_backout_bundle(
        project_root,
        plan,
        root,
        require_project_preimage=True,
    )
    if verify_errors or result.cleanup_warnings:
        recovery = bootstrap_transaction.transaction_recovery_status(root)
        binding_errors = _backout_recovery_binding_errors(
            recovery,
            expected_recovery_paths,
        )
        return EXIT_RECOVERY_REQUIRED, {
            "status": "backout-bundle-verification-failed",
            "bundle": str(root / bundle_ref),
            "recovery_root": str(root),
            "transaction_id": recovery.transaction_id,
            "errors": [*verify_errors, *result.cleanup_warnings, *binding_errors],
        }
    return 0, {
        "status": "backout-bundle-created",
        "bundle": str(root / bundle_ref),
        "manifest": verified_manifest,
        "written": result.written,
        "errors": [],
    }


def verify_backout_bundle(
    project_root: Path,
    plan: dict[str, object],
    supplied_root: Path,
    *,
    require_project_preimage: bool,
) -> tuple[int, dict[str, object]]:
    project_root, recovery_blocker = _clean_project_preflight(project_root)
    if recovery_blocker is not None:
        return EXIT_RECOVERY_REQUIRED, recovery_blocker
    plan_errors = _validate_plan(plan)
    if plan_errors:
        return EXIT_INVOCATION, {
            "status": _error_status("invalid-plan", plan_errors),
            "errors": plan_errors,
        }
    if str(project_root) != plan.get("project_root"):
        return EXIT_BLOCKED, {
            "status": "stale-plan",
            "errors": ["refresh plan is bound to a different project root"],
        }
    root, bundle_ref, location_errors = _backout_bundle_location(
        plan,
        supplied_root,
        require_current=True,
    )
    if root is None or bundle_ref is None:
        return EXIT_BLOCKED, {
            "status": "invalid-backout-root",
            "errors": location_errors,
        }
    lifecycle_blocker = _backout_root_lifecycle_blocker(
        project_root,
        plan,
        root,
        bundle_ref,
    )
    if lifecycle_blocker is not None:
        return lifecycle_blocker
    _blobs, manifest, errors = _read_verified_backout_bundle(
        project_root,
        plan,
        root,
        require_project_preimage=require_project_preimage,
    )
    return (
        (EXIT_BLOCKED if errors else 0),
        {
            "status": "invalid-backout-bundle" if errors else "backout-bundle-verified",
            "manifest": manifest,
            "project_preimage_checked": require_project_preimage,
            "errors": errors,
        },
    )


def recover_backout_bundle(
    project_root: Path,
    plan: dict[str, object],
    supplied_root: Path,
    *,
    action: str,
    approved_transaction_id: str,
) -> tuple[int, dict[str, object]]:
    if action not in {"rollback", "finalize"}:
        return EXIT_INVOCATION, {
            "status": "invalid-backout-recovery-request",
            "errors": ["recovery action must be exactly rollback or finalize"],
        }
    project_root, recovery_blocker = _clean_project_preflight(project_root)
    if recovery_blocker is not None:
        return EXIT_RECOVERY_REQUIRED, recovery_blocker
    errors = _validate_plan(plan)
    if str(project_root) != plan.get("project_root"):
        errors.append("refresh plan is bound to a different project root")
    root, bundle_ref, root_errors = _backout_bundle_location(
        plan,
        supplied_root,
        require_current=True,
    )
    errors.extend(root_errors)
    if errors or root is None or bundle_ref is None:
        return EXIT_BLOCKED, {
            "status": "invalid-backout-recovery-request",
            "errors": errors,
        }
    try:
        recovery = bootstrap_transaction.transaction_recovery_status(root)
    except (OSError, ValueError) as exc:
        return EXIT_RECOVERY_REQUIRED, {
            "status": "invalid-backout-recovery-request",
            "recovery_root": str(root),
            "errors": [f"private backout-root recovery state could not be inspected: {exc}"],
        }
    binding_errors = _backout_recovery_binding_errors(
        recovery,
        _expected_backout_transaction_paths(plan, bundle_ref),
    )
    if binding_errors:
        return EXIT_RECOVERY_REQUIRED, {
            "status": "invalid-backout-recovery-request",
            "recovery_root": str(root),
            "transaction_id": recovery.transaction_id,
            "operation_paths": list(recovery.operation_paths),
            "errors": binding_errors,
        }
    code, report = recover_project(
        root,
        action=action,
        approved_transaction_id=approved_transaction_id,
    )
    return code, {**report, "recovery_root": str(root), "backout_recovery": True}


def restore_backout_bundle(
    project_root: Path,
    plan: dict[str, object],
    supplied_root: Path,
    *,
    approved_digest: str,
    approved_transaction_id: str,
) -> tuple[int, dict[str, object]]:
    project_root, recovery_blocker = _clean_project_preflight(project_root)
    if recovery_blocker is not None:
        return EXIT_RECOVERY_REQUIRED, recovery_blocker
    errors = _validate_plan(plan)
    if errors:
        return EXIT_INVOCATION, {
            "status": _error_status("invalid-plan", errors),
            "errors": errors,
        }
    if str(project_root) != plan.get("project_root"):
        return EXIT_BLOCKED, {
            "status": "stale-plan",
            "errors": ["refresh plan is bound to a different project root"],
        }
    if approved_digest != plan.get("plan_sha256"):
        return EXIT_BLOCKED, {
            "status": "approval-required",
            "errors": ["--approve-plan-sha256 must exactly match the bundle-bound plan"],
        }
    if approved_transaction_id != plan.get("refresh_transaction_id"):
        return EXIT_BLOCKED, {
            "status": "approval-required",
            "errors": [
                "--approve-refresh-transaction-id must exactly match the bundle-bound refresh transaction"
            ],
        }
    root, bundle_ref, location_errors = _backout_bundle_location(
        plan,
        supplied_root,
        require_current=True,
    )
    if root is None or bundle_ref is None:
        return EXIT_BLOCKED, {
            "status": "invalid-backout-root",
            "errors": location_errors,
        }
    lifecycle_blocker = _backout_root_lifecycle_blocker(
        project_root,
        plan,
        root,
        bundle_ref,
    )
    if lifecycle_blocker is not None:
        return lifecycle_blocker
    blobs, manifest, bundle_errors = _read_verified_backout_bundle(
        project_root,
        plan,
        root,
        require_project_preimage=False,
    )
    if bundle_errors:
        return EXIT_BLOCKED, {
            "status": "invalid-backout-bundle",
            "errors": bundle_errors,
        }
    operations = plan["operations"]
    assert isinstance(operations, list)
    for operation in operations:
        assert isinstance(operation, dict)
        path = str(operation["path"])
        digest, mode, evidence_error = _existing_project_file_evidence(
            project_root,
            path,
        )
        if evidence_error is not None:
            return EXIT_BLOCKED, {
                "status": "stale-target",
                "errors": [evidence_error],
            }
        if (
            digest != operation.get("target_sha256")
            or mode != operation.get("target_mode")
        ):
            return EXIT_BLOCKED, {
                "status": "stale-target",
                "errors": [
                    "project no longer matches the exact post-apply bytes and mode; refusing to "
                    f"overwrite later work: {path}"
                ],
            }

    entries = _expected_backout_entries(plan)
    ordered_outputs: list[tuple[str, str]] = []
    remove_outputs: list[str] = []
    for entry in entries:
        path = str(entry["path"])
        if entry["state"] == "absent":
            remove_outputs.append(path)
            continue
        raw = blobs[path]
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            return EXIT_BLOCKED, {
                "status": "invalid-backout-bundle",
                "errors": [f"backout preimage is not valid UTF-8 text for {path}: {exc}"],
            }
        ordered_outputs.append((path, text))
    expected_preimages = {
        str(operation["path"]): operation.get("target_sha256")
        for operation in operations
        if operation.get("action") != "preserve"
    }
    expected_preimage_modes: dict[str, int | None] = {
        str(operation["path"]): cast(int | None, operation.get("target_mode"))
        for operation in operations
        if operation.get("action") != "preserve"
    }
    assert_preimages = {
        str(operation["path"]): str(operation["current_sha256"])
        for operation in operations
        if operation.get("action") == "preserve"
    }
    assert_preimage_modes = {
        str(operation["path"]): cast(int, operation["current_mode"])
        for operation in operations
        if operation.get("action") == "preserve"
    }
    target_modes = {
        str(entry["path"]): cast(int, entry["mode"])
        for entry in entries
        if entry["state"] == "file"
    }
    creation_modes = cast(dict[str, int | None], plan["creation_modes"])
    absent_parent_directories = cast(
        list[str],
        plan["absent_parent_directories"],
    )
    retired_directory_modes = {
        path: cast(int, creation_modes["directory"])
        for path in absent_parent_directories
    }
    verification: dict[str, object] = {}

    def verify() -> None:
        for entry in entries:
            path = str(entry["path"])
            digest, mode, evidence_error = _existing_project_file_evidence(
                project_root,
                path,
            )
            if (
                evidence_error is not None
                or digest != entry["sha256"]
                or mode != entry["mode"]
            ):
                raise ValueError(
                    f"restored preimage does not match exact bundle evidence: {path}: "
                    f"{evidence_error or 'digest or mode mismatch'}"
                )
        preimage = project_instance_lint.validate_recorded_preimage(
            project_root,
            str(plan["current_contract_root"]),
        )
        preimage_errors = list(cast(list[str], preimage["errors"]))
        if preimage_errors:
            raise ValueError(
                "restored current-format instance failed recorded-preimage validation: "
                + "; ".join(preimage_errors)
            )
        verification["recorded_preimage"] = "pass"
        selected = project_instance_lint.validate_selected_checkout(
            preimage,
            framework_root=FRAMEWORK_ROOT,
        )
        verification["selected_checkout"] = (
            "pass" if not selected["errors"] else "historical-not-current"
        )
        verification["selected_checkout_errors"] = selected["errors"]
        verification["selected_checkout_warnings"] = selected["warnings"]

    try:
        result = bootstrap_transaction.transactional_write_outputs(
            project_root,
            ordered_outputs,
            force=True,
            remove_outputs=remove_outputs,
            retire_empty_directories=absent_parent_directories,
            post_install_verifier=verify,
            expected_preimages=expected_preimages,
            expected_preimage_modes=expected_preimage_modes,
            assert_preimages=assert_preimages,
            assert_preimage_modes=assert_preimage_modes,
            target_modes=target_modes,
            retired_directory_modes=retired_directory_modes,
        )
    except (bootstrap_transaction.BootstrapTransactionError, OSError, ValueError) as exc:
        try:
            recovery = bootstrap_transaction.transaction_recovery_status(project_root)
        except (OSError, ValueError) as status_exc:
            return EXIT_RECOVERY_REQUIRED, {
                "status": "recovery-required",
                "errors": [str(exc), str(status_exc)],
            }
        return (
            EXIT_RECOVERY_REQUIRED if recovery.state != "clean" else EXIT_ROLLED_BACK,
            {
                "status": (
                    "recovery-required" if recovery.state != "clean" else "rolled-back"
                ),
                "transaction_id": recovery.transaction_id,
                "errors": [str(exc), *recovery.errors],
            },
        )
    try:
        recovery = bootstrap_transaction.transaction_recovery_status(project_root)
    except (OSError, ValueError) as exc:
        return EXIT_RECOVERY_REQUIRED, {
            "status": "recovery-required",
            "errors": [f"restore completed but clean transaction state is unproved: {exc}"],
        }
    if recovery.state != "clean" or recovery.errors or result.cleanup_warnings:
        return EXIT_RECOVERY_REQUIRED, {
            "status": "recovery-required",
            "transaction_id": recovery.transaction_id,
            "errors": [*recovery.errors, *result.cleanup_warnings],
        }
    return 0, {
        "status": "restored",
        "plan_sha256": plan["plan_sha256"],
        "refresh_transaction_id": plan["refresh_transaction_id"],
        "bundle_manifest": manifest,
        "written": result.written,
        "removed": result.removed,
        "verification": verification,
        "errors": [],
    }


def _run_profiles(
    project_root: Path,
    contract_root_ref: str,
    profiles: list[str],
    *,
    project_kind: str,
) -> list[dict[str, object]]:
    contract_root, errors = _contract_root(project_root, contract_root_ref)
    if errors:
        raise ValueError("post-install contract root is invalid: " + "; ".join(errors))
    report = conformance_check.run_profiles(
        profiles,
        project_root,
        contract_root=contract_root,
        contract_root_ref=contract_root_ref,
        project_kind=project_kind,
    )
    report_errors = report.get("errors")
    report_warnings = report.get("warnings")
    if not isinstance(report_errors, list) or not all(
        isinstance(item, str) for item in report_errors
    ):
        raise ValueError("post-install conformance union returned invalid errors")
    if not isinstance(report_warnings, list) or not all(
        isinstance(item, str) for item in report_warnings
    ):
        raise ValueError("post-install conformance union returned invalid warnings")
    if report.get("status") == "fail" or report_errors:
        details = [*report_errors, *report_warnings]
        raise ValueError(
            "post-install conformance union did not pass: "
            + "; ".join(str(item) for item in details)
        )
    if report.get("status") not in {"pass", "warn"}:
        raise ValueError("post-install conformance union returned invalid status")
    if report_warnings:
        raise ValueError(
            "post-install conformance union produced non-waivable warnings: "
            + "; ".join(cast(list[str], report_warnings))
        )
    if report.get("status") != "pass":
        raise ValueError(
            "post-install conformance union did not return pass without warnings"
        )
    return [cast(dict[str, object], report)]


def apply_plan(
    project_root: Path,
    plan: dict[str, object],
    *,
    approved_digest: str,
    approved_actions: set[str],
    approved_warnings: set[str],
) -> tuple[int, dict[str, object]]:
    project_root, recovery_blocker = _clean_project_preflight(project_root)
    if recovery_blocker is not None:
        return EXIT_RECOVERY_REQUIRED, recovery_blocker
    errors = _validate_plan(plan)
    if errors:
        return EXIT_INVOCATION, {
            "status": _error_status("invalid-plan", errors),
            "errors": errors,
        }
    plan_digest = str(plan["plan_sha256"])
    if approved_digest != plan_digest:
        return EXIT_BLOCKED, {
            "status": "approval-required",
            "errors": ["--approve-plan-sha256 must exactly match the canonical plan digest"],
        }
    if str(project_root) != plan.get("project_root"):
        return EXIT_BLOCKED, {
            "status": "stale-plan",
            "errors": ["refresh plan is bound to a different project root"],
        }
    required_actions = set(cast(list[str], plan.get("required_actions", [])))
    if approved_actions != required_actions:
        return EXIT_BLOCKED, {
            "status": "approval-required",
            "errors": [
                "--approve-action values must exactly match required_actions: "
                + ", ".join(sorted(required_actions))
            ],
        }
    warning_items = cast(list[dict[str, object]], plan.get("warnings", []))
    required_warnings = {
        str(item["id"])
        for item in warning_items
        if isinstance(item, dict) and "id" in item
    }
    if approved_warnings != required_warnings:
        return EXIT_BLOCKED, {
            "status": "approval-required",
            "errors": [
                "--approve-warning values must exactly match plan warning ids: "
                + ", ".join(sorted(required_warnings))
            ],
        }
    backout = plan.get("post_apply_backout")
    backout_errors = _validate_backout_basis(
        backout,
        require_current=True,
        project_root=project_root,
    )
    if backout_errors:
        return EXIT_BLOCKED, {"status": "stale-plan", "errors": backout_errors}
    if isinstance(backout, dict) and backout.get("kind") == "exact-preimage-bundle":
        bundle_root = Path(str(backout["root"]))
        bundle_code, bundle_report = verify_backout_bundle(
            project_root,
            plan,
            bundle_root,
            require_project_preimage=True,
        )
        if bundle_code != 0:
            return bundle_code, bundle_report
        _verified_root, verified_bundle_ref, verified_location_errors = (
            _backout_bundle_location(
                plan,
                bundle_root,
                require_current=True,
            )
        )
        if verified_location_errors or verified_bundle_ref is None:
            return EXIT_BLOCKED, {
                "status": "invalid-backout-root",
                "errors": verified_location_errors,
            }
    else:
        bundle_root = None
        verified_bundle_ref = None
    rebuilt = _rebuild_plan(project_root, plan)
    if rebuilt.payload is None:
        return EXIT_BLOCKED, {"status": "stale-plan", "errors": rebuilt.errors}
    if rebuilt.payload.get("plan_sha256") != plan_digest:
        return EXIT_BLOCKED, {
            "status": "stale-plan",
            "errors": [
                "project or framework preimages changed after planning; inspect and create a new plan"
            ],
        }
    operations = cast(list[dict[str, object]], plan["operations"])
    write_names = {
        str(item["path"])
        for item in operations
        if isinstance(item, dict) and item.get("action") in {"create", "replace"}
    }
    ordered_outputs = [
        (name, rebuilt.target_outputs[name])
        for name in sorted(write_names)
    ]
    expected_preimages = {
        str(item["path"]): (
            str(item["current_sha256"])
            if item.get("current_sha256") is not None
            else None
        )
        for item in operations
        if isinstance(item, dict)
        and item.get("action") in {"create", "replace", "remove"}
    }
    assert_preimages = {
        str(item["path"]): str(item["current_sha256"])
        for item in operations
        if isinstance(item, dict)
        and item.get("action") == "preserve"
        and item.get("current_sha256") is not None
    }
    expected_preimage_modes: dict[str, int | None] = {
        str(item["path"]): cast(int | None, item.get("current_mode"))
        for item in operations
        if isinstance(item, dict)
        and item.get("action") in {"create", "replace", "remove"}
    }
    assert_preimage_modes = {
        str(item["path"]): cast(int, item["current_mode"])
        for item in operations
        if isinstance(item, dict) and item.get("action") == "preserve"
    }
    target_modes = {
        str(item["path"]): cast(int, item["target_mode"])
        for item in operations
        if isinstance(item, dict)
        and item.get("action") in {"create", "replace"}
    }
    creation_modes = cast(dict[str, int | None], plan["creation_modes"])
    profile_reports: list[dict[str, object]] = []
    target_input = plan["target_input"]
    assert isinstance(target_input, dict)
    project_kind = str(target_input.get("project_kind"))

    def verify_framework_and_preserved_state() -> None:
        selected_identity = project_bootstrap.capture_framework_identity(FRAMEWORK_ROOT)
        if (
            selected_identity.content_sha256 != plan.get("framework_content_sha256")
            or selected_identity.distribution_sha256
            != plan.get("framework_distribution_sha256")
        ):
            raise ValueError("selected framework bytes changed after planning")
        current_backout_errors = _validate_backout_basis(
            plan.get("post_apply_backout"),
            require_current=True,
            project_root=project_root,
        )
        if current_backout_errors:
            raise ValueError("; ".join(current_backout_errors))
        if bundle_root is not None and verified_bundle_ref is not None:
            lifecycle_blocker = _backout_root_lifecycle_blocker(
                project_root,
                plan,
                bundle_root,
                verified_bundle_ref,
            )
            if lifecycle_blocker is not None:
                _code, report = lifecycle_blocker
                raise ValueError(
                    "; ".join(cast(list[str], report.get("errors", [])))
                )
            _blobs, _manifest, bundle_errors = _read_verified_backout_bundle(
                project_root,
                plan,
                bundle_root,
                require_project_preimage=False,
            )
            if bundle_errors:
                raise ValueError(
                    "exact-preimage bundle changed after preflight: "
                    + "; ".join(bundle_errors)
                )
        for item in operations:
            if not isinstance(item, dict) or item.get("action") != "preserve":
                continue
            name = str(item["path"])
            digest, mode, evidence_error = _existing_project_file_evidence(
                project_root,
                name,
            )
            if (
                evidence_error is not None
                or digest != item.get("current_sha256")
                or mode != item.get("current_mode")
            ):
                raise ValueError(
                    f"preserved project file changed after planning: {name}: "
                    f"{evidence_error or 'digest or mode mismatch'}"
                )

    def verify() -> None:
        verify_framework_and_preserved_state()
        profile_reports.extend(
            _run_profiles(
                project_root,
                str(plan["target_contract_root"]),
                list(cast(list[str], plan["active_profiles"])),
                project_kind=project_kind,
            )
        )
        verify_framework_and_preserved_state()

    if not ordered_outputs and not rebuilt.remove_outputs:
        try:
            verify()
        except (OSError, ValueError) as exc:
            return EXIT_BLOCKED, {
                "status": "verification-failed",
                "plan_sha256": plan_digest,
                "errors": [str(exc)],
            }
        return 0, {
            "status": "current",
            "plan_sha256": plan_digest,
            "written": [],
            "removed": [],
            "preserved": sorted(
                str(item["path"])
                for item in operations
                if isinstance(item, dict) and item.get("action") == "preserve"
            ),
            "profiles": profile_reports,
            "cleanup_warnings": [],
        }
    try:
        result = bootstrap_transaction.transactional_write_outputs(
            project_root,
            ordered_outputs,
            force=True,
            remove_outputs=rebuilt.remove_outputs,
            post_install_verifier=verify,
            expected_preimages=expected_preimages,
            expected_preimage_modes=expected_preimage_modes,
            assert_preimages=assert_preimages,
            assert_preimage_modes=assert_preimage_modes,
            target_modes=target_modes,
            create_file_mode=creation_modes["file"],
            create_directory_mode=creation_modes["directory"],
        )
    except (bootstrap_transaction.BootstrapTransactionError, OSError, ValueError) as exc:
        try:
            recovery = bootstrap_transaction.transaction_recovery_status(project_root)
        except (OSError, ValueError) as status_exc:
            return EXIT_RECOVERY_REQUIRED, {
                "status": "recovery-required",
                "plan_sha256": plan_digest,
                "errors": [
                    str(exc),
                    f"recovery state could not be proved after apply failure: {status_exc}",
                ],
                "transaction_id": None,
            }
        recovery_required = (
            recovery.state != "clean"
            or bool(recovery.errors)
            or recovery.transaction_id is not None
            or recovery.can_rollback
            or recovery.can_finalize
        )
        return (
            EXIT_RECOVERY_REQUIRED if recovery_required else EXIT_ROLLED_BACK,
            {
                "status": "recovery-required" if recovery_required else "rolled-back",
                "plan_sha256": plan_digest,
                "errors": [str(exc), *recovery.errors],
                "transaction_id": recovery.transaction_id,
            },
        )
    try:
        recovery = bootstrap_transaction.transaction_recovery_status(project_root)
    except (OSError, ValueError) as status_exc:
        return EXIT_RECOVERY_REQUIRED, {
            "status": "recovery-required",
            "plan_sha256": plan_digest,
            "written": result.written,
            "removed": result.removed,
            "cleanup_warnings": result.cleanup_warnings,
            "transaction_id": None,
            "errors": [
                f"recovery state could not be proved after candidate installation: {status_exc}"
            ],
        }
    if (
        recovery.state != "clean"
        or recovery.errors
        or recovery.transaction_id is not None
        or result.cleanup_warnings
    ):
        return EXIT_RECOVERY_REQUIRED, {
            "status": "recovery-required",
            "plan_sha256": plan_digest,
            "written": result.written,
            "removed": result.removed,
            "cleanup_warnings": result.cleanup_warnings,
            "transaction_id": recovery.transaction_id,
            "phase": recovery.phase,
            "can_finalize": recovery.can_finalize,
            "errors": list(recovery.errors),
        }
    return 0, {
        "status": "applied",
        "plan_sha256": plan_digest,
        "written": result.written,
        "removed": result.removed,
        "preserved": sorted(
            str(item["path"])
            for item in operations
            if isinstance(item, dict) and item.get("action") == "preserve"
        ),
        "profiles": profile_reports,
        "cleanup_warnings": result.cleanup_warnings,
    }


def recover_project(
    project_root: Path,
    *,
    action: str,
    approved_transaction_id: str,
) -> tuple[int, dict[str, object]]:
    if action not in {"rollback", "finalize"}:
        return EXIT_INVOCATION, {
            "status": "invalid-recovery-request",
            "errors": ["recovery action must be exactly rollback or finalize"],
        }
    project_root = project_root.expanduser().resolve(strict=False)
    try:
        before = bootstrap_transaction.transaction_recovery_status(project_root)
    except (OSError, ValueError) as exc:
        return EXIT_RECOVERY_REQUIRED, {
            "status": "invalid",
            "errors": [f"transaction recovery state could not be inspected: {exc}"],
        }
    if before.errors:
        return EXIT_RECOVERY_REQUIRED, {
            "status": "invalid",
            "errors": list(before.errors),
            "transaction_id": before.transaction_id,
        }
    if before.state == "clean" and before.transaction_id is None:
        return 0, {"status": "clean", "transaction_id": None, "errors": []}
    if before.transaction_id is None:
        return EXIT_RECOVERY_REQUIRED, {
            "status": before.state,
            "transaction_id": None,
            "errors": [
                "recovery state is not clean but has no actionable transaction identity"
            ],
        }
    if approved_transaction_id != before.transaction_id:
        return EXIT_BLOCKED, {
            "status": "approval-required",
            "transaction_id": before.transaction_id,
            "errors": [
                "--approve-transaction-id must exactly match the inspected recovery transaction"
            ],
        }
    try:
        if action == "rollback":
            if not before.can_rollback:
                return EXIT_BLOCKED, {
                    "status": "action-not-allowed",
                    "transaction_id": before.transaction_id,
                    "errors": ["the current recovery phase cannot be rolled back"],
                }
            after = bootstrap_transaction.rollback_interrupted_transaction(
                project_root,
                expected_transaction_id=approved_transaction_id,
            )
        else:
            if not before.can_finalize:
                return EXIT_BLOCKED, {
                    "status": "action-not-allowed",
                    "transaction_id": before.transaction_id,
                    "errors": ["the current recovery phase cannot be finalized"],
                }
            after = bootstrap_transaction.finalize_interrupted_transaction(
                project_root,
                expected_transaction_id=approved_transaction_id,
            )
    except (bootstrap_transaction.BootstrapTransactionError, OSError, ValueError) as exc:
        return EXIT_RECOVERY_REQUIRED, {
            "status": "recovery-required",
            "transaction_id": before.transaction_id,
            "errors": [f"recovery action failed without proving a clean state: {exc}"],
        }
    code = 0 if not after.errors and after.transaction_id is None else EXIT_RECOVERY_REQUIRED
    return code, {
        "status": after.state,
        "transaction_id": after.transaction_id,
        "phase": after.phase,
        "operation_paths": list(after.operation_paths),
        "errors": list(after.errors),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Render candidate input, inspect lifecycle state, plan and apply an exact "
            "refresh, manage plan-bound backout, or recover an interrupted Master "
            "Prompt Agreement project transaction."
        ),
        allow_abbrev=False,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    candidate_parser = subparsers.add_parser(
        "candidate",
        help="Render validated canonical candidate input without modifying the project.",
        description=(
            "Render validated canonical candidate PROJECT_INPUT JSON on stdout from "
            "complete revised answers. This command does not modify the project."
        ),
        allow_abbrev=False,
    )
    candidate_parser.add_argument(
        "--answers",
        required=True,
        help="Path to the complete revised answers JSON used to render candidate input.",
    )
    candidate_parser.add_argument(
        "--project-root",
        required=True,
        help=(
            "Governed project root whose verified current instance supplies retained "
            "defaults and identity."
        ),
    )
    candidate_parser.add_argument(
        "--project-kind",
        choices=("downstream", "framework-authoring"),
        default="downstream",
        help=(
            "Project role to record. Downstream requires --runtime; framework-authoring "
            "forbids runtime and wrapper selection."
        ),
    )
    candidate_parser.add_argument(
        "--contract-root",
        help=(
            "Safe project-relative contract root. Omit only when a root-scoped "
            "current receipt can select it."
        ),
    )
    candidate_parser.add_argument(
        "--runtime",
        choices=sorted(project_bootstrap.ENTRYPOINT_TEMPLATES),
        help=(
            "Downstream runtime family to record; required for downstream and forbidden "
            "for framework-authoring."
        ),
    )
    wrapper_group = candidate_parser.add_mutually_exclusive_group()
    wrapper_group.add_argument(
        "--runtime-wrapper",
        action="append",
        default=None,
        help=(
            "For a downstream candidate, replace the complete runtime-wrapper "
            "selection with one registry-owned ID; repeat for the exact target set, "
            "or omit to retain the verified current runtime family and wrapper-ID "
            "selection. Framework-authoring candidates must omit both wrapper flags."
        ),
    )
    wrapper_group.add_argument(
        "--clear-runtime-wrappers",
        action="store_true",
        help=(
            "For a downstream candidate, explicitly replace the runtime-wrapper "
            "selection with the empty set. Framework-authoring candidates must omit "
            "both wrapper flags."
        ),
    )
    candidate_parser.add_argument(
        "--framework-ref",
        required=True,
        help=(
            "Selected framework reference to record. Candidate rendering never fetches "
            "or updates the reference."
        ),
    )
    candidate_parser.add_argument(
        "--framework-revision-policy",
        choices=sorted(project_input.REVISION_POLICIES),
        required=True,
        help=(
            "Record whether the selected framework reference is intentionally live or "
            "operator-pinned."
        ),
    )

    inspect_parser = subparsers.add_parser(
        "inspect",
        help="Classify the exact current project lifecycle state without writing.",
        description=(
            "Inspect and classify a retained project instance without writing. Use "
            "--check when only an exact current result may exit successfully."
        ),
        allow_abbrev=False,
    )
    inspect_parser.add_argument(
        "--project-root",
        required=True,
        help="Governed project root to inspect and classify without writing.",
    )
    inspect_parser.add_argument(
        "--contract-root",
        help=(
            "Expected safe project-relative contract root. Defaults to the value "
            "recorded by the root-scoped current receipt."
        ),
    )
    inspect_parser.add_argument(
        "--check",
        action="store_true",
        help="Exit unsuccessfully unless the reported lifecycle status is exactly current.",
    )

    plan_parser = subparsers.add_parser(
        "plan",
        help="Emit a canonical no-write refresh plan bound to exact preimages.",
        description=(
            "Build a canonical refresh plan on stdout after verifying the current "
            "instance, candidate input when supplied, and selected backout basis. The "
            "command does not modify project paths."
        ),
        allow_abbrev=False,
    )
    plan_parser.add_argument(
        "--project-root",
        required=True,
        help="Governed project root whose exact current preimage the plan must bind.",
    )
    plan_parser.add_argument(
        "--contract-root",
        help=(
            "Expected safe project-relative contract root. Defaults to the value "
            "recorded by the root-scoped current receipt."
        ),
    )
    plan_parser.add_argument(
        "--candidate-input",
        help=(
            "Path to canonical candidate PROJECT_INPUT JSON for a contract, runtime, or "
            "optional-surface revision; omit for a framework-only refresh."
        ),
    )
    plan_parser.add_argument(
        "--backout-root",
        help=(
            "Existing absolute private directory for a plan-bound exact-preimage bundle. "
            "Required for the normal mutating path."
        ),
    )
    plan_parser.add_argument(
        "--accept-no-post-apply-backout",
        action="store_true",
        help="Explicitly accept that transaction recovery does not provide post-success semantic backout.",
    )
    apply_parser = subparsers.add_parser(
        "apply",
        help="Revalidate and transactionally apply exactly one reviewed refresh plan.",
        description=(
            "Revalidate and transactionally apply exactly one reviewed refresh plan. "
            "The supplied digest, action IDs, and warning IDs must exactly approve the "
            "plan."
        ),
        allow_abbrev=False,
    )
    apply_parser.add_argument(
        "--project-root",
        required=True,
        help="Governed project root bound by the reviewed refresh plan.",
    )
    apply_parser.add_argument(
        "--plan",
        required=True,
        help="Path to the canonical reviewed refresh-plan JSON.",
    )
    apply_parser.add_argument(
        "--approve-plan-sha256",
        required=True,
        help="Exact plan_sha256 value from the reviewed refresh plan.",
    )
    apply_parser.add_argument(
        "--approve-action",
        action="append",
        default=[],
        help=(
            "Approve one exact required_actions ID from the plan; repeat until the "
            "supplied set exactly matches the plan."
        ),
    )
    apply_parser.add_argument(
        "--approve-warning",
        action="append",
        default=[],
        help=(
            "Approve one exact warning ID from the plan; repeat until the supplied set "
            "exactly matches the plan."
        ),
    )

    preview_parser = subparsers.add_parser(
        "preview",
        help="Expose plan-bound current and target evidence without writing.",
        description=(
            "Regenerate and report plan-bound current and target text, unified diffs, "
            "digests, and POSIX rwx modes without writing project paths."
        ),
        allow_abbrev=False,
    )
    preview_parser.add_argument(
        "--project-root",
        required=True,
        help="Governed project root bound by the reviewed refresh plan.",
    )
    preview_parser.add_argument(
        "--plan",
        required=True,
        help="Path to the canonical reviewed refresh-plan JSON to preview.",
    )

    backout_command_help = {
        "backout-create": (
            "Capture exact affected-path preimages in the plan-bound private bundle.",
            "Transactionally capture the plan's exact affected-path preimages in its "
            "plan-bound, owner-only private backout bundle.",
        ),
        "backout-verify": (
            "Verify the plan-bound private backout bundle and optional live preimages.",
            "Verify the closed manifest and exact preimage blobs in the plan-bound "
            "private backout bundle, optionally including the live project preimage.",
        ),
    }
    for command in ("backout-create", "backout-verify"):
        command_help, command_description = backout_command_help[command]
        backout_parser = subparsers.add_parser(
            command,
            help=command_help,
            description=command_description,
            allow_abbrev=False,
        )
        backout_parser.add_argument(
            "--project-root",
            required=True,
            help="Governed project root bound by the refresh plan.",
        )
        backout_parser.add_argument(
            "--plan",
            required=True,
            help="Path to the canonical reviewed refresh-plan JSON.",
        )
        backout_parser.add_argument(
            "--backout-root",
            required=True,
            help=(
                "Existing absolute, owner-only private directory bound by the plan as "
                "the bundle root."
            ),
        )
        if command == "backout-verify":
            backout_parser.add_argument(
                "--require-project-preimage",
                action="store_true",
                help="Also prove that the project still matches every captured preimage.",
            )

    restore_parser = subparsers.add_parser(
        "backout-restore",
        help="Restore exact preimages while every managed target remains post-apply.",
        description=(
            "Transactionally restore the bundle's exact affected-path preimages only "
            "while every plan-listed managed target still matches its exact post-apply "
            "state."
        ),
        allow_abbrev=False,
    )
    restore_parser.add_argument(
        "--project-root",
        required=True,
        help="Governed project root to restore from the plan-bound bundle.",
    )
    restore_parser.add_argument(
        "--plan",
        required=True,
        help="Path to the canonical bundle-bound refresh-plan JSON.",
    )
    restore_parser.add_argument(
        "--backout-root",
        required=True,
        help="Existing absolute, owner-only private directory containing the bundle.",
    )
    restore_parser.add_argument(
        "--approve-plan-sha256",
        required=True,
        help="Exact plan_sha256 value from the bundle-bound refresh plan.",
    )
    restore_parser.add_argument(
        "--approve-refresh-transaction-id",
        required=True,
        help="Exact refresh_transaction_id value from the bundle-bound refresh plan.",
    )

    backout_recover_parser = subparsers.add_parser(
        "backout-recover",
        help="Recover an interrupted private backout-bundle creation transaction.",
        description=(
            "Run only the permitted rollback or finalize action for an interrupted "
            "plan-bound private backout-bundle creation transaction. This is not "
            "governed-project recovery."
        ),
        allow_abbrev=False,
    )
    backout_recover_parser.add_argument(
        "--project-root",
        required=True,
        help="Governed project root bound by the refresh plan and backout bundle.",
    )
    backout_recover_parser.add_argument(
        "--plan",
        required=True,
        help="Path to the canonical bundle-bound refresh-plan JSON.",
    )
    backout_recover_parser.add_argument(
        "--backout-root",
        required=True,
        help=(
            "Existing absolute, owner-only private directory containing the interrupted "
            "bundle transaction."
        ),
    )
    backout_recover_parser.add_argument(
        "--action",
        choices=("rollback", "finalize"),
        required=True,
        help="Exact recovery action permitted by the inspected private-root transaction.",
    )
    backout_recover_parser.add_argument(
        "--approve-transaction-id",
        required=True,
        help="Exact transaction ID reported for the private backout-root recovery state.",
    )

    recover_parser = subparsers.add_parser(
        "recover",
        help="Recover an interrupted governed-project refresh transaction.",
        description=(
            "Run only the rollback or finalize action permitted by the inspected durable "
            "governed-project transaction state, using its exact transaction identity."
        ),
        allow_abbrev=False,
    )
    recover_parser.add_argument(
        "--project-root",
        required=True,
        help="Governed project root whose interrupted transaction will be recovered.",
    )
    recover_parser.add_argument(
        "--action",
        choices=("rollback", "finalize"),
        required=True,
        help="Exact recovery action permitted by the inspected project transaction.",
    )
    recover_parser.add_argument(
        "--approve-transaction-id",
        required=True,
        help="Exact transaction ID reported by inspection for the project recovery state.",
    )
    return parser


def _run_command(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    project_root = Path(args.project_root)
    if args.command not in {"inspect", "recover"}:
        project_root, recovery_blocker = _clean_project_preflight(project_root)
        if recovery_blocker is not None:
            _print(recovery_blocker)
            return EXIT_RECOVERY_REQUIRED
    if args.command == "candidate":
        runtime = args.runtime
        if args.project_kind == "downstream" and runtime is None:
            _print(
                {
                    "status": "invalid-candidate-input",
                    "errors": ["downstream candidate creation requires --runtime"],
                }
            )
            return EXIT_INVOCATION
        if args.project_kind == "framework-authoring" and runtime is not None:
            _print(
                {
                    "status": "invalid-candidate-input",
                    "errors": ["framework-authoring candidate creation must omit --runtime"],
                }
            )
            return EXIT_INVOCATION
        if args.project_kind == "framework-authoring" and (
            args.runtime_wrapper is not None or args.clear_runtime_wrappers
        ):
            _print(
                {
                    "status": "invalid-candidate-input",
                    "errors": [
                        "framework-authoring candidate creation must omit runtime-wrapper selection flags"
                    ],
                }
            )
            return EXIT_INVOCATION
        runtime_wrappers = (
            ()
            if args.clear_runtime_wrappers
            else None
            if args.runtime_wrapper is None
            else tuple(sorted(args.runtime_wrapper))
        )
        candidate, errors = render_candidate_input(
            answers_path=Path(args.answers),
            project_root=project_root.expanduser().resolve(strict=False),
            project_kind=args.project_kind,
            contract_root_ref=args.contract_root,
            runtime=runtime,
            runtime_wrappers=runtime_wrappers,
            framework_reference=args.framework_ref,
            framework_revision_policy=args.framework_revision_policy,
        )
        if candidate is None:
            _print(
                {
                    "status": _error_status("invalid-candidate-input", errors),
                    "errors": errors,
                }
            )
            return EXIT_INVOCATION
        _print(candidate)
        return 0
    if args.command == "preview":
        plan, errors = _load_plan(Path(args.plan))
        if plan is None or errors:
            _print(
                {
                    "status": _error_status("invalid-plan", errors),
                    "errors": errors,
                }
            )
            return EXIT_INVOCATION
        code, report = preview_plan(project_root, plan)
        _print(report)
        return code
    if args.command in {
        "backout-create",
        "backout-verify",
        "backout-restore",
        "backout-recover",
    }:
        plan, errors = _load_plan(Path(args.plan))
        if plan is None or errors:
            _print(
                {
                    "status": _error_status("invalid-plan", errors),
                    "errors": errors,
                }
            )
            return EXIT_INVOCATION
        if args.command == "backout-create":
            code, report = create_backout_bundle(
                project_root,
                plan,
                Path(args.backout_root),
            )
        elif args.command == "backout-verify":
            code, report = verify_backout_bundle(
                project_root,
                plan,
                Path(args.backout_root),
                require_project_preimage=args.require_project_preimage,
            )
        elif args.command == "backout-restore":
            code, report = restore_backout_bundle(
                project_root,
                plan,
                Path(args.backout_root),
                approved_digest=args.approve_plan_sha256,
                approved_transaction_id=args.approve_refresh_transaction_id,
            )
        else:
            code, report = recover_backout_bundle(
                project_root,
                plan,
                Path(args.backout_root),
                action=args.action,
                approved_transaction_id=args.approve_transaction_id,
            )
        _print(report)
        return code
    if args.command == "inspect":
        report = inspect_project(project_root, args.contract_root)
        _print(report)
        return 0 if not args.check or report["status"] == "current" else EXIT_BLOCKED
    if args.command == "plan":
        candidate: dict[str, object] | None = None
        if args.candidate_input:
            candidate, errors = _load_candidate_input(Path(args.candidate_input))
            if candidate is None or errors:
                _print(
                    {
                        "status": _error_status("invalid-candidate-input", errors),
                        "errors": errors,
                    }
                )
                return EXIT_INVOCATION
        backout, backout_errors = _backout_basis(
            project_root=project_root.expanduser().resolve(strict=False),
            backout_root=args.backout_root,
            accept_none=args.accept_no_post_apply_backout,
        )
        if backout_errors:
            _print({"status": "blocked", "errors": backout_errors})
            return EXIT_BLOCKED
        plan = build_plan(
            project_root,
            args.contract_root,
            candidate_input=candidate,
            post_apply_backout=backout,
        )
        if plan.payload is None:
            _print(
                {
                    "status": _error_status("blocked", plan.errors),
                    "errors": plan.errors,
                }
            )
            return EXIT_BLOCKED
        _print(plan.payload)
        return 0
    if args.command == "apply":
        plan, errors = _load_plan(Path(args.plan))
        if plan is None or errors:
            _print(
                {
                    "status": _error_status("invalid-plan", errors),
                    "errors": errors,
                }
            )
            return EXIT_INVOCATION
        code, report = apply_plan(
            project_root,
            plan,
            approved_digest=args.approve_plan_sha256,
            approved_actions=set(args.approve_action),
            approved_warnings=set(args.approve_warning),
        )
        _print(report)
        return code
    code, report = recover_project(
        project_root,
        action=args.action,
        approved_transaction_id=args.approve_transaction_id,
    )
    _print(report)
    return code


def main(argv: list[str] | None = None) -> int:
    """Run one public refresh command with bounded operational-error reporting.

    Filesystem failures and invalid path values can occur before a command's
    command-specific validator is reached.  They are expected operational input
    failures, so keep their CLI contract structured.  Deliberately do not catch
    assertion failures or general exceptions: programmer defects must remain
    visible rather than being mislabeled as user errors.
    """

    try:
        return _run_command(argv)
    except (OSError, ValueError) as exc:
        _print(
            {
                "status": "invalid-invocation",
                "errors": [f"refresh command could not inspect its input paths: {exc}"],
            }
        )
        return EXIT_INVOCATION
    except RuntimeError as exc:
        if str(exc) != "Could not determine home directory.":
            raise
        _print(
            {
                "status": "invalid-invocation",
                "errors": [f"refresh command could not expand its input paths: {exc}"],
            }
        )
        return EXIT_INVOCATION


if __name__ == "__main__":
    raise SystemExit(main())
