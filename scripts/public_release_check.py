#!/usr/bin/env python3

from __future__ import annotations

import argparse
import ast
import codecs
from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import tempfile
from collections.abc import Callable, Generator, Iterator, Mapping, Set
from typing import BinaryIO, Protocol

import bounded_subprocess
import public_surface
import resource_cleanup
import safe_paths


REPO_ROOT = Path(__file__).resolve().parent.parent
PUBLIC_EXPORT_OWNERSHIP_MARKER = public_surface.PUBLIC_EXPORT_OWNERSHIP_MARKER
PUBLIC_EXPORT_OWNERSHIP_SCHEMA_VERSION = 2
PUBLIC_EXPORT_GENERATOR = "master-prompt-agreement/scripts/public_export.py"
PUBLIC_EXPORT_MARKER_KEYS = {"files", "generator", "schema_version"}
PUBLIC_EXPORT_FILE_RECORD_KEYS = {"posix_mode", "sha256"}
PUBLIC_EXPORT_ROOT_MODE = 0o700
PUBLIC_EXPORT_DIRECTORY_MODE = 0o755
PUBLIC_EXPORT_MARKER_MODE = 0o644
PUBLIC_EXPORT_SENTINEL_FILES = {".gitignore", "AGENTS.md", "README.md", "scripts/public_export.py"}
TEXT_SUFFIXES = {
    ".css",
    ".html",
    ".js",
    ".json",
    ".md",
    ".py",
    ".svg",
    ".template",
    ".ts",
    ".txt",
    ".yaml",
    ".yml",
}
TEXT_FILENAMES = {".gitignore", "LICENSE", "NOTICE"}
# A non-text public product file must be reviewed and named explicitly here;
# suffix-wide binary exemptions would let future content bypass leak scanning.
PUBLIC_BINARY_FILES: frozenset[str] = frozenset()
PLATFORM_METADATA_DIRS = {"__MACOSX"}
GIT_COMMAND_TIMEOUT_SECONDS = 60.0
GIT_COMMAND_MAX_OUTPUT_BYTES = 4 * 1024 * 1024
GIT_INDEX_MAX_BYTES = 64 * 1024 * 1024
GIT_EXECUTABLE_MAX_BYTES = 128 * 1024 * 1024
GIT_TERMINATION_GRACE_SECONDS = 0.5
MINIMUM_FSMONITOR_BOOLEAN_GIT_VERSION = (2, 36, 0)
MINIMUM_FSMONITOR_BOOLEAN_GIT_VERSION_TEXT = "2.36.0"
PUBLICATION_BOUNDARY_ENV = "MPA_PUBLICATION_BOUNDARY"
PUBLICATION_GIT_PROC_PATH_ENV = "MPA_RELEASE_GIT_PROC_PATH"
PUBLICATION_GIT_SHA256_ENV = "MPA_RELEASE_GIT_SHA256"
PUBLIC_TEXT_INPUT_MAX_BYTES = safe_paths.DEFAULT_JSON_INPUT_MAX_BYTES
HOST_PATH_RE = safe_paths.LOCAL_ABSOLUTE_PATH_RE
PATH_SEGMENT_PREFIX = r"(?:(?<![\w./-])|(?<=[A-Za-z0-9_.@%+=:,~-][\\/]))"
PRIVATE_STATE_RE = re.compile(
    PATH_SEGMENT_PREFIX
    + r"(?:private[\\/]|review_artifacts[\\/]|external_review[\\/]|source_dumps[\\/]|source_material[\\/])"
)
SENSITIVE_LOCAL_REFERENCE_PATTERN_PARTS = (
    r"(?<![\w.-])(?:",
    r"\.env(?!\.example\b)(?:\.[A-Za-z0-9_-]+)?",
    r"|\.envrc",
    r"|\.netrc",
    r"|\.npmrc",
    r"|\.pypirc",
    r"|pip\.conf",
    r"|credentials\.json",
    r"|token\.json",
    r"|client_secret[A-Za-z0-9_.-]*\.json",
    r"|service-account[A-Za-z0-9_.-]*\.json",
    r"|google-credentials[A-Za-z0-9_.-]*\.json",
    r"|(?:id_rsa|id_dsa|id_ecdsa|id_ed25519)(?:\.pub)?",
    r"|[A-Za-z0-9_.-]+\.(?:pem|p12|pfx|jks|keystore|kdbx)",
    r"|\.codex(?:[\\/]|\b)",
    r"|\.cursor(?:[\\/]|\b)",
    r"|\.continue(?:[\\/]|\b)",
    r"|\.mcp\.json",
    r"|\.kube(?:[\\/]|\b)",
    r"|\.aws(?:[\\/]|\b)",
    r"|\.azure(?:[\\/]|\b)",
    r"|\.gcloud(?:[\\/]|\b)",
    r")",
)
SENSITIVE_LOCAL_REFERENCE_RE = re.compile(
    "".join(SENSITIVE_LOCAL_REFERENCE_PATTERN_PARTS)
)
SENSITIVE_VALUE_PATTERNS = (
    (
        "private-key header",
        re.compile(r"-----BEGIN(?: [A-Z0-9]+)* PRIVATE KEY-----"),
    ),
    (
        "authorization bearer value",
        re.compile(r"\b(?:Authorization\s*:\s*)?Bearer\s+[A-Za-z0-9._~+/=-]{16,}", re.IGNORECASE),
    ),
    (
        "JWT-like value",
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    ),
    (
        "credential-bearing URL",
        re.compile(r"https?://[^\s/:@]+:[^\s/@]{4,}@", re.IGNORECASE),
    ),
    (
        "provider-token value",
        re.compile(
            r"\b(?:"
            r"gh[pousr]_[A-Za-z0-9]{20,}"
            r"|github_pat_[A-Za-z0-9_]{30,}"
            r"|(?:AKIA|ASIA)[0-9A-Z]{16}"
            r"|AIza[0-9A-Za-z_-]{35}"
            r"|xox[baprs]-[A-Za-z0-9-]{16,}"
            r"|sk-(?:(?:proj|svcacct|ant)-)?[A-Za-z0-9_-]{20,}"
            r")\b"
        ),
    ),
)
SENSITIVE_ASSIGNMENT_KEY_PATTERN = (
    r"api[_-]?key|access[_-]?key|access[_-]?token|auth[_-]?token|"
    r"client[_-]?secret|password|passwd|refresh[_-]?token|secret[_-]?key"
)
SENSITIVE_ASSIGNMENT_RE = re.compile(
    r"(?i)(?<![\w])(?P<key_quote>['\"]?)(?:"
    + SENSITIVE_ASSIGNMENT_KEY_PATTERN
    + r")(?P=key_quote)\s*[:=]\s*(?:"
    r"\"(?P<double>[^\"\r\n]+)\"|"
    r"'(?P<single>[^'\r\n]+)'|"
    r"(?P<bare>[^\s#;,}\]]+)"
    r")"
)
SENSITIVE_JSON_KEYS = {
    "access_key",
    "access_token",
    "accesskey",
    "accesstoken",
    "api_key",
    "apikey",
    "auth_token",
    "authtoken",
    "client_secret",
    "clientsecret",
    "password",
    "passwd",
    "refresh_token",
    "refreshtoken",
    "secret_key",
    "secretkey",
}
SECRET_PLACEHOLDER_MARKERS = (
    "change-me",
    "configured-via",
    "configured_via",
    "dummy",
    "example",
    "from-env",
    "from_env",
    "keychain",
    "not-a-real",
    "not_a_real",
    "placeholder",
    "redacted",
    "replace-me",
    "replace_with",
    "replace-with",
    "sample",
    "secret-store",
    "secret_store",
    "test-only",
    "test_only",
    "vault://",
    "your-",
    "your_",
)
LOCAL_STATE_PATH_RE = re.compile(
    PATH_SEGMENT_PREFIX
    + r"(?:notes|scratch|transcripts|session_logs|captures|local|tmp)[\\/]"
    r"(?:[A-Za-z0-9_.@%+=:,~-]+[\\/])*"
    r"(?:[A-Za-z0-9_.@%+=:,~-]+(?:\.[A-Za-z0-9]+)?)?"
)
PRIVATE_WORKFLOW_PATTERNS_PATH = Path("private") / "authoring" / "release" / "leak_patterns.json"
PRIVATE_STATE_REFERENCE_ALLOWLIST = {
    "AGENTS.md": (
        r"^If `private/authoring/AGENT_PROJECT\.md` exists, load it after the operative charter as the concrete authoring-project runtime layer and resolve its project-state references against `private/authoring/`\.$",
        r"^Consult `private/authoring/STATEMENT_OF_WORK\.md` only for authoring-project ambiguity\. Revise the concrete authoring contract through the retained-source procedure in `private/authoring/README\.md`, not by hand-editing rendered contract files\. If the private authoring instance is absent, continue under this generic maintainer contract\.$",
    ),
    ".gitignore": (
        r"^\s*(?:!/?|/?)(?:private|review_artifacts|external_review|notes|scratch|transcripts|session_logs|captures|source_dumps|source_material|local|tmp)(?:/|\b)",
        r"^\s*!?/?(?:internal|INTERNAL)_\*\.md$",
        r"^\s*!?/?\*_(?:STATE|Commit)(?:\*?\.md)?$",
    ),
    "scripts/check_reference_freshness.py": (
        r'Path\("private/references"\)',
        r"Defaults to private/references",
    ),
    "docs/source_chain_artifacts.md": (
        r"review_artifacts/",
    ),
    "scripts/automation_orders_lint.py": (
        r'^ARTIFACT_OUTPUT_PREFIXES = \("artifacts/", "review_artifacts/"\)$',
    ),
    "SECURITY.md": (
        r"local/private file inclusion",
    ),
    "practice_guides/scheduled_automation.md": (
        r"local/cloud boundary",
    ),
    "practice_guides/seo.md": (
        r"local/entity,",
    ),
    "practice_guides/risk_routing.md": (
        r"small/local/reversible,",
    ),
    "task_orders/automation.md": (
        r"local/cloud",
    ),
    "task_orders/orchestrate.md": (
        r"local/project environment",
    ),
    "project_state_templates/SOURCE_UPDATE.md": (
        r"release notes/advisories",
    ),
    "scripts/project_bootstrap.py": (
        r'^\s+r"\(\?<!\[\\w\.-\]\)\(\?:\\\.codex\|\\\.cursor\|\\\.continue\|\\\.mcp\\\.json',
        r'^\s+r"\\\.(?:codex|env|kube)',
        r'^\s+r"private\[\\\\/\]',
    ),
    "scripts/source_registry_access_audit.py": (
        r'Path\("private/references"\)',
        r"Defaults to private/references",
    ),
    "scripts/source_chain_artifact_lint.py": (
        r"review_artifacts/",
    ),
    "scripts/safe_paths.py": (
        r'^\s+"(?:private|review_artifacts|external_review|notes|scratch|transcripts|session_logs|captures|source_dumps|source_material|local|tmp)",?$',
    ),
    "scripts/public_release_check.py": (
        r"excluded private/local",
        r"public \.gitignore re-includes private/local authoring path",
        r'^\s*rel == "private/authoring" or rel\.startswith\("private/authoring/"\)$',
    ),
    "scripts/public_surface.py": (
        r'^\s+"/?(?:private/(?:\*)?|review_artifacts/|external_review/|notes/|scratch/|transcripts/|session_logs/|captures/|source_dumps/|source_material/|local/|tmp/)",\s*$',
    ),
    "scripts/validate_framework.py": (
        r'^\s+"/(?:private|review_artifacts|external_review|notes|scratch|transcripts|session_logs|captures|source_dumps|source_material|local|tmp)',
    ),
    "tests/validation_automation_state.py": (
        r"output path must be repo-relative: /" + r"tmp/out\.md",
    ),
    "tests/validation_evidence_scope.py": (
        r'"--output=/tmp/out"',
    ),
    "tests/validation_framework_quality.py": (
        r"tmp/(?:example|site|public-export)",
    ),
    "tests/validation_conformance.py": (
        r'^\s*unix_path = "/" \+ "tmp/local"$',
    ),
    "tests/validation_publication.py": (
        r"public_release_check\.(?:PRIVATE_STATE_RE|check_public_release|is_public_excluded)",
        r'PATH = "private/source\.md"',
        r'private\\+source\.md',
        r'assert(?:In|NotIn)\("!?(?:private|review_artifacts)/"',
        r'^\s+"excluded private/local path" in error$',
        r'^\s+"excluded private/local path(?: is tracked in public release candidate| exists(?: in public export)?)[^"]*" in error$',
        r'^\s+"public \.gitignore re-includes private/local authoring path" in error$',
        r'^\s+"private or generated local-state reference leaked into public release file: tests/test_validation_scripts\.py"$',
        r"private or generated local-state reference leaked into public release file: tests/test_validation_scripts\.py(?::\d+)?",
        r"tmp/(?:example|site|public-export)(?:\\n)?",
        r"docs/private/source\.md",
        r"public/tmp/session\.?(?:\\n)?",
    ),
    "tests/validation_source_chain.py": (
        r"reference_freshness",
        r"source_chain",
        r'^\s*canonical_monitor = "review_artifacts/source_monitor/[0-9_-]+\.md"$',
        r'^\s*"review_artifacts/alternate/review_artifacts/"$',
        r'^\s+"(?:input_(?:monitor|review|apply)_artifact|external_reviewer_packet_manifest): review_artifacts/(?:source_monitor|source_review|source_apply|external_review_packets)/[A-Za-z0-9_.@%+=:,~/-]+",?$',
        r'^\s+"(?:input_(?:monitor|review|apply)_artifact|external_reviewer_packet_manifest)": "review_artifacts/(?:source_monitor|source_review|source_apply|external_review_packets)/[A-Za-z0-9_.@%+=:,~/-]+",?$',
        r'^\s+"review_artifacts/(?:source_monitor|source_review|source_apply|external_review_packets)/[A-Za-z0-9_.@%+=:,~/-]+",?$',
        r'^\s+Path\("review_artifacts/(?:source_monitor|source_review|source_apply|external_review_packets)/[A-Za-z0-9_.@%+=:,~/-]+"\),?$',
        r'^\s+"assurance: review_artifacts/(?:automation_assurance|source_automation)/[A-Za-z0-9_.@%+=:,~/-]+",?$',
        r'^\s+"  - path: private/references/[A-Za-z0-9_.@%+=:,~/-]+",?$',
        r'^\s+"  - private/references/[A-Za-z0-9_.@%+=:,~/-]+",?$',
    ),
}
HOST_PATH_REFERENCE_ALLOWLIST = {
    "tests/validation_automation_state.py": (
        r'"/' + r'tmp/project"',
        r'"/' + r'tmp/out\.md"',
        r"output path must be repo-relative: /" + r"tmp/out\.md",
    ),
    "tests/validation_bootstrap_runtime.py": (
        r'"/' + r'tmp/project"',
    ),
    "tests/validation_evidence_scope.py": (
        r'"--output=/' + r'tmp/out"',
    ),
}
SENSITIVE_REFERENCE_ALLOWLIST = {
    ".gitignore": (
        r"^\s*!?/?\.(?:codex|claude|cursor|continue)/?$",
        r"^\s*!?/?\.mcp\.json$",
        r"^\s*!?/?\.env(?:\.\*)?$",
        r"^\s*!?/?\.envrc$",
        r"^\s*!?/?\.env\.(?:example|template)$",
        r"^\s*!?/?\.(?:netrc|npmrc|pypirc)$",
        r"^\s*!?/?pip\.conf$",
        r"^\s*!?/?(?:credentials|token)\.json$",
        r"^\s*!?/?(?:client_secret|service-account|google-credentials)\*\.json$",
        r"^\s*!?/?id_(?:rsa|dsa|ecdsa|ed25519)\*$",
        r"^\s*!?/?\.(?:aws|azure|gcloud|kube)/$",
    ),
    "scripts/safe_paths.py": (
        r"PRIVATE_STATE_PARTS",
        r"PRIVATE_STATE_PATH_RE",
        r'^\s+"(?:\.codex|\.cursor|\.continue|\.mcp\.json)",?$',
    ),
    "annexes/authority.md": (
        r"Do not treat `\.env` files as a default vault",
    ),
    "annexes/security.md": (
        r"Never commit secret-bearing `\.env` files",
        r"Placeholder-only examples such as `\.env\.example`",
    ),
    "master_service_agreement.md": (
        r"Do not stage files that contain secrets \(\.env, credentials, API keys",
    ),
    "practice_guides/security_audit.md": (
        r"Flag `\.env` or raw environment variables",
    ),
    "task_orders/commit.md": (
        r"Do not stage files that contain secrets \(\.env, credentials, API keys",
    ),
    "scripts/context_manifest.py": (
        r'"\.codex"',
    ),
    "scripts/project_bootstrap.py": (
        r"\\\.(?:codex|cursor|continue|mcp|env|npmrc|pypirc|kube|aws|azure|gcloud)",
    ),
    "scripts/public_surface.py": (
        r'^\s+"\.(?:env|envrc|netrc|npmrc|pypirc)',
        r'^\s+"/?\.(?:codex|claude|cursor|continue|aws|azure|gcloud|kube)(?:/)?",\s*$',
        r'^\s+"/?\.mcp\.json",\s*$',
        r'^\s+"(?:pip\.conf|credentials\.json|token\.json)',
        r'^\s+"\*\.env\.\*"',
        r'^\s+"id_(?:rsa|dsa|ecdsa|ed25519)\*",?$',
    ),
    "scripts/validate_framework.py": (
        r'^\s+"\.(?:env|envrc|npmrc|pypirc)',
        r'^\s+"\.netrc',
        r'^\s+"(?:credentials\.json|token\.json)',
        r'^\s+"pip\.conf',
        r'^\s+"/\.codex',
    ),
    "tests/validation_framework_quality.py": (
        r"^import public_surface  # noqa: E402$",
        r"public_surface\.(?:is_public_excluded|PUBLIC_REQUIRED_FILES)",
        r'^\s+"(?:\.env|\.env\.local|\.envrc|\.netrc|\.npmrc|\.pypirc|pip\.conf|credentials\.json|token\.json|client_secret-prod\.json|service-account-prod\.json|google-credentials-prod\.json|id_rsa|id_rsa\.key|id_rsa\.pub|id_ed25519|id_ed25519\.pub|vault\.kdbx|project_state_templates/\.env|project_state_templates/\.env\.local|scripts/credentials\.json|practice_guides/token\.json|\.direnv/allow)",?$',
    ),
    "tests/validation_publication.py": (
        r"^import public_release_check  # noqa: E402$",
        r"^import public_surface  # noqa: E402$",
        r"public_release_check\.(?:PRIVATE_STATE_RE|check_public_release|is_public_excluded)",
        r"public_surface\.(?:is_public_excluded|PUBLIC_REQUIRED_FILES)",
        r"Use \.env\.local for secrets",
        r'CRED = "credentials\.json"',
        r'STATE = "\.codex/config\.json"',
        r'WIN_STATE = "\.aws\\+credentials"',
        r'CLIENT_SECRET = "client_secret-prod\.json"',
        r'KEY = "id_rsa\.key"',
        r'AWS = "\.aws/credentials"',
        r"Never commit secret-bearing `\.env` files",
        r'^\s+"/\.(?:mcp\.json|cursor/|continue/|aws/|azure/|gcloud/|kube/)",?\s*$',
    ),
}
PRIVATE_WORKFLOW_SCANNER_ALLOWLIST = {
    "scripts/public_release_check.py": (
        r"PRIVATE_WORKFLOW_SCANNER_ALLOWLIST",
        r"PRIVATE_WORKFLOW_PATTERNS_PATH",
        r"load_private_workflow_policy",
        r"private workflow reference",
    ),
    "tests/validation_publication.py": (
        r"leak_patterns\.json",
        r"private workflow reference leaked into public release file",
    ),
}
SCANNER_MODELED_REFERENCE_PATTERNS = frozenset(
    SENSITIVE_LOCAL_REFERENCE_PATTERN_PARTS
).union(
    pattern
    for allowlist in (
        PRIVATE_STATE_REFERENCE_ALLOWLIST,
        HOST_PATH_REFERENCE_ALLOWLIST,
        SENSITIVE_REFERENCE_ALLOWLIST,
        PRIVATE_WORKFLOW_SCANNER_ALLOWLIST,
    )
    for patterns in allowlist.values()
    for pattern in patterns
)
ROOT_AGENTS_REQUIRED_SNIPPETS = (
    "framework-maintenance instructions only",
    "Do not copy this root file into downstream projects",
    "GETTING_STARTED.md",
    "task_orders/init.md",
)


