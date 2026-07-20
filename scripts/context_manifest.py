#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

import recommend_stack
import routing_policy
import safe_paths


REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_CATALOG_PATH = REPO_ROOT / "runtime" / "workflow_catalog.json"
PRIVATE_EVIDENCE_PARTS = {
    ".codex",
    ".claude",
    "external_review",
    "private",
    "review_artifacts",
    "source_dumps",
    "source_material",
}
EVIDENCE_PROMPT_BOUNDARY_RE = re.compile(
    r"</?(?:framework|project|practice|codex|system|developer|assistant|user|tool|instructions)[A-Za-z0-9_-]*\b",
    re.IGNORECASE,
)


def validate_workflow_consumer_projection(
    catalog: dict[str, object],
) -> list[dict[str, object]]:
    """Validate identities consumed by the runtime lookup maps."""

    task_orders = catalog.get("task_orders")
    if not isinstance(task_orders, list):
        raise ValueError("workflow catalog task_orders must be a list")

    entries: list[dict[str, object]] = []
    task_names: set[str] = set()
    task_paths: set[str] = set()
    module_names: set[str] = set()
    module_paths: set[str] = set()
    direct_flag_owners: dict[str, str] = {}
    allowed_direct_flags = routing_policy.allowed_trigger_flags()

    for position, entry in enumerate(task_orders):
        label = f"workflow catalog task_orders[{position}]"
        if not isinstance(entry, dict):
            raise ValueError("workflow catalog task_orders entries must be objects")
        entries.append(entry)

        name = entry.get("name")
        path = entry.get("path")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"{label}.name must be a non-empty string")
        if not isinstance(path, str) or not path.strip():
            raise ValueError(f"{label}.path must be a non-empty string")
        if name in task_names:
            raise ValueError(f"workflow catalog has duplicate task order name: {name}")
        if path in task_paths:
            raise ValueError(f"workflow catalog has duplicate task order path: {path}")
        task_names.add(name)
        task_paths.add(path)
        expected_task_path = f"task_orders/{name}.md"
        if path != expected_task_path:
            raise ValueError(
                f"{label}.path must equal the name-derived path: {expected_task_path}"
            )

        module = entry.get("runtime_task_module")
        if module is not None:
            if not isinstance(module, dict):
                raise ValueError(f"{label}.runtime_task_module must be null or an object")
            module_name = module.get("name")
            module_path = module.get("path")
            if not isinstance(module_name, str) or not module_name.strip():
                raise ValueError(
                    f"{label}.runtime_task_module.name must be a non-empty string"
                )
            if not isinstance(module_path, str) or not module_path.strip():
                raise ValueError(
                    f"{label}.runtime_task_module.path must be a non-empty string"
                )
            if module_name in module_names:
                raise ValueError(
                    f"workflow catalog has duplicate runtime task module name: {module_name}"
                )
            if module_path in module_paths:
                raise ValueError(
                    f"workflow catalog has duplicate runtime task module path: {module_path}"
                )
            module_names.add(module_name)
            module_paths.add(module_path)
            expected_module_path = f"runtime/task_modules/{module_name}.md"
            if module_path != expected_module_path:
                raise ValueError(
                    f"{label}.runtime_task_module.path must equal the name-derived "
                    f"path: {expected_module_path}"
                )
            if module.get("canonical_task_order") != path:
                raise ValueError(
                    f"{label}.runtime_task_module.canonical_task_order must equal "
                    f"its owning task order path: {path}"
                )

        if "direct_full_when_flags" not in entry:
            continue
        if module is not None:
            raise ValueError(
                f"{label}.direct_full_when_flags cannot coexist with a runtime task module"
            )
        direct_flags = entry["direct_full_when_flags"]
        if (
            not isinstance(direct_flags, list)
            or not direct_flags
            or not all(
                isinstance(flag, str) and bool(flag.strip())
                for flag in direct_flags
            )
        ):
            raise ValueError(
                f"{label}.direct_full_when_flags must be a non-empty string list"
            )
        if len(direct_flags) != len(set(direct_flags)):
            raise ValueError(
                f"{label}.direct_full_when_flags must not contain duplicate values"
            )
        for flag in direct_flags:
            if flag not in allowed_direct_flags:
                raise ValueError(
                    f"{label}.direct_full_when_flags uses unknown routing flag: {flag}"
                )
            previous_owner = direct_flag_owners.get(flag)
            if previous_owner is not None:
                raise ValueError(
                    "workflow catalog direct routing flag has multiple owners: "
                    f"{flag} ({previous_owner}, {name})"
                )
            direct_flag_owners[flag] = name

    return entries


