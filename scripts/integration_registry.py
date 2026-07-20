#!/usr/bin/env python3

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
import posixpath
import re
import stat

import bootstrap_transaction
import markdown_structure
import project_contract_model as contract_model
import safe_paths


REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = REPO_ROOT / "integrations" / "registry.json"
INTEGRATION_REGISTRY_MAX_BYTES = safe_paths.DEFAULT_JSON_INPUT_MAX_BYTES
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
WRAPPER_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
WRAPPER_OUTPUT_PATTERNS = {
    "codex": re.compile(r"^\.agents/skills/[a-z0-9][a-z0-9-]*/SKILL\.md$"),
    "claude-code": re.compile(r"^\.claude/agents/[a-z0-9][a-z0-9-]*\.md$"),
}
NATIVE_WRAPPER_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
ROOT_KEYS = {"families"}
FAMILY_KEYS = {"template_root", "entrypoint", "wrappers"}
ENTRYPOINT_KEYS = {"path", "output", "authority_load_syntax"}
WRAPPER_KEYS = {"path", "repo_output", "lifecycle", "authority_precondition"}
RECOVERY_GUARD_MARKER = contract_model.ENTRYPOINT_RECOVERY_GUARD_MARKER
FRAMEWORK_CORE_MARKER = "<!-- mpa-entrypoint-contract: entrypoint-framework-core-v1 -->"
PROJECT_CONTRACT_MARKER = (
    "<!-- mpa-entrypoint-contract: entrypoint-project-contract-authority-v1 -->"
)
STATE_LOADING_MARKER = "<!-- mpa-entrypoint-contract: entrypoint-state-gated-loading-v1 -->"
ROUTING_AFTER_STATE_MARKER = (
    "<!-- mpa-entrypoint-contract: entrypoint-routing-after-state-v1 -->"
)
WRAPPER_AUTHORITY_PRECONDITION_ID = "entrypoint-recovery-project-contract-v1"
WRAPPER_AUTHORITY_PRECONDITION_MARKER = (
    "<!-- mpa-wrapper-contract: entrypoint-recovery-project-contract-v1 -->"
)
WRAPPER_AUTHORITY_PRECONDITION_CLAUSE = (
    "Run this wrapper only after the generated runtime entrypoint has confirmed "
    "that its recovery gate is clear and loaded the project contract in the "
    "current agent context. Otherwise, stop this wrapper and return to that "
    "entrypoint or its recovery route."
)
WRAPPER_AUTHORITY_CONSUMER_LIFECYCLE = "entrypoint-authority-consumer-v1"
WRAPPER_PROJECT_INIT_LIFECYCLE = "project-initialization-launcher-v1"
WRAPPER_PROJECT_REFRESH_LIFECYCLE = "project-refresh-launcher-v1"
FRAMEWORK_UNAVAILABLE_CLAUSE = (
    contract_model.ENTRYPOINT_FRAMEWORK_UNAVAILABLE_CLAUSE
)
RECOVERY_GUARD_CLAUSE = contract_model.ENTRYPOINT_RECOVERY_GUARD_CLAUSE
PROJECT_FILE_NAMES = contract_model.DOWNSTREAM_CONTRACT_REFERENCE_FILES
PROJECT_FILE_REFERENCE_RE = re.compile(
    r"(?<![A-Za-z0-9_./-])(?P<local_prefix>\./)?(?P<name>"
    + "|".join(re.escape(name) for name in sorted(PROJECT_FILE_NAMES, key=len, reverse=True))
    + r")(?![A-Za-z0-9_.-])"
)
RESERVED_PROJECT_OUTPUTS = frozenset(
    {"PROJECT_INPUT.json", "PROJECT_INSTANCE.json", *PROJECT_FILE_NAMES}
)


@dataclass(frozen=True, slots=True)
class AuthorityLoadSyntaxSpec:
    """Exact marker-owned grammar for one generated runtime entrypoint."""

    syntax_id: str
    framework_block_open: str | None
    framework_block_close: str | None
    project_block_open: str | None
    project_block_close: str | None
    framework_load_suffix: str


@dataclass(frozen=True, slots=True)
class WrapperLifecycleSpec:
    """Closed execution contract for one registered runtime wrapper."""

    authority_precondition: str | None
    required_route_references: tuple[str, ...]
    reads_generated_project_authority: bool


WRAPPER_LIFECYCLE_SPECS = {
    WRAPPER_AUTHORITY_CONSUMER_LIFECYCLE: WrapperLifecycleSpec(
        authority_precondition=WRAPPER_AUTHORITY_PRECONDITION_ID,
        required_route_references=(),
        reads_generated_project_authority=True,
    ),
    WRAPPER_PROJECT_INIT_LIFECYCLE: WrapperLifecycleSpec(
        authority_precondition=None,
        required_route_references=("GETTING_STARTED.md", "task_orders/init.md"),
        reads_generated_project_authority=False,
    ),
    WRAPPER_PROJECT_REFRESH_LIFECYCLE: WrapperLifecycleSpec(
        authority_precondition=None,
        required_route_references=(
            "UPDATING.md",
            "task_orders/framework_refresh.md",
        ),
        reads_generated_project_authority=False,
    ),
}
WRAPPER_LIFECYCLES = frozenset(WRAPPER_LIFECYCLE_SPECS)


AUTHORITY_LOAD_SYNTAX_SPECS = {
    "generic-markdown-read-v1": AuthorityLoadSyntaxSpec(
        syntax_id="generic-markdown-read-v1",
        framework_block_open="<framework-rules>",
        framework_block_close="</framework-rules>",
        project_block_open="<project-contract>",
        project_block_close="</project-contract>",
        framework_load_suffix=(
            "` before acting. It is the always-on operative charter."
        ),
    ),
    "codex-markdown-read-v1": AuthorityLoadSyntaxSpec(
        syntax_id="codex-markdown-read-v1",
        framework_block_open="<framework-core>",
        framework_block_close="</framework-core>",
        project_block_open="<project-contract>",
        project_block_close="</project-contract>",
        framework_load_suffix=(
            "` before acting. This is the always-on operative charter."
        ),
    ),
    "claude-markdown-read-v1": AuthorityLoadSyntaxSpec(
        syntax_id="claude-markdown-read-v1",
        framework_block_open=None,
        framework_block_close=None,
        project_block_open=None,
        project_block_close=None,
        framework_load_suffix=(
            "` before acting. It is the always-on operative charter."
        ),
    ),
}
AUTHORITY_LOAD_SYNTAXES = frozenset(AUTHORITY_LOAD_SYNTAX_SPECS)


