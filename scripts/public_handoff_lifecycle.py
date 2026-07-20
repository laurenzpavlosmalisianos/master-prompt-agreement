#!/usr/bin/env python3

"""Close the deterministic gaps around the read-only public handoff gate.

This command validates publication inputs before network-capable Git use,
parses exact remote records, materializes one verified export into a disposable
independent clone, validates handoff-receipt continuity, and checks remote
readback records. It never invokes Git, commits, tags, pushes, or selects
credentials. A failed mutation leaves only the disposable release clone to be
abandoned with its operation root.
"""

from __future__ import annotations

import argparse
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
from typing import NoReturn

import public_handoff_check
import public_release_check
import public_surface
import safe_paths


_FULL_OID_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_RECEIPT_MAX_BYTES = 64 * 1024
_FDINFO_MAX_BYTES = 16 * 1024
_DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY")
    | getattr(os, "O_NOFOLLOW")
    | getattr(os, "O_CLOEXEC", 0)
)
_FILE_CREATE_FLAGS = (
    os.O_WRONLY
    | os.O_CREAT
    | os.O_EXCL
    | getattr(os, "O_NOFOLLOW")
    | getattr(os, "O_CLOEXEC", 0)
)
_FILE_READ_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_NOFOLLOW")
    | getattr(os, "O_NONBLOCK")
    | getattr(os, "O_CLOEXEC", 0)
)


class _CliError(ValueError):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise _CliError(message)


