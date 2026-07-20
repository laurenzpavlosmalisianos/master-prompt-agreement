#!/usr/bin/env python3

"""Prove that one verified export is the exact public Git candidate.

The command neither fetches nor changes protected roots, the worktree, index,
refs, configuration, commits, remotes, or object stores. It creates and removes
only bounded parser scratch state below an explicit isolated temporary root.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from enum import StrEnum
import hashlib
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
from collections.abc import Callable
from typing import NoReturn
from urllib.parse import unquote, urlsplit

import bounded_subprocess
import public_release_check
import public_surface
import resource_cleanup
import safe_paths


HANDOFF_SCHEMA_VERSION = 4
HANDOFF_CONTINUITY_FIELDS = (
    "schema_version",
    "branch",
    "expected_parent_commit",
    "export_marker_sha256",
    "git_executable_sha256",
    "object_format",
    "payload_file_count",
    "remote_name",
    "remote_target_sha256",
)
HANDOFF_RECEIPT_FIELDS = frozenset(
    {
        *HANDOFF_CONTINUITY_FIELDS,
        "candidate_commit",
        "errors",
        "notes",
        "phase",
        "tag_object_type",
        "tag_oid",
        "tag_peeled_commit",
        "tag_ref",
    }
)
_GIT_ENVIRONMENT = {
    "GIT_ATTR_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_NO_LAZY_FETCH": "1",
    "GIT_NO_REPLACE_OBJECTS": "1",
    "GIT_OPTIONAL_LOCKS": "0",
}
_REMOTE_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_FULL_OID_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
_REMOTE_HELPER_URL_RE = re.compile(r"[A-Za-z][A-Za-z0-9+._-]*::")
_SCP_STYLE_SSH_URL_RE = re.compile(
    r"(?P<username>[A-Za-z0-9._-]+)@"
    r"(?P<host>[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?):"
    r"(?P<path>[^\\\r\n]+)"
)
_DNS_LABEL_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?")
_SSH_USERNAME_RE = re.compile(r"[A-Za-z0-9._-]+")
_URL_PROVIDER_TOKEN_RE = re.compile(
    r"(?:"
    r"gh[pousr]_[A-Za-z0-9]{20,}"
    r"|github_pat_[A-Za-z0-9_]{30,}"
    r"|glpat-[A-Za-z0-9_-]{20,}"
    r")",
    re.IGNORECASE,
)
_PUBLIC_REMOTE_URL_SCHEMES = frozenset({"git+ssh", "https", "ssh", "ssh+git"})
_NATIVE_GIT_URL_SCHEMES = frozenset(
    {"file", "ftp", "ftps", "git", "git+ssh", "http", "https", "ssh", "ssh+git"}
)
_REMOTE_TARGET_BINDING_DOMAIN = b"mpa-public-handoff-remote-target-v1\0"
_GIT_EXECUTABLE_MAX_BYTES = 256 * 1024 * 1024
_GIT_CONTROL_FILE_MAX_BYTES = 16 * 1024 * 1024
_GIT_CONTROL_HASH_MAX_BYTES = 64 * 1024 * 1024
_GIT_CONTROL_MAX_ENTRIES = 100_000
_GIT_CONTROL_OPAQUE_DIRECTORIES = frozenset({"objects"})
_AUTHORING_FSMONITOR_IPC_ROOT_ENTRY = "fsmonitor--daemon.ipc"
_LOCAL_VERIFIER_SOURCES = (
    ("public_handoff_check", "scripts/public_handoff_check.py"),
    ("public_release_check", "scripts/public_release_check.py"),
    ("public_surface", "scripts/public_surface.py"),
    ("resource_cleanup", "scripts/resource_cleanup.py"),
    ("safe_paths", "scripts/safe_paths.py"),
    ("bounded_subprocess", "scripts/bounded_subprocess.py"),
)


class HandoffPhase(StrEnum):
    STAGED = "staged"
    COMMITTED = "committed"


@dataclass(frozen=True)
class _ExpectedFile:
    sha256: str
    size: int
    posix_mode: int
    git_mode: str
    git_oid: str


@dataclass(frozen=True)
class _ObjectStoreSnapshot:
    signature: tuple[object, ...]
    file_identities: frozenset[tuple[int, int]]
    directory_identities: frozenset[tuple[int, int]]


@dataclass(frozen=True)
class _GitControlSnapshot:
    signatures: tuple[tuple[str, tuple[object, ...]], ...]
    file_identities: frozenset[tuple[int, int]]
    directory_identities: frozenset[tuple[int, int]]
    critical_digests: tuple[tuple[str, str, int, str], ...]
    opaque_entries: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class _GitControlInventory:
    tree: public_release_check._TreeInventory
    opaque_entries: tuple[str, ...]


@dataclass(frozen=True)
class _TagState:
    ref: str
    oid: str
    object_type: str
    peeled_commit: str


@dataclass
class _GitStorageBinding:
    metadata: public_release_check._GitMetadataBinding
    gitdir: safe_paths.OutputDirectoryBinding
    common: safe_paths.OutputDirectoryBinding
    objects: safe_paths.OutputDirectoryBinding
    _closed: bool = False

    def require_current(self, *, description: str) -> None:
        self.gitdir.require_unchanged_chain(
            description=f"{description} Git directory"
        )
        self.common.require_unchanged_chain(
            description=f"{description} Git common directory"
        )
        self.objects.require_unchanged_chain(
            description=f"{description} Git object directory"
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        resource_cleanup.cleanup_actions(
            (
                ("Git object-directory binding", self.objects.close),
                ("Git common-directory binding", self.common.close),
                ("Git directory binding", self.gitdir.close),
            )
        )


@dataclass
class _GitExecutableBinding:
    file: public_release_check._RegularFileBinding | _InheritedDescriptorBinding
    sha256: str
    _closed: bool = False

    @property
    def command(self) -> str:
        descriptor_path = Path("/proc/self/fd") / str(self.file.descriptor)
        if not descriptor_path.exists():
            raise RuntimeError(
                "bound Git execution requires Linux procfs descriptor paths"
            )
        return str(descriptor_path)

    @property
    def pass_fds(self) -> tuple[int, ...]:
        return (self.file.descriptor,)

    def require_current(self) -> None:
        self.file.require_current(description="reviewed Git executable")
        if _git_executable_sha256(self.file) != self.sha256:
            raise ValueError("reviewed Git executable changed during handoff verification")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.require_current()
        except BaseException as primary:
            resource_cleanup.cleanup_actions(
                (("reviewed Git executable binding", self.file.close),),
                primary=primary,
            )
            raise
        self.file.close()


@dataclass
class _InheritedDescriptorBinding:
    descriptor: int
    metadata: os.stat_result
    lexical_path: Path
    _closed: bool = False

    def require_current(self, *, description: str) -> None:
        current = os.fstat(self.descriptor)
        if safe_paths.stable_file_metadata(current) != safe_paths.stable_file_metadata(
            self.metadata
        ):
            raise ValueError(f"{description} inherited descriptor changed")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        os.close(self.descriptor)


@dataclass(frozen=True)
class _GitState:
    head_ref: str
    head: str
    remote_tracking: str
    upstream: str
    fetch_urls: tuple[str, ...]
    push_urls: tuple[str, ...]
    branch_push_remote: tuple[str, ...]
    default_push_remote: tuple[str, ...]
    remote_push_refspecs: tuple[str, ...]
    remote_mirror: tuple[str, ...]
    remote_receivepack: tuple[str, ...]
    remote_vcs: tuple[str, ...]
    remote_proxy: tuple[str, ...]
    push_default: tuple[str, ...]
    push_follow_tags: tuple[str, ...]
    push_gpg_sign: tuple[str, ...]
    push_options: tuple[str, ...]
    core_ssh_command: tuple[str, ...]
    core_ask_pass: tuple[str, ...]
    core_attributes_file: tuple[str, ...]
    core_git_proxy: tuple[str, ...]
    core_hooks_path: tuple[str, ...]
    effective_http_config_keys: tuple[str, ...]
    effective_http_proxies: tuple[tuple[str, tuple[str, ...]], ...]
    replacement_refs: tuple[str, ...]
    core_whitespace: tuple[str, ...]
    candidate_blobs: tuple[tuple[str, int, str], ...]
    parents: tuple[str, ...]
    committed_tree: tuple[tuple[str, str, str], ...]
    tag: _TagState | None


class _CliError(ValueError):
    pass


class _JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise _CliError(message)


def _base_report(
    *,
    phase: HandoffPhase | None,
    remote_name: str | None,
    branch: str | None,
    expected_parent_commit: str | None,
    tag_ref: str | None,
) -> dict[str, object]:
    return {
        "branch": branch,
        "candidate_commit": None,
        "errors": [],
        "expected_parent_commit": expected_parent_commit,
        "export_marker_sha256": None,
        "git_executable_sha256": None,
        "notes": [
            "This read-only check performs no fetch; the caller must supply a "
            "fresh full remote parent commit."
        ],
        "object_format": None,
        "payload_file_count": 0,
        "phase": phase.value if phase is not None else None,
        "remote_name": remote_name,
        "remote_target_sha256": None,
        "schema_version": HANDOFF_SCHEMA_VERSION,
        "tag_object_type": None,
        "tag_oid": None,
        "tag_peeled_commit": None,
        "tag_ref": tag_ref,
    }


def _canonical_json(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def _remote_target_sha256(
    *,
    remote_name: str,
    fetch_url: str,
    push_url: str,
    object_format: str,
) -> str:
    digest = hashlib.sha256(_REMOTE_TARGET_BINDING_DOMAIN)
    for label, value in (
        ("remote-name", remote_name),
        ("fetch-url", fetch_url),
        ("push-url", push_url),
        ("object-format", object_format),
    ):
        encoded = value.encode("utf-8")
        digest.update(label.encode("ascii"))
        digest.update(b"\0")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()


def _safe_branch_name(value: str) -> bool:
    if (
        not value
        or value == "HEAD"
        or len(value) > 255
        or value.startswith(("-", "/", "."))
        or value.endswith(("/", ".", ".lock"))
        or "//" in value
        or ".." in value
        or "@{" in value
        or "\\" in value
        or any(
            character.isspace() or ord(character) < 32 or ord(character) == 127
            for character in value
        )
        or any(character in "~^:?*[" for character in value)
    ):
        return False
    return all(
        part not in {"", ".", "..", "@"}
        and not part.startswith(".")
        and not part.endswith(".lock")
        for part in value.split("/")
    )


def _safe_remote_name(value: str) -> bool:
    return (
        _REMOTE_NAME_RE.fullmatch(value) is not None
        and ".." not in value
        and not value.endswith((".", ".lock"))
    )


def _safe_full_tag_ref(value: str) -> bool:
    """Accept one bounded full tag ref without relying on Git's DWIM rules."""

    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    if (
        not value.startswith("refs/tags/")
        or len(encoded) > 1024
        or value.endswith(("/", "."))
        or "//" in value
        or ".." in value
        or "@{" in value
        or "\\" in value
        or any(
            character.isspace() or ord(character) < 32 or ord(character) == 127
            for character in value
        )
        or any(character in "~^:?*[" for character in value)
    ):
        return False
    tag = value.removeprefix("refs/tags/")
    parts = tag.split("/")
    return bool(tag) and all(
        part
        and part not in {".", "..", "@"}
        and not part.startswith(".")
        and not part.endswith(".lock")
        for part in parts
    )


