#!/usr/bin/env python3

"""Bounded, argv-only POSIX subprocess execution with explicit cleanup.

Linux runs are scoped child subreapers.  The caller must be single-threaded,
must have no pre-existing direct children, and must use the default SIGCHLD
disposition.  Those preconditions let this module identify every child adopted
from the launched tree, terminate it through a pidfd, reap it, prove that no new
direct child remains, and then restore the prior subreaper state.

Other POSIX systems have only the process-group guarantee.  Commands used there
must be trusted not to call setsid(2), detach, close both captured streams while
continuing to run, or deliberately leave background descendants.  This module
does not claim hostile-subtree containment on those systems.
"""

from __future__ import annotations

import ctypes
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import errno
import math
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time

import resource_cleanup


HARD_MAX_TIMEOUT_SECONDS = 60.0 * 60.0
HARD_MAX_OUTPUT_BYTES = 64 * 1024 * 1024
HARD_MAX_TERMINATION_GRACE_SECONDS = 10.0
MAX_LINUX_PROC_ENTRIES = 262_144
_READ_CHUNK_BYTES = 64 * 1024
_CLEANUP_POLL_SECONDS = 0.01
_PR_SET_CHILD_SUBREAPER = 36
_PR_GET_CHILD_SUBREAPER = 37


class BoundedSubprocessError(RuntimeError):
    """Base error for the shared bounded-subprocess contract."""


class BoundedSubprocessPreconditionError(BoundedSubprocessError):
    """Raised before spawn when safe ownership cannot be established."""


class BoundedSubprocessStartError(BoundedSubprocessError):
    """Raised when the validated child cannot be started."""


class BoundedSubprocessCleanupError(BoundedSubprocessError):
    """Raised when the leader or an adopted descendant cannot be cleaned up."""


@dataclass(frozen=True)
class BoundedProcessResult:
    """Captured bounded-process result; stdout and stderr remain separate."""

    args: tuple[str, ...]
    returncode: int
    stdout: bytes
    stderr: bytes
    timed_out: bool
    output_exceeded: bool


@dataclass(frozen=True)
class _LinuxProcessRecord:
    pid: int
    parent_pid: int
    process_group_id: int
    session_id: int
    start_time_ticks: int

    @property
    def identity(self) -> tuple[int, int]:
        return (self.pid, self.start_time_ticks)


def _is_linux() -> bool:
    return sys.platform.startswith("linux")


def _validate_positive_finite_number(
    value: object,
    *,
    label: str,
    maximum: float,
) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{label} must be finite, positive, and at most {maximum:g}")
    try:
        normalized = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise ValueError(
            f"{label} must be finite, positive, and at most {maximum:g}"
        ) from exc
    if not math.isfinite(normalized) or normalized <= 0 or normalized > maximum:
        raise ValueError(f"{label} must be finite, positive, and at most {maximum:g}")
    return normalized


def _validate_positive_integer(
    value: object,
    *,
    label: str,
    maximum: int,
) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value <= 0
        or value > maximum
    ):
        raise ValueError(f"{label} must be an integer from 1 through {maximum}")
    return value


def _validated_command(args: Sequence[str]) -> tuple[str, ...]:
    if not isinstance(args, Sequence) or isinstance(args, (str, bytes)):
        raise ValueError("bounded subprocess command must be an argv sequence")
    command = tuple(args)
    if not command:
        raise ValueError("bounded subprocess command must not be empty")
    for index, argument in enumerate(command):
        if not isinstance(argument, str):
            raise ValueError(f"bounded subprocess argv[{index}] must be a string")
        if not argument:
            raise ValueError(f"bounded subprocess argv[{index}] must not be empty")
        if "\0" in argument:
            raise ValueError(f"bounded subprocess argv[{index}] must not contain NUL")
    return command


def _validated_environment(
    env: Mapping[str, str] | None,
) -> dict[str, str] | None:
    if env is None:
        return None
    if not isinstance(env, Mapping):
        raise ValueError("bounded subprocess environment must be a string mapping")
    validated: dict[str, str] = {}
    for key, value in env.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ValueError(
                "bounded subprocess environment keys and values must be strings"
            )
        if not key or "=" in key or "\0" in key or "\0" in value:
            raise ValueError(
                "bounded subprocess environment contains an invalid key or NUL"
            )
        validated[key] = value
    return validated