def load_workflow_catalog(
    path: Path = WORKFLOW_CATALOG_PATH,
) -> dict[str, object]:
    raw = safe_paths.read_regular_file_bytes(
        path,
        description="workflow catalog",
    ).decode("utf-8")
    catalog = safe_paths.loads_json_no_duplicates(raw)
    if not isinstance(catalog, dict):
        raise ValueError("workflow catalog must be a JSON object")
    validate_workflow_consumer_projection(catalog)
    return catalog


def load_task_modules(
    catalog: dict[str, object],
) -> dict[str, dict[str, object]]:
    modules: dict[str, dict[str, object]] = {}
    for entry in validate_workflow_consumer_projection(catalog):
        module = entry.get("runtime_task_module")
        if isinstance(module, dict) and isinstance(module.get("name"), str):
            modules[module["name"]] = module
    return modules


def load_direct_full_task_orders(
    catalog: dict[str, object],
) -> dict[str, dict[str, object]]:
    routes: dict[str, dict[str, object]] = {}
    for entry in validate_workflow_consumer_projection(catalog):
        flags = entry.get("direct_full_when_flags")
        if not isinstance(flags, list):
            continue
        name = entry.get("name")
        path = entry.get("path")
        if not isinstance(name, str) or not isinstance(path, str):
            raise ValueError("validated workflow consumer projection lost task identity")
        routes[name] = {"path": path, "routing_flags": flags}
    return routes


def load_task_module_paths(
    modules: dict[str, dict[str, object]],
) -> dict[str, str]:
    return {
        name: str(module["path"])
        for name, module in modules.items()
    }


WORKFLOW_CATALOG = load_workflow_catalog()
TASK_MODULES = load_task_modules(WORKFLOW_CATALOG)
TASK_MODULE_PATHS = load_task_module_paths(TASK_MODULES)
DIRECT_FULL_TASK_ORDERS = load_direct_full_task_orders(WORKFLOW_CATALOG)


def infer_direct_full_task_orders(args: argparse.Namespace) -> list[str]:
    selected: list[str] = []
    for name, route in DIRECT_FULL_TASK_ORDERS.items():
        flags = route.get("routing_flags")
        if isinstance(flags, list) and any(
            isinstance(flag, str) and getattr(args, flag, False)
            for flag in flags
        ):
            selected.append(name)
    return selected


def resolve_direct_full_loading(names: list[str]) -> dict[str, object]:
    if len(names) != 1:
        return {
            "canonical_task_order": None,
            "candidate_task_orders": names,
            "candidate_task_modules": [],
            "evaluated_use_full_when": [],
            "explicit_full_task_order": True,
            "mode": "unresolved",
            "required_action": "resolve the competing direct full Task Order routes",
        }
    name = names[0]
    return {
        "canonical_task_order": {"name": name, "path": DIRECT_FULL_TASK_ORDERS[name]["path"]},
        "candidate_task_orders": [name],
        "candidate_task_modules": [],
        "evaluated_use_full_when": [],
        "explicit_full_task_order": True,
        "mode": "full_task_order",
        "required_action": "load the canonical full Task Order",
    }


def infer_task_module(args: argparse.Namespace) -> str | None:
    candidates = workflow_selection_candidates(args)
    return candidates[0] if len(candidates) == 1 else None


def infer_task_module_candidates(args: argparse.Namespace) -> list[str]:
    return [
        name
        for flag, name in (
            ("scheduled", "automation"),
            ("planning", "plan"),
            ("audit", "audit"),
            ("review", "review"),
        )
        if getattr(args, flag)
    ]