def publication_branch_ref(branch: str) -> str:
    """Return the exact full publication branch ref or fail closed."""

    if not _safe_branch_name(branch):
        raise ValueError("branch must be a canonical bounded Git branch name")
    return f"refs/heads/{branch}"


def publication_remote_name_is_safe(remote_name: str) -> bool:
    """Expose the exact bounded remote-name policy to lifecycle support."""

    return _safe_remote_name(remote_name)


def publication_tag_ref_is_safe(tag_ref: str) -> bool:
    """Expose the checker's exact full-tag-ref policy to lifecycle support."""

    return _safe_full_tag_ref(tag_ref)


def _userinfo_is_credential(username: str | None, password: str | None) -> bool:
    if password is not None:
        return True
    if username is None:
        return False
    decoded = unquote(username)
    return bool(
        public_release_check.sensitive_value_kinds(decoded)
        or _URL_PROVIDER_TOKEN_RE.search(decoded)
    )


def _url_component_has_credential(value: str) -> bool:
    decoded = unquote(value)
    return bool(
        public_release_check.sensitive_value_kinds(decoded)
        or _URL_PROVIDER_TOKEN_RE.search(decoded)
    )


def _url_has_credentials(value: str) -> bool:
    """Reject embedded credentials while permitting ordinary SSH usernames."""

    try:
        parsed = urlsplit(value)
    except ValueError:
        parsed = None
    if parsed is not None and parsed.netloc:
        if parsed.scheme.casefold() in {"http", "https"} and parsed.username is not None:
            return True
        if _userinfo_is_credential(parsed.username, parsed.password):
            return True
        hostname = parsed.hostname
        if hostname is not None and any(
            _url_component_has_credential(label)
            for label in hostname.split(".")
            if label
        ):
            return True
        return any(
            _url_component_has_credential(segment)
            for segment in parsed.path.split("/")
            if segment
        )
    scheme_separator = value.find("://")
    if scheme_separator >= 0:
        scheme = value[:scheme_separator].casefold()
        authority = re.split(r"[/\?#]", value[scheme_separator + 3 :], maxsplit=1)[0]
        if "@" in authority:
            if scheme in {"http", "https"}:
                return True
            userinfo = authority.rsplit("@", maxsplit=1)[0]
            username, separator, userinfo_suffix = userinfo.partition(":")
            return _userinfo_is_credential(
                username,
                userinfo_suffix if separator else None,
            )
    scp_match = _SCP_STYLE_SSH_URL_RE.fullmatch(value)
    if scp_match is not None:
        username = scp_match.group("username")
        if _userinfo_is_credential(username, None):
            return True
        if any(
            _url_component_has_credential(label)
            for label in scp_match.group("host").split(".")
            if label
        ):
            return True
        return any(
            _url_component_has_credential(segment)
            for segment in scp_match.group("path").split("/")
            if segment
        )
    return False


def _raw_url_scheme(value: str) -> str:
    match = re.match(r"([A-Za-z][A-Za-z0-9+._-]*):", value)
    return match.group(1) if match is not None else ""


def _url_uses_remote_helper(value: str) -> bool:
    if _REMOTE_HELPER_URL_RE.match(value) is not None:
        return True
    scheme = _raw_url_scheme(value)
    return bool(scheme) and scheme not in _NATIVE_GIT_URL_SCHEMES


def _safe_network_hostname(value: str) -> bool:
    if (
        not value
        or len(value) > 253
        or "%" in value
        or any(character.isspace() or ord(character) < 33 or ord(character) == 127 for character in value)
    ):
        return False
    try:
        ipaddress.ip_address(value)
    except ValueError:
        labels = value.removesuffix(".").split(".")
        return bool(labels) and all(_DNS_LABEL_RE.fullmatch(label) for label in labels)
    return True


def _decoded_url_component_is_canonical(value: str) -> bool:
    decoded = unquote(value)
    return bool(decoded) and not any(
        character.isspace() or ord(character) < 32 or ord(character) == 127
        for character in decoded
    )


def _supported_public_remote_url(value: str) -> bool:
    """Accept only reviewed credential-free network forms for publication."""

    scp_match = _SCP_STYLE_SSH_URL_RE.fullmatch(value)
    if scp_match is not None:
        return (
            _safe_network_hostname(scp_match.group("host"))
            and _decoded_url_component_is_canonical(scp_match.group("path"))
        )
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return False
    username = unquote(parsed.username) if parsed.username is not None else None
    return (
        _raw_url_scheme(value) in _PUBLIC_REMOTE_URL_SCHEMES
        and hostname is not None
        and _safe_network_hostname(hostname)
        and (port is None or 1 <= port <= 65535)
        and (
            username is None
            or (
                parsed.password is None
                and _SSH_USERNAME_RE.fullmatch(username) is not None
                and not username.startswith("-")
            )
        )
        and _decoded_url_component_is_canonical(parsed.path)
        and parsed.path != "/"
        and not parsed.query
        and not parsed.fragment
    )


def publication_target_errors(
    *,
    remote_name: str,
    branch: str,
    expected_fetch_url: str,
    expected_push_url: str,
) -> list[str]:
    """Validate publication routing before any network-capable Git command."""

    errors: list[str] = []
    if not _safe_remote_name(remote_name):
        errors.append("remote name must use a bounded simple Git remote spelling")
    if not _safe_branch_name(branch):
        errors.append("branch must be a canonical bounded Git branch name")
    for label, value in (
        ("expected fetch URL", expected_fetch_url),
        ("expected push URL", expected_push_url),
    ):
        if not value or any(
            ord(character) < 32 or ord(character) == 127
            for character in value
        ):
            errors.append(f"{label} must be non-empty single-line text")
        elif _url_uses_remote_helper(value):
            errors.append(
                f"{label} must not use an executable Git remote-helper URL form"
            )
        elif any(character.isspace() for character in value):
            errors.append(f"{label} must be non-empty single-line text")
        elif value.startswith("-"):
            errors.append(f"{label} must not begin with a command-option prefix")
        elif _url_has_credentials(value):
            errors.append(f"{label} must not contain embedded credentials")
        elif not _supported_public_remote_url(value):
            errors.append(
                f"{label} must use a reviewed HTTPS, SSH URL, or scp-style SSH form"
            )
    return errors


def _cli_validation_errors(
    *,
    phase: HandoffPhase,
    remote_name: str,
    branch: str,
    expected_fetch_url: str,
    expected_push_url: str,
    expected_parent_commit: str,
    tag_ref: str | None,
) -> list[str]:
    errors = publication_target_errors(
        remote_name=remote_name,
        branch=branch,
        expected_fetch_url=expected_fetch_url,
        expected_push_url=expected_push_url,
    )
    if _FULL_OID_RE.fullmatch(expected_parent_commit) is None:
        errors.append("expected parent commit must be a full lowercase SHA-1 or SHA-256 OID")
    if tag_ref is not None:
        if phase is not HandoffPhase.COMMITTED:
            errors.append("tag preflight is available only in committed phase")
        if not _safe_full_tag_ref(tag_ref):
            errors.append("tag ref must be one bounded canonical full refs/tags/... ref")
    return errors


def _paths_overlap(left: Path, right: Path) -> bool:
    return (
        left == right
        or safe_paths.path_within_root(left, right)
        or safe_paths.path_within_root(right, left)
    )


def _root_separation_errors(
    roots: tuple[tuple[str, safe_paths.OutputDirectoryBinding], ...],
) -> list[str]:
    errors: list[str] = []
    for index, (left_name, left) in enumerate(roots):
        for right_name, right in roots[index + 1 :]:
            if _paths_overlap(left.bound_path, right.bound_path):
                errors.append(
                    f"{left_name} and {right_name} must be distinct non-nested directories"
                )
            if left.identity == right.identity:
                errors.append(
                    f"{left_name} and {right_name} identify the same filesystem directory"
                )
    return errors


def _loaded_verifier_origin_errors(
    export_root: Path,
    snapshot: public_release_check.PublicExportTreeSnapshot,
) -> list[str]:
    """Bind loaded source origins to exact marker-committed export paths.

    The export snapshot already proves that each named path is a no-follow,
    regular, singly linked file. Keep this check lexical so an alternate loader
    origin cannot be normalized into the accepted export path through a link.
    """

    snapshot_paths = {relative for relative, _digest, _mode in snapshot.files}
    expected_paths = {
        module_name: export_root / relative
        for module_name, relative in _LOCAL_VERIFIER_SOURCES
    }
    errors: list[str] = []
    for module_name, relative in _LOCAL_VERIFIER_SOURCES:
        if relative not in snapshot_paths:
            errors.append(
                f"verified export is missing handoff verifier source: {relative}"
            )

    checker_origin = globals().get("__file__")
    if (
        not isinstance(checker_origin, str)
        or not Path(checker_origin).is_absolute()
        or Path(checker_origin) != expected_paths["public_handoff_check"]
    ):
        errors.append(
            "loaded handoff verifier source origin does not match the verified export: "
            "public_handoff_check"
        )

    loaded_modules = (
        ("public_release_check", public_release_check),
        ("public_surface", public_surface),
        ("resource_cleanup", resource_cleanup),
        ("safe_paths", safe_paths),
        ("bounded_subprocess", bounded_subprocess),
    )
    for module_name, module in loaded_modules:
        spec = module.__spec__
        origin = None if spec is None else spec.origin
        if (
            not isinstance(origin, str)
            or not Path(origin).is_absolute()
            or Path(origin) != expected_paths[module_name]
        ):
            errors.append(
                "loaded handoff verifier source origin does not match the verified "
                f"export: {module_name}"
            )
    return errors


def _git_executable_sha256(
    binding: public_release_check._RegularFileBinding | _InheritedDescriptorBinding,
) -> str:
    before = os.fstat(binding.descriptor)
    if before.st_size > _GIT_EXECUTABLE_MAX_BYTES:
        raise ValueError("reviewed Git executable exceeds the bounded input limit")
    if not stat.S_IMODE(before.st_mode) & 0o111:
        raise ValueError("reviewed Git executable is not marked executable")
    digest = hashlib.sha256()
    total = 0
    while chunk := os.pread(binding.descriptor, 1024 * 1024, total):
        total += len(chunk)
        if total > _GIT_EXECUTABLE_MAX_BYTES:
            raise ValueError("reviewed Git executable exceeds the bounded input limit")
        digest.update(chunk)
    after = os.fstat(binding.descriptor)
    if (
        safe_paths.stable_file_metadata(before)
        != safe_paths.stable_file_metadata(after)
        or total != after.st_size
    ):
        raise ValueError("reviewed Git executable changed while it was inspected")
    binding.require_current(description="reviewed Git executable")
    return digest.hexdigest()


def _open_git_executable_binding(path: Path) -> _GitExecutableBinding:
    if not path.is_absolute():
        raise ValueError("reviewed Git executable must use an absolute path")
    file_binding = public_release_check._open_regular_descriptor(
        path,
        description="reviewed Git executable",
        require_single_link=False,
    )
    try:
        result = _GitExecutableBinding(
            file=file_binding,
            sha256=_git_executable_sha256(file_binding),
        )
        result.require_current()
        return result
    except BaseException as primary:
        try:
            file_binding.close()
        except BaseException as cleanup:
            primary.add_note(f"reviewed Git executable cleanup failure: {cleanup}")
        raise