def render_project_file_references(text: str, contract_root_ref: str) -> str:
    """Prefix project-file references in one pass against the source text."""

    if contract_root_ref == ".":
        return text
    prefix = f"{contract_root_ref}/"
    return PROJECT_FILE_REFERENCE_RE.sub(
        lambda match: (
            f"{match.group('local_prefix') or ''}{prefix}{match.group('name')}"
        ),
        text,
    )


def render_template_text(
    text: str,
    framework_ref: str,
    contract_root_ref: str,
    *,
    template_label: str,
) -> str:
    """Render the shared tokens supported by integration templates."""

    rendered = safe_paths.render_framework_reference_tokens(text, framework_ref)
    rendered = render_project_file_references(rendered, contract_root_ref)
    if "{{" in rendered or "}}" in rendered:
        raise ValueError(f"unresolved template placeholder in {template_label}")
    return rendered


def _rebase_project_root_reference_for_output(reference: str, output: str) -> str:
    """Express one project-root reference from a nested output's directory."""

    canonical = safe_paths.canonical_framework_reference(reference)
    posix_reference = PurePosixPath(canonical)
    windows_reference = PureWindowsPath(canonical)
    if (
        posix_reference.is_absolute()
        or windows_reference.is_absolute()
        or windows_reference.drive
        or canonical.startswith(("$", "~"))
    ):
        return canonical
    parent_depth = len(PurePosixPath(output).parent.parts)
    prefix = "/".join(".." for _ in range(parent_depth)) or "."
    return posixpath.normpath(f"{prefix}/{canonical}")


def render_wrapper_template_text(
    family: str,
    output: str,
    text: str,
    framework_ref: str,
    contract_root_ref: str,
    *,
    template_label: str,
) -> str:
    """Render a wrapper from the path base declared by its native runtime."""

    if family == "codex":
        framework_ref = _rebase_project_root_reference_for_output(
            framework_ref,
            output,
        )
        contract_root_ref = _rebase_project_root_reference_for_output(
            contract_root_ref,
            output,
        )
    return render_template_text(
        text,
        framework_ref,
        contract_root_ref,
        template_label=template_label,
    )


