#!/usr/bin/env python3

from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import shutil
import sys

import bootstrap_transaction


MIN_PYTHON = (3, 14)
OPTIONAL_TOOLS = {
    "uv": "normal runner for framework Python maintenance when already available in the approved environment",
    "uvx": "normal runner for basedpyright Python type checks when already available in the approved environment",
    "gh": "GitHub-backed comparative review and reference snapshotting",
    "git": "repository bootstrap and history inspection",
    "py": "Windows Python launcher fallback for stdlib-only framework scripts",
}


def descriptor_safe_io_supported() -> bool:
    return not bootstrap_transaction.transaction_capability_errors()


def version_string(info: tuple[int, int, int]) -> str:
    return ".".join(str(part) for part in info)


def main() -> int:
    current = sys.version_info[:3]
    supported = current >= MIN_PYTHON
    tools = {
        name: {
            "found": shutil.which(name) is not None,
            "path": shutil.which(name),
            "purpose": purpose,
        }
        for name, purpose in OPTIONAL_TOOLS.items()
    }
    raw_executable = sys.executable
    try:
        qualified_executable = (
            str(Path(raw_executable).resolve(strict=True)) if raw_executable else ""
        )
    except OSError:
        qualified_executable = ""
    selected_runner = (
        shlex.join((qualified_executable, "-B")) if qualified_executable else ""
    )
    warnings: list[str] = []
    errors: list[str] = []

    if not qualified_executable or not Path(qualified_executable).is_absolute():
        errors.append(
            "the executing Python interpreter has no resolvable absolute executable path"
        )
    if not supported:
        errors.append(
            f"python {version_string(current)} is too old; framework scripts require at least {version_string(MIN_PYTHON + (0,))}"
        )
    transaction_capability_errors = list(
        bootstrap_transaction.transaction_capability_errors()
    )
    safe_io_supported = not transaction_capability_errors
    if not safe_io_supported:
        errors.append(
            "this Python/platform lacks one or more transaction primitives; "
            "authority-bearing framework inputs and transactional lifecycle "
            "changes cannot be handled safely on any project filesystem: "
            + "; ".join(transaction_capability_errors)
        )
    if not tools["uv"]["found"]:
        warnings.append(
            "uv not found; candidate launcher spellings remain unqualified until this diagnostic is run through that exact launcher"
        )
    if not tools["uvx"]["found"]:
        warnings.append("uvx not found; framework Python type-check gate will be unavailable")
    if not tools["gh"]["found"]:
        warnings.append("gh not found; GitHub-backed comparative review and reference snapshotting will be unavailable")
    if not tools["git"]["found"]:
        warnings.append("git not found; repository bootstrap and history inspection will be unavailable")

    framework_scripts = "<framework-checkout-as-visible-to-runner>/scripts"
    commands = {
        "check_prereqs": f"{selected_runner} {framework_scripts}/check_prereqs.py",
        "framework_compliance_authoring_source": f"{selected_runner} {framework_scripts}/framework_compliance.py --tree-role authoring-source",
        "framework_compliance_public_export": f"{selected_runner} {framework_scripts}/framework_compliance.py --tree-role public-export",
        "project_bootstrap_dry_run": f"{selected_runner} {framework_scripts}/project_bootstrap.py --dry-run --answers <temporary-answers-json> --project-root /path/to/project --runtime <codex|claude-code|generic> --framework-revision-policy <live|pinned>",
        "project_contract_sync": f"{selected_runner} {framework_scripts}/project_contract_sync.py --strict-warnings /path/to/project",
        "validate_framework": f"{selected_runner} {framework_scripts}/validate_framework.py",
    }
    if tools["uvx"]["found"]:
        commands["python_type_check"] = "uvx basedpyright scripts tests"
    commands["normal_framework_commands"] = (
        f"use the exact qualified runner {selected_runner} for stdlib-only framework "
        "scripts; uv run python -B, python3 -B, and py -3 -B are only candidate "
        "spellings until this diagnostic is invoked through that exact prefix"
    )

    runner_usable = not errors
    result = {
        "commands": commands,
        "errors": errors,
        "framework_checkout_path_contract": (
            "Replace <framework-checkout-as-visible-to-runner> with the exact "
            "selected checkout path inside the runner filesystem or mount namespace."
        ),
        "warnings": warnings,
        "python": {
            "executable": raw_executable,
            "minimum_supported": version_string(MIN_PYTHON + (0,)),
            "qualified_executable": qualified_executable,
            "supported": supported,
            "version": version_string(current),
        },
        "platform_capabilities": {
            "native_windows_supported": False,
            "transaction_platform_primitives": safe_io_supported,
            "transaction_capability_errors": transaction_capability_errors,
            "qualification_scope": (
                "Interpreter and operating-system primitives only. The transaction "
                "test suite and the first bounded lifecycle transaction must still "
                "qualify behavior on the selected project filesystem."
            ),
        },
        "runner": selected_runner,
        "runner_usable": runner_usable,
        "runners": {
            "project_command_policy": (
                "Use the project-recorded runner or verification command first. "
                "Use this exact tested interpreter for stdlib-only framework scripts "
                "when no project runner is recorded and this report has no errors. "
                "A container or uv prefix is qualified only when the operator invoked "
                "this diagnostic through that exact boundary and retains it unchanged."
            ),
            "unqualified_candidate_order": [
                "uv run python -B",
                "python3 -B",
                "py -3 -B",
            ],
            "qualification_basis": (
                "runner identifies the exact Python executable that produced this report"
            ),
            "selected": selected_runner,
        },
        "tools": tools,
    }
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