def _canonical_json(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def _absolute_path(path: Path, *, description: str) -> Path:
    if (
        not path.is_absolute()
        or not path.parts
        or any(component in {"", ".", ".."} for component in path.parts)
    ):
        raise ValueError(f"{description} must be one canonical absolute path")
    return path


def _direct_child(path: Path, parent: Path, name: str, *, description: str) -> None:
    if path != parent / name:
        raise ValueError(
            f"{description} must be the exact {name!r} child of the operation root"
        )


def _directory_names(descriptor: int) -> tuple[str, ...]:
    with os.scandir(descriptor) as entries:
        return tuple(sorted(entry.name for entry in entries))


def _descriptor_mount_id(descriptor: int) -> int:
    """Return the Linux mount ID for one open descriptor or fail closed."""

    fdinfo_path = f"/proc/{os.getpid()}/fdinfo/{descriptor}"
    fdinfo = os.open(fdinfo_path, _FILE_READ_FLAGS)
    try:
        chunks: list[bytes] = []
        remaining = _FDINFO_MAX_BYTES + 1
        while remaining:
            chunk = os.read(fdinfo, min(4096, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
    finally:
        os.close(fdinfo)
    if len(raw) > _FDINFO_MAX_BYTES:
        raise ValueError("Linux descriptor mount metadata exceeds its bounded limit")
    values = [
        line.removeprefix(b"mnt_id:\t")
        for line in raw.splitlines()
        if line.startswith(b"mnt_id:\t")
    ]
    if len(values) != 1 or not values[0].isdigit():
        raise ValueError("Linux descriptor mount metadata lacks one canonical mount ID")
    mount_id = int(values[0])
    if mount_id <= 0:
        raise ValueError("Linux descriptor mount ID must be positive")
    return mount_id


def _require_directory_mode(descriptor: int, expected: int, *, description: str) -> None:
    observed = stat.S_IMODE(os.fstat(descriptor).st_mode)
    if observed != expected:
        raise ValueError(
            f"{description} mode must equal {expected:#o}; observed {observed:#o}"
        )


def _paths_overlap(left: Path, right: Path) -> bool:
    return (
        left == right
        or safe_paths.path_within_root(left, right)
        or safe_paths.path_within_root(right, left)
    )


def _bind_existing(
    stack: ExitStack,
    path: Path,
    *,
    description: str,
) -> safe_paths.OutputDirectoryBinding:
    try:
        return stack.enter_context(
            safe_paths.open_output_directory(path, create_missing=False)
        )
    except (OSError, ValueError) as exc:
        raise ValueError(f"{description} could not be bound safely: {exc}") from exc


def _validate_topology(
    *,
    operation_root: Path,
    control_root: Path,
    state_root: Path,
    temporary_root: Path,
    export_root: Path,
    public_clone_root: Path,
    authoring_root: Path,
    require_clone: bool,
) -> tuple[ExitStack, dict[str, safe_paths.OutputDirectoryBinding]]:
    operation_root = _absolute_path(operation_root, description="operation root")
    control_root = _absolute_path(control_root, description="control root")
    state_root = _absolute_path(state_root, description="state root")
    temporary_root = _absolute_path(temporary_root, description="temporary root")
    export_root = _absolute_path(export_root, description="export root")
    public_clone_root = _absolute_path(
        public_clone_root, description="public clone root"
    )
    authoring_root = _absolute_path(authoring_root, description="authoring root")
    _direct_child(control_root, operation_root, "control", description="control root")
    _direct_child(state_root, operation_root, "state", description="state root")
    _direct_child(
        temporary_root,
        operation_root,
        "temporary",
        description="temporary root",
    )
    _direct_child(export_root, operation_root, "export", description="export root")
    _direct_child(
        public_clone_root,
        operation_root,
        "public-clone",
        description="public clone root",
    )
    if _paths_overlap(operation_root, authoring_root):
        raise ValueError("operation root and authoring root must be distinct and non-nested")

    stack = ExitStack()
    try:
        bindings = {
            "operation": _bind_existing(
                stack, operation_root, description="operation root"
            ),
            "control": _bind_existing(stack, control_root, description="control root"),
            "state": _bind_existing(stack, state_root, description="state root"),
            "temporary": _bind_existing(
                stack, temporary_root, description="temporary root"
            ),
            "export": _bind_existing(stack, export_root, description="export root"),
            "authoring": _bind_existing(
                stack, authoring_root, description="authoring root"
            ),
        }
        if require_clone:
            bindings["clone"] = _bind_existing(
                stack, public_clone_root, description="public clone root"
            )

        operation_mount_id = _descriptor_mount_id(bindings["operation"].descriptor)
        for label in ("control", "state", "temporary", "export", "clone"):
            binding = bindings.get(label)
            if (
                binding is not None
                and _descriptor_mount_id(binding.descriptor) != operation_mount_id
            ):
                raise ValueError(
                    f"{label} root must remain on the operation root mount"
                )
        operation_metadata = os.fstat(bindings["operation"].descriptor)
        authoring_metadata = os.fstat(bindings["authoring"].descriptor)
        if (operation_metadata.st_dev, operation_metadata.st_ino) == (
            authoring_metadata.st_dev,
            authoring_metadata.st_ino,
        ):
            raise ValueError("operation and authoring roots must not share one identity")

        expected_names = {"control", "export", "state", "temporary"}
        if require_clone:
            expected_names.add("public-clone")
        observed_names = set(_directory_names(bindings["operation"].descriptor))
        if observed_names != expected_names:
            raise ValueError(
                "operation root entries do not equal the closed release topology: "
                + ", ".join(sorted(observed_names))
            )
        _require_directory_mode(
            bindings["operation"].descriptor,
            0o700,
            description="operation root",
        )
        for label in ("control", "state", "temporary"):
            _require_directory_mode(
                bindings[label].descriptor,
                0o700,
                description=f"{label} root",
            )
        for label in ("control", "temporary"):
            if _directory_names(bindings[label].descriptor):
                raise ValueError(f"{label} root must be empty")
        public_release_check.checked_public_export_ownership_descriptor(
            bindings["export"].descriptor
        )
        if not require_clone and public_clone_root.exists():
            raise ValueError("public clone destination must remain absent before clone")
        return stack, bindings
    except BaseException:
        stack.close()
        raise


def preflight_network_inputs(
    *,
    operation_root: Path,
    control_root: Path,
    state_root: Path,
    temporary_root: Path,
    export_root: Path,
    public_clone_root: Path,
    authoring_root: Path,
    remote_name: str,
    branch: str,
    fetch_url: str,
    push_url: str,
) -> dict[str, object]:
    """Validate closed topology and routing before the first Git network use."""

    errors = public_handoff_check.publication_target_errors(
        remote_name=remote_name,
        branch=branch,
        expected_fetch_url=fetch_url,
        expected_push_url=push_url,
    )
    if errors:
        raise ValueError("; ".join(errors))
    stack, bindings = _validate_topology(
        operation_root=operation_root,
        control_root=control_root,
        state_root=state_root,
        temporary_root=temporary_root,
        export_root=export_root,
        public_clone_root=public_clone_root,
        authoring_root=authoring_root,
        require_clone=False,
    )
    with stack:
        for label in (
            "control",
            "state",
            "temporary",
            "export",
            "authoring",
            "operation",
        ):
            binding = bindings[label]
            binding.require_unchanged_chain(
                description=(
                    "public clone root" if label == "clone" else f"{label} root"
                )
            )
    return {
        "branch_ref": public_handoff_check.publication_branch_ref(branch),
        "errors": [],
        "remote_name": remote_name,
        "status": "ready-for-network",
    }


def preflight_existing_clone_inputs(
    *,
    operation_root: Path,
    control_root: Path,
    state_root: Path,
    temporary_root: Path,
    export_root: Path,
    public_clone_root: Path,
    authoring_root: Path,
    remote_name: str,
    branch: str,
    fetch_url: str,
    push_url: str,
) -> dict[str, object]:
    """Bind one retained clone before a fresh remote-parent observation.

    This is a topology check, not evidence that the clone is acceptable.  The
    caller must still run the complete staged handoff verifier before recording
    a verified staging receipt.
    """

    errors = public_handoff_check.publication_target_errors(
        remote_name=remote_name,
        branch=branch,
        expected_fetch_url=fetch_url,
        expected_push_url=push_url,
    )
    if errors:
        raise ValueError("; ".join(errors))
    stack, bindings = _validate_topology(
        operation_root=operation_root,
        control_root=control_root,
        state_root=state_root,
        temporary_root=temporary_root,
        export_root=export_root,
        public_clone_root=public_clone_root,
        authoring_root=authoring_root,
        require_clone=True,
    )
    with stack:
        for label in (
            "control",
            "state",
            "temporary",
            "export",
            "clone",
            "authoring",
            "operation",
        ):
            bindings[label].require_unchanged_chain(
                description=(
                    "public clone root" if label == "clone" else f"{label} root"
                )
            )
    return {
        "branch_ref": public_handoff_check.publication_branch_ref(branch),
        "errors": [],
        "remote_name": remote_name,
        "status": "ready-for-existing-clone-readback",
    }


def parse_remote_parent(*, branch: str, record: str) -> str:
    """Parse exactly one full remote branch record and return its object ID."""

    expected_ref = public_handoff_check.publication_branch_ref(branch)
    if not record or record != record.strip() or "\r" in record or "\n" in record:
        raise ValueError("remote branch query must return exactly one unpadded record")
    oid, separator, ref = record.partition("\t")
    if separator != "\t" or not oid or ref != expected_ref or "\t" in ref:
        raise ValueError("remote branch query did not return the exact selected full ref")
    if _FULL_OID_RE.fullmatch(oid) is None:
        raise ValueError("remote branch query must return one full lowercase object ID")
    return oid


def _write_all(descriptor: int, content: bytes) -> None:
    offset = 0
    while offset < len(content):
        written = os.write(descriptor, content[offset:])
        if written <= 0:
            raise OSError("short write while materializing public payload")
        offset += written


def _open_relative_directory(
    root_descriptor: int,
    parts: tuple[str, ...],
    *,
    expected_mount_id: int | None = None,
) -> int:
    descriptor = os.dup(root_descriptor)
    try:
        if (
            expected_mount_id is not None
            and _descriptor_mount_id(descriptor) != expected_mount_id
        ):
            raise ValueError("descriptor-relative path crossed a mount boundary")
        for component in parts:
            next_descriptor = os.open(
                component,
                _DIRECTORY_FLAGS,
                dir_fd=descriptor,
            )
            os.close(descriptor)
            descriptor = next_descriptor
            if (
                expected_mount_id is not None
                and _descriptor_mount_id(descriptor) != expected_mount_id
            ):
                raise ValueError("descriptor-relative path crossed a mount boundary")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _remove_entry(
    parent_descriptor: int,
    name: str,
    *,
    relative: str,
    expected_mount_id: int,
) -> None:
    metadata = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
    if stat.S_ISDIR(metadata.st_mode):
        descriptor = os.open(name, _DIRECTORY_FLAGS, dir_fd=parent_descriptor)
        try:
            if _descriptor_mount_id(descriptor) != expected_mount_id:
                raise ValueError(
                    f"public clone entry crosses a mount boundary: {relative}"
                )
            opened = os.fstat(descriptor)
            if (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino):
                raise ValueError(f"public clone entry changed during removal: {relative}")
            for child in _directory_names(descriptor):
                _remove_entry(
                    descriptor,
                    child,
                    relative=f"{relative}/{child}",
                    expected_mount_id=expected_mount_id,
                )
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        current = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
        if (
            not stat.S_ISDIR(current.st_mode)
            or (current.st_dev, current.st_ino) != (metadata.st_dev, metadata.st_ino)
        ):
            raise ValueError(f"public clone entry changed during removal: {relative}")
        os.rmdir(name, dir_fd=parent_descriptor)
        return
    if stat.S_ISREG(metadata.st_mode):
        if metadata.st_nlink != 1:
            raise ValueError(
                f"public clone worktree file must have one hard link before removal: {relative}"
            )
        os.unlink(name, dir_fd=parent_descriptor)
        return
    if stat.S_ISLNK(metadata.st_mode):
        os.unlink(name, dir_fd=parent_descriptor)
        return
    raise ValueError(f"public clone contains unsupported entry before removal: {relative}")


def _create_payload_directories(
    clone_descriptor: int,
    directories: tuple[tuple[str, int], ...],
    *,
    clone_mount_id: int,
) -> None:
    for relative, mode in sorted(
        directories,
        key=lambda item: (len(PurePosixPath(item[0]).parts), item[0]),
    ):
        parts = PurePosixPath(relative).parts
        if not parts or any(part in {"", ".", ".."} for part in parts):
            raise ValueError(f"public export contains an unsafe directory path: {relative}")
        parent = _open_relative_directory(
            clone_descriptor,
            parts[:-1],
            expected_mount_id=clone_mount_id,
        )
        try:
            os.mkdir(parts[-1], mode=0o700, dir_fd=parent)
            child = os.open(parts[-1], _DIRECTORY_FLAGS, dir_fd=parent)
            try:
                os.fchmod(child, mode)
                os.fsync(child)
            finally:
                os.close(child)
            os.fsync(parent)
        finally:
            os.close(parent)


def _copy_payload_file(
    *,
    export_descriptor: int,
    export_mount_id: int,
    clone_descriptor: int,
    clone_mount_id: int,
    relative: str,
    expected_sha256: str,
    expected_mode: int,
) -> None:
    parts = PurePosixPath(relative).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"public export contains an unsafe file path: {relative}")
    source_parent = _open_relative_directory(
        export_descriptor,
        parts[:-1],
        expected_mount_id=export_mount_id,
    )
    destination_parent = _open_relative_directory(
        clone_descriptor,
        parts[:-1],
        expected_mount_id=clone_mount_id,
    )
    source: int | None = None
    destination: int | None = None
    try:
        source = os.open(parts[-1], _FILE_READ_FLAGS, dir_fd=source_parent)
        source_before = os.fstat(source)
        source_named_before = os.stat(
            parts[-1],
            dir_fd=source_parent,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISREG(source_before.st_mode)
            or source_before.st_nlink != 1
            or stat.S_IMODE(source_before.st_mode) != expected_mode
            or safe_paths.stable_file_metadata(source_before)
            != safe_paths.stable_file_metadata(source_named_before)
        ):
            raise ValueError(f"public export payload metadata changed: {relative}")
        destination = os.open(
            parts[-1],
            _FILE_CREATE_FLAGS,
            0o600,
            dir_fd=destination_parent,
        )
        digest = hashlib.sha256()
        copied_size = 0
        while chunk := os.read(source, 1024 * 1024):
            digest.update(chunk)
            _write_all(destination, chunk)
            copied_size += len(chunk)
        source_after = os.fstat(source)
        source_named_after = os.stat(
            parts[-1],
            dir_fd=source_parent,
            follow_symlinks=False,
        )
        if (
            safe_paths.stable_file_metadata(source_before)
            != safe_paths.stable_file_metadata(source_after)
            or safe_paths.stable_file_metadata(source_after)
            != safe_paths.stable_file_metadata(source_named_after)
            or copied_size != source_after.st_size
        ):
            raise ValueError(f"public export payload changed while copied: {relative}")
        if digest.hexdigest() != expected_sha256:
            raise ValueError(f"public export payload digest changed: {relative}")
        os.fchmod(destination, expected_mode)
        os.fsync(destination)
        metadata = os.fstat(destination)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) != expected_mode
            or metadata.st_size != copied_size
        ):
            raise ValueError(f"materialized payload metadata mismatch: {relative}")
        os.fsync(destination_parent)
    finally:
        if destination is not None:
            os.close(destination)
        if source is not None:
            os.close(source)
        os.close(destination_parent)
        os.close(source_parent)


