#!/usr/bin/env python3

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path, PurePosixPath
import secrets
import stat
import sys
from collections.abc import Callable, Mapping

import public_release_check
import public_surface
import resource_cleanup
import safe_paths


REPO_ROOT = Path(__file__).resolve().parent.parent
EXPORT_FILE_MODE = 0o600
EXPORT_DIRECTORY_MODE = public_release_check.PUBLIC_EXPORT_DIRECTORY_MODE
EXPORT_ROOT_MODE = public_release_check.PUBLIC_EXPORT_ROOT_MODE


@dataclass(frozen=True)
class PublicExportResult:
    copied_files: tuple[str, ...]
    retained_previous_export: Path | None


class PublicExportFailure(RuntimeError):
    """An export failure whose uncertain filesystem state was retained."""

    def __init__(
        self,
        retained_paths: tuple[Path, ...],
        unverified_locations: tuple[Path, ...],
        cause: BaseException,
        *,
        candidate_identity: tuple[int, ...] | None = None,
        parent_identity: tuple[int, ...] | None = None,
    ) -> None:
        if not retained_paths and not unverified_locations:
            raise ValueError("public export failure must identify uncertain state")
        if set(retained_paths) & set(unverified_locations):
            raise ValueError(
                "verified retained paths and unverified locations must be disjoint"
            )
        self.retained_paths = retained_paths
        self.unverified_locations = unverified_locations
        self.candidate_identity = candidate_identity
        self.parent_identity = parent_identity
        retained = ", ".join(str(path) for path in retained_paths) or "none"
        unverified = (
            ", ".join(str(path) for path in unverified_locations) or "none"
        )
        identity = (
            f"; bound candidate identity {candidate_identity}"
            if candidate_identity is not None
            else ""
        )
        if parent_identity is not None:
            identity += f"; bound output-parent identity {parent_identity}"
        super().__init__(
            "public export failed; verified retained paths: "
            f"{retained}; unverified nominal locations: {unverified}"
            f"{identity}: {cause}"
        )


@dataclass(frozen=True)
class PublicSourceFile:
    path: Path
    relative_path: str
    content: bytes
    source_sha256: str
    sha256: str
    posix_mode: int


@dataclass
class _DirectoryAllocation:
    name: str = ""
    attempted: bool = False
    descriptor: int | None = None


@dataclass(frozen=True)
class _PreimageSnapshot:
    identity_and_mode: tuple[int, ...]
    tree: public_release_check.PublicExportTreeSnapshot | None


@dataclass
class _ExportTransaction:
    output: Path
    parent: safe_paths.OutputDirectoryBinding
    parent_identity: tuple[int, ...]
    candidate: _DirectoryAllocation
    backup: _DirectoryAllocation
    previous_descriptor: int | None = None
    previous_snapshot: _PreimageSnapshot | None = None
    candidate_location: str = "none"
    preimage_location: str = "none"

    @property
    def parent_descriptor(self) -> int:
        return self.parent.descriptor


def _cleanup_export_resources(
    descriptors: tuple[tuple[str, int], ...],
    *,
    bindings: tuple[tuple[str, safe_paths.OutputDirectoryBinding], ...] = (),
    actions: tuple[tuple[str, Callable[[], object]], ...] = (),
    primary: BaseException | None = None,
) -> None:
    """Attempt every cleanup and preserve any failure already in flight."""

    resource_cleanup.cleanup_actions(
        tuple(
            (
                description,
                lambda descriptor=descriptor: os.close(descriptor),
            )
            for description, descriptor in descriptors
        )
        + tuple((description, binding.close) for description, binding in bindings)
        + actions,
        primary=primary,
    )


def _required_open_flag(name: str) -> int:
    value = getattr(os, name, None)
    if not isinstance(value, int) or value == 0:
        raise ValueError(
            f"descriptor-safe public export requires platform flag {name}"
        )
    return value


def _directory_open_flags() -> int:
    return (
        os.O_RDONLY
        | _required_open_flag("O_DIRECTORY")
        | _required_open_flag("O_NOFOLLOW")
        | getattr(os, "O_CLOEXEC", 0)
    )


def _object_identity(metadata: os.stat_result) -> tuple[int, ...]:
    """Bind one object without mutable size, timestamps, or directory nlink."""

    return (
        metadata.st_dev,
        metadata.st_ino,
        stat.S_IFMT(metadata.st_mode),
        metadata.st_uid,
    )


