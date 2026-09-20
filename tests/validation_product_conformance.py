"""Product-facing conformance-registry and execution tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from typing import Any

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

    def test_exact_product_tree_owns_manifest_completeness(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with mock.patch.object(
                conformance_check.product_manifest,
                "PRODUCT_REQUIRED_FILES",
                ("docs/guide.md",),
            ), mock.patch.object(
                conformance_check.product_manifest,
                "PRODUCT_REQUIRED_FILE_SET",
                frozenset({"docs/guide.md"}),
            ), mock.patch.object(
                conformance_check.product_manifest,
                "PRODUCT_DIRECTORY_PATHS",
                frozenset({"docs"}),
            ), mock.patch.object(
                conformance_check.safe_paths,
                "bounded_input_errors",
                side_effect=AssertionError(
                    "exact mode must not perform pathname file validation"
                ),
            ):
                missing_directory = (
                    conformance_check.check_framework_product_files(
                        root,
                        exact_product_tree=True,
                    )
                )
                (root / "docs").mkdir()
                missing_file = conformance_check.check_framework_product_files(
                    root,
                    exact_product_tree=True,
                )

        self.assertEqual(
            ["missing product directory: docs"],
            missing_directory,
        )
        self.assertEqual(
            ["missing product file: docs/guide.md"],
            missing_file,
        )

    def test_exact_product_tree_stops_at_undeclared_directory_without_descent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "README.md").write_text("# Product\n", encoding="utf-8")
            (root / "unexpected-dir").mkdir()
            (root / "unexpected-dir" / "nested.txt").write_text(
                "must not be inspected\n",
                encoding="utf-8",
            )
            root_identity = (root.stat().st_dev, root.stat().st_ino)
            unexpected_identity = (
                (root / "unexpected-dir").stat().st_dev,
                (root / "unexpected-dir").stat().st_ino,
            )
            enumerated: list[tuple[int, int]] = []
            real_scandir = os.scandir

            def observe_scandir(directory_descriptor: int) -> Any:
                metadata = os.fstat(directory_descriptor)
                observed_identity = (metadata.st_dev, metadata.st_ino)
                enumerated.append(observed_identity)
                if observed_identity == unexpected_identity:
                    raise AssertionError(
                        "exact-tree validation descended into contamination"
                    )
                return real_scandir(directory_descriptor)

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
                side_effect=observe_scandir,
            ):
                exact = conformance_check._exact_product_tree_errors(root)

        self.assertEqual(["undeclared product directory: unexpected-dir"], exact)
        self.assertEqual([root_identity], enumerated)

    def test_exact_product_tree_streams_until_first_contaminating_entry(self) -> None:
        class FakeEntry:
            def __init__(self, name: str) -> None:
                self.name = name

            def stat(self, *, follow_symlinks: bool = True) -> os.stat_result:
                raise AssertionError(
                    "exact-tree validation must stat descriptor-relative names"
                )

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
                    FakeEntry("README.md"),
                    FakeEntry("unexpected.txt"),
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
            root_metadata = root.stat()
            docs_metadata = (root / "docs").stat()
            git_metadata_stat = git_metadata.stat()
            expected_scan_targets = {
                (root_metadata.st_dev, root_metadata.st_ino),
                (docs_metadata.st_dev, docs_metadata.st_ino),
            }
            git_identity = (
                git_metadata_stat.st_dev,
                git_metadata_stat.st_ino,
            )
            scan_targets: list[tuple[int, int]] = []
            real_scandir = os.scandir

            def observe_scandir(directory_descriptor: int) -> Any:
                self.assertIsInstance(directory_descriptor, int)
                metadata = os.fstat(directory_descriptor)
                scan_targets.append((metadata.st_dev, metadata.st_ino))
                return real_scandir(directory_descriptor)

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
            ), mock.patch.object(
                conformance_check.os,
                "scandir",
                side_effect=observe_scandir,
            ):
                exact = conformance_check.check_framework_product_files(
                    root,
                    exact_product_tree=True,
                )

        self.assertEqual([], exact)
        self.assertEqual(expected_scan_targets, set(scan_targets))
        self.assertNotIn(git_identity, scan_targets)

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

    @unittest.skipUnless(hasattr(os, "mkfifo"), "requires POSIX FIFOs")
    def test_exact_product_tree_observes_a_causal_special_entry_swap(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            readme = root / "README.md"
            readme.write_text("# Product\n", encoding="utf-8")
            held = root / "held.md"
            swapped = False

            def replace_with_fifo(
                phase: str,
                relative: str,
                _identity: tuple[int, int, int],
            ) -> None:
                nonlocal swapped
                if phase == "before_entry_stat" and relative == "README.md":
                    readme.rename(held)
                    os.mkfifo(readme)
                    swapped = True

            with mock.patch.object(
                conformance_check.product_manifest,
                "PRODUCT_REQUIRED_FILE_SET",
                frozenset({"README.md"}),
            ), mock.patch.object(
                conformance_check.product_manifest,
                "PRODUCT_DIRECTORY_PATHS",
                frozenset(),
            ):
                exact = conformance_check._exact_product_tree_errors(
                    root,
                    _test_hook=replace_with_fifo,
                )

        self.assertTrue(swapped)
        self.assertEqual(
            ["product distribution contains special entry: README.md"],
            exact,
        )

    def test_exact_product_tree_fails_when_descriptor_primitives_are_unsupported(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with mock.patch.object(
                conformance_check,
                "_EXACT_TREE_SCANDIR_SUPPORTS_FD",
                False,
            ):
                missing_scandir = conformance_check._exact_product_tree_errors(root)
            with mock.patch.object(
                conformance_check.os,
                "O_NOFOLLOW",
                0,
                create=True,
            ):
                missing_no_follow = conformance_check._exact_product_tree_errors(root)

        self.assertEqual(
            [
                "exact product tree inspection requires descriptor-safe "
                "filesystem primitives: os.scandir(fd)"
            ],
            missing_scandir,
        )
        self.assertEqual(
            [
                "exact product tree inspection requires descriptor-safe "
                "filesystem primitives: O_NOFOLLOW"
            ],
            missing_no_follow,
        )

    def test_exact_product_tree_never_follows_a_causal_symlink_swap(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            parent = Path(temp_dir)
            root = parent / "product"
            root.mkdir()
            (root / "README.md").write_text("# Product\n", encoding="utf-8")
            docs = root / "docs"
            docs.mkdir()
            (docs / "guide.md").write_text("# Guide\n", encoding="utf-8")
            outside = parent / "outside"
            outside.mkdir()
            (outside / "guide.md").write_text("outside\n", encoding="utf-8")
            held = parent / "held-docs"
            outside_metadata = outside.stat()
            outside_identity = (
                outside_metadata.st_dev,
                outside_metadata.st_ino,
            )
            root_metadata = root.stat()
            root_identity = (root_metadata.st_dev, root_metadata.st_ino)
            enumerated: list[tuple[int, int]] = []
            real_scandir = os.scandir
            swapped = False

            def observe_scandir(directory_descriptor: int) -> Any:
                metadata = os.fstat(directory_descriptor)
                enumerated.append((metadata.st_dev, metadata.st_ino))
                return real_scandir(directory_descriptor)

            def swap_to_symlink(
                phase: str,
                relative: str,
                _identity: tuple[int, int, int],
            ) -> None:
                nonlocal swapped
                if phase == "before_directory_open" and relative == "docs":
                    docs.rename(held)
                    docs.symlink_to(outside, target_is_directory=True)
                    swapped = True

            with mock.patch.object(
                conformance_check.product_manifest,
                "PRODUCT_REQUIRED_FILE_SET",
                frozenset({"README.md", "docs/guide.md"}),
            ), mock.patch.object(
                conformance_check.product_manifest,
                "PRODUCT_DIRECTORY_PATHS",
                frozenset({"docs"}),
            ), mock.patch.object(
                conformance_check.os,
                "scandir",
                side_effect=observe_scandir,
            ):
                exact = conformance_check._exact_product_tree_errors(
                    root,
                    _test_hook=swap_to_symlink,
                )

        self.assertTrue(swapped)
        self.assertEqual(
            ["product distribution directory changed before traversal: docs"],
            exact,
        )
        self.assertEqual({root_identity}, set(enumerated))
        self.assertNotIn(outside_identity, enumerated)

    def test_exact_product_tree_rejects_a_causal_directory_inode_swap(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            parent = Path(temp_dir)
            root = parent / "product"
            root.mkdir()
            (root / "README.md").write_text("# Product\n", encoding="utf-8")
            docs = root / "docs"
            docs.mkdir()
            (docs / "guide.md").write_text("# Guide\n", encoding="utf-8")
            replacement = parent / "replacement-docs"
            replacement.mkdir()
            (replacement / "guide.md").write_text(
                "replacement\n",
                encoding="utf-8",
            )
            held = parent / "held-docs"
            replacement_metadata = replacement.stat()
            replacement_identity = (
                replacement_metadata.st_dev,
                replacement_metadata.st_ino,
            )
            root_metadata = root.stat()
            root_identity = (root_metadata.st_dev, root_metadata.st_ino)
            enumerated: list[tuple[int, int]] = []
            real_scandir = os.scandir
            swapped = False

            def observe_scandir(directory_descriptor: int) -> Any:
                metadata = os.fstat(directory_descriptor)
                enumerated.append((metadata.st_dev, metadata.st_ino))
                return real_scandir(directory_descriptor)

            def swap_directory_inode(
                phase: str,
                relative: str,
                _identity: tuple[int, int, int],
            ) -> None:
                nonlocal swapped
                if phase == "before_directory_open" and relative == "docs":
                    docs.rename(held)
                    replacement.rename(docs)
                    swapped = True

            with mock.patch.object(
                conformance_check.product_manifest,
                "PRODUCT_REQUIRED_FILE_SET",
                frozenset({"README.md", "docs/guide.md"}),
            ), mock.patch.object(
                conformance_check.product_manifest,
                "PRODUCT_DIRECTORY_PATHS",
                frozenset({"docs"}),
            ), mock.patch.object(
                conformance_check.os,
                "scandir",
                side_effect=observe_scandir,
            ):
                exact = conformance_check._exact_product_tree_errors(
                    root,
                    _test_hook=swap_directory_inode,
                )

        self.assertTrue(swapped)
        self.assertEqual(
            ["product distribution directory changed before traversal: docs"],
            exact,
        )
        self.assertEqual({root_identity}, set(enumerated))
        self.assertNotIn(replacement_identity, enumerated)

    def test_exact_product_tree_rejects_an_after_open_name_swap(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            parent = Path(temp_dir)
            root = parent / "product"
            root.mkdir()
            docs = root / "docs"
            docs.mkdir()
            (docs / "guide.md").write_text("# Guide\n", encoding="utf-8")
            replacement = parent / "replacement-docs"
            replacement.mkdir()
            (replacement / "guide.md").write_text(
                "replacement\n",
                encoding="utf-8",
            )
            held = parent / "held-docs"
            root_metadata = root.stat()
            replacement_metadata = replacement.stat()
            root_identity = (root_metadata.st_dev, root_metadata.st_ino)
            replacement_identity = (
                replacement_metadata.st_dev,
                replacement_metadata.st_ino,
            )
            scan_targets: list[tuple[int, int]] = []
            real_scandir = os.scandir
            swapped = False

            def observe_scandir(directory_descriptor: int) -> Any:
                metadata = os.fstat(directory_descriptor)
                scan_targets.append((metadata.st_dev, metadata.st_ino))
                return real_scandir(directory_descriptor)

            def replace_opened_name(
                phase: str,
                relative: str,
                _identity: tuple[int, int, int],
            ) -> None:
                nonlocal swapped
                if phase == "after_directory_open" and relative == "docs":
                    docs.rename(held)
                    replacement.rename(docs)
                    swapped = True

            with mock.patch.object(
                conformance_check.product_manifest,
                "PRODUCT_REQUIRED_FILE_SET",
                frozenset({"docs/guide.md"}),
            ), mock.patch.object(
                conformance_check.product_manifest,
                "PRODUCT_DIRECTORY_PATHS",
                frozenset({"docs"}),
            ), mock.patch.object(
                conformance_check.os,
                "scandir",
                side_effect=observe_scandir,
            ):
                exact = conformance_check._exact_product_tree_errors(
                    root,
                    _test_hook=replace_opened_name,
                )

        self.assertTrue(swapped)
        self.assertEqual(
            [
                "product distribution directory name changed before traversal: "
                "docs"
            ],
            exact,
        )
        self.assertEqual({root_identity}, set(scan_targets))
        self.assertNotIn(replacement_identity, scan_targets)

    def test_exact_product_tree_rejects_post_enumeration_name_replacement(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            parent = Path(temp_dir)
            root = parent / "product"
            root.mkdir()
            readme = root / "README.md"
            readme.write_text("# Product\n", encoding="utf-8")
            replacement = parent / "replacement.md"
            replacement.write_text("replacement\n", encoding="utf-8")
            replaced = False

            def replace_enumerated_name(
                phase: str,
                relative: str,
                _identity: tuple[int, int, int],
            ) -> None:
                nonlocal replaced
                if phase == "after_directory_enumeration" and relative == ".":
                    os.replace(replacement, readme)
                    replaced = True

            with mock.patch.object(
                conformance_check.product_manifest,
                "PRODUCT_REQUIRED_FILE_SET",
                frozenset({"README.md"}),
            ), mock.patch.object(
                conformance_check.product_manifest,
                "PRODUCT_DIRECTORY_PATHS",
                frozenset(),
            ):
                exact = conformance_check._exact_product_tree_errors(
                    root,
                    _test_hook=replace_enumerated_name,
                )

        self.assertTrue(replaced)
        self.assertEqual(
            [
                "product distribution entry name changed during traversal: "
                "README.md"
            ],
            exact,
        )

    def test_exact_product_tree_rejects_post_enumeration_set_changes(self) -> None:
        for mutation in ("add", "remove"):
            with (
                self.subTest(mutation=mutation),
                tempfile.TemporaryDirectory() as temp_dir,
            ):
                root = Path(temp_dir)
                readme = root / "README.md"
                readme.write_text("# Product\n", encoding="utf-8")
                changed = False

                def change_name_set(
                    phase: str,
                    relative: str,
                    _identity: tuple[int, int, int],
                ) -> None:
                    nonlocal changed
                    if (
                        phase != "after_directory_enumeration"
                        or relative != "."
                        or changed
                    ):
                        return
                    if mutation == "add":
                        (root / "extra.txt").write_text(
                            "unexpected\n",
                            encoding="utf-8",
                        )
                    else:
                        readme.unlink()
                    changed = True

                with mock.patch.object(
                    conformance_check.product_manifest,
                    "PRODUCT_REQUIRED_FILE_SET",
                    frozenset({"README.md"}),
                ), mock.patch.object(
                    conformance_check.product_manifest,
                    "PRODUCT_DIRECTORY_PATHS",
                    frozenset(),
                ):
                    exact = conformance_check._exact_product_tree_errors(
                        root,
                        _test_hook=change_name_set,
                    )

                self.assertTrue(changed)
                self.assertEqual(
                    [
                        "product distribution directory entries changed during "
                        "traversal: ."
                    ],
                    exact,
                )

    def test_exact_product_tree_rechecks_directory_edges_after_traversal(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            parent = Path(temp_dir)
            root = parent / "product"
            root.mkdir()
            docs = root / "docs"
            docs.mkdir()
            (docs / "guide.md").write_text("# Guide\n", encoding="utf-8")
            replacement = parent / "replacement-docs"
            replacement.mkdir()
            (replacement / "guide.md").write_text(
                "replacement\n",
                encoding="utf-8",
            )
            held = parent / "held-docs"
            replacement_metadata = replacement.stat()
            replacement_identity = (
                replacement_metadata.st_dev,
                replacement_metadata.st_ino,
            )
            enumerated: list[tuple[int, int]] = []
            real_scandir = os.scandir
            swapped = False

            def observe_scandir(directory_descriptor: int) -> Any:
                metadata = os.fstat(directory_descriptor)
                enumerated.append((metadata.st_dev, metadata.st_ino))
                return real_scandir(directory_descriptor)

            def replace_traversed_edge(
                phase: str,
                relative: str,
                _identity: tuple[int, int, int],
            ) -> None:
                nonlocal swapped
                if (
                    phase == "before_directory_edge_recheck"
                    and relative == "docs"
                ):
                    docs.rename(held)
                    replacement.rename(docs)
                    swapped = True

            with mock.patch.object(
                conformance_check.product_manifest,
                "PRODUCT_REQUIRED_FILE_SET",
                frozenset({"docs/guide.md"}),
            ), mock.patch.object(
                conformance_check.product_manifest,
                "PRODUCT_DIRECTORY_PATHS",
                frozenset({"docs"}),
            ), mock.patch.object(
                conformance_check.os,
                "scandir",
                side_effect=observe_scandir,
            ):
                exact = conformance_check._exact_product_tree_errors(
                    root,
                    _test_hook=replace_traversed_edge,
                )

        self.assertTrue(swapped)
        self.assertEqual(
            [
                "product distribution directory name changed during traversal: "
                "docs"
            ],
            exact,
        )
        self.assertNotIn(replacement_identity, enumerated)

    def test_exact_product_tree_rejects_terminal_incomplete_root_rebind(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            parent = Path(temp_dir)
            root = parent / "product"
            root.mkdir()
            (root / "README.md").write_text("# Product\n", encoding="utf-8")
            replacement = parent / "replacement-product"
            replacement.mkdir()
            root_metadata = root.stat()
            replacement_metadata = replacement.stat()
            root_identity = (root_metadata.st_dev, root_metadata.st_ino)
            replacement_identity = (
                replacement_metadata.st_dev,
                replacement_metadata.st_ino,
            )
            held = parent / "held-product"
            scan_targets: list[tuple[int, int]] = []
            real_scandir = os.scandir
            rebound = False

            def observe_scandir(directory_descriptor: int) -> Any:
                metadata = os.fstat(directory_descriptor)
                scan_targets.append((metadata.st_dev, metadata.st_ino))
                return real_scandir(directory_descriptor)

            def rebind_root_name(
                phase: str,
                relative: str,
                _identity: tuple[int, int, int],
            ) -> None:
                nonlocal rebound
                if phase == "before_root_edge_recheck" and relative == ".":
                    root.rename(held)
                    replacement.rename(root)
                    rebound = True

            with mock.patch.object(
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
                side_effect=observe_scandir,
            ):
                exact = conformance_check._exact_product_tree_errors(
                    root,
                    _test_hook=rebind_root_name,
                )

        self.assertTrue(rebound)
        self.assertEqual(1, len(exact))
        self.assertTrue(
            exact[0].startswith(
                "product distribution root name changed during traversal: "
            ),
            exact,
        )
        self.assertEqual({root_identity}, set(scan_targets))
        self.assertNotIn(replacement_identity, scan_targets)

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

    def test_source_freshness_child_deadline_precedes_parent_cleanup_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "SOURCE_PACKS.md").write_text("# Sources\n", encoding="utf-8")
            (root / "SOURCE_UPDATE.md").write_text("# Update\n", encoding="utf-8")
            with mock.patch.object(
                conformance_check,
                "run_json_child",
                return_value=conformance_check.CheckOutcome(),
            ) as child:
                outcome = conformance_check.check_source_freshness_metadata(root)

        self.assertEqual(conformance_check.CheckOutcome(), outcome)
        child.assert_called_once()
        command = child.call_args.args[1]
        child_deadline = float(command[command.index("--run-deadline") + 1])
        parent_timeout = child.call_args.kwargs["timeout_seconds"]
        self.assertEqual(
            conformance_check.COMMAND_TIMEOUT_SECONDS,
            parent_timeout,
        )
        self.assertEqual(
            conformance_check.NESTED_CHILD_SHUTDOWN_MARGIN_SECONDS,
            parent_timeout - child_deadline,
        )
        self.assertLess(child_deadline, parent_timeout)

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
