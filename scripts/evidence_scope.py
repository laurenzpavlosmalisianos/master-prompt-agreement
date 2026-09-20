#!/usr/bin/env python3

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
import re
import shlex
import stat
import sys
from pathlib import Path, PureWindowsPath
from typing import Protocol

import bounded_subprocess
import git_query
import recommend_stack
import safe_paths


SHARED_SURFACE_TERMS = (
    "auth",
    "cache",
    "user",
    "config",
    "core",
    "default",
    "flag",
    "helper",
    "middleware",
    "policy",
    "router",
    "schema",
    "setting",
    "shared",
    "util",
)
TOKEN_RE = re.compile(r"[a-z0-9]+")
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
SCOPE_ORDER = (
    "patch",
    "touched-files",
    "commit-series",
    "feature-slice",
    "trust-boundary",
    "repo-slice",
)
GIT_COMMAND_TIMEOUT_SECONDS = 10.0
GIT_COMMAND_MAX_OUTPUT_BYTES = 4 * 1024 * 1024
GIT_TERMINATION_GRACE_SECONDS = 0.1
GIT_WORKTREE_COMPARISON_MAX_BYTES = 64 * 1024 * 1024
GIT_WORKTREE_GENERATION_MAX_ENTRIES = 100_000
GIT_WORKTREE_GENERATION_MAX_PATH_BYTES = 16 * 1024 * 1024
GIT_IGNORE_GENERATION_MAX_BYTES = 4 * 1024 * 1024
GIT_WORKTREE_GENERATION_MAX_DEPTH = 128


class _GitBlobHasher(Protocol):
    def update(self, value: bytes, /) -> None: ...

    def hexdigest(self) -> str: ...


@dataclass(frozen=True)
class GitIndexEntry:
    mode: str
    oid: str
    stage: int
    path: str


def _close_index_descriptors(
    descriptors: tuple[int, ...] | list[int],
    *,
    primary: BaseException | None = None,
) -> None:
    cleanup_failure: OSError | None = None
    for descriptor in reversed(descriptors):
        try:
            os.close(descriptor)
        except OSError as exc:
            if primary is not None:
                primary.add_note(
                    f"worktree-parent descriptor cleanup also failed: {exc}"
                )
            elif cleanup_failure is None:
                cleanup_failure = exc
            else:
                cleanup_failure.add_note(
                    f"additional worktree-parent descriptor cleanup failure: {exc}"
                )
    if primary is None and cleanup_failure is not None:
        raise cleanup_failure


@dataclass
class _IndexParentBinding:
    """Retain every relative directory edge leading to one index entry."""

    components: tuple[str, ...]
    descriptors: tuple[int, ...]
    _closed: bool = False

    @property
    def descriptor(self) -> int:
        if self._closed:
            raise SystemExit("safe worktree parent binding is closed")
        return self.descriptors[-1]

    def require_current(self) -> None:
        if self._closed:
            raise SystemExit("safe worktree parent binding is closed")
        for parent, component, child in zip(
            self.descriptors[:-1],
            self.components,
            self.descriptors[1:],
            strict=True,
        ):
            try:
                named = os.stat(component, dir_fd=parent, follow_symlinks=False)
                opened = os.fstat(child)
            except OSError as exc:
                raise SystemExit(
                    "worktree parent changed during safe comparison: "
                    f"{component}: {exc}"
                ) from exc
            if (
                not stat.S_ISDIR(named.st_mode)
                or not stat.S_ISDIR(opened.st_mode)
                or _stable_identity(named) != _stable_identity(opened)
            ):
                raise SystemExit(
                    "worktree parent no longer identifies its bound directory: "
                    f"{component}"
                )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        _close_index_descriptors(self.descriptors)

    def __enter__(self) -> "_IndexParentBinding":
        try:
            self.require_current()
        except BaseException as primary:
            try:
                self.close()
            except BaseException as cleanup:
                primary.add_note(
                    f"worktree-parent descriptor cleanup also failed: {cleanup}"
                )
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
                exception.add_note(f"worktree-parent revalidation also failed: {exc}")
        try:
            self.close()
        except BaseException as cleanup:
            if exception is not None:
                exception.add_note(
                    f"worktree-parent descriptor cleanup also failed: {cleanup}"
                )
            elif verification is not None:
                verification.add_note(
                    f"worktree-parent descriptor cleanup also failed: {cleanup}"
                )
            else:
                raise
        if verification is not None and exception is None:
            raise verification