def _path_exists_at(parent_descriptor: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return False
    return True


def _assert_bound_name(
    parent_descriptor: int,
    name: str,
    descriptor: int,
    *,
    description: str,
) -> None:
    try:
        named = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
    except FileNotFoundError as exc:
        raise ValueError(f"{description} pathname disappeared") from exc
    bound = os.fstat(descriptor)
    if (
        not stat.S_ISDIR(named.st_mode)
        or not stat.S_ISDIR(bound.st_mode)
        or _object_identity(named) != _object_identity(bound)
    ):
        raise ValueError(
            f"{description} pathname no longer identifies its bound directory"
        )


def _allocate_bound_directory(
    parent_descriptor: int,
    allocation: _DirectoryAllocation,
    prefix: str,
) -> None:
    for _attempt in range(32):
        name = f"{prefix}{secrets.token_hex(16)}"
        allocation.name = name
        allocation.attempted = True
        try:
            os.mkdir(name, EXPORT_ROOT_MODE, dir_fd=parent_descriptor)
        except FileExistsError:
            allocation.name = ""
            allocation.attempted = False
            continue
        descriptor = os.open(
            name,
            _directory_open_flags(),
            dir_fd=parent_descriptor,
        )
        allocation.descriptor = descriptor
        os.fchmod(descriptor, EXPORT_ROOT_MODE)
        _assert_bound_name(
            parent_descriptor,
            name,
            descriptor,
            description="new public-export directory",
        )
        return
    raise OSError("could not allocate a unique public-export directory")


def _write_all(descriptor: int, content: bytes) -> None:
    offset = 0
    while offset < len(content):
        written = os.write(descriptor, content[offset:])
        if written <= 0:
            raise OSError("public-export file write made no progress")
        offset += written


def _write_planned_file(
    parent_descriptor: int,
    name: str,
    content: bytes,
    posix_mode: int,
) -> None:
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | _required_open_flag("O_NOFOLLOW")
        | getattr(os, "O_CLOEXEC", 0)
    )
    descriptor = os.open(
        name,
        flags,
        EXPORT_FILE_MODE,
        dir_fd=parent_descriptor,
    )
    try:
        _write_all(descriptor, content)
        os.fchmod(descriptor, posix_mode)
        os.fsync(descriptor)
        metadata = os.fstat(descriptor)
        named_metadata = os.stat(
            name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_size != len(content)
            or stat.S_IMODE(metadata.st_mode) != posix_mode
            or _object_identity(named_metadata) != _object_identity(metadata)
        ):
            raise ValueError(
                f"public-export file does not match its planned bytes/mode: {name}"
            )
    finally:
        _cleanup_export_resources(
            (("planned public-export file", descriptor),),
            primary=sys.exception(),
        )
    os.fsync(parent_descriptor)


def _write_export_files(
    root_descriptor: int,
    sources: list[PublicSourceFile],
    marker_bytes: bytes,
) -> None:
    descriptors: dict[str, int] = {"": root_descriptor}
    try:
        for source in sources:
            parts = PurePosixPath(source.relative_path).parts
            current = ""
            for component in parts[:-1]:
                next_relative = (
                    component if not current else f"{current}/{component}"
                )
                if next_relative not in descriptors:
                    os.mkdir(
                        component,
                        EXPORT_DIRECTORY_MODE,
                        dir_fd=descriptors[current],
                    )
                    os.fsync(descriptors[current])
                    child = os.open(
                        component,
                        _directory_open_flags(),
                        dir_fd=descriptors[current],
                    )
                    try:
                        descriptors[next_relative] = child
                    except BaseException as exc:
                        _cleanup_export_resources(
                            ((f"unregistered public-export directory {next_relative}", child),),
                            primary=exc,
                        )
                        raise
                    os.fchmod(child, EXPORT_DIRECTORY_MODE)
                current = next_relative
            _write_planned_file(
                descriptors[current],
                parts[-1],
                source.content,
                source.posix_mode,
            )
        _write_planned_file(
            root_descriptor,
            public_release_check.PUBLIC_EXPORT_OWNERSHIP_MARKER,
            marker_bytes,
            public_release_check.PUBLIC_EXPORT_MARKER_MODE,
        )
        os.fsync(root_descriptor)
    finally:
        _cleanup_export_resources(
            tuple(
                (f"public-export directory {relative_path}", descriptor)
                for relative_path, descriptor in reversed(tuple(descriptors.items()))
                if relative_path
            ),
            primary=sys.exception(),
        )


def _marker_bytes(records: Mapping[str, tuple[str, int]]) -> bytes:
    return public_release_check.public_export_marker_bytes(records)


def has_symlink_in_relative_path(root: Path, path: Path) -> bool:
    current = root
    for part in path.relative_to(root).parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def safe_existing_output_path(path: Path) -> None:
    safe_paths.require_output_path(path)
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return
    if not stat.S_ISDIR(metadata.st_mode):
        raise ValueError(f"refusing to overwrite non-directory output path: {path}")