def _digest_payload_file(
    root_descriptor: int,
    *,
    relative: str,
    expected_mode: int,
    expected_mount_id: int,
) -> str:
    """Hash one stable descriptor-relative ordinary payload without a size cap."""

    parts = PurePosixPath(relative).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"materialized clone contains an unsafe file path: {relative}")
    parent = _open_relative_directory(
        root_descriptor,
        parts[:-1],
        expected_mount_id=expected_mount_id,
    )
    descriptor: int | None = None
    try:
        descriptor = os.open(parts[-1], _FILE_READ_FLAGS, dir_fd=parent)
        before = os.fstat(descriptor)
        named_before = os.stat(
            parts[-1],
            dir_fd=parent,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) != expected_mode
            or safe_paths.stable_file_metadata(before)
            != safe_paths.stable_file_metadata(named_before)
        ):
            raise ValueError(f"materialized payload metadata mismatch: {relative}")
        digest = hashlib.sha256()
        observed_size = 0
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
            observed_size += len(chunk)
        after = os.fstat(descriptor)
        named_after = os.stat(
            parts[-1],
            dir_fd=parent,
            follow_symlinks=False,
        )
        if (
            safe_paths.stable_file_metadata(before)
            != safe_paths.stable_file_metadata(after)
            or safe_paths.stable_file_metadata(after)
            != safe_paths.stable_file_metadata(named_after)
            or observed_size != after.st_size
        ):
            raise ValueError(f"materialized payload changed while hashed: {relative}")
        return digest.hexdigest()
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(parent)