def validate_relative_path(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty relative path")
    path = Path(value)
    windows_path = PureWindowsPath(value)
    if (
        "\\" in value
        or "://" in value
        or path.is_absolute()
        or windows_path.is_absolute()
        or windows_path.drive
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or ".." in windows_path.parts
    ):
        raise ValueError(f"{label} must stay inside the repository: {value}")
    return value


def resolve_repo_path(repo_root: Path, rel: object, label: str) -> Path:
    root = repo_root.expanduser().absolute()
    relative = validate_relative_path(rel, label)
    unsafe_root_symlinks = [
        component
        for component in safe_paths.symlink_components(root)
        if not safe_paths.is_allowed_system_symlink(component)
    ]
    if unsafe_root_symlinks:
        raise ValueError(
            f"{label} repository root must not use symlink path components: "
            + ", ".join(str(component) for component in unsafe_root_symlinks)
        )

    candidate = root / Path(relative)
    current = root
    for component in Path(relative).parts:
        current = current / component
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            break
        except OSError as exc:
            raise ValueError(
                f"{label} could not be inspected without following links: {current}"
            ) from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise ValueError(
                f"{label} must not use symlink path components: {relative}"
            )
    return candidate


def _require_existing_kind(path: Path, label: str, *, directory: bool) -> None:
    if directory:
        safe_paths.validate_directory_no_follow(path, description=label)
        return
    try:
        safe_paths.read_regular_file_bytes(
            path,
            description=label,
            max_bytes=safe_paths.DEFAULT_JSON_INPUT_MAX_BYTES,
        )
    except ValueError:
        raise
    except OSError as exc:
        raise ValueError(f"{label} must be an existing file: {path}") from exc


def _wrapper_frontmatter_name(text: str, label: str) -> str:
    """Return one plain native wrapper name from a bounded frontmatter block."""

    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise ValueError(f"{label} must begin with a Markdown frontmatter block")
    try:
        closing_index = lines.index("---", 1)
    except ValueError as exc:
        raise ValueError(f"{label} frontmatter block is not closed") from exc
    names = [
        line.removeprefix("name:").strip()
        for line in lines[1:closing_index]
        if line.startswith("name:")
    ]
    if len(names) != 1 or not NATIVE_WRAPPER_NAME_RE.fullmatch(names[0]):
        raise ValueError(
            f"{label} frontmatter must contain exactly one plain slug name"
        )
    return names[0]


def _validate_wrapper_native_identity(
    family: str,
    output: str,
    text: str,
    label: str,
) -> None:
    """Bind wrapper-native identity to its one registry-owned destination."""

    name = _wrapper_frontmatter_name(text, label)
    output_path = Path(output)
    expected = (
        output_path.parent.name
        if family == "codex"
        else output_path.stem
        if family == "claude-code"
        else None
    )
    if expected is None:
        raise ValueError(f"{label} has no native destination owner for {family}")
    if name != expected:
        raise ValueError(
            f"{label} frontmatter name {name!r} must match its registry-owned "
            f"destination identity {expected!r}"
        )


def wrapper_authority_precondition_errors(text: str, *, output: str) -> list[str]:
    """Validate one registry-declared wrapper's entrypoint precondition.

    The exact marker and clause provide a machine-owned boundary. Markdown
    visibility prevents fenced or commented examples from satisfying it, while
    filename-aware ordering rejects project authority loaded before the gate.
    """

    lines = text.splitlines()
    active_indexes = _active_line_indexes(lines)
    marker_indexes = [
        index
        for index, line in enumerate(lines)
        if index in active_indexes and line == WRAPPER_AUTHORITY_PRECONDITION_MARKER
    ]
    if len(marker_indexes) != 1:
        return [
            f"{output} wrapper authority-precondition marker occurs "
            f"{len(marker_indexes)} times; expected exactly one active marker"
        ]

    marker_index = marker_indexes[0]
    clause_indexes = [
        index
        for index, line in enumerate(lines)
        if index in active_indexes and line == WRAPPER_AUTHORITY_PRECONDITION_CLAUSE
    ]
    errors: list[str] = []
    if clause_indexes != [marker_index + 1]:
        errors.append(
            f"{output} wrapper authority precondition must contain the exact "
            "active clause once, immediately after its structural marker"
        )

    authority_lines = [
        index + 1
        for index, line in enumerate(lines)
        if index in active_indexes
        and any(filename in line for filename in PROJECT_FILE_NAMES)
        and index <= marker_index + 1
    ]
    if authority_lines:
        errors.append(
            f"{output} active generated project authority/state reference occurs "
            "before the wrapper authority precondition at line(s): "
            + ", ".join(str(line_number) for line_number in authority_lines)
        )
    return errors


def wrapper_lifecycle_errors(
    text: str,
    *,
    output: str,
    lifecycle: object,
    authority_precondition: object,
) -> list[str]:
    """Validate one wrapper against its closed registry-declared lifecycle."""

    if not isinstance(lifecycle, str) or lifecycle not in WRAPPER_LIFECYCLE_SPECS:
        return [
            f"{output} wrapper lifecycle must be one of "
            f"{sorted(WRAPPER_LIFECYCLES)}"
        ]
    spec = WRAPPER_LIFECYCLE_SPECS[lifecycle]
    errors: list[str] = []
    if authority_precondition != spec.authority_precondition:
        errors.append(
            f"{output} wrapper lifecycle {lifecycle!r} requires "
            f"authority_precondition={spec.authority_precondition!r}"
        )

    lines = text.splitlines()
    active_indexes = _active_line_indexes(lines)
    active_lines = [lines[index] for index in sorted(active_indexes)]
    for route_lifecycle, route_spec in WRAPPER_LIFECYCLE_SPECS.items():
        if not route_spec.required_route_references:
            continue
        present_routes = [
            reference
            for reference in route_spec.required_route_references
            if any(reference in line for line in active_lines)
        ]
        if present_routes and lifecycle != route_lifecycle:
            errors.append(
                f"{output} wrapper routes through {', '.join(present_routes)} "
                f"but declares lifecycle {lifecycle!r} instead of "
                f"{route_lifecycle!r}"
            )
    project_authority_lines = [
        index + 1
        for index in sorted(active_indexes)
        if any(filename in lines[index] for filename in PROJECT_FILE_NAMES)
    ]
    if spec.reads_generated_project_authority:
        if not project_authority_lines:
            errors.append(
                f"{output} wrapper lifecycle {lifecycle!r} declares generated "
                "project-authority use but has no active project-authority reference"
            )
    elif project_authority_lines:
        errors.append(
            f"{output} wrapper reads generated project authority at active line(s) "
            + ", ".join(str(line_number) for line_number in project_authority_lines)
            + f" but lifecycle {lifecycle!r} does not permit it"
        )

    for reference in spec.required_route_references:
        if not any(reference in line for line in active_lines):
            errors.append(
                f"{output} wrapper lifecycle {lifecycle!r} requires one active "
                f"route reference to {reference}"
            )

    if spec.authority_precondition == WRAPPER_AUTHORITY_PRECONDITION_ID:
        errors.extend(wrapper_authority_precondition_errors(text, output=output))
    return errors


def _validate_closed_template_surface(
    template_root: Path,
    expected_files: dict[Path, str],
    family: str,
) -> None:
    """Reject unregistered files and directories in one integration family tree."""

    expected_relative = {
        path.relative_to(template_root): label for path, label in expected_files.items()
    }
    expected_directories = {
        parent
        for relative in expected_relative
        for parent in relative.parents
        if parent != Path(".")
    }
    actual_files: set[Path] = set()
    actual_directories: set[Path] = set()
    try:
        candidates = sorted(template_root.rglob("*"))
    except OSError as exc:
        raise ValueError(
            f"{family}.template_root could not be inventoried without following links"
        ) from exc
    for candidate in candidates:
        relative = candidate.relative_to(template_root)
        try:
            metadata = candidate.lstat()
        except OSError as exc:
            raise ValueError(
                f"{family}.template_root entry changed during inventory: {relative}"
            ) from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise ValueError(
                f"{family}.template_root must not contain symlink entries: {relative}"
            )
        if stat.S_ISDIR(metadata.st_mode):
            actual_directories.add(relative)
        elif stat.S_ISREG(metadata.st_mode):
            actual_files.add(relative)
        else:
            raise ValueError(
                f"{family}.template_root entry must be a directory or regular file: "
                f"{relative}"
            )

    unexpected_files = sorted(actual_files - set(expected_relative))
    unexpected_directories = sorted(actual_directories - expected_directories)
    if unexpected_files or unexpected_directories:
        details = [
            *(f"file {path.as_posix()}" for path in unexpected_files),
            *(f"directory {path.as_posix()}" for path in unexpected_directories),
        ]
        raise ValueError(
            f"{family}.template_root contains unregistered integration content: "
            + ", ".join(details)
        )
    missing_files = sorted(set(expected_relative) - actual_files)
    if missing_files:
        raise ValueError(
            f"{family}.template_root is missing registered integration files: "
            + ", ".join(path.as_posix() for path in missing_files)
        )
    _require_existing_kind(
        template_root,
        f"{family}.template_root",
        directory=True,
    )


def validate_registry(data: object, repo_root: Path) -> dict:
    if not isinstance(data, dict) or not isinstance(data.get("families"), dict):
        raise ValueError("integration registry must contain a families object")
    unknown_root_keys = sorted(set(data) - ROOT_KEYS)
    if unknown_root_keys:
        raise ValueError(f"integration registry has unknown keys: {unknown_root_keys}")
    all_entrypoint_outputs = {
        entrypoint.get("output")
        for config in data["families"].values()
        if isinstance(config, dict)
        for entrypoint in [config.get("entrypoint")]
        if isinstance(entrypoint, dict) and isinstance(entrypoint.get("output"), str)
    }
    wrapper_destination_owners: dict[str, str] = {}
    for family, config in data["families"].items():
        if not isinstance(family, str) or not SLUG_RE.fullmatch(family):
            raise ValueError(f"integration family name must be a slug: {family!r}")
        if not isinstance(config, dict):
            raise ValueError(f"integration family {family!r} must be an object")
        unknown_family_keys = sorted(set(config) - FAMILY_KEYS)
        if unknown_family_keys:
            raise ValueError(
                f"integration family {family!r} has unknown keys: {unknown_family_keys}"
            )
        template_root = resolve_repo_path(repo_root, config.get("template_root"), f"{family}.template_root")
        _require_existing_kind(
            template_root,
            f"{family}.template_root",
            directory=True,
        )
        entrypoint = config.get("entrypoint")
        if not isinstance(entrypoint, dict):
            raise ValueError(f"{family}.entrypoint must be an object")
        unknown_entrypoint_keys = sorted(set(entrypoint) - ENTRYPOINT_KEYS)
        if unknown_entrypoint_keys:
            raise ValueError(
                f"{family}.entrypoint has unknown keys: {unknown_entrypoint_keys}"
            )
        entrypoint_path = resolve_repo_path(repo_root, entrypoint.get("path"), f"{family}.entrypoint.path")
        if not entrypoint_path.is_relative_to(template_root):
            raise ValueError(f"{family}.entrypoint.path must stay inside {family}.template_root")
        _require_existing_kind(
            entrypoint_path,
            f"{family}.entrypoint.path",
            directory=False,
        )
        registered_sources = {
            entrypoint_path: f"{family}.entrypoint.path",
        }
        output = validate_relative_path(entrypoint.get("output"), f"{family}.entrypoint.output")
        if "/" in output or "\\" in output:
            raise ValueError(f"{family}.entrypoint.output must be a root-level file name")
        authority_load_syntax = entrypoint.get("authority_load_syntax")
        if authority_load_syntax not in AUTHORITY_LOAD_SYNTAXES:
            raise ValueError(
                f"{family}.entrypoint.authority_load_syntax must be one of "
                f"{sorted(AUTHORITY_LOAD_SYNTAXES)}"
            )
        entrypoint_relative = entrypoint_path.relative_to(template_root)
        rendered_entrypoint = entrypoint_relative.with_name(
            entrypoint_relative.name[: -len(".template")]
            if entrypoint_relative.name.endswith(".template")
            else entrypoint_relative.name
        )
        if rendered_entrypoint.as_posix() != output:
            raise ValueError(
                f"{family}.entrypoint.output must match its rendered template-relative path: "
                f"{rendered_entrypoint.as_posix()}"
            )
        wrappers = config.get("wrappers", {})
        if not isinstance(wrappers, dict):
            raise ValueError(f"{family}.wrappers must be an object")
        wrapper_sources: dict[Path, str] = {}
        wrapper_outputs: dict[str, str] = {}
        for wrapper, wrapper_config in wrappers.items():
            if not isinstance(wrapper, str) or not WRAPPER_NAME_RE.fullmatch(wrapper):
                raise ValueError(f"{family}.wrappers name must be a slug: {wrapper!r}")
            if not isinstance(wrapper_config, dict):
                raise ValueError(f"{family}.wrappers.{wrapper} must be an object")
            missing_wrapper_declarations = sorted(
                {"lifecycle", "authority_precondition"} - set(wrapper_config)
            )
            if missing_wrapper_declarations:
                raise ValueError(
                    f"{family}.wrappers.{wrapper} must explicitly declare: "
                    + ", ".join(missing_wrapper_declarations)
                )
            unknown_wrapper_keys = sorted(set(wrapper_config) - WRAPPER_KEYS)
            if unknown_wrapper_keys:
                raise ValueError(
                    f"{family}.wrappers.{wrapper} has unknown keys: {unknown_wrapper_keys}"
                )
            wrapper_path = resolve_repo_path(
                repo_root,
                wrapper_config.get("path"),
                f"{family}.wrappers.{wrapper}.path",
            )
            if not wrapper_path.is_relative_to(template_root):
                raise ValueError(
                    f"{family}.wrappers.{wrapper}.path must stay inside {family}.template_root"
                )
            _require_existing_kind(
                wrapper_path,
                f"{family}.wrappers.{wrapper}.path",
                directory=False,
            )
            if wrapper_path == entrypoint_path:
                raise ValueError(
                    f"{family}.wrappers.{wrapper}.path duplicates the registered "
                    "entrypoint source"
                )
            previous_wrapper = wrapper_sources.get(wrapper_path)
            if previous_wrapper is not None:
                raise ValueError(
                    f"{family}.wrappers.{wrapper}.path duplicates wrapper {previous_wrapper!r}: "
                    f"{wrapper_path}"
                )
            wrapper_sources[wrapper_path] = wrapper
            registered_sources[wrapper_path] = f"{family}.wrappers.{wrapper}.path"
            wrapper_output = validate_relative_path(
                wrapper_config.get("repo_output"),
                f"{family}.wrappers.{wrapper}.repo_output",
            )
            output_errors = safe_paths.project_relative_reference_errors(
                wrapper_output,
                f"{family}.wrappers.{wrapper}.repo_output",
            )
            if output_errors:
                raise ValueError("; ".join(output_errors))
            if wrapper_output in all_entrypoint_outputs:
                raise ValueError(
                    f"{family}.wrappers.{wrapper}.repo_output collides with a "
                    f"registered runtime entrypoint: {wrapper_output}"
                )
            if (
                wrapper_output in RESERVED_PROJECT_OUTPUTS
                or bootstrap_transaction.is_reserved_transaction_output(wrapper_output)
            ):
                raise ValueError(
                    f"{family}.wrappers.{wrapper}.repo_output uses a reserved project path: "
                    f"{wrapper_output}"
                )
            output_pattern = WRAPPER_OUTPUT_PATTERNS.get(family)
            if output_pattern is None or not output_pattern.fullmatch(wrapper_output):
                expected = (
                    ".agents/skills/<skill>/SKILL.md"
                    if family == "codex"
                    else ".claude/agents/<agent>.md"
                    if family == "claude-code"
                    else "no repo-scoped wrapper output"
                )
                raise ValueError(
                    f"{family}.wrappers.{wrapper}.repo_output must use the native "
                    f"family-owned shape {expected}: {wrapper_output}"
                )
            expected_source_name = (
                "SKILL.md.template"
                if family == "codex"
                else f"{Path(wrapper_output).name}.template"
            )
            if wrapper_path.name != expected_source_name:
                raise ValueError(
                    f"{family}.wrappers.{wrapper}.path must be the one native "
                    f"wrapper template file {expected_source_name}: {wrapper_path.name}"
                )
            previous_output = wrapper_outputs.get(wrapper_output)
            if previous_output is not None:
                raise ValueError(
                    f"{family}.wrappers.{wrapper}.repo_output duplicates wrapper "
                    f"{previous_output!r}: {wrapper_output}"
                )
            wrapper_outputs[wrapper_output] = wrapper
            owner = f"{family}.wrappers.{wrapper}"
            previous_owner = wrapper_destination_owners.get(wrapper_output)
            if previous_owner is not None:
                raise ValueError(
                    f"{owner}.repo_output duplicates the destination owned by "
                    f"{previous_owner}: {wrapper_output}"
                )
            wrapper_destination_owners[wrapper_output] = owner

            raw_wrapper = safe_paths.read_regular_file_bytes(
                wrapper_path,
                description=f"{owner}.path",
                max_bytes=INTEGRATION_REGISTRY_MAX_BYTES,
            )
            try:
                wrapper_text = raw_wrapper.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError(f"{owner}.path must be UTF-8") from exc
            rendered_wrapper = render_wrapper_template_text(
                family,
                wrapper_output,
                wrapper_text,
                "$FRAMEWORK",
                ".",
                template_label=f"{owner}.path",
            )
            _validate_wrapper_native_identity(
                family,
                wrapper_output,
                rendered_wrapper,
                owner,
            )
            lifecycle_errors = wrapper_lifecycle_errors(
                rendered_wrapper,
                output=wrapper_output,
                lifecycle=wrapper_config["lifecycle"],
                authority_precondition=wrapper_config["authority_precondition"],
            )
            if lifecycle_errors:
                raise ValueError(f"{owner}: " + "; ".join(lifecycle_errors))
        _validate_closed_template_surface(
            template_root,
            registered_sources,
            family,
        )
    return data


def load_registry(repo_root: Path | None = None) -> dict:
    root = (repo_root or REPO_ROOT).expanduser().absolute()
    registry_path = root / "integrations" / "registry.json"
    raw = safe_paths.read_regular_file_bytes(
        registry_path,
        description="integration registry",
        max_bytes=INTEGRATION_REGISTRY_MAX_BYTES,
    )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"integration registry must be UTF-8: {registry_path}"
        ) from exc
    data = safe_paths.loads_json_no_duplicates(text)
    return validate_registry(data, root)


