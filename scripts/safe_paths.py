#!/usr/bin/env python3

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
import re
import secrets
import shlex
import stat
import sys
from typing import Any
import unicodedata

import resource_cleanup


ALLOWED_SYSTEM_SYMLINK_TARGETS = {
    Path("/" + "tmp"): Path("/" + "private" + "/" + "tmp"),
    Path("/" + "var"): Path("/" + "private" + "/" + "var"),
}
LOCAL_PATH_CHARS = r"[^\s`'\"<>)]+"
FILE_URI_PREFIX = r"(?:file://)?"
WINDOWS_USER_PATH_PATTERN = r"(?:/[A-Za-z]:[\\/]Users[\\/]|[A-Za-z]:[\\/]Users[\\/])" + LOCAL_PATH_CHARS
WINDOWS_ABSOLUTE_PATH_PATTERN = r"(?:/[A-Za-z]:[\\/]|[A-Za-z]:[\\/])" + LOCAL_PATH_CHARS


def _absolute_prefix(*parts: str) -> str:
    return "/" + "/".join(parts) + "/"


# Generic local filesystem path shapes that must not leak into portable public
# templates, rendered integration outputs, automation prompts, or feedback files.
# These are deny-list patterns, not project locations or execution defaults.
HOST_IDENTITY_PREFIXES = (
    _absolute_prefix("Users"),
    _absolute_prefix("home"),
    _absolute_prefix("virtual", "projects"),
    _absolute_prefix("Volumes"),
)
LOCAL_ABSOLUTE_PREFIXES = (
    *HOST_IDENTITY_PREFIXES,
    _absolute_prefix("opt"),
    _absolute_prefix("var", "home"),
    _absolute_prefix("tmp"),
    _absolute_prefix("private", "tmp"),
    _absolute_prefix("workspace"),
    _absolute_prefix("workspaces"),
    _absolute_prefix("mnt"),
    _absolute_prefix("private", "var"),
    _absolute_prefix("var", "folders"),
)
PRIVATE_STATE_PARTS = (
    ".codex",
    ".cursor",
    ".continue",
    ".mcp.json",
    "private",
    "review_artifacts",
    "external_review",
    "notes",
    "scratch",
    "transcripts",
    "session_logs",
    "captures",
    "source_dumps",
    "source_material",
    "local",
    "tmp",
)
PRIVATE_STATE_PATH_RE = re.compile(
    r"(?<![\w.-])(?:"
    + "|".join(
        re.escape(part) + (r"(?:[\\/]|$)" if "." in part else r"[\\/]")
        for part in PRIVATE_STATE_PARTS
    )
    + r")"
)
INTERNAL_LOCAL_STATE_PATTERNS = (
    re.compile(
        r"\binternal_(?:update|framework|agent|june|april|input)[A-Za-z0-9_.-]*\.(?:md|json|txt)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b[A-Za-z0-9_.-]*_STATE[A-Za-z0-9_.-]*\.md\b"),
    re.compile(r"\b[A-Za-z][A-Za-z0-9_.-]*_Commit\.md\b"),
)
PATH_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
URI_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
FRAMEWORK_REFERENCE_METACHARACTERS = frozenset("`'\";|&()<>!*?#[]@\\%^")
PROJECT_RELATIVE_REFERENCE_METACHARACTERS = (
    FRAMEWORK_REFERENCE_METACHARACTERS | frozenset("${}\\%^~")
)
SIMPLE_ENV_REFERENCE_RE = re.compile(
    r"\$(?:[A-Za-z_][A-Za-z0-9_]*|\{[A-Za-z_][A-Za-z0-9_]*\})"
)
_FRAMEWORK_CHARTER_REFERENCE_RE = re.compile(
    r"(?P<ref>[^\s`@<>]*?)/runtime/operative_charter\.md"
)
DEFAULT_JSON_INPUT_MAX_BYTES = 4 * 1024 * 1024
MAX_JSON_NESTING_DEPTH = 256
OPEN_SUPPORTS_DIR_FD = os.open in getattr(os, "supports_dir_fd", set())


class DuplicateJSONKeyError(json.JSONDecodeError):
    """JSON syntax error raised when an object repeats a member name."""

    def __init__(self, member_name: str) -> None:
        self.member_name = member_name
        super().__init__(f"duplicate JSON key: {member_name}", "", 0)


class NonFiniteJSONNumberError(json.JSONDecodeError):
    """JSON syntax error raised for a non-finite numeric value."""

    def __init__(self, token: str) -> None:
        self.token = token
        super().__init__(f"non-finite JSON number: {token}", "", 0)


def _path_pattern(prefixes: tuple[str, ...], windows_pattern: str) -> str:
    return r"(?:" + "|".join([*(re.escape(prefix) + LOCAL_PATH_CHARS for prefix in prefixes), windows_pattern]) + r")"


HOST_IDENTITY_PATH_BODY = _path_pattern(HOST_IDENTITY_PREFIXES, WINDOWS_USER_PATH_PATTERN)
LOCAL_ABSOLUTE_PATH_BODY = _path_pattern(LOCAL_ABSOLUTE_PREFIXES, WINDOWS_ABSOLUTE_PATH_PATTERN)
ANY_ABSOLUTE_PATH_BODY = r"(?:" + r"/(?!/)" + LOCAL_PATH_CHARS + r"|" + WINDOWS_ABSOLUTE_PATH_PATTERN + r")"
HOST_IDENTITY_PATH_RE = re.compile(r"(?<![\w.-])" + FILE_URI_PREFIX + HOST_IDENTITY_PATH_BODY)
LOCAL_ABSOLUTE_PATH_RE = re.compile(r"(?<![\w.-])" + FILE_URI_PREFIX + LOCAL_ABSOLUTE_PATH_BODY)
ANY_ABSOLUTE_PATH_RE = re.compile(r"(?<![\w.-])" + FILE_URI_PREFIX + ANY_ABSOLUTE_PATH_BODY)
HOST_IDENTITY_PATH_START_RE = re.compile(r"^" + FILE_URI_PREFIX + HOST_IDENTITY_PATH_BODY)
URI_START_RE = re.compile(
    r"(?<![A-Za-z0-9+.-])(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*)://",
)
URI_SPAN_TERMINATORS = frozenset("`'\"<>|;&\\")


