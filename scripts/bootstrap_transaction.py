#!/usr/bin/env python3

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
import errno
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
import sys
import unicodedata

import resource_cleanup
import safe_paths

try:
    import fcntl
except ImportError:  # Native Windows does not expose POSIX advisory file locks.
    fcntl = None


__all__ = (
    "BootstrapRecoveryStatus",
    "BootstrapTransactionError",
    "BootstrapWriteResult",
    "finalize_interrupted_transaction",
    "is_reserved_transaction_output",
    "rollback_interrupted_transaction",
    "transaction_capability_errors",
    "transaction_recovery_status",
    "transactional_write_outputs",
)

RECOVERY_JOURNAL_NAME = ".mpa-bootstrap-recovery.json"
TRANSACTION_LOCK_NAME = ".mpa-bootstrap.lock"
RECOVERY_JOURNAL_SCHEMA_VERSION = 5
_RECOVERY_JOURNAL_MAX_BYTES = 1024 * 1024
_RECOVERY_JOURNAL_MAX_OPERATIONS = 2048
_RECOVERY_JOURNAL_MAX_CREATED_DIRECTORIES = 4096
_RECOVERY_JOURNAL_MAX_RETIRED_DIRECTORIES = 4096
_RECOVERY_JOURNAL_MAX_BOUND_DIRECTORIES = 4096
_RECOVERY_JOURNAL_TEMP_NAME = ".mpa-bootstrap-recovery.tmp"
_RECOVERY_JOURNAL_PREVIOUS_NAME = ".mpa-bootstrap-recovery.previous"
_INITIALIZATION_SCAN_MAX_DIRECTORIES = 16384
_INITIALIZATION_SCAN_MAX_ENTRIES = 262144
_SPELLING_SCAN_MAX_ENTRIES = 262144
_RECOVERY_PHASES = frozenset({"preparing", "prepared", "applying", "verified"})
_RECOVERY_ACTIONS = frozenset({"write", "remove"})
_RECOVERY_JOURNAL_KEYS = frozenset(
    {
        "schema_version",
        "transaction_id",
        "phase",
        "applied_count",
        "bound_directories",
        "created_directories",
        "retired_directories",
        "operations",
    }
)
_RECOVERY_OPERATION_KEYS = frozenset(
    {
        "path",
        "action",
        "transaction_directory",
        "stage_name",
        "backup_name",
        "original",
        "candidate",
    }
)
_RECOVERY_EVIDENCE_KEYS = frozenset({"sha256", "mode", "size"})
_RECOVERY_CREATED_DIRECTORY_KEYS = frozenset({"path", "identity"})
_RECOVERY_RETIRED_DIRECTORY_KEYS = frozenset({"path", "identity"})
_RECOVERY_BOUND_DIRECTORY_KEYS = frozenset({"path", "identity"})

_TRANSACTION_DIR_FD_FUNCTIONS = (
    ("link", os.link),
    ("mkdir", os.mkdir),
    ("open", os.open),
    ("rename", os.rename),
    ("rmdir", os.rmdir),
    ("stat", os.stat),
    ("unlink", os.unlink),
)

_EXPECTED_DIRECTORY_IDENTITY_KEYS = frozenset(
    {"device", "inode", "file_type"}
)


def _required_transaction_flag(name: str) -> int:
    value = getattr(os, name, None)
    if not isinstance(value, int) or value == 0:
        raise ValueError(
            f"transactional bootstrap writes require platform flag {name}"
        )
    return value


def transaction_capability_errors() -> tuple[str, ...]:
    """Report unavailable transaction primitives without touching the filesystem."""

    errors: list[str] = []
    supports_dir_fd = getattr(os, "supports_dir_fd", set())
    missing = [
        name
        for name, function in _TRANSACTION_DIR_FD_FUNCTIONS
        if function not in supports_dir_fd
    ]
    if missing:
        errors.append(
            "descriptor-relative support is unavailable for: "
            + ", ".join(sorted(missing))
        )
    if os.stat not in getattr(os, "supports_follow_symlinks", set()):
        errors.append(
            "no-follow descriptor-relative stat support is unavailable"
        )
    if os.scandir not in getattr(os, "supports_fd", set()):
        errors.append(
            "descriptor-relative directory enumeration is unavailable"
        )
    if not hasattr(os, "geteuid"):
        errors.append(
            "effective-user ownership checks are unavailable"
        )
    if fcntl is None or not all(
        hasattr(fcntl, name)
        for name in ("flock", "LOCK_EX", "LOCK_SH", "LOCK_NB", "LOCK_UN")
    ):
        errors.append(
            "POSIX advisory flock support is unavailable"
        )
    for flag_name in ("O_DIRECTORY", "O_NOFOLLOW"):
        value = getattr(os, flag_name, None)
        if not isinstance(value, int) or value == 0:
            errors.append(f"platform flag {flag_name} is unavailable")
    for function_name in ("fchmod", "fsync", "fstat", "fwalk", "read", "write"):
        if not callable(getattr(os, function_name, None)):
            errors.append(f"os.{function_name} is unavailable")
    return tuple(errors)


def _require_transaction_support() -> None:
    errors = transaction_capability_errors()
    if errors:
        raise ValueError(
            "transactional bootstrap writes are unavailable: " + "; ".join(errors)
        )


def _transaction_directory_flags() -> int:
    return (
        os.O_RDONLY
        | _required_transaction_flag("O_DIRECTORY")
        | _required_transaction_flag("O_NOFOLLOW")
        | getattr(os, "O_CLOEXEC", 0)
    )


def _transaction_file_flags() -> int:
    return (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | _required_transaction_flag("O_NOFOLLOW")
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )


def _transaction_read_flags() -> int:
    return (
        os.O_RDONLY
        | _required_transaction_flag("O_NOFOLLOW")
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )


def _transaction_lock_flags(*, create: bool, exclusive_create: bool = False) -> int:
    return (
        os.O_RDWR
        | (os.O_CREAT if create else 0)
        | (os.O_EXCL if exclusive_create else 0)
        | _required_transaction_flag("O_NOFOLLOW")
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )


def _acquire_project_lock(
    root: _DirectoryBinding,
    *,
    exclusive: bool,
    create: bool = True,
) -> tuple[int, bool]:
    fcntl_module = fcntl
    if fcntl_module is None:
        raise ValueError(
            "transactional bootstrap writes require POSIX advisory flock support"
        )
    root_descriptor = _binding_descriptor(root)
    operation = fcntl_module.LOCK_EX if exclusive else fcntl_module.LOCK_SH
    try:
        fcntl_module.flock(root_descriptor, operation | fcntl_module.LOCK_NB)
    except OSError as exc:
        if exc.errno in {errno.EACCES, errno.EAGAIN}:
            raise BootstrapTransactionError(
                "another bootstrap transaction holds the project lock"
            ) from exc
        raise
    created = False
    try:
        if create:
            try:
                descriptor = os.open(
                    TRANSACTION_LOCK_NAME,
                    _transaction_lock_flags(create=True, exclusive_create=True),
                    0o600,
                    dir_fd=_binding_descriptor(root),
                )
                created = True
            except FileExistsError:
                descriptor = os.open(
                    TRANSACTION_LOCK_NAME,
                    _transaction_lock_flags(create=False),
                    dir_fd=_binding_descriptor(root),
                )
        else:
            descriptor = os.open(
                TRANSACTION_LOCK_NAME,
                _transaction_lock_flags(create=False),
                dir_fd=_binding_descriptor(root),
            )
    except BaseException as exc:
        resource_cleanup.cleanup_actions(
            (
                (
                    "bootstrap project root advisory lock",
                    lambda: fcntl_module.flock(
                        root_descriptor,
                        fcntl_module.LOCK_UN,
                    ),
                ),
            ),
            primary=exc,
        )
        raise
    try:
        if created:
            os.fchmod(descriptor, 0o600)
            os.fsync(descriptor)
            os.fsync(root_descriptor)
        metadata = os.fstat(descriptor)
        _require_owned_regular_output(
            metadata,
            description="bootstrap project transaction lock",
            require_single_link=True,
        )
        if stat.S_IMODE(metadata.st_mode) & 0o077:
            raise ValueError(
                "bootstrap project transaction lock must not be group- or world-accessible"
            )
        try:
            fcntl_module.flock(
                descriptor,
                operation | fcntl_module.LOCK_NB,
            )
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN}:
                raise BootstrapTransactionError(
                    "another bootstrap transaction holds the project lock"
                ) from exc
            raise
        _verify_project_lock(root, descriptor)
        return descriptor, created
    except BaseException as exc:
        cleanup_actions: list[tuple[str, Callable[[], object]]] = []
        if created:

            def retire_created_lock() -> None:
                current = _lstat_at(root, TRANSACTION_LOCK_NAME)
                if current is None:
                    return
                opened = os.fstat(descriptor)
                if (
                    _inode_payload_identity(current)
                    == _inode_payload_identity(opened)
                ):
                    os.unlink(
                        TRANSACTION_LOCK_NAME,
                        dir_fd=_binding_descriptor(root),
                    )
                    os.fsync(_binding_descriptor(root))
            cleanup_actions.append(
                ("new bootstrap project transaction lock", retire_created_lock)
            )
        cleanup_actions.extend(
            (
                (
                    "bootstrap project transaction lock advisory lock",
                    lambda: fcntl_module.flock(
                        descriptor,
                        fcntl_module.LOCK_UN,
                    ),
                ),
                (
                    "bootstrap project transaction lock descriptor",
                    lambda: os.close(descriptor),
                ),
                (
                    "bootstrap project root advisory lock",
                    lambda: fcntl_module.flock(
                        root_descriptor,
                        fcntl_module.LOCK_UN,
                    ),
                ),
            )
        )
        resource_cleanup.cleanup_actions(cleanup_actions, primary=exc)
        raise


def _release_project_lock(
    root: _DirectoryBinding | None,
    descriptor: int | None,
) -> None:
    fcntl_module = fcntl
    if fcntl_module is None:
        error = ValueError(
            "transactional bootstrap writes require POSIX advisory flock support"
        )
        if descriptor is not None:
            resource_cleanup.cleanup_actions(
                (
                    (
                        "bootstrap project transaction lock descriptor",
                        lambda: os.close(descriptor),
                    ),
                ),
                primary=error,
            )
        raise error
    actions: list[tuple[str, Callable[[], object]]] = []
    if descriptor is not None:
        actions.extend(
            (
                (
                    "bootstrap project transaction lock advisory lock",
                    lambda: fcntl_module.flock(
                        descriptor,
                        fcntl_module.LOCK_UN,
                    ),
                ),
                (
                    "bootstrap project transaction lock descriptor",
                    lambda: os.close(descriptor),
                ),
            )
        )
    if root is not None and root.descriptor is not None:
        actions.append(
            (
                "bootstrap project root advisory lock",
                lambda: fcntl_module.flock(
                    _binding_descriptor(root),
                    fcntl_module.LOCK_UN,
                ),
            )
        )
    resource_cleanup.cleanup_actions(actions)


def _verify_project_lock(root: _DirectoryBinding, descriptor: int) -> None:
    opened = os.fstat(descriptor)
    current = _lstat_at(root, TRANSACTION_LOCK_NAME)
    if current is None:
        raise BootstrapTransactionError(
            "bootstrap project transaction lock was removed or replaced"
        )
    _require_owned_regular_output(
        opened,
        description="bootstrap project transaction lock",
        require_single_link=True,
    )
    _require_owned_regular_output(
        current,
        description="bootstrap project transaction lock",
        require_single_link=True,
    )
    if (
        stat.S_IMODE(opened.st_mode) & 0o077
        or stat.S_IMODE(current.st_mode) & 0o077
    ):
        raise BootstrapTransactionError(
            "bootstrap project transaction lock became group- or world-accessible"
        )
    if _inode_payload_identity(current) != _inode_payload_identity(opened):
        raise BootstrapTransactionError(
            "bootstrap project transaction lock was removed or replaced"
        )


def _remove_project_lock(root: _DirectoryBinding, descriptor: int) -> None:
    """Unlink the exact held marker while the stable root-directory lock remains."""

    _verify_project_lock(root, descriptor)
    if _lstat_at(root, RECOVERY_JOURNAL_NAME) is not None:
        raise BootstrapTransactionError(
            "bootstrap project transaction lock cannot be removed while the "
            "canonical recovery journal exists"
        )
    if _journal_temporary_metadata(root) is not None:
        raise BootstrapTransactionError(
            "bootstrap project transaction lock cannot be removed while a "
            "recovery journal temporary exists"
        )
    if _journal_previous_metadata(root) is not None:
        raise BootstrapTransactionError(
            "bootstrap project transaction lock cannot be removed while a "
            "previous recovery journal is retained"
        )
    transaction_artifact_errors = _initialization_transaction_artifact_errors(root)
    if transaction_artifact_errors:
        raise BootstrapTransactionError("; ".join(transaction_artifact_errors))
    os.unlink(TRANSACTION_LOCK_NAME, dir_fd=_binding_descriptor(root))
    os.fsync(_binding_descriptor(root))


def _project_lock_transaction_id(
    root: _DirectoryBinding,
    descriptor: int,
) -> str:
    """Derive the approval identity from the exact installed lock inode.

    The lock entry itself is the first durable transaction mutation. Deriving
    the ID from its bound inode avoids an unidentifiable interval between lock
    creation and a later payload write: a hard exit can leave an empty lock,
    but inspection can still recover the same exact 32-hex identity. The root
    identity prevents an ID observed in one project from authorizing another.
    """

    _verify_project_lock(root, descriptor)
    lock_metadata = os.fstat(descriptor)
    identity = {
        "domain": "mpa-bootstrap-project-lock-v1",
        "project_root": list(
            _directory_identity(os.fstat(_binding_descriptor(root)))
        ),
        "lock": list(_inode_payload_identity(lock_metadata)),
        "lock_ctime_ns": lock_metadata.st_ctime_ns,
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()[:32]


def _recovery_journal_identity_errors(
    root: _DirectoryBinding,
    lock_descriptor: int,
    payload: Mapping[str, object],
) -> list[str]:
    """Bind canonical journal identity to the exact selected root and lock."""

    expected = _project_lock_transaction_id(root, lock_descriptor)
    if payload.get("transaction_id") == expected:
        return []
    return [
        "bootstrap recovery journal transaction ID does not match the exact "
        "project transaction lock identity"
    ]


def _directory_identity(metadata: os.stat_result) -> tuple[int, ...]:
    return _inode_object_identity(metadata)


def _directory_node_identity(metadata: os.stat_result) -> tuple[int, int, int]:
    """Return the path-stable directory identity used by reviewed plans."""

    return (
        metadata.st_dev,
        metadata.st_ino,
        stat.S_IFMT(metadata.st_mode),
    )


def _validated_expected_directory_identity(
    value: Mapping[str, object] | None,
    *,
    label: str,
    allow_absent: bool,
) -> tuple[int, int, int] | None:
    """Validate one closed public directory-identity record."""

    if value is None:
        if allow_absent:
            return None
        raise ValueError(f"{label} must bind an existing directory identity")
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a directory identity object")
    if set(value) != _EXPECTED_DIRECTORY_IDENTITY_KEYS:
        raise ValueError(
            f"{label} keys must be exactly: "
            + ", ".join(sorted(_EXPECTED_DIRECTORY_IDENTITY_KEYS))
        )
    device, inode, file_type = (
        value["device"], value["inode"], value["file_type"]
    )
    if (
        type(device) is not int
        or type(inode) is not int
        or type(file_type) is not int
        or min(device, inode, file_type) < 0
    ):
        raise ValueError(
            f"{label} must contain non-negative integer identity fields"
        )
    identity = (device, inode, file_type)
    if identity[2] != stat.S_IFDIR:
        raise ValueError(f"{label} must identify a directory")
    return identity


def _inode_object_identity(metadata: os.stat_result) -> tuple[int, ...]:
    """Identity fields that remain stable while one inode's payload changes."""

    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_uid,
        metadata.st_gid,
    )


def _inode_payload_identity(metadata: os.stat_result) -> tuple[int, ...]:
    """Identity that remains stable while a staged file is linked and unlinked."""

    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_uid,
        metadata.st_gid,
        metadata.st_size,
        metadata.st_mtime_ns,
    )


def _relative_output_parts(name: str) -> tuple[str, ...]:
    parts = tuple(name.split("/"))
    if (
        not name
        or "\\" in name
        or name.startswith("/")
        or any(part in {"", ".", ".."} for part in parts)
        or any(safe_paths.PATH_CONTROL_RE.search(part) for part in parts)
    ):
        raise ValueError(f"bootstrap output must be a normalized relative path: {name!r}")
    return parts


def _is_reserved_transaction_path(parts: tuple[str, ...]) -> bool:
    return bool(parts) and (
        parts[0]
        in {
            TRANSACTION_LOCK_NAME,
            RECOVERY_JOURNAL_NAME,
            _RECOVERY_JOURNAL_TEMP_NAME,
            _RECOVERY_JOURNAL_PREVIOUS_NAME,
        }
        or any(
            part.startswith(".mpa-bootstrap-transaction-")
            or part.startswith(".mpa-bootstrap-recovery.")
            for part in parts
        )
    )


def is_reserved_transaction_output(name: str) -> bool:
    """Return whether a normalized output path collides with transaction controls."""

    return _is_reserved_transaction_path(_relative_output_parts(name))


def _initialization_transaction_artifact_errors(
    root: _DirectoryBinding,
) -> list[str]:
    """Boundedly prove that initialization never reached private staging.

    A canonical journal is installed before any project parent or transaction
    directory is created. Therefore a lock-only or first-journal-temporary
    state is cleanup-safe only while no private transaction directory exists
    anywhere below the bound project root. The scan never follows symlinks and
    fails closed on traversal errors or its explicit work limits.
    """

    directory_count = 0
    entry_count = 0
    def record_traversal_error(exc: OSError) -> None:
        raise exc

    try:
        for directory, directories, files, _descriptor in os.fwalk(
            ".",
            topdown=True,
            onerror=record_traversal_error,
            follow_symlinks=False,
            dir_fd=_binding_descriptor(root),
        ):
            directory_count += 1
            entry_count += len(directories) + len(files)
            if directory_count > _INITIALIZATION_SCAN_MAX_DIRECTORIES:
                return [
                    "bootstrap initialization recovery could not prove the absence "
                    "of transaction directories within its directory limit"
                ]
            if entry_count > _INITIALIZATION_SCAN_MAX_ENTRIES:
                return [
                    "bootstrap initialization recovery could not prove the absence "
                    "of transaction directories within its entry limit"
                ]
            prefix = "" if directory == "." else directory.removeprefix("./") + "/"
            matching_directories = [
                name
                for name in directories
                if name.startswith(".mpa-bootstrap-transaction-")
            ]
            matching_files = [
                name
                for name in files
                if name.startswith(".mpa-bootstrap-transaction-")
            ]
            artifacts = [
                *(prefix + name for name in matching_directories),
                *(prefix + name for name in matching_files),
            ]
            if artifacts:
                preview = ", ".join(sorted(artifacts[:8]))
                remainder = len(artifacts) - 8
                if remainder > 0:
                    preview += f", and {remainder} more"
                return [
                    "bootstrap initialization recovery found transaction artifacts "
                    f"without a canonical journal: {preview}"
                ]
    except OSError as exc:
        return [
            "bootstrap initialization recovery could not inspect the project tree: "
            + str(exc)
        ]
    return []


def _retirement_expected_children(
    retired_parts: set[tuple[str, ...]],
    removal_parts: list[tuple[str, ...]],
) -> tuple[dict[tuple[str, ...], set[str]], list[str]]:
    """Describe the exact directory forest required for bounded retirement.

    Every intervening directory between a retired ancestor and a removed file
    must itself be named for retirement. This makes cleanup non-recursive and
    ensures an unlisted sibling or directory can never be consumed implicitly.
    """

    expected: dict[tuple[str, ...], set[str]] = {
        parts: set() for parts in retired_parts
    }
    errors: list[str] = []
    missing_intervening: set[tuple[str, ...]] = set()
    for retired in sorted(retired_parts, key=lambda value: (len(value), value)):
        affected = [
            removal
            for removal in removal_parts
            if len(retired) < len(removal)
            and removal[: len(retired)] == retired
        ]
        if not affected:
            errors.append(
                "retired bootstrap directory is not a strict ancestor of a "
                f"planned removal: {'/'.join(retired)}"
            )
            continue
        for removal in affected:
            child_parts = removal[: len(retired) + 1]
            if len(removal) > len(retired) + 1 and child_parts not in retired_parts:
                missing_intervening.add(child_parts)
                continue
            expected[retired].add(child_parts[-1])
    errors.extend(
        "retired bootstrap topology must name every intervening directory: "
        + "/".join(parts)
        for parts in sorted(missing_intervening)
    )
    return expected, errors


@dataclass
class _DirectoryBinding:
    descriptor: int | None
    parent: _DirectoryBinding | None
    entry_name: str | None
    identity: tuple[int, ...]
    label: str
    created: bool = False
    active: bool = True
    project_relative_parts: tuple[str, ...] | None = None


@dataclass(frozen=True)
class _AbsentDirectoryBinding:
    """One approved-absent directory edge under retained parent descriptors."""

    parent: _DirectoryBinding
    entry_name: str
    relative_path: str


@dataclass
class _TransactionDirectory:
    parent: _DirectoryBinding
    binding: _DirectoryBinding
    relative_path: str


@dataclass
class _OutputTransactionRecord:
    name: str
    parent: _DirectoryBinding
    target_name: str
    action: str
    content: bytes | None
    target_mode: int | None
    original_metadata: os.stat_result | None
    original_evidence: dict[str, object] | None = None
    candidate_evidence: dict[str, object] | None = None
    transaction_directory: _TransactionDirectory | None = None
    stage_name: str | None = None
    staged_identity: tuple[int, ...] | None = None
    backup_name: str | None = None
    backup_identity: tuple[int, ...] | None = None
    observed_install_identity: tuple[int, ...] | None = None
    installed_signature: tuple[int, ...] | None = None


@dataclass(frozen=True)
class _PlannedOperation:
    """Mutation-free operation plan installed in the preparing journal."""

    name: str
    parts: tuple[str, ...]
    action: str
    content: bytes | None
    target_mode: int | None
    original_metadata: os.stat_result | None
    original_evidence: dict[str, object] | None
    candidate_evidence: dict[str, object] | None
    transaction_directory_name: str


@dataclass(frozen=True)
class BootstrapWriteResult:
    written: list[str]
    cleanup_warnings: list[str]
    removed: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class BootstrapRecoveryStatus:
    """Bounded transaction state for callers.

    ``active`` means another process currently owns the lock: wait or retry and
    never invoke recovery. ``recovery-required`` permits rollback only;
    ``verified`` permits finalize only; ``invalid`` requires manual inspection.
    ``clean`` has no lock, journal, or transaction-directory control state.
    """

    state: str
    transaction_id: str | None
    phase: str | None
    operation_paths: tuple[str, ...]
    can_rollback: bool
    can_finalize: bool
    errors: tuple[str, ...]


@dataclass
class _RecoveryOperationView:
    operation: dict[str, object]
    parent: _DirectoryBinding | None
    transaction_directory: _TransactionDirectory | None
    target_evidence: dict[str, object] | None
    stage_evidence: dict[str, object] | None
    backup_evidence: dict[str, object] | None
    target_quarantine_evidence: dict[str, object] | None
    stage_quarantine_evidence: dict[str, object] | None
    backup_quarantine_evidence: dict[str, object] | None


class BootstrapTransactionError(ValueError):
    """A bootstrap write failed before commit; rollback was attempted."""


def _binding_descriptor(binding: _DirectoryBinding) -> int:
    if binding.descriptor is None:
        raise BootstrapTransactionError(
            f"directory descriptor closed before transaction completed: {binding.label}"
        )
    return binding.descriptor


def _require_owned_directory(
    metadata: os.stat_result,
    *,
    description: str,
) -> None:
    if not stat.S_ISDIR(metadata.st_mode):
        raise ValueError(f"{description} must be a directory")
    if metadata.st_uid != os.geteuid():
        raise ValueError(
            f"{description} must be owned by the bootstrap user before files are installed"
        )


def _validated_create_mode(value: int | None, *, kind: str) -> int | None:
    """Validate an optional exact mode for newly created transaction outputs."""

    if value is None:
        return None
    if type(value) is not int or not 0 <= value <= 0o777:
        raise ValueError(f"bootstrap {kind} create mode must be an integer from 0 through 511")
    if value & 0o022:
        raise ValueError(
            f"bootstrap {kind} create mode must not grant group or world write access"
        )
    if kind == "file":
        if value & 0o600 != 0o600:
            raise ValueError(
                "bootstrap file create mode must grant the owner read and write access"
            )
        if value & 0o111:
            raise ValueError(
                "bootstrap file create mode must not grant execute access"
            )
    elif kind == "directory":
        if value & 0o700 != 0o700:
            raise ValueError(
                "bootstrap directory create mode must grant the owner read, "
                "write, and execute access"
            )
    else:  # Internal callers must select one of the two public mode classes.
        raise ValueError(f"unsupported bootstrap create mode kind: {kind}")
    return value