def _open_inherited_git_executable_binding(
    source_descriptor: int,
) -> _GitExecutableBinding:
    if source_descriptor < 3:
        raise ValueError("reviewed Git executable descriptor must be at least 3")
    descriptor: int | None = None
    try:
        descriptor = os.dup(source_descriptor)
        os.set_inheritable(descriptor, False)
        descriptor_path = Path("/proc/self/fd") / str(descriptor)
        try:
            raw_target = os.readlink(descriptor_path)
        except OSError as exc:
            raise ValueError(
                "reviewed Git executable descriptor is not available through Linux procfs"
            ) from exc
        if raw_target.endswith(" (deleted)"):
            raise ValueError("reviewed Git executable descriptor names a deleted file")
        lexical_path = Path(raw_target)
        if not lexical_path.is_absolute():
            raise ValueError(
                "reviewed Git executable descriptor must identify an absolute file"
            )
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("reviewed Git executable descriptor must identify a regular file")
        if metadata.st_nlink == 0:
            raise ValueError("reviewed Git executable descriptor must identify a linked file")
        file_binding = _InheritedDescriptorBinding(
            descriptor=descriptor,
            metadata=metadata,
            lexical_path=lexical_path,
        )
        result = _GitExecutableBinding(
            file=file_binding,
            sha256=_git_executable_sha256(file_binding),
        )
        result.require_current()
        return result
    except BaseException as primary:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except BaseException as cleanup:
                primary.add_note(
                    f"reviewed Git executable descriptor cleanup failure: {cleanup}"
                )
        raise


def _deduplicate_report_errors(report: dict[str, object]) -> dict[str, object]:
    errors = report.get("errors")
    if isinstance(errors, list) and all(isinstance(item, str) for item in errors):
        errors[:] = list(dict.fromkeys(errors))
    return report


def _git_blob_oid(content: bytes, *, object_format: str) -> str:
    if object_format == "sha1":
        digest = hashlib.sha1()
    elif object_format == "sha256":
        digest = hashlib.sha256()
    else:
        raise ValueError("unsupported Git object format")
    digest.update(f"blob {len(content)}\0".encode("ascii"))
    digest.update(content)
    return digest.hexdigest()


def _expected_export_files(
    export_root: Path,
    snapshot: public_release_check.PublicExportTreeSnapshot,
    *,
    object_format: str,
) -> tuple[dict[str, _ExpectedFile], str]:
    raw_files = {
        relative: (digest, mode)
        for relative, digest, mode in snapshot.files
    }
    marker = raw_files.get(public_surface.PUBLIC_EXPORT_OWNERSHIP_MARKER)
    if marker is None:
        raise ValueError("verified export snapshot lost its ownership marker")
    expected: dict[str, _ExpectedFile] = {}
    for relative, (digest, mode) in sorted(raw_files.items()):
        if relative == public_surface.PUBLIC_EXPORT_OWNERSHIP_MARKER:
            continue
        if mode not in {0o644, 0o755}:
            raise ValueError(
                "public export contains a file mode that Git cannot preserve exactly: "
                f"{relative}"
            )
        content = public_release_check.stable_file_bytes(
            export_root / relative,
            expected_snapshot=(digest, mode),
        )
        expected[relative] = _ExpectedFile(
            sha256=digest,
            size=len(content),
            posix_mode=mode,
            git_mode="100755" if mode == 0o755 else "100644",
            git_oid=_git_blob_oid(content, object_format=object_format),
        )
    return expected, marker[0]


def _worktree_snapshot(
    root: Path,
    binding: safe_paths.OutputDirectoryBinding,
    expected: dict[str, _ExpectedFile],
    errors: list[str],
) -> tuple[object, ...]:
    inventory = public_release_check._inventory_release_tree_descriptor(
        binding.descriptor
    )
    if inventory.errors:
        raise ValueError("public clone worktree could not be enumerated safely")
    if ".git" not in inventory.directories:
        errors.append("public clone must contain an ordinary .git directory")
    if ".git" in inventory.files or ".git" in inventory.symlinks or ".git" in inventory.special:
        errors.append("public clone must not be a linked worktree or gitfile checkout")

    actual_files = set(inventory.files)
    missing_files = sorted(set(expected) - actual_files)
    extra_files = sorted(actual_files - set(expected))
    if missing_files:
        errors.append("public clone worktree is missing export files: " + ", ".join(missing_files))
    if extra_files:
        errors.append("public clone worktree has files outside the export payload: " + ", ".join(extra_files))

    expected_directories = public_release_check._manifest_parent_directories(
        set(expected)
    )
    actual_directories = set(inventory.directories) - {".git"}
    missing_directories = sorted(expected_directories - actual_directories)
    extra_directories = sorted(actual_directories - expected_directories)
    if missing_directories:
        errors.append(
            "public clone worktree is missing export directories: "
            + ", ".join(missing_directories)
        )
    if extra_directories:
        errors.append(
            "public clone worktree has directories outside the export payload: "
            + ", ".join(extra_directories)
        )
    if inventory.symlinks:
        errors.append("public clone worktree contains symlink entries")
    if inventory.special:
        errors.append("public clone worktree contains unsupported filesystem entries")

    records: list[tuple[str, str, int]] = []
    for relative in sorted(set(expected) & actual_files):
        metadata = inventory.files[relative]
        if metadata.st_nlink != 1:
            errors.append(
                f"public clone worktree file must have exactly one hard link: {relative}"
            )
            continue
        digest, mode = public_release_check.stable_file_snapshot(
            root / relative,
            _expected=metadata,
        )
        records.append((relative, digest, mode))
        if digest != expected[relative].sha256:
            errors.append(f"public clone worktree content differs from export: {relative}")
        if mode != expected[relative].posix_mode:
            errors.append(f"public clone worktree mode differs from export: {relative}")
    return (
        public_release_check._inventory_signature(inventory),
        tuple(records),
    )


