#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
import re
from typing import cast

import integration_registry
import markdown_structure
import project_contract_model as contract_model
import safe_paths


REPO_ROOT = Path(__file__).resolve().parent.parent
AUTHORING_ENTRYPOINT_FILES = ["AGENTS.md", "CLAUDE.md"]
RUNTIME_CORE_FILES = [
    "runtime/operative_charter.md",
    "runtime/load_order.md",
    "runtime/standards_of_care.md",
]
PROJECT_CONTRACT_TEMPLATE_FILES = ["runtime/project_template.md"]
ENTRYPOINT_FILES = [
    *integration_registry.entrypoint_paths(REPO_ROOT),
]

# These are configured file-size ceilings for files that a runtime may load into
# prompt context. They are not token estimates, quality scores, or targets.
ENTRYPOINT_MAX_BYTES = 8 * 1024
RUNTIME_CORE_MAX_BYTES = 16 * 1024
PROJECT_CONTRACT_TEMPLATE_MAX_BYTES = 16 * 1024
SELECTED_RUNTIME_INPUT_MAX_BYTES = 4 * 1024 * 1024

MEASUREMENT_SCOPE = {
    "purpose": "informational configured file-size-ceiling inventory",
    "reported_values": (
        "full-file UTF-8 byte and line counts for resolved full-load files; "
        "safe presence only for header-only obligations"
    ),
    "limitations": [
        "header-only obligation contents and sizes are not read",
        "file bytes are not tokenizer output or prompt/context cost",
        "file bytes and line counts do not prove compactness, instruction quality, or task quality",
    ],
}

ACTIVE_PROJECT_MODULES_HEADING = "## Active Project Modules"
ACTIVE_PROJECT_MODULE_RE = re.compile(r"^- (?P<label>.+?):\s+(?P<path>.+)$")
KNOWN_PROJECT_MODULE_LABELS = frozenset(
    (*contract_model.ANNEX_LABELS.values(), contract_model.SECURITY_POLICY_ANNEX_LABEL)
)
AUTHORITY_MODULE_LABEL = contract_model.ANNEX_LABELS["authority"]


def loaded_surface_byte_budgets(repo_root: Path = REPO_ROOT) -> dict[str, int]:
    budgets = {
        rel: ENTRYPOINT_MAX_BYTES for rel in AUTHORING_ENTRYPOINT_FILES
    }
    budgets.update({rel: RUNTIME_CORE_MAX_BYTES for rel in RUNTIME_CORE_FILES})
    budgets.update(
        {
            rel: PROJECT_CONTRACT_TEMPLATE_MAX_BYTES
            for rel in PROJECT_CONTRACT_TEMPLATE_FILES
        }
    )
    budgets.update(
        {
            rel: ENTRYPOINT_MAX_BYTES
            for rel in integration_registry.entrypoint_paths(repo_root)
        }
    )
    return budgets


def loaded_surface_budget_errors(
    repo_root: Path,
    budgets: dict[str, int] | None = None,
) -> list[str]:
    errors: list[str] = []
    selected_budgets = (
        loaded_surface_byte_budgets(repo_root) if budgets is None else budgets
    )
    for rel, limit in sorted(selected_budgets.items()):
        path = repo_root / rel
        if not path.is_file() or path.is_symlink():
            continue
        size = path.stat().st_size
        if size > limit:
            errors.append(
                f"configured loaded-surface file-size ceiling exceeded: {rel} has "
                f"{size} UTF-8 bytes, limit is {limit}"
            )
    return errors