def materialize_export(
    *,
    operation_root: Path,
    control_root: Path,
    state_root: Path,
    temporary_root: Path,
    export_root: Path,
    public_clone_root: Path,
    authoring_root: Path,
) -> dict[str, object]:
    """Replace disposable clone payload while preserving its ordinary .git."""

    stack, bindings = _validate_topology(
        operation_root=operation_root,
        control_root=control_root,
        state_root=state_root,
        temporary_root=temporary_root,
        export_root=export_root,
        public_clone_root=public_clone_root,
        authoring_root=authoring_root,
        require_clone=True,
    )
    with stack:
        export_binding = bindings["export"]
        clone_binding = bindings["clone"]
        export_mount_id = _descriptor_mount_id(export_binding.descriptor)
        clone_mount_id = _descriptor_mount_id(clone_binding.descriptor)
        initial_export = public_release_check.checked_public_export_ownership_descriptor(
            export_binding.descriptor
        )
        export_inventory = public_release_check._inventory_release_tree_descriptor(
            export_binding.descriptor
        )
        if export_inventory.errors:
            raise ValueError(
                "public export could not be inventoried before materialization: "
                + "; ".join(export_inventory.errors)
            )
        oversized_payloads = sorted(
            relative
            for relative, metadata in export_inventory.files.items()
            if relative != public_surface.PUBLIC_EXPORT_OWNERSHIP_MARKER
            and metadata.st_size > public_release_check.PUBLIC_TEXT_INPUT_MAX_BYTES
        )
        if oversized_payloads:
            raise ValueError(
                "public export payload exceeds the canonical 4 MiB per-file limit "
                "before materialization: "
                + ", ".join(oversized_payloads)
            )
        for relative, _mode in initial_export.directories:
            directory = _open_relative_directory(
                export_binding.descriptor,
                PurePosixPath(relative).parts,
                expected_mount_id=export_mount_id,
            )
            os.close(directory)
        preimage = public_release_check._inventory_release_tree_descriptor(
            clone_binding.descriptor
        )
        if preimage.errors:
            raise ValueError(
                "public clone could not be inventoried before materialization: "
                + "; ".join(preimage.errors)
            )
        if preimage.special:
            raise ValueError(
                "public clone contains unsupported worktree entries before materialization: "
                + ", ".join(sorted(preimage.special))
            )
        git_metadata = preimage.directories.get(".git")
        if (
            git_metadata is None
            or ".git" in preimage.files
            or ".git" in preimage.symlinks
        ):
            raise ValueError("public clone must contain one ordinary .git directory")
        git_descriptor = os.open(
            ".git",
            _DIRECTORY_FLAGS,
            dir_fd=clone_binding.descriptor,
        )
        try:
            if _descriptor_mount_id(git_descriptor) != clone_mount_id:
                raise ValueError("public clone .git directory crosses a mount boundary")
            git_identity = safe_paths.stable_file_metadata(os.fstat(git_descriptor))
            if git_identity != safe_paths.stable_file_metadata(git_metadata):
                raise ValueError("public clone .git binding changed before materialization")
            for relative in sorted(preimage.directories):
                if relative == ".git":
                    continue
                directory = _open_relative_directory(
                    clone_binding.descriptor,
                    PurePosixPath(relative).parts,
                    expected_mount_id=clone_mount_id,
                )
                os.close(directory)
            for name in _directory_names(clone_binding.descriptor):
                if name == ".git":
                    continue
                _remove_entry(
                    clone_binding.descriptor,
                    name,
                    relative=name,
                    expected_mount_id=clone_mount_id,
                )

            _create_payload_directories(
                clone_binding.descriptor,
                initial_export.directories,
                clone_mount_id=clone_mount_id,
            )
            payload_files = tuple(
                record
                for record in initial_export.files
                if record[0] != public_surface.PUBLIC_EXPORT_OWNERSHIP_MARKER
            )
            for relative, digest, mode in payload_files:
                _copy_payload_file(
                    export_descriptor=export_binding.descriptor,
                    export_mount_id=export_mount_id,
                    clone_descriptor=clone_binding.descriptor,
                    clone_mount_id=clone_mount_id,
                    relative=relative,
                    expected_sha256=digest,
                    expected_mode=mode,
                )
            os.fsync(clone_binding.descriptor)

            terminal = public_release_check._inventory_release_tree_descriptor(
                clone_binding.descriptor
            )
            if terminal.errors or terminal.symlinks or terminal.special:
                raise ValueError("materialized public clone inventory is not ordinary")
            expected_files = {relative for relative, _digest, _mode in payload_files}
            expected_directories = {
                relative for relative, _mode in initial_export.directories
            } | {".git"}
            if set(terminal.files) != expected_files:
                raise ValueError("materialized public clone file set differs from export")
            if set(terminal.directories) != expected_directories:
                raise ValueError("materialized public clone directory set differs from export")
            if public_surface.PUBLIC_EXPORT_OWNERSHIP_MARKER in terminal.files:
                raise ValueError("public export ownership marker entered the public clone")
            if (
                safe_paths.stable_file_metadata(terminal.directories[".git"])
                != git_identity
            ):
                raise ValueError("public clone .git name changed during materialization")
            for relative, digest, mode in payload_files:
                metadata = terminal.files[relative]
                if stat.S_IMODE(metadata.st_mode) != mode or metadata.st_nlink != 1:
                    raise ValueError(f"materialized payload mode/link mismatch: {relative}")
                if (
                    _digest_payload_file(
                        clone_binding.descriptor,
                        relative=relative,
                        expected_mode=mode,
                        expected_mount_id=clone_mount_id,
                    )
                    != digest
                ):
                    raise ValueError(f"materialized payload digest mismatch: {relative}")
            named_git = os.stat(
                ".git",
                dir_fd=clone_binding.descriptor,
                follow_symlinks=False,
            )
            if (
                safe_paths.stable_file_metadata(os.fstat(git_descriptor)) != git_identity
                or safe_paths.stable_file_metadata(named_git) != git_identity
            ):
                raise ValueError("public clone .git directory changed during materialization")
        finally:
            os.close(git_descriptor)

        terminal_export = public_release_check.checked_public_export_ownership_descriptor(
            export_binding.descriptor
        )
        if terminal_export != initial_export:
            raise ValueError("public export changed during materialization")
        for label in (
            "control",
            "state",
            "temporary",
            "export",
            "authoring",
            "operation",
        ):
            bindings[label].require_unchanged_chain(
                description=(
                    "public clone root" if label == "clone" else f"{label} root"
                )
            )
        clone_binding.require_lexical_binding(description="public clone root")
    return {
        "errors": [],
        "payload_file_count": len(payload_files),
        "status": "materialized",
    }