def _validated_pass_fds(pass_fds: Sequence[int]) -> tuple[int, ...]:
    if not isinstance(pass_fds, Sequence) or isinstance(pass_fds, (str, bytes)):
        raise ValueError("bounded subprocess pass_fds must be an integer sequence")
    descriptors = tuple(pass_fds)
    if any(
        not isinstance(descriptor, int)
        or isinstance(descriptor, bool)
        or descriptor < 3
        for descriptor in descriptors
    ):
        raise ValueError("bounded subprocess pass_fds must contain integers >= 3")
    if len(descriptors) != len(set(descriptors)):
        raise ValueError("bounded subprocess pass_fds must not contain duplicates")
    for descriptor in descriptors:
        try:
            os.fstat(descriptor)
        except OSError as exc:
            raise ValueError(
                f"bounded subprocess pass_fds contains an invalid descriptor: {descriptor}"
            ) from exc
    return descriptors


def _validate_limits(
    *,
    timeout_seconds: object,
    max_output_bytes: object,
    maximum_timeout_seconds: object,
    maximum_output_bytes: object,
    termination_grace_seconds: object,
) -> tuple[float, int, float]:
    maximum_timeout = _validate_positive_finite_number(
        maximum_timeout_seconds,
        label="maximum timeout",
        maximum=HARD_MAX_TIMEOUT_SECONDS,
    )
    timeout = _validate_positive_finite_number(
        timeout_seconds,
        label="timeout",
        maximum=maximum_timeout,
    )
    maximum_output = _validate_positive_integer(
        maximum_output_bytes,
        label="maximum output-byte limit",
        maximum=HARD_MAX_OUTPUT_BYTES,
    )
    output_limit = _validate_positive_integer(
        max_output_bytes,
        label="output-byte limit",
        maximum=maximum_output,
    )
    grace = _validate_positive_finite_number(
        termination_grace_seconds,
        label="termination grace",
        maximum=HARD_MAX_TERMINATION_GRACE_SECONDS,
    )
    return timeout, output_limit, grace


def _linux_task_ids() -> tuple[int, ...]:
    process_id = os.getpid()
    task_root = Path("/proc") / str(process_id) / "task"
    try:
        with os.scandir(task_root) as entries:
            task_ids = sorted(
                int(entry.name)
                for entry in entries
                if entry.name.isdecimal()
            )
    except OSError as exc:
        raise BoundedSubprocessPreconditionError(
            f"Linux bounded subprocesses require readable {task_root}: {exc}"
        ) from exc
    return tuple(task_ids)


def _validated_linux_child_pid_tokens(text: str) -> tuple[int, ...]:
    try:
        child_pids = tuple(int(token) for token in text.split())
    except ValueError as exc:
        raise BoundedSubprocessCleanupError(
            f"Linux direct-child inventory is malformed: {text!r}"
        ) from exc
    if any(pid <= 0 for pid in child_pids) or len(child_pids) != len(set(child_pids)):
        raise BoundedSubprocessCleanupError(
            f"Linux direct-child inventory is invalid: {child_pids!r}"
        )
    return child_pids


def _linux_children_file_pids() -> tuple[int, ...] | None:
    process_id = os.getpid()
    path = (
        Path("/proc")
        / str(process_id)
        / "task"
        / str(process_id)
        / "children"
    )
    try:
        text = path.read_text(encoding="ascii")
    except FileNotFoundError:
        # CONFIG_CHECKPOINT_RESTORE controls this task-file interface. Some
        # otherwise suitable Linux containers omit it, so use the bounded
        # identity scan below instead of weakening child ownership checks.
        return None
    except (OSError, UnicodeError) as exc:
        raise BoundedSubprocessCleanupError(
            f"Linux bounded subprocesses require readable {path}: {exc}"
        ) from exc
    return _validated_linux_child_pid_tokens(text)