def _validated_mode_map(
    value: Mapping[str, int | None] | None,
    *,
    expected_keys: set[str],
    label: str,
    allow_absence: bool,
) -> dict[str, int | None] | None:
    """Validate one optional, closed exact-mode companion map."""

    if value is None:
        return None
    modes = dict(value)
    if set(modes) != expected_keys:
        missing = sorted(expected_keys - set(modes))
        extra = sorted(set(modes) - expected_keys)
        details: list[str] = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if extra:
            details.append("unexpected " + ", ".join(extra))
        raise ValueError(
            f"{label} must exactly cover its companion path set"
            + (": " + "; ".join(details) if details else "")
        )
    for path, mode in modes.items():
        if allow_absence and mode is None:
            continue
        if type(mode) is not int or not 0 <= mode <= 0o777:
            raise ValueError(
                f"{label} value must be an integer from 0 through 511"
                + (" or null for an absent preimage" if allow_absence else "")
                + f": {path}"
            )
    return modes


def _validated_max_bytes_map(
    value: Mapping[str, int | None] | None,
    *,
    expected_keys: set[str],
    label: str,
) -> dict[str, int | None] | None:
    """Validate an exact assertion-path map of optional positive byte bounds."""

    if value is None:
        return None
    limits = dict(value)
    if set(limits) != expected_keys:
        missing = sorted(expected_keys - set(limits))
        extra = sorted(set(limits) - expected_keys)
        details: list[str] = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if extra:
            details.append("unexpected " + ", ".join(extra))
        raise ValueError(
            f"{label} must exactly cover its assertion path set"
            + (": " + "; ".join(details) if details else "")
        )
    for path, limit in limits.items():
        if limit is not None and (type(limit) is not int or limit <= 0):
            raise ValueError(
                f"{label} value must be a positive integer or null: {path}"
            )
    return limits


def _directory_entry_spelling_identity(value: str) -> str:
    """Return the portable collision identity for one directory entry."""

    return unicodedata.normalize("NFC", value).casefold()


def _require_exact_directory_entry_spelling(
    parent: _DirectoryBinding,
    expected: str,
    *,
    description: str,
) -> None:
    """Reject case or Unicode aliases through the retained parent descriptor."""

    expected_identity = _directory_entry_spelling_identity(expected)
    aliases: list[str] = []
    with os.scandir(_binding_descriptor(parent)) as entries:
        for entry_count, entry in enumerate(entries, start=1):
            if entry_count > _SPELLING_SCAN_MAX_ENTRIES:
                raise BootstrapTransactionError(
                    f"{description} exceeds its directory spelling entry limit"
                )
            if _directory_entry_spelling_identity(entry.name) == expected_identity:
                aliases.append(entry.name)
    if expected not in aliases:
        if aliases:
            raise BootstrapTransactionError(
                f"{description} must use exact path spelling {expected!r}; "
                f"found {sorted(aliases)!r}"
            )
        return
    if len(aliases) > 1:
        raise BootstrapTransactionError(
            f"{description} has ambiguous path spellings for {expected!r}: "
            f"{sorted(aliases)!r}"
        )


def _open_bound_directory(
    parent: _DirectoryBinding,
    name: str,
    *,
    label: str,
    create: bool,
    require_owner: bool,
    created_bindings: list[_DirectoryBinding],
    all_bindings: list[_DirectoryBinding],
    create_mode: int | None = None,
    require_absent: bool = False,
) -> _DirectoryBinding:
    parent_descriptor = _binding_descriptor(parent)
    created = False
    if require_absent and not create:
        raise ValueError("require_absent directory opening requires create=True")
    if require_absent:
        try:
            os.mkdir(
                name,
                mode=0o755 if create_mode is None else create_mode,
                dir_fd=parent_descriptor,
            )
        except FileExistsError as exc:
            raise BootstrapTransactionError(
                f"approved-absent directory appeared before creation: {label}"
            ) from exc
        created = True
        descriptor: int | None = None
    else:
        try:
            descriptor = os.open(
                name,
                _transaction_directory_flags(),
                dir_fd=parent_descriptor,
            )
        except FileNotFoundError:
            if not create:
                raise
            os.mkdir(
                name,
                mode=0o755 if create_mode is None else create_mode,
                dir_fd=parent_descriptor,
            )
            created = True
            descriptor = None
    if created:
        try:
            descriptor = os.open(
                name,
                _transaction_directory_flags(),
                dir_fd=parent_descriptor,
            )
        except BaseException as exc:
            resource_cleanup.cleanup_actions(
                (
                    (
                        f"new bootstrap directory {label}",
                        lambda: os.rmdir(name, dir_fd=parent_descriptor),
                    ),
                    (
                        f"new bootstrap directory parent {label}",
                        lambda: os.fsync(parent_descriptor),
                    ),
                ),
                primary=exc,
            )
            raise
    if descriptor is None:
        raise AssertionError("bound directory opening did not produce a descriptor")
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISDIR(metadata.st_mode):
            raise ValueError(f"{label} must be a directory")
        if require_owner:
            _require_owned_directory(metadata, description=label)
        if created and create_mode is not None:
            os.fchmod(descriptor, create_mode)
            metadata = os.fstat(descriptor)
            if stat.S_IMODE(metadata.st_mode) != create_mode:
                raise BootstrapTransactionError(
                    f"new bootstrap directory has the wrong mode: {label}"
                )
        if created:
            os.fsync(descriptor)
            os.fsync(parent_descriptor)
    except BaseException as exc:
        cleanup_actions: list[tuple[str, Callable[[], object]]] = [
            (
                f"new bootstrap directory descriptor {label}",
                lambda: os.close(descriptor),
            )
        ]
        if created:
            cleanup_actions.extend(
                (
                    (
                        f"new bootstrap directory {label}",
                        lambda: os.rmdir(name, dir_fd=parent_descriptor),
                    ),
                    (
                        f"new bootstrap directory parent {label}",
                        lambda: os.fsync(parent_descriptor),
                    ),
                )
            )
        resource_cleanup.cleanup_actions(cleanup_actions, primary=exc)
        raise
    binding = _DirectoryBinding(
        descriptor=descriptor,
        parent=parent,
        entry_name=name,
        identity=_directory_identity(metadata),
        label=label,
        created=created,
        project_relative_parts=(
            (*parent.project_relative_parts, name)
            if parent.project_relative_parts is not None
            else None
        ),
    )
    all_bindings.append(binding)
    if created:
        created_bindings.append(binding)
    return binding


def _open_project_root_transaction(
    project_root: Path,
    *,
    all_bindings: list[_DirectoryBinding],
) -> _DirectoryBinding:
    absolute = Path(os.path.abspath(os.fspath(project_root.expanduser())))
    for alias, physical in safe_paths.ALLOWED_SYSTEM_SYMLINK_TARGETS.items():
        try:
            relative = absolute.relative_to(alias)
        except ValueError:
            continue
        if safe_paths.is_allowed_system_symlink(alias):
            absolute = physical / relative
            break
    if absolute.anchor != "/" or len(absolute.parts) < 2:
        raise ValueError("target project root must be a normalized absolute directory below /")
    if any(part in {"", ".", ".."} for part in absolute.parts[1:]):
        raise ValueError(f"target project root contains an unsafe component: {absolute}")
    root_descriptor = os.open("/", _transaction_directory_flags())
    try:
        filesystem_root = _DirectoryBinding(
            descriptor=root_descriptor,
            parent=None,
            entry_name=None,
            identity=_directory_identity(os.fstat(root_descriptor)),
            label="filesystem root",
        )
    except BaseException as exc:
        resource_cleanup.cleanup_actions(
            (("filesystem root descriptor", lambda: os.close(root_descriptor)),),
            primary=exc,
        )
        raise
    all_bindings.append(filesystem_root)
    current = filesystem_root
    root_created_bindings: list[_DirectoryBinding] = []
    for index, part in enumerate(absolute.parts[1:]):
        final = index == len(absolute.parts[1:]) - 1
        try:
            current = _open_bound_directory(
                current,
                part,
                label=("target project root" if final else f"target project ancestor {part}"),
                create=False,
                require_owner=final,
                created_bindings=root_created_bindings,
                all_bindings=all_bindings,
            )
        except FileNotFoundError:
            raise FileNotFoundError(f"target project root does not exist: {absolute}") from None
    _require_owned_directory(
        os.fstat(_binding_descriptor(current)),
        description="target project root",
    )
    current.project_relative_parts = ()
    return current


def _validated_expected_directory_identities(
    value: Mapping[str, Mapping[str, object] | None] | None,
) -> dict[tuple[str, ...], tuple[int, int, int] | None]:
    """Validate an exact project-relative directory-identity map."""

    if value is None:
        return {}
    if not value:
        raise ValueError(
            "expected_directory_identities must bind a non-empty exact "
            "project-relative directory chain"
        )
    identities: dict[tuple[str, ...], tuple[int, int, int] | None] = {}
    for raw_path, raw_identity in value.items():
        if not isinstance(raw_path, str):
            raise ValueError(
                "expected_directory_identities paths must be strings"
            )
        if raw_path == ".":
            parts: tuple[str, ...] = ()
        else:
            parts = _relative_output_parts(raw_path)
            if _is_reserved_transaction_path(parts):
                raise ValueError(
                    "expected directory identity uses a reserved transaction "
                    f"path: {raw_path}"
                )
        identities[parts] = _validated_expected_directory_identity(
            raw_identity,
            label=f"expected directory identity {raw_path}",
            allow_absent=True,
        )
    ordered_parts = sorted(identities, key=lambda item: (len(item), item))
    for index, parts in enumerate(ordered_parts):
        if not parts and identities[parts] is None:
            raise ValueError(
                "expected directory identity . must bind the existing project root"
            )
        if len(parts) > 1 and parts[:-1] not in identities:
            raise ValueError(
                "expected directory identities must bind every project-relative "
                f"parent edge before its child: {'/'.join(parts)}"
            )
        if index:
            previous = ordered_parts[index - 1]
            if len(parts) != len(previous) + 1 or parts[:-1] != previous:
                raise ValueError(
                    "expected directory identities must describe one exact "
                    "project-relative prefix chain"
                )
        for depth in range(1, len(parts)):
            ancestor = parts[:depth]
            if identities.get(ancestor) is None:
                raise ValueError(
                    "expected directory identities must stop at the first approved "
                    f"absence: {'/'.join(ancestor)}"
                )
    return identities


def _bind_expected_directories(
    root: _DirectoryBinding,
    expected: Mapping[tuple[str, ...], tuple[int, int, int] | None],
    *,
    all_bindings: list[_DirectoryBinding],
) -> tuple[
    dict[tuple[str, ...], _DirectoryBinding],
    list[_AbsentDirectoryBinding],
]:
    """Bind existing reviewed directories and exact approved absences."""

    directory_bindings: dict[tuple[str, ...], _DirectoryBinding] = {(): root}
    absent_bindings: list[_AbsentDirectoryBinding] = []
    created_bindings: list[_DirectoryBinding] = []
    for parts, expected_identity in sorted(
        expected.items(),
        key=lambda item: (len(item[0]), item[0]),
    ):
        if not parts:
            actual_identity = _directory_node_identity(
                os.fstat(_binding_descriptor(root))
            )
            if expected_identity is None:
                raise BootstrapTransactionError(
                    "approved contract root was expected to be absent but is the "
                    "project root"
                )
            if actual_identity != expected_identity:
                raise BootstrapTransactionError(
                    "approved project-relative directory identity changed before "
                    "the transaction opened"
                )
            continue
        parent = root
        missing = False
        for depth, component in enumerate(parts, start=1):
            key = parts[:depth]
            existing = directory_bindings.get(key)
            if existing is not None:
                parent = existing
                continue
            try:
                opened = _open_bound_directory(
                    parent,
                    component,
                    label=(
                        "approved project-relative directory " + "/".join(key)
                    ),
                    create=False,
                    require_owner=True,
                    created_bindings=created_bindings,
                    all_bindings=all_bindings,
                )
            except FileNotFoundError:
                if expected_identity is not None:
                    raise BootstrapTransactionError(
                        "approved project-relative directory disappeared before "
                        f"the transaction opened: {'/'.join(parts)}"
                    ) from None
                absent_bindings.append(
                    _AbsentDirectoryBinding(
                        parent=parent,
                        entry_name=component,
                        relative_path="/".join(parts),
                    )
                )
                missing = True
                break
            directory_bindings[key] = opened
            parent = opened
        if missing:
            continue
        actual_identity = _directory_node_identity(
            os.fstat(_binding_descriptor(parent))
        )
        if expected_identity is None:
            raise BootstrapTransactionError(
                "approved-absent project-relative directory appeared before the "
                f"transaction opened: {'/'.join(parts)}"
            )
        if actual_identity != expected_identity:
            raise BootstrapTransactionError(
                "approved project-relative directory identity changed before the "
                f"transaction opened: {'/'.join(parts)}"
            )
    if created_bindings:
        raise AssertionError("read-only expected-directory binding created a directory")
    return directory_bindings, absent_bindings


def _verify_absent_directory_bindings(
    bindings: list[_AbsentDirectoryBinding],
) -> None:
    """Require every approved-absent edge to remain absent."""

    for binding in bindings:
        try:
            os.stat(
                binding.entry_name,
                dir_fd=_binding_descriptor(binding.parent),
                follow_symlinks=False,
            )
        except FileNotFoundError:
            continue
        raise BootstrapTransactionError(
            "approved-absent project-relative directory appeared before "
            f"transaction mutation: {binding.relative_path}"
        )


def _verify_bound_directories(bindings: list[_DirectoryBinding]) -> None:
    for binding in bindings:
        if not binding.active:
            continue
        descriptor = _binding_descriptor(binding)
        if _directory_identity(os.fstat(descriptor)) != binding.identity:
            raise BootstrapTransactionError(
                f"bound output directory changed during bootstrap transaction: {binding.label}"
            )
        if binding.parent is None:
            continue
        parent_descriptor = _binding_descriptor(binding.parent)
        if binding.entry_name is None:
            raise BootstrapTransactionError(
                f"bound output directory lacks an entry name: {binding.label}"
            )
        try:
            reopened = os.open(
                binding.entry_name,
                _transaction_directory_flags(),
                dir_fd=parent_descriptor,
            )
        except OSError as exc:
            raise BootstrapTransactionError(
                f"bound output directory was removed or replaced during bootstrap transaction: {binding.label}"
            ) from exc
        try:
            if _directory_identity(os.fstat(reopened)) != binding.identity:
                raise BootstrapTransactionError(
                    f"bound output directory was replaced during bootstrap transaction: {binding.label}"
                )
        finally:
            os.close(reopened)


def _verify_transaction_context(
    root: _DirectoryBinding,
    lock_descriptor: int,
    bindings: list[_DirectoryBinding],
) -> None:
    """Require every retained directory edge and the exact lock together."""

    _verify_bound_directories(bindings)
    _verify_project_lock(root, lock_descriptor)


def _binding_entry_matches(binding: _DirectoryBinding) -> bool:
    if binding.parent is None:
        return _directory_identity(
            os.fstat(_binding_descriptor(binding))
        ) == binding.identity
    if binding.entry_name is None:
        return False
    try:
        reopened = os.open(
            binding.entry_name,
            _transaction_directory_flags(),
            dir_fd=_binding_descriptor(binding.parent),
        )
    except OSError:
        return False
    try:
        return _directory_identity(os.fstat(reopened)) == binding.identity
    finally:
        os.close(reopened)


def _lstat_at(directory: _DirectoryBinding, name: str) -> os.stat_result | None:
    try:
        return os.stat(
            name,
            dir_fd=_binding_descriptor(directory),
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return None


def _require_owned_regular_output(
    metadata: os.stat_result,
    *,
    description: str,
    require_single_link: bool,
) -> None:
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"{description} must be a regular file")
    if metadata.st_uid != os.geteuid():
        raise ValueError(f"{description} must be owned by the bootstrap user")
    if require_single_link and metadata.st_nlink != 1:
        raise ValueError(f"{description} must have exactly one hard link")


def _metadata_evidence(metadata: os.stat_result, digest: str) -> dict[str, object]:
    return {
        "sha256": digest,
        "mode": stat.S_IMODE(metadata.st_mode) & 0o777,
        "size": metadata.st_size,
    }


def _file_evidence_at(
    directory: _DirectoryBinding,
    name: str,
    *,
    description: str,
    expected_metadata: os.stat_result | None = None,
    max_bytes: int | None = None,
) -> dict[str, object] | None:
    metadata = _lstat_at(directory, name)
    if metadata is None:
        return None
    _require_owned_regular_output(
        metadata,
        description=description,
        require_single_link=False,
    )
    if max_bytes is not None and metadata.st_size > max_bytes:
        raise BootstrapTransactionError(
            f"{description} exceeds its bounded read limit of {max_bytes} bytes"
        )
    if (
        expected_metadata is not None
        and safe_paths.stable_file_metadata(metadata)
        != safe_paths.stable_file_metadata(expected_metadata)
    ):
        raise BootstrapTransactionError(f"{description} changed before it was recorded")
    descriptor = os.open(
        name,
        _transaction_read_flags(),
        dir_fd=_binding_descriptor(directory),
    )
    try:
        opened = os.fstat(descriptor)
        _require_owned_regular_output(
            opened,
            description=description,
            require_single_link=False,
        )
        if max_bytes is not None and opened.st_size > max_bytes:
            raise BootstrapTransactionError(
                f"{description} exceeds its bounded read limit of {max_bytes} bytes"
            )
        if _inode_payload_identity(opened) != _inode_payload_identity(metadata):
            raise BootstrapTransactionError(f"{description} changed while it was opened")
        digest = hashlib.sha256()
        total = 0
        while True:
            read_size = (
                1024 * 1024
                if max_bytes is None
                else min(1024 * 1024, max_bytes - total + 1)
            )
            chunk = os.read(descriptor, read_size)
            if not chunk:
                break
            total += len(chunk)
            if max_bytes is not None and total > max_bytes:
                raise BootstrapTransactionError(
                    f"{description} exceeds its bounded read limit of "
                    f"{max_bytes} bytes"
                )
            digest.update(chunk)
        final = os.fstat(descriptor)
        if _inode_payload_identity(final) != _inode_payload_identity(opened):
            raise BootstrapTransactionError(f"{description} changed while it was read")
        named_final = _lstat_at(directory, name)
        if (
            named_final is None
            or safe_paths.stable_file_metadata(named_final)
            != safe_paths.stable_file_metadata(final)
        ):
            raise BootstrapTransactionError(
                f"{description} pathname changed while it was read"
            )
        return _metadata_evidence(final, digest.hexdigest())
    finally:
        os.close(descriptor)


def _evidence_matches(
    actual: dict[str, object] | None,
    expected: object,
) -> bool:
    if not isinstance(expected, dict) or actual is None:
        return False
    if expected.get("mode") is None:
        return (
            actual.get("sha256") == expected.get("sha256")
            and actual.get("size") == expected.get("size")
            and type(actual.get("mode")) is int
        )
    return actual == expected


def _preimage_evidence_at(
    parent: _DirectoryBinding,
    target_name: str,
    *,
    output_name: str,
    max_bytes: int | None = None,
) -> dict[str, object] | None:
    metadata = _lstat_at(parent, target_name)
    if metadata is None:
        return None
    _require_owned_regular_output(
        metadata,
        description=f"existing bootstrap output {output_name}",
        require_single_link=True,
    )
    evidence = _file_evidence_at(
        parent,
        target_name,
        description=f"existing bootstrap output {output_name}",
        expected_metadata=metadata,
        max_bytes=max_bytes,
    )
    if evidence is None or not isinstance(evidence.get("sha256"), str):
        raise BootstrapTransactionError(
            f"could not establish bootstrap output preimage: {output_name}"
        )
    return evidence


def _preimage_contract_matches(
    actual: dict[str, object] | None,
    *,
    expected_digest: str | None,
    expected_mode: int | None,
    check_mode: bool,
) -> bool:
    actual_digest = actual.get("sha256") if actual is not None else None
    actual_mode = actual.get("mode") if actual is not None else None
    return actual_digest == expected_digest and (
        not check_mode or actual_mode == expected_mode
    )


def _preimage_contract_description(
    evidence: dict[str, object] | None,
    *,
    mode_required: bool,
) -> str:
    if evidence is None:
        return "absent"
    digest = evidence.get("sha256")
    if not mode_required:
        return str(digest)
    mode = evidence.get("mode")
    rendered_mode = f"{mode:#05o}" if type(mode) is int else "invalid"
    return f"{digest} at mode {rendered_mode}"


def _snapshot_output_target(
    parent: _DirectoryBinding,
    target_name: str,
    *,
    output_name: str,
    force: bool,
) -> os.stat_result | None:
    metadata = _lstat_at(parent, target_name)
    if metadata is None:
        return None
    if not force:
        raise FileExistsError(
            f"refusing to overwrite existing file without --force: {output_name}"
        )
    _require_owned_regular_output(
        metadata,
        description=f"existing bootstrap output {output_name}",
        require_single_link=True,
    )
    return metadata


def _create_transaction_directory(
    parent: _DirectoryBinding,
    *,
    entry_name: str,
    all_bindings: list[_DirectoryBinding],
) -> _TransactionDirectory:
    parent_descriptor = _binding_descriptor(parent)
    parent_parts = parent.project_relative_parts
    if parent_parts is None:
        raise BootstrapTransactionError(
            "bootstrap transaction parent is not inside the bound project root"
        )
    parts = _relative_output_parts(entry_name)
    if (
        len(parts) != 1
        or not entry_name.startswith(".mpa-bootstrap-transaction-")
        or len(entry_name.removeprefix(".mpa-bootstrap-transaction-")) != 32
        or any(
            character not in "0123456789abcdef"
            for character in entry_name.removeprefix(
                ".mpa-bootstrap-transaction-"
            )
        )
    ):
        raise ValueError("bootstrap transaction directory name is invalid")
    os.mkdir(entry_name, mode=0o700, dir_fd=parent_descriptor)
    try:
        descriptor = os.open(
            entry_name,
            _transaction_directory_flags(),
            dir_fd=parent_descriptor,
        )
    except BaseException as exc:
        resource_cleanup.cleanup_actions(
            (
                (
                    "new bootstrap transaction directory",
                    lambda: os.rmdir(entry_name, dir_fd=parent_descriptor),
                ),
                (
                    "bootstrap transaction directory parent",
                    lambda: os.fsync(parent_descriptor),
                ),
            ),
            primary=exc,
        )
        raise
    try:
        metadata = os.fstat(descriptor)
        os.fchmod(descriptor, 0o700)
        metadata = os.fstat(descriptor)
        _require_owned_directory(
            metadata,
            description="bootstrap transaction directory",
        )
        if stat.S_IMODE(metadata.st_mode) & 0o077:
            raise ValueError(
                "bootstrap transaction directory must not be group- or world-accessible"
            )
    except BaseException as exc:
        resource_cleanup.cleanup_actions(
            (
                (
                    "new bootstrap transaction directory descriptor",
                    lambda: os.close(descriptor),
                ),
                (
                    "new bootstrap transaction directory",
                    lambda: os.rmdir(entry_name, dir_fd=parent_descriptor),
                ),
                (
                    "bootstrap transaction directory parent",
                    lambda: os.fsync(parent_descriptor),
                ),
            ),
            primary=exc,
        )
        raise
    binding = _DirectoryBinding(
        descriptor=descriptor,
        parent=parent,
        entry_name=entry_name,
        identity=_directory_identity(metadata),
        label="bootstrap transaction directory",
        project_relative_parts=(*parent_parts, entry_name),
    )
    all_bindings.append(binding)
    os.fsync(descriptor)
    os.fsync(parent_descriptor)
    return _TransactionDirectory(
        parent=parent,
        binding=binding,
        relative_path="/".join((*parent_parts, entry_name)),
    )


def _write_all(descriptor: int, content: bytes) -> None:
    offset = 0
    while offset < len(content):
        written = os.write(descriptor, content[offset:])
        if written <= 0:
            raise OSError("bootstrap staging write made no progress")
        offset += written


def _stage_output(
    record: _OutputTransactionRecord,
    index: int,
    *,
    create_file_mode: int | None,
) -> None:
    if record.action == "remove":
        return
    transaction_directory = record.transaction_directory
    if transaction_directory is None or record.content is None:
        raise BootstrapTransactionError("bootstrap output has no transaction directory")
    transaction_descriptor = _binding_descriptor(transaction_directory.binding)
    stage_name = f"stage-{index}"
    record.stage_name = stage_name
    descriptor = os.open(
        stage_name,
        _transaction_file_flags(),
        0o666 if create_file_mode is None else create_file_mode,
        dir_fd=transaction_descriptor,
    )
    try:
        _write_all(descriptor, record.content)
        expected_mode = record.target_mode
        if expected_mode is None and record.original_metadata is not None:
            expected_mode = stat.S_IMODE(record.original_metadata.st_mode) & 0o777
        if expected_mode is None:
            expected_mode = create_file_mode
        if expected_mode is not None:
            os.fchmod(descriptor, expected_mode)
        os.fsync(descriptor)
        metadata = os.fstat(descriptor)
        _require_owned_regular_output(
            metadata,
            description=f"staged bootstrap output {record.name}",
            require_single_link=True,
        )
        if metadata.st_size != len(record.content):
            raise OSError(
                f"staged bootstrap output has the wrong byte length: {record.name}"
            )
        if expected_mode is not None and stat.S_IMODE(metadata.st_mode) != expected_mode:
            raise BootstrapTransactionError(
                f"staged bootstrap output has the wrong mode: {record.name}"
            )
        record.staged_identity = _inode_payload_identity(metadata)
        record.candidate_evidence = _metadata_evidence(
            metadata,
            hashlib.sha256(record.content).hexdigest(),
        )
    finally:
        os.close(descriptor)
    os.fsync(transaction_descriptor)