def _receipt_oid(value: object, *, object_format: str, description: str) -> str:
    expected_length = 40 if object_format == "sha1" else 64
    if (
        not isinstance(value, str)
        or len(value) != expected_length
        or _FULL_OID_RE.fullmatch(value) is None
    ):
        raise ValueError(f"{description} is not a full {object_format} object ID")
    return value


def _load_receipt(text: str, *, description: str) -> dict[str, object]:
    if not text or len(text.encode("utf-8")) > _RECEIPT_MAX_BYTES:
        raise ValueError(f"{description} exceeds the bounded receipt size")
    try:
        raw = safe_paths.loads_json_no_duplicates(text)
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"{description} is not canonical duplicate-free JSON: {exc}") from exc
    if not isinstance(raw, dict) or not all(isinstance(key, str) for key in raw):
        raise ValueError(f"{description} must be one JSON object")
    if set(raw) != public_handoff_check.HANDOFF_RECEIPT_FIELDS:
        raise ValueError(f"{description} does not use the closed handoff schema")
    canonical = _canonical_json(raw)
    if text not in {canonical, canonical.removesuffix("\n")}:
        raise ValueError(f"{description} does not use canonical JSON encoding")
    return raw


def _validate_receipt_shape(
    receipt: dict[str, object],
    *,
    phase: public_handoff_check.HandoffPhase,
    expected_git_sha256: str,
    expected_tag_ref: str | None,
    expected_tag_object_type: str | None,
) -> tuple[str, str | None, str | None]:
    if (
        type(receipt["schema_version"]) is not int
        or receipt["schema_version"] != public_handoff_check.HANDOFF_SCHEMA_VERSION
    ):
        raise ValueError("handoff receipt schema version is not supported")
    if receipt["phase"] != phase.value or receipt["errors"] != []:
        raise ValueError("handoff receipt phase or error state is not clean")
    if receipt["git_executable_sha256"] != expected_git_sha256:
        raise ValueError("handoff receipt Git executable digest changed")
    if not isinstance(receipt["notes"], list) or not all(
        isinstance(note, str) for note in receipt["notes"]
    ):
        raise ValueError("handoff receipt notes must be a string list")
    branch = receipt["branch"]
    remote_name = receipt["remote_name"]
    if not isinstance(branch, str) or not isinstance(remote_name, str):
        raise ValueError("handoff receipt branch and remote must be strings")
    public_handoff_check.publication_branch_ref(branch)
    if not public_handoff_check.publication_remote_name_is_safe(remote_name):
        raise ValueError("handoff receipt remote name is not canonical")
    object_format = receipt["object_format"]
    if object_format not in {"sha1", "sha256"}:
        raise ValueError("handoff receipt object format is unsupported")
    assert isinstance(object_format, str)
    _receipt_oid(
        receipt["expected_parent_commit"],
        object_format=object_format,
        description="handoff expected parent",
    )
    for field in (
        "export_marker_sha256",
        "git_executable_sha256",
        "remote_target_sha256",
    ):
        digest = receipt[field]
        if not isinstance(digest, str) or _SHA256_RE.fullmatch(digest) is None:
            raise ValueError(f"handoff receipt {field} is not a SHA-256 digest")
    if type(receipt["payload_file_count"]) is not int or receipt["payload_file_count"] <= 0:
        raise ValueError("handoff receipt payload count must be positive")

    candidate: str | None
    if phase is public_handoff_check.HandoffPhase.STAGED:
        if receipt["candidate_commit"] is not None:
            raise ValueError("staged handoff receipt must not bind a candidate commit")
        candidate = None
    else:
        candidate = _receipt_oid(
            receipt["candidate_commit"],
            object_format=object_format,
            description="handoff candidate commit",
        )

    tag_oid: str | None = None
    tag_fields = (
        receipt["tag_ref"],
        receipt["tag_oid"],
        receipt["tag_object_type"],
        receipt["tag_peeled_commit"],
    )
    if expected_tag_ref is None:
        if any(value is not None for value in tag_fields):
            raise ValueError("untagged handoff receipt contains tag state")
    else:
        if phase is not public_handoff_check.HandoffPhase.COMMITTED:
            raise ValueError("tag state is valid only for a committed handoff receipt")
        if (
            not public_handoff_check.publication_tag_ref_is_safe(expected_tag_ref)
            or receipt["tag_ref"] != expected_tag_ref
            or receipt["tag_object_type"] not in {"commit", "tag"}
        ):
            raise ValueError("handoff receipt tag binding is invalid")
        if (
            expected_tag_object_type is not None
            and receipt["tag_object_type"] != expected_tag_object_type
        ):
            raise ValueError("handoff receipt tag object type is not the expected type")
        tag_oid = _receipt_oid(
            receipt["tag_oid"],
            object_format=object_format,
            description="handoff tag object",
        )
        peeled = _receipt_oid(
            receipt["tag_peeled_commit"],
            object_format=object_format,
            description="handoff peeled tag commit",
        )
        if peeled != candidate:
            raise ValueError("handoff tag does not peel to the candidate commit")
    return object_format, candidate, tag_oid


