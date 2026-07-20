#!/usr/bin/env python3

from __future__ import annotations

import argparse
from collections.abc import Callable
from datetime import datetime, timezone
import hashlib
import hmac
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import selectors
import signal
import stat
import subprocess
import sys
import time
from typing import Any
import unicodedata

import automation_orders_lint
import generated_sow_text
import project_state_identity
import resource_cleanup
import safe_paths


FRAMEWORK_ROOT = Path(__file__).resolve().parent.parent
CRON_JOB_AUTHORITY_DIGEST_VERSION = 5
CRON_PYCACHE_PREFIX = os.devnull
CRON_HELPER_PYTHON_FLAGS = (
    "-B",
    "-X",
    f"pycache_prefix={CRON_PYCACHE_PREFIX}",
)
CRON_RUNTIME_SOURCE_PATHS = (
    "scripts/automation_orders_lint.py",
    "scripts/generated_sow_text.py",
    "scripts/project_state_identity.py",
    "scripts/resource_cleanup.py",
    "scripts/run_scheduled_job.py",
    "scripts/safe_paths.py",
)
MAX_BOUND_CONTROL_SOURCE_TOTAL_BYTES = 64 * 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PROCESS_TERMINATION_GRACE_SECONDS = 1.0
LOG_CONTROL_RESERVE_BYTES = 1024
LOG_LIMIT_EXIT = 125
LINGERING_PROCESS_EXIT = 126


def job_authority_sha256(
    job: dict[str, object],
    project_root: Path,
    manifest_path: Path,
) -> str:
    """Seal one cron job's declared local control inputs for drift detection."""

    normalized_root = automation_orders_lint.normalize_project_root(project_root)
    manifest_relative = automation_orders_lint.manifest_relative_to_project(
        normalized_root,
        manifest_path,
        require_existing=False,
    )

    cwd_errors: list[str] = []
    cwd = automation_orders_lint.normalized_job_cwd(
        "job cwd",
        job.get("cwd"),
        normalized_root,
        cwd_errors,
        require_existing=True,
    )
    if cwd is None or cwd_errors:
        raise ValueError("; ".join(cwd_errors) or "job cwd is invalid")
    _verify_local_runtime_module_origins()
    owned = resource_cleanup.OwnedFileDescriptors()
    project_descriptor = owned.adopt(
        open_absolute_directory(
            normalized_root,
            description="selected project root",
        ),
        "selected project-root descriptor",
    )
    try:
        framework_descriptor = owned.adopt(
            open_absolute_directory(
                FRAMEWORK_ROOT,
                description="selected framework root",
            ),
            "selected framework-root descriptor",
        )
        cwd_descriptor = owned.adopt(
            open_project_relative_directory(
                project_descriptor,
                cwd,
                description="job cwd",
            ),
            "job-cwd descriptor",
        )
        return _job_authority_sha256_from_descriptors(
            job,
            normalized_root,
            manifest_relative,
            project_descriptor,
            cwd_descriptor,
            framework_descriptor,
        )
    finally:
        owned.cleanup(primary=sys.exception())


def _directory_identity(descriptor: int) -> dict[str, int]:
    opened = os.fstat(descriptor)
    if not stat.S_ISDIR(opened.st_mode):
        raise ValueError("cron authority identity must refer to a directory")
    return {"device": opened.st_dev, "inode": opened.st_ino}


def _job_authority_sha256_from_descriptors(
    job: dict[str, object],
    project_root: Path,
    manifest_relative: Path,
    project_descriptor: int,
    cwd_descriptor: int,
    framework_descriptor: int,
) -> str:
    bound_sources = _bound_source_records(
        job,
        project_descriptor=project_descriptor,
        framework_descriptor=framework_descriptor,
    )
    payload = {
        "automation_orders_schema_version": automation_orders_lint.SCHEMA_VERSION,
        "backend": "cron",
        "bound_sources": bound_sources,
        "cwd_identity": _directory_identity(cwd_descriptor),
        "digest_version": CRON_JOB_AUTHORITY_DIGEST_VERSION,
        "framework_root": str(FRAMEWORK_ROOT),
        "framework_root_identity": _directory_identity(framework_descriptor),
        "job": job,
        "manifest": manifest_relative.as_posix(),
        "project_root": str(project_root),
        "project_root_identity": _directory_identity(project_descriptor),
        "python_runtime_flags": list(CRON_HELPER_PYTHON_FLAGS),
    }
    canonical = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _verify_local_runtime_module_origins() -> None:
    expected_modules = {
        "automation_orders_lint": (
            automation_orders_lint,
            "scripts/automation_orders_lint.py",
        ),
        "generated_sow_text": (generated_sow_text, "scripts/generated_sow_text.py"),
        "project_state_identity": (
            project_state_identity,
            "scripts/project_state_identity.py",
        ),
        "safe_paths": (safe_paths, "scripts/safe_paths.py"),
    }
    expected_runner = (FRAMEWORK_ROOT / "scripts/run_scheduled_job.py").resolve(
        strict=True
    )
    if Path(__file__).resolve(strict=True) != expected_runner:
        raise RuntimeError("scheduled runtime runner did not load from the bound framework root")
    for name, (module, relative_path) in expected_modules.items():
        module_file = getattr(module, "__file__", None)
        if not isinstance(module_file, str):
            raise RuntimeError(f"scheduled runtime module {name} has no file origin")
        expected = (FRAMEWORK_ROOT / relative_path).resolve(strict=True)
        if Path(module_file).resolve(strict=True) != expected:
            raise RuntimeError(
                f"scheduled runtime module {name} did not load from the bound framework root"
            )