def validate_diff_base(value: str) -> None:
    if not value.strip():
        raise SystemExit("--diff-base must be non-empty")
    if value.startswith("-") or CONTROL_RE.search(value):
        raise SystemExit("--diff-base must be a revision, not an option or control string")


def validate_root(value: Path) -> Path:
    try:
        root = value.resolve(strict=True)
    except OSError as exc:
        raise SystemExit(f"--root cannot be resolved: {value}: {exc}") from exc
    if not root.is_dir():
        raise SystemExit(f"--root must be a directory: {value}")
    return root


def validate_paths(paths: list[str], root: Path) -> list[str]:
    validated: list[str] = []
    for value in paths:
        try:
            validated.append(
                safe_paths.normalize_repo_relative_path(
                    value,
                    root,
                    description="evidence path",
                )
            )
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
    return validated


def _normalize_git_evidence_path(value: str) -> tuple[str, tuple[str, ...]]:
    """Validate lexical spelling without resolving a Git-reported leaf.

    Git can legitimately report a tracked or untracked symlink as the changed
    artifact.  The explicit-path route remains stricter and rejects every
    symlink component; this route is reserved for paths returned by the closed
    Git queries below and validates their ancestors separately.
    """

    if (
        not value
        or CONTROL_RE.search(value)
        or any(marker in value for marker in ("<", ">"))
    ):
        raise SystemExit("Git evidence path must be non-empty plain path text")
    if "://" in value or safe_paths.URI_SCHEME_RE.match(value):
        raise SystemExit(
            "Git evidence path must be repo-relative, not a URI or absolute "
            f"path: {value}"
        )
    path = Path(value)
    windows_path = PureWindowsPath(value)
    if (
        "\\" in value
        or path.is_absolute()
        or windows_path.is_absolute()
        or ".." in path.parts
        or ".." in windows_path.parts
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or not path.parts
        or all(part in {"", "."} for part in path.parts)
    ):
        raise SystemExit(
            f"Git evidence path must be a safe repo-relative path: {value}"
        )
    return path.as_posix(), path.parts


