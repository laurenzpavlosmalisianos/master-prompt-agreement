#!/usr/bin/env python3

from __future__ import annotations

from typing import Any


AUTHORITY_SCOPE_SELECTS = {"standards_of_care", "evidentiary_scopes", "practice_guides"}
AUTHORITY_SCOPE_NON_OVERRIDES = {
    "master_service_agreement",
    "statement_of_work",
    "task_orders",
    "practice_guides",
    "inspected_evidence",
}
STARTUP_HEADER_FILES = {"TODO.md", "DECISIONS.md"}
PROJECT_LOCAL_STATE_FILES = {
    "TODO.md",
    "DECISIONS.md",
    "FINDINGS.md",
    "FRAMEWORK_FEEDBACK.md",
    "REVIEWER_LANE_FEEDBACK.md",
    "PRECEDENTS.md",
    "SOURCE_PACKS.md",
    "SOURCE_UPDATE.md",
    "SOURCE_MONITOR_RESEARCHER.md",
    "SECURITY_VERIFICATION.md",
    "AUTOMATION_ORDERS.json",
}


def validate_operative_schedule_authority_scope(schedule: dict[str, Any], errors: list[str]) -> None:
    authority_scope = schedule.get("authority_scope")
    if not isinstance(authority_scope, dict):
        errors.append("operative schedule must define structured authority_scope")
        return
    if authority_scope.get("allowed_effect") != "select-runtime-routing":
        errors.append("operative schedule authority_scope.allowed_effect must be select-runtime-routing")
    selects = authority_scope.get("selects")
    if not isinstance(selects, list) or set(selects) != AUTHORITY_SCOPE_SELECTS:
        errors.append(
            "operative schedule authority_scope.selects must name standards_of_care, evidentiary_scopes, and practice_guides"
        )
    else:
        for key in selects:
            if key not in schedule:
                errors.append(f"operative schedule authority_scope.selects names missing schedule key: {key}")
    does_not_override = authority_scope.get("does_not_override")
    if not isinstance(does_not_override, list) or set(does_not_override) != AUTHORITY_SCOPE_NON_OVERRIDES:
        errors.append(
            "operative schedule authority_scope.does_not_override must name stable IDs for MSA, SOW, Task Orders, Practice Guides, and inspected evidence"
        )
    if authority_scope.get("grants_permission") is not False:
        errors.append("operative schedule authority_scope.grants_permission must be false")
    if authority_scope.get("grants_doctrine") is not False:
        errors.append("operative schedule authority_scope.grants_doctrine must be false")


def validate_load_order_contract(
    contract: object,
    errors: list[str],
    *,
    known_project_state_files: set[str],
) -> None:
    if not isinstance(contract, dict):
        errors.append("consistency contract load_order_contract must be an object")
        return
    if contract.get("schema_version") != 2:
        errors.append("load_order_contract.schema_version must be 2")
    phase_order = string_list(contract.get("phase_order"))
    if not phase_order:
        errors.append("load_order_contract.phase_order must be a non-empty string list")
    elif len(phase_order) != len(set(phase_order)):
        errors.append("load_order_contract.phase_order must not contain duplicates")
    phase_titles = contract.get("phase_titles")
    if not isinstance(phase_titles, dict):
        errors.append("load_order_contract.phase_titles must be an object")
        phase_titles = {}
    missing_titles = sorted(set(phase_order) - set(phase_titles))
    if missing_titles:
        errors.append(f"load_order_contract.phase_titles missing phases: {', '.join(missing_titles)}")
    for key in phase_order:
        if not isinstance(phase_titles.get(key), str) or not phase_titles.get(key):
            errors.append(f"load_order_contract.phase_titles.{key} must be non-empty")
    if phase_order:
        if not ordered_between(phase_order, "user_request", "startup_state", "routing"):
            errors.append("load_order_contract must place startup_state after user_request and before routing")
    startup_state = contract.get("startup_state")
    if not isinstance(startup_state, dict):
        errors.append("load_order_contract.startup_state must be an object")
        return
    header_files = string_list(startup_state.get("header_files"))
    if set(header_files) != STARTUP_HEADER_FILES:
        errors.append("load_order_contract.startup_state.header_files must be TODO.md and DECISIONS.md")
    empty_count_markers = startup_state.get("empty_count_markers")
    if not isinstance(empty_count_markers, dict) or set(empty_count_markers) != set(header_files):
        errors.append("load_order_contract.startup_state.empty_count_markers must map each header file")
    elif not all(string_list(value) for value in empty_count_markers.values()):
        errors.append("load_order_contract.startup_state.empty_count_markers values must be non-empty string lists")
    for field in ("empty_markers", "full_record_gate", "barred_by"):
        if not string_list(startup_state.get(field)):
            errors.append(f"load_order_contract.startup_state.{field} must be a non-empty string list")
    if startup_state.get("permission_effect") != "none":
        errors.append("load_order_contract.startup_state.permission_effect must be none")
    conditional_files = startup_state.get("conditional_files")
    if not isinstance(conditional_files, dict) or not conditional_files:
        errors.append("load_order_contract.startup_state.conditional_files must be a non-empty object")
    else:
        unknown = sorted(set(conditional_files) - known_project_state_files)
        if unknown:
            errors.append(f"load_order_contract.startup_state.conditional_files contains unknown files: {', '.join(unknown)}")
        for filename, triggers in conditional_files.items():
            if not isinstance(filename, str) or not filename:
                errors.append("load_order_contract.startup_state.conditional_files keys must be filenames")
            if not string_list(triggers):
                errors.append(f"load_order_contract.startup_state.conditional_files.{filename} must list triggers")
    projection_paths = string_list(contract.get("projection_paths"))
    if "runtime/load_order.md" not in projection_paths:
        errors.append("load_order_contract.projection_paths must include runtime/load_order.md")


def string_list(value: object) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        return []
    return value


def ordered_between(values: list[str], before: str, target: str, after: str) -> bool:
    if before not in values or target not in values or after not in values:
        return False
    return values.index(before) < values.index(target) < values.index(after)