class ReleaseTreeRole(StrEnum):
    AUTHORING_SOURCE = "authoring-source"
    PUBLIC_EXPORT = "public-export"


@dataclass(frozen=True)
class PublicExportTreeSnapshot:
    """Closed descriptor-native semantic snapshot of one public export."""

    root_mode: int
    directories: tuple[tuple[str, int], ...]
    files: tuple[tuple[str, str, int], ...]


@dataclass(frozen=True)
class _TreeInventory:
    files: dict[str, os.stat_result]
    directories: dict[str, os.stat_result]
    symlinks: dict[str, os.stat_result]
    special: dict[str, os.stat_result]
    root_metadata: os.stat_result | None
    errors: tuple[str, ...]


@dataclass(frozen=True)
class _PrivateWorkflowPolicy:
    reference_re: re.Pattern[str]
    allowed_gitignore_lines: frozenset[str]


@dataclass(frozen=True)
class _GitMetadataBinding:
    physical_root: Path
    gitdir: Path
    root_identity: tuple[int, ...]
    control_identity: tuple[int, ...]
    gitdir_identity: tuple[int, ...]
    backlink_identity: tuple[int, ...] | None


@dataclass(frozen=True)
class GitStageEntry:
    """One exact entry read from an immutable Git index snapshot."""

    mode: str
    oid: str
    stage: int
    path: str


@dataclass
class GitExecutableBinding:
    """One retained, digest-verified publication executable capability."""

    descriptor: int
    metadata: os.stat_result
    lexical_path: Path
    sha256: str
    description: str = "bound Git executable"
    _closed: bool = False

    @property
    def command(self) -> str:
        descriptor_path = Path("/proc/self/fd") / str(self.descriptor)
        if not descriptor_path.exists():
            raise RuntimeError(
                f"{self.description} execution requires Linux procfs descriptor paths"
            )
        return str(descriptor_path)

    @property
    def external_command(self) -> str:
        descriptor_path = (
            Path("/proc") / str(os.getpid()) / "fd" / str(self.descriptor)
        )
        if not descriptor_path.exists():
            raise RuntimeError(
                f"{self.description} propagation requires Linux procfs descriptor paths"
            )
        return str(descriptor_path)

    @property
    def pass_fds(self) -> tuple[int, ...]:
        return (self.descriptor,)

    def require_current(self) -> None:
        if self._closed:
            raise RuntimeError(f"{self.description} is already closed")
        current = os.fstat(self.descriptor)
        if _stable_identity_metadata(current) != _stable_identity_metadata(
            self.metadata
        ):
            raise ValueError(f"{self.description} descriptor changed")
        if _executable_descriptor_sha256(
            self.descriptor,
            description=self.description,
        ) != self.sha256:
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
                primary.add_note(
                    f"{self.description} descriptor cleanup failure: {cleanup}"
                )
            else:
                raise
        if primary is not None:
            raise primary


@dataclass
class _GitInventoryBinding:
    root: Path
    inventory: _TreeInventory
    metadata: _GitMetadataBinding
    gitdir: safe_paths.OutputDirectoryBinding
    index: _RegularFileBinding | None
    snapshot_file: BinaryIO | None
    object_format: str | None
    tracked_files: frozenset[str]
    _closed: bool = False

    def require_current(self) -> None:
        self.gitdir.require_unchanged_chain(description="Git metadata directory")
        if self.index is None:
            try:
                os.stat(
                    "index",
                    dir_fd=self.gitdir.descriptor,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                pass
            else:
                raise RuntimeError("Git index appeared while tracked files were inspected")
        else:
            self.index.require_current(description="Git index")
            if (
                safe_paths.stable_file_metadata(os.fstat(self.index.descriptor))
                != safe_paths.stable_file_metadata(self.index.metadata)
            ):
                raise RuntimeError("Git index changed while tracked files were inspected")
        final_metadata = _git_metadata_binding(self.root, self.inventory)
        if final_metadata != self.metadata:
            raise RuntimeError(
                "Git metadata binding changed while tracked files were inspected"
            )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        _close_git_inventory_resources(
            self.snapshot_file,
            self.index,
            self.gitdir,
        )


@dataclass
class PublicSourceSnapshotBinding:
    """Retain one checked authoring root and Git generation for an export."""

    root: Path
    relative_paths: frozenset[str]
    snapshots: dict[str, tuple[str, int]]
    inventory_signature: tuple[object, ...]
    root_binding: safe_paths.OutputDirectoryBinding
    git_inventory: _GitInventoryBinding
    _closed: bool = False

    def require_generation_current(self, *, description: str) -> None:
        if self._closed:
            raise RuntimeError(f"{description} binding is already closed")
        self.root_binding.require_unchanged_chain(
            description=f"{description} root"
        )
        self.git_inventory.require_current()

    def require_current(
        self,
        *,
        description: str,
        confirm_release: bool = False,
    ) -> None:
        """Recheck the selected source and the retained root/index generation."""

        self.require_generation_current(description=description)
        inventory = _inventory_release_tree_descriptor(
            self.root_binding.descriptor
        )
        if inventory.errors:
            raise ValueError("; ".join(inventory.errors))
        if _inventory_signature(inventory) != self.inventory_signature:
            raise ValueError(
                f"{description} tree changed after its checked snapshot"
            )
        for relative_path in sorted(self.relative_paths):
            metadata = inventory.files.get(relative_path)
            if metadata is None:
                raise ValueError(
                    f"{description} source disappeared: {relative_path}"
                )
            if stable_file_snapshot(
                self.root / relative_path,
                _expected=metadata,
            ) != self.snapshots[relative_path]:
                raise ValueError(
                    f"{description} source content or POSIX rwx mode changed: "
                    f"{relative_path}"
                )
        if confirm_release:
            confirmation = _check_public_release_with_binding(
                self.root,
                tree_role=ReleaseTreeRole.AUTHORING_SOURCE,
                root_binding=self.root_binding,
                _git_inventory=self.git_inventory,
            )
            confirmation_errors = confirmation.get("errors")
            if not isinstance(confirmation_errors, list) or not all(
                isinstance(item, str) for item in confirmation_errors
            ):
                raise TypeError(
                    "public source release confirmation returned invalid errors payload"
                )
            if confirmation_errors:
                raise ValueError(
                    f"{description} failed release confirmation: "
                    + "; ".join(confirmation_errors)
                )
        self.require_generation_current(description=description)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        resource_cleanup.cleanup_actions(
            (
                ("public source Git inventory", self.git_inventory.close),
                ("public source root binding", self.root_binding.close),
            )
        )


@dataclass
class _RegularFileBinding:
    descriptor: int
    metadata: os.stat_result
    lexical_path: Path
    parent: safe_paths.OutputDirectoryBinding
    name: str
    _closed: bool = False

    def require_current(self, *, description: str) -> None:
        self.parent.require_lexical_binding(description=f"{description} parent")
        named = os.stat(
            self.name,
            dir_fd=self.parent.descriptor,
            follow_symlinks=False,
        )
        current = os.fstat(self.descriptor)
        if (
            not stat.S_ISREG(named.st_mode)
            or _stable_identity_metadata(named)
            != _stable_identity_metadata(current)
        ):
            raise ValueError(
                f"{description} pathname no longer identifies its bound file: "
                f"{self.lexical_path}"
            )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        resource_cleanup.cleanup_actions(
            (
                (
                    "regular-file descriptor",
                    lambda: os.close(self.descriptor),
                ),
                ("regular-file parent binding", self.parent.close),
            )
        )


class _Closable(Protocol):
    def close(self) -> None: ...


def _cleanup_release_resources(
    *,
    descriptors: tuple[tuple[str, int], ...] = (),
    resources: tuple[tuple[str, _Closable], ...] = (),
    primary: BaseException | None = None,
) -> None:
    """Attempt all owned cleanup and never replace a failure already in flight."""

    resource_cleanup.cleanup_actions(
        tuple(
            (
                description,
                lambda descriptor=descriptor: os.close(descriptor),
            )
            for description, descriptor in descriptors
        )
        + tuple((description, resource.close) for description, resource in resources),
        primary=primary,
    )


def _close_preserving_primary(
    resource: _Closable,
    *,
    description: str,
    primary: BaseException | None = None,
) -> None:
    _cleanup_release_resources(
        resources=((description, resource),),
        primary=primary,
    )


def _close_snapshot_file(snapshot: BinaryIO) -> None:
    """Make one close attempt without retrying an ambiguous descriptor number."""

    snapshot.close()


def _close_git_inventory_resources(
    snapshot: BinaryIO | None,
    index: _RegularFileBinding | None,
    gitdir: safe_paths.OutputDirectoryBinding,
    *,
    primary: BaseException | None = None,
) -> None:
    """Attempt every Git binding cleanup without masking a primary failure."""

    actions: list[tuple[str, Callable[[], object]]] = []
    if snapshot is not None:
        actions.append(
            (
                "Git index snapshot",
                lambda snapshot=snapshot: _close_snapshot_file(snapshot),
            )
        )
    for description, resource in (
        ("Git index binding", index),
        ("Git metadata directory binding", gitdir),
    ):
        if resource is None:
            continue
        actions.append((description, resource.close))
    resource_cleanup.cleanup_actions(actions, primary=primary)


@dataclass
class _ReleaseCheckContext:
    root: Path
    tree_role: ReleaseTreeRole
    inventory: _TreeInventory
    errors: list[str]
    notes: list[str]
    warnings: list[str]
    root_binding: safe_paths.OutputDirectoryBinding | None = None
    git_inventory: _GitInventoryBinding | None = None
    git_executable: GitExecutableBinding | None = None
    tracked_files: set[str] | None = None
    private_workflow_policy: _PrivateWorkflowPolicy | None = None
    public_rels: tuple[str, ...] = ()


def _stable_identity_metadata(metadata: os.stat_result) -> tuple[int, ...]:
    """Return object identity without mutable content timestamps or size."""

    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_nlink,
        metadata.st_uid,
        metadata.st_gid,
    )


def _expected_sha256(value: str, *, description: str) -> str:
    if re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"{description} must be one lowercase SHA-256 digest")
    return value


def _executable_descriptor_sha256(
    descriptor: int,
    *,
    description: str,
) -> str:
    before = os.fstat(descriptor)
    if not stat.S_ISREG(before.st_mode):
        raise ValueError(f"{description} must identify a regular file")
    if before.st_nlink < 1:
        raise ValueError(f"{description} must identify a linked file")
    if not stat.S_IMODE(before.st_mode) & 0o111:
        raise ValueError(f"{description} is not marked executable")
    if before.st_size > GIT_EXECUTABLE_MAX_BYTES:
        raise ValueError(f"{description} exceeds the bounded input limit")
    digest = hashlib.sha256()
    offset = 0
    while chunk := os.pread(descriptor, 1024 * 1024, offset):
        offset += len(chunk)
        if offset > GIT_EXECUTABLE_MAX_BYTES:
            raise ValueError(f"{description} exceeds the bounded input limit")
        digest.update(chunk)
    after = os.fstat(descriptor)
    if (
        _stable_identity_metadata(before) != _stable_identity_metadata(after)
        or offset != after.st_size
    ):
        raise ValueError(f"{description} changed while it was inspected")
    return digest.hexdigest()


def _git_executable_lexical_path(
    descriptor: int,
    *,
    description: str,
) -> Path:
    descriptor_path = Path("/proc/self/fd") / str(descriptor)
    try:
        raw_target = os.readlink(descriptor_path)
    except OSError as exc:
        raise ValueError(
            f"{description} descriptor is unavailable through Linux procfs"
        ) from exc
    if raw_target.endswith(" (deleted)"):
        raise ValueError(f"{description} descriptor names a deleted file")
    lexical_path = Path(raw_target)
    if not lexical_path.is_absolute():
        raise ValueError(
            f"{description} descriptor must identify an absolute file"
        )
    return lexical_path


def _git_executable_binding_from_owned_descriptor(
    descriptor: int,
    *,
    expected_sha256: str,
    description: str,
) -> GitExecutableBinding:
    expected = _expected_sha256(
        expected_sha256,
        description=f"expected {description} SHA-256",
    )
    try:
        os.set_inheritable(descriptor, False)
        metadata = os.fstat(descriptor)
        lexical_path = _git_executable_lexical_path(
            descriptor,
            description=description,
        )
        observed = _executable_descriptor_sha256(
            descriptor,
            description=description,
        )
        if observed != expected:
            raise ValueError(
                f"{description} SHA-256 does not match the approved digest"
            )
        binding = GitExecutableBinding(
            descriptor=descriptor,
            metadata=metadata,
            lexical_path=lexical_path,
            sha256=observed,
            description=description,
        )
        binding.require_current()
        return binding
    except BaseException as primary:
        try:
            os.close(descriptor)
        except BaseException as cleanup:
            primary.add_note(
                f"{description} descriptor cleanup failure: {cleanup}"
            )
        raise


def open_inherited_git_executable_binding(
    source_descriptor: int,
    *,
    expected_sha256: str,
    description: str = "bound Git executable",
) -> GitExecutableBinding:
    """Duplicate and verify one inherited Git executable descriptor."""

    if (
        isinstance(source_descriptor, bool)
        or not isinstance(source_descriptor, int)
        or source_descriptor < 3
    ):
        raise ValueError(f"{description} descriptor must be at least 3")
    try:
        descriptor = os.dup(source_descriptor)
    except OSError as exc:
        raise ValueError(f"{description} descriptor is unavailable") from exc
    return _git_executable_binding_from_owned_descriptor(
        descriptor,
        expected_sha256=expected_sha256,
        description=description,
    )


def open_propagated_git_executable_binding(
    descriptor_path: Path,
    *,
    expected_sha256: str,
    description: str = "bound Git executable",
) -> GitExecutableBinding:
    """Open a retained ancestor-process descriptor through Linux procfs."""

    if not descriptor_path.is_absolute() or re.fullmatch(
        r"/proc/[1-9][0-9]*/fd/(?:[3-9]|[1-9][0-9]+)",
        descriptor_path.as_posix(),
    ) is None:
        raise ValueError(
            f"propagated {description} must be one absolute /proc/<pid>/fd/<fd> path"
        )
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(descriptor_path, flags)
    except OSError as exc:
        raise ValueError(f"propagated {description} descriptor is unavailable") from exc
    return _git_executable_binding_from_owned_descriptor(
        descriptor,
        expected_sha256=expected_sha256,
        description=description,
    )