def _validate_git_evidence_ancestors(
    root_descriptor: int,
    parts: tuple[str, ...],
) -> None:
    """Bind all existing ancestors without inspecting or following the leaf."""

    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    if not getattr(os, "O_DIRECTORY", 0) or not getattr(os, "O_NOFOLLOW", 0):
        raise SystemExit(
            "Git evidence path validation requires O_DIRECTORY and O_NOFOLLOW"
        )
    try:
        descriptors = [os.dup(root_descriptor)]
    except OSError as exc:
        raise SystemExit(
            f"Git evidence root descriptor could not be retained: {exc}"
        ) from exc
    opened_components: list[str] = []
    missing_edge: tuple[int, str] | None = None
    try:
        if not stat.S_ISDIR(os.fstat(descriptors[0]).st_mode):
            raise SystemExit("Git evidence root descriptor must identify a directory")
        for component in parts[:-1]:
            parent_descriptor = descriptors[-1]
            try:
                named = os.stat(
                    component,
                    dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                missing_edge = (parent_descriptor, component)
                break
            except OSError as exc:
                raise SystemExit(
                    "Git evidence path ancestor could not be inspected safely: "
                    f"{component}: {exc}"
                ) from exc
            if stat.S_ISLNK(named.st_mode):
                raise SystemExit(
                    "Git evidence path must not include symlink ancestors: "
                    + "/".join(parts)
                )
            if not stat.S_ISDIR(named.st_mode):
                raise SystemExit(
                    "Git evidence path ancestor must be a directory: "
                    + "/".join((*opened_components, component))
                )
            try:
                child_descriptor = os.open(
                    component,
                    flags,
                    dir_fd=parent_descriptor,
                )
            except OSError as exc:
                raise SystemExit(
                    "Git evidence path ancestor could not be opened safely: "
                    f"{component}: {exc}"
                ) from exc
            descriptors.append(child_descriptor)
            try:
                opened = os.fstat(child_descriptor)
            except OSError as exc:
                raise SystemExit(
                    "Git evidence path ancestor could not be bound safely: "
                    f"{component}: {exc}"
                ) from exc
            if (
                not stat.S_ISDIR(opened.st_mode)
                or _stable_identity(opened) != _stable_identity(named)
            ):
                raise SystemExit(
                    "Git evidence path ancestor changed while it was opened: "
                    + "/".join((*opened_components, component))
                )
            opened_components.append(component)

        _IndexParentBinding(
            components=tuple(opened_components),
            descriptors=tuple(descriptors),
        ).require_current()
        if missing_edge is not None:
            parent_descriptor, component = missing_edge
            try:
                os.stat(
                    component,
                    dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                pass
            except OSError as exc:
                raise SystemExit(
                    "Git evidence path missing ancestor could not be revalidated: "
                    f"{component}: {exc}"
                ) from exc
            else:
                raise SystemExit(
                    "Git evidence path ancestor appeared during validation: "
                    + "/".join((*opened_components, component))
                )
    except BaseException as primary:
        _close_index_descriptors(descriptors, primary=primary)
        raise
    else:
        _close_index_descriptors(descriptors)


def validate_git_paths(
    paths: list[str],
    root_descriptor: int,
) -> list[str]:
    """Validate paths produced by bound Git queries, permitting a symlink leaf."""

    validated: list[str] = []
    for value in paths:
        normalized, parts = _normalize_git_evidence_path(value)
        _validate_git_evidence_ancestors(root_descriptor, parts)
        validated.append(normalized)
    return validated


def _bounded_git_with_binding(
    args: list[str],
    binding: git_query.GitRepositoryBinding,
) -> tuple[int, bytes, bytes]:
    if os.name != "posix":
        raise SystemExit("Git path collection requires POSIX process-group pipes")
    try:
        binding.require_current()
        result = bounded_subprocess.run_bounded_process(
            git_query.closed_git_query_command(
                args,
                executable=binding.child_git_executable(),
            ),
            cwd=Path(binding.child_worktree()),
            env=git_query.closed_git_query_environment(binding),
            pass_fds=binding.pass_fds,
            timeout_seconds=GIT_COMMAND_TIMEOUT_SECONDS,
            max_output_bytes=GIT_COMMAND_MAX_OUTPUT_BYTES,
            maximum_timeout_seconds=GIT_COMMAND_TIMEOUT_SECONDS,
            maximum_output_bytes=GIT_COMMAND_MAX_OUTPUT_BYTES,
            termination_grace_seconds=GIT_TERMINATION_GRACE_SECONDS,
        )
        binding.require_current()
    except bounded_subprocess.BoundedSubprocessStartError as exc:
        detail = exc.__cause__ if isinstance(exc.__cause__, OSError) else exc
        raise SystemExit(f"git {' '.join(args)} could not start: {detail}") from exc
    except bounded_subprocess.BoundedSubprocessError as exc:
        raise SystemExit(f"Git path collection failed: {exc}") from exc
    except (OSError, RuntimeError, ValueError) as exc:
        raise SystemExit(f"Git repository boundary rejected query: {exc}") from exc
    if result.timed_out:
        raise SystemExit(
            f"git {' '.join(args)} timed out after {GIT_COMMAND_TIMEOUT_SECONDS:g}s"
        )
    if result.output_exceeded:
        raise SystemExit(
            "Git path collection output exceeded the "
            f"{GIT_COMMAND_MAX_OUTPUT_BYTES}-byte limit"
        )
    return result.returncode, result.stdout, result.stderr


def _bounded_git(args: list[str], root: Path) -> tuple[int, bytes, bytes]:
    try:
        with git_query.bind_git_repository(root) as binding:
            return _bounded_git_with_binding(args, binding)
    except (OSError, RuntimeError, ValueError) as exc:
        raise SystemExit(f"Git repository boundary rejected query: {exc}") from exc


def run_git(
    args: list[str],
    root: Path,
    *,
    binding: git_query.GitRepositoryBinding | None = None,
) -> list[str]:
    if binding is None:
        returncode, stdout, stderr = _bounded_git(args, root)
    else:
        returncode, stdout, stderr = _bounded_git_with_binding(args, binding)
    if returncode != 0:
        detail = stderr.decode("utf-8", errors="replace").strip()
        raise SystemExit(detail or f"git {' '.join(args)} failed")
    if stdout and not stdout.endswith(b"\0"):
        raise SystemExit("Git path collection did not return a terminal NUL delimiter")
    raw_paths = stdout[:-1].split(b"\0") if stdout else []
    if any(not value for value in raw_paths):
        raise SystemExit("Git path collection returned an empty NUL-delimited path")
    try:
        return [value.decode("utf-8") for value in raw_paths]
    except UnicodeDecodeError as exc:
        raise SystemExit(f"Git path collection returned a non-UTF-8 path: {exc}") from exc


def run_git_index(
    root: Path,
    *,
    binding: git_query.GitRepositoryBinding | None = None,
) -> list[GitIndexEntry]:
    args = ["ls-files", "--stage", "-z", "--"]
    if binding is None:
        returncode, stdout, stderr = _bounded_git(args, root)
    else:
        returncode, stdout, stderr = _bounded_git_with_binding(args, binding)
    if returncode != 0:
        detail = stderr.decode("utf-8", errors="replace").strip()
        raise SystemExit(detail or "git ls-files --stage -z -- failed")
    if stdout and not stdout.endswith(b"\0"):
        raise SystemExit("Git index inventory did not return a terminal NUL delimiter")
    entries: list[GitIndexEntry] = []
    object_id_length: int | None = None
    for record in stdout.split(b"\0"):
        if not record:
            continue
        header, separator, raw_path = record.partition(b"\t")
        fields = header.split(b" ")
        if (
            separator != b"\t"
            or not raw_path
            or len(fields) != 3
            or re.fullmatch(rb"[0-7]{6}", fields[0]) is None
            or fields[2] not in {b"0", b"1", b"2", b"3"}
            or re.fullmatch(rb"[0-9a-f]{40}|[0-9a-f]{64}", fields[1]) is None
        ):
            raise SystemExit("Git index inventory returned a malformed stage record")
        if object_id_length is None:
            object_id_length = len(fields[1])
        elif len(fields[1]) != object_id_length:
            raise SystemExit("Git index inventory mixed object-ID formats")
        try:
            path = raw_path.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SystemExit(
                f"Git index inventory returned a non-UTF-8 path: {exc}"
            ) from exc
        entries.append(
            GitIndexEntry(
                mode=fields[0].decode("ascii"),
                oid=fields[1].decode("ascii"),
                stage=int(fields[2]),
                path=path,
            )
        )
    return entries


def _index_path_parts(path: str) -> tuple[str, ...]:
    candidate = Path(path)
    if (
        not path
        or CONTROL_RE.search(path)
        or "\\" in path
        or candidate.is_absolute()
        or not candidate.parts
        or any(part in {"", ".", ".."} for part in candidate.parts)
    ):
        raise SystemExit(f"Git index inventory returned an unsafe path: {path!r}")
    return candidate.parts


def _git_blob_hasher(oid: str, size: int) -> _GitBlobHasher:
    if len(oid) == 40:
        hasher = hashlib.sha1(usedforsecurity=False)
    elif len(oid) == 64:
        hasher = hashlib.sha256()
    else:
        raise SystemExit("Git index inventory used an unsupported object-ID format")
    hasher.update(f"blob {size}\0".encode("ascii"))
    return hasher


def _stable_identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_nlink,
        metadata.st_uid,
        metadata.st_gid,
    )


def _read_ignore_generation(
    parent_descriptor: int,
    name: str,
    before: os.stat_result,
    *,
    remaining_bytes: int,
) -> tuple[bytes, int]:
    if before.st_size > remaining_bytes:
        raise SystemExit(
            "worktree ignore inputs exceeded the "
            f"{GIT_IGNORE_GENERATION_MAX_BYTES}-byte read limit"
        )
    flags = (
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    if not getattr(os, "O_NOFOLLOW", 0) or not getattr(os, "O_NONBLOCK", 0):
        raise SystemExit(
            "worktree generation binding requires O_NOFOLLOW and O_NONBLOCK"
        )
    try:
        descriptor = os.open(name, flags, dir_fd=parent_descriptor)
    except OSError as exc:
        raise SystemExit(f"worktree ignore input could not be opened safely: {exc}") from exc
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or _stable_identity(opened) != _stable_identity(before)
        ):
            raise SystemExit("worktree ignore input changed while it was opened")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(1024 * 1024, remaining_bytes - total + 1))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > remaining_bytes:
                raise SystemExit(
                    "worktree ignore inputs exceeded the "
                    f"{GIT_IGNORE_GENERATION_MAX_BYTES}-byte read limit"
                )
        after = os.fstat(descriptor)
        named_after = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
        if (
            total != after.st_size
            or safe_paths.stable_file_metadata(opened)
            != safe_paths.stable_file_metadata(after)
            or _stable_identity(named_after) != _stable_identity(after)
        ):
            raise SystemExit("worktree ignore input changed while it was read")
        return b"".join(chunks), total
    except OSError as exc:
        raise SystemExit(f"worktree ignore input could not be read safely: {exc}") from exc
    finally:
        os.close(descriptor)


