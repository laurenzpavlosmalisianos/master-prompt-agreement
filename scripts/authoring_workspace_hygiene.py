#!/usr/bin/env python3

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path, PurePosixPath
import stat
from typing import Any

import public_surface
import safe_paths


REPORT_SCHEMA_VERSION = 1
POLICY_SCHEMA_VERSION = 1
MAX_POLICY_BYTES = 64 * 1024
MAX_SCAN_ENTRIES = 100_000
MAX_SCAN_DEPTH = 64
MAX_REPORTED_ITEMS = 256
FDINFO_MAX_BYTES = 16 * 1024
TRANSACTION_REVIEW_CODES = frozenset(
    {"transaction-recovery-state", "transaction-protected-container"}
)
ANOMALY_REVIEW_CODES = frozenset(
    {
        "anomaly-protected-container",
        "hardlinked-file",
        "nested-mount-boundary",
        "owner-drift",
        "platform-metadata-kind-mismatch",
        "special-entry",
        "symlink-entry",
    }
)
POLICY_FIELDS = {
    "schema_version",
    "allowed_top_level_entries",
    "allowed_empty_directories",
    "allowed_empty_subtree_roots",
    "disposable_subtrees",
}
IGNORED_PLATFORM_METADATA_NAMES = frozenset({".DS_Store", "Thumbs.db"})
TRANSACTION_CONTROL_ROOT_NAMES = frozenset(
    {
        ".mpa-bootstrap-recovery.json",
        ".mpa-bootstrap.lock",
        ".mpa-bootstrap-recovery.tmp",
    }
)
TRANSACTION_CONTROL_PREFIX = ".mpa-bootstrap-transaction-"
RESIDUE_DIRECTORY_NAMES = frozenset(
    {
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        ".pyre",
        ".pytype",
        ".hypothesis",
        ".tox",
        ".nox",
        ".venv",
        ".direnv",
        "node_modules",
        ".npm",
        ".pnpm-store",
        ".yarn",
        "htmlcov",
    }
)
RESIDUE_FILE_SUFFIXES = (
    ".pyc",
    ".pyo",
    ".tmp",
    ".bak",
    ".orig",
    ".rej",
    ".swp",
    ".swo",
)


class WorkspaceScanError(RuntimeError):
    """Raised when a stable, bounded metadata inventory cannot be proved."""


@dataclass(frozen=True)
class Policy:
    allowed_top_level_entries: frozenset[str]
    allowed_empty_directories: frozenset[str]
    allowed_empty_subtree_roots: frozenset[str]
    disposable_subtrees: frozenset[str]


@dataclass(frozen=True)
class EntryRecord:
    kind: str
    signature: tuple[int, ...]
    mode: int
    nlink: int
    uid: int
    mount_id: int


@dataclass(frozen=True)
class Inventory:
    root_signature: tuple[int, ...]
    root_uid: int
    root_mount_id: int
    entries: tuple[tuple[str, EntryRecord], ...]

    def as_dict(self) -> dict[str, EntryRecord]:
        return dict(self.entries)


def _entry_kind(mode: int) -> str:
    if stat.S_ISREG(mode):
        return "file"
    if stat.S_ISDIR(mode):
        return "directory"
    if stat.S_ISLNK(mode):
        return "symlink"
    return "special"


def _record(metadata: os.stat_result, *, mount_id: int) -> EntryRecord:
    return EntryRecord(
        kind=_entry_kind(metadata.st_mode),
        signature=safe_paths.stable_file_metadata(metadata),
        mode=metadata.st_mode,
        nlink=metadata.st_nlink,
        uid=metadata.st_uid,
        mount_id=mount_id,
    )


def _directory_open_flags() -> int:
    required: list[str] = []
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    for name in ("O_DIRECTORY", "O_NOFOLLOW"):
        value = getattr(os, name, None)
        if not isinstance(value, int):
            required.append(name)
        else:
            flags |= value
    if required or os.open not in getattr(os, "supports_dir_fd", set()):
        detail = ", ".join(required) if required else "os.open dir_fd"
        raise WorkspaceScanError(
            "authoring workspace hygiene requires descriptor-safe POSIX traversal: "
            + detail
        )
    return flags


