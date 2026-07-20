#!/usr/bin/env python3

"""Prepare, resume, and publish one sanitized public framework release.

The controller keeps the existing read-only handoff verifier as the acceptance
oracle.  It adds durable, append-only phase receipts so an interpreter or shell
exit does not erase already verified export, candidate, or push evidence.
Credentials are accepted only at the push boundary and are never persisted.
"""

from __future__ import annotations

import sys

if __name__ == "__main__" and not (
    sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode
):
    sys.stderr.write(
        "public release failed: controller requires Python -I -S -B\n"
    )
    raise SystemExit(2)

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import NoReturn

# Isolated mode deliberately omits the script directory from ``sys.path``.
# Add only this controller's resolved sibling directory so the public framework
# modules below remain importable without re-enabling ambient import paths.
_SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(_SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIRECTORY))

import bounded_subprocess
import public_handoff_check
import public_handoff_lifecycle
import public_release_check
import public_release_state
import safe_paths


REQUEST_SCHEMA_VERSION = 1
NO_CREDENTIAL_BOUNDARY_SHA256 = (
    public_release_state.NO_CREDENTIAL_BOUNDARY_SHA256
)
COMMAND_TIMEOUT_SECONDS = 60.0 * 60.0
NETWORK_TIMEOUT_SECONDS = 5.0 * 60.0
COMMAND_MAX_OUTPUT_BYTES = 64 * 1024 * 1024
TERMINATION_GRACE_SECONDS = 5.0
COMMIT_TEXT_MAX_CHARS = 512
_ISOLATED_SCRIPT_BOOTSTRAP = """\
import runpy
import sys
from pathlib import Path

script = Path(sys.argv[1])
if not script.is_absolute() or any(part in {"", ".", ".."} for part in script.parts):
    raise SystemExit("framework command path must be canonical and absolute")
script_directory = str(script.parent)
sys.path.insert(0, script_directory)
sys.argv = sys.argv[1:]
runpy.run_path(str(script), run_name="__main__")
"""
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_FULL_OID_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
_EMAIL_RE = re.compile(r"[^\s<>@]+@[^\s<>@]+")
_REQUEST_FIELDS = frozenset(
    {
        "schema_version",
        "authoring_root",
        "git_executable",
        "uv_executable",
        "python_executable",
        "remote_name",
        "branch",
        "remote_url",
        "public_name",
        "public_email",
        "commit_message",
        "commit_timestamp",
    }
)


class _CliError(ValueError):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise _CliError(message)


@dataclass
class _Executable:
    descriptor: int
    metadata: os.stat_result
    path: Path
    sha256: str
    description: str
    _closed: bool = False

    @property
    def command(self) -> str:
        self.require_current()
        path = f"/proc/self/fd/{self.descriptor}"
        if not Path(path).exists():
            raise ValueError(f"{self.description} requires Linux procfs descriptors")
        return path

    @property
    def external_command(self) -> str:
        self.require_current()
        path = f"/proc/{os.getpid()}/fd/{self.descriptor}"
        if not Path(path).exists():
            raise ValueError(f"{self.description} requires Linux procfs descriptors")
        return path

    @property
    def pass_fds(self) -> tuple[int, ...]:
        return (self.descriptor,)

    def require_current(self) -> None:
        if self._closed:
            raise ValueError(f"{self.description} is closed")
        current = os.fstat(self.descriptor)
        if (
            current.st_dev,
            current.st_ino,
            current.st_uid,
            current.st_mode,
            current.st_size,
        ) != (
            self.metadata.st_dev,
            self.metadata.st_ino,
            self.metadata.st_uid,
            self.metadata.st_mode,
            self.metadata.st_size,
        ):
            raise ValueError(f"{self.description} descriptor identity changed")
        if _descriptor_sha256(self.descriptor) != self.sha256:
            raise ValueError(f"{self.description} content changed")

    def close(self) -> None:
        if self._closed:
            return
        primary: BaseException | None = None
        try:
            self.require_current()
        except BaseException as exc:
            primary = exc
        self._closed = True
        try:
            os.close(self.descriptor)
        except BaseException as cleanup:
            if primary is not None:
                primary.add_note(f"{self.description} close failed: {cleanup}")
            else:
                raise
        if primary is not None:
            raise primary


@dataclass
class _Toolset:
    git: _Executable
    uv: _Executable
    python: _Executable

    def require_current(self) -> None:
        self.git.require_current()
        self.uv.require_current()
        self.python.require_current()

    def close(self) -> None:
        primary = sys.exception()
        failures: list[BaseException] = []
        for tool in (self.python, self.uv, self.git):
            try:
                tool.close()
            except BaseException as exc:
                failures.append(exc)
        if failures:
            if primary is not None:
                for failure in failures:
                    primary.add_note(f"release tool cleanup failed: {failure}")
                return
            raise BaseExceptionGroup("release tool cleanup failed", failures)


def _pretty_json(value: object) -> str:
    return json.dumps(
        value,
        indent=2,
        sort_keys=True,
        allow_nan=False,
        ensure_ascii=False,
    ) + "\n"


def _descriptor_sha256(descriptor: int) -> str:
    digest = hashlib.sha256()
    offset = 0
    while chunk := os.pread(descriptor, 1024 * 1024, offset):
        digest.update(chunk)
        offset += len(chunk)
    return digest.hexdigest()


def _canonical_absolute(path: Path, *, description: str) -> Path:
    if (
        not path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError(f"{description} must be one canonical absolute path")
    return path


def _open_executable(path: Path, *, description: str) -> _Executable:
    path = _canonical_absolute(path, description=description)
    resolved = Path(os.path.realpath(path))
    if path != resolved:
        raise ValueError(f"{description} must be supplied as its resolved path")
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_mode & 0o022
            or not metadata.st_mode & 0o111
        ):
            raise ValueError(
                f"{description} must be a singly linked executable regular file "
                "without group/world write permission"
            )
        digest = _descriptor_sha256(descriptor)
        tool = _Executable(descriptor, metadata, path, digest, description)
        tool.require_current()
        return tool
    except BaseException:
        os.close(descriptor)
        raise