def _linux_proc_direct_children_snapshot() -> tuple[_LinuxProcessRecord, ...]:
    parent_pid = os.getpid()
    records: list[_LinuxProcessRecord] = []
    numeric_entries = 0
    try:
        with os.scandir("/proc") as entries:
            for entry in entries:
                if not entry.name.isdecimal():
                    continue
                numeric_entries += 1
                if numeric_entries > MAX_LINUX_PROC_ENTRIES:
                    raise BoundedSubprocessCleanupError(
                        "Linux process inventory exceeded the explicit "
                        f"{MAX_LINUX_PROC_ENTRIES}-entry scan limit"
                    )
                record = _linux_read_process(int(entry.name))
                if record is not None and record.parent_pid == parent_pid:
                    records.append(record)
    except BoundedSubprocessCleanupError:
        raise
    except OSError as exc:
        raise BoundedSubprocessCleanupError(
            f"could not enumerate the bounded Linux process inventory: {exc}"
        ) from exc
    return tuple(sorted(records, key=lambda record: record.identity))


def _linux_direct_child_pids() -> tuple[int, ...]:
    child_pids = _linux_children_file_pids()
    if child_pids is not None:
        return child_pids
    for _attempt in range(4):
        first = _linux_proc_direct_children_snapshot()
        second = _linux_proc_direct_children_snapshot()
        if tuple(record.identity for record in first) == tuple(
            record.identity for record in second
        ):
            return tuple(record.pid for record in second)
    raise BoundedSubprocessCleanupError(
        "Linux direct-child process inventory did not stabilize"
    )


def _linux_read_process(pid: int) -> _LinuxProcessRecord | None:
    try:
        raw = (Path("/proc") / str(pid) / "stat").read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        if exc.errno in {errno.ENOENT, errno.ESRCH}:
            return None
        raise BoundedSubprocessCleanupError(
            f"could not inspect Linux process identity for pid {pid}: {exc}"
        ) from exc
    prefix, separator, suffix = raw.rpartition(b")")
    if not separator or b"(" not in prefix:
        raise BoundedSubprocessCleanupError(
            f"Linux process identity is malformed for pid {pid}"
        )
    declared_pid_text = prefix.split(b"(", 1)[0].strip()
    fields = suffix.strip().split()
    try:
        declared_pid = int(declared_pid_text)
        parent_pid = int(fields[1])
        process_group_id = int(fields[2])
        session_id = int(fields[3])
        start_time_ticks = int(fields[19])
    except (IndexError, ValueError) as exc:
        raise BoundedSubprocessCleanupError(
            f"Linux process identity is incomplete for pid {pid}"
        ) from exc
    if declared_pid != pid or start_time_ticks < 0:
        raise BoundedSubprocessCleanupError(
            f"Linux process identity does not match requested pid {pid}"
        )
    return _LinuxProcessRecord(
        pid=pid,
        parent_pid=parent_pid,
        process_group_id=process_group_id,
        session_id=session_id,
        start_time_ticks=start_time_ticks,
    )


def _linux_direct_children() -> tuple[_LinuxProcessRecord, ...]:
    parent_pid = os.getpid()
    for _attempt in range(4):
        child_pids = _linux_direct_child_pids()
        records: list[_LinuxProcessRecord] = []
        stable = True
        for child_pid in child_pids:
            record = _linux_read_process(child_pid)
            if record is None or record.parent_pid != parent_pid:
                stable = False
                break
            records.append(record)
        if stable and _linux_direct_child_pids() == child_pids:
            return tuple(records)
    raise BoundedSubprocessCleanupError(
        "Linux direct-child identities did not stabilize during discovery"
    )


def _linux_prctl_get_subreaper() -> int:
    # prctl(2) is variadic after the operation code. Pass pointer-width values
    # explicitly; ``value`` remains alive for the complete synchronous call.
    libc = ctypes.CDLL(None, use_errno=True)
    prctl = libc.prctl
    value = ctypes.c_int()
    result = prctl(
        ctypes.c_int(_PR_GET_CHILD_SUBREAPER),
        ctypes.c_ulong(ctypes.addressof(value)),
        ctypes.c_ulong(0),
        ctypes.c_ulong(0),
        ctypes.c_ulong(0),
    )
    if result != 0:
        error_number = ctypes.get_errno()
        raise BoundedSubprocessPreconditionError(
            f"PR_GET_CHILD_SUBREAPER failed: {os.strerror(error_number)}"
        )
    if value.value not in (0, 1):
        raise BoundedSubprocessPreconditionError(
            f"PR_GET_CHILD_SUBREAPER returned invalid state: {value.value}"
        )
    return value.value