def workflow_selection_candidates(args: argparse.Namespace) -> list[str]:
    candidates = infer_task_module_candidates(args)
    if args.task_module:
        candidates.append(args.task_module)
    return sorted(set(candidates))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a concrete routing and loading manifest for a task.",
        allow_abbrev=False,
    )
    for flag, help_text in recommend_stack.CLI_FLAGS:
        parser.add_argument(f"--{flag}", action="store_true", help=help_text)
    for option_strings, destination, help_text in routing_policy.context_condition_arguments():
        parser.add_argument(
            *option_strings,
            dest=destination,
            action="store_true",
            help=help_text,
        )
    parser.add_argument(
        "--full",
        "--full-task-order",
        dest="full_task_order",
        action="store_true",
        help="Explicitly require the canonical full Task Order in addition to the compact module.",
    )
    parser.add_argument(
        "--path",
        action="append",
        default=[],
        help="Repo-relative evidence path to include first in the manifest.",
    )
    parser.add_argument(
        "--external-evidence",
        action="store_true",
        help="Allow absolute or out-of-repository evidence paths. Use only when approved by the project boundary.",
    )
    parser.add_argument(
        "--task-module",
        choices=sorted(TASK_MODULE_PATHS),
        help="Force a specific runtime task module.",
    )
    return parser


def validate_evidence_paths(paths: list[str], allow_external: bool, parser: argparse.ArgumentParser) -> list[str]:
    validated: list[str] = []
    for value in paths:
        if safe_paths.PATH_CONTROL_RE.search(value) or any(marker in value for marker in ("<", ">")):
            parser.error(f"--path must be plain path text without control characters or angle brackets: {value}")
        if EVIDENCE_PROMPT_BOUNDARY_RE.search(value):
            parser.error(f"--path must not contain prompt-boundary tags: {value}")
        if allow_external:
            validated.append(value)
            continue
        try:
            normalized = safe_paths.normalize_repo_relative_path(
                value,
                REPO_ROOT,
                description="--path",
            )
        except ValueError as exc:
            parser.error(str(exc))
        path = Path(normalized)
        if any(part.casefold() in PRIVATE_EVIDENCE_PARTS for part in path.parts):
            parser.error(f"--path must not reference private or generated local state: {value}")
        validated.append(normalized)
    return validated


def _unresolved_condition(
    description: object,
    reason: str,
    condition_id: object = None,
) -> dict[str, object]:
    return {
        "condition": str(description),
        "id": condition_id if isinstance(condition_id, str) else None,
        "matched_flags": [],
        "status": "unresolved",
        "unresolved_reason": reason,
    }


def _condition_indexes(
    conditions: list[object],
    descriptions: list[object],
) -> tuple[dict[str, list[dict[object, object]]], dict[str, int], dict[str, int]]:
    by_description: dict[str, list[dict[object, object]]] = {}
    id_counts: dict[str, int] = {}
    for condition in conditions:
        if not isinstance(condition, dict):
            continue
        description = condition.get("description")
        if isinstance(description, str):
            by_description.setdefault(description, []).append(condition)
        condition_id = condition.get("id")
        if isinstance(condition_id, str):
            id_counts[condition_id] = id_counts.get(condition_id, 0) + 1
    description_counts = {
        description: sum(1 for item in descriptions if item == description)
        for description in descriptions
        if isinstance(description, str)
    }
    return by_description, description_counts, id_counts