def write_ownership_marker(
    output: Path,
    records: Mapping[str, tuple[str, int]],
) -> None:
    """Write a deterministic fixture/export marker from explicit expectations."""

    descriptor = os.open(output, _directory_open_flags())
    try:
        _write_planned_file(
            descriptor,
            public_release_check.PUBLIC_EXPORT_OWNERSHIP_MARKER,
            _marker_bytes(records),
            public_release_check.PUBLIC_EXPORT_MARKER_MODE,
        )
    finally:
        _cleanup_export_resources(
            (("public-export ownership-marker root", descriptor),),
            primary=sys.exception(),
        )


def public_source_files(
    root: Path,
    *,
    git_executable: public_release_check.GitExecutableBinding | None = None,
    _binding_sink: list[public_release_check.PublicSourceSnapshotBinding]
    | None = None,
) -> list[PublicSourceFile]:
    root = root.resolve()
    selected = set(public_surface.PUBLIC_REQUIRED_FILES)
    retained_bindings: list[public_release_check.PublicSourceSnapshotBinding] = []
    if git_executable is None:
        snapshots = public_release_check.checked_public_source_snapshots(
            root,
            selected,
            _binding_sink=retained_bindings,
        )
    else:
        git_executable.require_current()
        snapshots = public_release_check.checked_public_source_snapshots(
            root,
            selected,
            git_executable=git_executable,
            _binding_sink=retained_bindings,
        )
        git_executable.require_current()
    if len(retained_bindings) != 1:
        failure = RuntimeError(
            "public source snapshot did not retain exactly one root/Git binding"
        )
        resource_cleanup.cleanup_actions(
            tuple(
                (f"unexpected public source binding {index}", binding.close)
                for index, binding in enumerate(retained_bindings, start=1)
            ),
            primary=failure,
        )
        raise failure
    binding = retained_bindings[0]
    binding_transferred = False
    try:
        files: list[PublicSourceFile] = []
        binding.require_generation_current(
            description="public source before selected-file reads"
        )
        for rel in sorted(selected):
            path = root / rel
            if has_symlink_in_relative_path(root, path):
                raise ValueError(f"refusing to export symlink path: {rel}")
            if not safe_paths.path_within_root(path, root):
                raise ValueError(f"refusing to export path outside repository root: {rel}")
            source_sha256, posix_mode = snapshots[rel]
            source_content = public_release_check.stable_file_bytes(
                path,
                expected_snapshot=(source_sha256, posix_mode),
            )
            binding.require_generation_current(
                description=f"public source selected-file read {rel}"
            )
            content = (
                public_surface.PUBLIC_EXPORT_GITIGNORE_TEXT.encode("utf-8")
                if rel == ".gitignore"
                else source_content
            )
            files.append(
                PublicSourceFile(
                    path=path,
                    relative_path=rel,
                    content=content,
                    source_sha256=source_sha256,
                    sha256=hashlib.sha256(content).hexdigest(),
                    posix_mode=posix_mode,
                )
            )
        binding.require_current(description="public source after selected-file reads")
        if _binding_sink is not None:
            _binding_sink.append(binding)
            binding_transferred = True
        return files
    finally:
        if not binding_transferred:
            resource_cleanup.cleanup_actions(
                (("public source snapshot binding", binding.close),),
                primary=sys.exception(),
            )


def _checked_bound_export(
    descriptor: int,
    records: Mapping[str, tuple[str, int]],
) -> public_release_check.PublicExportTreeSnapshot:
    return public_release_check.checked_public_export_ownership_descriptor(
        descriptor,
        expected_records=records,
    )


def _open_existing_output(parent_descriptor: int, name: str) -> int:
    descriptor = os.open(name, _directory_open_flags(), dir_fd=parent_descriptor)
    try:
        _assert_bound_name(
            parent_descriptor,
            name,
            descriptor,
            description="existing public-export destination",
        )
        return descriptor
    except BaseException as primary:
        _cleanup_export_resources(
            (("existing public-export destination", descriptor),),
            primary=primary,
        )
        raise