def _minimal_git_inventory(
    root_binding: safe_paths.OutputDirectoryBinding,
) -> public_release_check._TreeInventory:
    files: dict[str, os.stat_result] = {}
    directories: dict[str, os.stat_result] = {}
    symlinks: dict[str, os.stat_result] = {}
    special: dict[str, os.stat_result] = {}
    try:
        metadata = os.stat(
            ".git",
            dir_fd=root_binding.descriptor,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        pass
    else:
        if stat.S_ISREG(metadata.st_mode):
            files[".git"] = metadata
        elif stat.S_ISDIR(metadata.st_mode):
            directories[".git"] = metadata
        elif stat.S_ISLNK(metadata.st_mode):
            symlinks[".git"] = metadata
        else:
            special[".git"] = metadata
    return public_release_check._TreeInventory(
        files=files,
        directories=directories,
        symlinks=symlinks,
        special=special,
        root_metadata=os.fstat(root_binding.descriptor),
        errors=(),
    )


def _run_git(
    git: _GitExecutableBinding,
    root: Path,
    gitdir: Path,
    arguments: list[str],
    *,
    label: str,
    allow_absent: bool = False,
    extra_pass_fds: tuple[int, ...] = (),
) -> bytes:
    git.require_current()
    pass_fds = tuple(dict.fromkeys((*git.pass_fds, *extra_pass_fds)))
    try:
        returncode, stdout, stderr = public_release_check._bounded_git_command(
            root,
            [
                git.command,
                "--no-optional-locks",
                "--no-replace-objects",
                "-c",
                "core.fsmonitor=false",
                "-c",
                "core.untrackedCache=false",
                "-C",
                str(root),
                f"--git-dir={gitdir}",
                f"--work-tree={root}",
                *arguments,
            ],
            label=label,
            environment=_GIT_ENVIRONMENT,
            pass_fds=pass_fds,
            inherit_non_git_environment=False,
        )
    except BaseException as primary:
        try:
            git.require_current()
        except BaseException as verification:
            primary.add_note(
                f"reviewed Git executable terminal verification failed: {verification}"
            )
        raise
    git.require_current()
    if allow_absent and returncode == 1 and not stdout and not stderr:
        return b""
    if returncode != 0 or stderr:
        raise RuntimeError(f"{label} failed without a usable bounded result")
    return stdout


def _single_line(raw: bytes, *, description: str, allow_empty: bool = False) -> str:
    if b"\0" in raw:
        raise RuntimeError(f"{description} contains NUL")
    value = raw[:-1] if raw.endswith(b"\n") else raw
    if b"\n" in value or b"\r" in value:
        raise RuntimeError(f"{description} must contain exactly one line")
    try:
        decoded = value.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError(f"{description} is not valid UTF-8") from exc
    if not decoded and not allow_empty:
        raise RuntimeError(f"{description} is empty")
    return decoded


def _lines(raw: bytes, *, description: str) -> tuple[str, ...]:
    if b"\0" in raw or b"\r" in raw:
        raise RuntimeError(f"{description} has invalid line framing")
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError(f"{description} is not valid UTF-8") from exc
    values = decoded.splitlines()
    if any(not value for value in values):
        raise RuntimeError(f"{description} contains an empty value")
    return tuple(values)


def _nul_values(raw: bytes, *, description: str) -> tuple[str, ...]:
    if raw and not raw.endswith(b"\0"):
        raise RuntimeError(f"{description} has unterminated NUL framing")
    values: list[str] = []
    for raw_value in raw.split(b"\0"):
        if not raw_value:
            continue
        if b"\n" in raw_value or b"\r" in raw_value:
            raise RuntimeError(f"{description} contains an invalid name")
        try:
            value = raw_value.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RuntimeError(f"{description} is not valid UTF-8") from exc
        values.append(value)
    return tuple(values)


def _git_config_values(
    git: _GitExecutableBinding,
    root: Path,
    gitdir: Path,
    *,
    key: str,
    description: str,
) -> tuple[str, ...]:
    return _lines(
        _run_git(
            git,
            root,
            gitdir,
            ["config", "--get-all", key],
            label=description,
            allow_absent=True,
        ),
        description=description,
    )


def _effective_http_proxy_values(
    git: _GitExecutableBinding,
    root: Path,
    gitdir: Path,
    *,
    fetch_urls: tuple[str, ...],
    push_urls: tuple[str, ...],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    records: list[tuple[str, tuple[str, ...]]] = []
    for role, urls in (("fetch", fetch_urls), ("push", push_urls)):
        for index, url in enumerate(urls):
            try:
                scheme = urlsplit(url).scheme.casefold()
            except ValueError:
                scheme = ""
            if scheme not in {"http", "https"}:
                continue
            description = f"Git effective {role} HTTP-proxy inspection"
            values = _lines(
                _run_git(
                    git,
                    root,
                    gitdir,
                    ["config", "--get-urlmatch", "http.proxy", url],
                    label=description,
                    allow_absent=True,
                ),
                description=description,
            )
            records.append((f"{role}-{index}", values))
    return tuple(records)


def _effective_http_config_keys(
    git: _GitExecutableBinding,
    root: Path,
    gitdir: Path,
) -> tuple[str, ...]:
    keys = _lines(
        _run_git(
            git,
            root,
            gitdir,
            ["config", "--includes", "--name-only", "--list"],
            label="Git effective-configuration inspection",
        ),
        description="Git effective-configuration inspection",
    )
    return tuple(sorted(key for key in keys if key.casefold().startswith("http.")))


def _common_git_directory(
    git: _GitExecutableBinding,
    root: Path,
    metadata: public_release_check._GitMetadataBinding,
) -> Path:
    raw = _run_git(
        git,
        root,
        metadata.gitdir,
        ["rev-parse", "--path-format=absolute", "--git-common-dir"],
        label="Git common-directory inspection",
    )
    return public_release_check._control_file_path(
        raw,
        prefix=b"",
        base=root,
        description="Git common-directory inspection",
    )


def _open_storage_binding(
    git: _GitExecutableBinding,
    root: Path,
    metadata: public_release_check._GitMetadataBinding,
) -> _GitStorageBinding:
    gitdir: safe_paths.OutputDirectoryBinding | None = None
    common: safe_paths.OutputDirectoryBinding | None = None
    objects: safe_paths.OutputDirectoryBinding | None = None
    try:
        gitdir = safe_paths.open_output_directory(
            metadata.gitdir,
            create_missing=False,
        )
        common_path = _common_git_directory(git, root, metadata)
        common = safe_paths.open_output_directory(common_path, create_missing=False)
        objects = safe_paths.open_output_directory(
            common.bound_path / "objects",
            create_missing=False,
        )
        return _GitStorageBinding(
            metadata=metadata,
            gitdir=gitdir,
            common=common,
            objects=objects,
        )
    except BaseException as primary:
        resource_cleanup.cleanup_actions(
            tuple(
                (description, binding.close)
                for description, binding in (
                    ("Git object directory", objects),
                    ("Git common directory", common),
                    ("Git directory", gitdir),
                )
                if binding is not None
            ),
            primary=primary,
        )
        raise


def _graft_info_snapshot(
    storage: _GitStorageBinding,
    *,
    errors: list[str],
) -> tuple[object, ...] | None:
    """Snapshot an optional common ``info`` directory and reject substitutions."""

    directory_flags = (
        os.O_RDONLY
        | public_release_check._required_open_flag("O_DIRECTORY")
        | public_release_check._required_open_flag("O_NOFOLLOW")
        | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        info_descriptor = os.open(
            "info",
            directory_flags,
            dir_fd=storage.common.descriptor,
        )
    except FileNotFoundError:
        return None
    try:
        inventory = public_release_check._inventory_release_tree_descriptor(
            info_descriptor
        )
        if inventory.errors:
            raise ValueError("Git common info directory could not be enumerated safely")
        all_entries = (
            set(inventory.files)
            | set(inventory.directories)
            | set(inventory.symlinks)
            | set(inventory.special)
        )
        if "grafts" in all_entries:
            errors.append("public clone contains a forbidden Git grafts file")
        if "attributes" in all_entries:
            errors.append("public clone contains a forbidden Git info/attributes entry")
        return public_release_check._inventory_signature(inventory)
    finally:
        os.close(info_descriptor)


def _object_store_snapshot(
    storage: _GitStorageBinding,
    *,
    public: bool,
    errors: list[str],
) -> _ObjectStoreSnapshot:
    inventory = public_release_check._inventory_release_tree_descriptor(
        storage.objects.descriptor
    )
    if inventory.errors:
        raise ValueError("Git object store could not be enumerated safely")
    if public and inventory.symlinks:
        errors.append("public Git object store contains symlink entries")
    if not public and inventory.symlinks:
        errors.append("authoring Git object store contains symlink entries")
    if public and inventory.special:
        errors.append("public Git object store contains unsupported entries")
    if not public and inventory.special:
        errors.append("authoring Git object store contains unsupported entries")
    if public and any(
        relative in inventory.files
        for relative in ("info/alternates", "info/http-alternates")
    ):
        errors.append("public Git object store uses an alternate object-store declaration")
    if public and any(metadata.st_nlink != 1 for metadata in inventory.files.values()):
        errors.append("public Git object store contains multiply-linked object files")
    identities = frozenset(
        (metadata.st_dev, metadata.st_ino)
        for metadata in inventory.files.values()
    )
    directory_identities = frozenset(
        (metadata.st_dev, metadata.st_ino)
        for metadata in inventory.directories.values()
    )
    return _ObjectStoreSnapshot(
        signature=public_release_check._inventory_signature(inventory),
        file_identities=identities,
        directory_identities=directory_identities,
    )


def _git_control_entry_metadata(
    entry: os.DirEntry[str],
    *,
    prefix: str,
    allow_opaque_authoring_fsmonitor_projection: bool,
) -> os.stat_result | None:
    """Read one control entry, or bind the exact opaque host projection."""

    try:
        return entry.stat(follow_symlinks=False)
    except FileNotFoundError:
        if (
            allow_opaque_authoring_fsmonitor_projection
            and not prefix
            and entry.name == _AUTHORING_FSMONITOR_IPC_ROOT_ENTRY
        ):
            return None
        raise


def _git_control_inventory_descriptor(
    descriptor: int,
    *,
    allow_opaque_authoring_fsmonitor_projection: bool = False,
) -> _GitControlInventory:
    """Inventory Git control metadata while leaving object stores opaque."""

    files: dict[str, os.stat_result] = {}
    directories: dict[str, os.stat_result] = {}
    symlinks: dict[str, os.stat_result] = {}
    special: dict[str, os.stat_result] = {}
    root_metadata: os.stat_result | None = None
    errors: list[str] = []
    opaque_entries: set[str] = set()
    entry_count = 0

    directory_flags = (
        os.O_RDONLY
        | public_release_check._required_open_flag("O_DIRECTORY")
        | public_release_check._required_open_flag("O_NOFOLLOW")
        | getattr(os, "O_CLOEXEC", 0)
    )

    def walk(directory_descriptor: int, prefix: str) -> None:
        nonlocal entry_count
        before = os.fstat(directory_descriptor)
        with os.scandir(directory_descriptor) as iterator:
            entries = sorted(iterator, key=lambda item: item.name)
        for entry in entries:
            entry_count += 1
            if entry_count > _GIT_CONTROL_MAX_ENTRIES:
                raise ValueError("Git control metadata exceeds the bounded entry limit")
            try:
                entry.name.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise ValueError("Git control paths must be valid UTF-8") from exc
            relative = f"{prefix}/{entry.name}" if prefix else entry.name
            metadata = _git_control_entry_metadata(
                entry,
                prefix=prefix,
                allow_opaque_authoring_fsmonitor_projection=(
                    allow_opaque_authoring_fsmonitor_projection
                ),
            )
            if metadata is None:
                opaque_entries.add(relative)
                continue
            mode = metadata.st_mode
            if stat.S_ISLNK(mode):
                symlinks[relative] = metadata
            elif stat.S_ISDIR(mode):
                directories[relative] = metadata
                if not prefix and entry.name in _GIT_CONTROL_OPAQUE_DIRECTORIES:
                    continue
                child_descriptor = os.open(
                    entry.name,
                    directory_flags,
                    dir_fd=directory_descriptor,
                )
                try:
                    if (
                        safe_paths.stable_file_metadata(os.fstat(child_descriptor))
                        != safe_paths.stable_file_metadata(metadata)
                    ):
                        raise ValueError(
                            f"Git control metadata changed during enumeration: {relative}"
                        )
                    walk(child_descriptor, relative)
                finally:
                    os.close(child_descriptor)
            elif stat.S_ISREG(mode):
                files[relative] = metadata
            else:
                special[relative] = metadata
        after = os.fstat(directory_descriptor)
        if safe_paths.stable_file_metadata(before) != safe_paths.stable_file_metadata(after):
            raise ValueError(
                "Git control metadata changed during enumeration: "
                + (prefix or ".")
            )

    try:
        root_metadata = os.fstat(descriptor)
        walk(descriptor, "")
    except (OSError, ValueError) as exc:
        errors.append(f"Git control metadata could not be enumerated safely: {exc}")
    return _GitControlInventory(
        tree=public_release_check._TreeInventory(
            files=files,
            directories=directories,
            symlinks=symlinks,
            special=special,
            root_metadata=root_metadata,
            errors=tuple(errors),
        ),
        opaque_entries=tuple(sorted(opaque_entries)),
    )


def _git_control_file_sha256(
    root_descriptor: int,
    relative: str,
    expected: os.stat_result,
) -> tuple[int, str]:
    parts = PurePosixPath(relative).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ValueError("Git control digest path is not canonical")
    directory_flags = (
        os.O_RDONLY
        | public_release_check._required_open_flag("O_DIRECTORY")
        | public_release_check._required_open_flag("O_NOFOLLOW")
        | getattr(os, "O_CLOEXEC", 0)
    )
    file_flags = (
        os.O_RDONLY
        | public_release_check._required_open_flag("O_NOFOLLOW")
        | public_release_check._required_open_flag("O_NONBLOCK")
        | getattr(os, "O_CLOEXEC", 0)
    )
    opened_directories: list[int] = []
    file_descriptor: int | None = None
    try:
        parent_descriptor = root_descriptor
        for part in parts[:-1]:
            child_descriptor = os.open(
                part,
                directory_flags,
                dir_fd=parent_descriptor,
            )
            opened_directories.append(child_descriptor)
            parent_descriptor = child_descriptor
        file_descriptor = os.open(
            parts[-1],
            file_flags,
            dir_fd=parent_descriptor,
        )
        before = os.fstat(file_descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or safe_paths.stable_file_metadata(before)
            != safe_paths.stable_file_metadata(expected)
        ):
            raise ValueError(f"Git control file changed before hashing: {relative}")
        if before.st_size > _GIT_CONTROL_FILE_MAX_BYTES:
            raise ValueError(f"Git control file exceeds the bounded limit: {relative}")
        digest = hashlib.sha256()
        total = 0
        while chunk := os.pread(file_descriptor, 1024 * 1024, total):
            total += len(chunk)
            if total > _GIT_CONTROL_FILE_MAX_BYTES:
                raise ValueError(f"Git control file exceeds the bounded limit: {relative}")
            digest.update(chunk)
        after = os.fstat(file_descriptor)
        if (
            safe_paths.stable_file_metadata(before)
            != safe_paths.stable_file_metadata(after)
            or total != after.st_size
        ):
            raise ValueError(f"Git control file changed while hashing: {relative}")
        return total, digest.hexdigest()
    finally:
        if file_descriptor is not None:
            os.close(file_descriptor)
        for directory_descriptor in reversed(opened_directories):
            os.close(directory_descriptor)


def _git_control_snapshot(
    storage: _GitStorageBinding,
    *,
    public: bool,
    errors: list[str],
) -> _GitControlSnapshot:
    signatures: list[tuple[str, tuple[object, ...]]] = []
    file_identities: set[tuple[int, int]] = set()
    directory_identities: set[tuple[int, int]] = set()
    critical_digests: list[tuple[str, str, int, str]] = []
    opaque_entries: list[tuple[str, str]] = []
    total_hashed = 0
    seen_roots: set[tuple[int, int]] = set()

    for label, binding in (("gitdir", storage.gitdir), ("common", storage.common)):
        owner = "public clone" if public else "authoring checkout"
        root_metadata = os.fstat(binding.descriptor)
        root_identity = (root_metadata.st_dev, root_metadata.st_ino)
        if root_identity in seen_roots:
            continue
        seen_roots.add(root_identity)
        control_inventory = _git_control_inventory_descriptor(
            binding.descriptor,
            allow_opaque_authoring_fsmonitor_projection=not public,
        )
        inventory = control_inventory.tree
        if inventory.errors:
            raise ValueError(
                f"{owner} {label} Git control metadata could not be inspected"
            )
        binding.require_unchanged_chain(
            description=f"{owner} {label} Git control"
        )
        opaque_entries.extend(
            (label, relative) for relative in control_inventory.opaque_entries
        )
        signatures.append(
            (label, public_release_check._inventory_signature(inventory))
        )
        directory_identities.add(root_identity)
        directory_identities.update(
            (metadata.st_dev, metadata.st_ino)
            for metadata in inventory.directories.values()
        )
        file_identities.update(
            (metadata.st_dev, metadata.st_ino)
            for metadata in inventory.files.values()
        )

        if inventory.symlinks:
            owner = "public" if public else "authoring"
            errors.append(f"{owner} Git control metadata contains symlink entries")
        unsupported_special = inventory.special
        if not public:
            unsupported_special = {
                relative: metadata
                for relative, metadata in inventory.special.items()
                if not (
                    relative == _AUTHORING_FSMONITOR_IPC_ROOT_ENTRY
                    and stat.S_ISSOCK(metadata.st_mode)
                )
            }
        if unsupported_special:
            owner = "public" if public else "authoring"
            errors.append(f"{owner} Git control metadata contains unsupported entries")
        if public:
            if any(metadata.st_nlink != 1 for metadata in inventory.files.values()):
                errors.append("public Git control metadata contains multiply-linked files")
            all_entries = (
                set(inventory.files)
                | set(inventory.directories)
                | set(inventory.symlinks)
                | set(inventory.special)
            )
            for forbidden in (
                "commondir",
                "config.worktree",
                "gitdir",
                "modules",
                "reftable",
                "worktrees",
            ):
                if forbidden in all_entries:
                    errors.append(
                        f"public Git control metadata contains forbidden {forbidden}"
                    )
            if "shallow" in all_entries:
                errors.append("public clone must be a full non-shallow clone")
            if any(PurePosixPath(relative).name.endswith(".lock") for relative in all_entries):
                errors.append("public Git control metadata contains lock files")
            for required in ("config", "HEAD"):
                if required not in inventory.files:
                    errors.append(
                        f"public Git control metadata requires a regular {required} file"
                    )

        critical_paths = sorted(
            relative
            for relative in inventory.files
            if relative in {"config", "HEAD", "packed-refs", "shallow"}
            or relative.startswith("refs/")
        )
        for relative in critical_paths:
            size, digest = _git_control_file_sha256(
                binding.descriptor,
                relative,
                inventory.files[relative],
            )
            total_hashed += size
            if total_hashed > _GIT_CONTROL_HASH_MAX_BYTES:
                raise ValueError("Git control digests exceed the aggregate bounded limit")
            critical_digests.append((label, relative, size, digest))

    return _GitControlSnapshot(
        signatures=tuple(signatures),
        file_identities=frozenset(file_identities),
        directory_identities=frozenset(directory_identities),
        critical_digests=tuple(critical_digests),
        opaque_entries=tuple(opaque_entries),
    )


def _git_control_independence_errors(
    public_control: _GitControlSnapshot,
    authoring_control: _GitControlSnapshot,
) -> list[str]:
    errors: list[str] = []
    if public_control.file_identities & authoring_control.file_identities:
        errors.append("public clone shares Git control files with authoring")
    if public_control.directory_identities & authoring_control.directory_identities:
        errors.append("public clone shares Git control directories with authoring")
    return errors


def _exact_local_config_keys(
    git: _GitExecutableBinding,
    root: Path,
    gitdir: Path,
    config: public_release_check._RegularFileBinding,
) -> tuple[str, ...]:
    config.require_current(description="public Git local config")
    raw = _run_git(
        git,
        root,
        gitdir,
        [
            "config",
            "--file",
            f"/proc/self/fd/{config.descriptor}",
            "--no-includes",
            "--name-only",
            "--null",
            "--list",
        ],
        label="Git exact local-configuration inspection",
        extra_pass_fds=(config.descriptor,),
    )
    config.require_current(description="public Git local config")
    return _nul_values(raw, description="Git exact local-configuration inspection")


def _local_config_control_errors(keys: tuple[str, ...]) -> list[str]:
    folded = {key.casefold() for key in keys}
    errors: list[str] = []
    if "include.path" in folded or any(key.startswith("includeif.") for key in folded):
        errors.append("public Git local config must not include external configuration")
    if "core.fsmonitor" in folded:
        errors.append("public Git local config must not configure core.fsmonitor")
    if any(key.startswith("hook.") for key in folded):
        errors.append("public Git local config must not configure hook commands")
    for key, description in (
        ("core.worktree", "core.worktree"),
        ("extensions.refstorage", "alternate ref storage"),
        ("extensions.worktreeconfig", "worktree-specific config"),
    ):
        if key in folded:
            errors.append(f"public Git local config must not enable {description}")
    return errors


def _storage_independence_errors(
    public_storage: _GitStorageBinding,
    authoring_storage: _GitStorageBinding,
    public_control: _GitControlSnapshot,
    authoring_control: _GitControlSnapshot,
    public_objects: _ObjectStoreSnapshot,
    authoring_objects: _ObjectStoreSnapshot,
) -> list[str]:
    errors: list[str] = []
    public_git_identities = {
        public_storage.gitdir.identity,
        public_storage.common.identity,
        public_storage.objects.identity,
    }
    authoring_git_identities = {
        authoring_storage.gitdir.identity,
        authoring_storage.common.identity,
        authoring_storage.objects.identity,
    }
    if public_git_identities & authoring_git_identities:
        errors.append("public clone shares Git metadata or object storage with authoring")
    if public_objects.file_identities & authoring_objects.file_identities:
        errors.append("public clone shares hardlinked Git object files with authoring")
    if public_objects.directory_identities & authoring_objects.directory_identities:
        errors.append("public clone shares Git object directories with authoring")
    if (
        public_control.file_identities & authoring_objects.file_identities
        or public_objects.file_identities & authoring_control.file_identities
    ):
        errors.append(
            "public clone shares files across Git control metadata and authoring object storage"
        )
    if (
        public_control.directory_identities & authoring_objects.directory_identities
        or public_objects.directory_identities & authoring_control.directory_identities
    ):
        errors.append(
            "public clone shares directories across Git control metadata and authoring object storage"
        )
    return errors


def _index_errors(
    entries: tuple[public_release_check.GitStageEntry, ...],
    expected: dict[str, _ExpectedFile],
) -> list[str]:
    errors: list[str] = []
    if any(entry.stage != 0 for entry in entries):
        errors.append("public clone index contains unresolved conflict stages")
    paths = [entry.path for entry in entries]
    if len(paths) != len(set(paths)):
        errors.append("public clone index contains duplicate paths")
    if any(
        not public_release_check._safe_manifest_path(path)
        for path in paths
    ):
        errors.append("public clone index contains a non-canonical publication path")
    actual = {
        entry.path: entry
        for entry in entries
        if entry.stage == 0 and public_release_check._safe_manifest_path(entry.path)
    }
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    if missing:
        errors.append("public clone index is missing export files: " + ", ".join(missing))
    if extra:
        errors.append("public clone index has files outside the export payload: " + ", ".join(extra))
    for relative in sorted(set(expected) & set(actual)):
        if actual[relative].mode != expected[relative].git_mode:
            errors.append(f"public clone index mode differs from export: {relative}")
        if actual[relative].oid != expected[relative].git_oid:
            errors.append(f"public clone index content differs from export: {relative}")
    return errors


def _parse_tree_entries(
    raw: bytes,
    *,
    object_format: str,
) -> tuple[tuple[str, str, str], ...]:
    if raw and not raw.endswith(b"\0"):
        raise RuntimeError("git ls-tree returned unterminated NUL-delimited output")
    oid_length = 40 if object_format == "sha1" else 64
    entries: list[tuple[str, str, str]] = []
    for record in raw.split(b"\0"):
        if not record:
            continue
        header, separator, raw_path = record.partition(b"\t")
        fields = header.split(b" ")
        if (
            separator != b"\t"
            or not raw_path
            or len(fields) != 3
            or fields[0] not in {b"100644", b"100755"}
            or fields[1] != b"blob"
            or re.fullmatch(rb"[0-9a-f]{%d}" % oid_length, fields[2]) is None
        ):
            raise RuntimeError("git ls-tree returned an unsupported or malformed entry")
        try:
            path = raw_path.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RuntimeError("git ls-tree returned a non-UTF-8 path") from exc
        if not public_release_check._safe_manifest_path(path):
            raise RuntimeError("git ls-tree returned a non-canonical publication path")
        entries.append(
            (
                path,
                fields[0].decode("ascii"),
                fields[2].decode("ascii"),
            )
        )
    if len({entry[0] for entry in entries}) != len(entries):
        raise RuntimeError("git ls-tree returned duplicate paths")
    return tuple(sorted(entries))


def _parse_raw_commit(
    raw: bytes,
    *,
    object_format: str,
) -> tuple[str, tuple[str, ...]]:
    header, separator, _message = raw.partition(b"\n\n")
    if separator != b"\n\n" or b"\0" in header or b"\r" in header:
        raise RuntimeError("raw Git commit has invalid header framing")
    oid_length = 40 if object_format == "sha1" else 64
    oid_pattern = re.compile(rb"[0-9a-f]{%d}" % oid_length)
    tree_values: list[str] = []
    parent_values: list[str] = []
    previous_header = False
    for line in header.split(b"\n"):
        if line.startswith(b" "):
            if not previous_header:
                raise RuntimeError("raw Git commit has an orphan continuation header")
            continue
        key, separator, value = line.partition(b" ")
        if separator != b" " or not key or not value:
            raise RuntimeError("raw Git commit has a malformed header")
        previous_header = True
        if key not in {b"tree", b"parent"}:
            continue
        if oid_pattern.fullmatch(value) is None:
            raise RuntimeError("raw Git commit has a malformed tree or parent OID")
        decoded = value.decode("ascii")
        if key == b"tree":
            tree_values.append(decoded)
        else:
            parent_values.append(decoded)
    if len(tree_values) != 1:
        raise RuntimeError("raw Git commit must contain exactly one tree header")
    return tree_values[0], tuple(parent_values)


def _tag_state(
    git: _GitExecutableBinding,
    root: Path,
    gitdir: Path,
    *,
    tag_ref: str,
    object_format: str,
) -> _TagState:
    _run_git(
        git,
        root,
        gitdir,
        ["check-ref-format", tag_ref],
        label="Git tag-ref format inspection",
    )
    oid = _single_line(
        _run_git(
            git,
            root,
            gitdir,
            ["show-ref", "--verify", "--hash", tag_ref],
            label="Git tag-ref identity inspection",
        ),
        description="Git tag-ref identity inspection",
    )
    expected_oid_length = 40 if object_format == "sha1" else 64
    if re.fullmatch(rf"[0-9a-f]{{{expected_oid_length}}}", oid) is None:
        raise RuntimeError("Git tag ref did not identify one full object ID")
    object_type = _single_line(
        _run_git(
            git,
            root,
            gitdir,
            ["cat-file", "-t", oid],
            label="Git tag object-type inspection",
        ),
        description="Git tag object-type inspection",
    )
    if object_type not in {"commit", "tag"}:
        raise RuntimeError("Git tag ref must directly identify a commit or tag object")
    peeled_commit = _single_line(
        _run_git(
            git,
            root,
            gitdir,
            ["rev-parse", "--verify", f"{tag_ref}^{{commit}}"],
            label="Git tag peeled-commit inspection",
        ),
        description="Git tag peeled-commit inspection",
    )
    if re.fullmatch(
        rf"[0-9a-f]{{{expected_oid_length}}}", peeled_commit
    ) is None:
        raise RuntimeError("Git tag did not peel to one full commit object ID")
    return _TagState(
        ref=tag_ref,
        oid=oid,
        object_type=object_type,
        peeled_commit=peeled_commit,
    )


def _candidate_blob_snapshot(
    git: _GitExecutableBinding,
    root: Path,
    gitdir: Path,
    expected: dict[str, _ExpectedFile],
) -> tuple[tuple[str, int, str], ...]:
    expected_by_oid: dict[str, tuple[int, str]] = {}
    for item in expected.values():
        identity = (item.size, item.sha256)
        prior = expected_by_oid.setdefault(item.git_oid, identity)
        if prior != identity:
            raise RuntimeError("export files produce one Git OID for different content")
    records: list[tuple[str, int, str]] = []
    for oid, (expected_size, expected_sha256) in sorted(expected_by_oid.items()):
        content = _run_git(
            git,
            root,
            gitdir,
            ["cat-file", "blob", oid],
            label="Git candidate-blob inspection",
        )
        actual_sha256 = hashlib.sha256(content).hexdigest()
        if len(content) != expected_size or actual_sha256 != expected_sha256:
            raise RuntimeError("Git candidate blob does not equal the verified export")
        records.append((oid, len(content), actual_sha256))
    return tuple(records)


def _committed_tree_errors(
    tree: tuple[tuple[str, str, str], ...],
    expected: dict[str, _ExpectedFile],
) -> list[str]:
    errors: list[str] = []
    actual = {path: (mode, oid) for path, mode, oid in tree}
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    if missing:
        errors.append("candidate commit tree is missing export files: " + ", ".join(missing))
    if extra:
        errors.append("candidate commit tree has files outside the export payload: " + ", ".join(extra))
    for relative in sorted(set(expected) & set(actual)):
        if actual[relative][0] != expected[relative].git_mode:
            errors.append(f"candidate commit tree mode differs from export: {relative}")
        if actual[relative][1] != expected[relative].git_oid:
            errors.append(f"candidate commit tree content differs from export: {relative}")
    return errors


def _git_state(
    git: _GitExecutableBinding,
    root: Path,
    gitdir: Path,
    *,
    phase: HandoffPhase,
    remote_name: str,
    branch: str,
    tag_ref: str | None,
    object_format: str,
    expected: dict[str, _ExpectedFile],
) -> _GitState:
    head_ref = _single_line(
        _run_git(git, root, gitdir, ["symbolic-ref", "--quiet", "HEAD"], label="Git branch inspection"),
        description="Git branch inspection",
    )
    head = _single_line(
        _run_git(git, root, gitdir, ["rev-parse", "--verify", "HEAD"], label="Git HEAD inspection"),
        description="Git HEAD inspection",
    )
    head_type = _single_line(
        _run_git(git, root, gitdir, ["cat-file", "-t", head], label="Git HEAD type inspection"),
        description="Git HEAD type inspection",
    )
    if head_type != "commit":
        raise RuntimeError("public clone branch must directly identify a commit object")
    remote_ref = f"refs/remotes/{remote_name}/{branch}"
    remote_tracking = _single_line(
        _run_git(
            git,
            root,
            gitdir,
            ["rev-parse", "--verify", remote_ref],
            label="Git remote-tracking inspection",
        ),
        description="Git remote-tracking inspection",
    )
    remote_type = _single_line(
        _run_git(
            git,
            root,
            gitdir,
            ["cat-file", "-t", remote_tracking],
            label="Git remote-tracking type inspection",
        ),
        description="Git remote-tracking type inspection",
    )
    if remote_type != "commit":
        raise RuntimeError("public clone remote-tracking ref must directly identify a commit")
    upstream = _single_line(
        _run_git(
            git,
            root,
            gitdir,
            ["rev-parse", "--symbolic-full-name", "--verify", "@{upstream}"],
            label="Git upstream inspection",
        ),
        description="Git upstream inspection",
    )
    fetch_urls = _lines(
        _run_git(
            git,
            root,
            gitdir,
            ["remote", "get-url", "--all", remote_name],
            label="Git fetch-URL inspection",
        ),
        description="Git fetch-URL inspection",
    )
    push_urls = _lines(
        _run_git(
            git,
            root,
            gitdir,
            ["remote", "get-url", "--push", "--all", remote_name],
            label="Git push-URL inspection",
        ),
        description="Git push-URL inspection",
    )
    branch_push_remote = _lines(
        _run_git(
            git,
            root,
            gitdir,
            ["config", "--get-all", f"branch.{branch}.pushRemote"],
            label="Git branch push-remote inspection",
            allow_absent=True,
        ),
        description="Git branch push-remote inspection",
    )
    default_push_remote = _lines(
        _run_git(
            git,
            root,
            gitdir,
            ["config", "--get-all", "remote.pushDefault"],
            label="Git default push-remote inspection",
            allow_absent=True,
        ),
        description="Git default push-remote inspection",
    )
    remote_push_refspecs = _lines(
        _run_git(
            git,
            root,
            gitdir,
            ["config", "--get-all", f"remote.{remote_name}.push"],
            label="Git remote push-refspec inspection",
            allow_absent=True,
        ),
        description="Git remote push-refspec inspection",
    )
    remote_mirror = _lines(
        _run_git(
            git,
            root,
            gitdir,
            ["config", "--bool", "--get-all", f"remote.{remote_name}.mirror"],
            label="Git remote mirror inspection",
            allow_absent=True,
        ),
        description="Git remote mirror inspection",
    )
    remote_receivepack = _git_config_values(
        git,
        root,
        gitdir,
        key=f"remote.{remote_name}.receivepack",
        description="Git selected-remote receive-pack inspection",
    )
    remote_vcs = _git_config_values(
        git,
        root,
        gitdir,
        key=f"remote.{remote_name}.vcs",
        description="Git selected-remote VCS-helper inspection",
    )
    remote_proxy = _git_config_values(
        git,
        root,
        gitdir,
        key=f"remote.{remote_name}.proxy",
        description="Git selected-remote proxy inspection",
    )
    push_default = _lines(
        _run_git(
            git,
            root,
            gitdir,
            ["config", "--get-all", "push.default"],
            label="Git default push mode inspection",
            allow_absent=True,
        ),
        description="Git default push mode inspection",
    )
    push_follow_tags = _lines(
        _run_git(
            git,
            root,
            gitdir,
            ["config", "--bool", "--get-all", "push.followTags"],
            label="Git push follow-tags inspection",
            allow_absent=True,
        ),
        description="Git push follow-tags inspection",
    )
    push_gpg_sign = _git_config_values(
        git,
        root,
        gitdir,
        key="push.gpgSign",
        description="Git push-signing inspection",
    )
    push_options = _git_config_values(
        git,
        root,
        gitdir,
        key="push.pushOption",
        description="Git configured push-option inspection",
    )
    core_ssh_command = _git_config_values(
        git,
        root,
        gitdir,
        key="core.sshCommand",
        description="Git SSH-command inspection",
    )
    core_ask_pass = _git_config_values(
        git,
        root,
        gitdir,
        key="core.askPass",
        description="Git askpass inspection",
    )
    core_attributes_file = _git_config_values(
        git,
        root,
        gitdir,
        key="core.attributesFile",
        description="Git attributes-file inspection",
    )
    core_git_proxy = _git_config_values(
        git,
        root,
        gitdir,
        key="core.gitProxy",
        description="Git proxy-command inspection",
    )
    core_hooks_path = _git_config_values(
        git,
        root,
        gitdir,
        key="core.hooksPath",
        description="Git hooks-path inspection",
    )
    core_whitespace = _git_config_values(
        git,
        root,
        gitdir,
        key="core.whitespace",
        description="Git whitespace-rule inspection",
    )
    effective_http_config_keys = _effective_http_config_keys(git, root, gitdir)
    effective_http_proxies = _effective_http_proxy_values(
        git,
        root,
        gitdir,
        fetch_urls=fetch_urls,
        push_urls=push_urls,
    )
    replacement_refs = _lines(
        _run_git(
            git,
            root,
            gitdir,
            ["for-each-ref", "--format=%(refname)", "refs/replace"],
            label="Git replacement-ref inspection",
        ),
        description="Git replacement-ref inspection",
    )
    raw_commit = _run_git(
        git,
        root,
        gitdir,
        ["cat-file", "commit", head],
        label="raw Git candidate-commit inspection",
    )
    tree_oid, parents = _parse_raw_commit(raw_commit, object_format=object_format)
    candidate_blobs = _candidate_blob_snapshot(git, root, gitdir, expected)
    tree: tuple[tuple[str, str, str], ...] = ()
    if phase is HandoffPhase.COMMITTED:
        tree = _parse_tree_entries(
            _run_git(
                git,
                root,
                gitdir,
                ["ls-tree", "-r", "-z", "--full-tree", tree_oid],
                label="Git candidate-tree inspection",
            ),
            object_format=object_format,
        )
    tag = (
        _tag_state(
            git,
            root,
            gitdir,
            tag_ref=tag_ref,
            object_format=object_format,
        )
        if tag_ref is not None
        else None
    )
    return _GitState(
        head_ref=head_ref,
        head=head,
        remote_tracking=remote_tracking,
        upstream=upstream,
        fetch_urls=fetch_urls,
        push_urls=push_urls,
        branch_push_remote=branch_push_remote,
        default_push_remote=default_push_remote,
        remote_push_refspecs=remote_push_refspecs,
        remote_mirror=remote_mirror,
        remote_receivepack=remote_receivepack,
        remote_vcs=remote_vcs,
        remote_proxy=remote_proxy,
        push_default=push_default,
        push_follow_tags=push_follow_tags,
        push_gpg_sign=push_gpg_sign,
        push_options=push_options,
        core_ssh_command=core_ssh_command,
        core_ask_pass=core_ask_pass,
        core_attributes_file=core_attributes_file,
        core_git_proxy=core_git_proxy,
        core_hooks_path=core_hooks_path,
        effective_http_config_keys=effective_http_config_keys,
        effective_http_proxies=effective_http_proxies,
        replacement_refs=replacement_refs,
        core_whitespace=core_whitespace,
        candidate_blobs=candidate_blobs,
        parents=parents,
        committed_tree=tree,
        tag=tag,
    )


def _git_state_errors(
    state: _GitState,
    expected: dict[str, _ExpectedFile],
    *,
    phase: HandoffPhase,
    remote_name: str,
    branch: str,
    expected_fetch_url: str,
    expected_push_url: str,
    expected_parent_commit: str,
) -> list[str]:
    errors: list[str] = []
    expected_head_ref = f"refs/heads/{branch}"
    expected_upstream = f"refs/remotes/{remote_name}/{branch}"
    if state.head_ref != expected_head_ref:
        errors.append("public clone HEAD is detached or attached to the wrong branch")
    if state.remote_tracking != expected_parent_commit:
        errors.append("public clone remote-tracking ref does not equal the expected parent")
    if state.upstream != expected_upstream:
        errors.append("public clone branch upstream does not equal the selected remote branch")
    if any(_url_has_credentials(value) for value in state.fetch_urls):
        errors.append("public clone fetch URL contains embedded credentials")
    if any(_url_has_credentials(value) for value in state.push_urls):
        errors.append("public clone push URL contains embedded credentials")
    if any(_url_uses_remote_helper(value) for value in state.fetch_urls):
        errors.append("public clone fetch URL uses a forbidden executable remote helper")
    if any(_url_uses_remote_helper(value) for value in state.push_urls):
        errors.append("public clone push URL uses a forbidden executable remote helper")
    if state.fetch_urls != (expected_fetch_url,):
        errors.append("public clone does not have exactly the expected fetch URL")
    if state.push_urls != (expected_push_url,):
        errors.append("public clone does not have exactly the expected push URL")
    if state.branch_push_remote:
        errors.append("public clone branch pushRemote must be unset for explicit publication")
    if state.default_push_remote:
        errors.append("public clone remote.pushDefault must be unset for explicit publication")
    if state.remote_push_refspecs:
        errors.append("public clone selected remote must not configure default push refspecs")
    if state.remote_mirror not in {(), ("false",)}:
        errors.append("public clone selected remote must not enable mirror publication")
    if state.remote_receivepack:
        errors.append("public clone selected remote receivepack must be unset")
    if state.remote_vcs:
        errors.append("public clone selected remote VCS helper must be unset")
    if state.remote_proxy:
        errors.append("public clone selected remote proxy must be unset")
    allowed_push_defaults = {"nothing", "current", "upstream", "simple"}
    if len(state.push_default) > 1 or any(
        value not in allowed_push_defaults for value in state.push_default
    ):
        errors.append("public clone push.default configuration can broaden publication")
    if state.push_follow_tags not in {(), ("false",)}:
        errors.append("public clone must not enable automatic tag publication")
    false_values = {"0", "false", "no", "off"}
    if any(value.casefold() not in false_values for value in state.push_gpg_sign):
        errors.append("public clone must not enable or conditionally request signed pushes")
    if state.push_options:
        errors.append("public clone must not configure default push options")
    if state.core_ssh_command:
        errors.append("public clone core.sshCommand must be unset")
    if state.core_ask_pass:
        errors.append("public clone core.askPass must be unset")
    if state.core_attributes_file:
        errors.append("public clone core.attributesFile must be unset")
    if state.core_git_proxy:
        errors.append("public clone core.gitProxy must be unset")
    if state.core_hooks_path:
        errors.append("public clone core.hooksPath must be unset")
    if state.core_whitespace:
        errors.append("public clone core.whitespace must be unset")
    if state.effective_http_config_keys:
        errors.append("public clone must not contain effective HTTP transport configuration")
    if any(values for _role, values in state.effective_http_proxies):
        errors.append("public clone must not configure an effective HTTP proxy")
    if state.replacement_refs:
        errors.append("public clone contains forbidden Git replacement refs")
    if phase is HandoffPhase.STAGED:
        if state.head != expected_parent_commit:
            errors.append("staged handoff HEAD does not equal the expected parent")
    else:
        if len(state.parents) != 1:
            errors.append("candidate commit must have exactly one parent")
        elif state.parents[0] != expected_parent_commit:
            errors.append("candidate commit parent does not equal the expected parent")
        errors.extend(_committed_tree_errors(state.committed_tree, expected))
        if state.tag is not None and state.tag.peeled_commit != state.head:
            errors.append("selected tag does not peel to the checked candidate commit")
    return errors


def check_public_handoff(
    *,
    phase: HandoffPhase,
    export_root: Path,
    public_clone_root: Path,
    authoring_root: Path,
    git_executable: Path | None,
    temporary_root: Path,
    remote_name: str,
    branch: str,
    expected_fetch_url: str,
    expected_push_url: str,
    expected_parent_commit: str,
    tag_ref: str | None = None,
    git_executable_fd: int | None = None,
) -> dict[str, object]:
    """Return a receipt without mutating protected roots or Git state.

    Bounded ephemeral files are created only below ``temporary_root`` and are
    removed before the terminal isolation check.
    """

    if not isinstance(phase, HandoffPhase):
        raise TypeError("phase must be a HandoffPhase")
    report = _base_report(
        phase=phase,
        remote_name=remote_name,
        branch=branch,
        expected_parent_commit=expected_parent_commit,
        tag_ref=tag_ref,
    )
    errors = report["errors"]
    if not isinstance(errors, list):
        raise TypeError("handoff report lost its errors list")
    if sys.platform != "linux":
        errors.append(
            "public handoff verification requires the qualified Linux container boundary"
        )
        return _deduplicate_report_errors(report)
    errors.extend(
        _cli_validation_errors(
            phase=phase,
            remote_name=remote_name,
            branch=branch,
            expected_fetch_url=expected_fetch_url,
            expected_push_url=expected_push_url,
            expected_parent_commit=expected_parent_commit,
            tag_ref=tag_ref,
        )
    )
    if errors:
        return _deduplicate_report_errors(report)
    if (git_executable is None) == (git_executable_fd is None):
        errors.append(
            "exactly one reviewed Git executable path or inherited descriptor is required"
        )
    if git_executable_fd is not None and (
        isinstance(git_executable_fd, bool) or git_executable_fd < 3
    ):
        errors.append("reviewed Git executable descriptor must be at least 3")
    for description, path in (
        ("public export root", export_root),
        ("public clone root", public_clone_root),
        ("authoring root", authoring_root),
        ("temporary root", temporary_root),
    ):
        if not path.is_absolute():
            errors.append(f"{description} must use an absolute path")
    if git_executable is not None and not git_executable.is_absolute():
        errors.append("reviewed Git executable must use an absolute path")
    if errors:
        return _deduplicate_report_errors(report)
    resources: list[tuple[str, Callable[[], object]]] = []
    export_binding: safe_paths.OutputDirectoryBinding | None = None
    public_binding: safe_paths.OutputDirectoryBinding | None = None
    authoring_binding: safe_paths.OutputDirectoryBinding | None = None
    temporary_binding: safe_paths.OutputDirectoryBinding | None = None
    git_binding: _GitExecutableBinding | None = None
    public_git: public_release_check._GitInventoryBinding | None = None
    public_storage: _GitStorageBinding | None = None
    authoring_storage: _GitStorageBinding | None = None
    public_config: public_release_check._RegularFileBinding | None = None
    try:
        export_binding = safe_paths.open_output_directory(
            export_root,
            create_missing=False,
        )
        resources.append(("public export root", export_binding.close))
        export_snapshot = public_release_check.checked_public_export_ownership_descriptor(
            export_binding.descriptor
        )
        errors.extend(
            _loaded_verifier_origin_errors(
                export_binding.bound_path,
                export_snapshot,
            )
        )
        if errors:
            raise ValueError("handoff verifier source boundary failed")

        public_binding = safe_paths.open_output_directory(
            public_clone_root,
            create_missing=False,
        )
        resources.append(("public clone root", public_binding.close))
        authoring_binding = safe_paths.open_output_directory(
            authoring_root,
            create_missing=False,
        )
        resources.append(("authoring root", authoring_binding.close))
        temporary_binding = safe_paths.open_output_directory(
            temporary_root,
            create_missing=False,
        )
        resources.append(("handoff temporary root", temporary_binding.close))
        temporary_inventory = public_release_check._inventory_release_tree_descriptor(
            temporary_binding.descriptor
        )
        if temporary_inventory.errors:
            raise ValueError("handoff temporary root could not be enumerated safely")
        if any(
            (
                temporary_inventory.files,
                temporary_inventory.directories,
                temporary_inventory.symlinks,
                temporary_inventory.special,
            )
        ):
            raise ValueError("handoff temporary root must be empty")
        errors.extend(
            _root_separation_errors(
                (
                    ("public export", export_binding),
                    ("public clone", public_binding),
                    ("authoring checkout", authoring_binding),
                    ("handoff temporary root", temporary_binding),
                )
            )
        )
        if errors:
            raise ValueError("handoff roots failed the isolation boundary")

        if git_executable is not None:
            git_binding = _open_git_executable_binding(git_executable)
        else:
            if git_executable_fd is None:
                raise ValueError("reviewed Git executable descriptor is missing")
            git_binding = _open_inherited_git_executable_binding(git_executable_fd)
        resources.append(("reviewed Git executable", git_binding.close))
        report["git_executable_sha256"] = git_binding.sha256
        for description, root_binding in (
            ("public export", export_binding),
            ("public clone", public_binding),
            ("authoring checkout", authoring_binding),
            ("handoff temporary root", temporary_binding),
        ):
            if safe_paths.path_within_root(
                git_binding.file.lexical_path,
                root_binding.bound_path,
            ):
                errors.append(
                    f"reviewed Git executable must be outside the {description}"
                )
        if errors:
            raise ValueError("reviewed Git executable failed the isolation boundary")
        git_binding.require_current()
        try:
            public_release_check.require_git_fsmonitor_boolean_support(
                temporary_binding.bound_path,
                git_command=git_binding.command,
                git_pass_fds=git_binding.pass_fds,
                inherit_non_git_environment=False,
                environment=_GIT_ENVIRONMENT,
            )
        finally:
            git_binding.require_current()
        temporary_descriptor_path = (
            Path("/proc/self/fd") / str(temporary_binding.descriptor)
        )
        if not temporary_descriptor_path.is_dir():
            raise ValueError(
                "handoff temporary root requires a usable Linux procfs descriptor path"
            )
        git_parser_pass_fds = (
            *git_binding.pass_fds,
            temporary_binding.descriptor,
        )

        public_inventory = public_release_check._inventory_release_tree_descriptor(
            public_binding.descriptor
        )
        if public_inventory.errors:
            raise ValueError("public clone could not be enumerated safely")
        if ".git" not in public_inventory.directories:
            raise ValueError("public clone must use an ordinary .git directory")
        git_binding.require_current()
        try:
            public_git = public_release_check._open_git_inventory_binding(
                public_clone_root,
                public_inventory,
                git_command=git_binding.command,
                git_pass_fds=git_parser_pass_fds,
                temporary_root=temporary_descriptor_path,
                inherit_non_git_environment=False,
            )
        finally:
            git_binding.require_current()
        if public_git is None:
            raise ValueError("public clone must have a usable Git inventory")
        resources.insert(0, ("public clone Git inventory", public_git.close))
        if public_git.index is None or public_git.snapshot_file is None:
            raise ValueError("public clone must have a usable nonempty Git index")
        object_format = public_git.object_format
        if object_format not in {"sha1", "sha256"}:
            raise ValueError("public clone Git object format is unavailable")
        report["object_format"] = object_format
        report["remote_target_sha256"] = _remote_target_sha256(
            remote_name=remote_name,
            fetch_url=expected_fetch_url,
            push_url=expected_push_url,
            object_format=object_format,
        )
        if len(expected_parent_commit) != (40 if object_format == "sha1" else 64):
            errors.append("expected parent OID length does not match the public clone object format")

        expected, marker_sha256 = _expected_export_files(
            export_root,
            export_snapshot,
            object_format=object_format,
        )
        report["payload_file_count"] = len(expected)
        report["export_marker_sha256"] = marker_sha256
        if any(PurePosixPath(relative).name == ".gitattributes" for relative in expected):
            errors.append(
                "public export must not contain .gitattributes under this release procedure"
            )
        initial_worktree = _worktree_snapshot(
            public_clone_root,
            public_binding,
            expected,
            errors,
        )
        git_binding.require_current()
        try:
            entries = public_release_check.git_stage_entries_from_index_snapshot(
                public_git.metadata.physical_root,
                public_git.snapshot_file,
                object_format=object_format,
                git_command=git_binding.command,
                git_pass_fds=git_parser_pass_fds,
                temporary_root=temporary_descriptor_path,
                inherit_non_git_environment=False,
            )
        finally:
            git_binding.require_current()
        errors.extend(_index_errors(entries, expected))

        authoring_metadata = public_release_check._git_metadata_binding(
            authoring_root,
            _minimal_git_inventory(authoring_binding),
        )
        if authoring_metadata is None:
            raise ValueError("authoring root must be a Git checkout")
        public_storage = _open_storage_binding(
            git_binding,
            public_clone_root,
            public_git.metadata,
        )
        resources.insert(0, ("public Git storage", public_storage.close))
        authoring_storage = _open_storage_binding(
            git_binding,
            authoring_root,
            authoring_metadata,
        )
        resources.insert(0, ("authoring Git storage", authoring_storage.close))
        expected_public_gitdir = public_binding.bound_path / ".git"
        if (
            public_storage.gitdir.bound_path != expected_public_gitdir
            or public_storage.common.bound_path != expected_public_gitdir
            or public_storage.gitdir.identity != public_storage.common.identity
        ):
            errors.append("public clone must use one clone-local ordinary Git directory")
        if public_storage.objects.bound_path != expected_public_gitdir / "objects":
            errors.append("public clone primary object store must be clone-local")

        public_config = public_release_check._open_regular_descriptor(
            public_storage.common.bound_path / "config",
            description="public Git local config",
            require_single_link=True,
        )
        resources.insert(0, ("public Git local config", public_config.close))
        initial_public_control = _git_control_snapshot(
            public_storage,
            public=True,
            errors=errors,
        )
        initial_authoring_control = _git_control_snapshot(
            authoring_storage,
            public=False,
            errors=errors,
        )
        errors.extend(
            _git_control_independence_errors(
                initial_public_control,
                initial_authoring_control,
            )
        )
        errors.extend(
            _local_config_control_errors(
                _exact_local_config_keys(
                    git_binding,
                    public_clone_root,
                    public_git.metadata.gitdir,
                    public_config,
                )
            )
        )

        public_graft_info = _graft_info_snapshot(
            public_storage,
            errors=errors,
        )
        public_objects = _object_store_snapshot(
            public_storage,
            public=True,
            errors=errors,
        )
        authoring_objects = _object_store_snapshot(
            authoring_storage,
            public=False,
            errors=errors,
        )
        errors.extend(
            _storage_independence_errors(
                public_storage,
                authoring_storage,
                initial_public_control,
                initial_authoring_control,
                public_objects,
                authoring_objects,
            )
        )
        initial_git_state = _git_state(
            git_binding,
            public_clone_root,
            public_git.metadata.gitdir,
            phase=phase,
            remote_name=remote_name,
            branch=branch,
            tag_ref=tag_ref,
            object_format=object_format,
            expected=expected,
        )
        errors.extend(
            _git_state_errors(
                initial_git_state,
                expected,
                phase=phase,
                remote_name=remote_name,
                branch=branch,
                expected_fetch_url=expected_fetch_url,
                expected_push_url=expected_push_url,
                expected_parent_commit=expected_parent_commit,
            )
        )
        if phase is HandoffPhase.COMMITTED:
            report["candidate_commit"] = initial_git_state.head
        if initial_git_state.tag is not None:
            report["tag_object_type"] = initial_git_state.tag.object_type
            report["tag_oid"] = initial_git_state.tag.oid
            report["tag_peeled_commit"] = initial_git_state.tag.peeled_commit

        export_binding.require_unchanged_chain(description="public export root")
        terminal_export = public_release_check.checked_public_export_ownership_descriptor(
            export_binding.descriptor
        )
        if terminal_export != export_snapshot:
            errors.append("public export changed during handoff verification")
        errors.extend(
            _loaded_verifier_origin_errors(
                export_binding.bound_path,
                export_snapshot,
            )
        )
        terminal_worktree = _worktree_snapshot(
            public_clone_root,
            public_binding,
            expected,
            errors,
        )
        if terminal_worktree != initial_worktree:
            errors.append("public clone worktree changed during handoff verification")
        public_git.require_current()
        public_storage.require_current(description="public clone")
        authoring_storage.require_current(description="authoring checkout")
        terminal_git_state = _git_state(
            git_binding,
            public_clone_root,
            public_git.metadata.gitdir,
            phase=phase,
            remote_name=remote_name,
            branch=branch,
            tag_ref=tag_ref,
            object_format=object_format,
            expected=expected,
        )
        if terminal_git_state != initial_git_state:
            errors.append("public Git refs or configuration changed during handoff verification")
        terminal_public_control = _git_control_snapshot(
            public_storage,
            public=True,
            errors=errors,
        )
        terminal_authoring_control = _git_control_snapshot(
            authoring_storage,
            public=False,
            errors=errors,
        )
        if terminal_public_control != initial_public_control:
            errors.append("public Git control metadata changed during handoff verification")
        if terminal_authoring_control != initial_authoring_control:
            errors.append("authoring Git control metadata changed during handoff verification")
        errors.extend(
            _git_control_independence_errors(
                terminal_public_control,
                terminal_authoring_control,
            )
        )
        public_config.require_current(description="public Git local config")
        terminal_public_graft_info = _graft_info_snapshot(
            public_storage,
            errors=errors,
        )
        if terminal_public_graft_info != public_graft_info:
            errors.append("public Git common info directory changed during handoff verification")
        terminal_public_objects = _object_store_snapshot(
            public_storage,
            public=True,
            errors=errors,
        )
        terminal_authoring_objects = _object_store_snapshot(
            authoring_storage,
            public=False,
            errors=errors,
        )
        if terminal_public_objects != public_objects:
            errors.append("public Git object store changed during handoff verification")
        if terminal_authoring_objects != authoring_objects:
            errors.append("authoring Git object store changed during handoff verification")
        errors.extend(
            _storage_independence_errors(
                public_storage,
                authoring_storage,
                terminal_public_control,
                terminal_authoring_control,
                terminal_public_objects,
                terminal_authoring_objects,
            )
        )
        terminal_authoring_metadata = public_release_check._git_metadata_binding(
            authoring_root,
            _minimal_git_inventory(authoring_binding),
        )
        if terminal_authoring_metadata != authoring_metadata:
            errors.append("authoring Git metadata changed during handoff verification")
        public_binding.require_unchanged_chain(description="public clone root")
        authoring_binding.require_unchanged_chain(description="authoring root")
        git_binding.require_current()
        temporary_binding.require_lexical_binding(
            description="handoff temporary root"
        )
        terminal_temporary = public_release_check._inventory_release_tree_descriptor(
            temporary_binding.descriptor
        )
        if terminal_temporary.errors or any(
            (
                terminal_temporary.files,
                terminal_temporary.directories,
                terminal_temporary.symlinks,
                terminal_temporary.special,
            )
        ):
            errors.append("handoff temporary root was not restored to empty")
    except (OSError, RuntimeError, ValueError) as exc:
        errors.append(f"public handoff verification failed closed: {exc}")
    finally:
        try:
            resource_cleanup.cleanup_actions(resources)
        except Exception as cleanup:
            errors.append(f"public handoff resource cleanup failed: {cleanup}")
    return _deduplicate_report_errors(report)


def _parser() -> _JsonArgumentParser:
    parser = _JsonArgumentParser(
        description="Verify an exact sanitized-export handoff to an independent public clone.",
        allow_abbrev=False,
    )
    parser.add_argument(
        "--phase",
        type=HandoffPhase,
        choices=tuple(HandoffPhase),
        required=True,
        help="Handoff state to verify: staged tree or committed candidate.",
    )
    parser.add_argument(
        "--export-root",
        type=Path,
        required=True,
        help="Absolute root of the exact sanitized export being handed off.",
    )
    parser.add_argument(
        "--public-clone-root",
        type=Path,
        required=True,
        help="Absolute root of the independent public Git clone to inspect.",
    )
    parser.add_argument(
        "--authoring-root",
        type=Path,
        required=True,
        help="Absolute private authoring root that must remain isolated.",
    )
    git_source = parser.add_mutually_exclusive_group(required=True)
    git_source.add_argument(
        "--git-executable",
        type=Path,
        help="absolute path of the reviewed Git executable",
    )
    git_source.add_argument(
        "--git-executable-fd",
        type=int,
        help="already-open reviewed Git executable descriptor inherited by this process",
    )
    parser.add_argument(
        "--temporary-root",
        type=Path,
        required=True,
        help="Absolute empty scratch root for bounded verifier-owned files.",
    )
    parser.add_argument(
        "--remote-name",
        required=True,
        help="Exact reviewed Git remote name configured in the public clone.",
    )
    parser.add_argument(
        "--branch",
        required=True,
        help="Exact canonical public branch name being prepared.",
    )
    parser.add_argument(
        "--expected-fetch-url",
        required=True,
        help="Exact credential-free fetch URL expected for the selected remote.",
    )
    parser.add_argument(
        "--expected-push-url",
        required=True,
        help="Exact credential-free push URL expected for the selected remote.",
    )
    parser.add_argument(
        "--expected-parent-commit",
        required=True,
        help=(
            "Fresh full lowercase parent commit OID: staged HEAD, or the sole "
            "parent of the committed candidate."
        ),
    )
    parser.add_argument(
        "--tag-ref",
        help=(
            "Optional canonical full refs/tags/... ref to preflight in committed "
            "phase."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
    except _CliError as exc:
        report = _base_report(
            phase=None,
            remote_name=None,
            branch=None,
            expected_parent_commit=None,
            tag_ref=None,
        )
        errors = report["errors"]
        if isinstance(errors, list):
            errors.append(f"invalid command arguments: {exc}")
        sys.stdout.write(_canonical_json(report))
        return 2
    validation_errors = _cli_validation_errors(
        phase=args.phase,
        remote_name=args.remote_name,
        branch=args.branch,
        expected_fetch_url=args.expected_fetch_url,
        expected_push_url=args.expected_push_url,
        expected_parent_commit=args.expected_parent_commit,
        tag_ref=args.tag_ref,
    )
    for description, path in (
        ("public export root", args.export_root),
        ("public clone root", args.public_clone_root),
        ("authoring root", args.authoring_root),
        ("temporary root", args.temporary_root),
    ):
        if not path.is_absolute():
            validation_errors.append(f"{description} must use an absolute path")
    if args.git_executable is not None and not args.git_executable.is_absolute():
        validation_errors.append("reviewed Git executable must use an absolute path")
    if args.git_executable_fd is not None and args.git_executable_fd < 3:
        validation_errors.append("reviewed Git executable descriptor must be at least 3")
    if validation_errors:
        report = _base_report(
            phase=args.phase,
            remote_name=args.remote_name,
            branch=args.branch,
            expected_parent_commit=args.expected_parent_commit,
            tag_ref=args.tag_ref,
        )
        errors = report["errors"]
        if isinstance(errors, list):
            errors.extend(validation_errors)
        sys.stdout.write(_canonical_json(report))
        return 2
    report = check_public_handoff(
        phase=args.phase,
        export_root=args.export_root,
        public_clone_root=args.public_clone_root,
        authoring_root=args.authoring_root,
        git_executable=args.git_executable,
        temporary_root=args.temporary_root,
        remote_name=args.remote_name,
        branch=args.branch,
        expected_fetch_url=args.expected_fetch_url,
        expected_push_url=args.expected_push_url,
        expected_parent_commit=args.expected_parent_commit,
        tag_ref=args.tag_ref,
        git_executable_fd=args.git_executable_fd,
    )
    sys.stdout.write(_canonical_json(report))
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
