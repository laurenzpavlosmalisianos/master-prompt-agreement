#!/usr/bin/env python3

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from typing import Any

import safe_paths


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONTRACT = Path("runtime/framework_quality_contract.json")
EXPECTED_GUARD_KIND_BY_ID = {
    "private-path-leak": "deterministic",
    "vendor-specific-public-doctrine": "semantic_review",
    "exact-url-monitor-root": "deterministic",
    "prose-derived-source-control": "deterministic",
    "lower-tier-source-adoption": "deterministic",
    "prose-derived-research-state": "deterministic",
    "unbounded-reviewer-lane": "semantic_review",
    "unabstracted-external-source": "semantic_review",
    "semantic-validator-gap": "semantic_review",
    "durable-generator-snapshot-only": "semantic_review",
    "unclassified-authoring-workspace-residue": "deterministic",
}
REQUIRED_MISTAKE_CLASS_IDS = set(EXPECTED_GUARD_KIND_BY_ID)
GUARD_KINDS = {"deterministic", "semantic_review"}


def load_json(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        data = safe_paths.loads_json_no_duplicates(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, [f"missing contract: {path}"]
    except json.JSONDecodeError as exc:
        return None, [f"invalid JSON in {path}: {exc}"]
    if not isinstance(data, dict):
        return None, [f"contract root must be an object: {path}"]
    return data, []


def string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def validate_mistake_classes(contract: dict[str, Any], errors: list[str]) -> None:
    classes = contract.get("repeated_mistake_classes")
    if not isinstance(classes, list) or not classes:
        errors.append("repeated_mistake_classes must be a non-empty list")
        return
    ids: list[str] = []
    for index, item in enumerate(classes):
        if not isinstance(item, dict):
            errors.append(f"repeated_mistake_classes[{index}] must be an object")
            continue
        class_id = item.get("id")
        if not isinstance(class_id, str) or not class_id:
            errors.append(f"repeated_mistake_classes[{index}] must define id")
            continue
        ids.append(class_id)
        for field in ("failure", "guard"):
            if not isinstance(item.get(field), str) or not item[field].strip():
                errors.append(f"repeated_mistake_classes {class_id} must define {field}")
        guard_kind = item.get("guard_kind")
        if guard_kind not in GUARD_KINDS:
            errors.append(
                f"repeated_mistake_classes {class_id} must define guard_kind as one of: "
                + ", ".join(sorted(GUARD_KINDS))
            )
        expected_guard_kind = EXPECTED_GUARD_KIND_BY_ID.get(class_id)
        if expected_guard_kind is not None and guard_kind != expected_guard_kind:
            errors.append(
                f"repeated_mistake_classes {class_id} guard_kind must be "
                f"{expected_guard_kind}"
            )
    duplicates = sorted(name for name, count in Counter(ids).items() if count > 1)
    if duplicates:
        errors.append(f"duplicate repeated_mistake_classes ids: {', '.join(duplicates)}")
    missing = sorted(REQUIRED_MISTAKE_CLASS_IDS - set(ids))
    if missing:
        errors.append(f"missing repeated mistake classes: {', '.join(missing)}")


def validate_required_task_orders(root: Path, contract: dict[str, Any], errors: list[str]) -> None:
    required = string_list(contract.get("required_task_orders"))
    if not required:
        errors.append("required_task_orders must be a non-empty string list")
    catalog, catalog_errors = load_json(root / "runtime/workflow_catalog.json")
    errors.extend(catalog_errors)
    catalog_paths = set()
    if catalog:
        raw_task_orders = catalog.get("task_orders")
        if isinstance(raw_task_orders, list):
            catalog_paths = {
                item.get("path")
                for item in raw_task_orders
                if isinstance(item, dict) and isinstance(item.get("path"), str)
            }
    for rel in required:
        if not (root / rel).is_file():
            errors.append(f"required quality task order missing: {rel}")
        if rel not in catalog_paths:
            errors.append(f"required quality task order missing from workflow catalog: {rel}")


def validate_guide_surface_roles(root: Path, contract: dict[str, Any], errors: list[str]) -> None:
    guide_entries = contract.get("guide_surface_roles")
    if not isinstance(guide_entries, list) or not guide_entries:
        errors.append("guide_surface_roles must be a non-empty list")
        return
    actual_guides = {
        path.relative_to(root).as_posix()
        for path in (root / "practice_guides").glob("*.md")
        if path.is_file()
    }
    declared_paths: list[str] = []
    owned_concepts: list[str] = []
    for index, item in enumerate(guide_entries):
        if not isinstance(item, dict):
            errors.append(f"guide_surface_roles[{index}] must be an object")
            continue
        rel = item.get("path")
        if not isinstance(rel, str) or not rel.startswith("practice_guides/") or not rel.endswith(".md"):
            errors.append(f"guide_surface_roles[{index}] path must be a practice guide path")
            continue
        declared_paths.append(rel)
        if not (root / rel).is_file():
            errors.append(f"guide_surface_roles path missing: {rel}")
        owns = string_list(item.get("owns"))
        supports = string_list(item.get("supports"))
        non_goals = string_list(item.get("must_not_own"))
        if not owns:
            errors.append(f"guide_surface_roles {rel} must define owned concepts")
        if not supports:
            errors.append(f"guide_surface_roles {rel} must define supporting surfaces")
        if not non_goals:
            errors.append(f"guide_surface_roles {rel} must define must_not_own")
        owned_concepts.extend(concept.casefold() for concept in owns)
    duplicate_paths = sorted(path for path, count in Counter(declared_paths).items() if count > 1)
    if duplicate_paths:
        errors.append(f"duplicate guide_surface_roles paths: {', '.join(duplicate_paths)}")
    missing_guides = sorted(actual_guides - set(declared_paths))
    extra_guides = sorted(set(declared_paths) - actual_guides)
    if missing_guides:
        errors.append(f"practice guides missing ownership map entries: {', '.join(missing_guides)}")
    if extra_guides:
        errors.append(f"ownership map references unknown practice guides: {', '.join(extra_guides)}")
    duplicate_concepts = sorted(name for name, count in Counter(owned_concepts).items() if count > 1)
    if duplicate_concepts:
        errors.append(f"duplicate owned quality concepts: {', '.join(duplicate_concepts)}")


def validate(root: Path, contract_path: Path) -> list[str]:
    errors: list[str] = []
    contract, contract_errors = load_json(contract_path)
    errors.extend(contract_errors)
    if contract is None:
        return errors
    if contract.get("schema_version") != 2:
        errors.append("schema_version must be 2")
    if contract.get("purpose") != "framework-quality-regression-contract":
        errors.append("purpose must be framework-quality-regression-contract")
    validate_mistake_classes(contract, errors)
    validate_required_task_orders(root, contract, errors)
    validate_guide_surface_roles(root, contract, errors)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Lint structural framework-quality guardrails.",
        allow_abbrev=False,
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=REPO_ROOT,
        help="Framework root to inspect (default: this repository).",
    )
    parser.add_argument(
        "--contract",
        type=Path,
        default=None,
        help=(
            "Framework-quality contract to enforce (default: the canonical "
            "contract below --root)."
        ),
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Report format (default: text).",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    contract = args.contract.resolve() if args.contract else root / DEFAULT_CONTRACT
    errors = validate(root, contract)
    report = {"contract": str(contract), "errors": errors}
    if args.format == "json":
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print("PASS" if not errors else "FAIL")
        for error in errors:
            print(f"- {error}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