def family_names(repo_root: Path | None = None) -> list[str]:
    return sorted(load_registry(repo_root)["families"])


def family_config(name: str, repo_root: Path | None = None) -> dict:
    return load_registry(repo_root)["families"][name]


def wrapper_names(family: str, repo_root: Path | None = None) -> list[str]:
    """Return the sorted closed wrapper IDs registered for one runtime family."""

    config = family_config(family, repo_root)
    return sorted(config["wrappers"])


def wrapper_output_map(
    family: str,
    wrapper_ids: list[str] | tuple[str, ...],
    repo_root: Path | None = None,
) -> dict[str, str]:
    """Resolve selected family-local IDs to registry-owned project paths."""

    config = family_config(family, repo_root)
    wrappers = config["wrappers"]
    unknown = sorted(set(wrapper_ids) - set(wrappers))
    if unknown:
        raise ValueError(
            f"unknown {family} runtime wrapper IDs: {', '.join(unknown)}"
        )
    return {
        wrapper_id: str(wrappers[wrapper_id]["repo_output"])
        for wrapper_id in sorted(wrapper_ids)
    }


def wrapper_id_for_output(
    family: str,
    output: str,
    repo_root: Path | None = None,
) -> str | None:
    """Return the unique family-local wrapper ID owning one project output."""

    config = family_config(family, repo_root)
    matches = [
        wrapper_id
        for wrapper_id, wrapper in config["wrappers"].items()
        if wrapper["repo_output"] == output
    ]
    if len(matches) > 1:
        raise ValueError(
            f"integration registry has duplicate {family} wrapper output: {output}"
        )
    return matches[0] if matches else None