def load_text(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def report_group(
    files: list[str],
    budgets: dict[str, int],
) -> dict[str, object]:
    details = []
    for rel in files:
        text = load_text(rel)
        byte_count = len(text.encode("utf-8"))
        detail: dict[str, object] = {
            "bytes": byte_count,
            "lines": len(text.splitlines()),
            "path": rel,
        }
        if rel in budgets:
            detail["max_bytes"] = budgets[rel]
            detail["within_byte_budget"] = byte_count <= budgets[rel]
        details.append(detail)
    return {
        "files": details,
        "total_bytes": sum(item["bytes"] for item in details),
        "total_lines": sum(item["lines"] for item in details),
    }


def duplicate_lines(files: list[str]) -> list[dict[str, object]]:
    counter: Counter[str] = Counter()
    for rel in files:
        for line in load_text(rel).splitlines():
            normalized = line.strip()
            if normalized and not normalized.startswith("#") and len(normalized) > 20:
                counter[normalized] += 1
    return [
        {"count": count, "line": line}
        for line, count in counter.most_common()
        if count > 1
    ][:10]


def eager_practice_guide_imports() -> list[str]:
    findings: list[str] = []
    for rel in ENTRYPOINT_FILES:
        text = load_text(rel)
        for line in text.splitlines():
            if "practice_guides/" in line and line.strip().startswith("@"):
                findings.append(f"{rel}: {line.strip()}")
    return findings


def framework_source_inventory() -> dict[str, object]:
    """Report configured framework-owned source surfaces.

    This framework-source inventory intentionally includes every integration
    template. It is not a selected downstream runtime closure.
    """

    budgets = loaded_surface_byte_budgets(REPO_ROOT)
    runtime_files = RUNTIME_CORE_FILES + ENTRYPOINT_FILES
    return {
        "mode": "framework_source_inventory",
        "measurement_scope": MEASUREMENT_SCOPE,
        "authoring_entrypoints": report_group(AUTHORING_ENTRYPOINT_FILES, budgets),
        "budget_errors": loaded_surface_budget_errors(REPO_ROOT, budgets),
        "duplicate_lines": duplicate_lines(runtime_files),
        "eager_practice_guide_imports": eager_practice_guide_imports(),
        "entrypoints": report_group(ENTRYPOINT_FILES, budgets),
        "native_wrapper_candidates": [
            guide["name"]
            for guide in safe_paths.loads_json_no_duplicates((REPO_ROOT / "runtime/operative_schedule.json").read_text(encoding="utf-8"))[
                "practice_guides"
            ]
            if guide.get("wrapper_status") in {"candidate", "required"}
        ],
        "project_contract_templates": report_group(
            PROJECT_CONTRACT_TEMPLATE_FILES,
            budgets,
        ),
        "runtime_core": report_group(RUNTIME_CORE_FILES, budgets),
    }


def normalized_contract_root(value: str, project_root: Path) -> str:
    if value == ".":
        return value
    return safe_paths.normalize_repo_relative_path(
        value,
        project_root,
        description="contract root",
    )


def contract_relative_path(contract_root: str, name: str) -> str:
    return name if contract_root == "." else f"{contract_root}/{name}"


def read_report_file(
    root: Path,
    relative_path: str,
    *,
    source: str,
    role: str,
    load_mode: str,
) -> tuple[dict[str, object], str | None, str | None]:
    record: dict[str, object] = {
        "load_mode": load_mode,
        "path": relative_path,
        "role": role,
        "source": source,
    }
    try:
        path = safe_paths.safe_relative_child(
            root,
            Path(relative_path),
            description=f"{role} path",
        )
    except ValueError as exc:
        record["status"] = "unsafe"
        return record, None, str(exc)

    if not path.exists() and not path.is_symlink():
        record["status"] = "missing"
        return record, None, f"missing mandatory {role}: {source}:{relative_path}"

    try:
        raw = safe_paths.read_regular_file_bytes(
            path,
            description=f"{role} file",
            max_bytes=SELECTED_RUNTIME_INPUT_MAX_BYTES,
        )
        text = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        record["status"] = "unreadable"
        return record, None, f"could not read mandatory {role} {source}:{relative_path}: {exc}"

    record.update(
        {
            "file_bytes": len(raw),
            "file_lines": len(text.splitlines()),
            "status": "resolved",
        }
    )
    return record, text, None


def active_project_modules(contract_text: str) -> tuple[list[dict[str, str]], list[str]]:
    lines = contract_text.splitlines()
    operative_by_index = {
        line_number - 1: line
        for line_number, line in markdown_structure.operative_lines(contract_text)
    }

    heading_indexes = [
        index
        for index, line in operative_by_index.items()
        if line == ACTIVE_PROJECT_MODULES_HEADING
    ]
    if not heading_indexes:
        return [], []
    if len(heading_indexes) > 1:
        return [], [
            "duplicate top-level Active Project Modules headings make module loading ambiguous"
        ]
    start = heading_indexes[0] + 1

    modules: list[dict[str, str]] = []
    errors: list[str] = []
    seen_labels: set[str] = set()
    for index, _raw_line in enumerate(lines[start:], start=start):
        line = operative_by_index.get(index)
        if line is None:
            continue
        if line.startswith("## "):
            break
        stripped = line.strip()
        if not stripped:
            continue
        match = ACTIVE_PROJECT_MODULE_RE.fullmatch(stripped)
        if match is None:
            errors.append(f"unrecognized Active Project Modules entry: {stripped}")
            continue
        label = match.group("label").strip()
        path = match.group("path").strip().strip("`")
        if not label or not path:
            errors.append(f"incomplete Active Project Modules entry: {stripped}")
            continue
        if label not in KNOWN_PROJECT_MODULE_LABELS:
            errors.append(f"unknown Active Project Modules label: {label}")
            continue
        if label in seen_labels:
            errors.append(f"duplicate Active Project Modules label: {label}")
            continue
        seen_labels.add(label)
        modules.append({"label": label, "path": path})
    return modules, errors


def dynamic_load_rules(contract_root: str) -> list[dict[str, object]]:
    statement_of_work = contract_relative_path(
        contract_root,
        "STATEMENT_OF_WORK.md",
    )
    return [
        {
            "category": "canonical_project_source",
            "path": statement_of_work,
            "reason_unresolved": (
                "load only for project-contract ambiguity, interpretation, or revision"
            ),
            "source": "project",
        },
        {
            "category": "canonical_framework_source",
            "path": "master_service_agreement.md",
            "reason_unresolved": (
                "load only for framework-rule interpretation, ambiguity, or revision"
            ),
            "source": "framework",
        },
        {
            "category": "project_state_full_records",
            "governed_by": "runtime/operative_charter.md Article 5",
            "reason_unresolved": (
                "full state depends on current-task relevance, scope, privacy, "
                "and approval limits"
            ),
        },
        {
            "category": "workflow_procedure",
            "governed_by": "selected runtime entrypoint and runtime/load_order.md",
            "reason_unresolved": (
                "workflow identity and compact-versus-full routing require "
                "current-task evidence"
            ),
        },
        {
            "category": "practice_guides",
            "governed_by": "selected runtime entrypoint and runtime/load_order.md",
            "reason_unresolved": (
                "guide selection requires current-task domain and risk characteristics"
            ),
        },
        {
            "category": "task_evidence_and_tool_results",
            "governed_by": "runtime/operative_charter.md Articles 4 and 6",
            "reason_unresolved": (
                "evidence scope and tool results require the current task and authority"
            ),
        },
    ]


def header_only_obligation(
    root: Path,
    relative_path: str,
) -> tuple[dict[str, object] | None, str | None]:
    record: dict[str, object] = {
        "load_mode": "header_only",
        "path": relative_path,
        "role": "startup_state_header",
        "source": "project",
    }
    try:
        path = safe_paths.safe_relative_child(
            root,
            Path(relative_path),
            description="startup state header path",
        )
    except ValueError as exc:
        record["status"] = "unsafe"
        return record, str(exc)
    if not path.exists() and not path.is_symlink():
        return None, None
    errors = safe_paths.bounded_input_errors(
        path,
        root,
        description="startup state header",
    )
    if errors:
        record["status"] = "unsafe"
        return record, "; ".join(errors)
    record["status"] = "present_not_read"
    return record, None


def selected_runtime_load_surface(
    project_root: Path,
    runtime: str,
    contract_root: str = ".",
) -> dict[str, object]:
    """Resolve one concrete downstream runtime's mandatory file closure."""

    if runtime not in integration_registry.family_names(REPO_ROOT):
        raise ValueError(f"unsupported runtime: {runtime}")

    root = project_root.expanduser().absolute()
    root_errors = safe_paths.bounded_input_errors(
        root,
        root,
        description="project root",
        expected_kind="directory",
    )
    if not root.exists():
        root_errors.append(f"project root does not exist: {root}")
    elif not root.is_dir():
        root_errors.append(f"project root must be a directory: {root}")
    if root_errors:
        raise ValueError("; ".join(dict.fromkeys(root_errors)))

    selected_contract_root = normalized_contract_root(contract_root, root)
    config = integration_registry.family_config(runtime, REPO_ROOT)
    entrypoint_config = cast(dict[str, object], config["entrypoint"])
    entrypoint_path = cast(str, entrypoint_config["output"])
    contract_path = contract_relative_path(selected_contract_root, "AGENT_PROJECT.md")

    errors: list[str] = []
    mandatory_files: list[dict[str, object]] = []
    entrypoint_record, entrypoint_text, error = read_report_file(
        root,
        entrypoint_path,
        source="project",
        role="selected_runtime_entrypoint",
        load_mode="full",
    )
    mandatory_files.append(entrypoint_record)
    if error is not None:
        errors.append(error)
    elif entrypoint_text is not None and contract_path not in entrypoint_text:
        errors.append(
            f"selected runtime entrypoint {entrypoint_path} does not reference {contract_path}"
        )

    framework_reference: str | None = None
    framework_root: Path | None = None
    if entrypoint_text is not None:
        references = list(
            dict.fromkeys(safe_paths.extract_framework_references(entrypoint_text))
        )
        if not references:
            errors.append(
                f"selected runtime entrypoint {entrypoint_path} has no "
                "operative-charter framework reference"
            )
        elif len(references) > 1:
            errors.append(
                f"selected runtime entrypoint {entrypoint_path} has conflicting framework references: "
                + ", ".join(references)
            )
        else:
            framework_reference = references[0]
            framework_root = safe_paths.resolve_framework_reference(
                framework_reference,
                root,
            )
            if framework_root is None:
                errors.append(
                    "operative-charter framework reference is unresolved in this "
                    f"environment: {framework_reference}"
                )
            else:
                charter_record, _, charter_error = read_report_file(
                    framework_root,
                    "runtime/operative_charter.md",
                    source="framework",
                    role="operative_charter",
                    load_mode="full",
                )
                mandatory_files.append(charter_record)
                if charter_error is not None:
                    errors.append(charter_error)

    contract_record, contract_text, contract_error = read_report_file(
        root,
        contract_path,
        source="project",
        role="project_contract",
        load_mode="full",
    )
    mandatory_files.append(contract_record)
    if contract_error is not None:
        errors.append(contract_error)

    unresolved_dynamic_loads: list[dict[str, object]] = []
    if contract_text is not None:
        modules, module_errors = active_project_modules(contract_text)
        errors.extend(module_errors)
        for module in modules:
            label = module["label"]
            raw_path = module["path"]
            reference_errors = safe_paths.project_relative_reference_errors(
                raw_path,
                f"Active Project Modules path for {label}",
            )
            if reference_errors:
                errors.extend(reference_errors)
                continue
            try:
                module_path = safe_paths.normalize_repo_relative_path(
                    raw_path,
                    root,
                    description=f"Active Project Modules path for {label}",
                )
            except ValueError as exc:
                errors.append(str(exc))
                continue
            if label == AUTHORITY_MODULE_LABEL:
                authority_record, _, authority_error = read_report_file(
                    root,
                    module_path,
                    source="project",
                    role="scope_of_authority",
                    load_mode="full",
                )
                authority_record["module_label"] = label
                mandatory_files.append(authority_record)
                if authority_error is not None:
                    errors.append(authority_error)
            else:
                unresolved_dynamic_loads.append(
                    {
                        "category": "active_project_module",
                        "module_label": label,
                        "path": module_path,
                        "reason_unresolved": (
                            "load only when the current work is governed by this "
                            "module's subject"
                        ),
                        "source": "project",
                    }
                )

    for state_name in contract_model.CORE_STATE_TEMPLATES:
        state_relative = contract_relative_path(selected_contract_root, state_name)
        state_record, state_error = header_only_obligation(
            root,
            state_relative,
        )
        if state_record is not None:
            mandatory_files.append(state_record)
        if state_error is not None:
            errors.append(state_error)

    unresolved_dynamic_loads.extend(dynamic_load_rules(selected_contract_root))
    return {
        "errors": errors,
        "mandatory_files": mandatory_files,
        "measurement_scope": MEASUREMENT_SCOPE,
        "mode": "selected_downstream_runtime",
        "selection": {
            "contract_root": selected_contract_root,
            "framework_reference": framework_reference,
            "framework_root": (
                str(framework_root) if framework_root is not None else None
            ),
            "project_root": str(root),
            "runtime": runtime,
        },
        "unresolved_dynamic_loads": unresolved_dynamic_loads,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Inventory configured framework surfaces or one selected downstream "
            "runtime closure."
        ),
        allow_abbrev=False,
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        help="downstream project root; requires --runtime",
    )
    parser.add_argument(
        "--runtime",
        choices=integration_registry.family_names(REPO_ROOT),
        help="selected downstream runtime family; requires --project-root",
    )
    parser.add_argument(
        "--contract-root",
        default=".",
        help="safe project-relative directory containing AGENT_PROJECT.md (default: .)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    project_root = cast(Path | None, args.project_root)
    runtime = cast(str | None, args.runtime)
    contract_root = cast(str, args.contract_root)
    if (project_root is None) != (runtime is None):
        parser.error("--project-root and --runtime must be provided together")
    if project_root is None and contract_root != ".":
        parser.error("--contract-root requires --project-root and --runtime")

    if project_root is None or runtime is None:
        result = framework_source_inventory()
    else:
        try:
            result = selected_runtime_load_surface(
                project_root,
                runtime,
                contract_root,
            )
        except (OSError, ValueError) as exc:
            result = {
                "errors": [str(exc)],
                "measurement_scope": MEASUREMENT_SCOPE,
                "mode": "selected_downstream_runtime",
            }
    print(json.dumps(result, indent=2, sort_keys=True))
    errors = result.get("errors")
    return 1 if isinstance(errors, list) and errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
