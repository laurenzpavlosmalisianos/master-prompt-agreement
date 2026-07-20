#!/usr/bin/env python3

"""Durable, append-only state for a resumable public release operation.

This module owns no Git, network, or credential behavior.  It records evidence
produced by those boundaries in a small owner-only ledger.  The initialized
event retains the controller-defined release request and binds its canonical
SHA-256 together with the controller source digest.

The filesystem protocol is intentionally POSIX-specific.  Every operation
takes an exclusive advisory lock, validates the complete ledger, and fails
closed on an unexpected directory entry or inode relationship.  An append is
committed by linking a fully synced fixed ``.next`` inode to its numbered final
name without replacement, syncing the directory, removing ``.next``, and
syncing the directory again.
"""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Iterator, NoReturn


SCHEMA_VERSION = 1
LOCK_NAME = ".lock"
OPERATION_LOCK_NAME = ".operation.lock"
NEXT_NAME = ".next"
STATE_DIRECTORY_MODE = 0o700
STATE_FILE_MODE = 0o600
MAX_EVENT_BYTES = 1024 * 1024
MAX_JSON_DEPTH = 32
PHASES = (
    "initialized",
    "export-verified",
    "staged-verified",
    "candidate-verified",
    "publication-bound",
    "push-observed",
    "readback-verified",
)