def _linux_prctl_set_subreaper(enabled: int) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    prctl = libc.prctl
    result = prctl(
        ctypes.c_int(_PR_SET_CHILD_SUBREAPER),
        ctypes.c_ulong(enabled),
        ctypes.c_ulong(0),
        ctypes.c_ulong(0),
        ctypes.c_ulong(0),
    )
    if result != 0:
        error_number = ctypes.get_errno()
        raise BoundedSubprocessCleanupError(
            f"PR_SET_CHILD_SUBREAPER failed: {os.strerror(error_number)}"
        )


def _assert_linux_pidfd_support() -> None:
    if (
        not hasattr(os, "pidfd_open")
        or not hasattr(os, "P_PIDFD")
        or not hasattr(signal, "pidfd_send_signal")
    ):
        raise BoundedSubprocessPreconditionError(
            "Linux bounded subprocesses require pidfd_open, P_PIDFD, and "
            "pidfd_send_signal"
        )


class _LinuxSubreaperScope:
    def __init__(self) -> None:
        self._prior_state: int | None = None
        self._active = False

    def activate(self) -> None:
        task_ids = _linux_task_ids()
        if task_ids != (os.getpid(),):
            raise BoundedSubprocessPreconditionError(
                "Linux bounded subprocesses require exactly one task; "
                f"found task ids {task_ids!r}"
            )
        if signal.getsignal(signal.SIGCHLD) != signal.SIG_DFL:
            raise BoundedSubprocessPreconditionError(
                "Linux bounded subprocesses require the default SIGCHLD disposition"
            )
        _assert_linux_pidfd_support()
        child_pids = _linux_direct_child_pids()
        if child_pids:
            raise BoundedSubprocessPreconditionError(
                "Linux bounded subprocesses require no pre-existing direct children; "
                f"found {child_pids!r}"
            )
        prior_state = _linux_prctl_get_subreaper()
        _linux_prctl_set_subreaper(1)
        self._prior_state = prior_state
        self._active = True
        child_pids = _linux_direct_child_pids()
        if child_pids:
            # The command has not been spawned, so this raced child is not
            # owned by the scope. Restore immediately and refuse to proceed.
            _linux_prctl_set_subreaper(prior_state)
            restored_state = _linux_prctl_get_subreaper()
            self._active = False
            if restored_state != prior_state:
                raise BoundedSubprocessCleanupError(
                    "subreaper activation rollback could not be verified"
                )
            raise BoundedSubprocessPreconditionError(
                "a direct child appeared while activating the scoped subreaper: "
                f"{child_pids!r}"
            )

    def restore(self) -> None:
        if not self._active:
            return
        child_pids = _linux_direct_child_pids()
        if child_pids:
            raise BoundedSubprocessCleanupError(
                "cannot restore the prior subreaper state while direct children "
                f"remain: {child_pids!r}"
            )
        if self._prior_state is None:
            raise BoundedSubprocessCleanupError(
                "scoped subreaper has no recorded prior state"
            )
        prior_state = self._prior_state
        _linux_prctl_set_subreaper(prior_state)
        restored_state = _linux_prctl_get_subreaper()
        if restored_state != prior_state:
            raise BoundedSubprocessCleanupError(
                "scoped subreaper state restoration could not be verified: "
                f"expected {prior_state}, found {restored_state}"
            )
        self._active = False


def _open_verified_pidfd(record: _LinuxProcessRecord) -> int:
    try:
        pidfd = os.pidfd_open(record.pid, 0)
    except (OSError, AttributeError) as exc:
        raise BoundedSubprocessCleanupError(
            f"could not open pidfd for child identity {record.identity!r}: {exc}"
        ) from exc
    try:
        current = _linux_read_process(record.pid)
        if current is None or current.identity != record.identity:
            raise BoundedSubprocessCleanupError(
                f"child identity changed before pidfd verification: {record.identity!r}"
            )
        if current.parent_pid != os.getpid():
            raise BoundedSubprocessCleanupError(
                f"pid {record.pid} is no longer a direct child"
            )
        return pidfd
    except BaseException as primary:
        resource_cleanup.cleanup_actions(
            (("verified child pidfd", lambda: os.close(pidfd)),),
            primary=primary,
        )
        raise