def _descriptor_is_empty(descriptor: int) -> bool:
    before = os.fstat(descriptor)
    if not stat.S_ISDIR(before.st_mode):
        raise ValueError("bound public-export preimage is not a directory")

    def names() -> tuple[str, ...]:
        scan_descriptor = os.open(
            ".",
            _directory_open_flags(),
            dir_fd=descriptor,
        )
        try:
            if (
                safe_paths.stable_file_metadata(os.fstat(scan_descriptor))
                != safe_paths.stable_file_metadata(os.fstat(descriptor))
            ):
                raise ValueError(
                    "bound public-export preimage changed before enumeration"
                )
            with os.scandir(scan_descriptor) as entries:
                return tuple(sorted(entry.name for entry in entries))
        finally:
            _cleanup_export_resources(
                (("public-export preimage scan", scan_descriptor),),
                primary=sys.exception(),
            )

    first_names = names()
    second_names = names()
    after = os.fstat(descriptor)
    if (
        first_names != second_names
        or safe_paths.stable_file_metadata(before)
        != safe_paths.stable_file_metadata(after)
    ):
        raise ValueError("bound public-export preimage changed during inspection")
    return not first_names


def _preimage_identity_and_mode(descriptor: int) -> tuple[int, ...]:
    metadata = os.fstat(descriptor)
    if not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("public-export preimage is not a directory")
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_uid,
        metadata.st_gid,
    )


def _capture_preimage_snapshot(descriptor: int) -> _PreimageSnapshot:
    before = os.fstat(descriptor)
    if _descriptor_is_empty(descriptor):
        tree = None
    else:
        tree = public_release_check.checked_public_export_ownership_descriptor(
            descriptor
        )
    after = os.fstat(descriptor)
    if (
        safe_paths.stable_file_metadata(before)
        != safe_paths.stable_file_metadata(after)
    ):
        raise ValueError("public-export preimage changed while it was captured")
    return _PreimageSnapshot(_preimage_identity_and_mode(descriptor), tree)


def _require_preimage_snapshot(
    descriptor: int,
    expected: _PreimageSnapshot,
) -> None:
    if _preimage_identity_and_mode(descriptor) != expected.identity_and_mode:
        raise ValueError("public-export preimage identity or mode changed")
    if expected.tree is None:
        if not _descriptor_is_empty(descriptor):
            raise ValueError("empty public-export preimage acquired unexpected content")
        return
    actual = public_release_check.checked_public_export_ownership_descriptor(
        descriptor
    )
    if actual != expected.tree:
        raise ValueError("retained previous public export changed")


def _transaction_parent_current(transaction: _ExportTransaction) -> bool:
    try:
        transaction.parent.require_lexical_binding(
            description="public-export output parent"
        )
    except (OSError, ValueError):
        return False
    return True


def _bound_name_matches(
    parent_descriptor: int,
    name: str,
    descriptor: int,
) -> bool:
    try:
        _assert_bound_name(
            parent_descriptor,
            name,
            descriptor,
            description="public-export retained object",
        )
    except (OSError, ValueError):
        return False
    return True


def _transaction_failure_locations(
    transaction: _ExportTransaction,
) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
    """Return a no-throw, location-only receipt for retained transaction state."""

    retained: list[Path] = []
    unverified: list[Path] = []
    parent_current = _transaction_parent_current(transaction)
    for created_path in transaction.parent.created_paths:
        (retained if parent_current else unverified).append(created_path)

    candidate = transaction.candidate
    if candidate.attempted and candidate.name:
        staging_path = transaction.output.parent / candidate.name
        output_path = transaction.output
        matches: list[Path] = []
        if parent_current and candidate.descriptor is not None:
            for name, path in (
                (candidate.name, staging_path),
                (transaction.output.name, output_path),
            ):
                if _bound_name_matches(
                    transaction.parent_descriptor,
                    name,
                    candidate.descriptor,
                ):
                    matches.append(path)
        if len(matches) == 1:
            retained.extend(matches)
        elif matches:
            unverified.extend(matches)
        else:
            nominal = (
                output_path
                if transaction.candidate_location == "output"
                else staging_path
            )
            unverified.append(nominal)

    backup = transaction.backup
    if backup.attempted and backup.name:
        wrapper_path = transaction.output.parent / backup.name
        wrapper_current = (
            parent_current
            and backup.descriptor is not None
            and _bound_name_matches(
                transaction.parent_descriptor,
                backup.name,
                backup.descriptor,
            )
        )
        if wrapper_current:
            retained.append(wrapper_path)
        else:
            unverified.append(wrapper_path)
        if transaction.preimage_location in {"backup", "unknown"}:
            tree_path = wrapper_path / "tree"
            tree_current = (
                wrapper_current
                and backup.descriptor is not None
                and transaction.previous_descriptor is not None
                and _bound_name_matches(
                    backup.descriptor,
                    "tree",
                    transaction.previous_descriptor,
                )
            )
            if tree_current:
                retained.append(tree_path)
            else:
                unverified.append(tree_path)

    if (
        transaction.previous_descriptor is not None
        and transaction.preimage_location in {"restored", "unknown"}
    ):
        restored_current = parent_current and _bound_name_matches(
            transaction.parent_descriptor,
            transaction.output.name,
            transaction.previous_descriptor,
        )
        (retained if restored_current else unverified).append(transaction.output)

    retained_tuple = tuple(dict.fromkeys(retained))
    unverified_tuple = tuple(
        path
        for path in dict.fromkeys(unverified)
        if path not in retained_tuple
    )
    return retained_tuple, unverified_tuple


