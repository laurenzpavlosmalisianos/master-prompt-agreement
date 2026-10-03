#!/usr/bin/env python3

"""Closed Git query policy for caller-selected repositories."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import threading
from typing import Protocol

import bounded_subprocess
import resource_cleanup
import safe_paths


_CONTROL_FILE_MAX_BYTES = 64 * 1024
_CONFIG_FILE_MAX_BYTES = 4 * 1024 * 1024
_INDEX_FILE_MAX_BYTES = 64 * 1024 * 1024
_GIT_EXECUTABLE_MAX_BYTES = 128 * 1024 * 1024
_GIT_NAMESPACE_MAX_ENTRIES = 250_000
_GIT_NAMESPACE_MAX_PATH_BYTES = 64 * 1024 * 1024
_GIT_NAMESPACE_MAX_DEPTH = 64
_GIT_REFERENCE_MAX_FILE_BYTES = 64 * 1024
_GIT_REFERENCE_MAX_TOTAL_BYTES = 16 * 1024 * 1024
_GIT_VERSION_TIMEOUT_SECONDS = 5.0
_GIT_VERSION_MAX_OUTPUT_BYTES = 4 * 1024
_GIT_VERSION_TERMINATION_GRACE_SECONDS = 0.1
_MINIMUM_SAFE_GIT_VERSION = (2, 45, 0)
_MINIMUM_SAFE_GIT_VERSION_TEXT = "2.45.0"
_UTF8_BOM = b"\xef\xbb\xbf"
_UNBOUND_INCLUDE_SECTION_RE = re.compile(
    rb"(?im)^[ \t\v\f\r]*\[[ \t\v\f\r]*include(?:if)?"
    rb"(?=[ \t\v\f\r.\]\"])",
)
_CONFIG_SECTION_RE = re.compile(
    rb"^[ \t\v\f\r]*\[[ \t\v\f\r]*"
    rb"(?P<section>[A-Za-z0-9][A-Za-z0-9.-]*)"
)
_CONFIG_VARIABLE_RE = re.compile(
    rb"^[ \t\v\f\r]*(?P<variable>[A-Za-z][A-Za-z0-9-]*)"
    rb"(?=[ \t\v\f\r]*(?:=|$))"
)
_GIT_VERSION_RE = re.compile(
    rb"git version ([0-9]{1,4})\.([0-9]{1,4})\.([0-9]{1,4})"
    rb"(?: \([ -~]{1,96}\))?\n?"
)
_BOUNDED_GIT_VERSION_RUNNER = bounded_subprocess.run_bounded_process
_GIT_VERSION_CACHE_LOCK = threading.Lock()
_GIT_VERSION_CACHE: tuple[
    tuple[tuple[int, ...], str],
    tuple[int, int, int],
] | None = None


class _Closable(Protocol):
    def close(self) -> None: ...


def _object_identity(metadata: os.stat_result) -> tuple[int, ...]:
    """Return the stable filesystem identity of one bound object."""

    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_nlink,
        metadata.st_uid,
        metadata.st_gid,
    )


def _physical_absolute_path(path: Path) -> Path:
    """Normalize one absolute path without resolving repository-owned links."""

    lexical = Path(os.path.abspath(os.fspath(path.expanduser())))
    for alias, target in safe_paths.ALLOWED_SYSTEM_SYMLINK_TARGETS.items():
        try:
            relative = lexical.relative_to(alias)
        except ValueError:
            continue
        if safe_paths.is_allowed_system_symlink(alias):
            return target / relative
    return lexical


@dataclass
class _RegularFileBinding:
    descriptor: int
    parent: safe_paths.OutputDirectoryBinding
    name: str
    path: Path
    metadata_signature: tuple[int, ...]
    sha256: str
    _closed: bool = False

    def _read(self, *, description: str, max_bytes: int) -> bytes:
        if self._closed:
            raise RuntimeError(f"{description} binding is closed")
        before = os.fstat(self.descriptor)
        if before.st_size > max_bytes:
            raise RuntimeError(
                f"{description} exceeds the {max_bytes}-byte input limit: {self.path}"
            )
        os.lseek(self.descriptor, 0, os.SEEK_SET)
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining:
            chunk = os.read(self.descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(self.descriptor)
        if len(raw) > max_bytes:
            raise RuntimeError(
                f"{description} exceeds the {max_bytes}-byte input limit: {self.path}"
            )
        if (
            safe_paths.stable_file_metadata(before)
            != safe_paths.stable_file_metadata(after)
            or len(raw) != after.st_size
        ):
            raise RuntimeError(f"{description} changed while it was read: {self.path}")
        return raw

    def require_identity_current(self, *, description: str) -> None:
        if self._closed:
            raise RuntimeError(f"{description} binding is closed")
        self.parent.require_lexical_binding(description=f"{description} parent")
        try:
            named = os.stat(
                self.name,
                dir_fd=self.parent.descriptor,
                follow_symlinks=False,
            )
        except OSError as exc:
            raise RuntimeError(
                f"{description} pathname changed after it was bound: {self.path}"
            ) from exc
        current = os.fstat(self.descriptor)
        if (
            not stat.S_ISREG(named.st_mode)
            or _object_identity(named) != _object_identity(current)
            or safe_paths.stable_file_metadata(current) != self.metadata_signature
        ):
            raise RuntimeError(
                f"{description} pathname no longer identifies its bound file: {self.path}"
            )

    def require_current(self, *, description: str, max_bytes: int) -> None:
        self.require_identity_current(description=description)
        raw = self._read(description=description, max_bytes=max_bytes)
        if hashlib.sha256(raw).hexdigest() != self.sha256:
            raise RuntimeError(f"{description} content changed after it was bound: {self.path}")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        os.close(self.descriptor)


@dataclass(frozen=True)
class _AbsentFileBinding:
    parent: safe_paths.OutputDirectoryBinding
    name: str
    path: Path

    def require_current(self, *, description: str) -> None:
        self.parent.require_lexical_binding(description=f"{description} parent")
        try:
            os.stat(
                self.name,
                dir_fd=self.parent.descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            return
        except OSError as exc:
            raise RuntimeError(
                f"{description} absence could not be revalidated: {self.path}"
            ) from exc
        raise RuntimeError(f"{description} appeared after repository binding: {self.path}")


@dataclass(frozen=True)
class _NamespaceEntry:
    relative_path: str
    kind: str
    metadata_signature: tuple[int, ...]
    sha256: str | None


@dataclass
class _DirectoryNamespaceBinding:
    """Bound root plus a bounded generation snapshot of one Git namespace.

    Object payloads are intentionally not presented as immutable snapshots.
    Their inode, ownership, size, link count, mtime, and ctime are rebound after
    every query. Reference payloads are small enough to hash as well. This is a
    fail-closed cooperative-concurrency boundary; it is not a claim that a
    hostile same-UID writer cannot perform an undetectable transient ABA.
    """

    binding: safe_paths.OutputDirectoryBinding
    parent: safe_paths.OutputDirectoryBinding
    name: str
    description: str
    profile: str
    identity: tuple[int, ...]
    snapshot: tuple[_NamespaceEntry, ...]
    _closed: bool = False

    @property
    def descriptor(self) -> int:
        if self._closed:
            raise RuntimeError(f"{self.description} binding is closed")
        return self.binding.descriptor

    def child_path(self) -> str:
        return _descriptor_directory_path(self.descriptor)

    def require_current(self) -> None:
        if self._closed:
            raise RuntimeError(f"{self.description} binding is closed")
        self.parent.require_lexical_binding(
            description=f"{self.description} parent"
        )
        try:
            named = os.stat(
                self.name,
                dir_fd=self.parent.descriptor,
                follow_symlinks=False,
            )
        except OSError as exc:
            raise RuntimeError(
                f"{self.description} pathname changed after it was bound"
            ) from exc
        current = os.fstat(self.descriptor)
        if (
            not stat.S_ISDIR(named.st_mode)
            or _object_identity(named) != self.identity
            or _object_identity(current) != self.identity
        ):
            raise RuntimeError(
                f"{self.description} pathname no longer identifies its bound directory"
            )
        self.binding.require_lexical_binding(description=self.description)
        observed = _scan_git_namespace(
            self.descriptor,
            description=self.description,
            profile=self.profile,
        )
        if observed != self.snapshot:
            raise RuntimeError(f"{self.description} generation changed during Git query")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.binding.close()


@dataclass
class _GitExecutableBinding:
    file: _RegularFileBinding
    parent: safe_paths.OutputDirectoryBinding
    version: tuple[int, int, int]
    _closed: bool = False

    @property
    def descriptor(self) -> int:
        if self._closed:
            raise RuntimeError("Git executable binding is closed")
        return self.file.descriptor

    def child_path(self) -> str:
        return _descriptor_regular_file_path(self.descriptor)

    def require_current(self) -> None:
        if self._closed:
            raise RuntimeError("Git executable binding is closed")
        self.file.require_identity_current(description="system Git executable")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        primary: BaseException | None = None
        try:
            self.file.close()
        except BaseException as exc:
            primary = exc
        try:
            self.parent.close()
        except BaseException as exc:
            if primary is None:
                primary = exc
            else:
                primary.add_note(f"Git executable parent cleanup failure: {exc}")
        if primary is not None:
            raise primary


def _open_regular_file(
    parent: safe_paths.OutputDirectoryBinding,
    name: str,
    *,
    description: str,
    max_bytes: int,
    require_single_link: bool,
) -> tuple[_RegularFileBinding, bytes]:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    if not getattr(os, "O_NOFOLLOW", 0) or not getattr(os, "O_NONBLOCK", 0):
        raise RuntimeError(
            "descriptor-safe Git metadata binding requires O_NOFOLLOW and O_NONBLOCK"
        )
    path = parent.bound_path / name
    descriptor: int | None = None
    try:
        parent.require_lexical_binding(description=f"{description} parent")
        named = os.stat(name, dir_fd=parent.descriptor, follow_symlinks=False)
        if not stat.S_ISREG(named.st_mode):
            raise RuntimeError(f"{description} must be a regular file without links: {path}")
        if require_single_link and named.st_nlink != 1:
            raise RuntimeError(f"{description} must have exactly one hard link: {path}")
        descriptor = os.open(name, flags, dir_fd=parent.descriptor)
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or _object_identity(opened) != _object_identity(named)
        ):
            raise RuntimeError(f"{description} changed while it was opened: {path}")
        provisional = _RegularFileBinding(
            descriptor=descriptor,
            parent=parent,
            name=name,
            path=path,
            metadata_signature=safe_paths.stable_file_metadata(opened),
            sha256="",
        )
        raw = provisional._read(description=description, max_bytes=max_bytes)
        binding = _RegularFileBinding(
            descriptor=descriptor,
            parent=parent,
            name=name,
            path=path,
            metadata_signature=safe_paths.stable_file_metadata(opened),
            sha256=hashlib.sha256(raw).hexdigest(),
        )
        binding.require_current(description=description, max_bytes=max_bytes)
        descriptor = None
        return binding, raw
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise RuntimeError(f"{description} could not be bound safely: {path}: {exc}") from exc
    finally:
        if descriptor is not None:
            provisional_descriptor = descriptor
            resource_cleanup.cleanup_actions(
                ((
                    f"{description} provisional file descriptor",
                    lambda: os.close(provisional_descriptor),
                ),),
                primary=sys.exception(),
            )


def _open_optional_file(
    parent: safe_paths.OutputDirectoryBinding,
    name: str,
    *,
    description: str,
    max_bytes: int,
    require_single_link: bool = False,
) -> _RegularFileBinding | _AbsentFileBinding:
    try:
        binding, _raw = _open_regular_file(
            parent,
            name,
            description=description,
            max_bytes=max_bytes,
            require_single_link=require_single_link,
        )
    except FileNotFoundError:
        return _AbsentFileBinding(
            parent=parent,
            name=name,
            path=parent.bound_path / name,
        )
    return binding


def _scan_git_namespace(
    root_descriptor: int,
    *,
    description: str,
    profile: str,
) -> tuple[_NamespaceEntry, ...]:
    """Return one bounded no-follow namespace generation snapshot."""

    if profile not in {"objects", "references"}:
        raise ValueError(f"unsupported Git namespace profile: {profile}")
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    file_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    if (
        not getattr(os, "O_DIRECTORY", 0)
        or not getattr(os, "O_NOFOLLOW", 0)
        or not getattr(os, "O_NONBLOCK", 0)
    ):
        raise RuntimeError(
            "descriptor-safe Git namespace binding requires O_DIRECTORY, "
            "O_NOFOLLOW, and O_NONBLOCK"
        )

    entries: list[_NamespaceEntry] = []
    entry_count = 0
    path_bytes = 0
    reference_bytes = 0
    root_device = os.fstat(root_descriptor).st_dev

    def account_path(relative_path: str) -> None:
        nonlocal entry_count, path_bytes
        entry_count += 1
        path_bytes += len(os.fsencode(relative_path))
        if entry_count > _GIT_NAMESPACE_MAX_ENTRIES:
            raise RuntimeError(
                f"{description} exceeds the {_GIT_NAMESPACE_MAX_ENTRIES}-entry limit"
            )
        if path_bytes > _GIT_NAMESPACE_MAX_PATH_BYTES:
            raise RuntimeError(
                f"{description} paths exceed the "
                f"{_GIT_NAMESPACE_MAX_PATH_BYTES}-byte aggregate limit"
            )

    def reject_redirect_surface(relative_path: str) -> None:
        folded = relative_path.casefold()
        if profile == "objects":
            if folded in {"info/alternates", "info/http-alternates"}:
                raise RuntimeError(
                    f"{description} must not use an alternate object-store redirect: "
                    f"{relative_path}"
                )
            if folded.endswith(".promisor"):
                raise RuntimeError(
                    f"{description} must not contain partial-clone promisor state: "
                    f"{relative_path}"
                )
        else:
            first_component = folded.partition("/")[0]
            if first_component in {"replace", "namespaces"}:
                raise RuntimeError(
                    f"{description} must not contain replace or namespace redirects: "
                    f"{relative_path}"
                )

    def scan_directory(descriptor: int, prefix: str, depth: int) -> None:
        nonlocal reference_bytes
        before = os.fstat(descriptor)
        if not stat.S_ISDIR(before.st_mode):
            raise RuntimeError(f"{description} contains a non-directory traversal root")
        if before.st_dev != root_device:
            raise RuntimeError(f"{description} crosses a filesystem mount boundary")
        relative_root = prefix or "."
        account_path(relative_root)
        entries.append(
            _NamespaceEntry(
                relative_path=relative_root,
                kind="directory",
                metadata_signature=safe_paths.stable_file_metadata(before),
                sha256=None,
            )
        )
        with os.scandir(descriptor) as iterator:
            for entry in iterator:
                relative_path = f"{prefix}/{entry.name}" if prefix else entry.name
                child_depth = depth + 1
                if child_depth > _GIT_NAMESPACE_MAX_DEPTH:
                    raise RuntimeError(
                        f"{description} exceeds the "
                        f"{_GIT_NAMESPACE_MAX_DEPTH}-component depth limit"
                    )
                reject_redirect_surface(relative_path)
                try:
                    named = entry.stat(follow_symlinks=False)
                except OSError as exc:
                    raise RuntimeError(
                        f"{description} entry changed during inspection: {relative_path}"
                    ) from exc
                if stat.S_ISLNK(named.st_mode):
                    raise RuntimeError(
                        f"{description} must not contain symbolic links: {relative_path}"
                    )
                if named.st_dev != root_device:
                    raise RuntimeError(
                        f"{description} crosses a filesystem boundary: {relative_path}"
                    )
                if stat.S_ISDIR(named.st_mode):
                    child_descriptor: int | None = None
                    try:
                        child_descriptor = os.open(
                            entry.name,
                            directory_flags,
                            dir_fd=descriptor,
                        )
                        opened = os.fstat(child_descriptor)
                        if (
                            not stat.S_ISDIR(opened.st_mode)
                            or _object_identity(opened) != _object_identity(named)
                        ):
                            raise RuntimeError(
                                f"{description} directory changed while it was opened: "
                                f"{relative_path}"
                            )
                        scan_directory(child_descriptor, relative_path, child_depth)
                    except OSError as exc:
                        raise RuntimeError(
                            f"{description} directory could not be bound safely: "
                            f"{relative_path}: {exc}"
                        ) from exc
                    finally:
                        if child_descriptor is not None:
                            os.close(child_descriptor)
                    continue
                if not stat.S_ISREG(named.st_mode):
                    raise RuntimeError(
                        f"{description} must contain only regular files and directories: "
                        f"{relative_path}"
                    )
                account_path(relative_path)
                if named.st_nlink != 1:
                    raise RuntimeError(
                        f"{description} file must have exactly one hard link: "
                        f"{relative_path}"
                    )
                file_descriptor: int | None = None
                try:
                    file_descriptor = os.open(
                        entry.name,
                        file_flags,
                        dir_fd=descriptor,
                    )
                    opened = os.fstat(file_descriptor)
                    if (
                        not stat.S_ISREG(opened.st_mode)
                        or _object_identity(opened) != _object_identity(named)
                    ):
                        raise RuntimeError(
                            f"{description} file changed while it was opened: "
                            f"{relative_path}"
                        )
                    digest: str | None = None
                    if profile == "references":
                        if opened.st_size > _GIT_REFERENCE_MAX_FILE_BYTES:
                            raise RuntimeError(
                                f"{description} reference exceeds the "
                                f"{_GIT_REFERENCE_MAX_FILE_BYTES}-byte limit: "
                                f"{relative_path}"
                            )
                        reference_bytes += opened.st_size
                        if reference_bytes > _GIT_REFERENCE_MAX_TOTAL_BYTES:
                            raise RuntimeError(
                                f"{description} reference payloads exceed the "
                                f"{_GIT_REFERENCE_MAX_TOTAL_BYTES}-byte aggregate limit"
                            )
                        chunks: list[bytes] = []
                        remaining = _GIT_REFERENCE_MAX_FILE_BYTES + 1
                        while remaining:
                            chunk = os.read(
                                file_descriptor,
                                min(64 * 1024, remaining),
                            )
                            if not chunk:
                                break
                            chunks.append(chunk)
                            remaining -= len(chunk)
                        raw = b"".join(chunks)
                        after = os.fstat(file_descriptor)
                        if (
                            len(raw) > _GIT_REFERENCE_MAX_FILE_BYTES
                            or len(raw) != after.st_size
                            or safe_paths.stable_file_metadata(opened)
                            != safe_paths.stable_file_metadata(after)
                        ):
                            raise RuntimeError(
                                f"{description} reference changed while it was read: "
                                f"{relative_path}"
                            )
                        digest = hashlib.sha256(raw).hexdigest()
                    entries.append(
                        _NamespaceEntry(
                            relative_path=relative_path,
                            kind="file",
                            metadata_signature=safe_paths.stable_file_metadata(opened),
                            sha256=digest,
                        )
                    )
                except OSError as exc:
                    raise RuntimeError(
                        f"{description} file could not be bound safely: "
                        f"{relative_path}: {exc}"
                    ) from exc
                finally:
                    if file_descriptor is not None:
                        os.close(file_descriptor)
        after = os.fstat(descriptor)
        if safe_paths.stable_file_metadata(before) != safe_paths.stable_file_metadata(
            after
        ):
            raise RuntimeError(f"{description} changed while it was inspected")

    scan_directory(root_descriptor, "", 0)
    return tuple(sorted(entries, key=lambda entry: entry.relative_path))


def _open_directory_namespace(
    parent: safe_paths.OutputDirectoryBinding,
    name: str,
    *,
    description: str,
    profile: str,
) -> _DirectoryNamespaceBinding:
    path = parent.bound_path / name
    parent.require_lexical_binding(description=f"{description} parent")
    try:
        named = os.stat(name, dir_fd=parent.descriptor, follow_symlinks=False)
    except FileNotFoundError as exc:
        raise RuntimeError(f"{description} is missing: {path}") from exc
    if not stat.S_ISDIR(named.st_mode):
        raise RuntimeError(f"{description} must be a directory without links: {path}")
    binding = safe_paths.open_output_directory(path, create_missing=False)
    try:
        opened = os.fstat(binding.descriptor)
        if _object_identity(opened) != _object_identity(named):
            raise RuntimeError(f"{description} changed while it was opened: {path}")
        result = _DirectoryNamespaceBinding(
            binding=binding,
            parent=parent,
            name=name,
            description=description,
            profile=profile,
            identity=_object_identity(opened),
            snapshot=_scan_git_namespace(
                binding.descriptor,
                description=description,
                profile=profile,
            ),
        )
        result.require_current()
        return result
    except BaseException as primary:
        try:
            binding.close()
        except BaseException as cleanup:
            primary.add_note(f"{description} cleanup failure: {cleanup}")
        raise


def _open_optional_directory_namespace(
    parent: safe_paths.OutputDirectoryBinding,
    name: str,
    *,
    description: str,
    profile: str,
) -> _DirectoryNamespaceBinding | _AbsentFileBinding:
    try:
        os.stat(name, dir_fd=parent.descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return _AbsentFileBinding(
            parent=parent,
            name=name,
            path=parent.bound_path / name,
        )
    return _open_directory_namespace(
        parent,
        name,
        description=description,
        profile=profile,
    )


def _require_absent_entry(
    parent: safe_paths.OutputDirectoryBinding,
    name: str,
    *,
    description: str,
) -> _AbsentFileBinding:
    binding = _AbsentFileBinding(
        parent=parent,
        name=name,
        path=parent.bound_path / name,
    )
    try:
        binding.require_current(description=description)
    except RuntimeError as exc:
        raise RuntimeError(
            f"{description} is unsupported by closed Git queries: {binding.path}"
        ) from exc
    return binding


def _reject_unbound_config_includes(raw: bytes, *, description: str) -> None:
    """Reject config that can load bytes outside the retained bindings.

    System and global configuration are disabled for every child. Repository
    configuration remains necessary for Git's own repository-format metadata,
    but an include/includeIf section would let that configuration import an
    unbound file after this module has verified the repository. Rejecting the
    section is both smaller and stronger than trying to reproduce Git's
    conditional-include evaluator.
    """

    if b"\0" in raw:
        raise RuntimeError(f"{description} contains NUL")
    if _UTF8_BOM in raw:
        raise RuntimeError(
            f"{description} must not contain a UTF-8 BOM because it can obscure "
            "configuration section classification"
        )
    if _UNBOUND_INCLUDE_SECTION_RE.search(raw):
        raise RuntimeError(
            f"{description} must not use include/includeIf sections because "
            "included configuration is not descriptor-bound"
        )


def _reject_unbound_configuration_surfaces(
    raw: bytes,
    *,
    description: str,
) -> None:
    """Reject repository configuration that can select a foreign namespace."""

    current_section: bytes | None = None
    continued_value = False
    for line_number, raw_line in enumerate(raw.split(b"\n"), start=1):
        line = raw_line.rstrip(b"\r")
        if continued_value:
            trailing_backslashes = len(line) - len(line.rstrip(b"\\"))
            continued_value = trailing_backslashes % 2 == 1
            continue
        stripped = line.lstrip(b" \t\v\f\r")
        if not stripped or stripped.startswith((b"#", b";")):
            continue
        if stripped.startswith(b"["):
            section_match = _CONFIG_SECTION_RE.match(line)
            if section_match is None or b"]" not in line[section_match.end() :]:
                raise RuntimeError(
                    f"{description} has an unclassifiable section on line {line_number}"
                )
            current_section = section_match.group("section").split(b".", 1)[0].lower()
            continue
        variable_match = _CONFIG_VARIABLE_RE.match(line)
        if current_section is None or variable_match is None:
            raise RuntimeError(
                f"{description} has an unclassifiable entry on line {line_number}"
            )
        variable = variable_match.group("variable").lower()
        if (
            (current_section == b"extensions" and variable in {b"partialclone", b"refstorage"})
            or (
                current_section == b"remote"
                and variable in {b"promisor", b"partialclonefilter"}
            )
            or (
                current_section == b"core"
                and variable in {b"alternaterefscommand", b"alternaterefsprefixes"}
            )
        ):
            raise RuntimeError(
                f"{description} selects an unsupported object/reference redirect "
                f"on line {line_number}"
            )
        trailing_backslashes = len(line) - len(line.rstrip(b"\\"))
        continued_value = trailing_backslashes % 2 == 1


def _require_safe_configuration(
    binding: _RegularFileBinding | _AbsentFileBinding,
    *,
    description: str,
) -> None:
    if isinstance(binding, _RegularFileBinding):
        raw = binding._read(
            description=description,
            max_bytes=_CONFIG_FILE_MAX_BYTES,
        )
        _reject_unbound_configuration_surfaces(raw, description=description)
        _reject_unbound_config_includes(raw, description=description)


def _open_required_file(
    parent: safe_paths.OutputDirectoryBinding,
    name: str,
    *,
    description: str,
    max_bytes: int,
    require_single_link: bool,
) -> tuple[_RegularFileBinding, bytes]:
    try:
        return _open_regular_file(
            parent,
            name,
            description=description,
            max_bytes=max_bytes,
            require_single_link=require_single_link,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"{description} is missing: {parent.bound_path / name}"
        ) from exc


def _control_path(
    raw: bytes,
    *,
    prefix: bytes,
    base: Path,
    description: str,
) -> Path:
    if b"\0" in raw:
        raise RuntimeError(f"{description} contains NUL")
    line = raw[:-1] if raw.endswith(b"\n") else raw
    if line.endswith(b"\r"):
        line = line[:-1]
    if b"\n" in line or b"\r" in line or not line.startswith(prefix):
        raise RuntimeError(f"{description} has invalid syntax")
    value = line[len(prefix) :]
    if not value:
        raise RuntimeError(f"{description} has an empty path")
    try:
        decoded = value.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError(f"{description} path is not valid UTF-8: {exc}") from exc
    if safe_paths.PATH_CONTROL_RE.search(decoded):
        raise RuntimeError(f"{description} path contains control characters")
    candidate = Path(decoded)
    if not candidate.is_absolute():
        candidate = base / candidate
    return _physical_absolute_path(candidate)


def _directory_identity(binding: safe_paths.OutputDirectoryBinding) -> tuple[int, ...]:
    return _object_identity(os.fstat(binding.descriptor))


def _descriptor_directory_path(descriptor: int) -> str:
    expected = _object_identity(os.fstat(descriptor))
    for base in (Path("/proc/self/fd"), Path("/dev/fd")):
        candidate = base / str(descriptor)
        try:
            observed = os.stat(candidate)
            traversed = os.stat(f"{candidate}/.")
        except OSError:
            continue
        if (
            stat.S_ISDIR(observed.st_mode)
            and stat.S_ISDIR(traversed.st_mode)
            and _object_identity(observed) == expected
            and _object_identity(traversed) == expected
        ):
            return str(candidate)
    raise RuntimeError(
        "bound Git queries require a descriptor path that preserves directory identity"
    )


def _descriptor_regular_file_path(descriptor: int) -> str:
    expected = _object_identity(os.fstat(descriptor))
    for base in (Path("/proc/self/fd"), Path("/dev/fd")):
        candidate = base / str(descriptor)
        try:
            observed = os.stat(candidate)
        except OSError:
            continue
        if (
            stat.S_ISREG(observed.st_mode)
            and observed.st_mode & stat.S_IXUSR
            and _object_identity(observed) == expected
        ):
            return str(candidate)
    raise RuntimeError(
        "bound Git queries require a descriptor path that preserves executable identity"
    )


def _git_version_environment() -> dict[str, str]:
    """Return a repository-independent environment for the version probe."""

    return {
        "GIT_ATTR_NOSYSTEM": "1",
        "GIT_CONFIG_COUNT": "0",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_DISCOVERY_ACROSS_FILESYSTEM": "0",
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_PAGER": "",
        "GIT_TERMINAL_PROMPT": "0",
        "LC_ALL": "C",
        "PATH": os.defpath,
    }


def _probe_bound_git_version(
    executable: _RegularFileBinding,
) -> tuple[int, int, int]:
    """Probe only the retained executable, without repository discovery."""

    executable.require_identity_current(description="system Git executable")
    command_path = _descriptor_regular_file_path(executable.descriptor)
    try:
        result = _BOUNDED_GIT_VERSION_RUNNER(
            [command_path, "--version"],
            cwd=Path("/"),
            env=_git_version_environment(),
            pass_fds=(executable.descriptor,),
            timeout_seconds=_GIT_VERSION_TIMEOUT_SECONDS,
            max_output_bytes=_GIT_VERSION_MAX_OUTPUT_BYTES,
            maximum_timeout_seconds=_GIT_VERSION_TIMEOUT_SECONDS,
            maximum_output_bytes=_GIT_VERSION_MAX_OUTPUT_BYTES,
            termination_grace_seconds=_GIT_VERSION_TERMINATION_GRACE_SECONDS,
        )
    except (
        bounded_subprocess.BoundedSubprocessPreconditionError,
        bounded_subprocess.BoundedSubprocessCleanupError,
    ):
        raise
    except bounded_subprocess.BoundedSubprocessError as exc:
        raise RuntimeError(f"system Git version probe failed: {exc}") from exc
    executable.require_identity_current(description="system Git executable")
    if result.timed_out:
        raise RuntimeError(
            "system Git version probe timed out after "
            f"{_GIT_VERSION_TIMEOUT_SECONDS:g}s"
        )
    if result.output_exceeded:
        raise RuntimeError(
            "system Git version probe output exceeded the "
            f"{_GIT_VERSION_MAX_OUTPUT_BYTES}-byte limit"
        )
    if result.returncode != 0 or result.stderr:
        raise RuntimeError(
            "system Git version probe failed without one clean version result"
        )
    match = _GIT_VERSION_RE.fullmatch(result.stdout)
    if match is None:
        raise RuntimeError(
            "system Git version probe returned an unrecognized version line"
        )
    version = (
        int(match.group(1)),
        int(match.group(2)),
        int(match.group(3)),
    )
    if version < _MINIMUM_SAFE_GIT_VERSION:
        raise RuntimeError(
            f"system Git {_MINIMUM_SAFE_GIT_VERSION_TEXT} or newer is required "
            "for non-executing fsmonitor disablement and --no-lazy-fetch"
        )
    return version


def _bound_git_version(executable: _RegularFileBinding) -> tuple[int, int, int]:
    """Return a version cached only against the retained binary generation."""

    global _GIT_VERSION_CACHE
    executable.require_identity_current(description="system Git executable")
    key = (executable.metadata_signature, executable.sha256)
    with _GIT_VERSION_CACHE_LOCK:
        cached = _GIT_VERSION_CACHE
    if cached is not None and cached[0] == key:
        return cached[1]
    version = _probe_bound_git_version(executable)
    executable.require_identity_current(description="system Git executable")
    with _GIT_VERSION_CACHE_LOCK:
        _GIT_VERSION_CACHE = (key, version)
    return version


def _bind_system_git_executable() -> _GitExecutableBinding:
    path = Path(default_path_git_executable())
    parent = safe_paths.open_output_directory(path.parent, create_missing=False)
    executable: _RegularFileBinding | None = None
    try:
        for descriptor in parent.descriptors:
            directory_metadata = os.fstat(descriptor)
            if directory_metadata.st_uid != 0 or directory_metadata.st_mode & 0o022:
                raise RuntimeError(
                    "platform-default Git path must traverse only root-owned, "
                    "non-group/world-writable directories"
                )
        executable, _raw = _open_required_file(
            parent,
            path.name,
            description="system Git executable",
            max_bytes=_GIT_EXECUTABLE_MAX_BYTES,
            require_single_link=False,
        )
        metadata = os.fstat(executable.descriptor)
        if metadata.st_uid != 0 or metadata.st_mode & 0o022:
            raise RuntimeError(
                "platform-default Git must be root-owned and not group/world writable"
            )
        if not metadata.st_mode & stat.S_IXUSR:
            raise RuntimeError("platform-default Git is not owner-executable")
        binding = _GitExecutableBinding(
            file=executable,
            parent=parent,
            version=_bound_git_version(executable),
        )
        binding.require_current()
        executable = None
        return binding
    except BaseException as primary:
        if executable is not None:
            try:
                executable.close()
            except BaseException as cleanup:
                primary.add_note(f"Git executable cleanup failure: {cleanup}")
        try:
            parent.close()
        except BaseException as cleanup:
            primary.add_note(f"Git executable parent cleanup failure: {cleanup}")
        raise


@dataclass(frozen=True)
class GitQueryCapability:
    """Optional query capability observed without retaining execution authority."""

    available: bool
    minimum_version: str
    path: str | None
    version: str | None
    reason: str | None
    cleanup_failed: bool = False


class _GitCapabilityCleanupError(RuntimeError):
    """A retained capability binding could not be closed reliably."""


def _cleanup_failure_reason(error: BaseException) -> str | None:
    """Find typed teardown failures or owner-added cleanup aggregation notes."""

    pending = [error]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(
            current,
            (bounded_subprocess.BoundedSubprocessCleanupError, _GitCapabilityCleanupError),
        ):
            return str(current)
        for note in getattr(current, "__notes__", ()):
            if "cleanup failure" in note or "cleanup failed for" in note:
                return note
        if current.__cause__ is not None:
            pending.append(current.__cause__)
        if current.__context__ is not None:
            pending.append(current.__context__)
    return None


def git_query_capability() -> GitQueryCapability:
    """Observe the trusted executable boundary and close every retained binding.

    This repository-independent snapshot does not authorize a later query:
    query execution must still bind and validate its own executable/repository.
    """

    try:
        binding = _bind_system_git_executable()
        try:
            binding.require_current()
            path = str(binding.file.path)
            version = ".".join(str(part) for part in binding.version)
        finally:
            try:
                binding.close()
            except Exception as cleanup:
                raise _GitCapabilityCleanupError(
                    f"system Git capability binding cleanup failed: {cleanup}"
                ) from cleanup
    except (OSError, RuntimeError) as exc:
        cleanup_reason = _cleanup_failure_reason(exc)
        return GitQueryCapability(
            available=False,
            minimum_version=_MINIMUM_SAFE_GIT_VERSION_TEXT,
            path=None,
            version=None,
            reason=(cleanup_reason if cleanup_reason is not None else str(exc))[:1024],
            cleanup_failed=cleanup_reason is not None,
        )
    return GitQueryCapability(
        available=True,
        minimum_version=_MINIMUM_SAFE_GIT_VERSION_TEXT,
        path=path,
        version=version,
        reason=None,
    )


@dataclass
class GitRepositoryBinding:
    """Retained no-follow binding for one selected repository generation."""

    root: Path
    root_binding: safe_paths.OutputDirectoryBinding
    metadata_kind: str
    metadata_file: _RegularFileBinding | None
    admin_path: Path
    admin_binding: safe_paths.OutputDirectoryBinding
    admin_identity: tuple[int, ...]
    common_path: Path
    common_binding: safe_paths.OutputDirectoryBinding | None
    common_identity: tuple[int, ...]
    control_files: tuple[tuple[str, _RegularFileBinding], ...]
    configuration_files: tuple[
        tuple[str, _RegularFileBinding | _AbsentFileBinding], ...
    ]
    generation_files: tuple[
        tuple[str, _RegularFileBinding | _AbsentFileBinding], ...
    ] = ()
    generation_directories: tuple[
        tuple[str, safe_paths.OutputDirectoryBinding], ...
    ] = ()
    generation_absences: tuple[tuple[str, _AbsentFileBinding], ...] = ()
    object_namespace: _DirectoryNamespaceBinding | None = None
    reference_namespaces: tuple[
        tuple[str, _DirectoryNamespaceBinding | _AbsentFileBinding], ...
    ] = ()
    executable: _GitExecutableBinding | None = None
    _closed: bool = False

    @property
    def admin_descriptor(self) -> int:
        if self._closed:
            raise RuntimeError("Git repository binding is closed")
        return self.admin_binding.descriptor

    @property
    def common_descriptor(self) -> int:
        if self._closed:
            raise RuntimeError("Git repository binding is closed")
        if self.common_binding is None:
            return self.admin_binding.descriptor
        return self.common_binding.descriptor

    @property
    def worktree_descriptor(self) -> int:
        if self._closed:
            raise RuntimeError("Git repository binding is closed")
        return self.root_binding.descriptor

    @property
    def pass_fds(self) -> tuple[int, ...]:
        if self.executable is None:
            raise RuntimeError("Git executable is not bound")
        if self.object_namespace is None:
            raise RuntimeError("Git object namespace is not bound")
        return tuple(
            dict.fromkeys(
                (
                    self.worktree_descriptor,
                    self.admin_descriptor,
                    self.common_descriptor,
                    self.object_namespace.descriptor,
                    self.executable.descriptor,
                )
            )
        )

    def child_worktree(self) -> str:
        return _descriptor_directory_path(self.worktree_descriptor)

    def child_git_dir(self) -> str:
        return _descriptor_directory_path(self.admin_descriptor)

    def child_common_dir(self) -> str:
        return _descriptor_directory_path(self.common_descriptor)

    def child_git_executable(self) -> str:
        if self.executable is None:
            raise RuntimeError("Git executable is not bound")
        return self.executable.child_path()

    def child_object_directory(self) -> str:
        if self.object_namespace is None:
            raise RuntimeError("Git object namespace is not bound")
        return self.object_namespace.child_path()

    def require_current(self) -> None:
        if self._closed:
            raise RuntimeError("Git repository binding is closed")
        if self.executable is not None:
            self.executable.require_current()
        self.root_binding.require_lexical_binding(description="Git worktree root")
        self.admin_binding.require_lexical_binding(
            description="Git administrative directory"
        )
        if _directory_identity(self.admin_binding) != self.admin_identity:
            raise RuntimeError("Git administrative directory identity changed")
        if self.common_binding is not None:
            self.common_binding.require_lexical_binding(
                description="Git common directory"
            )
            if _directory_identity(self.common_binding) != self.common_identity:
                raise RuntimeError("Git common directory identity changed")
        elif self.common_identity != self.admin_identity:
            raise RuntimeError("normal Git repository common-directory identity changed")
        if self.metadata_file is not None:
            self.metadata_file.require_current(
                description="Git metadata file",
                max_bytes=_CONTROL_FILE_MAX_BYTES,
            )
        for description, binding in self.control_files:
            binding.require_current(
                description=description,
                max_bytes=_CONTROL_FILE_MAX_BYTES,
            )
        for description, binding in self.configuration_files:
            if isinstance(binding, _RegularFileBinding):
                binding.require_current(
                    description=description,
                    max_bytes=_CONFIG_FILE_MAX_BYTES,
                )
            else:
                binding.require_current(description=description)
        for description, binding in self.generation_files:
            if isinstance(binding, _RegularFileBinding):
                binding.require_current(
                    description=description,
                    max_bytes=(
                        _INDEX_FILE_MAX_BYTES
                        if description == "Git index"
                        else (
                            _CONTROL_FILE_MAX_BYTES
                            if description == "Git HEAD control"
                            else _CONFIG_FILE_MAX_BYTES
                        )
                    ),
                )
            else:
                binding.require_current(description=description)
        for description, binding in self.generation_directories:
            binding.require_lexical_binding(description=description)
            binding.require_unchanged_chain(description=description)
        for description, binding in self.generation_absences:
            binding.require_current(description=description)
        if self.object_namespace is not None:
            self.object_namespace.require_current()
        for description, binding in self.reference_namespaces:
            if isinstance(binding, _DirectoryNamespaceBinding):
                binding.require_current()
            else:
                binding.require_current(description=description)
        self.root_binding.require_unchanged_chain(description="Git worktree root")
        self.admin_binding.require_unchanged_chain(
            description="Git administrative directory"
        )
        if self.common_binding is not None:
            self.common_binding.require_unchanged_chain(
                description="Git common directory"
            )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        resources: list[tuple[str, _Closable]] = []
        if self.executable is not None:
            resources.append(("system Git executable", self.executable))
        if self.metadata_file is not None:
            resources.append(("Git metadata file", self.metadata_file))
        resources.extend(
            (description, binding)
            for description, binding in self.generation_files
            if isinstance(binding, _RegularFileBinding)
        )
        resources.extend(self.generation_directories)
        if self.object_namespace is not None:
            resources.append(("Git object namespace", self.object_namespace))
        resources.extend(
            (description, binding)
            for description, binding in self.reference_namespaces
            if isinstance(binding, _DirectoryNamespaceBinding)
        )
        resources.extend(self.control_files)
        resources.extend(
            (description, binding)
            for description, binding in self.configuration_files
            if isinstance(binding, _RegularFileBinding)
        )
        resources.append(("Git administrative directory", self.admin_binding))
        if self.common_binding is not None:
            resources.append(("Git common directory", self.common_binding))
        resources.append(("Git worktree root", self.root_binding))
        primary: BaseException | None = None
        for description, resource in resources:
            try:
                resource.close()
            except BaseException as exc:
                if primary is None:
                    primary = exc
                else:
                    primary.add_note(f"{description} cleanup failure: {exc}")
        if primary is not None:
            raise primary

    def __enter__(self) -> "GitRepositoryBinding":
        try:
            self.require_current()
        except BaseException as primary:
            try:
                self.close()
            except BaseException as cleanup:
                primary.add_note(f"Git repository binding cleanup failure: {cleanup}")
            raise
        return self

    def __exit__(
        self,
        _exception_type: object,
        exception: BaseException | None,
        _traceback: object,
    ) -> None:
        verification: BaseException | None = None
        try:
            self.require_current()
        except BaseException as exc:
            verification = exc
            if exception is not None:
                exception.add_note(f"Git repository revalidation also failed: {exc}")
        try:
            self.close()
        except BaseException as cleanup:
            if verification is not None:
                if exception is None:
                    verification.add_note(
                        f"Git repository binding cleanup failure: {cleanup}"
                    )
                else:
                    exception.add_note(
                        f"Git repository binding cleanup failure: {cleanup}"
                    )
            elif exception is None:
                raise
            else:
                exception.add_note(f"Git repository binding cleanup failure: {cleanup}")
        if verification is not None and exception is None:
            raise verification


def _bind_normal_repository(
    root: Path,
    root_binding: safe_paths.OutputDirectoryBinding,
    metadata: os.stat_result,
) -> GitRepositoryBinding:
    admin = safe_paths.open_output_directory(root / ".git", create_missing=False)
    config: _RegularFileBinding | None = None
    config_worktree: _RegularFileBinding | _AbsentFileBinding | None = None
    try:
        if _object_identity(os.fstat(admin.descriptor)) != _object_identity(metadata):
            raise RuntimeError("Git metadata directory changed while it was bound")
        try:
            os.stat("commondir", dir_fd=admin.descriptor, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise RuntimeError(
                "a directory-form .git must not redirect its common directory"
            )
        config, raw_config = _open_required_file(
            admin,
            "config",
            description="Git common configuration",
            max_bytes=_CONFIG_FILE_MAX_BYTES,
            require_single_link=False,
        )
        _reject_unbound_config_includes(
            raw_config,
            description="Git common configuration",
        )
        _reject_unbound_configuration_surfaces(
            raw_config,
            description="Git common configuration",
        )
        config_worktree = _open_optional_file(
            admin,
            "config.worktree",
            description="Git worktree configuration",
            max_bytes=_CONFIG_FILE_MAX_BYTES,
        )
        _require_safe_configuration(
            config_worktree,
            description="Git worktree configuration",
        )
        identity = _directory_identity(admin)
        result = GitRepositoryBinding(
            root=root,
            root_binding=root_binding,
            metadata_kind="directory",
            metadata_file=None,
            admin_path=admin.bound_path,
            admin_binding=admin,
            admin_identity=identity,
            common_path=admin.bound_path,
            common_binding=None,
            common_identity=identity,
            control_files=(),
            configuration_files=(
                ("Git common configuration", config),
                ("Git worktree configuration", config_worktree),
            ),
        )
        result.require_current()
        return result
    except BaseException as primary:
        for description, binding in (
            ("Git worktree configuration", config_worktree),
            ("Git common configuration", config),
        ):
            if not isinstance(binding, _RegularFileBinding):
                continue
            try:
                binding.close()
            except BaseException as cleanup:
                primary.add_note(f"{description} cleanup failure: {cleanup}")
        try:
            admin.close()
        except BaseException as cleanup:
            primary.add_note(f"Git administrative directory cleanup failure: {cleanup}")
        raise


def _bind_linked_worktree(
    root: Path,
    root_binding: safe_paths.OutputDirectoryBinding,
    metadata: os.stat_result,
) -> GitRepositoryBinding:
    metadata_file: _RegularFileBinding | None = None
    admin: safe_paths.OutputDirectoryBinding | None = None
    common: safe_paths.OutputDirectoryBinding | None = None
    control_files: list[tuple[str, _RegularFileBinding]] = []
    configuration_files: list[
        tuple[str, _RegularFileBinding | _AbsentFileBinding]
    ] = []
    try:
        metadata_file, raw_gitfile = _open_required_file(
            root_binding,
            ".git",
            description="Git metadata file",
            max_bytes=_CONTROL_FILE_MAX_BYTES,
            require_single_link=True,
        )
        if _object_identity(os.fstat(metadata_file.descriptor)) != _object_identity(
            metadata
        ):
            raise RuntimeError("Git metadata file changed while it was bound")
        admin_path = _control_path(
            raw_gitfile,
            prefix=b"gitdir: ",
            base=root,
            description="Git metadata file",
        )
        admin = safe_paths.open_output_directory(admin_path, create_missing=False)
        commondir, raw_commondir = _open_required_file(
            admin,
            "commondir",
            description="linked-worktree Git common-directory control",
            max_bytes=_CONTROL_FILE_MAX_BYTES,
            require_single_link=True,
        )
        control_files.append(
            ("linked-worktree Git common-directory control", commondir)
        )
        common_path = _control_path(
            raw_commondir,
            prefix=b"",
            base=admin.bound_path,
            description="linked-worktree Git common-directory control",
        )
        common = safe_paths.open_output_directory(common_path, create_missing=False)
        if (
            admin.bound_path.parent.name != "worktrees"
            or admin.bound_path.parent.parent != common.bound_path
        ):
            raise RuntimeError(
                "Git metadata file does not identify a registered linked-worktree "
                "administrative directory"
            )
        backlink, raw_backlink = _open_required_file(
            admin,
            "gitdir",
            description="linked-worktree Git backlink",
            max_bytes=_CONTROL_FILE_MAX_BYTES,
            require_single_link=True,
        )
        control_files.append(("linked-worktree Git backlink", backlink))
        backlink_path = _control_path(
            raw_backlink,
            prefix=b"",
            base=admin.bound_path,
            description="linked-worktree Git backlink",
        )
        if backlink_path != root / ".git":
            raise RuntimeError(
                "linked-worktree Git backlink does not exactly identify the selected .git file"
            )
        common_config, raw_common_config = _open_required_file(
            common,
            "config",
            description="Git common configuration",
            max_bytes=_CONFIG_FILE_MAX_BYTES,
            require_single_link=False,
        )
        configuration_files.append(("Git common configuration", common_config))
        _reject_unbound_config_includes(
            raw_common_config,
            description="Git common configuration",
        )
        _reject_unbound_configuration_surfaces(
            raw_common_config,
            description="Git common configuration",
        )
        worktree_config = _open_optional_file(
            admin,
            "config.worktree",
            description="Git worktree configuration",
            max_bytes=_CONFIG_FILE_MAX_BYTES,
        )
        configuration_files.append(("Git worktree configuration", worktree_config))
        _require_safe_configuration(
            worktree_config,
            description="Git worktree configuration",
        )
        result = GitRepositoryBinding(
            root=root,
            root_binding=root_binding,
            metadata_kind="linked-worktree",
            metadata_file=metadata_file,
            admin_path=admin.bound_path,
            admin_binding=admin,
            admin_identity=_directory_identity(admin),
            common_path=common.bound_path,
            common_binding=common,
            common_identity=_directory_identity(common),
            control_files=tuple(control_files),
            configuration_files=tuple(configuration_files),
        )
        result.require_current()
        return result
    except BaseException as primary:
        for _description, binding in reversed(configuration_files):
            if isinstance(binding, _RegularFileBinding):
                try:
                    binding.close()
                except BaseException as cleanup:
                    primary.add_note(f"Git configuration cleanup failure: {cleanup}")
        for _description, binding in reversed(control_files):
            try:
                binding.close()
            except BaseException as cleanup:
                primary.add_note(f"Git control-file cleanup failure: {cleanup}")
        if metadata_file is not None:
            try:
                metadata_file.close()
            except BaseException as cleanup:
                primary.add_note(f"Git metadata-file cleanup failure: {cleanup}")
        for description, binding in (
            ("Git administrative directory", admin),
            ("Git common directory", common),
        ):
            if binding is None:
                continue
            try:
                binding.close()
            except BaseException as cleanup:
                primary.add_note(f"{description} cleanup failure: {cleanup}")
        raise


def _bind_repository_generation(repository: GitRepositoryBinding) -> None:
    """Retain the mutable files that can change one evidence query generation."""

    files: list[tuple[str, _RegularFileBinding | _AbsentFileBinding]] = []
    directories: list[tuple[str, safe_paths.OutputDirectoryBinding]] = []
    absences: list[tuple[str, _AbsentFileBinding]] = []
    object_namespace: _DirectoryNamespaceBinding | None = None
    reference_namespaces: list[
        tuple[str, _DirectoryNamespaceBinding | _AbsentFileBinding]
    ] = []
    try:
        files.append(
            (
                "Git index",
                _open_optional_file(
                    repository.admin_binding,
                    "index",
                    description="Git index",
                    max_bytes=_INDEX_FILE_MAX_BYTES,
                ),
            )
        )
        head, _raw_head = _open_required_file(
            repository.admin_binding,
            "HEAD",
            description="Git HEAD control",
            max_bytes=_CONTROL_FILE_MAX_BYTES,
            require_single_link=True,
        )
        files.append(("Git HEAD control", head))
        files.append(
            (
                "Git packed references",
                _open_optional_file(
                    repository.common_binding or repository.admin_binding,
                    "packed-refs",
                    description="Git packed references",
                    max_bytes=_CONFIG_FILE_MAX_BYTES,
                    require_single_link=True,
                ),
            )
        )

        common = repository.common_binding or repository.admin_binding
        object_namespace = _open_directory_namespace(
            common,
            "objects",
            description="Git object namespace",
            profile="objects",
        )
        common_references = _open_optional_directory_namespace(
            common,
            "refs",
            description="Git common reference namespace",
            profile="references",
        )
        reference_namespaces.append(
            ("Git common reference namespace", common_references)
        )
        if repository.admin_binding.descriptor != common.descriptor:
            worktree_references = _open_optional_directory_namespace(
                repository.admin_binding,
                "refs",
                description="Git worktree reference namespace",
                profile="references",
            )
            reference_namespaces.append(
                ("Git worktree reference namespace", worktree_references)
            )
        absence_parents = [(common, "common")]
        if repository.admin_binding.descriptor != common.descriptor:
            absence_parents.append((repository.admin_binding, "worktree"))
        for parent, qualifier in absence_parents:
            for name, label in (
                ("shallow", "shallow-boundary file"),
                ("reftable", "reftable reference store"),
                ("tables.list", "reftable table list"),
            ):
                absences.append(
                    (
                        f"Git {qualifier} {label}",
                        _require_absent_entry(
                            parent,
                            name,
                            description=f"Git {qualifier} {label}",
                        ),
                    )
                )
        try:
            named_info = os.stat(
                "info",
                dir_fd=common.descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            absences.append(
                (
                    "Git information directory",
                    _AbsentFileBinding(
                        parent=common,
                        name="info",
                        path=common.bound_path / "info",
                    ),
                )
            )
        else:
            if not stat.S_ISDIR(named_info.st_mode):
                raise RuntimeError(
                    "Git information path must be a directory without links"
                )
            info = safe_paths.open_output_directory(
                common.bound_path / "info",
                create_missing=False,
            )
            directories.append(("Git information directory", info))
            if _object_identity(os.fstat(info.descriptor)) != _object_identity(
                named_info
            ):
                raise RuntimeError(
                    "Git information directory changed while it was bound"
                )
            absences.append(
                (
                    "Git grafts file",
                    _require_absent_entry(
                        info,
                        "grafts",
                        description="Git grafts file",
                    ),
                )
            )
            files.append(
                (
                    "Git repository excludes",
                    _open_optional_file(
                        info,
                        "exclude",
                        description="Git repository excludes",
                        max_bytes=_CONFIG_FILE_MAX_BYTES,
                    ),
                )
            )
        repository.generation_files = tuple(files)
        repository.generation_directories = tuple(directories)
        repository.generation_absences = tuple(absences)
        repository.object_namespace = object_namespace
        repository.reference_namespaces = tuple(reference_namespaces)
        repository.require_current()
    except BaseException as primary:
        for _description, binding in reversed(files):
            if not isinstance(binding, _RegularFileBinding):
                continue
            try:
                binding.close()
            except BaseException as cleanup:
                primary.add_note(f"Git generation-file cleanup failure: {cleanup}")
        for _description, binding in reversed(directories):
            try:
                binding.close()
            except BaseException as cleanup:
                primary.add_note(f"Git generation-directory cleanup failure: {cleanup}")
        for _description, binding in reversed(reference_namespaces):
            if not isinstance(binding, _DirectoryNamespaceBinding):
                continue
            try:
                binding.close()
            except BaseException as cleanup:
                primary.add_note(f"Git reference-namespace cleanup failure: {cleanup}")
        if object_namespace is not None:
            try:
                object_namespace.close()
            except BaseException as cleanup:
                primary.add_note(f"Git object-namespace cleanup failure: {cleanup}")
        repository.generation_files = ()
        repository.generation_directories = ()
        repository.generation_absences = ()
        repository.object_namespace = None
        repository.reference_namespaces = ()
        raise


def bind_git_repository(repo_root: Path) -> GitRepositoryBinding:
    """Bind a normal repository or a reciprocally registered linked worktree."""

    try:
        root = repo_root.resolve(strict=True)
    except OSError as exc:
        raise RuntimeError(f"Git worktree root cannot be resolved: {repo_root}: {exc}") from exc
    if not root.is_dir():
        raise RuntimeError(f"Git worktree root must be a directory: {repo_root}")
    root = _physical_absolute_path(root)
    root_binding = safe_paths.open_output_directory(root, create_missing=False)
    repository: GitRepositoryBinding
    try:
        root_binding.require_lexical_binding(description="Git worktree root")
        try:
            metadata = os.stat(
                ".git",
                dir_fd=root_binding.descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"selected worktree has no direct .git metadata entry: {root}"
            ) from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise RuntimeError("selected .git metadata entry must not be a symbolic link")
        if stat.S_ISDIR(metadata.st_mode):
            repository = _bind_normal_repository(root, root_binding, metadata)
        elif stat.S_ISREG(metadata.st_mode):
            repository = _bind_linked_worktree(root, root_binding, metadata)
        else:
            raise RuntimeError(
                "selected .git metadata entry must be a regular file or directory"
            )
    except BaseException as primary:
        try:
            root_binding.close()
        except BaseException as cleanup:
            primary.add_note(f"Git worktree-root cleanup failure: {cleanup}")
        raise
    try:
        _bind_repository_generation(repository)
        repository.executable = _bind_system_git_executable()
        repository.require_current()
        return repository
    except BaseException as primary:
        try:
            repository.close()
        except BaseException as cleanup:
            primary.add_note(f"Git repository cleanup failure: {cleanup}")
        raise


def default_path_git_executable() -> str:
    """Resolve Git without consulting the caller's ambient PATH."""

    candidate = shutil.which("git", path=os.defpath)
    if candidate is None:
        raise RuntimeError(
            "Git executable was not found on the platform default executable path"
        )
    candidate_path = Path(candidate)
    if not candidate_path.is_absolute():
        raise RuntimeError(
            "platform default executable path returned a non-absolute Git executable"
        )
    try:
        resolved = candidate_path.resolve(strict=True)
    except OSError as exc:
        raise RuntimeError(f"Git executable cannot be resolved: {candidate}: {exc}") from exc
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        raise RuntimeError(f"Git executable is not a regular executable file: {resolved}")
    return str(resolved)