def _signal_linux_child(record: _LinuxProcessRecord, signal_number: int) -> None:
    pidfd = _open_verified_pidfd(record)
    try:
        try:
            signal.pidfd_send_signal(pidfd, signal_number)
        except ProcessLookupError:
            # An exited, unreaped child is already beyond signal handling and
            # remains available to the identity-safe waitid(P_PIDFD) path.
            pass
    finally:
        resource_cleanup.cleanup_actions(
            (("signaled child pidfd", lambda: os.close(pidfd)),),
            primary=sys.exception(),
        )


def _reap_linux_child_if_exited(record: _LinuxProcessRecord) -> bool:
    pidfd = _open_verified_pidfd(record)
    try:
        try:
            wait_result = os.waitid(
                os.P_PIDFD,
                pidfd,
                os.WEXITED | os.WNOHANG,
            )
        except ChildProcessError as exc:
            raise BoundedSubprocessCleanupError(
                f"direct child could not be reaped: {record.identity!r}"
            ) from exc
        return wait_result is not None
    finally:
        resource_cleanup.cleanup_actions(
            (("reaped child pidfd", lambda: os.close(pidfd)),),
            primary=sys.exception(),
        )


def _same_linux_identity(
    expected: _LinuxProcessRecord,
    current: _LinuxProcessRecord | None,
) -> bool:
    return current is not None and current.identity == expected.identity


def _signal_process_group(
    process: subprocess.Popen[bytes],
    leader: _LinuxProcessRecord | None,
    signal_number: int,
) -> None:
    if leader is not None:
        current = _linux_read_process(leader.pid)
        if not _same_linux_identity(leader, current):
            raise BoundedSubprocessCleanupError(
                f"subprocess leader identity changed before group signal: {leader.identity!r}"
            )
        if current is None or current.process_group_id != leader.pid:
            raise BoundedSubprocessCleanupError(
                f"subprocess leader no longer owns process group {leader.pid}"
            )
    else:
        try:
            process_group_id = os.getpgid(process.pid)
        except ProcessLookupError as exc:
            raise BoundedSubprocessCleanupError(
                f"subprocess leader disappeared before group signal: pid={process.pid}"
            ) from exc
        if process_group_id != process.pid:
            raise BoundedSubprocessCleanupError(
                f"subprocess leader does not own its group: "
                f"pid={process.pid}, pgid={process_group_id}"
            )
    try:
        os.killpg(process.pid, signal_number)
    except ProcessLookupError:
        # A group containing only an exited leader can report ESRCH.  The
        # unreaped, identity-verified leader still prevents group-id reuse.
        pass


def _reap_leader(
    process: subprocess.Popen[bytes],
    *,
    timeout_seconds: float,
) -> int:
    try:
        returncode = process.wait(timeout=timeout_seconds)
    except (subprocess.TimeoutExpired, ChildProcessError) as exc:
        raise BoundedSubprocessCleanupError(
            f"bounded subprocess leader could not be reaped: pid={process.pid}"
        ) from exc
    if process.returncode is None:
        raise BoundedSubprocessCleanupError(
            f"bounded subprocess cleanup returned no leader status: pid={process.pid}"
        )
    return returncode


def _signal_new_linux_children(
    *,
    signal_number: int,
    seen: set[tuple[int, int]],
    excluded_pid: int | None,
) -> None:
    for record in _linux_direct_children():
        if record.pid == excluded_pid or record.identity in seen:
            continue
        _signal_linux_child(record, signal_number)
        seen.add(record.identity)