def render_wrapper_outputs(
    family: str,
    wrapper_ids: list[str] | tuple[str, ...],
    framework_ref: str,
    contract_root_ref: str,
    repo_root: Path | None = None,
) -> dict[str, str]:
    """Render selected repo-scoped wrapper files at their registry-owned paths."""

    root = (repo_root or REPO_ROOT).expanduser().absolute()
    config = family_config(family, root)
    wrappers = config["wrappers"]
    unknown = sorted(set(wrapper_ids) - set(wrappers))
    if unknown:
        raise ValueError(
            f"unknown {family} runtime wrapper IDs: {', '.join(unknown)}"
        )
    outputs = {
        wrapper_id: str(wrappers[wrapper_id]["repo_output"])
        for wrapper_id in sorted(wrapper_ids)
    }
    rendered: dict[str, str] = {}
    for wrapper_id, output in outputs.items():
        source = resolve_repo_path(
            root,
            config["wrappers"][wrapper_id]["path"],
            f"{family}.wrappers.{wrapper_id}.path",
        )
        raw = safe_paths.read_regular_file_bytes(
            source,
            description=f"{family} runtime wrapper {wrapper_id}",
        )
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(
                f"{family} runtime wrapper {wrapper_id} must be UTF-8"
            ) from exc
        if source.name.endswith(".template"):
            text = render_wrapper_template_text(
                family,
                output,
                text,
                framework_ref,
                contract_root_ref,
                template_label=str(source),
            )
        _validate_wrapper_native_identity(
            family,
            output,
            text,
            f"{family}.wrappers.{wrapper_id}",
        )
        wrapper_config = config["wrappers"][wrapper_id]
        lifecycle_errors = wrapper_lifecycle_errors(
            text,
            output=output,
            lifecycle=wrapper_config["lifecycle"],
            authority_precondition=wrapper_config["authority_precondition"],
        )
        if lifecycle_errors:
            raise ValueError("; ".join(lifecycle_errors))
        rendered[output] = text
    return rendered


