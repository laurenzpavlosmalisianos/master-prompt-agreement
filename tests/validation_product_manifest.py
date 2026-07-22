"""Invariants for the exact installable-product manifest."""

from __future__ import annotations

import ast
from pathlib import Path, PurePosixPath
import unittest

from tests.validation_test_support import REPO_ROOT

import product_manifest


IGNORED_LOCAL_OS_METADATA_NAMES = frozenset({".DS_Store", "Thumbs.db"})


class ProductManifestTests(unittest.TestCase):
    def test_product_manifest_paths_are_unique_normalized_files(self) -> None:
        declared = product_manifest.PRODUCT_REQUIRED_FILES
        self.assertEqual(len(declared), len(set(declared)))
        self.assertEqual(frozenset(declared), product_manifest.PRODUCT_REQUIRED_FILE_SET)
        for relative in declared:
            path = PurePosixPath(relative)
            self.assertFalse(path.is_absolute(), relative)
            self.assertNotIn("..", path.parts, relative)
            self.assertEqual(path.as_posix(), relative)
            target = REPO_ROOT / relative
            self.assertTrue(target.is_file(), relative)
            self.assertFalse(target.is_symlink(), relative)

    def test_product_iterator_is_exact_and_deterministic(self) -> None:
        expected = [
            REPO_ROOT / relative
            for relative in sorted(product_manifest.PRODUCT_REQUIRED_FILES)
        ]
        self.assertEqual(expected, product_manifest.iter_product_files(REPO_ROOT))

    def test_complete_product_directories_have_no_undeclared_files(self) -> None:
        declared = product_manifest.PRODUCT_REQUIRED_FILE_SET
        observed: set[str] = set()
        for relative_root in product_manifest.PRODUCT_COMPLETE_DIRECTORY_ROOTS:
            root = REPO_ROOT / relative_root
            self.assertTrue(root.is_dir(), relative_root)
            for path in root.rglob("*"):
                if path.is_file() or path.is_symlink():
                    if path.name in IGNORED_LOCAL_OS_METADATA_NAMES and path.is_file():
                        continue
                    observed.add(path.relative_to(REPO_ROOT).as_posix())
        self.assertEqual(set(), observed - declared)

    def test_product_script_imports_are_product_closed(self) -> None:
        for relative in product_manifest.PRODUCT_REQUIRED_FILES:
            if not relative.startswith("scripts/") or not relative.endswith(".py"):
                continue
            script = REPO_ROOT / relative
            dependencies = product_manifest._local_script_dependencies(REPO_ROOT, script)
            for dependency in dependencies:
                self.assertIn(
                    dependency.relative_to(REPO_ROOT).as_posix(),
                    product_manifest.PRODUCT_REQUIRED_FILE_SET,
                )

    def test_all_product_python_imports_are_product_closed(self) -> None:
        """Reject a public test or command that imports an excluded local module."""

        declared = product_manifest.PRODUCT_REQUIRED_FILE_SET
        local_roots = {"scripts", "tests"}
        for relative in product_manifest.PRODUCT_REQUIRED_FILES:
            if not relative.endswith(".py"):
                continue
            source_path = REPO_ROOT / relative
            tree = ast.parse(
                source_path.read_text(encoding="utf-8"),
                filename=relative,
            )
            candidates: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    modules = [node.module] if node.module else []
                    if node.module in local_roots:
                        modules.extend(
                            f"{node.module}.{alias.name}" for alias in node.names
                        )
                else:
                    continue
                for module in modules:
                    if not module:
                        continue
                    module_path = module.replace(".", "/")
                    candidates.add(f"{module_path}.py")
                    candidates.add(f"{module_path}/__init__.py")
                    candidates.add(f"scripts/{module.split('.', 1)[0]}.py")

            for candidate in sorted(candidates):
                local_path = REPO_ROOT / candidate
                if local_path.exists() or local_path.is_symlink():
                    self.assertIn(
                        candidate,
                        declared,
                        f"{relative} imports excluded local module {candidate}",
                    )

    def test_downstream_effective_files_are_product_files(self) -> None:
        effective = product_manifest.iter_downstream_effective_files(REPO_ROOT)
        self.assertTrue(effective)
        self.assertEqual(len(effective), len(set(effective)))
        for path in effective:
            self.assertIn(
                path.relative_to(REPO_ROOT).as_posix(),
                product_manifest.PRODUCT_REQUIRED_FILE_SET,
            )


if __name__ == "__main__":
    unittest.main()