def _verify_target_snapshot(record: _OutputTransactionRecord) -> None:
    current = _lstat_at(record.parent, record.target_name)
    if record.original_metadata is None:
        if current is not None:
            raise BootstrapTransactionError(
                f"bootstrap output appeared after preflight: {record.name}"
            )
        return
    if (
        current is None
        or safe_paths.stable_file_metadata(current)
        != safe_paths.stable_file_metadata(record.original_metadata)
    ):
        raise BootstrapTransactionError(
            f"bootstrap output changed or was replaced after preflight: {record.name}"
        )
    _require_owned_regular_output(
        current,
        description=f"existing bootstrap output {record.name}",
        require_single_link=True,
    )


def _install_staged_output(
    record: _OutputTransactionRecord,
    index: int,
    all_bindings: list[_DirectoryBinding],
) -> None:
    transaction_directory = record.transaction_directory
    if transaction_directory is None:
        raise BootstrapTransactionError(
            f"bootstrap output has no transaction directory: {record.name}"
        )
    if record.action == "write" and (
        record.stage_name is None or record.staged_identity is None
    ):
        raise BootstrapTransactionError(
            f"bootstrap output was not staged before installation: {record.name}"
        )
    _verify_bound_directories(all_bindings)
    _verify_target_snapshot(record)
    parent_descriptor = _binding_descriptor(record.parent)
    transaction_descriptor = _binding_descriptor(transaction_directory.binding)
    if record.original_metadata is not None:
        backup_name = record.backup_name or f"backup-{index}"
        record.backup_name = backup_name
        os.rename(
            record.target_name,
            backup_name,
            src_dir_fd=parent_descriptor,
            dst_dir_fd=transaction_descriptor,
        )
        backup_metadata = _lstat_at(transaction_directory.binding, backup_name)
        if backup_metadata is None:
            raise BootstrapTransactionError(
                f"bootstrap backup disappeared during installation: {record.name}"
            )
        record.backup_identity = _inode_payload_identity(backup_metadata)
        if _inode_payload_identity(backup_metadata) != _inode_payload_identity(
            record.original_metadata
        ):
            raise BootstrapTransactionError(
                f"bootstrap output was replaced while its backup was created: {record.name}"
            )
        os.fsync(parent_descriptor)
        os.fsync(transaction_descriptor)
    if record.action == "remove":
        if _lstat_at(record.parent, record.target_name) is not None:
            raise BootstrapTransactionError(
                f"removed bootstrap output still exists: {record.name}"
            )
        record.installed_signature = None
        os.fsync(parent_descriptor)
        os.fsync(transaction_descriptor)
        _verify_bound_directories(all_bindings)
        return
    if record.stage_name is None or record.staged_identity is None:
        raise BootstrapTransactionError(
            f"bootstrap output was not staged before installation: {record.name}"
        )
    named_stage = _lstat_at(transaction_directory.binding, record.stage_name)
    if (
        named_stage is None
        or _inode_payload_identity(named_stage) != record.staged_identity
    ):
        raise BootstrapTransactionError(
            f"staged bootstrap output changed before installation: {record.name}"
        )
    os.link(
        record.stage_name,
        record.target_name,
        src_dir_fd=transaction_descriptor,
        dst_dir_fd=parent_descriptor,
    )
    record.observed_install_identity = record.staged_identity
    installed = _lstat_at(record.parent, record.target_name)
    if installed is None or _inode_payload_identity(installed) != record.staged_identity:
        raise BootstrapTransactionError(
            f"installed bootstrap output does not match its staged inode: {record.name}"
        )
    os.unlink(record.stage_name, dir_fd=transaction_descriptor)
    installed = _lstat_at(record.parent, record.target_name)
    if installed is None:
        raise BootstrapTransactionError(
            f"installed bootstrap output disappeared: {record.name}"
        )
    _require_owned_regular_output(
        installed,
        description=f"installed bootstrap output {record.name}",
        require_single_link=True,
    )
    if _inode_payload_identity(installed) != record.staged_identity:
        raise BootstrapTransactionError(
            f"installed bootstrap output changed during installation: {record.name}"
        )
    record.installed_signature = safe_paths.stable_file_metadata(installed)
    os.fsync(parent_descriptor)
    os.fsync(transaction_descriptor)
    _verify_bound_directories(all_bindings)


def _recovery_quarantine_name(index: int, artifact: str) -> str:
    if artifact not in {"target", "stage", "backup"}:
        raise ValueError(f"unsupported bootstrap recovery artifact: {artifact}")
    return f"quarantine-{artifact}-{index}"


def _move_file_to_verified_quarantine(
    source: _DirectoryBinding,
    source_name: str,
    quarantine: _DirectoryBinding,
    quarantine_name: str,
    *,
    expected_evidence: object,
    description: str,
    expected_payload_identity: tuple[int, ...] | None = None,
) -> tuple[int, ...]:
    """Move a selected name aside, then prove the moved inode and bytes.

    Validation after the rename closes the check-then-unlink/restore race: a
    syscall-boundary source substitution is retained under the quarantine name
    and recovery controls remain available instead of deleting unrelated bytes.
    """

    if _lstat_at(quarantine, quarantine_name) is not None:
        raise BootstrapTransactionError(
            f"{description} quarantine already exists: {quarantine_name}"
        )
    os.rename(
        source_name,
        quarantine_name,
        src_dir_fd=_binding_descriptor(source),
        dst_dir_fd=_binding_descriptor(quarantine),
    )
    os.fsync(_binding_descriptor(source))
    if source is not quarantine:
        os.fsync(_binding_descriptor(quarantine))
    moved = _lstat_at(quarantine, quarantine_name)
    if moved is None:
        raise BootstrapTransactionError(
            f"{description} disappeared while it was moved to quarantine"
        )
    moved_identity = _inode_payload_identity(moved)
    moved_evidence = _file_evidence_at(
        quarantine,
        quarantine_name,
        description=f"quarantined {description}",
    )
    if (
        expected_payload_identity is not None
        and moved_identity != expected_payload_identity
    ) or not _evidence_matches(moved_evidence, expected_evidence):
        raise BootstrapTransactionError(
            f"{description} changed while it was moved to quarantine; retained "
            f"{quarantine_name} and transaction controls for inspection"
        )
    return moved_identity


def _retire_verified_quarantine(
    quarantine: _DirectoryBinding,
    quarantine_name: str,
    *,
    expected_evidence: object,
    expected_payload_identity: tuple[int, ...],
    description: str,
) -> None:
    """Retire a verified private quarantine under the exclusive refresh window.

    The selection move is verified after its syscall and therefore retains a
    substituted source.  Final name retirement relies on the repository's
    enforced lifecycle precondition: ordinary project writers are quiesced and
    cooperating lifecycle writers honor the held advisory project lock.  POSIX
    does not provide a portable inode-identity-bound unlink for an arbitrary
    same-UID process that violates that boundary.
    """

    _verified_quarantine_identity(
        quarantine,
        quarantine_name,
        expected_evidence=expected_evidence,
        expected_payload_identity=expected_payload_identity,
        description=description,
    )
    os.unlink(quarantine_name, dir_fd=_binding_descriptor(quarantine))
    os.fsync(_binding_descriptor(quarantine))


def _verified_quarantine_identity(
    quarantine: _DirectoryBinding,
    quarantine_name: str,
    *,
    expected_evidence: object,
    expected_payload_identity: tuple[int, ...] | None,
    description: str,
) -> tuple[int, ...]:
    current = _lstat_at(quarantine, quarantine_name)
    if current is None:
        raise BootstrapTransactionError(
            f"quarantined {description} disappeared before retirement"
        )
    current_evidence = _file_evidence_at(
        quarantine,
        quarantine_name,
        description=f"quarantined {description}",
    )
    if (
        expected_payload_identity is not None
        and _inode_payload_identity(current) != expected_payload_identity
        or not _evidence_matches(current_evidence, expected_evidence)
    ):
        raise BootstrapTransactionError(
            f"quarantined {description} changed before retirement"
        )
    return _inode_payload_identity(current)


def _restore_verified_quarantine(
    quarantine: _DirectoryBinding,
    quarantine_name: str,
    target: _DirectoryBinding,
    target_name: str,
    *,
    expected_evidence: object,
    expected_payload_identity: tuple[int, ...],
    description: str,
) -> None:
    if _lstat_at(target, target_name) is not None:
        raise BootstrapTransactionError(
            f"{description} target was concurrently recreated; retained quarantine"
        )
    current = _lstat_at(quarantine, quarantine_name)
    if current is None:
        raise BootstrapTransactionError(
            f"quarantined {description} disappeared before restoration"
        )
    current_evidence = _file_evidence_at(
        quarantine,
        quarantine_name,
        description=f"quarantined {description}",
    )
    if (
        _inode_payload_identity(current) != expected_payload_identity
        or not _evidence_matches(current_evidence, expected_evidence)
    ):
        raise BootstrapTransactionError(
            f"quarantined {description} changed before restoration"
        )
    os.link(
        quarantine_name,
        target_name,
        src_dir_fd=_binding_descriptor(quarantine),
        dst_dir_fd=_binding_descriptor(target),
    )
    os.fsync(_binding_descriptor(target))
    restored = _lstat_at(target, target_name)
    restored_evidence = _file_evidence_at(
        target,
        target_name,
        description=f"restored {description}",
    )
    if (
        restored is None
        or _inode_payload_identity(restored) != expected_payload_identity
        or not _evidence_matches(restored_evidence, expected_evidence)
    ):
        raise BootstrapTransactionError(
            f"{description} restoration did not install the exact quarantined file"
        )
    _retire_verified_quarantine(
        quarantine,
        quarantine_name,
        expected_evidence=expected_evidence,
        expected_payload_identity=expected_payload_identity,
        description=description,
    )


def _rollback_output(record: _OutputTransactionRecord, index: int) -> list[str]:
    errors: list[str] = []
    transaction_directory = record.transaction_directory
    if transaction_directory is None:
        return errors
    parent_descriptor = _binding_descriptor(record.parent)
    transaction_descriptor = _binding_descriptor(transaction_directory.binding)
    try:
        target = _lstat_at(record.parent, record.target_name)
        removable_identity = (
            record.observed_install_identity or record.staged_identity
        )
        if (
            target is not None
            and removable_identity is not None
            and _inode_payload_identity(target) == removable_identity
            and record.candidate_evidence is not None
        ):
            quarantine_name = _recovery_quarantine_name(index, "target")
            quarantined_identity = _move_file_to_verified_quarantine(
                record.parent,
                record.target_name,
                transaction_directory.binding,
                quarantine_name,
                expected_evidence=record.candidate_evidence,
                expected_payload_identity=removable_identity,
                description=f"rollback candidate {record.name}",
            )
            _retire_verified_quarantine(
                transaction_directory.binding,
                quarantine_name,
                expected_evidence=record.candidate_evidence,
                expected_payload_identity=quarantined_identity,
                description=f"rollback candidate {record.name}",
            )
        if record.backup_name is not None:
            backup = _lstat_at(transaction_directory.binding, record.backup_name)
            if backup is not None:
                if record.original_evidence is None:
                    raise BootstrapTransactionError(
                        f"rollback backup lacks original evidence: {record.name}"
                    )
                quarantine_name = _recovery_quarantine_name(index, "backup")
                quarantined_identity = _move_file_to_verified_quarantine(
                    transaction_directory.binding,
                    record.backup_name,
                    transaction_directory.binding,
                    quarantine_name,
                    expected_evidence=record.original_evidence,
                    expected_payload_identity=record.backup_identity,
                    description=f"rollback backup {record.name}",
                )
                current_target = _lstat_at(record.parent, record.target_name)
                current_target_evidence = (
                    _file_evidence_at(
                        record.parent,
                        record.target_name,
                        description=f"rollback target {record.name}",
                    )
                    if current_target is not None
                    else None
                )
                if _evidence_matches(
                    current_target_evidence,
                    record.original_evidence,
                ):
                    _retire_verified_quarantine(
                        transaction_directory.binding,
                        quarantine_name,
                        expected_evidence=record.original_evidence,
                        expected_payload_identity=quarantined_identity,
                        description=f"rollback backup {record.name}",
                    )
                elif current_target is None:
                    _restore_verified_quarantine(
                        transaction_directory.binding,
                        quarantine_name,
                        record.parent,
                        record.target_name,
                        expected_evidence=record.original_evidence,
                        expected_payload_identity=quarantined_identity,
                        description=f"rollback backup {record.name}",
                    )
                else:
                    raise BootstrapTransactionError(
                        "rollback target was concurrently recreated; retained "
                        f"quarantined backup for {record.name}"
                    )
        if record.stage_name is not None:
            stage = _lstat_at(transaction_directory.binding, record.stage_name)
            if stage is not None:
                stage_evidence = (
                    record.candidate_evidence
                    if record.staged_identity is not None
                    else _file_evidence_at(
                        transaction_directory.binding,
                        record.stage_name,
                        description=f"incomplete rollback stage {record.name}",
                    )
                )
                if stage_evidence is None:
                    raise BootstrapTransactionError(
                        f"rollback stage lacks candidate evidence: {record.name}"
                    )
                quarantine_name = _recovery_quarantine_name(index, "stage")
                quarantined_identity = _move_file_to_verified_quarantine(
                    transaction_directory.binding,
                    record.stage_name,
                    transaction_directory.binding,
                    quarantine_name,
                    expected_evidence=stage_evidence,
                    expected_payload_identity=(
                        record.staged_identity
                        if record.staged_identity is not None
                        else _inode_payload_identity(stage)
                    ),
                    description=f"rollback stage {record.name}",
                )
                _retire_verified_quarantine(
                    transaction_directory.binding,
                    quarantine_name,
                    expected_evidence=stage_evidence,
                    expected_payload_identity=quarantined_identity,
                    description=f"rollback stage {record.name}",
                )
        os.fsync(parent_descriptor)
        os.fsync(transaction_descriptor)
    except BaseException as exc:
        errors.append(f"rollback failed for {record.name}: {exc}")
    errors.extend(_rollback_terminal_errors(record, index))
    return errors


def _rollback_terminal_errors(
    record: _OutputTransactionRecord,
    index: int,
) -> list[str]:
    """Prove one live rollback reached its exact file and artifact contract."""

    errors: list[str] = []
    try:
        target_metadata = _lstat_at(record.parent, record.target_name)
        target_evidence = (
            _file_evidence_at(
                record.parent,
                record.target_name,
                description=f"rolled-back bootstrap output {record.name}",
            )
            if target_metadata is not None
            else None
        )
        if record.original_evidence is None:
            if target_evidence is not None:
                errors.append(
                    f"rollback did not restore approved target absence: {record.name}"
                )
        elif not _evidence_matches(target_evidence, record.original_evidence):
            errors.append(
                f"rollback did not restore the exact original output: {record.name}"
            )
        transaction_directory = record.transaction_directory
        if transaction_directory is not None:
            for artifact_name, artifact_label in (
                (record.stage_name, "stage"),
                (record.backup_name, "backup"),
                (_recovery_quarantine_name(index, "target"), "target quarantine"),
                (_recovery_quarantine_name(index, "stage"), "stage quarantine"),
                (_recovery_quarantine_name(index, "backup"), "backup quarantine"),
            ):
                if (
                    artifact_name is not None
                    and _lstat_at(
                        transaction_directory.binding,
                        artifact_name,
                    )
                    is not None
                ):
                    errors.append(
                        f"rollback retained its {artifact_label} artifact for "
                        f"{record.name}"
                    )
    except BaseException as exc:
        errors.append(
            f"rollback terminal state could not be verified for {record.name}: {exc}"
        )
    return errors


def _verify_installed_records(records: list[_OutputTransactionRecord]) -> None:
    for record in records:
        installed = _lstat_at(record.parent, record.target_name)
        if record.action == "remove":
            if installed is not None:
                raise BootstrapTransactionError(
                    f"removed bootstrap output reappeared before commit: {record.name}"
                )
            continue
        if (
            installed is None
            or record.installed_signature is None
            or safe_paths.stable_file_metadata(installed)
            != record.installed_signature
        ):
            raise BootstrapTransactionError(
                f"installed bootstrap output changed before commit: {record.name}"
            )
        evidence = _file_evidence_at(
            record.parent,
            record.target_name,
            description=f"installed bootstrap output {record.name}",
        )
        if not _evidence_matches(evidence, record.candidate_evidence):
            raise BootstrapTransactionError(
                f"installed bootstrap output bytes changed before commit: {record.name}"
            )


def _close_binding(binding: _DirectoryBinding) -> None:
    descriptor = binding.descriptor
    binding.descriptor = None
    if descriptor is not None:
        os.close(descriptor)


def _cleanup_transaction_resources(
    root: _DirectoryBinding | None,
    lock_descriptor: int | None,
    bindings: list[_DirectoryBinding],
    *,
    primary: BaseException | None = None,
    committed_cleanup_warnings: list[str] | None = None,
) -> None:
    """Attempt lock and binding cleanup once each without masking a primary."""

    actions: list[tuple[str, Callable[[], object]]] = [
        (
            "bootstrap project lock release",
            lambda: _release_project_lock(root, lock_descriptor),
        )
    ]
    actions.extend(
        (
            f"bootstrap transaction directory binding ({binding.label})",
            lambda binding=binding: _close_binding(binding),
        )
        for binding in reversed(bindings)
    )
    failures: list[tuple[str, BaseException]] = []
    for description, action in actions:
        try:
            action()
        except BaseException as cleanup:
            failures.append((description, cleanup))
    if primary is not None:
        for description, cleanup in failures:
            primary.add_note(f"{description} cleanup failure: {cleanup}")
        return
    if not failures:
        return
    if committed_cleanup_warnings is not None:
        interruptions = [
            (description, cleanup)
            for description, cleanup in failures
            if not isinstance(cleanup, Exception)
        ]
        if interruptions:
            description, interruption = interruptions[0]
            interruption.add_note(
                "bootstrap outputs were durably committed before terminal "
                f"cleanup was interrupted during {description}"
            )
            for other_description, other_cleanup in failures:
                if other_cleanup is interruption:
                    continue
                interruption.add_note(
                    f"additional {other_description} cleanup failure: "
                    f"{other_cleanup}"
                )
            raise interruption
        details = "; ".join(
            f"{description}: {cleanup}"
            for description, cleanup in failures
        )
        committed_cleanup_warnings.append(
            "could not complete post-commit bootstrap terminal cleanup: " + details
        )
        return
    description, first = failures[0]
    first.add_note(f"cleanup failed for {description}")
    for other_description, other_cleanup in failures[1:]:
        first.add_note(
            f"additional {other_description} cleanup failure: {other_cleanup}"
        )
    raise first


def _remove_empty_transaction_directories(
    transaction_directories: list[_TransactionDirectory],
) -> list[str]:
    warnings: list[str] = []
    for transaction_directory in reversed(transaction_directories):
        binding = transaction_directory.binding
        if not binding.active:
            continue
        descriptor = _binding_descriptor(binding)
        try:
            with os.scandir(descriptor) as iterator:
                remaining = sorted(entry.name for entry in iterator)
            if remaining:
                warnings.append(
                    "retained a bootstrap transaction directory containing recovery artifacts"
                )
                continue
            parent_descriptor = _binding_descriptor(transaction_directory.parent)
            entry_name = binding.entry_name
            if entry_name is None:
                warnings.append("retained an unnamed bootstrap transaction directory")
                continue
            if not _binding_entry_matches(binding):
                warnings.append(
                    "retained a bootstrap transaction directory whose path entry was replaced"
                )
                continue
            os.rmdir(entry_name, dir_fd=parent_descriptor)
            binding.active = False
            _close_binding(binding)
            os.fsync(parent_descriptor)
        except BaseException as exc:
            warnings.append(
                f"could not remove an empty bootstrap transaction directory: {exc}"
            )
    return warnings


def _remove_created_directories(created_bindings: list[_DirectoryBinding]) -> list[str]:
    errors: list[str] = []
    for binding in reversed(created_bindings):
        if not binding.active or binding.parent is None or binding.entry_name is None:
            continue
        try:
            parent_descriptor = _binding_descriptor(binding.parent)
            if not _binding_entry_matches(binding):
                errors.append(
                    f"refused to remove replaced newly created directory {binding.label}"
                )
                continue
            os.rmdir(binding.entry_name, dir_fd=parent_descriptor)
            binding.active = False
            _close_binding(binding)
            os.fsync(parent_descriptor)
        except BaseException as exc:
            errors.append(f"could not remove newly created directory {binding.label}: {exc}")
    return errors


def _directory_entries(binding: _DirectoryBinding) -> set[str]:
    with os.scandir(_binding_descriptor(binding)) as iterator:
        return {entry.name for entry in iterator}


def _verify_retirement_inventory(
    bindings: Mapping[tuple[str, ...], _DirectoryBinding],
    expected_children: Mapping[tuple[str, ...], set[str]],
    expected_modes: Mapping[str, int | None] | None = None,
) -> None:
    """Require the exact pre-transaction forest selected for retirement."""

    for parts in sorted(expected_children, key=lambda value: (len(value), value)):
        binding = bindings.get(parts)
        path = "/".join(parts)
        if binding is None:
            raise BootstrapTransactionError(
                f"retired bootstrap directory is missing: {path}"
            )
        metadata = os.fstat(_binding_descriptor(binding))
        if expected_modes is not None:
            expected_mode = expected_modes[path]
            if type(expected_mode) is not int:
                raise BootstrapTransactionError(
                    f"retired bootstrap directory mode contract is invalid: {path}"
                )
            actual_mode = stat.S_IMODE(metadata.st_mode) & 0o777
            if actual_mode != expected_mode:
                raise BootstrapTransactionError(
                    "retired bootstrap directory mode changed after plan "
                    f"inspection: {path} (expected {expected_mode:#05o}, "
                    f"found {actual_mode:#05o})"
                )
        if not _binding_entry_matches(binding):
            raise BootstrapTransactionError(
                f"retired bootstrap directory was removed or replaced: {path}"
            )
        actual = _directory_entries(binding)
        expected = expected_children[parts]
        if actual != expected:
            unexpected = sorted(actual - expected)
            missing = sorted(expected - actual)
            detail: list[str] = []
            if unexpected:
                detail.append("unexpected " + ", ".join(unexpected))
            if missing:
                detail.append("missing " + ", ".join(missing))
            raise BootstrapTransactionError(
                "retired bootstrap directory contents changed or exceed the "
                f"approved topology: {path} ({'; '.join(detail)})"
            )


def _retire_empty_directories(
    bindings: list[_DirectoryBinding],
) -> list[str]:
    """Remove only exact, already-bound empty directories, deepest first."""

    errors: list[str] = []
    ordered = sorted(
        bindings,
        key=lambda binding: (
            len(binding.project_relative_parts or ()),
            binding.project_relative_parts or (),
        ),
        reverse=True,
    )
    for binding in ordered:
        if not binding.active or binding.parent is None or binding.entry_name is None:
            continue
        path = "/".join(binding.project_relative_parts or ()) or binding.label
        try:
            if not _binding_entry_matches(binding):
                errors.append(
                    f"refused to retire replaced bootstrap directory: {path}"
                )
                continue
            remaining = sorted(_directory_entries(binding))
            if remaining:
                errors.append(
                    "refused to retire non-empty bootstrap directory: "
                    f"{path} ({', '.join(remaining)})"
                )
                continue
            parent_descriptor = _binding_descriptor(binding.parent)
            os.rmdir(binding.entry_name, dir_fd=parent_descriptor)
            binding.active = False
            _close_binding(binding)
            os.fsync(parent_descriptor)
        except BaseException as exc:
            errors.append(f"could not retire bootstrap directory {path}: {exc}")
    return errors


def _cleanup_committed_outputs(
    records: list[_OutputTransactionRecord],
    transaction_directories: list[_TransactionDirectory],
) -> list[str]:
    """Best-effort cleanup after installed output bytes are committed."""

    warnings: list[str] = []
    for record in records:
        if record.backup_name is None or record.transaction_directory is None:
            continue
        try:
            backup = _lstat_at(
                record.transaction_directory.binding,
                record.backup_name,
            )
        except BaseException as exc:
            warnings.append(
                "retained a bootstrap backup because post-commit cleanup "
                f"inspection failed for {record.name}: {exc}"
            )
            continue
        if backup is None:
            continue
        if (
            record.backup_identity is None
            or _inode_payload_identity(backup) != record.backup_identity
        ):
            warnings.append(
                f"retained a changed bootstrap backup for manual recovery: {record.name}"
            )
            continue
        try:
            transaction_descriptor = _binding_descriptor(
                record.transaction_directory.binding
            )
            os.unlink(record.backup_name, dir_fd=transaction_descriptor)
        except BaseException as exc:
            warnings.append(
                "retained a bootstrap backup because post-commit cleanup failed "
                f"for {record.name}: {exc}"
            )
            continue
        try:
            os.fsync(transaction_descriptor)
        except BaseException as exc:
            warnings.append(
                "bootstrap backup was removed but its directory fsync failed "
                f"for {record.name}: {exc}"
            )
    try:
        warnings.extend(
            _remove_empty_transaction_directories(transaction_directories)
        )
    except BaseException as exc:
        warnings.append(
            "could not complete post-commit bootstrap transaction-directory "
            f"cleanup: {exc}"
        )
    return warnings


