#!/usr/bin/env python3

"""Declarative source of truth for project-contract setup and projection.

This module owns the accepted bootstrap-answer shape, contract-definition
projection, optional-state declarations, public contract blueprints, and the
stable prose shared by blueprint and concrete rendering.  The bootstrap and
sync tools consume this model; the checked-in JSON Schema and Markdown
blueprints are generated assets, not independent authorities.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path
import re
import shlex
from typing import Literal
import unicodedata

import automation_orders_lint
import bootstrap_transaction
import generated_sow_text
import safe_paths


REPO_ROOT = Path(__file__).resolve().parent.parent
MODEL_SCHEMA_VERSION = 1
CONTRACT_FORMAT_VERSION = 2
CONTRACT_FORMAT_MARKER_KEY = "mpa-project-contract-format"
ANSWER_SCHEMA_PATH = "examples/project_bootstrap_answers.schema.json"
SOW_BLUEPRINT_PATH = "statement_of_work_template.md"
PROJECT_BLUEPRINT_PATH = "runtime/project_template.md"
GENERATED_ASSET_PATHS = (
    ANSWER_SCHEMA_PATH,
    SOW_BLUEPRINT_PATH,
    PROJECT_BLUEPRINT_PATH,
)
ORDERED_REPEATED_PROJECTIONS = frozenset({"Active Deliverables"})


def contract_format_marker(version: int = CONTRACT_FORMAT_VERSION) -> str:
    """Return the exact identity marker for one generated contract format."""

    return f"<!-- {CONTRACT_FORMAT_MARKER_KEY}: {version} -->"


CONTRACT_FORMAT_MARKER = contract_format_marker()

# Re-export the neutral grammar API for existing contract/bootstrap consumers.
GENERATED_SOW_COMMENT_TOKENS = generated_sow_text.GENERATED_SOW_COMMENT_TOKENS
PYTHON_SPLITLINES_BOUNDARIES = generated_sow_text.PYTHON_SPLITLINES_BOUNDARIES
ECMASCRIPT_SPLITLINES_BOUNDARY = (
    generated_sow_text.ECMASCRIPT_SPLITLINES_BOUNDARY
)
ECMASCRIPT_NON_SPLITLINE_TEXT = generated_sow_text.ECMASCRIPT_NON_SPLITLINE_TEXT
ECMASCRIPT_MULTILINE_FORBIDDEN_CONTROL = (
    generated_sow_text.ECMASCRIPT_MULTILINE_FORBIDDEN_CONTROL
)
ECMASCRIPT_SINGLE_LINE_FORBIDDEN_CONTROL = (
    generated_sow_text.ECMASCRIPT_SINGLE_LINE_FORBIDDEN_CONTROL
)
GENERATED_SOW_CONTROL_LINE_SYNTAX = (
    generated_sow_text.GENERATED_SOW_CONTROL_LINE_SYNTAX
)
contains_splitlines_boundary = generated_sow_text.contains_splitlines_boundary
generated_sow_control_syntax_kind = (
    generated_sow_text.generated_sow_control_syntax_kind
)

ENTRYPOINT_RECOVERY_CONTROL_PATHS = (
    bootstrap_transaction.RECOVERY_JOURNAL_NAME,
    bootstrap_transaction.TRANSACTION_LOCK_NAME,
    bootstrap_transaction._RECOVERY_JOURNAL_TEMP_NAME,
)
ENTRYPOINT_RECOVERY_GUARD_MARKER = (
    "<!-- mpa-entrypoint-contract: entrypoint-recovery-guard-v2 -->"
)

ENTRYPOINT_FRAMEWORK_UNAVAILABLE_CLAUSE = (
    "If the operative charter or another required framework resource cannot be read "
    "through the declared framework reference, stop ordinary project work. Report the "
    "unavailable resource and observed failure; limit activity to bounded read-only "
    "diagnosis or an explicitly User-authorized access or reference repair, and do not "
    "silently or without that approval substitute another checkout, runner, cached "
    "rules, or partial local rules."
)
ENTRYPOINT_RECOVERY_GUARD_CLAUSE = (
    "After loading the operative charter and before loading `AGENT_PROJECT.md`, "
    "`STATEMENT_OF_WORK.md`, or project state, check for any member of the closed "
    "transaction-control set in the project root (the directory containing this "
    f"entrypoint): `{ENTRYPOINT_RECOVERY_CONTROL_PATHS[0]}`, "
    f"`{ENTRYPOINT_RECOVERY_CONTROL_PATHS[1]}`, or "
    f"`{ENTRYPOINT_RECOVERY_CONTROL_PATHS[2]}`. If any exists, stop ordinary "
    "project work and do not load generated project authority or state. Permit only "
    "bounded read-only recovery-status inspection through the selected framework's "
    "`scripts/project_refresh.py inspect` route and, only when that inspection "
    "reports a permitted recovery action and exact transaction ID, recovery through its "
    "`recover --action rollback|finalize --approve-transaction-id <transaction-id>` "
    "route. Invoke those routes only through a runner already supplied by the runtime "
    "or operator without reading generated project authority; if no such runner is "
    "available or inspection does not identify a permitted recovery action, report "
    "the recovery blocker and await direction. Do not edit or delete any transaction-"
    "control artifact manually."
)


AnswerKind = Literal[
    "annexes",
    "arbitration_panel",
    "automation_orders",
    "auxiliary_tools",
    "boolean",
    "command_restrictions",
    "commands",
    "deliverables",
    "lines",
    "minimal_deferrals",
    "string",
    "workflows",
]
StructuredFieldRenderMode = Literal["container", "labeled", "positional"]
DefinitionProjection = Literal[
    "answer",
    "arbitration-panel",
    "bootstrap-mode",
    "command",
    "direct-panel-rules",
    "optional-state",
    "runtime-standards",
    "source-monitor-instruction-sources",
    "source-monitor-source-data",
]
RuntimeDefinitionPolicy = Literal[
    "always",
    "when-active",
    "when-overridden",
    "section-owned",
    "state-owned",
    "canonical-only",
]
RuntimeOwnerInclusion = Literal["always", "when-active", "when-overridden"]
RuntimeOwnerStyle = Literal["labeled", "native"]
ProjectSectionRowStyle = Literal["bullet", "numbered", "scope"]
SowSectionRowStyle = Literal[
    "arbitration-panel",
    "automation",
    "bullet",
    "command-restrictions",
    "commands",
    "direct-panel-rules",
    "free-form",
    "labeled",
    "numbered",
    "policy-bullet",
    "scope",
    "technical-specifications",
    "workflows",
]
SowLabeledSemanticOwner = Literal["definition-parity", "shared-source-reference"]
SowLabeledComparison = Literal["normalized", "exact"]
SowLabeledSectionAbsence = Literal[
    "compare-absent",
    "ignore",
    "use-definition-default",
]
StateTemplatePlaceholderOwner = Literal[
    "definition-parity",
    "framework-reference",
    "shared-source-reference",
    "source-monitor-verification-command",
]
OptionalStatePartition = Literal["mutable", "immutable"]
OPTIONAL_STATE_PARTITIONS = frozenset({"mutable", "immutable"})


@dataclass(frozen=True, slots=True)
class AnswerFieldSpec:
    name: str
    kind: AnswerKind
    required_in: frozenset[str] = frozenset()
    operative: bool = False
    profile_default_allowed: bool = True
    enum: tuple[str, ...] = ()
    active_when: str | None = None


@dataclass(frozen=True, slots=True)
class AnswerTextGrammarSpec:
    answer_key: str
    member_keys: frozenset[str] = frozenset()
    forbidden_exact_lines: frozenset[str] = frozenset()
    forbidden_substrings: tuple[str, ...] = ()
    forbidden_line_syntax: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class DefinitionSpec:
    label: str
    hint: str
    surfaces: frozenset[str]
    projection: DefinitionProjection = "answer"
    answer_key: str | None = None
    active_when: str | None = None
    default: str | None = None
    suffix: str = ""
    runtime_policy: RuntimeDefinitionPolicy = "always"
    runtime_owner: str | None = None
    runtime_owner_inclusion: RuntimeOwnerInclusion | None = None
    runtime_owner_style: RuntimeOwnerStyle | None = None


@dataclass(frozen=True, slots=True)
class OptionalStateSpec:
    flag: str
    filename: str
    template: str
    partition: OptionalStatePartition
    bootstrap_template: str | None = None
    definition_label: str | None = None


@dataclass(frozen=True, slots=True)
class SectionSpec:
    key: str
    title: str
    blueprint_lines: tuple[str, ...]
    policy_lines: tuple[str, ...] = ()
    sow_row_style: SowSectionRowStyle | None = None


@dataclass(frozen=True, slots=True)
class SowLabeledFieldSpec:
    section_key: str
    label: str
    semantic_owner: SowLabeledSemanticOwner
    definition_label: str | None = None
    comparison: SowLabeledComparison = "normalized"
    section_absence: SowLabeledSectionAbsence = "compare-absent"


@dataclass(frozen=True, slots=True)
class StateDefinitionProjectionSpec:
    sow_section_key: str
    filename: str
    state_section: str
    state_key: str
    definition_label: str


@dataclass(frozen=True, slots=True)
class StateTemplatePlaceholderSpec:
    filename: str
    placeholder: str
    semantic_owner: StateTemplatePlaceholderOwner
    definition_label: str | None = None


@dataclass(frozen=True, slots=True)
class CommandSpec:
    answer_key: str
    sow_label: str
    runtime_label: str
    deferral_field: str


@dataclass(frozen=True, slots=True)
class StructuredFieldSpec:
    """Own one accepted structured-record field and its rendered grammar."""

    key: str
    label: str
    prefix: str
    required: bool = True
    render_mode: StructuredFieldRenderMode = "labeled"
    suffix: str = ""
    runtime_order: int | None = None
    non_rendered_reason: str | None = None


def _structured_keys(specs: tuple[StructuredFieldSpec, ...]) -> frozenset[str]:
    return frozenset(spec.key for spec in specs)


def _structured_required_keys(
    specs: tuple[StructuredFieldSpec, ...],
) -> frozenset[str]:
    return frozenset(spec.key for spec in specs if spec.required)


COMMAND_SPECS = (
    CommandSpec("dev", "Development", "Development", "Development"),
    CommandSpec("build", "Build", "Build", "Build"),
    CommandSpec(
        "build_all",
        "Regenerate all deliverable artifacts from source",
        "Regenerate artifacts",
        "Build All",
    ),
    CommandSpec("test", "Test", "Test", "Test Command"),
    CommandSpec("lint", "Lint", "Lint", "Lint Command"),
    CommandSpec("type_check", "Type Check", "Type check", "Type Check Command"),
    CommandSpec("deploy", "Deploy (if applicable)", "Deploy", "Deploy"),
)
COMMAND_KEYS = frozenset(spec.answer_key for spec in COMMAND_SPECS)
COMMAND_DEFINITION_FIELDS = frozenset(
    spec.deferral_field
    for spec in COMMAND_SPECS
    if spec.deferral_field.endswith(" Command")
)
COMMAND_DEFINITION_POINTER = "see Build and Development Commands"
DELIVERABLE_FIELD_SPECS = (
    StructuredFieldSpec(
        "description",
        "deliverable",
        "",
        render_mode="positional",
    ),
    StructuredFieldSpec(
        "test",
        "verification",
        " — ",
        render_mode="positional",
    ),
    StructuredFieldSpec(
        "pass_criteria",
        "pass criteria",
        " — ",
        render_mode="positional",
    ),
)
DELIVERABLE_KEYS = _structured_keys(DELIVERABLE_FIELD_SPECS)
DELIVERABLE_REQUIRED_KEYS = tuple(spec.key for spec in DELIVERABLE_FIELD_SPECS)

RESTRICTION_FIELD_SPECS = (
    StructuredFieldSpec("command", "command", "", render_mode="positional"),
    StructuredFieldSpec(
        "reason",
        "reason",
        " — never run — ",
        render_mode="positional",
    ),
    StructuredFieldSpec(
        "alternative",
        "alternative",
        " — use ",
        render_mode="positional",
        suffix=" instead",
    ),
)
RESTRICTION_KEYS = _structured_keys(RESTRICTION_FIELD_SPECS)

AUXILIARY_TOOL_FIELD_SPECS = (
    StructuredFieldSpec(
        "name",
        "name",
        "",
        render_mode="positional",
        runtime_order=0,
    ),
    StructuredFieldSpec(
        "purpose",
        "purpose",
        " — ",
        render_mode="positional",
        runtime_order=1,
    ),
    StructuredFieldSpec("invocation", "invoke", " — invoke: ", required=False),
    StructuredFieldSpec("docs", "docs", " — docs: ", required=False),
    StructuredFieldSpec("source", "source", " — source: ", required=False),
    StructuredFieldSpec("version", "version", " — version: ", required=False),
    StructuredFieldSpec(
        "permissions",
        "permissions",
        " — permissions: ",
        required=False,
    ),
    StructuredFieldSpec("review", "review", " — review: ", required=False),
    StructuredFieldSpec("owner", "owner", " — owner: ", required=False),
    StructuredFieldSpec(
        "transport",
        "transport",
        " — transport: ",
        required=False,
    ),
    StructuredFieldSpec(
        "allowed_tools",
        "allowed tools",
        " — allowed tools: ",
        required=False,
    ),
    StructuredFieldSpec(
        "capability_surface",
        "capability surface",
        " — capability surface: ",
        required=False,
    ),
    StructuredFieldSpec("scopes", "scopes", " — scopes: ", required=False),
    StructuredFieldSpec(
        "credential_source",
        "credential source",
        " — credential source: ",
        required=False,
    ),
    StructuredFieldSpec(
        "env_allowlist",
        "env allowlist",
        " — env allowlist: ",
        required=False,
    ),
    StructuredFieldSpec(
        "data_boundary",
        "data boundary",
        " — data boundary: ",
        required=False,
    ),
    StructuredFieldSpec(
        "effect_boundary",
        "effect boundary",
        " — effect boundary: ",
        required=False,
    ),
    StructuredFieldSpec(
        "persistence",
        "persistence",
        " — persistence: ",
        required=False,
    ),
    StructuredFieldSpec(
        "control_role",
        "control role",
        " — control role: ",
        required=False,
        runtime_order=4,
    ),
    StructuredFieldSpec(
        "control_coverage",
        "control coverage",
        " — control coverage: ",
        required=False,
        runtime_order=5,
    ),
    StructuredFieldSpec("trust", "trust", " — trust: ", required=False),
    StructuredFieldSpec(
        "when_to_use",
        "use when",
        " — use when: ",
        required=False,
        runtime_order=2,
    ),
    StructuredFieldSpec(
        "approval",
        "approval",
        " — approval: ",
        required=False,
        runtime_order=3,
    ),
)
AUXILIARY_TOOL_KEYS = _structured_keys(AUXILIARY_TOOL_FIELD_SPECS)
REQUIRED_AUXILIARY_TOOL_KEYS = _structured_required_keys(
    AUXILIARY_TOOL_FIELD_SPECS
)
AUXILIARY_CONTROL_ROLES = frozenset(
    {"enforcement_boundary", "lifecycle_guardrail", "none"}
)
AUXILIARY_CONTROL_COVERAGE_ROLES = frozenset(
    {"enforcement_boundary", "lifecycle_guardrail"}
)
AUXILIARY_TOOL_FACT_GROUPS: tuple[tuple[str, frozenset[str]], ...] = (
    ("owner", frozenset({"owner"})),
    ("provenance", frozenset({"docs", "source"})),
    ("interface/transport", frozenset({"transport"})),
    (
        "capability/permissions",
        frozenset({"allowed_tools", "capability_surface", "permissions", "scopes"}),
    ),
    ("data boundary", frozenset({"data_boundary"})),
    ("effect boundary", frozenset({"effect_boundary"})),
    ("persistence", frozenset({"persistence"})),
    ("trust", frozenset({"trust"})),
    ("credential disposition", frozenset({"credential_source"})),
    ("approval disposition", frozenset({"approval"})),
    ("scope disposition", frozenset({"allowed_tools", "permissions", "scopes"})),
    ("control role", frozenset({"control_role"})),
)
PANEL_SEAT_FIELD_SPECS = (
    StructuredFieldSpec("model", "model", "", render_mode="positional"),
    StructuredFieldSpec("role", "role", " — ", render_mode="positional"),
    StructuredFieldSpec("focus", "focus", " — ", render_mode="positional"),
)
PANEL_SEAT_KEYS = _structured_keys(PANEL_SEAT_FIELD_SPECS)

PANEL_CONFIG_FIELD_SPECS = (
    StructuredFieldSpec(
        "seats",
        "seats",
        "",
        render_mode="container",
        non_rendered_reason="rendered through nested arbitration-panel seat records",
    ),
    StructuredFieldSpec("quorum", "Quorum", "Quorum: "),
    StructuredFieldSpec(
        "recommendation_threshold",
        "Recommendation threshold",
        "Recommendation threshold: ",
    ),
    StructuredFieldSpec(
        "failure_handling",
        "Failure handling",
        "Failure handling: ",
    ),
    StructuredFieldSpec("tie_handling", "Tie handling", "Tie handling: "),
    StructuredFieldSpec(
        "no_majority_handling",
        "No-majority handling",
        "No-majority handling: ",
    ),
    StructuredFieldSpec(
        "abstention_handling",
        "Abstention handling",
        "Abstention handling: ",
    ),
    StructuredFieldSpec(
        "unavailable_panelist_handling",
        "Unavailable-panelist handling",
        "Unavailable-panelist handling: ",
    ),
    StructuredFieldSpec(
        "binding_effect",
        "Binding effect",
        "Binding effect: ",
    ),
    StructuredFieldSpec(
        "accountable_owner",
        "Ratification or accountable owner",
        "Ratification or accountable owner: ",
    ),
    StructuredFieldSpec(
        "appeal_or_override_path",
        "Appeal or override path",
        "Appeal or override path: ",
    ),
)
PANEL_CONFIG_KEYS = _structured_keys(PANEL_CONFIG_FIELD_SPECS)

WORKFLOW_FIELD_SPECS = (
    StructuredFieldSpec(
        "name",
        "name",
        "",
        render_mode="positional",
        runtime_order=0,
    ),
    StructuredFieldSpec("sequence", "sequence", ": sequence: "),
    StructuredFieldSpec("when", "when", " — when: ", runtime_order=1),
    StructuredFieldSpec(
        "owner",
        "owner",
        " — owner: ",
        required=False,
        runtime_order=2,
    ),
    StructuredFieldSpec(
        "control_plane",
        "control plane",
        " — control plane: ",
        required=False,
        runtime_order=3,
    ),
    StructuredFieldSpec(
        "write_ownership",
        "write ownership",
        " — write ownership: ",
        required=False,
        runtime_order=4,
    ),
    StructuredFieldSpec(
        "checkpoint_rule",
        "checkpoint",
        " — checkpoint: ",
        required=False,
        runtime_order=5,
    ),
    StructuredFieldSpec(
        "resume_rule",
        "resume",
        " — resume: ",
        required=False,
        runtime_order=6,
    ),
    StructuredFieldSpec(
        "verifier_gate",
        "verifier",
        " — verifier: ",
        required=False,
        runtime_order=7,
    ),
    StructuredFieldSpec(
        "stop_condition",
        "stop",
        " — stop: ",
        required=False,
        runtime_order=8,
    ),
    StructuredFieldSpec(
        "escalation_path",
        "escalation",
        " — escalation: ",
        required=False,
        runtime_order=9,
    ),
    StructuredFieldSpec(
        "backout_path",
        "backout",
        " — backout: ",
        required=False,
        runtime_order=10,
    ),
)
WORKFLOW_KEYS = _structured_keys(WORKFLOW_FIELD_SPECS)
WORKFLOW_REQUIRED_KEYS = _structured_required_keys(WORKFLOW_FIELD_SPECS)
RUNTIME_WORKFLOW_CONTROL_FIELDS: tuple[tuple[str, str], ...] = tuple(
    (spec.key, spec.label)
    for spec in sorted(
        (spec for spec in WORKFLOW_FIELD_SPECS if spec.runtime_order is not None),
        key=lambda spec: spec.runtime_order if spec.runtime_order is not None else -1,
    )
    if spec.key not in {"name", "when"}
)
RUNTIME_WORKFLOW_ROUTE = "load STATEMENT_OF_WORK.md Workflows entry when"
RUNTIME_AUXILIARY_TOOL_ROUTE = (
    "load STATEMENT_OF_WORK.md Auxiliary Tools entry before use"
)
RUNTIME_AUXILIARY_TOOL_FIELDS: tuple[tuple[str, str], ...] = tuple(
    (spec.key, spec.label)
    for spec in sorted(
        (
            spec
            for spec in AUXILIARY_TOOL_FIELD_SPECS
            if spec.runtime_order is not None
        ),
        key=lambda spec: spec.runtime_order if spec.runtime_order is not None else -1,
    )
    if spec.key not in {"name", "purpose"}
)
STRUCTURED_IDENTITY_FIELDS = {
    "auxiliary_tools": "name",
    "command_restrictions": "command",
    "workflows": "name",
}
STRUCTURED_IDENTITY_DELIMITERS = {
    "auxiliary_tools": " — ",
    "command_restrictions": " — never run — ",
    "workflows": ":",
}
STRUCTURED_ROW_DELIMITERS = {
    "auxiliary_tools": " — ",
    "workflows": " — ",
}
STRUCTURED_FIELD_DELIMITERS = {
    ("command_restrictions", "reason"): (" — use ",),
}
STRUCTURED_COLLECTION_FIELDS = {
    "auxiliary_tools": AUXILIARY_TOOL_KEYS,
    "command_restrictions": RESTRICTION_KEYS,
    "workflows": WORKFLOW_KEYS,
}
AUTOMATION_SOW_SUMMARY_FIELDS = automation_orders_lint.AUTOMATION_SOW_SUMMARY_FIELDS


def structured_field_delimiters(collection: str, field: str) -> tuple[str, ...]:
    """Return each reserved rendered delimiter for one structured answer field."""

    return tuple(
        dict.fromkeys(
            delimiter
            for delimiter in (
                STRUCTURED_ROW_DELIMITERS.get(collection),
                (
                    STRUCTURED_IDENTITY_DELIMITERS.get(collection)
                    if STRUCTURED_IDENTITY_FIELDS.get(collection) == field
                    else None
                ),
                *STRUCTURED_FIELD_DELIMITERS.get((collection, field), ()),
            )
            if delimiter is not None
        )
    )


ANNEX_KEYS_IN_ORDER = ("soul", "capabilities", "authority")
ANNEX_KEYS = frozenset(ANNEX_KEYS_IN_ORDER)
AUTOMATION_ORDER_KEYS = frozenset({"jobs", "preferred_backend"})
MINIMAL_DEFERRAL_FIELD_SPECS = (
    StructuredFieldSpec("field", "Field", "Field: "),
    StructuredFieldSpec("owner", "Owner", " — Owner: "),
    StructuredFieldSpec("reason", "Reason", " — Reason: "),
    StructuredFieldSpec(
        "boundary_type",
        "Boundary Type",
        " — Boundary Type: ",
    ),
    StructuredFieldSpec(
        "closure_boundary",
        "Closure Boundary",
        " — Closure Boundary: ",
        suffix=".",
    ),
)
MINIMAL_DEFERRAL_KEYS = _structured_keys(MINIMAL_DEFERRAL_FIELD_SPECS)
MINIMAL_DEFERRAL_BOUNDARY_TYPES = frozenset({"date", "milestone", "event"})
MINIMAL_DEFERRABLE_FIELDS = frozenset(
    {
        "Architecture",
        "Deliverables and Acceptance Evidence",
        "In scope",
        "Language/Runtime Standards",
        "Out of scope",
        "Recitals",
        "Tech stack",
        *(spec.deferral_field for spec in COMMAND_SPECS),
    }
)


def structured_field_specs(family: str) -> tuple[StructuredFieldSpec, ...]:
    """Return the ordered, model-owned fields for one structured record family."""

    families = {
        "arbitration_panel": PANEL_CONFIG_FIELD_SPECS,
        "arbitration_panel.seats": PANEL_SEAT_FIELD_SPECS,
        "auxiliary_tools": AUXILIARY_TOOL_FIELD_SPECS,
        "command_restrictions": RESTRICTION_FIELD_SPECS,
        "deliverables": DELIVERABLE_FIELD_SPECS,
        "minimal_deferrals": MINIMAL_DEFERRAL_FIELD_SPECS,
        "workflows": WORKFLOW_FIELD_SPECS,
    }
    try:
        return families[family]
    except KeyError as exc:
        raise KeyError(f"unknown structured record family: {family}") from exc


def structured_labeled_field_map(family: str) -> dict[str, str]:
    """Map exact rendered labels to keys for a family with labeled segments."""

    return {
        spec.label: spec.key
        for spec in structured_field_specs(family)
        if spec.render_mode == "labeled"
    }


def render_structured_record(
    family: str,
    item: Mapping[str, object],
    *,
    empty_required: str = "TBD",
) -> str:
    """Render every non-container field through its model-owned byte grammar."""

    segments: list[str] = []
    for spec in structured_field_specs(family):
        if spec.render_mode == "container":
            continue
        value = str(item.get(spec.key, "")).strip()
        if not value:
            if not spec.required:
                continue
            value = empty_required
        segments.append(f"{spec.prefix}{value}{spec.suffix}")
    return "".join(segments)


def _structured_family_contracts() -> dict[
    str,
    tuple[frozenset[str], frozenset[str], tuple[StructuredFieldSpec, ...]],
]:
    """Return live aliases so model mutation checks cannot use stale snapshots."""

    return {
        "arbitration_panel": (
            PANEL_CONFIG_KEYS,
            PANEL_CONFIG_KEYS,
            PANEL_CONFIG_FIELD_SPECS,
        ),
        "arbitration_panel.seats": (
            PANEL_SEAT_KEYS,
            PANEL_SEAT_KEYS,
            PANEL_SEAT_FIELD_SPECS,
        ),
        "auxiliary_tools": (
            AUXILIARY_TOOL_KEYS,
            REQUIRED_AUXILIARY_TOOL_KEYS,
            AUXILIARY_TOOL_FIELD_SPECS,
        ),
        "command_restrictions": (
            RESTRICTION_KEYS,
            RESTRICTION_KEYS,
            RESTRICTION_FIELD_SPECS,
        ),
        "deliverables": (
            DELIVERABLE_KEYS,
            frozenset(DELIVERABLE_REQUIRED_KEYS),
            DELIVERABLE_FIELD_SPECS,
        ),
        "minimal_deferrals": (
            MINIMAL_DEFERRAL_KEYS,
            MINIMAL_DEFERRAL_KEYS,
            MINIMAL_DEFERRAL_FIELD_SPECS,
        ),
        "workflows": (
            WORKFLOW_KEYS,
            WORKFLOW_REQUIRED_KEYS,
            WORKFLOW_FIELD_SPECS,
        ),
    }


def structured_field_spec_errors() -> list[str]:
    """Reject accepted nested fields without one render/parser owner."""

    errors: list[str] = []
    for family, (accepted, required, specs) in _structured_family_contracts().items():
        keys = [spec.key for spec in specs]
        duplicate_keys = sorted({key for key in keys if keys.count(key) > 1})
        if duplicate_keys:
            errors.append(
                f"structured family {family!r} has duplicate field specs: "
                f"{duplicate_keys}"
            )
        spec_keys = set(keys)
        if spec_keys != set(accepted):
            missing = sorted(set(accepted) - spec_keys)
            unknown = sorted(spec_keys - set(accepted))
            if missing:
                errors.append(
                    f"structured family {family!r} accepted fields lack render/parser "
                    f"owners: {missing}"
                )
            if unknown:
                errors.append(
                    f"structured family {family!r} field specs name unaccepted fields: "
                    f"{unknown}"
                )
        spec_required = {spec.key for spec in specs if spec.required}
        if spec_required != set(required):
            errors.append(
                f"structured family {family!r} required fields differ from its "
                "model-owned field specs"
            )

        labels: list[str] = []
        runtime_orders: list[int] = []
        for spec in specs:
            if not spec.key.strip():
                errors.append(f"structured family {family!r} has a blank field key")
            if not spec.label.strip():
                errors.append(
                    f"structured family {family!r} field {spec.key!r} has no "
                    "semantic/rendered label owner"
                )
            else:
                labels.append(spec.label.casefold())
            if spec.render_mode not in {"container", "labeled", "positional"}:
                errors.append(
                    f"structured family {family!r} field {spec.key!r} uses an "
                    f"unknown render mode: {spec.render_mode!r}"
                )
            if spec.render_mode == "container":
                if spec.prefix or spec.suffix:
                    errors.append(
                        f"structured family {family!r} container field "
                        f"{spec.key!r} must not declare rendered bytes"
                    )
                if not (spec.non_rendered_reason or "").strip():
                    errors.append(
                        f"structured family {family!r} non-rendered field "
                        f"{spec.key!r} lacks a documented classification"
                    )
                if spec.runtime_order is not None:
                    errors.append(
                        f"structured family {family!r} container field "
                        f"{spec.key!r} cannot be a runtime-route field"
                    )
            else:
                if spec.non_rendered_reason is not None:
                    errors.append(
                        f"structured family {family!r} rendered field "
                        f"{spec.key!r} must not declare a non-rendered reason"
                    )
                if spec.render_mode == "labeled":
                    if f"{spec.label}:" not in spec.prefix:
                        errors.append(
                            f"structured family {family!r} field {spec.key!r} "
                            "render prefix does not own its exact label"
                        )
            if spec.runtime_order is not None:
                if spec.runtime_order < 0:
                    errors.append(
                        f"structured family {family!r} field {spec.key!r} has a "
                        "negative runtime order"
                    )
                runtime_orders.append(spec.runtime_order)
        duplicate_semantic_labels = sorted(
            {label for label in labels if labels.count(label) > 1}
        )
        if duplicate_semantic_labels:
            errors.append(
                f"structured family {family!r} has duplicate semantic/rendered labels: "
                f"{duplicate_semantic_labels}"
            )
        if len(runtime_orders) != len(set(runtime_orders)):
            errors.append(
                f"structured family {family!r} has duplicate runtime route order"
            )

    expected_workflow_runtime = tuple(
        (spec.key, spec.label)
        for spec in sorted(
            (
                spec
                for spec in WORKFLOW_FIELD_SPECS
                if spec.runtime_order is not None
            ),
            key=lambda spec: spec.runtime_order
            if spec.runtime_order is not None
            else -1,
        )
        if spec.key not in {"name", "when"}
    )
    if RUNTIME_WORKFLOW_CONTROL_FIELDS != expected_workflow_runtime:
        errors.append("workflow runtime-route fields differ from their field specs")
    expected_auxiliary_runtime = tuple(
        (spec.key, spec.label)
        for spec in sorted(
            (
                spec
                for spec in AUXILIARY_TOOL_FIELD_SPECS
                if spec.runtime_order is not None
            ),
            key=lambda spec: spec.runtime_order
            if spec.runtime_order is not None
            else -1,
        )
        if spec.key not in {"name", "purpose"}
    )
    if RUNTIME_AUXILIARY_TOOL_FIELDS != expected_auxiliary_runtime:
        errors.append("auxiliary-tool runtime-route fields differ from their field specs")
    if DELIVERABLE_REQUIRED_KEYS != tuple(
        spec.key for spec in DELIVERABLE_FIELD_SPECS if spec.required
    ):
        errors.append("deliverable required-field order differs from its field specs")
    if set(MINIMAL_DELIVERABLE_VALUES_BY_KEY) != set(DELIVERABLE_KEYS):
        errors.append(
            "minimal deliverable values do not cover the model-owned deliverable fields"
        )
    expected_panel_labels = {
        spec.label
        for spec in PANEL_CONFIG_FIELD_SPECS
        if spec.render_mode == "labeled"
    }
    blueprint_panel_labels = set(
        sow_blueprint_labeled_row_labels("arbitration_panel")
    ) - {"Seat 1"}
    if blueprint_panel_labels != expected_panel_labels:
        errors.append(
            "arbitration-panel blueprint labels differ from their field specs"
        )
    return errors

EXECUTION_POSTURES = frozenset({"act", "advise", "ask-when-ambiguous"})
DEPENDENCY_POSTURES = frozenset(
    {"no-external-dependencies", "justify-external-dependencies"}
)
BOOTSTRAP_MODES = frozenset({"full", "minimal"})


@dataclass(frozen=True, slots=True)
class InstructionDirectiveRequirement:
    """One exact ordered paragraph in a trusted instruction-surface policy."""

    description: str
    exact_normalized_paragraph: str


@dataclass(frozen=True, slots=True)
class InstructionSurfaceRequirement:
    """One existing instruction surface required by a trusted layout policy."""

    relative_path: str
    description: str
    ordered_directives: tuple[InstructionDirectiveRequirement, ...]


@dataclass(frozen=True, slots=True)
class ProjectLayoutPolicy:
    """Trusted code-only policy for one project lifecycle layout.

    The public command surface registers only the downstream policy below.
    A non-product maintainer adapter may install another policy before importing
    lifecycle entrypoints. Retained JSON can select only an already registered
    policy; it cannot create or alter one.
    """

    kind: str
    manages_runtime_entrypoint: bool
    runtime_required: bool
    runtime_forbidden: bool
    runtime_wrappers_allowed: bool
    forbid_target_within_framework_root: bool = False
    require_framework_root_target: bool = False
    require_nested_contract_root: bool = False
    require_non_product_contract_root: bool = False
    retained_input_within_contract_root: bool = False
    require_explicit_render_date: bool = False
    emit_external_input_warnings: bool = True
    required_framework_markers: tuple[str, ...] = ()
    instruction_surfaces: tuple[InstructionSurfaceRequirement, ...] = ()
    state_template_source_paths: frozenset[str] = frozenset()
    contract_sync_command_prefix: tuple[str, ...] = ()


_PROJECT_LAYOUT_POLICIES: dict[str, ProjectLayoutPolicy] = {}
PROJECT_KINDS: frozenset[str] = frozenset()


def register_project_layout_policy(policy: ProjectLayoutPolicy) -> None:
    """Install one trusted in-process layout policy before lifecycle imports."""

    global PROJECT_KINDS
    if not re.fullmatch(r"[a-z][a-z0-9-]*", policy.kind):
        raise ValueError("project layout policy kind must be a stable lowercase ID")
    if policy.runtime_required and policy.runtime_forbidden:
        raise ValueError("project layout policy cannot require and forbid runtime")
    if policy.manages_runtime_entrypoint and policy.runtime_forbidden:
        raise ValueError("runtime-entrypoint layout cannot forbid runtime")
    if not policy.manages_runtime_entrypoint and policy.runtime_wrappers_allowed:
        raise ValueError("layout without a runtime entrypoint cannot allow wrappers")
    if any(not token for token in policy.contract_sync_command_prefix):
        raise ValueError("project layout contract-sync prefix tokens must be non-empty")
    for surface in policy.instruction_surfaces:
        if not surface.relative_path or not surface.description.strip():
            raise ValueError(
                "project layout instruction surfaces require a path and description"
            )
        if not surface.ordered_directives:
            raise ValueError(
                "project layout instruction surfaces require ordered directives"
            )
        ordered_paragraphs: list[str] = []
        for directive in surface.ordered_directives:
            paragraph = directive.exact_normalized_paragraph
            normalized = " ".join(paragraph.split())
            if not directive.description.strip() or not paragraph:
                raise ValueError(
                    "project layout instruction directives require a description "
                    "and exact normalized paragraph"
                )
            if paragraph != normalized:
                raise ValueError(
                    "project layout instruction directive paragraphs must be "
                    "non-empty normalized single-line values"
                )
            without_contract_root = paragraph.replace("{contract_root}", "")
            if "{" in without_contract_root or "}" in without_contract_root:
                raise ValueError(
                    "project layout instruction directive paragraphs may use "
                    "only the {contract_root} placeholder"
                )
            ordered_paragraphs.append(paragraph)
        if len(ordered_paragraphs) != len(set(ordered_paragraphs)):
            raise ValueError(
                "project layout instruction directive paragraphs must be unique "
                "per surface"
            )
    existing = _PROJECT_LAYOUT_POLICIES.get(policy.kind)
    if existing is not None:
        if existing != policy:
            raise ValueError(f"project layout policy already registered: {policy.kind}")
        return
    _PROJECT_LAYOUT_POLICIES[policy.kind] = policy
    PROJECT_KINDS = frozenset(_PROJECT_LAYOUT_POLICIES)


def project_layout_policy(kind: object) -> ProjectLayoutPolicy:
    """Return one registered policy selected by validated lifecycle data."""

    if not isinstance(kind, str) or kind not in _PROJECT_LAYOUT_POLICIES:
        raise ValueError(
            "project kind must be one of: " + ", ".join(sorted(PROJECT_KINDS))
        )
    return _PROJECT_LAYOUT_POLICIES[kind]


register_project_layout_policy(
    ProjectLayoutPolicy(
        kind="downstream",
        manages_runtime_entrypoint=True,
        runtime_required=True,
        runtime_forbidden=False,
        runtime_wrappers_allowed=True,
        forbid_target_within_framework_root=True,
    )
)
SECURITY_POLICY_FILES = frozenset(
    {"inline in this SOW", "project SECURITY.md", "none"}
)
INDEPENDENT_ASSESSMENT_APPROVALS = frozenset({"Required", "Autonomous"})
DEFERRED_VALUE_RE = re.compile(
    r"^(?:tbd|to be confirmed(?:\b| by)|replace with|replace-with)",
    re.IGNORECASE,
)


def is_deferred_value(value: object) -> bool:
    """Classify the shared raw-answer and rendered-contract deferral grammar."""

    return isinstance(value, str) and bool(DEFERRED_VALUE_RE.search(value.strip()))

_MINIMAL_REQUIRED = frozenset(
    {"agent", "bootstrap_mode", "framework_verification_runner", "project_name"}
)
_FULL_REQUIRED = frozenset(
    {
        "architecture",
        "bootstrap_mode",
        "commands",
        "agent",
        "deliverables",
        "framework_verification_runner",
        "in_scope",
        "language_runtime_standards",
        "out_of_scope",
        "project_name",
        "recitals",
        "tech_stack",
    }
)


def _field(
    name: str,
    kind: AnswerKind,
    *,
    required_in: tuple[str, ...] = (),
    operative: bool = False,
    profile_default_allowed: bool = True,
    enum: tuple[str, ...] = (),
    active_when: str | None = None,
) -> AnswerFieldSpec:
    return AnswerFieldSpec(
        name=name,
        kind=kind,
        required_in=frozenset(required_in),
        operative=operative,
        profile_default_allowed=profile_default_allowed,
        enum=enum,
        active_when=active_when,
    )


ANSWER_FIELD_SPECS = (
    _field("acceptance_checklist", "lines"),
    _field("acquisition_boundary", "lines", operative=True),
    _field("agent", "string", required_in=("minimal", "full"), operative=True, profile_default_allowed=False),
    _field("ai_disclosure", "string", operative=True),
    _field("annexes", "annexes", profile_default_allowed=False),
    _field("applicable_standards", "lines"),
    _field("approval_boundaries", "lines", operative=True),
    _field("arbitration_panel", "arbitration_panel"),
    _field("architecture", "string", required_in=("full",), profile_default_allowed=False),
    _field(
        "automation_orders",
        "automation_orders",
        profile_default_allowed=False,
        active_when="include_automation_orders",
    ),
    _field("auxiliary_tools", "auxiliary_tools"),
    _field("backout_policy", "string", operative=True),
    _field("bootstrap_mode", "string", required_in=("minimal", "full"), enum=tuple(sorted(BOOTSTRAP_MODES))),
    _field("branch_policy", "string", operative=True),
    _field("code_review_checklist", "lines"),
    _field("command_restrictions", "command_restrictions"),
    _field("commands", "commands", required_in=("full",), profile_default_allowed=False),
    _field("constraints", "lines", operative=True),
    _field("credential_delivery", "string", operative=True),
    _field("critical_surface_policy", "string", operative=True),
    _field("critical_surfaces", "lines", operative=True, profile_default_allowed=False),
    _field("date", "string", profile_default_allowed=False),
    _field("decision_authority_grant", "string", operative=True),
    _field("default_review_topology", "string", operative=True),
    _field("deliverables", "deliverables", required_in=("full",), profile_default_allowed=False),
    _field("dependency_posture", "string", operative=True, enum=tuple(sorted(DEPENDENCY_POSTURES))),
    _field("direct_panel_rules", "lines", operative=True),
    _field("execution_posture", "string", operative=True, enum=tuple(sorted(EXECUTION_POSTURES))),
    _field("file_structure", "lines", profile_default_allowed=False),
    _field("framework_verification_runner", "string", required_in=("minimal", "full"), operative=True, profile_default_allowed=False),
    _field("in_scope", "lines", required_in=("full",), profile_default_allowed=False),
    _field("include_automation_orders", "boolean"),
    _field("include_findings", "boolean"),
    _field("include_framework_feedback", "boolean"),
    _field("include_precedents", "boolean"),
    _field("include_reviewer_lane_feedback", "boolean"),
    _field("include_security_verification", "boolean"),
    _field("include_source_monitor_researcher", "boolean"),
    _field("include_source_packs", "boolean"),
    _field("include_source_update", "boolean"),
    _field("independent_assessment_approval", "string", operative=True, enum=tuple(sorted(INDEPENDENT_ASSESSMENT_APPROVALS))),
    _field("key_dependencies", "lines", operative=True, profile_default_allowed=False),
    _field("key_directories", "lines", operative=True, profile_default_allowed=False),
    _field("language_runtime_standards", "string", required_in=("full",), profile_default_allowed=False),
    _field("language_specific_rules", "lines", operative=True, profile_default_allowed=False),
    _field("minimal_deferrals", "minimal_deferrals", profile_default_allowed=False),
    _field("out_of_scope", "lines", required_in=("full",), profile_default_allowed=False),
    _field("package_manager", "string", operative=True, profile_default_allowed=False),
    _field("pattern_sources", "lines", operative=True, profile_default_allowed=False),
    _field("persistent_memory_boundary", "string", operative=True),
    _field("project_name", "string", required_in=("minimal", "full"), operative=True, profile_default_allowed=False),
    _field("project_vocabulary", "lines", operative=True, profile_default_allowed=False),
    _field("recitals", "lines", required_in=("full",), profile_default_allowed=False),
    _field("reviewer_lane_inventory", "string", operative=True),
    _field("secret_store", "string", operative=True),
    _field("security_policy_file", "string", operative=True, enum=tuple(sorted(SECURITY_POLICY_FILES))),
    _field("security_policy_terms", "lines", operative=True),
    _field("security_verification_profile_scope", "string", operative=True, active_when="include_security_verification"),
    _field("security_verification_target_policy", "string", operative=True, active_when="include_security_verification"),
    _field("shared_framework_source_reference", "string", profile_default_allowed=False, active_when="include_source_packs"),
    _field("source_freshness_policy", "string", operative=True),
    _field("source_monitor_boundary", "string", operative=True, active_when="include_source_monitor_researcher"),
    _field("source_monitor_instruction_sources", "lines", operative=True, profile_default_allowed=False, active_when="include_source_monitor_researcher"),
    _field("source_monitor_role", "string", operative=True, active_when="include_source_monitor_researcher"),
    _field("source_monitor_source_data", "lines", operative=True, profile_default_allowed=False, active_when="include_source_monitor_researcher"),
    _field("source_originality_policy", "string", operative=True),
    _field("source_registry_scope", "string", operative=True, profile_default_allowed=False, active_when="include_source_update"),
    _field("source_review_cadence", "string", operative=True, active_when="include_source_update"),
    _field("sow_version", "string"),
    _field("standing_panel_convocation_approval", "string", operative=True),
    _field("tech_stack", "string", required_in=("full",), profile_default_allowed=False),
    _field("user", "string", profile_default_allowed=False),
    _field("verification_profiles", "lines", operative=True),
    _field("version_control_policy", "string", operative=True),
    _field("version_control_profile", "lines", operative=True),
    _field("version_review_policy", "string", operative=True),
    _field("workflows", "workflows"),
)

ANSWER_FIELDS = {spec.name: spec for spec in ANSWER_FIELD_SPECS}
ALLOWED_KEYS = frozenset(ANSWER_FIELDS)
REQUIRED_KEYS_MINIMAL = frozenset(
    spec.name for spec in ANSWER_FIELD_SPECS if "minimal" in spec.required_in
)
REQUIRED_KEYS_FULL = frozenset(
    spec.name for spec in ANSWER_FIELD_SPECS if "full" in spec.required_in
)
BOOLEAN_KEYS = frozenset(
    spec.name for spec in ANSWER_FIELD_SPECS if spec.kind == "boolean"
)
LINE_VALUE_KEYS = frozenset(
    spec.name for spec in ANSWER_FIELD_SPECS if spec.kind == "lines"
)
STRING_KEYS = frozenset(
    spec.name for spec in ANSWER_FIELD_SPECS if spec.kind == "string"
)
OPERATIVE_STRING_KEYS = frozenset(
    spec.name
    for spec in ANSWER_FIELD_SPECS
    if spec.kind == "string" and spec.operative
)
OPERATIVE_LINE_KEYS = frozenset(
    spec.name
    for spec in ANSWER_FIELD_SPECS
    if spec.kind == "lines" and spec.operative
)
SETUP_PROFILE_FORBIDDEN_KEYS = frozenset(
    spec.name for spec in ANSWER_FIELD_SPECS if not spec.profile_default_allowed
)

if REQUIRED_KEYS_MINIMAL != _MINIMAL_REQUIRED:
    raise RuntimeError("minimal answer requirements drifted from the declarative model")
if REQUIRED_KEYS_FULL != _FULL_REQUIRED:
    raise RuntimeError("full answer requirements drifted from the declarative model")


CORE_STATE_TEMPLATES = {
    "TODO.md": "project_state_templates/TODO.md",
    "DECISIONS.md": "project_state_templates/DECISIONS.md",
}
OPTIONAL_STATE_SPECS = (
    OptionalStateSpec(
        flag="include_findings",
        filename="FINDINGS.md",
        template="project_state_templates/FINDINGS.md",
        partition="mutable",
    ),
    OptionalStateSpec(
        flag="include_reviewer_lane_feedback",
        filename="REVIEWER_LANE_FEEDBACK.md",
        template="project_state_templates/REVIEWER_LANE_FEEDBACK.md",
        partition="mutable",
        definition_label="Reviewer Lane Feedback File",
    ),
    OptionalStateSpec(
        flag="include_framework_feedback",
        filename="FRAMEWORK_FEEDBACK.md",
        template="project_state_templates/FRAMEWORK_FEEDBACK.md",
        partition="mutable",
        definition_label="Framework Feedback File",
    ),
    OptionalStateSpec(
        flag="include_precedents",
        filename="PRECEDENTS.md",
        template="project_state_templates/PRECEDENTS.md",
        partition="mutable",
        bootstrap_template="project_state_templates/bootstrap/PRECEDENTS.md",
        definition_label="Precedent File",
    ),
    OptionalStateSpec(
        flag="include_source_packs",
        filename="SOURCE_PACKS.md",
        template="project_state_templates/SOURCE_PACKS.md",
        partition="mutable",
        bootstrap_template="project_state_templates/bootstrap/SOURCE_PACKS.md",
        definition_label="Source Packs File",
    ),
    OptionalStateSpec(
        flag="include_source_update",
        filename="SOURCE_UPDATE.md",
        template="project_state_templates/SOURCE_UPDATE.md",
        partition="mutable",
        bootstrap_template="project_state_templates/bootstrap/SOURCE_UPDATE.md",
        definition_label="Source Update File",
    ),
    OptionalStateSpec(
        flag="include_source_monitor_researcher",
        filename="SOURCE_MONITOR_RESEARCHER.md",
        template="project_state_templates/SOURCE_MONITOR_RESEARCHER.md",
        partition="immutable",
        definition_label="Source Monitor Researcher Brief",
    ),
    OptionalStateSpec(
        flag="include_security_verification",
        filename="SECURITY_VERIFICATION.md",
        template="project_state_templates/SECURITY_VERIFICATION.md",
        partition="mutable",
        bootstrap_template="project_state_templates/bootstrap/SECURITY_VERIFICATION.md",
        definition_label="Security Verification File",
    ),
    OptionalStateSpec(
        flag="include_automation_orders",
        filename="AUTOMATION_ORDERS.json",
        template="project_state_templates/AUTOMATION_ORDERS.json",
        partition="mutable",
        definition_label="Automation Orders File",
    ),
)


def optional_state_filenames(
    partition: OptionalStatePartition,
) -> frozenset[str]:
    """Return the model-declared optional-state files in one receipt partition."""

    if partition not in OPTIONAL_STATE_PARTITIONS:
        raise ValueError(f"unsupported optional-state partition: {partition}")
    return frozenset(
        spec.filename
        for spec in OPTIONAL_STATE_SPECS
        if spec.partition == partition
    )


STATE_TEMPLATES = {
    **CORE_STATE_TEMPLATES,
    **{spec.filename: spec.template for spec in OPTIONAL_STATE_SPECS},
}
DOWNSTREAM_CONTRACT_REFERENCE_FILES = (
    "AGENT_PROJECT.md",
    "STATEMENT_OF_WORK.md",
    *STATE_TEMPLATES,
)
BOOTSTRAP_STATE_TEMPLATES = {
    spec.filename: spec.bootstrap_template
    for spec in OPTIONAL_STATE_SPECS
    if spec.bootstrap_template is not None
}
OPTIONAL_STATE_FLAGS = tuple(
    (spec.flag, spec.filename) for spec in OPTIONAL_STATE_SPECS
)
DECLARED_OPTIONAL_STATE = {
    spec.definition_label: spec.filename
    for spec in OPTIONAL_STATE_SPECS
    if spec.definition_label is not None
}
OPTIONAL_STATE_BY_DEFINITION_LABEL = {
    spec.definition_label: spec
    for spec in OPTIONAL_STATE_SPECS
    if spec.definition_label is not None
}
OPTIONAL_STATE_DEFINITION_BY_FLAG = {
    spec.flag: spec.definition_label
    for spec in OPTIONAL_STATE_SPECS
    if spec.definition_label is not None
}
MANUAL_STATE_TEMPLATES = {
    "DELEGATED_COMMUNICATIONS_COVERAGE.md": (
        "project_state_templates/DELEGATED_COMMUNICATIONS_COVERAGE.md"
    ),
    "SOURCE_DEEP_RESEARCH.md": "project_state_templates/SOURCE_DEEP_RESEARCH.md",
    "VIDEO_DELIVERABLE_QA.md": "project_state_templates/VIDEO_DELIVERABLE_QA.md",
    "VISUAL_ASSET_QA.md": "project_state_templates/VISUAL_ASSET_QA.md",
}

FRAMEWORK_VERIFICATION_RUNNER_PLACEHOLDER = (
    "REPLACE WITH THE EXACT RUNNER REPORTED BY scripts/check_prereqs.py"
)
FRAMEWORK_REFERENCE_TEMPLATE_PLACEHOLDER = "[framework reference]"
RUNNER_METACHAR_RE = re.compile(r"[;&|<>`$(){}\[\]*?!#~\\%^]")
PYTHON_RUNNER_EXECUTABLE_RE = re.compile(
    r"^python(?:\d+(?:\.\d+)*)?(?:\.exe)?$",
    re.IGNORECASE,
)
PY_LAUNCHER_EXECUTABLES = frozenset({"py", "py.exe"})
UV_EXECUTABLES = frozenset({"uv", "uv.exe"})
UV_PYTHON_EXECUTABLES = frozenset({"python", "python.exe"})
TRANSPARENT_EXEC_WORKDIR_OPTIONS = frozenset({"-w", "--workdir"})
QUALIFIED_TRANSPARENT_EXEC_WRAPPER_TOKENS = frozenset({"container"})


def runner_executable_name(token: str) -> str:
    """Return a portable basename for a shell-parsed executable token."""

    return token.replace("\\", "/").rsplit("/", maxsplit=1)[-1].casefold()


def direct_python_runner_start(tokens: list[str]) -> int | None:
    """Find a supported launcher suffix that cannot consume a script argv."""

    required_flags = ["-E", "-S", "-B"]
    if len(tokens) >= 6:
        uv_name = runner_executable_name(tokens[-6])
        python_name = runner_executable_name(tokens[-4])
        if (
            uv_name in UV_EXECUTABLES
            and tokens[-5] == "run"
            and python_name in UV_PYTHON_EXECUTABLES
            and tokens[-3:] == required_flags
        ):
            return len(tokens) - 6
    if len(tokens) >= 5:
        launcher_name = runner_executable_name(tokens[-5])
        if (
            launcher_name in PY_LAUNCHER_EXECUTABLES
            and tokens[-4] == "-3"
            and tokens[-3:] == required_flags
        ):
            return len(tokens) - 5
    if len(tokens) >= 4:
        python_name = runner_executable_name(tokens[-4])
        if (
            PYTHON_RUNNER_EXECUTABLE_RE.fullmatch(python_name)
            and tokens[-3:] == required_flags
        ):
            return len(tokens) - 4
    return None


def transparent_exec_wrapper_errors(tokens: list[str], label: str) -> list[str]:
    """Validate the bounded qualified outer-wrapper grammar for project runners."""

    contract = (
        "<qualified-exec-wrapper> exec [-w|--workdir <directory>] "
        "<target> <direct-python-runner>"
    )
    if len(tokens) < 3 or tokens[1] != "exec":
        return [f"{label} outer wrapper must use the bounded form: {contract}"]
    if tokens[0] not in QUALIFIED_TRANSPARENT_EXEC_WRAPPER_TOKENS:
        return [
            f"{label} outer wrapper executable is not a qualified transparent exec wrapper"
        ]

    wrapper_args = tokens[2:]
    if wrapper_args and wrapper_args[0] in TRANSPARENT_EXEC_WORKDIR_OPTIONS:
        if len(wrapper_args) != 3:
            return [f"{label} outer wrapper must use the bounded form: {contract}"]
        workdir = wrapper_args[1]
        target = wrapper_args[2]
        if not workdir or not target or workdir.startswith("-") or target.startswith("-"):
            return [
                f"{label} outer wrapper directory and target must be fixed positional values"
            ]
        return []
    if len(wrapper_args) != 1 or not wrapper_args[0] or wrapper_args[0].startswith("-"):
        return [f"{label} outer wrapper must use the bounded form: {contract}"]
    return []


def framework_verification_runner_errors(value: object, label: str) -> list[str]:
    """Validate the shared inert runner-prefix contract without filesystem I/O."""

    if not isinstance(value, str):
        return [f"{label} must be a string"]
    runner = value.strip()
    if runner.casefold() in {"", "none", "tbd"} or is_deferred_value(runner):
        return [f"{label} must be a concrete executable command prefix"]
    errors: list[str] = []
    try:
        tokens = shlex.split(runner)
    except ValueError as exc:
        return [f"{label} is not shell-parseable: {exc}"]
    if safe_paths.PATH_CONTROL_RE.search(runner):
        errors.append(f"{label} must be single-line text without control characters")
    if not tokens or tokens[0].startswith("-"):
        errors.append(f"{label} must start with a concrete executable")
    if RUNNER_METACHAR_RE.search(runner):
        errors.append(
            f"{label} must be one inert command prefix without shell control or expansion metacharacters"
        )
    if errors:
        return errors

    leaf_start = direct_python_runner_start(tokens)
    if leaf_start is None:
        return [
            f"{label} must end exactly with a supported non-consuming Python runner: "
            "uv run python -E -S -B, python[version] -E -S -B, or "
            "py -3 -E -S -B"
        ]
    wrapper_tokens = tokens[:leaf_start]
    if wrapper_tokens:
        errors.extend(transparent_exec_wrapper_errors(wrapper_tokens, label))
    return errors


ANNEX_LABELS = {
    "authority": "Annex C — Scope of Authority (AUTHORITY.md)",
    "capabilities": "Annex B — Agent Qualifications (CAPABILITIES.md)",
    "soul": "Annex A — Agent Profile (SOUL.md)",
}
SECURITY_POLICY_ANNEX_LABEL = "Annex D — Security Policy (SECURITY.md)"
SECURITY_POLICY_ANNEX_REFERENCE = "SECURITY.md"
ANNEX_IDENTITY_BY_KEY = {
    "soul": "A",
    "capabilities": "B",
    "authority": "C",
}
SECURITY_POLICY_ANNEX_IDENTITY = "D"
ANNEX_LABEL_BY_IDENTITY = {
    **{
        ANNEX_IDENTITY_BY_KEY[key]: label
        for key, label in ANNEX_LABELS.items()
    },
    SECURITY_POLICY_ANNEX_IDENTITY: SECURITY_POLICY_ANNEX_LABEL,
}
ANNEX_IDENTITY_BY_LABEL = {
    label: identity for identity, label in ANNEX_LABEL_BY_IDENTITY.items()
}


def normalized_contract_identity(value: str) -> str:
    """Normalize one declared structured identity for collision checks."""

    canonical = unicodedata.normalize("NFC", value).casefold()
    return unicodedata.normalize("NFC", " ".join(canonical.split()))


def render_runtime_workflow_route(item: Mapping[str, object]) -> str:
    """Render the active workflow index without copying its canonical sequence."""

    segments = [
        f"{str(item.get('name', '')).strip()}: {RUNTIME_WORKFLOW_ROUTE} "
        f"{str(item.get('when', '')).strip()}"
    ]
    for key, label in RUNTIME_WORKFLOW_CONTROL_FIELDS:
        value = str(item.get(key, "")).strip()
        if value:
            segments.append(f"{label}: {value}")
    return " — ".join(segments)


def render_runtime_auxiliary_tool_route(item: Mapping[str, object]) -> str:
    """Render an auxiliary-tool index while canonical detail remains in the SOW."""

    segments = [
        str(item.get("name", "")).strip(),
        str(item.get("purpose", "")).strip(),
        RUNTIME_AUXILIARY_TOOL_ROUTE,
    ]
    for key, label in RUNTIME_AUXILIARY_TOOL_FIELDS:
        value = str(item.get(key, "")).strip()
        if value:
            segments.append(f"{label}: {value}")
    return " — ".join(segments)


DEFAULT_SOURCE_FRESHNESS_POLICY = (
    "Verify current primary sources before recording or using latest/current stable/unpinned versions; "
    "use version-scoped docs for pinned versions; use user-supplied material when network acquisition is not approved; "
    "check project-approved and framework-approved source registries before duplicate research."
)
DEFAULT_VERSION_REVIEW_POLICY = (
    "Keep pinned versions unless the User approves an upgrade review; after an approved source check shows a pin is behind current stable, ask whether to keep, defer, or review upgrade."
)
DEFAULT_SOURCE_ORIGINALITY_POLICY = (
    "Independent implementation for external inspiration; external code or assets only after approval and applicable license, attribution, and notice review."
)
DEFAULT_CRITICAL_SURFACE_POLICY = (
    "Use the project Critical Surfaces list to select stronger review, approval, and verification burden; treat unclassified high-impact surfaces as unknown until inspected."
)
DEFAULT_DECISION_AUTHORITY_GRANT = (
    "framework default; creative or implementation discretion does not include architecture, stack, dependency, deployment, VCS, acquisition, memory, or policy choices unless explicitly granted."
)
DEFAULT_VERSION_CONTROL_POLICY = (
    "Use the existing repository state; do not initialize repositories or modify VCS metadata without explicit User scope."
)
DEFAULT_BRANCH_POLICY = (
    "Use the current branch unless the User defines a default/protected branch or side-branch workflow."
)
DEFAULT_BACKOUT_POLICY = (
    "Prefer the smallest reversible fix; require User approval before destructive VCS, data, migration, deploy, or reset operations."
)
DEFAULT_PERSISTENT_MEMORY_BOUNDARY = (
    "Persistent memory is disabled unless an enabled project policy authorizes the write class; every write also requires a current User request or confirmation, or independent validation under that policy. Provenance is evidence only and never write authority; memory entries record declarative facts, not standing instructions."
)
DEFAULT_SECURITY_POLICY_FILE = "none"
DEFAULT_SHARED_FRAMEWORK_SOURCE_REFERENCE = "none"
DEFAULT_AUTOMATION_BACKEND = "unspecified"
DEFAULT_SOURCE_REGISTRY_SCOPE = "project-approved source-sensitive surfaces"
DEFAULT_SOURCE_REVIEW_CADENCE = (
    "manual or source-triggered unless the project defines a recurring cadence"
)
DEFAULT_SOURCE_MONITOR_ROLE = (
    "observe-only recurring or explicitly delegated source-discovery brief for later "
    "coordinator review; project authority owns the cadence or trigger"
)
DEFAULT_SOURCE_MONITOR_INSTRUCTION_SOURCES = (
    "task_orders/source_update.md in observe mode / "
    "practice_guides/source_freshness_review.md / "
    "practice_guides/scheduled_automation.md / project local_overlays/ instruction files when present"
)
DEFAULT_SOURCE_MONITOR_BOUNDARY = (
    "no tracked edits, package installs, staging, commits, pushes, or external system "
    "changes unless a separate approved task order grants them"
)
DEFAULT_SECURITY_VERIFICATION_PROFILE_SCOPE = (
    "secure-code, dependency, secret, approved static-analysis, authorized dynamic-check, "
    "high-risk input, and release-hardening checks as project-approved"
)
DEFAULT_SECURITY_VERIFICATION_TARGET_POLICY = (
    "local or explicitly approved staging targets only"
)
MINIMAL_DELIVERABLE_DESCRIPTION = (
    "deferred by minimal bootstrap; define the deliverable before deliverable-specific work"
)
MINIMAL_DELIVERABLE_TEST = (
    "deferred by minimal bootstrap; define the verification method before claiming completion"
)
MINIMAL_DELIVERABLE_PASS_CRITERIA = (
    "deferred by minimal bootstrap; define pass criteria before claiming completion"
)
MINIMAL_DELIVERABLE_VALUES_BY_KEY = {
    "description": MINIMAL_DELIVERABLE_DESCRIPTION,
    "test": MINIMAL_DELIVERABLE_TEST,
    "pass_criteria": MINIMAL_DELIVERABLE_PASS_CRITERIA,
}
MINIMAL_COMMAND_DEFERRAL = (
    "deferred by minimal bootstrap; define a command or explicit none before command-dependent work"
)
DEFAULT_DEFINITION_VALUE = "TBD"
DEFAULT_OPTIONAL_DEFINITION_VALUE = "none"
DEFAULT_ARBITRATION_PANEL_PROJECTION = "framework default"
CUSTOM_ARBITRATION_PANEL_PROJECTION = "custom package; consult SOW Arbitration Panel"
EXECUTION_MODE_SUFFIX = (
    " (does not override approval, safety, or scope boundaries)"
)
DEPENDENCY_RULE_SUFFIX = (
    " (governs adding new dependencies, not already-approved project dependencies)"
)
PYTHON_LANGUAGE_POLICY = (
    "Python work uses the command form recorded in this SOW. `uv run python -E -S -B` is normal only "
    "when `uv` is already approved and available for this project; when the SOW and project "
    "language rules do not require a stricter runner, direct `python3 -E -S -B` or "
    "`py -3 -E -S -B` is "
    "acceptable for stdlib-only scripts after the project prerequisite check reports a supported "
    "interpreter and no errors. Any `uv` command that may create or update environments, download "
    "Python, resolve dependencies, or install packages is a state-changing step. Python source, "
    "packaging, typing, tests, or runtime changes route through `python_coding_quality`."
)
MINIMAL_DEFERRAL_DEFAULT_OWNER = "User"
MINIMAL_DEFERRAL_DEFAULT_REASON = "minimal bootstrap deferral"
MINIMAL_DEFERRAL_DEFAULT_BOUNDARY_TYPE = "event"
MINIMAL_DEFERRAL_CLOSURE_TEMPLATE = (
    "before the first task that depends on {field_name}, and no later than full bootstrap before "
    "implementation"
)
MINIMAL_DEFERRAL_ABSENT_VALUES = frozenset(
    {
        "",
        "n/a",
        "n.a",
        "na",
        "none",
        "not applicable",
        "not assigned",
        "not available",
        "not known",
        "pending",
        "tbd",
        "to be confirmed",
        "to be determined",
        "unassigned",
        "unknown",
        "unspecified",
    }
)
MINIMAL_DEFERRAL_GENERIC_TRIGGER_TARGETS = frozenset(
    {
        "event",
        "later",
        "milestone",
        "next event",
        "next milestone",
        "next task",
        "soon",
        "task",
        "work",
    }
)
_MINIMAL_DEFERRAL_PLACEHOLDER_PREFIX_RE = re.compile(
    r"^(?:tbd|to be (?:confirmed|determined)|replace(?:-with| with))(?:\b|$)",
    re.IGNORECASE,
)
_MINIMAL_DEFERRAL_NAMED_TRIGGER_RE = re.compile(
    r"^(?:after|at|before|by|no later than|once|upon|when)\s+(?P<trigger>\S(?:.*\S)?)$",
    re.IGNORECASE,
)


def minimal_deferral_value_is_absent_or_placeholder(value: object) -> bool:
    """Return whether a deferral fact is semantically absent or templated."""

    if not isinstance(value, str):
        return True
    stripped = value.strip()
    normalized = " ".join(stripped.casefold().split()).rstrip(" .:;-")
    return (
        normalized in MINIMAL_DEFERRAL_ABSENT_VALUES
        or bool(_MINIMAL_DEFERRAL_PLACEHOLDER_PREFIX_RE.match(stripped))
        or (stripped.startswith("[") and stripped.endswith("]"))
    )


def minimal_deferral_closure_boundary_error(
    boundary_type: str,
    closure_boundary: str,
    *,
    today: date | None = None,
) -> str | None:
    """Validate one objective date or named-trigger deferral boundary."""

    if minimal_deferral_value_is_absent_or_placeholder(closure_boundary):
        return "must be concrete, not absent or placeholder text"
    if boundary_type == "date":
        try:
            boundary_date = date.fromisoformat(closure_boundary)
        except ValueError:
            return "date boundary must be ISO YYYY-MM-DD"
        if boundary_date < (today or date.today()):
            return "date boundary has passed"
        return None
    if boundary_type not in {"event", "milestone"}:
        return None
    match = _MINIMAL_DEFERRAL_NAMED_TRIGGER_RE.fullmatch(closure_boundary.strip())
    if match is None:
        return (
            f"{boundary_type} boundary must name an exact trigger beginning with "
            "after, at, before, by, no later than, once, upon, or when"
        )
    trigger = " ".join(match.group("trigger").casefold().split()).rstrip(" .:;-")
    if trigger in MINIMAL_DEFERRAL_GENERIC_TRIGGER_TARGETS:
        return f"{boundary_type} boundary trigger is too generic: {trigger!r}"
    return None


MINIMAL_STACK_DEFERRAL = (
    "deferred by minimal bootstrap; inspect the repository or ask before stack-specific work"
)
MINIMAL_ARCHITECTURE_DEFERRAL = (
    "deferred by minimal bootstrap; inspect the repository or ask before architecture-specific work"
)
MINIMAL_IN_SCOPE_DEFERRAL = (
    "deferred by minimal bootstrap; inspect the repository or ask before expanding scope"
)
MINIMAL_OUT_OF_SCOPE_DEFERRAL = (
    "deferred by minimal bootstrap; treat unstated work as out of scope until confirmed"
)
MINIMAL_RUNTIME_STANDARDS_DEFERRAL = (
    "deferred by minimal bootstrap; verify before version-specific work"
)
MINIMAL_RECITALS_DEFERRAL = (
    "Project purpose deferred by minimal bootstrap; confirm it before purpose-dependent work."
)
SOW_OPTIONAL_DEFAULT_RULE = (
    "Only omitted optional governance terms fall back to framework defaults. Required project facts "
    "must be stated or represented by their canonical structured deferral in minimal mode; a bare "
    "TBD is not a substitute for a required structured deferral."
)
SOW_DEFINITION_INDEX_RULE = (
    "This section is a compact index of project terms. Dedicated sections below are authoritative "
    "for detailed command, workflow, source, memory, VCS, and verification policy."
)
PROJECT_PREAMBLE_RULE = (
    "This file contains only active runtime facts projected from STATEMENT_OF_WORK.md "
    "plus the non-authoritative framework-reference binding in Framework Verification."
)
PROJECT_OPTIONAL_OMISSION_RULE = (
    "Omit inactive optional sections and rows plus model-owned default Definition values. "
    "Retain every required core section, exact resolved or minimally deferred command row, "
    "non-default runtime fact, and structured minimal-mode deferral."
)

INDEPENDENT_ASSESSMENT_POLICY_LINES = (
    "Independent Assessment is an advisory review by a fresh agent for focused technical uncertainty "
    "before a dispute exists. It does not adjudicate a contested issue.",
)
REVIEWER_LANE_POLICY_LINES = (
    "Review topology is opt-in and risk-triggered. Live lane plans and execution follow "
    "task_orders/orchestrate.md.",
)
SOURCE_UPDATE_POLICY_LINES = (
    "Volatility Model: stable doctrine / version-sensitive implementation / high-volatility runtime "
    "or security surface / incident-triggered",
)
SOURCE_PACK_POLICY_LINES = (
    "Scope: project-approved source lists with tier, volatility, reviewed date, acquisition method, "
    "and action rule",
    "Boundary: source identity and source-use rules only; no copied documentation, transcripts, "
    "private source dumps, or maintenance notes",
)
FRAMEWORK_FEEDBACK_POLICY_LINES = (
    "Role: project-local queue of sanitized candidate improvements to the shared framework",
    "Boundary: feedback is private, untrusted evidence; raw project names, paths, logs, code, issue "
    "IDs, private URLs, identities, secrets, and proprietary context must not be copied into public "
    "framework files",
    "Promotion Rule: maintainer review must abstract, verify, approve, and implement any generalized "
    "framework change separately",
)
REVIEWER_FEEDBACK_POLICY_LINES = (
    "Role: project-local evidence about reviewer-lane use, skipped lanes, accepted/rejected reviewer "
    "findings, observed lane strengths, and observed lane limits",
    "Boundary: not a model leaderboard; not startup-loaded; raw logs, transcripts, screenshots, "
    "private paths, account data, secrets, and private writing profiles must not be used as primary "
    "evidence",
    "Promotion Rule: only sanitized reusable routing or verification lessons may become "
    "FRAMEWORK_FEEDBACK.md candidates",
)
SECURITY_VERIFICATION_POLICY_LINES = (
    "If Security Policy File is inline in this SOW, the Security Policy section contains the operative "
    "project terms. If it is none, no project-specific security policy is asserted. "
    "SECURITY_VERIFICATION.md defines verification procedures, not policy.",
)


def _definition(
    label: str,
    hint: str,
    surfaces: tuple[str, ...],
    *,
    projection: DefinitionProjection = "answer",
    answer_key: str | None = None,
    active_when: str | None = None,
    default: str | None = None,
    suffix: str = "",
    runtime_policy: RuntimeDefinitionPolicy = "always",
    runtime_owner: str | None = None,
    runtime_owner_inclusion: RuntimeOwnerInclusion | None = None,
    runtime_owner_style: RuntimeOwnerStyle | None = None,
) -> DefinitionSpec:
    return DefinitionSpec(
        label=label,
        hint=hint,
        surfaces=frozenset(surfaces),
        projection=projection,
        answer_key=answer_key,
        active_when=active_when,
        default=default,
        suffix=suffix,
        runtime_policy=runtime_policy,
        runtime_owner=runtime_owner,
        runtime_owner_inclusion=runtime_owner_inclusion,
        runtime_owner_style=runtime_owner_style,
    )


DEFINITION_SPECS = (
    _definition(
        "Agent",
        "selected coding runtime or agent",
        ("sow", "project"),
        answer_key="agent",
    ),
    _definition(
        "User",
        "project label; default User",
        ("sow",),
        answer_key="user",
        default="User",
    ),
    _definition(
        "Bootstrap Mode",
        "full or minimal",
        ("sow", "project"),
        projection="bootstrap-mode",
        answer_key="bootstrap_mode",
    ),
    _definition(
        "Execution Mode",
        "act / advise / ask-when-ambiguous",
        ("sow", "project"),
        answer_key="execution_posture",
        default="ask-when-ambiguous",
        suffix=EXECUTION_MODE_SUFFIX,
        runtime_policy="when-overridden",
    ),
    _definition(
        "Decision Boundary",
        "approved implementation discretion and explicit approval limits",
        ("sow", "project"),
        answer_key="decision_authority_grant",
        default=DEFAULT_DECISION_AUTHORITY_GRANT,
        runtime_policy="section-owned",
        runtime_owner="approval_boundaries",
        runtime_owner_inclusion="when-overridden",
        runtime_owner_style="labeled",
    ),
    _definition(
        "Dependency Rule",
        "no-external-dependencies / justify-external-dependencies",
        ("sow", "project"),
        answer_key="dependency_posture",
        default="justify-external-dependencies",
        suffix=DEPENDENCY_RULE_SUFFIX,
        runtime_policy="section-owned",
        runtime_owner="active_stack",
        runtime_owner_inclusion="when-overridden",
        runtime_owner_style="labeled",
    ),
    _definition(
        "External Source Rule",
        "independent implementation and approved license/attribution boundary",
        ("sow", "project"),
        answer_key="source_originality_policy",
        default=DEFAULT_SOURCE_ORIGINALITY_POLICY,
        runtime_policy="section-owned",
        runtime_owner="acquisition_boundary",
        runtime_owner_inclusion="when-overridden",
        runtime_owner_style="labeled",
    ),
    _definition(
        "Secret Store",
        "approved secret store or none required",
        ("sow", "project"),
        answer_key="secret_store",
        default="none required",
        runtime_policy="section-owned",
        runtime_owner="acquisition_boundary",
        runtime_owner_inclusion="when-overridden",
        runtime_owner_style="labeled",
    ),
    _definition(
        "Credential Delivery",
        "approved delivery mechanism or none",
        ("sow", "project"),
        answer_key="credential_delivery",
        default="none",
        runtime_policy="section-owned",
        runtime_owner="acquisition_boundary",
        runtime_owner_inclusion="when-overridden",
        runtime_owner_style="labeled",
    ),
    _definition(
        "Memory Boundary",
        "disabled or approved store/write/review/retention boundary",
        ("sow", "project"),
        answer_key="persistent_memory_boundary",
        default=DEFAULT_PERSISTENT_MEMORY_BOUNDARY,
        runtime_policy="section-owned",
        runtime_owner="memory_boundary",
        runtime_owner_inclusion="always",
        runtime_owner_style="native",
    ),
    _definition(
        "Source Freshness Rule",
        "primary-source and version-scope rule",
        ("sow", "project"),
        answer_key="source_freshness_policy",
        default=DEFAULT_SOURCE_FRESHNESS_POLICY,
        runtime_policy="section-owned",
        runtime_owner="acquisition_boundary",
        runtime_owner_inclusion="when-overridden",
        runtime_owner_style="labeled",
    ),
    _definition("Precedent File", "PRECEDENTS.md or none", ("sow", "project"), projection="optional-state", default="none", runtime_policy="state-owned"),
    _definition("Framework Feedback File", "FRAMEWORK_FEEDBACK.md or none", ("sow", "project"), projection="optional-state", default="none", runtime_policy="state-owned"),
    _definition("Reviewer Lane Feedback File", "REVIEWER_LANE_FEEDBACK.md or none", ("sow", "project"), projection="optional-state", default="none", runtime_policy="state-owned"),
    _definition("Source Packs File", "SOURCE_PACKS.md or none", ("sow", "project"), projection="optional-state", default="none", runtime_policy="state-owned"),
    _definition("Source Update File", "SOURCE_UPDATE.md or none", ("sow", "project"), projection="optional-state", default="none", runtime_policy="state-owned"),
    _definition("Source Monitor Researcher Brief", "SOURCE_MONITOR_RESEARCHER.md or none", ("sow", "project"), projection="optional-state", default="none", runtime_policy="state-owned"),
    _definition("Reviewer Lane Inventory", "private path / project-local file / none", ("sow", "project"), answer_key="reviewer_lane_inventory", default="none", runtime_policy="section-owned", runtime_owner="review_routing", runtime_owner_inclusion="when-overridden", runtime_owner_style="labeled"),
    _definition("Default Review Topology", "none or approved named profile", ("sow", "project"), answer_key="default_review_topology", default="none", runtime_policy="section-owned", runtime_owner="review_routing", runtime_owner_inclusion="when-overridden", runtime_owner_style="labeled"),
    _definition("Arbitration Panel", "framework default or custom package", ("sow", "project"), projection="arbitration-panel", default=DEFAULT_ARBITRATION_PANEL_PROJECTION, runtime_policy="canonical-only"),
    _definition("Direct Panel Rules", "none or compact direct-routing categories", ("sow", "project"), projection="direct-panel-rules", answer_key="direct_panel_rules", default="none", runtime_policy="section-owned", runtime_owner="review_routing", runtime_owner_inclusion="when-overridden", runtime_owner_style="labeled"),
    _definition("Independent Assessment Approval", "Required / Autonomous", ("sow", "project"), answer_key="independent_assessment_approval", default="Required", runtime_policy="section-owned", runtime_owner="review_routing", runtime_owner_inclusion="when-overridden", runtime_owner_style="labeled"),
    _definition("Standing Panel Convocation Approval", "No / Yes, limited to: ...", ("sow", "project"), answer_key="standing_panel_convocation_approval", default="No", runtime_policy="section-owned", runtime_owner="review_routing", runtime_owner_inclusion="when-overridden", runtime_owner_style="labeled"),
    _definition("Security Policy File", "none / project SECURITY.md / inline in this SOW", ("sow", "project"), answer_key="security_policy_file", default=DEFAULT_SECURITY_POLICY_FILE, runtime_policy="section-owned", runtime_owner="active_modules", runtime_owner_inclusion="when-overridden", runtime_owner_style="labeled"),
    _definition("Security Verification File", "SECURITY_VERIFICATION.md or none", ("sow", "project"), projection="optional-state", default="none", runtime_policy="state-owned"),
    _definition("Source Registry Scope", "active only with SOURCE_UPDATE.md", ("sow", "project"), answer_key="source_registry_scope", active_when="include_source_update", default=DEFAULT_SOURCE_REGISTRY_SCOPE, runtime_policy="state-owned"),
    _definition("Source Review Cadence", "active only with SOURCE_UPDATE.md", ("sow", "project"), answer_key="source_review_cadence", active_when="include_source_update", default=DEFAULT_SOURCE_REVIEW_CADENCE, runtime_policy="state-owned"),
    _definition("Source Monitor Role", "active only with SOURCE_MONITOR_RESEARCHER.md", ("sow", "project"), answer_key="source_monitor_role", active_when="include_source_monitor_researcher", default=DEFAULT_SOURCE_MONITOR_ROLE, runtime_policy="state-owned"),
    _definition("Source Monitor Instruction Sources", "active only with SOURCE_MONITOR_RESEARCHER.md", ("sow", "project"), projection="source-monitor-instruction-sources", answer_key="source_monitor_instruction_sources", active_when="include_source_monitor_researcher", default=DEFAULT_SOURCE_MONITOR_INSTRUCTION_SOURCES, runtime_policy="state-owned"),
    _definition("Source Monitor Source Data", "active only with SOURCE_MONITOR_RESEARCHER.md", ("sow", "project"), projection="source-monitor-source-data", answer_key="source_monitor_source_data", active_when="include_source_monitor_researcher", default="none", runtime_policy="state-owned"),
    _definition("Source Monitor Boundary", "active only with SOURCE_MONITOR_RESEARCHER.md", ("sow", "project"), answer_key="source_monitor_boundary", active_when="include_source_monitor_researcher", default=DEFAULT_SOURCE_MONITOR_BOUNDARY, runtime_policy="state-owned"),
    _definition("Security Verification Profile Scope", "active only with SECURITY_VERIFICATION.md", ("sow", "project"), answer_key="security_verification_profile_scope", active_when="include_security_verification", default=DEFAULT_SECURITY_VERIFICATION_PROFILE_SCOPE, runtime_policy="state-owned"),
    _definition("Security Verification Target Policy", "active only with SECURITY_VERIFICATION.md", ("sow", "project"), answer_key="security_verification_target_policy", active_when="include_security_verification", default=DEFAULT_SECURITY_VERIFICATION_TARGET_POLICY, runtime_policy="state-owned"),
    _definition("Automation Orders File", "AUTOMATION_ORDERS.json or none", ("sow", "project"), projection="optional-state", default="none", runtime_policy="state-owned"),
    _definition("Version Review Rule", "pinned-version review and upgrade-decision rule", ("sow", "project"), answer_key="version_review_policy", default=DEFAULT_VERSION_REVIEW_POLICY, runtime_policy="section-owned", runtime_owner="framework_verification", runtime_owner_inclusion="when-overridden", runtime_owner_style="labeled"),
    _definition("Critical Surface Rule", "classification and stronger-review rule", ("sow", "project"), answer_key="critical_surface_policy", default=DEFAULT_CRITICAL_SURFACE_POLICY, runtime_policy="section-owned", runtime_owner="critical_surfaces", runtime_owner_inclusion="when-overridden", runtime_owner_style="labeled"),
    _definition("Version Control Rule", "approved VCS posture", ("sow", "project"), answer_key="version_control_policy", default=DEFAULT_VERSION_CONTROL_POLICY, runtime_policy="section-owned", runtime_owner="version_control", runtime_owner_inclusion="when-overridden", runtime_owner_style="labeled"),
    _definition("Branch Rule", "current/default/protected branch posture", ("sow", "project"), answer_key="branch_policy", default=DEFAULT_BRANCH_POLICY, runtime_policy="section-owned", runtime_owner="version_control", runtime_owner_inclusion="when-overridden", runtime_owner_style="labeled"),
    _definition("Backout Rule", "reversible fix and destructive-action approval rule", ("sow", "project"), answer_key="backout_policy", default=DEFAULT_BACKOUT_POLICY, runtime_policy="section-owned", runtime_owner="version_control", runtime_owner_inclusion="when-overridden", runtime_owner_style="labeled"),
    _definition("Test Command", COMMAND_DEFINITION_POINTER, ("sow",), projection="command", default="none"),
    _definition("Lint Command", COMMAND_DEFINITION_POINTER, ("sow",), projection="command", default="none"),
    _definition("Type Check Command", COMMAND_DEFINITION_POINTER, ("sow",), projection="command", default="none"),
    _definition("Framework Verification Runner", "exact qualified runner established by the successful prerequisite diagnostic", ("sow", "project"), answer_key="framework_verification_runner", default=FRAMEWORK_VERIFICATION_RUNNER_PLACEHOLDER, runtime_policy="section-owned", runtime_owner="framework_verification", runtime_owner_inclusion="always", runtime_owner_style="native"),
    _definition("Package Manager", "approved tool or none", ("sow", "project"), answer_key="package_manager", default="none", runtime_policy="section-owned", runtime_owner="active_stack", runtime_owner_inclusion="when-overridden", runtime_owner_style="labeled"),
    _definition("Language/Runtime Standards", "version, edition, SDK/target, dialect, and pin status", ("sow", "project"), projection="runtime-standards", answer_key="language_runtime_standards", runtime_policy="section-owned", runtime_owner="active_stack", runtime_owner_inclusion="always", runtime_owner_style="labeled"),
    _definition("AI Disclosure", "none or required wording/location", ("sow", "project"), answer_key="ai_disclosure", default="none", runtime_policy="section-owned", runtime_owner="constraints", runtime_owner_inclusion="when-overridden", runtime_owner_style="labeled"),
)

SOW_DEFINITION_SPECS = tuple(
    spec for spec in DEFINITION_SPECS if "sow" in spec.surfaces
)
PROJECT_DEFINITION_SPECS = tuple(
    spec for spec in DEFINITION_SPECS if "project" in spec.surfaces
)
DEFINITIONS_BY_LABEL = {spec.label: spec for spec in DEFINITION_SPECS}
PROJECTED_DEFINITION_FIELDS = tuple(
    spec.label
    for spec in DEFINITION_SPECS
    if spec.surfaces == frozenset({"sow", "project"})
)
FIELD_MAP = {label: label for label in PROJECTED_DEFINITION_FIELDS}


def _normalized_definition_value(value: str) -> str:
    return " ".join(value.casefold().split())


def rendered_definition_default(spec: DefinitionSpec) -> str | None:
    """Return the concrete default representation used by Definition rendering."""

    if spec.default is None:
        return None
    return spec.default + spec.suffix


def runtime_definition_included(
    spec: DefinitionSpec,
    value: str | None,
    *,
    active_when_enabled: bool,
) -> bool:
    """Decide runtime Definition presence from model policy and canonical value."""

    if "project" not in spec.surfaces or value is None:
        return False
    if spec.runtime_policy in {"section-owned", "state-owned", "canonical-only"}:
        return False
    if spec.runtime_policy == "when-active":
        return active_when_enabled
    if spec.runtime_policy == "when-overridden":
        default = rendered_definition_default(spec)
        return default is not None and _normalized_definition_value(
            value
        ) != _normalized_definition_value(default)
    if spec.runtime_policy == "always":
        return True
    raise ValueError(
        f"Definition {spec.label!r} uses unknown runtime policy {spec.runtime_policy!r}"
    )


def runtime_owned_definition_included(
    spec: DefinitionSpec,
    value: str | None,
    *,
    active_when_enabled: bool,
) -> bool:
    """Decide whether a section-owned fact needs one labeled runtime row."""

    if (
        spec.runtime_policy != "section-owned"
        or spec.runtime_owner_style != "labeled"
        or value is None
    ):
        return False
    if spec.runtime_owner_inclusion == "always":
        return True
    if spec.runtime_owner_inclusion == "when-active":
        return active_when_enabled
    if spec.runtime_owner_inclusion == "when-overridden":
        default = rendered_definition_default(spec)
        return default is not None and _normalized_definition_value(
            value
        ) != _normalized_definition_value(default)
    raise ValueError(
        f"Definition {spec.label!r} has no valid section-owner inclusion policy"
    )


def runtime_definition_activation_enabled(
    spec: DefinitionSpec,
    definitions: Mapping[str, str],
) -> bool:
    """Resolve a conditional runtime Definition from its canonical owner row."""

    if spec.active_when is None:
        return True
    owner_label = OPTIONAL_STATE_DEFINITION_BY_FLAG.get(spec.active_when)
    if owner_label is None:
        return False
    owner_spec = DEFINITIONS_BY_LABEL.get(owner_label)
    if owner_spec is None:
        return False
    owner_value = definitions.get(owner_label)
    owner_default = rendered_definition_default(owner_spec)
    return (
        owner_value is not None
        and owner_default is not None
        and _normalized_definition_value(owner_value)
        != _normalized_definition_value(owner_default)
    )

PROJECT_AUTHORITY_TEXT = (
    "Authority: Generated projection, not independent authority. `STATEMENT_OF_WORK.md` "
    "governs conflicting project terms. Never hand-edit this file."
)
PROJECT_LOADING_RULE_OPERATIVE_LINES = (
    "- After context compaction, restart, or handoff, reload this file from disk; do not rely on summaries.",
    "- Resolve Active Project Modules references from the project root. Load Scope of Authority before any action and each other listed module before work governed by its subject; after compaction, restart, or handoff, reload applicable modules before resuming that work.",
    "- Active Workflows, Auxiliary Tools, Review Routing, and Canonical Detail Routes are indexes, not complete procedures. Before executing a workflow, invoking a tool, convening custom review, or using routed canonical detail, load the same-named STATEMENT_OF_WORK.md entry.",
    "- If this file conflicts with STATEMENT_OF_WORK.md, the SOW governs; stop relying on the conflicting projection. Diagnose and correct a generated contract, framework-reference binding, or generated optional-state lifecycle only through the selected framework's `task_orders/framework_refresh.md` route; never hand-edit managed projections or add or retire generated state ad hoc.",
    "- Preserve the exact framework-generated origin marker when editing receipt-declared mutable state.",
    "- Keep project-specific rules in this contract rather than growing the runtime entrypoint unless that entrypoint itself must carry the rule.",
)
PROJECT_LOADING_RULE_AUTHOR_GUIDANCE = (
    "- Delete unused sections, leave no placeholder prose, and keep the concrete contract factual and short.",
    "- Record auxiliary-integration facts only to the bounded purpose, reference, capability, permission, provenance, credential, data, effect, persistence, trust, approval, version, audit, rollback, and control-coverage surfaces that apply.",
    "- Record source-freshness facts as source, version or date scope, and approved acquisition method; do not copy documentation into the contract.",
    "- Keep Project Vocabulary to terms that reduce operational ambiguity; do not turn it into an implementation specification.",
    "- Keep scope and critical-surface facts explicit; represent unresolved minimal-mode facts as structured deferrals rather than placeholder Definitions.",
    "- Keep active VCS, release, rollback, and memory-boundary facts concise; detailed history and standing policy remain in their owning project surfaces.",
)
PROJECT_LOADING_RULE_LINES = PROJECT_LOADING_RULE_OPERATIVE_LINES
ARBITRATION_PANEL_RUNTIME_ROUTE = (
    "Arbitration Panel: load STATEMENT_OF_WORK.md Arbitration Panel before panel use"
)
CANONICAL_DETAIL_RUNTIME_ROUTES: Mapping[str, str] = {
    "file_structure": (
        "File Structure: load STATEMENT_OF_WORK.md Technical Specifications "
        "before structural or path-topology work"
    ),
    "pattern_sources": (
        "Pattern Sources: load STATEMENT_OF_WORK.md Representative Pattern Sources "
        "before pattern-guided implementation"
    ),
    "code_review_checklist": (
        "Code Review Checklist: load STATEMENT_OF_WORK.md Code Review Checklist "
        "before code review"
    ),
}
ANNEX_CONFLICT_RULE = (
    "Referenced annexes are incorporated into this SOW. Explicit SOW body text governs "
    "conflicts among project-specific terms unless it expressly delegates the matter to an annex. "
    "Annexes cannot override non-delegable MSA duties."
)
AUTOMATION_AUTHORITY_RULE = (
    "This section declares project automation configuration; it does not itself authorize "
    "execution, external effects, or standing grants. Live automation remains governed by "
    "the active task order, approval mode, and validated AUTOMATION_ORDERS.json manifest."
)


def render_command_restriction(
    command: str,
    reason: str,
    alternative: str,
) -> str:
    """Render the canonical command-restriction contract row."""

    return render_command_restriction_record(
        {
            "command": command,
            "reason": reason,
            "alternative": alternative,
        }
    )


def render_command_restriction_record(item: Mapping[str, object]) -> str:
    """Render one accepted command-restriction record through its field specs."""

    return render_structured_record("command_restrictions", item)


SOW_SECTION_SPECS = (
    SectionSpec(
        "arbitration_panel",
        "Arbitration Panel",
        ("_Delete if framework defaults apply._", "Seat 1: [model] — [role] — [focus]", "Quorum: [exact rule]", "Recommendation threshold: [exact rule]", "Failure handling: [exact rule]", "Tie handling: [exact rule]", "No-majority handling: [exact rule]", "Abstention handling: [exact rule]", "Unavailable-panelist handling: [exact rule]", "Binding effect: [recommendation or delegated authority]", "Ratification or accountable owner: [owner]", "Appeal or override path: [exact rule]"),
        sow_row_style="arbitration-panel",
    ),
    SectionSpec(
        "direct_panel_rules",
        "Direct Panel Rules",
        ("_Delete if no categories route directly to panel._", "- [dispute category]", "Standing Panel Convocation Approval: [No / Yes, limited to: ...]"),
        sow_row_style="direct-panel-rules",
    ),
    SectionSpec(
        "independent_assessment",
        "Independent Assessment",
        (
            "_Delete to use the framework default._",
            *INDEPENDENT_ASSESSMENT_POLICY_LINES,
            "Independent Assessment Approval: [Required / Autonomous]",
        ),
        INDEPENDENT_ASSESSMENT_POLICY_LINES,
        "labeled",
    ),
    SectionSpec("recitals", "Recitals", ("[What the project is, what it does, and who it serves.]",), sow_row_style="free-form"),
    SectionSpec("project_vocabulary", "Project Vocabulary", ("- [term] — [project meaning] — [aliases or ambiguity to avoid]",), sow_row_style="bullet"),
    SectionSpec("scope", "Scope", ("In scope:", "- [approved work]", "", "Out of scope:", "- [excluded work]"), sow_row_style="scope"),
    SectionSpec("minimal_deferrals", "Minimal Bootstrap Deferrals", ("_Use only in minimal mode._", "- Field: [canonical field] — Owner: [owner] — Reason: [reason] — Boundary Type: [date | milestone | event] — Closure Boundary: [boundary]."), sow_row_style="bullet"),
    SectionSpec("technical_specifications", "Technical Specifications", ("Tech stack: [active stack]", "", "Architecture: [active architecture]", "", "Key dependencies: [dependencies or none]", "", "Key directories: [directories or none]", "", "File structure:", "[operationally relevant paths]"), sow_row_style="technical-specifications"),
    SectionSpec("pattern_sources", "Representative Pattern Sources", ("- [path or reference] — [represented pattern] — [normative / illustrative]",), sow_row_style="bullet"),
    SectionSpec("deliverables", "Deliverables and Acceptance Tests", ("1. [deliverable] — [verification] — [pass criteria]",), sow_row_style="numbered"),
    SectionSpec("acceptance_checklist", "Acceptance Checklist (per deliverable)", ("- [ ] [objective or explicitly manual acceptance criterion]",), sow_row_style="bullet"),
    SectionSpec("constraints", "Project-Specific Constraints", ("- [project-specific constraint]",), sow_row_style="bullet"),
    SectionSpec("critical_surfaces", "Critical Surfaces", ("- [path / workflow / boundary] — [risk] — [review burden]",), sow_row_style="bullet"),
    SectionSpec("version_control_profile", "Version Control Profile", ("- [VCS/forge/branch/staging/commit/PR/release fact] — [policy or evidence]",), sow_row_style="bullet"),
    SectionSpec("memory_boundary", "Memory Boundary", ("- [store/path/service] — [write authority] — [review/retention/backout]",), sow_row_style="bullet"),
    SectionSpec("verification_profiles", "Verification Profiles", ("- [profile] — [checks] — [trigger]",), sow_row_style="bullet"),
    SectionSpec("approval_boundaries", "Approval Boundaries", ("- [action requiring approval]",), sow_row_style="bullet"),
    SectionSpec("acquisition_boundary", "Information Acquisition Boundary", ("- [approved sources, acquisition method, egress, credentials, and data boundary]",), sow_row_style="bullet"),
    SectionSpec(
        "commands",
        "Build and Development Commands",
        tuple(
            f"[{spec.answer_key.replace('_', '-')} command] — {spec.sow_label}"
            for spec in COMMAND_SPECS
        ),
        sow_row_style="commands",
    ),
    SectionSpec("auxiliary_tools", "Auxiliary Tools", ("1. [integration] — [purpose] — [canonical reference] — [owner/transport/capability/permissions/credentials/data/effect/persistence/trust/approval/version/control-role facts]",), sow_row_style="numbered"),
    SectionSpec(
        "reviewer_lanes",
        "Reviewer Lanes",
        (
            "Reviewer Lane Inventory: [private path / project-local file / none]",
            "Default Review Topology: [none / named profile]",
            *REVIEWER_LANE_POLICY_LINES,
        ),
        REVIEWER_LANE_POLICY_LINES,
        "labeled",
    ),
    SectionSpec(
        "command_restrictions",
        "Command Restrictions",
        (render_command_restriction("[command]", "[reason]", "[alternative]"),),
        sow_row_style="command-restrictions",
    ),
    SectionSpec("applicable_standards", "Applicable Standards", ("- [project-specific standard and version/date scope]",), sow_row_style="bullet"),
    SectionSpec("language_rules", "Language-Specific Rules", ("- [language or stack] — [project rule] — [verification]",), sow_row_style="bullet"),
    SectionSpec("code_review", "Code Review Checklist", ("1. [project-specific review criterion]",), sow_row_style="numbered"),
    SectionSpec(
        "workflows",
        "Workflows",
        ("`[name]`: sequence: [sequence] — when: [trigger] — [active controls]",),
        sow_row_style="workflows",
    ),
    SectionSpec(
        "automation",
        "Standing Automation Orders",
        ("Automation Orders File: [AUTOMATION_ORDERS.json or none]", "Preferred Scheduler Backend: [approved backend]", "[job id]: [objective] — [schedule] — [autonomy] — [approval mode]", AUTOMATION_AUTHORITY_RULE),
        (AUTOMATION_AUTHORITY_RULE,),
        "automation",
    ),
    SectionSpec(
        "source_update",
        "Source Update Plan",
        (
            "Source Packs File: [SOURCE_PACKS.md or none]",
            "Source Update File: [SOURCE_UPDATE.md or none]",
            "Source Registry Scope: [approved scope]",
            "Shared Framework Source Reference: [reference or none]",
            "Default Review Cadence: [project-owned trigger or cadence]",
            *SOURCE_UPDATE_POLICY_LINES,
        ),
        SOURCE_UPDATE_POLICY_LINES,
        "labeled",
    ),
    SectionSpec(
        "source_packs",
        "Source Packs",
        (
            "Source Packs File: [SOURCE_PACKS.md or none]",
            SOURCE_PACK_POLICY_LINES[0],
            "Shared Framework Source Reference: [reference or none]",
            SOURCE_PACK_POLICY_LINES[1],
        ),
        SOURCE_PACK_POLICY_LINES,
        "labeled",
    ),
    SectionSpec("source_monitor", "Source Monitor Researcher Brief", ("Source Monitor Researcher File: [SOURCE_MONITOR_RESEARCHER.md or none]", "Role: [observe-only role]", "Instruction Sources: [approved instruction sources]", "Source Data: [declared project source files or none]", "Boundary: [no unapproved edits or external effects]"), sow_row_style="labeled"),
    SectionSpec(
        "framework_feedback",
        "Framework Feedback",
        (
            "Framework Feedback File: [FRAMEWORK_FEEDBACK.md or none]",
            *FRAMEWORK_FEEDBACK_POLICY_LINES,
        ),
        FRAMEWORK_FEEDBACK_POLICY_LINES,
        "labeled",
    ),
    SectionSpec(
        "reviewer_feedback",
        "Reviewer Lane Feedback",
        (
            "Reviewer Lane Feedback File: [REVIEWER_LANE_FEEDBACK.md or none]",
            *REVIEWER_FEEDBACK_POLICY_LINES,
        ),
        REVIEWER_FEEDBACK_POLICY_LINES,
        "labeled",
    ),
    SectionSpec("security_policy", "Security Policy", ("_Use only when Security Policy File is inline in this SOW._", "- [project-specific security policy term]"), sow_row_style="bullet"),
    SectionSpec(
        "security_verification",
        "Security Verification Plan",
        (
            "Security Policy File: [none / project SECURITY.md / inline in this SOW]",
            "Security Verification File: [SECURITY_VERIFICATION.md or none]",
            *SECURITY_VERIFICATION_POLICY_LINES,
            "Profile Scope: [approved checks]",
            "Default Target Policy: [approved targets]",
        ),
        SECURITY_VERIFICATION_POLICY_LINES,
        "labeled",
    ),
    SectionSpec(
        "annexes",
        "Annexes",
        (
            ANNEX_CONFLICT_RULE,
            "- Annex A — Agent Profile (SOUL.md): [existing project-relative file]",
            "- Annex B — Agent Qualifications (CAPABILITIES.md): [existing project-relative file]",
            "- Annex C — Scope of Authority (AUTHORITY.md): [existing project-relative file]",
            "- Annex D — Security Policy (SECURITY.md): [generated from Security Policy File; do not configure through annexes]",
        ),
        (ANNEX_CONFLICT_RULE,),
        "policy-bullet",
    ),
)
SOW_SECTIONS = {spec.key: spec for spec in SOW_SECTION_SPECS}
SOW_SECTION_TITLES = frozenset(spec.title for spec in SOW_SECTION_SPECS)
SOW_SECTION_ROW_STYLES = {
    spec.key: spec.sow_row_style
    for spec in SOW_SECTION_SPECS
    if spec.sow_row_style is not None
}
SOW_LABELED_FIELD_SPECS = (
    SowLabeledFieldSpec(
        "independent_assessment",
        "Independent Assessment Approval",
        "definition-parity",
        "Independent Assessment Approval",
        section_absence="use-definition-default",
    ),
    SowLabeledFieldSpec(
        "reviewer_lanes",
        "Reviewer Lane Inventory",
        "definition-parity",
        "Reviewer Lane Inventory",
    ),
    SowLabeledFieldSpec(
        "reviewer_lanes",
        "Default Review Topology",
        "definition-parity",
        "Default Review Topology",
    ),
    SowLabeledFieldSpec(
        "source_update",
        "Source Packs File",
        "definition-parity",
        "Source Packs File",
        comparison="exact",
        section_absence="ignore",
    ),
    SowLabeledFieldSpec(
        "source_update",
        "Source Update File",
        "definition-parity",
        "Source Update File",
        comparison="exact",
    ),
    SowLabeledFieldSpec(
        "source_update",
        "Source Registry Scope",
        "definition-parity",
        "Source Registry Scope",
    ),
    SowLabeledFieldSpec(
        "source_update",
        "Shared Framework Source Reference",
        "shared-source-reference",
    ),
    SowLabeledFieldSpec(
        "source_update",
        "Default Review Cadence",
        "definition-parity",
        "Source Review Cadence",
    ),
    SowLabeledFieldSpec(
        "source_packs",
        "Source Packs File",
        "definition-parity",
        "Source Packs File",
        comparison="exact",
    ),
    SowLabeledFieldSpec(
        "source_packs",
        "Shared Framework Source Reference",
        "shared-source-reference",
    ),
    SowLabeledFieldSpec(
        "source_monitor",
        "Source Monitor Researcher File",
        "definition-parity",
        "Source Monitor Researcher Brief",
        comparison="exact",
    ),
    SowLabeledFieldSpec(
        "source_monitor",
        "Role",
        "definition-parity",
        "Source Monitor Role",
    ),
    SowLabeledFieldSpec(
        "source_monitor",
        "Instruction Sources",
        "definition-parity",
        "Source Monitor Instruction Sources",
    ),
    SowLabeledFieldSpec(
        "source_monitor",
        "Source Data",
        "definition-parity",
        "Source Monitor Source Data",
    ),
    SowLabeledFieldSpec(
        "source_monitor",
        "Boundary",
        "definition-parity",
        "Source Monitor Boundary",
    ),
    SowLabeledFieldSpec(
        "framework_feedback",
        "Framework Feedback File",
        "definition-parity",
        "Framework Feedback File",
        comparison="exact",
    ),
    SowLabeledFieldSpec(
        "reviewer_feedback",
        "Reviewer Lane Feedback File",
        "definition-parity",
        "Reviewer Lane Feedback File",
        comparison="exact",
    ),
    SowLabeledFieldSpec(
        "security_verification",
        "Security Policy File",
        "definition-parity",
        "Security Policy File",
        section_absence="ignore",
    ),
    SowLabeledFieldSpec(
        "security_verification",
        "Security Verification File",
        "definition-parity",
        "Security Verification File",
        comparison="exact",
    ),
    SowLabeledFieldSpec(
        "security_verification",
        "Profile Scope",
        "definition-parity",
        "Security Verification Profile Scope",
    ),
    SowLabeledFieldSpec(
        "security_verification",
        "Default Target Policy",
        "definition-parity",
        "Security Verification Target Policy",
    ),
)
STATE_DEFINITION_PROJECTION_SPECS = (
    StateDefinitionProjectionSpec(
        "source_update",
        "SOURCE_UPDATE.md",
        "Update Policy",
        "Source Registry Scope",
        "Source Registry Scope",
    ),
    StateDefinitionProjectionSpec(
        "source_update",
        "SOURCE_UPDATE.md",
        "Update Policy",
        "Default Review Cadence",
        "Source Review Cadence",
    ),
    StateDefinitionProjectionSpec(
        "source_update",
        "SOURCE_UPDATE.md",
        "Update Policy",
        "Version Review Rule",
        "Version Review Rule",
    ),
    StateDefinitionProjectionSpec(
        "source_monitor",
        "SOURCE_MONITOR_RESEARCHER.md",
        "Project Configuration",
        "Role",
        "Source Monitor Role",
    ),
    StateDefinitionProjectionSpec(
        "source_monitor",
        "SOURCE_MONITOR_RESEARCHER.md",
        "Project Configuration",
        "Delegated-Run Instruction Sources",
        "Source Monitor Instruction Sources",
    ),
    StateDefinitionProjectionSpec(
        "source_monitor",
        "SOURCE_MONITOR_RESEARCHER.md",
        "Project Configuration",
        "Source Data",
        "Source Monitor Source Data",
    ),
    StateDefinitionProjectionSpec(
        "source_monitor",
        "SOURCE_MONITOR_RESEARCHER.md",
        "Project Configuration",
        "Boundary",
        "Source Monitor Boundary",
    ),
    StateDefinitionProjectionSpec(
        "security_verification",
        "SECURITY_VERIFICATION.md",
        "Scope",
        "Profile Scope",
        "Security Verification Profile Scope",
    ),
    StateDefinitionProjectionSpec(
        "security_verification",
        "SECURITY_VERIFICATION.md",
        "Authorization Boundaries",
        "Default Target Policy",
        "Security Verification Target Policy",
    ),
)
STATE_TEMPLATE_PLACEHOLDER_SPECS = (
    StateTemplatePlaceholderSpec(
        "SOURCE_UPDATE.md",
        "{{SOURCE_REGISTRY_SCOPE}}",
        "definition-parity",
        "Source Registry Scope",
    ),
    StateTemplatePlaceholderSpec(
        "SOURCE_UPDATE.md",
        "{{SOURCE_REVIEW_CADENCE}}",
        "definition-parity",
        "Source Review Cadence",
    ),
    StateTemplatePlaceholderSpec(
        "SOURCE_UPDATE.md",
        "{{VERSION_REVIEW_RULE}}",
        "definition-parity",
        "Version Review Rule",
    ),
    StateTemplatePlaceholderSpec(
        "SECURITY_VERIFICATION.md",
        "{{SECURITY_VERIFICATION_PROFILE_SCOPE}}",
        "definition-parity",
        "Security Verification Profile Scope",
    ),
    StateTemplatePlaceholderSpec(
        "SECURITY_VERIFICATION.md",
        "{{SECURITY_VERIFICATION_TARGET_POLICY}}",
        "definition-parity",
        "Security Verification Target Policy",
    ),
    StateTemplatePlaceholderSpec(
        "SOURCE_PACKS.md",
        "{{SHARED_FRAMEWORK_SOURCE_REFERENCE}}",
        "shared-source-reference",
    ),
    StateTemplatePlaceholderSpec(
        "SOURCE_MONITOR_RESEARCHER.md",
        "{{SOURCE_MONITOR_ROLE}}",
        "definition-parity",
        "Source Monitor Role",
    ),
    StateTemplatePlaceholderSpec(
        "SOURCE_MONITOR_RESEARCHER.md",
        "{{SOURCE_MONITOR_INSTRUCTION_SOURCES}}",
        "definition-parity",
        "Source Monitor Instruction Sources",
    ),
    StateTemplatePlaceholderSpec(
        "SOURCE_MONITOR_RESEARCHER.md",
        "{{SOURCE_MONITOR_SOURCE_DATA}}",
        "definition-parity",
        "Source Monitor Source Data",
    ),
    StateTemplatePlaceholderSpec(
        "SOURCE_MONITOR_RESEARCHER.md",
        "{{SOURCE_MONITOR_BOUNDARY}}",
        "definition-parity",
        "Source Monitor Boundary",
    ),
    StateTemplatePlaceholderSpec(
        "SOURCE_MONITOR_RESEARCHER.md",
        "{{FRAMEWORK_ROOT}}",
        "framework-reference",
    ),
    StateTemplatePlaceholderSpec(
        "SOURCE_MONITOR_RESEARCHER.md",
        "{{SOURCE_MONITOR_ARTIFACT_LINT_COMMAND}}",
        "source-monitor-verification-command",
    ),
)
STATE_TEMPLATE_PLACEHOLDER_RE = re.compile(r"\{\{[A-Z0-9_]+\}\}")
SOURCE_MONITOR_ARTIFACT_LINT_RELATIVE_PATH = (
    "scripts/source_chain_artifact_lint.py"
)
SOURCE_MONITOR_ARTIFACT_LINT_ARGUMENTS = (
    "--project-root [selected project root] --stage monitor "
    "--expected-model-route [route-id from the owning trigger authority] "
    "--expected-timezone [IANA timezone from the owning trigger authority] "
    "--verify-current-input-hashes [artifact]"
)


def source_monitor_artifact_lint_command(
    runner: str,
    framework_reference: str,
) -> str:
    """Render the one model-owned monitor handoff command exactly."""

    if framework_reference == "{{FRAMEWORK_ROOT}}":
        script = (
            f'"{{{{FRAMEWORK_ROOT}}}}/{SOURCE_MONITOR_ARTIFACT_LINT_RELATIVE_PATH}"'
        )
    else:
        script = safe_paths.shell_framework_path_token(
            framework_reference,
            SOURCE_MONITOR_ARTIFACT_LINT_RELATIVE_PATH,
        )
    return f"{runner} -- {script} {SOURCE_MONITOR_ARTIFACT_LINT_ARGUMENTS}"


def state_template_source_path(filename: str) -> str:
    """Return the concrete template used to create one generated state file."""

    return BOOTSTRAP_STATE_TEMPLATES.get(filename, STATE_TEMPLATES[filename])


def source_monitor_framework_reference_lines(
    framework_reference: str,
    *,
    root: Path = REPO_ROOT,
) -> tuple[str, ...]:
    """Render exact model-owned SOURCE_MONITOR_RESEARCHER framework-ref lines."""

    template = (root / state_template_source_path("SOURCE_MONITOR_RESEARCHER.md")).read_text(
        encoding="utf-8"
    )
    return tuple(
        safe_paths.render_framework_reference_tokens(line, framework_reference)
        for line in template.splitlines()
        if "{{FRAMEWORK_ROOT}}" in line
    )


def state_template_placeholder_errors(
    specs: tuple[StateTemplatePlaceholderSpec, ...] = STATE_TEMPLATE_PLACEHOLDER_SPECS,
    *,
    root: Path = REPO_ROOT,
) -> list[str]:
    """Prove every dynamic generated-state placeholder has one semantic owner."""

    errors: list[str] = []
    declared = [(spec.filename, spec.placeholder) for spec in specs]
    duplicate_declarations = sorted(
        {item for item in declared if declared.count(item) > 1}
    )
    if duplicate_declarations:
        errors.append(
            "state-template placeholder owners contain duplicate declarations: "
            f"{duplicate_declarations}"
        )

    observed: set[tuple[str, str]] = set()
    for filename in STATE_TEMPLATES:
        template_path = root / state_template_source_path(filename)
        try:
            text = template_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            errors.append(
                f"state template placeholder inventory could not read {template_path}: {exc}"
            )
            continue
        observed.update(
            (filename, placeholder)
            for placeholder in STATE_TEMPLATE_PLACEHOLDER_RE.findall(text)
        )

    declared_set = set(declared)
    missing = sorted(observed - declared_set)
    unknown = sorted(declared_set - observed)
    if missing:
        errors.append(
            f"state-template placeholders missing semantic owners: {missing}"
        )
    if unknown:
        errors.append(
            f"state-template placeholder owners name absent placeholders: {unknown}"
        )

    for spec in specs:
        if spec.filename not in STATE_TEMPLATES:
            errors.append(
                f"state-template placeholder owner names unknown file: {spec.filename}"
            )
        if STATE_TEMPLATE_PLACEHOLDER_RE.fullmatch(spec.placeholder) is None:
            errors.append(
                "state-template placeholder owner uses malformed identity: "
                f"{spec.filename}:{spec.placeholder}"
            )
        if spec.semantic_owner == "definition-parity":
            if spec.definition_label not in DEFINITIONS_BY_LABEL:
                errors.append(
                    "state-template Definition owner names unknown Definition: "
                    f"{spec.filename}:{spec.placeholder} -> {spec.definition_label!r}"
                )
        elif spec.definition_label is not None:
            errors.append(
                "non-Definition state-template placeholder owner must not name a "
                f"Definition: {spec.filename}:{spec.placeholder}"
            )
        if spec.semantic_owner not in {
            "definition-parity",
            "framework-reference",
            "shared-source-reference",
            "source-monitor-verification-command",
        }:
            errors.append(
                "state-template placeholder uses unknown semantic owner: "
                f"{spec.filename}:{spec.placeholder} -> {spec.semantic_owner!r}"
            )
    return errors

SOW_SCALAR_SECTION_TITLES = frozenset(
    spec.title
    for spec in SOW_SECTION_SPECS
    if spec.sow_row_style
    in {"arbitration-panel", "automation", "direct-panel-rules", "labeled"}
)
SOW_FREE_FORM_SECTION_KEYS = frozenset(
    spec.key
    for spec in SOW_SECTION_SPECS
    if spec.sow_row_style == "free-form"
)
SOW_PLAIN_STRUCTURAL_TITLES = SOW_SECTION_TITLES | {"Definitions"}
SOW_IDENTITY_ROW_SYNTAX = (
    ("SOW Version:", r"SOW Version:"),
    ("Statement of Work —", r"Statement of Work\s+[—-](?:\s|$)"),
)
SOW_WORKFLOW_IDENTITY_ROW_SYNTAX = (
    ("SOW Version:", r"SOW Version(?::|$)"),
    SOW_IDENTITY_ROW_SYNTAX[1],
)
ANSWER_TEXT_GRAMMAR_SPECS = (
    AnswerTextGrammarSpec(
        "direct_panel_rules",
        forbidden_exact_lines=SOW_PLAIN_STRUCTURAL_TITLES,
    ),
    AnswerTextGrammarSpec(
        "file_structure",
        forbidden_exact_lines=SOW_PLAIN_STRUCTURAL_TITLES,
        forbidden_line_syntax=SOW_IDENTITY_ROW_SYNTAX,
    ),
    AnswerTextGrammarSpec(
        "recitals",
        forbidden_exact_lines=SOW_PLAIN_STRUCTURAL_TITLES,
        forbidden_line_syntax=SOW_IDENTITY_ROW_SYNTAX,
    ),
    AnswerTextGrammarSpec(
        "commands",
        member_keys=COMMAND_KEYS,
        forbidden_line_syntax=SOW_IDENTITY_ROW_SYNTAX,
    ),
    AnswerTextGrammarSpec(
        "command_restrictions",
        member_keys=frozenset({"command"}),
        forbidden_line_syntax=SOW_IDENTITY_ROW_SYNTAX,
    ),
    AnswerTextGrammarSpec(
        "workflows",
        member_keys=frozenset({"name"}),
        forbidden_line_syntax=SOW_WORKFLOW_IDENTITY_ROW_SYNTAX,
    ),
    AnswerTextGrammarSpec(
        "sow_version",
        forbidden_substrings=("Date:", "MSA Reference:"),
    ),
)
ANSWER_TEXT_GRAMMAR_BY_KEY = {
    spec.answer_key: spec for spec in ANSWER_TEXT_GRAMMAR_SPECS
}

PROJECT_SECTION_SPECS = (
    SectionSpec("active_stack", "Active Stack", ("- Languages and frameworks: [active stack]", "- Architecture: [active architecture]", "- Key dependencies: [only when active]", "- Key directories: [only when operationally relevant]")),
    SectionSpec(
        "active_modules",
        "Active Project Modules",
        (
            "- Annex A — Agent Profile (SOUL.md): [existing project-relative file]",
            "- Annex B — Agent Qualifications (CAPABILITIES.md): [existing project-relative file]",
            "- Annex C — Scope of Authority (AUTHORITY.md): [existing project-relative file]",
            "- Annex D — Security Policy (SECURITY.md): [derived from Security Policy File]",
        ),
    ),
    SectionSpec("project_vocabulary", "Project Vocabulary", ("- [term] — [project meaning] — [ambiguity to avoid]",)),
    SectionSpec("common_commands", "Common Commands", ("- Development: [command or none]", "- Build: [command or none]", "- Regenerate artifacts: [command or none]", "- Test: [command or none]", "- Lint: [command or none]", "- Type check: [command or none]", "- Deploy: [command or none]")),
    SectionSpec("framework_verification", "Framework Verification Commands", ("{FRAMEWORK_VERIFICATION_COMMANDS}",)),
    SectionSpec("active_deliverables", "Active Deliverables", ("1. [deliverable] — [verification] — [pass criteria]",)),
    SectionSpec("acceptance_checklist", "Acceptance Checklist", ("- [ ] [objective or explicitly manual acceptance criterion]",)),
    SectionSpec("active_scope", "Active Scope", ("In scope:", "- [active scope]", "", "Out of scope:", "- [active exclusions]")),
    SectionSpec("active_workflows", "Active Workflows", ("- [name]: load the same-named SOW Workflows entry when [trigger] — [active control, ownership, verification, and stop facts]",)),
    SectionSpec("review_routing", "Review Routing", ("- [active review override or canonical SOW route]",)),
    SectionSpec("canonical_routes", "Canonical Detail Routes", ("- [task trigger]: load [same-named SOW entry] before governed work",)),
    SectionSpec("minimal_deferrals", "Minimal Bootstrap Deferrals", ("- Field: [field] — Owner: [owner] — Reason: [reason] — Boundary Type: [type] — Closure Boundary: [boundary].",)),
    SectionSpec("constraints", "Non-Negotiable Constraints", ("- [active constraint]",)),
    SectionSpec("applicable_standards", "Applicable Standards", ("- [project-specific standard and version/date scope]",)),
    SectionSpec("critical_surfaces", "Critical Surfaces", ("- [surface] — [risk] — [review burden]",)),
    SectionSpec("security_policy", "Security Policy", ("- [project-specific term copied from the SOW]",)),
    SectionSpec("version_control", "Version Control Profile", ("- [active VCS fact] — [policy or evidence]",)),
    SectionSpec("memory_boundary", "Memory Boundary", ("- [active memory boundary]",)),
    SectionSpec("verification_profiles", "Verification Profiles", ("- [profile] — [checks] — [trigger]",)),
    SectionSpec("approval_boundaries", "Approval Boundaries", ("- [action requiring approval]",)),
    SectionSpec("acquisition_boundary", "Acquisition Boundary", ("- [approved source/acquisition/egress/data boundary]",)),
    SectionSpec("definitions", "Definitions", ("{PROJECT_DEFINITIONS}",)),
    SectionSpec(
        "command_restrictions",
        "Command Restrictions",
        ("- " + render_command_restriction("[command]", "[reason]", "[alternative]"),),
    ),
    SectionSpec("auxiliary_tools", "Auxiliary Tools", ("- [integration] — [purpose] — load the same-named SOW Auxiliary Tools entry before use — [use trigger / approval / control role]",)),
    SectionSpec(
        "loading_rule",
        "Loading Rule",
        (
            "_Blueprint-only authoring guidance; concrete generated contracts retain only applicable facts and operative rules._",
            *PROJECT_LOADING_RULE_AUTHOR_GUIDANCE,
            "",
            *PROJECT_LOADING_RULE_OPERATIVE_LINES,
        ),
    ),
)
PROJECT_SECTIONS = {spec.key: spec for spec in PROJECT_SECTION_SPECS}
PROJECT_SECTION_TITLES = frozenset(spec.title for spec in PROJECT_SECTION_SPECS)
PROJECT_SECTION_ROW_STYLES: dict[str, ProjectSectionRowStyle] = {
    spec.key: (
        "numbered"
        if spec.key == "active_deliverables"
        else "scope"
        if spec.key == "active_scope"
        else "bullet"
    )
    for spec in PROJECT_SECTION_SPECS
}


def project_blueprint_labeled_row_labels(section_key: str) -> tuple[str, ...]:
    """Derive native labeled-row names from one project-section blueprint."""

    labels: list[str] = []
    for line in PROJECT_SECTIONS[section_key].blueprint_lines:
        match = re.fullmatch(r"- ([^\[\]{}:]+): .+", line)
        if match is not None:
            labels.append(match.group(1).strip())
    return tuple(labels)


def sow_section_title(key: str) -> str:
    return SOW_SECTIONS[key].title


def sow_section_policy_lines(key: str) -> tuple[str, ...]:
    return SOW_SECTIONS[key].policy_lines


def sow_blueprint_labeled_row_labels(section_key: str) -> tuple[str, ...]:
    """Derive concrete scalar labels from one SOW section blueprint."""

    spec = SOW_SECTIONS[section_key]
    labels: list[str] = []
    for line in spec.blueprint_lines:
        if line in spec.policy_lines or line.startswith(("- ", "1. ", "_", "`", "[")):
            continue
        label, separator, value = line.partition(": ")
        if separator and label.strip() and value.strip():
            labels.append(label.strip())
    return tuple(labels)


def render_automation_job_summary(job: Mapping[str, object]) -> str:
    """Render the canonical SOW summary row for one automation job."""

    def value(key: str) -> str:
        rendered = str(job.get(key, "")).strip()
        return rendered or "TBD"

    fields = {field: value(field) for field in AUTOMATION_SOW_SUMMARY_FIELDS}
    return (
        f"{fields['id']}: {fields['objective']} — {fields['schedule']} "
        f"{fields['timezone']} — {fields['autonomy_level']} — "
        f"{fields['approval_mode']}"
    )


def project_section_title(key: str) -> str:
    return "## " + PROJECT_SECTIONS[key].title


# Every accepted answer field has an explicit semantic consumer.  These
# projections are an accounting ledger, not a second renderer: the bootstrap
# owns value formatting while this model owns which contract surface receives
# each value.
FIELD_PROJECTIONS: dict[str, tuple[str, ...]] = {
    "acceptance_checklist": ("sow:acceptance_checklist", "project:acceptance_checklist"),
    "acquisition_boundary": ("sow:acquisition_boundary", "project:acquisition_boundary"),
    "agent": ("definition:Agent", "project:definitions"),
    "ai_disclosure": ("definition:AI Disclosure", "project:constraints"),
    "annexes": ("sow:annexes", "project:active_modules"),
    "applicable_standards": ("sow:applicable_standards", "project:applicable_standards"),
    "approval_boundaries": ("sow:approval_boundaries", "project:approval_boundaries"),
    "arbitration_panel": (
        "sow:arbitration_panel",
        "definition:Arbitration Panel",
        "project:review_routing",
    ),
    "architecture": ("sow:technical_specifications", "project:active_stack"),
    "automation_orders": ("sow:automation", "state:AUTOMATION_ORDERS.json"),
    "auxiliary_tools": ("sow:auxiliary_tools", "project:auxiliary_tools"),
    "backout_policy": ("definition:Backout Rule", "project:version_control"),
    "bootstrap_mode": (
        "definition:Bootstrap Mode",
        "project:definitions",
        "control:bootstrap-mode",
    ),
    "branch_policy": ("definition:Branch Rule", "project:version_control"),
    "code_review_checklist": ("sow:code_review", "project:canonical_routes"),
    "command_restrictions": ("sow:command_restrictions", "project:command_restrictions"),
    "commands": ("sow:commands", "project:common_commands"),
    "constraints": ("sow:constraints", "project:constraints"),
    "credential_delivery": (
        "definition:Credential Delivery",
        "project:acquisition_boundary",
    ),
    "critical_surface_policy": (
        "definition:Critical Surface Rule",
        "project:critical_surfaces",
    ),
    "critical_surfaces": ("sow:critical_surfaces", "project:critical_surfaces"),
    "date": ("header:date",),
    "decision_authority_grant": (
        "definition:Decision Boundary",
        "project:approval_boundaries",
    ),
    "default_review_topology": (
        "definition:Default Review Topology",
        "sow:reviewer_lanes",
        "project:review_routing",
    ),
    "deliverables": ("sow:deliverables", "project:active_deliverables"),
    "dependency_posture": ("definition:Dependency Rule", "project:active_stack"),
    "direct_panel_rules": (
        "sow:direct_panel_rules",
        "definition:Direct Panel Rules",
        "project:review_routing",
    ),
    "execution_posture": ("definition:Execution Mode", "project:definitions"),
    "file_structure": (
        "sow:technical_specifications",
        "project:canonical_routes",
    ),
    "framework_verification_runner": ("definition:Framework Verification Runner", "project:framework_verification"),
    "in_scope": ("sow:scope", "project:active_scope"),
    "include_automation_orders": ("state:AUTOMATION_ORDERS.json", "control:optional-section"),
    "include_findings": ("state:FINDINGS.md",),
    "include_framework_feedback": ("state:FRAMEWORK_FEEDBACK.md", "control:optional-section"),
    "include_precedents": ("state:PRECEDENTS.md",),
    "include_reviewer_lane_feedback": ("state:REVIEWER_LANE_FEEDBACK.md", "control:optional-section"),
    "include_security_verification": ("state:SECURITY_VERIFICATION.md", "control:optional-section"),
    "include_source_monitor_researcher": ("state:SOURCE_MONITOR_RESEARCHER.md", "control:optional-section"),
    "include_source_packs": ("state:SOURCE_PACKS.md", "control:optional-section"),
    "include_source_update": ("state:SOURCE_UPDATE.md", "control:optional-section"),
    "independent_assessment_approval": (
        "sow:independent_assessment",
        "definition:Independent Assessment Approval",
        "project:review_routing",
    ),
    "key_dependencies": ("sow:technical_specifications", "project:active_stack"),
    "key_directories": ("sow:technical_specifications", "project:active_stack"),
    "language_runtime_standards": (
        "definition:Language/Runtime Standards",
        "project:active_stack",
    ),
    "language_specific_rules": ("sow:language_rules", "project:constraints"),
    "minimal_deferrals": ("sow:minimal_deferrals", "project:minimal_deferrals"),
    "out_of_scope": ("sow:scope", "project:active_scope"),
    "package_manager": ("definition:Package Manager", "project:active_stack"),
    "pattern_sources": ("sow:pattern_sources", "project:canonical_routes"),
    "persistent_memory_boundary": ("definition:Memory Boundary", "sow:memory_boundary", "project:memory_boundary"),
    "project_name": ("header:project-name",),
    "project_vocabulary": ("sow:project_vocabulary", "project:project_vocabulary"),
    "recitals": ("sow:recitals",),
    "reviewer_lane_inventory": (
        "definition:Reviewer Lane Inventory",
        "sow:reviewer_lanes",
        "project:review_routing",
    ),
    "secret_store": ("definition:Secret Store", "project:acquisition_boundary"),
    "security_policy_file": (
        "definition:Security Policy File",
        "sow:security_verification",
        "project:active_modules",
    ),
    "security_policy_terms": ("sow:security_policy", "project:security_policy"),
    "security_verification_profile_scope": (
        "definition:Security Verification Profile Scope",
        "sow:security_verification",
        "state:SECURITY_VERIFICATION.md",
    ),
    "security_verification_target_policy": (
        "definition:Security Verification Target Policy",
        "sow:security_verification",
        "state:SECURITY_VERIFICATION.md",
    ),
    "shared_framework_source_reference": (
        "sow:source_packs",
        "sow:source_update",
        "state:SOURCE_PACKS.md",
    ),
    "source_freshness_policy": (
        "definition:Source Freshness Rule",
        "project:acquisition_boundary",
    ),
    "source_monitor_boundary": (
        "definition:Source Monitor Boundary",
        "sow:source_monitor",
        "state:SOURCE_MONITOR_RESEARCHER.md",
    ),
    "source_monitor_instruction_sources": (
        "definition:Source Monitor Instruction Sources",
        "sow:source_monitor",
        "state:SOURCE_MONITOR_RESEARCHER.md",
    ),
    "source_monitor_role": (
        "definition:Source Monitor Role",
        "sow:source_monitor",
        "state:SOURCE_MONITOR_RESEARCHER.md",
    ),
    "source_monitor_source_data": (
        "definition:Source Monitor Source Data",
        "sow:source_monitor",
        "state:SOURCE_MONITOR_RESEARCHER.md",
    ),
    "source_originality_policy": (
        "definition:External Source Rule",
        "project:acquisition_boundary",
    ),
    "source_registry_scope": (
        "definition:Source Registry Scope",
        "sow:source_update",
        "state:SOURCE_UPDATE.md",
    ),
    "source_review_cadence": (
        "definition:Source Review Cadence",
        "sow:source_update",
        "state:SOURCE_UPDATE.md",
    ),
    "sow_version": ("header:sow-version",),
    "standing_panel_convocation_approval": (
        "definition:Standing Panel Convocation Approval",
        "sow:direct_panel_rules",
        "project:review_routing",
    ),
    "tech_stack": ("sow:technical_specifications", "project:active_stack"),
    "user": ("definition:User",),
    "verification_profiles": ("sow:verification_profiles", "project:verification_profiles"),
    "version_control_policy": (
        "definition:Version Control Rule",
        "project:version_control",
    ),
    "version_control_profile": ("sow:version_control_profile", "project:version_control"),
    "version_review_policy": (
        "definition:Version Review Rule",
        "project:framework_verification",
    ),
    "workflows": ("sow:workflows", "project:active_workflows"),
}

# Every accepted answer has exactly one primary runtime owner. Canonical and
# generated-state owners intentionally do not become always-loaded runtime
# copies; project:* owners identify the one runtime section allowed to carry
# the fact or its mandatory canonical-detail route.
RUNTIME_FIELD_OWNERS: dict[str, str] = {
    "acceptance_checklist": "project:acceptance_checklist",
    "acquisition_boundary": "project:acquisition_boundary",
    "agent": "project:definitions",
    "ai_disclosure": "project:constraints",
    "annexes": "project:active_modules",
    "applicable_standards": "project:applicable_standards",
    "approval_boundaries": "project:approval_boundaries",
    "arbitration_panel": "project:review_routing",
    "architecture": "project:active_stack",
    "automation_orders": "state:AUTOMATION_ORDERS.json",
    "auxiliary_tools": "project:auxiliary_tools",
    "backout_policy": "project:version_control",
    "bootstrap_mode": "project:definitions",
    "branch_policy": "project:version_control",
    "code_review_checklist": "project:canonical_routes",
    "command_restrictions": "project:command_restrictions",
    "commands": "project:common_commands",
    "constraints": "project:constraints",
    "credential_delivery": "project:acquisition_boundary",
    "critical_surface_policy": "project:critical_surfaces",
    "critical_surfaces": "project:critical_surfaces",
    "date": "header:date",
    "decision_authority_grant": "project:approval_boundaries",
    "default_review_topology": "project:review_routing",
    "deliverables": "project:active_deliverables",
    "dependency_posture": "project:active_stack",
    "direct_panel_rules": "project:review_routing",
    "execution_posture": "project:definitions",
    "file_structure": "project:canonical_routes",
    "framework_verification_runner": "project:framework_verification",
    "in_scope": "project:active_scope",
    "include_automation_orders": "state:AUTOMATION_ORDERS.json",
    "include_findings": "state:FINDINGS.md",
    "include_framework_feedback": "state:FRAMEWORK_FEEDBACK.md",
    "include_precedents": "state:PRECEDENTS.md",
    "include_reviewer_lane_feedback": "state:REVIEWER_LANE_FEEDBACK.md",
    "include_security_verification": "state:SECURITY_VERIFICATION.md",
    "include_source_monitor_researcher": "state:SOURCE_MONITOR_RESEARCHER.md",
    "include_source_packs": "state:SOURCE_PACKS.md",
    "include_source_update": "state:SOURCE_UPDATE.md",
    "independent_assessment_approval": "project:review_routing",
    "key_dependencies": "project:active_stack",
    "key_directories": "project:active_stack",
    "language_runtime_standards": "project:active_stack",
    "language_specific_rules": "project:constraints",
    "minimal_deferrals": "project:minimal_deferrals",
    "out_of_scope": "project:active_scope",
    "package_manager": "project:active_stack",
    "pattern_sources": "project:canonical_routes",
    "persistent_memory_boundary": "project:memory_boundary",
    "project_name": "header:project-name",
    "project_vocabulary": "project:project_vocabulary",
    "recitals": "canonical-only",
    "reviewer_lane_inventory": "project:review_routing",
    "secret_store": "project:acquisition_boundary",
    "security_policy_file": "project:active_modules",
    "security_policy_terms": "project:security_policy",
    "security_verification_profile_scope": "state:SECURITY_VERIFICATION.md",
    "security_verification_target_policy": "state:SECURITY_VERIFICATION.md",
    "shared_framework_source_reference": "state:SOURCE_PACKS.md",
    "source_freshness_policy": "project:acquisition_boundary",
    "source_monitor_boundary": "state:SOURCE_MONITOR_RESEARCHER.md",
    "source_monitor_instruction_sources": "state:SOURCE_MONITOR_RESEARCHER.md",
    "source_monitor_role": "state:SOURCE_MONITOR_RESEARCHER.md",
    "source_monitor_source_data": "state:SOURCE_MONITOR_RESEARCHER.md",
    "source_originality_policy": "project:acquisition_boundary",
    "source_registry_scope": "state:SOURCE_UPDATE.md",
    "source_review_cadence": "state:SOURCE_UPDATE.md",
    "sow_version": "canonical-only",
    "standing_panel_convocation_approval": "project:review_routing",
    "tech_stack": "project:active_stack",
    "user": "canonical-only",
    "verification_profiles": "project:verification_profiles",
    "version_control_policy": "project:version_control",
    "version_control_profile": "project:version_control",
    "version_review_policy": "project:framework_verification",
    "workflows": "project:active_workflows",
}


def framework_verification_command_lines(
    framework_ref: str,
    *,
    project_kind: str = "downstream",
    contract_root_ref: str = ".",
    runner: str = FRAMEWORK_VERIFICATION_RUNNER_PLACEHOLDER,
) -> list[str]:
    """Render the framework-owned verification command block."""

    reference = (
        framework_ref
        if framework_ref
        in {"{{FRAMEWORK_ROOT}}", FRAMEWORK_REFERENCE_TEMPLATE_PLACEHOLDER}
        else safe_paths.canonical_framework_reference(framework_ref)
    )
    configured_runner = runner.strip() or FRAMEWORK_VERIFICATION_RUNNER_PLACEHOLDER
    layout_args = f" --project-kind {project_kind}"
    if contract_root_ref != ".":
        layout_args += f" --contract-root {contract_root_ref}"

    def script_reference(relative: str) -> str:
        if reference in {
            "{{FRAMEWORK_ROOT}}",
            FRAMEWORK_REFERENCE_TEMPLATE_PLACEHOLDER,
        }:
            return f'"{reference}/{relative}"'
        return safe_paths.shell_framework_path_token(reference, relative)

    return [
        f"- Framework reference: {reference}",
        f"- Framework Verification Runner: {configured_runner}",
        "- Run from the project root; the routine gate calls the framework-owned aggregate checker through the framework reference. Use its named child checks only for setup or diagnosis.",
        f"- Core conformance: {configured_runner} -- {script_reference('scripts/conformance_check.py')} --profile core-project --root .{layout_args}",
        f"- Runner fallback: do not silently replace the configured runner. If it is unavailable, stop and resolve the project runner requirement; when available, its prerequisite command is {configured_runner} -- {script_reference('scripts/check_prereqs.py')}.",
    ]


def missing_auxiliary_tool_fact_groups(
    item: Mapping[str, object],
) -> tuple[str, ...]:
    """Return missing protocol-neutral integration-boundary fact groups."""

    return tuple(
        label
        for label, keys in AUXILIARY_TOOL_FACT_GROUPS
        if not any(str(item.get(key, "")).strip() for key in keys)
    )


def auxiliary_tool_control_errors(
    item: Mapping[str, object],
) -> tuple[str, ...]:
    """Return contradictions in the protocol-neutral control declaration."""

    role = str(item.get("control_role", "")).strip()
    coverage = str(item.get("control_coverage", "")).strip()
    if not role:
        return ()
    if role not in AUXILIARY_CONTROL_ROLES:
        return (
            "control_role must be one of: "
            + ", ".join(sorted(AUXILIARY_CONTROL_ROLES)),
        )
    if role in AUXILIARY_CONTROL_COVERAGE_ROLES and not coverage:
        return (
            f"control_coverage is required when control_role is {role!r}",
        )
    if role == "none" and coverage:
        return ("control_coverage must be omitted when control_role is 'none'",)
    return ()


def _closed_object(
    properties: dict[str, object],
    *,
    required: Iterable[str] = (),
) -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": sorted(required),
    }


def _control_free_text_schema() -> dict[str, object]:
    return generated_sow_text.control_free_text_schema(single_line=True)


def _nullable_control_free_text_schema() -> dict[str, object]:
    return {
        "oneOf": [
            _control_free_text_schema(),
            {"type": "null"},
        ]
    }


def _string_array(*, min_items: int = 0) -> dict[str, object]:
    schema: dict[str, object] = {
        "type": "array",
        "items": _control_free_text_schema(),
    }
    if min_items:
        schema["minItems"] = min_items
    return schema


def _enum_schema(values: Iterable[str]) -> dict[str, object]:
    return {"type": "string", "enum": sorted(values)}


def _automation_job_schema() -> dict[str, object]:
    """Derive the answer-file job shape from the automation validator owner."""

    text = _control_free_text_schema()
    sow_summary_text = _generated_sow_text_schema(single_line=True)

    def sow_summary_enum(values: Iterable[str]) -> dict[str, object]:
        return {
            **dict(sow_summary_text),
            "enum": sorted(values),
        }
    nullable_text = _nullable_control_free_text_schema()
    idempotency = _closed_object(
        {
            "key": nullable_text,
            "mode": _enum_schema(automation_orders_lint.IDEMPOTENCY_MODES),
        },
        required=automation_orders_lint.IDEMPOTENCY_KEYS,
    )
    state_policy = _closed_object(
        {
            "checkpoint": _enum_schema(automation_orders_lint.STATE_CHECKPOINT_MODES),
            "persistence": _enum_schema(automation_orders_lint.STATE_PERSISTENCE_MODES),
            "reference": nullable_text,
            "resume": _enum_schema(automation_orders_lint.STATE_RESUME_MODES),
        },
        required=automation_orders_lint.STATE_POLICY_KEYS,
    )
    retention = _closed_object(
        {
            "days": {"type": ["integer", "null"], "minimum": 1, "maximum": 3650},
            "manual_owner": nullable_text,
            "manual_trigger": nullable_text,
            "mode": _enum_schema(automation_orders_lint.RETENTION_MODES),
        },
        required=automation_orders_lint.RETENTION_KEYS,
    )
    redaction = _closed_object(
        {"mode": _enum_schema(automation_orders_lint.REDACTION_MODES)},
        required=automation_orders_lint.REDACTION_KEYS,
    )
    scheduler_artifacts = _closed_object(
        {
            "lock_file": nullable_text,
            "log_file": text,
            "max_log_bytes": {
                "type": "integer",
                "minimum": automation_orders_lint.MIN_SCHEDULER_LOG_BYTES,
                "maximum": automation_orders_lint.MAX_SCHEDULER_LOG_BYTES,
            },
            "redaction": redaction,
            "retention": retention,
            "root": text,
        },
        required=automation_orders_lint.SCHEDULER_ARTIFACT_KEYS,
    )
    external_review = _closed_object(
        {
            "allowed_data_classes": {
                **_string_array(min_items=1),
                "items": _enum_schema(automation_orders_lint.EXTERNAL_REVIEW_DATA_CLASSES),
                "uniqueItems": True,
            },
            "authentication": _enum_schema(automation_orders_lint.EXTERNAL_REVIEW_AUTH_MODES),
            "egress": {"const": "approved_endpoints_only"},
            "max_requests": {"type": "integer", "minimum": 1, "maximum": 100000},
            "redaction": _enum_schema(automation_orders_lint.EXTERNAL_REVIEW_REDACTION_MODES),
            "retained_artifacts": _enum_schema(automation_orders_lint.EXTERNAL_REVIEW_RETAINED_MODES),
            "retention_days": {"type": "integer", "minimum": 0, "maximum": 3650},
            "sensitive_data": {"const": "deny"},
            "unlisted_data": {"const": "deny"},
        },
        required=automation_orders_lint.EXTERNAL_REVIEW_KEYS,
    )
    source_policy = _closed_object(
        {
            "allowed_capabilities": {
                **_string_array(min_items=1),
                "items": _enum_schema(automation_orders_lint.SOURCE_CAPABILITIES),
                "uniqueItems": True,
            },
            "max_requests_per_run": {"type": "integer", "minimum": 1, "maximum": 100000},
            "oauth_scopes": {**_string_array(), "uniqueItems": True},
            "primary_source_verification": {"const": "required"},
            "retention_days": {"type": "integer", "minimum": 0, "maximum": 3650},
            "source_aliases": {**_string_array(min_items=1), "uniqueItems": True},
            "terms_reviewed_on": {
                **_control_free_text_schema(),
                "format": "date",
            },
            "write_access": {"const": "deny"},
        },
        required=automation_orders_lint.SOURCE_POLICY_KEYS,
    )
    parser_change_properties: dict[str, object] = {
        key: text for key in automation_orders_lint.PARSER_CHANGE_KEYS
    }
    parser_digest_schema = {
        **_string_array(min_items=1),
        "items": {
            **_control_free_text_schema(),
            "pattern": rf"^(?:{automation_orders_lint.SHA256_TOKEN_RE.pattern})$",
        },
        "uniqueItems": True,
    }
    for key in (
        "approved_output_digests",
        "expected_output_digests",
        "input_fixture_digests",
    ):
        parser_change_properties[key] = parser_digest_schema
    for key in ("golden_fixture_paths",):
        parser_change_properties[key] = _string_array(min_items=1)
    for key in ("old_new_comparison_completed", "primary_evidence_verified"):
        parser_change_properties[key] = {"const": True}
    parser_change_properties["change_kind"] = _enum_schema(
        automation_orders_lint.PARSER_CHANGE_KINDS
    )
    parser_change_properties["fail_closed_action"] = _enum_schema(
        automation_orders_lint.PARSER_FAIL_CLOSED_ACTIONS
    )
    parser_change = _closed_object(
        parser_change_properties,
        required=automation_orders_lint.PARSER_CHANGE_KEYS,
    )
    authority_validity = _closed_object(
        {
            "expires_on": {
                "oneOf": [
                    {**_control_free_text_schema(), "format": "date"},
                    {"type": "null"},
                ]
            },
            "mode": _enum_schema(automation_orders_lint.AUTHORITY_VALIDITY_MODES),
            "revocation_events": {
                **_string_array(min_items=1),
                "items": _enum_schema(automation_orders_lint.AUTHORITY_REVOCATION_EVENTS),
                "uniqueItems": True,
            },
        },
        required=automation_orders_lint.AUTHORITY_VALIDITY_KEYS,
    )
    authority_verification = _closed_object(
        {
            "evidence_refs": {**_string_array(min_items=1), "uniqueItems": True},
            "kind": _enum_schema(automation_orders_lint.AUTHORITY_VERIFICATION_KINDS),
            "on_failure": {"const": "block"},
        },
        required=automation_orders_lint.AUTHORITY_VERIFICATION_KEYS,
    )
    authority = _closed_object(
        {
            "allowed_actions": {**_string_array(min_items=1), "uniqueItems": True},
            "basis": _enum_schema(automation_orders_lint.AUTHORITY_BASES),
            "effect_class": _enum_schema(automation_orders_lint.AUTHORITY_EFFECT_CLASSES),
            "failure_action": _enum_schema(automation_orders_lint.AUTHORITY_FAILURE_ACTIONS),
            "resource_refs": {**_string_array(min_items=1), "uniqueItems": True},
            "source_ref": text,
            "validity": authority_validity,
            "verification": authority_verification,
        },
        required=automation_orders_lint.AUTHORITY_KEYS,
    )
    source_reference = _closed_object(
        {
            "path": text,
            "root": _enum_schema(automation_orders_lint.SOURCE_REFERENCE_ROOTS),
        },
        required=automation_orders_lint.SOURCE_REFERENCE_KEYS,
    )
    source_references = {
        "type": "array",
        "items": source_reference,
        "maxItems": automation_orders_lint.MAX_BOUND_SOURCE_REFERENCES,
        "uniqueItems": True,
    }

    properties: dict[str, object] = {
        key: (
            dict(sow_summary_text)
            if key in AUTOMATION_SOW_SUMMARY_FIELDS
            else text
        )
        for key in automation_orders_lint.JOB_KEYS
    }
    properties.update(
        {
            "approval_mode": sow_summary_enum(
                automation_orders_lint.APPROVAL_MODES
            ),
            "authority": authority,
            "autonomy_level": sow_summary_enum(
                automation_orders_lint.AUTONOMY_LEVELS
            ),
            "concurrency": _enum_schema(automation_orders_lint.CONCURRENCY_MODES),
            "enabled": {"type": "boolean"},
            "external_review": external_review,
            "failure_policy": _enum_schema(automation_orders_lint.FAILURE_POLICIES),
            "id": {
                **dict(sow_summary_text),
                "pattern": rf"^(?:{automation_orders_lint.JOB_ID_RE.pattern})$",
            },
            "idempotency": idempotency,
            "execution_sources": dict(source_references),
            "instruction_sources": {**source_references, "minItems": 1},
            "outputs": _string_array(),
            "parser_change": parser_change,
            "reviewer_boundary_mode": _enum_schema(automation_orders_lint.REVIEWER_BOUNDARY_MODES),
            "reviewer_runtime_class": _enum_schema(automation_orders_lint.REVIEWER_RUNTIME_CLASSES),
            "scheduler_artifacts": scheduler_artifacts,
            "scheduler_context_mode": _enum_schema(automation_orders_lint.SCHEDULER_CONTEXT_MODES),
            "source_access_class": _enum_schema(automation_orders_lint.SOURCE_ACCESS_CLASSES),
            "source_policy": source_policy,
            "standard_of_care": _enum_schema(automation_orders_lint.STANDARDS),
            "state_policy": state_policy,
            "timeout_minutes": {
                "type": "integer",
                "minimum": 1,
                "maximum": automation_orders_lint.MAX_TIMEOUT_MINUTES,
            },
            "workload_class": _enum_schema(automation_orders_lint.WORKLOAD_CLASSES),
            "write_scope": _enum_schema(automation_orders_lint.WRITE_SCOPES),
        }
    )
    return {
        **_closed_object(properties, required=automation_orders_lint.REQUIRED_JOB_KEYS),
        "$comment": (
            "Cross-field, path, date-freshness, command, and scheduler semantics are "
            "authoritatively validated by scripts/automation_orders_lint.py."
        ),
        "x-mpa-runtime-validator": "scripts/automation_orders_lint.py",
    }


def _ecmascript_literal(value: str) -> str:
    return generated_sow_text.ecmascript_literal(value)


def _generated_sow_text_schema(*, single_line: bool) -> dict[str, object]:
    """Return the shared lexical grammar for text rendered into a generated SOW."""

    return generated_sow_text.generated_sow_text_schema(single_line=single_line)


def _answer_text_schema(
    spec: AnswerFieldSpec,
    member_key: str | None = None,
    *,
    single_line: bool | None = None,
) -> dict[str, object]:
    schema = _generated_sow_text_schema(
        single_line=(spec.kind != "lines" if single_line is None else single_line)
    )
    raw_constraints = schema.get("allOf")
    if not isinstance(raw_constraints, list):
        raise TypeError("generated SOW text schema constraints must be a list")
    constraints: list[dict[str, object]] = list(raw_constraints)
    grammar = ANSWER_TEXT_GRAMMAR_BY_KEY.get(spec.name)
    if grammar is None or (
        (grammar.member_keys and member_key not in grammar.member_keys)
        or (not grammar.member_keys and member_key is not None)
    ):
        schema["allOf"] = constraints
        return schema
    if grammar.forbidden_exact_lines:
        alternatives = "|".join(
            _ecmascript_literal(value)
            for value in sorted(grammar.forbidden_exact_lines)
        )
        constraints.append(
            {
                "not": {
                    "pattern": (
                        rf"(?:^|{ECMASCRIPT_SPLITLINES_BOUNDARY})"
                        rf"[ \t]*(?:{alternatives})[ \t]*"
                        rf"(?:{ECMASCRIPT_SPLITLINES_BOUNDARY}|$)"
                    )
                }
            }
        )
    if grammar.forbidden_substrings:
        alternatives = "|".join(
            _ecmascript_literal(value) for value in grammar.forbidden_substrings
        )
        constraints.append({"not": {"pattern": rf"(?:{alternatives})"}})
    if grammar.forbidden_line_syntax:
        alternatives = "|".join(
            f"(?:{pattern})"
            for _label, pattern in grammar.forbidden_line_syntax
        )
        constraints.append(
            {
                "not": {
                    "pattern": (
                        rf"(?:^|{ECMASCRIPT_SPLITLINES_BOUNDARY})"
                        rf"[ \t]*(?:{alternatives})"
                    )
                }
            }
        )
    if constraints:
        schema["allOf"] = constraints
    return schema


def _forbid_string_pattern(
    schema: Mapping[str, object],
    pattern: str,
) -> dict[str, object]:
    """Add one generated-text grammar exclusion without discarding prior rules."""

    result = dict(schema)
    existing_constraints = result.get("allOf")
    if existing_constraints is not None and not isinstance(existing_constraints, list):
        raise TypeError("schema allOf constraints must be a list")
    constraints: list[object] = list(existing_constraints or [])
    constraints.append({"not": {"pattern": pattern}})
    result["allOf"] = constraints
    return result


def _base_field_schema(spec: AnswerFieldSpec) -> dict[str, object]:
    text = _answer_text_schema(spec)
    line_member = _answer_text_schema(spec, single_line=True)
    line_value: dict[str, object] = {
        "oneOf": [text, {"type": "array", "items": line_member}],
    }
    if spec.kind == "boolean":
        return {"type": "boolean"}
    if spec.kind == "string":
        schema = dict(text)
        if spec.enum:
            schema["enum"] = list(spec.enum)
        return schema
    if spec.kind == "lines":
        return line_value
    if spec.kind == "commands":
        return _closed_object(
            {
                key: _answer_text_schema(spec, key)
                for key in sorted(COMMAND_KEYS)
            }
        )
    if spec.kind == "deliverables":
        return {
            "type": "array",
            "items": _closed_object(
                {key: text for key in sorted(DELIVERABLE_KEYS)},
                required=DELIVERABLE_KEYS,
            ),
        }
    if spec.kind == "command_restrictions":
        return {
            "type": "array",
            "items": _closed_object(
                {
                    key: _answer_text_schema(spec, key)
                    for key in sorted(RESTRICTION_KEYS)
                },
                required=RESTRICTION_KEYS,
            ),
        }
    if spec.kind == "auxiliary_tools":
        tool_properties: dict[str, object] = {
            key: text for key in sorted(AUXILIARY_TOOL_KEYS)
        }
        tool_properties["control_role"] = _enum_schema(AUXILIARY_CONTROL_ROLES)
        tool = _closed_object(
            tool_properties,
            required=REQUIRED_AUXILIARY_TOOL_KEYS,
        )
        tool_constraints: list[dict[str, object]] = [
            {"anyOf": [{"required": [key]} for key in sorted(keys)]}
            for _label, keys in AUXILIARY_TOOL_FACT_GROUPS
        ]
        tool_constraints.extend(
            (
                {
                    "if": {
                        "required": ["control_role"],
                        "properties": {
                            "control_role": {
                                "enum": sorted(AUXILIARY_CONTROL_COVERAGE_ROLES)
                            }
                        },
                    },
                    "then": {"required": ["control_coverage"]},
                },
                {
                    "if": {
                        "required": ["control_role"],
                        "properties": {"control_role": {"const": "none"}},
                    },
                    "then": {"not": {"required": ["control_coverage"]}},
                },
            )
        )
        tool["allOf"] = tool_constraints
        return {"type": "array", "items": tool}
    if spec.kind == "arbitration_panel":
        seat = _closed_object(
            {key: text for key in sorted(PANEL_SEAT_KEYS)},
            required=PANEL_SEAT_KEYS,
        )
        panel_properties: dict[str, object] = {
            key: text for key in sorted(PANEL_CONFIG_KEYS - {"seats"})
        }
        panel_properties["seats"] = {"type": "array", "minItems": 1, "items": seat}
        return _closed_object(panel_properties, required=PANEL_CONFIG_KEYS)
    if spec.kind == "workflows":
        workflow_properties: dict[str, object] = {
            key: _answer_text_schema(spec, key)
            for key in sorted(WORKFLOW_KEYS)
        }
        return {
            "type": "array",
            "items": _closed_object(
                workflow_properties,
                required=WORKFLOW_REQUIRED_KEYS,
            ),
        }
    if spec.kind == "annexes":
        schema = _closed_object({key: text for key in sorted(ANNEX_KEYS)})
        schema["description"] = (
            "Each selected Annex A-C key must identify a different canonical "
            "project-relative authority-module path; one path cannot have multiple "
            "owner labels."
        )
        return schema
    if spec.kind == "automation_orders":
        return _closed_object(
            {
                "jobs": {"type": "array", "items": _automation_job_schema()},
                "preferred_backend": {
                    **_generated_sow_text_schema(single_line=True),
                    "pattern": (
                        rf"^(?:{automation_orders_lint.BACKEND_RE.pattern})$"
                    ),
                },
            }
        )
    if spec.kind == "minimal_deferrals":
        return {
            "type": "array",
            "items": _closed_object(
                {
                    "boundary_type": _enum_schema(MINIMAL_DEFERRAL_BOUNDARY_TYPES),
                    "closure_boundary": text,
                    "field": _enum_schema(MINIMAL_DEFERRABLE_FIELDS),
                    "owner": text,
                    "reason": text,
                },
                required=MINIMAL_DEFERRAL_KEYS,
            ),
        }
    raise RuntimeError(f"unsupported answer field kind: {spec.kind}")


def _structured_delimiter_schema(
    spec: AnswerFieldSpec,
    schema: Mapping[str, object],
) -> dict[str, object]:
    """Project declared rendered delimiters into every structured item schema."""

    identity_field = STRUCTURED_IDENTITY_FIELDS.get(spec.name)
    if identity_field is None:
        return dict(schema)

    result = dict(schema)
    raw_items = result.get("items")
    if not isinstance(raw_items, Mapping):
        raise RuntimeError(
            f"structured collection schema must expose object items: {spec.name}"
        )
    items = dict(raw_items)
    raw_properties = items.get("properties")
    if not isinstance(raw_properties, Mapping):
        raise RuntimeError(
            f"structured collection item schema must expose properties: {spec.name}"
        )
    if identity_field not in raw_properties:
        raise RuntimeError(
            f"structured identity field is absent from item schema: "
            f"{spec.name}.{identity_field}"
        )

    properties: dict[str, object] = {}
    for field, raw_field_schema in raw_properties.items():
        if not isinstance(field, str) or not isinstance(raw_field_schema, Mapping):
            raise RuntimeError(
                f"structured collection properties must be schema objects: {spec.name}"
            )
        field_schema = dict(raw_field_schema)
        for delimiter in structured_field_delimiters(spec.name, field):
            field_schema = _forbid_string_pattern(
                field_schema,
                _ecmascript_literal(delimiter),
            )
        properties[field] = field_schema

    items["properties"] = properties
    result["items"] = items
    return result


def _field_schema(spec: AnswerFieldSpec) -> dict[str, object]:
    return _structured_delimiter_schema(spec, _base_field_schema(spec))


def _mode_requirement(mode: str, required: frozenset[str]) -> dict[str, object]:
    then: dict[str, object] = {"required": sorted(required)}
    if mode == "full":
        concrete_text = {"type": "string", "pattern": "\\S"}
        concrete_lines = {
            "oneOf": [
                concrete_text,
                {
                    "type": "array",
                    "minItems": 1,
                    "items": concrete_text,
                },
            ]
        }
        then["properties"] = {
            "architecture": concrete_text,
            "commands": {
                **_field_schema(ANSWER_FIELDS["commands"]),
                "required": sorted(COMMAND_KEYS),
            },
            "deliverables": {
                **_field_schema(ANSWER_FIELDS["deliverables"]),
                "minItems": 1,
            },
            "in_scope": concrete_lines,
            "language_runtime_standards": concrete_text,
            "out_of_scope": concrete_lines,
            "recitals": concrete_lines,
            "tech_stack": concrete_text,
        }
    return {
        "if": {
            "required": ["bootstrap_mode"],
            "properties": {"bootstrap_mode": {"const": mode}},
        },
        "then": then,
    }


def answer_json_schema() -> dict[str, object]:
    """Return the complete generated schema for bootstrap answers."""

    automation_order_schema = _field_schema(ANSWER_FIELDS["automation_orders"])
    automation_properties = automation_order_schema.get("properties")
    if not isinstance(automation_properties, dict):
        raise RuntimeError("automation_orders field schema must expose properties")
    conditions: list[dict[str, object]] = [
        _mode_requirement("minimal", REQUIRED_KEYS_MINIMAL),
        _mode_requirement("full", REQUIRED_KEYS_FULL),
    ]
    for spec in ANSWER_FIELD_SPECS:
        if spec.active_when is None:
            continue
        conditions.append(
            {
                "if": {"required": [spec.name]},
                "then": {
                    "required": [spec.active_when],
                    "properties": {spec.active_when: {"const": True}},
                },
            }
        )
    conditions.extend(
        [
            {
                "if": {
                    "required": ["include_source_update"],
                    "properties": {"include_source_update": {"const": True}},
                },
                "then": {
                    "required": ["include_source_packs"],
                    "properties": {"include_source_packs": {"const": True}},
                },
            },
            {
                "if": {"required": ["security_policy_terms"]},
                "then": {
                    "required": ["security_policy_file"],
                    "properties": {
                        "security_policy_file": {"const": "inline in this SOW"}
                    },
                },
            },
            {
                "if": {
                    "required": ["security_policy_file"],
                    "properties": {
                        "security_policy_file": {"const": "inline in this SOW"}
                    },
                },
                "then": {
                    "required": ["security_policy_terms"],
                    "properties": {
                        "security_policy_terms": {
                            "oneOf": [
                                {"type": "string", "pattern": "\\S"},
                                {
                                    "type": "array",
                                    "minItems": 1,
                                    "items": {"type": "string", "pattern": "\\S"},
                                },
                            ]
                        }
                    },
                },
            },
            {
                "if": {"required": ["minimal_deferrals"]},
                "then": {
                    "required": ["bootstrap_mode"],
                    "properties": {"bootstrap_mode": {"const": "minimal"}},
                },
            },
            {
                "if": {
                    "required": ["include_automation_orders"],
                    "properties": {"include_automation_orders": {"const": True}},
                },
                "then": {
                    "required": ["automation_orders"],
                    "properties": {
                        "automation_orders": {
                            **automation_order_schema,
                            "required": ["jobs"],
                            "properties": {
                                **automation_properties,
                                "jobs": {
                                    "type": "array",
                                    "minItems": 1,
                                    "items": _automation_job_schema(),
                                },
                            },
                        }
                    },
                },
            },
        ]
    )
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "project_bootstrap_answers.schema.json",
        "title": "Master Prompt Agreement project bootstrap answers",
        "description": (
            "Closed structural contract for scripts/project_bootstrap.py. Python remains "
            "authoritative for contextual checks that JSON Schema cannot prove, including "
            "filesystem boundaries, runner grammar, placeholder rejection, current dates, "
            "automation cross-field semantics, and local-state leak detection."
        ),
        "type": "object",
        "additionalProperties": False,
        "properties": {
            spec.name: _field_schema(spec) for spec in ANSWER_FIELD_SPECS
        },
        "required": sorted(REQUIRED_KEYS_MINIMAL),
        "allOf": conditions,
        "x-mpa-model-version": MODEL_SCHEMA_VERSION,
        "x-mpa-runtime-validator": "scripts/project_bootstrap.py",
    }


def _definition_blueprint_lines(surface: str, *, prefix: str = "") -> list[str]:
    specs = SOW_DEFINITION_SPECS if surface == "sow" else PROJECT_DEFINITION_SPECS
    return [f"{prefix}{spec.label}: [{spec.hint}]" for spec in specs]


def _render_sections(specs: tuple[SectionSpec, ...], *, heading: str) -> list[str]:
    lines: list[str] = []
    for spec in specs:
        title = f"{heading} {spec.title}" if heading else spec.title
        lines.extend([title, ""])
        for line in spec.blueprint_lines:
            if line == "{FRAMEWORK_VERIFICATION_COMMANDS}":
                lines.extend(
                    framework_verification_command_lines(
                        FRAMEWORK_REFERENCE_TEMPLATE_PLACEHOLDER,
                        runner="[confirmed framework verification runner]",
                    )
                )
            elif line == "{PROJECT_DEFINITIONS}":
                lines.extend(_definition_blueprint_lines("project", prefix="- "))
            else:
                lines.append(line)
        lines.append("")
    return lines


def render_sow_blueprint() -> str:
    lines = [
        "<!-- Generated from scripts/project_contract_model.py; do not edit directly. -->",
        CONTRACT_FORMAT_MARKER,
        "Statement of Work — [PROJECT NAME]",
        "",
        "Recommended output filename: `STATEMENT_OF_WORK.md`",
        "",
        "SOW Version: [version]  MSA Reference: master_service_agreement.md [version]  Date: [YYYY-MM-DD]",
        "",
        SOW_OPTIONAL_DEFAULT_RULE,
        "",
        "This generated blueprint is the human-readable projection of the declarative contract model in `scripts/project_contract_model.py`. `scripts/project_bootstrap.py` renders concrete values; do not invent unsupported answer keys or treat unfilled placeholders as policy.",
        "",
        "Definitions",
        "",
        SOW_DEFINITION_INDEX_RULE,
        "",
        *_definition_blueprint_lines("sow"),
        "",
        *_render_sections(SOW_SECTION_SPECS, heading=""),
    ]
    return "\n".join(lines).rstrip() + "\n"


def render_project_blueprint() -> str:
    lines = [
        "<!-- Generated from scripts/project_contract_model.py; do not edit directly. -->",
        CONTRACT_FORMAT_MARKER,
        "# Runtime Project Contract Template",
        "",
        "<!-- mpa-clause-projections: msa-2-6 msa-article-5 msa-article-6 msa-article-9 -->",
        "Recommended output filename: `AGENT_PROJECT.md`",
        "Source: distilled from `STATEMENT_OF_WORK.md`",
        "",
        "Project: [PROJECT NAME]",
        "Date: [YYYY-MM-DD]",
        "",
        PROJECT_PREAMBLE_RULE,
        PROJECT_OPTIONAL_OMISSION_RULE,
        "",
        PROJECT_AUTHORITY_TEXT,
        "",
        *_render_sections(PROJECT_SECTION_SPECS, heading="##"),
    ]
    return "\n".join(lines).rstrip() + "\n"


def generated_assets() -> dict[str, str]:
    return {
        ANSWER_SCHEMA_PATH: json.dumps(
            answer_json_schema(),
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        SOW_BLUEPRINT_PATH: render_sow_blueprint(),
        PROJECT_BLUEPRINT_PATH: render_project_blueprint(),
    }


def generated_asset_errors(root: Path = REPO_ROOT) -> list[str]:
    errors = validate_model()
    for relative, expected in generated_assets().items():
        path = root / relative
        try:
            actual = safe_paths.read_regular_file_bytes(
                path,
                description=f"generated project-contract asset {relative}",
                max_bytes=safe_paths.DEFAULT_JSON_INPUT_MAX_BYTES,
            ).decode("utf-8")
        except FileNotFoundError:
            errors.append(f"generated project-contract asset is missing: {relative}")
            continue
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            errors.append(
                f"generated project-contract asset could not be read safely: "
                f"{relative}: {exc}"
            )
            continue
        if actual != expected:
            errors.append(
                f"generated project-contract asset is stale: {relative}; run "
                "`uv run python -E -S -B -- \"scripts/project_contract_model.py\" --write`"
            )
    return errors


def _projection_target_errors(field: str, targets: tuple[str, ...]) -> list[str]:
    errors: list[str] = []
    definition_labels = {spec.label for spec in DEFINITION_SPECS}
    state_files = set(STATE_TEMPLATES)
    for target in targets:
        kind, separator, value = target.partition(":")
        if not separator or not value:
            errors.append(f"field projection {field!r} has malformed target: {target!r}")
        elif kind == "sow" and value not in SOW_SECTIONS:
            errors.append(f"field projection {field!r} names unknown SOW section: {value}")
        elif kind == "project" and value not in PROJECT_SECTIONS:
            errors.append(f"field projection {field!r} names unknown project section: {value}")
        elif kind == "definition" and value not in definition_labels:
            errors.append(f"field projection {field!r} names unknown Definition: {value}")
        elif kind == "state" and value not in state_files:
            errors.append(f"field projection {field!r} names unknown state file: {value}")
        elif kind not in {"control", "definition", "header", "project", "sow", "state"}:
            errors.append(f"field projection {field!r} uses unknown target kind: {kind}")
    return errors


def validate_model() -> list[str]:
    errors: list[str] = structured_field_spec_errors()
    if set(ANNEX_LABELS) != set(ANNEX_KEYS):
        errors.append("annex labels and accepted annex keys differ")
    if set(ANNEX_IDENTITY_BY_KEY) != set(ANNEX_KEYS):
        errors.append("annex identities and accepted annex keys differ")
    if len(set(ANNEX_IDENTITY_BY_KEY.values())) != len(ANNEX_IDENTITY_BY_KEY):
        errors.append("annex identities must be unique")
    expected_annex_identities = {
        *ANNEX_IDENTITY_BY_KEY.values(),
        SECURITY_POLICY_ANNEX_IDENTITY,
    }
    if set(ANNEX_LABEL_BY_IDENTITY) != expected_annex_identities:
        errors.append("annex identity labels do not cover the canonical annex set")
    if len(ANNEX_IDENTITY_BY_LABEL) != len(ANNEX_LABEL_BY_IDENTITY):
        errors.append("canonical annex labels must be unique")
    if "security" in ANNEX_KEYS:
        errors.append(
            "security policy must be owned only by security_policy_file, not annexes"
        )
    if set(STRUCTURED_IDENTITY_FIELDS) != set(STRUCTURED_IDENTITY_DELIMITERS):
        errors.append("structured identity fields and delimiters differ")
    if set(STRUCTURED_COLLECTION_FIELDS) != set(STRUCTURED_IDENTITY_FIELDS):
        errors.append(
            "structured collection fields and identity declarations differ"
        )
    for collection, accepted in (
        ("auxiliary_tools", AUXILIARY_TOOL_KEYS),
        ("command_restrictions", RESTRICTION_KEYS),
        ("workflows", WORKFLOW_KEYS),
    ):
        if STRUCTURED_COLLECTION_FIELDS.get(collection) != accepted:
            errors.append(
                f"structured collection {collection!r} field ledger differs from "
                "its model-owned field specs"
            )
    unknown_row_delimiter_collections = sorted(
        set(STRUCTURED_ROW_DELIMITERS) - set(STRUCTURED_IDENTITY_FIELDS)
    )
    if unknown_row_delimiter_collections:
        errors.append(
            "structured row delimiters name collections without identities: "
            f"{unknown_row_delimiter_collections}"
        )
    for collection, field in STRUCTURED_IDENTITY_FIELDS.items():
        answer_spec = ANSWER_FIELDS.get(collection)
        if answer_spec is None or answer_spec.kind != collection:
            errors.append(
                f"structured identity collection is not a matching answer kind: {collection}"
            )
        if not field.strip() or not STRUCTURED_IDENTITY_DELIMITERS[collection]:
            errors.append(
                f"structured identity declaration is incomplete: {collection}"
            )
        elif field not in STRUCTURED_COLLECTION_FIELDS.get(collection, frozenset()):
            errors.append(
                f"structured identity names an unknown field: {collection}.{field}"
            )
        if collection in STRUCTURED_ROW_DELIMITERS and not STRUCTURED_ROW_DELIMITERS[
            collection
        ]:
            errors.append(
                f"structured row-delimiter declaration is incomplete: {collection}"
            )
    for (collection, field), delimiters in STRUCTURED_FIELD_DELIMITERS.items():
        if collection not in STRUCTURED_IDENTITY_FIELDS:
            errors.append(
                "structured field delimiter names a collection without an identity: "
                f"{collection}.{field}"
            )
        elif field not in STRUCTURED_COLLECTION_FIELDS[collection]:
            errors.append(
                f"structured field delimiter names an unknown field: "
                f"{collection}.{field}"
            )
        if not delimiters or any(not delimiter for delimiter in delimiters):
            errors.append(
                f"structured field-delimiter declaration is incomplete: "
                f"{collection}.{field}"
            )
    if not AUXILIARY_CONTROL_COVERAGE_ROLES:
        errors.append("auxiliary control coverage roles must not be empty")
    if not AUXILIARY_CONTROL_COVERAGE_ROLES <= AUXILIARY_CONTROL_ROLES:
        errors.append("auxiliary control coverage roles must be declared control roles")
    if "none" in AUXILIARY_CONTROL_COVERAGE_ROLES:
        errors.append("auxiliary non-control role must not require control coverage")
    field_names = [spec.name for spec in ANSWER_FIELD_SPECS]
    answer_fields = {spec.name: spec for spec in ANSWER_FIELD_SPECS}
    duplicate_fields = sorted(
        {name for name in field_names if field_names.count(name) > 1}
    )
    if duplicate_fields:
        errors.append(f"duplicate answer field declarations: {duplicate_fields}")
    if set(FIELD_PROJECTIONS) != set(field_names):
        missing = sorted(set(field_names) - set(FIELD_PROJECTIONS))
        unknown = sorted(set(FIELD_PROJECTIONS) - set(field_names))
        if missing:
            errors.append(f"answer fields missing semantic projections: {missing}")
        if unknown:
            errors.append(f"semantic projections name unknown answer fields: {unknown}")
    if set(RUNTIME_FIELD_OWNERS) != set(field_names):
        missing = sorted(set(field_names) - set(RUNTIME_FIELD_OWNERS))
        unknown = sorted(set(RUNTIME_FIELD_OWNERS) - set(field_names))
        if missing:
            errors.append(f"answer fields missing primary runtime owners: {missing}")
        if unknown:
            errors.append(f"primary runtime owners name unknown answer fields: {unknown}")
    for field, owner in RUNTIME_FIELD_OWNERS.items():
        projection_targets = FIELD_PROJECTIONS.get(field, ())
        runtime_targets = {
            target
            for target in projection_targets
            if target.startswith(("project:", "state:"))
        }
        kind, separator, value = owner.partition(":")
        if kind == "header":
            runtime_targets.update(
                target
                for target in projection_targets
                if target.startswith("header:")
            )
        if owner == "canonical-only":
            if runtime_targets:
                errors.append(
                    f"canonical-only answer field {field!r} declares runtime projections: "
                    f"{sorted(runtime_targets)}"
                )
            continue
        if not separator or not value:
            errors.append(f"answer field {field!r} has malformed runtime owner: {owner!r}")
        elif kind == "project" and value not in PROJECT_SECTIONS:
            errors.append(
                f"answer field {field!r} names unknown project runtime owner: {value}"
            )
        elif kind == "state" and value not in STATE_TEMPLATES:
            errors.append(
                f"answer field {field!r} names unknown state runtime owner: {value}"
            )
        elif kind == "header" and not value.strip():
            errors.append(f"answer field {field!r} has blank runtime header owner")
        elif kind not in {"project", "state", "header"}:
            errors.append(
                f"answer field {field!r} uses unknown runtime owner kind: {kind}"
            )
        if runtime_targets != {owner}:
            errors.append(
                f"answer field {field!r} direct runtime projections {sorted(runtime_targets)} "
                f"must equal its sole owner {owner!r}"
            )
    for field, targets in FIELD_PROJECTIONS.items():
        if not targets:
            errors.append(f"answer field has no semantic projection targets: {field}")
        errors.extend(_projection_target_errors(field, targets))
    for spec in ANSWER_FIELD_SPECS:
        if spec.active_when is not None:
            flag = answer_fields.get(spec.active_when)
            if flag is None or flag.kind != "boolean":
                errors.append(
                    f"answer field {spec.name!r} has unknown/non-boolean active flag: {spec.active_when!r}"
                )
    grammar_keys = [spec.answer_key for spec in ANSWER_TEXT_GRAMMAR_SPECS]
    if len(grammar_keys) != len(set(grammar_keys)):
        errors.append("duplicate answer text-grammar declarations")
    for label, pattern in GENERATED_SOW_CONTROL_LINE_SYNTAX:
        if not label.strip():
            errors.append("generated SOW control grammar has a blank syntax label")
        try:
            re.compile(pattern)
        except re.error as exc:
            errors.append(f"generated SOW control grammar is invalid: {exc}")
    for grammar in ANSWER_TEXT_GRAMMAR_SPECS:
        field = answer_fields.get(grammar.answer_key)
        if field is None:
            errors.append(
                f"answer text grammar names unknown field: {grammar.answer_key}"
            )
            continue
        structured_members = {
            "command_restrictions": RESTRICTION_KEYS,
            "commands": COMMAND_KEYS,
            "workflows": WORKFLOW_KEYS,
        }
        if grammar.member_keys:
            available_members = structured_members.get(field.kind)
            if available_members is None:
                errors.append(
                    "answer text grammar member rules require a supported structured "
                    f"field: {grammar.answer_key}"
                )
            else:
                unknown_members = sorted(grammar.member_keys - available_members)
                if unknown_members:
                    errors.append(
                        f"answer text grammar names unknown members for {grammar.answer_key}: "
                        f"{unknown_members}"
                    )
        else:
            if grammar.forbidden_exact_lines and field.kind != "lines":
                errors.append(
                    f"answer text grammar exact-line rules require a lines field: {grammar.answer_key}"
                )
            if grammar.forbidden_substrings and field.kind != "string":
                errors.append(
                    f"answer text grammar substring rules require a string field: {grammar.answer_key}"
                )
            if grammar.forbidden_line_syntax and field.kind not in {"lines", "string"}:
                errors.append(
                    "answer text grammar line-syntax rules require a text field: "
                    f"{grammar.answer_key}"
                )
        for label, pattern in grammar.forbidden_line_syntax:
            if not label.strip():
                errors.append(
                    f"answer text grammar has a blank line-syntax label: {grammar.answer_key}"
                )
            try:
                re.compile(rf"^(?:{pattern})")
            except re.error as exc:
                errors.append(
                    f"answer text grammar has invalid line syntax for {grammar.answer_key}: {exc}"
                )
    for attribute in ("answer_key", "sow_label", "runtime_label", "deferral_field"):
        values = [getattr(spec, attribute) for spec in COMMAND_SPECS]
        if any(not value.strip() for value in values):
            errors.append(f"command declarations contain blank {attribute}")
        if len(values) != len(set(values)):
            errors.append(f"command declarations contain duplicate {attribute}")
    definition_labels = [spec.label for spec in DEFINITION_SPECS]
    definition_specs_by_label = {spec.label: spec for spec in DEFINITION_SPECS}
    duplicate_definitions = sorted(
        {label for label in definition_labels if definition_labels.count(label) > 1}
    )
    if duplicate_definitions:
        errors.append(f"duplicate Definition declarations: {duplicate_definitions}")
    command_projection_labels = {
        spec.label for spec in DEFINITION_SPECS if spec.projection == "command"
    }
    if command_projection_labels != COMMAND_DEFINITION_FIELDS:
        errors.append(
            "command Definition projections do not match command deferral fields"
        )
    project_section_keys = {section.key for section in PROJECT_SECTION_SPECS}
    if set(PROJECT_SECTION_ROW_STYLES) != project_section_keys:
        errors.append("project runtime row styles do not cover every project section")
    if not set(PROJECT_SECTION_ROW_STYLES.values()) <= {
        "bullet",
        "numbered",
        "scope",
    }:
        errors.append("project runtime row styles contain an unknown grammar")
    sow_section_keys = {section.key for section in SOW_SECTION_SPECS}
    if set(SOW_SECTION_ROW_STYLES) != sow_section_keys:
        errors.append("SOW row styles do not cover every SOW section")
    if not set(SOW_SECTION_ROW_STYLES.values()) <= {
        "arbitration-panel",
        "automation",
        "bullet",
        "command-restrictions",
        "commands",
        "direct-panel-rules",
        "free-form",
        "labeled",
        "numbered",
        "policy-bullet",
        "scope",
        "technical-specifications",
        "workflows",
    }:
        errors.append("SOW row styles contain an unknown grammar")
    if SOW_FREE_FORM_SECTION_KEYS != {"recitals"}:
        errors.append("Recitals must be the sole free-form SOW section")
    if SOW_SECTION_ROW_STYLES.get("technical_specifications") != (
        "technical-specifications"
    ):
        errors.append(
            "Technical Specifications must own the bounded file-structure tail grammar"
        )
    for spec in SOW_SECTION_SPECS:
        missing_policy = sorted(set(spec.policy_lines) - set(spec.blueprint_lines))
        if missing_policy:
            errors.append(
                f"SOW section {spec.key!r} policy lines are absent from its blueprint"
            )
        if spec.sow_row_style == "labeled" and not sow_blueprint_labeled_row_labels(
            spec.key
        ):
            errors.append(
                f"SOW labeled-row section {spec.key!r} has no model-owned labels"
            )
    expected_labeled_edges = {
        (spec.key, label)
        for spec in SOW_SECTION_SPECS
        if spec.sow_row_style == "labeled"
        for label in sow_blueprint_labeled_row_labels(spec.key)
    }
    declared_labeled_edges = [
        (spec.section_key, spec.label) for spec in SOW_LABELED_FIELD_SPECS
    ]
    duplicate_labeled_edges = sorted(
        {
            edge
            for edge in declared_labeled_edges
            if declared_labeled_edges.count(edge) > 1
        }
    )
    if duplicate_labeled_edges:
        errors.append(
            "SOW labeled-field semantic owners contain duplicate edges: "
            f"{duplicate_labeled_edges}"
        )
    missing_labeled_edges = sorted(
        expected_labeled_edges - set(declared_labeled_edges)
    )
    unknown_labeled_edges = sorted(
        set(declared_labeled_edges) - expected_labeled_edges
    )
    if missing_labeled_edges:
        errors.append(
            "SOW labeled fields missing semantic owners: "
            f"{missing_labeled_edges}"
        )
    if unknown_labeled_edges:
        errors.append(
            "SOW labeled semantic owners name unknown blueprint fields: "
            f"{unknown_labeled_edges}"
        )
    for field_spec in SOW_LABELED_FIELD_SPECS:
        definition_spec = (
            definition_specs_by_label.get(field_spec.definition_label)
            if field_spec.definition_label is not None
            else None
        )
        if field_spec.semantic_owner == "definition-parity":
            if definition_spec is None:
                errors.append(
                    "SOW labeled Definition-parity owner names an unknown Definition: "
                    f"{field_spec.section_key}.{field_spec.label} -> "
                    f"{field_spec.definition_label!r}"
                )
            elif (
                field_spec.definition_label in DECLARED_OPTIONAL_STATE
                and field_spec.comparison != "exact"
            ):
                errors.append(
                    "SOW labeled optional-state identity must use exact comparison: "
                    f"{field_spec.section_key}.{field_spec.label}"
                )
        elif field_spec.semantic_owner == "shared-source-reference":
            if field_spec.definition_label is not None:
                errors.append(
                    "shared-source-reference owner must not name a Definition: "
                    f"{field_spec.section_key}.{field_spec.label}"
                )
            if field_spec.comparison != "normalized":
                errors.append(
                    "shared-source-reference owner must use normalized comparison: "
                    f"{field_spec.section_key}.{field_spec.label}"
                )
        else:
            errors.append(
                "SOW labeled field uses unknown semantic owner: "
                f"{field_spec.section_key}.{field_spec.label} -> "
                f"{field_spec.semantic_owner!r}"
            )
        if field_spec.section_absence == "use-definition-default" and (
            definition_spec is None
            or rendered_definition_default(definition_spec) is None
        ):
            errors.append(
                "SOW labeled field default-on-absence policy requires a concrete "
                f"Definition default: {field_spec.section_key}.{field_spec.label}"
            )

    state_projection_edges = [
        (
            spec.sow_section_key,
            spec.filename,
            spec.state_section,
            spec.state_key,
        )
        for spec in STATE_DEFINITION_PROJECTION_SPECS
    ]
    duplicate_state_projection_edges = sorted(
        {
            edge
            for edge in state_projection_edges
            if state_projection_edges.count(edge) > 1
        }
    )
    if duplicate_state_projection_edges:
        errors.append(
            "state Definition projections contain duplicate edges: "
            f"{duplicate_state_projection_edges}"
        )
    for projection in STATE_DEFINITION_PROJECTION_SPECS:
        if projection.sow_section_key not in SOW_SECTIONS:
            errors.append(
                "state Definition projection names unknown SOW section: "
                f"{projection.sow_section_key}"
            )
        if projection.filename not in STATE_TEMPLATES:
            errors.append(
                "state Definition projection names unknown state file: "
                f"{projection.filename}"
            )
        if projection.definition_label not in definition_specs_by_label:
            errors.append(
                "state Definition projection names unknown Definition: "
                f"{projection.definition_label}"
            )
    definition_placeholder_edges = {
        (spec.filename, spec.definition_label)
        for spec in STATE_TEMPLATE_PLACEHOLDER_SPECS
        if spec.semantic_owner == "definition-parity"
        and spec.definition_label is not None
    }
    state_definition_projection_edges = {
        (spec.filename, spec.definition_label)
        for spec in STATE_DEFINITION_PROJECTION_SPECS
    }
    missing_state_definition_edges = sorted(
        definition_placeholder_edges - state_definition_projection_edges
    )
    surplus_state_definition_edges = sorted(
        state_definition_projection_edges - definition_placeholder_edges
    )
    if missing_state_definition_edges:
        errors.append(
            "state Definition projections are missing definition-parity placeholder "
            f"coverage: {missing_state_definition_edges}"
        )
    if surplus_state_definition_edges:
        errors.append(
            "state Definition projections have no matching definition-parity "
            f"placeholder: {surplus_state_definition_edges}"
        )
    errors.extend(state_template_placeholder_errors())
    for spec in DEFINITION_SPECS:
        answer_field = (
            answer_fields.get(spec.answer_key) if spec.answer_key is not None else None
        )
        if spec.answer_key is not None and answer_field is None:
            errors.append(
                f"Definition {spec.label!r} names unknown answer key: {spec.answer_key}"
            )
        if spec.active_when is not None:
            flag = answer_fields.get(spec.active_when)
            if flag is None or flag.kind != "boolean":
                errors.append(
                    f"Definition {spec.label!r} has unknown/non-boolean active flag: "
                    f"{spec.active_when!r}"
                )
        if answer_field is not None and spec.active_when != answer_field.active_when:
            errors.append(
                f"Definition {spec.label!r} activation gate {spec.active_when!r} does "
                f"not match answer field {spec.answer_key!r} activation gate "
                f"{answer_field.active_when!r}"
            )
        if spec.projection == "answer" and spec.answer_key is None:
            errors.append(
                f"Definition {spec.label!r} uses answer projection without an answer key"
            )
        if spec.projection == "command" and spec.label not in COMMAND_DEFINITION_FIELDS:
            errors.append(f"Definition {spec.label!r} names an unknown command projection")
        if spec.runtime_policy == "when-active" and spec.active_when is None:
            errors.append(
                f"Definition {spec.label!r} uses when-active runtime policy without an activation gate"
            )
        if spec.active_when is not None and spec.runtime_policy not in {
            "when-active",
            "state-owned",
        }:
            errors.append(
                f"Definition {spec.label!r} activation gate requires a conditional runtime policy"
            )
        if (
            spec.runtime_policy == "when-overridden"
            and rendered_definition_default(spec) is None
        ):
            errors.append(
                f"Definition {spec.label!r} uses when-overridden runtime policy without a concrete default"
            )
        if spec.runtime_policy == "section-owned":
            if spec.runtime_owner not in project_section_keys:
                errors.append(
                    f"Definition {spec.label!r} section-owned runtime policy names unknown owner: "
                    f"{spec.runtime_owner!r}"
                )
            if spec.runtime_owner_inclusion not in {
                "always",
                "when-active",
                "when-overridden",
            }:
                errors.append(
                    f"Definition {spec.label!r} section-owned runtime policy has no valid inclusion policy"
                )
            if spec.runtime_owner_style not in {"labeled", "native"}:
                errors.append(
                    f"Definition {spec.label!r} section-owned runtime policy has no valid render style"
                )
            if (
                spec.runtime_owner_inclusion == "when-active"
                and spec.active_when is None
            ):
                errors.append(
                    f"Definition {spec.label!r} section-owned when-active policy has no activation gate"
                )
            if (
                spec.runtime_owner_inclusion == "when-overridden"
                and rendered_definition_default(spec) is None
            ):
                errors.append(
                    f"Definition {spec.label!r} section-owned when-overridden policy has no concrete default"
                )
            if spec.answer_key is not None:
                declared_owner = RUNTIME_FIELD_OWNERS.get(spec.answer_key)
                expected_owner = f"project:{spec.runtime_owner}"
                if declared_owner != expected_owner:
                    errors.append(
                        f"Definition {spec.label!r} runtime owner {expected_owner!r} "
                        f"does not match field owner {declared_owner!r}"
                    )
        elif any(
            value is not None
            for value in (
                spec.runtime_owner,
                spec.runtime_owner_inclusion,
                spec.runtime_owner_style,
            )
        ):
            errors.append(
                f"Definition {spec.label!r} names runtime-owner metadata without section-owned policy"
            )
    for owner in sorted(project_section_keys):
        native_labels = project_blueprint_labeled_row_labels(owner)
        if len(native_labels) != len(set(native_labels)):
            errors.append(
                f"project section {owner!r} has duplicate native labeled-row names"
            )
        owned_labels = {
            spec.label
            for spec in DEFINITION_SPECS
            if spec.runtime_policy == "section-owned"
            and spec.runtime_owner == owner
            and spec.runtime_owner_style == "labeled"
        }
        collisions = sorted(set(native_labels) & owned_labels)
        if collisions:
            errors.append(
                f"project section {owner!r} native and Definition-owned labels collide: "
                f"{collisions}"
            )
    for surface, specs in (
        ("SOW", SOW_SECTION_SPECS),
        ("project", PROJECT_SECTION_SPECS),
    ):
        keys = [spec.key for spec in specs]
        titles = [spec.title for spec in specs]
        if len(keys) != len(set(keys)):
            errors.append(f"duplicate {surface} section keys")
        if len(titles) != len(set(titles)):
            errors.append(f"duplicate {surface} section titles")
        for spec in specs:
            missing_policy = [
                line for line in spec.policy_lines if line not in spec.blueprint_lines
            ]
            if missing_policy:
                errors.append(
                    f"{surface} section {spec.key!r} omits model-owned policy from its blueprint"
                )
    filenames = [spec.filename for spec in OPTIONAL_STATE_SPECS]
    flags = [spec.flag for spec in OPTIONAL_STATE_SPECS]
    optional_definition_labels = [
        spec.definition_label
        for spec in OPTIONAL_STATE_SPECS
        if spec.definition_label is not None
    ]
    if len(filenames) != len(set(filenames)):
        errors.append("duplicate optional-state filenames")
    if len(flags) != len(set(flags)):
        errors.append("duplicate optional-state flags")
    mutable_optional_state = optional_state_filenames("mutable")
    immutable_optional_state = optional_state_filenames("immutable")
    overlapping_optional_state = sorted(
        mutable_optional_state & immutable_optional_state
    )
    if overlapping_optional_state:
        errors.append(
            "optional-state receipt partitions overlap: "
            f"{overlapping_optional_state}"
        )
    unpartitioned_optional_state = sorted(
        set(filenames) - mutable_optional_state - immutable_optional_state
    )
    if unpartitioned_optional_state:
        errors.append(
            "optional-state declarations lack a supported receipt partition: "
            f"{unpartitioned_optional_state}"
        )
    duplicate_optional_definition_labels = sorted(
        {
            label
            for label in optional_definition_labels
            if optional_definition_labels.count(label) > 1
        }
    )
    if duplicate_optional_definition_labels:
        errors.append(
            "duplicate optional-state Definition labels: "
            f"{duplicate_optional_definition_labels}"
        )
    optional_states_by_label: dict[str, list[OptionalStateSpec]] = {}
    for spec in OPTIONAL_STATE_SPECS:
        if spec.partition not in OPTIONAL_STATE_PARTITIONS:
            errors.append(
                f"optional-state declaration {spec.filename!r} has unsupported "
                f"receipt partition: {spec.partition!r}"
            )
        flag = answer_fields.get(spec.flag)
        if flag is None or flag.kind != "boolean":
            errors.append(
                f"optional-state declaration {spec.filename!r} has unknown/non-boolean "
                f"flag: {spec.flag!r}"
            )
        if spec.definition_label is not None:
            optional_states_by_label.setdefault(spec.definition_label, []).append(spec)
    optional_definitions_by_label: dict[str, list[DefinitionSpec]] = {}
    for spec in DEFINITION_SPECS:
        if spec.projection == "optional-state":
            optional_definitions_by_label.setdefault(spec.label, []).append(spec)
    for label, states in optional_states_by_label.items():
        definition_count = len(optional_definitions_by_label.get(label, ()))
        if definition_count != 1:
            for state in states:
                errors.append(
                    f"optional-state declaration {state.filename!r} Definition label "
                    f"{label!r} resolves to {definition_count} optional-state Definitions"
                )
    for label, definitions in optional_definitions_by_label.items():
        state_count = len(optional_states_by_label.get(label, ()))
        if state_count != 1:
            for _definition_spec in definitions:
                errors.append(
                    f"optional-state Definition {label!r} resolves to {state_count} "
                    "optional-state declarations"
                )
    optional_state_definition_by_flag = {
        spec.flag: spec.definition_label
        for spec in OPTIONAL_STATE_SPECS
        if spec.definition_label is not None
    }
    for spec in DEFINITION_SPECS:
        if spec.active_when is None:
            continue
        owner_label = optional_state_definition_by_flag.get(spec.active_when)
        owner_spec = definition_specs_by_label.get(owner_label or "")
        if owner_label is None or owner_spec is None:
            errors.append(
                f"Definition {spec.label!r} activation gate {spec.active_when!r} "
                "does not resolve to one canonical optional-state Definition"
            )
        elif owner_spec.projection != "optional-state":
            errors.append(
                f"Definition {spec.label!r} activation owner {owner_label!r} "
                "is not an optional-state Definition"
            )
        elif (
            owner_spec.runtime_policy != "state-owned"
            or _normalized_definition_value(
                rendered_definition_default(owner_spec) or ""
            )
            != "none"
        ):
            errors.append(
                f"Definition {spec.label!r} activation owner {owner_label!r} "
                "must use a none-default state-owned runtime policy"
            )
    if set(automation_orders_lint.REQUIRED_JOB_KEYS) - set(automation_orders_lint.JOB_KEYS):
        errors.append("automation validator required job keys are outside JOB_KEYS")
    job_schema = _automation_job_schema()
    schema_properties = job_schema.get("properties")
    if not isinstance(schema_properties, dict) or set(schema_properties) != set(
        automation_orders_lint.JOB_KEYS
    ):
        errors.append("generated automation job schema does not match automation validator JOB_KEYS")
    schema_required = job_schema.get("required")
    if not isinstance(schema_required, list) or set(schema_required) != set(
        automation_orders_lint.REQUIRED_JOB_KEYS
    ):
        errors.append(
            "generated automation job schema does not match automation validator REQUIRED_JOB_KEYS"
        )
    if isinstance(schema_properties, dict):
        scheduler_schema = schema_properties.get("scheduler_artifacts")
        scheduler_properties = (
            scheduler_schema.get("properties")
            if isinstance(scheduler_schema, dict)
            else None
        )
        retention_schema = (
            scheduler_properties.get("retention")
            if isinstance(scheduler_properties, dict)
            else None
        )
        retention_properties = (
            retention_schema.get("properties")
            if isinstance(retention_schema, dict)
            else None
        )
        retention_required = (
            retention_schema.get("required")
            if isinstance(retention_schema, dict)
            else None
        )
        if (
            not isinstance(retention_properties, dict)
            or set(retention_properties) != automation_orders_lint.RETENTION_KEYS
            or not isinstance(retention_required, list)
            or set(retention_required) != automation_orders_lint.RETENTION_KEYS
        ):
            errors.append(
                "generated automation retention schema does not match RETENTION_KEYS"
            )
        for field_name in ("instruction_sources", "execution_sources"):
            references_schema = schema_properties.get(field_name)
            reference_schema = (
                references_schema.get("items")
                if isinstance(references_schema, dict)
                else None
            )
            reference_properties = (
                reference_schema.get("properties")
                if isinstance(reference_schema, dict)
                else None
            )
            reference_required = (
                reference_schema.get("required")
                if isinstance(reference_schema, dict)
                else None
            )
            if (
                not isinstance(reference_properties, dict)
                or set(reference_properties)
                != automation_orders_lint.SOURCE_REFERENCE_KEYS
                or not isinstance(reference_required, list)
                or set(reference_required)
                != automation_orders_lint.SOURCE_REFERENCE_KEYS
            ):
                errors.append(
                    f"generated automation {field_name} item schema does not "
                    "match SOURCE_REFERENCE_KEYS"
                )
    return errors


def write_generated_assets(root: Path = REPO_ROOT) -> None:
    errors = validate_model()
    if errors:
        raise ValueError("; ".join(errors))
    result = bootstrap_transaction.transactional_write_outputs(
        root,
        list(generated_assets().items()),
        force=True,
    )
    if result.cleanup_warnings:
        raise RuntimeError(
            "generated assets committed but transaction cleanup was incomplete: "
            + "; ".join(result.cleanup_warnings)
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check or regenerate project-contract model assets.",
        allow_abbrev=False,
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--check",
        action="store_true",
        help="Verify that every generated project-contract asset is current.",
    )
    mode.add_argument(
        "--write",
        action="store_true",
        help="Regenerate the canonical project-contract assets transactionally.",
    )
    args = parser.parse_args()
    if args.write:
        write_generated_assets()
        print("project-contract generated assets updated")
        return 0
    errors = generated_asset_errors()
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("project-contract generated assets are current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