def _reconcile_transaction_locations(transaction: _ExportTransaction) -> None:
    if not _transaction_parent_current(transaction):
        return
    candidate = transaction.candidate
    if candidate.descriptor is not None and candidate.name:
        candidate_edges = [
            location
            for location, name in (
                ("staging", candidate.name),
                ("output", transaction.output.name),
            )
            if _bound_name_matches(
                transaction.parent_descriptor,
                name,
                candidate.descriptor,
            )
        ]
        if len(candidate_edges) == 1:
            transaction.candidate_location = candidate_edges[0]
    if transaction.previous_descriptor is not None:
        preimage_edges: list[str] = []
        if _bound_name_matches(
            transaction.parent_descriptor,
            transaction.output.name,
            transaction.previous_descriptor,
        ):
            preimage_edges.append(
                "output"
                if transaction.preimage_location == "output"
                else "restored"
            )
        if (
            transaction.backup.descriptor is not None
            and _bound_name_matches(
                transaction.backup.descriptor,
                "tree",
                transaction.previous_descriptor,
            )
        ):
            preimage_edges.append("backup")
        if len(preimage_edges) == 1:
            transaction.preimage_location = preimage_edges[0]


def _restore_preimage_if_safe(
    transaction: _ExportTransaction,
    primary: BaseException,
) -> None:
    try:
        _reconcile_transaction_locations(transaction)
        if (
            transaction.candidate_location == "output"
            or transaction.preimage_location != "backup"
            or transaction.backup.descriptor is None
            or transaction.previous_descriptor is None
            or transaction.previous_snapshot is None
            or _path_exists_at(
                transaction.parent_descriptor,
                transaction.output.name,
            )
        ):
            return
        transaction.parent.require_lexical_binding(
            description="public-export output parent"
        )
        _assert_bound_name(
            transaction.parent_descriptor,
            transaction.backup.name,
            transaction.backup.descriptor,
            description="previous-export wrapper",
        )
        _assert_bound_name(
            transaction.backup.descriptor,
            "tree",
            transaction.previous_descriptor,
            description="retained previous public export",
        )
        _require_preimage_snapshot(
            transaction.previous_descriptor,
            transaction.previous_snapshot,
        )
        transaction.preimage_location = "unknown"
        os.rename(
            "tree",
            transaction.output.name,
            src_dir_fd=transaction.backup.descriptor,
            dst_dir_fd=transaction.parent_descriptor,
        )
        transaction.preimage_location = "restored"
        os.fsync(transaction.parent_descriptor)
        os.fsync(transaction.backup.descriptor)
        _assert_bound_name(
            transaction.parent_descriptor,
            transaction.output.name,
            transaction.previous_descriptor,
            description="restored previous public export",
        )
        _require_preimage_snapshot(
            transaction.previous_descriptor,
            transaction.previous_snapshot,
        )
    except BaseException as recovery_error:
        primary.add_note(
            "previous public export could not be restored intact: "
            f"{recovery_error}"
        )