def _required_open_flag(name: str) -> int:
    value = getattr(os, name, None)
    if not isinstance(value, int) or value == 0:
        raise ValueError(f"descriptor-safe release inspection requires platform flag {name}")
    return value


def _physical_system_alias_path(path: Path) -> Path:
    for alias, target in safe_paths.ALLOWED_SYSTEM_SYMLINK_TARGETS.items():
        try:
            relative = path.relative_to(alias)
        except ValueError:
            continue
        if safe_paths.is_allowed_system_symlink(alias):
            return target / relative
    return path


def _absolute_inspection_path(path: Path, *, description: str) -> tuple[Path, Path]:
    lexical = Path(os.path.abspath(os.fspath(path.expanduser())))
    physical = _physical_system_alias_path(lexical)
    if physical.anchor != "/":
        raise ValueError(f"{description} must be an absolute path")
    if any(component in {"", ".", ".."} for component in physical.parts[1:]):
        raise ValueError(f"{description} contains an unsafe path component: {lexical}")
    return lexical, physical


def _unsafe_symlink_components(path: Path) -> list[Path]:
    return [
        component
        for component in safe_paths.symlink_components(path)
        if not safe_paths.is_allowed_system_symlink(component)
    ]


def _open_directory_descriptor(path: Path, *, description: str) -> tuple[int, Path]:
    if not safe_paths.OPEN_SUPPORTS_DIR_FD or os.scandir not in getattr(os, "supports_fd", set()):
        raise ValueError("descriptor-safe release inspection requires directory-descriptor support")
    lexical, physical = _absolute_inspection_path(path, description=description)
    flags = (
        os.O_RDONLY
        | _required_open_flag("O_DIRECTORY")
        | _required_open_flag("O_NOFOLLOW")
        | getattr(os, "O_CLOEXEC", 0)
    )
    descriptor: int | None = None
    try:
        descriptor = os.open("/", flags)
        for component in physical.parts[1:]:
            next_descriptor = os.open(component, flags, dir_fd=descriptor)
            previous_descriptor = descriptor
            try:
                _cleanup_release_resources(
                    descriptors=((f"{description} traversed directory", previous_descriptor),),
                )
            except BaseException as exc:
                descriptor = None
                _cleanup_release_resources(
                    descriptors=((f"{description} next directory", next_descriptor),),
                    primary=exc,
                )
                raise
            descriptor = next_descriptor
        return descriptor, lexical
    except BaseException as exc:
        if descriptor is not None:
            _cleanup_release_resources(
                descriptors=((f"{description} directory", descriptor),),
                primary=exc,
            )
        if isinstance(exc, OSError):
            unsafe_symlinks = _unsafe_symlink_components(lexical)
            if unsafe_symlinks:
                raise ValueError(
                    f"{description} must not use symlink path components: "
                    + ", ".join(str(component) for component in unsafe_symlinks)
                ) from exc
        raise