def _evaluate_declared_condition(
    args: argparse.Namespace,
    description: object,
    matches: list[dict[object, object]],
    description_count: int,
    id_counts: dict[str, int],
) -> dict[str, object]:
    if not isinstance(description, str):
        return _unresolved_condition(
            description,
            "use_full_when description is not a string",
        )
    if len(matches) != 1 or description_count != 1:
        return _unresolved_condition(
            description,
            "condition has no unique machine-evaluable catalog rule",
        )
    condition = matches[0]
    condition_id = condition.get("id")
    any_flags = condition.get("any_flags", [])
    all_flags = condition.get("all_flags", [])
    if not (
        isinstance(condition_id, str)
        and bool(condition_id)
        and id_counts.get(condition_id) == 1
        and isinstance(any_flags, list)
        and isinstance(all_flags, list)
        and bool(any_flags or all_flags)
    ):
        return _unresolved_condition(
            description,
            "catalog rule has an invalid id or flag predicate",
            condition_id,
        )

    registered_flags = routing_policy.runtime_condition_flags()
    flag_values: dict[str, bool] = {}
    any_flag_names: list[str] = []
    all_flag_names: list[str] = []
    for raw_flags, destination in (
        (any_flags, any_flag_names),
        (all_flags, all_flag_names),
    ):
        for raw_flag in raw_flags:
            if not isinstance(raw_flag, str) or raw_flag not in registered_flags:
                return _unresolved_condition(
                    description,
                    "catalog rule uses an unregistered flag predicate",
                    condition_id,
                )
            value = getattr(args, raw_flag, None)
            if type(value) is not bool:
                return _unresolved_condition(
                    description,
                    "catalog rule flag predicate is not an exact boolean",
                    condition_id,
                )
            destination.append(raw_flag)
            flag_values[raw_flag] = value

    matched_flags = [
        flag
        for flag in [*any_flag_names, *all_flag_names]
        if flag_values[flag]
    ]
    any_match = not any_flag_names or any(
        flag_values[flag] for flag in any_flag_names
    )
    all_match = all(flag_values[flag] for flag in all_flag_names)
    return {
        "condition": description,
        "id": condition_id,
        "matched_flags": matched_flags,
        "status": "matched" if any_match and all_match else "not_matched",
    }


def _evaluate_module_conditions(
    args: argparse.Namespace,
    module: dict[str, object],
) -> list[dict[str, object]]:
    raw_conditions = module.get("use_full_when_conditions")
    conditions = raw_conditions if isinstance(raw_conditions, list) else []
    raw_descriptions = module.get("use_full_when")
    descriptions = raw_descriptions if isinstance(raw_descriptions, list) else []
    by_description, description_counts, id_counts = _condition_indexes(
        conditions,
        descriptions,
    )
    evaluated: list[dict[str, object]] = []
    if not descriptions:
        evaluated.append(
            _unresolved_condition(
                "catalog use_full_when",
                "catalog module has no declared use_full_when conditions",
            )
        )
    for description in descriptions:
        matches = by_description.get(description, []) if isinstance(description, str) else []
        evaluated.append(
            _evaluate_declared_condition(
                args,
                description,
                matches,
                description_counts.get(description, 0)
                if isinstance(description, str)
                else 0,
                id_counts,
            )
        )
    described = {item for item in descriptions if isinstance(item, str)}
    for condition in conditions:
        if not isinstance(condition, dict):
            evaluated.append(
                _unresolved_condition(
                    condition,
                    "machine condition must be an object",
                )
            )
        elif condition.get("description") not in described:
            evaluated.append(
                _unresolved_condition(
                    condition.get("description"),
                    "machine rule does not map to a declared use_full_when condition",
                    condition.get("id"),
                )
            )
    return evaluated


def _module_loading_mode(
    canonical: dict[str, object] | None,
    evaluated: list[dict[str, object]],
    explicit_full: bool,
) -> tuple[str, str]:
    matched = any(item["status"] == "matched" for item in evaluated)
    unresolved = any(item["status"] == "unresolved" for item in evaluated)
    if canonical is None:
        return (
            "unresolved",
            "repair the missing canonical Task Order reference before selecting a compact module",
        )
    if explicit_full or matched:
        return (
            "full_task_order",
            "load the compact runtime module and its canonical full Task Order",
        )
    if unresolved:
        return (
            "unresolved",
            "resolve the listed conditions or load the canonical full Task Order conservatively",
        )
    return "compact_module", "load the compact runtime task module"