def validate_receipt(
    *,
    phase: public_handoff_check.HandoffPhase,
    receipt_json: str,
    expected_git_sha256: str,
    baseline_json: str | None,
    expected_tag_ref: str | None,
    emit: str,
    expected_tag_object_type: str | None = None,
) -> str:
    """Validate one closed receipt and its required continuity baseline."""

    if _SHA256_RE.fullmatch(expected_git_sha256) is None:
        raise ValueError("expected Git executable digest must be SHA-256")
    if expected_tag_ref is None and expected_tag_object_type is not None:
        raise ValueError("expected tag object type requires an expected tag ref")
    receipt = _load_receipt(receipt_json, description="handoff receipt")
    _object_format, candidate, tag_oid = _validate_receipt_shape(
        receipt,
        phase=phase,
        expected_git_sha256=expected_git_sha256,
        expected_tag_ref=expected_tag_ref,
        expected_tag_object_type=expected_tag_object_type,
    )
    if phase is public_handoff_check.HandoffPhase.STAGED:
        if baseline_json is not None or expected_tag_ref is not None:
            raise ValueError("staged receipt must not have a continuity baseline or tag")
    else:
        if baseline_json is None:
            raise ValueError("committed receipt requires its exact prior baseline")
        baseline = _load_receipt(
            baseline_json,
            description="handoff continuity baseline",
        )
        baseline_phase = (
            public_handoff_check.HandoffPhase.COMMITTED
            if expected_tag_ref is not None
            else public_handoff_check.HandoffPhase.STAGED
        )
        _baseline_format, baseline_candidate, _baseline_tag_oid = _validate_receipt_shape(
            baseline,
            phase=baseline_phase,
            expected_git_sha256=expected_git_sha256,
            expected_tag_ref=None,
            expected_tag_object_type=None,
        )
        for field in public_handoff_check.HANDOFF_CONTINUITY_FIELDS:
            if receipt[field] != baseline[field]:
                raise ValueError(f"handoff receipt continuity changed: {field}")
        if expected_tag_ref is not None and candidate != baseline_candidate:
            raise ValueError("tag-bearing receipt changed the candidate commit")

    canonical = _canonical_json(receipt).encode("utf-8")
    if emit == "receipt-sha256":
        return hashlib.sha256(canonical).hexdigest()
    if emit == "candidate-commit" and candidate is not None:
        return candidate
    if emit == "tag-oid" and tag_oid is not None:
        return tag_oid
    raise ValueError(f"requested receipt field is unavailable for {phase.value} phase")