def _file_open_flags() -> int:
    required: list[str] = []
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    for name in ("O_NOFOLLOW", "O_NONBLOCK"):
        value = getattr(os, name, None)
        if not isinstance(value, int):
            required.append(name)
        else:
            flags |= value
    if required or os.open not in getattr(os, "supports_dir_fd", set()):
        detail = ", ".join(required) if required else "os.open dir_fd"
        raise WorkspaceScanError(
            "authoring workspace hygiene requires descriptor-safe POSIX reads: "
            + detail
        )
    return flags


def _descriptor_mount_id(descriptor: int) -> int:
    """Return one bounded Linux mount ID for an open descriptor."""

    fdinfo_path = f"/proc/{os.getpid()}/fdinfo/{descriptor}"
    fdinfo_descriptor: int | None = None
    try:
        fdinfo_descriptor = os.open(fdinfo_path, _file_open_flags())
        chunks: list[bytes] = []
        remaining = FDINFO_MAX_BYTES + 1
        while remaining:
            chunk = os.read(fdinfo_descriptor, min(4096, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
    except OSError as exc:
        raise WorkspaceScanError(
            "authoring workspace hygiene requires readable Linux procfs "
            f"descriptor mount metadata: {exc}"
        ) from exc
    finally:
        if fdinfo_descriptor is not None:
            os.close(fdinfo_descriptor)

    raw = b"".join(chunks)
    if len(raw) > FDINFO_MAX_BYTES:
        raise WorkspaceScanError(
            "Linux descriptor mount metadata exceeds the bounded input limit"
        )
    values = [
        line.removeprefix(b"mnt_id:\t")
        for line in raw.splitlines()
        if line.startswith(b"mnt_id:\t")
    ]
    if len(values) != 1 or not values[0].isdigit():
        raise WorkspaceScanError(
            "Linux descriptor mount metadata lacks one canonical mount ID"
        )
    mount_id = int(values[0])
    if mount_id <= 0:
        raise WorkspaceScanError("Linux descriptor mount ID must be positive")
    return mount_id


def validate_root(value: Path) -> Path:
    return Path(os.path.abspath(os.fspath(value.expanduser())))


def _normalize_policy_list(
    value: object,
    *,
    field: str,
    root: Path,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    if not isinstance(value, list):
        return [], [f"policy {field} must be an array"]
    normalized: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str):
            errors.append(f"policy {field}[{index}] must be a string")
            continue
        if item.count("/") + 1 > MAX_SCAN_DEPTH:
            errors.append(
                f"policy {field}[{index}] exceeds the "
                f"{MAX_SCAN_DEPTH}-component traversal depth bound"
            )
            continue
        try:
            normalized_item = safe_paths.normalize_repo_relative_path(
                item,
                root,
                description=f"policy {field}[{index}]",
            )
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if len(PurePosixPath(normalized_item).parts) > MAX_SCAN_DEPTH:
            errors.append(
                f"policy {field}[{index}] exceeds the "
                f"{MAX_SCAN_DEPTH}-component traversal depth bound"
            )
            continue
        normalized.append(normalized_item)
    if len(normalized) != len(set(normalized)):
        errors.append(f"policy {field} must not contain duplicate paths")
    if normalized != sorted(normalized):
        errors.append(f"policy {field} must be sorted")
    return normalized, errors


def parse_policy(raw: bytes, root: Path) -> tuple[Policy | None, list[str]]:
    errors: list[str] = []
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        return None, [f"workspace hygiene policy must be UTF-8: byte {exc.start}"]
    try:
        value = safe_paths.loads_json_no_duplicates(text)
    except json.JSONDecodeError as exc:
        return None, [f"workspace hygiene policy is invalid JSON: {exc}"]
    if not isinstance(value, dict):
        return None, ["workspace hygiene policy root must be an object"]
    if set(value) != POLICY_FIELDS:
        errors.append(
            "workspace hygiene policy fields must be exactly: "
            + ", ".join(sorted(POLICY_FIELDS))
        )
    schema_version = value.get("schema_version")
    if type(schema_version) is not int or schema_version != POLICY_SCHEMA_VERSION:
        errors.append(
            f"workspace hygiene policy schema_version must be {POLICY_SCHEMA_VERSION}"
        )

    top_level, top_errors = _normalize_policy_list(
        value.get("allowed_top_level_entries"),
        field="allowed_top_level_entries",
        root=root,
    )
    exact_empty, exact_errors = _normalize_policy_list(
        value.get("allowed_empty_directories"),
        field="allowed_empty_directories",
        root=root,
    )
    subtree_empty, subtree_errors = _normalize_policy_list(
        value.get("allowed_empty_subtree_roots"),
        field="allowed_empty_subtree_roots",
        root=root,
    )
    disposable, disposable_errors = _normalize_policy_list(
        value.get("disposable_subtrees"),
        field="disposable_subtrees",
        root=root,
    )
    errors.extend(top_errors)
    errors.extend(exact_errors)
    errors.extend(subtree_errors)
    errors.extend(disposable_errors)

    public_top_level = public_top_level_entries()
    for path in top_level:
        parts = PurePosixPath(path).parts
        if len(parts) != 1:
            errors.append(
                "policy allowed_top_level_entries must contain one-component paths: "
                + path
            )
        if path == ".git" or path in public_top_level:
            errors.append(
                "policy must not redeclare mechanism-owned or public top-level entry: "
                + path
            )

    classified_top_level = public_top_level | set(top_level) | {".git"}
    for field, paths in (
        ("allowed_empty_directories", exact_empty),
        ("allowed_empty_subtree_roots", subtree_empty),
        ("disposable_subtrees", disposable),
    ):
        for path in paths:
            parts = PurePosixPath(path).parts
            if len(parts) < 2:
                errors.append(
                    f"policy {field} must remain below a top-level root: {path}"
                )
                continue
            if parts[0] not in classified_top_level or parts[0] == ".git":
                errors.append(
                    f"policy {field} must remain below a classified non-Git root: {path}"
                )

    for path in disposable:
        if PurePosixPath(path).parts[0] in public_top_level:
            errors.append(
                "policy disposable_subtrees must not classify a public product path: "
                + path
            )

    subtree_set = set(subtree_empty)
    subtree_ancestors = {
        ancestor
        for path in subtree_empty
        for ancestor in _ancestors(path)
    }
    exact_covered_subtrees = {
        ancestor
        for path in exact_empty
        for ancestor in (path, *_ancestors(path))
        if ancestor in subtree_set
    }
    for path in subtree_empty:
        if path in subtree_ancestors:
            errors.append(
                "policy allowed_empty_subtree_roots must not contain redundant descendants: "
                + path
            )
        if path in exact_covered_subtrees:
            errors.append(
                "policy allowed_empty_directories must not duplicate a subtree allowance: "
                + path
            )

    disposable_ancestors = {
        ancestor
        for path in disposable
        for ancestor in _ancestors(path)
    }
    empty_paths = set(exact_empty) | subtree_set
    empty_ancestors = {
        ancestor
        for path in empty_paths
        for ancestor in _ancestors(path)
    }
    for path in disposable:
        if path in disposable_ancestors:
            errors.append(
                "policy disposable_subtrees must not contain redundant descendants: "
                + path
            )
        if (
            path in empty_paths
            or path in empty_ancestors
            or any(ancestor in empty_paths for ancestor in _ancestors(path))
        ):
            errors.append(
                "policy disposable_subtrees must not overlap an empty-directory allowance: "
                + path
            )

    if errors:
        return None, errors
    return (
        Policy(
            allowed_top_level_entries=frozenset(top_level),
            allowed_empty_directories=frozenset(exact_empty),
            allowed_empty_subtree_roots=frozenset(subtree_empty),
            disposable_subtrees=frozenset(disposable),
        ),
        [],
    )


def _read_bound_regular_file(
    root_descriptor: int,
    relative_path: str,
    *,
    description: str,
    max_bytes: int,
) -> bytes:
    directory_flags = _directory_open_flags()
    file_flags = _file_open_flags()
    parts = PurePosixPath(relative_path).parts
    directory_descriptor: int | None = None
    file_descriptor: int | None = None
    try:
        directory_descriptor = os.dup(root_descriptor)
        for component in parts[:-1]:
            next_descriptor = os.open(
                component,
                directory_flags,
                dir_fd=directory_descriptor,
            )
            os.close(directory_descriptor)
            directory_descriptor = next_descriptor
        file_descriptor = os.open(
            parts[-1],
            file_flags,
            dir_fd=directory_descriptor,
        )
        before = os.fstat(file_descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise WorkspaceScanError(f"{description} must be a regular file")
        if before.st_nlink != 1:
            raise WorkspaceScanError(f"{description} must have exactly one hard link")
        if before.st_size > max_bytes:
            raise WorkspaceScanError(
                f"{description} exceeds the {max_bytes}-byte input limit"
            )
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining:
            chunk = os.read(file_descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(file_descriptor)
        if len(raw) > max_bytes:
            raise WorkspaceScanError(
                f"{description} exceeds the {max_bytes}-byte input limit"
            )
        if (
            safe_paths.stable_file_metadata(before)
            != safe_paths.stable_file_metadata(after)
            or len(raw) != after.st_size
        ):
            raise WorkspaceScanError(f"{description} changed while it was read")
        return raw
    except OSError as exc:
        raise WorkspaceScanError(f"{description} cannot be read safely: {exc}") from exc
    finally:
        if file_descriptor is not None:
            os.close(file_descriptor)
        if directory_descriptor is not None:
            os.close(directory_descriptor)


def load_policy(
    root: Path,
    root_descriptor: int,
    policy_ref: str,
) -> tuple[Policy | None, bytes | None, list[str]]:
    try:
        normalized = safe_paths.normalize_repo_relative_path(
            policy_ref,
            root,
            description="workspace hygiene policy",
        )
        raw = _read_bound_regular_file(
            root_descriptor,
            normalized,
            description="workspace hygiene policy",
            max_bytes=MAX_POLICY_BYTES,
        )
    except (OSError, ValueError, WorkspaceScanError) as exc:
        return None, None, [f"workspace hygiene policy cannot be read safely: {exc}"]
    policy, errors = parse_policy(raw, root)
    return policy, raw, errors


def _scan_once(bound_root_descriptor: int) -> Inventory:
    directory_flags = _directory_open_flags()
    file_flags = _file_open_flags()
    try:
        root_descriptor = os.dup(bound_root_descriptor)
    except OSError as exc:
        raise WorkspaceScanError(f"workspace root descriptor cannot be duplicated: {exc}") from exc
    records: dict[str, EntryRecord] = {}
    entry_counter = [0]
    try:
        root_metadata = os.fstat(root_descriptor)
        if not stat.S_ISDIR(root_metadata.st_mode):
            raise WorkspaceScanError("opened workspace root is not a directory")
        root_mount_id = _descriptor_mount_id(root_descriptor)

        def walk(descriptor: int, prefix: str, depth: int) -> None:
            if depth > MAX_SCAN_DEPTH:
                raise WorkspaceScanError(
                    f"workspace traversal exceeds the {MAX_SCAN_DEPTH}-component depth bound"
                )
            before = os.fstat(descriptor)
            if _descriptor_mount_id(descriptor) != root_mount_id:
                raise WorkspaceScanError(
                    "workspace traversal crossed the bound root mount unexpectedly"
                )
            try:
                with os.scandir(descriptor) as iterator:
                    entries: list[os.DirEntry[str]] = []
                    for entry in iterator:
                        entry_counter[0] += 1
                        if entry_counter[0] > MAX_SCAN_ENTRIES:
                            raise WorkspaceScanError(
                                "workspace contains more than "
                                f"{MAX_SCAN_ENTRIES} inspected entries"
                            )
                        entries.append(entry)
                    entries.sort(key=lambda item: item.name)
            except OSError as exc:
                label = prefix or "."
                raise WorkspaceScanError(f"cannot enumerate workspace directory {label}: {exc}") from exc
            for entry in entries:
                try:
                    entry.name.encode("utf-8")
                except UnicodeEncodeError as exc:
                    raise WorkspaceScanError(
                        "workspace path names must be valid UTF-8"
                    ) from exc
                if safe_paths.PATH_CONTROL_RE.search(entry.name):
                    raise WorkspaceScanError(
                        "workspace path names must not contain control characters"
                    )
                rel = f"{prefix}/{entry.name}" if prefix else entry.name
                if depth + 1 > MAX_SCAN_DEPTH:
                    raise WorkspaceScanError(
                        "workspace traversal exceeds the "
                        f"{MAX_SCAN_DEPTH}-component depth bound: {rel}"
                    )
                try:
                    metadata = entry.stat(follow_symlinks=False)
                except OSError as exc:
                    raise WorkspaceScanError(f"cannot inspect workspace entry {rel}: {exc}") from exc
                kind = _entry_kind(metadata.st_mode)
                entry_descriptor: int | None = None
                try:
                    entry_mount_id = root_mount_id
                    if kind in {"directory", "file"}:
                        try:
                            entry_descriptor = os.open(
                                entry.name,
                                directory_flags if kind == "directory" else file_flags,
                                dir_fd=descriptor,
                            )
                        except OSError as exc:
                            raise WorkspaceScanError(
                                f"workspace {kind} cannot be opened without following "
                                f"links: {rel}: {exc}"
                            ) from exc
                        opened_metadata = os.fstat(entry_descriptor)
                        if (
                            safe_paths.stable_file_metadata(opened_metadata)
                            != safe_paths.stable_file_metadata(metadata)
                        ):
                            raise WorkspaceScanError(
                                f"workspace {kind} changed before inspection: {rel}"
                            )
                        entry_mount_id = _descriptor_mount_id(entry_descriptor)
                    record = _record(metadata, mount_id=entry_mount_id)
                    records[rel] = record
                    if (
                        kind == "directory"
                        and rel != ".git"
                        and entry_mount_id == root_mount_id
                    ):
                        if entry_descriptor is None:
                            raise WorkspaceScanError(
                                f"workspace directory descriptor is unavailable: {rel}"
                            )
                        walk(entry_descriptor, rel, depth + 1)
                finally:
                    if entry_descriptor is not None:
                        os.close(entry_descriptor)
            after = os.fstat(descriptor)
            if safe_paths.stable_file_metadata(before) != safe_paths.stable_file_metadata(after):
                label = prefix or "."
                raise WorkspaceScanError(f"workspace directory changed during scan: {label}")

        walk(root_descriptor, "", 0)
        final_root_metadata = os.fstat(root_descriptor)
        if safe_paths.stable_file_metadata(root_metadata) != safe_paths.stable_file_metadata(
            final_root_metadata
        ):
            raise WorkspaceScanError("workspace root changed during scan")
        if _descriptor_mount_id(root_descriptor) != root_mount_id:
            raise WorkspaceScanError("workspace root mount changed during scan")
        return Inventory(
            root_signature=safe_paths.stable_file_metadata(root_metadata),
            root_uid=root_metadata.st_uid,
            root_mount_id=root_mount_id,
            entries=tuple(sorted(records.items())),
        )
    finally:
        os.close(root_descriptor)


def scan_stably(bound_root_descriptor: int) -> Inventory:
    first = _scan_once(bound_root_descriptor)
    second = _scan_once(bound_root_descriptor)
    if first != second:
        raise WorkspaceScanError("workspace metadata changed between stability scans")
    return second


def public_top_level_entries() -> set[str]:
    return {PurePosixPath(path).parts[0] for path in public_surface.PUBLIC_ROOTS}


def _is_below(path: str, root: str) -> bool:
    return path.startswith(root + "/")


def _ancestors(path: str) -> list[str]:
    parts = PurePosixPath(path).parts
    return ["/".join(parts[:index]) for index in range(1, len(parts))]


def _transaction_control_root(path: str) -> str | None:
    parts = PurePosixPath(path).parts
    if parts and parts[0] in TRANSACTION_CONTROL_ROOT_NAMES:
        return parts[0]
    for index, component in enumerate(parts):
        if component.startswith(TRANSACTION_CONTROL_PREFIX):
            return "/".join(parts[: index + 1])
    return None


def _ordinary_platform_metadata(record: EntryRecord, root_uid: int) -> bool:
    return record.kind == "file" and record.nlink == 1 and record.uid == root_uid


def _residue_reason(
    path: str,
    record: EntryRecord,
    policy: Policy,
) -> tuple[str, str] | None:
    name = PurePosixPath(path).name
    if path in policy.disposable_subtrees or any(
        ancestor in policy.disposable_subtrees for ancestor in _ancestors(path)
    ):
        return (
            "declared-disposable-subtree",
            "the operator policy classifies this lifecycle-specific subtree as disposable",
        )
    if name.startswith(".mpa-tmp-"):
        return (
            "transaction-temporary-residue",
            "superseded transaction-temporary material has no retained workspace role",
        )
    if record.kind == "directory" and name in RESIDUE_DIRECTORY_NAMES:
        return ("generated-cache-directory", "generated cache or coverage directory")
    if record.kind == "file" and (
        name == ".coverage" or name.startswith(".coverage.")
    ):
        return ("generated-coverage-data", "generated coverage data file")
    if record.kind == "file" and (name.endswith(RESIDUE_FILE_SUFFIXES) or name.endswith("~")):
        return ("temporary-or-backup-residue", "temporary, bytecode, editor, or backup file")
    return None


def _collapse_candidates(
    candidates: dict[str, dict[str, str]],
    entries: dict[str, EntryRecord],
) -> dict[str, dict[str, str]]:
    collapsed: dict[str, dict[str, str]] = {}
    selected_directory_set: set[str] = set()
    for path in sorted(candidates, key=lambda item: (len(PurePosixPath(item).parts), item)):
        if any(parent in selected_directory_set for parent in _ancestors(path)):
            continue
        collapsed[path] = candidates[path]
        record = entries.get(path)
        if record is not None and record.kind == "directory":
            selected_directory_set.add(path)
    return collapsed


def _protect_candidate_containers(
    candidates: dict[str, dict[str, str]],
    protected_paths: set[str],
    review: list[dict[str, str]],
    *,
    reason_code: str,
    reason: str,
) -> None:
    protected_containers: set[str] = set()
    for path in protected_paths:
        protected_containers.add(path)
        protected_containers.update(_ancestors(path))
    for path in tuple(candidates):
        overlaps_protected_path = path in protected_containers or any(
            ancestor in protected_paths for ancestor in _ancestors(path)
        )
        if not overlaps_protected_path:
            continue
        del candidates[path]
        review.append(
            {
                "path": path,
                "reason_code": reason_code,
                "reason": reason,
            }
        )


def _review_priority(item: dict[str, str]) -> tuple[int, str, str]:
    code = item["reason_code"]
    if code in TRANSACTION_REVIEW_CODES:
        rank = 0
    elif code in ANOMALY_REVIEW_CODES:
        rank = 1
    else:
        rank = 2
    return rank, item["path"], code


def analyze_inventory(inventory: Inventory, policy: Policy) -> dict[str, Any]:
    entries = inventory.as_dict()
    public_top = public_top_level_entries()
    allowed_top = public_top | set(policy.allowed_top_level_entries) | {".git"}
    protected_top = public_top | {".git"}
    candidates: dict[str, dict[str, str]] = {}
    review: list[dict[str, str]] = []
    ordinary_platform_paths: set[str] = set()
    transaction_roots: set[str] = set()
    anomaly_paths: set[str] = set()

    for path, record in sorted(entries.items()):
        name = PurePosixPath(path).name
        is_platform_metadata = name in IGNORED_PLATFORM_METADATA_NAMES
        if is_platform_metadata and _ordinary_platform_metadata(
            record,
            inventory.root_uid,
        ):
            ordinary_platform_paths.add(path)
        transaction_root = _transaction_control_root(path)
        if transaction_root is not None:
            transaction_roots.add(transaction_root)
        if (
            "/" not in path
            and path not in allowed_top
            and not is_platform_metadata
            and transaction_root is None
        ):
            review.append(
                {
                    "path": path,
                    "reason_code": "unknown-top-level-entry",
                    "reason": "top-level entry is absent from the closed public and authoring classifications",
                }
            )
        if record.mount_id != inventory.root_mount_id:
            anomaly_paths.add(path)
            review.append(
                {
                    "path": path,
                    "reason_code": "nested-mount-boundary",
                    "reason": (
                        "entry is on a nested mount outside the bound workspace "
                        "mount; its contents were not traversed and it is never a "
                        "cleanup candidate"
                    ),
                }
            )
        if record.kind == "symlink":
            anomaly_paths.add(path)
            review.append(
                {
                    "path": path,
                    "reason_code": "symlink-entry",
                    "reason": "workspace hygiene does not follow or accept symbolic links",
                }
            )
        elif is_platform_metadata and record.kind == "directory":
            anomaly_paths.add(path)
            review.append(
                {
                    "path": path,
                    "reason_code": "platform-metadata-kind-mismatch",
                    "reason": "ignored platform metadata names are accepted only as ordinary regular files",
                }
            )
        elif record.kind == "special":
            anomaly_paths.add(path)
            review.append(
                {
                    "path": path,
                    "reason_code": "special-entry",
                    "reason": "workspace contains a socket, device, FIFO, or other special entry",
                }
            )
        elif record.kind == "file" and record.nlink != 1:
            anomaly_paths.add(path)
            review.append(
                {
                    "path": path,
                    "reason_code": "hardlinked-file",
                    "reason": "regular workspace files must have exactly one hard link",
                }
            )
        if record.uid != inventory.root_uid:
            anomaly_paths.add(path)
            review.append(
                {
                    "path": path,
                    "reason_code": "owner-drift",
                    "reason": (
                        "runner-visible entry owner differs from the "
                        "runner-visible bound workspace root owner"
                    ),
                }
            )

        if (
            path in ordinary_platform_paths
            or transaction_root is not None
            or path in anomaly_paths
        ):
            continue
        residue = _residue_reason(path, record, policy)
        if residue is not None:
            reason_code, reason = residue
            candidates[path] = {
                "path": path,
                "reason_code": reason_code,
                "reason": reason,
            }

    review.extend(
        {
            "path": path,
            "reason_code": "transaction-recovery-state",
            "reason": "transaction-control state requires the framework recovery route and is never a cleanup candidate",
        }
        for path in sorted(transaction_roots)
    )

    _protect_candidate_containers(
        candidates,
        transaction_roots,
        review,
        reason_code="transaction-protected-container",
        reason="this otherwise disposable path overlaps transaction-control state reserved for recovery",
    )
    _protect_candidate_containers(
        candidates,
        anomaly_paths,
        review,
        reason_code="anomaly-protected-container",
        reason="this otherwise disposable path overlaps a filesystem anomaly that requires review first",
    )

    for path in sorted(
        policy.allowed_empty_directories | policy.allowed_empty_subtree_roots
    ):
        record = entries.get(path)
        if record is not None and record.kind != "directory":
            review.append(
                {
                    "path": path,
                    "reason_code": "empty-policy-kind-mismatch",
                    "reason": "an empty-directory policy path exists but is not a directory",
                }
            )

    candidates = _collapse_candidates(candidates, entries)
    candidate_directories = {
        path
        for path in candidates
        if entries.get(path) is not None and entries[path].kind == "directory"
    }

    def removed_by_candidate(path: str) -> bool:
        if path in candidates:
            return True
        return any(parent in candidate_directories for parent in _ancestors(path))

    payload_ancestors: set[str] = {".git"}
    for path in transaction_roots:
        payload_ancestors.add(path)
        payload_ancestors.update(_ancestors(path))
    for path, record in entries.items():
        if (
            record.kind == "directory"
            or removed_by_candidate(path)
            or path in ordinary_platform_paths
        ):
            continue
        payload_ancestors.update(_ancestors(path))
    for path in (
        policy.allowed_empty_directories | policy.allowed_empty_subtree_roots
    ):
        if entries.get(path) is not None and entries[path].kind == "directory":
            payload_ancestors.add(path)
            payload_ancestors.update(_ancestors(path))

    fileless_directories = {
        path
        for path, record in entries.items()
        if record.kind == "directory"
        and path != ".git"
        and _transaction_control_root(path) is None
        and not removed_by_candidate(path)
        and path not in payload_ancestors
    }

    def allowed_fileless(path: str) -> bool:
        if path in policy.allowed_empty_directories:
            return True
        return path in policy.allowed_empty_subtree_roots or any(
            ancestor in policy.allowed_empty_subtree_roots
            for ancestor in _ancestors(path)
        )

    topmost_fileless = [
        path
        for path in sorted(fileless_directories)
        if not any(
            parent in fileless_directories and parent not in protected_top
            for parent in _ancestors(path)
        )
    ]
    for path in topmost_fileless:
        if allowed_fileless(path):
            continue
        top = PurePosixPath(path).parts[0]
        item = {
            "path": path,
            "reason_code": "unreferenced-fileless-subtree",
            "reason": "directory subtree has no retained file or declared empty-directory role after proposed residue cleanup",
        }
        if path == top and top in protected_top:
            review.append(item)
        else:
            candidates[path] = item

    _protect_candidate_containers(
        candidates,
        transaction_roots,
        review,
        reason_code="transaction-protected-container",
        reason="this otherwise disposable path overlaps transaction-control state reserved for recovery",
    )
    _protect_candidate_containers(
        candidates,
        anomaly_paths,
        review,
        reason_code="anomaly-protected-container",
        reason="this otherwise disposable path overlaps a filesystem anomaly that requires review first",
    )
    candidates = _collapse_candidates(candidates, entries)
    candidate_items = [candidates[path] for path in sorted(candidates)]
    review_by_key = {
        (item["path"], item["reason_code"]): item
        for item in review
    }
    review_items = sorted(review_by_key.values(), key=_review_priority)
    combined: list[tuple[str, dict[str, str]]] = [
        *(('review', item) for item in review_items),
        *(('candidate', item) for item in candidate_items),
    ]
    record_limit = MAX_REPORTED_ITEMS // 2
    selected = combined[:record_limit]
    omitted = len(combined) - len(selected)
    if omitted and len(selected) * 2 + 1 > MAX_REPORTED_ITEMS:
        selected = selected[:-1]
        omitted += 1
    candidate_items = [item for kind, item in selected if kind == "candidate"]
    review_items = [item for kind, item in selected if kind == "review"]
    errors = [
        (
            f"deletion candidate requires explicit approval: {item['path']} "
            f"[{item['reason_code']}]"
            if kind == "candidate"
            else f"workspace entry requires review: {item['path']} "
            f"[{item['reason_code']}]"
        )
        for kind, item in selected
    ]
    if omitted:
        errors.append(
            f"workspace hygiene omitted {omitted} additional diagnostic records "
            f"after the {MAX_REPORTED_ITEMS}-item global report bound"
        )

    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "checked_entry_count": len(entries),
        "stability_scan_count": 2,
        "deletion_candidates": candidate_items,
        "review_required": review_items,
        "diagnostics_truncated": bool(omitted),
        "omitted_diagnostic_count": omitted,
        "errors": errors,
        "warnings": [],
    }


def failure_report(error: str | list[str]) -> dict[str, Any]:
    supplied = [error] if isinstance(error, str) else list(error)
    selected = supplied[:MAX_REPORTED_ITEMS]
    omitted = len(supplied) - len(selected)
    if omitted:
        selected = selected[: MAX_REPORTED_ITEMS - 1]
        omitted = len(supplied) - len(selected)
        selected.append(
            f"workspace hygiene omitted {omitted} additional errors after the "
            f"{MAX_REPORTED_ITEMS}-item global report bound"
        )
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "checked_entry_count": 0,
        "stability_scan_count": 0,
        "deletion_candidates": [],
        "review_required": [],
        "diagnostics_truncated": bool(omitted),
        "omitted_diagnostic_count": omitted,
        "errors": selected,
        "warnings": [],
    }


def check_workspace(root: Path, policy_ref: str) -> dict[str, Any]:
    try:
        selected_root = validate_root(root)
    except (OSError, RuntimeError, ValueError) as exc:
        return failure_report(f"workspace root cannot be normalized safely: {exc}")
    try:
        with safe_paths.open_output_directory(
            selected_root,
            create_missing=False,
        ) as binding:
            binding.require_unchanged_chain(description="workspace hygiene")
            policy, first_policy_raw, policy_errors = load_policy(
                selected_root,
                binding.descriptor,
                policy_ref,
            )
            if policy is None or first_policy_raw is None:
                return failure_report(
                    policy_errors or ["workspace hygiene policy is invalid"]
                )
            inventory = scan_stably(binding.descriptor)
            _final_policy, final_policy_raw, final_policy_errors = load_policy(
                selected_root,
                binding.descriptor,
                policy_ref,
            )
            binding.require_unchanged_chain(description="workspace hygiene")
            if final_policy_errors or final_policy_raw != first_policy_raw:
                return failure_report(
                    "workspace hygiene policy changed or became invalid during the stable scan"
                )
            return analyze_inventory(inventory, policy)
    except (
        OSError,
        ValueError,
        WorkspaceScanError,
        safe_paths.OutputDirectoryBindingError,
    ) as exc:
        return failure_report(f"workspace root cannot be bound and scanned safely: {exc}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only physical hygiene audit for a framework-authoring workspace; "
            "the command reports exact candidates and never deletes or fixes paths."
        ),
        allow_abbrev=False,
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Framework-authoring workspace root (default: current directory).",
    )
    parser.add_argument(
        "--policy",
        required=True,
        help="Tracked repo-relative operator policy describing workspace classifications.",
    )
    parser.add_argument(
        "--format",
        choices=("json", "text"),
        default="json",
        help="Diagnostic output format (default: json).",
    )
    return parser


def render_text(report: dict[str, Any]) -> str:
    lines = [
        "authoring workspace hygiene: " + ("PASS" if not report["errors"] else "FAIL"),
        f"checked entries: {report['checked_entry_count']}",
        "files changed: none",
    ]
    candidates = report["deletion_candidates"]
    if candidates:
        lines.append("deletion candidates (approval required):")
        lines.extend(
            f"- {item['path']}: {item['reason']}" for item in candidates
        )
    review = report["review_required"]
    if review:
        lines.append("review required:")
        lines.extend(f"- {item['path']}: {item['reason']}" for item in review)
    if report["errors"]:
        lines.append("errors:")
        lines.extend(f"- {error}" for error in report["errors"])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = check_workspace(args.root, args.policy)
    if args.format == "json":
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        print(render_text(report))
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