def _require_running_python(executable: _Executable) -> None:
    executable.require_current()
    descriptor = os.open(
        "/proc/self/exe",
        os.O_RDONLY | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        before = os.fstat(descriptor)
        digest = _descriptor_sha256(descriptor)
        after = os.fstat(descriptor)
        running_identity = (
            before.st_dev,
            before.st_ino,
            before.st_uid,
            before.st_mode,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        terminal_identity = (
            after.st_dev,
            after.st_ino,
            after.st_uid,
            after.st_mode,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        retained_identity = (
            executable.metadata.st_dev,
            executable.metadata.st_ino,
            executable.metadata.st_uid,
            executable.metadata.st_mode,
            executable.metadata.st_size,
            executable.metadata.st_mtime_ns,
            executable.metadata.st_ctime_ns,
        )
        if (
            running_identity != terminal_identity
            or terminal_identity != retained_identity
            or digest != executable.sha256
        ):
            raise ValueError(
                "running Python image does not equal the retained Python executable"
            )
    finally:
        os.close(descriptor)
    executable.require_current()


def _open_tools(request: dict[str, object]) -> _Toolset:
    git = _open_executable(Path(str(request["git_executable"])), description="Git")
    try:
        uv = _open_executable(Path(str(request["uv_executable"])), description="uv")
        try:
            python = _open_executable(
                Path(str(request["python_executable"])),
                description="Python",
            )
        except BaseException:
            uv.close()
            raise
    except BaseException:
        git.close()
        raise
    tools = _Toolset(git=git, uv=uv, python=python)
    if Path(os.path.realpath(sys.executable)) != tools.python.path:
        tools.close()
        raise ValueError(
            "controller must run with the exact Python executable recorded in the request"
        )
    try:
        _require_running_python(tools.python)
    except BaseException:
        tools.close()
        raise
    return tools


def _base_environment() -> dict[str, str]:
    return {
        "LC_ALL": "C.UTF-8",
        "PATH": "/usr/sbin:/usr/bin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONUTF8": "1",
    }


def _run(
    args: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    pass_fds: tuple[int, ...],
    timeout_seconds: float = COMMAND_TIMEOUT_SECONDS,
) -> tuple[bytes, bytes]:
    result = bounded_subprocess.run_bounded_process(
        args,
        cwd=cwd,
        env=env,
        pass_fds=pass_fds,
        timeout_seconds=timeout_seconds,
        max_output_bytes=COMMAND_MAX_OUTPUT_BYTES,
        maximum_timeout_seconds=COMMAND_TIMEOUT_SECONDS,
        maximum_output_bytes=COMMAND_MAX_OUTPUT_BYTES,
        termination_grace_seconds=TERMINATION_GRACE_SECONDS,
    )
    if result.returncode != 0 or result.timed_out or result.output_exceeded:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        stdout = result.stdout.decode("utf-8", errors="replace").strip()
        diagnostic = stderr or stdout or f"exit {result.returncode}"
        raise RuntimeError(f"release command failed: {diagnostic[:4096]}")
    return result.stdout, result.stderr


def _run_python(
    tools: _Toolset,
    script: Path,
    arguments: list[str],
    *,
    cwd: Path,
    pass_fds: tuple[int, ...] = (),
    timeout_seconds: float = COMMAND_TIMEOUT_SECONDS,
) -> tuple[bytes, bytes]:
    tools.require_current()
    descriptors = tuple(dict.fromkeys((*tools.python.pass_fds, *pass_fds)))
    script = _canonical_absolute(script, description="framework command path")
    result = _run(
        [
            tools.python.external_command,
            "-I",
            "-S",
            "-B",
            "-c",
            _ISOLATED_SCRIPT_BOOTSTRAP,
            str(script),
            *arguments,
        ],
        cwd=cwd,
        env=_base_environment(),
        pass_fds=descriptors,
        timeout_seconds=timeout_seconds,
    )
    tools.require_current()
    return result


def _safe_text(value: str, *, description: str, maximum: int) -> str:
    if (
        not value
        or len(value) > maximum
        or value != value.strip()
        or any(ord(character) < 0x20 and character not in {"\n", "\t"} for character in value)
        or "\x7f" in value
    ):
        raise ValueError(f"{description} is not bounded clean text")
    return value


def _require_public_metadata_safe(values: dict[str, str]) -> None:
    policy_errors: list[str] = []
    policy = public_release_check.load_private_workflow_policy(
        _SCRIPT_DIRECTORY.parent,
        policy_errors,
        required=False,
    )
    if policy_errors:
        raise ValueError("public release metadata privacy policy could not be validated")
    for field, value in values.items():
        for line_number, line in enumerate(value.splitlines() or [value], start=1):
            errors = public_release_check._line_leak_errors(
                f"public-release-{field}",
                line_number,
                line,
                structured_secret_keys=set(),
                private_workflow_reference_re=(
                    policy.reference_re if policy is not None else None
                ),
            )
            if errors:
                raise ValueError(
                    "public release metadata failed private-path or credential "
                    f"screening in {field}"
                )


def _validate_request(
    value: object,
    *,
    screen_metadata: bool = True,
) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != _REQUEST_FIELDS:
        raise ValueError("release request does not use the closed schema")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValueError("release request schema version is unsupported")
    request = dict(value)
    for field in ("authoring_root", "git_executable", "uv_executable", "python_executable"):
        if not isinstance(request[field], str):
            raise ValueError(f"release request {field} must be a string")
        _canonical_absolute(Path(request[field]), description=field.replace("_", " "))
    selected_authoring_root = Path(str(request["authoring_root"]))
    if selected_authoring_root != _SCRIPT_DIRECTORY.parent:
        raise ValueError(
            "authoring root must be the controller's exact framework checkout"
        )
    for field in (
        "remote_name",
        "branch",
        "remote_url",
        "public_name",
        "public_email",
        "commit_message",
        "commit_timestamp",
    ):
        if not isinstance(request[field], str):
            raise ValueError(f"release request {field} must be a string")
    errors = public_handoff_check.publication_target_errors(
        remote_name=str(request["remote_name"]),
        branch=str(request["branch"]),
        expected_fetch_url=str(request["remote_url"]),
        expected_push_url=str(request["remote_url"]),
    )
    if errors:
        raise ValueError("; ".join(errors))
    remote_url = str(request["remote_url"])
    if not remote_url.startswith("https://"):
        raise ValueError(
            "public release controller requires one lowercase HTTPS remote URL"
        )
    public_name = _safe_text(
        str(request["public_name"]),
        description="public name",
        maximum=128,
    )
    if any(character in public_name for character in "\n\r\t<>"):
        raise ValueError("public name must be single-line text without angle brackets")
    email = _safe_text(
        str(request["public_email"]), description="public email", maximum=254
    )
    if _EMAIL_RE.fullmatch(email) is None:
        raise ValueError("public email is not canonical")
    message = _safe_text(
        str(request["commit_message"]),
        description="commit message",
        maximum=COMMIT_TEXT_MAX_CHARS,
    )
    if "\n\n\n" in message:
        raise ValueError("commit message contains excessive blank paragraphs")
    if screen_metadata:
        _require_public_metadata_safe(
            {
                "commit-message": message,
                "public-email": email,
                "public-name": public_name,
            }
        )
    timestamp = str(request["commit_timestamp"])
    try:
        parsed = datetime.fromisoformat(timestamp)
    except ValueError as exc:
        raise ValueError("commit timestamp must be ISO 8601 with an offset") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("commit timestamp must include an explicit UTC offset")
    if parsed.isoformat(timespec="seconds") != timestamp:
        raise ValueError("commit timestamp must use canonical second precision")
    return request


def _request_from_args(args: argparse.Namespace) -> dict[str, object]:
    timestamp = (
        args.commit_timestamp
        if args.commit_timestamp is not None
        else datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    return _validate_request(
        {
            "schema_version": REQUEST_SCHEMA_VERSION,
            "authoring_root": str(args.authoring_root),
            "git_executable": str(args.git_executable),
            "uv_executable": str(args.uv_executable),
            "python_executable": str(args.python_executable),
            "remote_name": args.remote_name,
            "branch": args.branch,
            "remote_url": args.remote_url,
            "public_name": args.public_name,
            "public_email": args.public_email,
            "commit_message": args.commit_message,
            "commit_timestamp": timestamp,
        }
    )


@dataclass(frozen=True)
class _ReleasePaths:
    operation: Path
    control: Path
    state: Path
    temporary: Path
    export: Path
    clone: Path


def _release_paths(operation: Path) -> _ReleasePaths:
    operation = _canonical_absolute(operation, description="release root")
    return _ReleasePaths(
        operation=operation,
        control=operation / "control",
        state=operation / "state",
        temporary=operation / "temporary",
        export=operation / "export",
        clone=operation / "public-clone",
    )


def _initialize_operation(paths: _ReleasePaths) -> None:
    if paths.operation.exists() or paths.operation.is_symlink():
        raise FileExistsError("release root must be absent for prepare")
    parent = safe_paths.open_output_directory(paths.operation.parent, create_missing=False)
    operation_descriptor: int | None = None
    try:
        if paths.operation.name in {"", ".", ".."}:
            raise ValueError("release root must have one safe final component")
        os.mkdir(paths.operation.name, 0o700, dir_fd=parent.descriptor)
        operation_descriptor = os.open(
            paths.operation.name,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            dir_fd=parent.descriptor,
        )
        os.fchmod(operation_descriptor, 0o700)
        for name in ("control", "temporary"):
            os.mkdir(name, 0o700, dir_fd=operation_descriptor)
        os.fsync(operation_descriptor)
        os.fsync(parent.descriptor)
        parent.require_lexical_binding(description="release-root parent")
    finally:
        if operation_descriptor is not None:
            os.close(operation_descriptor)
        parent.close()


def _operation_id(paths: _ReleasePaths) -> str:
    digest = hashlib.sha256()
    digest.update(b"mpa-public-release-operation-v1\0")
    digest.update(os.urandom(32))
    digest.update(str(paths.operation).encode("utf-8"))
    return digest.hexdigest()


def _snapshot_request(
    snapshot: public_release_state.ReleaseStateSnapshot,
) -> dict[str, object]:
    if not snapshot.events or snapshot.events[0].phase != "initialized":
        raise ValueError("release state lacks its initialized event")
    request = snapshot.events[0].payload.get("request")
    validated = _validate_request(request, screen_metadata=False)
    digest = public_release_state.canonical_json_sha256(validated)
    if digest != snapshot.request_sha256:
        raise ValueError("release request digest does not match initialized state")
    return validated


def _inspect(paths: _ReleasePaths) -> tuple[public_release_state.ReleaseStateSnapshot, dict[str, object]]:
    preliminary = public_release_state.inspect_state(paths.state)
    request = _snapshot_request(preliminary)
    checked = public_release_state.inspect_state(
        paths.state,
        operation_id=preliminary.operation_id,
        request_sha256=public_release_state.canonical_json_sha256(request),
    )
    return checked, request


def _git_environment(paths: _ReleasePaths) -> dict[str, str]:
    return {
        "GIT_ATTR_NOSYSTEM": "1",
        "GIT_CEILING_DIRECTORIES": str(paths.operation),
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_PAGER": "cat",
        "GIT_TERMINAL_PROMPT": "0",
        "LC_ALL": "C",
        "PATH": "/usr/sbin:/usr/bin:/bin",
    }


def _git(
    tools: _Toolset,
    paths: _ReleasePaths,
    arguments: list[str],
    *,
    cwd: Path,
    environment: dict[str, str] | None = None,
    extra_fds: tuple[int, ...] = (),
    timeout_seconds: float = NETWORK_TIMEOUT_SECONDS,
) -> str:
    tools.git.require_current()
    command = [
        tools.git.command,
        "-c",
        "core.fsmonitor=false",
        "-c",
        "hook.post-index-change.enabled=false",
        *arguments,
    ]
    selected_environment = _git_environment(paths)
    if environment:
        selected_environment.update(environment)
    stdout, _stderr = _run(
        command,
        cwd=cwd,
        env=selected_environment,
        pass_fds=tuple(dict.fromkeys((*tools.git.pass_fds, *extra_fds))),
        timeout_seconds=timeout_seconds,
    )
    tools.git.require_current()
    return stdout.decode("utf-8", errors="strict")


def _remote_parent(
    tools: _Toolset,
    paths: _ReleasePaths,
    request: dict[str, object],
) -> str:
    record = _git(
        tools,
        paths,
        [
            "-C",
            str(paths.control),
            "-c",
            "credential.helper=",
            "ls-remote",
            "--upload-pack=git-upload-pack",
            "--refs",
            "--exit-code",
            "--",
            str(request["remote_url"]),
            f"refs/heads/{request['branch']}",
        ],
        cwd=paths.control,
    ).rstrip("\n")
    return public_handoff_lifecycle.parse_remote_parent(
        branch=str(request["branch"]),
        record=record,
    )


def _commit_spec(request: dict[str, object]) -> dict[str, object]:
    return {
        "name": request["public_name"],
        "email": request["public_email"],
        "message": request["commit_message"],
        "timestamp": request["commit_timestamp"],
    }


def _event(
    snapshot: public_release_state.ReleaseStateSnapshot,
    phase: str,
) -> public_release_state.ReleaseEvent | None:
    for event in snapshot.events:
        if event.phase == phase:
            return event
    return None


def _require_checkpoint_tools(
    snapshot: public_release_state.ReleaseStateSnapshot,
    tools: _Toolset,
) -> None:
    export_event = _event(snapshot, "export-verified")
    if export_event is None:
        return
    expected = {
        "git_sha256": tools.git.sha256,
        "python_sha256": tools.python.sha256,
        "uv_sha256": tools.uv.sha256,
    }
    observed = {field: export_event.payload.get(field) for field in expected}
    if observed != expected:
        raise ValueError(
            "release tool generation changed after export verification; "
            "start a new operation root"
        )


def _controller_sha256() -> str:
    scripts_root = _SCRIPT_DIRECTORY
    directory_descriptor = os.open(
        scripts_root,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        directory_before = os.fstat(directory_descriptor)
        named_directory_before = os.lstat(scripts_root)
        if (
            not stat.S_ISDIR(directory_before.st_mode)
            or (directory_before.st_dev, directory_before.st_ino)
            != (named_directory_before.st_dev, named_directory_before.st_ino)
        ):
            raise ValueError("release controller scripts directory is not stable")
        with os.scandir(directory_descriptor) as entries:
            names = tuple(
                sorted(entry.name for entry in entries if entry.name.endswith(".py"))
            )
        if "public_release.py" not in names:
            raise ValueError("release controller bundle omits public_release.py")

        digest = hashlib.sha256()
        digest.update(b"mpa-public-release-controller-bundle-v1\0")
        read_flags = (
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0)
        )
        for name in names:
            named_before = os.stat(
                name,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
            descriptor = os.open(name, read_flags, dir_fd=directory_descriptor)
            try:
                opened_before = os.fstat(descriptor)
                if (
                    not stat.S_ISREG(opened_before.st_mode)
                    or opened_before.st_nlink != 1
                    or (opened_before.st_dev, opened_before.st_ino)
                    != (named_before.st_dev, named_before.st_ino)
                ):
                    raise ValueError(
                        "release controller bundle member is not stable and singly "
                        f"linked: {name}"
                    )
                content_sha256 = _descriptor_sha256(descriptor)
                opened_after = os.fstat(descriptor)
                named_after = os.stat(
                    name,
                    dir_fd=directory_descriptor,
                    follow_symlinks=False,
                )
                stable_fields_before = (
                    opened_before.st_dev,
                    opened_before.st_ino,
                    opened_before.st_uid,
                    opened_before.st_mode,
                    opened_before.st_nlink,
                    opened_before.st_size,
                    opened_before.st_mtime_ns,
                    opened_before.st_ctime_ns,
                )
                stable_fields_after = (
                    opened_after.st_dev,
                    opened_after.st_ino,
                    opened_after.st_uid,
                    opened_after.st_mode,
                    opened_after.st_nlink,
                    opened_after.st_size,
                    opened_after.st_mtime_ns,
                    opened_after.st_ctime_ns,
                )
                if (
                    stable_fields_before != stable_fields_after
                    or (opened_after.st_dev, opened_after.st_ino)
                    != (named_after.st_dev, named_after.st_ino)
                ):
                    raise ValueError(
                        f"release controller bundle member changed while hashed: {name}"
                    )
                digest.update(name.encode("utf-8"))
                digest.update(b"\0")
                digest.update(
                    f"{stat.S_IMODE(opened_after.st_mode):04o}".encode("ascii")
                )
                digest.update(b"\0")
                digest.update(content_sha256.encode("ascii"))
                digest.update(b"\0")
            finally:
                os.close(descriptor)

        with os.scandir(directory_descriptor) as entries:
            terminal_names = tuple(
                sorted(entry.name for entry in entries if entry.name.endswith(".py"))
            )
        directory_after = os.fstat(directory_descriptor)
        named_directory_after = os.lstat(scripts_root)
        if (
            terminal_names != names
            or (directory_before.st_dev, directory_before.st_ino)
            != (directory_after.st_dev, directory_after.st_ino)
            or directory_before.st_mtime_ns != directory_after.st_mtime_ns
            or directory_before.st_ctime_ns != directory_after.st_ctime_ns
            or (directory_after.st_dev, directory_after.st_ino)
            != (named_directory_after.st_dev, named_directory_after.st_ino)
        ):
            raise ValueError("release controller scripts directory changed while hashed")
        return digest.hexdigest()
    finally:
        os.close(directory_descriptor)


def _require_controller_generation(
    snapshot: public_release_state.ReleaseStateSnapshot,
) -> None:
    expected = snapshot.events[0].payload.get("controller_sha256")
    observed = _controller_sha256()
    if expected != observed:
        raise ValueError(
            "release controller generation changed; start a new operation root"
        )


def _clean_json_report(stdout: bytes, *, description: str) -> dict[str, object]:
    try:
        report = safe_paths.loads_json_no_duplicates(stdout.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise ValueError(f"{description} did not emit duplicate-free JSON: {exc}") from exc
    if not isinstance(report, dict):
        raise ValueError(f"{description} must emit one JSON object")
    errors = report.get("errors")
    warnings = report.get("warnings", [])
    if (
        not isinstance(errors, list)
        or not all(isinstance(item, str) for item in errors)
        or not isinstance(warnings, list)
        or not all(isinstance(item, str) for item in warnings)
    ):
        raise ValueError(f"{description} emitted an invalid diagnostic shape")
    if errors or warnings:
        raise ValueError(
            f"{description} was not clean: " + "; ".join([*errors, *warnings])
        )
    return report


def _verify_export(paths: _ReleasePaths, tools: _Toolset) -> str:
    report = public_release_check.check_public_release(
        paths.export,
        tree_role=public_release_check.ReleaseTreeRole.PUBLIC_EXPORT,
    )
    errors = report.get("errors")
    warnings = report.get("warnings")
    if errors or warnings:
        raise ValueError(
            "public export release check failed: "
            + "; ".join(
                str(item)
                for item in [
                    *(errors if isinstance(errors, list) else ["invalid errors"]),
                    *(warnings if isinstance(warnings, list) else ["invalid warnings"]),
                ]
            )
        )
    stdout, _stderr = _run_python(
        tools,
        paths.export / "scripts" / "conformance_check.py",
        [
            "--profile",
            "framework-public-release",
            "--root",
            str(paths.export),
            "--strict-warnings",
            "--format",
            "json",
        ],
        cwd=paths.export,
    )
    _clean_json_report(stdout, description="public export conformance")
    marker = paths.export / public_release_check.PUBLIC_EXPORT_OWNERSHIP_MARKER
    marker_sha256, marker_mode = public_release_check.stable_file_snapshot(marker)
    if marker_mode != public_release_check.PUBLIC_EXPORT_MARKER_MODE:
        raise ValueError("public export marker mode changed")
    return marker_sha256


def _qualify_and_export(
    paths: _ReleasePaths,
    snapshot: public_release_state.ReleaseStateSnapshot,
    request: dict[str, object],
    tools: _Toolset,
) -> public_release_state.ReleaseStateSnapshot:
    if paths.export.exists() or paths.export.is_symlink():
        raise ValueError(
            "an unsealed export exists without an export checkpoint; use a fresh release root"
        )
    authoring = Path(str(request["authoring_root"]))
    source_script = authoring / "scripts" / "framework_compliance.py"
    _run_python(
        tools,
        source_script,
        [
            "--tree-role",
            "authoring-source",
            "--publication-boundary",
            "--git-executable-fd",
            str(tools.git.descriptor),
            "--git-executable-sha256",
            tools.git.sha256,
            "--uv-executable-fd",
            str(tools.uv.descriptor),
            "--uv-executable-sha256",
            tools.uv.sha256,
        ],
        cwd=authoring,
        pass_fds=(*tools.git.pass_fds, *tools.uv.pass_fds),
    )
    _run_python(
        tools,
        authoring / "scripts" / "public_export.py",
        [
            "--root",
            str(authoring),
            "--output",
            str(paths.export),
            "--publication-boundary",
            "--git-executable-fd",
            str(tools.git.descriptor),
            "--git-executable-sha256",
            tools.git.sha256,
        ],
        cwd=authoring,
        pass_fds=tools.git.pass_fds,
    )
    marker_sha256 = _verify_export(paths, tools)
    tools.require_current()
    return public_release_state.append_event(
        paths.state,
        operation_id=snapshot.operation_id,
        request_sha256=snapshot.request_sha256,
        phase="export-verified",
        payload={
            "export_marker_sha256": marker_sha256,
            "git_sha256": tools.git.sha256,
            "python_sha256": tools.python.sha256,
            "uv_sha256": tools.uv.sha256,
        },
    )


def _handoff_receipt(
    *,
    phase: public_handoff_check.HandoffPhase,
    paths: _ReleasePaths,
    request: dict[str, object],
    tools: _Toolset,
    expected_parent: str,
) -> dict[str, object]:
    stdout, _stderr = _run_python(
        tools,
        paths.export / "scripts" / "public_handoff_check.py",
        [
            "--phase",
            phase.value,
            "--export-root",
            str(paths.export),
            "--public-clone-root",
            str(paths.clone),
            "--authoring-root",
            str(request["authoring_root"]),
            "--git-executable-fd",
            str(tools.git.descriptor),
            "--temporary-root",
            str(paths.temporary),
            "--remote-name",
            str(request["remote_name"]),
            "--branch",
            str(request["branch"]),
            "--expected-fetch-url",
            str(request["remote_url"]),
            "--expected-push-url",
            str(request["remote_url"]),
            "--expected-parent-commit",
            expected_parent,
        ],
        cwd=paths.export,
        pass_fds=tools.git.pass_fds,
    )
    report = _clean_json_report(stdout, description=f"{phase.value} handoff")
    if report.get("git_executable_sha256") != tools.git.sha256:
        raise ValueError("handoff receipt did not bind the retained Git executable")
    return report


def _prepare_staged_candidate(
    paths: _ReleasePaths,
    snapshot: public_release_state.ReleaseStateSnapshot,
    request: dict[str, object],
    tools: _Toolset,
) -> public_release_state.ReleaseStateSnapshot:
    marker_sha256 = _verify_export(paths, tools)
    export_event = _event(snapshot, "export-verified")
    if export_event is None or export_event.payload["export_marker_sha256"] != marker_sha256:
        raise ValueError("live public export does not match its durable checkpoint")
    retained_clone = paths.clone.exists() or paths.clone.is_symlink()
    preflight = (
        public_handoff_lifecycle.preflight_existing_clone_inputs
        if retained_clone
        else public_handoff_lifecycle.preflight_network_inputs
    )
    preflight(
        operation_root=paths.operation,
        control_root=paths.control,
        state_root=paths.state,
        temporary_root=paths.temporary,
        export_root=paths.export,
        public_clone_root=paths.clone,
        authoring_root=Path(str(request["authoring_root"])),
        remote_name=str(request["remote_name"]),
        branch=str(request["branch"]),
        fetch_url=str(request["remote_url"]),
        push_url=str(request["remote_url"]),
    )
    expected_parent = _remote_parent(tools, paths, request)
    if not retained_clone:
        _git(
            tools,
            paths,
            [
                "-C",
                str(paths.control),
                "-c",
                "credential.helper=",
                "-c",
                "init.templateDir=",
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "hook.post-checkout.enabled=false",
                "-c",
                "hook.reference-transaction.enabled=false",
                "clone",
                "--upload-pack=git-upload-pack",
                "--no-local",
                "--no-tags",
                "--no-recurse-submodules",
                "--single-branch",
                "--branch",
                str(request["branch"]),
                "--origin",
                str(request["remote_name"]),
                "--",
                str(request["remote_url"]),
                str(paths.clone),
            ],
            cwd=paths.control,
        )
        public_handoff_lifecycle.materialize_export(
            operation_root=paths.operation,
            control_root=paths.control,
            state_root=paths.state,
            temporary_root=paths.temporary,
            export_root=paths.export,
            public_clone_root=paths.clone,
            authoring_root=Path(str(request["authoring_root"])),
        )
        _git(
            tools,
            paths,
            [
                "-c",
                "core.attributesFile=/dev/null",
                "-c",
                "core.hooksPath=/dev/null",
                "--no-optional-locks",
                "-C",
                str(paths.clone),
                "add",
                "--all",
                "--",
            ],
            cwd=paths.clone,
            timeout_seconds=COMMAND_TIMEOUT_SECONDS,
        )
    _git(
        tools,
        paths,
        [
            "-c",
            "core.attributesFile=/dev/null",
            "-c",
            "core.whitespace=blank-at-eol,blank-at-eof,space-before-tab",
            "--no-optional-locks",
            "-C",
            str(paths.clone),
            "diff",
            "--cached",
            "--check",
        ],
        cwd=paths.clone,
        timeout_seconds=COMMAND_TIMEOUT_SECONDS,
    )
    staged = _handoff_receipt(
        phase=public_handoff_check.HandoffPhase.STAGED,
        paths=paths,
        request=request,
        tools=tools,
        expected_parent=expected_parent,
    )
    staged_json = _pretty_json(staged)
    public_handoff_lifecycle.validate_receipt(
        phase=public_handoff_check.HandoffPhase.STAGED,
        receipt_json=staged_json,
        expected_git_sha256=tools.git.sha256,
        baseline_json=None,
        expected_tag_ref=None,
        emit="receipt-sha256",
    )
    return public_release_state.append_event(
        paths.state,
        operation_id=snapshot.operation_id,
        request_sha256=snapshot.request_sha256,
        phase="staged-verified",
        payload={
            "expected_parent": expected_parent,
            "staged_receipt": staged,
            "commit_spec_sha256": public_release_state.canonical_json_sha256(
                _commit_spec(request)
            ),
        },
    )


def _validate_commit_metadata(
    tools: _Toolset,
    paths: _ReleasePaths,
    request: dict[str, object],
    candidate: str,
    expected_parent: str,
) -> None:
    output = _git(
        tools,
        paths,
        [
            "-C",
            str(paths.clone),
            "show",
            "--no-patch",
            "--format=%H%n%P%n%an%n%ae%n%aI%n%cn%n%ce%n%cI%n%B",
            candidate,
        ],
        cwd=paths.clone,
        timeout_seconds=COMMAND_TIMEOUT_SECONDS,
    )
    lines = output.splitlines()
    if len(lines) < 9:
        raise ValueError("candidate metadata output is incomplete")
    expected_prefix = [
        candidate,
        expected_parent,
        str(request["public_name"]),
        str(request["public_email"]),
    ]
    if lines[:4] != expected_prefix or lines[5:7] != expected_prefix[2:]:
        raise ValueError("candidate public identity or parent changed")
    expected_time = datetime.fromisoformat(str(request["commit_timestamp"]))
    observed_times: list[datetime] = []
    for observed in (lines[4], lines[7]):
        try:
            observed_times.append(
                datetime.fromisoformat(
                    observed.removesuffix("Z") + ("+00:00" if observed.endswith("Z") else "")
                )
            )
        except ValueError as exc:
            raise ValueError("candidate timestamp is not ISO 8601") from exc
    if any(observed != expected_time for observed in observed_times):
        raise ValueError("candidate author or committer timestamp changed")
    if "\n".join(lines[8:]).rstrip("\n") != str(request["commit_message"]):
        raise ValueError("candidate public commit message changed")


def _commit_candidate(
    paths: _ReleasePaths,
    snapshot: public_release_state.ReleaseStateSnapshot,
    request: dict[str, object],
    tools: _Toolset,
) -> public_release_state.ReleaseStateSnapshot:
    staged_event = _event(snapshot, "staged-verified")
    if staged_event is None:
        raise ValueError("candidate creation requires a staged checkpoint")
    expected_parent = staged_event.payload["expected_parent"]
    staged = staged_event.payload["staged_receipt"]
    if not isinstance(expected_parent, str) or _FULL_OID_RE.fullmatch(expected_parent) is None:
        raise ValueError("staged checkpoint has an invalid parent")
    if not isinstance(staged, dict):
        raise ValueError("staged checkpoint has an invalid handoff receipt")
    if staged_event.payload["commit_spec_sha256"] != public_release_state.canonical_json_sha256(
        _commit_spec(request)
    ):
        raise ValueError("commit specification changed after staged verification")

    head = _git(
        tools,
        paths,
        ["-C", str(paths.clone), "rev-parse", "--verify", "HEAD"],
        cwd=paths.clone,
        timeout_seconds=COMMAND_TIMEOUT_SECONDS,
    ).strip()
    if head == expected_parent:
        live_staged = _handoff_receipt(
            phase=public_handoff_check.HandoffPhase.STAGED,
            paths=paths,
            request=request,
            tools=tools,
            expected_parent=expected_parent,
        )
        if _pretty_json(live_staged) != _pretty_json(staged):
            raise ValueError("staged handoff changed before candidate creation")
        timestamp = str(request["commit_timestamp"])
        commit_environment = {
            "GIT_AUTHOR_DATE": timestamp,
            "GIT_AUTHOR_EMAIL": str(request["public_email"]),
            "GIT_AUTHOR_NAME": str(request["public_name"]),
            "GIT_COMMITTER_DATE": timestamp,
            "GIT_COMMITTER_EMAIL": str(request["public_email"]),
            "GIT_COMMITTER_NAME": str(request["public_name"]),
            "TZ": "UTC",
        }
        _git(
            tools,
            paths,
            [
                "-c",
                "core.attributesFile=/dev/null",
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "hook.commit-msg.enabled=false",
                "-c",
                "hook.post-commit.enabled=false",
                "-c",
                "hook.pre-commit.enabled=false",
                "-c",
                "hook.prepare-commit-msg.enabled=false",
                "-c",
                "hook.reference-transaction.enabled=false",
                "-c",
                "commit.gpgSign=false",
                "-c",
                "commit.cleanup=verbatim",
                "-c",
                f"user.name={request['public_name']}",
                "-c",
                f"user.email={request['public_email']}",
                "--no-optional-locks",
                "-C",
                str(paths.clone),
                "commit",
                "--no-verify",
                "--no-gpg-sign",
                "--cleanup=verbatim",
                "--message",
                str(request["commit_message"]),
            ],
            cwd=paths.clone,
            environment=commit_environment,
            timeout_seconds=COMMAND_TIMEOUT_SECONDS,
        )
        head = _git(
            tools,
            paths,
            ["-C", str(paths.clone), "rev-parse", "--verify", "HEAD"],
            cwd=paths.clone,
            timeout_seconds=COMMAND_TIMEOUT_SECONDS,
        ).strip()
    if _FULL_OID_RE.fullmatch(head) is None:
        raise ValueError("candidate commit is not a full object ID")
    committed = _handoff_receipt(
        phase=public_handoff_check.HandoffPhase.COMMITTED,
        paths=paths,
        request=request,
        tools=tools,
        expected_parent=expected_parent,
    )
    committed_json = _pretty_json(committed)
    candidate = public_handoff_lifecycle.validate_receipt(
        phase=public_handoff_check.HandoffPhase.COMMITTED,
        receipt_json=committed_json,
        expected_git_sha256=tools.git.sha256,
        baseline_json=_pretty_json(staged),
        expected_tag_ref=None,
        emit="candidate-commit",
    )
    if candidate != head:
        raise ValueError("committed handoff candidate does not equal clone HEAD")
    _validate_commit_metadata(
        tools,
        paths,
        request,
        candidate,
        expected_parent,
    )
    return public_release_state.append_event(
        paths.state,
        operation_id=snapshot.operation_id,
        request_sha256=snapshot.request_sha256,
        phase="candidate-verified",
        payload={
            "candidate_commit": candidate,
            "committed_receipt": committed,
            "staged_receipt_sha256": public_release_state.canonical_json_sha256(staged),
        },
    )


def _revalidate_candidate(
    paths: _ReleasePaths,
    snapshot: public_release_state.ReleaseStateSnapshot,
    request: dict[str, object],
    tools: _Toolset,
) -> tuple[str, str]:
    _require_checkpoint_tools(snapshot, tools)
    marker_sha256 = _verify_export(paths, tools)
    export_event = _event(snapshot, "export-verified")
    staged_event = _event(snapshot, "staged-verified")
    candidate_event = _event(snapshot, "candidate-verified")
    if export_event is None or staged_event is None or candidate_event is None:
        raise ValueError("candidate revalidation requires export, staged, and candidate receipts")
    if export_event.payload["export_marker_sha256"] != marker_sha256:
        raise ValueError("public export changed after qualification")
    staged = staged_event.payload["staged_receipt"]
    committed = candidate_event.payload["committed_receipt"]
    expected_parent = staged_event.payload["expected_parent"]
    candidate = candidate_event.payload["candidate_commit"]
    if (
        not isinstance(staged, dict)
        or not isinstance(committed, dict)
        or not isinstance(expected_parent, str)
        or not isinstance(candidate, str)
    ):
        raise ValueError("candidate checkpoint has invalid typed bindings")
    if candidate_event.payload["staged_receipt_sha256"] != public_release_state.canonical_json_sha256(staged):
        raise ValueError("candidate checkpoint lost staged-receipt continuity")
    live = _handoff_receipt(
        phase=public_handoff_check.HandoffPhase.COMMITTED,
        paths=paths,
        request=request,
        tools=tools,
        expected_parent=expected_parent,
    )
    if _pretty_json(live) != _pretty_json(committed):
        raise ValueError("live committed handoff differs from the durable receipt")
    live_candidate = public_handoff_lifecycle.validate_receipt(
        phase=public_handoff_check.HandoffPhase.COMMITTED,
        receipt_json=_pretty_json(live),
        expected_git_sha256=tools.git.sha256,
        baseline_json=_pretty_json(staged),
        expected_tag_ref=None,
        emit="candidate-commit",
    )
    if live_candidate != candidate:
        raise ValueError("live candidate differs from the durable candidate")
    _validate_commit_metadata(
        tools,
        paths,
        request,
        candidate,
        expected_parent,
    )
    return candidate, expected_parent


def _validate_github_config(config_directory: Path) -> Path:
    config_directory = _canonical_absolute(
        config_directory,
        description="GitHub CLI config directory",
    )
    metadata = os.lstat(config_directory)
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_mode & 0o022
    ):
        raise ValueError(
            "GitHub CLI config directory must be current-user-owned and not "
            "group/world writable"
        )
    hosts = config_directory / "hosts.yml"
    hosts_metadata = os.lstat(hosts)
    if (
        not stat.S_ISREG(hosts_metadata.st_mode)
        or hosts_metadata.st_uid != os.geteuid()
        or hosts_metadata.st_nlink != 1
        or stat.S_IMODE(hosts_metadata.st_mode) & 0o077
    ):
        raise ValueError("GitHub CLI hosts.yml must be one owner-only regular file")
    return config_directory


def _github_credential_helper(descriptor: int) -> str:
    if descriptor < 0:
        raise ValueError("GitHub CLI descriptor must be nonnegative")
    # Git appends the credential operation (get/store/erase) to this shell
    # command, so gh receives it as its third argument.
    return f"!/proc/self/fd/{descriptor} auth git-credential"


def _append_push_observed(
    paths: _ReleasePaths,
    snapshot: public_release_state.ReleaseStateSnapshot,
    candidate: str,
) -> public_release_state.ReleaseStateSnapshot:
    if _event(snapshot, "push-observed") is not None:
        return snapshot
    return public_release_state.append_event(
        paths.state,
        operation_id=snapshot.operation_id,
        request_sha256=snapshot.request_sha256,
        phase="push-observed",
        payload={"candidate_commit": candidate},
    )


def _candidate_was_observed(snapshot: public_release_state.ReleaseStateSnapshot) -> bool:
    if _event(snapshot, "push-observed") is not None:
        return True
    publication = _event(snapshot, "publication-bound")
    return (
        publication is not None
        and publication.payload.get("mode") == "adopt-observed-candidate"
    )


def _append_reconciliation_binding(
    paths: _ReleasePaths,
    snapshot: public_release_state.ReleaseStateSnapshot,
    request: dict[str, object],
    candidate: str,
    expected_parent: str,
) -> public_release_state.ReleaseStateSnapshot:
    """Bind an already-published candidate without inventing credential use."""

    if _event(snapshot, "publication-bound") is not None:
        return snapshot
    refspec = f"{candidate}:refs/heads/{request['branch']}"
    return public_release_state.append_event(
        paths.state,
        operation_id=snapshot.operation_id,
        request_sha256=snapshot.request_sha256,
        phase="publication-bound",
        payload={
            "candidate_commit": candidate,
            "expected_parent": expected_parent,
            "refspec_sha256": hashlib.sha256(refspec.encode("utf-8")).hexdigest(),
            "credential_boundary_sha256": NO_CREDENTIAL_BOUNDARY_SHA256,
            "mode": "adopt-observed-candidate",
        },
    )


def _complete_readback(
    paths: _ReleasePaths,
    snapshot: public_release_state.ReleaseStateSnapshot,
    request: dict[str, object],
    tools: _Toolset,
    candidate: str,
) -> public_release_state.ReleaseStateSnapshot:
    remote = _remote_parent(tools, paths, request)
    public_handoff_lifecycle.verify_remote_readback(
        branch=str(request["branch"]),
        branch_records=f"{remote}\trefs/heads/{request['branch']}",
        candidate_commit=candidate,
        tag_ref=None,
        tag_records=None,
        tag_oid=None,
        tag_object_type=None,
    )
    if _event(snapshot, "readback-verified") is not None:
        return snapshot
    return public_release_state.append_event(
        paths.state,
        operation_id=snapshot.operation_id,
        request_sha256=snapshot.request_sha256,
        phase="readback-verified",
        payload={"candidate_commit": candidate},
    )


def _publish(
    paths: _ReleasePaths,
    snapshot: public_release_state.ReleaseStateSnapshot,
    request: dict[str, object],
    tools: _Toolset,
    *,
    approved_candidate: str,
    github_cli_path: Path | None,
    github_config_directory: Path | None,
    approved_retry_event: str | None = None,
) -> public_release_state.ReleaseStateSnapshot:
    candidate, expected_parent = _revalidate_candidate(
        paths,
        snapshot,
        request,
        tools,
    )
    if approved_candidate != candidate:
        raise ValueError("approved candidate does not equal the verified candidate")
    remote = _remote_parent(tools, paths, request)
    if remote == candidate:
        snapshot = _append_reconciliation_binding(
            paths,
            snapshot,
            request,
            candidate,
            expected_parent,
        )
        snapshot = _append_push_observed(paths, snapshot, candidate)
        return _complete_readback(paths, snapshot, request, tools, candidate)
    if remote != expected_parent:
        raise ValueError(
            "remote branch is neither the recorded parent nor the candidate; "
            "publication is blocked as a remote conflict"
        )
    if _candidate_was_observed(snapshot):
        raise ValueError(
            "remote returned to the old parent after the candidate was observed; "
            "do not repush"
        )
    publication = _event(snapshot, "publication-bound")
    if publication is None:
        if approved_retry_event is not None:
            raise ValueError(
                "retry-event approval was supplied before any publication binding"
            )
    elif approved_retry_event != publication.sha256:
        raise ValueError(
            "an existing controller-push publication binding is ambiguous; "
            "retry requires exact approval of its event SHA-256"
        )
    if github_cli_path is None or github_config_directory is None:
        raise ValueError(
            "remote still equals the parent; an exact GitHub CLI credential boundary "
            "is required to perform the push"
        )
    github_config_directory = _validate_github_config(github_config_directory)
    github = _open_executable(github_cli_path, description="GitHub CLI")
    try:
        refspec = f"{candidate}:refs/heads/{request['branch']}"
        refspec_sha256 = hashlib.sha256(refspec.encode("utf-8")).hexdigest()
        publication = _event(snapshot, "publication-bound")
        if publication is None:
            snapshot = public_release_state.append_event(
                paths.state,
                operation_id=snapshot.operation_id,
                request_sha256=snapshot.request_sha256,
                phase="publication-bound",
                payload={
                    "candidate_commit": candidate,
                    "expected_parent": expected_parent,
                    "refspec_sha256": refspec_sha256,
                    "credential_boundary_sha256": github.sha256,
                    "mode": "controller-push",
                },
            )
        else:
            expected_publication = {
                "candidate_commit": candidate,
                "expected_parent": expected_parent,
                "refspec_sha256": refspec_sha256,
                "credential_boundary_sha256": github.sha256,
                "mode": "controller-push",
            }
            if publication.payload != expected_publication:
                raise ValueError(
                    "push credential or refspec changed after publication binding"
                )
        github.require_current()
        helper = _github_credential_helper(github.descriptor)
        push_failed: RuntimeError | None = None
        try:
            _git(
                tools,
                paths,
                [
                    "-c",
                    "credential.helper=",
                    "-c",
                    f"credential.helper={helper}",
                    "-c",
                    "core.hooksPath=/dev/null",
                    "-c",
                    "hook.pre-push.enabled=false",
                    "-c",
                    "hook.reference-transaction.enabled=false",
                    "-C",
                    str(paths.clone),
                    "push",
                    f"--force-with-lease=refs/heads/{request['branch']}:{expected_parent}",
                    "--receive-pack=git-receive-pack",
                    "--no-verify",
                    "--no-follow-tags",
                    "--no-tags",
                    "--no-recurse-submodules",
                    "--no-mirror",
                    "--no-signed",
                    "--no-push-option",
                    str(request["remote_name"]),
                    refspec,
                ],
                cwd=paths.clone,
                environment={"GH_CONFIG_DIR": str(github_config_directory)},
                extra_fds=github.pass_fds,
            )
        except RuntimeError as exc:
            push_failed = exc
        github.require_current()
        observed = _remote_parent(tools, paths, request)
        if observed == candidate:
            snapshot = _append_push_observed(paths, snapshot, candidate)
            return _complete_readback(paths, snapshot, request, tools, candidate)
        if observed == expected_parent:
            if push_failed is not None:
                raise RuntimeError(
                    "push failed before a remote mutation; the verified candidate and "
                    "publication binding remain retryable"
                ) from push_failed
            raise RuntimeError(
                "push command succeeded but the remote still equals the parent; "
                "publication remains unresolved and must not be reported complete"
            )
        raise ValueError(
            "remote changed to a third object after publication binding; "
            "publication is blocked"
        )
    finally:
        github.close()


def _advance_to_candidate(
    paths: _ReleasePaths,
    snapshot: public_release_state.ReleaseStateSnapshot,
    request: dict[str, object],
    tools: _Toolset,
) -> public_release_state.ReleaseStateSnapshot:
    _require_checkpoint_tools(snapshot, tools)
    if snapshot.phase == "initialized":
        snapshot = _qualify_and_export(paths, snapshot, request, tools)
        _require_checkpoint_tools(snapshot, tools)
    if snapshot.phase == "export-verified":
        snapshot = _prepare_staged_candidate(paths, snapshot, request, tools)
    if snapshot.phase == "staged-verified":
        snapshot = _commit_candidate(paths, snapshot, request, tools)
    if snapshot.phase in {
        "candidate-verified",
        "publication-bound",
        "push-observed",
        "readback-verified",
    }:
        _revalidate_candidate(paths, snapshot, request, tools)
        return snapshot
    raise ValueError(f"unsupported release resume phase: {snapshot.phase}")


def _status_payload(
    snapshot: public_release_state.ReleaseStateSnapshot,
) -> dict[str, object]:
    candidate_event = _event(snapshot, "candidate-verified")
    candidate = (
        candidate_event.payload["candidate_commit"]
        if candidate_event is not None
        else None
    )
    nominal_next_action = {
        "initialized": "resume",
        "export-verified": "resume",
        "staged-verified": "resume",
        "candidate-verified": "publish",
        "publication-bound": "publish-reconcile",
        "push-observed": "readback",
        "readback-verified": "complete",
    }[snapshot.phase]
    return {
        "candidate_commit": candidate,
        "errors": [],
        "event_count": len(snapshot.events),
        "last_event_sha256": snapshot.latest_event_sha256,
        "nominal_next_action": nominal_next_action,
        "operation_id": snapshot.operation_id,
        "phase": snapshot.phase,
        "schema_version": 1,
        "status": "complete" if snapshot.phase == "readback-verified" else "in-progress",
    }


def _prepare(args: argparse.Namespace) -> dict[str, object]:
    paths = _release_paths(args.release_root)
    request = _request_from_args(args)
    authoring = Path(str(request["authoring_root"]))
    if (
        paths.operation == authoring
        or safe_paths.path_within_root(paths.operation, authoring)
        or safe_paths.path_within_root(authoring, paths.operation)
    ):
        raise ValueError("release and authoring roots must be distinct and non-nested")
    _initialize_operation(paths)
    snapshot = public_release_state.init_state(
        paths.state,
        operation_id=_operation_id(paths),
        request=request,
        controller_sha256=_controller_sha256(),
    )
    with public_release_state.operation_lease(paths.state):
        tools = _open_tools(request)
        try:
            snapshot = _advance_to_candidate(paths, snapshot, request, tools)
        finally:
            tools.close()
    return _status_payload(snapshot)


def _resume(args: argparse.Namespace) -> dict[str, object]:
    paths = _release_paths(args.release_root)
    with public_release_state.operation_lease(paths.state):
        snapshot, request = _inspect(paths)
        _require_controller_generation(snapshot)
        tools = _open_tools(request)
        try:
            snapshot = _advance_to_candidate(paths, snapshot, request, tools)
        finally:
            tools.close()
    return _status_payload(snapshot)


def _publish_command(args: argparse.Namespace) -> dict[str, object]:
    paths = _release_paths(args.release_root)
    with public_release_state.operation_lease(paths.state):
        snapshot, request = _inspect(paths)
        _require_controller_generation(snapshot)
        tools = _open_tools(request)
        try:
            snapshot = _publish(
                paths,
                snapshot,
                request,
                tools,
                approved_candidate=args.approve_candidate,
                github_cli_path=args.github_cli,
                github_config_directory=args.github_config_dir,
                approved_retry_event=args.approve_retry_event,
            )
        finally:
            tools.close()
    return _status_payload(snapshot)


def _status(args: argparse.Namespace) -> dict[str, object]:
    paths = _release_paths(args.release_root)
    snapshot, _request = _inspect(paths)
    _require_controller_generation(snapshot)
    return _status_payload(snapshot)


def _readback_command(args: argparse.Namespace) -> dict[str, object]:
    paths = _release_paths(args.release_root)
    with public_release_state.operation_lease(paths.state):
        snapshot, request = _inspect(paths)
        _require_controller_generation(snapshot)
        if _event(snapshot, "publication-bound") is None:
            raise ValueError("readback requires a durable publication binding")
        tools = _open_tools(request)
        try:
            candidate, expected_parent = _revalidate_candidate(
                paths,
                snapshot,
                request,
                tools,
            )
            remote = _remote_parent(tools, paths, request)
            if remote == candidate:
                snapshot = _append_push_observed(paths, snapshot, candidate)
                snapshot = _complete_readback(
                    paths,
                    snapshot,
                    request,
                    tools,
                    candidate,
                )
            elif remote == expected_parent:
                if _candidate_was_observed(snapshot):
                    raise ValueError(
                        "remote returned to the recorded parent after the candidate "
                        "was observed; do not repush or report publication complete"
                    )
            else:
                raise ValueError(
                    "remote readback found a third object; publication is blocked"
                )
        finally:
            tools.close()
    return _status_payload(snapshot)


def _add_release_root(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--release-root",
        type=Path,
        required=True,
        help="Exact absolute owner-only root for this release operation.",
    )


def _parser() -> _Parser:
    parser = _Parser(
        description="Durable verified public framework release controller.",
        allow_abbrev=False,
    )
    commands = parser.add_subparsers(dest="command", required=True)

    prepare = commands.add_parser(
        "prepare",
        allow_abbrev=False,
        help="Qualify, export, clone, stage, and create one verified candidate.",
        description=(
            "Qualify the authoring source and create one verified public candidate."
        ),
    )
    _add_release_root(prepare)
    prepare.add_argument(
        "--authoring-root",
        type=Path,
        required=True,
        help="Exact absolute root of this controller's framework checkout.",
    )
    prepare.add_argument(
        "--git-executable",
        type=Path,
        required=True,
        help="Resolved absolute path to the reviewed Git executable.",
    )
    prepare.add_argument(
        "--uv-executable",
        type=Path,
        required=True,
        help="Resolved absolute path to the reviewed uv executable.",
    )
    prepare.add_argument(
        "--python-executable",
        type=Path,
        required=True,
        help="Resolved absolute path to the Python running this controller.",
    )
    prepare.add_argument(
        "--remote-name",
        required=True,
        help="Exact ordinary Git remote name, normally origin.",
    )
    prepare.add_argument(
        "--branch",
        required=True,
        help="Exact direct-commit public branch name.",
    )
    prepare.add_argument(
        "--remote-url",
        required=True,
        help="One credential-free lowercase HTTPS URL used for fetch and push.",
    )
    prepare.add_argument(
        "--public-name",
        required=True,
        help="Single-line public Git author and committer name.",
    )
    prepare.add_argument(
        "--public-email",
        required=True,
        help="Public Git author and committer email address.",
    )
    prepare.add_argument(
        "--commit-message",
        required=True,
        help="Professional public commit message, bounded to 512 characters.",
    )
    prepare.add_argument(
        "--commit-timestamp",
        help=(
            "Optional canonical offset-aware ISO 8601 timestamp. When omitted, "
            "prepare fixes the current UTC second in durable state."
        ),
    )

    for name, help_text in (
        ("resume", "Resume preparation from the last fully validated phase."),
        ("status", "Inspect the canonical checkpoint chain without network use."),
        (
            "readback",
            "Reconcile a durable publication binding without issuing another push.",
        ),
    ):
        command = commands.add_parser(
            name,
            allow_abbrev=False,
            help=help_text,
            description=help_text,
        )
        _add_release_root(command)

    publish = commands.add_parser(
        "publish",
        allow_abbrev=False,
        help="Push one exactly approved candidate with CAS and verify remote readback.",
        description=(
            "Publish one exactly approved candidate and verify remote readback."
        ),
    )
    _add_release_root(publish)
    publish.add_argument(
        "--approve-candidate",
        required=True,
        help="Exact full candidate object ID authorized for publication.",
    )
    publish.add_argument(
        "--approve-retry-event",
        help=(
            "Exact publication-bound event SHA-256 authorizing one deliberate "
            "retry after an ambiguous prior controller-push attempt."
        ),
    )
    publish.add_argument(
        "--github-cli",
        type=Path,
        help="Resolved GitHub CLI executable used only as an in-memory credential helper.",
    )
    publish.add_argument(
        "--github-config-dir",
        type=Path,
        help="Exact GitHub CLI config directory; never persisted in release state.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        if args.command == "prepare":
            result = _prepare(args)
        elif args.command == "resume":
            result = _resume(args)
        elif args.command == "status":
            result = _status(args)
        elif args.command == "publish":
            if _FULL_OID_RE.fullmatch(args.approve_candidate) is None:
                raise ValueError("approved candidate must be one full lowercase object ID")
            if (args.github_cli is None) != (args.github_config_dir is None):
                raise ValueError(
                    "GitHub CLI executable and config directory must be supplied together"
                )
            if (
                args.approve_retry_event is not None
                and _SHA256_RE.fullmatch(args.approve_retry_event) is None
            ):
                raise ValueError(
                    "approved retry event must be one lowercase SHA-256 digest"
                )
            result = _publish_command(args)
        elif args.command == "readback":
            result = _readback_command(args)
        else:
            raise ValueError("unsupported release command")
        sys.stdout.write(_pretty_json(result))
        return 0
    except (
        _CliError,
        OSError,
        RuntimeError,
        ValueError,
        bounded_subprocess.BoundedSubprocessError,
    ) as exc:
        sys.stderr.write(f"public release failed: {exc}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