def wrapper_generation_source(
    family: str,
    output: str,
    repo_root: Path | None = None,
) -> str | None:
    """Return the repository-relative template source for one wrapper output."""

    root = (repo_root or REPO_ROOT).expanduser().absolute()
    wrapper_id = wrapper_id_for_output(family, output, root)
    if wrapper_id is None:
        return None
    config = family_config(family, root)
    return str(config["wrappers"][wrapper_id]["path"])


def authority_load_syntax_specs_for_output(
    output: str,
    repo_root: Path | None = None,
) -> tuple[AuthorityLoadSyntaxSpec, ...]:
    """Return every registry-owned grammar applicable to one output name."""

    syntax_ids = sorted(
        {
            config["entrypoint"]["authority_load_syntax"]
            for config in load_registry(repo_root)["families"].values()
            if config["entrypoint"]["output"] == output
        }
    )
    if not syntax_ids:
        raise ValueError(f"integration registry has no entrypoint output: {output}")
    return tuple(AUTHORITY_LOAD_SYNTAX_SPECS[syntax_id] for syntax_id in syntax_ids)


def _active_line_indexes(lines: list[str]) -> set[int]:
    """Return lines that are operative Markdown rather than fenced/commented examples."""

    active: set[int] = set()
    visibility = markdown_structure.MarkdownVisibilityState()
    structural_markers = {
        RECOVERY_GUARD_MARKER,
        FRAMEWORK_CORE_MARKER,
        PROJECT_CONTRACT_MARKER,
        STATE_LOADING_MARKER,
        ROUTING_AFTER_STATE_MARKER,
        WRAPPER_AUTHORITY_PRECONDITION_MARKER,
    }
    for index, line in enumerate(lines):
        if (
            visibility.fence.character is None
            and not visibility.in_html_comment
            and line in structural_markers
        ):
            # Marker comments are intentionally machine-operative even though
            # ordinary HTML comments are excluded from instruction parsing.
            active.add(index)
            continue
        fence_event, visible_line = visibility.consume(line)
        if fence_event is None and visible_line is not None and visible_line.strip():
            active.add(index)
    return active


def _unique_marker_index(
    lines: list[str],
    active_indexes: set[int],
    marker: str,
    label: str,
    output: str,
    errors: list[str],
) -> int | None:
    indexes = [
        index
        for index, line in enumerate(lines)
        if index in active_indexes and line == marker
    ]
    if len(indexes) != 1:
        errors.append(
            f"{output} structural authority-load marker {label} occurs "
            f"{len(indexes)} times; expected exactly one"
        )
        return None
    return indexes[0]


def _select_authority_load_syntax(
    output: str,
    lines: list[str],
    active_indexes: set[int],
    framework_index: int,
    contract_index: int,
    *,
    authority_load_syntax: str | None,
    repo_root: Path | None,
    errors: list[str],
) -> AuthorityLoadSyntaxSpec | None:
    if authority_load_syntax is not None:
        spec = AUTHORITY_LOAD_SYNTAX_SPECS.get(authority_load_syntax)
        if spec is None:
            errors.append(
                f"{output} selects unknown authority-load syntax "
                f"{authority_load_syntax!r}"
            )
        return spec
    candidates = authority_load_syntax_specs_for_output(output, repo_root)
    if len(candidates) == 1:
        return candidates[0]
    selected: list[AuthorityLoadSyntaxSpec] = []
    for spec in candidates:
        selector = spec.framework_block_open or FRAMEWORK_UNAVAILABLE_CLAUSE
        if any(
            index in active_indexes and lines[index] == selector
            for index in range(framework_index + 1, contract_index)
        ):
            selected.append(spec)
    if len(selected) != 1:
        errors.append(
            f"{output} does not select exactly one registry-owned authority-load "
            "syntax from its active framework block"
        )
        return None
    return selected[0]


def _active_occurrences(
    lines: list[str],
    active_indexes: set[int],
    value: str,
    start: int,
    end: int,
) -> list[int]:
    return [
        index
        for index in range(start, end)
        if index in active_indexes and lines[index] == value
    ]


def _line_at(lines: list[str], index: int) -> str | None:
    return lines[index] if 0 <= index < len(lines) else None


def _recovery_guard_errors(
    output: str,
    lines: list[str],
    active_indexes: set[int],
    recovery_index: int,
    contract_root_ref: str,
) -> list[str]:
    """Require the exact guard after charter load and before project authority."""

    errors: list[str] = []
    expected_clause = render_project_file_references(
        RECOVERY_GUARD_CLAUSE,
        contract_root_ref,
    )
    clause_indexes = [
        index
        for index, line in enumerate(lines)
        if index in active_indexes and line == expected_clause
    ]
    if clause_indexes != [recovery_index + 1]:
        errors.append(
            f"{output} recovery guard must contain the exact recovery clause once, "
            "immediately after its structural marker"
        )
    return errors