def _kill_and_reap_linux_children(*, timeout_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    while True:
        children = _linux_direct_children()
        if not children:
            if _linux_direct_child_pids():
                raise BoundedSubprocessCleanupError(
                    "a Linux direct child remained without a stable identity"
                )
            return
        for record in children:
            _signal_linux_child(record, signal.SIGKILL)
        for record in children:
            current = _linux_read_process(record.pid)
            if _same_linux_identity(record, current):
                _reap_linux_child_if_exited(record)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            identities = tuple(record.identity for record in _linux_direct_children())
            raise BoundedSubprocessCleanupError(
                f"adopted descendants could not be reaped: {identities!r}"
            )
        time.sleep(min(_CLEANUP_POLL_SECONDS, remaining))


def _terminate_linux_children_after_normal_exit(*, grace_seconds: float) -> None:
    children = _linux_direct_children()
    if not children:
        return
    deadline = time.monotonic() + grace_seconds
    seen: set[tuple[int, int]] = set()
    while True:
        _signal_new_linux_children(
            signal_number=signal.SIGTERM,
            seen=seen,
            excluded_pid=None,
        )
        for record in _linux_direct_children():
            current = _linux_read_process(record.pid)
            if _same_linux_identity(record, current):
                _reap_linux_child_if_exited(record)
        if not _linux_direct_child_pids():
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(_CLEANUP_POLL_SECONDS, remaining))
    _kill_and_reap_linux_children(timeout_seconds=grace_seconds)


def _terminate_failed_process(
    process: subprocess.Popen[bytes],
    *,
    leader: _LinuxProcessRecord | None,
    grace_seconds: float,
) -> int:
    _signal_process_group(process, leader, signal.SIGTERM)
    if _is_linux():
        deadline = time.monotonic() + grace_seconds
        seen: set[tuple[int, int]] = set()
        while True:
            _signal_new_linux_children(
                signal_number=signal.SIGTERM,
                seen=seen,
                excluded_pid=process.pid,
            )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(_CLEANUP_POLL_SECONDS, remaining))
    else:
        time.sleep(grace_seconds)
    _signal_process_group(process, leader, signal.SIGKILL)
    if _is_linux():
        for record in _linux_direct_children():
            if record.pid != process.pid:
                _signal_linux_child(record, signal.SIGKILL)
    returncode = _reap_leader(process, timeout_seconds=grace_seconds)
    if _is_linux():
        _kill_and_reap_linux_children(timeout_seconds=grace_seconds)
    return returncode


def _kill_unverified_leader(
    process: subprocess.Popen[bytes],
    *,
    grace_seconds: float,
) -> None:
    try:
        process.kill()
    except ProcessLookupError:
        pass
    _reap_leader(process, timeout_seconds=grace_seconds)
    if _is_linux():
        _kill_and_reap_linux_children(timeout_seconds=grace_seconds)


def _collect_output(
    process: subprocess.Popen[bytes],
    *,
    deadline: float,
    max_output_bytes: int,
) -> tuple[bytes, bytes, bool, bool]:
    stdout = bytearray()
    stderr = bytearray()
    total_bytes = 0
    timed_out = False
    output_exceeded = False
    selector = selectors.DefaultSelector()
    try:
        if process.stdout is None or process.stderr is None:
            raise BoundedSubprocessError(
                "bounded subprocess did not create both captured streams"
            )
        selector.register(process.stdout, selectors.EVENT_READ, stdout)
        selector.register(process.stderr, selectors.EVENT_READ, stderr)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            events = selector.select(timeout=remaining)
            if not events:
                if time.monotonic() < deadline:
                    continue
                timed_out = True
                break
            for key, _mask in events:
                capacity = max_output_bytes - total_bytes
                chunk = os.read(key.fd, min(_READ_CHUNK_BYTES, capacity + 1))
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                accepted = chunk[:capacity]
                key.data.extend(accepted)
                total_bytes += len(accepted)
                if len(chunk) > capacity:
                    output_exceeded = True
                    break
            if output_exceeded:
                break
    finally:
        resource_cleanup.cleanup_actions(
            tuple(
                (
                    "bounded subprocess stream selector registration",
                    lambda fileobj=key.fileobj: selector.unregister(fileobj),
                )
                for key in list(selector.get_map().values())
            )
            + (("bounded subprocess selector", selector.close),),
            primary=sys.exception(),
        )
    return bytes(stdout), bytes(stderr), timed_out, output_exceeded