def _journal_bytes(payload: dict[str, object]) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _valid_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _evidence_errors(
    value: object,
    label: str,
    *,
    nullable: bool,
    allow_unknown_mode: bool = False,
) -> list[str]:
    if value is None:
        return [] if nullable else [f"{label} must be an evidence object"]
    if not isinstance(value, dict):
        return [f"{label} must be an evidence object or null"]
    errors: list[str] = []
    keys = set(value)
    if keys != _RECOVERY_EVIDENCE_KEYS:
        errors.append(
            f"{label} keys must be exactly: {', '.join(sorted(_RECOVERY_EVIDENCE_KEYS))}"
        )
    if not _valid_sha256(value.get("sha256")):
        errors.append(f"{label}.sha256 must be one lowercase SHA-256 digest")
    mode = value.get("mode")
    if not (allow_unknown_mode and mode is None) and (
        type(mode) is not int or not 0 <= mode <= 0o777
    ):
        errors.append(
            f"{label}.mode must be an integer from 0 through 511"
            + (" or null while preparing" if allow_unknown_mode else "")
        )
    size = value.get("size")
    if type(size) is not int or size < 0:
        errors.append(f"{label}.size must be a non-negative integer")
    return errors


def _directory_identity_errors(
    value: object,
    label: str,
    *,
    allow_unknown: bool = False,
) -> list[str]:
    if allow_unknown and value is None:
        return []
    if not isinstance(value, list) or len(value) != 5:
        return [f"{label} must contain exactly five identity integers"]
    if any(type(item) is not int or item < 0 for item in value):
        return [f"{label} must contain exactly five non-negative identity integers"]
    return []


def _validate_journal_payload(payload: object) -> list[str]:
    if not isinstance(payload, dict):
        return ["bootstrap recovery journal must be a JSON object"]
    errors: list[str] = []
    keys = set(payload)
    if keys != _RECOVERY_JOURNAL_KEYS:
        errors.append(
            "bootstrap recovery journal keys must be exactly: "
            + ", ".join(sorted(_RECOVERY_JOURNAL_KEYS))
        )
    if payload.get("schema_version") != RECOVERY_JOURNAL_SCHEMA_VERSION or type(
        payload.get("schema_version")
    ) is not int:
        errors.append(
            "bootstrap recovery journal schema_version must be exactly "
            f"{RECOVERY_JOURNAL_SCHEMA_VERSION}"
        )
    transaction_id = payload.get("transaction_id")
    if (
        not isinstance(transaction_id, str)
        or len(transaction_id) != 32
        or any(character not in "0123456789abcdef" for character in transaction_id)
    ):
        errors.append("bootstrap recovery journal transaction_id must be 32 lowercase hex characters")
    phase = payload.get("phase")
    if not isinstance(phase, str) or phase not in _RECOVERY_PHASES:
        errors.append(
            "bootstrap recovery journal phase must be one of: "
            + ", ".join(sorted(_RECOVERY_PHASES))
        )
    bound_directories = payload.get("bound_directories")
    bound_directory_parts: list[tuple[str, ...]] = []
    bound_directory_identities: dict[tuple[str, ...], object] = {}
    if not isinstance(bound_directories, list):
        errors.append("bootstrap recovery journal bound_directories must be a list")
    else:
        if len(bound_directories) > _RECOVERY_JOURNAL_MAX_BOUND_DIRECTORIES:
            errors.append(
                "bootstrap recovery journal bound_directories exceed the bounded "
                "directory limit"
            )
        normalized_bound: list[str] = []
        for index, item in enumerate(bound_directories):
            label = f"bootstrap recovery journal bound_directories[{index}]"
            if not isinstance(item, dict):
                errors.append(f"{label} must be an object")
                continue
            if set(item) != _RECOVERY_BOUND_DIRECTORY_KEYS:
                errors.append(
                    f"{label} keys must be exactly: "
                    + ", ".join(sorted(_RECOVERY_BOUND_DIRECTORY_KEYS))
                )
            path = item.get("path")
            if path == ".":
                parts: tuple[str, ...] = ()
                normalized = "."
            else:
                try:
                    parts = _relative_output_parts(path) if isinstance(path, str) else ()
                except ValueError as exc:
                    errors.append(f"{label}.path is invalid: {exc}")
                    parts = ()
                normalized = "/".join(parts)
                if not parts:
                    errors.append(
                        f"{label}.path must be '.' or a normalized relative path"
                    )
                elif _is_reserved_transaction_path(parts):
                    errors.append(f"{label}.path uses a reserved transaction namespace")
            if path == "." or parts:
                normalized_bound.append(normalized)
                bound_directory_parts.append(parts)
                bound_directory_identities[parts] = item.get("identity")
            errors.extend(
                _directory_identity_errors(item.get("identity"), f"{label}.identity")
            )
        if len(set(normalized_bound)) != len(normalized_bound):
            errors.append("bootstrap recovery journal bound_directories must be unique")
        if normalized_bound != sorted(
            normalized_bound,
            key=lambda value: (0 if value == "." else len(value.split("/")), value),
        ):
            errors.append(
                "bootstrap recovery journal bound_directories must use canonical "
                "parent-before-child order"
            )
        if () not in bound_directory_parts:
            errors.append(
                "bootstrap recovery journal bound_directories must include project root '.'"
            )
        bound_directory_set = set(bound_directory_parts)
        for parts in bound_directory_parts:
            if parts and parts[:-1] not in bound_directory_set:
                errors.append(
                    "bootstrap recovery journal bound directory lacks its exact "
                    "pre-existing parent binding: " + "/".join(parts)
                )
    created_directories = payload.get("created_directories")
    created_directory_parts: list[tuple[str, ...]] = []
    if not isinstance(created_directories, list):
        errors.append("bootstrap recovery journal created_directories must be a list")
    else:
        if len(created_directories) > _RECOVERY_JOURNAL_MAX_CREATED_DIRECTORIES:
            errors.append(
                "bootstrap recovery journal created_directories exceed the bounded directory limit"
            )
        normalized_created: list[str] = []
        for index, item in enumerate(created_directories):
            label = f"bootstrap recovery journal created_directories[{index}]"
            if not isinstance(item, dict):
                errors.append(f"{label} must be an object")
                continue
            if set(item) != _RECOVERY_CREATED_DIRECTORY_KEYS:
                errors.append(
                    f"{label} keys must be exactly: "
                    + ", ".join(sorted(_RECOVERY_CREATED_DIRECTORY_KEYS))
                )
            path = item.get("path")
            try:
                parts = _relative_output_parts(path) if isinstance(path, str) else ()
            except ValueError as exc:
                errors.append(f"{label}.path is invalid: {exc}")
                parts = ()
            if not parts:
                errors.append(f"{label}.path must be a normalized relative path")
            elif _is_reserved_transaction_path(parts):
                errors.append(f"{label}.path uses a reserved transaction namespace")
            else:
                normalized_created.append("/".join(parts))
                created_directory_parts.append(parts)
            errors.extend(
                _directory_identity_errors(
                    item.get("identity"),
                    f"{label}.identity",
                    allow_unknown=phase == "preparing",
                )
            )
        if len(set(normalized_created)) != len(normalized_created):
            errors.append("bootstrap recovery journal created_directories must be unique")
    retired_directories = payload.get("retired_directories")
    retired_directory_parts: list[tuple[str, ...]] = []
    if not isinstance(retired_directories, list):
        errors.append("bootstrap recovery journal retired_directories must be a list")
        retired_directories = []
    else:
        if len(retired_directories) > _RECOVERY_JOURNAL_MAX_RETIRED_DIRECTORIES:
            errors.append(
                "bootstrap recovery journal retired_directories exceed the bounded directory limit"
            )
        normalized_retired: list[str] = []
        for index, item in enumerate(retired_directories):
            label = f"bootstrap recovery journal retired_directories[{index}]"
            if not isinstance(item, dict):
                errors.append(f"{label} must be an object")
                continue
            if set(item) != _RECOVERY_RETIRED_DIRECTORY_KEYS:
                errors.append(
                    f"{label} keys must be exactly: "
                    + ", ".join(sorted(_RECOVERY_RETIRED_DIRECTORY_KEYS))
                )
            path = item.get("path")
            try:
                parts = _relative_output_parts(path) if isinstance(path, str) else ()
            except ValueError as exc:
                errors.append(f"{label}.path is invalid: {exc}")
                parts = ()
            if not parts:
                errors.append(f"{label}.path must be a normalized relative path")
            elif _is_reserved_transaction_path(parts):
                errors.append(f"{label}.path uses a reserved transaction namespace")
            else:
                normalized_retired.append("/".join(parts))
                retired_directory_parts.append(parts)
            errors.extend(
                _directory_identity_errors(
                    item.get("identity"),
                    f"{label}.identity",
                )
            )
        if len(set(normalized_retired)) != len(normalized_retired):
            errors.append("bootstrap recovery journal retired_directories must be unique")
    overlap_directories = set(created_directory_parts).intersection(
        retired_directory_parts
    )
    if overlap_directories:
        errors.append(
            "bootstrap recovery journal cannot both create and retire a directory: "
            + ", ".join("/".join(parts) for parts in sorted(overlap_directories))
        )
    bound_created_overlap = set(bound_directory_parts).intersection(
        created_directory_parts
    )
    if bound_created_overlap:
        errors.append(
            "bootstrap recovery journal cannot classify a directory as both "
            "pre-existing and transaction-created: "
            + ", ".join(
                "/".join(parts) for parts in sorted(bound_created_overlap)
            )
        )
    for retired in retired_directory_parts:
        if retired not in bound_directory_identities:
            errors.append(
                "bootstrap recovery journal retired directory lacks its "
                f"pre-existing binding: {'/'.join(retired)}"
            )
            continue
        retired_entry = next(
            (
                item
                for item in retired_directories
                if isinstance(item, dict) and item.get("path") == "/".join(retired)
            ),
            None,
        )
        if (
            isinstance(retired_entry, dict)
            and retired_entry.get("identity")
            != bound_directory_identities[retired]
        ):
            errors.append(
                "bootstrap recovery journal retired directory identity disagrees "
                f"with its pre-existing binding: {'/'.join(retired)}"
            )
    operations = payload.get("operations")
    if not isinstance(operations, list) or not operations:
        errors.append("bootstrap recovery journal operations must be a non-empty list")
        return errors
    if len(operations) > _RECOVERY_JOURNAL_MAX_OPERATIONS:
        errors.append(
            "bootstrap recovery journal operations exceed the bounded operation limit"
        )
    applied_count = payload.get("applied_count")
    if type(applied_count) is not int or not 0 <= applied_count <= len(operations):
        errors.append("bootstrap recovery journal applied_count is outside its operation range")
    seen_paths: set[str] = set()
    seen_path_parts: list[tuple[str, ...]] = []
    removal_path_parts: list[tuple[str, ...]] = []
    write_path_parts: list[tuple[str, ...]] = []
    for index, operation in enumerate(operations):
        label = f"bootstrap recovery journal operations[{index}]"
        if not isinstance(operation, dict):
            errors.append(f"{label} must be an object")
            continue
        if set(operation) != _RECOVERY_OPERATION_KEYS:
            errors.append(
                f"{label} keys must be exactly: "
                + ", ".join(sorted(_RECOVERY_OPERATION_KEYS))
            )
        path = operation.get("path")
        try:
            path_parts = _relative_output_parts(path) if isinstance(path, str) else ()
        except ValueError as exc:
            errors.append(f"{label}.path is invalid: {exc}")
            path_parts = ()
        if not path_parts:
            errors.append(f"{label}.path must be a normalized relative path")
        elif _is_reserved_transaction_path(path_parts):
            errors.append(f"{label}.path uses a reserved transaction namespace")
        elif path in seen_paths:
            errors.append(f"{label}.path is duplicated: {path}")
        elif isinstance(path, str):
            if any(
                path_parts[: len(other)] == other
                or other[: len(path_parts)] == path_parts
                for other in seen_path_parts
            ):
                errors.append(
                    f"{label}.path has an ancestor collision with another operation"
                )
            seen_path_parts.append(path_parts)
            seen_paths.add(path)
        action = operation.get("action")
        if not isinstance(action, str) or action not in _RECOVERY_ACTIONS:
            errors.append(
                f"{label}.action must be one of: {', '.join(sorted(_RECOVERY_ACTIONS))}"
            )
        elif path_parts:
            if action == "remove":
                removal_path_parts.append(path_parts)
            else:
                write_path_parts.append(path_parts)
        transaction_directory = operation.get("transaction_directory")
        try:
            transaction_parts = (
                _relative_output_parts(transaction_directory)
                if isinstance(transaction_directory, str)
                else ()
            )
        except ValueError as exc:
            errors.append(f"{label}.transaction_directory is invalid: {exc}")
            transaction_parts = ()
        if transaction_parts:
            suffix = transaction_parts[-1].removeprefix(".mpa-bootstrap-transaction-")
            expected_parent = path_parts[:-1]
            if (
                transaction_parts[:-1] != expected_parent
                or not transaction_parts[-1].startswith(".mpa-bootstrap-transaction-")
                or len(suffix) != 32
                or any(character not in "0123456789abcdef" for character in suffix)
            ):
                errors.append(
                    f"{label}.transaction_directory must be the private transaction directory beside its target"
                )
        else:
            errors.append(f"{label}.transaction_directory must be a normalized relative path")
        original = operation.get("original")
        candidate = operation.get("candidate")
        errors.extend(_evidence_errors(original, f"{label}.original", nullable=True))
        if original is not None and any(
            len(created_parts) < len(path_parts)
            and path_parts[: len(created_parts)] == created_parts
            for created_parts in created_directory_parts
        ):
            errors.append(
                f"{label}.original must be null beneath a transaction-created directory"
            )
        errors.extend(
            _evidence_errors(
                candidate,
                f"{label}.candidate",
                nullable=action == "remove",
                allow_unknown_mode=phase == "preparing" and action == "write",
            )
        )
        if action == "remove" and candidate is not None:
            errors.append(f"{label}.candidate must be null for a removal")
        expected_stage = f"stage-{index}" if action == "write" else None
        if operation.get("stage_name") != expected_stage:
            errors.append(f"{label}.stage_name does not match its action and index")
        expected_backup = f"backup-{index}" if original is not None else None
        if operation.get("backup_name") != expected_backup:
            errors.append(f"{label}.backup_name does not match its original evidence and index")
        if action == "remove" and original is None:
            errors.append(f"{label} removal requires original evidence")
    covered_directory_parts = set(bound_directory_parts).union(
        created_directory_parts
    )
    for operation_parts in seen_path_parts:
        for depth in range(0, len(operation_parts)):
            parent_parts = operation_parts[:depth]
            if parent_parts not in covered_directory_parts:
                errors.append(
                    "bootstrap recovery journal operation parent lacks an exact "
                    "pre-existing or transaction-created binding: "
                    + ("." if not parent_parts else "/".join(parent_parts))
                )
    for parts in created_directory_parts:
        if not any(
            len(parts) < len(operation_parts)
            and operation_parts[: len(parts)] == parts
            for operation_parts in seen_path_parts
        ):
            errors.append(
                "bootstrap recovery journal created directory is not an ancestor "
                f"of an operation: {'/'.join(parts)}"
            )
    retired_set = set(retired_directory_parts)
    _retirement_children, retirement_errors = _retirement_expected_children(
        retired_set,
        removal_path_parts,
    )
    errors.extend(
        "bootstrap recovery journal " + error
        for error in retirement_errors
    )
    for retired in retired_set:
        if any(
            len(retired) < len(path_parts)
            and path_parts[: len(retired)] == retired
            for path_parts in write_path_parts
        ):
            errors.append(
                "bootstrap recovery journal retired directory contains a planned "
                f"write: {'/'.join(retired)}"
            )
    if (phase == "preparing" or phase == "prepared") and applied_count != 0:
        errors.append(
            f"a {phase} bootstrap recovery journal must have applied_count 0"
        )
    if phase == "verified" and applied_count != len(operations):
        errors.append(
            "a verified bootstrap recovery journal must account for every operation"
        )
    try:
        serialized_size = len(_journal_bytes(payload))
    except (TypeError, ValueError) as exc:
        errors.append(f"bootstrap recovery journal cannot be serialized canonically: {exc}")
    else:
        if serialized_size > _RECOVERY_JOURNAL_MAX_BYTES:
            errors.append(
                "bootstrap recovery journal exceeds its byte limit before installation: "
                f"{serialized_size} > {_RECOVERY_JOURNAL_MAX_BYTES}"
            )
    return errors


def _journal_metadata(root: _DirectoryBinding) -> os.stat_result | None:
    metadata = _lstat_at(root, RECOVERY_JOURNAL_NAME)
    if metadata is None:
        return None
    _require_owned_regular_output(
        metadata,
        description="bootstrap recovery journal",
        require_single_link=True,
    )
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise ValueError(
            "bootstrap recovery journal must not be group- or world-accessible"
        )
    if metadata.st_size > _RECOVERY_JOURNAL_MAX_BYTES:
        raise ValueError("bootstrap recovery journal exceeds its byte limit")
    return metadata


def _journal_temporary_metadata(root: _DirectoryBinding) -> os.stat_result | None:
    metadata = _lstat_at(root, _RECOVERY_JOURNAL_TEMP_NAME)
    if metadata is None:
        return None
    _require_owned_regular_output(
        metadata,
        description="bootstrap recovery journal temporary file",
        require_single_link=True,
    )
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise ValueError(
            "bootstrap recovery journal temporary file must not be group- or world-accessible"
        )
    if metadata.st_size > _RECOVERY_JOURNAL_MAX_BYTES:
        raise ValueError(
            "bootstrap recovery journal temporary file exceeds its byte limit"
        )
    return metadata


def _journal_previous_metadata(root: _DirectoryBinding) -> os.stat_result | None:
    """Inspect the exact prior journal retained across a journal rewrite.

    The prior canonical bytes are copied from a retained descriptor into this
    O_EXCL name.  It therefore remains a single-link control independently of
    later canonical-name replacement.
    """

    metadata = _lstat_at(root, _RECOVERY_JOURNAL_PREVIOUS_NAME)
    if metadata is None:
        return None
    _require_owned_regular_output(
        metadata,
        description="previous bootstrap recovery journal",
        require_single_link=False,
    )
    if metadata.st_nlink != 1:
        raise ValueError(
            "previous bootstrap recovery journal must have exactly one hard link"
        )
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise ValueError(
            "previous bootstrap recovery journal must not be group- or world-accessible"
        )
    if metadata.st_size > _RECOVERY_JOURNAL_MAX_BYTES:
        raise ValueError("previous bootstrap recovery journal exceeds its byte limit")
    return metadata


def _remove_recovery_journal_previous(
    root: _DirectoryBinding,
    *,
    expected_payload_identity: tuple[int, ...],
) -> None:
    metadata = _journal_previous_metadata(root)
    if metadata is None:
        raise BootstrapTransactionError(
            "previous bootstrap recovery journal disappeared"
        )
    if _inode_payload_identity(metadata) != expected_payload_identity:
        raise BootstrapTransactionError(
            "previous bootstrap recovery journal was replaced"
        )
    current = _lstat_at(root, _RECOVERY_JOURNAL_PREVIOUS_NAME)
    if (
        current is None
        or _inode_payload_identity(current) != expected_payload_identity
    ):
        raise BootstrapTransactionError(
            "previous bootstrap recovery journal changed before removal"
        )
    os.unlink(
        _RECOVERY_JOURNAL_PREVIOUS_NAME,
        dir_fd=_binding_descriptor(root),
    )
    os.fsync(_binding_descriptor(root))


def _remove_recovery_journal_temporary(
    root: _DirectoryBinding,
    *,
    expected_object_identity: tuple[int, ...] | None = None,
) -> None:
    metadata = _journal_temporary_metadata(root)
    if metadata is None:
        if expected_object_identity is not None:
            raise BootstrapTransactionError(
                "bootstrap recovery journal temporary file disappeared"
            )
        return
    object_identity = _inode_object_identity(metadata)
    if (
        expected_object_identity is not None
        and object_identity != expected_object_identity
    ):
        raise BootstrapTransactionError(
            "bootstrap recovery journal temporary file was replaced"
        )
    current = _lstat_at(root, _RECOVERY_JOURNAL_TEMP_NAME)
    if current is None or _inode_object_identity(current) != object_identity:
        raise BootstrapTransactionError(
            "bootstrap recovery journal temporary file changed before removal"
        )
    os.unlink(_RECOVERY_JOURNAL_TEMP_NAME, dir_fd=_binding_descriptor(root))
    os.fsync(_binding_descriptor(root))