def _verify_python_cache_isolation() -> None:
    if sys.pycache_prefix != CRON_PYCACHE_PREFIX or not sys.dont_write_bytecode:
        raise RuntimeError(
            "scheduled runtime requires its sealed Python bytecode-cache isolation flags"
        )


def _declared_source_references(
    job: dict[str, object],
    field_name: str,
) -> list[tuple[str, str]]:
    value = job.get(field_name)
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list")
    references: list[tuple[str, str]] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict) or set(item) != automation_orders_lint.SOURCE_REFERENCE_KEYS:
            raise ValueError(
                f"{field_name}[{index}] must be a closed source-reference object"
            )
        source_root = item.get("root")
        path = item.get("path")
        if source_root not in automation_orders_lint.SOURCE_REFERENCE_ROOTS:
            raise ValueError(f"{field_name}[{index}].root is invalid")
        if not isinstance(path, str):
            raise ValueError(f"{field_name}[{index}].path must be a string")
        references.append((str(source_root), path))
    return references


def _bound_source_records(
    job: dict[str, object],
    *,
    project_descriptor: int,
    framework_descriptor: int,
) -> list[dict[str, object]]:
    sources: list[tuple[str, str, str]] = [
        ("runtime", "framework", path) for path in CRON_RUNTIME_SOURCE_PATHS
    ]
    for field_name, role in (
        ("instruction_sources", "instruction"),
        ("execution_sources", "execution"),
    ):
        sources.extend(
            (role, source_root, path)
            for source_root, path in _declared_source_references(job, field_name)
        )
    if len(sources) > (
        automation_orders_lint.MAX_BOUND_SOURCE_REFERENCES
        + len(CRON_RUNTIME_SOURCE_PATHS)
    ):
        raise ValueError("bound source count exceeds the runtime limit")

    records: list[dict[str, object]] = []
    total_bytes = 0
    declared_bytes = 0
    for role, source_root, path in sorted(sources):
        descriptor = (
            framework_descriptor if source_root == "framework" else project_descriptor
        )
        raw = read_project_regular_file_bytes(
            descriptor,
            Path(path),
            description=f"{role} {source_root}-rooted source",
            max_bytes=automation_orders_lint.MAX_BOUND_SOURCE_FILE_BYTES,
        )
        total_bytes += len(raw)
        if role != "runtime":
            declared_bytes += len(raw)
            if declared_bytes > automation_orders_lint.MAX_BOUND_SOURCE_TOTAL_BYTES:
                raise ValueError(
                    "declared instruction and execution sources exceed the "
                    f"{automation_orders_lint.MAX_BOUND_SOURCE_TOTAL_BYTES}-byte "
                    "aggregate limit"
                )
        if total_bytes > MAX_BOUND_CONTROL_SOURCE_TOTAL_BYTES:
            raise ValueError(
                "bound runtime, instruction, and execution sources exceed the "
                f"{MAX_BOUND_CONTROL_SOURCE_TOTAL_BYTES}-byte aggregate limit"
            )
        records.append(
            {
                "byte_count": len(raw),
                "path": path,
                "role": role,
                "root": source_root,
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    return records


def _directory_flags() -> int:
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory = getattr(os, "O_DIRECTORY", 0)
    if not nofollow or not directory or os.open not in os.supports_dir_fd:
        raise RuntimeError("confined cron execution requires POSIX no-follow directory-descriptor support")
    return os.O_RDONLY | nofollow | directory | getattr(os, "O_CLOEXEC", 0)


def _platform_physical_path(path: Path) -> Path:
    for alias, target in safe_paths.ALLOWED_SYSTEM_SYMLINK_TARGETS.items():
        if not alias.is_symlink() or not safe_paths.is_allowed_system_symlink(alias):
            continue
        try:
            suffix = path.relative_to(alias)
        except ValueError:
            continue
        return target / suffix
    return path


def open_absolute_directory(path: Path, *, description: str) -> int:
    """Open an absolute directory one no-follow component at a time."""

    path = _platform_physical_path(path.expanduser().absolute())
    if not path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts[1:]):
        raise ValueError(f"{description} must be a normalized absolute directory path")
    flags = _directory_flags()
    owned = resource_cleanup.OwnedFileDescriptors()
    descriptor = owned.adopt(
        os.open(path.anchor, flags),
        f"{description} path-component descriptor",
    )
    try:
        for part in path.parts[1:]:
            next_descriptor = owned.adopt(
                os.open(part, flags, dir_fd=descriptor),
                f"{description} path-component descriptor",
            )
            owned.close(descriptor)
            descriptor = next_descriptor
        opened = os.fstat(descriptor)
        if not stat.S_ISDIR(opened.st_mode):
            raise ValueError(f"{description} must be a directory")
        return owned.release(descriptor)
    except BaseException as primary:
        owned.cleanup(primary=primary)
        raise


def open_project_relative_directory(
    project_descriptor: int,
    relative_value: str,
    *,
    description: str,
) -> int:
    """Open one existing project-relative directory without following symlinks."""

    parts = () if relative_value == "." else _relative_parts(
        relative_value,
        description=description,
    )
    if parts:
        _require_exact_descriptor_spelling(
            project_descriptor,
            parts,
            description=description,
        )
    owned = resource_cleanup.OwnedFileDescriptors()
    descriptor = owned.adopt(
        os.dup(project_descriptor),
        f"{description} path-component descriptor",
    )
    flags = _directory_flags()
    try:
        for part in parts:
            next_descriptor = owned.adopt(
                os.open(part, flags, dir_fd=descriptor),
                f"{description} path-component descriptor",
            )
            owned.close(descriptor)
            descriptor = next_descriptor
        return owned.release(descriptor)
    except BaseException as primary:
        owned.cleanup(primary=primary)
        raise


def _require_private_owned_directory(descriptor: int, *, description: str) -> None:
    opened = os.fstat(descriptor)
    if not stat.S_ISDIR(opened.st_mode):
        raise ValueError(f"{description} must be a directory")
    if opened.st_uid != os.geteuid():
        raise ValueError(f"{description} must be owned by the scheduler user")
    if stat.S_IMODE(opened.st_mode) & 0o077:
        raise ValueError(f"{description} must not grant group or world permissions")


def open_or_create_private_directory(
    parent_descriptor: int,
    relative_parts: tuple[str, ...],
    *,
    description: str,
) -> int:
    owned = resource_cleanup.OwnedFileDescriptors()
    descriptor = owned.adopt(
        os.dup(parent_descriptor),
        f"{description} path-component descriptor",
    )
    flags = _directory_flags()
    try:
        for part in relative_parts:
            try:
                os.mkdir(part, mode=0o700, dir_fd=descriptor)
            except FileExistsError:
                pass
            next_descriptor = owned.adopt(
                os.open(part, flags, dir_fd=descriptor),
                f"{description} path-component descriptor",
            )
            owned.close(descriptor)
            descriptor = next_descriptor
            _require_private_owned_directory(descriptor, description=description)
        return owned.release(descriptor)
    except BaseException as primary:
        owned.cleanup(primary=primary)
        raise


def _relative_parts(value: str, *, description: str) -> tuple[str, ...]:
    path = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError(f"{description} must be a safe repo-relative path")
    return path.parts


def _filesystem_identity(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def _require_exact_descriptor_spelling(
    root_descriptor: int,
    parts: tuple[str, ...],
    *,
    description: str,
) -> None:
    owned = resource_cleanup.OwnedFileDescriptors()
    descriptor = owned.adopt(
        os.dup(root_descriptor),
        f"{description} spelling-check descriptor",
    )
    try:
        for index, expected in enumerate(parts):
            with os.scandir(descriptor) as entries:
                names = [entry.name for entry in entries]
            aliases = [
                name
                for name in names
                if _filesystem_identity(name) == _filesystem_identity(expected)
            ]
            if expected not in names:
                if aliases:
                    raise ValueError(
                        f"{description} must use exact path spelling {expected!r}; "
                        f"found {sorted(aliases)!r}"
                    )
                return
            if len(aliases) > 1:
                raise ValueError(
                    f"{description} has ambiguous path spellings for {expected!r}: "
                    f"{sorted(aliases)!r}"
                )
            if index == len(parts) - 1:
                return
            next_descriptor = owned.adopt(
                os.open(
                    expected,
                    _directory_flags(),
                    dir_fd=descriptor,
                ),
                f"{description} spelling-check descriptor",
            )
            owned.close(descriptor)
            descriptor = next_descriptor
    finally:
        owned.cleanup(primary=sys.exception())


def open_private_regular_file(
    root_descriptor: int,
    relative_value: str,
    *,
    description: str,
    append: bool,
) -> int:
    parts = _relative_parts(relative_value, description=description)
    owned = resource_cleanup.OwnedFileDescriptors()
    parent_descriptor = owned.adopt(
        open_or_create_private_directory(
            root_descriptor,
            parts[:-1],
            description=f"{description} parent",
        ),
        f"{description} parent descriptor",
    )
    try:
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        if not nofollow or os.open not in os.supports_dir_fd:
            raise RuntimeError("confined cron execution requires POSIX no-follow file support")
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | nofollow
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NONBLOCK", 0)
        )
        if append:
            flags |= os.O_APPEND
        descriptor = owned.adopt(
            os.open(parts[-1], flags, 0o600, dir_fd=parent_descriptor),
            f"{description} file descriptor",
        )
        owned.close(parent_descriptor)
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise ValueError(f"{description} must be a regular file")
        if opened.st_uid != os.geteuid():
            raise ValueError(f"{description} must be owned by the scheduler user")
        if opened.st_nlink != 1:
            raise ValueError(f"{description} must not be hard-linked")
        if stat.S_IMODE(opened.st_mode) & 0o077:
            raise ValueError(f"{description} must not grant group or world permissions")
        return owned.release(descriptor)
    except BaseException as primary:
        owned.cleanup(primary=primary)
        raise


def read_project_regular_file_bytes(
    project_descriptor: int,
    relative_path: Path,
    *,
    description: str,
    max_bytes: int = safe_paths.DEFAULT_JSON_INPUT_MAX_BYTES,
) -> bytes:
    """Read one bounded stable regular file relative to a bound project root."""

    parts = _relative_parts(relative_path.as_posix(), description=description)
    _require_exact_descriptor_spelling(
        project_descriptor,
        parts,
        description=description,
    )
    parent = PurePosixPath(*parts[:-1]).as_posix() if parts[:-1] else "."
    owned = resource_cleanup.OwnedFileDescriptors()
    parent_descriptor = owned.adopt(
        open_project_relative_directory(
            project_descriptor,
            parent,
            description=f"{description} parent",
        ),
        f"{description} parent descriptor",
    )
    try:
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        nonblock = getattr(os, "O_NONBLOCK", 0)
        if not nofollow or not nonblock or os.open not in os.supports_dir_fd:
            raise RuntimeError(
                "confined cron execution requires POSIX no-follow regular-file support"
            )
        descriptor = owned.adopt(
            os.open(
                parts[-1],
                os.O_RDONLY | nofollow | nonblock | getattr(os, "O_CLOEXEC", 0),
                dir_fd=parent_descriptor,
            ),
            f"{description} file descriptor",
        )
        owned.close(parent_descriptor)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError(f"{description} must be a regular file")
        if before.st_nlink != 1:
            raise ValueError(f"{description} must have exactly one hard link")
        if before.st_size > max_bytes:
            raise ValueError(f"{description} exceeds the {max_bytes}-byte input limit")
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(descriptor)
        stable_fields = (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_nlink",
            "st_uid",
            "st_gid",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
        if len(raw) > max_bytes:
            raise ValueError(f"{description} exceeds the {max_bytes}-byte input limit")
        if any(getattr(before, field) != getattr(after, field) for field in stable_fields):
            raise ValueError(f"{description} changed while it was being read")
        if len(raw) != after.st_size:
            raise ValueError(f"{description} changed while it was being read")
        return raw
    finally:
        owned.cleanup(primary=sys.exception())


def _append_capped(descriptor: int, payload: bytes, max_bytes: int) -> int:
    """Atomically append one complete record without growing beyond the cap."""

    import fcntl

    fcntl.flock(descriptor, fcntl.LOCK_EX)
    try:
        current_size = os.fstat(descriptor).st_size
        remaining = max(0, max_bytes - current_size)
        if len(payload) > remaining:
            return 0
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise OSError("scheduler log write made no progress")
            offset += written
        return len(payload)
    finally:
        resource_cleanup.cleanup_actions(
            [
                (
                    "scheduler log advisory lock",
                    lambda: fcntl.flock(descriptor, fcntl.LOCK_UN),
                )
            ],
            primary=sys.exception(),
        )


def _write_control_record(
    descriptor: int,
    run_id: str,
    event: str,
    message: str,
    max_log_bytes: int,
) -> bool:
    payload = (
        f"[{datetime.now(timezone.utc).isoformat()}] CONTROL run={run_id} "
        f"event={event} {message.rstrip()}\n"
    ).encode("utf-8", errors="replace")
    return _append_capped(descriptor, payload, max_log_bytes) == len(payload)


def _write_output_record(
    descriptor: int,
    run_id: str,
    payload: bytes,
    max_log_bytes: int,
) -> bool:
    header = (
        f"[{datetime.now(timezone.utc).isoformat()}] OUTPUT run={run_id} "
        f"bytes={len(payload)}\n"
    ).encode("ascii")
    framed = header + payload + b"\n"
    return _append_capped(descriptor, framed, max_log_bytes) == len(framed)


def _selected_job_from_data(
    data: object,
    job_id: str,
) -> dict[str, Any]:
    if (
        automation_orders_lint.has_control(job_id)
        or automation_orders_lint.JOB_ID_RE.fullmatch(job_id) is None
    ):
        raise ValueError("scheduled job id must be one control-free safe slug")
    if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
        raise ValueError("automation manifest jobs must be a list")
    matches = [
        job
        for job in data["jobs"]
        if isinstance(job, dict) and job.get("id") == job_id
    ]
    if len(matches) != 1:
        raise ValueError(f"automation manifest must contain exactly one job {job_id!r}")
    job = matches[0]
    return job


def _validate_descriptor_bound_data(
    data: object,
    project_root: Path,
    manifest_path: Path,
) -> None:
    errors, _warnings = automation_orders_lint.validate_descriptor_bound_manifest(
        data,
        "cron",
        project_root=project_root,
        manifest_path=manifest_path,
    )
    if errors:
        raise ValueError(
            "automation manifest is no longer cron-compatible: "
            + "; ".join(errors)
        )


def _verify_job_authority(
    job: dict[str, object],
    project_root: Path,
    manifest_relative: Path,
    project_descriptor: int,
    cwd_descriptor: int,
    framework_descriptor: int,
    expected_job_sha256: str,
) -> None:
    if not SHA256_RE.fullmatch(expected_job_sha256):
        raise ValueError(
            "expected job SHA-256 must be exactly 64 lowercase hexadecimal characters"
        )
    current_job_sha256 = _job_authority_sha256_from_descriptors(
        job,
        project_root,
        manifest_relative,
        project_descriptor,
        cwd_descriptor,
        framework_descriptor,
    )
    if not hmac.compare_digest(current_job_sha256, expected_job_sha256):
        raise ValueError(
            f"automation job {job.get('id')!r} authority changed since cron rendering "
            "(job data, bound source bytes, runtime bundle, or project/framework "
            "identity); rerender and reinstall the cron entry"
        )


def validated_job(
    project_root: Path,
    manifest_path: Path,
    job_id: str,
    expected_job_sha256: str,
) -> dict[str, Any]:
    _verify_local_runtime_module_origins()
    normalized_root = automation_orders_lint.normalize_project_root(project_root)
    manifest_relative = automation_orders_lint.manifest_relative_to_project(
        normalized_root,
        manifest_path,
    )
    owned = resource_cleanup.OwnedFileDescriptors()
    project_descriptor = owned.adopt(
        open_absolute_directory(
            normalized_root,
            description="selected project root",
        ),
        "selected project root descriptor",
    )
    try:
        framework_descriptor = owned.adopt(
            open_absolute_directory(
                FRAMEWORK_ROOT,
                description="selected framework root",
            ),
            "selected framework root descriptor",
        )
        raw = read_project_regular_file_bytes(
            project_descriptor,
            manifest_relative,
            description="automation manifest",
        )
        data = safe_paths.loads_json_no_duplicates(raw.decode("utf-8"))
        job = _selected_job_from_data(
            data,
            job_id,
        )
        cwd_value = job.get("cwd")
        if not isinstance(cwd_value, str):
            raise ValueError(f"automation job {job_id!r} cwd must be a string")
        cwd_descriptor = owned.adopt(
            open_project_relative_directory(
                project_descriptor,
                cwd_value,
                description="job cwd",
            ),
            "job cwd descriptor",
        )
        _validate_descriptor_bound_data(data, normalized_root, manifest_path)
        _verify_job_authority(
            job,
            normalized_root,
            manifest_relative,
            project_descriptor,
            cwd_descriptor,
            framework_descriptor,
            expected_job_sha256,
        )
        if job.get("enabled") is not True:
            raise ValueError(f"automation job {job_id!r} is not enabled")
        return job
    finally:
        owned.cleanup(primary=sys.exception())


def _process_group_exists(process_group_id: int) -> bool:
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _parse_linux_proc_stat_state_and_process_group(
    stat_record: bytes,
) -> tuple[bytes, int] | None:
    """Extract state and process-group fields without decoding ``comm``."""

    opening_parenthesis = stat_record.find(b"(")
    closing_parenthesis = stat_record.rfind(b")")
    if (
        opening_parenthesis <= 0
        or closing_parenthesis <= opening_parenthesis
        or not stat_record[:opening_parenthesis].strip().isdigit()
    ):
        return None

    fields = stat_record[closing_parenthesis + 1 :].split()
    if len(fields) < 3:
        return None
    state, parent_process, process_group = fields[:3]
    if len(state) != 1 or not state.isalpha():
        return None

    def parse_signed_decimal(value: bytes) -> int | None:
        magnitude = value[1:] if value.startswith(b"-") else value
        if not magnitude or not magnitude.isdigit():
            return None
        return int(value)

    if parse_signed_decimal(parent_process) is None:
        return None
    process_group_id = parse_signed_decimal(process_group)
    if process_group_id is None:
        return None
    return state, process_group_id


def _process_group_has_live_linux_member(process_group_id: int) -> bool | None:
    """Report whether a Linux process group has a non-zombie member.

    A killed orphan can remain as a zombie until the container's init process
    reaps it. ``killpg(..., 0)`` still reports that group as present even though
    no member can execute. Linux exposes enough read-only process metadata to
    distinguish that state; other platforms fall back to the portable probe.
    """

    proc_root = Path("/proc")
    if not proc_root.is_dir():
        return None
    try:
        entries = proc_root.iterdir()
        for entry in entries:
            if not entry.name.isdecimal():
                continue
            try:
                stat_record = (entry / "stat").read_bytes()
            except (FileNotFoundError, ProcessLookupError):
                continue
            except OSError:
                return None
            parsed = _parse_linux_proc_stat_state_and_process_group(stat_record)
            if parsed is None:
                return None
            state, member_process_group_id = parsed
            if member_process_group_id != process_group_id:
                continue
            if state not in {b"X", b"Z"}:
                return True
    except OSError:
        return None
    return False


def _wait_for_process_group_exit(process_group_id: int, deadline: float) -> bool:
    while _process_group_exists(process_group_id):
        live_linux_member = _process_group_has_live_linux_member(process_group_id)
        if live_linux_member is False:
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(0.01, remaining))
    return True


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    """Terminate and prove exit of the entire non-detached dedicated group."""

    process_group_id = process.pid
    try:
        os.killpg(process_group_id, signal.SIGTERM)
    except ProcessLookupError:
        process.poll()
        return
    try:
        process.wait(timeout=PROCESS_TERMINATION_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        pass
    if _process_group_exists(process_group_id):
        try:
            os.killpg(process_group_id, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.returncode is None:
        try:
            process.wait(timeout=PROCESS_TERMINATION_GRACE_SECONDS)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("scheduled process leader could not be reaped") from exc
    kill_deadline = time.monotonic() + PROCESS_TERMINATION_GRACE_SECONDS
    if not _wait_for_process_group_exit(process_group_id, kill_deadline):
        raise RuntimeError("scheduled process group could not be fully terminated")


def _stream_bounded_output(
    process: subprocess.Popen[bytes],
    log_descriptor: int,
    *,
    run_id: str,
    timeout_seconds: float,
    output_log_limit: int,
) -> tuple[int | None, bool, bool, bool]:
    """Stream one child pipe into the capped log under a monotonic deadline."""

    timed_out = False
    exceeded = False
    lingering = False
    selector = selectors.DefaultSelector()
    stdout_stream = process.stdout
    try:
        if stdout_stream is None:
            raise RuntimeError("scheduled job output pipe was not created")
        if (
            not isinstance(timeout_seconds, (int, float))
            or isinstance(timeout_seconds, bool)
            or not math.isfinite(float(timeout_seconds))
            or not 0 < float(timeout_seconds) <= automation_orders_lint.MAX_TIMEOUT_MINUTES * 60
        ):
            raise ValueError(
                "scheduled timeout must be finite, positive, and no greater than "
                f"{automation_orders_lint.MAX_TIMEOUT_MINUTES * 60} seconds"
            )
        if (
            not isinstance(output_log_limit, int)
            or isinstance(output_log_limit, bool)
            or output_log_limit <= 0
        ):
            raise ValueError("scheduled output log limit must be a positive integer")
        deadline = time.monotonic() + float(timeout_seconds)
        selector.register(stdout_stream, selectors.EVENT_READ)
        while selector.get_map():
            remaining_seconds = deadline - time.monotonic()
            if remaining_seconds <= 0:
                timed_out = True
                _terminate_process_group(process)
                break
            events = selector.select(timeout=remaining_seconds)
            if not events:
                timed_out = True
                _terminate_process_group(process)
                break
            for key, _mask in events:
                chunk = os.read(key.fd, 64 * 1024)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                if not _write_output_record(
                    log_descriptor,
                    run_id,
                    chunk,
                    output_log_limit,
                ):
                    exceeded = True
                    _terminate_process_group(process)
                    break
            if exceeded:
                break

        if not timed_out and not exceeded and process.poll() is None:
            remaining_seconds = deadline - time.monotonic()
            try:
                process.wait(timeout=max(remaining_seconds, 0.0))
            except subprocess.TimeoutExpired:
                timed_out = True
                _terminate_process_group(process)
        if not timed_out and not exceeded and _process_group_exists(process.pid):
            lingering = True
            _terminate_process_group(process)
    except BaseException as primary:
        resource_cleanup.cleanup_actions(
            [("scheduled process group", lambda: _terminate_process_group(process))],
            primary=primary,
        )
        raise
    finally:
        def clear_selector_registrations() -> None:
            resource_cleanup.cleanup_actions(
                [
                    (
                        "scheduled output selector registration",
                        lambda file_object=key.fileobj: selector.unregister(file_object),
                    )
                    for key in list(selector.get_map().values())
                ]
            )

        actions: list[tuple[str, Callable[[], object]]] = [
            (
                "scheduled output selector registrations",
                clear_selector_registrations,
            )
        ]
        actions.append(("scheduled output selector", selector.close))
        if stdout_stream is not None:
            actions.append(("scheduled stdout stream", stdout_stream.close))
        resource_cleanup.cleanup_actions(actions, primary=sys.exception())
    return process.returncode, timed_out, exceeded, lingering


def run_job(
    project_root: Path,
    manifest_path: Path,
    job_id: str,
    expected_job_sha256: str,
) -> int:
    _verify_local_runtime_module_origins()
    normalized_root = automation_orders_lint.normalize_project_root(project_root)
    manifest_relative = automation_orders_lint.manifest_relative_to_project(
        normalized_root,
        manifest_path,
    )
    owned = resource_cleanup.OwnedFileDescriptors()
    project_descriptor = owned.adopt(
        open_absolute_directory(
            normalized_root,
            description="selected project root",
        ),
        "selected project-root descriptor",
    )
    try:
        framework_descriptor = owned.adopt(
            open_absolute_directory(
                FRAMEWORK_ROOT,
                description="selected framework root",
            ),
            "selected framework-root descriptor",
        )
        raw = read_project_regular_file_bytes(
            project_descriptor,
            manifest_relative,
            description="automation manifest",
        )
        data = safe_paths.loads_json_no_duplicates(raw.decode("utf-8"))
        job = _selected_job_from_data(
            data,
            job_id,
        )
        cwd_value = job.get("cwd")
        if not isinstance(cwd_value, str):
            raise ValueError(f"automation job {job_id!r} cwd must be a string")
        cwd_descriptor = owned.adopt(
            open_project_relative_directory(
                project_descriptor,
                cwd_value,
                description="job cwd",
            ),
            "job-cwd descriptor",
        )
        _validate_descriptor_bound_data(data, normalized_root, manifest_path)
        _verify_job_authority(
            job,
            normalized_root,
            manifest_relative,
            project_descriptor,
            cwd_descriptor,
            framework_descriptor,
            expected_job_sha256,
        )
        if job.get("enabled") is not True:
            raise ValueError(f"automation job {job_id!r} is not enabled")
        artifacts = job.get("scheduler_artifacts")
        if not isinstance(artifacts, dict):
            raise ValueError("scheduler_artifacts must be an object")
        root_parts = _relative_parts(str(artifacts["root"]), description="scheduler_artifacts.root")
        artifact_descriptor = owned.adopt(
            open_or_create_private_directory(
                cwd_descriptor,
                root_parts,
                description="scheduler_artifacts.root",
            ),
            "scheduler-artifacts root descriptor",
        )
        log_descriptor = owned.adopt(
            open_private_regular_file(
                artifact_descriptor,
                str(artifacts["log_file"]),
                description="scheduler log",
                append=True,
            ),
            "scheduler-log descriptor",
        )
        max_log_bytes = artifacts.get("max_log_bytes")
        if not isinstance(max_log_bytes, int) or isinstance(max_log_bytes, bool):
            raise ValueError("scheduler_artifacts.max_log_bytes must be an integer")
        output_log_limit = max_log_bytes - LOG_CONTROL_RESERVE_BYTES
        if output_log_limit <= 0:
            raise ValueError("scheduler_artifacts.max_log_bytes is too small")
        run_id = secrets.token_hex(16)

        if job.get("concurrency") == "forbid":
            lock_value = artifacts.get("lock_file")
            if not isinstance(lock_value, str):
                raise ValueError("forbidden-overlap job requires scheduler_artifacts.lock_file")
            lock_descriptor = owned.adopt(
                open_private_regular_file(
                    artifact_descriptor,
                    lock_value,
                    description="scheduler lock",
                    append=False,
                ),
                "scheduler-lock descriptor",
            )
            try:
                import fcntl

                fcntl.flock(lock_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                if not _write_control_record(
                    log_descriptor,
                    run_id,
                    "overlap-skip",
                    f"job {job_id} skipped because its scheduler lock is held",
                    max_log_bytes,
                ):
                    print(
                        f"ERROR: scheduler log for {job_id} reached its byte limit",
                        file=sys.stderr,
                    )
                return 1
            except ImportError as exc:
                raise RuntimeError("confined cron execution requires POSIX advisory locking") from exc

        if not _write_control_record(
            log_descriptor,
            run_id,
            "start",
            f"job {job_id} started",
            max_log_bytes,
        ):
            raise ValueError(
                f"scheduler log for {job_id!r} reached max_log_bytes; "
                "archive or truncate it before the next run"
            )

        saved_cwd_owner = resource_cleanup.OwnedFileDescriptors()
        saved_cwd = saved_cwd_owner.adopt(
            os.open(".", _directory_flags()),
            "scheduler saved-cwd descriptor",
        )
        process: subprocess.Popen[bytes] | None = None
        try:
            os.fchdir(cwd_descriptor)
            process = subprocess.Popen(
                ["/bin/sh", "-c", str(job["command"])],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        finally:
            def restore_scheduler_cwd() -> None:
                try:
                    os.fchdir(saved_cwd)
                except BaseException as restore_failure:
                    started_process = process
                    if started_process is not None:
                        resource_cleanup.cleanup_actions(
                            [
                                (
                                    "scheduled process group",
                                    lambda: _terminate_process_group(started_process),
                                )
                            ],
                            primary=restore_failure,
                        )
                    raise

            resource_cleanup.cleanup_actions(
                [
                    ("scheduler working directory", restore_scheduler_cwd),
                    (
                        "scheduler saved-cwd descriptor",
                        lambda: saved_cwd_owner.cleanup(),
                    ),
                ],
                primary=sys.exception(),
            )
        if process is None:
            raise RuntimeError("scheduled process did not start")

        returncode, timed_out, exceeded, lingering = _stream_bounded_output(
            process,
            log_descriptor,
            run_id=run_id,
            timeout_seconds=int(job["timeout_minutes"]) * 60,
            output_log_limit=output_log_limit,
        )
        if timed_out:
            _write_control_record(
                log_descriptor,
                run_id,
                "timeout",
                f"job {job_id} exceeded its declared timeout",
                max_log_bytes,
            )
            return 124
        if exceeded:
            _write_control_record(
                log_descriptor,
                run_id,
                "output-limit",
                f"job {job_id} exceeded scheduler_artifacts.max_log_bytes",
                max_log_bytes,
            )
            return LOG_LIMIT_EXIT
        if lingering:
            _write_control_record(
                log_descriptor,
                run_id,
                "background-process",
                f"job {job_id} left a background process; its process group was terminated",
                max_log_bytes,
            )
            return LINGERING_PROCESS_EXIT
        if not _write_control_record(
            log_descriptor,
            run_id,
            "exit",
            f"job {job_id} exited with status {returncode}",
            max_log_bytes,
        ):
            return LOG_LIMIT_EXIT
        return returncode if returncode is not None else 1
    finally:
        owned.cleanup(primary=sys.exception())


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run one validated cron job with descriptor-confined scheduler artifacts.",
        allow_abbrev=False,
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        required=True,
        help="Project root that owns the automation order and bounded job inputs.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        required=True,
        help="Validated cron automation-order manifest within the project root.",
    )
    parser.add_argument(
        "--job-id",
        required=True,
        help="Exact enabled cron job id to execute from the manifest.",
    )
    parser.add_argument(
        "--expected-job-sha256",
        required=True,
        help=(
            "Lowercase SHA-256 unkeyed drift seal emitted when the cron entry was "
            "rendered; changed job inputs are refused, but the digest is not "
            "authenticity or authority evidence."
        ),
    )
    args = parser.parse_args()
    try:
        _verify_python_cache_isolation()
        return run_job(
            args.project_root,
            args.manifest,
            args.job_id,
            args.expected_job_sha256,
        )
    except (OSError, UnicodeError, ValueError, RuntimeError) as exc:
        print(f"ERROR: scheduled job refused: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