_EVENT_NAME_RE = re.compile(r"([0-9]{8})\.json")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_GIT_OID_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
_OPERATION_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_ZERO_SHA256 = "0" * 64
NO_CREDENTIAL_BOUNDARY_SHA256 = hashlib.sha256(
    b"mpa-public-release-no-credential-boundary-v1"
).hexdigest()
_DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
_READ_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_NONBLOCK", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
_LOCK_FLAGS = (
    os.O_RDWR
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_NONBLOCK", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
_CREATE_FLAGS = (
    os.O_WRONLY
    | os.O_CREAT
    | os.O_EXCL
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)

_EVENT_FIELDS = frozenset(
    {
        "schema_version",
        "operation_id",
        "sequence",
        "phase",
        "previous_event_sha256",
        "payload",
    }
)
_PAYLOAD_FIELDS = {
    "initialized": frozenset(
        {"request", "request_sha256", "controller_sha256"}
    ),
    "export-verified": frozenset(
        {
            "export_marker_sha256",
            "git_sha256",
            "python_sha256",
            "uv_sha256",
        }
    ),
    "staged-verified": frozenset(
        {"expected_parent", "staged_receipt", "commit_spec_sha256"}
    ),
    "candidate-verified": frozenset(
        {"candidate_commit", "committed_receipt", "staged_receipt_sha256"}
    ),
    "publication-bound": frozenset(
        {
            "candidate_commit",
            "expected_parent",
            "refspec_sha256",
            "credential_boundary_sha256",
            "mode",
        }
    ),
    "push-observed": frozenset({"candidate_commit"}),
    "readback-verified": frozenset({"candidate_commit"}),
}


class ReleaseStateError(ValueError):
    """The release-state directory or requested transition is invalid."""


@dataclass(frozen=True)
class ReleaseEvent:
    """One validated event and the SHA-256 of its canonical file bytes."""

    schema_version: int
    operation_id: str
    sequence: int
    phase: str
    previous_event_sha256: str
    payload: dict[str, object]
    sha256: str


@dataclass(frozen=True)
class ReleaseStateSnapshot:
    """A complete validated view of one release ledger."""

    state_directory: Path
    operation_id: str
    request_sha256: str
    request: dict[str, object]
    controller_sha256: str
    events: tuple[ReleaseEvent, ...]

    @property
    def sequence(self) -> int:
        return self.events[-1].sequence

    @property
    def phase(self) -> str:
        return self.events[-1].phase

    @property
    def latest_event_sha256(self) -> str:
        return self.events[-1].sha256


def _fail(message: str) -> NoReturn:
    raise ReleaseStateError(message)


def _require_platform() -> None:
    required_flags = ("O_DIRECTORY", "O_NOFOLLOW")
    missing = [name for name in required_flags if not getattr(os, name, 0)]
    if missing:
        _fail(
            "public release state requires POSIX filesystem flags: "
            + ", ".join(missing)
        )
    if not hasattr(os, "geteuid"):
        _fail("public release state requires effective-user ownership checks")
    try:
        import fcntl as _fcntl  # noqa: F401
    except ImportError as exc:
        raise ReleaseStateError(
            "public release state requires POSIX advisory file locking"
        ) from exc


def _acquire_exclusive_lock(descriptor: int, *, nonblocking: bool) -> None:
    try:
        import fcntl
    except ImportError as exc:
        raise ReleaseStateError(
            "public release state requires POSIX advisory file locking"
        ) from exc
    flags = fcntl.LOCK_EX | (fcntl.LOCK_NB if nonblocking else 0)
    fcntl.flock(descriptor, flags)


def _release_lock(descriptor: int) -> None:
    try:
        import fcntl
    except ImportError as exc:
        raise ReleaseStateError(
            "public release state requires POSIX advisory file locking"
        ) from exc
    fcntl.flock(descriptor, fcntl.LOCK_UN)


def _state_path(value: Path | str) -> Path:
    path = Path(value)
    if not path.is_absolute() or path == Path(path.anchor):
        _fail("release state directory must be a non-root absolute path")
    if any(part in {"", ".", ".."} for part in path.parts[1:]):
        _fail("release state directory must be one canonical absolute path")
    return path


def _require_operation_id(value: object) -> str:
    if not isinstance(value, str) or _OPERATION_ID_RE.fullmatch(value) is None:
        _fail(
            "operation ID must be 1-128 ASCII letters, digits, dots, underscores, "
            "or hyphens and must begin with a letter or digit"
        )
    return value


def _require_sha256(value: object, *, description: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        _fail(f"{description} must be one lowercase SHA-256 digest")
    return value


def _require_git_oid(value: object, *, description: str) -> str:
    if not isinstance(value, str) or _GIT_OID_RE.fullmatch(value) is None:
        _fail(f"{description} must be one lowercase full Git object ID")
    return value


def _validate_json_value(value: object, *, depth: int = 0) -> None:
    if depth > MAX_JSON_DEPTH:
        _fail("release event JSON exceeds the maximum nesting depth")
    if value is None or type(value) in {bool, int, str}:
        if isinstance(value, str):
            try:
                value.encode("utf-8", errors="strict")
            except UnicodeEncodeError as exc:
                raise ReleaseStateError(
                    "release event JSON contains an invalid Unicode surrogate"
                ) from exc
        return
    if type(value) is list:
        for item in value:
            _validate_json_value(item, depth=depth + 1)
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                _fail("release event JSON object keys must be strings")
            _validate_json_value(key, depth=depth + 1)
            _validate_json_value(item, depth=depth + 1)
        return
    _fail(
        "release event JSON permits only null, booleans, integers, strings, "
        "arrays, and objects"
    )


def _canonical_json_bytes(value: object) -> bytes:
    _validate_json_value(value)
    try:
        encoded = (
            json.dumps(
                value,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8", errors="strict")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ReleaseStateError(f"release event cannot be encoded canonically: {exc}") from exc
    if len(encoded) > MAX_EVENT_BYTES:
        _fail(f"release event exceeds the {MAX_EVENT_BYTES}-byte limit")
    return encoded


def canonical_json_sha256(value: object) -> str:
    """Return the ledger's canonical SHA-256 for one JSON value."""

    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            _fail(f"release event JSON contains duplicate key {key!r}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> NoReturn:
    _fail(f"release event JSON contains unsupported constant {value!r}")


def _decode_canonical_json(raw: bytes, *, description: str) -> dict[str, object]:
    if not raw or len(raw) > MAX_EVENT_BYTES:
        _fail(f"{description} must contain 1-{MAX_EVENT_BYTES} bytes")
    try:
        text = raw.decode("utf-8", errors="strict")
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseStateError(f"{description} is not valid canonical JSON: {exc}") from exc
    if type(value) is not dict:
        _fail(f"{description} must contain one JSON object")
    if _canonical_json_bytes(value) != raw:
        _fail(f"{description} is not encoded as canonical ledger JSON")
    return value


def _require_owned_mode(
    metadata: os.stat_result,
    *,
    description: str,
    mode: int,
    regular: bool,
    links: int | None,
) -> None:
    expected_kind = stat.S_ISREG if regular else stat.S_ISDIR
    if not expected_kind(metadata.st_mode):
        _fail(f"{description} has the wrong filesystem type")
    if metadata.st_uid != os.geteuid():
        _fail(f"{description} must be owned by the effective user")
    observed_mode = stat.S_IMODE(metadata.st_mode)
    if observed_mode != mode:
        _fail(
            f"{description} mode must equal {mode:#o}; observed {observed_mode:#o}"
        )
    if links is not None and metadata.st_nlink != links:
        _fail(
            f"{description} link count must equal {links}; "
            f"observed {metadata.st_nlink}"
        )


def _identity(metadata: os.stat_result) -> tuple[int, int]:
    return metadata.st_dev, metadata.st_ino


def _lstat_at(directory_descriptor: int, name: str) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=directory_descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return None


def _require_named_identity(
    directory_descriptor: int,
    name: str,
    descriptor: int,
    *,
    description: str,
) -> os.stat_result:
    opened = os.fstat(descriptor)
    current = _lstat_at(directory_descriptor, name)
    if current is None or _identity(current) != _identity(opened):
        _fail(f"{description} was removed or replaced")
    return opened


def _read_bounded(descriptor: int, *, description: str) -> bytes:
    chunks: list[bytes] = []
    remaining = MAX_EVENT_BYTES + 1
    while remaining:
        chunk = os.read(descriptor, min(64 * 1024, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    raw = b"".join(chunks)
    if len(raw) > MAX_EVENT_BYTES:
        _fail(f"{description} exceeds the {MAX_EVENT_BYTES}-byte limit")
    return raw


def _write_all(descriptor: int, raw: bytes) -> None:
    offset = 0
    while offset < len(raw):
        written = os.write(descriptor, raw[offset:])
        if written <= 0:
            _fail("release event write made no progress")
        offset += written


def _event_name(sequence: int) -> str:
    return f"{sequence:08d}.json"


def _directory_names(directory_descriptor: int) -> tuple[str, ...]:
    with os.scandir(directory_descriptor) as entries:
        return tuple(sorted(entry.name for entry in entries))


@contextmanager
def _locked_state(path: Path) -> Iterator[int]:
    directory_descriptor = os.open(path, _DIRECTORY_FLAGS)
    lock_descriptor: int | None = None
    primary: BaseException | None = None
    try:
        _require_owned_mode(
            os.fstat(directory_descriptor),
            description="release state directory",
            mode=STATE_DIRECTORY_MODE,
            regular=False,
            links=None,
        )
        lock_descriptor = os.open(LOCK_NAME, _LOCK_FLAGS, dir_fd=directory_descriptor)
        lock_metadata = os.fstat(lock_descriptor)
        _require_owned_mode(
            lock_metadata,
            description="release state lock",
            mode=STATE_FILE_MODE,
            regular=True,
            links=1,
        )
        if lock_metadata.st_size != 0:
            _fail("release state lock must remain empty")
        try:
            _acquire_exclusive_lock(lock_descriptor, nonblocking=True)
        except BlockingIOError as exc:
            raise ReleaseStateError(
                "another process currently owns the release state lock"
            ) from exc
        _require_named_identity(
            directory_descriptor,
            LOCK_NAME,
            lock_descriptor,
            description="release state lock",
        )
        yield directory_descriptor
        _require_named_identity(
            directory_descriptor,
            LOCK_NAME,
            lock_descriptor,
            description="release state lock",
        )
    except BaseException as exc:
        primary = exc
        raise
    finally:
        cleanup_error: BaseException | None = None
        if lock_descriptor is not None:
            try:
                _release_lock(lock_descriptor)
            except BaseException as exc:
                cleanup_error = exc
            try:
                os.close(lock_descriptor)
            except BaseException as exc:
                cleanup_error = cleanup_error or exc
        try:
            os.close(directory_descriptor)
        except BaseException as exc:
            cleanup_error = cleanup_error or exc
        if primary is None and cleanup_error is not None:
            raise cleanup_error


@contextmanager
def operation_lease(state_directory: Path | str) -> Iterator[None]:
    """Hold the nonblocking process-lifetime lease for one mutating command."""

    _require_platform()
    path = _state_path(state_directory)
    directory_descriptor: int | None = None
    lease_descriptor: int | None = None
    primary: BaseException | None = None
    try:
        directory_descriptor = os.open(path, _DIRECTORY_FLAGS)
        _require_owned_mode(
            os.fstat(directory_descriptor),
            description="release state directory",
            mode=STATE_DIRECTORY_MODE,
            regular=False,
            links=None,
        )
        lease_descriptor = os.open(
            OPERATION_LOCK_NAME,
            _LOCK_FLAGS,
            dir_fd=directory_descriptor,
        )
        metadata = os.fstat(lease_descriptor)
        _require_owned_mode(
            metadata,
            description="release operation lock",
            mode=STATE_FILE_MODE,
            regular=True,
            links=1,
        )
        if metadata.st_size != 0:
            _fail("release operation lock must remain empty")
        try:
            _acquire_exclusive_lock(lease_descriptor, nonblocking=True)
        except BlockingIOError as exc:
            raise ReleaseStateError(
                "another process currently owns the release operation lease"
            ) from exc
        _require_named_identity(
            directory_descriptor,
            OPERATION_LOCK_NAME,
            lease_descriptor,
            description="release operation lock",
        )
        yield
        _require_named_identity(
            directory_descriptor,
            OPERATION_LOCK_NAME,
            lease_descriptor,
            description="release operation lock",
        )
    except BaseException as exc:
        primary = exc
        raise
    finally:
        cleanup_error: BaseException | None = None
        if lease_descriptor is not None:
            try:
                _release_lock(lease_descriptor)
            except BaseException as exc:
                cleanup_error = exc
            try:
                os.close(lease_descriptor)
            except BaseException as exc:
                cleanup_error = cleanup_error or exc
        if directory_descriptor is not None:
            try:
                os.close(directory_descriptor)
            except BaseException as exc:
                cleanup_error = cleanup_error or exc
        if primary is None and cleanup_error is not None:
            raise cleanup_error


def _validate_payload(phase: str, payload: object) -> dict[str, object]:
    if type(payload) is not dict:
        _fail(f"{phase} payload must be one JSON object")
    expected = _PAYLOAD_FIELDS[phase]
    observed = frozenset(payload)
    if observed != expected:
        unknown = sorted(observed - expected)
        missing = sorted(expected - observed)
        details: list[str] = []
        if unknown:
            details.append("unknown fields: " + ", ".join(unknown))
        if missing:
            details.append("missing fields: " + ", ".join(missing))
        _fail(f"{phase} payload schema mismatch ({'; '.join(details)})")

    result = dict(payload)
    if phase == "initialized":
        _require_sha256(result["request_sha256"], description="request_sha256")
        _require_sha256(
            result["controller_sha256"], description="controller_sha256"
        )
        if type(result["request"]) is not dict:
            _fail("initialized request must be one JSON object")
        if canonical_json_sha256(result["request"]) != result["request_sha256"]:
            _fail("initialized request does not match request_sha256")
    elif phase == "export-verified":
        for field in expected:
            _require_sha256(result[field], description=field)
    elif phase == "staged-verified":
        _require_git_oid(result["expected_parent"], description="expected_parent")
        _require_sha256(
            result["commit_spec_sha256"], description="commit_spec_sha256"
        )
        if type(result["staged_receipt"]) is not dict:
            _fail("staged_receipt must be one JSON object")
    elif phase == "candidate-verified":
        _require_git_oid(result["candidate_commit"], description="candidate_commit")
        _require_sha256(
            result["staged_receipt_sha256"],
            description="staged_receipt_sha256",
        )
        if type(result["committed_receipt"]) is not dict:
            _fail("committed_receipt must be one JSON object")
    elif phase == "publication-bound":
        _require_git_oid(result["candidate_commit"], description="candidate_commit")
        _require_git_oid(result["expected_parent"], description="expected_parent")
        _require_sha256(result["refspec_sha256"], description="refspec_sha256")
        _require_sha256(
            result["credential_boundary_sha256"],
            description="credential_boundary_sha256",
        )
        if result["mode"] not in {
            "controller-push",
            "adopt-observed-candidate",
        }:
            _fail("publication-bound mode is unsupported")
        if (
            result["mode"] == "adopt-observed-candidate"
            and result["credential_boundary_sha256"]
            != NO_CREDENTIAL_BOUNDARY_SHA256
        ):
            _fail(
                "observed-candidate publication binding requires the "
                "no-credential sentinel"
            )
        if (
            result["mode"] == "controller-push"
            and result["credential_boundary_sha256"]
            == NO_CREDENTIAL_BOUNDARY_SHA256
        ):
            _fail("controller-push publication binding requires a credential digest")
    else:
        _require_git_oid(result["candidate_commit"], description="candidate_commit")
    _validate_json_value(result)
    return result


def _validate_event_object(
    value: dict[str, object],
    *,
    expected_sequence: int,
    expected_phase: str,
    expected_operation_id: str,
    expected_previous_sha256: str,
) -> tuple[dict[str, object], dict[str, object]]:
    observed_fields = frozenset(value)
    if observed_fields != _EVENT_FIELDS:
        unknown = sorted(observed_fields - _EVENT_FIELDS)
        missing = sorted(_EVENT_FIELDS - observed_fields)
        details: list[str] = []
        if unknown:
            details.append("unknown fields: " + ", ".join(unknown))
        if missing:
            details.append("missing fields: " + ", ".join(missing))
        _fail("release event schema mismatch (" + "; ".join(details) + ")")
    if type(value["schema_version"]) is not int or value["schema_version"] != SCHEMA_VERSION:
        _fail(f"release event schema_version must equal {SCHEMA_VERSION}")
    if type(value["sequence"]) is not int or value["sequence"] != expected_sequence:
        _fail(f"release event sequence must equal {expected_sequence}")
    if value["phase"] != expected_phase:
        _fail(f"release event {expected_sequence} phase must equal {expected_phase!r}")
    if value["operation_id"] != expected_operation_id:
        _fail("release event operation ID does not match the selected operation")
    previous = _require_sha256(
        value["previous_event_sha256"], description="previous_event_sha256"
    )
    if previous != expected_previous_sha256:
        _fail("release event previous-event digest breaks ledger continuity")
    payload = _validate_payload(expected_phase, value["payload"])
    return value, payload


def _open_event(
    directory_descriptor: int,
    name: str,
    *,
    allow_transient_link: bool,
) -> tuple[bytes, os.stat_result]:
    descriptor = os.open(name, _READ_FLAGS, dir_fd=directory_descriptor)
    try:
        before = os.fstat(descriptor)
        _require_owned_mode(
            before,
            description=f"release event {name}",
            mode=STATE_FILE_MODE,
            regular=True,
            links=2 if allow_transient_link else 1,
        )
        _require_named_identity(
            directory_descriptor,
            name,
            descriptor,
            description=f"release event {name}",
        )
        raw = _read_bounded(descriptor, description=f"release event {name}")
        after = os.fstat(descriptor)
        if (
            _identity(before) != _identity(after)
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or after.st_size != len(raw)
        ):
            _fail(f"release event {name} changed while it was read")
        _require_named_identity(
            directory_descriptor,
            name,
            descriptor,
            description=f"release event {name}",
        )
        return raw, after
    finally:
        os.close(descriptor)


def _validate_empty_lock_file(
    directory_descriptor: int,
    name: str,
    *,
    description: str,
) -> None:
    descriptor = os.open(name, _READ_FLAGS, dir_fd=directory_descriptor)
    try:
        metadata = os.fstat(descriptor)
        _require_owned_mode(
            metadata,
            description=description,
            mode=STATE_FILE_MODE,
            regular=True,
            links=1,
        )
        if metadata.st_size != 0:
            _fail(f"{description} must remain empty")
        _require_named_identity(
            directory_descriptor,
            name,
            descriptor,
            description=description,
        )
    finally:
        os.close(descriptor)


def _recover_next(
    directory_descriptor: int,
    *,
    event_names: tuple[str, ...],
    final_metadata: dict[str, os.stat_result],
) -> None:
    next_metadata = _lstat_at(directory_descriptor, NEXT_NAME)
    if next_metadata is None:
        return
    descriptor = os.open(NEXT_NAME, _READ_FLAGS, dir_fd=directory_descriptor)
    try:
        opened = os.fstat(descriptor)
        _require_owned_mode(
            opened,
            description="release event staging file",
            mode=STATE_FILE_MODE,
            regular=True,
            links=None,
        )
        _require_named_identity(
            directory_descriptor,
            NEXT_NAME,
            descriptor,
            description="release event staging file",
        )
        if opened.st_nlink == 1:
            pass
        elif opened.st_nlink == 2 and event_names:
            final = final_metadata[event_names[-1]]
            if _identity(opened) != _identity(final):
                _fail(
                    "release event staging hard link does not identify the final event"
                )
        else:
            _fail("release event staging file has an invalid hard-link relationship")
        current = _lstat_at(directory_descriptor, NEXT_NAME)
        if current is None or _identity(current) != _identity(opened):
            _fail("release event staging file was removed or replaced")
        os.unlink(NEXT_NAME, dir_fd=directory_descriptor)
        os.fsync(directory_descriptor)
        if os.fstat(descriptor).st_nlink != opened.st_nlink - 1:
            _fail("release event staging unlink produced an invalid link count")
    finally:
        os.close(descriptor)


def _inspect_locked(
    directory_descriptor: int,
    state_directory: Path,
    *,
    operation_id: str | None,
    request_sha256: str | None,
    recover: bool,
) -> ReleaseStateSnapshot:
    names = _directory_names(directory_descriptor)
    unknown: list[str] = []
    event_names: list[str] = []
    for name in names:
        if name in {LOCK_NAME, OPERATION_LOCK_NAME, NEXT_NAME}:
            continue
        match = _EVENT_NAME_RE.fullmatch(name)
        if match is None:
            unknown.append(name)
        else:
            event_names.append(name)
    if LOCK_NAME not in names:
        _fail("release state lock is absent")
    if OPERATION_LOCK_NAME not in names:
        _fail("release operation lock is absent")
    _validate_empty_lock_file(
        directory_descriptor,
        OPERATION_LOCK_NAME,
        description="release operation lock",
    )
    if unknown:
        _fail("release state directory contains unknown entries: " + ", ".join(unknown))
    if not event_names:
        _fail("release state ledger has no initialized event")
    if len(event_names) > len(PHASES):
        _fail("release state ledger contains more events than phases")
    expected_names = tuple(_event_name(index) for index in range(1, len(event_names) + 1))
    observed_names = tuple(sorted(event_names))
    if observed_names != expected_names:
        _fail("release state ledger contains an event gap or non-monotonic name")

    next_metadata = _lstat_at(directory_descriptor, NEXT_NAME)
    transient_final = observed_names[-1] if next_metadata is not None else None
    final_metadata: dict[str, os.stat_result] = {}
    events: list[ReleaseEvent] = []
    previous_sha256 = _ZERO_SHA256
    selected_operation_id = operation_id
    for sequence, name in enumerate(observed_names, start=1):
        allow_transient = False
        if name == transient_final and next_metadata is not None:
            allow_transient = (
                next_metadata.st_nlink == 2
                and _identity(next_metadata)
                == _identity(_lstat_at(directory_descriptor, name) or next_metadata)
            )
        raw, metadata = _open_event(
            directory_descriptor,
            name,
            allow_transient_link=allow_transient,
        )
        final_metadata[name] = metadata
        value = _decode_canonical_json(raw, description=f"release event {name}")
        expected_phase = PHASES[sequence - 1]
        if sequence == 1:
            observed_operation_id = _require_operation_id(value.get("operation_id"))
            if (
                selected_operation_id is not None
                and observed_operation_id != selected_operation_id
            ):
                _fail("release event operation ID does not match the selected operation")
            selected_operation_id = observed_operation_id
        if selected_operation_id is None:
            _fail("release ledger did not establish an operation ID")
        _, payload = _validate_event_object(
            value,
            expected_sequence=sequence,
            expected_phase=expected_phase,
            expected_operation_id=selected_operation_id,
            expected_previous_sha256=previous_sha256,
        )
        event_sha256 = hashlib.sha256(raw).hexdigest()
        events.append(
            ReleaseEvent(
                schema_version=SCHEMA_VERSION,
                operation_id=selected_operation_id,
                sequence=sequence,
                phase=expected_phase,
                previous_event_sha256=previous_sha256,
                payload=payload,
                sha256=event_sha256,
            )
        )
        previous_sha256 = event_sha256

    if selected_operation_id is None:
        _fail("release ledger did not establish an operation ID")
    initialized_request_sha256 = _require_sha256(
        events[0].payload["request_sha256"], description="initialized request_sha256"
    )
    if (
        request_sha256 is not None
        and initialized_request_sha256 != request_sha256
    ):
        _fail("release request digest does not match the initialized ledger")
    initialized_request = events[0].payload["request"]
    if type(initialized_request) is not dict:
        _fail("initialized request must be one JSON object")
    controller_sha256 = _require_sha256(
        events[0].payload["controller_sha256"],
        description="initialized controller_sha256",
    )
    _validate_cross_event_continuity(events)

    if next_metadata is not None:
        if not recover:
            _fail("release state requires staging-file recovery")
        _recover_next(
            directory_descriptor,
            event_names=observed_names,
            final_metadata=final_metadata,
        )
        for name in observed_names:
            current = _lstat_at(directory_descriptor, name)
            if current is None or current.st_nlink != 1:
                _fail(f"release event {name} did not recover to one final link")
    return ReleaseStateSnapshot(
        state_directory=state_directory,
        operation_id=selected_operation_id,
        request_sha256=initialized_request_sha256,
        request=dict(initialized_request),
        controller_sha256=controller_sha256,
        events=tuple(events),
    )


def _validate_cross_event_continuity(events: list[ReleaseEvent]) -> None:
    by_phase = {event.phase: event for event in events}
    staged = by_phase.get("staged-verified")
    candidate = by_phase.get("candidate-verified")
    if staged is not None and candidate is not None:
        expected_receipt_sha256 = canonical_json_sha256(staged.payload["staged_receipt"])
        if candidate.payload["staged_receipt_sha256"] != expected_receipt_sha256:
            _fail("candidate event does not bind the staged receipt")
    publication = by_phase.get("publication-bound")
    if candidate is not None and publication is not None:
        if publication.payload["candidate_commit"] != candidate.payload["candidate_commit"]:
            _fail("publication binding candidate does not match the verified candidate")
        if (
            staged is None
            or publication.payload["expected_parent"]
            != staged.payload["expected_parent"]
        ):
            _fail("publication binding parent does not match the staged parent")
    push_observed = by_phase.get("push-observed")
    if candidate is not None and push_observed is not None:
        if push_observed.payload["candidate_commit"] != candidate.payload["candidate_commit"]:
            _fail("observed push candidate does not match the verified candidate")
    readback = by_phase.get("readback-verified")
    if candidate is not None and readback is not None:
        if readback.payload["candidate_commit"] != candidate.payload["candidate_commit"]:
            _fail("readback candidate does not match the verified candidate")


def _append_locked(
    directory_descriptor: int,
    *,
    operation_id: str,
    sequence: int,
    phase: str,
    previous_event_sha256: str,
    payload: dict[str, object],
) -> None:
    event = {
        "schema_version": SCHEMA_VERSION,
        "operation_id": operation_id,
        "sequence": sequence,
        "phase": phase,
        "previous_event_sha256": previous_event_sha256,
        "payload": payload,
    }
    raw = _canonical_json_bytes(event)
    final_name = _event_name(sequence)
    if _lstat_at(directory_descriptor, final_name) is not None:
        _fail(f"release event {final_name} already exists")

    descriptor = os.open(
        NEXT_NAME,
        _CREATE_FLAGS,
        STATE_FILE_MODE,
        dir_fd=directory_descriptor,
    )
    try:
        os.fchmod(descriptor, STATE_FILE_MODE)
        metadata = os.fstat(descriptor)
        _require_owned_mode(
            metadata,
            description="new release event staging file",
            mode=STATE_FILE_MODE,
            regular=True,
            links=1,
        )
        _write_all(descriptor, raw)
        os.fsync(descriptor)
        _require_named_identity(
            directory_descriptor,
            NEXT_NAME,
            descriptor,
            description="new release event staging file",
        )
        os.link(
            NEXT_NAME,
            final_name,
            src_dir_fd=directory_descriptor,
            dst_dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
        opened = os.fstat(descriptor)
        final = _lstat_at(directory_descriptor, final_name)
        staged = _lstat_at(directory_descriptor, NEXT_NAME)
        if (
            final is None
            or staged is None
            or opened.st_nlink != 2
            or final.st_nlink != 2
            or staged.st_nlink != 2
            or _identity(final) != _identity(opened)
            or _identity(staged) != _identity(opened)
        ):
            _fail("new release event hard-link installation failed identity checks")
        os.fsync(directory_descriptor)
        os.unlink(NEXT_NAME, dir_fd=directory_descriptor)
        os.fsync(directory_descriptor)
        final = _lstat_at(directory_descriptor, final_name)
        if final is None or _identity(final) != _identity(opened) or final.st_nlink != 1:
            _fail("new release event final inode failed post-commit checks")
    except BaseException:
        # Do not roll back a linked final: it is the durable append.  A retained
        # .next is recovered on the next locked operation.  Before the link,
        # leave .next in place for the same bounded recovery path.
        raise
    finally:
        os.close(descriptor)


def init_state(
    state_directory: Path | str,
    *,
    operation_id: str,
    request: Mapping[str, object],
    controller_sha256: str,
) -> ReleaseStateSnapshot:
    """Create a new ledger and append its initialized event.

    The destination must be absent.  The request must be a plain JSON object;
    its canonical value and digest are retained in the initialized event.
    """

    _require_platform()
    path = _state_path(state_directory)
    operation_id = _require_operation_id(operation_id)
    if type(request) is not dict:
        _fail("release request must be a plain dictionary")
    retained_request = dict(request)
    request_sha256 = canonical_json_sha256(retained_request)
    controller_sha256 = _require_sha256(
        controller_sha256, description="controller SHA-256"
    )
    initialized_payload = _validate_payload(
        "initialized",
        {
            "request": retained_request,
            "request_sha256": request_sha256,
            "controller_sha256": controller_sha256,
        },
    )
    _canonical_json_bytes(
        {
            "schema_version": SCHEMA_VERSION,
            "operation_id": operation_id,
            "sequence": 1,
            "phase": "initialized",
            "previous_event_sha256": _ZERO_SHA256,
            "payload": initialized_payload,
        }
    )

    parent_descriptor = os.open(path.parent, _DIRECTORY_FLAGS)
    directory_descriptor: int | None = None
    lock_descriptor: int | None = None
    operation_lock_descriptor: int | None = None
    try:
        os.mkdir(path.name, STATE_DIRECTORY_MODE, dir_fd=parent_descriptor)
        os.fsync(parent_descriptor)
        directory_descriptor = os.open(path.name, _DIRECTORY_FLAGS, dir_fd=parent_descriptor)
        os.fchmod(directory_descriptor, STATE_DIRECTORY_MODE)
        _require_owned_mode(
            os.fstat(directory_descriptor),
            description="new release state directory",
            mode=STATE_DIRECTORY_MODE,
            regular=False,
            links=None,
        )
        lock_descriptor = os.open(
            LOCK_NAME,
            _LOCK_FLAGS | os.O_CREAT | os.O_EXCL,
            STATE_FILE_MODE,
            dir_fd=directory_descriptor,
        )
        os.fchmod(lock_descriptor, STATE_FILE_MODE)
        os.fsync(lock_descriptor)
        os.fsync(directory_descriptor)
        _require_owned_mode(
            os.fstat(lock_descriptor),
            description="new release state lock",
            mode=STATE_FILE_MODE,
            regular=True,
            links=1,
        )
        operation_lock_descriptor = os.open(
            OPERATION_LOCK_NAME,
            _LOCK_FLAGS | os.O_CREAT | os.O_EXCL,
            STATE_FILE_MODE,
            dir_fd=directory_descriptor,
        )
        os.fchmod(operation_lock_descriptor, STATE_FILE_MODE)
        os.fsync(operation_lock_descriptor)
        os.fsync(directory_descriptor)
        _require_owned_mode(
            os.fstat(operation_lock_descriptor),
            description="new release operation lock",
            mode=STATE_FILE_MODE,
            regular=True,
            links=1,
        )
        _acquire_exclusive_lock(lock_descriptor, nonblocking=False)
        _append_locked(
            directory_descriptor,
            operation_id=operation_id,
            sequence=1,
            phase="initialized",
            previous_event_sha256=_ZERO_SHA256,
            payload=initialized_payload,
        )
    finally:
        if operation_lock_descriptor is not None:
            os.close(operation_lock_descriptor)
        if lock_descriptor is not None:
            try:
                _release_lock(lock_descriptor)
            finally:
                os.close(lock_descriptor)
        if directory_descriptor is not None:
            os.close(directory_descriptor)
        os.close(parent_descriptor)
    return inspect_state(
        path,
        operation_id=operation_id,
        request_sha256=request_sha256,
    )


def inspect_state(
    state_directory: Path | str,
    *,
    operation_id: str | None = None,
    request_sha256: str | None = None,
) -> ReleaseStateSnapshot:
    """Validate the complete ledger and recover only a safe ``.next`` residue."""

    _require_platform()
    path = _state_path(state_directory)
    if operation_id is not None:
        operation_id = _require_operation_id(operation_id)
    if request_sha256 is not None:
        request_sha256 = _require_sha256(
            request_sha256, description="request SHA-256"
        )
    try:
        with _locked_state(path) as directory_descriptor:
            return _inspect_locked(
                directory_descriptor,
                path,
                operation_id=operation_id,
                request_sha256=request_sha256,
                recover=True,
            )
    except OSError as exc:
        raise ReleaseStateError(f"release state inspection failed: {exc}") from exc


def append_event(
    state_directory: Path | str,
    *,
    operation_id: str,
    request_sha256: str,
    phase: str,
    payload: Mapping[str, object],
) -> ReleaseStateSnapshot:
    """Append the one valid next phase after validating all retained state."""

    _require_platform()
    path = _state_path(state_directory)
    operation_id = _require_operation_id(operation_id)
    request_sha256 = _require_sha256(request_sha256, description="request SHA-256")
    if phase not in PHASES:
        _fail("release phase is not recognized")
    if type(payload) is not dict:
        _fail("release phase payload must be a plain dictionary")
    validated_payload = _validate_payload(phase, dict(payload))
    try:
        with _locked_state(path) as directory_descriptor:
            snapshot = _inspect_locked(
                directory_descriptor,
                path,
                operation_id=operation_id,
                request_sha256=request_sha256,
                recover=True,
            )
            if snapshot.sequence >= len(PHASES):
                _fail("release ledger is already complete")
            expected_phase = PHASES[snapshot.sequence]
            if phase != expected_phase:
                _fail(f"next release phase must equal {expected_phase!r}")

            prospective = list(snapshot.events)
            prospective.append(
                ReleaseEvent(
                    schema_version=SCHEMA_VERSION,
                    operation_id=operation_id,
                    sequence=snapshot.sequence + 1,
                    phase=phase,
                    previous_event_sha256=snapshot.latest_event_sha256,
                    payload=validated_payload,
                    sha256="",
                )
            )
            _validate_cross_event_continuity(prospective)
            _append_locked(
                directory_descriptor,
                operation_id=operation_id,
                sequence=snapshot.sequence + 1,
                phase=phase,
                previous_event_sha256=snapshot.latest_event_sha256,
                payload=validated_payload,
            )
            return _inspect_locked(
                directory_descriptor,
                path,
                operation_id=operation_id,
                request_sha256=request_sha256,
                recover=True,
            )
    except OSError as exc:
        if exc.errno == errno.EEXIST:
            raise ReleaseStateError(
                "release event append found an existing staging or final file"
            ) from exc
        raise ReleaseStateError(f"release event append failed: {exc}") from exc