def _read_recovery_journal_snapshot(
    root: _DirectoryBinding,
    *,
    name: str,
    metadata: os.stat_result,
    description: str,
    require_single_link: bool,
) -> tuple[dict[str, object] | None, list[str]]:
    descriptor = os.open(
        name,
        _transaction_read_flags(),
        dir_fd=_binding_descriptor(root),
    )
    try:
        opened = os.fstat(descriptor)
        _require_owned_regular_output(
            opened,
            description=f"opened {description}",
            require_single_link=require_single_link,
        )
        if (
            stat.S_IMODE(opened.st_mode) & 0o077
            or safe_paths.stable_file_metadata(opened)
            != safe_paths.stable_file_metadata(metadata)
        ):
            return None, [f"{description} changed while it was opened"]
        raw = bytearray()
        while True:
            chunk = os.read(descriptor, 64 * 1024)
            if not chunk:
                break
            raw.extend(chunk)
            if len(raw) > _RECOVERY_JOURNAL_MAX_BYTES:
                return None, [f"{description} exceeds its byte limit"]
        final = os.fstat(descriptor)
        current = _lstat_at(root, name)
        try:
            _require_owned_regular_output(
                final,
                description=f"read {description}",
                require_single_link=require_single_link,
            )
            if current is not None:
                _require_owned_regular_output(
                    current,
                    description=f"named {description}",
                    require_single_link=require_single_link,
                )
        except (OSError, ValueError) as exc:
            return None, [str(exc)]
        if (
            stat.S_IMODE(final.st_mode) & 0o077
            or current is not None
            and stat.S_IMODE(current.st_mode) & 0o077
            or safe_paths.stable_file_metadata(final)
            != safe_paths.stable_file_metadata(opened)
            or current is None
            or safe_paths.stable_file_metadata(current)
            != safe_paths.stable_file_metadata(opened)
        ):
            return None, [f"{description} changed while it was read"]
    finally:
        os.close(descriptor)
    try:
        payload = safe_paths.loads_json_no_duplicates(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        return None, [f"{description} is invalid UTF-8 JSON: {exc}"]
    errors = _validate_journal_payload(payload)
    return (payload if isinstance(payload, dict) else None), errors


def _read_recovery_journal(
    root: _DirectoryBinding,
) -> tuple[dict[str, object] | None, list[str]]:
    try:
        metadata = _journal_metadata(root)
    except (OSError, ValueError) as exc:
        return None, [str(exc)]
    if metadata is None:
        return None, []
    return _read_recovery_journal_snapshot(
        root,
        name=RECOVERY_JOURNAL_NAME,
        metadata=metadata,
        description="bootstrap recovery journal",
        require_single_link=True,
    )


def _read_previous_recovery_journal(
    root: _DirectoryBinding,
) -> tuple[dict[str, object] | None, list[str]]:
    try:
        metadata = _journal_previous_metadata(root)
    except (OSError, ValueError) as exc:
        return None, [str(exc)]
    if metadata is None:
        return None, []
    return _read_recovery_journal_snapshot(
        root,
        name=_RECOVERY_JOURNAL_PREVIOUS_NAME,
        metadata=metadata,
        description="previous bootstrap recovery journal",
        require_single_link=False,
    )


def _select_recovery_journal(
    root: _DirectoryBinding,
    lock_descriptor: int,
) -> tuple[
    dict[str, object] | None,
    list[str],
    tuple[int, ...] | None,
]:
    """Select a canonical or exactly retained prior journal without mutation."""

    canonical_payload, canonical_errors = _read_recovery_journal(root)
    previous_metadata = _journal_previous_metadata(root)
    if previous_metadata is None:
        return canonical_payload, canonical_errors, None
    previous_payload, previous_errors = _read_previous_recovery_journal(root)
    if previous_payload is None or previous_errors:
        # A hard exit can leave the O_EXCL descriptor copy incomplete while
        # the canonical journal and its lock remain exact.  In that bounded
        # state the canonical record supplies the authorization identity and
        # recovery may retire only the exact inspected previous inode.
        if canonical_payload is not None and not canonical_errors:
            canonical_identity_errors = _recovery_journal_identity_errors(
                root,
                lock_descriptor,
                canonical_payload,
            )
            if not canonical_identity_errors:
                return (
                    canonical_payload,
                    [],
                    _inode_payload_identity(previous_metadata),
                )
        return (
            None,
            [
                *canonical_errors,
                *previous_errors,
                "retained previous bootstrap recovery journal is not a valid "
                "exact-ID recovery record",
            ],
            None,
        )
    previous_errors.extend(
        _recovery_journal_identity_errors(
            root,
            lock_descriptor,
            previous_payload,
        )
    )
    if previous_errors:
        return None, previous_errors, None
    previous_identity = _inode_payload_identity(previous_metadata)
    if canonical_payload is not None and not canonical_errors:
        if canonical_payload.get("transaction_id") != previous_payload.get(
            "transaction_id"
        ):
            return (
                None,
                [
                    "canonical and previous bootstrap recovery journals bind "
                    "different transaction identities"
                ],
                previous_identity,
            )
        return canonical_payload, [], previous_identity
    canonical_metadata = _lstat_at(root, RECOVERY_JOURNAL_NAME)
    if canonical_metadata is None:
        return (
            None,
            [
                "canonical bootstrap recovery journal is missing while its "
                "descriptor-copied previous record remains"
            ],
            previous_identity,
        )
    return (
        None,
        [
            *canonical_errors,
            "canonical bootstrap recovery journal does not match the exact "
            "retained previous journal",
        ],
        previous_identity,
    )


def _normalize_previous_recovery_journal(
    root: _DirectoryBinding,
    *,
    payload: dict[str, object],
    previous_identity: tuple[int, ...],
) -> None:
    """Restore one exact selected journal name, then retire its prior link."""

    canonical_metadata = _lstat_at(root, RECOVERY_JOURNAL_NAME)
    if canonical_metadata is None:
        raise BootstrapTransactionError(
            "selected previous bootstrap recovery journal could not be restored"
        )
    canonical_payload_identity = _inode_payload_identity(canonical_metadata)
    canonical_payload, canonical_errors = _read_recovery_journal_snapshot(
        root,
        name=RECOVERY_JOURNAL_NAME,
        metadata=canonical_metadata,
        description="selected bootstrap recovery journal",
        require_single_link=False,
    )
    if canonical_errors or canonical_payload != payload:
        raise BootstrapTransactionError(
            "selected bootstrap recovery journal changed before previous-journal "
            "normalization: "
            + "; ".join(canonical_errors or ["payload mismatch"])
        )
    if (
        canonical_payload_identity != previous_identity
        and _lstat_at(root, _RECOVERY_JOURNAL_PREVIOUS_NAME) is None
    ):
        raise BootstrapTransactionError(
            "previous bootstrap recovery journal disappeared before normalization"
        )
    _remove_recovery_journal_previous(
        root,
        expected_payload_identity=previous_identity,
    )
    normalized_payload, normalized_errors = _read_recovery_journal(root)
    if normalized_errors or normalized_payload != payload:
        raise BootstrapTransactionError(
            "bootstrap recovery journal normalization did not retain the exact "
            "selected payload: "
            + "; ".join(normalized_errors or ["payload mismatch"])
        )


def _copy_open_journal_to_previous(
    root: _DirectoryBinding,
    source_descriptor: int,
    source_metadata: os.stat_result,
) -> tuple[int, ...]:
    """Copy one descriptor-bound canonical journal into an O_EXCL control."""

    # A rename of the already-open canonical name may legitimately change
    # ctime while leaving the descriptor-bound payload intact.  Bind the copy
    # to payload identity so that pathname substitution is detected by the
    # caller's canonical-name recheck without discarding the exact prior bytes.
    source_signature = _inode_payload_identity(source_metadata)
    os.lseek(source_descriptor, 0, os.SEEK_SET)
    raw = bytearray()
    while True:
        chunk = os.read(source_descriptor, 64 * 1024)
        if not chunk:
            break
        raw.extend(chunk)
        if len(raw) > _RECOVERY_JOURNAL_MAX_BYTES:
            raise BootstrapTransactionError(
                "prior bootstrap recovery journal exceeds its bounded copy limit"
            )
    source_final = os.fstat(source_descriptor)
    if _inode_payload_identity(source_final) != source_signature:
        raise BootstrapTransactionError(
            "prior bootstrap recovery journal changed during descriptor-bound copy"
        )
    descriptor = os.open(
        _RECOVERY_JOURNAL_PREVIOUS_NAME,
        _transaction_file_flags(),
        0o600,
        dir_fd=_binding_descriptor(root),
    )
    created_object_identity: tuple[int, ...] | None = None
    try:
        created_object_identity = _inode_object_identity(os.fstat(descriptor))
        os.fchmod(descriptor, stat.S_IMODE(source_metadata.st_mode) & 0o777)
        _write_all(descriptor, bytes(raw))
        os.fsync(descriptor)
        copied = os.fstat(descriptor)
        _require_owned_regular_output(
            copied,
            description="descriptor-copied previous bootstrap recovery journal",
            require_single_link=True,
        )
        copied_identity = _inode_payload_identity(copied)
    except BaseException as exc:
        def retire_failed_previous_copy() -> None:
            current = _lstat_at(root, _RECOVERY_JOURNAL_PREVIOUS_NAME)
            if (
                created_object_identity is not None
                and current is not None
                and _inode_object_identity(current) == created_object_identity
            ):
                os.unlink(
                    _RECOVERY_JOURNAL_PREVIOUS_NAME,
                    dir_fd=_binding_descriptor(root),
                )

        resource_cleanup.cleanup_actions(
            (
                ("failed previous journal descriptor", lambda: os.close(descriptor)),
                ("failed exact previous journal copy", retire_failed_previous_copy),
                (
                    "previous journal parent directory",
                    lambda: os.fsync(_binding_descriptor(root)),
                ),
            ),
            primary=exc,
        )
        raise
    else:
        os.close(descriptor)
    expected_evidence = {
        "sha256": hashlib.sha256(raw).hexdigest(),
        "mode": stat.S_IMODE(source_metadata.st_mode) & 0o777,
        "size": len(raw),
    }
    copied_evidence = _file_evidence_at(
        root,
        _RECOVERY_JOURNAL_PREVIOUS_NAME,
        description="descriptor-copied previous bootstrap recovery journal",
        max_bytes=_RECOVERY_JOURNAL_MAX_BYTES,
    )
    if copied_evidence != expected_evidence:
        raise BootstrapTransactionError(
            "descriptor-copied previous bootstrap recovery journal does not "
            "match its exact source bytes"
        )
    os.fsync(_binding_descriptor(root))
    return copied_identity


def _write_recovery_journal(
    root: _DirectoryBinding,
    payload: dict[str, object],
    *,
    require_absent: bool,
    lock_descriptor: int,
) -> None:
    errors = _validate_journal_payload(payload)
    errors.extend(
        _recovery_journal_identity_errors(
            root,
            lock_descriptor,
            payload,
        )
    )
    if errors:
        raise BootstrapTransactionError("invalid bootstrap recovery journal: " + "; ".join(errors))
    serialized = _journal_bytes(payload)
    if len(serialized) > _RECOVERY_JOURNAL_MAX_BYTES:
        raise BootstrapTransactionError(
            "invalid bootstrap recovery journal: bootstrap recovery journal "
            "exceeds its byte limit before installation"
        )
    existing = _journal_metadata(root)
    if require_absent and existing is not None:
        raise BootstrapTransactionError(
            "an interrupted bootstrap transaction requires recovery before another write"
        )
    if not require_absent and existing is None:
        raise BootstrapTransactionError(
            "bootstrap recovery journal disappeared before transaction completion"
        )
    if _journal_temporary_metadata(root) is not None:
        raise BootstrapTransactionError(
            "an incomplete bootstrap recovery journal update requires inspection"
        )
    if _journal_previous_metadata(root) is not None:
        raise BootstrapTransactionError(
            "an incomplete bootstrap recovery journal replacement requires inspection"
        )
    descriptor = os.open(
        _RECOVERY_JOURNAL_TEMP_NAME,
        _transaction_file_flags(),
        0o600,
        dir_fd=_binding_descriptor(root),
    )
    temporary_object_identity: tuple[int, ...] | None = None
    temporary_payload_identity: tuple[int, ...] | None = None
    previous_payload_identity: tuple[int, ...] | None = None
    previous_source_identity: tuple[int, ...] | None = None
    previous_source_descriptor: int | None = None
    try:
        os.fchmod(descriptor, 0o600)
        temporary_object_identity = _inode_object_identity(os.fstat(descriptor))
        _write_all(descriptor, serialized)
        os.fsync(descriptor)
        temporary_payload_identity = _inode_payload_identity(os.fstat(descriptor))
    except BaseException as exc:
        def retire_exact_temporary() -> None:
            current_temporary = _journal_temporary_metadata(root)
            if (
                current_temporary is not None
                and temporary_object_identity is not None
            ):
                _remove_recovery_journal_temporary(
                    root,
                    expected_object_identity=temporary_object_identity,
                )
        resource_cleanup.cleanup_actions(
            (
                (
                    "bootstrap recovery journal temporary descriptor",
                    lambda: os.close(descriptor),
                ),
                (
                    "exact bootstrap recovery journal temporary file",
                    retire_exact_temporary,
                ),
            ),
            primary=exc,
        )
        raise
    try:
        _verify_project_lock(root, lock_descriptor)
        current = _journal_metadata(root)
        if require_absent:
            if current is not None:
                raise BootstrapTransactionError(
                    "an interrupted bootstrap transaction requires recovery before another write"
                )
        elif (
            current is None
            or existing is None
            or _inode_payload_identity(current) != _inode_payload_identity(existing)
        ):
            raise BootstrapTransactionError(
                "bootstrap recovery journal changed before its durable update"
            )
        temporary = _journal_temporary_metadata(root)
        if (
            temporary is None
            or temporary_object_identity is None
            or temporary_payload_identity is None
            or _inode_object_identity(temporary) != temporary_object_identity
            or _inode_payload_identity(temporary) != temporary_payload_identity
        ):
            raise BootstrapTransactionError(
                "bootstrap recovery journal temporary file changed before installation"
            )
        if not require_absent:
            if existing is None:
                raise BootstrapTransactionError(
                    "bootstrap recovery journal disappeared before its prior "
                    "version could be retained"
                )
            previous_source_identity = _inode_payload_identity(existing)
            previous_source_descriptor = os.open(
                RECOVERY_JOURNAL_NAME,
                _transaction_read_flags(),
                dir_fd=_binding_descriptor(root),
            )
            held_previous = os.fstat(previous_source_descriptor)
            _require_owned_regular_output(
                held_previous,
                description="held prior bootstrap recovery journal",
                require_single_link=True,
            )
            if _inode_payload_identity(held_previous) != previous_source_identity:
                raise BootstrapTransactionError(
                    "bootstrap recovery journal changed while its prior version "
                    "was bound for preservation"
                )
            previous_payload_identity = _copy_open_journal_to_previous(
                root,
                previous_source_descriptor,
                held_previous,
            )
            retained_previous = _journal_previous_metadata(root)
            rebound_canonical = _journal_metadata(root)
            if (
                retained_previous is None
                or _inode_payload_identity(retained_previous)
                != previous_payload_identity
                or _inode_payload_identity(os.fstat(previous_source_descriptor))
                != previous_source_identity
                or rebound_canonical is None
                or _inode_payload_identity(rebound_canonical)
                != previous_source_identity
            ):
                raise BootstrapTransactionError(
                    "bootstrap recovery journal replacement did not retain the "
                    "exact descriptor-bound prior journal"
                )
            os.close(previous_source_descriptor)
            previous_source_descriptor = None
        if previous_source_identity is not None:
            rebound_canonical = _journal_metadata(root)
            if (
                rebound_canonical is None
                or _inode_payload_identity(rebound_canonical)
                != previous_source_identity
            ):
                raise BootstrapTransactionError(
                    "canonical bootstrap recovery journal changed after its "
                    "descriptor-bound prior copy"
                )
        os.rename(
            _RECOVERY_JOURNAL_TEMP_NAME,
            RECOVERY_JOURNAL_NAME,
            src_dir_fd=_binding_descriptor(root),
            dst_dir_fd=_binding_descriptor(root),
        )
        os.fsync(_binding_descriptor(root))
        _verify_project_lock(root, lock_descriptor)
        installed = _journal_metadata(root)
        held = os.fstat(descriptor)
        expected_evidence = {
            "sha256": hashlib.sha256(serialized).hexdigest(),
            "mode": 0o600,
            "size": len(serialized),
        }
        installed_evidence = _file_evidence_at(
            root,
            RECOVERY_JOURNAL_NAME,
            description="installed bootstrap recovery journal",
            max_bytes=_RECOVERY_JOURNAL_MAX_BYTES,
        )
        if (
            installed is None
            or temporary_payload_identity is None
            or _inode_payload_identity(held) != temporary_payload_identity
            or _inode_payload_identity(installed) != temporary_payload_identity
            or installed_evidence != expected_evidence
        ):
            raise BootstrapTransactionError(
                "bootstrap recovery journal installation did not retain the "
                "exact staged inode and bytes"
            )
        if previous_payload_identity is not None:
            _remove_recovery_journal_previous(
                root,
                expected_payload_identity=previous_payload_identity,
            )
    except BaseException as exc:
        try:
            current_temporary = _journal_temporary_metadata(root)
            if (
                current_temporary is not None
                and temporary_object_identity is not None
            ):
                _remove_recovery_journal_temporary(
                    root,
                    expected_object_identity=temporary_object_identity,
                )
        except BaseException as cleanup_exc:
            raise BootstrapTransactionError(
                "bootstrap recovery journal installation failed and its exact "
                f"temporary file could not be removed: {cleanup_exc}"
            ) from exc
        try:
            if previous_source_descriptor is not None:
                os.close(previous_source_descriptor)
                previous_source_descriptor = None
            os.close(descriptor)
        except BaseException as close_exc:
            exc.add_note(
                "bootstrap recovery journal staged descriptor cleanup failure: "
                f"{close_exc}"
            )
        raise
    else:
        os.close(descriptor)
    _journal_metadata(root)
    if _recovery_journal_identity_errors(root, lock_descriptor, payload):
        raise BootstrapTransactionError(
            "bootstrap recovery journal lost its exact project transaction "
            "lock identity after installation"
        )


def _remove_recovery_journal(root: _DirectoryBinding) -> None:
    if _journal_previous_metadata(root) is not None:
        raise BootstrapTransactionError(
            "bootstrap recovery journal cannot be removed while its previous "
            "version is retained"
        )
    metadata = _journal_metadata(root)
    if metadata is None:
        return
    current = _lstat_at(root, RECOVERY_JOURNAL_NAME)
    if (
        current is None
        or _inode_payload_identity(current) != _inode_payload_identity(metadata)
    ):
        raise BootstrapTransactionError(
            "bootstrap recovery journal changed before it could be removed"
        )
    os.unlink(RECOVERY_JOURNAL_NAME, dir_fd=_binding_descriptor(root))
    os.fsync(_binding_descriptor(root))


def _render_recovery_payload(
    records: list[_OutputTransactionRecord],
    *,
    transaction_id: str,
    bound_directories: list[dict[str, object]],
    created_directories: list[dict[str, object]],
    retired_directories: list[dict[str, object]],
) -> dict[str, object]:
    operations: list[dict[str, object]] = []
    for record in records:
        if record.transaction_directory is None:
            raise BootstrapTransactionError(
                f"bootstrap output lacks recovery directory: {record.name}"
            )
        operations.append(
            {
                "path": record.name,
                "action": record.action,
                "transaction_directory": record.transaction_directory.relative_path,
                "stage_name": record.stage_name,
                "backup_name": record.backup_name,
                "original": record.original_evidence,
                "candidate": record.candidate_evidence,
            }
        )
    return {
        "schema_version": RECOVERY_JOURNAL_SCHEMA_VERSION,
        "transaction_id": transaction_id,
        "phase": "prepared",
        "applied_count": 0,
        "bound_directories": bound_directories,
        "created_directories": sorted(
            created_directories,
            key=lambda value: (
                len(str(value.get("path", "")).split("/")),
                str(value.get("path", "")),
            ),
        ),
        "retired_directories": sorted(
            retired_directories,
            key=lambda value: (
                len(str(value.get("path", "")).split("/")),
                str(value.get("path", "")),
            ),
        ),
        "operations": operations,
    }


def _journal_bound_directory_records(
    bindings: list[_DirectoryBinding],
) -> list[dict[str, object]]:
    """Serialize every exact pre-existing project directory binding once."""

    by_parts: dict[tuple[str, ...], tuple[int, ...]] = {}
    for binding in bindings:
        parts = binding.project_relative_parts
        if parts is None or binding.created or _is_reserved_transaction_path(parts):
            continue
        previous = by_parts.get(parts)
        if previous is not None and previous != binding.identity:
            raise BootstrapTransactionError(
                "pre-existing project directory was rebound to a different inode: "
                + ("." if not parts else "/".join(parts))
            )
        by_parts[parts] = binding.identity
    if () not in by_parts:
        raise BootstrapTransactionError(
            "project root binding is unavailable for recovery journaling"
        )
    return [
        {
            "path": "." if not parts else "/".join(parts),
            "identity": list(by_parts[parts]),
        }
        for parts in sorted(by_parts, key=lambda value: (len(value), value))
    ]


def _open_recovery_directory(
    root: _DirectoryBinding,
    parts: tuple[str, ...],
    cache: dict[tuple[str, ...], _DirectoryBinding],
    all_bindings: list[_DirectoryBinding],
) -> _DirectoryBinding | None:
    parent = root
    for depth, part in enumerate(parts, start=1):
        key = parts[:depth]
        existing = cache.get(key)
        if existing is None:
            existing = next(
                (
                    binding
                    for binding in all_bindings
                    if binding.active and binding.project_relative_parts == key
                ),
                None,
            )
            if existing is not None:
                cache[key] = existing
        if existing is not None:
            parent = existing
            continue
        try:
            parent = _open_bound_directory(
                parent,
                part,
                label=f"bootstrap recovery directory {'/'.join(key)}",
                create=False,
                require_owner=True,
                created_bindings=[],
                all_bindings=all_bindings,
            )
        except FileNotFoundError:
            return None
        cache[key] = parent
    return parent


def _recovery_bound_directory_bindings(
    root: _DirectoryBinding,
    payload: Mapping[str, object],
    all_bindings: list[_DirectoryBinding],
) -> tuple[dict[tuple[str, ...], _DirectoryBinding], list[str]]:
    """Rebind every journaled pre-existing directory to its exact inode."""

    cache: dict[tuple[str, ...], _DirectoryBinding] = {(): root}
    errors: list[str] = []
    raw_entries = payload.get("bound_directories")
    if not isinstance(raw_entries, list):
        return cache, ["bootstrap recovery bound_directories are unavailable"]
    retired_parts: set[tuple[str, ...]] = set()
    raw_retired = payload.get("retired_directories")
    if isinstance(raw_retired, list):
        for entry in raw_retired:
            path = entry.get("path") if isinstance(entry, dict) else None
            if isinstance(path, str):
                try:
                    retired_parts.add(_relative_output_parts(path))
                except ValueError:
                    pass
    phase = payload.get("phase")
    parsed: list[tuple[tuple[str, ...], object]] = []
    for entry in raw_entries:
        if not isinstance(entry, dict):
            continue
        path = entry.get("path")
        if path == ".":
            parts: tuple[str, ...] = ()
        elif isinstance(path, str):
            try:
                parts = _relative_output_parts(path)
            except ValueError:
                continue
        else:
            continue
        parsed.append((parts, entry.get("identity")))
    for parts, raw_identity in sorted(parsed, key=lambda value: (len(value[0]), value[0])):
        expected_identity = _journal_directory_identity(raw_identity)
        if expected_identity is None:
            errors.append(
                "bootstrap recovery pre-existing directory identity is invalid: "
                + ("." if not parts else "/".join(parts))
            )
            continue
        if not parts:
            binding = root
        else:
            try:
                binding = _open_recovery_directory(
                    root,
                    parts,
                    cache,
                    all_bindings,
                )
            except (OSError, ValueError) as exc:
                errors.append(
                    "bootstrap recovery pre-existing directory could not be bound: "
                    f"{'/'.join(parts)}: {exc}"
                )
                continue
            if binding is None:
                retired_missing = phase == "verified" and any(
                    len(retired) <= len(parts) and parts[: len(retired)] == retired
                    for retired in retired_parts
                )
                if retired_missing:
                    continue
                errors.append(
                    "bootstrap recovery pre-existing directory is missing: "
                    f"{'/'.join(parts)}"
                )
                continue
        if binding.identity != expected_identity:
            errors.append(
                "bootstrap recovery pre-existing directory identity changed: "
                + ("." if not parts else "/".join(parts))
            )
            continue
        cache[parts] = binding
    return cache, errors


def _recovery_operation_views(
    root: _DirectoryBinding,
    payload: dict[str, object],
    all_bindings: list[_DirectoryBinding],
) -> tuple[list[_RecoveryOperationView], list[str]]:
    views: list[_RecoveryOperationView] = []
    errors: list[str] = []
    cache: dict[tuple[str, ...], _DirectoryBinding] = {(): root}
    operations = payload.get("operations")
    if not isinstance(operations, list):
        return views, ["bootstrap recovery journal operations are unavailable"]
    phase = payload.get("phase")
    rollback_capable = phase in {"preparing", "prepared", "applying"}
    created_parent_parts: set[tuple[str, ...]] = set()
    raw_created_directories = payload.get("created_directories")
    if isinstance(raw_created_directories, list):
        for entry in raw_created_directories:
            path = entry.get("path") if isinstance(entry, dict) else None
            if not isinstance(path, str):
                continue
            try:
                created_parent_parts.add(_relative_output_parts(path))
            except ValueError:
                continue
    retired_directory_parts: set[tuple[str, ...]] = set()
    raw_retired_directories = payload.get("retired_directories")
    if isinstance(raw_retired_directories, list):
        for entry in raw_retired_directories:
            path = entry.get("path") if isinstance(entry, dict) else None
            if not isinstance(path, str):
                continue
            try:
                retired_directory_parts.add(_relative_output_parts(path))
            except ValueError:
                continue
    transaction_cache: dict[str, _TransactionDirectory | None] = {}
    allowed_artifacts: dict[str, set[str]] = {}
    recognized_quarantines: dict[str, set[str]] = {}
    for index, raw_operation in enumerate(operations):
        if not isinstance(raw_operation, dict):
            errors.append(f"bootstrap recovery operation {index} is not an object")
            continue
        operation = dict(raw_operation)
        path = operation.get("path")
        transaction_path = operation.get("transaction_directory")
        if not isinstance(path, str) or not isinstance(transaction_path, str):
            errors.append(f"bootstrap recovery operation {index} lacks bounded paths")
            continue
        allowed = allowed_artifacts.setdefault(transaction_path, set())
        for artifact_key in ("stage_name", "backup_name"):
            artifact_name = operation.get(artifact_key)
            if isinstance(artifact_name, str):
                allowed.add(artifact_name)
        quarantines = recognized_quarantines.setdefault(transaction_path, set())
        for artifact in ("target", "stage", "backup"):
            quarantine_name = _recovery_quarantine_name(index, artifact)
            quarantines.add(quarantine_name)
            allowed.add(quarantine_name)
        parts = _relative_output_parts(path)
        parent = _open_recovery_directory(root, parts[:-1], cache, all_bindings)
        if parent is None:
            parent_was_planned = any(
                len(created_parts) <= len(parts[:-1])
                and parts[: len(created_parts)] == created_parts
                for created_parts in created_parent_parts
            )
            already_rolled_back = (
                rollback_capable
                and parent_was_planned
                and operation.get("original") is None
            )
            already_retired = (
                phase == "verified"
                and operation.get("action") == "remove"
                and any(
                    len(retired_parts) <= len(parts[:-1])
                    and parts[: len(retired_parts)] == retired_parts
                    for retired_parts in retired_directory_parts
                )
            )
            if not (already_rolled_back or already_retired):
                errors.append(f"bootstrap recovery target parent is missing: {path}")
                continue
        if transaction_path in transaction_cache:
            transaction_directory = transaction_cache[transaction_path]
        else:
            transaction_parts = _relative_output_parts(transaction_path)
            transaction_binding = _open_recovery_directory(
                root,
                transaction_parts,
                cache,
                all_bindings,
            )
            if transaction_binding is None:
                transaction_directory = None
            else:
                metadata = os.fstat(_binding_descriptor(transaction_binding))
                if stat.S_IMODE(metadata.st_mode) & 0o077:
                    errors.append(
                        f"bootstrap recovery transaction directory is not owner-only: {transaction_path}"
                    )
                transaction_parent = transaction_binding.parent
                if transaction_parent is None:
                    errors.append(
                        "bootstrap recovery transaction directory lacks its bound parent: "
                        f"{transaction_path}"
                    )
                    transaction_directory = None
                else:
                    transaction_directory = _TransactionDirectory(
                        parent=transaction_parent,
                        binding=transaction_binding,
                        relative_path=transaction_path,
                    )
            transaction_cache[transaction_path] = transaction_directory
        try:
            target_evidence = (
                _file_evidence_at(
                    parent,
                    parts[-1],
                    description=f"bootstrap recovery target {path}",
                )
                if parent is not None
                else None
            )
            if transaction_directory is None:
                stage_evidence = None
                backup_evidence = None
                target_quarantine_evidence = None
                stage_quarantine_evidence = None
                backup_quarantine_evidence = None
            else:
                stage_name = operation.get("stage_name")
                backup_name = operation.get("backup_name")
                stage_evidence = (
                    _file_evidence_at(
                        transaction_directory.binding,
                        stage_name,
                        description=f"bootstrap recovery stage for {path}",
                    )
                    if isinstance(stage_name, str)
                    else None
                )
                backup_evidence = (
                    _file_evidence_at(
                        transaction_directory.binding,
                        backup_name,
                        description=f"bootstrap recovery backup for {path}",
                    )
                    if isinstance(backup_name, str)
                    else None
                )
                quarantine_evidence: dict[str, dict[str, object] | None] = {}
                for artifact in ("target", "stage", "backup"):
                    quarantine_name = _recovery_quarantine_name(index, artifact)
                    quarantine_evidence[artifact] = _file_evidence_at(
                        transaction_directory.binding,
                        quarantine_name,
                        description=(
                            f"bootstrap recovery {artifact} quarantine for {path}"
                        ),
                    )
                target_quarantine_evidence = quarantine_evidence["target"]
                stage_quarantine_evidence = quarantine_evidence["stage"]
                backup_quarantine_evidence = quarantine_evidence["backup"]
        except (OSError, ValueError) as exc:
            errors.append(str(exc))
            continue
        views.append(
            _RecoveryOperationView(
                operation=operation,
                parent=parent,
                transaction_directory=transaction_directory,
                target_evidence=target_evidence,
                stage_evidence=stage_evidence,
                backup_evidence=backup_evidence,
                target_quarantine_evidence=target_quarantine_evidence,
                stage_quarantine_evidence=stage_quarantine_evidence,
                backup_quarantine_evidence=backup_quarantine_evidence,
            )
        )
    for transaction_path, transaction_directory in transaction_cache.items():
        if transaction_directory is None:
            continue
        try:
            with os.scandir(
                _binding_descriptor(transaction_directory.binding)
            ) as iterator:
                actual_artifacts = {entry.name for entry in iterator}
        except OSError as exc:
            errors.append(
                "bootstrap recovery transaction directory could not be enumerated: "
                f"{transaction_path}: {exc}"
            )
            continue
        unexpected = sorted(
            actual_artifacts - allowed_artifacts.get(transaction_path, set())
        )
        if unexpected:
            errors.append(
                "bootstrap recovery transaction directory contains unrelated "
                f"artifacts: {transaction_path}: {', '.join(unexpected)}"
            )
    return views, errors


def _journal_directory_identity(value: object) -> tuple[int, ...] | None:
    if (
        not isinstance(value, list)
        or len(value) != 5
        or any(type(item) is not int or item < 0 for item in value)
    ):
        return None
    return tuple(value)


def _recovery_created_directory_bindings(
    payload: dict[str, object],
    all_bindings: list[_DirectoryBinding],
) -> tuple[list[_DirectoryBinding], list[str], list[str]]:
    """Bind exact journaled new directories without trusting absolute path text."""

    errors: list[str] = []
    inside_bindings: list[_DirectoryBinding] = []
    unknown_identity_paths: list[str] = []
    bindings_by_parts = {
        binding.project_relative_parts: binding
        for binding in all_bindings
        if binding.project_relative_parts is not None
    }
    phase = payload.get("phase")
    preparing = phase == "preparing"
    rollback_capable = phase in {"preparing", "prepared", "applying"}
    operations = payload.get("operations")

    def missing_directory_is_already_rolled_back(
        parts: tuple[str, ...],
    ) -> bool:
        if not rollback_capable or not isinstance(operations, list):
            return False
        affected: list[dict[str, object]] = []
        for operation in operations:
            if not isinstance(operation, dict):
                return False
            operation_path = operation.get("path")
            if not isinstance(operation_path, str):
                return False
            try:
                operation_parts = _relative_output_parts(operation_path)
            except ValueError:
                return False
            if (
                len(parts) < len(operation_parts)
                and operation_parts[: len(parts)] == parts
            ):
                affected.append(operation)
        return bool(affected) and all(
            operation.get("original") is None for operation in affected
        )

    created_directories = payload.get("created_directories")
    if not isinstance(created_directories, list):
        errors.append("bootstrap recovery created_directories are unavailable")
    else:
        for index, entry in enumerate(created_directories):
            if not isinstance(entry, dict):
                errors.append(
                    f"bootstrap recovery created directory {index} is not an object"
                )
                continue
            path = entry.get("path")
            if not isinstance(path, str):
                errors.append(
                    f"bootstrap recovery created directory {index} lacks a path"
                )
                continue
            try:
                parts = _relative_output_parts(path)
            except ValueError as exc:
                errors.append(str(exc))
                continue
            binding = bindings_by_parts.get(parts)
            expected_identity = _journal_directory_identity(entry.get("identity"))
            if binding is None:
                if not missing_directory_is_already_rolled_back(parts):
                    errors.append(
                        f"bootstrap recovery created directory is missing: {path}"
                    )
                continue
            if (
                expected_identity is None
                and preparing
                and entry.get("identity") is None
            ):
                # A crash can occur after mkdir but before its inode identity is
                # durably journaled. Never interpret the currently bound path as
                # transaction-owned in that state: another process may have
                # replaced it after the crash. Recovery may restore file state,
                # but it must retain this directory for bounded manual review.
                unknown_identity_paths.append(path)
            elif expected_identity is None or binding.identity != expected_identity:
                errors.append(
                    f"bootstrap recovery created directory identity changed: {path}"
                )
            else:
                inside_bindings.append(binding)
    inside_bindings.sort(
        key=lambda binding: (
            len(binding.project_relative_parts or ()),
            binding.project_relative_parts or (),
        )
    )
    return inside_bindings, unknown_identity_paths, errors


def _unknown_created_directory_errors(paths: list[str]) -> list[str]:
    if not paths:
        return []
    preview = ", ".join(paths[:8])
    remainder = len(paths) - 8
    if remainder > 0:
        preview += f", and {remainder} more"
    return [
        "bootstrap recovery retained newly created directory paths whose exact "
        "journaled identity is unknown; inspect them as project content and "
        "reconcile only paths proved safe through a project-specific manual "
        f"cleanup before inspecting recovery again: {preview}"
    ]


def _recovery_retired_directory_bindings(
    root: _DirectoryBinding,
    payload: dict[str, object],
    all_bindings: list[_DirectoryBinding],
) -> tuple[list[_DirectoryBinding], list[str]]:
    """Bind and inventory the exact directory forest selected for retirement."""

    errors: list[str] = []
    inside_bindings: list[_DirectoryBinding] = []
    raw_entries = payload.get("retired_directories")
    if not isinstance(raw_entries, list):
        return [], ["bootstrap recovery retired_directories are unavailable"]
    parsed: list[tuple[tuple[str, ...], dict[str, object]]] = []
    for index, entry in enumerate(raw_entries):
        if not isinstance(entry, dict):
            errors.append(
                f"bootstrap recovery retired directory {index} is not an object"
            )
            continue
        path = entry.get("path")
        if not isinstance(path, str):
            errors.append(
                f"bootstrap recovery retired directory {index} lacks a path"
            )
            continue
        try:
            parsed.append((_relative_output_parts(path), entry))
        except ValueError as exc:
            errors.append(str(exc))
    parsed.sort(key=lambda value: (len(value[0]), value[0]))
    retired_parts = {parts for parts, _entry in parsed}
    operations = payload.get("operations")
    removal_parts: list[tuple[str, ...]] = []
    direct_transaction_names: dict[tuple[str, ...], set[str]] = {
        parts: set() for parts in retired_parts
    }
    if isinstance(operations, list):
        for operation in operations:
            if not isinstance(operation, dict):
                continue
            operation_path = operation.get("path")
            transaction_path = operation.get("transaction_directory")
            if operation.get("action") == "remove" and isinstance(
                operation_path, str
            ):
                try:
                    removal_parts.append(_relative_output_parts(operation_path))
                except ValueError:
                    pass
            if isinstance(transaction_path, str):
                try:
                    transaction_parts = _relative_output_parts(transaction_path)
                except ValueError:
                    continue
                parent_parts = transaction_parts[:-1]
                if parent_parts in direct_transaction_names:
                    direct_transaction_names[parent_parts].add(transaction_parts[-1])
    expected_children, topology_errors = _retirement_expected_children(
        retired_parts,
        removal_parts,
    )
    errors.extend(
        "bootstrap recovery " + error for error in topology_errors
    )
    phase = payload.get("phase")
    cache: dict[tuple[str, ...], _DirectoryBinding] = {(): root}
    bindings_by_parts: dict[tuple[str, ...], _DirectoryBinding] = {}
    for parts, entry in parsed:
        try:
            binding = _open_recovery_directory(root, parts, cache, all_bindings)
        except (OSError, ValueError) as exc:
            errors.append(
                "bootstrap recovery retired directory could not be bound: "
                f"{'/'.join(parts)}: {exc}"
            )
            continue
        if binding is None:
            if phase != "verified":
                errors.append(
                    "bootstrap recovery retired directory is missing before "
                    f"verified cleanup: {'/'.join(parts)}"
                )
            continue
        expected_identity = _journal_directory_identity(entry.get("identity"))
        if expected_identity is None or binding.identity != expected_identity:
            errors.append(
                "bootstrap recovery retired directory identity changed: "
                f"{'/'.join(parts)}"
            )
            continue
        bindings_by_parts[parts] = binding
        inside_bindings.append(binding)
    immediate_retired_children: dict[tuple[str, ...], set[str]] = {
        parts: {
            child[-1]
            for child in retired_parts
            if len(child) == len(parts) + 1 and child[: len(parts)] == parts
        }
        for parts in retired_parts
    }
    for parts, binding in bindings_by_parts.items():
        allowed = set(immediate_retired_children.get(parts, set()))
        allowed.update(direct_transaction_names.get(parts, set()))
        if phase != "verified":
            allowed.update(expected_children.get(parts, set()))
        try:
            actual = _directory_entries(binding)
        except OSError as exc:
            errors.append(
                "bootstrap recovery retired directory could not be enumerated: "
                f"{'/'.join(parts)}: {exc}"
            )
            continue
        unexpected = sorted(actual - allowed)
        if unexpected:
            errors.append(
                "bootstrap recovery retired directory contains unrelated "
                f"entries: {'/'.join(parts)}: {', '.join(unexpected)}"
            )
    inside_bindings.sort(
        key=lambda binding: (
            len(binding.project_relative_parts or ()),
            binding.project_relative_parts or (),
        )
    )
    return inside_bindings, errors


def _recovery_status_from_payload(
    payload: dict[str, object],
    views: list[_RecoveryOperationView],
    errors: list[str],
) -> BootstrapRecoveryStatus:
    raw_phase = payload.get("phase")
    phase = raw_phase if isinstance(raw_phase, str) else None
    raw_transaction_id = payload.get("transaction_id")
    transaction_id = raw_transaction_id if isinstance(raw_transaction_id, str) else None
    operations = payload.get("operations")
    operation_path_list: list[str] = []
    if isinstance(operations, list):
        for operation in operations:
            if not isinstance(operation, dict):
                continue
            path = operation.get("path")
            if isinstance(path, str):
                operation_path_list.append(path)
    operation_paths = tuple(operation_path_list)
    can_rollback = phase in {"preparing", "prepared", "applying"} and not errors
    can_finalize = phase == "verified" and not errors
    preapply = phase in {"preparing", "prepared"}
    for view in views:
        operation = view.operation
        action = operation.get("action")
        original = operation.get("original")
        candidate = operation.get("candidate")
        target_is_original = _evidence_matches(view.target_evidence, original)
        target_is_candidate = _evidence_matches(view.target_evidence, candidate)
        backup_is_original = _evidence_matches(view.backup_evidence, original)
        stage_is_candidate = _evidence_matches(view.stage_evidence, candidate)
        target_quarantine_is_candidate = _evidence_matches(
            view.target_quarantine_evidence,
            candidate,
        )
        backup_quarantine_is_original = _evidence_matches(
            view.backup_quarantine_evidence,
            original,
        )
        stage_quarantine_is_candidate = _evidence_matches(
            view.stage_quarantine_evidence,
            candidate,
        )
        if view.target_evidence is not None and not (
            target_is_original or target_is_candidate
        ):
            errors.append(f"unexpected recovery target bytes: {operation.get('path')}")
        elif preapply and view.target_evidence is not None and not target_is_original:
            errors.append(
                "recovery target changed before bootstrap installation: "
                f"{operation.get('path')}"
            )
        if view.backup_evidence is not None and (
            preapply or not backup_is_original
        ):
            errors.append(f"unexpected recovery backup bytes: {operation.get('path')}")
        if view.target_quarantine_evidence is not None and (
            preapply
            or view.target_evidence is not None
            or not target_quarantine_is_candidate
        ):
            errors.append(
                "unexpected recovery target quarantine bytes or topology: "
                f"{operation.get('path')}"
            )
        if view.backup_quarantine_evidence is not None and (
            preapply
            or view.backup_evidence is not None
            or not backup_quarantine_is_original
        ):
            errors.append(
                "unexpected recovery backup quarantine bytes or topology: "
                f"{operation.get('path')}"
            )
        if (
            view.stage_evidence is not None
            and not stage_is_candidate
            and phase != "preparing"
        ):
            errors.append(f"unexpected recovery stage bytes: {operation.get('path')}")
        if view.stage_quarantine_evidence is not None and (
            view.stage_evidence is not None
            or phase != "preparing" and not stage_quarantine_is_candidate
        ):
            errors.append(
                "unexpected recovery stage quarantine bytes or topology: "
                f"{operation.get('path')}"
            )
        candidate_available = target_is_candidate or target_quarantine_is_candidate
        backup_available = backup_is_original or backup_quarantine_is_original
        if preapply:
            rollback_ok = (
                target_is_original
                if original is not None
                else view.target_evidence is None
            )
            finalize_ok = False
        elif action == "write":
            if original is None:
                rollback_ok = view.target_evidence is None or candidate_available
            else:
                rollback_ok = target_is_original or (
                    backup_available
                    and (view.target_evidence is None or candidate_available)
                )
            finalize_ok = target_is_candidate
        else:
            rollback_ok = target_is_original or (
                backup_available and view.target_evidence is None
            )
            finalize_ok = view.target_evidence is None
        can_rollback = can_rollback and rollback_ok
        can_finalize = can_finalize and finalize_ok
    if len(views) != len(operation_paths):
        errors.append("not every bootstrap recovery operation could be inspected")
        can_rollback = False
        can_finalize = False
    if errors:
        can_rollback = False
        can_finalize = False
        state = "invalid"
    elif can_finalize:
        state = "verified"
    elif can_rollback:
        state = "recovery-required"
    else:
        state = "invalid"
    return BootstrapRecoveryStatus(
        state=state,
        transaction_id=transaction_id,
        phase=phase,
        operation_paths=operation_paths,
        can_rollback=can_rollback,
        can_finalize=can_finalize,
        errors=tuple(errors),
    )


def _clean_recovery_status() -> BootstrapRecoveryStatus:
    return BootstrapRecoveryStatus(
        state="clean",
        transaction_id=None,
        phase=None,
        operation_paths=(),
        can_rollback=False,
        can_finalize=False,
        errors=(),
    )


def transaction_recovery_status(project_root: Path) -> BootstrapRecoveryStatus:
    """Inspect transaction state without creating or changing project files.

    Callers must treat ``active`` as busy, not as an interrupted transaction.
    Only capability flags on a status with an observed transaction ID authorize
    the matching ID-bound recovery helper.
    """

    _require_transaction_support()
    all_bindings: list[_DirectoryBinding] = []
    lock_descriptor: int | None = None
    root: _DirectoryBinding | None = None
    try:
        root = _open_project_root_transaction(
            project_root,
            all_bindings=all_bindings,
        )
        if fcntl is None:
            raise ValueError(
                "transactional bootstrap writes require POSIX advisory flock support"
            )
        try:
            fcntl.flock(
                _binding_descriptor(root),
                fcntl.LOCK_SH | fcntl.LOCK_NB,
            )
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN}:
                return BootstrapRecoveryStatus(
                    state="active",
                    transaction_id=None,
                    phase=None,
                    operation_paths=(),
                    can_rollback=False,
                    can_finalize=False,
                    errors=(),
                )
            raise
        lock_metadata = _lstat_at(root, TRANSACTION_LOCK_NAME)
        journal_metadata = _lstat_at(root, RECOVERY_JOURNAL_NAME)
        temporary_metadata = _journal_temporary_metadata(root)
        previous_metadata = _journal_previous_metadata(root)
        if (
            lock_metadata is None
            and journal_metadata is None
            and temporary_metadata is None
            and previous_metadata is None
        ):
            orphan_errors = _initialization_transaction_artifact_errors(root)
            if not orphan_errors:
                return _clean_recovery_status()
            return BootstrapRecoveryStatus(
                state="invalid",
                transaction_id=None,
                phase=None,
                operation_paths=(),
                can_rollback=False,
                can_finalize=False,
                errors=tuple(orphan_errors),
            )
        if lock_metadata is not None:
            try:
                lock_descriptor, _lock_created = _acquire_project_lock(
                    root,
                    exclusive=False,
                    create=False,
                )
            except BootstrapTransactionError:
                return BootstrapRecoveryStatus(
                    state="active",
                    transaction_id=None,
                    phase=None,
                    operation_paths=(),
                    can_rollback=False,
                    can_finalize=False,
                    errors=(),
                )
        if (
            journal_metadata is not None or previous_metadata is not None
        ) and lock_descriptor is None:
            return BootstrapRecoveryStatus(
                state="invalid",
                transaction_id=None,
                phase=None,
                operation_paths=(),
                can_rollback=False,
                can_finalize=False,
                errors=(
                    "bootstrap recovery journal exists without its original "
                    "transaction lock",
                ),
            )
        if lock_descriptor is None:
            payload, journal_errors = _read_recovery_journal(root)
        else:
            payload, journal_errors, _previous_identity = (
                _select_recovery_journal(root, lock_descriptor)
            )
        if payload is None:
            if journal_errors:
                return BootstrapRecoveryStatus(
                    state="invalid",
                    transaction_id=None,
                    phase=None,
                    operation_paths=(),
                    can_rollback=False,
                    can_finalize=False,
                    errors=tuple(journal_errors),
                )
            if journal_metadata is None and lock_descriptor is not None:
                transaction_id = _project_lock_transaction_id(
                    root,
                    lock_descriptor,
                )
                initialization_errors = _initialization_transaction_artifact_errors(
                    root
                )
                return BootstrapRecoveryStatus(
                    state=(
                        "invalid"
                        if initialization_errors
                        else "recovery-required"
                    ),
                    transaction_id=transaction_id,
                    phase="initializing",
                    operation_paths=(),
                    can_rollback=not initialization_errors,
                    can_finalize=False,
                    errors=tuple(initialization_errors),
                )
            return BootstrapRecoveryStatus(
                state="invalid",
                transaction_id=None,
                phase=None,
                operation_paths=(),
                can_rollback=False,
                can_finalize=False,
                errors=(
                    (
                        "an incomplete bootstrap recovery journal temporary file "
                        "exists without a canonical journal"
                        if temporary_metadata is not None
                        else "bootstrap project transaction lock exists without a recovery journal"
                    ),
                ),
            )
        if lock_descriptor is None:
            return BootstrapRecoveryStatus(
                state="invalid",
                transaction_id=None,
                phase=None,
                operation_paths=(),
                can_rollback=False,
                can_finalize=False,
                errors=(
                    "bootstrap recovery journal exists without its original "
                    "transaction lock",
                ),
            )
        journal_errors.extend(
            _recovery_journal_identity_errors(
                root,
                lock_descriptor,
                payload,
            )
        )
        _bound_cache, bound_errors = _recovery_bound_directory_bindings(
            root,
            payload,
            all_bindings,
        )
        views, view_errors = _recovery_operation_views(root, payload, all_bindings)
        (
            _inside,
            unknown_created,
            created_errors,
        ) = _recovery_created_directory_bindings(payload, all_bindings)
        _retired_inside, retired_errors = _recovery_retired_directory_bindings(
            root,
            payload,
            all_bindings,
        )
        return _recovery_status_from_payload(
            payload,
            views,
            [
                *journal_errors,
                *bound_errors,
                *view_errors,
                *created_errors,
                *_unknown_created_directory_errors(unknown_created),
                *retired_errors,
            ],
        )
    except (OSError, ValueError) as exc:
        return BootstrapRecoveryStatus(
            state="invalid",
            transaction_id=None,
            phase=None,
            operation_paths=(),
            can_rollback=False,
            can_finalize=False,
            errors=(str(exc),),
        )
    finally:
        _cleanup_transaction_resources(
            root,
            lock_descriptor,
            all_bindings,
            primary=sys.exception(),
        )