def run_bounded_process(
    args: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str] | None = None,
    pass_fds: Sequence[int] = (),
    timeout_seconds: float,
    max_output_bytes: int,
    maximum_timeout_seconds: float,
    maximum_output_bytes: int,
    termination_grace_seconds: float,
) -> BoundedProcessResult:
    """Run one argv-only POSIX command and leave no owned Linux child behind."""

    command = _validated_command(args)
    validated_env = _validated_environment(env)
    validated_pass_fds = _validated_pass_fds(pass_fds)
    timeout, output_limit, grace = _validate_limits(
        timeout_seconds=timeout_seconds,
        max_output_bytes=max_output_bytes,
        maximum_timeout_seconds=maximum_timeout_seconds,
        maximum_output_bytes=maximum_output_bytes,
        termination_grace_seconds=termination_grace_seconds,
    )
    if os.name != "posix":
        raise BoundedSubprocessPreconditionError(
            "bounded subprocess execution requires POSIX process groups"
        )

    scope = _LinuxSubreaperScope() if _is_linux() else None
    process: subprocess.Popen[bytes] | None = None
    leader: _LinuxProcessRecord | None = None
    try:
        if scope is not None:
            scope.activate()
        try:
            process = subprocess.Popen(
                command,
                cwd=cwd,
                env=validated_env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
                pass_fds=validated_pass_fds,
            )
        except OSError as exc:
            raise BoundedSubprocessStartError(
                f"bounded subprocess could not start: {exc}"
            ) from exc
        if _is_linux():
            leader = _linux_read_process(process.pid)
            if leader is None or leader.parent_pid != os.getpid():
                raise BoundedSubprocessCleanupError(
                    f"could not establish subprocess leader identity: pid={process.pid}"
                )
            if leader.process_group_id != process.pid or leader.session_id != process.pid:
                raise BoundedSubprocessCleanupError(
                    "subprocess leader did not establish its dedicated session: "
                    f"pid={process.pid}, pgid={leader.process_group_id}, "
                    f"sid={leader.session_id}"
                )
        else:
            process_group_id = os.getpgid(process.pid)
            if process_group_id != process.pid:
                raise BoundedSubprocessCleanupError(
                    "subprocess leader did not establish its dedicated POSIX group: "
                    f"pid={process.pid}, pgid={process_group_id}"
                )

        deadline = time.monotonic() + timeout
        stdout, stderr, timed_out, output_exceeded = _collect_output(
            process,
            deadline=deadline,
            max_output_bytes=output_limit,
        )
        if timed_out or output_exceeded:
            returncode = _terminate_failed_process(
                process,
                leader=leader,
                grace_seconds=grace,
            )
        else:
            remaining = max(deadline - time.monotonic(), 0.0)
            try:
                returncode = process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                timed_out = True
                returncode = _terminate_failed_process(
                    process,
                    leader=leader,
                    grace_seconds=grace,
                )
            if _is_linux():
                _terminate_linux_children_after_normal_exit(grace_seconds=grace)

        if process.returncode is None:
            raise BoundedSubprocessCleanupError(
                f"bounded subprocess leader was not reaped: pid={process.pid}"
            )
        if _is_linux() and _linux_direct_child_pids():
            raise BoundedSubprocessCleanupError(
                "bounded subprocess left a new direct child after cleanup"
            )
        return BoundedProcessResult(
            args=command,
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            timed_out=timed_out,
            output_exceeded=output_exceeded,
        )
    except BaseException as primary_error:
        if process is not None:
            try:
                if process.returncode is None:
                    if leader is None:
                        _kill_unverified_leader(process, grace_seconds=grace)
                    else:
                        _terminate_failed_process(
                            process,
                            leader=leader,
                            grace_seconds=grace,
                        )
                elif _is_linux():
                    _kill_and_reap_linux_children(timeout_seconds=grace)
            except BaseException as cleanup_error:
                raise BoundedSubprocessCleanupError(
                    "bounded subprocess failed and cleanup also failed: "
                    f"primary={primary_error!r}; cleanup={cleanup_error!r}"
                ) from cleanup_error
        raise
    finally:
        cleanup_actions: list[tuple[str, Callable[[], object]]] = []
        if process is not None:
            for label, stream in (
                ("stdout", process.stdout),
                ("stderr", process.stderr),
            ):
                if stream is not None:
                    cleanup_actions.append(
                        (f"bounded subprocess {label} stream", stream.close)
                    )
        if scope is not None:
            cleanup_actions.append(("bounded subprocess subreaper scope", scope.restore))
        resource_cleanup.cleanup_actions(cleanup_actions, primary=sys.exception())
