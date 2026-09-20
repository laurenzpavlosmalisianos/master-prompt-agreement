#!/usr/bin/env python3

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import os
from pathlib import Path
import stat

import safe_paths


DEFAULT_MAX_REGISTRY_FILES = 512
MAX_REGISTRY_FILES = 100_000
DEFAULT_MAX_REGISTRY_BYTES = 32 * 1024 * 1024
MAX_REGISTRY_BYTES = 1024 * 1024 * 1024
DEFAULT_MAX_REGISTRY_ENTRIES = 4_096
MAX_REGISTRY_ENTRIES = 1_000_000


class RegistryLimitError(ValueError):
    """A structured, fail-closed registry inventory limit failure."""

    def __init__(self, code: str, label: str, limit: int, observed: int) -> None:
        self.code = code
        self.limit = limit
        self.observed = observed
        super().__init__(
            f"{label} limit exceeded (limit={limit}, observed_at_least={observed})"
        )


@dataclass(frozen=True)
class RegistryFileLimits:
    """Typed aggregate bounds shared by every registry inventory API."""

    max_files: int = DEFAULT_MAX_REGISTRY_FILES
    max_aggregate_bytes: int = DEFAULT_MAX_REGISTRY_BYTES
    max_visited_entries: int = DEFAULT_MAX_REGISTRY_ENTRIES

    def __post_init__(self) -> None:
        _validate_limit(
            self.max_files,
            label="max_files",
            maximum=MAX_REGISTRY_FILES,
        )
        _validate_limit(
            self.max_aggregate_bytes,
            label="max_aggregate_bytes",
            maximum=MAX_REGISTRY_BYTES,
        )
        _validate_limit(
            self.max_visited_entries,
            label="max_visited_entries",
            maximum=MAX_REGISTRY_ENTRIES,
        )


def _validate_limit(value: int, *, label: str, maximum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{label} must be an integer")
    if not 1 <= value <= maximum:
        raise ValueError(f"{label} must be between 1 and {maximum}")


DEFAULT_REGISTRY_FILE_LIMITS = RegistryFileLimits()
ProgressCheck = Callable[[], None]


def _check_progress(progress_check: ProgressCheck | None) -> None:
    if progress_check is not None:
        progress_check()


class _SnapshotBudget:
    def __init__(self, limits: RegistryFileLimits) -> None:
        if not isinstance(limits, RegistryFileLimits):
            raise TypeError("limits must be a RegistryFileLimits instance")
        self.limits = limits
        self.paths: set[Path] = set()
        self.aggregate_bytes = 0
        self.visited_entries = 0

    def reserve_visit(self) -> None:
        observed = self.visited_entries + 1
        if observed > self.limits.max_visited_entries:
            raise RegistryLimitError(
                "source_registry_entry_limit_exceeded",
                "source registry inventory entry count",
                self.limits.max_visited_entries,
                observed,
            )
        self.visited_entries = observed

    def contains(self, path: Path) -> bool:
        return path in self.paths

    def reserve_path(self, path: Path) -> bool:
        if path in self.paths:
            return False
        observed = len(self.paths) + 1
        if observed > self.limits.max_files:
            raise RegistryLimitError(
                "source_registry_file_limit_exceeded",
                "source registry file count",
                self.limits.max_files,
                observed,
            )
        self.paths.add(path)
        return True

    def reserve_bytes(self, byte_count: int) -> None:
        observed = self.aggregate_bytes + byte_count
        if observed > self.limits.max_aggregate_bytes:
            raise RegistryLimitError(
                "source_registry_byte_limit_exceeded",
                "source registry aggregate bytes",
                self.limits.max_aggregate_bytes,
                observed,
            )
        self.aggregate_bytes = observed


@dataclass(frozen=True)
class MarkdownSnapshot:
    """One immutable, bounded UTF-8 registry-file snapshot."""

    path: Path
    text: str


def normalize_reference_dirs(reference_dirs: Path | tuple[Path, ...] | list[Path]) -> tuple[Path, ...]:
    if isinstance(reference_dirs, Path):
        return (reference_dirs,)
    return tuple(reference_dirs)


def _relative_label(root: Path, path: Path, *, description: str) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError(f"{description} must stay under repository root: {path}") from exc


def _required_open_flag(name: str) -> int:
    value = getattr(os, name, None)
    if not isinstance(value, int) or value == 0:
        raise ValueError(
            f"descriptor-bound source registry traversal requires os.{name}"
        )
    return value


def _registry_node_identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        stat.S_IFMT(metadata.st_mode),
        metadata.st_uid,
        metadata.st_gid,
    )