def _recovery_transaction_directories(
    views: list[_RecoveryOperationView],
) -> list[_TransactionDirectory]:
    unique: dict[str, _TransactionDirectory] = {}
    for view in views:
        transaction_directory = view.transaction_directory
        if transaction_directory is not None:
            unique[transaction_directory.relative_path] = transaction_directory
    return list(unique.values())


def _recovery_terminal_state_errors(
    views: list[_RecoveryOperationView],
    *,
    action: str,
) -> list[str]:
    """Re-read every target and artifact before recovery controls may retire."""

    errors: list[str] = []
    for index, view in enumerate(views):
        operation = view.operation
        path = operation.get("path")
        if not isinstance(path, str):
            errors.append("bootstrap recovery terminal operation path is missing")
            continue
        expected = (
            operation.get("original")
            if action == "rollback"
            else operation.get("candidate")
        )
        try:
            if view.parent is None:
                actual = None
            else:
                target_name = _relative_output_parts(path)[-1]
                actual = (
                    _file_evidence_at(
                        view.parent,
                        target_name,
                        description=f"bootstrap recovery terminal target {path}",
                    )
                    if _lstat_at(view.parent, target_name) is not None
                    else None
                )
            if expected is None:
                if actual is not None:
                    errors.append(
                        "bootstrap recovery did not restore approved target "
                        f"absence: {path}"
                    )
            elif not _evidence_matches(actual, expected):
                errors.append(
                    "bootstrap recovery target does not match its exact terminal "
                    f"evidence: {path}"
                )
            transaction_directory = view.transaction_directory
            if transaction_directory is not None:
                artifact_names = [
                    operation.get("stage_name"),
                    operation.get("backup_name"),
                    *(
                        _recovery_quarantine_name(index, artifact)
                        for artifact in ("target", "stage", "backup")
                    ),
                ]
                for artifact_name in artifact_names:
                    if (
                        isinstance(artifact_name, str)
                        and _lstat_at(
                            transaction_directory.binding,
                            artifact_name,
                        )
                        is not None
                    ):
                        errors.append(
                            "bootstrap recovery retained a transaction artifact "
                            f"after {action}: {path}: {artifact_name}"
                        )
        except (OSError, ValueError) as exc:
            errors.append(
                f"bootstrap recovery terminal state could not be verified for {path}: {exc}"
            )
    return errors