def _open_regular_descriptor(
    path: Path,
    *,
    description: str,
    expected: os.stat_result | None = None,
    require_single_link: bool = True,
) -> _RegularFileBinding:
    if not safe_paths.OPEN_SUPPORTS_DIR_FD:
        raise ValueError("descriptor-safe release inspection requires os.open dir_fd support")
    lexical, physical = _absolute_inspection_path(path, description=description)
    if len(physical.parts) < 2:
        raise ValueError(f"{description} must name an absolute regular file")
    file_flags = (
        os.O_RDONLY
        | _required_open_flag("O_NOFOLLOW")
        | _required_open_flag("O_NONBLOCK")
        | getattr(os, "O_CLOEXEC", 0)
    )
    parent_binding: safe_paths.OutputDirectoryBinding | None = None
    file_descriptor: int | None = None
    try:
        parent_binding = safe_paths.open_output_directory(
            physical.parent,
            create_missing=False,
        )
        file_descriptor = os.open(
            physical.parts[-1],
            file_flags,
            dir_fd=parent_binding.descriptor,
        )
        before = os.fstat(file_descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError(f"{description} must be a regular file: {lexical}")
        if require_single_link and before.st_nlink != 1:
            raise ValueError(f"{description} must have exactly one hard link: {lexical}")
        if (
            expected is not None
            and safe_paths.stable_file_metadata(before)
            != safe_paths.stable_file_metadata(expected)
        ):
            raise ValueError(f"{description} changed after release-tree enumeration: {lexical}")
        binding = _RegularFileBinding(
            descriptor=file_descriptor,
            metadata=before,
            lexical_path=lexical,
            parent=parent_binding,
            name=physical.parts[-1],
        )
        binding.require_current(description=description)
        return binding
    except BaseException as exc:
        _cleanup_release_resources(
            descriptors=(
                ((f"{description} file descriptor", file_descriptor),)
                if file_descriptor is not None
                else ()
            ),
            resources=(
                ((f"{description} parent binding", parent_binding),)
                if parent_binding is not None
                else ()
            ),
            primary=exc,
        )
        if isinstance(exc, OSError):
            unsafe_symlinks = _unsafe_symlink_components(lexical)
            if unsafe_symlinks:
                raise ValueError(
                    f"{description} must not use symlink path components: "
                    + ", ".join(str(component) for component in unsafe_symlinks)
                ) from exc
        if isinstance(
            exc,
            (safe_paths.OutputDirectoryBindingError, ValueError),
        ) and "symlink" in str(exc).lower():
            raise ValueError(
                f"{description} must not use symlink path components: {lexical}"
            ) from exc
        raise


def _iter_stable_file_chunks(
    path: Path,
    *,
    description: str,
    expected: os.stat_result | None = None,
    max_bytes: int | None = None,
    require_single_link: bool = True,
) -> Generator[bytes, None, None]:
    if max_bytes is not None and max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    binding = _open_regular_descriptor(
        path,
        description=description,
        expected=expected,
        require_single_link=require_single_link,
    )
    descriptor = binding.descriptor
    before = binding.metadata
    lexical = binding.lexical_path
    total = 0
    try:
        if max_bytes is not None and before.st_size > max_bytes:
            raise ValueError(
                f"{description} exceeds the {max_bytes}-byte input limit: {lexical}"
            )
        while True:
            read_size = 1024 * 1024
            if max_bytes is not None:
                read_size = min(read_size, max_bytes - total + 1)
            chunk = os.read(descriptor, read_size)
            if not chunk:
                break
            total += len(chunk)
            if max_bytes is not None and total > max_bytes:
                raise ValueError(
                    f"{description} exceeds the {max_bytes}-byte input limit: {lexical}"
                )
            yield chunk
        after = os.fstat(descriptor)
        if (
            safe_paths.stable_file_metadata(before)
            != safe_paths.stable_file_metadata(after)
            or total != after.st_size
        ):
            raise ValueError(f"{description} changed while it was being read: {lexical}")
        binding.require_current(description=description)
    finally:
        _close_preserving_primary(
            binding,
            description=f"{description} stable-file binding",
            primary=sys.exception(),
        )


def _read_stable_file_bytes(
    path: Path,
    *,
    description: str,
    expected: os.stat_result | None = None,
    max_bytes: int,
) -> bytes:
    return b"".join(
        _iter_stable_file_chunks(
            path,
            description=description,
            expected=expected,
            max_bytes=max_bytes,
        )
    )


def _line_without_ending(value: str) -> str:
    if value.endswith("\r\n"):
        return value[:-2]
    return value[:-1]


def _has_line_ending(value: str) -> bool:
    return value.endswith(("\n", "\r", "\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"))


def _iter_stable_utf8_lines(
    path: Path,
    *,
    description: str,
    expected: os.stat_result | None = None,
    max_bytes: int = PUBLIC_TEXT_INPUT_MAX_BYTES,
) -> Iterator[str]:
    decoder = codecs.getincrementaldecoder("utf-8")("strict")
    buffered = ""
    chunks = _iter_stable_file_chunks(
        path,
        description=description,
        expected=expected,
        max_bytes=max_bytes,
    )
    try:
        for chunk in chunks:
            buffered += decoder.decode(chunk)
            pieces = buffered.splitlines(keepends=True)
            buffered = ""
            for index, piece in enumerate(pieces):
                is_last = index == len(pieces) - 1
                if not _has_line_ending(piece) or (is_last and piece.endswith("\r")):
                    buffered = piece
                else:
                    yield _line_without_ending(piece)
        buffered += decoder.decode(b"", final=True)
    finally:
        _close_preserving_primary(
            chunks,
            description=f"{description} UTF-8 chunk iterator",
            primary=sys.exception(),
        )
    for piece in buffered.splitlines():
        yield piece


def _inventory_signature(inventory: _TreeInventory) -> tuple[object, ...]:
    groups = (
        ("file", inventory.files),
        ("directory", inventory.directories),
        ("symlink", inventory.symlinks),
        ("special", inventory.special),
    )
    return (
        safe_paths.stable_file_metadata(inventory.root_metadata)
        if inventory.root_metadata is not None
        else None,
        tuple(
            (
                kind,
                rel,
                (
                    _stable_identity_metadata(metadata)
                    if rel == ".git" and kind == "directory"
                    else safe_paths.stable_file_metadata(metadata)
                ),
            )
            for kind, entries in groups
            for rel, metadata in sorted(entries.items())
        ),
    )


def _inventory_release_tree_descriptor(descriptor: int) -> _TreeInventory:
    """Inventory one release tree through a caller-owned root descriptor."""

    files: dict[str, os.stat_result] = {}
    directories: dict[str, os.stat_result] = {}
    symlinks: dict[str, os.stat_result] = {}
    special: dict[str, os.stat_result] = {}
    root_metadata: os.stat_result | None = None
    errors: list[str] = []
    directory_flags = 0

    def walk(directory_descriptor: int, prefix: str) -> None:
        before = os.fstat(directory_descriptor)
        with os.scandir(directory_descriptor) as iterator:
            entries = sorted(iterator, key=lambda item: item.name)
        for entry in entries:
            try:
                entry.name.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise ValueError("release-tree path names must be valid UTF-8") from exc
            rel = f"{prefix}/{entry.name}" if prefix else entry.name
            metadata = entry.stat(follow_symlinks=False)
            mode = metadata.st_mode
            if stat.S_ISLNK(mode):
                symlinks[rel] = metadata
            elif stat.S_ISDIR(mode):
                directories[rel] = metadata
                if rel == ".git":
                    # Git metadata is not public product content. Its daemon
                    # sockets and lock files may change during an otherwise
                    # stable public-source check, so bind only the top-level
                    # metadata object and obtain tracked paths via git ls-files.
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
                        raise ValueError(f"release tree changed during enumeration: {rel}")
                    walk(child_descriptor, rel)
                finally:
                    _cleanup_release_resources(
                        descriptors=((f"release-tree directory {rel}", child_descriptor),),
                        primary=sys.exception(),
                    )
            elif stat.S_ISREG(mode):
                files[rel] = metadata
            else:
                special[rel] = metadata
        after = os.fstat(directory_descriptor)
        if safe_paths.stable_file_metadata(before) != safe_paths.stable_file_metadata(after):
            label = prefix or "."
            raise ValueError(f"release tree changed during enumeration: {label}")

    try:
        directory_flags = (
            os.O_RDONLY
            | _required_open_flag("O_DIRECTORY")
            | _required_open_flag("O_NOFOLLOW")
            | getattr(os, "O_CLOEXEC", 0)
        )
        root_metadata = os.fstat(descriptor)
        walk(descriptor, "")
    except (OSError, ValueError) as exc:
        errors.append(f"public release tree could not be enumerated safely: {exc}")
    return _TreeInventory(
        files=files,
        directories=directories,
        symlinks=symlinks,
        special=special,
        root_metadata=root_metadata,
        errors=tuple(errors),
    )


def _inventory_release_tree(root: Path) -> _TreeInventory:
    try:
        binding = safe_paths.open_output_directory(root, create_missing=False)
    except (OSError, safe_paths.OutputDirectoryBindingError, ValueError) as exc:
        return _TreeInventory(
            files={},
            directories={},
            symlinks={},
            special={},
            root_metadata=None,
            errors=(f"public release tree could not be enumerated safely: {exc}",),
        )
    result: _TreeInventory
    try:
        inventory = _inventory_release_tree_descriptor(binding.descriptor)
        binding.require_unchanged_chain(description="public release root")
        result = inventory
    except (OSError, ValueError) as exc:
        result = _TreeInventory(
            files={},
            directories={},
            symlinks={},
            special={},
            root_metadata=None,
            errors=(f"public release tree could not be enumerated safely: {exc}",),
        )
    except BaseException as exc:
        _close_preserving_primary(
            binding,
            description="public release inventory root",
            primary=exc,
        )
        raise
    try:
        binding.close()
    except Exception as cleanup:
        result = _TreeInventory(
            files=result.files,
            directories=result.directories,
            symlinks=result.symlinks,
            special=result.special,
            root_metadata=result.root_metadata,
            errors=result.errors
            + (f"public release inventory root cleanup failed: {cleanup}",),
        )
    return result


def root_entrypoint_errors(
    root: Path,
    *,
    _inventory: _TreeInventory | None = None,
) -> list[str]:
    owns_inventory = _inventory is None
    inventory = _inventory_release_tree(root) if _inventory is None else _inventory
    errors = list(inventory.errors) if owns_inventory else []

    agents_metadata = inventory.files.get("AGENTS.md")
    if agents_metadata is not None and agents_metadata.st_nlink == 1:
        found = dict.fromkeys(ROOT_AGENTS_REQUIRED_SNIPPETS, False)
        try:
            for line in _iter_stable_utf8_lines(
                root / "AGENTS.md",
                description="root AGENTS.md",
                expected=agents_metadata,
            ):
                for snippet in found:
                    if snippet in line:
                        found[snippet] = True
        except (OSError, UnicodeError, ValueError) as exc:
            errors.append(f"root AGENTS.md could not be read safely as UTF-8: {exc}")
        else:
            for snippet, present in found.items():
                if not present:
                    errors.append(f"root AGENTS.md missing framework-maintenance guard: {snippet}")

    claude_metadata = inventory.files.get("CLAUDE.md")
    if claude_metadata is not None and claude_metadata.st_nlink == 1:
        content_lines: list[str] = []
        invalid_content = False
        try:
            for line in _iter_stable_utf8_lines(
                root / "CLAUDE.md",
                description="root CLAUDE.md",
                expected=claude_metadata,
            ):
                stripped = line.strip()
                if not stripped or line.lstrip().startswith("#"):
                    continue
                if len(content_lines) < 2:
                    content_lines.append(stripped)
                else:
                    invalid_content = True
        except (OSError, UnicodeError, ValueError) as exc:
            errors.append(f"root CLAUDE.md could not be read safely as UTF-8: {exc}")
        else:
            if invalid_content or content_lines != ["@AGENTS.md"]:
                errors.append("root CLAUDE.md must keep @AGENTS.md as its only non-heading content")
    return errors


def is_public_excluded(rel: str) -> bool:
    return public_surface.is_public_excluded(rel)


def is_platform_metadata_sidecar(rel: str) -> bool:
    parts = Path(rel).parts
    return any(part in PLATFORM_METADATA_DIRS or part.startswith("._") for part in parts)


def platform_metadata_sidecar_errors(
    root: Path,
    *,
    _inventory: _TreeInventory | None = None,
) -> list[str]:
    owns_inventory = _inventory is None
    inventory = _inventory_release_tree(root) if _inventory is None else _inventory
    errors = list(inventory.errors) if owns_inventory else []
    all_paths = set(inventory.files) | set(inventory.directories) | set(inventory.symlinks) | set(inventory.special)
    errors.extend(
        f"platform metadata sidecar path is not allowed in public release: {rel}"
        for rel in sorted(all_paths)
        if is_platform_metadata_sidecar(rel)
    )
    return errors


def _sanitized_git_environment() -> dict[str, str]:
    """Return the inherited process environment without Git control inputs."""

    return {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith("GIT_")
    }


def _bounded_git_command(
    root: Path,
    command: list[str],
    *,
    label: str,
    environment: Mapping[str, str] | None = None,
    pass_fds: tuple[int, ...] = (),
    inherit_non_git_environment: bool = True,
) -> tuple[int, bytes, bytes]:
    if os.name != "posix":
        raise RuntimeError(f"{label} requires POSIX bounded subprocess pipes")
    try:
        child_environment = (
            _sanitized_git_environment()
            if inherit_non_git_environment
            else {}
        )
        if environment is not None:
            child_environment.update(environment)
        result = bounded_subprocess.run_bounded_process(
            command,
            cwd=root,
            env=child_environment,
            pass_fds=pass_fds,
            timeout_seconds=GIT_COMMAND_TIMEOUT_SECONDS,
            max_output_bytes=GIT_COMMAND_MAX_OUTPUT_BYTES,
            maximum_timeout_seconds=GIT_COMMAND_TIMEOUT_SECONDS,
            maximum_output_bytes=GIT_COMMAND_MAX_OUTPUT_BYTES,
            termination_grace_seconds=GIT_TERMINATION_GRACE_SECONDS,
        )
    except bounded_subprocess.BoundedSubprocessStartError as exc:
        detail = exc.__cause__ if isinstance(exc.__cause__, OSError) else exc
        raise RuntimeError(f"{label} could not start: {detail}") from exc
    if result.timed_out:
        raise RuntimeError(
            f"{label} timed out after {GIT_COMMAND_TIMEOUT_SECONDS:g}s"
        )
    if result.output_exceeded:
        raise RuntimeError(
            f"{label} output exceeded the "
            f"{GIT_COMMAND_MAX_OUTPUT_BYTES}-byte limit"
        )
    return result.returncode, result.stdout, result.stderr


def require_git_fsmonitor_boolean_support(
    root: Path,
    *,
    git_command: str = "git",
    git_pass_fds: tuple[int, ...] = (),
    inherit_non_git_environment: bool = True,
    environment: Mapping[str, str] | None = None,
) -> tuple[int, int, int]:
    """Require Git semantics where ``core.fsmonitor=false`` is a boolean."""

    version_environment = {} if environment is None else dict(environment)
    version_environment["LC_ALL"] = "C"
    returncode, stdout, stderr = _bounded_git_command(
        root,
        [git_command, "--version"],
        label="Git fsmonitor-boolean version inspection",
        environment=version_environment,
        pass_fds=git_pass_fds,
        inherit_non_git_environment=inherit_non_git_environment,
    )
    if returncode != 0 or stderr:
        raise RuntimeError(
            "Git fsmonitor-boolean version inspection failed without a usable "
            "bounded result"
        )
    match = re.fullmatch(
        rb"git version ([0-9]+)\.([0-9]+)\.([0-9]+)\n?",
        stdout,
    )
    if match is None:
        raise RuntimeError(
            "Git fsmonitor-boolean version inspection did not return one exact "
            "numeric version line"
        )
    version = (
        int(match.group(1)),
        int(match.group(2)),
        int(match.group(3)),
    )
    if version < MINIMUM_FSMONITOR_BOOLEAN_GIT_VERSION:
        raise RuntimeError(
            "Git "
            f"{MINIMUM_FSMONITOR_BOOLEAN_GIT_VERSION_TEXT} or newer is required "
            "before core.fsmonitor=false can be used as a disable control"
        )
    return version


def _bounded_git_worktree_root(root: Path, gitdir: Path) -> tuple[int, bytes, bytes]:
    return _bounded_git_command(
        root,
        [
            "git",
            "-C",
            str(root),
            f"--git-dir={gitdir}",
            "rev-parse",
            "--path-format=absolute",
            "--show-toplevel",
        ],
        label="git worktree identity",
    )


def _bounded_git_ls_files(
    root: Path,
    gitdir: Path,
    *,
    index_descriptor: int | None = None,
    git_command: str = "git",
    git_pass_fds: tuple[int, ...] = (),
    inherit_non_git_environment: bool = True,
) -> tuple[int, bytes, bytes]:
    environment = {
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_OPTIONAL_LOCKS": "0",
    }
    require_git_fsmonitor_boolean_support(
        root,
        git_command=git_command,
        git_pass_fds=git_pass_fds,
        inherit_non_git_environment=inherit_non_git_environment,
        environment=environment,
    )
    pass_fds = git_pass_fds
    if index_descriptor is not None:
        descriptor_path = Path("/dev/fd") / str(index_descriptor)
        if not descriptor_path.exists():
            raise RuntimeError(
                "git index snapshot requires an available /dev/fd descriptor path"
            )
        environment["GIT_INDEX_FILE"] = str(descriptor_path)
        pass_fds = (*git_pass_fds, index_descriptor)
    return _bounded_git_command(
        root,
        [
            git_command,
            "--no-optional-locks",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.untrackedCache=false",
            "-C",
            str(root),
            f"--git-dir={gitdir}",
            f"--work-tree={root}",
            "ls-files",
            "--stage",
            "--sparse",
            "-z",
        ],
        label="git ls-files",
        environment=environment,
        pass_fds=pass_fds,
        inherit_non_git_environment=inherit_non_git_environment,
    )


def _control_file_path(
    raw: bytes,
    *,
    prefix: bytes,
    base: Path,
    description: str,
) -> Path:
    if b"\0" in raw:
        raise RuntimeError(f"{description} contains NUL")
    line = raw[:-1] if raw.endswith(b"\n") else raw
    if line.endswith(b"\r"):
        line = line[:-1]
    if b"\n" in line or b"\r" in line or not line.startswith(prefix):
        raise RuntimeError(f"{description} has invalid syntax")
    value = line[len(prefix) :]
    if not value:
        raise RuntimeError(f"{description} has an empty path")
    try:
        decoded = value.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError(f"{description} path is not valid UTF-8: {exc}") from exc
    candidate = Path(decoded)
    if not candidate.is_absolute():
        candidate = base / candidate
    _lexical, physical = _absolute_inspection_path(
        candidate,
        description=description,
    )
    return physical


def _nonempty_directory_identity(path: Path, *, description: str) -> tuple[int, ...]:
    descriptor, _lexical = _open_directory_descriptor(path, description=description)
    try:
        metadata = os.fstat(descriptor)
        with os.scandir(descriptor) as entries:
            if next(entries, None) is None:
                raise RuntimeError(f"{description} must not be empty: {path}")
        return _stable_identity_metadata(metadata)
    finally:
        _cleanup_release_resources(
            descriptors=((f"{description} directory", descriptor),),
            primary=sys.exception(),
        )


def _git_metadata_binding(
    root: Path,
    inventory: _TreeInventory,
) -> _GitMetadataBinding | None:
    if inventory.root_metadata is None:
        raise RuntimeError("Git worktree root metadata is unavailable")
    _root_lexical, physical_root = _absolute_inspection_path(
        root,
        description="Git worktree root",
    )
    root_descriptor, _lexical = _open_directory_descriptor(
        physical_root,
        description="Git worktree root",
    )
    try:
        root_metadata = os.fstat(root_descriptor)
    finally:
        _cleanup_release_resources(
            descriptors=(("Git worktree root", root_descriptor),),
            primary=sys.exception(),
        )
    if _stable_identity_metadata(root_metadata) != _stable_identity_metadata(
        inventory.root_metadata
    ):
        raise RuntimeError("Git worktree root changed after release-tree enumeration")

    if ".git" in inventory.symlinks or ".git" in inventory.special:
        raise RuntimeError(
            "Git metadata path must be a regular file or directory without symlinks: .git"
        )
    git_directory_metadata = inventory.directories.get(".git")
    gitfile_metadata = inventory.files.get(".git")
    if git_directory_metadata is None and gitfile_metadata is None:
        return None

    control_path = physical_root / ".git"
    backlink_identity: tuple[int, ...] | None = None
    if git_directory_metadata is not None:
        gitdir = control_path
        control_identity = _nonempty_directory_identity(
            control_path,
            description="Git metadata directory",
        )
        if control_identity != _stable_identity_metadata(git_directory_metadata):
            raise RuntimeError("Git metadata directory changed after release-tree enumeration")
        gitdir_identity = control_identity
    else:
        if gitfile_metadata is None:
            raise RuntimeError("Git metadata classification is inconsistent")
        if gitfile_metadata.st_nlink != 1:
            raise RuntimeError("Git metadata file must have exactly one hard link: .git")
        raw = _read_stable_file_bytes(
            control_path,
            description="Git metadata file",
            expected=gitfile_metadata,
            max_bytes=64 * 1024,
        )
        gitdir = _control_file_path(
            raw,
            prefix=b"gitdir: ",
            base=physical_root,
            description="Git metadata file",
        )
        control_identity = safe_paths.stable_file_metadata(gitfile_metadata)
        gitdir_identity = _nonempty_directory_identity(
            gitdir,
            description="linked-worktree Git directory",
        )
        backlink = gitdir / "gitdir"
        backlink_binding = _open_regular_descriptor(
            backlink,
            description="linked-worktree Git backlink",
        )
        backlink_descriptor = backlink_binding.descriptor
        backlink_metadata = backlink_binding.metadata
        try:
            if backlink_metadata.st_size > 64 * 1024:
                raise RuntimeError("linked-worktree Git backlink exceeds 65536 bytes")
            chunks: list[bytes] = []
            while chunk := os.read(backlink_descriptor, 64 * 1024):
                chunks.append(chunk)
            after = os.fstat(backlink_descriptor)
            if safe_paths.stable_file_metadata(after) != safe_paths.stable_file_metadata(
                backlink_metadata
            ):
                raise RuntimeError("linked-worktree Git backlink changed while being read")
            backlink_binding.require_current(
                description="linked-worktree Git backlink"
            )
        finally:
            _close_preserving_primary(
                backlink_binding,
                description="linked-worktree Git backlink",
                primary=sys.exception(),
            )
        backlink_target = _control_file_path(
            b"".join(chunks),
            prefix=b"",
            base=gitdir,
            description="linked-worktree Git backlink",
        )
        if backlink_target != control_path:
            raise RuntimeError(
                "linked-worktree Git backlink does not identify the inspected worktree .git file"
            )
        backlink_identity = safe_paths.stable_file_metadata(backlink_metadata)

    return _GitMetadataBinding(
        physical_root=physical_root,
        gitdir=gitdir,
        root_identity=_stable_identity_metadata(root_metadata),
        control_identity=control_identity,
        gitdir_identity=gitdir_identity,
        backlink_identity=backlink_identity,
    )


def _git_index_object_format(content: bytes) -> str:
    if len(content) < 32 or content[:4] != b"DIRC":
        raise RuntimeError("Git index snapshot has an invalid header")
    version = int.from_bytes(content[4:8], "big")
    if version not in {2, 3, 4}:
        raise RuntimeError(
            f"Git index snapshot uses unsupported format version: {version}"
        )
    matches: list[str] = []
    if len(content) >= 20 and hashlib.sha1(content[:-20]).digest() == content[-20:]:
        matches.append("sha1")
    if len(content) >= 32 and hashlib.sha256(content[:-32]).digest() == content[-32:]:
        matches.append("sha256")
    if len(matches) != 1:
        raise RuntimeError(
            "Git index snapshot checksum is missing, skipped, ambiguous, or invalid"
        )
    return matches[0]


def _copy_git_index_snapshot(
    index: _RegularFileBinding,
    *,
    temporary_root: Path | None = None,
) -> tuple[BinaryIO, str]:
    before = os.fstat(index.descriptor)
    if before.st_size > GIT_INDEX_MAX_BYTES:
        raise RuntimeError(
            f"Git index exceeds the {GIT_INDEX_MAX_BYTES}-byte input limit"
        )
    os.lseek(index.descriptor, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = os.read(
            index.descriptor,
            min(1024 * 1024, GIT_INDEX_MAX_BYTES - total + 1),
        )
        if not chunk:
            break
        total += len(chunk)
        if total > GIT_INDEX_MAX_BYTES:
            raise RuntimeError(
                f"Git index exceeds the {GIT_INDEX_MAX_BYTES}-byte input limit"
            )
        chunks.append(chunk)
    after = os.fstat(index.descriptor)
    if (
        safe_paths.stable_file_metadata(before)
        != safe_paths.stable_file_metadata(after)
        or total != after.st_size
    ):
        raise RuntimeError("Git index changed while its immutable snapshot was created")
    index.require_current(description="Git index")
    content = b"".join(chunks)
    object_format = _git_index_object_format(content)
    snapshot = tempfile.TemporaryFile(mode="w+b", dir=temporary_root)
    try:
        offset = 0
        descriptor = snapshot.fileno()
        while offset < len(content):
            written = os.write(descriptor, content[offset:])
            if written <= 0:
                raise OSError("Git index snapshot write made no progress")
            offset += written
        os.lseek(descriptor, 0, os.SEEK_SET)
        return snapshot, object_format
    except BaseException as primary:
        try:
            _close_snapshot_file(snapshot)
        except BaseException as cleanup:
            primary.add_note(f"Git index snapshot cleanup failure: {cleanup}")
        raise


def parse_git_stage_entries(
    stdout: bytes,
    *,
    object_format: str,
) -> tuple[GitStageEntry, ...]:
    if stdout and not stdout.endswith(b"\0"):
        raise RuntimeError("git ls-files returned unterminated NUL-delimited output")
    oid_length = 40 if object_format == "sha1" else 64
    entries: list[GitStageEntry] = []
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
            or re.fullmatch(rb"[0-9a-f]{%d}" % oid_length, fields[1]) is None
            or fields[2] not in {b"0", b"1", b"2", b"3"}
        ):
            raise RuntimeError("git ls-files returned a malformed stage record")
        if fields[0] == b"040000":
            raise RuntimeError(
                "sparse Git indexes are unsupported for release inventory"
            )
        try:
            path = raw_path.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RuntimeError(
                f"git ls-files returned a path that is not valid UTF-8: {exc}"
            ) from exc
        entries.append(
            GitStageEntry(
                mode=fields[0].decode("ascii"),
                oid=fields[1].decode("ascii"),
                stage=int(fields[2]),
                path=path,
            )
        )
    return tuple(entries)


def _parse_git_stage_inventory(
    stdout: bytes,
    *,
    object_format: str,
) -> frozenset[str]:
    return frozenset(
        entry.path
        for entry in parse_git_stage_entries(
            stdout,
            object_format=object_format,
        )
    )


def _tracked_files_from_git_index_snapshot(
    root: Path,
    snapshot: BinaryIO,
    *,
    object_format: str,
    git_command: str = "git",
    git_pass_fds: tuple[int, ...] = (),
    temporary_root: Path | None = None,
    inherit_non_git_environment: bool = True,
) -> frozenset[str]:
    return frozenset(
        entry.path
        for entry in git_stage_entries_from_index_snapshot(
            root,
            snapshot,
            object_format=object_format,
            git_command=git_command,
            git_pass_fds=git_pass_fds,
            temporary_root=temporary_root,
            inherit_non_git_environment=inherit_non_git_environment,
        )
    )


def git_stage_entries_from_index_snapshot(
    root: Path,
    snapshot: BinaryIO,
    *,
    object_format: str,
    git_command: str = "git",
    git_pass_fds: tuple[int, ...] = (),
    temporary_root: Path | None = None,
    inherit_non_git_environment: bool = True,
) -> tuple[GitStageEntry, ...]:
    """Return exact entries from one retained immutable index snapshot."""

    with tempfile.TemporaryDirectory(
        prefix="mpa-git-index-",
        dir=temporary_root,
    ) as temp_dir:
        gitdir = Path(temp_dir) / "gitdir"
        gitdir.mkdir(mode=0o700)
        (gitdir / "objects").mkdir(mode=0o700)
        (gitdir / "refs").mkdir(mode=0o700)
        (gitdir / "HEAD").write_text("ref: refs/heads/main\n", encoding="ascii")
        config = "[core]\n\trepositoryformatversion = 0\n\tbare = false\n"
        if object_format == "sha256":
            config = (
                "[core]\n\trepositoryformatversion = 1\n\tbare = false\n"
                "[extensions]\n\tobjectformat = sha256\n"
            )
        (gitdir / "config").write_text(config, encoding="ascii")
        os.lseek(snapshot.fileno(), 0, os.SEEK_SET)
        returncode, stdout, stderr = _bounded_git_ls_files(
            root,
            gitdir,
            index_descriptor=snapshot.fileno(),
            git_command=git_command,
            git_pass_fds=git_pass_fds,
            inherit_non_git_environment=inherit_non_git_environment,
        )
    detail = stderr.decode("utf-8", errors="replace").strip()
    if returncode != 0 or detail:
        message = "immutable Git index snapshot is unsupported or could not be parsed"
        if detail:
            message += f": {detail}"
        raise RuntimeError(message)
    return parse_git_stage_entries(stdout, object_format=object_format)


def _open_git_inventory_binding(
    root: Path,
    inventory: _TreeInventory,
    *,
    git_executable: GitExecutableBinding | None = None,
    git_command: str = "git",
    git_pass_fds: tuple[int, ...] = (),
    temporary_root: Path | None = None,
    inherit_non_git_environment: bool = True,
) -> _GitInventoryBinding | None:
    if git_executable is not None:
        if (
            git_command != "git"
            or git_pass_fds
            or inherit_non_git_environment is not True
        ):
            raise ValueError(
                "bound Git executable cannot be combined with an independent Git command policy"
            )
        git_executable.require_current()
        git_command = git_executable.command
        git_pass_fds = git_executable.pass_fds
        inherit_non_git_environment = False
    metadata = _git_metadata_binding(root, inventory)
    if metadata is None:
        return None
    gitdir_binding = safe_paths.open_output_directory(
        metadata.gitdir,
        create_missing=False,
    )
    index_binding: _RegularFileBinding | None = None
    snapshot: BinaryIO | None = None
    try:
        if _stable_identity_metadata(os.fstat(gitdir_binding.descriptor)) != (
            metadata.gitdir_identity
        ):
            raise RuntimeError("Git metadata directory changed before index binding")
        try:
            index_binding = _open_regular_descriptor(
                metadata.gitdir / "index",
                description="Git index",
            )
        except FileNotFoundError:
            result = _GitInventoryBinding(
                root=root,
                inventory=inventory,
                metadata=metadata,
                gitdir=gitdir_binding,
                index=None,
                snapshot_file=None,
                object_format=None,
                tracked_files=frozenset(),
            )
            result.require_current()
            if git_executable is not None:
                git_executable.require_current()
            return result
        snapshot, object_format = _copy_git_index_snapshot(
            index_binding,
            temporary_root=temporary_root,
        )
        tracked_files = _tracked_files_from_git_index_snapshot(
            metadata.physical_root,
            snapshot,
            object_format=object_format,
            git_command=git_command,
            git_pass_fds=git_pass_fds,
            temporary_root=temporary_root,
            inherit_non_git_environment=inherit_non_git_environment,
        )
        if git_executable is not None:
            git_executable.require_current()
        result = _GitInventoryBinding(
            root=root,
            inventory=inventory,
            metadata=metadata,
            gitdir=gitdir_binding,
            index=index_binding,
            snapshot_file=snapshot,
            object_format=object_format,
            tracked_files=tracked_files,
        )
        result.require_current()
        return result
    except BaseException as primary:
        _close_git_inventory_resources(
            snapshot,
            index_binding,
            gitdir_binding,
            primary=primary,
        )
        raise


def git_tracked_files(
    root: Path,
    *,
    git_executable: GitExecutableBinding | None = None,
    _inventory: _TreeInventory | None = None,
    _binding_sink: list[_GitInventoryBinding] | None = None,
) -> set[str] | None:
    inventory = _inventory_release_tree(root) if _inventory is None else _inventory
    if inventory.errors:
        raise RuntimeError("; ".join(inventory.errors))
    binding = _open_git_inventory_binding(
        root,
        inventory,
        git_executable=git_executable,
    )
    if binding is None:
        return None
    retained = False
    try:
        binding.require_current()
        tracked_files = set(binding.tracked_files)
        if _binding_sink is not None:
            _binding_sink.append(binding)
            retained = True
        return tracked_files
    finally:
        if not retained:
            _close_preserving_primary(
                binding,
                description="Git tracked inventory",
                primary=sys.exception(),
            )


def _constant_string_expression_value(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _constant_string_expression_value(node.left)
        right = _constant_string_expression_value(node.right)
        if left is not None and right is not None:
            return left + right
    return None


def _modeled_scanner_reference_span(rel: str, line: str) -> tuple[int, int] | None:
    """Return the span of an exact scanner pattern declaration, if present."""

    if rel != "scripts/public_release_check.py":
        return None
    start = len(line) - len(line.lstrip())
    end = len(line.rstrip())
    source = line[start:end]
    if source.endswith(","):
        source = source[:-1].rstrip()
    if not source:
        return None
    try:
        parsed = ast.parse(source, mode="eval")
    except SyntaxError:
        return None
    expression = parsed.body
    if ast.get_source_segment(source, expression) != source:
        return None
    value = _constant_string_expression_value(expression)
    if value not in SCANNER_MODELED_REFERENCE_PATTERNS:
        return None
    return start, end


def _reference_match_is_allowlisted(
    rel: str,
    line: str,
    reference_match: re.Match[str],
    allowlist: dict[str, tuple[str, ...]],
) -> bool:
    """Return true only when one approved construct contains this exact match."""

    reference_start, reference_end = reference_match.span()
    modeled_span = _modeled_scanner_reference_span(rel, line)
    if modeled_span is not None:
        modeled_start, modeled_end = modeled_span
        if modeled_start <= reference_start and reference_end <= modeled_end:
            return True
    for pattern in allowlist.get(rel, ()):
        for allowed_match in re.finditer(pattern, line):
            allowed_start, allowed_end = allowed_match.span()
            if (
                allowed_start <= reference_start
                and reference_end <= allowed_end
            ):
                return True
    return False


def _all_reference_matches_are_allowlisted(
    reference_re: re.Pattern[str],
    rel: str,
    line: str,
    allowlist: dict[str, tuple[str, ...]],
) -> bool:
    matches = tuple(reference_re.finditer(line))
    return bool(matches) and all(
        _reference_match_is_allowlisted(rel, line, match, allowlist)
        for match in matches
    )


def allowed_private_state_reference(
    rel: str,
    line: str,
    reference_re: re.Pattern[str] = PRIVATE_STATE_RE,
) -> bool:
    return _all_reference_matches_are_allowlisted(
        reference_re,
        rel,
        line,
        PRIVATE_STATE_REFERENCE_ALLOWLIST,
    )


def allowed_host_path_reference(rel: str, line: str) -> bool:
    return _all_reference_matches_are_allowlisted(
        HOST_PATH_RE,
        rel,
        line,
        HOST_PATH_REFERENCE_ALLOWLIST,
    )


def allowed_sensitive_reference(rel: str, line: str) -> bool:
    return _all_reference_matches_are_allowlisted(
        SENSITIVE_LOCAL_REFERENCE_RE,
        rel,
        line,
        SENSITIVE_REFERENCE_ALLOWLIST,
    )


def normalized_sensitive_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")


def high_confidence_assigned_secret(value: object) -> bool:
    if not isinstance(value, str):
        return False
    candidate = value.strip()
    lowered = candidate.casefold()
    if len(candidate) < 20 or any(character.isspace() for character in candidate):
        return False
    if any(marker in lowered for marker in SECRET_PLACEHOLDER_MARKERS):
        return False
    if candidate.startswith(("${", "{{", "$(")):
        return False
    if lowered.startswith(("env:", "environment:", "os.environ", "process.env")):
        return False
    return (
        len(set(candidate)) > 4
        and not set(candidate) <= {"0", "x", "X", "*", "-", "_"}
        and not lowered.endswith((".json", ".pem", ".key", ".p12", ".pfx", ".kdbx"))
    )


def structured_json_secret_keys(value: object) -> set[str]:
    matches: set[str] = set()
    pending = [value]
    while pending:
        current = pending.pop()
        if isinstance(current, dict):
            for key, item in current.items():
                normalized = normalized_sensitive_key(key)
                if normalized in SENSITIVE_JSON_KEYS and high_confidence_assigned_secret(item):
                    matches.add(normalized)
                pending.append(item)
        elif isinstance(current, list):
            pending.extend(current)
    return matches


def sensitive_value_kinds(line: str) -> list[str]:
    kinds = {label for label, pattern in SENSITIVE_VALUE_PATTERNS if pattern.search(line)}
    for assignment in SENSITIVE_ASSIGNMENT_RE.finditer(line):
        value = next(
            (
                assignment.group(group)
                for group in ("double", "single", "bare")
                if assignment.group(group) is not None
            ),
            "",
        )
        if high_confidence_assigned_secret(value):
            kinds.add("assigned secret-like value")
    return sorted(kinds)


def allowed_private_workflow_reference(
    rel: str,
    line: str,
    reference_re: re.Pattern[str] | None = None,
    allowed_gitignore_lines: frozenset[str] = frozenset(),
) -> bool:
    if rel == ".gitignore" and line in allowed_gitignore_lines:
        return True
    if reference_re is None:
        return any(
            re.fullmatch(pattern, line) is not None
            for pattern in PRIVATE_WORKFLOW_SCANNER_ALLOWLIST.get(rel, ())
        )
    return _all_reference_matches_are_allowlisted(
        reference_re,
        rel,
        line,
        PRIVATE_WORKFLOW_SCANNER_ALLOWLIST,
    )


def load_private_workflow_policy(
    root: Path,
    errors: list[str],
    *,
    required: bool = False,
    expected: os.stat_result | None = None,
    inventory_bound: bool = False,
) -> _PrivateWorkflowPolicy | None:
    path = root / PRIVATE_WORKFLOW_PATTERNS_PATH
    if inventory_bound and expected is None:
        if required:
            errors.append(
                "authoring-tree release checks require the local private workflow "
                f"pattern file: {PRIVATE_WORKFLOW_PATTERNS_PATH}"
            )
        return None
    try:
        raw = _read_stable_file_bytes(
            path,
            description="local private workflow pattern file",
            expected=expected,
            max_bytes=safe_paths.DEFAULT_JSON_INPUT_MAX_BYTES,
        )
    except safe_paths.OutputDirectoryBindingError as exc:
        if isinstance(exc.__cause__, FileNotFoundError):
            if required:
                errors.append(
                    "authoring-tree release checks require the local private "
                    f"workflow pattern file: {PRIVATE_WORKFLOW_PATTERNS_PATH}"
                )
            return None
        errors.append(
            "local private workflow pattern file must have a safely bound parent "
            "path without symlink components: "
            f"{PRIVATE_WORKFLOW_PATTERNS_PATH}: {exc}"
        )
        return None
    except FileNotFoundError:
        if required:
            errors.append(
                "authoring-tree release checks require the local private workflow "
                f"pattern file: {PRIVATE_WORKFLOW_PATTERNS_PATH}"
            )
        return None
    except (OSError, ValueError) as exc:
        errors.append(
            "local private workflow pattern file must be a bounded regular file and "
            "must not use symlink path components: "
            f"{PRIVATE_WORKFLOW_PATTERNS_PATH}: {exc}"
        )
        return None
    try:
        data = safe_paths.loads_json_no_duplicates(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        errors.append(
            f"invalid local private workflow pattern file: "
            f"{PRIVATE_WORKFLOW_PATTERNS_PATH}: {exc}"
        )
        return None
    if not isinstance(data, dict):
        errors.append(f"local private workflow pattern file must be a JSON object: {PRIVATE_WORKFLOW_PATTERNS_PATH}")
        return None
    expected_keys = {
        "schema_version",
        "literal_terms",
        "regexes",
        "allowed_gitignore_lines",
    }
    missing_keys = sorted(expected_keys - set(data))
    unknown_keys = sorted(set(data) - expected_keys)
    if missing_keys:
        errors.append(
            "local private workflow pattern file is missing keys: "
            f"{', '.join(missing_keys)}: {PRIVATE_WORKFLOW_PATTERNS_PATH}"
        )
    if unknown_keys:
        errors.append(
            "local private workflow pattern file has unknown keys: "
            f"{', '.join(unknown_keys)}: {PRIVATE_WORKFLOW_PATTERNS_PATH}"
        )
    if missing_keys or unknown_keys:
        return None
    if type(data.get("schema_version")) is not int or data.get("schema_version") != 2:
        errors.append(f"local private workflow pattern file schema_version must be 2: {PRIVATE_WORKFLOW_PATTERNS_PATH}")
        return None
    literal_terms = data["literal_terms"]
    regexes = data["regexes"]
    raw_allowed_gitignore_lines = data["allowed_gitignore_lines"]
    if not isinstance(literal_terms, list) or not all(isinstance(term, str) and term.strip() for term in literal_terms):
        errors.append(f"local private workflow literal_terms must be non-empty strings: {PRIVATE_WORKFLOW_PATTERNS_PATH}")
        return None
    if not isinstance(regexes, list) or not all(isinstance(pattern, str) and pattern.strip() for pattern in regexes):
        errors.append(f"local private workflow regexes must be non-empty strings: {PRIVATE_WORKFLOW_PATTERNS_PATH}")
        return None
    if not isinstance(raw_allowed_gitignore_lines, list) or not all(
        isinstance(line, str) and line.strip() == line and line
        for line in raw_allowed_gitignore_lines
    ):
        errors.append(
            "local private workflow allowed_gitignore_lines must be a list of "
            "non-empty, whitespace-exact strings: "
            f"{PRIVATE_WORKFLOW_PATTERNS_PATH}"
        )
        return None
    allowed_gitignore_lines = frozenset(raw_allowed_gitignore_lines)
    if len(allowed_gitignore_lines) != len(raw_allowed_gitignore_lines):
        errors.append(
            "local private workflow allowed_gitignore_lines must not contain "
            f"duplicates: {PRIVATE_WORKFLOW_PATTERNS_PATH}"
        )
        return None
    for line in allowed_gitignore_lines:
        if not line.startswith("!/"):
            errors.append(
                "local private workflow allowed_gitignore_lines may contain only "
                f"exact root-relative re-inclusions: {PRIVATE_WORKFLOW_PATTERNS_PATH}"
            )
            return None
        reinclude_path = line[2:]
        if not _safe_manifest_path(reinclude_path) or not is_public_excluded(
            reinclude_path
        ):
            errors.append(
                "local private workflow allowed_gitignore_lines may re-include only "
                "safe paths from the public-excluded namespace: "
                f"{PRIVATE_WORKFLOW_PATTERNS_PATH}"
            )
            return None
    pattern_parts = [r"(?<![\w-])" + re.escape(term.strip()) + r"(?![\w-])" for term in literal_terms]
    pattern_parts.extend(regexes)
    if not pattern_parts:
        errors.append(
            "local private workflow pattern file must define at least one literal_terms or regexes entry: "
            f"{PRIVATE_WORKFLOW_PATTERNS_PATH}"
        )
        return None
    try:
        reference_re = re.compile(
            "|".join(f"(?:{part})" for part in pattern_parts),
            re.IGNORECASE,
        )
    except re.error as exc:
        errors.append(f"invalid local private workflow regex in {PRIVATE_WORKFLOW_PATTERNS_PATH}: {exc}")
        return None
    dead_allowances = sorted(
        line for line in allowed_gitignore_lines if reference_re.search(line) is None
    )
    if dead_allowances:
        errors.append(
            "local private workflow allowed_gitignore_lines must each contain a "
            "configured private workflow term: "
            f"{PRIVATE_WORKFLOW_PATTERNS_PATH}"
        )
        return None
    return _PrivateWorkflowPolicy(
        reference_re=reference_re,
        allowed_gitignore_lines=allowed_gitignore_lines,
    )


def public_gitignore_reinclude_errors(
    root: Path,
    *,
    _inventory: _TreeInventory | None = None,
) -> list[str]:
    inventory = _inventory_release_tree(root) if _inventory is None else _inventory
    metadata = inventory.files.get(".gitignore")
    if metadata is None or metadata.st_nlink != 1:
        return []
    errors: list[str] = []
    excluded_prefixes = tuple(prefix.rstrip("/") for prefix in public_surface.PUBLIC_EXCLUDED_PREFIXES)
    try:
        lines = _iter_stable_utf8_lines(
            root / ".gitignore",
            description="public .gitignore",
            expected=metadata,
        )
        for line_no, raw_line in enumerate(lines, start=1):
            line = raw_line.strip()
            if not line.startswith("!"):
                continue
            pattern = line[1:].lstrip("/")
            if (
                pattern.startswith(excluded_prefixes)
                or pattern.startswith("internal_")
                or pattern.startswith("INTERNAL_")
                or pattern.startswith("*_STATE")
                or pattern.startswith("*_Commit")
            ):
                errors.append(f"public .gitignore re-includes private/local authoring path: .gitignore:{line_no}")
    except (OSError, UnicodeError, ValueError) as exc:
        errors.append(f"public .gitignore could not be read safely as UTF-8: {exc}")
    return errors


def file_sha256(
    path: Path,
    *,
    _expected: os.stat_result | None = None,
) -> str:
    digest = hashlib.sha256()
    for chunk in _iter_stable_file_chunks(
        path,
        description="public release file",
        expected=_expected,
    ):
        digest.update(chunk)
    return digest.hexdigest()


def posix_rwx_mode(metadata: os.stat_result) -> int:
    """Return only portable POSIX owner/group/other rwx permission bits."""

    return stat.S_IMODE(metadata.st_mode) & 0o777


def stable_file_snapshot(
    path: Path,
    *,
    _expected: os.stat_result | None = None,
) -> tuple[str, int]:
    """Return a content digest and stable POSIX rwx mode for one regular file."""

    binding = _open_regular_descriptor(
        path,
        description="public release file",
        expected=_expected,
    )
    descriptor = binding.descriptor
    before = binding.metadata
    lexical = binding.lexical_path
    digest = hashlib.sha256()
    try:
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
        after = os.fstat(descriptor)
        if safe_paths.stable_file_metadata(before) != safe_paths.stable_file_metadata(after):
            raise ValueError(f"public release file changed while it was being read: {lexical}")
        binding.require_current(description="public release file")
        return digest.hexdigest(), posix_rwx_mode(before)
    finally:
        _close_preserving_primary(
            binding,
            description="public release file snapshot",
            primary=sys.exception(),
        )


def stable_file_bytes(
    path: Path,
    *,
    expected_snapshot: tuple[str, int],
) -> bytes:
    """Read one no-follow regular file and require an exact digest/mode snapshot."""

    binding = _open_regular_descriptor(
        path,
        description="public export source file",
    )
    descriptor = binding.descriptor
    before = binding.metadata
    lexical = binding.lexical_path
    chunks: list[bytes] = []
    digest = hashlib.sha256()
    try:
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
            digest.update(chunk)
        after = os.fstat(descriptor)
        if safe_paths.stable_file_metadata(before) != safe_paths.stable_file_metadata(after):
            raise ValueError(
                f"public export source file changed while it was being read: {lexical}"
            )
        actual_snapshot = (digest.hexdigest(), posix_rwx_mode(before))
        if actual_snapshot != expected_snapshot:
            raise ValueError(
                "public source content or POSIX rwx mode changed between "
                f"release validation and export read: {lexical}"
            )
        binding.require_current(description="public export source file")
        return b"".join(chunks)
    finally:
        _close_preserving_primary(
            binding,
            description="public export source file",
            primary=sys.exception(),
        )


def public_export_marker_payload(
    records: Mapping[str, tuple[str, int]],
) -> dict[str, object]:
    """Render ownership data from retained expected records, never a tree rescan."""

    unsafe = sorted(path for path in records if not _safe_manifest_path(path))
    if unsafe:
        raise ValueError(
            "public export ownership records have unsafe or non-canonical paths: "
            + ", ".join(unsafe)
        )
    missing_sentinels = sorted(PUBLIC_EXPORT_SENTINEL_FILES - set(records))
    if missing_sentinels:
        raise ValueError(
            "public export ownership records are missing framework sentinel files: "
            + ", ".join(missing_sentinels)
        )
    invalid = sorted(
        path
        for path, record in records.items()
        if (
            not isinstance(record, tuple)
            or len(record) != 2
            or not isinstance(record[0], str)
            or re.fullmatch(r"[0-9a-f]{64}", record[0]) is None
            or type(record[1]) is not int
            or not 0 <= record[1] <= 0o777
        )
    )
    if invalid:
        raise ValueError(
            "public export ownership records have invalid digest/mode values for: "
            + ", ".join(invalid)
        )
    files = {
        rel: {"posix_mode": mode, "sha256": digest}
        for rel, (digest, mode) in sorted(records.items())
    }
    return {
        "files": files,
        "generator": PUBLIC_EXPORT_GENERATOR,
        "schema_version": PUBLIC_EXPORT_OWNERSHIP_SCHEMA_VERSION,
    }


def public_export_marker_bytes(
    records: Mapping[str, tuple[str, int]],
) -> bytes:
    """Render the sole canonical public-export ownership marker encoding."""

    return (
        json.dumps(
            public_export_marker_payload(records),
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _safe_manifest_path(value: str) -> bool:
    if not value or "\\" in value:
        return False
    path = PurePosixPath(value)
    return (
        not path.is_absolute()
        and path.as_posix() == value
        and value != "."
        and all(part not in {"", ".", ".."} for part in path.parts)
        and value != PUBLIC_EXPORT_OWNERSHIP_MARKER
    )


def _manifest_parent_directories(paths: set[str]) -> set[str]:
    directories: set[str] = set()
    for value in paths:
        parent = PurePosixPath(value).parent
        while parent.as_posix() != ".":
            directories.add(parent.as_posix())
            parent = parent.parent
    return directories


def _ownership_marker_contract(
    raw: dict[str, object],
) -> tuple[list[str], dict[str, object] | None, set[str], list[str], list[str]]:
    errors: list[str] = []
    keys = set(raw)
    missing = sorted(PUBLIC_EXPORT_MARKER_KEYS - keys)
    unknown = sorted(keys - PUBLIC_EXPORT_MARKER_KEYS)
    if missing:
        errors.append(f"public export ownership marker is missing keys: {', '.join(missing)}")
    if unknown:
        errors.append(f"public export ownership marker has unknown keys: {', '.join(unknown)}")
    if raw.get("generator") != PUBLIC_EXPORT_GENERATOR:
        errors.append("public export ownership marker generator is invalid")
    if type(raw.get("schema_version")) is not int or raw.get("schema_version") != PUBLIC_EXPORT_OWNERSHIP_SCHEMA_VERSION:
        errors.append(f"public export ownership marker schema_version must equal {PUBLIC_EXPORT_OWNERSHIP_SCHEMA_VERSION}")

    raw_files = raw.get("files")
    if not isinstance(raw_files, dict):
        errors.append("public export ownership marker files must be an object")
        return errors, None, set(), [], []
    declared_paths = set(raw_files)
    unsafe_paths = sorted(path for path in declared_paths if not _safe_manifest_path(path))
    if unsafe_paths:
        errors.append("public export ownership marker has unsafe or non-canonical file paths: " + ", ".join(unsafe_paths))
    missing_sentinels = sorted(PUBLIC_EXPORT_SENTINEL_FILES - declared_paths)
    if missing_sentinels:
        errors.append("public export ownership marker is missing framework sentinel files: " + ", ".join(missing_sentinels))
    invalid_records = sorted(
        path
        for path, record in raw_files.items()
        if (
            not isinstance(record, dict)
            or set(record) != PUBLIC_EXPORT_FILE_RECORD_KEYS
            or not isinstance(record.get("sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", record["sha256"]) is None
            or type(record.get("posix_mode")) is not int
            or not 0 <= record["posix_mode"] <= 0o777
        )
    )
    if invalid_records:
        errors.append(
            "public export ownership marker has invalid digest/mode records for: "
            + ", ".join(invalid_records)
        )
    return errors, raw_files, declared_paths, unsafe_paths, invalid_records


@dataclass(frozen=True)
class _DescriptorPublicExportRead:
    snapshot: PublicExportTreeSnapshot
    marker_bytes: bytes | None
    gitignore_bytes: bytes | None
    mutation_signature: tuple[object, ...]


def _fresh_directory_names(directory_descriptor: int) -> tuple[str, ...]:
    scan_descriptor = os.open(
        ".",
        (
            os.O_RDONLY
            | _required_open_flag("O_DIRECTORY")
            | _required_open_flag("O_NOFOLLOW")
            | getattr(os, "O_CLOEXEC", 0)
        ),
        dir_fd=directory_descriptor,
    )
    try:
        if (
            safe_paths.stable_file_metadata(os.fstat(scan_descriptor))
            != safe_paths.stable_file_metadata(os.fstat(directory_descriptor))
        ):
            raise ValueError("public-export directory changed before enumeration")
        with os.scandir(scan_descriptor) as entries:
            return tuple(sorted(entry.name for entry in entries))
    finally:
        _cleanup_release_resources(
            descriptors=(("public-export directory scan", scan_descriptor),),
            primary=sys.exception(),
        )


def _closed_public_export_read(
    root_descriptor: int,
) -> _DescriptorPublicExportRead:
    """Read one stable export through retained descriptors and closed traversals."""

    directory_flags = (
        os.O_RDONLY
        | _required_open_flag("O_DIRECTORY")
        | _required_open_flag("O_NOFOLLOW")
        | getattr(os, "O_CLOEXEC", 0)
    )
    file_flags = (
        os.O_RDONLY
        | _required_open_flag("O_NOFOLLOW")
        | _required_open_flag("O_NONBLOCK")
        | getattr(os, "O_CLOEXEC", 0)
    )
    directories: list[tuple[str, int]] = []
    files: list[tuple[str, str, int]] = []
    signatures: list[tuple[str, str, tuple[int, ...]]] = []
    marker_bytes: bytes | None = None
    gitignore_bytes: bytes | None = None

    def visit(directory_descriptor: int, parent: str) -> None:
        nonlocal marker_bytes, gitignore_bytes
        directory_before = os.fstat(directory_descriptor)
        if not stat.S_ISDIR(directory_before.st_mode):
            raise ValueError("bound public-export object is not a directory")
        before_signature = safe_paths.stable_file_metadata(directory_before)
        initial_names = _fresh_directory_names(directory_descriptor)
        for name in initial_names:
            try:
                name.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise ValueError(
                    "public-export path names must be valid UTF-8"
                ) from exc
            relative = name if not parent else f"{parent}/{name}"
            relative_path = PurePosixPath(relative)
            if (
                "\\" in relative
                or relative_path.as_posix() != relative
                or any(part in {"", ".", ".."} for part in relative_path.parts)
            ):
                raise ValueError(
                    f"public-export tree contains a non-canonical path: {relative}"
                )
            named_before = os.stat(
                name,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
            if stat.S_ISDIR(named_before.st_mode):
                child = os.open(
                    name,
                    directory_flags,
                    dir_fd=directory_descriptor,
                )
                try:
                    child_before = os.fstat(child)
                    if (
                        safe_paths.stable_file_metadata(child_before)
                        != safe_paths.stable_file_metadata(named_before)
                    ):
                        raise ValueError(
                            "public-export directory changed before inspection: "
                            f"{relative}"
                        )
                    visit(child, relative)
                    child_after = os.fstat(child)
                    if (
                        safe_paths.stable_file_metadata(child_before)
                        != safe_paths.stable_file_metadata(child_after)
                    ):
                        raise ValueError(
                            "public-export directory changed while inspected: "
                            f"{relative}"
                        )
                    named_after = os.stat(
                        name,
                        dir_fd=directory_descriptor,
                        follow_symlinks=False,
                    )
                    if (
                        safe_paths.stable_file_metadata(named_after)
                        != safe_paths.stable_file_metadata(child_after)
                    ):
                        raise ValueError(
                            "public-export directory name changed while inspected: "
                            f"{relative}"
                        )
                    directories.append((relative, stat.S_IMODE(child_after.st_mode)))
                    signatures.append(
                        (
                            "directory",
                            relative,
                            safe_paths.stable_file_metadata(child_after),
                        )
                    )
                finally:
                    _cleanup_release_resources(
                        descriptors=((f"public-export directory {relative}", child),),
                        primary=sys.exception(),
                    )
                continue
            if not stat.S_ISREG(named_before.st_mode):
                raise ValueError(
                    f"public-export tree contains unsupported entry: {relative}"
                )
            if named_before.st_nlink != 1:
                raise ValueError(
                    f"public-export tree contains multiply-linked file: {relative}"
                )
            file_descriptor = os.open(
                name,
                file_flags,
                dir_fd=directory_descriptor,
            )
            digest = hashlib.sha256()
            captured = bytearray()
            capture_limit: int | None = None
            if relative == PUBLIC_EXPORT_OWNERSHIP_MARKER:
                capture_limit = safe_paths.DEFAULT_JSON_INPUT_MAX_BYTES
            elif relative == ".gitignore":
                capture_limit = len(
                    public_surface.PUBLIC_EXPORT_GITIGNORE_TEXT.encode("utf-8")
                ) + 1
            try:
                file_before = os.fstat(file_descriptor)
                if (
                    not stat.S_ISREG(file_before.st_mode)
                    or file_before.st_nlink != 1
                    or safe_paths.stable_file_metadata(file_before)
                    != safe_paths.stable_file_metadata(named_before)
                ):
                    raise ValueError(
                        f"public-export file changed before inspection: {relative}"
                    )
                while chunk := os.read(file_descriptor, 1024 * 1024):
                    digest.update(chunk)
                    if capture_limit is not None:
                        captured.extend(chunk)
                        if len(captured) > capture_limit:
                            raise ValueError(
                                f"public-export control file exceeds its size limit: {relative}"
                            )
                file_after = os.fstat(file_descriptor)
                if (
                    safe_paths.stable_file_metadata(file_before)
                    != safe_paths.stable_file_metadata(file_after)
                ):
                    raise ValueError(
                        f"public-export file changed while inspected: {relative}"
                    )
                named_after = os.stat(
                    name,
                    dir_fd=directory_descriptor,
                    follow_symlinks=False,
                )
                if (
                    safe_paths.stable_file_metadata(named_after)
                    != safe_paths.stable_file_metadata(file_after)
                ):
                    raise ValueError(
                        f"public-export file name changed while inspected: {relative}"
                    )
                if relative == PUBLIC_EXPORT_OWNERSHIP_MARKER:
                    marker_bytes = bytes(captured)
                elif relative == ".gitignore":
                    gitignore_bytes = bytes(captured)
                files.append(
                    (
                        relative,
                        digest.hexdigest(),
                        stat.S_IMODE(file_after.st_mode),
                    )
                )
                signatures.append(
                    (
                        "file",
                        relative,
                        safe_paths.stable_file_metadata(file_after),
                    )
                )
            finally:
                _cleanup_release_resources(
                    descriptors=((f"public-export file {relative}", file_descriptor),),
                    primary=sys.exception(),
                )
        if _fresh_directory_names(directory_descriptor) != initial_names:
            label = parent or "."
            raise ValueError(
                f"public-export directory entries changed while inspected: {label}"
            )
        directory_after = os.fstat(directory_descriptor)
        if (
            safe_paths.stable_file_metadata(directory_after)
            != before_signature
        ):
            label = parent or "."
            raise ValueError(
                f"public-export directory changed while inspected: {label}"
            )

    root_before = os.fstat(root_descriptor)
    visit(root_descriptor, "")
    root_after = os.fstat(root_descriptor)
    if (
        safe_paths.stable_file_metadata(root_before)
        != safe_paths.stable_file_metadata(root_after)
    ):
        raise ValueError("bound public-export root changed while inspected")
    root_signature = safe_paths.stable_file_metadata(root_after)
    return _DescriptorPublicExportRead(
        snapshot=PublicExportTreeSnapshot(
            root_mode=stat.S_IMODE(root_after.st_mode),
            directories=tuple(sorted(directories)),
            files=tuple(sorted(files)),
        ),
        marker_bytes=marker_bytes,
        gitignore_bytes=gitignore_bytes,
        mutation_signature=(root_signature, tuple(sorted(signatures))),
    )


def public_export_tree_snapshot(
    root_descriptor: int,
) -> PublicExportTreeSnapshot:
    """Return a closed, exact-mode snapshot from a caller-owned root fd."""

    return _closed_public_export_read(root_descriptor).snapshot


def _parse_public_export_marker_bytes(
    marker_bytes: bytes,
) -> tuple[dict[str, object] | None, list[str]]:
    try:
        raw = safe_paths.loads_json_no_duplicates(marker_bytes.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        return None, [
            "invalid public export ownership marker: "
            f"{PUBLIC_EXPORT_OWNERSHIP_MARKER}: {exc}"
        ]
    if not isinstance(raw, dict):
        return None, [
            "public export ownership marker must be a JSON object: "
            f"{PUBLIC_EXPORT_OWNERSHIP_MARKER}"
        ]
    return raw, []


def _normalized_marker_records(
    raw_files: dict[str, object],
) -> dict[str, tuple[str, int]]:
    return {
        relative: (record["sha256"], record["posix_mode"])
        for relative, record in raw_files.items()
        if (
            isinstance(record, dict)
            and isinstance(record.get("sha256"), str)
            and type(record.get("posix_mode")) is int
        )
    }


def _public_export_ownership_descriptor_result(
    root_descriptor: int,
    *,
    expected_records: Mapping[str, tuple[str, int]] | None,
    require_generated_gitignore: bool,
) -> tuple[list[str], PublicExportTreeSnapshot | None]:
    errors: list[str] = []
    try:
        first = _closed_public_export_read(root_descriptor)
    except (OSError, ValueError) as exc:
        return [f"public export ownership tree could not be read safely: {exc}"], None
    snapshot = first.snapshot
    if snapshot.root_mode != PUBLIC_EXPORT_ROOT_MODE:
        errors.append(
            "public export ownership root mode must equal "
            f"{PUBLIC_EXPORT_ROOT_MODE:#o}"
        )
    bad_directories = sorted(
        relative
        for relative, mode in snapshot.directories
        if mode != PUBLIC_EXPORT_DIRECTORY_MODE
    )
    if bad_directories:
        errors.append(
            "public export ownership directory mode must equal "
            f"{PUBLIC_EXPORT_DIRECTORY_MODE:#o}: " + ", ".join(bad_directories)
        )
    actual_files = {
        relative: (digest, mode)
        for relative, digest, mode in snapshot.files
    }
    marker_record = actual_files.get(PUBLIC_EXPORT_OWNERSHIP_MARKER)
    if first.marker_bytes is None or marker_record is None:
        errors.append(
            f"public export is missing ownership marker: {PUBLIC_EXPORT_OWNERSHIP_MARKER}"
        )
        raw = None
    else:
        if marker_record[1] != PUBLIC_EXPORT_MARKER_MODE:
            errors.append(
                "public export ownership marker POSIX rwx mode must equal "
                f"{PUBLIC_EXPORT_MARKER_MODE:#o}: {PUBLIC_EXPORT_OWNERSHIP_MARKER}"
            )
        raw, parse_errors = _parse_public_export_marker_bytes(first.marker_bytes)
        errors.extend(parse_errors)

    if raw is not None:
        (
            contract_errors,
            raw_files,
            declared_paths,
            unsafe_paths,
            invalid_records,
        ) = _ownership_marker_contract(raw)
        errors.extend(contract_errors)
        if raw_files is not None:
            ordinary_files = set(actual_files) - {PUBLIC_EXPORT_OWNERSHIP_MARKER}
            missing_files = sorted(declared_paths - ordinary_files)
            unexpected_files = sorted(ordinary_files - declared_paths)
            if missing_files:
                errors.append(
                    "public export ownership marker lists missing files: "
                    + ", ".join(missing_files)
                )
            if unexpected_files:
                errors.append(
                    "public export ownership tree has unrecorded files: "
                    + ", ".join(unexpected_files)
                )
            expected_directories = _manifest_parent_directories(declared_paths)
            actual_directories = {
                relative for relative, _mode in snapshot.directories
            }
            missing_directories = sorted(expected_directories - actual_directories)
            unexpected_directories = sorted(actual_directories - expected_directories)
            if missing_directories:
                errors.append(
                    "public export ownership tree is missing directories: "
                    + ", ".join(missing_directories)
                )
            if unexpected_directories:
                errors.append(
                    "public export ownership tree has unrecorded directories: "
                    + ", ".join(unexpected_directories)
                )
            if not contract_errors and not unsafe_paths and not invalid_records:
                normalized = _normalized_marker_records(raw_files)
                digest_mismatched = sorted(
                    relative
                    for relative in declared_paths & ordinary_files
                    if actual_files[relative][0] != normalized[relative][0]
                )
                mode_mismatched = sorted(
                    relative
                    for relative in declared_paths & ordinary_files
                    if actual_files[relative][1] != normalized[relative][1]
                )
                if digest_mismatched:
                    errors.append(
                        "public export ownership marker digest mismatch for: "
                        + ", ".join(digest_mismatched)
                    )
                if mode_mismatched:
                    errors.append(
                        "public export ownership marker POSIX rwx mode mismatch for: "
                        + ", ".join(mode_mismatched)
                    )
                if first.marker_bytes != public_export_marker_bytes(normalized):
                    errors.append(
                        "public export ownership marker does not use its canonical encoding"
                    )
                if expected_records is not None and dict(expected_records) != normalized:
                    errors.append(
                        "public export ownership records do not match retained expectations"
                    )
    if require_generated_gitignore:
        expected_gitignore = public_surface.PUBLIC_EXPORT_GITIGNORE_TEXT.encode("utf-8")
        if first.gitignore_bytes is None:
            errors.append("strict public export is missing generated .gitignore marker")
        elif first.gitignore_bytes != expected_gitignore:
            errors.append(
                "strict public export .gitignore does not match generated public-export marker"
            )
    try:
        second = _closed_public_export_read(root_descriptor)
    except (OSError, ValueError) as exc:
        errors.append(
            f"public export ownership tree could not be confirmed safely: {exc}"
        )
    else:
        if (
            second.snapshot != first.snapshot
            or second.marker_bytes != first.marker_bytes
            or second.gitignore_bytes != first.gitignore_bytes
            or second.mutation_signature != first.mutation_signature
        ):
            errors.append("public export ownership tree changed while it was being verified")
    return errors, snapshot


def public_export_ownership_descriptor_errors(
    root_descriptor: int,
    *,
    expected_records: Mapping[str, tuple[str, int]] | None = None,
    require_generated_gitignore: bool = True,
) -> list[str]:
    """Validate ownership solely through one caller-owned root descriptor."""

    errors, _snapshot = _public_export_ownership_descriptor_result(
        root_descriptor,
        expected_records=expected_records,
        require_generated_gitignore=require_generated_gitignore,
    )
    return errors


def checked_public_export_ownership_descriptor(
    root_descriptor: int,
    *,
    expected_records: Mapping[str, tuple[str, int]] | None = None,
    require_generated_gitignore: bool = True,
) -> PublicExportTreeSnapshot:
    errors, snapshot = _public_export_ownership_descriptor_result(
        root_descriptor,
        expected_records=expected_records,
        require_generated_gitignore=require_generated_gitignore,
    )
    if errors or snapshot is None:
        raise ValueError("public export ownership validation failed: " + "; ".join(errors))
    return snapshot


def public_export_ownership_marker_errors(
    root: Path,
    *,
    _inventory: _TreeInventory | None = None,
) -> list[str]:
    if root.is_symlink():
        return ["public export ownership root must not be a symlink"]
    binding: safe_paths.OutputDirectoryBinding | None = None
    result: list[str] | None = None
    try:
        binding = safe_paths.open_output_directory(
            root,
            create_missing=False,
        )
        if (
            _inventory is not None
            and _inventory.root_metadata is not None
            and safe_paths.stable_file_metadata(os.fstat(binding.descriptor))
            != safe_paths.stable_file_metadata(_inventory.root_metadata)
        ):
            result = [
                "public export ownership root differs from the inventoried release root"
            ]
            return result
        errors = public_export_ownership_descriptor_errors(binding.descriptor)
        try:
            binding.require_unchanged_chain(
                description="public export ownership root"
            )
        except (OSError, ValueError) as exc:
            errors.append(
                "public export ownership root changed while it was checked: "
                f"{exc}"
            )
        result = errors
        return result
    except (OSError, RuntimeError, ValueError) as exc:
        result = [f"public export ownership root could not be opened safely: {exc}"]
        return result
    finally:
        if binding is not None:
            active_failure = sys.exception()
            try:
                binding.close()
            except BaseException as cleanup:
                if active_failure is not None:
                    active_failure.add_note(
                        f"public export ownership root cleanup failure: {cleanup}"
                    )
                elif result is not None and isinstance(cleanup, Exception):
                    result.append(
                        f"public export ownership root cleanup failed: {cleanup}"
                    )
                else:
                    cleanup.add_note(
                        "public export ownership root cleanup interrupted after inspection"
                    )
                    raise


def generated_public_export_marker_errors(
    root: Path,
    *,
    _inventory: _TreeInventory | None = None,
) -> list[str]:
    return public_export_ownership_marker_errors(root, _inventory=_inventory)


def _all_inventory_paths(inventory: _TreeInventory) -> set[str]:
    return set(inventory.files) | set(inventory.directories) | set(inventory.symlinks) | set(inventory.special)


def _authoring_policy_present(inventory: _TreeInventory) -> bool:
    return any(
        rel == "private/authoring" or rel.startswith("private/authoring/")
        for rel in _all_inventory_paths(inventory)
    )


def _release_tree_identity_errors(context: _ReleaseCheckContext) -> list[str]:
    if context.tree_role is ReleaseTreeRole.PUBLIC_EXPORT:
        # Public exports are identity-bound by exporter-generated artifacts.
        # This branch must never consult Git: a copied or added .git path is an
        # ownership-inventory failure, not a reason to reinterpret the tree.
        if context.root_binding is None:
            return ["public export ownership root descriptor is unavailable"]
        return public_export_ownership_descriptor_errors(
            context.root_binding.descriptor
        )

    inventory_paths = _all_inventory_paths(context.inventory)
    if PUBLIC_EXPORT_OWNERSHIP_MARKER in inventory_paths:
        return [
            "authoring-source tree contains reserved public-export ownership "
            f"marker path: {PUBLIC_EXPORT_OWNERSHIP_MARKER}"
        ]
    if context.inventory.errors:
        return list(context.inventory.errors)
    if context.git_inventory is not None:
        retained = context.git_inventory
        if retained.root != context.root:
            return [
                "authoring-source retained Git inventory belongs to a different root"
            ]
        if _inventory_signature(retained.inventory) != _inventory_signature(
            context.inventory
        ):
            return [
                "authoring-source tree changed after its Git inventory was bound"
            ]
        try:
            retained.require_current()
        except (OSError, RuntimeError, ValueError) as exc:
            return [
                "authoring-source retained Git inventory is no longer current: "
                f"{exc}"
            ]
        tracked_files = set(retained.tracked_files)
        if not tracked_files:
            return [
                "authoring-source release check requires a nonempty Git-tracked "
                "inventory"
            ]
        context.tracked_files = tracked_files
        return []
    retained_bindings: list[_GitInventoryBinding] = []
    try:
        if context.git_executable is None:
            tracked_files = git_tracked_files(
                context.root,
                _inventory=context.inventory,
                _binding_sink=retained_bindings,
            )
        else:
            tracked_files = git_tracked_files(
                context.root,
                git_executable=context.git_executable,
                _inventory=context.inventory,
                _binding_sink=retained_bindings,
            )
    except (OSError, RuntimeError, ValueError) as exc:
        return [
            "authoring-source release check could not obtain a usable "
            f"Git-tracked inventory: {exc}"
        ]
    if tracked_files is None:
        if retained_bindings:
            detail = ""
            try:
                _cleanup_release_resources(
                    resources=tuple(
                        (f"unexpected Git inventory binding {index}", retained)
                        for index, retained in enumerate(retained_bindings, start=1)
                    ),
                )
            except Exception as cleanup:
                detail = f"; unexpected Git binding cleanup failed: {cleanup}"
            return [
                "authoring-source Git inventory returned no tracked result but "
                f"retained {len(retained_bindings)} binding(s){detail}"
            ]
        return [
            "authoring-source release check requires a usable Git-tracked "
            "inventory"
        ]
    if len(retained_bindings) != 1:
        detail = ""
        try:
            _cleanup_release_resources(
                resources=tuple(
                    (f"invalid Git inventory binding {index}", retained)
                    for index, retained in enumerate(retained_bindings, start=1)
                ),
            )
        except Exception as cleanup:
            detail = f"; binding cleanup failed: {cleanup}"
        return [
            "authoring-source Git inventory retained an invalid binding count: "
            f"{len(retained_bindings)}{detail}"
        ]
    context.git_inventory = retained_bindings[0]
    if not tracked_files:
        return [
            "authoring-source release check requires a nonempty Git-tracked "
            "inventory"
        ]
    context.tracked_files = tracked_files
    return []


def _load_release_inputs(context: _ReleaseCheckContext) -> None:
    if context.tree_role is ReleaseTreeRole.AUTHORING_SOURCE:
        context.private_workflow_policy = load_private_workflow_policy(
            context.root,
            context.errors,
            required=_authoring_policy_present(context.inventory),
            expected=context.inventory.files.get(
                PRIVATE_WORKFLOW_PATTERNS_PATH.as_posix()
            ),
            inventory_bound=True,
        )
    context.errors.extend(root_entrypoint_errors(context.root, _inventory=context.inventory))


def _required_and_tracked_errors(context: _ReleaseCheckContext) -> None:
    context.errors.extend(required_public_content_classification_errors())
    tracked_files = context.tracked_files
    for rel in public_surface.PUBLIC_REQUIRED_FILES:
        if rel in context.inventory.symlinks:
            context.errors.append(f"public required file is symlink: {rel}")
        elif rel not in context.inventory.files:
            context.errors.append(f"missing public required file: {rel}")
        elif tracked_files is not None and rel not in tracked_files:
            context.errors.append(f"public required file is not tracked by Git: {rel}")
    if tracked_files is None:
        return
    for rel in sorted(tracked_files):
        if is_platform_metadata_sidecar(rel):
            context.errors.append(f"platform metadata sidecar path is tracked in public release candidate: {rel}")
            continue
        if is_public_excluded(rel):
            if context.tree_role is not ReleaseTreeRole.AUTHORING_SOURCE:
                context.errors.append(f"excluded private/local path is tracked in public release candidate: {rel}")
        elif not public_surface.is_under_public_root(rel):
            context.errors.append(f"tracked file is outside public release surface: {rel}")


def required_public_content_classification_errors() -> list[str]:
    """Require every declared public product file to be scanned or explicitly binary."""

    errors: list[str] = []
    for rel in sorted(public_surface.PUBLIC_REQUIRED_FILES):
        if not public_surface.is_under_public_root(rel):
            errors.append(f"public required file is outside public roots: {rel}")
        if is_public_excluded(rel):
            errors.append(f"public required file is excluded from publication: {rel}")
        path = PurePosixPath(rel)
        if (
            path.suffix not in TEXT_SUFFIXES
            and path.name not in TEXT_FILENAMES
            and rel not in PUBLIC_BINARY_FILES
        ):
            errors.append(
                "public required file lacks a content-scan classification: "
                f"{rel}"
            )
    return errors


def _public_inventory_errors(context: _ReleaseCheckContext) -> None:
    context.errors.extend(context.inventory.errors)
    context.errors.extend(
        platform_metadata_sidecar_errors(context.root, _inventory=context.inventory)
    )
    public_regular = tuple(
        rel
        for rel in sorted(context.inventory.files)
        if public_surface.is_under_public_root(rel)
        and not is_public_excluded(rel)
        and not is_platform_metadata_sidecar(rel)
    )
    context.public_rels = public_regular
    hardlinks = [
        rel
        for rel in public_regular
        if context.inventory.files[rel].st_nlink != 1
    ]
    for rel in hardlinks:
        context.errors.append(f"public release file must have exactly one hard link: {rel}")
    for rel in sorted(context.inventory.special):
        if public_surface.is_under_public_root(rel) and not is_public_excluded(rel):
            context.errors.append(f"public release surface contains unsupported filesystem entry: {rel}")
    undeclared = sorted(set(public_regular) - set(public_surface.PUBLIC_REQUIRED_FILES))
    for rel in undeclared:
        context.errors.append(f"undeclared public-surface file: {rel}; add to PUBLIC_REQUIRED_FILES or exclude it")


def _public_export_errors(context: _ReleaseCheckContext) -> None:
    if context.tree_role is not ReleaseTreeRole.PUBLIC_EXPORT:
        return
    context.errors.extend(
        public_gitignore_reinclude_errors(
            context.root,
            _inventory=context.inventory,
        )
    )
    for rel in sorted(_all_inventory_paths(context.inventory)):
        if is_platform_metadata_sidecar(rel) or rel == PUBLIC_EXPORT_OWNERSHIP_MARKER:
            continue
        if rel in context.inventory.symlinks:
            context.errors.append(f"public export contains symlink path: {rel}")
        if rel in context.inventory.files:
            if public_surface.is_public_excluded(rel):
                context.errors.append(f"excluded private/local path exists in public export: {rel}")
            elif not public_surface.is_under_public_root(rel):
                context.errors.append(f"unexpected file outside public export surface: {rel}")
    all_paths = _all_inventory_paths(context.inventory)
    for prefix in public_surface.PUBLIC_EXCLUDED_PREFIXES:
        value = prefix.rstrip("/")
        if value in all_paths:
            context.errors.append(f"excluded private/local path exists in public export: {value}")


def _public_root_symlink_errors(context: _ReleaseCheckContext) -> None:
    inventory_paths = _all_inventory_paths(context.inventory)
    for item in public_surface.PUBLIC_ROOTS:
        candidates: list[str] = []
        if item in inventory_paths:
            candidates.append(item)
        if item in context.inventory.directories:
            candidates.extend(
                rel for rel in sorted(inventory_paths) if rel.startswith(f"{item}/")
            )
        for rel in candidates:
            if is_platform_metadata_sidecar(rel):
                continue
            if (
                context.tree_role is ReleaseTreeRole.PUBLIC_EXPORT
                and is_public_excluded(rel)
            ):
                context.errors.append(f"excluded private/local path exists in public export: {rel}")
                continue
            if rel in context.inventory.symlinks and not is_public_excluded(rel):
                context.errors.append(f"public export surface contains symlink path: {rel}")
    for rel in context.public_rels:
        if is_public_excluded(rel):
            context.errors.append(f"excluded private/local path would be published: {rel}")


def _line_leak_errors(
    rel: str,
    line_no: int,
    line: str,
    *,
    structured_secret_keys: set[str],
    private_workflow_reference_re: re.Pattern[str] | None,
    private_workflow_allowed_gitignore_lines: frozenset[str] = frozenset(),
) -> list[str]:
    errors: list[str] = []
    if HOST_PATH_RE.search(line) and not allowed_host_path_reference(rel, line):
        errors.append(f"host-specific absolute path leaked into public release file: {rel}:{line_no}")
    if PRIVATE_STATE_RE.search(line) and not allowed_private_state_reference(rel, line):
        errors.append(f"private or generated local-state reference leaked into public release file: {rel}:{line_no}")
    if SENSITIVE_LOCAL_REFERENCE_RE.search(line) and not allowed_sensitive_reference(rel, line):
        errors.append(f"secret or local credential reference leaked into public release file: {rel}:{line_no}")
    secret_kinds = sensitive_value_kinds(line)
    if structured_secret_keys:
        secret_kinds = [kind for kind in secret_kinds if kind != "assigned secret-like value"]
    errors.extend(
        f"credential-like secret value ({secret_kind}) leaked into public release file: {rel}:{line_no}"
        for secret_kind in secret_kinds
    )
    if LOCAL_STATE_PATH_RE.search(line) and not allowed_private_state_reference(
        rel,
        line,
        LOCAL_STATE_PATH_RE,
    ):
        errors.append(f"local-only workspace path reference leaked into public release file: {rel}:{line_no}")
    if (
        private_workflow_reference_re is not None
        and private_workflow_reference_re.search(line)
        and not allowed_private_workflow_reference(
            rel,
            line,
            private_workflow_reference_re,
            private_workflow_allowed_gitignore_lines,
        )
    ):
        errors.append(f"private workflow reference leaked into public release file: {rel}:{line_no}")
    return errors


def _static_python_private_workflow_errors(
    rel: str,
    source: str,
    reference_re: re.Pattern[str] | None,
) -> list[str]:
    """Detect private terms reconstructed by constant Python concatenation.

    This narrow check covers decoded literals and literal ``+`` expressions
    that can be folded without execution. It does not claim to detect arbitrary
    runtime string construction or obfuscation.
    """

    if reference_re is None:
        return []
    try:
        tree = ast.parse(source, filename=rel)
    except (SyntaxError, ValueError) as exc:
        return [f"public Python file could not be parsed for static leak checks: {rel}: {exc}"]
    errors: list[str] = []
    reported_lines: set[int] = set()
    source_lines = source.splitlines()
    for node in ast.walk(tree):
        if not isinstance(node, ast.expr):
            continue
        value = _constant_string_expression_value(node)
        if value is None or reference_re.search(value) is None:
            continue
        line_no = getattr(node, "lineno", 1)
        raw_line = source_lines[line_no - 1] if 0 < line_no <= len(source_lines) else ""
        if reference_re.search(raw_line) is not None:
            # The ordinary line scanner owns direct textual occurrences.
            continue
        if line_no in reported_lines:
            continue
        reported_lines.add(line_no)
        errors.append(
            "private workflow reference reconstructed by static Python string "
            f"expression in public release file: {rel}:{line_no}"
        )
    return errors


def _scan_public_text_file(context: _ReleaseCheckContext, rel: str) -> list[str]:
    path = context.root / rel
    if path.suffix not in TEXT_SUFFIXES and path.name not in TEXT_FILENAMES:
        return []
    metadata = context.inventory.files[rel]
    if metadata.st_nlink != 1:
        return []
    errors: list[str] = []
    structured_keys: set[str] = set()
    try:
        if path.suffix in {".json", ".py"}:
            raw = _read_stable_file_bytes(
                path,
                description=f"public release structured text file {rel}",
                expected=metadata,
                max_bytes=safe_paths.DEFAULT_JSON_INPUT_MAX_BYTES,
            )
            text = raw.decode("utf-8")
            if path.suffix == ".json":
                try:
                    structured_keys = structured_json_secret_keys(
                        safe_paths.loads_json_no_duplicates(text)
                    )
                except (json.JSONDecodeError, RecursionError):
                    structured_keys = set()
            else:
                errors.extend(
                    _static_python_private_workflow_errors(
                        rel,
                        text,
                        (
                            context.private_workflow_policy.reference_re
                            if context.private_workflow_policy is not None
                            else None
                        ),
                    )
                )
            lines: Iterator[str] = iter(text.splitlines())
        else:
            lines = _iter_stable_utf8_lines(
                path,
                description=f"public release text file {rel}",
                expected=metadata,
            )
        for key in sorted(structured_keys):
            errors.append(
                "credential-like secret value "
                f"(structured sensitive JSON key: {key}) leaked into public release file: {rel}"
            )
        for line_no, line in enumerate(lines, start=1):
            errors.extend(
                _line_leak_errors(
                    rel,
                    line_no,
                    line,
                    structured_secret_keys=structured_keys,
                    private_workflow_reference_re=(
                        context.private_workflow_policy.reference_re
                        if context.private_workflow_policy is not None
                        else None
                    ),
                    private_workflow_allowed_gitignore_lines=(
                        context.private_workflow_policy.allowed_gitignore_lines
                        if context.private_workflow_policy is not None
                        else frozenset()
                    ),
                )
            )
    except (OSError, UnicodeError, ValueError) as exc:
        return [f"public release text file could not be read safely as UTF-8: {rel}: {exc}"]
    return errors


def _public_text_errors(context: _ReleaseCheckContext) -> None:
    for rel in context.public_rels:
        context.errors.extend(_scan_public_text_file(context, rel))


def _tree_stability_errors(context: _ReleaseCheckContext) -> None:
    if context.inventory.errors:
        return
    if context.root_binding is None:
        context.errors.append("public release root descriptor is unavailable")
        return
    final_inventory = _inventory_release_tree_descriptor(
        context.root_binding.descriptor
    )
    if final_inventory.errors:
        context.errors.extend(final_inventory.errors)
        return
    elif _inventory_signature(final_inventory) != _inventory_signature(context.inventory):
        context.errors.append("public release tree changed while it was being checked")
        return
    if context.tree_role is not ReleaseTreeRole.AUTHORING_SOURCE:
        return
    try:
        if context.git_inventory is not None:
            context.git_inventory.require_current()
            final_tracked_files = set(context.git_inventory.tracked_files)
        elif context.git_executable is None:
            final_tracked_files = git_tracked_files(
                context.root,
                _inventory=final_inventory,
            )
        else:
            final_tracked_files = git_tracked_files(
                context.root,
                git_executable=context.git_executable,
                _inventory=final_inventory,
            )
    except (OSError, RuntimeError, ValueError) as exc:
        context.errors.append(
            "Git-tracked inventory changed while the authoring-source release "
            f"tree was being checked: {exc}"
        )
        return
    if final_tracked_files != context.tracked_files:
        context.errors.append(
            "Git-tracked inventory changed while the authoring-source release "
            "tree was being checked"
        )


def _check_public_release_with_binding(
    root: Path,
    *,
    tree_role: ReleaseTreeRole,
    root_binding: safe_paths.OutputDirectoryBinding,
    _git_executable: GitExecutableBinding | None = None,
    _git_inventory: _GitInventoryBinding | None = None,
    _retained_git_inventory_sink: list[_GitInventoryBinding] | None = None,
) -> dict[str, object]:
    if _git_inventory is not None and tree_role is not ReleaseTreeRole.AUTHORING_SOURCE:
        raise ValueError("a retained Git inventory is valid only for an authoring source")
    if _git_inventory is not None and _retained_git_inventory_sink is not None:
        raise ValueError("a borrowed Git inventory cannot also be retained")
    inventory = _inventory_release_tree_descriptor(root_binding.descriptor)
    context = _ReleaseCheckContext(
        root=root,
        tree_role=tree_role,
        inventory=inventory,
        errors=[],
        notes=[],
        warnings=[],
        root_binding=root_binding,
        git_inventory=_git_inventory,
        git_executable=_git_executable,
        tracked_files=(
            set(_git_inventory.tracked_files)
            if _git_inventory is not None
            else None
        ),
    )
    owns_git_inventory = _git_inventory is None
    report: dict[str, object] | None = None
    try:
        identity_errors = _release_tree_identity_errors(context)
        if identity_errors:
            # The declared role is a prerequisite for every ordinary tree check.
            # Fail closed without cascading through an unproven or misclassified
            # filesystem surface.
            context.errors.extend(identity_errors)
        else:
            _load_release_inputs(context)
            _required_and_tracked_errors(context)
            _public_inventory_errors(context)
            _public_export_errors(context)
            _public_root_symlink_errors(context)
            _public_text_errors(context)
            _tree_stability_errors(context)
        try:
            root_binding.require_unchanged_chain(description="public release root")
        except (OSError, ValueError) as exc:
            context.errors.append(
                "public release root pathname changed while it was being "
                f"checked: {exc}"
            )
        report = {
            "errors": context.errors,
            "excluded_prefixes": list(public_surface.PUBLIC_EXCLUDED_PREFIXES),
            "public_file_count": len(context.public_rels),
            "notes": context.notes,
            "tree_role": context.tree_role.value,
            "warnings": context.warnings,
            "tracked_file_count": (
                len(context.tracked_files)
                if context.tracked_files is not None
                else None
            ),
        }
        return report
    finally:
        if context.git_inventory is not None and owns_git_inventory:
            active_failure = sys.exception()
            report_errors = report.get("errors") if report is not None else None
            if (
                _retained_git_inventory_sink is not None
                and active_failure is None
                and report_errors == []
            ):
                try:
                    _retained_git_inventory_sink.append(context.git_inventory)
                except BaseException as transfer_error:
                    _close_preserving_primary(
                        context.git_inventory,
                        description="retained Git inventory transfer",
                        primary=transfer_error,
                    )
                    raise
            else:
                try:
                    context.git_inventory.close()
                except BaseException as cleanup:
                    if active_failure is not None:
                        active_failure.add_note(
                            f"Git inventory cleanup failure: {cleanup}"
                        )
                    elif report is not None and isinstance(cleanup, Exception):
                        errors = report.get("errors")
                        if isinstance(errors, list):
                            errors.append(f"Git inventory cleanup failed: {cleanup}")
                        else:
                            raise TypeError(
                                "public release report lost its errors payload during cleanup"
                            ) from cleanup
                    else:
                        cleanup.add_note(
                            "Git inventory cleanup interrupted after release validation"
                        )
                        raise


def check_public_release(
    root: Path,
    *,
    tree_role: ReleaseTreeRole,
    git_executable: GitExecutableBinding | None = None,
) -> dict[str, object]:
    if not isinstance(tree_role, ReleaseTreeRole):
        raise TypeError("tree_role must be a ReleaseTreeRole")
    try:
        root_binding = safe_paths.open_output_directory(
            root,
            create_missing=False,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        return {
            "errors": [
                f"public release tree could not be enumerated safely: {exc}"
            ],
            "excluded_prefixes": list(public_surface.PUBLIC_EXCLUDED_PREFIXES),
            "public_file_count": 0,
            "notes": [],
            "tree_role": tree_role.value,
            "warnings": [],
            "tracked_file_count": None,
        }
    report: dict[str, object] | None = None
    try:
        if git_executable is None:
            report = _check_public_release_with_binding(
                root,
                tree_role=tree_role,
                root_binding=root_binding,
            )
        else:
            report = _check_public_release_with_binding(
                root,
                tree_role=tree_role,
                root_binding=root_binding,
                _git_executable=git_executable,
            )
        report["git_executable_sha256"] = (
            git_executable.sha256 if git_executable is not None else None
        )
        return report
    finally:
        active_failure = sys.exception()
        try:
            root_binding.close()
        except BaseException as cleanup:
            if active_failure is not None:
                active_failure.add_note(
                    f"public release root cleanup failure: {cleanup}"
                )
            elif report is not None and isinstance(cleanup, Exception):
                errors = report.get("errors")
                if isinstance(errors, list):
                    errors.append(f"public release root cleanup failed: {cleanup}")
                else:
                    raise TypeError(
                        "public release report lost its errors payload during cleanup"
                    ) from cleanup
            else:
                cleanup.add_note(
                    "public release root cleanup interrupted after validation"
                )
                raise


def checked_public_source_snapshots(
    root: Path,
    relative_paths: Set[str],
    *,
    git_executable: GitExecutableBinding | None = None,
    _binding_sink: list[PublicSourceSnapshotBinding] | None = None,
) -> dict[str, tuple[str, int]]:
    """Return digest/mode snapshots for a stable, release-checked authoring tree."""

    unsafe = sorted(rel for rel in relative_paths if not _safe_manifest_path(rel))
    if unsafe:
        raise ValueError(
            "public source snapshot contains unsafe paths: " + ", ".join(unsafe)
        )
    binding = safe_paths.open_output_directory(root, create_missing=False)
    retained_git_inventory: list[_GitInventoryBinding] = []
    source_binding: PublicSourceSnapshotBinding | None = None
    binding_transferred = False
    try:
        if git_executable is None:
            report = _check_public_release_with_binding(
                root,
                tree_role=ReleaseTreeRole.AUTHORING_SOURCE,
                root_binding=binding,
                _retained_git_inventory_sink=retained_git_inventory,
            )
        else:
            report = _check_public_release_with_binding(
                root,
                tree_role=ReleaseTreeRole.AUTHORING_SOURCE,
                root_binding=binding,
                _git_executable=git_executable,
                _retained_git_inventory_sink=retained_git_inventory,
            )
        raw_errors = report.get("errors")
        if not isinstance(raw_errors, list) or not all(
            isinstance(item, str) for item in raw_errors
        ):
            raise TypeError("public release check returned invalid errors payload")
        if raw_errors:
            raise ValueError(
                "public source tree failed release check: " + "; ".join(raw_errors)
            )
        if len(retained_git_inventory) != 1:
            raise RuntimeError(
                "public source release check did not retain exactly one Git inventory"
            )
        git_inventory = retained_git_inventory[0]

        inventory = _inventory_release_tree_descriptor(binding.descriptor)
        if inventory.errors:
            raise ValueError("; ".join(inventory.errors))
        missing = sorted(relative_paths - set(inventory.files))
        if missing:
            raise ValueError(
                "public source snapshot is missing files: " + ", ".join(missing)
            )
        multiply_linked = sorted(
            rel for rel in relative_paths if inventory.files[rel].st_nlink != 1
        )
        if multiply_linked:
            raise ValueError(
                "public source snapshot contains multiply-linked files: "
                + ", ".join(multiply_linked)
            )
        snapshots = {
            rel: stable_file_snapshot(root / rel, _expected=inventory.files[rel])
            for rel in sorted(relative_paths)
        }
        final_inventory = _inventory_release_tree_descriptor(binding.descriptor)
        if final_inventory.errors:
            raise ValueError("; ".join(final_inventory.errors))
        if _inventory_signature(final_inventory) != _inventory_signature(inventory):
            raise ValueError(
                "public source tree changed while its export snapshot was created"
            )
        confirmation = _check_public_release_with_binding(
            root,
            tree_role=ReleaseTreeRole.AUTHORING_SOURCE,
            root_binding=binding,
            _git_inventory=git_inventory,
        )
        confirmation_errors = confirmation.get("errors")
        if not isinstance(confirmation_errors, list) or not all(
            isinstance(item, str) for item in confirmation_errors
        ):
            raise TypeError("public release confirmation returned invalid errors payload")
        if confirmation_errors:
            raise ValueError(
                "public source tree failed snapshot confirmation: "
                + "; ".join(confirmation_errors)
            )
        binding.require_unchanged_chain(description="public source snapshot root")
        git_inventory.require_current()
        source_binding = PublicSourceSnapshotBinding(
            root=root,
            relative_paths=frozenset(relative_paths),
            snapshots=dict(snapshots),
            inventory_signature=_inventory_signature(inventory),
            root_binding=binding,
            git_inventory=git_inventory,
        )
        if _binding_sink is not None:
            _binding_sink.append(source_binding)
            binding_transferred = True
        return snapshots
    finally:
        if not binding_transferred:
            primary = sys.exception()
            actions: list[tuple[str, Callable[[], object]]] = []
            if source_binding is not None:
                actions.append(("public source snapshot binding", source_binding.close))
            else:
                actions.extend(
                    (
                        ("public source retained Git inventory", retained.close)
                        for retained in retained_git_inventory
                    )
                )
                actions.append(("public source snapshot root", binding.close))
            resource_cleanup.cleanup_actions(actions, primary=primary)


def publication_executable_binding(
    parser: argparse.ArgumentParser,
    *,
    explicit_descriptor: int | None,
    explicit_sha256: str | None,
    propagated_path_env: str,
    propagated_sha256_env: str,
    description: str,
) -> GitExecutableBinding | None:
    """Open one explicit or propagated digest-approved executable."""

    if (explicit_descriptor is None) != (explicit_sha256 is None):
        parser.error(f"{description} descriptor and SHA-256 must be supplied together")
    propagated_path = os.environ.get(propagated_path_env)
    propagated_sha256 = os.environ.get(propagated_sha256_env)
    if (propagated_path is None) != (propagated_sha256 is None):
        parser.error(
            f"propagated {description} descriptor path and SHA-256 must be supplied together"
        )
    if explicit_descriptor is not None and propagated_path is not None:
        parser.error(
            f"explicit and propagated {description} bindings are mutually exclusive"
        )
    try:
        if explicit_descriptor is not None and explicit_sha256 is not None:
            return open_inherited_git_executable_binding(
                explicit_descriptor,
                expected_sha256=explicit_sha256,
                description=description,
            )
        if propagated_path is not None and propagated_sha256 is not None:
            return open_propagated_git_executable_binding(
                Path(propagated_path),
                expected_sha256=propagated_sha256,
                description=description,
            )
    except (OSError, RuntimeError, ValueError) as exc:
        parser.error(str(exc))
    return None


def publication_git_binding(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
) -> tuple[GitExecutableBinding | None, bool]:
    inherited_boundary = os.environ.get(PUBLICATION_BOUNDARY_ENV)
    if inherited_boundary not in {None, "1"}:
        parser.error(f"{PUBLICATION_BOUNDARY_ENV} must be absent or equal 1")
    boundary = bool(args.publication_boundary or inherited_boundary == "1")
    explicit_descriptor = args.git_executable_fd
    explicit_sha256 = args.git_executable_sha256
    if (explicit_descriptor is None) != (explicit_sha256 is None):
        parser.error(
            "--git-executable-fd and --git-executable-sha256 must be supplied together"
        )
    propagated_path = os.environ.get(PUBLICATION_GIT_PROC_PATH_ENV)
    propagated_sha256 = os.environ.get(PUBLICATION_GIT_SHA256_ENV)
    if (propagated_path is None) != (propagated_sha256 is None):
        parser.error(
            "propagated publication Git descriptor path and digest must be supplied together"
        )
    if explicit_descriptor is not None and propagated_path is not None:
        parser.error(
            "explicit and propagated publication Git bindings are mutually exclusive"
        )
    if args.tree_role is ReleaseTreeRole.PUBLIC_EXPORT:
        if explicit_descriptor is not None:
            parser.error("public-export release checks must not receive a Git binding")
        return None, boundary
    binding = publication_executable_binding(
        parser,
        explicit_descriptor=explicit_descriptor,
        explicit_sha256=explicit_sha256,
        propagated_path_env=PUBLICATION_GIT_PROC_PATH_ENV,
        propagated_sha256_env=PUBLICATION_GIT_SHA256_ENV,
        description="bound Git executable",
    )
    if binding is not None:
        return binding, boundary
    if boundary:
        parser.error(
            "publication-boundary authoring checks require one retained Git "
            "descriptor and approved SHA-256 digest"
        )
    return None, boundary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check the intended public framework release surface.",
        allow_abbrev=False,
    )
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help="Repository root to inspect.")
    parser.add_argument(
        "--tree-role",
        type=ReleaseTreeRole,
        choices=tuple(ReleaseTreeRole),
        required=True,
        help="Declared identity of the checked tree.",
    )
    parser.add_argument(
        "--publication-boundary",
        action="store_true",
        help=(
            "Require the canonical isolated publication invocation; authoring "
            "checks then require an exact retained Git descriptor and digest."
        ),
    )
    parser.add_argument(
        "--git-executable-fd",
        type=int,
        help=(
            "Inherited descriptor for the reviewed Git executable; supply it "
            "with --git-executable-sha256 for authoring-source checks."
        ),
    )
    parser.add_argument(
        "--git-executable-sha256",
        help=(
            "Approved lowercase SHA-256 digest of the executable bound by "
            "--git-executable-fd."
        ),
    )
    args = parser.parse_args(argv)
    git_executable, publication_boundary = publication_git_binding(parser, args)

    try:
        report = check_public_release(
            args.root.expanduser().absolute(),
            tree_role=args.tree_role,
            git_executable=git_executable,
        )
        report["publication_boundary"] = publication_boundary
    finally:
        if git_executable is not None:
            try:
                git_executable.close()
            except (OSError, RuntimeError, ValueError) as exc:
                parser.error(f"bound Git executable cleanup failed: {exc}")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