def _worktree_generation_digest(root_descriptor: int) -> str:
    """Hash a bounded descriptor-relative metadata and ignore-input snapshot."""

    digest = hashlib.sha256()
    entry_count = 0
    path_bytes = 0
    ignore_bytes = 0
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    if not getattr(os, "O_DIRECTORY", 0) or not getattr(os, "O_NOFOLLOW", 0):
        raise SystemExit(
            "worktree generation binding requires O_DIRECTORY and O_NOFOLLOW"
        )

    def visit(directory_descriptor: int, prefix: bytes, depth: int) -> None:
        nonlocal entry_count, path_bytes, ignore_bytes
        if depth > GIT_WORKTREE_GENERATION_MAX_DEPTH:
            raise SystemExit(
                "worktree generation exceeded the "
                f"{GIT_WORKTREE_GENERATION_MAX_DEPTH}-directory-depth limit"
            )
        before_directory = os.fstat(directory_descriptor)
        try:
            entries: list[tuple[bytes, os.DirEntry[str]]] = []
            with os.scandir(directory_descriptor) as iterator:
                for entry in iterator:
                    name_bytes = os.fsencode(entry.name)
                    if name_bytes == b".git":
                        continue
                    relative = prefix + (b"/" if prefix else b"") + name_bytes
                    entry_count += 1
                    path_bytes += len(relative)
                    if entry_count > GIT_WORKTREE_GENERATION_MAX_ENTRIES:
                        raise SystemExit(
                            "worktree generation exceeded the "
                            f"{GIT_WORKTREE_GENERATION_MAX_ENTRIES}-entry limit"
                        )
                    if path_bytes > GIT_WORKTREE_GENERATION_MAX_PATH_BYTES:
                        raise SystemExit(
                            "worktree generation paths exceeded the "
                            f"{GIT_WORKTREE_GENERATION_MAX_PATH_BYTES}-byte limit"
                        )
                    entries.append((name_bytes, entry))
            entries.sort(key=lambda item: item[0])
        except OSError as exc:
            raise SystemExit(f"worktree generation could not be inventoried: {exc}") from exc
        for name_bytes, entry in entries:
            name = entry.name
            relative = prefix + (b"/" if prefix else b"") + name_bytes
            try:
                named = os.stat(
                    name,
                    dir_fd=directory_descriptor,
                    follow_symlinks=False,
                )
            except OSError as exc:
                raise SystemExit(
                    f"worktree generation entry changed during inventory: {os.fsdecode(relative)}"
                ) from exc
            digest.update(len(relative).to_bytes(8, "big"))
            digest.update(relative)
            digest.update(repr(safe_paths.stable_file_metadata(named)).encode("ascii"))
            if stat.S_ISDIR(named.st_mode):
                try:
                    child = os.open(name, directory_flags, dir_fd=directory_descriptor)
                except OSError as exc:
                    raise SystemExit(
                        "worktree generation directory could not be opened safely: "
                        f"{os.fsdecode(relative)}: {exc}"
                    ) from exc
                try:
                    opened = os.fstat(child)
                    if _stable_identity(opened) != _stable_identity(named):
                        raise SystemExit(
                            "worktree generation directory changed while it was opened: "
                            f"{os.fsdecode(relative)}"
                        )
                    visit(child, relative, depth + 1)
                    after = os.fstat(child)
                    named_after = os.stat(
                        name,
                        dir_fd=directory_descriptor,
                        follow_symlinks=False,
                    )
                    if (
                        safe_paths.stable_file_metadata(opened)
                        != safe_paths.stable_file_metadata(after)
                        or _stable_identity(named_after) != _stable_identity(after)
                    ):
                        raise SystemExit(
                            "worktree generation directory changed during inventory: "
                            f"{os.fsdecode(relative)}"
                        )
                except OSError as exc:
                    raise SystemExit(
                        "worktree generation directory changed during inventory: "
                        f"{os.fsdecode(relative)}: {exc}"
                    ) from exc
                finally:
                    os.close(child)
            elif stat.S_ISREG(named.st_mode) and name_bytes == b".gitignore":
                raw, consumed = _read_ignore_generation(
                    directory_descriptor,
                    name,
                    named,
                    remaining_bytes=GIT_IGNORE_GENERATION_MAX_BYTES - ignore_bytes,
                )
                ignore_bytes += consumed
                digest.update(hashlib.sha256(raw).digest())
        after_directory = os.fstat(directory_descriptor)
        if (
            safe_paths.stable_file_metadata(before_directory)
            != safe_paths.stable_file_metadata(after_directory)
        ):
            raise SystemExit("worktree generation changed during inventory")

    try:
        retained_root = os.dup(root_descriptor)
    except OSError as exc:
        raise SystemExit(f"worktree generation root could not be retained: {exc}") from exc
    try:
        visit(retained_root, b"", 0)
    finally:
        os.close(retained_root)
    return digest.hexdigest()