def _non_file_uri_spans(text: str) -> list[tuple[int, int]]:
    """Return bounded URI-token spans while retaining unmatched delimiters."""

    spans: list[tuple[int, int]] = []
    cursor = 0
    while match := URI_START_RE.search(text, cursor):
        cursor = match.end()
        if match.group("scheme").casefold() == "file":
            continue
        end = match.end()
        parenthesis_depth = 0
        while end < len(text):
            character = text[end]
            if character.isspace() or character in URI_SPAN_TERMINATORS:
                break
            if character == "(":
                parenthesis_depth += 1
            elif character == ")":
                if parenthesis_depth == 0:
                    break
                parenthesis_depth -= 1
            end += 1
        spans.append((match.start(), end))
        cursor = end
    return spans


def _without_non_file_uris(text: str) -> str:
    characters = list(text)
    for start, end in _non_file_uri_spans(text):
        characters[start:end] = " " * (end - start)
    return "".join(characters)


def contains_host_identity_path(text: str) -> bool:
    return bool(HOST_IDENTITY_PATH_RE.search(text))


def contains_local_absolute_path(text: str) -> bool:
    return bool(LOCAL_ABSOLUTE_PATH_RE.search(text))


def contains_absolute_path(text: str) -> bool:
    return bool(ANY_ABSOLUTE_PATH_RE.search(_without_non_file_uris(text)))


def starts_with_host_identity_path(text: str) -> bool:
    return bool(HOST_IDENTITY_PATH_START_RE.match(text))


def local_absolute_path_matches(text: str) -> list[str]:
    return [match.group(0) for match in LOCAL_ABSOLUTE_PATH_RE.finditer(text)]


def framework_reference_errors(value: str) -> list[str]:
    """Validate one filesystem reference that will also appear in shell commands.

    Framework references may be absolute, repo-relative, home-relative, or
    environment-variable based. They must remain one inert shell token because
    bootstrap writes them into executable verification commands as well as
    Markdown/runtime import paths.
    """
    if not value.strip():
        return ["framework reference must not be empty"]
    errors: list[str] = []
    if PATH_CONTROL_RE.search(value):
        errors.append("framework reference must not contain control characters")
    if any(character.isspace() for character in value):
        errors.append("framework reference must not contain whitespace")
    if any(character in FRAMEWORK_REFERENCE_METACHARACTERS for character in value):
        errors.append("framework reference must not contain shell or Markdown metacharacters")
    non_environment_text = SIMPLE_ENV_REFERENCE_RE.sub("", value)
    if any(character in non_environment_text for character in "${}"):
        errors.append(
            "framework reference may use only simple $NAME or ${NAME} environment-variable references"
        )
    if "~" in value and not (value == "~" or value.startswith("~/")):
        errors.append("framework reference may use home expansion only as '~' or a leading '~/'")
    if value.startswith("-"):
        errors.append("framework reference must not start with an option prefix")
    if "://" in value:
        errors.append("framework reference must be a filesystem reference, not a URI")
    if "{{" in value or "}}" in value:
        errors.append("framework reference must not contain unresolved template placeholders")
    if value.strip().casefold() in {"tbd", "todo", "replace me"}:
        errors.append("framework reference must be a concrete resolvable reference")
    return errors


def canonical_framework_reference(value: str) -> str:
    """Return one validated framework reference for every rendered surface."""

    errors = framework_reference_errors(value)
    if errors:
        raise ValueError("; ".join(errors))
    if value == "/":
        return value
    canonical = value.rstrip("/")
    return canonical or "/"


def framework_reference_path(value: str, relative: str) -> str:
    """Join a validated framework reference to one framework-relative path."""

    canonical = canonical_framework_reference(value)
    suffix = relative.lstrip("/")
    return f"/{suffix}" if canonical == "/" else f"{canonical}/{suffix}"


def shell_framework_path_token(value: str, relative: str) -> str:
    """Render one framework-relative path as exactly one inert shell token.

    Framework references may deliberately defer their root to ``$NAME``,
    ``${NAME}``, or ``~``.  Shell quoting must therefore preserve expansion
    while preventing the expanded value from becoming options or multiple
    arguments.  Required-value expansion also makes an unset or empty root
    fail closed instead of resolving against the current directory.
    """

    joined = framework_reference_path(value, relative)
    expansion_required = False
    if joined == "~" or joined.startswith("~/"):
        joined = "${HOME:?HOME is required}" + joined[1:]
        expansion_required = True

    def require_environment_value(match: re.Match[str]) -> str:
        nonlocal expansion_required
        expansion_required = True
        token = match.group(0)
        name = token[2:-1] if token.startswith("${") else token[1:]
        return f"${{{name}:?{name} is required}}"

    joined = SIMPLE_ENV_REFERENCE_RE.sub(require_environment_value, joined)
    return f'"{joined}"' if expansion_required else shlex.quote(joined)


