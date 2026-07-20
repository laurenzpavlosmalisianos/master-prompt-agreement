"""Regression tests for physical framework-authoring workspace hygiene."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tests.validation_test_support import SCRIPTS_DIR

import authoring_workspace_hygiene  # noqa: E402


class AuthoringWorkspaceHygieneTests(unittest.TestCase):
    def write_policy(
        self,
        root: Path,
        *,
        top_level: tuple[str, ...] = ("evidence", "records", "work"),
        exact_empty: tuple[str, ...] = (),
        subtree_empty: tuple[str, ...] = (),
        disposable: tuple[str, ...] = (),
    ) -> str:
        policy_ref = "conformance/workspace_hygiene.json"
        policy = root / policy_ref
        policy.parent.mkdir(parents=True, exist_ok=True)
        policy.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "allowed_top_level_entries": sorted(top_level),
                    "allowed_empty_directories": sorted(exact_empty),
                    "allowed_empty_subtree_roots": sorted(subtree_empty),
                    "disposable_subtrees": sorted(disposable),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return policy_ref

    @staticmethod
    def candidate_paths(report: dict[str, object]) -> set[str]:
        candidates = report["deletion_candidates"]
        if not isinstance(candidates, list):
            raise AssertionError("deletion_candidates must be a list")
        return {
            item["path"]
            for item in candidates
            if isinstance(item, dict) and isinstance(item.get("path"), str)
        }

    @staticmethod
    def review_codes(report: dict[str, object]) -> set[tuple[str, str]]:
        items = report["review_required"]
        if not isinstance(items, list):
            raise AssertionError("review_required must be a list")
        return {
            (item["path"], item["reason_code"])
            for item in items
            if isinstance(item, dict)
            and isinstance(item.get("path"), str)
            and isinstance(item.get("reason_code"), str)
        }

    def test_authoring_workspace_hygiene_accepts_declared_empty_evidence_roles(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            policy_ref = self.write_policy(
                root,
                exact_empty=(
                    "evidence/research",
                    "evidence/review-handoff",
                ),
                subtree_empty=("work/retained-scans",),
            )
            (root / "evidence/research").mkdir(parents=True)
            (root / "evidence/review-handoff").mkdir(parents=True)
            retained = root / "work/retained-scans/run-1"
            (retained / "empty-reporting-stage").mkdir(parents=True)
            (retained / "manifest.json").write_text("{}\n", encoding="utf-8")

            report = authoring_workspace_hygiene.check_workspace(root, policy_ref)

        self.assertEqual([], report["errors"])
        self.assertEqual([], report["deletion_candidates"])
        self.assertEqual([], report["review_required"])

    def test_authoring_workspace_hygiene_accepts_empty_declared_subtree_root(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            policy_ref = self.write_policy(
                root,
                subtree_empty=("work/retained-scans",),
            )
            (root / "work/retained-scans").mkdir(parents=True)

            report = authoring_workspace_hygiene.check_workspace(root, policy_ref)

        self.assertEqual([], report["errors"])
        self.assertEqual([], report["deletion_candidates"])
        self.assertEqual([], report["review_required"])

    def test_authoring_workspace_hygiene_accepts_empty_declared_subtree_chain(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            policy_ref = self.write_policy(
                root,
                subtree_empty=("work/retained-scans",),
            )
            (root / "work/retained-scans/run-1/empty-stage").mkdir(parents=True)

            report = authoring_workspace_hygiene.check_workspace(root, policy_ref)

        self.assertEqual([], report["errors"])
        self.assertEqual([], report["deletion_candidates"])
        self.assertEqual([], report["review_required"])

    def test_authoring_workspace_hygiene_rejects_unclassified_empty_root(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            policy_ref = self.write_policy(root)
            suspect = root / "orphan_workspace"
            suspect.mkdir()

            report = authoring_workspace_hygiene.check_workspace(root, policy_ref)

            self.assertTrue(suspect.is_dir(), "the report-only check must not delete paths")
        self.assertIn("orphan_workspace", self.candidate_paths(report))
        self.assertIn(
            ("orphan_workspace", "unknown-top-level-entry"),
            self.review_codes(report),
        )

    def test_authoring_workspace_hygiene_rejects_unknown_nonempty_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            policy_ref = self.write_policy(root)
            unknown = root / "warehouse"
            unknown.mkdir()
            (unknown / "record.txt").write_text("retained\n", encoding="utf-8")

            report = authoring_workspace_hygiene.check_workspace(root, policy_ref)

        self.assertNotIn("warehouse", self.candidate_paths(report))
        self.assertIn(
            ("warehouse", "unknown-top-level-entry"),
            self.review_codes(report),
        )

    def test_authoring_workspace_hygiene_rejects_empty_on_demand_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            policy_ref = self.write_policy(
                root,
                top_level=("evidence", "records", "staging", "work"),
            )
            (root / "staging").mkdir()

            report = authoring_workspace_hygiene.check_workspace(root, policy_ref)

        self.assertIn("staging", self.candidate_paths(report))

    def test_authoring_workspace_hygiene_reports_cache_and_stale_refresh_residue(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            policy_ref = self.write_policy(
                root,
                disposable=("records/authoring-temp",),
            )
            cache = root / "scripts/__pycache__"
            cache.mkdir(parents=True)
            (cache / "worker.cpython-314.pyc").write_bytes(b"bytecode")
            refresh_temp = root / "records/authoring-temp"
            refresh_temp.mkdir(parents=True)
            (refresh_temp / "refresh-plan-old.json").write_text("{}\n", encoding="utf-8")

            report = authoring_workspace_hygiene.check_workspace(root, policy_ref)

            self.assertTrue(cache.exists())
            self.assertTrue(refresh_temp.exists())
        candidates = self.candidate_paths(report)
        self.assertEqual({"records", "scripts/__pycache__"}, candidates)

    def test_authoring_workspace_hygiene_closes_residue_cleanup_in_one_report(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            policy_ref = self.write_policy(root)
            residue = root / "work/session/only.tmp"
            residue.parent.mkdir(parents=True)
            residue.write_text("temporary\n", encoding="utf-8")

            report = authoring_workspace_hygiene.check_workspace(root, policy_ref)

            self.assertTrue(
                residue.is_file(),
                "the report-only check must not delete paths",
            )
        self.assertEqual({"work"}, self.candidate_paths(report))

    def test_authoring_workspace_hygiene_preserves_public_root_while_closing_child(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            policy_ref = self.write_policy(root)
            residue = root / "scripts/unused-subtree/only.tmp"
            residue.parent.mkdir(parents=True)
            residue.write_text("temporary\n", encoding="utf-8")

            report = authoring_workspace_hygiene.check_workspace(root, policy_ref)

        candidates = self.candidate_paths(report)
        self.assertIn("scripts/unused-subtree", candidates)
        self.assertNotIn("scripts", candidates)
        self.assertIn(
            ("scripts", "unreferenced-fileless-subtree"),
            self.review_codes(report),
        )

    def test_authoring_workspace_hygiene_ignores_platform_metadata_and_git_internals(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            policy_ref = self.write_policy(root)
            (root / ".DS_Store").write_bytes(b"metadata")
            git_root = root / ".git"
            git_root.mkdir()
            (git_root / ".DS_Store").write_bytes(b"metadata")
            (git_root / "config").write_text("[core]\n", encoding="utf-8")

            report = authoring_workspace_hygiene.check_workspace(root, policy_ref)

        self.assertEqual([], report["errors"])
        self.assertEqual([], report["deletion_candidates"])
        self.assertEqual([], report["review_required"])

    def test_authoring_workspace_hygiene_reports_hostile_platform_metadata_type(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            policy_ref = self.write_policy(root)
            target = root / "ordinary.txt"
            target.write_text("retained\n", encoding="utf-8")
            metadata = root / "scripts/htmlcov/.DS_Store"
            metadata.parent.mkdir(parents=True)
            metadata.symlink_to(target)

            report = authoring_workspace_hygiene.check_workspace(root, policy_ref)

        codes = self.review_codes(report)
        self.assertIn(("scripts/htmlcov/.DS_Store", "symlink-entry"), codes)
        self.assertIn(
            ("scripts/htmlcov", "anomaly-protected-container"),
            codes,
        )
        self.assertNotIn("scripts/htmlcov", self.candidate_paths(report))

    def test_authoring_workspace_hygiene_rejects_platform_metadata_directory(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            policy_ref = self.write_policy(root)
            (root / ".DS_Store").mkdir()

            report = authoring_workspace_hygiene.check_workspace(root, policy_ref)

        self.assertNotIn(".DS_Store", self.candidate_paths(report))
        self.assertIn(
            (".DS_Store", "platform-metadata-kind-mismatch"),
            self.review_codes(report),
        )

    def test_authoring_workspace_hygiene_reserves_transaction_control_state(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            policy_ref = self.write_policy(root)
            control = root / ".mpa-bootstrap-recovery.tmp"
            control.write_text("{}\n", encoding="utf-8")

            report = authoring_workspace_hygiene.check_workspace(root, policy_ref)

        self.assertNotIn(control.name, self.candidate_paths(report))
        self.assertIn(
            (control.name, "transaction-recovery-state"),
            self.review_codes(report),
        )

    def test_authoring_workspace_hygiene_never_proposes_transaction_container(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            policy_ref = self.write_policy(root)
            control = root / "scripts/htmlcov/.mpa-bootstrap-transaction-held"
            control.parent.mkdir(parents=True)
            control.write_text("{}\n", encoding="utf-8")

            report = authoring_workspace_hygiene.check_workspace(root, policy_ref)

        self.assertNotIn("scripts/htmlcov", self.candidate_paths(report))
        codes = self.review_codes(report)
        self.assertIn(
            ("scripts/htmlcov", "transaction-protected-container"),
            codes,
        )
        self.assertIn(
            (
                "scripts/htmlcov/.mpa-bootstrap-transaction-held",
                "transaction-recovery-state",
            ),
            codes,
        )

    def test_authoring_workspace_hygiene_uses_scoped_residue_rules(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            policy_ref = self.write_policy(root)
            retained = root / "examples/dist/manifest.txt"
            retained.parent.mkdir(parents=True)
            retained.write_text("retained\n", encoding="utf-8")
            coverage_data = root / "scripts/.coverage"
            coverage_data.parent.mkdir(parents=True)
            coverage_data.write_bytes(b"generated")
            coverage_report = root / "scripts/htmlcov/index.html"
            coverage_report.parent.mkdir()
            coverage_report.write_text("generated\n", encoding="utf-8")

            report = authoring_workspace_hygiene.check_workspace(root, policy_ref)

        candidates = self.candidate_paths(report)
        self.assertNotIn("examples/dist", candidates)
        self.assertIn("scripts/.coverage", candidates)
        self.assertIn("scripts/htmlcov", candidates)

    def test_authoring_workspace_hygiene_never_follows_symlinks(self) -> None:
        with (
            tempfile.TemporaryDirectory() as temp_dir,
            tempfile.TemporaryDirectory() as outside_dir,
        ):
            root = Path(temp_dir)
            policy_ref = self.write_policy(root)
            outside = Path(outside_dir)
            (outside / ".DS_Store").write_bytes(b"outside")
            review_root = root / "evidence"
            review_root.mkdir()
            (review_root / "alias").symlink_to(outside, target_is_directory=True)

            report = authoring_workspace_hygiene.check_workspace(root, policy_ref)

        self.assertIn(
            ("evidence/alias", "symlink-entry"),
            self.review_codes(report),
        )
        self.assertNotIn(
            "evidence/alias/.DS_Store",
            self.candidate_paths(report),
        )

    def test_authoring_workspace_hygiene_rejects_hardlinked_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            policy_ref = self.write_policy(root)
            link_fixture = root / "examples/links"
            link_fixture.mkdir(parents=True)
            first = link_fixture / "first.txt"
            first.write_text("evidence\n", encoding="utf-8")
            os.link(first, link_fixture / "second.txt")

            report = authoring_workspace_hygiene.check_workspace(root, policy_ref)

        codes = self.review_codes(report)
        self.assertIn(("examples/links/first.txt", "hardlinked-file"), codes)
        self.assertIn(("examples/links/second.txt", "hardlinked-file"), codes)

    def test_authoring_workspace_hygiene_does_not_traverse_nested_mount(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            nested_mount = root / "records/external"
            nested_mount.mkdir(parents=True)
            hidden = nested_mount / "should-not-be-inventoried.tmp"
            hidden.write_text("outside mount payload\n", encoding="utf-8")
            nested_mount_inode = nested_mount.stat().st_ino

            def synthetic_mount_id(descriptor: int) -> int:
                return 2 if os.fstat(descriptor).st_ino == nested_mount_inode else 1

            root_descriptor = os.open(
                root,
                authoring_workspace_hygiene._directory_open_flags(),
            )
            try:
                with mock.patch.object(
                    authoring_workspace_hygiene,
                    "_descriptor_mount_id",
                    side_effect=synthetic_mount_id,
                ):
                    inventory = authoring_workspace_hygiene._scan_once(root_descriptor)
            finally:
                os.close(root_descriptor)

        entries = inventory.as_dict()
        self.assertEqual(1, inventory.root_mount_id)
        self.assertEqual(2, entries["records/external"].mount_id)
        self.assertNotIn("records/external/should-not-be-inventoried.tmp", entries)

    def test_authoring_workspace_hygiene_protects_nested_mount_boundary(self) -> None:
        root_uid = 1000

        def directory(mount_id: int) -> authoring_workspace_hygiene.EntryRecord:
            return authoring_workspace_hygiene.EntryRecord(
                kind="directory",
                signature=(mount_id,),
                mode=0o040755,
                nlink=2,
                uid=root_uid,
                mount_id=mount_id,
            )

        inventory = authoring_workspace_hygiene.Inventory(
            root_signature=(1,),
            root_uid=root_uid,
            root_mount_id=1,
            entries=(
                ("records", directory(1)),
                ("records/external", directory(2)),
            ),
        )
        policy = authoring_workspace_hygiene.Policy(
            allowed_top_level_entries=frozenset({"records"}),
            allowed_empty_directories=frozenset(),
            allowed_empty_subtree_roots=frozenset(),
            disposable_subtrees=frozenset(),
        )

        report = authoring_workspace_hygiene.analyze_inventory(inventory, policy)

        self.assertEqual(set(), self.candidate_paths(report))
        codes = self.review_codes(report)
        self.assertIn(("records/external", "nested-mount-boundary"), codes)
        self.assertIn(("records", "anomaly-protected-container"), codes)

    def test_authoring_workspace_hygiene_never_proposes_anomalous_container(
        self,
    ) -> None:
        root_uid = 1000
        directory = authoring_workspace_hygiene.EntryRecord(
            kind="directory",
            signature=(1,),
            mode=0o040755,
            nlink=2,
            uid=root_uid + 1,
            mount_id=1,
        )
        inventory = authoring_workspace_hygiene.Inventory(
            root_signature=(1,),
            root_uid=root_uid,
            root_mount_id=1,
            entries=(("records", directory),),
        )
        policy = authoring_workspace_hygiene.Policy(
            allowed_top_level_entries=frozenset({"records"}),
            allowed_empty_directories=frozenset(),
            allowed_empty_subtree_roots=frozenset(),
            disposable_subtrees=frozenset(),
        )

        report = authoring_workspace_hygiene.analyze_inventory(inventory, policy)

        self.assertNotIn("records", self.candidate_paths(report))
        codes = self.review_codes(report)
        self.assertIn(("records", "owner-drift"), codes)
        self.assertIn(("records", "anomaly-protected-container"), codes)

    def test_authoring_workspace_hygiene_never_proposes_below_anomaly(self) -> None:
        root_uid = 1000

        def directory(uid: int) -> authoring_workspace_hygiene.EntryRecord:
            return authoring_workspace_hygiene.EntryRecord(
                kind="directory",
                signature=(uid,),
                mode=0o040755,
                nlink=2,
                uid=uid,
                mount_id=1,
            )

        regular = authoring_workspace_hygiene.EntryRecord(
            kind="file",
            signature=(1,),
            mode=0o100644,
            nlink=1,
            uid=root_uid,
            mount_id=1,
        )
        inventory = authoring_workspace_hygiene.Inventory(
            root_signature=(1,),
            root_uid=root_uid,
            root_mount_id=1,
            entries=(
                ("records", directory(root_uid)),
                ("records/foreign", directory(root_uid + 1)),
                ("records/foreign/__pycache__", directory(root_uid)),
                ("records/foreign/__pycache__/worker.pyc", regular),
            ),
        )
        policy = authoring_workspace_hygiene.Policy(
            allowed_top_level_entries=frozenset({"records"}),
            allowed_empty_directories=frozenset(),
            allowed_empty_subtree_roots=frozenset(),
            disposable_subtrees=frozenset(),
        )

        report = authoring_workspace_hygiene.analyze_inventory(inventory, policy)

        self.assertEqual(set(), self.candidate_paths(report))
        self.assertIn(
            ("records/foreign", "owner-drift"),
            self.review_codes(report),
        )

    def test_authoring_workspace_hygiene_policy_rejects_broad_empty_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            policy_ref = self.write_policy(root, subtree_empty=("work",))

            report = authoring_workspace_hygiene.check_workspace(root, policy_ref)

        self.assertTrue(
            any("must remain below a top-level root" in error for error in report["errors"]),
            report,
        )

    def test_authoring_workspace_hygiene_fails_on_entry_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            policy_ref = self.write_policy(root)
            with mock.patch.object(authoring_workspace_hygiene, "MAX_SCAN_ENTRIES", 1):
                report = authoring_workspace_hygiene.check_workspace(root, policy_ref)

        self.assertTrue(
            any("more than 1 inspected entries" in error for error in report["errors"]),
            report,
        )

    def test_authoring_workspace_hygiene_enforces_exact_scan_depth_bound(self) -> None:
        with (
            tempfile.TemporaryDirectory() as accepted_dir,
            tempfile.TemporaryDirectory() as rejected_dir,
        ):
            accepted_root = Path(accepted_dir)
            accepted_leaf = accepted_root / "a/b/leaf.txt"
            accepted_leaf.parent.mkdir(parents=True)
            accepted_leaf.write_text("at limit\n", encoding="utf-8")
            rejected_root = Path(rejected_dir)
            rejected_leaf = rejected_root / "a/b/c/leaf.txt"
            rejected_leaf.parent.mkdir(parents=True)
            rejected_leaf.write_text("over limit\n", encoding="utf-8")

            accepted_descriptor = os.open(
                accepted_root,
                authoring_workspace_hygiene._directory_open_flags(),
            )
            rejected_descriptor = os.open(
                rejected_root,
                authoring_workspace_hygiene._directory_open_flags(),
            )
            try:
                with (
                    mock.patch.object(
                        authoring_workspace_hygiene,
                        "MAX_SCAN_DEPTH",
                        3,
                    ),
                    mock.patch.object(
                        authoring_workspace_hygiene,
                        "_descriptor_mount_id",
                        return_value=1,
                    ),
                ):
                    accepted = authoring_workspace_hygiene._scan_once(
                        accepted_descriptor
                    )
                    with self.assertRaisesRegex(
                        authoring_workspace_hygiene.WorkspaceScanError,
                        "3-component depth bound",
                    ):
                        authoring_workspace_hygiene._scan_once(rejected_descriptor)
            finally:
                os.close(accepted_descriptor)
                os.close(rejected_descriptor)

        self.assertIn("a/b/leaf.txt", accepted.as_dict())

    def test_authoring_workspace_hygiene_bounds_all_diagnostics(self) -> None:
        root_uid = 1000
        regular = authoring_workspace_hygiene.EntryRecord(
            kind="file",
            signature=(1,),
            mode=0o100644,
            nlink=1,
            uid=root_uid,
            mount_id=1,
        )
        entries = tuple(
            (f"unclassified-{index:03d}", regular)
            for index in range(300)
        ) + ((".mpa-bootstrap.lock", regular),)
        inventory = authoring_workspace_hygiene.Inventory(
            root_signature=(1,),
            root_uid=root_uid,
            root_mount_id=1,
            entries=tuple(sorted(entries)),
        )
        policy = authoring_workspace_hygiene.Policy(
            allowed_top_level_entries=frozenset(),
            allowed_empty_directories=frozenset(),
            allowed_empty_subtree_roots=frozenset(),
            disposable_subtrees=frozenset(),
        )

        report = authoring_workspace_hygiene.analyze_inventory(inventory, policy)

        total = (
            len(report["deletion_candidates"])
            + len(report["review_required"])
            + len(report["errors"])
        )
        self.assertLessEqual(total, authoring_workspace_hygiene.MAX_REPORTED_ITEMS)
        self.assertTrue(report["diagnostics_truncated"])
        self.assertGreater(report["omitted_diagnostic_count"], 0)
        self.assertIn(
            (".mpa-bootstrap.lock", "transaction-recovery-state"),
            self.review_codes(report),
        )

    def test_authoring_workspace_hygiene_bounds_policy_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            policy_ref = "conformance/workspace_hygiene.json"
            policy = root / policy_ref
            policy.parent.mkdir(parents=True)
            policy.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "allowed_top_level_entries": list(range(500)),
                        "allowed_empty_directories": [],
                        "allowed_empty_subtree_roots": [],
                        "disposable_subtrees": [],
                    }
                ),
                encoding="utf-8",
            )

            report = authoring_workspace_hygiene.check_workspace(root, policy_ref)

        self.assertLessEqual(
            len(report["errors"]),
            authoring_workspace_hygiene.MAX_REPORTED_ITEMS,
        )
        self.assertTrue(report["diagnostics_truncated"])
        self.assertGreater(report["omitted_diagnostic_count"], 0)

    def test_authoring_workspace_hygiene_bounds_policy_path_depth(self) -> None:
        def policy_bytes(path: str) -> bytes:
            return json.dumps(
                {
                    "schema_version": 1,
                    "allowed_top_level_entries": ["records"],
                    "allowed_empty_directories": [path],
                    "allowed_empty_subtree_roots": [],
                    "disposable_subtrees": [],
                },
                sort_keys=True,
            ).encode("utf-8")

        at_limit = "/".join(
            ("records", *(f"d{index}" for index in range(
                authoring_workspace_hygiene.MAX_SCAN_DEPTH - 1
            )))
        )
        over_limit = at_limit + "/overflow"

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with mock.patch.object(
                authoring_workspace_hygiene.safe_paths,
                "normalize_repo_relative_path",
                side_effect=AssertionError("over-depth path reached normalizer"),
            ) as normalizer:
                normalized, lexical_errors = (
                    authoring_workspace_hygiene._normalize_policy_list(
                        [over_limit],
                        field="allowed_empty_directories",
                        root=root,
                    )
                )
            normalizer.assert_not_called()
            accepted, accepted_errors = authoring_workspace_hygiene.parse_policy(
                policy_bytes(at_limit),
                root,
            )
            rejected, rejected_errors = authoring_workspace_hygiene.parse_policy(
                policy_bytes(over_limit),
                root,
            )

        self.assertEqual([], normalized)
        self.assertTrue(
            any("traversal depth bound" in error for error in lexical_errors),
            lexical_errors,
        )
        self.assertIsNotNone(accepted)
        self.assertEqual([], accepted_errors)
        self.assertIsNone(rejected)
        self.assertTrue(
            any("traversal depth bound" in error for error in rejected_errors),
            rejected_errors,
        )

    def test_authoring_workspace_hygiene_returns_bounded_invalid_root_reports(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            parent = Path(temp_dir)
            missing = parent / "missing"
            ordinary_file = parent / "file"
            ordinary_file.write_text("not a directory\n", encoding="utf-8")
            target = parent / "target"
            target.mkdir()
            policy_ref = self.write_policy(target)
            symlink = parent / "linked-root"
            symlink.symlink_to(target, target_is_directory=True)

            reports = (
                authoring_workspace_hygiene.check_workspace(missing, policy_ref),
                authoring_workspace_hygiene.check_workspace(ordinary_file, policy_ref),
                authoring_workspace_hygiene.check_workspace(symlink, policy_ref),
                authoring_workspace_hygiene.check_workspace(
                    Path("~mpa_no_such_user_749205"),
                    policy_ref,
                ),
            )

        for report in reports:
            self.assertTrue(report["errors"])
            self.assertLessEqual(
                len(report["errors"]),
                authoring_workspace_hygiene.MAX_REPORTED_ITEMS,
            )

    def test_authoring_workspace_hygiene_rejects_control_bearing_names(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            policy_ref = self.write_policy(root)
            (root / "misleading\nname").write_text("payload\n", encoding="utf-8")

            report = authoring_workspace_hygiene.check_workspace(root, policy_ref)

        self.assertTrue(
            any("control characters" in error for error in report["errors"]),
            report,
        )

    def test_authoring_workspace_hygiene_requires_two_equal_scans(self) -> None:
        empty = authoring_workspace_hygiene.Inventory(
            root_signature=(1,),
            root_uid=0,
            root_mount_id=1,
            entries=(),
        )
        changed = authoring_workspace_hygiene.Inventory(
            root_signature=(2,),
            root_uid=0,
            root_mount_id=1,
            entries=(),
        )
        with (
            mock.patch.object(
                authoring_workspace_hygiene,
                "_scan_once",
                side_effect=(empty, changed),
            ),
            self.assertRaisesRegex(
                authoring_workspace_hygiene.WorkspaceScanError,
                "between stability scans",
            ),
        ):
            authoring_workspace_hygiene.scan_stably(-1)


if __name__ == "__main__":
    unittest.main()