def closed_git_query_environment(
    repository: GitRepositoryBinding,
) -> dict[str, str]:
    """Return a minimal environment bound to one classified repository."""

    repository.require_current()
    worktree = repository.child_worktree()
    git_dir = repository.child_git_dir()
    common_dir = repository.child_common_dir()
    object_directory = repository.child_object_directory()
    return {
        "GIT_ATTR_NOSYSTEM": "1",
        "GIT_COMMON_DIR": common_dir,
        "GIT_CONFIG_COUNT": "0",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_DISCOVERY_ACROSS_FILESYSTEM": "0",
        "GIT_DIR": git_dir,
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_OBJECT_DIRECTORY": object_directory,
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_PAGER": "",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_WORK_TREE": worktree,
        "LC_ALL": "C",
        "PATH": os.defpath,
    }


def _validate_ls_files_shape(selected: list[str]) -> None:
    if "--" not in selected:
        raise ValueError("Git ls-files query must terminate options with --")
    delimiter = selected.index("--")
    options = selected[1:delimiter]
    operands = selected[delimiter + 1 :]
    allowed = {
        "-z",
        "--cached",
        "--others",
        "--exclude-standard",
        "--error-unmatch",
        "--stage",
    }
    if any(option not in allowed for option in options) or len(options) != len(set(options)):
        raise ValueError("Git ls-files query uses an unmaintained option shape")
    if "--stage" in options:
        if set(options) != {"--stage", "-z"} or operands:
            raise ValueError("Git ls-files stage query must use the maintained exact form")
        return
    if "--error-unmatch" in options:
        if options != ["--error-unmatch"] or len(operands) != 1:
            raise ValueError(
                "Git ls-files error-unmatch query must use the maintained exact form"
            )
        return
    if "-z" not in options:
        raise ValueError("Git ls-files inventory query must request NUL framing")
    if "--exclude-standard" in options and "--others" not in options:
        raise ValueError("Git ls-files exclude-standard query must request other files")