def render_framework_reference_tokens(text: str, value: str) -> str:
    """Render framework placeholders without producing doubled separators."""

    canonical = canonical_framework_reference(value)
    prefix = "/" if canonical == "/" else f"{canonical}/"
    return text.replace("{{FRAMEWORK_ROOT}}/", prefix).replace(
        "{{FRAMEWORK_ROOT}}", canonical
    )


def extract_framework_references(text: str) -> list[str]:
    """Extract framework roots from rendered operative-charter references.

    The canonical filesystem root renders as ``/runtime/operative_charter.md``;
    its regex capture is empty and is normalized back to ``/`` here so every
    consumer handles that supported reference identically.
    """

    return [
        match.group("ref") or "/"
        for match in _FRAMEWORK_CHARTER_REFERENCE_RE.finditer(text)
    ]


def resolve_framework_reference(reference: str, project_root: Path) -> Path | None:
    """Resolve one concrete framework root relative to a project root.

    Environment or template references that remain unresolved are deliberately
    non-resolvable; callers decide whether their runtime may defer resolution.
    """

    expanded = os.path.expanduser(os.path.expandvars(reference))
    if "$" in expanded or expanded.strip() in {"", "{{FRAMEWORK_ROOT}}"}:
        return None
    path = Path(expanded)
    if not path.is_absolute():
        path = project_root / path
    return path.resolve(strict=False)


def project_relative_reference_errors(value: str, description: str) -> list[str]:
    """Validate a repo-relative path that is also rendered as one shell token."""

    errors: list[str] = []
    if PATH_CONTROL_RE.search(value):
        errors.append(f"{description} must not contain control characters")
    if any(character.isspace() for character in value):
        errors.append(f"{description} must not contain whitespace")
    if any(
        character in PROJECT_RELATIVE_REFERENCE_METACHARACTERS
        for character in value
    ):
        errors.append(
            f"{description} must not contain shell or Markdown metacharacters"
        )
    first_component = value.split("/", 1)[0]
    if first_component.startswith("-"):
        errors.append(f"{description} must not start with an option prefix")
    return errors


def path_within_root(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError:
        return False
    return True


def normalize_repo_relative_path(value: str, root: Path, *, description: str) -> str:
    """Return one safe POSIX repo-relative path or raise ``ValueError``.

    The lexical checks reject absolute, URI-like, Windows-style, traversal, and
    control-bearing values. The resolved check also rejects symlink
    components so a path that looks local cannot redirect evidence outside the
    selected repository root.
    """
    if not value or PATH_CONTROL_RE.search(value) or any(marker in value for marker in ("<", ">")):
        raise ValueError(f"{description} must be non-empty plain path text")
    if "://" in value or URI_SCHEME_RE.match(value):
        raise ValueError(f"{description} must be repo-relative, not a URI or absolute path: {value}")
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
        raise ValueError(f"{description} must be a safe repo-relative path: {value}")
    safe_relative_child(root, path, description=description)
    return path.as_posix()


def safe_relative_child(root: Path, relative_path: Path, *, description: str) -> Path:
    if relative_path.is_absolute():
        raise ValueError(f"{description} must be relative: {relative_path}")
    if ".." in relative_path.parts:
        raise ValueError(f"{description} must not contain traversal components: {relative_path}")
    candidate = root / relative_path
    current = root
    for part in relative_path.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"{description} must not include symlink components: {relative_path}")
    if not path_within_root(candidate, root):
        raise ValueError(f"{description} must stay under repository root: {relative_path}")
    return candidate


def bounded_input_errors(
    path: Path,
    root: Path,
    *,
    description: str,
    expected_kind: str = "file",
) -> list[str]:
    """Reject an existing input that escapes ``root`` or uses symlinks.

    Missing paths are left to the caller's ordinary required/optional handling.
    Existing inputs must be regular files or directories of the requested kind;
    the checker never follows a symlink to decide that question.
    """
    if expected_kind not in {"file", "directory"}:
        raise ValueError(f"unsupported expected input kind: {expected_kind}")
    absolute_root = root.expanduser().absolute()
    unsafe_root_symlinks = [
        component
        for component in symlink_components(absolute_root)
        if not is_allowed_system_symlink(component)
    ]
    if unsafe_root_symlinks:
        return [
            f"{description} root must not use symlink path components: "
            + ", ".join(str(component) for component in unsafe_root_symlinks)
        ]
    if absolute_root.exists() and not absolute_root.is_dir():
        return [f"{description} root must be a directory: {absolute_root}"]
    try:
        relative = path.relative_to(root)
        candidate = safe_relative_child(root, relative, description=description)
    except ValueError as exc:
        return [str(exc)]
    if not candidate.exists():
        return []
    if expected_kind == "file" and not candidate.is_file():
        return [f"{description} must be a regular file: {relative.as_posix()}"]
    if expected_kind == "directory" and not candidate.is_dir():
        return [f"{description} must be a directory: {relative.as_posix()}"]
    return []


def symlink_components(path: Path, root: Path | None = None) -> list[Path]:
    raw_path = path
    if root is not None:
        raw_root = root
        try:
            parts = raw_path.relative_to(raw_root).parts
        except ValueError:
            return []
        current = raw_root
        candidates = [current]
    else:
        parts = raw_path.parts
        if raw_path.is_absolute():
            current = Path(raw_path.anchor)
            parts = parts[1:]
            candidates = []
        else:
            current = Path()
            candidates = []
    for part in parts:
        if part in {"", "."}:
            continue
        current = current / part
        candidates.append(current)
    return [candidate for candidate in candidates if candidate.is_symlink()]


