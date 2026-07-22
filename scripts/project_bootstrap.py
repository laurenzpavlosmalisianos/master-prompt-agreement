#!/usr/bin/env python3

from __future__ import annotations

import _imp as _bootstrap_imp
import sys as _bootstrap_sys


def _require_python_startup_flags(label: str) -> None:
    """Reject an entrypoint before it can load repository-local modules."""

    if _bootstrap_sys.implementation.name != "cpython":
        raise RuntimeError(f"{label} requires CPython")
    required = (
        ("-E", "ignore_environment"),
        ("-S", "no_site"),
        ("-B", "dont_write_bytecode"),
    )
    missing = [flag for flag, name in required if not getattr(_bootstrap_sys.flags, name)]
    if missing:
        raise RuntimeError(
            f"{label} requires CPython startup flags -E -S -B before loading "
            f"repository-local modules; missing active flags: {' '.join(missing)}"
        )


def _load_trusted_import_boundary(entrypoint: str) -> str:
    """Load the shared boundary owner by exact regular-file source."""

    if not _bootstrap_imp.is_frozen("os"):
        raise RuntimeError("project bootstrap requires CPython's frozen os module")
    import os as bootstrap_os
    scripts_root = bootstrap_os.path.dirname(bootstrap_os.path.realpath(entrypoint))
    source_path = bootstrap_os.path.join(scripts_root, "python_import_boundary.py")
    close_on_exec = getattr(bootstrap_os, "O_CLOEXEC", 0)
    no_follow = getattr(bootstrap_os, "O_NOFOLLOW", 0)
    if not close_on_exec or not no_follow:
        raise RuntimeError("project bootstrap requires O_CLOEXEC and O_NOFOLLOW")
    flags = bootstrap_os.O_RDONLY | close_on_exec | no_follow
    descriptor = bootstrap_os.open(source_path, flags)
    try:
        metadata = bootstrap_os.fstat(descriptor)
        if metadata.st_mode & 0o170000 != 0o100000 or metadata.st_nlink != 1:
            raise RuntimeError("project bootstrap import boundary is not a regular file")
        chunks: list[bytes] = []
        remaining = 65_537
        while remaining:
            chunk = bootstrap_os.read(descriptor, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
    finally:
        bootstrap_os.close(descriptor)
    source = b"".join(chunks)
    if not source or len(source) > 65_536 or len(source) != metadata.st_size:
        raise RuntimeError("project bootstrap import boundary source is invalid")
    module = type(_bootstrap_sys)("python_import_boundary")
    module.__file__ = source_path
    _bootstrap_sys.modules["python_import_boundary"] = module
    exec(compile(source, source_path, "exec"), module.__dict__)
    return scripts_root


if __name__ == "__main__":
    _require_python_startup_flags("project bootstrap")
    _bootstrap_scripts_root = _load_trusted_import_boundary(__file__)
    import python_import_boundary as _python_import_boundary

    _python_import_boundary.establish_import_boundary(
        scripts_root=_bootstrap_scripts_root,
        label="project bootstrap",
    )

import argparse
from collections.abc import Iterable, Mapping, Set as AbstractSet
from dataclasses import dataclass
from datetime import date
from datetime import datetime
from datetime import timezone
import hashlib
import json
import os
import re
import shlex
import stat
from pathlib import Path

import automation_orders_lint
import bootstrap_transaction
import generated_sow_text
import integration_registry
import markdown_structure
import project_contract_model as contract_model
import project_input
import project_state_identity
import product_manifest
import resource_cleanup
import safe_paths
from project_contract_model import (
    ALLOWED_KEYS,
    ANSWER_TEXT_GRAMMAR_BY_KEY,
    ANNEX_CONFLICT_RULE,
    ANNEX_KEYS,
    ANNEX_KEYS_IN_ORDER,
    ANNEX_LABELS,
    AUTOMATION_AUTHORITY_RULE,
    AUTOMATION_ORDER_KEYS,
    AUXILIARY_TOOL_KEYS,
    BOOTSTRAP_MODES,
    BOOTSTRAP_STATE_TEMPLATES,
    BOOLEAN_KEYS,
    COMMAND_KEYS,
    DEFAULT_DECISION_AUTHORITY_GRANT,
    DEFAULT_PERSISTENT_MEMORY_BOUNDARY,
    DEFAULT_SECURITY_POLICY_FILE,
    DEFAULT_SECURITY_VERIFICATION_PROFILE_SCOPE,
    DEFAULT_SECURITY_VERIFICATION_TARGET_POLICY,
    DEFAULT_SOURCE_MONITOR_BOUNDARY,
    DEFAULT_SOURCE_MONITOR_INSTRUCTION_SOURCES,
    DEFAULT_SOURCE_MONITOR_ROLE,
    DEFAULT_SOURCE_REGISTRY_SCOPE,
    DEFAULT_SOURCE_REVIEW_CADENCE,
    DEFAULT_VERSION_REVIEW_POLICY,
    DELIVERABLE_KEYS,
    DELIVERABLE_REQUIRED_KEYS,
    DEPENDENCY_POSTURES,
    EXECUTION_POSTURES,
    FRAMEWORK_VERIFICATION_RUNNER_PLACEHOLDER,
    INDEPENDENT_ASSESSMENT_APPROVALS,
    LINE_VALUE_KEYS,
    MANUAL_STATE_TEMPLATES,
    MINIMAL_DEFERRABLE_FIELDS,
    MINIMAL_DEFERRAL_BOUNDARY_TYPES,
    MINIMAL_DEFERRAL_KEYS,
    MINIMAL_COMMAND_DEFERRAL,
    OPERATIVE_LINE_KEYS,
    OPERATIVE_STRING_KEYS,
    OPTIONAL_STATE_FLAGS,
    PANEL_CONFIG_KEYS,
    PANEL_SEAT_KEYS,
    PROJECTED_DEFINITION_FIELDS,
    PROJECT_LOADING_RULE_LINES,
    REQUIRED_AUXILIARY_TOOL_KEYS,
    REQUIRED_KEYS_FULL,
    REQUIRED_KEYS_MINIMAL,
    RESTRICTION_KEYS,
    SECURITY_POLICY_FILES,
    SECURITY_POLICY_ANNEX_LABEL,
    SETUP_PROFILE_FORBIDDEN_KEYS,
    SOW_SECTION_TITLES,
    STATE_TEMPLATES,
    STRING_KEYS,
    WORKFLOW_KEYS,
    WORKFLOW_REQUIRED_KEYS,
)


REPO_ROOT = Path(__file__).resolve().parent.parent
INSTANCE_MANIFEST = "PROJECT_INSTANCE.json"
PROJECT_INSTANCE_SCHEMA_VERSION = 5
EXIT_RECOVERY_REQUIRED = 4
FRAMEWORK_REVISION_POLICIES = frozenset({"live", "pinned"})
SETUP_PROFILE_SCHEMA_VERSION = 1
SETUP_PROFILE_KEYS = {"schema_version", "defaults"}
ENTRYPOINT_TEMPLATES = {
    name: (
        config["entrypoint"]["path"],
        config["entrypoint"]["output"],
    )
    for name, config in integration_registry.load_registry(REPO_ROOT)["families"].items()
}
GENERATED_SURFACE_DISCOVERY_MAX_DEPTH = 32
GENERATED_SURFACE_DISCOVERY_MAX_ENTRIES = 100_000
GENERATED_SURFACE_DISCOVERY_MAX_CANDIDATES = 512
GENERATED_SURFACE_DISCOVERY_MAX_BYTES = 128 * 1024
GENERATED_SURFACE_DISCOVERY_IGNORED_DIRECTORIES = frozenset(
    {".git", ".hg", ".svn"}
)
GENERATED_CONTRACT_BASENAMES = frozenset(
    {
        "AGENT_PROJECT.md",
        "STATEMENT_OF_WORK.md",
        project_input.INPUT_NAME,
        INSTANCE_MANIFEST,
    }
)
GENERATED_STATE_BASENAMES = frozenset(STATE_TEMPLATES)
INTERNAL_LOCAL_STATE_PATTERNS = safe_paths.INTERNAL_LOCAL_STATE_PATTERNS
CONTROL_RE = generated_sow_text.SINGLE_LINE_FORBIDDEN_CONTROL_RE
LINE_CONTROL_RE = generated_sow_text.MULTILINE_FORBIDDEN_CONTROL_RE
PROMPT_BOUNDARY_RE = re.compile(
    r"</?(?:framework|project|practice|codex|system|developer|assistant|user|tool|instructions)[A-Za-z0-9_-]*\b",
    re.IGNORECASE,
)
PRIVATE_STATE_RE = re.compile(
    r"(?<![\w.-])(?:"
    r"\.codex(?:[\\/]|\b)|\.cursor(?:[\\/]|\b)|\.continue(?:[\\/]|\b)|\.mcp\.json|"
    r"\.env(?:\.[A-Za-z0-9_-]+)?|\.npmrc|\.pypirc|"
    r"\.kube(?:[\\/]|\b)|\.aws(?:[\\/]|\b)|\.azure(?:[\\/]|\b)|\.gcloud(?:[\\/]|\b)|"
    r"private[\\/]|review_artifacts[\\/]|external_review[\\/]|notes[\\/]|scratch[\\/]|"
    r"transcripts[\\/]|session_logs[\\/]|captures[\\/]|source_dumps[\\/]|source_material[\\/]|"
    r"local[\\/]|tmp[\\/]"
    r")"
)
EXAMPLE_ANSWER_VALUES = {
    "example project",
    "project agent role to confirm",
    "selected runtime",
}
MSA_VERSION_RE = re.compile(
    r"^Version:\s*(?P<version>(?:0|[1-9][0-9]*)(?:\.[0-9]+)+)(?=\s|$)",
    re.MULTILINE,
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
BOOTSTRAP_WRITE_PLAN_APPROVAL_DOMAIN = (
    "master-prompt-agreement/bootstrap-write-plan-approval/v1"
)


@dataclass(frozen=True, slots=True)
class FrameworkIdentity:
    """One immutable snapshot of the framework surfaces bound to a project."""

    content_sha256: str
    effective_file_digests: tuple[tuple[str, str], ...]
    distribution_sha256: str

    def effective_file_digest_map(self) -> dict[str, str]:
        return dict(self.effective_file_digests)


def bootstrap_mode(answers: dict) -> str:
    return str(answers.get("bootstrap_mode", "")).strip().lower()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_json_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return sha256_bytes(encoded)


def bootstrap_warnings_sha256(warnings: object) -> str:
    """Return the canonical digest of one exact ordered warning list."""

    if not isinstance(warnings, list) or not all(
        isinstance(warning, str) for warning in warnings
    ):
        raise ValueError("bootstrap summary warnings must be a list of strings")
    return canonical_json_digest(warnings)


def bootstrap_write_plan_approval_errors(
    write_plan_sha256: object,
    approvals: tuple[str, ...],
    *,
    dry_run: bool,
) -> list[str]:
    """Validate approval against one complete rendered bootstrap write plan."""

    if (
        not isinstance(write_plan_sha256, str)
        or SHA256_RE.fullmatch(write_plan_sha256) is None
    ):
        return ["bootstrap write-plan approval digest is unavailable or malformed"]
    if dry_run:
        return (
            [
                "--approve-write-plan-sha256 is valid only on the write command "
                "after reviewing a dry-run write plan"
            ]
            if approvals
            else []
        )
    if len(approvals) > 1:
        return ["--approve-write-plan-sha256 must be supplied exactly once"]
    if not approvals:
        return [
            "bootstrap writes require exact rendered-plan approval; rerun the "
            "write command with --approve-write-plan-sha256 "
            "<write_plan_sha256> after reviewing the dry run"
        ]
    approved = approvals[0]
    if SHA256_RE.fullmatch(approved) is None:
        return [
            "--approve-write-plan-sha256 must be exactly 64 lowercase "
            "hexadecimal characters"
        ]
    if approved != write_plan_sha256:
        return [
            "--approve-write-plan-sha256 does not match the complete rendered "
            "bootstrap write plan; run and review a new dry run"
        ]
    return []


def _bootstrap_target_identity(path: Path) -> dict[str, int] | None:
    """Return the stable node identity bound by one bootstrap approval."""

    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return None
    return {
        "device": metadata.st_dev,
        "inode": metadata.st_ino,
        "file_type": stat.S_IFMT(metadata.st_mode),
    }


def _framework_inventory_sha256(paths: Iterable[Path], framework_root: Path) -> str:
    inventory: list[dict[str, object]] = []
    for path in paths:
        relative = path.relative_to(framework_root).as_posix()
        raw = safe_paths.read_regular_file_bytes(
            path,
            description=f"public framework content {relative}",
        )
        inventory.append(
            {
                "path": relative,
                "sha256": sha256_bytes(raw),
                "size": len(raw),
            }
        )
    return canonical_json_digest(inventory)


def framework_content_sha256(framework_root: Path) -> str:
    """Bind the downstream-effective framework surface to one digest."""

    return canonical_json_digest(framework_effective_file_digests(framework_root))


def framework_effective_file_digests(framework_root: Path) -> dict[str, str]:
    """Return exact current digests for approval-relevant downstream surfaces."""

    return {
        path.relative_to(framework_root).as_posix(): sha256_bytes(
            safe_paths.read_regular_file_bytes(
                path,
                description=(
                    "downstream-effective framework content "
                    + path.relative_to(framework_root).as_posix()
                ),
            )
        )
        for path in product_manifest.iter_downstream_effective_files(framework_root)
    }


def framework_distribution_sha256(framework_root: Path) -> str:
    """Bind the complete neutral public distribution to one provenance digest."""

    return _framework_inventory_sha256(
        product_manifest.iter_product_files(framework_root),
        framework_root,
    )


def capture_framework_identity(framework_root: Path) -> FrameworkIdentity:
    """Capture one comparison-safe effective and distribution identity."""

    effective = framework_effective_file_digests(framework_root)
    return FrameworkIdentity(
        content_sha256=canonical_json_digest(effective),
        effective_file_digests=tuple(sorted(effective.items())),
        distribution_sha256=framework_distribution_sha256(framework_root),
    )


def resolve_user_path(
    raw_path: str,
    label: str,
) -> tuple[Path, Path, list[str]]:
    """Expand and resolve one CLI path without leaking platform failures."""

    unresolved = Path(raw_path)
    try:
        expanded = unresolved.expanduser()
        resolved = expanded.resolve(strict=False)
    except (OSError, RuntimeError, ValueError) as exc:
        return unresolved, unresolved, [
            f"{label} could not be resolved from {raw_path!r}: {exc}"
        ]
    return expanded, resolved, []


def load_json_input(raw_path: str, label: str) -> tuple[Path, bytes | None, object | None, list[str]]:
    """Load one explicit JSON input without leaking filesystem failures as tracebacks."""

    unresolved, path, path_errors = resolve_user_path(raw_path, label)
    if path_errors:
        return path, None, None, path_errors
    try:
        raw = safe_paths.read_regular_file_bytes(unresolved, description=label)
    except FileNotFoundError:
        return path, None, None, [f"{label} is missing: {path}"]
    except ValueError as exc:
        return path, None, None, [str(exc)]
    except OSError as exc:
        return path, None, None, [f"{label} could not be read: {path}: {exc}"]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        return path, raw, None, [f"{label} must be valid UTF-8: {path}: {exc}"]
    try:
        payload = safe_paths.loads_json_no_duplicates(text)
    except (json.JSONDecodeError, ValueError) as exc:
        return path, raw, None, [f"{label} is invalid JSON: {path}: {exc}"]
    return path, raw, payload, []


def read_framework_source_text(relative_path: str, *, description: str) -> str:
    """Read one checked-in text source through a bounded no-follow descriptor."""

    normalized = safe_paths.normalize_repo_relative_path(
        relative_path,
        REPO_ROOT,
        description=description,
    )
    path = REPO_ROOT / normalized
    try:
        raw = safe_paths.read_regular_file_bytes(
            path,
            description=description,
        )
    except FileNotFoundError as exc:
        raise ValueError(f"{description} is missing: {path}") from exc
    except OSError as exc:
        raise ValueError(f"{description} could not be read: {path}: {exc}") from exc
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{description} must be valid UTF-8: {path}: {exc}") from exc


def validate_setup_profile(profile: object) -> list[str]:
    if not isinstance(profile, dict):
        return ["setup profile must be a JSON object"]
    errors: list[str] = []
    errors.extend(
        f"unknown setup profile key: {key}"
        for key in sorted(set(profile) - SETUP_PROFILE_KEYS)
    )
    errors.extend(
        f"missing setup profile key: {key}"
        for key in sorted(SETUP_PROFILE_KEYS - set(profile))
    )
    if profile.get("schema_version") != SETUP_PROFILE_SCHEMA_VERSION:
        errors.append(
            f"setup profile schema_version must be exactly {SETUP_PROFILE_SCHEMA_VERSION}"
        )
    defaults = profile.get("defaults")
    if not isinstance(defaults, dict):
        errors.append("setup profile defaults must be a JSON object")
        return errors
    errors.extend(
        f"unknown setup profile default key: {key}"
        for key in sorted(set(defaults) - ALLOWED_KEYS)
    )
    errors.extend(
        f"setup profile must not provide project-fact key: {key}"
        for key in sorted(set(defaults) & SETUP_PROFILE_FORBIDDEN_KEYS)
    )
    errors.extend(find_internal_leaks(defaults, "setup_profile.defaults"))
    probe: dict[str, object] = {
        key: value
        for key, value in defaults.items()
        if key in ALLOWED_KEYS and key not in SETUP_PROFILE_FORBIDDEN_KEYS
    }
    probe.setdefault("bootstrap_mode", "minimal")
    probe.setdefault("agent", "setup-profile validation agent")
    probe.setdefault("framework_verification_runner", "python -E -S -B")
    probe.setdefault("project_name", "setup-profile validation project")
    if bootstrap_mode(probe) == "full":
        probe.update(
            {
                "architecture": "setup-profile validation architecture",
                "commands": {key: "none" for key in COMMAND_KEYS},
                "deliverables": [
                    {
                        "description": "setup-profile validation deliverable",
                        "test": "manual validation",
                        "pass_criteria": "profile defaults validate",
                    }
                ],
                "in_scope": ["setup-profile validation"],
                "language_runtime_standards": "setup-profile validation runtime",
                "out_of_scope": ["all non-validation work"],
                "recitals": ["Validate reusable setup-profile defaults."],
                "tech_stack": "setup-profile validation stack",
            }
        )
    errors.extend(
        "setup profile defaults: " + error
        for error in validate_answers(probe)
    )
    return errors


def apply_setup_profile(
    answers: object,
    profile: object | None,
) -> tuple[object, list[str], list[str]]:
    if not isinstance(answers, dict) or profile is None:
        return answers, [], []
    if not isinstance(profile, dict) or not isinstance(profile.get("defaults"), dict):
        return answers, [], []
    defaults = profile["defaults"]
    effective = dict(answers)
    applied = sorted(key for key in defaults if key not in answers)
    overridden = sorted(key for key in defaults if key in answers)
    for key in applied:
        effective[key] = defaults[key]
    return effective, applied, overridden


def validate_line_value(key: str, value: object, errors: list[str]) -> None:
    if isinstance(value, str):
        validate_line_text(key, value, errors, single_line=False)
        return
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        for index, item in enumerate(value, start=1):
            validate_line_text(
                f"{key}[{index}]",
                item,
                errors,
                single_line=True,
            )
        return
    errors.append(f"bootstrap answer key '{key}' must be a string or list of strings")


def validate_line_text(
    label: str,
    value: str,
    errors: list[str],
    *,
    single_line: bool,
) -> None:
    has_line_boundary = contract_model.contains_splitlines_boundary(value)
    if LINE_CONTROL_RE.search(value):
        errors.append(f"{label} must not contain control characters")
    elif single_line and has_line_boundary:
        errors.append(
            f"{label} must be single-line text without Unicode line separators"
        )
    if PROMPT_BOUNDARY_RE.search(value):
        errors.append(f"{label} must not contain framework or prompt-boundary tags")
    if contract_model.CONTRACT_FORMAT_MARKER_KEY in value:
        errors.append(
            f"{label} must not contain the reserved generated-contract marker key"
        )
    if not (single_line and has_line_boundary):
        for line in value.splitlines() or [value]:
            syntax_kind = contract_model.generated_sow_control_syntax_kind(line)
            if syntax_kind is not None:
                errors.append(
                    f"{label} must not contain generated-SOW {syntax_kind}"
                )
                break


def validate_string_values(container: dict, allowed: AbstractSet[str], prefix: str, errors: list[str]) -> None:
    for key in sorted(set(container) & allowed):
        if not isinstance(container[key], str):
            errors.append(f"{prefix} key '{key}' must be a string")
            continue
        value = container[key]
        has_line_boundary = contract_model.contains_splitlines_boundary(value)
        if CONTROL_RE.search(value):
            errors.append(f"{prefix} key '{key}' must be single-line text without control characters")
        elif has_line_boundary:
            errors.append(
                f"{prefix} key '{key}' must be single-line text without Unicode "
                "line separators"
            )
        if not has_line_boundary:
            for line in value.splitlines() or [value]:
                syntax_kind = contract_model.generated_sow_control_syntax_kind(line)
                if syntax_kind is not None:
                    errors.append(
                        f"{prefix} key '{key}' must not contain generated-SOW "
                        f"{syntax_kind}"
                    )
                    break
        if PROMPT_BOUNDARY_RE.search(value):
            errors.append(f"{prefix} key '{key}' must not contain framework or prompt-boundary tags")
        if contract_model.CONTRACT_FORMAT_MARKER_KEY in value:
            errors.append(
                f"{prefix} key '{key}' must not contain the reserved generated-contract marker key"
            )


def validate_reserved_generated_text_values(
    container: dict,
    allowed: AbstractSet[str],
    prefix: str,
    errors: list[str],
) -> None:
    """Reject instruction-boundary tokens not owned by a downstream validator."""

    for key in sorted(set(container) & allowed):
        value = container[key]
        if not isinstance(value, str):
            continue
        if PROMPT_BOUNDARY_RE.search(value):
            errors.append(
                f"{prefix} key '{key}' must not contain framework or "
                "prompt-boundary tags"
            )
        if contract_model.CONTRACT_FORMAT_MARKER_KEY in value:
            errors.append(
                f"{prefix} key '{key}' must not contain the reserved "
                "generated-contract marker key"
            )


def validate_answer_text_grammar(answers: dict, errors: list[str]) -> None:
    for answer_key, grammar in ANSWER_TEXT_GRAMMAR_BY_KEY.items():
        value = answers.get(answer_key)
        candidates: list[tuple[str, str]] = []
        if grammar.member_keys and isinstance(value, dict):
            candidates.extend(
                (f"{answer_key} key '{member_key}'", member_value)
                for member_key, member_value in value.items()
                if member_key in grammar.member_keys
                and isinstance(member_value, str)
            )
        elif grammar.member_keys and isinstance(value, list):
            candidates.extend(
                (
                    f"{answer_key} item {index} key '{member_key}'",
                    member_value,
                )
                for index, item in enumerate(value, start=1)
                if isinstance(item, dict)
                for member_key, member_value in item.items()
                if member_key in grammar.member_keys
                and isinstance(member_value, str)
            )
        elif not grammar.member_keys:
            if isinstance(value, str):
                raw_candidates = value.splitlines() or [value]
            elif isinstance(value, list):
                raw_candidates = [
                    line
                    for item in value
                    if isinstance(item, str)
                    for line in (item.splitlines() or [item])
                ]
            else:
                raw_candidates = []
            candidates.extend(
                (f"{answer_key}[{index}]", candidate)
                for index, candidate in enumerate(raw_candidates, start=1)
            )
        if grammar.forbidden_exact_lines:
            for label, candidate in candidates:
                stripped = candidate.strip()
                if stripped in grammar.forbidden_exact_lines:
                    errors.append(
                        f"{label} must not equal reserved unprefixed "
                        f"SOW section title: {stripped!r}"
                    )
        for label, candidate in candidates:
            stripped = candidate.strip()
            for syntax_label, pattern in grammar.forbidden_line_syntax:
                if re.match(rf"^(?:{pattern})", stripped):
                    errors.append(
                        f"{label} must not start with reserved unprefixed SOW "
                        f"identity syntax: {syntax_label!r}"
                    )
        if isinstance(value, str):
            for token in grammar.forbidden_substrings:
                if token in value:
                    errors.append(
                        f"bootstrap answer key '{answer_key}' must not contain "
                        f"reserved SOW preamble token: {token!r}"
                    )


def validate_required_string_values(answers: dict, required_keys: AbstractSet[str], errors: list[str]) -> None:
    for key in sorted(required_keys):
        if key not in answers:
            continue
        value = answers[key]
        if isinstance(value, str) and not value.strip():
            errors.append(f"required bootstrap answer key '{key}' must not be empty")


def validate_shell_command(label: str, command: str, errors: list[str]) -> None:
    if not present_value(command):
        return
    try:
        shlex.split(command)
    except ValueError as exc:
        errors.append(f"{label} is not shell-parseable: {exc}")


def validate_object_list(
    value: object,
    label: str,
    required_keys: AbstractSet[str],
    allowed_keys: AbstractSet[str],
    errors: list[str],
    *,
    require_concrete_values: bool = True,
) -> None:
    if not isinstance(value, list):
        errors.append(f"bootstrap answer key '{label}' must be a list")
        return
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            errors.append(f"{label} item {index} must be an object")
            continue
        errors.extend(
            f"missing {label} key in item {index}: {key}"
            for key in sorted(required_keys - set(item))
        )
        errors.extend(
            f"unknown {label} key in item {index}: {key}"
            for key in sorted(set(item) - allowed_keys)
        )
        validate_string_values(item, allowed_keys, f"{label} item {index}", errors)
        if require_concrete_values:
            for key in sorted(required_keys & set(item)):
                value = item[key]
                if isinstance(value, str) and (
                    not value.strip() or contract_model.is_deferred_value(value)
                ):
                    errors.append(
                        f"{label} item {index} key '{key}' must be concrete; omit the optional item until it is known"
                    )


def _declared_delimiter_errors(
    value: object,
    *,
    collection: str,
    item_label: str,
) -> list[str]:
    """Validate model-owned rendered delimiters for one structured collection."""

    if not isinstance(value, list):
        return []
    errors: list[str] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            continue
        for field, raw_value in item.items():
            if not isinstance(field, str) or not isinstance(raw_value, str):
                continue
            for delimiter in contract_model.structured_field_delimiters(
                collection,
                field,
            ):
                if delimiter in raw_value:
                    errors.append(
                        f"{item_label} {index} key '{field}' must not contain "
                        f"reserved rendered delimiter {delimiter!r}"
                    )
    return errors


def _declared_identity_errors(
    value: object,
    *,
    collection: str,
    item_label: str,
) -> list[str]:
    """Validate one model-declared identity field without constraining prose lists."""

    if not isinstance(value, list):
        return []
    field = contract_model.STRUCTURED_IDENTITY_FIELDS[collection]
    seen: dict[str, tuple[int, str]] = {}
    errors: list[str] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            continue
        raw_identity = item.get(field)
        if not isinstance(raw_identity, str) or not raw_identity.strip():
            continue
        identity = raw_identity.strip()
        normalized = contract_model.normalized_contract_identity(identity)
        prior = seen.get(normalized)
        if prior is None:
            seen[normalized] = (index, identity)
            continue
        prior_index, prior_identity = prior
        errors.append(
            f"{item_label} {index} duplicates normalized {field} identity from "
            f"item {prior_index}: {identity!r} conflicts with {prior_identity!r}"
        )
    return errors


def workflow_identity_errors(value: object) -> list[str]:
    return _declared_identity_errors(
        value,
        collection="workflows",
        item_label="workflows item",
    )


def command_restriction_identity_errors(value: object) -> list[str]:
    return _declared_identity_errors(
        value,
        collection="command_restrictions",
        item_label="command restriction",
    )


def auxiliary_tool_identity_errors(value: object) -> list[str]:
    return _declared_identity_errors(
        value,
        collection="auxiliary_tools",
        item_label="auxiliary tool",
    )


def find_internal_leaks(value: object, path: str = "answers") -> list[str]:
    leaks: list[str] = []
    if isinstance(value, str):
        if any(pattern.search(value) for pattern in INTERNAL_LOCAL_STATE_PATTERNS):
            leaks.append(f"{path} contains an internal local-state filename reference")
    elif isinstance(value, list):
        for index, item in enumerate(value, start=1):
            leaks.extend(find_internal_leaks(item, f"{path}[{index}]"))
    elif isinstance(value, dict):
        for key, item in value.items():
            leaks.extend(find_internal_leaks(item, f"{path}.{key}"))
    return leaks


def find_local_state_references(value: object, path: str = "answers") -> list[str]:
    warnings: list[str] = []
    if isinstance(value, str):
        if safe_paths.contains_local_absolute_path(value):
            warnings.append(
                f"{path} contains a host-specific absolute path. Prefer repo-relative paths, approved environment variables, or an explicit local-only note."
            )
        if PRIVATE_STATE_RE.search(value):
            warnings.append(
                f"{path} references local agent, credential, private, or generated state. Keep public project contracts generic or explicitly local-only."
            )
    elif isinstance(value, list):
        for index, item in enumerate(value, start=1):
            warnings.extend(find_local_state_references(item, f"{path}[{index}]"))
    elif isinstance(value, dict):
        for key, item in value.items():
            warnings.extend(find_local_state_references(item, f"{path}.{key}"))
    return warnings


def validate_project_name(value: object, errors: list[str]) -> None:
    if not isinstance(value, str):
        return
    if CONTROL_RE.search(value) or any(marker in value for marker in ("<", ">")):
        errors.append(
            "project_name must be plain text without control characters or angle brackets"
        )


@dataclass
class AnswerValidationContext:
    answers: dict
    mode: str
    errors: list[str]


def validate_answer_scalars(context: AnswerValidationContext) -> None:
    answers = context.answers
    errors = context.errors
    errors.extend(
        f"unknown bootstrap answer key: {key}"
        for key in sorted(set(answers) - ALLOWED_KEYS)
    )
    errors.extend(find_internal_leaks(answers))
    validate_project_name(answers.get("project_name"), errors)
    if "bootstrap_mode" not in answers:
        errors.append("missing required bootstrap answer key: bootstrap_mode")
    if context.mode not in BOOTSTRAP_MODES:
        errors.append("bootstrap_mode must be 'full' or 'minimal'")
    for key in sorted(set(answers) & BOOLEAN_KEYS):
        if not isinstance(answers[key], bool):
            errors.append(f"bootstrap answer key '{key}' must be boolean")
    validate_string_values(answers, STRING_KEYS, "bootstrap answer", errors)
    for key in sorted(set(answers) & LINE_VALUE_KEYS):
        validate_line_value(key, answers[key], errors)
    validate_answer_text_grammar(answers, errors)
    for key in sorted(set(answers) & OPERATIVE_STRING_KEYS):
        value = answers[key]
        if isinstance(value, str) and contract_model.is_deferred_value(value):
            errors.append(
                f"bootstrap answer key '{key}' is operative runtime content and must not be placeholder text"
            )
    for key in sorted(set(answers) & OPERATIVE_LINE_KEYS):
        for index, value in enumerate(lines_for(answers[key]), start=1):
            if contract_model.is_deferred_value(value):
                errors.append(
                    f"bootstrap answer key '{key}' item {index} is operative runtime content and must not be placeholder text"
                )
    execution_posture = str(answers.get("execution_posture", "")).strip().lower()
    if execution_posture and execution_posture not in EXECUTION_POSTURES:
        errors.append("execution_posture must be one of: act, advise, ask-when-ambiguous")
    dependency_posture = str(answers.get("dependency_posture", "")).strip().lower()
    if dependency_posture and dependency_posture not in DEPENDENCY_POSTURES:
        errors.append(
            "dependency_posture must be one of: no-external-dependencies, justify-external-dependencies"
        )
    independent_assessment_approval = str(
        answers.get("independent_assessment_approval", "")
    ).strip()
    if (
        independent_assessment_approval
        and independent_assessment_approval not in INDEPENDENT_ASSESSMENT_APPROVALS
    ):
        errors.append(
            "independent_assessment_approval must be one of: Autonomous, Required"
        )
    standing_panel_approval = str(
        answers.get("standing_panel_convocation_approval", "")
    ).strip()
    if standing_panel_approval and not (
        standing_panel_approval in {"No", "Yes"}
        or standing_panel_approval.startswith("Yes,")
    ):
        errors.append(
            "standing_panel_convocation_approval must be 'No', 'Yes', or start with 'Yes,'"
        )
    security_policy = str(answers.get("security_policy_file", "")).strip()
    if security_policy and security_policy not in SECURITY_POLICY_FILES:
        errors.append(
            "security_policy_file must be one of: inline in this SOW, project SECURITY.md, none"
        )
    if context.mode == "minimal":
        required_keys = REQUIRED_KEYS_MINIMAL
    elif context.mode == "full":
        required_keys = REQUIRED_KEYS_FULL
    else:
        required_keys = set()
    errors.extend(
        f"missing required bootstrap answer key: {key}"
        for key in sorted(required_keys - set(answers))
    )
    validate_required_string_values(answers, required_keys, errors)


def validate_answer_commands(context: AnswerValidationContext) -> None:
    answers = context.answers
    errors = context.errors
    if "commands" in answers and not isinstance(answers["commands"], dict):
        errors.append("bootstrap answer key 'commands' must be an object")
    if isinstance(answers.get("commands"), dict):
        errors.extend(
            f"unknown commands key: {key}" for key in sorted(set(answers["commands"]) - COMMAND_KEYS)
        )
        validate_string_values(answers["commands"], COMMAND_KEYS, "commands", errors)
        for key, command in answers["commands"].items():
            if isinstance(command, str):
                validate_shell_command(f"commands key '{key}'", command, errors)
                if context.mode == "minimal" and contract_model.is_deferred_value(command):
                    errors.append(
                        f"commands key '{key}' must be omitted in minimal mode when it is deferred; the structured deferral records the gap"
                    )
    if isinstance(answers.get("date"), str) and answers["date"].strip():
        try:
            date.fromisoformat(answers["date"].strip())
        except ValueError:
            errors.append(f"bootstrap answer key 'date' must be a valid ISO date: {answers['date']!r}")
    if "framework_verification_runner" in answers:
        errors.extend(
            contract_model.framework_verification_runner_errors(
                answers.get("framework_verification_runner"),
                "framework_verification_runner",
            )
        )


def validate_answer_collection_shapes(context: AnswerValidationContext) -> None:
    answers = context.answers
    errors = context.errors
    if "deliverables" in answers and not isinstance(answers["deliverables"], list):
        errors.append("bootstrap answer key 'deliverables' must be a list")
    if context.mode == "full" and isinstance(answers.get("deliverables"), list) and not answers["deliverables"]:
        errors.append("full bootstrap requires at least one deliverable with acceptance evidence; use minimal bootstrap for deferred deliverables")
    if "command_restrictions" in answers and not isinstance(answers["command_restrictions"], list):
        errors.append("bootstrap answer key 'command_restrictions' must be a list")
    if "auxiliary_tools" in answers and not isinstance(answers["auxiliary_tools"], list):
        errors.append("bootstrap answer key 'auxiliary_tools' must be a list")
    if "annexes" in answers and not isinstance(answers["annexes"], dict):
        errors.append("bootstrap answer key 'annexes' must be an object")
    if "automation_orders" in answers and not isinstance(answers["automation_orders"], dict):
        errors.append("bootstrap answer key 'automation_orders' must be an object")
    if "minimal_deferrals" in answers:
        if context.mode != "minimal":
            errors.append("minimal_deferrals may be used only when bootstrap_mode is minimal")
        validate_object_list(
            answers["minimal_deferrals"],
            "minimal_deferrals",
            MINIMAL_DEFERRAL_KEYS,
            MINIMAL_DEFERRAL_KEYS,
            errors,
            require_concrete_values=False,
        )
        seen_deferral_fields: set[str] = set()
        if isinstance(answers["minimal_deferrals"], list):
            for index, item in enumerate(answers["minimal_deferrals"], start=1):
                if not isinstance(item, dict):
                    continue
                for key in ("owner", "reason", "closure_boundary"):
                    value = item.get(key)
                    if (
                        isinstance(value, str)
                        and contract_model.minimal_deferral_value_is_absent_or_placeholder(
                            value
                        )
                    ):
                        errors.append(
                            f"minimal_deferrals item {index} key '{key}' must be "
                            "concrete, not absent or placeholder text"
                        )
                field = item.get("field")
                if isinstance(field, str):
                    if not field.strip():
                        errors.append(
                            f"minimal_deferrals item {index} key 'field' must not be empty"
                        )
                    else:
                        if field not in MINIMAL_DEFERRABLE_FIELDS:
                            errors.append(
                                f"minimal_deferrals item {index} field is not "
                                f"deferrable: {field}"
                            )
                        if field in seen_deferral_fields:
                            errors.append(
                                f"minimal_deferrals item {index} duplicates field: "
                                f"{field}"
                            )
                        seen_deferral_fields.add(field)
                boundary_type = item.get("boundary_type")
                if isinstance(boundary_type, str):
                    if boundary_type not in MINIMAL_DEFERRAL_BOUNDARY_TYPES:
                        errors.append(
                            "minimal_deferrals item "
                            f"{index} boundary_type must be one of: {', '.join(sorted(MINIMAL_DEFERRAL_BOUNDARY_TYPES))}"
                        )
                    else:
                        closure_boundary = item.get("closure_boundary")
                        if (
                            isinstance(closure_boundary, str)
                            and not contract_model.minimal_deferral_value_is_absent_or_placeholder(
                                closure_boundary
                            )
                        ):
                            boundary_error = contract_model.minimal_deferral_closure_boundary_error(
                                boundary_type,
                                closure_boundary,
                            )
                            if boundary_error is not None:
                                errors.append(
                                    f"minimal_deferrals item {index} closure_boundary {boundary_error}"
                                )


def validate_answer_relationships(
    context: AnswerValidationContext,
    *,
    automation_project_root: Path | None = None,
    automation_manifest_path: Path | None = None,
    require_existing_automation_project_root: bool = True,
) -> None:
    answers = context.answers
    errors = context.errors
    for spec in contract_model.ANSWER_FIELD_SPECS:
        if (
            spec.active_when is not None
            and spec.name in answers
            and answers.get(spec.active_when) is not True
        ):
            errors.append(
                f"bootstrap answer key '{spec.name}' requires {spec.active_when} to be true"
            )
    if answers.get("include_source_update") and not answers.get("include_source_packs"):
        errors.append("include_source_update requires include_source_packs because SOURCE_UPDATE.md references SOURCE_PACKS.md")
    shared_source_reference = str(
        answers.get("shared_framework_source_reference", "")
    ).strip()
    if shared_source_reference and contract_model.is_deferred_value(shared_source_reference):
        errors.append(
            "shared_framework_source_reference must be concrete; omit it to render none"
        )
    selected_security_policy = security_policy_file(answers)
    inline_security_terms = lines_for(answers.get("security_policy_terms"))
    if selected_security_policy == "inline in this SOW" and not inline_security_terms:
        errors.append(
            "security_policy_file 'inline in this SOW' requires at least one security_policy_terms entry"
        )
    if selected_security_policy != "inline in this SOW" and inline_security_terms:
        errors.append(
            "security_policy_terms may be provided only when security_policy_file is 'inline in this SOW'"
        )
    automation_orders = answers.get("automation_orders")
    if answers.get("include_automation_orders"):
        jobs = automation_orders.get("jobs") if isinstance(automation_orders, dict) else None
        if not isinstance(jobs, list) or not jobs:
            errors.append("include_automation_orders requires automation_orders.jobs with at least one concrete job")
        elif isinstance(jobs, list):
            for index, job in enumerate(jobs, start=1):
                if isinstance(job, dict):
                    validate_reserved_generated_text_values(
                        job,
                        frozenset({"objective"}),
                        f"automation_orders.jobs item {index}",
                        errors,
                    )
            if automation_project_root is None or automation_manifest_path is None:
                errors.append(
                    "automation_orders.jobs validation requires the selected project root and automation manifest path"
                )
                return
            preferred_backend = automation_preferred_backend(answers)
            manifest = {
                "schema_version": automation_orders_lint.SCHEMA_VERSION,
                "preferred_backend": preferred_backend,
                "jobs": jobs,
            }
            manifest_errors, _manifest_warnings = automation_orders_lint.validate_manifest(
                manifest,
                project_root=automation_project_root,
                manifest_path=automation_manifest_path,
                require_existing_project_root=require_existing_automation_project_root,
            )
            if automation_orders_lint.BACKEND_RE.fullmatch(preferred_backend) is None:
                manifest_errors = [
                    error
                    for error in manifest_errors
                    if not error.startswith("preferred_backend ")
                ]
            errors.extend(f"automation_orders.jobs: {error}" for error in manifest_errors)
            if preferred_backend == "cron":
                cron_errors, _cron_warnings = automation_orders_lint.validate_manifest(
                    manifest,
                    target="cron",
                    project_root=automation_project_root,
                    manifest_path=automation_manifest_path,
                    require_existing_project_root=require_existing_automation_project_root,
                )
                errors.extend(
                    f"automation_orders.jobs: {error}"
                    for error in cron_errors
                    if error not in manifest_errors
                )


def validate_arbitration_panel(answers: dict, errors: list[str]) -> None:
    if "arbitration_panel" in answers:
        panel = answers["arbitration_panel"]
        if not isinstance(panel, dict):
            errors.append("bootstrap answer key 'arbitration_panel' must be an object")
        else:
            errors.extend(
                f"missing arbitration_panel key: {key}"
                for key in sorted(PANEL_CONFIG_KEYS - set(panel))
            )
            errors.extend(
                f"unknown arbitration_panel key: {key}"
                for key in sorted(set(panel) - PANEL_CONFIG_KEYS)
            )
            validate_string_values(
                panel,
                PANEL_CONFIG_KEYS - {"seats"},
                "arbitration_panel",
                errors,
            )
            for key in sorted((PANEL_CONFIG_KEYS - {"seats"}) & set(panel)):
                if isinstance(panel[key], str) and not panel[key].strip():
                    errors.append(f"arbitration_panel key '{key}' must not be empty")
            validate_object_list(
                panel.get("seats"),
                "arbitration_panel.seats",
                PANEL_SEAT_KEYS,
                PANEL_SEAT_KEYS,
                errors,
            )
            if isinstance(panel.get("seats"), list) and not panel["seats"]:
                errors.append("arbitration_panel.seats must contain at least one configured seat")


def validate_deliverables(answers: dict, errors: list[str]) -> None:
    if isinstance(answers.get("deliverables"), list):
        for index, item in enumerate(answers["deliverables"], start=1):
            if not isinstance(item, dict):
                errors.append(f"deliverable {index} must be an object")
                continue
            errors.extend(
                f"missing deliverable key in item {index}: {key}"
                for key in sorted(DELIVERABLE_KEYS - set(item))
            )
            errors.extend(
                f"unknown deliverable key in item {index}: {key}"
                for key in sorted(set(item) - DELIVERABLE_KEYS)
            )
            validate_string_values(item, DELIVERABLE_KEYS, f"deliverable {index}", errors)


def validate_command_restrictions(answers: dict, errors: list[str]) -> None:
    if isinstance(answers.get("command_restrictions"), list):
        for index, item in enumerate(answers["command_restrictions"], start=1):
            if not isinstance(item, dict):
                errors.append(f"command restriction {index} must be an object")
                continue
            errors.extend(
                f"missing command restriction key in item {index}: {key}"
                for key in sorted(RESTRICTION_KEYS - set(item))
            )
            errors.extend(
                f"unknown command restriction key in item {index}: {key}"
                for key in sorted(set(item) - RESTRICTION_KEYS)
            )
            validate_string_values(item, RESTRICTION_KEYS, f"command restriction {index}", errors)
            for key in sorted(RESTRICTION_KEYS & set(item)):
                value = item[key]
                if isinstance(value, str) and (
                    not value.strip() or contract_model.is_deferred_value(value)
                ):
                    errors.append(
                        f"command restriction {index} key '{key}' must be concrete; omit the optional restriction until it is known"
                    )
        errors.extend(
            command_restriction_identity_errors(answers["command_restrictions"])
        )
        errors.extend(
            _declared_delimiter_errors(
                answers["command_restrictions"],
                collection="command_restrictions",
                item_label="command restriction",
            )
        )


def validate_auxiliary_tools(answers: dict, errors: list[str]) -> None:
    if isinstance(answers.get("auxiliary_tools"), list):
        for index, item in enumerate(answers["auxiliary_tools"], start=1):
            if not isinstance(item, dict):
                errors.append(f"auxiliary tool {index} must be an object")
                continue
            errors.extend(
                f"missing auxiliary tool key in item {index}: {key}"
                for key in sorted(REQUIRED_AUXILIARY_TOOL_KEYS - set(item))
            )
            errors.extend(
                f"unknown auxiliary tool key in item {index}: {key}"
                for key in sorted(set(item) - AUXILIARY_TOOL_KEYS)
            )
            validate_string_values(item, AUXILIARY_TOOL_KEYS, f"auxiliary tool {index}", errors)
            for key in sorted(REQUIRED_AUXILIARY_TOOL_KEYS & set(item)):
                value = item[key]
                if isinstance(value, str) and (
                    not value.strip() or contract_model.is_deferred_value(value)
                ):
                    errors.append(
                        f"auxiliary tool {index} key '{key}' must be concrete; omit the optional tool until it is known"
                    )
            missing_facts = contract_model.missing_auxiliary_tool_fact_groups(item)
            if missing_facts:
                errors.append(
                    f"auxiliary tool {index} is missing protocol-neutral integration facts: "
                    + ", ".join(missing_facts)
                )
            errors.extend(
                f"auxiliary tool {index} {error}"
                for error in contract_model.auxiliary_tool_control_errors(item)
            )
        errors.extend(auxiliary_tool_identity_errors(answers["auxiliary_tools"]))
        errors.extend(
            _declared_delimiter_errors(
                answers["auxiliary_tools"],
                collection="auxiliary_tools",
                item_label="auxiliary tool",
            )
        )


def validate_remaining_structured_answers(
    context: AnswerValidationContext,
) -> None:
    answers = context.answers
    errors = context.errors
    if "workflows" in answers:
        validate_object_list(answers["workflows"], "workflows", WORKFLOW_REQUIRED_KEYS, WORKFLOW_KEYS, errors)
        errors.extend(workflow_identity_errors(answers["workflows"]))
        errors.extend(
            _declared_delimiter_errors(
                answers["workflows"],
                collection="workflows",
                item_label="workflows item",
            )
        )
    validate_deliverables(answers, errors)
    validate_command_restrictions(answers, errors)
    validate_auxiliary_tools(answers, errors)
    if isinstance(answers.get("annexes"), dict):
        if "security" in answers["annexes"]:
            errors.append(
                "annexes.security is not accepted; select the sole security-policy owner "
                "with security_policy_file"
            )
        errors.extend(
            f"unknown annexes key: {key}"
            for key in sorted(set(answers["annexes"]) - ANNEX_KEYS - {"security"})
        )
        validate_string_values(answers["annexes"], ANNEX_KEYS, "annexes", errors)
        for key in sorted(set(answers["annexes"]) & ANNEX_KEYS):
            value = answers["annexes"][key]
            if not isinstance(value, str):
                continue
            normalized = value.strip().casefold()
            if (
                not normalized
                or normalized == "none"
                or normalized == "inline"
                or normalized.startswith("inline:")
            ):
                errors.append(
                    f"annexes key '{key}' must name an existing project-relative file; "
                    "omit the key when the annex is unused"
                )
            else:
                errors.extend(
                    safe_paths.project_relative_reference_errors(
                        value,
                        f"annexes key '{key}'",
                    )
                )
    if isinstance(answers.get("automation_orders"), dict):
        errors.extend(
            f"unknown automation_orders key: {key}"
            for key in sorted(set(answers["automation_orders"]) - AUTOMATION_ORDER_KEYS)
        )
        preferred_backend = answers["automation_orders"].get("preferred_backend")
        if (
            "preferred_backend" in answers["automation_orders"]
            and (
                not isinstance(preferred_backend, str)
                or automation_orders_lint.BACKEND_RE.fullmatch(preferred_backend)
                is None
            )
        ):
            errors.append(
                "automation_orders.preferred_backend must be one lowercase safe slug"
            )
        if "jobs" in answers["automation_orders"] and not isinstance(answers["automation_orders"]["jobs"], list):
            errors.append("automation_orders.jobs must be a list")


def validate_answers(
    answers: object,
    *,
    automation_project_root: Path | None = None,
    automation_manifest_path: Path | None = None,
    require_existing_automation_project_root: bool = True,
) -> list[str]:
    if not isinstance(answers, dict):
        return ["bootstrap answers must be a JSON object"]
    context = AnswerValidationContext(
        answers=answers,
        mode=bootstrap_mode(answers),
        errors=[],
    )
    validate_answer_scalars(context)
    validate_answer_commands(context)
    validate_answer_collection_shapes(context)
    validate_answer_relationships(
        context,
        automation_project_root=automation_project_root,
        automation_manifest_path=automation_manifest_path,
        require_existing_automation_project_root=require_existing_automation_project_root,
    )
    validate_arbitration_panel(answers, context.errors)
    validate_remaining_structured_answers(context)
    context.errors.extend(minimal_deferral_resolution_errors(answers))
    if context.mode == "full":
        context.errors.extend(full_mode_semantic_errors(answers))
    return context.errors


def full_mode_semantic_errors(answers: dict) -> list[str]:
    errors: list[str] = []
    for key in ("architecture", "language_runtime_standards", "tech_stack"):
        value = str(answers.get(key, "")).strip()
        if not value or contract_model.is_deferred_value(value):
            errors.append(
                f"full bootstrap requires a concrete {key} value; use minimal bootstrap for deferred facts"
            )
    for key in ("recitals", "in_scope", "out_of_scope"):
        values = lines_for(answers.get(key))
        if not values or any(contract_model.is_deferred_value(value) for value in values):
            errors.append(
                f"full bootstrap requires concrete {key} entries; use minimal bootstrap for deferred facts"
            )
    raw_commands = answers.get("commands")
    command_block = raw_commands if isinstance(raw_commands, dict) else {}
    for key in sorted(COMMAND_KEYS):
        if key in command_block:
            value = str(command_block.get(key, "")).strip()
        else:
            errors.append(
                f"full bootstrap requires explicit commands.{key}; use 'none' when not applicable"
            )
            continue
        if not value or contract_model.is_deferred_value(value):
            errors.append(
                f"full bootstrap requires a concrete commands.{key} value; use 'none' when not applicable"
            )
    deliverables = answers.get("deliverables")
    if isinstance(deliverables, list):
        for index, item in enumerate(deliverables, start=1):
            if not isinstance(item, dict):
                continue
            for key in DELIVERABLE_REQUIRED_KEYS:
                value = str(item.get(key, "")).strip()
                if not value or contract_model.is_deferred_value(value):
                    errors.append(
                        "full bootstrap deliverable "
                        f"{index} requires concrete {key}; use minimal bootstrap for deferred acceptance evidence"
                    )
    return errors


def lines_for(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [line.strip() for line in value.splitlines() if line.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()]


def field(data: dict, key: str, default: str = "TBD") -> str:
    value = str(data.get(key, "")).strip()
    return value or default


def render_date(answers: dict) -> str:
    value = str(answers.get("date", "")).strip()
    if value:
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError as exc:
            raise SystemExit(f"date must be YYYY-MM-DD: {exc}") from exc
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch:
        try:
            return datetime.fromtimestamp(int(epoch), timezone.utc).date().isoformat()
        except (ValueError, OverflowError, OSError) as exc:
            raise SystemExit(
                "SOURCE_DATE_EPOCH must be a supported integer Unix timestamp"
            ) from exc
    return date.today().isoformat()


def deliverables_need_deferral(value: object) -> bool:
    if not isinstance(value, list) or not value:
        return True
    for item in value:
        if not isinstance(item, dict):
            return True
        for key in DELIVERABLE_REQUIRED_KEYS:
            raw_field_value = item.get(key)
            if not isinstance(raw_field_value, str):
                return True
            field_value = raw_field_value.strip()
            if not field_value or contract_model.is_deferred_value(field_value):
                return True
    return False


def runtime_deferred_value(answers: dict, key: str, minimal_text: str) -> str:
    value = str(answers.get(key, "")).strip()
    if bootstrap_mode(answers) == "minimal" and (
        not value or contract_model.is_deferred_value(value)
    ):
        return minimal_text
    return value or "TBD"


def runtime_scope_lines(answers: dict, key: str, minimal_text: str) -> list[str]:
    values = lines_for(answers.get(key))
    if bootstrap_mode(answers) == "minimal":
        concrete = [
            value for value in values
            if not contract_model.is_deferred_value(value)
        ]
        if len(concrete) != len(values) or not values:
            return bullets([*concrete, minimal_text])
    if values:
        return bullets(values)
    return []


def runtime_deliverable_value(value: object, minimal_text: str, mode: str) -> str:
    text = str(value or "").strip()
    if mode == "minimal" and (
        not text or contract_model.is_deferred_value(text)
    ):
        return minimal_text
    return text or "TBD"


def present_value(value: str) -> bool:
    return value.casefold() not in {"", "none", "tbd"}


def normalized_commands(answers: dict) -> dict[str, object]:
    raw_commands = answers.get("commands", {})
    return dict(raw_commands) if isinstance(raw_commands, dict) else {}


def effective_command(
    command_block: dict[str, object],
    command_key: str,
    mode: str,
) -> str:
    raw_value = command_block.get(command_key)
    value = str(raw_value or "").strip()
    if mode == "minimal" and (
        command_key not in command_block
        or not value
        or contract_model.is_deferred_value(value)
    ):
        return MINIMAL_COMMAND_DEFERRAL
    return value or "none"


def bullets(items: list[str]) -> list[str]:
    return [f"- {item}" for item in items]


def numbered(items: list[str]) -> list[str]:
    return [f"{index}. {item}" for index, item in enumerate(items, start=1)]


def add_section(lines: list[str], title: str, body: list[str]) -> None:
    if not body:
        return
    lines.extend([title, "", *body, ""])


def dedupe(items: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        normalized = item.casefold()
        if normalized not in seen:
            seen.add(normalized)
            result.append(item)
    return result


def uses_python(answers: dict) -> bool:
    haystack = " ".join(
        str(answers.get(key, ""))
        for key in ("language_runtime_standards", "package_manager", "tech_stack")
    ).casefold()
    return "python" in haystack or "uv" in haystack


def language_rules(answers: dict) -> list[str]:
    rules = lines_for(answers.get("language_specific_rules"))
    if uses_python(answers):
        rules.append(contract_model.PYTHON_LANGUAGE_POLICY)
    return dedupe(rules)


def command_values(answers: dict) -> dict[str, str]:
    command_block = normalized_commands(answers)
    mode = bootstrap_mode(answers)
    return {
        spec.deferral_field: effective_command(
            command_block,
            spec.answer_key,
            mode,
        )
        for spec in contract_model.COMMAND_SPECS
    }


def minimal_deferral_record(field_name: str) -> dict[str, str]:
    return {
        "field": field_name,
        "owner": contract_model.MINIMAL_DEFERRAL_DEFAULT_OWNER,
        "reason": contract_model.MINIMAL_DEFERRAL_DEFAULT_REASON,
        "boundary_type": contract_model.MINIMAL_DEFERRAL_DEFAULT_BOUNDARY_TYPE,
        "closure_boundary": contract_model.MINIMAL_DEFERRAL_CLOSURE_TEMPLATE.format(
            field_name=field_name
        ),
    }


def minimal_deferral_line(record: dict[str, str]) -> str:
    return contract_model.render_structured_record("minimal_deferrals", record)


def required_minimal_deferral_fields(answers: dict) -> set[str]:
    if bootstrap_mode(answers) != "minimal":
        return set()
    required: set[str] = set()
    scalar_fields = {
        "Tech stack": "tech_stack",
        "Architecture": "architecture",
        "Language/Runtime Standards": "language_runtime_standards",
    }
    for label, key in scalar_fields.items():
        raw_value = answers.get(key)
        if not isinstance(raw_value, str):
            required.add(label)
            continue
        value = raw_value.strip()
        if not value or contract_model.is_deferred_value(value):
            required.add(label)
    raw_recitals = answers.get("recitals")
    valid_recitals_shape = isinstance(raw_recitals, str) or (
        isinstance(raw_recitals, list)
        and all(isinstance(item, str) for item in raw_recitals)
    )
    recitals = lines_for(raw_recitals) if valid_recitals_shape else []
    if not recitals or any(
        contract_model.is_deferred_value(value) for value in recitals
    ):
        required.add("Recitals")
    for label, key in (("In scope", "in_scope"), ("Out of scope", "out_of_scope")):
        raw_lines = answers.get(key)
        valid_shape = isinstance(raw_lines, str) or (
            isinstance(raw_lines, list)
            and all(isinstance(item, str) for item in raw_lines)
        )
        values = lines_for(raw_lines) if valid_shape else []
        if not values or any(contract_model.is_deferred_value(value) for value in values):
            required.add(label)
    if deliverables_need_deferral(answers.get("deliverables")):
        required.add("Deliverables and Acceptance Evidence")
    raw_commands = answers.get("commands")
    commands = raw_commands if isinstance(raw_commands, dict) else {}
    for spec in contract_model.COMMAND_SPECS:
        value = commands.get(spec.answer_key)
        if (
            not isinstance(value, str)
            or not value.strip()
            or contract_model.is_deferred_value(value)
        ):
            required.add(spec.deferral_field)
    return required


def minimal_deferral_resolution_errors(answers: dict) -> list[str]:
    explicit = answers.get("minimal_deferrals")
    if bootstrap_mode(answers) != "minimal" or not isinstance(explicit, list):
        return []
    required_fields = required_minimal_deferral_fields(answers)
    errors: list[str] = []
    for index, item in enumerate(explicit, start=1):
        if not isinstance(item, dict):
            continue
        field_name = item.get("field")
        if (
            isinstance(field_name, str)
            and field_name in MINIMAL_DEFERRABLE_FIELDS
            and field_name not in required_fields
        ):
            errors.append(
                f"minimal_deferrals item {index} defers resolved canonical field: {field_name}"
            )
    return errors


def minimal_deferrals(answers: dict) -> list[str]:
    if bootstrap_mode(answers) != "minimal":
        return []
    records_by_field: dict[str, dict[str, str]] = {}
    explicit = answers.get("minimal_deferrals")
    if isinstance(explicit, list):
        for item in explicit:
            if not isinstance(item, dict):
                continue
            field = item.get("field")
            if not isinstance(field, str) or field not in MINIMAL_DEFERRABLE_FIELDS:
                continue
            records_by_field[field] = {
                "field": field,
                "owner": str(item.get("owner", "")).strip(),
                "reason": str(item.get("reason", "")).strip(),
                "boundary_type": str(item.get("boundary_type", "")).strip(),
                "closure_boundary": str(item.get("closure_boundary", "")).strip(),
            }
    for label in required_minimal_deferral_fields(answers):
        records_by_field.setdefault(label, minimal_deferral_record(label))
    return [minimal_deferral_line(records_by_field[field]) for field in sorted(records_by_field)]


def absolute_path_warnings(answers: dict) -> list[str]:
    warnings: list[str] = []
    commands_to_check = list(command_values(answers).items())
    runner = str(answers.get("framework_verification_runner", "")).strip()
    if runner:
        commands_to_check.append(("Framework Verification Runner", runner))
    for label, command in commands_to_check:
        if command.lower() in {"", "none", "tbd"}:
            continue
        try:
            tokens = shlex.split(command)
        except ValueError as exc:
            warnings.append(f"{label} command is not shell-parseable: {exc}")
            continue
        for token in tokens:
            if token_has_absolute_path(token):
                warnings.append(
                    f"host-specific absolute path in {label}: {command}. Prefer repo-local or relative commands when possible."
                )
                break
    for label, text in command_like_text_values(answers):
        if safe_paths.contains_absolute_path(text):
            warnings.append(
                f"host-specific absolute path in {label}: {text}. Prefer repo-local or relative commands when possible."
            )
    return warnings


def token_has_absolute_path(token: str) -> bool:
    return safe_paths.contains_absolute_path(token)


def command_like_text_values(answers: dict) -> list[tuple[str, str]]:
    values: list[tuple[str, str]] = []
    for index, item in enumerate(answers.get("deliverables", []), start=1):
        if isinstance(item, dict):
            test = str(item.get("test", "")).strip()
            if test:
                values.append((f"deliverables[{index}].test", test))
    for index, item in enumerate(lines_for(answers.get("verification_profiles")), start=1):
        values.append((f"verification_profiles[{index}]", item))
    return values


def answer_file_warnings(answers_path: Path, project_root: Path) -> list[str]:
    warnings: list[str] = []
    try:
        answers_path.relative_to(project_root)
    except ValueError:
        pass
    else:
        warnings.append(
            f"bootstrap answers file is inside the target project root: {answers_path}. Keep bootstrap answer files temporary and remove them from the project root after setup."
        )
    example_path = (REPO_ROOT / "examples" / "project_bootstrap_answers.example.json").resolve(strict=False)
    if answers_path.resolve(strict=False) == example_path:
        warnings.append(
            f"bootstrap answers file is the framework minimal example file: {answers_path}. Use examples/project_bootstrap_answers.schema.json for the closed field contract, and create a separate temporary answers file with confirmed project values before writing."
        )
    else:
        try:
            answers_path.relative_to(REPO_ROOT)
        except ValueError:
            pass
        else:
            warnings.append(
                f"bootstrap answers file is inside the framework root: {answers_path}. Keep bootstrap answer files temporary and outside both framework and target repositories."
            )
    return warnings


def parent_context_warnings(project_root: Path, framework_root: Path) -> list[str]:
    warnings: list[str] = []
    for parent in project_root.parents:
        if parent == framework_root:
            continue
        if (parent / "STATEMENT_OF_WORK.md").exists() or (parent / "AGENT_PROJECT.md").exists():
            warnings.append(
                f"target project root is nested inside existing project-contract root: {parent}. Confirm this is an intended nested project before writing setup files."
            )
            break
    return warnings


def resolve_contract_root(
    project_root: Path,
    raw_contract_root: str | None,
) -> tuple[Path, str, list[str]]:
    if raw_contract_root is None:
        return project_root, ".", []
    try:
        relative = safe_paths.normalize_repo_relative_path(
            raw_contract_root,
            project_root,
            description="contract root",
        )
    except ValueError as exc:
        return project_root, raw_contract_root, [str(exc)]
    reference_errors = safe_paths.project_relative_reference_errors(
        relative,
        "contract root",
    )
    contract_root = (project_root / relative).resolve(strict=False)
    errors = safe_paths.output_path_errors(
        project_root / relative,
        project_root,
        "target project root",
    )
    errors.extend(reference_errors)
    if contract_root.exists() and not contract_root.is_dir():
        errors.append(f"contract root must be a directory: {contract_root}")
    return contract_root, relative, errors


_INSTRUCTION_STRUCTURE_LINE_RE = re.compile(
    r"(?:#{1,6}[ \t]+.+|</?[A-Za-z][A-Za-z0-9_.:-]*(?:[ \t]+[^<>]+)?/?>)"
)


def _normalized_operative_paragraphs(text: str) -> tuple[str, ...]:
    """Return exact active prose paragraphs with wrapping normalized.

    Fenced content and HTML comments are already excluded by the shared
    Markdown visibility parser. Headings and repository-owned XML-like section
    tags delimit prose but are not themselves executable directives.
    """

    paragraphs: list[str] = []
    lines: list[str] = []

    def finish() -> None:
        if lines:
            paragraphs.append(" ".join(" ".join(lines).split()))
            lines.clear()

    for _line_number, raw_line in markdown_structure.operative_lines(text):
        line = raw_line.strip()
        if not line or _INSTRUCTION_STRUCTURE_LINE_RE.fullmatch(line):
            finish()
            continue
        lines.append(line)
    finish()
    return tuple(paragraphs)


def project_layout_errors(
    project_root: Path,
    contract_root: Path,
    contract_root_ref: str,
    framework_root: Path,
    project_kind: str,
) -> list[str]:
    try:
        policy = contract_model.project_layout_policy(project_kind)
    except ValueError as exc:
        return [str(exc)]
    errors: list[str] = []
    if policy.forbid_target_within_framework_root and safe_paths.path_within_root(
        project_root,
        framework_root,
    ):
        relation = "is" if project_root == framework_root else "is nested inside"
        errors.append(
            f"target project root {relation} the selected framework checkout: "
            f"{framework_root}. Select a separate downstream project root."
        )
    if policy.require_framework_root_target and project_root != framework_root:
        errors.append(
            f"{policy.kind} project kind requires the selected framework root as --project-root"
        )
    missing_markers = [
        marker
        for marker in policy.required_framework_markers
        if not (project_root / marker).exists()
    ]
    if policy.require_framework_root_target and missing_markers:
        errors.append(
            f"{policy.kind} project root is missing required framework markers: "
            + ", ".join(missing_markers)
        )
    if policy.require_nested_contract_root and (
        contract_root == project_root or contract_root_ref == "."
    ):
        errors.append(
            f"{policy.kind} project kind requires --contract-root to be a strict descendant of the project root"
        )
    if policy.require_nested_contract_root and not safe_paths.path_within_root(
        contract_root,
        project_root,
    ):
        errors.append(f"{policy.kind} contract root must stay inside the project root")
    if (
        policy.require_non_product_contract_root
        and contract_root_ref != "."
        and product_manifest.is_product_location(contract_root_ref)
    ):
        errors.append(
            f"{policy.kind} contract root must be excluded by the product manifest"
        )
    for requirement in policy.instruction_surfaces:
        entrypoint = project_root / requirement.relative_path
        description = requirement.description
        entrypoint_errors = safe_paths.bounded_input_errors(
            entrypoint,
            project_root,
            description=f"{description} input",
        )
        errors.extend(entrypoint_errors)
        if entrypoint_errors:
            continue
        if not entrypoint.is_file() or entrypoint.is_symlink():
            errors.append(
                f"{policy.kind} project kind requires an existing regular root "
                + entrypoint.name
            )
            continue
        try:
            entrypoint_bytes = safe_paths.read_regular_file_bytes(
                entrypoint,
                description=f"{description} input",
            )
        except (OSError, ValueError) as exc:
            errors.append(f"{description} could not be read safely: {exc}")
            continue
        try:
            entrypoint_text = entrypoint_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            errors.append(f"{description} must be valid UTF-8: {exc}")
            continue
        operative_paragraphs = _normalized_operative_paragraphs(entrypoint_text)
        required_index = 0
        for directive in requirement.ordered_directives:
            required_paragraph = directive.exact_normalized_paragraph.replace(
                "{contract_root}",
                contract_root_ref,
            )
            try:
                paragraph_index = operative_paragraphs.index(required_paragraph)
            except ValueError:
                errors.append(
                    f"{description} is missing the exact affirmative directive "
                    f"for {directive.description}: {required_paragraph}"
                )
                continue
            if paragraph_index < required_index:
                errors.append(
                    f"{description} places the exact affirmative directive out "
                    f"of policy order for {directive.description}: "
                    + required_paragraph
                )
                continue
            required_index = paragraph_index + 1
    return errors


def framework_reference_warnings(framework_ref: str) -> list[str]:
    if safe_paths.contains_local_absolute_path(framework_ref):
        return [
            "generated framework reference is host-specific. Use --framework-ref with a repo-relative path, approved environment variable, or stable mounted path before committing public/shared project files."
        ]
    return []


def framework_reference_binding(
    framework_ref: str,
    project_root: Path,
    framework_root: Path = REPO_ROOT,
) -> tuple[str, list[str], list[str]]:
    """Verify that a concrete rendered reference names this generator checkout."""

    resolved = safe_paths.resolve_framework_reference(framework_ref, project_root)
    if resolved is None:
        return (
            "unresolved",
            [],
            [
                "framework reference cannot be resolved in the current environment; "
                "the generated instance records this limitation and refresh must "
                "verify the binding before mutation"
            ],
        )
    if resolved != framework_root.resolve(strict=False):
        return (
            "verified",
            [
                "framework reference resolves to a different checkout than the "
                f"generator: {resolved} != {framework_root.resolve(strict=False)}"
            ],
            [],
        )
    return "verified", [], []


def project_file_reference_errors(
    project_root: Path,
    references: list[tuple[str, str]],
) -> list[str]:
    errors: list[str] = []
    for label, raw_value in references:
        value = raw_value.strip()
        if not value:
            continue
        try:
            candidate = safe_paths.safe_relative_child(
                project_root,
                Path(value),
                description=f"{label} reference",
            )
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if not candidate.is_file():
            errors.append(
                f"{label} references missing project file: {value}. "
                "Create and review the file first, or omit or change the owning configuration."
            )
    return errors


def project_module_references(answers: dict) -> list[tuple[str, str]]:
    """Return the project-root-relative files incorporated as active modules."""

    references: list[tuple[str, str]] = []
    annexes = answers.get("annexes", {})
    if isinstance(annexes, dict):
        for key in ANNEX_KEYS_IN_ORDER:
            value = annexes.get(key)
            if isinstance(value, str) and value.strip():
                references.append((ANNEX_LABELS[key], value.strip()))
    if security_policy_file(answers) == "project SECURITY.md":
        references.append(
            (
                SECURITY_POLICY_ANNEX_LABEL,
                contract_model.SECURITY_POLICY_ANNEX_REFERENCE,
            )
        )
    return references


def referenced_project_file_errors(answers: dict, project_root: Path) -> list[str]:
    return project_file_reference_errors(
        project_root,
        project_module_references(answers),
    )


def optional_state_names(answers: dict) -> list[str]:
    return [
        name
        for flag, name in OPTIONAL_STATE_FLAGS
        if answers.get(flag)
    ]


def immutable_optional_state_names(answers: dict) -> list[str]:
    return [
        name
        for name in optional_state_names(answers)
        if name in contract_model.optional_state_filenames("immutable")
    ]


def _registered_runtime_target_labels(
    framework_root: Path,
) -> dict[str, tuple[str, ...]]:
    """Return every registry-owned downstream runtime target and its owners."""

    registry = integration_registry.load_registry(framework_root)
    labels: dict[str, list[str]] = {}
    for family, config in registry["families"].items():
        entrypoint = config["entrypoint"]
        labels.setdefault(str(entrypoint["output"]), []).append(
            f"{family} entrypoint"
        )
        for wrapper_id, wrapper in config["wrappers"].items():
            labels.setdefault(str(wrapper["repo_output"]), []).append(
                f"{family} wrapper {wrapper_id}"
            )
    return {
        path: tuple(sorted(owners))
        for path, owners in sorted(labels.items())
    }


def _read_existing_surface_candidate(
    relative_path: str,
    project_root: Path,
    *,
    label: str,
) -> tuple[bytes | None, str | None]:
    """Read one exact registry target with stable parent and name bindings."""

    capability_errors = _generated_surface_discovery_capability_errors()
    if capability_errors:
        return None, "; ".join(capability_errors)
    relative = Path(relative_path)
    directory_flags = (
        os.O_RDONLY
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
    )
    descriptors: list[int] = []
    bindings: list[tuple[int, str, tuple[int, int, int]]] = []
    absent_bindings: list[tuple[int, str]] = []
    raw: bytes | None = None
    diagnostic: str | None = None
    propagating: BaseException | None = None
    try:
        descriptors.append(os.open(project_root, directory_flags))
        root_identity = _discovery_node_identity(os.fstat(descriptors[0]))
        missing = False
        for component in relative.parts[:-1]:
            parent_descriptor = descriptors[-1]
            try:
                descriptor = os.open(
                    component,
                    directory_flags,
                    dir_fd=parent_descriptor,
                )
            except FileNotFoundError:
                absent_bindings.append((parent_descriptor, component))
                missing = True
                break
            descriptors.append(descriptor)
            opened_identity = _discovery_node_identity(os.fstat(descriptor))
            current_identity = _discovery_node_identity(
                os.stat(
                    component,
                    dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
            )
            if current_identity != opened_identity:
                raise ValueError(
                    "registered runtime target parent changed during discovery: "
                    + relative.as_posix()
                )
            bindings.append(
                (parent_descriptor, component, opened_identity)
            )
        if not missing:
            parent_descriptor = descriptors[-1]
            try:
                observed = os.stat(
                    relative.name,
                    dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                absent_bindings.append((parent_descriptor, relative.name))
                missing = True
            else:
                raw = _read_bound_surface_candidate(
                    parent_descriptor,
                    relative.name,
                    relative,
                    observed,
                )
        for parent_descriptor, component, expected_identity in bindings:
            current_identity = _discovery_node_identity(
                os.stat(
                    component,
                    dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
            )
            if current_identity != expected_identity:
                raise ValueError(
                    "registered runtime target parent changed during discovery: "
                    + relative.as_posix()
                )
        for parent_descriptor, component in absent_bindings:
            try:
                os.stat(
                    component,
                    dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                continue
            raise ValueError(
                "registered runtime target appeared during discovery: "
                + relative.as_posix()
            )
        current_root_identity = _discovery_node_identity(
            os.stat(project_root, follow_symlinks=False)
        )
        if current_root_identity != root_identity:
            raise ValueError(
                "target project root changed during registered-target discovery"
            )
    except (OSError, ValueError) as exc:
        diagnostic = (
            f"could not safely inspect {label} {relative.as_posix()}: {exc}"
        )
        raw = None
    except BaseException as exc:
        propagating = exc
        raise
    finally:
        cleanup = tuple(
            (
                f"{label} retained directory descriptor {index}",
                lambda descriptor=descriptor: os.close(descriptor),
            )
            for index, descriptor in enumerate(reversed(descriptors), start=1)
        )
        if propagating is not None:
            resource_cleanup.cleanup_actions(cleanup, primary=propagating)
        else:
            try:
                resource_cleanup.cleanup_actions(cleanup)
            except OSError as exc:
                raw = None
                cleanup_diagnostic = f"descriptor cleanup failed: {exc}"
                diagnostic = (
                    f"{diagnostic}; {cleanup_diagnostic}"
                    if diagnostic is not None
                    else (
                        f"could not safely inspect {label} {relative.as_posix()}: "
                        + cleanup_diagnostic
                    )
                )
    return raw, diagnostic


def _is_registered_mpa_runtime_surface(raw: bytes) -> bool:
    """Recognize only framework-owned structure at an exact registry target."""

    return any(
        marker in raw
        for marker in (
            b"<!-- mpa-entrypoint-contract:",
            b"<!-- mpa-wrapper-contract:",
            b"Master Prompt Agreement",
        )
    )


def _is_generated_contract_or_identity_surface(name: str, raw: bytes) -> bool:
    """Recognize reserved identity, contract, or marked project-state surfaces."""

    if name in {project_input.INPUT_NAME, INSTANCE_MANIFEST}:
        return True
    if name in {"AGENT_PROJECT.md", "STATEMENT_OF_WORK.md"}:
        return (
            f"<!-- {contract_model.CONTRACT_FORMAT_MARKER_KEY}:".encode("utf-8")
            in raw
        )
    if name in GENERATED_STATE_BASENAMES:
        return project_state_identity.has_generated_state_origin(name, raw)
    return False


def _stable_discovery_metadata(metadata: os.stat_result) -> tuple[int, ...]:
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


def _discovery_node_identity(metadata: os.stat_result) -> tuple[int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        stat.S_IFMT(metadata.st_mode),
    )


def _generated_surface_discovery_capability_errors() -> list[str]:
    if (
        not getattr(os, "O_DIRECTORY", 0)
        or not getattr(os, "O_NOFOLLOW", 0)
        or os.open not in getattr(os, "supports_dir_fd", set())
        or os.stat not in getattr(os, "supports_dir_fd", set())
        or os.stat not in getattr(os, "supports_follow_symlinks", set())
        or os.scandir not in getattr(os, "supports_fd", set())
    ):
        return [
            "existing-surface discovery requires descriptor-relative no-follow "
            "directory traversal"
        ]
    return []


def _read_bound_surface_candidate(
    parent_descriptor: int,
    name: str,
    relative_path: Path,
    observed: os.stat_result,
    *,
    max_bytes: int = GENERATED_SURFACE_DISCOVERY_MAX_BYTES,
) -> bytes:
    """Read a candidate and prove its observed parent/name binding stayed current."""

    if not stat.S_ISREG(observed.st_mode):
        raise ValueError(
            "generated-surface candidate must be a regular non-link file: "
            + relative_path.as_posix()
        )
    if observed.st_nlink != 1:
        raise ValueError(
            "generated-surface candidate must have exactly one hard link: "
            + relative_path.as_posix()
        )
    if observed.st_size > max_bytes:
        raise ValueError(
            "generated-surface candidate exceeds its byte bound of "
            f"{max_bytes}: {relative_path.as_posix()}"
        )
    file_flags = (
        os.O_RDONLY
        | os.O_NOFOLLOW
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    descriptor: int | None = None
    try:
        descriptor = os.open(
            name,
            file_flags,
            dir_fd=parent_descriptor,
        )
        opened = os.fstat(descriptor)
        if _stable_discovery_metadata(opened) != _stable_discovery_metadata(
            observed
        ):
            raise ValueError(
                "generated-surface candidate changed while it was opened: "
                + relative_path.as_posix()
            )
        raw = bytearray()
        while True:
            chunk = os.read(descriptor, 64 * 1024)
            if not chunk:
                break
            raw.extend(chunk)
            if len(raw) > max_bytes:
                raise ValueError(
                    "generated-surface candidate exceeds its byte bound of "
                    f"{max_bytes}: "
                    + relative_path.as_posix()
                )
        final = os.fstat(descriptor)
        current = os.stat(
            name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        if (
            _stable_discovery_metadata(final)
            != _stable_discovery_metadata(opened)
            or _stable_discovery_metadata(current)
            != _stable_discovery_metadata(opened)
            or len(raw) != final.st_size
        ):
            raise ValueError(
                "generated-surface candidate changed while it was read: "
                + relative_path.as_posix()
            )
        return bytes(raw)
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _read_discovered_candidate(
    parent_descriptor: int,
    entry: os.DirEntry[str],
    relative_path: Path,
    *,
    max_bytes: int = GENERATED_SURFACE_DISCOVERY_MAX_BYTES,
) -> bytes:
    """Read one observed candidate while retaining its parent-directory binding."""

    observed = entry.stat(follow_symlinks=False)
    return _read_bound_surface_candidate(
        parent_descriptor,
        entry.name,
        relative_path,
        observed,
        max_bytes=max_bytes,
    )


def _bounded_generated_surface_candidates(
    project_root: Path,
    requested_outputs: AbstractSet[str],
    *,
    owned_state_template_source_paths: AbstractSet[str] = frozenset(),
) -> tuple[list[str], list[str]]:
    """Find only exact generated-surface basenames through a bounded no-link walk."""

    candidates: list[str] = []
    errors: list[str] = []
    entries_seen = 0
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    capability_errors = _generated_surface_discovery_capability_errors()
    if capability_errors:
        return [], capability_errors
    root_descriptor: int | None = None
    try:
        root_descriptor = os.open(project_root, directory_flags)
        root_identity = os.fstat(root_descriptor)
    except OSError as exc:
        if root_descriptor is not None:
            resource_cleanup.cleanup_actions(
                (
                    (
                        "target project discovery root descriptor",
                        lambda: os.close(root_descriptor),
                    ),
                ),
                primary=exc,
            )
        return [], [f"could not bind target project root for discovery: {exc}"]

    def walk(
        directory_descriptor: int,
        relative_directory: Path,
        depth: int,
    ) -> None:
        nonlocal entries_seen
        with os.scandir(directory_descriptor) as entries:
            for entry in entries:
                entries_seen += 1
                if entries_seen > GENERATED_SURFACE_DISCOVERY_MAX_ENTRIES:
                    raise ValueError(
                        "existing-surface discovery exceeded its entry bound "
                        f"of {GENERATED_SURFACE_DISCOVERY_MAX_ENTRIES}"
                    )
                relative_path = relative_directory / entry.name
                entry_path = project_root / relative_path
                try:
                    is_link = entry.is_symlink()
                    is_directory = entry.is_dir(follow_symlinks=False)
                    is_regular = entry.is_file(follow_symlinks=False)
                except OSError as exc:
                    raise ValueError(
                        "could not classify existing project entry "
                        f"{entry_path}: {exc}"
                    ) from exc

                if entry.name in GENERATED_CONTRACT_BASENAMES:
                    if relative_path.as_posix() not in requested_outputs:
                        try:
                            raw = _read_discovered_candidate(
                                directory_descriptor,
                                entry,
                                relative_path,
                            )
                        except (OSError, ValueError) as exc:
                            raise ValueError(
                                "could not bind generated-surface candidate: "
                                f"{relative_path.as_posix()}: {exc}"
                            ) from exc
                        if _is_generated_contract_or_identity_surface(
                            entry.name,
                            raw,
                        ):
                            candidates.append(relative_path.as_posix())
                elif (
                    entry.name in GENERATED_STATE_BASENAMES
                    and relative_path.as_posix() not in requested_outputs
                ):
                    if relative_path.as_posix() in owned_state_template_source_paths:
                        try:
                            _read_discovered_candidate(
                                directory_descriptor,
                                entry,
                                relative_path,
                                max_bytes=project_state_identity.STATE_INPUT_MAX_BYTES,
                            )
                        except (OSError, ValueError) as exc:
                            raise ValueError(
                                "could not bind owned state-template "
                                f"source: {relative_path.as_posix()}: {exc}"
                            ) from exc
                        continue
                    if is_link or not is_regular:
                        raise ValueError(
                            "generated-state marker candidate must be a regular "
                            f"non-link file: {relative_path.as_posix()}"
                        )
                    try:
                        raw = _read_discovered_candidate(
                            directory_descriptor,
                            entry,
                            relative_path,
                            max_bytes=project_state_identity.STATE_INPUT_MAX_BYTES,
                        )
                    except (OSError, ValueError) as exc:
                        raise ValueError(
                            "could not bind generated-state marker candidate: "
                            f"{relative_path.as_posix()}: {exc}"
                        ) from exc
                    recognized, identity_error = (
                        project_state_identity.inspect_generated_state_origin(
                            entry.name,
                            raw,
                        )
                    )
                    if identity_error is not None:
                        raise ValueError(
                            "could not inspect generated-state marker candidate: "
                            f"{relative_path.as_posix()}: {identity_error}"
                        )
                    if recognized:
                        candidates.append(relative_path.as_posix())
                if len(candidates) > GENERATED_SURFACE_DISCOVERY_MAX_CANDIDATES:
                    raise ValueError(
                        "existing-surface discovery exceeded its candidate "
                        f"bound of {GENERATED_SURFACE_DISCOVERY_MAX_CANDIDATES}"
                    )

                if not is_directory or is_link:
                    continue
                if entry.name in GENERATED_SURFACE_DISCOVERY_IGNORED_DIRECTORIES:
                    continue
                if depth >= GENERATED_SURFACE_DISCOVERY_MAX_DEPTH:
                    raise ValueError(
                        "existing-surface discovery exceeded its directory-depth "
                        f"bound of {GENERATED_SURFACE_DISCOVERY_MAX_DEPTH} at "
                        + relative_path.as_posix()
                    )
                child_descriptor: int | None = None
                try:
                    observed = entry.stat(follow_symlinks=False)
                    child_descriptor = os.open(
                        entry.name,
                        directory_flags,
                        dir_fd=directory_descriptor,
                    )
                    opened = os.fstat(child_descriptor)
                    if _discovery_node_identity(observed) != _discovery_node_identity(
                        opened
                    ):
                        raise ValueError(
                            "existing project directory changed during bounded "
                            f"discovery: {relative_path.as_posix()}"
                        )
                    walk(child_descriptor, relative_path, depth + 1)
                    current = os.stat(
                        entry.name,
                        dir_fd=directory_descriptor,
                        follow_symlinks=False,
                    )
                    if _discovery_node_identity(current) != _discovery_node_identity(
                        opened
                    ):
                        raise ValueError(
                            "existing project directory changed during bounded "
                            f"discovery: {relative_path.as_posix()}"
                        )
                except OSError as exc:
                    raise ValueError(
                        "could not bind existing project directory without "
                        f"following links: {relative_path.as_posix()}: {exc}"
                    ) from exc
                finally:
                    if child_descriptor is not None:
                        os.close(child_descriptor)

    try:
        walk(root_descriptor, Path(), 0)
        current_root = os.stat(project_root, follow_symlinks=False)
        if _discovery_node_identity(current_root) != _discovery_node_identity(
            root_identity
        ):
            raise ValueError(
                "target project root changed during bounded existing-surface discovery"
            )
    except (OSError, ValueError) as exc:
        errors.append(str(exc))
    finally:
        os.close(root_descriptor)
    return candidates, errors


def outside_requested_generated_surface_errors(
    project_root: Path,
    requested_outputs: AbstractSet[str],
    *,
    project_kind: str,
    framework_root: Path = REPO_ROOT,
) -> list[str]:
    """Reject a second bootstrap graph layered onto recognizable MPA surfaces."""

    found: set[str] = set()
    discovery_errors: list[str] = []
    policy = contract_model.project_layout_policy(project_kind)
    if policy.manages_runtime_entrypoint:
        for relative, owners in _registered_runtime_target_labels(
            framework_root
        ).items():
            if relative in requested_outputs:
                continue
            raw, error = _read_existing_surface_candidate(
                relative,
                project_root,
                label="registered runtime target",
            )
            if error is not None:
                discovery_errors.append(error)
            elif raw is not None and _is_registered_mpa_runtime_surface(raw):
                found.add(f"{relative} ({', '.join(owners)})")

    owned_state_template_source_paths: AbstractSet[str] = frozenset()
    if (
        policy.state_template_source_paths
        and project_root.resolve(strict=False)
        == framework_root.resolve(strict=False)
    ):
        owned_state_template_source_paths = policy.state_template_source_paths
    candidates, walk_errors = _bounded_generated_surface_candidates(
        project_root,
        requested_outputs,
        owned_state_template_source_paths=owned_state_template_source_paths,
    )
    discovery_errors.extend(walk_errors)
    found.update(candidates)

    errors: list[str] = []
    if discovery_errors:
        errors.append(
            "initial bootstrap could not complete bounded existing-surface "
            "discovery; resolve the inspection boundary through a reviewed "
            "project-specific manual update before bootstrap: "
            + "; ".join(sorted(set(discovery_errors)))
        )
    if found:
        errors.append(
            "initial bootstrap is create-only and found recognizable framework "
            "surfaces outside the requested output graph. Use a reviewed "
            "project-specific manual update instead of layering another bootstrap: "
            + ", ".join(sorted(found))
        )
    return errors


def existing_instance_bootstrap_errors(
    project_root: Path,
    contract_root_ref: str,
    answers: dict,
    runtime: str | None,
    project_kind: str,
    runtime_wrappers: tuple[str, ...] = (),
) -> list[str]:
    """Keep initial bootstrap from bypassing current lifecycle controls."""

    if not project_root.exists():
        return []
    input_name = project_relative_output(contract_root_ref, project_input.INPUT_NAME)
    root_manifest_name = INSTANCE_MANIFEST
    root_manifest = project_root / root_manifest_name
    if root_manifest.exists() or root_manifest.is_symlink():
        return [
            "initial bootstrap cannot overwrite an existing project instance; "
            "the root-scoped lifecycle receipt locates the selected contract root. "
            "Use scripts/project_refresh.py inspect to classify it: a verified "
            "complete current-format retained-input/receipt pair with an intact "
            "recorded preimage may enter refresh planning, a closed transaction-control "
            "state may instead permit only its reported exact-ID recovery action, "
            "older, malformed, or unrecognized instances require a reviewed "
            "project-specific manual update, and clearly newer instances require "
            f"a supporting framework checkout: {root_manifest_name}"
        ]
    contract_local_manifest_name = project_relative_output(
        contract_root_ref,
        INSTANCE_MANIFEST,
    )
    metadata_present = [
        name
        for name in (input_name, contract_local_manifest_name)
        if name != root_manifest_name
        if (project_root / name).exists() or (project_root / name).is_symlink()
    ]
    if metadata_present:
        return [
            "initial bootstrap cannot overwrite an existing project instance; "
            "generic refresh requires a complete current-format root receipt and retained input. "
            "A closed transaction-control state is handled independently through "
            "inspection-gated exact-ID recovery; otherwise perform a reviewed "
            "project-specific manual update before using the current refresh route: "
            + ", ".join(metadata_present)
        ]
    requested_outputs = set(
        planned_output_names(
            answers,
            runtime,
            project_kind=project_kind,
            contract_root_ref=contract_root_ref,
            runtime_wrappers=runtime_wrappers,
        )
    )
    outside_errors = outside_requested_generated_surface_errors(
        project_root,
        requested_outputs,
        project_kind=project_kind,
    )
    if outside_errors:
        return outside_errors
    generated = [
        name
        for name in requested_outputs
        if name not in {input_name, root_manifest_name}
        and ((project_root / name).exists() or (project_root / name).is_symlink())
    ]
    if generated:
        return [
            "initial bootstrap is create-only and cannot overwrite or reconstruct existing "
            "project surfaces. Generic refresh requires a complete current-format root receipt and "
            "retained input; perform a reviewed project-specific manual update first: "
            + ", ".join(sorted(generated))
        ]
    return []


def contract_output_names(answers: dict) -> list[str]:
    return [
        "STATEMENT_OF_WORK.md",
        "AGENT_PROJECT.md",
        "TODO.md",
        "DECISIONS.md",
        *optional_state_names(answers),
    ]


def mutable_state_output_names(answers: dict, contract_root_ref: str = ".") -> list[str]:
    return [
        project_relative_output(contract_root_ref, name)
        for name in [
            "TODO.md",
            "DECISIONS.md",
            *(
                name
                for name in optional_state_names(answers)
                if name in contract_model.optional_state_filenames("mutable")
            ),
        ]
    ]


def project_relative_output(contract_root_ref: str, name: str) -> str:
    return name if contract_root_ref == "." else f"{contract_root_ref}/{name}"


def active_project_profiles(
    answers: Mapping[str, object],
    *,
    project_kind: str = "downstream",
) -> list[str]:
    """Return the exact conformance profiles activated by retained inputs."""

    contract_model.project_layout_policy(project_kind)
    profiles = ["core-project"]
    if answers.get("include_source_update") is True:
        profiles.append("source-managed")
    if answers.get("include_security_verification") is True:
        profiles.append("security-managed")
    if answers.get("include_automation_orders") is True:
        profiles.append("automation-managed")
    if answers.get("include_precedents") is True:
        profiles.append("multi-agent-managed")
    if answers.get("include_reviewer_lane_feedback") is True:
        profiles.append("reviewer-lane-managed")
    return profiles


def project_instance_file_sets(
    *,
    answers: Mapping[str, object],
    runtime: str | None,
    project_kind: str,
    contract_root_ref: str,
    runtime_wrappers: list[str] | tuple[str, ...] = (),
) -> tuple[list[str], list[str], list[str]]:
    """Partition generated project surfaces without self-digesting metadata."""

    mutable = sorted(mutable_state_output_names(dict(answers), contract_root_ref))
    immutable = [
        project_relative_output(contract_root_ref, "STATEMENT_OF_WORK.md"),
        project_relative_output(contract_root_ref, "AGENT_PROJECT.md"),
        *(
            project_relative_output(contract_root_ref, name)
            for name in immutable_optional_state_names(dict(answers))
        ),
    ]
    policy = contract_model.project_layout_policy(project_kind)
    if policy.manages_runtime_entrypoint:
        if runtime is None:
            raise ValueError("downstream project file partitioning requires a runtime")
        immutable.append(ENTRYPOINT_TEMPLATES[runtime][1])
        immutable.extend(
            integration_registry.wrapper_output_map(
                runtime,
                list(runtime_wrappers),
                REPO_ROOT,
            ).values()
        )
    immutable = sorted(immutable)
    managed = sorted([*immutable, *mutable])
    return managed, immutable, mutable


def planned_output_names(
    answers: dict,
    runtime: str | None,
    *,
    project_kind: str = "downstream",
    contract_root_ref: str = ".",
    runtime_wrappers: list[str] | tuple[str, ...] = (),
) -> list[str]:
    outputs = [
        project_relative_output(contract_root_ref, name)
        for name in contract_output_names(answers)
    ]
    policy = contract_model.project_layout_policy(project_kind)
    if policy.manages_runtime_entrypoint:
        if runtime is None:
            raise ValueError("downstream project output planning requires a runtime")
        outputs.insert(2, ENTRYPOINT_TEMPLATES[runtime][1])
        outputs.extend(
            integration_registry.wrapper_output_map(
                runtime,
                list(runtime_wrappers),
                REPO_ROOT,
            ).values()
        )
    outputs.extend(
        [
            project_relative_output(contract_root_ref, project_input.INPUT_NAME),
            INSTANCE_MANIFEST,
        ]
    )
    return outputs


def state_template_content(
    name: str,
    answers: dict | None = None,
    framework_ref: str | None = None,
    *,
    contract_root_ref: str = ".",
) -> str:
    answers = answers or {}
    template_rel = BOOTSTRAP_STATE_TEMPLATES.get(name, STATE_TEMPLATES[name])
    template = read_framework_source_text(
        template_rel,
        description=f"framework state template {template_rel}",
    )
    if not project_state_identity.has_generated_state_origin(
        name,
        template.encode("utf-8"),
    ):
        raise ValueError(
            f"framework state template {template_rel} is missing its exact "
            "framework-generated state origin marker"
        )
    def finalize(content: str) -> str:
        if not name.endswith(".md"):
            return content
        return integration_registry.render_project_file_references(
            content,
            contract_root_ref,
        )

    if name == "SOURCE_UPDATE.md":
        replacements = {
            "{{SOURCE_REGISTRY_SCOPE}}": source_registry_scope(answers),
            "{{SOURCE_REVIEW_CADENCE}}": source_review_cadence(answers),
            "{{VERSION_REVIEW_RULE}}": field(
                answers,
                "version_review_policy",
                DEFAULT_VERSION_REVIEW_POLICY,
            ),
        }
        for placeholder, value in replacements.items():
            template = template.replace(placeholder, value)
        return finalize(template)
    if name == "SECURITY_VERIFICATION.md":
        return finalize(template.replace(
            "{{SECURITY_VERIFICATION_PROFILE_SCOPE}}",
            security_verification_profile_scope(answers),
        ).replace(
            "{{SECURITY_VERIFICATION_TARGET_POLICY}}",
            security_verification_target_policy(answers),
        ))
    if name == "SOURCE_MONITOR_RESEARCHER.md":
        runner = field(
            answers,
            "framework_verification_runner",
            FRAMEWORK_VERIFICATION_RUNNER_PLACEHOLDER,
        )
        reference = framework_ref or "{{FRAMEWORK_ROOT}}"
        replacements = {
            "{{SOURCE_MONITOR_ROLE}}": source_monitor_role(answers),
            "{{SOURCE_MONITOR_INSTRUCTION_SOURCES}}": source_monitor_instruction_sources(answers),
            "{{SOURCE_MONITOR_SOURCE_DATA}}": source_monitor_source_data(answers),
            "{{SOURCE_MONITOR_BOUNDARY}}": source_monitor_boundary(answers),
            "{{SOURCE_MONITOR_ARTIFACT_LINT_COMMAND}}": (
                contract_model.source_monitor_artifact_lint_command(
                    runner,
                    reference,
                )
            ),
        }
        for placeholder, value in replacements.items():
            template = template.replace(placeholder, value)
        if reference == "{{FRAMEWORK_ROOT}}":
            return finalize(template)
        return finalize(safe_paths.render_framework_reference_tokens(template, reference))
    if name == "SOURCE_PACKS.md":
        return finalize(template.replace(
            "{{SHARED_FRAMEWORK_SOURCE_REFERENCE}}",
            shared_framework_source_reference(answers),
        ))
    if name == "AUTOMATION_ORDERS.json":
        automation_orders = answers.get("automation_orders") if isinstance(answers, dict) else None
        jobs = automation_orders.get("jobs") if isinstance(automation_orders, dict) else []
        payload = safe_paths.loads_json_no_duplicates(template)
        if not isinstance(payload, dict):
            raise ValueError("AUTOMATION_ORDERS.json template must be a JSON object")
        payload["preferred_backend"] = automation_preferred_backend(answers)
        payload["jobs"] = jobs if isinstance(jobs, list) else []
        return json.dumps(payload, indent=2) + "\n"
    return finalize(template)


def render_output_files(
    answers: dict,
    runtime: str | None,
    framework_ref: str,
    *,
    project_kind: str = "downstream",
    contract_root_ref: str = ".",
    effective_date: str | None = None,
    runtime_wrappers: list[str] | tuple[str, ...] = (),
) -> dict[str, str]:
    batch_date = effective_date or render_date(answers)
    outputs: dict[str, str] = {
        project_relative_output(contract_root_ref, "STATEMENT_OF_WORK.md"): integration_registry.render_project_file_references(
            render_sow(answers, effective_date=batch_date),
            contract_root_ref,
        ),
        project_relative_output(contract_root_ref, "AGENT_PROJECT.md"): render_project_contract(
            answers,
            framework_ref,
            project_kind=project_kind,
            contract_root_ref=contract_root_ref,
            effective_date=batch_date,
        ),
        project_relative_output(contract_root_ref, "TODO.md"): state_template_content(
            "TODO.md",
            answers,
            framework_ref,
            contract_root_ref=contract_root_ref,
        ),
        project_relative_output(contract_root_ref, "DECISIONS.md"): state_template_content(
            "DECISIONS.md",
            answers,
            framework_ref,
            contract_root_ref=contract_root_ref,
        ),
    }
    policy = contract_model.project_layout_policy(project_kind)
    if policy.manages_runtime_entrypoint:
        if runtime is None:
            raise ValueError("downstream project rendering requires a runtime")
        entrypoint_name, entrypoint = render_entrypoint(
            runtime,
            framework_ref,
            contract_root_ref=contract_root_ref,
        )
        outputs[entrypoint_name] = entrypoint
    for name in optional_state_names(answers):
        outputs[project_relative_output(contract_root_ref, name)] = state_template_content(
            name,
            answers,
            framework_ref,
            contract_root_ref=contract_root_ref,
        )
    if policy.manages_runtime_entrypoint:
        assert runtime is not None
        wrapper_outputs = integration_registry.render_wrapper_outputs(
            runtime,
            runtime_wrappers,
            framework_ref,
            contract_root_ref,
            REPO_ROOT,
        )
        collisions = sorted(set(outputs).intersection(wrapper_outputs))
        if collisions:
            raise ValueError(
                "runtime wrapper outputs collide with generated project outputs: "
                + ", ".join(collisions)
            )
        outputs.update(wrapper_outputs)
    return outputs


def rendered_output_warnings(
    answers: dict,
    runtime: str | None,
    framework_ref: str,
    *,
    project_kind: str = "downstream",
    contract_root_ref: str = ".",
    effective_date: str | None = None,
    runtime_wrappers: list[str] | tuple[str, ...] = (),
) -> list[str]:
    warnings: list[str] = []
    rendered_outputs = render_output_files(
        answers,
        runtime,
        framework_ref,
        project_kind=project_kind,
        contract_root_ref=contract_root_ref,
        effective_date=effective_date,
        runtime_wrappers=runtime_wrappers,
    )
    for name, text in rendered_outputs.items():
        for warning in find_local_state_references(text, name):
            warnings.append(f"rendered output warning: {warning}")
    return warnings


def file_sha256(path: Path) -> str:
    return sha256_bytes(
        safe_paths.read_regular_file_bytes(
            path,
            description=f"framework generation source {path}",
        )
    )


def project_relative_input_source(path: Path, project_root: Path) -> str | None:
    try:
        relative = path.relative_to(project_root).as_posix()
        normalized = safe_paths.normalize_repo_relative_path(
            relative,
            project_root,
            description="project instance input source",
        )
    except ValueError:
        return None
    candidate = project_root / normalized
    if safe_paths.bounded_input_errors(
        candidate,
        project_root,
        description="project instance input source",
    ):
        return None
    if not candidate.is_file() or candidate.is_symlink():
        return None
    return normalized


def generation_sources_for_output(name: str, runtime: str | None) -> tuple[str, ...]:
    """Return the ordered direct repository sources used to generate one output.

    This provenance boundary includes checked-in content inputs, declarative
    semantic owners, and project-owned transformation/compiler modules whose
    functions shape output bytes. It excludes the Python runtime, standard
    library, and validation-only modules that do not shape the output.
    """

    basename = Path(name).name
    if basename == "STATEMENT_OF_WORK.md":
        return (
            "master_service_agreement.md",
            "scripts/project_contract_model.py",
            "scripts/integration_registry.py",
            "scripts/project_bootstrap.py",
        )
    if basename == "AGENT_PROJECT.md":
        return (
            "scripts/project_contract_model.py",
            "scripts/integration_registry.py",
            "scripts/safe_paths.py",
            "scripts/project_bootstrap.py",
        )
    if runtime is not None and basename == ENTRYPOINT_TEMPLATES[runtime][1]:
        return (
            ENTRYPOINT_TEMPLATES[runtime][0],
            "integrations/registry.json",
            "scripts/project_contract_model.py",
            "scripts/integration_registry.py",
            "scripts/safe_paths.py",
            "scripts/project_bootstrap.py",
        )
    if runtime is not None:
        wrapper_source = integration_registry.wrapper_generation_source(
            runtime,
            name,
            REPO_ROOT,
        )
        if wrapper_source is not None:
            return (
                wrapper_source,
                "integrations/registry.json",
                "scripts/integration_registry.py",
                "scripts/safe_paths.py",
                "scripts/project_bootstrap.py",
            )
    if basename in STATE_TEMPLATES:
        sources = [
            BOOTSTRAP_STATE_TEMPLATES.get(basename, STATE_TEMPLATES[basename]),
            "scripts/project_contract_model.py",
            "scripts/project_state_identity.py",
        ]
        if basename.endswith(".md"):
            sources.append("scripts/integration_registry.py")
        if basename in {"AUTOMATION_ORDERS.json", "SOURCE_MONITOR_RESEARCHER.md"}:
            sources.append("scripts/safe_paths.py")
        sources.append(
            "scripts/project_bootstrap.py",
        )
        return tuple(sources)
    raise ValueError(f"no generation sources registered for generated output: {name}")


def render_instance_manifest(
    *,
    input_bytes: bytes,
    project_kind: str,
    contract_root_ref: str,
    runtime: str | None,
    framework_reference: str,
    framework_revision_policy: str,
    framework_reference_status: str,
    managed_files: list[str],
    immutable_files: list[str],
    mutable_files: list[str],
    runtime_wrapper_outputs: dict[str, str],
    rendered_outputs: dict[str, str],
    active_profiles: list[str],
    effective_date: str,
    framework_identity: FrameworkIdentity | None = None,
) -> str:
    generation_sources: dict[str, list[dict[str, str]]] = {}
    for output in immutable_files:
        generation_sources[output] = [
            {
                "path": source,
                "sha256": file_sha256(REPO_ROOT / source),
            }
            for source in generation_sources_for_output(output, runtime)
        ]
    input_source = project_relative_output(
        contract_root_ref,
        project_input.INPUT_NAME,
    )
    identity = (
        capture_framework_identity(REPO_ROOT)
        if framework_identity is None
        else framework_identity
    )
    effective_file_digests = identity.effective_file_digest_map()
    payload = {
        "schema_version": PROJECT_INSTANCE_SCHEMA_VERSION,
        "project_input_schema_version": project_input.SCHEMA_VERSION,
        "project_contract_format": contract_model.CONTRACT_FORMAT_VERSION,
        "msa_version": msa_version(),
        "contract_effective_date": effective_date,
        "project_kind": project_kind,
        "contract_root": contract_root_ref,
        "runtime": runtime,
        "runtime_wrapper_outputs": dict(sorted(runtime_wrapper_outputs.items())),
        "framework_reference": framework_reference,
        "framework_revision_policy": framework_revision_policy,
        "framework_reference_status": framework_reference_status,
        "framework_content_sha256": identity.content_sha256,
        "framework_effective_file_digests": effective_file_digests,
        "framework_distribution_sha256": identity.distribution_sha256,
        "input_source": input_source,
        "input_sha256": project_input.project_input_sha256(input_bytes),
        "active_profiles": active_profiles,
        "managed_files": managed_files,
        "immutable_files": immutable_files,
        "mutable_files": mutable_files,
        "output_digests": {
            name: sha256_bytes(rendered_outputs[name].encode("utf-8"))
            for name in immutable_files
        },
        "generation_sources": generation_sources,
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def placeholder_answer_warnings(payload: object, path: str = "answers") -> list[str]:
    warnings: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            warnings.extend(placeholder_answer_warnings(value, f"{path}.{key}"))
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            warnings.extend(placeholder_answer_warnings(value, f"{path}[{index}]"))
    elif isinstance(payload, str):
        normalized = payload.strip().casefold()
        if (
            normalized in EXAMPLE_ANSWER_VALUES
            or contract_model.is_deferred_value(payload)
        ):
            warnings.append(
                f"placeholder answer at {path}: replace it with a confirmed project value before writing setup files"
            )
    return warnings


def summary_payload(
    answers: dict,
    project_root: Path,
    runtime: str | None,
    answers_path: Path,
    framework_root: Path,
    framework_ref: str,
    *,
    project_kind: str = "downstream",
    contract_root_ref: str = ".",
    setup_profile_summary: dict[str, object] | None = None,
    effective_date: str | None = None,
    runtime_wrappers: list[str] | tuple[str, ...] = (),
) -> dict[str, object]:
    policy = contract_model.project_layout_policy(project_kind)
    batch_date = effective_date or render_date(answers)
    mode = bootstrap_mode(answers)
    persistent_memory_boundary = str(answers.get("persistent_memory_boundary", "")).strip()
    planned_outputs = planned_output_names(
        answers,
        runtime,
        project_kind=project_kind,
        contract_root_ref=contract_root_ref,
        runtime_wrappers=runtime_wrappers,
    )
    optional_files = [
        project_relative_output(contract_root_ref, name)
        for name in optional_state_names(answers)
    ]
    policy_sections = [
        name
        for present, name in (
            (
                bool(str(answers.get("decision_authority_grant", "")).strip())
                and str(answers.get("decision_authority_grant", "")).strip().casefold()
                != DEFAULT_DECISION_AUTHORITY_GRANT.casefold(),
                "decision_authority_grant",
            ),
            (bool(answers.get("approval_boundaries")), "approval_boundaries"),
            (bool(lines_for(answers.get("acquisition_boundary"))), "acquisition_boundary"),
            (bool(lines_for(answers.get("critical_surfaces"))), "critical_surfaces"),
            (bool(lines_for(answers.get("version_control_profile"))), "version_control_profile"),
            (
                bool(persistent_memory_boundary)
                and persistent_memory_boundary.casefold() != DEFAULT_PERSISTENT_MEMORY_BOUNDARY.casefold(),
                "persistent_memory_boundary",
            ),
            (bool(lines_for(answers.get("verification_profiles"))), "verification_profiles"),
            (bool(answers.get("workflows")), "workflows"),
            (bool(answers.get("arbitration_panel")), "arbitration_panel"),
            (bool(answers.get("direct_panel_rules")), "direct_panel_rules"),
            (bool(str(answers.get("independent_assessment_approval", "")).strip()), "independent_assessment_override"),
            (bool(project_module_references(answers)), "active_project_modules"),
            (bool(optional_files), "optional_state_files"),
        )
        if present
    ]
    return {
        "project_name": field(answers, "project_name"),
        "project_kind": project_kind,
        "project_root": str(project_root),
        "contract_root": contract_root_ref,
        "runtime": runtime,
        "runtime_wrappers": sorted(runtime_wrappers),
        "bootstrap_mode": mode,
        "contract_effective_date": batch_date,
        "planned_outputs": planned_outputs,
        "optional_files": optional_files,
        "setup_profile": setup_profile_summary,
        "policy_sections": policy_sections,
        "notes": (
            ["minimal bootstrap selected. Commands, deliverables, and stack details may remain deferred."]
            if mode == "minimal"
            else []
        ),
        "warnings": [
            *absolute_path_warnings(answers),
            *(
                find_local_state_references(answers)
                if policy.emit_external_input_warnings
                else []
            ),
            *(
                answer_file_warnings(answers_path, project_root)
                if policy.emit_external_input_warnings
                else []
            ),
            *(
                parent_context_warnings(project_root, framework_root)
                if policy.emit_external_input_warnings
                else []
            ),
            *framework_reference_warnings(framework_ref),
            *(
                rendered_output_warnings(
                    answers,
                    runtime,
                    framework_ref,
                    project_kind=project_kind,
                    contract_root_ref=contract_root_ref,
                    effective_date=batch_date,
                    runtime_wrappers=runtime_wrappers,
                )
                if policy.emit_external_input_warnings
                else []
            ),
            *placeholder_answer_warnings(answers),
            *(
                [
                    "policy-specific sections are enabled. Confirm they were explicitly requested or clearly evidenced before writing files."
                ]
                if policy_sections
                else []
            ),
        ],
    }


def render_auxiliary_tool(item: dict) -> str:
    return contract_model.render_structured_record("auxiliary_tools", item)


def render_runtime_auxiliary_tool(item: dict) -> str:
    return contract_model.render_runtime_auxiliary_tool_route(item)


def render_workflow(item: dict) -> str:
    return contract_model.render_structured_record("workflows", item)


def render_runtime_workflow(item: dict) -> str:
    return contract_model.render_runtime_workflow_route(item)


def render_pattern_source(item: str) -> str:
    return f"- {item}"


def memory_boundary_lines(answers: dict) -> list[str]:
    return lines_for(answers.get("persistent_memory_boundary")) or [DEFAULT_PERSISTENT_MEMORY_BOUNDARY]


def security_policy_file(answers: dict) -> str:
    return field(answers, "security_policy_file", DEFAULT_SECURITY_POLICY_FILE)


def shared_framework_source_reference(answers: dict) -> str:
    return field(
        answers,
        "shared_framework_source_reference",
        contract_model.DEFAULT_SHARED_FRAMEWORK_SOURCE_REFERENCE,
    )


def source_registry_scope(answers: dict) -> str:
    return field(answers, "source_registry_scope", DEFAULT_SOURCE_REGISTRY_SCOPE)


def automation_preferred_backend(answers: dict) -> str:
    automation_orders = answers.get("automation_orders")
    if not isinstance(automation_orders, dict):
        return contract_model.DEFAULT_AUTOMATION_BACKEND
    value = automation_orders.get("preferred_backend")
    return (
        value
        if isinstance(value, str) and value
        else contract_model.DEFAULT_AUTOMATION_BACKEND
    )


def source_review_cadence(answers: dict) -> str:
    return field(answers, "source_review_cadence", DEFAULT_SOURCE_REVIEW_CADENCE)


def source_monitor_role(answers: dict) -> str:
    return field(answers, "source_monitor_role", DEFAULT_SOURCE_MONITOR_ROLE)


def source_monitor_instruction_sources(answers: dict) -> str:
    return (
        " / ".join(lines_for(answers.get("source_monitor_instruction_sources")))
        or DEFAULT_SOURCE_MONITOR_INSTRUCTION_SOURCES
    )


def source_monitor_source_data(answers: dict) -> str:
    configured = " / ".join(lines_for(answers.get("source_monitor_source_data")))
    if configured:
        return configured
    if answers.get("include_source_update"):
        return " / ".join(
            (
                contract_model.OPTIONAL_STATE_BY_DEFINITION_LABEL[
                    "Source Packs File"
                ].filename,
                contract_model.OPTIONAL_STATE_BY_DEFINITION_LABEL[
                    "Source Update File"
                ].filename,
            )
        )
    if answers.get("include_source_packs"):
        return contract_model.OPTIONAL_STATE_BY_DEFINITION_LABEL[
            "Source Packs File"
        ].filename
    return contract_model.DEFAULT_OPTIONAL_DEFINITION_VALUE


def optional_state_filename(definition_label: str) -> str:
    return contract_model.OPTIONAL_STATE_BY_DEFINITION_LABEL[
        definition_label
    ].filename


def source_monitor_boundary(answers: dict) -> str:
    return field(answers, "source_monitor_boundary", DEFAULT_SOURCE_MONITOR_BOUNDARY)


def security_verification_profile_scope(answers: dict) -> str:
    return field(
        answers,
        "security_verification_profile_scope",
        DEFAULT_SECURITY_VERIFICATION_PROFILE_SCOPE,
    )


def security_verification_target_policy(answers: dict) -> str:
    return field(
        answers,
        "security_verification_target_policy",
        DEFAULT_SECURITY_VERIFICATION_TARGET_POLICY,
    )


def arbitration_panel_projection(answers: dict) -> str:
    return (
        contract_model.CUSTOM_ARBITRATION_PANEL_PROJECTION
        if answers.get("arbitration_panel")
        else contract_model.DEFAULT_ARBITRATION_PANEL_PROJECTION
    )


def direct_panel_rules_projection(answers: dict) -> str:
    return (
        "; ".join(lines_for(answers.get("direct_panel_rules")))
        or contract_model.DEFAULT_OPTIONAL_DEFINITION_VALUE
    )


def msa_version() -> str:
    text = read_framework_source_text(
        "master_service_agreement.md",
        description="master service agreement source",
    )
    version_rows = [
        line for line in text.splitlines() if line.startswith("Version:")
    ]
    if len(version_rows) != 1:
        raise ValueError(
            "master service agreement source must contain exactly one anchored "
            f"Version row; found {len(version_rows)}"
        )
    match = MSA_VERSION_RE.match(version_rows[0])
    if match is None:
        raise ValueError(
            "master service agreement source has a malformed anchored Version row"
        )
    return match.group("version")


def msa_reference() -> str:
    return f"master_service_agreement.md v{msa_version()}"


@dataclass
class SowRenderContext:
    answers: dict
    mode: str
    commands: dict[str, str]
    lines: list[str]


def definition_values(
    answers: dict,
    mode: str,
    commands: dict[str, str],
    runtime_standards: str,
) -> dict[str, str]:
    """Resolve values using the model-owned projection declared for each Definition."""

    values: dict[str, str] = {}
    for spec in contract_model.DEFINITION_SPECS:
        if spec.projection == "answer":
            if spec.answer_key is None:
                raise ValueError(
                    f"Definition {spec.label!r} has no model-owned answer projection"
                )
            value = field(
                answers,
                spec.answer_key,
                spec.default or contract_model.DEFAULT_DEFINITION_VALUE,
            )
            values[spec.label] = value + spec.suffix
        elif spec.projection == "bootstrap-mode":
            values[spec.label] = mode
        elif spec.projection == "optional-state":
            state_spec = contract_model.OPTIONAL_STATE_BY_DEFINITION_LABEL[spec.label]
            values[spec.label] = (
                state_spec.filename
                if answers.get(state_spec.flag)
                else spec.default or contract_model.DEFAULT_OPTIONAL_DEFINITION_VALUE
            )
        elif spec.projection == "arbitration-panel":
            values[spec.label] = arbitration_panel_projection(answers)
        elif spec.projection == "direct-panel-rules":
            values[spec.label] = direct_panel_rules_projection(answers)
        elif spec.projection == "source-monitor-instruction-sources":
            values[spec.label] = source_monitor_instruction_sources(answers)
        elif spec.projection == "source-monitor-source-data":
            values[spec.label] = source_monitor_source_data(answers)
        elif spec.projection == "command":
            values[spec.label] = contract_model.COMMAND_DEFINITION_POINTER
        elif spec.projection == "runtime-standards":
            values[spec.label] = runtime_standards
        else:
            raise ValueError(
                f"Definition {spec.label!r} uses unknown model projection {spec.projection!r}"
            )
    return values


def rendered_definition_lines(
    surface: str,
    answers: dict,
    mode: str,
    commands: dict[str, str],
    runtime_standards: str,
    *,
    prefix: str = "",
) -> list[str]:
    specs = (
        contract_model.SOW_DEFINITION_SPECS
        if surface == "sow"
        else contract_model.PROJECT_DEFINITION_SPECS
    )
    values = definition_values(answers, mode, commands, runtime_standards)

    def include(spec: contract_model.DefinitionSpec) -> bool:
        active = spec.active_when is None or answers.get(spec.active_when) is True
        if surface == "sow":
            return active
        return contract_model.runtime_definition_included(
            spec,
            values[spec.label],
            active_when_enabled=(
                contract_model.runtime_definition_activation_enabled(spec, values)
            ),
        )

    return [
        f"{prefix}{spec.label}: {values[spec.label]}"
        for spec in specs
        if include(spec)
    ]


def section_owned_definition_lines(
    owner: str,
    answers: dict,
    mode: str,
    commands: dict[str, str],
    runtime_standards: str,
) -> list[str]:
    """Render each active labeled fact only in its declared runtime section."""

    values = definition_values(answers, mode, commands, runtime_standards)
    return [
        f"- {spec.label}: {values[spec.label]}"
        for spec in contract_model.PROJECT_DEFINITION_SPECS
        if spec.runtime_owner == owner
        and contract_model.runtime_owned_definition_included(
            spec,
            values[spec.label],
            active_when_enabled=contract_model.runtime_definition_activation_enabled(
                spec,
                values,
            ),
        )
    ]


def sow_preamble(
    answers: dict,
    mode: str,
    project_name: str,
    commands: dict[str, str],
    effective_date: str,
) -> list[str]:
    lines = [
        contract_model.CONTRACT_FORMAT_MARKER,
        f"Statement of Work — {project_name}",
        "",
        f"SOW Version: {field(answers, 'sow_version', '1.0.0')}  MSA Reference: {msa_reference()}  Date: {effective_date}",
        "",
        contract_model.SOW_OPTIONAL_DEFAULT_RULE,
        "",
        "Definitions",
        "",
        contract_model.SOW_DEFINITION_INDEX_RULE,
        "",
    ]
    lines.extend(
        rendered_definition_lines(
            "sow",
            answers,
            mode,
            commands,
            field(answers, "language_runtime_standards"),
        )
    )
    lines.append("")
    return lines


def append_sow_review_sections(context: SowRenderContext) -> None:
    answers = context.answers
    lines = context.lines
    panel = answers.get("arbitration_panel", {})
    if panel:
        panel_lines = [
            f"Seat {index}: "
            + contract_model.render_structured_record(
                "arbitration_panel.seats",
                item,
            )
            for index, item in enumerate(panel["seats"], start=1)
        ]
        panel_lines.extend(
            f"{spec.prefix}{field(panel, spec.key)}{spec.suffix}"
            for spec in contract_model.structured_field_specs("arbitration_panel")
            if spec.render_mode == "labeled"
        )
        add_section(
            lines,
            contract_model.sow_section_title("arbitration_panel"),
            panel_lines,
        )
    standing_orders = lines_for(answers.get("direct_panel_rules"))
    standing_approval = str(answers.get("standing_panel_convocation_approval", "")).strip()
    if standing_orders or standing_approval:
        direct_panel_lines = bullets(standing_orders)
        if standing_orders and standing_approval:
            direct_panel_lines.append("")
        if standing_approval:
            direct_panel_lines.append(
                f"Standing Panel Convocation Approval: {standing_approval}"
            )
        add_section(
            lines,
            contract_model.sow_section_title("direct_panel_rules"),
            direct_panel_lines,
        )
    if str(answers.get("independent_assessment_approval", "")).strip():
        add_section(
            lines,
            contract_model.sow_section_title("independent_assessment"),
            [
                *contract_model.sow_section_policy_lines(
                    "independent_assessment"
                ),
                f"Independent Assessment Approval: {field(answers, 'independent_assessment_approval')}",
            ],
        )


def append_sow_project_sections(context: SowRenderContext) -> None:
    answers = context.answers
    lines = context.lines
    recital_lines = lines_for(answers.get("recitals"))
    if context.mode == "minimal" and (
        not recital_lines
        or any(contract_model.is_deferred_value(item) for item in recital_lines)
    ):
        recital_lines = [
            *(
                item
                for item in recital_lines
                if not contract_model.is_deferred_value(item)
            ),
            contract_model.MINIMAL_RECITALS_DEFERRAL,
        ]
    add_section(
        lines,
        contract_model.sow_section_title("recitals"),
        recital_lines or ["TBD"],
    )
    add_section(lines, contract_model.sow_section_title("project_vocabulary"), bullets(lines_for(answers.get("project_vocabulary"))))
    add_section(lines, contract_model.sow_section_title("scope"), ["In scope:", *bullets(lines_for(answers.get("in_scope")) or ["TBD"]), "", "Out of scope:", *bullets(lines_for(answers.get("out_of_scope")) or ["TBD"])])
    add_section(lines, contract_model.sow_section_title("minimal_deferrals"), bullets(minimal_deferrals(answers)))
    file_structure = lines_for(answers.get("file_structure"))
    key_dependencies = lines_for(answers.get("key_dependencies"))
    key_directories = lines_for(answers.get("key_directories"))
    tech_specs = [
        f"Tech stack: {field(answers, 'tech_stack')}",
        "",
        f"Architecture: {field(answers, 'architecture')}",
    ]
    if key_dependencies:
        tech_specs.extend(["", f"Key dependencies: {', '.join(key_dependencies)}"])
    if key_directories:
        tech_specs.extend(["", f"Key directories: {', '.join(key_directories)}"])
    if file_structure:
        tech_specs.extend(["", "File structure:", *file_structure])
    add_section(lines, contract_model.sow_section_title("technical_specifications"), tech_specs)
    add_section(
        lines,
        contract_model.sow_section_title("pattern_sources"),
        [render_pattern_source(item) for item in lines_for(answers.get("pattern_sources"))],
    )
    deliverables = answers.get("deliverables", [])
    deliverable_lines = [
        f"{index}. "
        + contract_model.render_structured_record("deliverables", item)
        for index, item in enumerate(deliverables, start=1)
    ]
    if deliverable_lines or context.mode != "minimal":
        add_section(lines, contract_model.sow_section_title("deliverables"), deliverable_lines or ["1. TBD — TBD — TBD"])
    add_section(lines, contract_model.sow_section_title("acceptance_checklist"), bullets(lines_for(answers.get("acceptance_checklist"))))
    add_section(lines, contract_model.sow_section_title("constraints"), bullets(lines_for(answers.get("constraints"))))
    add_section(lines, contract_model.sow_section_title("critical_surfaces"), bullets(lines_for(answers.get("critical_surfaces"))))
    if security_policy_file(answers) == "inline in this SOW":
        add_section(lines, contract_model.sow_section_title("security_policy"), bullets(lines_for(answers.get("security_policy_terms"))))
    add_section(lines, contract_model.sow_section_title("version_control_profile"), bullets(lines_for(answers.get("version_control_profile"))))
    add_section(lines, contract_model.sow_section_title("memory_boundary"), bullets(memory_boundary_lines(answers)))
    add_section(lines, contract_model.sow_section_title("verification_profiles"), bullets(lines_for(answers.get("verification_profiles"))))
    add_section(lines, contract_model.sow_section_title("approval_boundaries"), bullets(lines_for(answers.get("approval_boundaries"))))
    add_section(lines, contract_model.sow_section_title("acquisition_boundary"), bullets(lines_for(answers.get("acquisition_boundary"))))


def append_sow_execution_sections(context: SowRenderContext) -> None:
    answers = context.answers
    commands = context.commands
    lines = context.lines

    add_section(
        lines,
        contract_model.sow_section_title("commands"),
        [
            f"{commands[spec.deferral_field]} — {spec.sow_label}"
            for spec in contract_model.COMMAND_SPECS
        ],
    )
    add_section(
        lines,
        contract_model.sow_section_title("auxiliary_tools"),
        [f"{index}. {render_auxiliary_tool(item)}" for index, item in enumerate(answers.get("auxiliary_tools", []), start=1)],
    )
    if any(
        str(answers.get(key, "")).strip()
        for key in ("reviewer_lane_inventory", "default_review_topology")
    ):
        add_section(
            lines,
            contract_model.sow_section_title("reviewer_lanes"),
            [
                f"Reviewer Lane Inventory: {field(answers, 'reviewer_lane_inventory', 'none')}",
                f"Default Review Topology: {field(answers, 'default_review_topology', 'none')}",
                *contract_model.sow_section_policy_lines("reviewer_lanes"),
            ],
        )
    restrictions = [
        contract_model.render_command_restriction_record(item)
        for item in answers.get("command_restrictions", [])
    ]
    add_section(lines, contract_model.sow_section_title("command_restrictions"), restrictions)
    add_section(lines, contract_model.sow_section_title("applicable_standards"), bullets(lines_for(answers.get("applicable_standards"))))
    add_section(lines, contract_model.sow_section_title("language_rules"), bullets(language_rules(answers)))
    add_section(lines, contract_model.sow_section_title("code_review"), numbered(lines_for(answers.get("code_review_checklist"))))
    workflows = [render_workflow(item) for item in answers.get("workflows", [])]
    add_section(lines, contract_model.sow_section_title("workflows"), workflows)
    automation = answers.get("automation_orders", {})
    automation_lines = []
    if answers.get("include_automation_orders") or automation:
        automation_lines = [
            "Automation Orders File: "
            + optional_state_filename("Automation Orders File"),
            f"Preferred Scheduler Backend: {automation_preferred_backend(answers)}",
        ]
        automation_lines.extend(
            contract_model.render_automation_job_summary(job)
            for job in automation.get("jobs", [])
            if isinstance(job, dict)
        )
        automation_lines.append(AUTOMATION_AUTHORITY_RULE)
    add_section(lines, contract_model.sow_section_title("automation"), automation_lines)


def append_sow_source_sections(context: SowRenderContext) -> None:
    answers = context.answers
    lines = context.lines
    if answers.get("include_source_update"):
        add_section(
            lines,
            contract_model.sow_section_title("source_update"),
            [
                "Source Packs File: " + optional_state_filename("Source Packs File"),
                "Source Update File: " + optional_state_filename("Source Update File"),
                f"Source Registry Scope: {source_registry_scope(answers)}",
                f"Shared Framework Source Reference: {shared_framework_source_reference(answers)}",
                f"Default Review Cadence: {source_review_cadence(answers)}",
                *contract_model.sow_section_policy_lines("source_update"),
            ],
        )
    if answers.get("include_source_packs"):
        add_section(
            lines,
            contract_model.sow_section_title("source_packs"),
            [
                "Source Packs File: " + optional_state_filename("Source Packs File"),
                contract_model.sow_section_policy_lines("source_packs")[0],
                f"Shared Framework Source Reference: {shared_framework_source_reference(answers)}",
                contract_model.sow_section_policy_lines("source_packs")[1],
            ],
        )
    if answers.get("include_source_monitor_researcher"):
        add_section(
            lines,
            contract_model.sow_section_title("source_monitor"),
            [
                "Source Monitor Researcher File: "
                + optional_state_filename("Source Monitor Researcher Brief"),
                f"Role: {source_monitor_role(answers)}",
                f"Instruction Sources: {source_monitor_instruction_sources(answers)}",
                f"Source Data: {source_monitor_source_data(answers)}",
                f"Boundary: {source_monitor_boundary(answers)}",
            ],
        )


def append_sow_feedback_and_security_sections(context: SowRenderContext) -> None:
    answers = context.answers
    lines = context.lines
    if answers.get("include_framework_feedback"):
        add_section(
            lines,
            contract_model.sow_section_title("framework_feedback"),
            [
                "Framework Feedback File: "
                + optional_state_filename("Framework Feedback File"),
                *contract_model.sow_section_policy_lines("framework_feedback"),
            ],
        )
    if answers.get("include_reviewer_lane_feedback"):
        add_section(
            lines,
            contract_model.sow_section_title("reviewer_feedback"),
            [
                "Reviewer Lane Feedback File: "
                + optional_state_filename("Reviewer Lane Feedback File"),
                *contract_model.sow_section_policy_lines("reviewer_feedback"),
            ],
        )
    if answers.get("include_security_verification"):
        add_section(
            lines,
            contract_model.sow_section_title("security_verification"),
            [
                "Security Verification File: "
                + optional_state_filename("Security Verification File"),
                f"Security Policy File: {security_policy_file(answers)}",
                *contract_model.sow_section_policy_lines("security_verification"),
                f"Profile Scope: {security_verification_profile_scope(answers)}",
                f"Default Target Policy: {security_verification_target_policy(answers)}",
            ],
        )


def append_sow_annexes(context: SowRenderContext) -> None:
    lines = context.lines
    annex_lines = [
        f"- {label}: {reference}"
        for label, reference in project_module_references(context.answers)
    ]
    if annex_lines:
        annex_lines.insert(0, ANNEX_CONFLICT_RULE)
    add_section(lines, contract_model.sow_section_title("annexes"), annex_lines)


def render_sow(answers: dict, *, effective_date: str | None = None) -> str:
    mode = bootstrap_mode(answers)
    commands = command_values(answers)
    batch_date = effective_date or render_date(answers)
    context = SowRenderContext(
        answers=answers,
        mode=mode,
        commands=commands,
        lines=sow_preamble(
            answers,
            mode,
            field(answers, "project_name"),
            commands,
            batch_date,
        ),
    )
    append_sow_review_sections(context)
    append_sow_project_sections(context)
    append_sow_execution_sections(context)
    append_sow_source_sections(context)
    append_sow_feedback_and_security_sections(context)
    append_sow_annexes(context)
    return "\n".join(context.lines).rstrip() + "\n"


@dataclass
class ProjectContractRenderContext:
    answers: dict
    mode: str
    commands: dict[str, str]
    runtime_standards: str
    lines: list[str]


def project_contract_preamble(
    answers: dict,
    project_name: str,
    effective_date: str,
) -> list[str]:
    return [
        contract_model.CONTRACT_FORMAT_MARKER,
        "# Runtime Project Contract",
        "",
        f"Project: {project_name}",
        f"Date: {effective_date}",
        "",
        contract_model.PROJECT_PREAMBLE_RULE,
        "",
        contract_model.PROJECT_AUTHORITY_TEXT,
        "",
    ]


def append_project_contract_active_sections(
    context: ProjectContractRenderContext,
    framework_ref: str,
    project_kind: str,
    contract_root_ref: str,
) -> None:
    answers = context.answers
    commands = context.commands
    lines = context.lines

    def owned(owner: str) -> list[str]:
        return section_owned_definition_lines(
            owner,
            answers,
            context.mode,
            context.commands,
            context.runtime_standards,
        )

    runtime_stack = runtime_deferred_value(
        answers,
        "tech_stack",
        contract_model.MINIMAL_STACK_DEFERRAL,
    )
    runtime_architecture = runtime_deferred_value(
        answers,
        "architecture",
        contract_model.MINIMAL_ARCHITECTURE_DEFERRAL,
    )
    stack_lines = [
        f"- Languages and frameworks: {runtime_stack}",
        f"- Architecture: {runtime_architecture}",
    ]
    dependencies = lines_for(answers.get("key_dependencies"))
    if dependencies:
        stack_lines.append(f"- Key dependencies: {', '.join(dependencies)}")
    directories = lines_for(answers.get("key_directories"))
    if directories:
        stack_lines.append(f"- Key directories: {', '.join(directories)}")
    stack_lines.extend(owned("active_stack"))
    add_section(lines, contract_model.project_section_title("active_stack"), stack_lines)
    add_section(
        lines,
        contract_model.project_section_title("active_modules"),
        [
            f"- {label}: {reference}"
            for label, reference in project_module_references(answers)
        ]
        + owned("active_modules"),
    )
    add_section(lines, contract_model.project_section_title("project_vocabulary"), bullets(lines_for(answers.get("project_vocabulary"))))
    add_section(
        lines,
        contract_model.project_section_title("common_commands"),
        [
            f"- {spec.runtime_label}: {commands[spec.deferral_field]}"
            for spec in contract_model.COMMAND_SPECS
        ],
    )
    add_section(
        lines,
        contract_model.project_section_title("framework_verification"),
        contract_model.framework_verification_command_lines(
            framework_ref,
            project_kind=project_kind,
            contract_root_ref=contract_root_ref,
            runner=field(
                answers,
                "framework_verification_runner",
                FRAMEWORK_VERIFICATION_RUNNER_PLACEHOLDER,
            ),
        )
        + owned("framework_verification"),
    )
    deliverables = [
        contract_model.render_structured_record(
            "deliverables",
            {
                spec.key: runtime_deliverable_value(
                    item.get(spec.key),
                    contract_model.MINIMAL_DELIVERABLE_VALUES_BY_KEY[spec.key],
                    context.mode,
                )
                for spec in contract_model.structured_field_specs("deliverables")
            },
        )
        for item in answers.get("deliverables", [])
    ]
    add_section(lines, contract_model.project_section_title("active_deliverables"), numbered(deliverables))
    add_section(
        lines,
        contract_model.project_section_title("acceptance_checklist"),
        bullets(lines_for(answers.get("acceptance_checklist"))),
    )
    add_section(
        lines,
        contract_model.project_section_title("active_scope"),
        [
            "In scope:",
            *runtime_scope_lines(
                answers,
                "in_scope",
                contract_model.MINIMAL_IN_SCOPE_DEFERRAL,
            ),
            "",
            "Out of scope:",
            *runtime_scope_lines(
                answers,
                "out_of_scope",
                contract_model.MINIMAL_OUT_OF_SCOPE_DEFERRAL,
            ),
        ],
    )
    add_section(
        lines,
        contract_model.project_section_title("active_workflows"),
        [f"- {render_runtime_workflow(item)}" for item in answers.get("workflows", [])],
    )
    review_routing = owned("review_routing")
    if (
        arbitration_panel_projection(answers)
        != contract_model.DEFAULT_ARBITRATION_PANEL_PROJECTION
    ):
        review_routing.append(f"- {contract_model.ARBITRATION_PANEL_RUNTIME_ROUTE}")
    add_section(
        lines,
        contract_model.project_section_title("review_routing"),
        review_routing,
    )
    canonical_routes = [
        f"- {route}"
        for key, route in contract_model.CANONICAL_DETAIL_RUNTIME_ROUTES.items()
        if lines_for(answers.get(key))
    ]
    add_section(
        lines,
        contract_model.project_section_title("canonical_routes"),
        canonical_routes,
    )
    add_section(lines, contract_model.project_section_title("minimal_deferrals"), bullets(minimal_deferrals(answers)))
    constraints = dedupe([*lines_for(answers.get("constraints")), *language_rules(answers)])
    add_section(
        lines,
        contract_model.project_section_title("constraints"),
        bullets(constraints) + owned("constraints"),
    )
    add_section(
        lines,
        contract_model.project_section_title("applicable_standards"),
        bullets(lines_for(answers.get("applicable_standards"))),
    )
    add_section(
        lines,
        contract_model.project_section_title("critical_surfaces"),
        bullets(lines_for(answers.get("critical_surfaces")))
        + owned("critical_surfaces"),
    )
    if security_policy_file(answers) == "inline in this SOW":
        add_section(lines, contract_model.project_section_title("security_policy"), bullets(lines_for(answers.get("security_policy_terms"))))
    add_section(
        lines,
        contract_model.project_section_title("version_control"),
        bullets(lines_for(answers.get("version_control_profile")))
        + owned("version_control"),
    )
    add_section(lines, contract_model.project_section_title("memory_boundary"), bullets(memory_boundary_lines(answers)))
    add_section(lines, contract_model.project_section_title("verification_profiles"), bullets(lines_for(answers.get("verification_profiles"))))
    add_section(
        lines,
        contract_model.project_section_title("approval_boundaries"),
        bullets(lines_for(answers.get("approval_boundaries")))
        + owned("approval_boundaries"),
    )
    add_section(
        lines,
        contract_model.project_section_title("acquisition_boundary"),
        bullets(lines_for(answers.get("acquisition_boundary")))
        + owned("acquisition_boundary"),
    )


def append_project_contract_definitions(
    context: ProjectContractRenderContext,
) -> None:
    answers = context.answers
    lines = context.lines
    lines.extend([contract_model.project_section_title("definitions"), ""])
    lines.extend(
        rendered_definition_lines(
            "project",
            answers,
            context.mode,
            context.commands,
            context.runtime_standards,
            prefix="- ",
        )
    )
    lines.append("")
    restrictions = bullets(
        [
            contract_model.render_command_restriction_record(item)
            for item in answers.get("command_restrictions", [])
        ]
    )
    add_section(lines, contract_model.project_section_title("command_restrictions"), restrictions)
    add_section(
        lines,
        contract_model.project_section_title("auxiliary_tools"),
        [
            f"- {render_runtime_auxiliary_tool(item)}"
            for item in answers.get("auxiliary_tools", [])
        ],
    )
    add_section(
        lines,
        contract_model.project_section_title("loading_rule"),
        list(PROJECT_LOADING_RULE_LINES),
    )


def render_project_contract(
    answers: dict,
    framework_ref: str = "{{FRAMEWORK_ROOT}}",
    *,
    project_kind: str = "downstream",
    contract_root_ref: str = ".",
    effective_date: str | None = None,
) -> str:
    batch_date = effective_date or render_date(answers)
    context = ProjectContractRenderContext(
        answers=answers,
        mode=bootstrap_mode(answers),
        commands=command_values(answers),
        runtime_standards=runtime_deferred_value(
            answers,
            "language_runtime_standards",
            contract_model.MINIMAL_RUNTIME_STANDARDS_DEFERRAL,
        ),
        lines=project_contract_preamble(
            answers,
            field(answers, "project_name"),
            batch_date,
        ),
    )
    append_project_contract_active_sections(
        context,
        framework_ref,
        project_kind,
        contract_root_ref,
    )
    append_project_contract_definitions(context)
    return integration_registry.render_project_file_references(
        "\n".join(context.lines).rstrip() + "\n",
        contract_root_ref,
    )


def render_entrypoint(
    runtime: str,
    framework_ref: str,
    *,
    contract_root_ref: str = ".",
) -> tuple[str, str]:
    template_rel, output_name = ENTRYPOINT_TEMPLATES[runtime]
    text = read_framework_source_text(
        template_rel,
        description=f"runtime entrypoint template {template_rel}",
    )
    text = integration_registry.render_template_text(
        text,
        framework_ref,
        contract_root_ref,
        template_label=template_rel,
    )
    return output_name, text


def planned_output_graph_errors(output_names: Iterable[str]) -> list[str]:
    """Reject file plans where one output must also be an output directory."""

    paths = [(name, Path(name)) for name in output_names]
    errors: list[str] = []
    by_path: dict[Path, list[str]] = {}
    for name, path in paths:
        by_path.setdefault(path, []).append(name)
    for names in by_path.values():
        if len(names) > 1:
            errors.append(
                "multiple bootstrap outputs resolve to the same target: "
                + ", ".join(sorted(names))
            )
    for parent_name, parent in paths:
        for child_name, child in paths:
            if parent == child:
                continue
            try:
                relative = child.relative_to(parent)
            except ValueError:
                continue
            if relative.parts:
                errors.append(
                    "bootstrap output target is both a file and an ancestor directory: "
                    f"{parent_name} contains {child_name}"
                )
    return sorted(set(errors))


def preflight_writes(project_root: Path, outputs: dict[str, str]) -> list[str]:
    """Validate one create-only bootstrap output graph before its transaction."""

    overwrite_errors = [
        "initial bootstrap refuses to overwrite existing file; a verified current "
        "instance uses project refresh, while any other framework-generated surface "
        f"requires reviewed manual update: {project_root / name}"
        for name in outputs
        if (project_root / name).exists()
    ]
    path_errors = [
        error
        for name in outputs
        for error in safe_paths.output_path_errors(
            project_root / name,
            project_root,
            "target project root",
        )
    ]
    return [
        *planned_output_graph_errors(outputs),
        *path_errors,
        *overwrite_errors,
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render framework project files from structured init answers.",
        allow_abbrev=False,
    )
    parser.add_argument("--answers", required=True, help="Path to a JSON file with collected init answers.")
    parser.add_argument("--project-root", required=True, help="Target project root.")
    parser.add_argument(
        "--project-kind",
        choices=sorted(contract_model.PROJECT_KINDS),
        default="downstream",
        help="Registered project layout. The product command supports downstream projects.",
    )
    parser.add_argument(
        "--contract-root",
        help="Safe project-relative directory for generated contract and state files. Defaults to the project root.",
    )
    parser.add_argument(
        "--setup-profile",
        help="Optional JSON setup profile whose allowed defaults fill only answer fields that are absent.",
    )
    parser.add_argument("--runtime", choices=sorted(ENTRYPOINT_TEMPLATES), help="Target downstream runtime.")
    parser.add_argument(
        "--runtime-wrapper",
        action="append",
        default=[],
        help=(
            "Family-local repo-scoped wrapper ID to manage as an immutable project "
            "output. Repeat for multiple wrappers; omit for none."
        ),
    )
    parser.add_argument("--framework-ref", help="Reference written into runtime entrypoints. Defaults to the executing framework checkout. Use a repo-relative path, environment variable, or stable mount path for public/shared projects.")
    parser.add_argument(
        "--framework-revision-policy",
        choices=sorted(FRAMEWORK_REVISION_POLICIES),
        required=True,
        help="Record whether the selected framework reference is intentionally live or operator-pinned. Bootstrap never fetches or updates that reference.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print a summary of outputs and warnings without writing files.")
    parser.add_argument(
        "--approve-write-plan-sha256",
        action="append",
        default=[],
        metavar="SHA256",
        help=(
            "Approve the complete rendered write-plan digest reported by the "
            "reviewed dry run. Required exactly once for every write."
        ),
    )
    parser.add_argument("--create-contract-root", action="store_true", help="Confirm that a missing nested contract root may be created inside an existing project root.")
    return parser


@dataclass(frozen=True)
class BootstrapOptions:
    answers: str
    project_root: str
    project_kind: str
    contract_root: str | None
    setup_profile: str | None
    runtime: str | None
    framework_ref: str | None
    dry_run: bool
    create_contract_root: bool
    runtime_wrappers: tuple[str, ...] = ()
    framework_revision_policy: str | None = None
    approve_write_plan_sha256: tuple[str, ...] = ()


def parse_options(argv: list[str] | None = None) -> BootstrapOptions:
    args = build_parser().parse_args(argv)
    return BootstrapOptions(
        answers=args.answers,
        project_root=args.project_root,
        project_kind=args.project_kind,
        contract_root=args.contract_root,
        setup_profile=args.setup_profile,
        runtime=args.runtime,
        runtime_wrappers=tuple(args.runtime_wrapper),
        framework_ref=args.framework_ref,
        framework_revision_policy=args.framework_revision_policy,
        dry_run=args.dry_run,
        create_contract_root=args.create_contract_root,
        approve_write_plan_sha256=tuple(args.approve_write_plan_sha256),
    )


def transaction_state_requires_recovery(
    recovery: bootstrap_transaction.BootstrapRecoveryStatus,
) -> bool:
    """Return whether ordinary bootstrap work must stop for transaction state."""

    return (
        recovery.state != "clean"
        or bool(recovery.errors)
        or recovery.transaction_id is not None
        or recovery.can_rollback
        or recovery.can_finalize
    )


def transaction_recovery_route(
    recovery: bootstrap_transaction.BootstrapRecoveryStatus,
) -> dict[str, object] | None:
    """Return the one ID-bound route authorized by a recovery status, if any."""

    if recovery.transaction_id is None:
        return None
    if recovery.can_finalize == recovery.can_rollback:
        return None
    return {
        "command": "recover",
        "action": "finalize" if recovery.can_finalize else "rollback",
        "approve_transaction_id": recovery.transaction_id,
    }


def bootstrap_recovery_payload(
    options: BootstrapOptions,
    project_root: Path,
    recovery: bootstrap_transaction.BootstrapRecoveryStatus,
) -> dict[str, object]:
    """Describe transaction state without loading any generated project inputs."""

    errors = list(recovery.errors)
    if recovery.state == "active" and not errors:
        errors.append(
            "a bootstrap transaction is active; wait for its owner and inspect "
            "transaction state before retrying"
        )
    elif not errors and recovery.state != "clean":
        errors.append(
            "bootstrap transaction controls require recovery inspection before "
            "ordinary project setup"
        )
    return {
        "status": "recovery-required",
        "transaction_state": recovery.state,
        "project_kind": options.project_kind,
        "project_root": str(project_root),
        "runtime": options.runtime,
        "transaction_id": recovery.transaction_id,
        "phase": recovery.phase,
        "can_rollback": recovery.can_rollback,
        "can_finalize": recovery.can_finalize,
        "recovery_route": transaction_recovery_route(recovery),
        "errors": errors,
    }


@dataclass(frozen=True, slots=True)
class BootstrapProjectRootPreflight:
    """One resolved project-root binding inspected before any bootstrap inputs."""

    raw_project_root: Path
    project_root: Path
    node_identity: tuple[int, int, int] | None


def bootstrap_project_root_binding_errors(
    preflight: BootstrapProjectRootPreflight,
) -> list[str]:
    """Reject raw-path or canonical-node drift from the transaction preflight."""

    _raw, current_root, resolution_errors = resolve_user_path(
        str(preflight.raw_project_root),
        "target project root",
    )
    errors = list(resolution_errors)
    if not resolution_errors and current_root != preflight.project_root:
        errors.append(
            "target project root resolved to a different location after transaction "
            "preflight"
        )
    try:
        errors.extend(
            safe_paths.output_path_errors(
                preflight.raw_project_root,
                None,
                "target project root",
            )
        )
    except (OSError, RuntimeError, ValueError) as exc:
        errors.append(f"target project root binding could not be inspected: {exc}")
    try:
        current_metadata = preflight.project_root.lstat()
    except FileNotFoundError:
        current_identity = None
    except OSError as exc:
        errors.append(f"target project root binding could not be inspected: {exc}")
        current_identity = None
    else:
        current_identity = _discovery_node_identity(current_metadata)
    if current_identity != preflight.node_identity:
        errors.append(
            "target project root binding changed after transaction preflight"
        )
    return sorted(set(errors))


def bootstrap_root_binding_recovery_payload(
    options: BootstrapOptions,
    preflight: BootstrapProjectRootPreflight,
    errors: Iterable[str],
) -> dict[str, object]:
    recovery = bootstrap_transaction.BootstrapRecoveryStatus(
        state="invalid",
        transaction_id=None,
        phase=None,
        operation_paths=(),
        can_rollback=False,
        can_finalize=False,
        errors=tuple(errors),
    )
    return bootstrap_recovery_payload(options, preflight.project_root, recovery)


def bootstrap_transaction_recheck_payload(
    options: BootstrapOptions,
    preflight: BootstrapProjectRootPreflight,
) -> dict[str, object] | None:
    """Recheck transaction controls before project-local classification begins."""

    if (
        preflight.node_identity is None
        or preflight.node_identity[2] != stat.S_IFDIR
    ):
        return None
    try:
        recovery = bootstrap_transaction.transaction_recovery_status(
            preflight.project_root
        )
    except (OSError, ValueError) as exc:
        recovery = bootstrap_transaction.BootstrapRecoveryStatus(
            state="invalid",
            transaction_id=None,
            phase=None,
            operation_paths=(),
            can_rollback=False,
            can_finalize=False,
            errors=(f"transaction state could not be reinspected: {exc}",),
        )
    if not transaction_state_requires_recovery(recovery):
        return None
    return bootstrap_recovery_payload(options, preflight.project_root, recovery)


def bootstrap_transaction_preflight(
    options: BootstrapOptions,
) -> tuple[
    BootstrapProjectRootPreflight | None,
    dict[str, object] | None,
    int | None,
]:
    """Inspect transaction controls before answers, profiles, or project inputs."""

    raw_project_root, project_root, root_errors = resolve_user_path(
        options.project_root,
        "target project root",
    )
    if root_errors:
        recovery = bootstrap_transaction.BootstrapRecoveryStatus(
            state="invalid",
            transaction_id=None,
            phase=None,
            operation_paths=(),
            can_rollback=False,
            can_finalize=False,
            errors=tuple(root_errors),
        )
        return (
            None,
            bootstrap_recovery_payload(options, project_root, recovery),
            EXIT_RECOVERY_REQUIRED,
        )
    try:
        raw_root_metadata = raw_project_root.lstat()
    except FileNotFoundError:
        raw_root_metadata = None
    except OSError as exc:
        recovery = bootstrap_transaction.BootstrapRecoveryStatus(
            state="invalid",
            transaction_id=None,
            phase=None,
            operation_paths=(),
            can_rollback=False,
            can_finalize=False,
            errors=(f"target project root could not be inspected: {exc}",),
        )
        return (
            None,
            bootstrap_recovery_payload(options, project_root, recovery),
            EXIT_RECOVERY_REQUIRED,
        )
    if raw_root_metadata is not None and stat.S_ISLNK(raw_root_metadata.st_mode):
        recovery = bootstrap_transaction.BootstrapRecoveryStatus(
            state="invalid",
            transaction_id=None,
            phase=None,
            operation_paths=(),
            can_rollback=False,
            can_finalize=False,
            errors=("target project root must not be a symbolic link",),
        )
        return (
            None,
            bootstrap_recovery_payload(options, project_root, recovery),
            EXIT_RECOVERY_REQUIRED,
        )
    try:
        root_metadata = project_root.lstat()
    except FileNotFoundError:
        return (
            BootstrapProjectRootPreflight(
                raw_project_root=raw_project_root,
                project_root=project_root,
                node_identity=None,
            ),
            None,
            None,
        )
    except OSError as exc:
        recovery = bootstrap_transaction.BootstrapRecoveryStatus(
            state="invalid",
            transaction_id=None,
            phase=None,
            operation_paths=(),
            can_rollback=False,
            can_finalize=False,
            errors=(f"target project root could not be inspected: {exc}",),
        )
        return (
            None,
            bootstrap_recovery_payload(options, project_root, recovery),
            EXIT_RECOVERY_REQUIRED,
        )
    preflight = BootstrapProjectRootPreflight(
        raw_project_root=raw_project_root,
        project_root=project_root,
        node_identity=_discovery_node_identity(root_metadata),
    )
    if not stat.S_ISDIR(root_metadata.st_mode):
        return preflight, None, None
    try:
        recovery = bootstrap_transaction.transaction_recovery_status(project_root)
    except (OSError, ValueError) as exc:
        recovery = bootstrap_transaction.BootstrapRecoveryStatus(
            state="invalid",
            transaction_id=None,
            phase=None,
            operation_paths=(),
            can_rollback=False,
            can_finalize=False,
            errors=(f"transaction state could not be inspected: {exc}",),
        )
    if not transaction_state_requires_recovery(recovery):
        return preflight, None, None
    return (
        preflight,
        bootstrap_recovery_payload(options, project_root, recovery),
        EXIT_RECOVERY_REQUIRED,
    )


@dataclass
class BootstrapInputs:
    options: BootstrapOptions
    answers_path: Path
    answers_bytes: bytes | None
    answers: object | None
    setup_profile_path: Path | None
    setup_profile_bytes: bytes | None
    setup_profile: object | None
    effective_answers: object
    profile_applied: list[str]
    profile_overridden: list[str]
    raw_project_root: Path
    project_root: Path
    framework_root: Path
    contract_root: Path
    contract_root_ref: str
    answers_source: str | None
    setup_profile_source: str | None
    framework_ref: str
    framework_reference_status: str
    framework_reference_errors: list[str]
    framework_reference_binding_warnings: list[str]
    input_errors: list[str]
    contract_root_errors: list[str]


def load_bootstrap_inputs(
    options: BootstrapOptions,
    *,
    project_root_preflight: BootstrapProjectRootPreflight | None = None,
) -> BootstrapInputs:
    if project_root_preflight is None:
        raw_project_root, project_root, project_root_errors = resolve_user_path(
            options.project_root,
            "target project root",
        )
    else:
        raw_project_root = project_root_preflight.raw_project_root
        project_root = project_root_preflight.project_root
        project_root_errors = []
    answers_path, answers_bytes, answers, input_errors = load_json_input(
        options.answers,
        "bootstrap answers file",
    )
    if options.setup_profile is not None:
        (
            setup_profile_path,
            setup_profile_bytes,
            setup_profile,
            setup_profile_input_errors,
        ) = load_json_input(options.setup_profile, "setup profile file")
        input_errors.extend(setup_profile_input_errors)
    else:
        setup_profile_path = None
        setup_profile_bytes = None
        setup_profile = None
    effective_answers, profile_applied, profile_overridden = apply_setup_profile(
        answers,
        setup_profile,
    )
    input_errors.extend(project_root_errors)
    contract_root, contract_root_ref, contract_root_errors = resolve_contract_root(
        project_root,
        options.contract_root,
    )
    answers_source = project_relative_input_source(answers_path, project_root)
    setup_profile_source = (
        project_relative_input_source(setup_profile_path, project_root)
        if setup_profile_path is not None
        else None
    )
    raw_framework_ref = (
        options.framework_ref
        if options.framework_ref is not None
        else str(REPO_ROOT)
    )
    try:
        framework_ref = safe_paths.canonical_framework_reference(raw_framework_ref)
    except ValueError as exc:
        input_errors.append(str(exc))
        framework_ref = raw_framework_ref
    (
        framework_reference_status,
        framework_reference_errors,
        framework_reference_binding_warnings,
    ) = framework_reference_binding(
        framework_ref,
        project_root,
        REPO_ROOT,
    )
    return BootstrapInputs(
        options=options,
        answers_path=answers_path,
        answers_bytes=answers_bytes,
        answers=answers,
        setup_profile_path=setup_profile_path,
        setup_profile_bytes=setup_profile_bytes,
        setup_profile=setup_profile,
        effective_answers=effective_answers,
        profile_applied=profile_applied,
        profile_overridden=profile_overridden,
        raw_project_root=raw_project_root,
        project_root=project_root,
        framework_root=REPO_ROOT,
        contract_root=contract_root,
        contract_root_ref=contract_root_ref,
        answers_source=answers_source,
        setup_profile_source=setup_profile_source,
        framework_ref=framework_ref,
        framework_reference_status=framework_reference_status,
        framework_reference_errors=framework_reference_errors,
        framework_reference_binding_warnings=framework_reference_binding_warnings,
        input_errors=input_errors,
        contract_root_errors=contract_root_errors,
    )


def bootstrap_validation_errors(inputs: BootstrapInputs) -> list[str]:
    options = inputs.options
    policy = contract_model.project_layout_policy(options.project_kind)
    effective_answers = inputs.effective_answers
    errors = list(inputs.input_errors)
    errors.extend(inputs.framework_reference_errors)
    if inputs.setup_profile is not None:
        errors.extend(validate_setup_profile(inputs.setup_profile))
    if inputs.answers is not None:
        errors.extend(
            validate_answers(
                effective_answers,
                automation_project_root=inputs.project_root,
                automation_manifest_path=inputs.contract_root / "AUTOMATION_ORDERS.json",
                require_existing_automation_project_root=False,
            )
        )
    if (
        isinstance(effective_answers, dict)
        and "framework_verification_runner" not in effective_answers
    ):
        errors.append(
            "missing required bootstrap answer key: framework_verification_runner; record the exact runner reported by scripts/check_prereqs.py or an approved wrapper"
        )
    if (
        policy.require_explicit_render_date
        and isinstance(effective_answers, dict)
        and not str(effective_answers.get("date", "")).strip()
    ):
        errors.append(
            f"{policy.kind} project kind requires an explicit date in retained answers for reproducible rendering"
        )
    errors.extend(
        safe_paths.output_path_errors(
            inputs.raw_project_root,
            None,
            "target project root",
        )
    )
    errors.extend(inputs.contract_root_errors)
    if inputs.project_root.exists() and not inputs.project_root.is_dir():
        errors.append(f"target project root must be a directory: {inputs.project_root}")
    if policy.runtime_required and options.runtime is None:
        errors.append(f"{policy.kind} project kind requires --runtime")
    if policy.runtime_forbidden and options.runtime is not None:
        errors.append(
            f"{policy.kind} project kind must not set --runtime"
        )
    if len(options.runtime_wrappers) != len(set(options.runtime_wrappers)):
        errors.append("--runtime-wrapper values must not contain duplicates")
    if not policy.runtime_wrappers_allowed and options.runtime_wrappers:
        errors.append(
            f"{policy.kind} project kind must not select runtime wrappers"
        )
    if policy.runtime_wrappers_allowed and options.runtime is not None:
        try:
            integration_registry.wrapper_output_map(
                options.runtime,
                list(options.runtime_wrappers),
                inputs.framework_root,
            )
        except (KeyError, ValueError) as exc:
            errors.append(str(exc))
    if policy.require_nested_contract_root and options.contract_root is None:
        errors.append(f"{policy.kind} project kind requires --contract-root")
    if options.framework_revision_policy not in FRAMEWORK_REVISION_POLICIES:
        errors.append(
            "framework revision policy must be one of: "
            + ", ".join(sorted(FRAMEWORK_REVISION_POLICIES))
        )
    if isinstance(effective_answers, dict) and (
        not policy.manages_runtime_entrypoint or options.runtime is not None
    ):
        errors.extend(
            existing_instance_bootstrap_errors(
                inputs.project_root,
                inputs.contract_root_ref,
                effective_answers,
                options.runtime,
                options.project_kind,
                tuple(sorted(options.runtime_wrappers)),
            )
        )
    errors.extend(
        project_layout_errors(
            inputs.project_root,
            inputs.contract_root,
            inputs.contract_root_ref,
            inputs.framework_root,
            options.project_kind,
        )
    )
    if isinstance(effective_answers, dict):
        errors.extend(
            referenced_project_file_errors(
                effective_answers,
                inputs.project_root,
            )
        )
    if not inputs.project_root.exists():
        errors.append(
            f"target project root does not exist: {inputs.project_root}. Create and approve the project root before running bootstrap; lifecycle transactions do not create it."
        )
    if (
        inputs.project_root.exists()
        and inputs.contract_root != inputs.project_root
        and not inputs.contract_root.exists()
        and not options.create_contract_root
    ):
        errors.append(
            f"contract root does not exist: {inputs.contract_root}. Confirm creation, then rerun with --create-contract-root."
        )
    return errors


def bootstrap_error_payload(
    inputs: BootstrapInputs,
    answers: dict,
    errors: list[str],
) -> dict[str, object]:
    return {
        "bootstrap_mode": bootstrap_mode(answers),
        "contract_root": inputs.contract_root_ref,
        "errors": errors,
        "project_kind": inputs.options.project_kind,
        "project_root": str(inputs.project_root),
        "runtime": inputs.options.runtime,
    }


def bootstrap_setup_profile_summary(
    inputs: BootstrapInputs,
) -> dict[str, object] | None:
    if inputs.setup_profile_bytes is None:
        return None
    return {
        "applied_fields": inputs.profile_applied,
        "overridden_fields": inputs.profile_overridden,
        "sha256": sha256_bytes(inputs.setup_profile_bytes),
    }


def _bootstrap_write_plan_approval_payload(
    inputs: BootstrapInputs,
    outputs: dict[str, str],
    framework_identity: FrameworkIdentity,
    warnings: object,
    *,
    effective_date: str,
) -> dict[str, object]:
    """Build the domain-separated receipt behind one bootstrap write approval."""

    if inputs.answers_bytes is None:
        raise ValueError("bootstrap write-plan approval requires validated answer bytes")
    if not isinstance(warnings, list) or not all(
        isinstance(warning, str) for warning in warnings
    ):
        raise ValueError("bootstrap summary warnings must be a list of strings")
    if not isinstance(inputs.effective_answers, dict):
        raise ValueError("bootstrap write-plan approval requires validated answers")
    names = planned_output_names(
        inputs.effective_answers,
        inputs.options.runtime,
        project_kind=inputs.options.project_kind,
        contract_root_ref=inputs.contract_root_ref,
        runtime_wrappers=tuple(sorted(inputs.options.runtime_wrappers)),
    )
    if len(names) != len(set(names)) or set(outputs) != set(names):
        missing = sorted(set(names) - set(outputs))
        unexpected = sorted(set(outputs) - set(names))
        details: list[str] = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if unexpected:
            details.append("unexpected " + ", ".join(unexpected))
        raise ValueError(
            "rendered bootstrap outputs do not exactly match the planned output set"
            + (": " + "; ".join(details) if details else "")
        )
    return {
        "domain": BOOTSTRAP_WRITE_PLAN_APPROVAL_DOMAIN,
        "target": {
            "project_root": str(inputs.project_root),
            "project_root_identity": _bootstrap_target_identity(inputs.project_root),
            "contract_root": str(inputs.contract_root),
            "contract_root_ref": inputs.contract_root_ref,
            "contract_root_identity": _bootstrap_target_identity(inputs.contract_root),
            "create_contract_root": inputs.options.create_contract_root,
        },
        "project": {
            "kind": inputs.options.project_kind,
            "runtime": inputs.options.runtime,
            "runtime_wrappers": sorted(inputs.options.runtime_wrappers),
            "effective_date": effective_date,
        },
        "framework": {
            "reference": inputs.framework_ref,
            "revision_policy": inputs.options.framework_revision_policy,
            "reference_status": inputs.framework_reference_status,
            "content_sha256": framework_identity.content_sha256,
            "distribution_sha256": framework_identity.distribution_sha256,
            "effective_file_digests": [
                {"path": path, "sha256": digest}
                for path, digest in framework_identity.effective_file_digests
            ],
        },
        "inputs": {
            "answers_sha256": sha256_bytes(inputs.answers_bytes),
            "setup_profile_sha256": (
                None
                if inputs.setup_profile_bytes is None
                else sha256_bytes(inputs.setup_profile_bytes)
            ),
        },
        "warnings": list(warnings),
        "outputs": [
            {
                "path": name,
                "sha256": sha256_bytes(outputs[name].encode("utf-8")),
            }
            for name in names
        ],
    }


def bootstrap_write_plan_sha256(
    inputs: BootstrapInputs,
    outputs: dict[str, str],
    framework_identity: FrameworkIdentity,
    warnings: object,
    *,
    effective_date: str,
) -> str:
    """Digest the complete rendered bootstrap plan approved for one write."""

    return canonical_json_digest(
        _bootstrap_write_plan_approval_payload(
            inputs,
            outputs,
            framework_identity,
            warnings,
            effective_date=effective_date,
        )
    )


@dataclass
class BootstrapWritePlan:
    summary: dict[str, object]
    errors: list[str]
    effective_date: str
    framework_identity: FrameworkIdentity


def build_bootstrap_write_plan(
    inputs: BootstrapInputs,
    answers: dict,
) -> BootstrapWritePlan:
    options = inputs.options
    effective_date = render_date(answers)
    framework_identity = capture_framework_identity(inputs.framework_root)
    summary = summary_payload(
        answers,
        inputs.project_root,
        options.runtime,
        inputs.answers_path,
        inputs.framework_root,
        inputs.framework_ref,
        project_kind=options.project_kind,
        contract_root_ref=inputs.contract_root_ref,
        setup_profile_summary=bootstrap_setup_profile_summary(inputs),
        effective_date=effective_date,
        runtime_wrappers=tuple(sorted(options.runtime_wrappers)),
    )
    summary["framework_revision_policy"] = options.framework_revision_policy
    summary["framework_reference_status"] = inputs.framework_reference_status
    summary_warnings = summary.get("warnings")
    if isinstance(summary_warnings, list):
        summary_warnings.extend(inputs.framework_reference_binding_warnings)
    summary["warnings_sha256"] = bootstrap_warnings_sha256(summary_warnings)
    errors = planned_output_graph_errors(
        planned_output_names(
            answers,
            options.runtime,
            project_kind=options.project_kind,
            contract_root_ref=inputs.contract_root_ref,
            runtime_wrappers=tuple(sorted(options.runtime_wrappers)),
        )
    )
    return BootstrapWritePlan(
        summary=summary,
        errors=errors,
        effective_date=effective_date,
        framework_identity=framework_identity,
    )


def render_bootstrap_write_outputs(
    inputs: BootstrapInputs,
    answers: dict,
    answers_bytes: bytes,
    effective_date: str,
    *,
    framework_identity: FrameworkIdentity | None = None,
) -> dict[str, str]:
    del answers_bytes  # The retained, fully materialized project input owns rerenders.
    options = inputs.options
    policy = contract_model.project_layout_policy(options.project_kind)
    materialized_answers = dict(answers)
    materialized_answers["date"] = effective_date
    outputs = render_output_files(
        materialized_answers,
        options.runtime,
        inputs.framework_ref,
        project_kind=options.project_kind,
        contract_root_ref=inputs.contract_root_ref,
        effective_date=effective_date,
        runtime_wrappers=tuple(sorted(options.runtime_wrappers)),
    )
    input_name = project_relative_output(
        inputs.contract_root_ref,
        project_input.INPUT_NAME,
    )
    revision_policy = options.framework_revision_policy
    if (
        not isinstance(revision_policy, str)
        or revision_policy not in FRAMEWORK_REVISION_POLICIES
    ):
        raise ValueError("bootstrap rendering requires an explicit framework revision policy")
    input_text = project_input.render_project_input(
        project_kind=options.project_kind,
        contract_root=inputs.contract_root_ref,
        runtime=options.runtime,
        framework_reference=inputs.framework_ref,
        framework_revision_policy=revision_policy,
        answers=materialized_answers,
        runtime_wrappers=tuple(sorted(options.runtime_wrappers)),
    )
    outputs[input_name] = input_text
    managed_files, immutable_files, mutable_files = project_instance_file_sets(
        answers=materialized_answers,
        runtime=options.runtime,
        project_kind=options.project_kind,
        contract_root_ref=inputs.contract_root_ref,
        runtime_wrappers=tuple(sorted(options.runtime_wrappers)),
    )
    manifest_name = INSTANCE_MANIFEST
    outputs[manifest_name] = render_instance_manifest(
        input_bytes=input_text.encode("utf-8"),
        project_kind=options.project_kind,
        contract_root_ref=inputs.contract_root_ref,
        runtime=options.runtime,
        framework_reference=inputs.framework_ref,
        framework_revision_policy=revision_policy,
        framework_reference_status=inputs.framework_reference_status,
        managed_files=managed_files,
        immutable_files=immutable_files,
        mutable_files=mutable_files,
        runtime_wrapper_outputs=(
            integration_registry.wrapper_output_map(
                options.runtime,
                list(options.runtime_wrappers),
                inputs.framework_root,
            )
            if policy.runtime_wrappers_allowed and options.runtime is not None
            else {}
        ),
        rendered_outputs=outputs,
        active_profiles=active_project_profiles(
            materialized_answers,
            project_kind=options.project_kind,
        ),
        effective_date=effective_date,
        framework_identity=framework_identity,
    )
    return outputs


def write_bootstrap_outputs(
    inputs: BootstrapInputs,
    answers: dict,
    outputs: dict[str, str],
    *,
    framework_identity: FrameworkIdentity,
) -> bootstrap_transaction.BootstrapWriteResult:
    names = planned_output_names(
        answers,
        inputs.options.runtime,
        project_kind=inputs.options.project_kind,
        contract_root_ref=inputs.contract_root_ref,
        runtime_wrappers=tuple(sorted(inputs.options.runtime_wrappers)),
    )
    expected_preimages: dict[str, str | None] = {name: None for name in names}

    def verify_installed_project() -> None:
        before = capture_framework_identity(inputs.framework_root)
        if before != framework_identity:
            raise ValueError(
                "selected framework identity changed between bootstrap planning "
                "and post-install verification"
            )
        # Imported lazily because conformance_check imports the instance linter,
        # whose renderer dependency is this module.
        import conformance_check

        selected_profiles = active_project_profiles(
            answers,
            project_kind=inputs.options.project_kind,
        )
        report = conformance_check.run_profiles(
            selected_profiles,
            inputs.project_root,
            contract_root=inputs.contract_root,
            contract_root_ref=inputs.contract_root_ref,
            project_kind=inputs.options.project_kind,
        )
        after = capture_framework_identity(inputs.framework_root)
        if after != framework_identity:
            raise ValueError(
                "selected framework identity changed while bootstrap conformance "
                "was running"
            )
        report_status = report.get("status")
        report_errors = report.get("errors")
        report_warnings = report.get("warnings")
        if (
            not isinstance(report_errors, list)
            or not all(isinstance(item, str) for item in report_errors)
            or not isinstance(report_warnings, list)
            or not all(isinstance(item, str) for item in report_warnings)
        ):
            raise ValueError(
                "bootstrap post-install profile conformance returned malformed diagnostics"
            )
        if (
            report_errors
            or report_status not in {"pass", "warn"}
            or (report_status == "pass" and bool(report_warnings))
            or (report_status == "warn" and not report_warnings)
            # Initial bootstrap has no durable warning-approval receipt.  A
            # planning-warning acknowledgement must not waive live
            # post-install conformance warnings.
            or bool(report_warnings)
        ):
            diagnostics = {
                "errors": report_errors,
                "warnings": report_warnings,
            }
            raise ValueError(
                "bootstrap post-install profile conformance did not pass: "
                + json.dumps(diagnostics, sort_keys=True)
            )
    return bootstrap_transaction.transactional_write_outputs(
        inputs.project_root,
        [(name, outputs[name]) for name in names],
        force=False,
        expected_preimages=expected_preimages,
        post_install_verifier=verify_installed_project,
    )


def main(argv: list[str] | None = None) -> int:
    options = parse_options(argv)
    (
        project_root_preflight,
        recovery_payload,
        recovery_exit,
    ) = bootstrap_transaction_preflight(options)
    if recovery_payload is not None and recovery_exit is not None:
        print(json.dumps(recovery_payload, indent=2, sort_keys=True))
        return recovery_exit
    if project_root_preflight is None:
        print(
            json.dumps(
                {
                    "errors": [
                        "target project root preflight did not produce a stable binding"
                    ]
                },
                indent=2,
                sort_keys=True,
            )
        )
        return EXIT_RECOVERY_REQUIRED
    binding_errors = bootstrap_project_root_binding_errors(project_root_preflight)
    if binding_errors:
        print(
            json.dumps(
                bootstrap_root_binding_recovery_payload(
                    options,
                    project_root_preflight,
                    binding_errors,
                ),
                indent=2,
                sort_keys=True,
            )
        )
        return EXIT_RECOVERY_REQUIRED
    inputs = load_bootstrap_inputs(
        options,
        project_root_preflight=project_root_preflight,
    )
    binding_errors = bootstrap_project_root_binding_errors(project_root_preflight)
    if binding_errors:
        print(
            json.dumps(
                bootstrap_root_binding_recovery_payload(
                    options,
                    project_root_preflight,
                    binding_errors,
                ),
                indent=2,
                sort_keys=True,
            )
        )
        return EXIT_RECOVERY_REQUIRED
    recovery_payload = bootstrap_transaction_recheck_payload(
        options,
        project_root_preflight,
    )
    if recovery_payload is not None:
        print(json.dumps(recovery_payload, indent=2, sort_keys=True))
        return EXIT_RECOVERY_REQUIRED
    errors = bootstrap_validation_errors(inputs)
    effective_answers = inputs.effective_answers
    if not isinstance(effective_answers, dict):
        print(json.dumps({"errors": errors}, indent=2, sort_keys=True))
        return 1
    answers_bytes = inputs.answers_bytes
    if answers_bytes is None:
        errors.append("validated bootstrap answers bytes are unavailable")
    if errors:
        print(
            json.dumps(
                bootstrap_error_payload(inputs, effective_answers, errors),
                indent=2,
                sort_keys=True,
            )
        )
        return 1
    if answers_bytes is None:
        print(
            json.dumps(
                {"errors": ["validated bootstrap answers bytes are unavailable"]},
                indent=2,
                sort_keys=True,
            )
        )
        return 1
    try:
        plan = build_bootstrap_write_plan(inputs, effective_answers)
    except (OSError, ValueError) as exc:
        print(
            json.dumps(
                bootstrap_error_payload(
                    inputs,
                    effective_answers,
                    [f"bootstrap planning failed: {exc}"],
                ),
                indent=2,
                sort_keys=True,
            )
        )
        return 1
    if plan.errors:
        print(
            json.dumps(
                {**plan.summary, "errors": plan.errors},
                indent=2,
                sort_keys=True,
            )
        )
        return 1
    try:
        outputs = render_bootstrap_write_outputs(
            inputs,
            effective_answers,
            answers_bytes,
            plan.effective_date,
            framework_identity=plan.framework_identity,
        )
        warnings = plan.summary.get("warnings")
        write_plan_sha256 = bootstrap_write_plan_sha256(
            inputs,
            outputs,
            plan.framework_identity,
            warnings,
            effective_date=plan.effective_date,
        )
    except (OSError, ValueError) as exc:
        print(
            json.dumps(
                {
                    **plan.summary,
                    "errors": [f"bootstrap rendering failed: {exc}"],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 1
    plan.summary["answers_sha256"] = sha256_bytes(answers_bytes)
    plan.summary["framework_identity"] = {
        "content_sha256": plan.framework_identity.content_sha256,
        "distribution_sha256": plan.framework_identity.distribution_sha256,
    }
    plan.summary["rendered_output_digests"] = {
        name: sha256_bytes(content.encode("utf-8"))
        for name, content in outputs.items()
    }
    plan.summary["write_plan_sha256"] = write_plan_sha256
    approval_errors = bootstrap_write_plan_approval_errors(
        write_plan_sha256,
        inputs.options.approve_write_plan_sha256,
        dry_run=inputs.options.dry_run,
    )
    if approval_errors:
        print(
            json.dumps(
                {**plan.summary, "errors": approval_errors},
                indent=2,
                sort_keys=True,
            )
        )
        return 1
    if inputs.options.dry_run:
        print(json.dumps(plan.summary, indent=2, sort_keys=True))
        return 0
    try:
        current_framework_identity = capture_framework_identity(inputs.framework_root)
        current_write_plan_sha256 = bootstrap_write_plan_sha256(
            inputs,
            outputs,
            current_framework_identity,
            warnings,
            effective_date=plan.effective_date,
        )
    except (OSError, ValueError) as exc:
        print(
            json.dumps(
                {
                    **plan.summary,
                    "errors": [
                        "bootstrap write plan could not be revalidated before "
                        f"preflight: {exc}"
                    ],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 1
    if current_write_plan_sha256 != write_plan_sha256:
        print(
            json.dumps(
                {
                    **plan.summary,
                    "errors": [
                        "bootstrap write plan changed after approval validation; "
                        "run and review a new dry run"
                    ],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 1
    write_errors = preflight_writes(inputs.project_root, outputs)
    if write_errors:
        print(
            json.dumps(
                {**plan.summary, "errors": write_errors},
                indent=2,
                sort_keys=True,
            )
        )
        return 1
    try:
        write_result = write_bootstrap_outputs(
            inputs,
            effective_answers,
            outputs,
            framework_identity=plan.framework_identity,
        )
    except (OSError, ValueError) as exc:
        print(
            json.dumps(
                {**plan.summary, "errors": [str(exc)]},
                indent=2,
                sort_keys=True,
            )
        )
        return 1
    try:
        recovery = bootstrap_transaction.transaction_recovery_status(
            inputs.project_root
        )
    except (OSError, ValueError) as exc:
        print(
            json.dumps(
                {
                    **plan.summary,
                    "cleanup_warnings": write_result.cleanup_warnings,
                    "status": "recovery-required",
                    "written": write_result.written,
                    "removed": write_result.removed,
                    "transaction_id": None,
                    "errors": [
                        "bootstrap wrote candidate files but could not prove clean "
                        f"transaction state: {exc}"
                    ],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return EXIT_RECOVERY_REQUIRED
    recovery_required = transaction_state_requires_recovery(recovery)
    if recovery_required:
        print(
            json.dumps(
                {
                    **plan.summary,
                    "cleanup_warnings": write_result.cleanup_warnings,
                    "status": "recovery-required",
                    "transaction_state": recovery.state,
                    "written": write_result.written,
                    "removed": write_result.removed,
                    "transaction_id": recovery.transaction_id,
                    "phase": recovery.phase,
                    "can_rollback": recovery.can_rollback,
                    "can_finalize": recovery.can_finalize,
                    "recovery_route": transaction_recovery_route(recovery),
                    "errors": list(recovery.errors),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return EXIT_RECOVERY_REQUIRED
    if write_result.cleanup_warnings:
        print(
            json.dumps(
                {
                    **plan.summary,
                    "cleanup_warnings": write_result.cleanup_warnings,
                    "status": "completed-with-cleanup-warnings",
                    "written": write_result.written,
                    "removed": write_result.removed,
                    "errors": [],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 1
    print(
        json.dumps(
            {
                **plan.summary,
                "written": write_result.written,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