def _scan_bound_directory(
    descriptor: int,
    logical_path: Path,
    *,
    budget: _SnapshotBudget,
    progress_check: ProgressCheck | None,
    charge_budget: bool,
) -> dict[str, os.stat_result]:
    """Capture one bounded no-follow directory generation through its fd."""

    captured: dict[str, os.stat_result] = {}
    observed = 0
    with os.scandir(descriptor) as entries:
        for entry in entries:
            _check_progress(progress_check)
            observed += 1
            if charge_budget:
                budget.reserve_visit()
            elif observed > budget.limits.max_visited_entries:
                raise RegistryLimitError(
                    "source_registry_entry_limit_exceeded",
                    "source registry inventory entry count",
                    budget.limits.max_visited_entries,
                    observed,
                )
            if entry.name in captured:
                raise ValueError(
                    f"reference directory returned a duplicate entry: "
                    f"{logical_path / entry.name}"
                )
            captured[entry.name] = entry.stat(follow_symlinks=False)
    return captured


def _read_bound_markdown_snapshot(
    parent_descriptor: int,
    name: str,
    path: Path,
    observed: os.stat_result,
    *,
    budget: _SnapshotBudget,
    progress_check: ProgressCheck | None,
    description: str = "reference file",
) -> MarkdownSnapshot:
    """Read one discovered Markdown file without reopening a pathname chain."""

    nofollow = _required_open_flag("O_NOFOLLOW")
    nonblock = _required_open_flag("O_NONBLOCK")
    flags = os.O_RDONLY | nofollow | nonblock | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(name, flags, dir_fd=parent_descriptor)
    except OSError as exc:
        raise ValueError(
            f"{description} could not be opened without following links: {path}"
        ) from exc
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(observed.st_mode)
            or not stat.S_ISREG(opened.st_mode)
            or observed.st_nlink != 1
            or opened.st_nlink != 1
            or safe_paths.stable_file_metadata(observed)
            != safe_paths.stable_file_metadata(opened)
        ):
            raise ValueError(f"{description} changed before it was opened: {path}")
        if opened.st_size > safe_paths.DEFAULT_JSON_INPUT_MAX_BYTES:
            raise ValueError(
                f"{description} exceeds the bounded byte input limit of "
                f"{safe_paths.DEFAULT_JSON_INPUT_MAX_BYTES}: {path}"
            )
        if not budget.reserve_path(path):
            raise AssertionError("duplicate registry path reached a bound file read")
        budget.reserve_bytes(opened.st_size)
        remaining = opened.st_size
        chunks: list[bytes] = []
        while remaining:
            _check_progress(progress_check)
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        final = os.fstat(descriptor)
        try:
            named_final = os.stat(
                name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except OSError as exc:
            raise ValueError(
                f"{description} pathname changed while it was read: {path}"
            ) from exc
        if (
            len(raw) != final.st_size
            or safe_paths.stable_file_metadata(opened)
            != safe_paths.stable_file_metadata(final)
            or safe_paths.stable_file_metadata(final)
            != safe_paths.stable_file_metadata(named_final)
        ):
            raise ValueError(f"{description} changed while it was read: {path}")
    finally:
        os.close(descriptor)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{description} must be valid UTF-8: {path}: {exc}") from exc
    return MarkdownSnapshot(path=path, text=text)


@dataclass
class _BoundDirectoryFrame:
    descriptor: int
    logical_path: Path
    initial_metadata: os.stat_result
    initial_entries: dict[str, os.stat_result]
    ordered_names: tuple[str, ...]
    parent_descriptor: int | None
    entry_name: str | None
    depth: int = 0
    next_index: int = 0
    owns_descriptor: bool = True


def _bound_reference_directory_snapshots(
    directory: Path,
    *,
    budget: _SnapshotBudget,
    progress_check: ProgressCheck | None,
    description: str = "reference directory",
    include_readme: bool = False,
    reject_symlinks: bool = False,
    max_depth: int | None = None,
) -> list[MarkdownSnapshot]:
    """Snapshot one stable Markdown tree without following queued pathnames."""

    if max_depth is not None and (
        isinstance(max_depth, bool) or not isinstance(max_depth, int) or max_depth < 0
    ):
        raise ValueError("max_depth must be a non-negative integer or None")

    directory_flags = (
        os.O_RDONLY
        | _required_open_flag("O_DIRECTORY")
        | _required_open_flag("O_NOFOLLOW")
        | getattr(os, "O_CLOEXEC", 0)
    )
    snapshots: list[MarkdownSnapshot] = []
    retained_frames: list[_BoundDirectoryFrame] = []
    with safe_paths.open_output_directory(
        directory,
        create_missing=False,
    ) as root_binding:
        root_metadata = os.fstat(root_binding.descriptor)
        root_entries = _scan_bound_directory(
            root_binding.descriptor,
            directory,
            budget=budget,
            progress_check=progress_check,
            charge_budget=True,
        )
        stack = [
            _BoundDirectoryFrame(
                descriptor=root_binding.descriptor,
                logical_path=directory,
                initial_metadata=root_metadata,
                initial_entries=root_entries,
                ordered_names=tuple(sorted(root_entries)),
                parent_descriptor=None,
                entry_name=None,
                depth=0,
                owns_descriptor=False,
            )
        ]
        try:
            while stack:
                frame = stack[-1]
                if frame.next_index < len(frame.ordered_names):
                    name = frame.ordered_names[frame.next_index]
                    frame.next_index += 1
                    observed = frame.initial_entries[name]
                    candidate = frame.logical_path / name
                    try:
                        current = os.stat(
                            name,
                            dir_fd=frame.descriptor,
                            follow_symlinks=False,
                        )
                    except OSError as exc:
                        raise ValueError(
                            f"{description} entry changed before use: {candidate}"
                        ) from exc
                    if safe_paths.stable_file_metadata(current) != (
                        safe_paths.stable_file_metadata(observed)
                    ):
                        raise ValueError(
                            f"{description} entry changed before use: {candidate}"
                        )
                    if stat.S_ISLNK(observed.st_mode):
                        if reject_symlinks or name.endswith(".md"):
                            raise ValueError(
                                f"{description} must not contain symlinks: {candidate}"
                            )
                        continue
                    if stat.S_ISDIR(observed.st_mode):
                        if max_depth is not None and frame.depth >= max_depth:
                            raise ValueError(
                                f"{description} exceeds the {max_depth}-level depth limit"
                            )
                        try:
                            child_descriptor = os.open(
                                name,
                                directory_flags,
                                dir_fd=frame.descriptor,
                            )
                        except OSError as exc:
                            raise ValueError(
                                f"{description} changed before descent: "
                                f"{candidate}"
                            ) from exc
                        try:
                            child_metadata = os.fstat(child_descriptor)
                            if (
                                _registry_node_identity(observed)
                                != _registry_node_identity(child_metadata)
                            ):
                                raise ValueError(
                                    f"{description} changed before descent: "
                                    f"{candidate}"
                                )
                            child_entries = _scan_bound_directory(
                                child_descriptor,
                                candidate,
                                budget=budget,
                                progress_check=progress_check,
                                charge_budget=True,
                            )
                        except BaseException:
                            os.close(child_descriptor)
                            raise
                        stack.append(
                            _BoundDirectoryFrame(
                                descriptor=child_descriptor,
                                logical_path=candidate,
                                initial_metadata=child_metadata,
                                initial_entries=child_entries,
                                ordered_names=tuple(sorted(child_entries)),
                                parent_descriptor=frame.descriptor,
                                entry_name=name,
                                depth=frame.depth + 1,
                            )
                        )
                        continue
                    if (
                        name.endswith(".md")
                        and (include_readme or name != "README.md")
                        and not budget.contains(candidate)
                    ):
                        if not stat.S_ISREG(observed.st_mode):
                            raise ValueError(
                                f"{description} Markdown must be a regular file: "
                                f"{candidate}"
                            )
                        snapshots.append(
                            _read_bound_markdown_snapshot(
                                frame.descriptor,
                                name,
                                candidate,
                                observed,
                                budget=budget,
                                progress_check=progress_check,
                                description=f"{description} Markdown",
                            )
                        )
                    continue

                stack.pop()
                retained_frames.append(frame)

            # Revalidate every retained descriptor only after the complete
            # selected tree has been inventoried and read.  This closes the
            # cross-sibling gap that would exist if a completed child were
            # closed before later siblings were visited.
            for frame in retained_frames:
                final_entries = _scan_bound_directory(
                    frame.descriptor,
                    frame.logical_path,
                    budget=budget,
                    progress_check=progress_check,
                    charge_budget=False,
                )
                final_metadata = os.fstat(frame.descriptor)
                if (
                    final_entries.keys() != frame.initial_entries.keys()
                    or any(
                        safe_paths.stable_file_metadata(final_entries[name])
                        != safe_paths.stable_file_metadata(initial)
                        for name, initial in frame.initial_entries.items()
                    )
                    or safe_paths.stable_file_metadata(final_metadata)
                    != safe_paths.stable_file_metadata(frame.initial_metadata)
                ):
                    raise ValueError(
                        f"{description} changed during inventory: "
                        f"{frame.logical_path}"
                    )
                if frame.parent_descriptor is not None and frame.entry_name is not None:
                    try:
                        named_final = os.stat(
                            frame.entry_name,
                            dir_fd=frame.parent_descriptor,
                            follow_symlinks=False,
                        )
                    except OSError as exc:
                        raise ValueError(
                            f"{description} pathname changed during inventory: "
                            f"{frame.logical_path}"
                        ) from exc
                    if _registry_node_identity(named_final) != _registry_node_identity(
                        final_metadata
                    ):
                        raise ValueError(
                            f"{description} pathname changed during inventory: "
                            f"{frame.logical_path}"
                        )
            root_binding.require_unchanged_chain(
                description=description
            )
        finally:
            for frame in reversed((*retained_frames, *stack)):
                if frame.owns_descriptor:
                    os.close(frame.descriptor)
    return snapshots


def _read_optional_bound_markdown_snapshot(
    root: Path,
    relative_path: Path,
    *,
    description: str,
    budget: _SnapshotBudget,
    progress_check: ProgressCheck | None,
) -> MarkdownSnapshot | None:
    """Observe and, when present, read one optional file through one parent fd.

    A missing file is accepted only when the bound parent generation remains
    unchanged through the absence observation.  Once discovered, deletion or
    substitution is an error rather than a silent optional-file outcome.
    """

    _check_progress(progress_check)
    candidate = safe_paths.safe_relative_child(
        root,
        relative_path,
        description=description,
    )
    if budget.contains(candidate):
        return None
    try:
        parent_context = safe_paths.open_output_directory(
            candidate.parent,
            create_missing=False,
        )
    except safe_paths.OutputDirectoryBindingError as exc:
        if isinstance(exc.__cause__, FileNotFoundError):
            return None
        raise
    with parent_context as parent_binding:
        try:
            observed = os.stat(
                candidate.name,
                dir_fd=parent_binding.descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            parent_binding.require_unchanged_chain(description=description)
            return None
        snapshot = _read_bound_markdown_snapshot(
            parent_binding.descriptor,
            candidate.name,
            candidate,
            observed,
            budget=budget,
            progress_check=progress_check,
            description=description,
        )
        parent_binding.require_unchanged_chain(description=description)
        return snapshot


def read_markdown_snapshot(
    root: Path,
    path: Path,
    *,
    description: str,
    missing_ok: bool = False,
    _budget: _SnapshotBudget | None = None,
    _path_reserved: bool = False,
    progress_check: ProgressCheck | None = None,
) -> MarkdownSnapshot | None:
    """Read one registry input once through the shared descriptor-safe reader."""

    _check_progress(progress_check)
    rel = _relative_label(root, path, description=description)
    try:
        raw = safe_paths.read_regular_file_bytes(
            path,
            description=description,
        )
    except FileNotFoundError as exc:
        if missing_ok:
            return None
        raise ValueError(f"{description} disappeared during inventory: {rel}") from exc
    if _budget is not None:
        if not _path_reserved:
            _budget.reserve_path(path)
        _budget.reserve_bytes(len(raw))
    _check_progress(progress_check)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{description} must be valid UTF-8: {rel}: {exc}") from exc
    return MarkdownSnapshot(path=path, text=text)


def reference_directory_markdown_snapshots(
    root: Path,
    reference_dirs: Path | tuple[Path, ...] | list[Path],
    *,
    limits: RegistryFileLimits = DEFAULT_REGISTRY_FILE_LIMITS,
    _budget: _SnapshotBudget | None = None,
    progress_check: ProgressCheck | None = None,
) -> tuple[MarkdownSnapshot, ...]:
    budget = _SnapshotBudget(limits) if _budget is None else _budget
    snapshots: list[MarkdownSnapshot] = []
    for reference_dir in normalize_reference_dirs(reference_dirs):
        _check_progress(progress_check)
        budget.reserve_visit()
        directory = safe_paths.safe_relative_child(
            root,
            reference_dir,
            description="reference directory",
        )
        try:
            snapshots.extend(
                _bound_reference_directory_snapshots(
                    directory,
                    budget=budget,
                    progress_check=progress_check,
                )
            )
        except safe_paths.OutputDirectoryBindingError as exc:
            if isinstance(exc.__cause__, FileNotFoundError):
                continue
            raise
    return tuple(sorted(snapshots, key=lambda item: item.path))


def project_registry_markdown_snapshots(
    root: Path,
    files: tuple[Path, ...],
    *,
    limits: RegistryFileLimits = DEFAULT_REGISTRY_FILE_LIMITS,
    _budget: _SnapshotBudget | None = None,
    progress_check: ProgressCheck | None = None,
) -> tuple[MarkdownSnapshot, ...]:
    budget = _SnapshotBudget(limits) if _budget is None else _budget
    snapshots: list[MarkdownSnapshot] = []
    for rel in files:
        _check_progress(progress_check)
        budget.reserve_visit()
        snapshot = _read_optional_bound_markdown_snapshot(
            root,
            rel,
            description="project source registry file",
            budget=budget,
            progress_check=progress_check,
        )
        if snapshot is not None:
            snapshots.append(snapshot)
    return tuple(sorted(snapshots, key=lambda item: item.path))


def documentation_markdown_snapshots(
    root: Path,
    files: tuple[Path, ...],
    directories: tuple[Path, ...],
    *,
    limits: RegistryFileLimits = DEFAULT_REGISTRY_FILE_LIMITS,
    _budget: _SnapshotBudget | None = None,
    progress_check: ProgressCheck | None = None,
    max_depth: int | None = None,
) -> tuple[MarkdownSnapshot, ...]:
    """Snapshot an optional, closed documentation scope without path reopens.

    Explicit files and directory roots may be absent in a focused fixture.  A
    discovered file is nevertheless mandatory for the remainder of its bound
    read, and each discovered directory's complete entry generation is
    revalidated after all selected Markdown bytes have been captured.
    """

    budget = _SnapshotBudget(limits) if _budget is None else _budget
    snapshots: list[MarkdownSnapshot] = []
    for relative_file in files:
        _check_progress(progress_check)
        budget.reserve_visit()
        snapshot = _read_optional_bound_markdown_snapshot(
            root,
            relative_file,
            description="product documentation file",
            budget=budget,
            progress_check=progress_check,
        )
        if snapshot is not None:
            snapshots.append(snapshot)

    for relative_directory in directories:
        _check_progress(progress_check)
        budget.reserve_visit()
        directory = safe_paths.safe_relative_child(
            root,
            relative_directory,
            description="product documentation directory",
        )
        try:
            snapshots.extend(
                _bound_reference_directory_snapshots(
                    directory,
                    budget=budget,
                    progress_check=progress_check,
                    description="product documentation directory",
                    include_readme=True,
                    reject_symlinks=True,
                    max_depth=max_depth,
                )
            )
        except safe_paths.OutputDirectoryBindingError as exc:
            if isinstance(exc.__cause__, FileNotFoundError):
                continue
            raise
    return tuple(sorted(snapshots, key=lambda item: item.path))


def registry_markdown_snapshots(
    root: Path,
    reference_dirs: Path | tuple[Path, ...] | list[Path],
    project_files: tuple[Path, ...] = (),
    *,
    limits: RegistryFileLimits = DEFAULT_REGISTRY_FILE_LIMITS,
    progress_check: ProgressCheck | None = None,
    documentation_files: tuple[Path, ...] = (),
    documentation_directories: tuple[Path, ...] = (),
    documentation_max_depth: int | None = None,
    documentation_progress_check: ProgressCheck | None = None,
) -> tuple[MarkdownSnapshot, ...]:
    budget = _SnapshotBudget(limits)
    by_path = {
        snapshot.path: snapshot
        for snapshot in (
            *documentation_markdown_snapshots(
                root,
                documentation_files,
                documentation_directories,
                limits=limits,
                _budget=budget,
                progress_check=(
                    progress_check
                    if documentation_progress_check is None
                    else documentation_progress_check
                ),
                max_depth=documentation_max_depth,
            ),
            *reference_directory_markdown_snapshots(
                root,
                reference_dirs,
                limits=limits,
                _budget=budget,
                progress_check=progress_check,
            ),
            *project_registry_markdown_snapshots(
                root,
                project_files,
                limits=limits,
                _budget=budget,
                progress_check=progress_check,
            ),
        )
    }
    return tuple(by_path[path] for path in sorted(by_path))


def project_registry_markdown_files(
    root: Path,
    files: tuple[Path, ...],
    *,
    limits: RegistryFileLimits = DEFAULT_REGISTRY_FILE_LIMITS,
    progress_check: ProgressCheck | None = None,
) -> list[Path]:
    return [
        snapshot.path
        for snapshot in project_registry_markdown_snapshots(
            root,
            files,
            limits=limits,
            progress_check=progress_check,
        )
    ]


def registry_markdown_files(
    root: Path,
    reference_dirs: Path | tuple[Path, ...] | list[Path],
    project_files: tuple[Path, ...] = (),
    *,
    limits: RegistryFileLimits = DEFAULT_REGISTRY_FILE_LIMITS,
    progress_check: ProgressCheck | None = None,
) -> list[Path]:
    return [
        snapshot.path
        for snapshot in registry_markdown_snapshots(
            root,
            reference_dirs,
            project_files,
            limits=limits,
            progress_check=progress_check,
        )
    ]
