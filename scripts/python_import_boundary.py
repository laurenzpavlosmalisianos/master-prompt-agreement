#!/usr/bin/env python3

from __future__ import annotations

import _imp
import os
import sys


EXECUTABLE_IMPORT_SUFFIXES = (
    ".pyc",
    ".pyo",
    ".so",
    ".pyd",
    ".dll",
    ".dylib",
)


def establish_import_boundary(*, scripts_root: str, label: str) -> None:
    """Install one source-only repository import boundary before local imports."""

    if not _imp.is_frozen("os"):
        raise RuntimeError(f"{label} requires CPython's frozen os module")
    canonical_scripts_root = os.path.realpath(scripts_root)
    root_metadata = os.lstat(canonical_scripts_root)
    if root_metadata.st_mode & 0o170000 != 0o040000:
        raise RuntimeError(f"{label} scripts root is not a physical directory")

    stdlib_root = os.path.realpath(str(getattr(sys, "_stdlib_dir", "")))
    if not stdlib_root or not os.path.isabs(stdlib_root):
        raise RuntimeError(f"{label} cannot resolve the standard library")

    sys.dont_write_bytecode = True
    sys.pycache_prefix = os.devnull
    safe_path: list[str] = []
    for raw in sys.path:
        if not raw:
            continue
        resolved = os.path.realpath(raw)
        relative = os.path.relpath(resolved, stdlib_root)
        parts = relative.split(os.sep)
        if (
            relative != os.pardir
            and not relative.startswith(os.pardir + os.sep)
            and "site-packages" not in parts
            and "dist-packages" not in parts
        ):
            safe_path.append(raw)
    if not safe_path:
        raise RuntimeError(f"{label} found no trusted standard-library path")
    sys.path[:] = list(dict.fromkeys(safe_path))

    local_module_names: set[str] = set()
    stdlib_names = {name.casefold() for name in sys.stdlib_module_names}
    with os.scandir(canonical_scripts_root) as entries:
        for entry in entries:
            if entry.name == "__pycache__":
                if entry.is_symlink() or not entry.is_dir(follow_symlinks=False):
                    raise RuntimeError(f"{label} rejected an unsafe __pycache__ entry")
                continue
            if entry.is_symlink() or entry.is_dir(follow_symlinks=False):
                raise RuntimeError(f"{label} rejected local import shadow: {entry.name}")
            if not entry.is_file(follow_symlinks=False):
                raise RuntimeError(
                    f"{label} rejected non-regular import-adjacent entry: {entry.name}"
                )
            lowered = entry.name.casefold()
            if lowered.endswith(EXECUTABLE_IMPORT_SUFFIXES):
                raise RuntimeError(
                    f"{label} rejected executable import artifact: {entry.name}"
                )
            if lowered.endswith(".py"):
                stem = entry.name[:-3]
                local_module_names.add(stem)
                if stem.casefold() in stdlib_names:
                    raise RuntimeError(
                        f"{label} rejected standard-library shadow: {entry.name}"
                    )

    for module_name in local_module_names - {"python_import_boundary"}:
        sys.modules.pop(module_name, None)
    sys.path_importer_cache.pop(canonical_scripts_root, None)
    sys.path.insert(0, canonical_scripts_root)