def export_public_tree(
    root: Path,
    output: Path,
    force: bool,
    *,
    git_executable: public_release_check.GitExecutableBinding | None = None,
) -> PublicExportResult:
    output = output.expanduser().absolute()
    safe_existing_output_path(output)
    root = root.resolve()
    if (
        output.resolve(strict=False) == root
        or safe_paths.path_within_root(output, root)
        or safe_paths.path_within_root(root, output)
    ):
        raise ValueError(
            "output directory must not be the repository root, inside it, or an ancestor of it"
        )
    safe_paths.require_output_path(output)

    parent_binding = safe_paths.open_output_directory(output.parent)
    try:
        parent_identity = _object_identity(os.fstat(parent_binding.descriptor))
    except BaseException as exc:
        if parent_binding.created_paths:
            exc.add_note(
                "public-export output-parent allocation created or may have "
                "created: "
                + ", ".join(str(path) for path in parent_binding.created_paths)
            )
        _cleanup_export_resources(
            (),
            bindings=(("public-export output parent", parent_binding),),
            primary=exc,
        )
        raise
    transaction = _ExportTransaction(
        output=output,
        parent=parent_binding,
        parent_identity=parent_identity,
        candidate=_DirectoryAllocation(),
        backup=_DirectoryAllocation(),
    )
    sources: list[PublicSourceFile] = []
    records: dict[str, tuple[str, int]] = {}
    source_binding: public_release_check.PublicSourceSnapshotBinding | None = None
    completed_result: PublicExportResult | None = None

    def require_parent() -> None:
        parent_binding.require_lexical_binding(
            description="public-export output parent"
        )

    def bind_preimage() -> None:
        transaction.previous_descriptor = _open_existing_output(
            transaction.parent_descriptor,
            output.name,
        )
        transaction.preimage_location = "output"
        if not _descriptor_is_empty(transaction.previous_descriptor) and not force:
            raise FileExistsError(
                "refusing to overwrite existing output directory without "
                f"--force: {output}"
            )
        try:
            transaction.previous_snapshot = _capture_preimage_snapshot(
                transaction.previous_descriptor
            )
        except ValueError as exc:
            raise ValueError(
                "refusing to replace a nonempty destination that is not an "
                f"intact exporter-owned public tree: {exc}"
            ) from exc

    try:
        require_parent()
        if _path_exists_at(transaction.parent_descriptor, output.name):
            bind_preimage()

        source_bindings: list[
            public_release_check.PublicSourceSnapshotBinding
        ] = []
        if git_executable is None:
            sources = public_source_files(root, _binding_sink=source_bindings)
        else:
            git_executable.require_current()
            sources = public_source_files(
                root,
                git_executable=git_executable,
                _binding_sink=source_bindings,
            )
            git_executable.require_current()
        if len(source_bindings) != 1:
            failure = RuntimeError(
                "public export did not retain exactly one source root/Git binding"
            )
            resource_cleanup.cleanup_actions(
                tuple(
                    (f"unexpected public export source binding {index}", binding.close)
                    for index, binding in enumerate(source_bindings, start=1)
                ),
                primary=failure,
            )
            raise failure
        source_binding = source_bindings[0]
        records = {
            source.relative_path: (source.sha256, source.posix_mode)
            for source in sources
        }
        marker_bytes = _marker_bytes(records)

        _allocate_bound_directory(
            transaction.parent_descriptor,
            transaction.candidate,
            f".{output.name}.public-export-",
        )
        candidate_descriptor = transaction.candidate.descriptor
        if candidate_descriptor is None:
            raise RuntimeError("public-export candidate descriptor is unavailable")
        transaction.candidate_location = "staging"
        require_parent()
        os.fsync(transaction.parent_descriptor)

        _write_export_files(candidate_descriptor, sources, marker_bytes)
        source_binding.require_current(
            description="public source after candidate write"
        )
        candidate_snapshot = _checked_bound_export(candidate_descriptor, records)

        if _path_exists_at(transaction.parent_descriptor, output.name):
            if transaction.previous_descriptor is None:
                bind_preimage()
            if (
                transaction.previous_descriptor is None
                or transaction.previous_snapshot is None
            ):
                raise RuntimeError("public-export preimage binding is unavailable")
            _assert_bound_name(
                transaction.parent_descriptor,
                output.name,
                transaction.previous_descriptor,
                description="existing public-export destination",
            )
            _require_preimage_snapshot(
                transaction.previous_descriptor,
                transaction.previous_snapshot,
            )
            _allocate_bound_directory(
                transaction.parent_descriptor,
                transaction.backup,
                f".{output.name}.previous-export-",
            )
            backup_descriptor = transaction.backup.descriptor
            if backup_descriptor is None:
                raise RuntimeError("previous-export wrapper descriptor is unavailable")
            require_parent()
            os.fsync(transaction.parent_descriptor)
            _require_preimage_snapshot(
                transaction.previous_descriptor,
                transaction.previous_snapshot,
            )
            transaction.preimage_location = "unknown"
            os.rename(
                output.name,
                "tree",
                src_dir_fd=transaction.parent_descriptor,
                dst_dir_fd=backup_descriptor,
            )
            transaction.preimage_location = "backup"
            os.fsync(transaction.parent_descriptor)
            os.fsync(backup_descriptor)
            _assert_bound_name(
                transaction.parent_descriptor,
                transaction.backup.name,
                backup_descriptor,
                description="previous-export wrapper",
            )
            _assert_bound_name(
                backup_descriptor,
                "tree",
                transaction.previous_descriptor,
                description="retained previous public export",
            )
            _require_preimage_snapshot(
                transaction.previous_descriptor,
                transaction.previous_snapshot,
            )
            require_parent()
        elif transaction.previous_descriptor is not None:
            raise ValueError(
                "existing public-export destination disappeared during replacement"
            )

        _assert_bound_name(
            transaction.parent_descriptor,
            transaction.candidate.name,
            candidate_descriptor,
            description="public-export staging candidate",
        )
        require_parent()
        if _checked_bound_export(candidate_descriptor, records) != candidate_snapshot:
            raise ValueError("public-export candidate changed before promotion")
        _assert_bound_name(
            transaction.parent_descriptor,
            transaction.candidate.name,
            candidate_descriptor,
            description="public-export staging candidate",
        )
        require_parent()
        source_binding.require_current(
            description="public source before candidate promotion"
        )
        if _path_exists_at(transaction.parent_descriptor, output.name):
            raise FileExistsError(
                f"public-export destination appeared before promotion: {output}"
            )
        transaction.candidate_location = "unknown"
        os.rename(
            transaction.candidate.name,
            output.name,
            src_dir_fd=transaction.parent_descriptor,
            dst_dir_fd=transaction.parent_descriptor,
        )
        transaction.candidate_location = "output"
        os.fsync(transaction.parent_descriptor)
        _assert_bound_name(
            transaction.parent_descriptor,
            output.name,
            candidate_descriptor,
            description="promoted public export",
        )
        require_parent()
        if _checked_bound_export(candidate_descriptor, records) != candidate_snapshot:
            raise ValueError(
                "promoted public export does not equal the validated candidate snapshot"
            )

        retained_previous_export: Path | None = None
        if transaction.preimage_location == "backup":
            if (
                transaction.backup.descriptor is None
                or transaction.previous_descriptor is None
                or transaction.previous_snapshot is None
            ):
                raise RuntimeError("retained preimage descriptors are unavailable")
            _assert_bound_name(
                transaction.parent_descriptor,
                transaction.backup.name,
                transaction.backup.descriptor,
                description="final previous-export wrapper",
            )
            _assert_bound_name(
                transaction.backup.descriptor,
                "tree",
                transaction.previous_descriptor,
                description="final retained previous public export",
            )
            _require_preimage_snapshot(
                transaction.previous_descriptor,
                transaction.previous_snapshot,
            )
            retained_previous_export = (
                output.parent / transaction.backup.name / "tree"
            )

        if _checked_bound_export(candidate_descriptor, records) != candidate_snapshot:
            raise ValueError(
                "post-check public export does not equal the validated candidate snapshot"
            )
        require_parent()
        _assert_bound_name(
            transaction.parent_descriptor,
            output.name,
            candidate_descriptor,
            description="final public export",
        )
        if retained_previous_export is not None:
            if (
                transaction.backup.descriptor is None
                or transaction.previous_descriptor is None
                or transaction.previous_snapshot is None
            ):
                raise RuntimeError("retained preimage binding was lost")
            _assert_bound_name(
                transaction.parent_descriptor,
                transaction.backup.name,
                transaction.backup.descriptor,
                description="terminal previous-export wrapper",
            )
            _assert_bound_name(
                transaction.backup.descriptor,
                "tree",
                transaction.previous_descriptor,
                description="terminal retained previous public export",
            )
            _require_preimage_snapshot(
                transaction.previous_descriptor,
                transaction.previous_snapshot,
            )
        require_parent()
        _assert_bound_name(
            transaction.parent_descriptor,
            output.name,
            candidate_descriptor,
            description="terminal public export",
        )
        source_binding.require_current(
            description="terminal public export source",
            confirm_release=True,
        )
        if git_executable is not None:
            git_executable.require_current()
        completed_result = PublicExportResult(
            tuple(source.relative_path for source in sources),
            retained_previous_export,
        )
        return completed_result
    except BaseException as exc:
        _restore_preimage_if_safe(transaction, exc)
        try:
            retained_paths, unverified_locations = _transaction_failure_locations(
                transaction
            )
        except BaseException as receipt_error:
            exc.add_note(f"public export receipt inspection failed: {receipt_error}")
            retained_paths = ()
            unverified_locations = ()
        candidate_identity: tuple[int, ...] | None = None
        if transaction.candidate.descriptor is not None:
            try:
                candidate_identity = _object_identity(
                    os.fstat(transaction.candidate.descriptor)
                )
            except BaseException as identity_error:
                exc.add_note(
                    "bound public-export candidate identity could not be read for "
                    f"the failure receipt: {identity_error}"
                )
        if (retained_paths or unverified_locations) and isinstance(exc, Exception):
            raise PublicExportFailure(
                retained_paths,
                unverified_locations,
                exc,
                candidate_identity=candidate_identity,
                parent_identity=transaction.parent_identity,
            ) from exc
        if retained_paths or unverified_locations:
            exc.add_note(
                "public export interruption state; verified retained paths: "
                + (", ".join(str(path) for path in retained_paths) or "none")
                + "; unverified nominal locations: "
                + (", ".join(str(path) for path in unverified_locations) or "none")
            )
        raise
    finally:
        active_failure = sys.exception()
        try:
            _cleanup_export_resources(
                tuple(
                    (description, descriptor)
                    for description, descriptor in (
                        (
                            "retained previous public-export tree",
                            transaction.previous_descriptor,
                        ),
                        (
                            "previous-export wrapper",
                            transaction.backup.descriptor,
                        ),
                        (
                            "public-export candidate",
                            transaction.candidate.descriptor,
                        ),
                    )
                    if descriptor is not None
                ),
                bindings=(("public-export output parent", parent_binding),),
                actions=(
                    (
                        "public source snapshot binding",
                        source_binding.close,
                    ),
                )
                if source_binding is not None
                else (),
                primary=active_failure,
            )
        except BaseException as cleanup:
            if completed_result is None:
                raise
            verified_paths = [output]
            if completed_result.retained_previous_export is not None:
                verified_paths.append(completed_result.retained_previous_export)
            retained_paths = tuple(verified_paths)
            if isinstance(cleanup, Exception):
                raise PublicExportFailure(
                    retained_paths,
                    (),
                    cleanup,
                    parent_identity=transaction.parent_identity,
                ) from cleanup
            cleanup.add_note(
                "public export cleanup interruption after terminal validation; "
                "verified retained paths: "
                + ", ".join(str(path) for path in retained_paths)
            )
            raise


