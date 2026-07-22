"""Product-facing conformance-registry and execution tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tests.validation_test_support import REPO_ROOT

import conformance_check


class ProductConformanceTests(unittest.TestCase):
    def test_current_product_registry_and_schema_are_valid(self) -> None:
        registry, errors = conformance_check.load_profiles()
        self.assertIsNotNone(registry)
        self.assertEqual([], errors)

    def test_registry_exposes_the_closed_product_profile_set(self) -> None:
        registry, errors = conformance_check.load_profiles()
        self.assertEqual([], errors)
        assert registry is not None
        self.assertEqual(
            {
                "automation-managed",
                "core-project",
                "framework-product",
                "multi-agent-managed",
                "reviewer-lane-managed",
                "security-managed",
                "source-managed",
            },
            set(conformance_check.profile_by_id(registry)),
        )

    def test_framework_product_profile_uses_no_maintainer_subprocess(self) -> None:
        with mock.patch.object(
            conformance_check,
            "run_command",
            side_effect=AssertionError("framework-product must stay in-process"),
        ):
            report = conformance_check.run_profiles(
                ["framework-product"],
                REPO_ROOT,
            )
        self.assertEqual("pass", report["status"], report)
        self.assertEqual(
            ["profile_required_surfaces", "framework_product_files"],
            [check["id"] for check in report["checks"]],
        )

    def test_product_profile_reports_one_missing_manifest_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with mock.patch.object(
                conformance_check.product_manifest,
                "PRODUCT_REQUIRED_FILES",
                ("README.md",),
            ):
                outcome = conformance_check.check_framework_product_files(root)
        self.assertTrue(any("missing product file: README.md" in item for item in outcome))

    def test_exact_product_tree_stops_at_undeclared_directory_without_descent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "README.md").write_text("# Product\n", encoding="utf-8")
            (root / "unexpected-dir").mkdir()
            (root / "unexpected-dir" / "nested.txt").write_text(
                "must not be inspected\n",
                encoding="utf-8",
            )
            real_scandir = os.scandir
            enumerated: list[Path] = []

            def guarded_scandir(path: os.PathLike[str] | str):
                candidate = Path(path)
                enumerated.append(candidate)
                if candidate == root / "unexpected-dir":
                    raise AssertionError("exact-tree validation descended into contamination")
                return real_scandir(path)

            with mock.patch.object(
                conformance_check.product_manifest,
                "PRODUCT_REQUIRED_FILES",
                ("README.md",),
            ), mock.patch.object(
                conformance_check.product_manifest,
                "PRODUCT_REQUIRED_FILE_SET",
                frozenset({"README.md"}),
            ), mock.patch.object(
                conformance_check.product_manifest,
                "PRODUCT_DIRECTORY_PATHS",
                frozenset(),
            ), mock.patch.object(
                conformance_check.os,
                "scandir",
                side_effect=guarded_scandir,
            ):
                exact = conformance_check._exact_product_tree_errors(root)

        self.assertEqual(["undeclared product directory: unexpected-dir"], exact)
        self.assertEqual([root], enumerated)

    def test_exact_product_tree_streams_until_first_contaminating_entry(self) -> None:
        class FakeEntry:
            def __init__(self, root: Path, name: str) -> None:
                self.name = name
                self.path = str(root / name)

            def stat(self, *, follow_symlinks: bool = True) -> os.stat_result:
                return os.stat(self.path, follow_symlinks=follow_symlinks)

        class BoundedIterator:
            def __init__(self, entries: tuple[FakeEntry, ...]) -> None:
                self._entries = entries
                self.consumed = 0

            def __enter__(self) -> BoundedIterator:
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def __iter__(self) -> BoundedIterator:
                return self

            def __next__(self) -> FakeEntry:
                if self.consumed >= len(self._entries):
                    raise AssertionError(
                        "exact-tree validation read beyond first contamination"
                    )
                entry = self._entries[self.consumed]
                self.consumed += 1
                return entry

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "README.md").write_text("# Product\n", encoding="utf-8")
            (root / "unexpected.txt").write_text("extra\n", encoding="utf-8")
            iterator = BoundedIterator(
                (
                    FakeEntry(root, "README.md"),
                    FakeEntry(root, "unexpected.txt"),
                )
            )
            with mock.patch.object(
                conformance_check.product_manifest,
                "PRODUCT_REQUIRED_FILES",
                ("README.md",),
            ), mock.patch.object(
                conformance_check.product_manifest,
                "PRODUCT_REQUIRED_FILE_SET",
                frozenset({"README.md"}),
            ), mock.patch.object(
                conformance_check.product_manifest,
                "PRODUCT_DIRECTORY_PATHS",
                frozenset(),
            ), mock.patch.object(
                conformance_check.os,
                "scandir",
                return_value=iterator,
            ):
                exact = conformance_check._exact_product_tree_errors(root)

        self.assertEqual(["undeclared product file: unexpected.txt"], exact)
        self.assertEqual(2, iterator.consumed)

    def test_exact_product_tree_allows_only_root_git_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "README.md").write_text("# Product\n", encoding="utf-8")
            git_metadata = root / ".git"
            git_metadata.mkdir()
            (git_metadata / "config").write_text("fixture\n", encoding="utf-8")
            (root / ".DS_Store").write_bytes(b"local")
            with mock.patch.object(
                conformance_check.product_manifest,
                "PRODUCT_REQUIRED_FILES",
                ("README.md",),
            ), mock.patch.object(
                conformance_check.product_manifest,
                "PRODUCT_REQUIRED_FILE_SET",
                frozenset({"README.md"}),
            ), mock.patch.object(
                conformance_check.product_manifest,
                "PRODUCT_DIRECTORY_PATHS",
                frozenset(),
            ):
                exact = conformance_check.check_framework_product_files(
                    root,
                    exact_product_tree=True,
                )

        self.assertEqual(["undeclared product file: .DS_Store"], exact)

    def test_exact_product_tree_accepts_declared_tree_and_root_git_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "README.md").write_text("# Product\n", encoding="utf-8")
            (root / "docs").mkdir()
            (root / "docs" / "guide.md").write_text("# Guide\n", encoding="utf-8")
            git_metadata = root / ".git"
            git_metadata.mkdir()
            (git_metadata / "config").write_text("fixture\n", encoding="utf-8")
            with mock.patch.object(
                conformance_check.product_manifest,
                "PRODUCT_REQUIRED_FILES",
                ("README.md", "docs/guide.md"),
            ), mock.patch.object(
                conformance_check.product_manifest,
                "PRODUCT_REQUIRED_FILE_SET",
                frozenset({"README.md", "docs/guide.md"}),
            ), mock.patch.object(
                conformance_check.product_manifest,
                "PRODUCT_DIRECTORY_PATHS",
                frozenset({"docs"}),
            ):
                exact = conformance_check.check_framework_product_files(
                    root,
                    exact_product_tree=True,
                )

        self.assertEqual([], exact)

    def test_exact_product_tree_returns_one_diagnostic_for_declared_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            parent = Path(temp_dir)
            root = parent / "product"
            root.mkdir()
            target = parent / "target.md"
            target.write_text("outside product\n", encoding="utf-8")
            (root / "README.md").symlink_to(target)
            with mock.patch.object(
                conformance_check.product_manifest,
                "PRODUCT_REQUIRED_FILE_SET",
                frozenset({"README.md"}),
            ), mock.patch.object(
                conformance_check.product_manifest,
                "PRODUCT_DIRECTORY_PATHS",
                frozenset(),
            ):
                exact = conformance_check._exact_product_tree_errors(root)

        self.assertEqual(
            ["product distribution contains symlink: README.md"],
            exact,
        )

    def test_project_profile_inheritance_is_deterministic(self) -> None:
        registry, errors = conformance_check.load_profiles()
        self.assertEqual([], errors)
        assert registry is not None
        checks, files, directories, error = conformance_check.expand_profile(
            "source-managed",
            registry,
        )
        self.assertIsNone(error)
        self.assertIn("project_core_files", checks)
        self.assertIn("source_freshness_metadata", checks)
        self.assertIn("PROJECT_INSTANCE.json", files)
        self.assertIn("SOURCE_PACKS.md", files)
        self.assertEqual([], directories)

    def test_cli_list_is_machine_readable(self) -> None:
        with mock.patch(
            "sys.argv",
            ["conformance_check.py", "--list", "--format", "json"],
        ), mock.patch("builtins.print") as output:
            result = conformance_check.main()
        self.assertEqual(0, result)
        payload = json.loads(output.call_args.args[0])
        self.assertIn(
            {"id": "framework-product", "subject": "framework"},
            payload,
        )


if __name__ == "__main__":
    unittest.main()