def resolve_task_module_loading(
    args: argparse.Namespace,
    task_module: str | None,
) -> dict[str, object]:
    if task_module is None:
        candidates = workflow_selection_candidates(args)
        unresolved = len(candidates) > 1 or bool(args.full_task_order)
        return {
            "canonical_task_order": None,
            "candidate_task_modules": candidates,
            "evaluated_use_full_when": [],
            "explicit_full_task_order": bool(args.full_task_order),
            "mode": "unresolved" if unresolved else "not_applicable",
            "required_action": (
                "resolve the workflow selection, then load its canonical full Task Order"
                if unresolved
                else (
                    "identify one workflow by explicit provenance or unambiguous task "
                    "intent before using a compact runtime module"
                )
            ),
            "selection_evidence": None,
        }

    module = TASK_MODULES[task_module]
    selection_evidence = (
        "explicit_task_module"
        if args.task_module == task_module
        else (
            "unambiguous_task_intent"
            if infer_task_module_candidates(args) == [task_module]
            else None
        )
    )
    canonical_path = module.get("canonical_task_order")
    canonical: dict[str, object] | None = (
        {"name": task_module, "path": canonical_path}
        if isinstance(canonical_path, str)
        else None
    )
    evaluated = _evaluate_module_conditions(args, module)
    mode, required_action = _module_loading_mode(
        canonical,
        evaluated,
        bool(args.full_task_order),
    )
    if selection_evidence is None:
        mode = "unresolved"
        required_action = (
            "identify one workflow by explicit provenance or unambiguous task intent, "
            "or load the canonical full Task Order"
        )
    return {
        "canonical_task_order": canonical if mode != "compact_module" else None,
        "candidate_task_modules": [task_module],
        "condition_evaluation_basis": "supplied positive task-characteristic flags",
        "evaluated_use_full_when": evaluated,
        "explicit_full_task_order": bool(args.full_task_order),
        "mode": mode,
        "required_action": required_action,
        "selection_evidence": selection_evidence,
    }


def summarize_reasons(args: argparse.Namespace, standard_of_care: str) -> list[str]:
    reasons = [
        help_text
        for flag, help_text in recommend_stack.CLI_FLAGS
        if getattr(args, flag.replace("-", "_"))
    ]
    if not reasons:
        reasons.append("No elevated risk flags were set.")
    reasons.append(f"Selected Risk Level: {standard_of_care}.")
    return reasons


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    evidence_files = validate_evidence_paths(args.path, args.external_evidence, parser)
    schedule = recommend_stack.load_schedule()
    standard_of_care = recommend_stack.choose_standard_of_care(args)
    guide_names = recommend_stack.collect_practice_guides(args, schedule)
    guide_map = {guide["name"]: guide["path"] for guide in schedule["practice_guides"]}
    direct_full_orders = infer_direct_full_task_orders(args)
    task_module = None if direct_full_orders else infer_task_module(args)
    task_module_loading = (
        resolve_direct_full_loading(direct_full_orders)
        if direct_full_orders
        else resolve_task_module_loading(args, task_module)
    )
    evidentiary_scope = recommend_stack.choose_evidentiary_scope(args, standard_of_care)

    manifest = {
        "always_on_files": [
            "runtime/operative_charter.md",
        ],
        "project_contract_files": [
            "AGENT_PROJECT.md",
        ],
        "routing_support_files": [
            "runtime/load_order.md",
            "runtime/standards_of_care.md",
        ],
        "evidence_files": evidence_files,
        "evidentiary_scope": evidentiary_scope,
        "practice_guides": [
            {"name": name, "path": guide_map[name]} for name in guide_names
        ],
        "required_checks": recommend_stack.report_checks(
            recommend_stack.collect_required_checks(
                args,
                standard_of_care,
                schedule,
            )
        ),
        "routing_reasons": summarize_reasons(args, standard_of_care),
        "second_review_recommended": recommend_stack.needs_second_review(args, standard_of_care),
        "standard_of_care": standard_of_care,
        "task_module": (
            {"name": task_module, "path": TASK_MODULE_PATHS[task_module]}
            if task_module
            else None
        ),
        "task_order": (
            task_module_loading["canonical_task_order"]
            if task_module_loading["mode"] == "full_task_order"
            else None
        ),
        "task_module_loading": task_module_loading,
    }
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