def is_allowed_system_symlink(component: Path) -> bool:
    target = ALLOWED_SYSTEM_SYMLINK_TARGETS.get(component)
    if target is None:
        return False
    try:
        return component.resolve(strict=True) == target.resolve(strict=True)
    except OSError:
        return False


def reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateJSONKeyError(key)
        result[key] = value
    return result


def reject_nonfinite_json_number(token: str) -> Any:
    raise NonFiniteJSONNumberError(token)


def parse_finite_json_float(token: str) -> float:
    value = float(token)
    if not math.isfinite(value):
        raise NonFiniteJSONNumberError(token)
    return value


def loads_json_no_duplicates(text: str) -> Any:
    depth = 0
    in_string = False
    escaped = False
    for index, character in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character in "[{":
            depth += 1
            if depth > MAX_JSON_NESTING_DEPTH:
                raise json.JSONDecodeError(
                    "JSON nesting exceeds the supported parser depth",
                    text,
                    index,
                )
        elif character in "]}":
            depth = max(0, depth - 1)
    try:
        return json.loads(
            text,
            object_pairs_hook=reject_duplicate_json_keys,
            parse_constant=reject_nonfinite_json_number,
            parse_float=parse_finite_json_float,
        )
    except RecursionError as exc:
        raise json.JSONDecodeError(
            "JSON nesting exceeds the supported parser depth",
            text,
            0,
        ) from exc


def _required_open_flag(name: str) -> int:
    value = getattr(os, name, None)
    if not isinstance(value, int) or value == 0:
        raise ValueError(
            f"descriptor-safe input validation requires platform flag {name}"
        )
    return value


def _descriptor_walk_supported() -> bool:
    return OPEN_SUPPORTS_DIR_FD


def _cleanup_descriptors(
    descriptors: tuple[tuple[str, int], ...],
    *,
    primary: BaseException | None = None,
) -> None:
    """Close every owned descriptor without masking an active failure."""

    resource_cleanup.cleanup_actions(
        tuple(
            (
                description,
                lambda descriptor=descriptor: os.close(descriptor),
            )
            for description, descriptor in descriptors
        ),
        primary=primary,
    )


def _physical_system_alias_path(path: Path) -> Path:
    """Map an explicitly trusted platform alias to its physical path."""

    for alias, target in ALLOWED_SYSTEM_SYMLINK_TARGETS.items():
        try:
            relative = path.relative_to(alias)
        except ValueError:
            continue
        if is_allowed_system_symlink(alias):
            return target / relative
    return path


def _filesystem_identity(value: str) -> str:
    """Return the collision identity used only for exact managed path spelling."""

    return unicodedata.normalize("NFC", value).casefold()


def exact_relative_path_spelling_errors(
    root: Path,
    relative_path: Path,
    *,
    description: str,
) -> list[str]:
    """Require exact directory-entry spelling below ``root`` without following links.

    Missing components remain the caller's ordinary missing-file concern.  A
    case- or Unicode-normalization alias is an identity error because it can be
    hidden on one filesystem and become a different path after transfer.
    """

    if relative_path.is_absolute() or not relative_path.parts or any(
        component in {"", ".", ".."} for component in relative_path.parts
    ):
        return [f"{description} must be a safe relative path: {relative_path}"]
    if (
        not _descriptor_walk_supported()
        or os.scandir not in getattr(os, "supports_fd", set())
    ):
        return [
            f"{description} exact spelling validation requires descriptor-safe "
            "directory enumeration"
        ]

    lexical_root = Path(os.path.abspath(os.fspath(root.expanduser())))
    physical_root = _physical_system_alias_path(lexical_root)
    if physical_root.anchor != "/":
        return [f"{description} root must be absolute: {lexical_root}"]
    root_components = physical_root.parts[1:]
    if any(component in {"", ".", ".."} for component in root_components):
        return [f"{description} root contains an unsafe path component: {lexical_root}"]

    directory_flags = (
        os.O_RDONLY
        | _required_open_flag("O_DIRECTORY")
        | _required_open_flag("O_NOFOLLOW")
        | getattr(os, "O_CLOEXEC", 0)
    )
    descriptor: int | None = None
    try:
        descriptor = os.open("/", directory_flags)
        for component in root_components:
            next_descriptor = os.open(
                component,
                directory_flags,
                dir_fd=descriptor,
            )
            previous_descriptor = descriptor
            descriptor = next_descriptor
            _cleanup_descriptors(
                ((f"{description} traversed root directory", previous_descriptor),)
            )

        for index, expected in enumerate(relative_path.parts):
            with os.scandir(descriptor) as entries:
                names = [entry.name for entry in entries]
            aliases = [
                name
                for name in names
                if _filesystem_identity(name) == _filesystem_identity(expected)
            ]
            if expected not in names:
                if aliases:
                    return [
                        f"{description} must use exact path spelling {expected!r}; "
                        f"found {sorted(aliases)!r}"
                    ]
                return []
            if len(aliases) > 1:
                return [
                    f"{description} has ambiguous path spellings for {expected!r}: "
                    f"{sorted(aliases)!r}"
                ]
            if index == len(relative_path.parts) - 1:
                return []
            next_descriptor = os.open(
                expected,
                directory_flags,
                dir_fd=descriptor,
            )
            previous_descriptor = descriptor
            descriptor = next_descriptor
            _cleanup_descriptors(
                ((f"{description} traversed relative directory", previous_descriptor),)
            )
    except OSError as exc:
        unsafe_symlinks = [
            component
            for component in symlink_components(lexical_root)
            if not is_allowed_system_symlink(component)
        ]
        if unsafe_symlinks:
            return [
                f"{description} root must not use symlink path components: "
                + ", ".join(str(component) for component in unsafe_symlinks)
            ]
        return [f"{description} exact spelling validation failed: {exc}"]
    finally:
        if descriptor is not None:
            _cleanup_descriptors(
                ((f"{description} spelling-validation directory", descriptor),),
                primary=sys.exception(),
            )
    return []