def _pre_guard_project_reference_errors(
    output: str,
    lines: list[str],
    active_indexes: set[int],
    recovery_index: int,
) -> list[str]:
    """Reject active project-authority or state references before the guard."""

    offending_lines = [
        index + 1
        for index in range(recovery_index)
        if index in active_indexes
        and any(filename in lines[index] for filename in PROJECT_FILE_NAMES)
    ]
    if not offending_lines:
        return []
    return [
        f"{output} active generated project authority/state reference occurs before "
        "the recovery guard at line(s): "
        + ", ".join(str(line_number) for line_number in offending_lines)
    ]


def recovery_guard_prefix_errors(
    text: str,
    *,
    output: str,
    charter_directive: str,
    contract_root_ref: str = ".",
) -> list[str]:
    """Validate a recovery gate immediately after one active charter directive.

    Maintainer entrypoints do not use the generated entrypoint marker grammar,
    but they share the same recovery invariant.  This public helper keeps the
    Markdown visibility and exact-clause logic in one owner without requiring a
    maintainer file to masquerade as a generated integration.
    """

    lines = text.splitlines()
    active_indexes = _active_line_indexes(lines)
    errors: list[str] = []
    recovery_index = _unique_marker_index(
        lines,
        active_indexes,
        RECOVERY_GUARD_MARKER,
        "recovery-guard",
        output,
        errors,
    )
    charter_indexes = [
        index
        for index, line in enumerate(lines)
        if index in active_indexes and line == charter_directive
    ]
    if len(charter_indexes) != 1:
        errors.append(
            f"{output} must contain the exact active operative-charter directive once"
        )
    if recovery_index is None:
        return errors
    errors.extend(
        _recovery_guard_errors(
            output,
            lines,
            active_indexes,
            recovery_index,
            contract_root_ref,
        )
    )
    errors.extend(
        _pre_guard_project_reference_errors(
            output,
            lines,
            active_indexes,
            recovery_index,
        )
    )
    if len(charter_indexes) == 1:
        active_between = [
            index
            for index in range(charter_indexes[0] + 1, recovery_index)
            if index in active_indexes
        ]
        if recovery_index <= charter_indexes[0] or active_between:
            errors.append(
                f"{output} recovery guard must be the next active instruction after "
                "the operative-charter directive"
            )
    return errors


def _framework_directive_reference(
    spec: AuthorityLoadSyntaxSpec,
    line: str | None,
) -> str | None:
    if line is None:
        return None
    target = "/runtime/operative_charter.md"
    prefix = "Read `"
    suffix = target + spec.framework_load_suffix
    if not line.startswith(prefix) or not line.endswith(suffix):
        return None
    reference = line[len(prefix) : len(line) - len(suffix)]
    return reference or "/"


def _framework_directive_candidate(
    line: str,
) -> bool:
    return line.startswith("Read ") and "operative_charter.md" in line


def _project_directive_candidate(
    line: str,
) -> bool:
    return line.startswith("Read ") and "AGENT_PROJECT.md" in line


def _owned_block_cursor(
    output: str,
    label: str,
    lines: list[str],
    active_indexes: set[int],
    marker_index: int,
    boundary_index: int,
    block_open: str | None,
    block_close: str | None,
    *,
    required_body_lines: int,
) -> tuple[int, list[str]]:
    """Return the first owner-block body line after validating exact delimiters."""

    cursor = marker_index + 1
    if block_open is None:
        return cursor, []
    errors: list[str] = []
    open_indexes = _active_occurrences(
        lines,
        active_indexes,
        block_open,
        marker_index + 1,
        boundary_index,
    )
    close_indexes = _active_occurrences(
        lines,
        active_indexes,
        block_close or "",
        marker_index + 1,
        boundary_index,
    )
    if open_indexes != [cursor]:
        errors.append(
            f"{output} {label} authority-load block does not have exactly one "
            f"marker-owned {block_open} opener"
        )
    cursor += 1
    if (
        len(close_indexes) != 1
        or close_indexes[0] <= cursor + required_body_lines - 1
    ):
        errors.append(
            f"{output} {label} authority-load block does not have exactly one "
            f"ordered {block_close} closer"
        )
    return cursor, errors


def _framework_authority_load_result(
    output: str,
    spec: AuthorityLoadSyntaxSpec,
    lines: list[str],
    active_indexes: set[int],
    framework_index: int,
    recovery_index: int,
) -> tuple[str | None, list[str]]:
    cursor, errors = _owned_block_cursor(
        output,
        "framework",
        lines,
        active_indexes,
        framework_index,
        recovery_index,
        spec.framework_block_open,
        spec.framework_block_close,
        required_body_lines=2,
    )
    unavailable_indexes = _active_occurrences(
        lines,
        active_indexes,
        FRAMEWORK_UNAVAILABLE_CLAUSE,
        framework_index + 1,
        recovery_index,
    )
    if unavailable_indexes != [cursor]:
        errors.append(
            f"{output} framework authority-load block must contain the exact "
            "framework-unavailable clause once, immediately before the load directive"
        )
    directive_index = cursor + 1
    reference = _framework_directive_reference(
        spec,
        _line_at(lines, directive_index),
    )
    if directive_index not in active_indexes or reference is None:
        errors.append(
            f"{output} framework authority-load directive is missing, inactive, or malformed"
        )
    candidates = [
        index
        for index in range(framework_index + 1, recovery_index)
        if index in active_indexes
        and _framework_directive_candidate(lines[index])
    ]
    if candidates != [directive_index]:
        errors.append(
            f"{output} framework authority-load block contains "
            f"{len(candidates)} active operative-charter directive candidates; "
            "expected exactly the marker-owned directive"
        )
    expected_scaffolding = [FRAMEWORK_CORE_MARKER]
    if spec.framework_block_open is not None:
        expected_scaffolding.append(spec.framework_block_open)
    expected_scaffolding.extend(
        [
            FRAMEWORK_UNAVAILABLE_CLAUSE,
            _line_at(lines, directive_index) or "",
        ]
    )
    if spec.framework_block_close is not None:
        expected_scaffolding.append(spec.framework_block_close)
    expected_scaffolding.append(RECOVERY_GUARD_MARKER)
    actual_scaffolding = [
        lines[index]
        for index in range(framework_index, recovery_index + 1)
        if index in active_indexes
    ]
    if actual_scaffolding != expected_scaffolding:
        errors.append(
            f"{output} framework load scaffolding must end at the recovery guard "
            "without intervening active instructions"
        )
    return reference, errors