def _remote_records(text: str, *, description: str) -> dict[str, str]:
    if not text or text != text.strip() or "\r" in text:
        raise ValueError(f"{description} must contain unpadded remote records")
    records: dict[str, str] = {}
    for line in text.split("\n"):
        oid, separator, ref = line.partition("\t")
        if (
            separator != "\t"
            or not ref
            or "\t" in ref
            or _FULL_OID_RE.fullmatch(oid) is None
            or ref in records
        ):
            raise ValueError(f"{description} contains an invalid or duplicate record")
        records[ref] = oid
    return records


def verify_remote_readback(
    *,
    branch: str,
    branch_records: str,
    candidate_commit: str,
    tag_ref: str | None,
    tag_records: str | None,
    tag_oid: str | None,
    tag_object_type: str | None,
) -> dict[str, object]:
    """Verify exact branch and optional tag records after publication."""

    branch_ref = public_handoff_check.publication_branch_ref(branch)
    records = _remote_records(branch_records, description="branch readback")
    if records != {branch_ref: candidate_commit}:
        raise ValueError("remote branch readback does not equal the candidate commit")
    optional = (tag_ref, tag_records, tag_oid, tag_object_type)
    if all(value is None for value in optional):
        return {"errors": [], "status": "branch-readback-verified"}
    if any(value is None for value in optional):
        raise ValueError("tag readback arguments must be supplied as one complete set")
    assert tag_ref is not None
    assert tag_records is not None
    assert tag_oid is not None
    assert tag_object_type is not None
    if not public_handoff_check.publication_tag_ref_is_safe(tag_ref):
        raise ValueError("tag readback requires one canonical full tag ref")
    observed_tags = _remote_records(tag_records, description="tag readback")
    if tag_object_type == "commit":
        expected_tags = {tag_ref: tag_oid}
        if tag_oid != candidate_commit:
            raise ValueError("lightweight tag object must equal the candidate commit")
    elif tag_object_type == "tag":
        expected_tags = {tag_ref: tag_oid, f"{tag_ref}^{{}}": candidate_commit}
    else:
        raise ValueError("tag object type must be commit or tag")
    if observed_tags != expected_tags:
        raise ValueError("remote tag readback does not equal the checked tag binding")
    return {"errors": [], "status": "branch-and-tag-readback-verified"}


def _add_topology_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--operation-root",
        type=Path,
        required=True,
        help="Fresh owner-only root for this complete release operation.",
    )
    parser.add_argument(
        "--control-root",
        type=Path,
        required=True,
        help="Exact empty control child of the operation root.",
    )
    parser.add_argument(
        "--state-root",
        type=Path,
        required=True,
        help="Exact owner-only durable-state child of the operation root.",
    )
    parser.add_argument(
        "--temporary-root",
        type=Path,
        required=True,
        help="Exact empty parser-scratch child of the operation root.",
    )
    parser.add_argument(
        "--export-root",
        type=Path,
        required=True,
        help="Exact exporter-owned export child of the operation root.",
    )
    parser.add_argument(
        "--public-clone-root",
        type=Path,
        required=True,
        help="Exact disposable public-clone child of the operation root.",
    )
    parser.add_argument(
        "--authoring-root",
        type=Path,
        required=True,
        help="Separate private authoring checkout used only for identity checks.",
    )