def closed_git_query_command(
    arguments: Sequence[str],
    *,
    executable: str | None = None,
) -> list[str]:
    """Return a closed argv for one maintained read-only Git query shape."""

    selected = list(arguments)
    if not selected:
        raise ValueError("Git query arguments must not be empty")
    subcommand = selected[0]
    if subcommand == "diff":
        if (
            len(selected) != 8
            or selected[1:6]
            != [
                "--cached",
                "--no-ext-diff",
                "--no-textconv",
                "--name-only",
                "-z",
            ]
            or not selected[6]
            or selected[6].startswith("-")
            or any(ord(character) < 32 or ord(character) == 127 for character in selected[6])
            or selected[7] != "--"
        ):
            raise ValueError(
                "Git diff query must compare one revision to the index, disable "
                "external diff and text conversion, and request NUL-delimited names"
            )
    elif subcommand == "ls-files":
        _validate_ls_files_shape(selected)
    elif subcommand == "cat-file":
        if (
            len(selected) != 3
            or selected[1] not in {"-s", "blob"}
            or not selected[2]
            or selected[2].startswith("-")
            or any(
                ord(character) < 32 or ord(character) == 127
                for character in selected[2]
            )
        ):
            raise ValueError("Git cat-file query must request one blob or blob size")
    elif subcommand == "check-ignore":
        if selected[1:4] != ["--no-index", "-q", "--"] or len(selected) != 5:
            raise ValueError("Git check-ignore query must use the maintained exact form")
    elif subcommand == "rev-parse":
        if (
            len(selected) != 4
            or selected[1:3] != ["--verify", "--end-of-options"]
            or not selected[3]
            or selected[3].startswith("-")
            or any(
                ord(character) < 32 or ord(character) == 127
                for character in selected[3]
            )
        ):
            raise ValueError(
                "Git revision query must verify one option-delimited revision"
            )
    else:
        raise ValueError(f"unsupported Git metadata query: {subcommand}")

    if executable is None:
        qualified_executable = default_path_git_executable()
    else:
        candidate = Path(executable)
        if not candidate.is_absolute():
            raise ValueError("explicit Git executable must be an absolute path")
        try:
            metadata = os.stat(candidate)
        except OSError as exc:
            raise ValueError(
                f"explicit Git executable cannot be inspected: {candidate}: {exc}"
            ) from exc
        if not stat.S_ISREG(metadata.st_mode) or not metadata.st_mode & stat.S_IXUSR:
            raise ValueError(
                f"explicit Git executable is not a regular owner-executable file: {candidate}"
            )
        qualified_executable = str(candidate)

    return [
        qualified_executable,
        "--no-lazy-fetch",
        "--no-optional-locks",
        "-c",
        "core.attributesFile=/dev/null",
        "-c",
        "core.commitGraph=false",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "core.multiPackIndex=false",
        "-c",
        "core.excludesFile=/dev/null",
        "-c",
        "credential.helper=",
        "-c",
        "http.emptyAuth=false",
        "-c",
        "protocol.allow=never",
        *selected,
    ]