def _recover_interrupted_transaction(
    project_root: Path,
    *,
    expected_transaction_id: str,
    action: str,
) -> BootstrapRecoveryStatus:
    _require_transaction_support()
    if action not in {"rollback", "finalize"}:
        raise ValueError(f"unsupported bootstrap recovery action: {action}")
    if (
        len(expected_transaction_id) != 32
        or any(character not in "0123456789abcdef" for character in expected_transaction_id)
    ):
        raise ValueError("expected_transaction_id must be 32 lowercase hex characters")
    all_bindings: list[_DirectoryBinding] = []
    lock_descriptor: int | None = None
    root: _DirectoryBinding | None = None
    try:
        root = _open_project_root_transaction(
            project_root,
            all_bindings=all_bindings,
        )
        if fcntl is None:
            raise ValueError(
                "transactional bootstrap writes require POSIX advisory flock support"
            )
        try:
            fcntl.flock(
                _binding_descriptor(root),
                fcntl.LOCK_EX | fcntl.LOCK_NB,
            )
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN}:
                raise BootstrapTransactionError(
                    "another bootstrap transaction holds the project lock"
                ) from exc
            raise
        lock_missing = _lstat_at(root, TRANSACTION_LOCK_NAME) is None
        journal_missing = _lstat_at(root, RECOVERY_JOURNAL_NAME) is None
        if lock_missing and journal_missing:
            raise BootstrapTransactionError(
                "bootstrap recovery cannot proceed without recorded transaction controls"
            )
        if lock_missing and not journal_missing:
            raise BootstrapTransactionError(
                "bootstrap recovery journal exists without its original "
                "transaction lock"
            )
        if not lock_missing:
            lock_descriptor, _lock_created = _acquire_project_lock(
                root,
                exclusive=True,
                create=False,
            )
        if lock_descriptor is None:
            payload, journal_errors = _read_recovery_journal(root)
            previous_identity = None
        else:
            payload, journal_errors, previous_identity = _select_recovery_journal(
                root,
                lock_descriptor,
            )
        if payload is None:
            if journal_errors:
                raise BootstrapTransactionError("; ".join(journal_errors))
            if lock_descriptor is None or not journal_missing:
                raise BootstrapTransactionError(
                    "bootstrap recovery cannot proceed without a recovery journal"
                )
            transaction_id = _project_lock_transaction_id(root, lock_descriptor)
            if transaction_id != expected_transaction_id:
                raise BootstrapTransactionError(
                    "bootstrap recovery transaction identity changed after inspection"
                )
            if action != "rollback":
                raise BootstrapTransactionError(
                    "bootstrap transaction cannot be finalized: phase "
                    "'initializing' permits rollback only"
                )
            temporary = _journal_temporary_metadata(root)
            temporary_identity = (
                None if temporary is None else _inode_object_identity(temporary)
            )
            initialization_errors = _initialization_transaction_artifact_errors(root)
            if initialization_errors:
                raise BootstrapTransactionError("; ".join(initialization_errors))
            _verify_project_lock(root, lock_descriptor)
            _verify_bound_directories(all_bindings)
            fresh_temporary = _journal_temporary_metadata(root)
            fresh_temporary_identity = (
                None
                if fresh_temporary is None
                else _inode_object_identity(fresh_temporary)
            )
            if fresh_temporary_identity != temporary_identity:
                raise BootstrapTransactionError(
                    "bootstrap recovery journal temporary file changed before "
                    "initialization cleanup"
                )
            fresh_initialization_errors = _initialization_transaction_artifact_errors(
                root
            )
            if fresh_initialization_errors:
                raise BootstrapTransactionError(
                    "; ".join(fresh_initialization_errors)
                )
            if fresh_temporary_identity is not None:
                _verify_transaction_context(root, lock_descriptor, all_bindings)
                _remove_recovery_journal_temporary(
                    root,
                    expected_object_identity=fresh_temporary_identity,
                )
                _verify_transaction_context(root, lock_descriptor, all_bindings)
            _verify_transaction_context(root, lock_descriptor, all_bindings)
            _remove_project_lock(root, lock_descriptor)
            _verify_bound_directories(all_bindings)
            return _clean_recovery_status()
        if lock_descriptor is None:
            raise BootstrapTransactionError(
                "bootstrap recovery journal exists without its original "
                "transaction lock"
            )
        identity_errors = _recovery_journal_identity_errors(
            root,
            lock_descriptor,
            payload,
        )
        if identity_errors:
            raise BootstrapTransactionError("; ".join(identity_errors))
        transaction_id = payload.get("transaction_id")
        if transaction_id != expected_transaction_id:
            raise BootstrapTransactionError(
                "bootstrap recovery transaction identity changed after inspection"
            )
        _bound_cache, bound_errors = _recovery_bound_directory_bindings(
            root,
            payload,
            all_bindings,
        )
        views, view_errors = _recovery_operation_views(root, payload, all_bindings)
        (
            _inside,
            unknown_created,
            created_errors,
        ) = _recovery_created_directory_bindings(payload, all_bindings)
        _retired_inside, retired_errors = _recovery_retired_directory_bindings(
            root,
            payload,
            all_bindings,
        )
        status = _recovery_status_from_payload(
            payload,
            views,
            [
                *journal_errors,
                *bound_errors,
                *view_errors,
                *created_errors,
                *_unknown_created_directory_errors(unknown_created),
                *retired_errors,
            ],
        )
        allowed = status.can_rollback if action == "rollback" else status.can_finalize
        if not allowed:
            detail = "; ".join(status.errors) or (
                f"phase {status.phase!r} does not permit {action}"
            )
            raise BootstrapTransactionError(
                f"bootstrap transaction cannot be {action}ed: {detail}"
            )
        _verify_project_lock(root, lock_descriptor)
        _verify_bound_directories(all_bindings)
        # Repeat the complete read-only preflight immediately before the first
        # recovery mutation. A later invalid operation must not leave an earlier
        # operation partially recovered.
        _fresh_bound_cache, fresh_bound_errors = (
            _recovery_bound_directory_bindings(
                root,
                payload,
                all_bindings,
            )
        )
        fresh_views, fresh_errors = _recovery_operation_views(root, payload, all_bindings)
        (
            created_inside,
            unknown_created_paths,
            fresh_created_errors,
        ) = _recovery_created_directory_bindings(payload, all_bindings)
        retired_inside, fresh_retired_errors = _recovery_retired_directory_bindings(
            root,
            payload,
            all_bindings,
        )
        fresh_status = _recovery_status_from_payload(
            payload,
            fresh_views,
            [
                *fresh_bound_errors,
                *fresh_errors,
                *fresh_created_errors,
                *_unknown_created_directory_errors(unknown_created_paths),
                *fresh_retired_errors,
            ],
        )
        fresh_allowed = (
            fresh_status.can_rollback if action == "rollback" else fresh_status.can_finalize
        )
        if not fresh_allowed:
            detail = "; ".join(fresh_status.errors) or "recovery evidence changed"
            raise BootstrapTransactionError(
                f"bootstrap transaction recovery preflight failed: {detail}"
            )
        views = fresh_views
        _verify_bound_directories(all_bindings)
        _verify_project_lock(root, lock_descriptor)
        if previous_identity is not None:
            _normalize_previous_recovery_journal(
                root,
                payload=payload,
                previous_identity=previous_identity,
            )
            _verify_project_lock(root, lock_descriptor)
        preapply = payload.get("phase") in {"preparing", "prepared"}
        for index in range(len(views) - 1, -1, -1):
            view = views[index]
            _verify_bound_directories(all_bindings)
            _verify_project_lock(root, lock_descriptor)
            operation = view.operation
            path = operation.get("path")
            if not isinstance(path, str):
                raise BootstrapTransactionError("bootstrap recovery operation path is missing")
            target_name = _relative_output_parts(path)[-1]
            transaction_directory = view.transaction_directory
            transaction_descriptor = (
                _binding_descriptor(transaction_directory.binding)
                if transaction_directory is not None
                else None
            )
            if action == "rollback":
                if not preapply:
                    original = operation.get("original")
                    if original is not None and not isinstance(original, dict):
                        raise BootstrapTransactionError(
                            f"bootstrap recovery original evidence is invalid: {path}"
                        )
                    if view.parent is None and original is not None:
                        raise BootstrapTransactionError(
                            f"bootstrap recovery target parent is missing: {path}"
                        )
                    if view.parent is not None:
                        if view.target_quarantine_evidence is not None:
                            if transaction_directory is None:
                                raise BootstrapTransactionError(
                                    "bootstrap recovery transaction directory is "
                                    f"unavailable for candidate quarantine: {path}"
                                )
                            quarantine_name = _recovery_quarantine_name(
                                index,
                                "target",
                            )
                            quarantined_identity = _verified_quarantine_identity(
                                transaction_directory.binding,
                                quarantine_name,
                                expected_evidence=operation.get("candidate"),
                                expected_payload_identity=None,
                                description=f"bootstrap recovery candidate {path}",
                            )
                            _retire_verified_quarantine(
                                transaction_directory.binding,
                                quarantine_name,
                                expected_evidence=operation.get("candidate"),
                                expected_payload_identity=quarantined_identity,
                                description=f"bootstrap recovery candidate {path}",
                            )
                            view.target_quarantine_evidence = None
                        elif _evidence_matches(
                            view.target_evidence,
                            operation.get("candidate"),
                        ):
                            if transaction_directory is None:
                                raise BootstrapTransactionError(
                                    "bootstrap recovery transaction directory is "
                                    f"unavailable for candidate quarantine: {path}"
                                )
                            quarantine_name = _recovery_quarantine_name(
                                index,
                                "target",
                            )
                            quarantined_identity = (
                                _move_file_to_verified_quarantine(
                                    view.parent,
                                    target_name,
                                    transaction_directory.binding,
                                    quarantine_name,
                                    expected_evidence=operation.get("candidate"),
                                    description=(
                                        f"bootstrap recovery candidate {path}"
                                    ),
                                )
                            )
                            _retire_verified_quarantine(
                                transaction_directory.binding,
                                quarantine_name,
                                expected_evidence=operation.get("candidate"),
                                expected_payload_identity=quarantined_identity,
                                description=f"bootstrap recovery candidate {path}",
                            )
                            view.target_evidence = None
                        if original is not None:
                            if _evidence_matches(view.target_evidence, original):
                                if (
                                    transaction_directory is not None
                                    and (
                                        _evidence_matches(
                                            view.backup_evidence,
                                            original,
                                        )
                                        or _evidence_matches(
                                            view.backup_quarantine_evidence,
                                            original,
                                        )
                                    )
                                ):
                                    backup_name = operation.get("backup_name")
                                    if not isinstance(backup_name, str):
                                        raise BootstrapTransactionError(
                                            "bootstrap recovery backup name is missing: "
                                            f"{path}"
                                        )
                                    quarantine_name = _recovery_quarantine_name(
                                        index,
                                        "backup",
                                    )
                                    if view.backup_quarantine_evidence is not None:
                                        quarantined_identity = (
                                            _verified_quarantine_identity(
                                                transaction_directory.binding,
                                                quarantine_name,
                                                expected_evidence=original,
                                                expected_payload_identity=None,
                                                description=(
                                                    "bootstrap recovery redundant "
                                                    f"backup {path}"
                                                ),
                                            )
                                        )
                                    else:
                                        quarantined_identity = (
                                            _move_file_to_verified_quarantine(
                                                transaction_directory.binding,
                                                backup_name,
                                                transaction_directory.binding,
                                                quarantine_name,
                                                expected_evidence=original,
                                                description=(
                                                    "bootstrap recovery redundant backup "
                                                    f"{path}"
                                                ),
                                            )
                                        )
                                    _retire_verified_quarantine(
                                        transaction_directory.binding,
                                        quarantine_name,
                                        expected_evidence=original,
                                        expected_payload_identity=(
                                            quarantined_identity
                                        ),
                                        description=(
                                            "bootstrap recovery redundant backup "
                                            f"{path}"
                                        ),
                                    )
                                    view.backup_evidence = None
                                    view.backup_quarantine_evidence = None
                            else:
                                backup_name = operation.get("backup_name")
                                if (
                                    transaction_directory is None
                                    or not isinstance(backup_name, str)
                                    or not (
                                        _evidence_matches(
                                            view.backup_evidence,
                                            original,
                                        )
                                        or _evidence_matches(
                                            view.backup_quarantine_evidence,
                                            original,
                                        )
                                    )
                                ):
                                    raise BootstrapTransactionError(
                                        "bootstrap recovery original is unavailable: "
                                        f"{path}"
                                    )
                                quarantine_name = _recovery_quarantine_name(
                                    index,
                                    "backup",
                                )
                                if view.backup_quarantine_evidence is not None:
                                    quarantined_identity = (
                                        _verified_quarantine_identity(
                                            transaction_directory.binding,
                                            quarantine_name,
                                            expected_evidence=original,
                                            expected_payload_identity=None,
                                            description=(
                                                f"bootstrap recovery backup {path}"
                                            ),
                                        )
                                    )
                                else:
                                    quarantined_identity = (
                                        _move_file_to_verified_quarantine(
                                            transaction_directory.binding,
                                            backup_name,
                                            transaction_directory.binding,
                                            quarantine_name,
                                            expected_evidence=original,
                                            description=(
                                                f"bootstrap recovery backup {path}"
                                            ),
                                        )
                                    )
                                _restore_verified_quarantine(
                                    transaction_directory.binding,
                                    quarantine_name,
                                    view.parent,
                                    target_name,
                                    expected_evidence=original,
                                    expected_payload_identity=quarantined_identity,
                                    description=f"bootstrap recovery backup {path}",
                                )
                                view.target_evidence = dict(original)
                                view.backup_evidence = None
                                view.backup_quarantine_evidence = None
                stage_name = operation.get("stage_name")
                if (
                    transaction_directory is not None
                    and isinstance(stage_name, str)
                    and (
                        view.stage_evidence is not None
                        or view.stage_quarantine_evidence is not None
                    )
                ):
                    expected_stage_evidence = (
                        (
                            view.stage_quarantine_evidence
                            if view.stage_quarantine_evidence is not None
                            else view.stage_evidence
                        )
                        if preapply
                        else operation.get("candidate")
                    )
                    quarantine_name = _recovery_quarantine_name(index, "stage")
                    if view.stage_quarantine_evidence is not None:
                        quarantined_identity = _verified_quarantine_identity(
                            transaction_directory.binding,
                            quarantine_name,
                            expected_evidence=expected_stage_evidence,
                            expected_payload_identity=None,
                            description=f"bootstrap recovery stage {path}",
                        )
                    else:
                        quarantined_identity = _move_file_to_verified_quarantine(
                            transaction_directory.binding,
                            stage_name,
                            transaction_directory.binding,
                            quarantine_name,
                            expected_evidence=expected_stage_evidence,
                            description=f"bootstrap recovery stage {path}",
                        )
                    _retire_verified_quarantine(
                        transaction_directory.binding,
                        quarantine_name,
                        expected_evidence=expected_stage_evidence,
                        expected_payload_identity=quarantined_identity,
                        description=f"bootstrap recovery stage {path}",
                    )
                    view.stage_evidence = None
                    view.stage_quarantine_evidence = None
            else:
                for (
                    artifact,
                    artifact_name,
                    artifact_evidence,
                    quarantine_evidence,
                    expected,
                ) in (
                    (
                        "stage",
                        operation.get("stage_name"),
                        view.stage_evidence,
                        view.stage_quarantine_evidence,
                        operation.get("candidate"),
                    ),
                    (
                        "backup",
                        operation.get("backup_name"),
                        view.backup_evidence,
                        view.backup_quarantine_evidence,
                        operation.get("original"),
                    ),
                ):
                    if (
                        transaction_directory is not None
                        and isinstance(artifact_name, str)
                        and (
                            artifact_evidence is not None
                            or quarantine_evidence is not None
                        )
                    ):
                        quarantine_name = _recovery_quarantine_name(index, artifact)
                        if quarantine_evidence is not None:
                            quarantined_identity = _verified_quarantine_identity(
                                transaction_directory.binding,
                                quarantine_name,
                                expected_evidence=expected,
                                expected_payload_identity=None,
                                description=(
                                    f"bootstrap recovery {artifact} {path}"
                                ),
                            )
                        else:
                            quarantined_identity = _move_file_to_verified_quarantine(
                                transaction_directory.binding,
                                artifact_name,
                                transaction_directory.binding,
                                quarantine_name,
                                expected_evidence=expected,
                                description=(
                                    f"bootstrap recovery {artifact} {path}"
                                ),
                            )
                        _retire_verified_quarantine(
                            transaction_directory.binding,
                            quarantine_name,
                            expected_evidence=expected,
                            expected_payload_identity=quarantined_identity,
                            description=(
                                f"bootstrap recovery {artifact} {path}"
                            ),
                        )
                        if artifact == "stage":
                            view.stage_evidence = None
                            view.stage_quarantine_evidence = None
                        else:
                            view.backup_evidence = None
                            view.backup_quarantine_evidence = None
            if view.parent is not None:
                os.fsync(_binding_descriptor(view.parent))
            if transaction_descriptor is not None:
                os.fsync(transaction_descriptor)
            _verify_transaction_context(root, lock_descriptor, all_bindings)
        _verify_transaction_context(root, lock_descriptor, all_bindings)
        terminal_errors = _recovery_terminal_state_errors(views, action=action)
        if terminal_errors:
            raise BootstrapTransactionError("; ".join(terminal_errors))
        cleanup_warnings = _remove_empty_transaction_directories(
            _recovery_transaction_directories(views)
        )
        if cleanup_warnings:
            raise BootstrapTransactionError("; ".join(cleanup_warnings))
        _verify_transaction_context(root, lock_descriptor, all_bindings)
        if action == "rollback":
            created_directory_errors = _remove_created_directories(created_inside)
            if created_directory_errors:
                raise BootstrapTransactionError("; ".join(created_directory_errors))
        else:
            retired_directory_errors = _retire_empty_directories(retired_inside)
            if retired_directory_errors:
                raise BootstrapTransactionError("; ".join(retired_directory_errors))
        _verify_transaction_context(root, lock_descriptor, all_bindings)
        _remove_recovery_journal_temporary(root)
        _verify_transaction_context(root, lock_descriptor, all_bindings)
        _remove_recovery_journal(root)
        _verify_transaction_context(root, lock_descriptor, all_bindings)
        _remove_project_lock(root, lock_descriptor)
        _verify_bound_directories(all_bindings)
        return _clean_recovery_status()
    except BootstrapTransactionError:
        raise
    except BaseException as exc:
        raise BootstrapTransactionError(
            f"bootstrap transaction {action} failed: {exc}"
        ) from exc
    finally:
        _cleanup_transaction_resources(
            root,
            lock_descriptor,
            all_bindings,
            primary=sys.exception(),
        )


def rollback_interrupted_transaction(
    project_root: Path,
    *,
    expected_transaction_id: str,
) -> BootstrapRecoveryStatus:
    """Restore exact pre-transaction file bytes for an inspected pending journal."""

    return _recover_interrupted_transaction(
        project_root,
        expected_transaction_id=expected_transaction_id,
        action="rollback",
    )


def finalize_interrupted_transaction(
    project_root: Path,
    *,
    expected_transaction_id: str,
) -> BootstrapRecoveryStatus:
    """Finalize cleanup for an inspected journal whose verifier durably passed."""

    return _recover_interrupted_transaction(
        project_root,
        expected_transaction_id=expected_transaction_id,
        action="finalize",
    )