def _project_authority_load_errors(
    output: str,
    spec: AuthorityLoadSyntaxSpec,
    lines: list[str],
    active_indexes: set[int],
    contract_index: int,
    state_index: int,
    contract_root_ref: str,
) -> list[str]:
    cursor, errors = _owned_block_cursor(
        output,
        "project-contract",
        lines,
        active_indexes,
        contract_index,
        state_index,
        spec.project_block_open,
        spec.project_block_close,
        required_body_lines=1,
    )
    expected_contract = (
        "AGENT_PROJECT.md"
        if contract_root_ref == "."
        else f"{contract_root_ref}/AGENT_PROJECT.md"
    )
    expected_sow = (
        "STATEMENT_OF_WORK.md"
        if contract_root_ref == "."
        else f"{contract_root_ref}/STATEMENT_OF_WORK.md"
    )
    expected_line = (
        f"Read `{expected_contract}` before acting. It is the compact runtime "
        f"project contract whose governing project terms are distilled from "
        f"`{expected_sow}`; its model-owned framework-reference binding is "
        "non-authoritative lifecycle data."
    )
    if cursor not in active_indexes or _line_at(lines, cursor) != expected_line:
        errors.append(
            f"{output} project-contract authority-load directive is missing, inactive, "
            "malformed, or selects the wrong contract"
        )
    candidates = [
        index
        for index in range(contract_index + 1, state_index)
        if index in active_indexes and _project_directive_candidate(lines[index])
    ]
    if candidates != [cursor]:
        errors.append(
            f"{output} project-contract authority-load block contains "
            f"{len(candidates)} active project-contract directive candidates; "
            "expected exactly the marker-owned directive"
        )
    return errors


def entrypoint_authority_load_references(
    output: str,
    text: str,
    *,
    contract_root_ref: str = ".",
    authority_load_syntax: str | None = None,
    repo_root: Path | None = None,
) -> tuple[str | None, list[str]]:
    """Validate marker-owned load directives and return the framework root reference."""

    lines = text.splitlines()
    active_indexes = _active_line_indexes(lines)
    errors: list[str] = []
    recovery_index = _unique_marker_index(
        lines,
        active_indexes,
        RECOVERY_GUARD_MARKER,
        "recovery guard",
        output,
        errors,
    )
    framework_index = _unique_marker_index(
        lines,
        active_indexes,
        FRAMEWORK_CORE_MARKER,
        "framework core",
        output,
        errors,
    )
    contract_index = _unique_marker_index(
        lines,
        active_indexes,
        PROJECT_CONTRACT_MARKER,
        "project contract",
        output,
        errors,
    )
    state_index = _unique_marker_index(
        lines,
        active_indexes,
        STATE_LOADING_MARKER,
        "state loading",
        output,
        errors,
    )
    routing_index = _unique_marker_index(
        lines,
        active_indexes,
        ROUTING_AFTER_STATE_MARKER,
        "post-state routing",
        output,
        errors,
    )
    if None in (
        recovery_index,
        framework_index,
        contract_index,
        state_index,
        routing_index,
    ):
        return None, errors
    assert recovery_index is not None
    assert framework_index is not None
    assert contract_index is not None
    assert state_index is not None
    assert routing_index is not None
    if not (
        framework_index
        < recovery_index
        < contract_index
        < state_index
        < routing_index
    ):
        errors.append(
            f"{output} structural authority-load markers are not in framework, "
            "recovery guard, project-contract, state-loading, post-state-routing order"
        )
        return None, errors

    route_tokens = (
        "master_service_agreement.md",
        "runtime/task_modules/",
        "task_orders/README.md",
        "practice_guides/",
        "scripts/recommend_stack.py",
    )
    routed_indexes = [
        index
        for index in active_indexes
        if any(token in lines[index] for token in route_tokens)
    ]
    if not routed_indexes or any(index <= routing_index for index in routed_indexes):
        errors.append(
            f"{output} workflow and Practice Guide routing must be active only "
            "after the post-state routing marker"
        )
        return None, errors

    errors.extend(
        _recovery_guard_errors(
            output,
            lines,
            active_indexes,
            recovery_index,
            contract_root_ref,
        )
    )
    errors.extend(
        _pre_guard_project_reference_errors(
            output,
            lines,
            active_indexes,
            recovery_index,
        )
    )

    spec = _select_authority_load_syntax(
        output,
        lines,
        active_indexes,
        framework_index,
        recovery_index,
        authority_load_syntax=authority_load_syntax,
        repo_root=repo_root,
        errors=errors,
    )
    if spec is None:
        return None, errors

    framework_reference, framework_errors = _framework_authority_load_result(
        output,
        spec,
        lines,
        active_indexes,
        framework_index,
        recovery_index,
    )
    errors.extend(framework_errors)
    errors.extend(
        _project_authority_load_errors(
            output,
            spec,
            lines,
            active_indexes,
            contract_index,
            state_index,
            contract_root_ref,
        )
    )

    if framework_reference is not None:
        errors.extend(
            f"{output} framework authority-load reference {error}"
            for error in safe_paths.framework_reference_errors(framework_reference)
        )
    return (framework_reference if not errors else None), errors


def entrypoint_paths(repo_root: Path | None = None) -> list[str]:
    registry = load_registry(repo_root)
    return [config["entrypoint"]["path"] for config in registry["families"].values()]


def required_template_files(repo_root: Path | None = None) -> list[str]:
    registry = load_registry(repo_root)
    files = ["integrations/registry.json"]
    for config in registry["families"].values():
        root = (repo_root or REPO_ROOT).expanduser().absolute()
        template_root = resolve_repo_path(root, config["template_root"], "template_root")
        files.extend(
            path.relative_to(root).as_posix()
            for path in template_root.rglob("*")
            if path.is_file()
        )
    return sorted(files)