def stable_file_metadata(metadata: os.stat_result) -> tuple[int, ...]:
    """Return the shared identity, ownership, size, and timestamp signature."""

    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_nlink,
        metadata.st_uid,
        metadata.st_gid,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def read_regular_file_bytes(
    path: Path,
    *,
    description: str,
    max_bytes: int = DEFAULT_JSON_INPUT_MAX_BYTES,
    require_single_link: bool = True,
) -> bytes:
    """Read one stable bounded file through a no-follow descriptor walk.

    Every parent and the final file are opened relative to an already-bound
    directory descriptor. Parent-component symlinks are therefore rejected
    without relying on a path check followed by a separate open. Explicit
    platform aliases are translated to their fixed physical targets first.
    The file descriptor's identity and metadata must remain stable across the
    bounded read.
    """

    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    if not _descriptor_walk_supported():
        raise ValueError(
            "descriptor-safe input validation requires os.open dir_fd support"
        )

    lexical_absolute = Path(
        os.path.abspath(os.fspath(path.expanduser()))
    )
    absolute = _physical_system_alias_path(lexical_absolute)
    if absolute.anchor != "/" or len(absolute.parts) < 2:
        raise ValueError(f"{description} must name an absolute regular file")
    components = absolute.parts[1:]
    if any(component in {"", ".", ".."} for component in components):
        raise ValueError(f"{description} contains an unsafe path component: {absolute}")

    nofollow = _required_open_flag("O_NOFOLLOW")
    directory_flags = (
        os.O_RDONLY
        | _required_open_flag("O_DIRECTORY")
        | nofollow
        | getattr(os, "O_CLOEXEC", 0)
    )
    file_flags = (
        os.O_RDONLY
        | nofollow
        | _required_open_flag("O_NONBLOCK")
        | getattr(os, "O_CLOEXEC", 0)
    )
    directory_descriptor: int | None = None
    file_descriptor: int | None = None
    try:
        directory_descriptor = os.open("/", directory_flags)
        for component in components[:-1]:
            next_descriptor = os.open(
                component,
                directory_flags,
                dir_fd=directory_descriptor,
            )
            previous_descriptor = directory_descriptor
            directory_descriptor = next_descriptor
            _cleanup_descriptors(
                ((f"{description} traversed directory", previous_descriptor),)
            )
        file_descriptor = os.open(
            components[-1],
            file_flags,
            dir_fd=directory_descriptor,
        )
        before = os.fstat(file_descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError(
                f"{description} must be a regular file: {lexical_absolute}"
            )
        if require_single_link and before.st_nlink != 1:
            raise ValueError(
                f"{description} must have exactly one hard link: {lexical_absolute}"
            )
        if before.st_size > max_bytes:
            raise ValueError(
                f"{description} exceeds the {max_bytes}-byte input limit: "
                f"{lexical_absolute}"
            )

        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining:
            chunk = os.read(file_descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(file_descriptor)
        if len(raw) > max_bytes:
            raise ValueError(
                f"{description} exceeds the {max_bytes}-byte input limit: "
                f"{lexical_absolute}"
            )
        if (
            stable_file_metadata(before) != stable_file_metadata(after)
            or len(raw) != after.st_size
        ):
            raise ValueError(
                f"{description} changed while it was being read: {lexical_absolute}"
            )
        return raw
    except OSError as exc:
        unsafe_symlinks = [
            component
            for component in symlink_components(lexical_absolute)
            if not is_allowed_system_symlink(component)
        ]
        if unsafe_symlinks:
            raise ValueError(
                f"{description} must not use symlink path components: "
                + ", ".join(str(component) for component in unsafe_symlinks)
            ) from exc
        raise
    finally:
        _cleanup_descriptors(
            tuple(
                (label, descriptor)
                for label, descriptor in (
                    (f"{description} file", file_descriptor),
                    (f"{description} parent directory", directory_descriptor),
                )
                if descriptor is not None
            ),
            primary=sys.exception(),
        )


def validate_directory_no_follow(path: Path, *, description: str) -> None:
    """Validate one stable directory through a no-follow descriptor walk.

    Every component is opened relative to an already-bound parent directory.
    The lexical parent/name bindings are rechecked against the opened directory
    identities before returning so a concurrent rename or substitution fails
    closed rather than validating a different path.
    """

    if not _descriptor_walk_supported():
        raise ValueError(
            "descriptor-safe directory validation requires os.open dir_fd support"
        )
    if (
        os.stat not in getattr(os, "supports_dir_fd", set())
        or os.stat not in getattr(os, "supports_follow_symlinks", set())
    ):
        raise ValueError(
            "descriptor-safe directory validation requires os.stat dir_fd and "
            "no-follow support"
        )

    lexical_absolute = Path(os.path.abspath(os.fspath(path.expanduser())))
    absolute = _physical_system_alias_path(lexical_absolute)
    if absolute.anchor != "/":
        raise ValueError(f"{description} must name an absolute directory")
    components = absolute.parts[1:]
    if any(component in {"", ".", ".."} for component in components):
        raise ValueError(
            f"{description} contains an unsafe path component: {absolute}"
        )

    directory_flags = (
        os.O_RDONLY
        | _required_open_flag("O_DIRECTORY")
        | _required_open_flag("O_NOFOLLOW")
        | getattr(os, "O_CLOEXEC", 0)
    )
    descriptors: list[int] = []
    bindings: list[tuple[int, str, tuple[int, int, int]]] = []
    try:
        descriptors.append(os.open("/", directory_flags))
        for component in components:
            parent_descriptor = descriptors[-1]
            descriptor = os.open(
                component,
                directory_flags,
                dir_fd=parent_descriptor,
            )
            descriptors.append(descriptor)
            metadata = os.fstat(descriptor)
            if not stat.S_ISDIR(metadata.st_mode):
                raise ValueError(
                    f"{description} must be an existing directory: "
                    f"{lexical_absolute}"
                )
            identity = (
                metadata.st_dev,
                metadata.st_ino,
                stat.S_IFMT(metadata.st_mode),
            )
            bindings.append((parent_descriptor, component, identity))

        for parent_descriptor, component, expected_identity in bindings:
            try:
                linked = os.stat(
                    component,
                    dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
            except OSError as exc:
                raise ValueError(
                    f"{description} changed while it was being validated: "
                    f"{lexical_absolute}"
                ) from exc
            linked_identity = (
                linked.st_dev,
                linked.st_ino,
                stat.S_IFMT(linked.st_mode),
            )
            if (
                not stat.S_ISDIR(linked.st_mode)
                or linked_identity != expected_identity
            ):
                raise ValueError(
                    f"{description} changed while it was being validated: "
                    f"{lexical_absolute}"
                )
    except OSError as exc:
        unsafe_symlinks = [
            component
            for component in symlink_components(lexical_absolute)
            if not is_allowed_system_symlink(component)
        ]
        if unsafe_symlinks:
            raise ValueError(
                f"{description} must not use symlink path components: "
                + ", ".join(str(component) for component in unsafe_symlinks)
            ) from exc
        raise ValueError(
            f"{description} must be an existing directory: {lexical_absolute}"
        ) from exc
    finally:
        _cleanup_descriptors(
            tuple(
                (f"{description} directory", descriptor)
                for descriptor in reversed(descriptors)
            ),
            primary=sys.exception(),
        )


def output_path_errors(path: Path, root: Path | None = None, root_label: str = "output root") -> list[str]:
    errors: list[str] = []
    for component in symlink_components(path, root):
        if is_allowed_system_symlink(component):
            continue
        errors.append(f"refusing to write through symlink output path component: {component}")
    if root is not None and not path_within_root(path, root):
        errors.append(f"refusing to write outside {root_label}: {path}")
    return errors


def require_output_path(path: Path, root: Path | None = None, root_label: str = "output root") -> None:
    errors = output_path_errors(path, root, root_label)
    if errors:
        raise ValueError("; ".join(errors))


def _output_directory_flags() -> int:
    return (
        os.O_RDONLY
        | _required_open_flag("O_DIRECTORY")
        | _required_open_flag("O_NOFOLLOW")
        | getattr(os, "O_CLOEXEC", 0)
    )


def _open_output_directory_chain(
    components: tuple[str, ...],
    *,
    create_missing: bool,
) -> int:
    """Bind one directory chain without following links."""

    directory_flags = _output_directory_flags()
    descriptor = os.open("/", directory_flags)
    try:
        for component in components:
            try:
                next_descriptor = os.open(
                    component,
                    directory_flags,
                    dir_fd=descriptor,
                )
            except FileNotFoundError:
                if not create_missing:
                    raise
                created = False
                try:
                    os.mkdir(component, mode=0o777, dir_fd=descriptor)
                    created = True
                except FileExistsError:
                    # A concurrent creator is acceptable only if the subsequent
                    # no-follow directory open binds an actual directory.
                    pass
                if created:
                    os.fsync(descriptor)
                next_descriptor = os.open(
                    component,
                    directory_flags,
                    dir_fd=descriptor,
                )
            previous_descriptor = descriptor
            descriptor = next_descriptor
            _cleanup_descriptors(
                (("output-directory traversed component", previous_descriptor),)
            )
        return descriptor
    except BaseException as primary:
        _cleanup_descriptors(
            (("output-directory current component", descriptor),),
            primary=primary,
        )
        raise


@dataclass
class OutputDirectoryBinding:
    """Owned descriptor chain binding every component of one output directory."""

    requested_path: Path
    bound_path: Path
    created_paths: tuple[Path, ...]
    components: tuple[str, ...]
    descriptors: tuple[int, ...]
    initial_leaf_metadata: tuple[int, ...]
    _closed: bool = False

    @property
    def descriptor(self) -> int:
        if self._closed:
            raise ValueError("output-directory binding is closed")
        return self.descriptors[-1]

    def fileno(self) -> int:
        return self.descriptor

    @property
    def identity(self) -> tuple[int, ...]:
        return _directory_object_identity(os.fstat(self.descriptor))

    def require_lexical_binding(
        self,
        *,
        description: str = "output directory",
    ) -> None:
        """Require every retained parent/name edge to still name the same object."""

        if self._closed:
            raise ValueError("output-directory binding is closed")
        for parent, component, child in zip(
            self.descriptors[:-1],
            self.components,
            self.descriptors[1:],
            strict=True,
        ):
            try:
                named = os.stat(
                    component,
                    dir_fd=parent,
                    follow_symlinks=False,
                )
            except FileNotFoundError as exc:
                raise ValueError(
                    f"{description} pathname component disappeared: "
                    f"{component}"
                ) from exc
            bound = os.fstat(child)
            if (
                not stat.S_ISDIR(named.st_mode)
                or not stat.S_ISDIR(bound.st_mode)
                or _directory_object_identity(named)
                != _directory_object_identity(bound)
            ):
                raise ValueError(
                    f"{description} pathname component no longer identifies "
                    f"its bound directory: {component}"
                )

    def require_current(self) -> None:
        self.require_lexical_binding()

    def require_unchanged_chain(
        self,
        *,
        description: str = "directory",
    ) -> None:
        """Require every edge plus the read-only leaf's stable metadata.

        Ancestor metadata is intentionally excluded: unrelated sibling changes
        must not invalidate an otherwise unchanged bound tree. Writers should
        use :meth:`require_lexical_binding` because their own leaf mutations
        legitimately change directory timestamps.
        """

        self.require_lexical_binding(description=description)
        current_leaf = stable_file_metadata(os.fstat(self.descriptor))
        if current_leaf != self.initial_leaf_metadata:
            raise ValueError(
                f"{description} root changed after it was bound"
            )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        _cleanup_descriptors(
            tuple(
                ("output-directory binding descriptor", descriptor)
                for descriptor in reversed(self.descriptors)
            )
        )

    def __enter__(self) -> "OutputDirectoryBinding":
        return self

    def __exit__(
        self,
        _exception_type: object,
        exception: BaseException | None,
        _traceback: object,
    ) -> None:
        try:
            self.close()
        except BaseException as cleanup:
            if exception is None:
                raise
            exception.add_note(f"output-directory binding cleanup failure: {cleanup}")


class OutputDirectoryBindingError(RuntimeError):
    """A component-wise output bind failed after possible directory creation."""

    def __init__(
        self,
        requested_path: Path,
        failed_component: str,
        created_or_uncertain_paths: tuple[Path, ...],
        cause: BaseException,
    ) -> None:
        self.requested_path = requested_path
        self.failed_component = failed_component
        self.created_or_uncertain_paths = created_or_uncertain_paths
        locations = ", ".join(str(path) for path in created_or_uncertain_paths)
        suffix = f"; created or uncertain paths: {locations}" if locations else ""
        super().__init__(
            "output-directory binding failed at component "
            f"{failed_component!r} for {requested_path}{suffix}: {cause}"
        )


def _open_output_directory_binding_chain(
    components: tuple[str, ...],
    *,
    requested_path: Path,
    bound_path: Path,
    create_missing: bool,
) -> OutputDirectoryBinding:
    directory_flags = _output_directory_flags()
    descriptors: list[int] = []
    created_paths: list[Path] = []
    created_or_uncertain_paths: list[Path] = []
    failed_component = "/"
    try:
        descriptors.append(os.open("/", directory_flags))
        current_path = Path("/")
        for component in components:
            failed_component = component
            current_path /= component
            parent = descriptors[-1]
            try:
                child = os.open(component, directory_flags, dir_fd=parent)
            except FileNotFoundError:
                if not create_missing:
                    raise
                created_or_uncertain_paths.append(current_path)
                try:
                    os.mkdir(component, mode=0o777, dir_fd=parent)
                except FileExistsError:
                    created_or_uncertain_paths.pop()
                else:
                    created_paths.append(current_path)
                    os.fsync(parent)
                child = os.open(component, directory_flags, dir_fd=parent)
            descriptors.append(child)
        binding = OutputDirectoryBinding(
            requested_path=requested_path,
            bound_path=bound_path,
            created_paths=tuple(created_paths),
            components=components,
            descriptors=tuple(descriptors),
            initial_leaf_metadata=stable_file_metadata(
                os.fstat(descriptors[-1])
            ),
        )
        binding.require_current()
        return binding
    except Exception as exc:
        _cleanup_descriptors(
            tuple(
                ("output-directory binding descriptor", descriptor)
                for descriptor in reversed(descriptors)
            ),
            primary=exc,
        )
        if isinstance(exc, OutputDirectoryBindingError):
            raise
        raise OutputDirectoryBindingError(
            requested_path,
            failed_component,
            tuple(dict.fromkeys(created_or_uncertain_paths)),
            exc,
        ) from exc
    except BaseException as exc:
        _cleanup_descriptors(
            tuple(
                ("output-directory binding descriptor", descriptor)
                for descriptor in reversed(descriptors)
            ),
            primary=exc,
        )
        uncertain = tuple(dict.fromkeys(created_or_uncertain_paths))
        if uncertain:
            exc.add_note(
                "output-directory binding interruption state; created or "
                "uncertain paths: " + ", ".join(str(path) for path in uncertain)
            )
        raise


def _output_directory_components(path: Path, root: Path | None) -> tuple[str, ...]:
    require_output_path(path, root)
    if not _descriptor_walk_supported():
        raise ValueError(
            "descriptor-safe output installation requires os.open dir_fd support"
        )
    lexical_absolute = Path(os.path.abspath(os.fspath(path.expanduser())))
    absolute = _physical_system_alias_path(lexical_absolute)
    if absolute.anchor != "/":
        raise ValueError("output directory must be absolute")
    components = absolute.parts[1:]
    if any(component in {"", ".", ".."} for component in components):
        raise ValueError(f"output directory contains an unsafe path component: {absolute}")
    return components


def _directory_object_identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        stat.S_IFMT(metadata.st_mode),
        metadata.st_uid,
    )


def open_output_directory(
    path: Path,
    *,
    root: Path | None = None,
    create_missing: bool = True,
) -> OutputDirectoryBinding:
    """Create and bind every retained component of ``path`` without links.

    The caller owns the returned binding and must close it. Retaining the full
    descriptor chain permits a later check that no ancestor/name edge was
    substituted after it was first opened.
    """

    components = _output_directory_components(path, root)
    requested_path = Path(os.path.abspath(os.fspath(path.expanduser())))
    bound_path = _physical_system_alias_path(requested_path)
    return _open_output_directory_binding_chain(
        components,
        requested_path=requested_path,
        bound_path=bound_path,
        create_missing=create_missing,
    )


def require_output_directory_binding(
    path: Path,
    binding: OutputDirectoryBinding,
    *,
    root: Path | None = None,
) -> None:
    """Require ``path`` and every retained edge to match ``binding`` now."""

    components = _output_directory_components(path, root)
    if components != binding.components:
        raise ValueError("output-directory binding was created for a different path")
    binding.require_current()


def ensure_directory(path: Path, *, root: Path | None = None) -> None:
    """Create and bind a directory path without following a raced parent symlink."""

    with open_output_directory(path, root=root) as binding:
        os.fsync(binding.descriptor)


def write_bytes(
    path: Path,
    content: bytes,
    *,
    force: bool = False,
    root: Path | None = None,
) -> None:
    """Install complete bytes atomically without following output symlinks."""

    if not isinstance(content, bytes):
        raise TypeError("atomic output content must be bytes")
    require_output_path(path, root)
    if not _descriptor_walk_supported():
        raise ValueError(
            "descriptor-safe output installation requires os.open dir_fd support"
        )

    lexical_absolute = Path(os.path.abspath(os.fspath(path.expanduser())))
    absolute = _physical_system_alias_path(lexical_absolute)
    if absolute.anchor != "/" or len(absolute.parts) < 2:
        raise ValueError("output must name an absolute file below /")
    components = absolute.parts[1:]
    if any(component in {"", ".", ".."} for component in components):
        raise ValueError(f"output contains an unsafe path component: {absolute}")

    nofollow = _required_open_flag("O_NOFOLLOW")
    staging_flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | nofollow
        | getattr(os, "O_CLOEXEC", 0)
    )
    parent_descriptor: int | None = None
    staging_descriptor: int | None = None
    staging_name = ""
    target_name = components[-1]
    try:
        parent_descriptor = _open_output_directory_chain(
            components[:-1],
            create_missing=True,
        )

        try:
            existing = os.stat(
                target_name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            existing = None
        if existing is not None:
            if not force:
                raise FileExistsError(
                    "refusing to overwrite existing output without --force: "
                    f"{path}"
                )
            if not stat.S_ISREG(existing.st_mode):
                raise ValueError(f"existing output must be a regular file: {path}")

        for _attempt in range(32):
            staging_name = f".{target_name}.tmp-{secrets.token_hex(16)}"
            try:
                staging_descriptor = os.open(
                    staging_name,
                    staging_flags,
                    0o666,
                    dir_fd=parent_descriptor,
                )
                break
            except FileExistsError:
                continue
        if staging_descriptor is None:
            raise OSError("could not allocate a unique output staging file")
        if existing is not None:
            os.fchmod(staging_descriptor, stat.S_IMODE(existing.st_mode))

        offset = 0
        while offset < len(content):
            written = os.write(staging_descriptor, content[offset:])
            if written <= 0:
                raise OSError("atomic output write made no progress")
            offset += written
        os.fsync(staging_descriptor)
        staged = os.fstat(staging_descriptor)
        if (
            not stat.S_ISREG(staged.st_mode)
            or staged.st_nlink != 1
            or staged.st_size != len(content)
        ):
            raise OSError("atomic output staging file has invalid metadata")

        if force:
            os.replace(
                staging_name,
                target_name,
                src_dir_fd=parent_descriptor,
                dst_dir_fd=parent_descriptor,
            )
            staging_name = ""
        else:
            try:
                os.link(
                    staging_name,
                    target_name,
                    src_dir_fd=parent_descriptor,
                    dst_dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
            except FileExistsError as exc:
                raise FileExistsError(
                    "refusing to overwrite output that appeared during atomic "
                    f"installation: {path}"
                ) from exc
            os.unlink(staging_name, dir_fd=parent_descriptor)
            staging_name = ""
        os.fsync(parent_descriptor)
        installed = os.stat(
            target_name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISREG(installed.st_mode)
            or installed.st_nlink != 1
            or installed.st_size != len(content)
        ):
            raise OSError("atomically installed output has invalid metadata")
    finally:
        active_failure = sys.exception()
        cleanup_primary = active_failure
        if staging_name and parent_descriptor is not None:
            try:
                os.unlink(staging_name, dir_fd=parent_descriptor)
                os.fsync(parent_descriptor)
            except FileNotFoundError:
                pass
            except BaseException as cleanup:
                if cleanup_primary is None:
                    cleanup_primary = cleanup
                else:
                    cleanup_primary.add_note(
                        f"atomic output staging cleanup failure: {cleanup}"
                    )
        _cleanup_descriptors(
            tuple(
                (label, descriptor)
                for label, descriptor in (
                    ("atomic output staging file", staging_descriptor),
                    ("atomic output parent directory", parent_descriptor),
                )
                if descriptor is not None
            ),
            primary=cleanup_primary,
        )
        if active_failure is None and cleanup_primary is not None:
            raise cleanup_primary


def write_text(
    path: Path,
    content: str,
    *,
    encoding: str = "utf-8",
    force: bool = False,
    root: Path | None = None,
) -> None:
    write_bytes(
        path,
        content.encode(encoding),
        force=force,
        root=root,
    )