def transactional_write_outputs(
    project_root: Path,
    ordered_outputs: list[tuple[str, str]],
    *,
    force: bool,
    remove_outputs: list[str] | None = None,
    retire_empty_directories: list[str] | None = None,
    expected_preimages: dict[str, str | None] | None = None,
    expected_preimage_modes: dict[str, int | None] | None = None,
    assert_preimages: dict[str, str] | None = None,
    assert_preimage_modes: dict[str, int] | None = None,
    assert_preimage_max_bytes: Mapping[str, int | None] | None = None,
    target_modes: dict[str, int] | None = None,
    retired_directory_modes: dict[str, int] | None = None,
    expected_project_root_identity: Mapping[str, object] | None = None,
    expected_directory_identities: Mapping[
        str,
        Mapping[str, object] | None,
    ] | None = None,
    post_install_verifier: Callable[[], None] | None = None,
    create_file_mode: int | None = None,
    create_directory_mode: int | None = None,
) -> BootstrapWriteResult:
    """Stage and install a complete bootstrap output set as one rollback unit.

    Paths are opened one component at a time with ``O_NOFOLLOW`` and retained
    directory descriptors. All bytes are written and fsynced before the first
    destination is changed. Existing outputs must be regular, single-link files
    owned by the invoking user; they move to same-filesystem private backups and
    are restored in reverse order if any later pre-commit operation fails.
    ``expected_preimages`` binds every planned write or removal to an approved
    SHA-256 digest (or to absence); optional exact-keyed mode companions bind the
    same preimages to POSIX rwx modes. ``assert_preimages`` protects disjoint
    files without staging them. Digest and mode are sampled together while the
    exclusive project lock is held, and asserted files are checked again
    immediately before durable commit. ``assert_preimage_max_bytes`` can impose
    an exact per-assertion bounded-read ceiling; null retains the established
    unbounded assertion behavior. ``target_modes`` applies an exact mode to every
    planned write rather than inheriting an existing mode or the creation default.
    ``retire_empty_directories`` names an exact, pre-existing directory forest
    that may be removed only after verified file commit. Every directory is
    descriptor-bound, journaled by identity, optionally bound to an exact-keyed
    mode map, required to contain only the named removal topology, and removed
    non-recursively deepest-first. Rollback never retires these directories;
    exact-ID finalize may resume verified cleanup.
    ``expected_project_root_identity`` and ``expected_directory_identities``
    carry reviewed directory-object identities (or an approved absence for a
    project-relative directory) into the descriptor-opening boundary. They are
    checked and retained before the project lock, journal, staging directory,
    or output graph can be created.
    Without ``target_modes``, explicit create modes are applied exactly to new
    files and directories after the platform umask and replacement files retain
    their original mode. ``None`` selects the standard umask-governed creation
    behavior.

    This primitive requires POSIX descriptor-relative, no-follow I/O and working
    advisory ``flock`` semantics. It intentionally does not claim native Windows
    or lock-unsafe/network-filesystem support. Directory bindings remain open
    through name-based ``rmdir`` calls, but POSIX has no identity-bound directory
    removal primitive; same-user project writers must honor the advisory lock.
    """

    _require_transaction_support()
    validated_project_root_identity = (
        None
        if expected_project_root_identity is None
        else _validated_expected_directory_identity(
            expected_project_root_identity,
            label="expected project root identity",
            allow_absent=False,
        )
    )
    validated_directory_identities = _validated_expected_directory_identities(
        expected_directory_identities
    )
    validated_file_mode = _validated_create_mode(create_file_mode, kind="file")
    validated_directory_mode = _validated_create_mode(
        create_directory_mode,
        kind="directory",
    )
    removals = [] if remove_outputs is None else list(remove_outputs)
    retirements = (
        []
        if retire_empty_directories is None
        else list(retire_empty_directories)
    )
    writes = list(ordered_outputs)
    if removals and not force:
        raise ValueError("explicit bootstrap removals require force=True")
    planned_names = [name for name, _content in writes] + removals
    if not planned_names:
        raise ValueError(
            "transactional bootstrap requires at least one planned write or removal"
        )
    seen_planned: set[str] = set()
    planned_parts: list[tuple[str, ...]] = []
    write_parts_by_name: dict[str, tuple[str, ...]] = {}
    removal_parts_by_name: dict[str, tuple[str, ...]] = {}
    for output_name in planned_names:
        if output_name in seen_planned:
            raise ValueError(f"duplicate bootstrap output path: {output_name}")
        seen_planned.add(output_name)
        parts = _relative_output_parts(output_name)
        if _is_reserved_transaction_path(parts):
            raise ValueError(
                f"bootstrap output uses a reserved transaction path: {output_name}"
            )
        if any(
            parts[: len(other)] == other or other[: len(parts)] == parts
            for other in planned_parts
        ):
            raise ValueError(
                "bootstrap output paths cannot be ancestors of each other: "
                f"{output_name}"
            )
        planned_parts.append(parts)
        if output_name in removals:
            removal_parts_by_name[output_name] = parts
        else:
            write_parts_by_name[output_name] = parts
    retired_parts: set[tuple[str, ...]] = set()
    for directory_name in retirements:
        parts = _relative_output_parts(directory_name)
        if _is_reserved_transaction_path(parts):
            raise ValueError(
                "retired bootstrap directory uses a reserved transaction path: "
                f"{directory_name}"
            )
        if parts in retired_parts:
            raise ValueError(
                f"duplicate retired bootstrap directory path: {directory_name}"
            )
        retired_parts.add(parts)
    if retirements and not force:
        raise ValueError("bootstrap directory retirement requires force=True")
    if retirements and not removals:
        raise ValueError(
            "bootstrap directory retirement requires at least one planned removal"
        )
    _retirement_children, retirement_errors = _retirement_expected_children(
        retired_parts,
        list(removal_parts_by_name.values()),
    )
    if retirement_errors:
        raise ValueError("; ".join(retirement_errors))
    for retired in retired_parts:
        if any(
            len(retired) < len(parts) and parts[: len(retired)] == retired
            for parts in write_parts_by_name.values()
        ):
            raise ValueError(
                "retired bootstrap directory contains a planned write: "
                f"{'/'.join(retired)}"
            )
    validated_target_modes = _validated_mode_map(
        target_modes,
        expected_keys=set(write_parts_by_name),
        label="target_modes",
        allow_absence=False,
    )
    validated_retirement_modes = _validated_mode_map(
        retired_directory_modes,
        expected_keys=set(retirements),
        label="retired_directory_modes",
        allow_absence=False,
    )
    preimages = None if expected_preimages is None else dict(expected_preimages)
    if preimages is not None:
        if set(preimages) != seen_planned:
            missing = sorted(seen_planned - set(preimages))
            extra = sorted(set(preimages) - seen_planned)
            details: list[str] = []
            if missing:
                details.append("missing " + ", ".join(missing))
            if extra:
                details.append("unexpected " + ", ".join(extra))
            raise ValueError(
                "expected_preimages must exactly cover planned bootstrap outputs"
                + (": " + "; ".join(details) if details else "")
            )
        for output_name, digest in preimages.items():
            if digest is not None and not _valid_sha256(digest):
                raise ValueError(
                    "expected bootstrap preimage must be null or one lowercase "
                    f"SHA-256 digest: {output_name}"
                )
    if expected_preimage_modes is not None and preimages is None:
        raise ValueError(
            "expected_preimage_modes requires expected_preimages"
        )
    validated_preimage_modes = _validated_mode_map(
        expected_preimage_modes,
        expected_keys=set() if preimages is None else set(preimages),
        label="expected_preimage_modes",
        allow_absence=True,
    )
    if validated_preimage_modes is not None and preimages is not None:
        for output_name, digest in preimages.items():
            mode = validated_preimage_modes[output_name]
            if (digest is None) != (mode is None):
                raise ValueError(
                    "expected_preimage_modes must use null exactly for an absent "
                    f"preimage: {output_name}"
                )
    assertions = {} if assert_preimages is None else dict(assert_preimages)
    overlap = seen_planned.intersection(assertions)
    if overlap:
        raise ValueError(
            "assert_preimages must be disjoint from planned bootstrap outputs: "
            + ", ".join(sorted(overlap))
        )
    for output_name, digest in assertions.items():
        parts = _relative_output_parts(output_name)
        if _is_reserved_transaction_path(parts):
            raise ValueError(
                "assert_preimages uses a reserved transaction path: "
                f"{output_name}"
            )
        if not _valid_sha256(digest):
            raise ValueError(
                "asserted bootstrap preimage must be one lowercase SHA-256 "
                f"digest: {output_name}"
            )
        if any(
            len(retired) < len(parts) and parts[: len(retired)] == retired
            for retired in retired_parts
        ):
            raise ValueError(
                "assert_preimages cannot be nested beneath a retired bootstrap "
                f"directory: {output_name}"
            )
    if assert_preimage_modes is not None and assert_preimages is None:
        raise ValueError("assert_preimage_modes requires assert_preimages")
    if assert_preimage_max_bytes is not None and assert_preimages is None:
        raise ValueError("assert_preimage_max_bytes requires assert_preimages")
    validated_assertion_modes = _validated_mode_map(
        assert_preimage_modes,
        expected_keys=set(assertions),
        label="assert_preimage_modes",
        allow_absence=False,
    )
    validated_assertion_max_bytes = _validated_max_bytes_map(
        assert_preimage_max_bytes,
        expected_keys=set(assertions),
        label="assert_preimage_max_bytes",
    )
    all_bindings: list[_DirectoryBinding] = []
    created_bindings: list[_DirectoryBinding] = []
    retired_bindings: list[_DirectoryBinding] = []
    transaction_directories: list[_TransactionDirectory] = []
    records: list[_OutputTransactionRecord] = []
    committed = False
    journal_created = False
    cleanup_warnings: list[str] = []
    project_lock: int | None = None
    project_lock_created = False
    root_binding: _DirectoryBinding | None = None
    transaction_id: str | None = None
    journal_update_started = False
    approved_directory_bindings: dict[
        tuple[str, ...],
        _DirectoryBinding,
    ] = {}
    approved_absent_directories: list[_AbsentDirectoryBinding] = []
    try:
        root_binding = _open_project_root_transaction(
            project_root,
            all_bindings=all_bindings,
        )
        if (
            validated_project_root_identity is not None
            and _directory_node_identity(
                os.fstat(_binding_descriptor(root_binding))
            )
            != validated_project_root_identity
        ):
            raise BootstrapTransactionError(
                "approved target project root identity changed before the "
                "transaction opened"
            )
        (
            approved_directory_bindings,
            approved_absent_directories,
        ) = _bind_expected_directories(
            root_binding,
            validated_directory_identities,
            all_bindings=all_bindings,
        )
        _verify_bound_directories(all_bindings)
        _verify_absent_directory_bindings(approved_absent_directories)
        project_lock, project_lock_created = _acquire_project_lock(
            root_binding,
            exclusive=True,
        )
        _verify_project_lock(root_binding, project_lock)
        _verify_bound_directories(all_bindings)
        _verify_absent_directory_bindings(approved_absent_directories)
        transaction_id = _project_lock_transaction_id(root_binding, project_lock)
        existing_journal, journal_errors = _read_recovery_journal(root_binding)
        if journal_errors:
            raise BootstrapTransactionError(
                "invalid interrupted bootstrap transaction journal: "
                + "; ".join(journal_errors)
            )
        if existing_journal is not None:
            raise BootstrapTransactionError(
                "an interrupted bootstrap transaction requires recovery before another write"
            )
        if _journal_temporary_metadata(root_binding) is not None:
            raise BootstrapTransactionError(
                "an incomplete bootstrap recovery journal update requires inspection"
            )
        if _journal_previous_metadata(root_binding) is not None:
            raise BootstrapTransactionError(
                "an incomplete bootstrap recovery journal replacement requires inspection"
            )
        if not project_lock_created:
            raise BootstrapTransactionError(
                "an orphaned bootstrap project transaction lock requires manual inspection"
            )
        directory_bindings: dict[tuple[str, ...], _DirectoryBinding] = dict(
            approved_directory_bindings
        )
        approved_absent_by_parts: dict[
            tuple[str, ...],
            _AbsentDirectoryBinding,
        ] = {}
        for approved_absence in approved_absent_directories:
            parent_parts = approved_absence.parent.project_relative_parts
            if parent_parts is None:
                raise BootstrapTransactionError(
                    "approved-absent directory lacks a project-relative parent binding"
                )
            approved_absent_by_parts[
                (*parent_parts, approved_absence.entry_name)
            ] = approved_absence

        def verify_locked_preimages(
            expected: Mapping[str, str | None],
            *,
            purpose: str,
            expected_modes: Mapping[str, int | None] | None = None,
            expected_max_bytes: Mapping[str, int | None] | None = None,
        ) -> None:
            for output_name in sorted(expected):
                parts = _relative_output_parts(output_name)
                parent = root_binding
                parent_missing = False
                for depth, part in enumerate(parts[:-1], start=1):
                    key = parts[:depth]
                    _require_exact_directory_entry_spelling(
                        parent,
                        part,
                        description=(
                            f"bootstrap {purpose} preimage path "
                            + "/".join(key)
                        ),
                    )
                    existing = directory_bindings.get(key)
                    if existing is not None:
                        parent = existing
                        continue
                    try:
                        parent = _open_bound_directory(
                            parent,
                            part,
                            label=f"bootstrap preimage parent {'/'.join(key)}",
                            create=False,
                            require_owner=True,
                            created_bindings=created_bindings,
                            all_bindings=all_bindings,
                        )
                    except FileNotFoundError:
                        parent_missing = True
                        break
                    directory_bindings[key] = parent
                if not parent_missing:
                    _require_exact_directory_entry_spelling(
                        parent,
                        parts[-1],
                        description=f"bootstrap {purpose} preimage {output_name}",
                    )
                actual_evidence = (
                    None
                    if parent_missing
                    else _preimage_evidence_at(
                        parent,
                        parts[-1],
                        output_name=output_name,
                        max_bytes=(
                            expected_max_bytes[output_name]
                            if expected_max_bytes is not None
                            else None
                        ),
                    )
                )
                expected_mode = (
                    expected_modes[output_name]
                    if expected_modes is not None
                    else None
                )
                if not _preimage_contract_matches(
                    actual_evidence,
                    expected_digest=expected[output_name],
                    expected_mode=expected_mode,
                    check_mode=expected_modes is not None,
                ):
                    expected_evidence = (
                        None
                        if expected[output_name] is None
                        else {
                            "sha256": expected[output_name],
                            "mode": expected_mode,
                        }
                    )
                    expected_description = _preimage_contract_description(
                        expected_evidence,
                        mode_required=expected_modes is not None,
                    )
                    actual_description = _preimage_contract_description(
                        actual_evidence,
                        mode_required=expected_modes is not None,
                    )
                    raise BootstrapTransactionError(
                        f"bootstrap {purpose} preimage changed after plan inspection: "
                        f"{output_name} (expected {expected_description}, "
                        f"found {actual_description})"
                    )
            _verify_bound_directories(all_bindings)
            _verify_project_lock(root_binding, project_lock)

        def bind_existing_parent(
            parts: tuple[str, ...],
            *,
            purpose: str,
        ) -> tuple[_DirectoryBinding | None, int | None]:
            parent = root_binding
            for depth, part in enumerate(parts[:-1], start=1):
                key = parts[:depth]
                existing = directory_bindings.get(key)
                if existing is not None:
                    parent = existing
                    continue
                try:
                    parent = _open_bound_directory(
                        parent,
                        part,
                        label=f"bootstrap {purpose} parent {'/'.join(key)}",
                        create=False,
                        require_owner=True,
                        created_bindings=created_bindings,
                        all_bindings=all_bindings,
                    )
                except FileNotFoundError:
                    return None, depth
                directory_bindings[key] = parent
            return parent, None

        plans: list[_PlannedOperation] = []
        planned_created_parts: set[tuple[str, ...]] = set()
        transaction_names: dict[tuple[str, ...], str] = {}
        planned_inputs = [
            (name, "write", content.encode("utf-8"))
            for name, content in writes
        ] + [(name, "remove", None) for name in removals]
        for output_name, action, content in planned_inputs:
            parts = _relative_output_parts(output_name)
            parent, missing_depth = bind_existing_parent(
                parts,
                purpose="planning",
            )
            if parent is None:
                if action == "remove":
                    raise FileNotFoundError(
                        f"refusing to remove missing bootstrap output: {output_name}"
                    )
                if missing_depth is None:
                    raise BootstrapTransactionError(
                        f"could not locate missing parent boundary: {output_name}"
                    )
                planned_created_parts.update(
                    parts[:depth]
                    for depth in range(missing_depth, len(parts))
                )
                original = None
                original_evidence = None
            else:
                original = _snapshot_output_target(
                    parent,
                    parts[-1],
                    output_name=output_name,
                    force=force,
                )
                if action == "remove" and original is None:
                    raise FileNotFoundError(
                        f"refusing to remove missing bootstrap output: {output_name}"
                    )
                original_evidence = (
                    _file_evidence_at(
                        parent,
                        parts[-1],
                        description=f"existing bootstrap output {output_name}",
                        expected_metadata=original,
                    )
                    if original is not None
                    else None
                )
            if preimages is not None:
                expected_mode = (
                    validated_preimage_modes[output_name]
                    if validated_preimage_modes is not None
                    else None
                )
                if not _preimage_contract_matches(
                    original_evidence,
                    expected_digest=preimages[output_name],
                    expected_mode=expected_mode,
                    check_mode=validated_preimage_modes is not None,
                ):
                    expected_evidence = (
                        None
                        if preimages[output_name] is None
                        else {
                            "sha256": preimages[output_name],
                            "mode": expected_mode,
                        }
                    )
                    expected_description = _preimage_contract_description(
                        expected_evidence,
                        mode_required=validated_preimage_modes is not None,
                    )
                    actual_description = _preimage_contract_description(
                        original_evidence,
                        mode_required=validated_preimage_modes is not None,
                    )
                    raise BootstrapTransactionError(
                        "bootstrap output preimage changed after plan inspection: "
                        f"{output_name} (expected {expected_description}, "
                        f"found {actual_description})"
                    )
            candidate_evidence: dict[str, object] | None = None
            target_mode = (
                validated_target_modes[output_name]
                if validated_target_modes is not None and action == "write"
                else None
            )
            if action == "write":
                if content is None:
                    raise BootstrapTransactionError(
                        f"planned bootstrap write lacks content: {output_name}"
                    )
                candidate_mode = target_mode
                if candidate_mode is None and original is not None:
                    candidate_mode = stat.S_IMODE(original.st_mode) & 0o777
                if candidate_mode is None:
                    candidate_mode = validated_file_mode
                candidate_evidence = {
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "mode": candidate_mode,
                    "size": len(content),
                }
            parent_parts = parts[:-1]
            transaction_name = transaction_names.setdefault(
                parent_parts,
                ".mpa-bootstrap-transaction-" + secrets.token_hex(16),
            )
            plans.append(
                _PlannedOperation(
                    name=output_name,
                    parts=parts,
                    action=action,
                    content=content,
                    target_mode=target_mode,
                    original_metadata=original,
                    original_evidence=original_evidence,
                    candidate_evidence=candidate_evidence,
                    transaction_directory_name=transaction_name,
                )
            )

        retirement_children, retirement_topology_errors = (
            _retirement_expected_children(
                retired_parts,
                [plan.parts for plan in plans if plan.action == "remove"],
            )
        )
        if retirement_topology_errors:
            raise BootstrapTransactionError("; ".join(retirement_topology_errors))
        retired_by_parts: dict[tuple[str, ...], _DirectoryBinding] = {}
        for parts in sorted(retired_parts, key=lambda value: (len(value), value)):
            binding = directory_bindings.get(parts)
            if binding is None:
                raise BootstrapTransactionError(
                    "retired bootstrap directory is missing or outside the planned "
                    f"removal topology: {'/'.join(parts)}"
                )
            retired_by_parts[parts] = binding
            retired_bindings.append(binding)
        if retired_bindings:
            _verify_retirement_inventory(
                retired_by_parts,
                retirement_children,
                validated_retirement_modes,
            )

        if assertions:
            verify_locked_preimages(
                assertions,
                purpose="asserted",
                expected_modes=validated_assertion_modes,
                expected_max_bytes=validated_assertion_max_bytes,
            )
        if not plans:
            if post_install_verifier is not None:
                post_install_verifier()
            if assertions:
                verify_locked_preimages(
                    assertions,
                    purpose="asserted",
                    expected_modes=validated_assertion_modes,
                    expected_max_bytes=validated_assertion_max_bytes,
                )
            _remove_project_lock(root_binding, project_lock)
            return BootstrapWriteResult(written=[], cleanup_warnings=[], removed=[])

        journal_bound_directories = _journal_bound_directory_records(all_bindings)
        journal: dict[str, object] = {
            "schema_version": RECOVERY_JOURNAL_SCHEMA_VERSION,
            "transaction_id": transaction_id,
            "phase": "preparing",
            "applied_count": 0,
            "bound_directories": journal_bound_directories,
            "created_directories": [
                {"path": "/".join(parts), "identity": None}
                for parts in sorted(
                    planned_created_parts,
                    key=lambda value: (len(value), value),
                )
            ],
            "retired_directories": [
                {
                    "path": "/".join(binding.project_relative_parts or ()),
                    "identity": list(binding.identity),
                }
                for binding in retired_bindings
                if binding.project_relative_parts
            ],
            "operations": [
                {
                    "path": plan.name,
                    "action": plan.action,
                    "transaction_directory": "/".join(
                        (*plan.parts[:-1], plan.transaction_directory_name)
                    ),
                    "stage_name": (
                        f"stage-{index}" if plan.action == "write" else None
                    ),
                    "backup_name": (
                        f"backup-{index}"
                        if plan.original_evidence is not None
                        else None
                    ),
                    "original": plan.original_evidence,
                    "candidate": plan.candidate_evidence,
                }
                for index, plan in enumerate(plans)
            ],
        }
        _verify_bound_directories(all_bindings)
        _verify_absent_directory_bindings(approved_absent_directories)
        _verify_project_lock(root_binding, project_lock)
        if retired_bindings:
            _verify_retirement_inventory(
                retired_by_parts,
                retirement_children,
                validated_retirement_modes,
            )
        journal_update_started = True
        _write_recovery_journal(
            root_binding,
            journal,
            require_absent=True,
            lock_descriptor=project_lock,
        )
        journal_created = True

        for plan in plans:
            parent = root_binding
            for depth, part in enumerate(plan.parts[:-1], start=1):
                key = plan.parts[:depth]
                existing = directory_bindings.get(key)
                if existing is not None:
                    parent = existing
                    continue
                approved_absence = approved_absent_by_parts.get(key)
                if (
                    approved_absence is not None
                    and approved_absence.parent is not parent
                ):
                    raise BootstrapTransactionError(
                        "approved-absent directory parent binding changed before "
                        f"creation: {'/'.join(key)}"
                    )
                parent = _open_bound_directory(
                    parent,
                    part,
                    label=f"bootstrap output parent {'/'.join(key)}",
                    create=plan.action == "write",
                    require_owner=True,
                    created_bindings=created_bindings,
                    all_bindings=all_bindings,
                    create_mode=validated_directory_mode,
                    require_absent=key in planned_created_parts,
                )
                directory_bindings[key] = parent
            original = _snapshot_output_target(
                parent,
                plan.parts[-1],
                output_name=plan.name,
                force=force,
            )
            if (original is None) != (plan.original_metadata is None):
                raise BootstrapTransactionError(
                    f"bootstrap output existence changed after planning: {plan.name}"
                )
            if (
                original is not None
                and plan.original_metadata is not None
                and safe_paths.stable_file_metadata(original)
                != safe_paths.stable_file_metadata(plan.original_metadata)
            ):
                raise BootstrapTransactionError(
                    f"bootstrap output changed after planning: {plan.name}"
                )
            original_evidence = (
                _file_evidence_at(
                    parent,
                    plan.parts[-1],
                    description=f"existing bootstrap output {plan.name}",
                    expected_metadata=original,
                )
                if original is not None
                else None
            )
            if original_evidence != plan.original_evidence:
                raise BootstrapTransactionError(
                    f"bootstrap output bytes changed after planning: {plan.name}"
                )
            records.append(
                _OutputTransactionRecord(
                    name=plan.name,
                    parent=parent,
                    target_name=plan.parts[-1],
                    action=plan.action,
                    content=plan.content,
                    target_mode=plan.target_mode,
                    original_metadata=original,
                    original_evidence=original_evidence,
                    candidate_evidence=plan.candidate_evidence,
                )
            )

        actual_created_parts = {
            binding.project_relative_parts
            for binding in created_bindings
            if binding.project_relative_parts is not None
        }
        if actual_created_parts != planned_created_parts:
            raise BootstrapTransactionError(
                "bootstrap output parent topology changed after planning"
            )
        journal["created_directories"] = [
            {
                "path": "/".join(binding.project_relative_parts or ()),
                "identity": list(binding.identity),
            }
            for binding in sorted(
                created_bindings,
                key=lambda value: (
                    len(value.project_relative_parts or ()),
                    value.project_relative_parts or (),
                ),
            )
            if binding.project_relative_parts
        ]
        _write_recovery_journal(
            root_binding,
            journal,
            require_absent=False,
            lock_descriptor=project_lock,
        )

        transaction_by_parent: dict[tuple[str, ...], _TransactionDirectory] = {}
        for plan, record in zip(plans, records, strict=True):
            parent_parts = plan.parts[:-1]
            transaction_directory = transaction_by_parent.get(parent_parts)
            if transaction_directory is None:
                transaction_directory = _create_transaction_directory(
                    record.parent,
                    entry_name=plan.transaction_directory_name,
                    all_bindings=all_bindings,
                )
                transaction_by_parent[parent_parts] = transaction_directory
                transaction_directories.append(transaction_directory)
            record.transaction_directory = transaction_directory
        for index, record in enumerate(records):
            _verify_bound_directories(all_bindings)
            _stage_output(
                record,
                index,
                create_file_mode=validated_file_mode,
            )
            if record.original_metadata is not None:
                record.backup_name = f"backup-{index}"
        created_directories: list[dict[str, object]] = [
            {
                "path": "/".join(binding.project_relative_parts),
                "identity": list(binding.identity),
            }
            for binding in created_bindings
            if binding.project_relative_parts
        ]
        journal = _render_recovery_payload(
            records,
            transaction_id=transaction_id,
            bound_directories=journal_bound_directories,
            created_directories=created_directories,
            retired_directories=[
                {
                    "path": "/".join(binding.project_relative_parts or ()),
                    "identity": list(binding.identity),
                }
                for binding in retired_bindings
                if binding.project_relative_parts
            ],
        )
        _verify_bound_directories(all_bindings)
        _verify_project_lock(root_binding, project_lock)
        _write_recovery_journal(
            root_binding,
            journal,
            require_absent=False,
            lock_descriptor=project_lock,
        )
        journal["phase"] = "applying"
        _write_recovery_journal(
            root_binding,
            journal,
            require_absent=False,
            lock_descriptor=project_lock,
        )
        for index, record in enumerate(records):
            _verify_project_lock(root_binding, project_lock)
            _install_staged_output(record, index, all_bindings)
            journal["applied_count"] = index + 1
            _write_recovery_journal(
                root_binding,
                journal,
                require_absent=False,
                lock_descriptor=project_lock,
            )
        _verify_bound_directories(all_bindings)
        _verify_project_lock(root_binding, project_lock)
        _verify_installed_records(records)
        if post_install_verifier is not None:
            post_install_verifier()
            _verify_bound_directories(all_bindings)
            _verify_project_lock(root_binding, project_lock)
            _verify_installed_records(records)
        if assertions:
            verify_locked_preimages(
                assertions,
                purpose="asserted",
                expected_modes=validated_assertion_modes,
                expected_max_bytes=validated_assertion_max_bytes,
            )
            _verify_installed_records(records)
        _verify_transaction_context(root_binding, project_lock, all_bindings)
        journal["phase"] = "verified"
        _write_recovery_journal(
            root_binding,
            journal,
            require_absent=False,
            lock_descriptor=project_lock,
        )
        _verify_transaction_context(root_binding, project_lock, all_bindings)
        committed = True
        try:
            _verify_transaction_context(root_binding, project_lock, all_bindings)
            cleanup_warnings.extend(
                _cleanup_committed_outputs(records, transaction_directories)
            )
            _verify_transaction_context(root_binding, project_lock, all_bindings)
        except BaseException as exc:
            cleanup_warnings.append(
                f"could not complete post-commit bootstrap cleanup: {exc}"
            )
        if not cleanup_warnings and retired_bindings:
            try:
                _verify_transaction_context(root_binding, project_lock, all_bindings)
                cleanup_warnings.extend(
                    _retire_empty_directories(retired_bindings)
                )
                _verify_transaction_context(root_binding, project_lock, all_bindings)
            except BaseException as exc:
                cleanup_warnings.append(
                    "could not complete verified directory retirement: " + str(exc)
                )
        if not cleanup_warnings:
            try:
                _verify_transaction_context(root_binding, project_lock, all_bindings)
                _remove_recovery_journal(root_binding)
                journal_created = False
                _verify_transaction_context(root_binding, project_lock, all_bindings)
                _remove_project_lock(root_binding, project_lock)
                _verify_bound_directories(all_bindings)
            except BaseException as exc:
                cleanup_warnings.append(
                    "could not remove verified bootstrap recovery controls: "
                    f"{exc}"
                )
        return BootstrapWriteResult(
            written=[record.name for record in records if record.action == "write"],
            cleanup_warnings=cleanup_warnings,
            removed=[record.name for record in records if record.action == "remove"],
        )
    except BaseException as exc:
        rollback_errors: list[str] = []
        if not committed:
            if (
                not journal_created
                and root_binding is not None
                and transaction_id is not None
            ):
                installed_journal, installed_errors = _read_recovery_journal(
                    root_binding
                )
                if (
                    installed_journal is not None
                    and installed_journal.get("transaction_id") == transaction_id
                ):
                    journal_created = True
                elif installed_errors:
                    rollback_errors.append(
                        "could not inspect bootstrap recovery journal after failure: "
                        + "; ".join(installed_errors)
                    )
            if root_binding is not None and project_lock is not None:
                try:
                    _verify_transaction_context(
                        root_binding,
                        project_lock,
                        all_bindings,
                    )
                except BaseException as context_exc:
                    rollback_errors.append(
                        "transaction directory context changed before rollback; "
                        f"retained recovery controls: {context_exc}"
                    )
            if not rollback_errors:
                for index in range(len(records) - 1, -1, -1):
                    record = records[index]
                    try:
                        assert root_binding is not None and project_lock is not None
                        _verify_transaction_context(
                            root_binding,
                            project_lock,
                            all_bindings,
                        )
                        rollback_errors.extend(_rollback_output(record, index))
                        _verify_transaction_context(
                            root_binding,
                            project_lock,
                            all_bindings,
                        )
                    except BaseException as rollback_exc:
                        rollback_errors.append(
                            f"rollback context verification failed: {rollback_exc}"
                        )
                        break
            if not rollback_errors:
                try:
                    assert root_binding is not None and project_lock is not None
                    _verify_transaction_context(
                        root_binding,
                        project_lock,
                        all_bindings,
                    )
                    cleanup_warnings.extend(
                        _remove_empty_transaction_directories(transaction_directories)
                    )
                    _verify_transaction_context(
                        root_binding,
                        project_lock,
                        all_bindings,
                    )
                except BaseException as cleanup_exc:
                    rollback_errors.append(
                        f"rollback cleanup context verification failed: {cleanup_exc}"
                    )
            rollback_errors.extend(cleanup_warnings)
            created_inside_project = [
                binding
                for binding in created_bindings
                if binding.project_relative_parts
            ]
            if not rollback_errors:
                try:
                    assert root_binding is not None and project_lock is not None
                    _verify_transaction_context(
                        root_binding,
                        project_lock,
                        all_bindings,
                    )
                    rollback_errors.extend(
                        _remove_created_directories(created_inside_project)
                    )
                    _verify_transaction_context(
                        root_binding,
                        project_lock,
                        all_bindings,
                    )
                except BaseException as directory_exc:
                    rollback_errors.append(
                        f"rollback directory context verification failed: {directory_exc}"
                    )
            if (
                root_binding is not None
                and journal_update_started
                and not rollback_errors
            ):
                try:
                    remaining_journal_temporary = _journal_temporary_metadata(
                        root_binding
                    )
                except BaseException as temporary_exc:
                    rollback_errors.append(
                        "could not prove the bootstrap recovery journal temporary "
                        "file absent after rollback; retained the transaction lock "
                        f"and canonical journal: {temporary_exc}"
                    )
                else:
                    if remaining_journal_temporary is not None:
                        rollback_errors.append(
                            "bootstrap recovery journal temporary file remains after "
                            "rollback; retained the transaction lock and canonical "
                            "journal for exact-ID recovery"
                        )
            if (
                root_binding is not None
                and project_lock is not None
                and project_lock_created
                and journal_created
                and not rollback_errors
            ):
                try:
                    _verify_transaction_context(
                        root_binding,
                        project_lock,
                        all_bindings,
                    )
                    _remove_recovery_journal(root_binding)
                    journal_created = False
                    _verify_transaction_context(
                        root_binding,
                        project_lock,
                        all_bindings,
                    )
                except BaseException as journal_exc:
                    rollback_errors.append(
                        "could not remove bootstrap recovery journal after "
                        f"rollback: {journal_exc}"
                    )
            if (
                root_binding is not None
                and project_lock is not None
                and project_lock_created
                and not journal_created
                and not rollback_errors
            ):
                try:
                    _remove_project_lock(root_binding, project_lock)
                    _verify_bound_directories(all_bindings)
                except BaseException as lock_exc:
                    rollback_errors.append(
                        f"could not remove bootstrap lock after rollback: {lock_exc}"
                    )
        detail = f"bootstrap write transaction failed: {exc}"
        if rollback_errors:
            detail += "; rollback incomplete: " + "; ".join(rollback_errors)
        raise BootstrapTransactionError(detail) from exc
    finally:
        active_primary = sys.exception()
        _cleanup_transaction_resources(
            root_binding,
            project_lock,
            all_bindings,
            primary=active_primary,
            committed_cleanup_warnings=(
                cleanup_warnings
                if committed and active_primary is None
                else None
            ),
        )