def _parser() -> _Parser:
    parser = _Parser(
        description="Deterministic lifecycle support for canonical public handoff.",
        allow_abbrev=False,
    )
    commands = parser.add_subparsers(dest="command", required=True)

    preflight = commands.add_parser(
        "preflight",
        allow_abbrev=False,
        help="Validate topology and publication routing before network use.",
        description="Validate closed release topology and safe publication routing.",
    )
    _add_topology_arguments(preflight)
    preflight.add_argument(
        "--remote-name",
        required=True,
        help="Bounded simple Git remote name selected for publication.",
    )
    preflight.add_argument(
        "--branch",
        required=True,
        help="Canonical direct-commit branch name selected for publication.",
    )
    preflight.add_argument(
        "--fetch-url",
        required=True,
        help="Reviewed credential-free native Git fetch URL.",
    )
    preflight.add_argument(
        "--push-url",
        required=True,
        help="Reviewed credential-free native Git push URL.",
    )

    remote_parent = commands.add_parser(
        "parse-remote-parent",
        allow_abbrev=False,
        help="Parse one exact remote branch record into its full object ID.",
        description="Parse the exact selected remote branch record fail closed.",
    )
    remote_parent.add_argument(
        "--branch",
        required=True,
        help="Canonical branch name expected in the remote record.",
    )
    remote_parent.add_argument(
        "--record",
        required=True,
        help="Single tab-delimited full-object-ID and full-ref record.",
    )

    materialize = commands.add_parser(
        "materialize",
        allow_abbrev=False,
        help="Replace a disposable clone worktree with the verified export.",
        description="Materialize exact export payload while preserving ordinary Git metadata.",
    )
    _add_topology_arguments(materialize)

    receipt = commands.add_parser(
        "validate-receipt",
        allow_abbrev=False,
        help="Validate one handoff receipt and its phase continuity.",
        description="Validate closed handoff receipt schema and continuity bindings.",
    )
    receipt.add_argument(
        "--phase",
        type=public_handoff_check.HandoffPhase,
        choices=tuple(public_handoff_check.HandoffPhase),
        required=True,
        help="Expected staged or committed receipt phase.",
    )
    receipt.add_argument(
        "--receipt-json",
        required=True,
        help="Exact canonical JSON receipt emitted by the handoff checker.",
    )
    receipt.add_argument(
        "--expected-git-sha256",
        required=True,
        help="Reviewed SHA-256 digest of the retained Git executable.",
    )
    receipt.add_argument(
        "--baseline-json",
        help="Exact prior staged or committed receipt required for continuity.",
    )
    receipt.add_argument(
        "--expected-tag-ref",
        help="Optional canonical full tag ref expected in a tagged receipt.",
    )
    receipt.add_argument(
        "--expected-tag-object-type",
        choices=("commit", "tag"),
        help="Optional expected direct tag object type.",
    )
    receipt.add_argument(
        "--emit",
        choices=("receipt-sha256", "candidate-commit", "tag-oid"),
        required=True,
        help="Single validated binding to emit after all checks pass.",
    )

    readback = commands.add_parser(
        "verify-remote-readback",
        allow_abbrev=False,
        help="Verify exact published branch and optional tag records.",
        description="Verify remote ref readback against checked candidate bindings.",
    )
    readback.add_argument(
        "--branch",
        required=True,
        help="Canonical published branch name.",
    )
    readback.add_argument(
        "--branch-records",
        required=True,
        help="Exact tab-delimited branch readback record.",
    )
    readback.add_argument(
        "--candidate-commit",
        required=True,
        help="Full candidate commit object ID bound before publication.",
    )
    readback.add_argument(
        "--tag-ref",
        help="Optional canonical full tag ref selected for publication.",
    )
    readback.add_argument(
        "--tag-records",
        help="Optional exact direct and peeled tag readback records.",
    )
    readback.add_argument(
        "--tag-oid",
        help="Optional full direct tag object ID bound before publication.",
    )
    readback.add_argument(
        "--tag-object-type",
        choices=("commit", "tag"),
        help="Optional direct tag object type bound before publication.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        if args.command == "preflight":
            result = preflight_network_inputs(
                operation_root=args.operation_root,
                control_root=args.control_root,
                state_root=args.state_root,
                temporary_root=args.temporary_root,
                export_root=args.export_root,
                public_clone_root=args.public_clone_root,
                authoring_root=args.authoring_root,
                remote_name=args.remote_name,
                branch=args.branch,
                fetch_url=args.fetch_url,
                push_url=args.push_url,
            )
            sys.stdout.write(_canonical_json(result))
        elif args.command == "parse-remote-parent":
            sys.stdout.write(parse_remote_parent(branch=args.branch, record=args.record) + "\n")
        elif args.command == "materialize":
            result = materialize_export(
                operation_root=args.operation_root,
                control_root=args.control_root,
                state_root=args.state_root,
                temporary_root=args.temporary_root,
                export_root=args.export_root,
                public_clone_root=args.public_clone_root,
                authoring_root=args.authoring_root,
            )
            sys.stdout.write(_canonical_json(result))
        elif args.command == "validate-receipt":
            sys.stdout.write(
                validate_receipt(
                    phase=args.phase,
                    receipt_json=args.receipt_json,
                    expected_git_sha256=args.expected_git_sha256,
                    baseline_json=args.baseline_json,
                    expected_tag_ref=args.expected_tag_ref,
                    emit=args.emit,
                    expected_tag_object_type=args.expected_tag_object_type,
                )
                + "\n"
            )
        elif args.command == "verify-remote-readback":
            result = verify_remote_readback(
                branch=args.branch,
                branch_records=args.branch_records,
                candidate_commit=args.candidate_commit,
                tag_ref=args.tag_ref,
                tag_records=args.tag_records,
                tag_oid=args.tag_oid,
                tag_object_type=args.tag_object_type,
            )
            sys.stdout.write(_canonical_json(result))
        else:
            raise ValueError("unsupported lifecycle command")
    except (_CliError, OSError, ValueError) as exc:
        sys.stderr.write(f"public handoff lifecycle failed: {exc}\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