def _open_index_path_parent(
    root_descriptor: int,
    parts: tuple[str, ...],
) -> _IndexParentBinding | None:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    if not getattr(os, "O_DIRECTORY", 0) or not getattr(os, "O_NOFOLLOW", 0):
        raise SystemExit(
            "safe worktree comparison requires O_DIRECTORY and O_NOFOLLOW"
        )
    try:
        descriptors = [os.dup(root_descriptor)]
    except OSError as exc:
        raise SystemExit(
            f"safe worktree root descriptor could not be retained: {exc}"
        ) from exc
    try:
        for component in parts[:-1]:
            try:
                next_descriptor = os.open(
                    component,
                    flags,
                    dir_fd=descriptors[-1],
                )
            except OSError:
                try:
                    _close_index_descriptors(descriptors)
                finally:
                    descriptors.clear()
                return None
            descriptors.append(next_descriptor)
        binding = _IndexParentBinding(
            components=parts[:-1],
            descriptors=tuple(descriptors),
        )
        binding.require_current()
        return binding
    except BaseException as primary:
        _close_index_descriptors(descriptors, primary=primary)
        raise


def _worktree_entry_matches_index(
    root_descriptor: int,
    entry: GitIndexEntry,
    *,
    remaining_bytes: int,
) -> tuple[bool, int]:
    if entry.mode == "040000":
        raise SystemExit(
            "safe worktree comparison does not support sparse-directory index entries"
        )
    if entry.mode == "160000":
        # A submodule is itself another repository boundary. Conservatively widen
        # evidence rather than following its metadata from this query.
        return False, 0
    if entry.mode not in {"100644", "100755", "120000"}:
        raise SystemExit(f"Git index inventory returned an unsupported mode: {entry.mode}")

    parts = _index_path_parts(entry.path)
    parent_binding = _open_index_path_parent(root_descriptor, parts)
    if parent_binding is None:
        return False, 0
    with parent_binding:
        parent_descriptor = parent_binding.descriptor
        name = parts[-1]
        try:
            before = os.stat(
                name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except OSError:
            return False, 0

        if entry.mode == "120000":
            if not stat.S_ISLNK(before.st_mode):
                return False, 0
            try:
                target = os.readlink(name, dir_fd=parent_descriptor)
                after = os.stat(
                    name,
                    dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
            except OSError:
                return False, 0
            if safe_paths.stable_file_metadata(before) != safe_paths.stable_file_metadata(
                after
            ):
                raise SystemExit(
                    f"worktree path changed during safe comparison: {entry.path}"
                )
            content = os.fsencode(target)
            if len(content) > remaining_bytes:
                raise SystemExit(
                    "safe worktree comparison exceeded the "
                    f"{GIT_WORKTREE_COMPARISON_MAX_BYTES}-byte read limit"
                )
            hasher = _git_blob_hasher(entry.oid, len(content))
            hasher.update(content)
            return hasher.hexdigest() == entry.oid, len(content)

        if not stat.S_ISREG(before.st_mode):
            return False, 0
        expected_executable = entry.mode == "100755"
        if bool(before.st_mode & stat.S_IXUSR) != expected_executable:
            return False, 0
        if before.st_size > remaining_bytes:
            raise SystemExit(
                "safe worktree comparison exceeded the "
                f"{GIT_WORKTREE_COMPARISON_MAX_BYTES}-byte read limit"
            )
        flags = (
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0)
            | getattr(os, "O_CLOEXEC", 0)
        )
        if not getattr(os, "O_NOFOLLOW", 0) or not getattr(os, "O_NONBLOCK", 0):
            raise SystemExit(
                "safe worktree comparison requires O_NOFOLLOW and O_NONBLOCK"
            )
        try:
            descriptor = os.open(name, flags, dir_fd=parent_descriptor)
        except OSError as exc:
            raise SystemExit(
                f"worktree path could not be opened safely: {entry.path}: {exc}"
            ) from exc
        try:
            opened = os.fstat(descriptor)
            if (
                not stat.S_ISREG(opened.st_mode)
                or _stable_identity(opened) != _stable_identity(before)
            ):
                return False, 0
            hasher = _git_blob_hasher(entry.oid, opened.st_size)
            total = 0
            while True:
                try:
                    chunk = os.read(
                        descriptor,
                        min(1024 * 1024, remaining_bytes - total + 1),
                    )
                except OSError as exc:
                    raise SystemExit(
                        f"worktree path could not be read safely: {entry.path}: {exc}"
                    ) from exc
                if not chunk:
                    break
                total += len(chunk)
                if total > remaining_bytes:
                    raise SystemExit(
                        "safe worktree comparison exceeded the "
                        f"{GIT_WORKTREE_COMPARISON_MAX_BYTES}-byte read limit"
                    )
                hasher.update(chunk)
            after = os.fstat(descriptor)
            try:
                named_after = os.stat(
                    name,
                    dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
            except OSError as exc:
                raise SystemExit(
                    f"worktree path changed during safe comparison: {entry.path}"
                ) from exc
            if (
                total != after.st_size
                or safe_paths.stable_file_metadata(opened)
                != safe_paths.stable_file_metadata(after)
                or _stable_identity(named_after) != _stable_identity(after)
            ):
                raise SystemExit(
                    f"worktree path changed during safe comparison: {entry.path}"
                )
            return hasher.hexdigest() == entry.oid, total
        finally:
            os.close(descriptor)


def _worktree_modified_paths_from_descriptor(
    root_descriptor: int,
    entries: list[GitIndexEntry],
) -> list[str]:
    by_path: dict[str, list[GitIndexEntry]] = {}
    for entry in entries:
        by_path.setdefault(entry.path, []).append(entry)
    modified: list[str] = []
    consumed_bytes = 0
    for path, path_entries in by_path.items():
        if len(path_entries) != 1 or path_entries[0].stage != 0:
            modified.append(path)
            continue
        matches, read_bytes = _worktree_entry_matches_index(
            root_descriptor,
            path_entries[0],
            remaining_bytes=GIT_WORKTREE_COMPARISON_MAX_BYTES - consumed_bytes,
        )
        consumed_bytes += read_bytes
        if not matches:
            modified.append(path)
    return modified


def worktree_modified_paths(
    root: Path,
    entries: list[GitIndexEntry],
    *,
    root_descriptor: int | None = None,
) -> list[str]:
    """Conservatively compare raw worktree bytes to index object identities.

    Built-in attribute or line-ending conversions can widen this set. External
    clean/process filters are never invoked; unbound config includes are
    rejected by the repository binding.
    """

    if root_descriptor is not None:
        return _worktree_modified_paths_from_descriptor(root_descriptor, entries)
    try:
        root_binding = safe_paths.open_output_directory(root, create_missing=False)
    except (OSError, RuntimeError, ValueError) as exc:
        raise SystemExit(f"worktree root cannot be bound for safe comparison: {exc}") from exc
    with root_binding:
        root_binding.require_unchanged_chain(
            description="safe worktree-comparison root"
        )
        modified = _worktree_modified_paths_from_descriptor(
            root_binding.descriptor,
            entries,
        )
        root_binding.require_unchanged_chain(
            description="safe worktree-comparison root"
        )
    return modified


def _git_revision_generation(
    revision: str,
    binding: git_query.GitRepositoryBinding,
) -> str:
    args = ["rev-parse", "--verify", "--end-of-options", revision]
    returncode, stdout, stderr = _bounded_git_with_binding(args, binding)
    if returncode != 0:
        detail = stderr.decode("utf-8", errors="replace").strip()
        raise SystemExit(detail or f"git revision verification failed: {revision}")
    if stderr or re.fullmatch(rb"[0-9a-f]{40}\n|[0-9a-f]{64}\n", stdout) is None:
        raise SystemExit("Git revision verification returned an invalid object identity")
    return stdout[:-1].decode("ascii")


def collect_paths(args: argparse.Namespace, root: Path) -> list[str]:
    if args.path:
        return sorted(dict.fromkeys(validate_paths(args.path, root)))
    if args.diff_base:
        validate_diff_base(args.diff_base)
        try:
            with git_query.bind_git_repository(root) as binding:
                initial_worktree = _worktree_generation_digest(
                    binding.worktree_descriptor
                )
                initial_revision = _git_revision_generation(args.diff_base, binding)
                staged = run_git(
                    [
                        "diff",
                        "--cached",
                        "--no-ext-diff",
                        "--no-textconv",
                        "--name-only",
                        "-z",
                        initial_revision,
                        "--",
                    ],
                    root,
                    binding=binding,
                )
                index_entries = run_git_index(root, binding=binding)
                unstaged = worktree_modified_paths(
                    root,
                    index_entries,
                    root_descriptor=binding.worktree_descriptor,
                )
                untracked = run_git(
                    ["ls-files", "--others", "--exclude-standard", "-z", "--"],
                    root,
                    binding=binding,
                )
                validated = validate_git_paths(
                    [*staged, *unstaged, *untracked],
                    binding.worktree_descriptor,
                )
                final_worktree = _worktree_generation_digest(
                    binding.worktree_descriptor
                )
                final_revision = _git_revision_generation(args.diff_base, binding)
                binding.require_current()
                if initial_revision != final_revision:
                    raise SystemExit(
                        "Git diff-base revision changed during path collection"
                    )
                if initial_worktree != final_worktree:
                    raise SystemExit(
                        "Git worktree or ignore generation changed during path collection"
                    )
        except (OSError, RuntimeError, ValueError) as exc:
            raise SystemExit(
                f"Git repository generation rejected path collection: {exc}"
            ) from exc
        return sorted(dict.fromkeys(validated))
    raise SystemExit("pass --path or --diff-base")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Recommend the smallest sufficient evidence scope for a task.",
        allow_abbrev=False,
    )
    for flag, help_text in recommend_stack.CLI_FLAGS:
        parser.add_argument(f"--{flag}", action="store_true", help=help_text)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--path", action="append", default=[], help="Repo-relative relevant file path.")
    source.add_argument(
        "--diff-base",
        help="Git revision to diff against when collecting changed files automatically.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Repository root for path validation and Git inspection. Defaults to the invocation working directory.",
    )
    return parser


def classify_path(path: str) -> dict[str, object]:
    lower = path.lower()
    tokens = set(TOKEN_RE.findall(lower))
    shared_terms = [term for term in SHARED_SURFACE_TERMS if term in tokens]
    stem = Path(path).stem
    return {
        "path": path,
        "consumer_query": f"rg -n -F -- {shlex.quote(stem)} .",
        "shared_surface_terms": shared_terms,
    }


def escalate_scope(
    base_scope: str,
    path_summaries: list[dict[str, object]],
    *,
    impact_review: bool = False,
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if impact_review and SCOPE_ORDER.index(base_scope) < SCOPE_ORDER.index("feature-slice"):
        reasons.append("Impact review requires following the changed invariant through its feature slice.")
        base_scope = "feature-slice"
    if any(summary["shared_surface_terms"] for summary in path_summaries):
        reasons.append("Shared-surface file names suggest unchanged consumers may depend on the old behavior.")
        if base_scope == "patch":
            base_scope = "touched-files"
        elif base_scope == "touched-files":
            base_scope = "feature-slice"
    return base_scope, reasons


def main() -> int:
    args = build_parser().parse_args()
    root = validate_root(args.root)
    paths = collect_paths(args, root)
    standard_of_care = recommend_stack.choose_standard_of_care(args)
    base_scope = recommend_stack.choose_evidentiary_scope(args, standard_of_care)
    path_summaries = [classify_path(path) for path in paths]
    recommended_scope, escalation_reasons = escalate_scope(
        base_scope,
        path_summaries,
        impact_review=args.impact_review,
    )

    result = {
        "evidence_files": paths,
        "path_collection": {
            "source": "explicit_paths" if args.path else "git_diff",
            "untracked_files_included": bool(args.diff_base),
        },
        "path_summaries": path_summaries,
        "recommended_scope": recommended_scope,
        "scope_reasons": escalation_reasons,
        "standard_of_care": standard_of_care,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