def _publication_git_binding(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
) -> tuple[public_release_check.GitExecutableBinding | None, bool]:
    inherited_boundary = os.environ.get(
        public_release_check.PUBLICATION_BOUNDARY_ENV
    )
    if inherited_boundary not in {None, "1"}:
        parser.error(
            f"{public_release_check.PUBLICATION_BOUNDARY_ENV} must be absent or equal 1"
        )
    boundary = bool(args.publication_boundary or inherited_boundary == "1")
    binding = public_release_check.publication_executable_binding(
        parser,
        explicit_descriptor=args.git_executable_fd,
        explicit_sha256=args.git_executable_sha256,
        propagated_path_env=public_release_check.PUBLICATION_GIT_PROC_PATH_ENV,
        propagated_sha256_env=public_release_check.PUBLICATION_GIT_SHA256_ENV,
        description="bound Git executable",
    )
    if boundary and binding is None:
        parser.error(
            "publication-boundary export requires one retained Git descriptor "
            "and approved SHA-256 digest"
        )
    return binding, boundary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create a sanitized public framework export tree.",
        allow_abbrev=False,
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=REPO_ROOT,
        help="Framework authoring repository root.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help=(
            "Absent, empty, or (with --force) intact exporter-owned destination "
            "outside the repository; it must not be the repository, a descendant, "
            "or an ancestor."
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Replace only an intact destination previously created by this "
            "exporter; unrelated nonempty directories are refused and the exact "
            "prior directory is retained for explicit cleanup."
        ),
    )
    parser.add_argument(
        "--publication-boundary",
        action="store_true",
        help="Require the canonical isolated source-to-export invocation.",
    )
    parser.add_argument(
        "--git-executable-fd",
        type=int,
        help=(
            "Inherited descriptor for the reviewed Git executable; supply it "
            "with --git-executable-sha256."
        ),
    )
    parser.add_argument(
        "--git-executable-sha256",
        help=(
            "Approved lowercase SHA-256 digest of the executable bound by "
            "--git-executable-fd."
        ),
    )
    args = parser.parse_args(argv)
    git_executable, publication_boundary = _publication_git_binding(parser, args)

    try:
        result = export_public_tree(
            args.root,
            args.output,
            args.force,
            git_executable=git_executable,
        )
    except (
        OSError,
        PublicExportFailure,
        UnicodeError,
        ValueError,
        safe_paths.OutputDirectoryBindingError,
    ) as exc:
        parser.error(str(exc))
    finally:
        if git_executable is not None:
            try:
                git_executable.close()
            except (OSError, RuntimeError, ValueError) as exc:
                parser.error(f"bound Git executable cleanup failed: {exc}")
    print(f"Exported {len(result.copied_files)} files to {args.output.resolve()}")
    if publication_boundary and git_executable is not None:
        print(f"Bound Git executable SHA-256: {git_executable.sha256}")
    if result.retained_previous_export is not None:
        print(
            "Retained the previous verified export for explicit inspection at "
            f"{result.retained_previous_export}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
