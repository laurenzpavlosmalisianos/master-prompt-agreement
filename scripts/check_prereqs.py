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
        raise RuntimeError("prerequisite diagnostic requires CPython's frozen os module")
    import os as bootstrap_os
    scripts_root = bootstrap_os.path.dirname(bootstrap_os.path.realpath(entrypoint))
    source_path = bootstrap_os.path.join(scripts_root, "python_import_boundary.py")
    close_on_exec = getattr(bootstrap_os, "O_CLOEXEC", 0)
    no_follow = getattr(bootstrap_os, "O_NOFOLLOW", 0)
    if not close_on_exec or not no_follow:
        raise RuntimeError("prerequisite diagnostic requires O_CLOEXEC and O_NOFOLLOW")
    flags = bootstrap_os.O_RDONLY | close_on_exec | no_follow
    descriptor = bootstrap_os.open(source_path, flags)
    try:
        metadata = bootstrap_os.fstat(descriptor)
        if metadata.st_mode & 0o170000 != 0o100000 or metadata.st_nlink != 1:
            raise RuntimeError(
                "prerequisite diagnostic import boundary is not a regular file"
            )
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
        raise RuntimeError("prerequisite diagnostic import boundary source is invalid")
    module = type(_bootstrap_sys)("python_import_boundary")
    module.__file__ = source_path
    _bootstrap_sys.modules["python_import_boundary"] = module
    exec(compile(source, source_path, "exec"), module.__dict__)
    return scripts_root


if __name__ == "__main__":
    _require_python_startup_flags("prerequisite diagnostic")
    _bootstrap_scripts_root = _load_trusted_import_boundary(__file__)
    import python_import_boundary as _python_import_boundary

    _python_import_boundary.establish_import_boundary(
        scripts_root=_bootstrap_scripts_root,
        label="prerequisite diagnostic",
    )

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
        shlex.join((qualified_executable, "-E", "-S", "-B"))
        if qualified_executable
        else ""
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
    cpython_import_boundary_compatible = (
        sys.implementation.name == "cpython" and _bootstrap_imp.is_frozen("os")
    )
    if not cpython_import_boundary_compatible:
        errors.append(
            "the executing interpreter is not compatible with the CPython frozen-module import boundary"
        )
    startup_flags_active = bool(
        sys.flags.ignore_environment
        and sys.flags.no_site
        and sys.flags.dont_write_bytecode
    )
    if not startup_flags_active:
        errors.append(
            "the prerequisite diagnostic was not invoked with required CPython startup flags -E -S -B"
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
    def command(script: str, arguments: str = "") -> str:
        suffix = f" {arguments}" if arguments else ""
        return (
            f"{selected_runner} -- "
            f"{shlex.quote(f'{framework_scripts}/{script}')}"
            f"{suffix}"
        )

    commands = {
        "check_prereqs": command("check_prereqs.py"),
        "framework_product_conformance": command(
            "conformance_check.py",
            "--profile framework-product --root <framework-checkout-as-visible-to-runner> "
            "--exact-product-tree --strict-warnings",
        ),
        "project_bootstrap_dry_run": command(
            "project_bootstrap.py",
            "--dry-run --answers <temporary-answers-json> --project-root /path/to/project "
            "--runtime <codex|claude-code|generic> --framework-revision-policy <live|pinned>",
        ),
        "project_contract_sync": command(
            "project_contract_sync.py",
            "--strict-warnings /path/to/project",
        ),
        "project_refresh_inspect": command(
            "project_refresh.py",
            "inspect --project-root /path/to/project",
        ),
    }
    if tools["uvx"]["found"]:
        commands["python_type_check"] = "uvx basedpyright scripts tests"
    commands["normal_framework_commands"] = (
        f"use the exact qualified runner {selected_runner} for stdlib-only framework "
        "scripts; uv run python -E -S -B, python3 -E -S -B, and "
        "py -3 -E -S -B are only candidate "
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
            "active_startup_flags": {
                "dont_write_bytecode": bool(sys.flags.dont_write_bytecode),
                "ignore_environment": bool(sys.flags.ignore_environment),
                "no_site": bool(sys.flags.no_site),
            },
            "implementation": sys.implementation.name,
            "import_boundary_compatible": cpython_import_boundary_compatible,
            "executable": raw_executable,
            "minimum_supported": version_string(MIN_PYTHON + (0,)),
            "qualified_executable": qualified_executable,
            "required_startup_flags": ["-E", "-S", "-B"],
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
                "uv run python -E -S -B",
                "python3 -E -S -B",
                "py -3 -E -S -B",
            ],
            "qualification_basis": (
                "runner identifies the exact compatible CPython executable and required "
                "startup flags that produced this report"
            ),
            "selected": selected_runner,
        },
        "tools": tools,
    }
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
