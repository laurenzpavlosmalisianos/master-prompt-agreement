"""Public-surface, release, and export validation tests."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
import unittest
from unittest import mock

from tests.validation_test_support import (
    REPO_ROOT,
    prepare_export_source,
    retained_git_discovery,
    run_bounded,
    string_items,
    write_required_public_files,
)

import public_export  # noqa: E402
import framework_compliance  # noqa: E402
import public_release_check  # noqa: E402
import public_surface  # noqa: E402
import safe_paths  # noqa: E402
import validate_framework  # noqa: E402


def _authoring_fixture_report(root: Path) -> dict[str, object]:
    """Check a synthetic authoring tree with an exact mocked Git inventory."""

    (root / ".git").mkdir(exist_ok=True)
    inventory = public_release_check._inventory_release_tree(root)
    tracked = set(inventory.files) | set(inventory.symlinks)
    if not tracked:
        (root / "README.md").write_text("# Synthetic authoring source\n", encoding="utf-8")
        inventory = public_release_check._inventory_release_tree(root)
        tracked = set(inventory.files) | set(inventory.symlinks)
    with mock.patch.object(
        public_release_check,
        "git_tracked_files",
        side_effect=retained_git_discovery(tracked),
    ):
        return public_release_check.check_public_release(
            root,
            tree_role=public_release_check.ReleaseTreeRole.AUTHORING_SOURCE,
        )


def _prepare_public_export_fixture(root: Path) -> None:
    """Create the immutable sentinel surface required before export sealing."""

    root.chmod(public_release_check.PUBLIC_EXPORT_ROOT_MODE)
    (root / ".gitignore").write_text(
        public_surface.PUBLIC_EXPORT_GITIGNORE_TEXT,
        encoding="utf-8",
    )
    for relative in public_release_check.PUBLIC_EXPORT_SENTINEL_FILES:
        path = root / relative
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# Synthetic public-export sentinel: {relative}\n", encoding="utf-8")


def _write_public_export_marker(root: Path) -> None:
    inventory = public_release_check._inventory_release_tree(root)
    records = {
        relative_path: public_release_check.stable_file_snapshot(
            root / relative_path,
            _expected=metadata,
        )
        for relative_path, metadata in inventory.files.items()
        if relative_path != public_release_check.PUBLIC_EXPORT_OWNERSHIP_MARKER
    }
    public_export.write_ownership_marker(root, records)


def _public_export_fixture_report(root: Path) -> dict[str, object]:
    """Seal and check a synthetic generated public export."""

    _prepare_public_export_fixture(root)
    _write_public_export_marker(root)
    return public_release_check.check_public_release(
        root,
        tree_role=public_release_check.ReleaseTreeRole.PUBLIC_EXPORT,
    )


@contextmanager
def _inject_export_cleanup_fault(
    *,
    when_primary: bool,
    message: str,
) -> Iterator[tuple[list[bool], list[int]]]:
    """Fail the first final resource close and release that descriptor afterward."""

    original_cleanup = public_export._cleanup_export_resources
    original_close = os.close
    injected: list[bool] = []
    leaked_descriptors: list[int] = []
    close_calls: list[int] = []

    def inject(
        descriptors: tuple[tuple[str, int], ...],
        *,
        bindings: tuple[tuple[str, safe_paths.OutputDirectoryBinding], ...] = (),
        actions: tuple[tuple[str, Callable[[], object]], ...] = (),
        primary: BaseException | None = None,
    ) -> None:
        primary_matches = primary is not None if when_primary else primary is None
        if bindings and primary_matches and not injected:
            injected.append(True)

            def fault_first_close(descriptor: int) -> None:
                close_calls.append(descriptor)
                if not leaked_descriptors:
                    leaked_descriptors.append(descriptor)
                    raise OSError(message)
                original_close(descriptor)

            with mock.patch.object(
                public_export.os,
                "close",
                side_effect=fault_first_close,
            ):
                original_cleanup(
                    descriptors,
                    bindings=bindings,
                    actions=actions,
                    primary=primary,
                )
            return
        original_cleanup(
            descriptors,
            bindings=bindings,
            actions=actions,
            primary=primary,
        )

    try:
        with mock.patch.object(
            public_export,
            "_cleanup_export_resources",
            side_effect=inject,
        ):
            yield injected, close_calls
    finally:
        for descriptor in leaked_descriptors:
            try:
                original_close(descriptor)
            except OSError:
                pass


class PublicationTests(unittest.TestCase):
    def test_release_inventory_reports_missing_root_without_creating_it(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = Path(temp_dir) / "missing"

            inventory = public_release_check._inventory_release_tree(missing)

            self.assertFalse(missing.exists())
            self.assertEqual(1, len(inventory.errors), inventory.errors)
            self.assertIn("could not be enumerated safely", inventory.errors[0])

    def test_downstream_effective_identity_includes_declared_lifecycle_owners(self) -> None:
        effective = {
            path.relative_to(REPO_ROOT).as_posix()
            for path in public_surface.iter_downstream_effective_files(REPO_ROOT)
        }

        for relative in public_surface.DOWNSTREAM_EFFECTIVE_EXACT_FILES:
            self.assertIn(relative, effective)
        for owner, commands in public_surface.DOWNSTREAM_EFFECTIVE_SCRIPT_OWNERS.items():
            self.assertIn(owner, effective, owner)
            for command in commands:
                self.assertIn(command, effective, f"{owner} -> {command}")

    def test_downstream_effective_script_identity_is_dependency_closed(self) -> None:
        effective_scripts = {
            path.relative_to(REPO_ROOT).as_posix()
            for path in public_surface.downstream_effective_script_files(REPO_ROOT)
        }

        for relative in (
            "scripts/bootstrap_transaction.py",
            "scripts/project_contract_model.py",
            "scripts/project_input.py",
            "scripts/project_instance_lint.py",
            "scripts/project_state_identity.py",
            "scripts/public_surface.py",
            "scripts/run_scheduled_job.py",
            "scripts/safe_paths.py",
        ):
            self.assertIn(relative, effective_scripts)

        for script in public_surface.downstream_effective_script_files(REPO_ROOT):
            dependencies = {
                path.relative_to(REPO_ROOT).as_posix()
                for path in public_surface._local_script_dependencies(REPO_ROOT, script)
            }
            self.assertLessEqual(
                dependencies,
                effective_scripts,
                script.relative_to(REPO_ROOT).as_posix(),
            )
            self.assertIn(
                script.relative_to(REPO_ROOT).as_posix(),
                public_surface.PUBLIC_REQUIRED_FILES,
            )

    def test_repository_only_commands_remain_distribution_only(self) -> None:
        effective = {
            path.relative_to(REPO_ROOT).as_posix()
            for path in public_surface.iter_downstream_effective_files(REPO_ROOT)
        }
        distribution_only = (
            "scripts/framework_compliance.py",
            "scripts/public_export.py",
            "scripts/public_handoff_check.py",
            "scripts/public_release.py",
            "scripts/public_release_check.py",
            "scripts/public_release_state.py",
            "scripts/validate_framework.py",
        )

        for relative in distribution_only:
            self.assertNotIn(relative, effective)
            self.assertIn(relative, public_surface.PUBLIC_REQUIRED_FILES)
            self.assertFalse(public_surface.is_public_excluded(relative))

    def test_downstream_command_owners_cover_effective_external_dispatches(self) -> None:
        expected = {
            "conformance/profiles.json": "scripts/check_reference_freshness.py",
            "task_orders/compliance.md": "scripts/link_check.py",
            "project_state_templates/SOURCE_MONITOR_RESEARCHER.md": (
                "scripts/source_chain_artifact_lint.py"
            ),
            "project_state_templates/SOURCE_DEEP_RESEARCH.md": (
                "scripts/source_deep_research_lint.py"
            ),
        }
        effective = {
            path.relative_to(REPO_ROOT).as_posix()
            for path in public_surface.iter_downstream_effective_files(REPO_ROOT)
        }

        for owner, command in expected.items():
            with self.subTest(owner=owner, command=command):
                self.assertIn(command, public_surface.DOWNSTREAM_EFFECTIVE_SCRIPT_OWNERS[owner])
                self.assertIn(command, effective)

        compliance = (REPO_ROOT / "task_orders" / "compliance.md").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "<runner> <framework-ref>/scripts/link_check.py --root <project-root>",
            compliance,
        )
        self.assertNotIn(
            "<runner> scripts/link_check.py --root <project-root>",
            compliance,
        )

    def test_downstream_effective_script_closure_follows_local_imports(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            scripts = root / "scripts"
            scripts.mkdir()
            (scripts / "command.py").write_text(
                "import support\nimport json\n",
                encoding="utf-8",
            )
            (scripts / "support.py").write_text(
                "from pathlib import Path\n",
                encoding="utf-8",
            )
            with mock.patch.object(
                public_surface,
                "DOWNSTREAM_EFFECTIVE_SCRIPT_OWNERS",
                {"owner.md": ("scripts/command.py",)},
            ):
                selected = {
                    path.relative_to(root).as_posix()
                    for path in public_surface.downstream_effective_script_files(root)
                }

        self.assertEqual(
            {"scripts/command.py", "scripts/support.py"},
            selected,
        )

    def test_public_release_inventory_failure_is_one_root_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            missing_root = Path(temp_dir) / "missing"
            dependent_phases = (
                "required_public_content_classification_errors",
                "_load_release_inputs",
                "_required_and_tracked_errors",
                "_public_inventory_errors",
                "_public_export_errors",
                "_public_root_symlink_errors",
                "_public_text_errors",
                "_tree_stability_errors",
            )
            patches = [
                mock.patch.object(public_release_check, name)
                for name in dependent_phases
            ]
            started = [patch.start() for patch in patches]
            self.addCleanup(
                lambda: [patch.stop() for patch in reversed(patches)]
            )

            report = public_release_check.check_public_release(
                missing_root,
                tree_role=public_release_check.ReleaseTreeRole.AUTHORING_SOURCE,
            )

        errors = string_items(report["errors"])
        self.assertEqual(1, len(errors), errors)
        self.assertIn(
            "public release tree could not be enumerated safely",
            errors[0],
        )
        for phase_name, phase in zip(dependent_phases, started, strict=True):
            with self.subTest(phase=phase_name):
                phase.assert_not_called()

    def test_public_release_requires_enum_role_at_api_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with self.assertRaisesRegex(TypeError, "tree_role"):
                public_release_check.check_public_release(root)  # type: ignore[call-arg]
            with self.assertRaisesRegex(
                TypeError,
                "tree_role must be a ReleaseTreeRole",
            ):
                public_release_check.check_public_release(
                    root,
                    tree_role="public-export",  # type: ignore[arg-type]
                )

    def test_invalid_release_role_stops_inventory_and_ordinary_scanners(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with (
                mock.patch.object(public_release_check, "_inventory_release_tree") as inventory,
                mock.patch.object(public_release_check, "_load_release_inputs") as load_inputs,
                mock.patch.object(
                    public_release_check,
                    "required_public_content_classification_errors",
                ) as classification,
                self.assertRaisesRegex(TypeError, "tree_role must be a ReleaseTreeRole"),
            ):
                public_release_check.check_public_release(
                    root,
                    tree_role=object(),  # type: ignore[arg-type]
                )

        inventory.assert_not_called()
        load_inputs.assert_not_called()
        classification.assert_not_called()

    def test_authoring_source_rejects_gitless_copied_tree_before_scanning(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "README.md").write_text("# Copied source tree\n", encoding="utf-8")
            with mock.patch.object(public_release_check, "_load_release_inputs") as load_inputs:
                report = public_release_check.check_public_release(
                    root,
                    tree_role=public_release_check.ReleaseTreeRole.AUTHORING_SOURCE,
                )

        self.assertEqual(
            ["authoring-source release check requires a usable Git-tracked inventory"],
            string_items(report["errors"]),
        )
        load_inputs.assert_not_called()

    def test_valid_public_export_never_invokes_git_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "README.md").write_text("# Generated public export\n", encoding="utf-8")
            with mock.patch.object(public_release_check, "git_tracked_files") as git_discovery:
                report = _public_export_fixture_report(root)

        git_discovery.assert_not_called()
        self.assertEqual("public-export", report["tree_role"])
        self.assertFalse(
            any("ownership marker" in error for error in string_items(report["errors"])),
            report["errors"],
        )

    def test_public_release_reuses_one_bound_root_for_inventory_and_ownership(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "nested" / "public"
            root.mkdir(parents=True)
            _prepare_public_export_fixture(root)
            _write_public_export_marker(root)
            inventory_descriptors: list[int] = []
            ownership_descriptors: list[int] = []
            original_inventory = public_release_check._inventory_release_tree_descriptor
            original_ownership = (
                public_release_check.public_export_ownership_descriptor_errors
            )

            def record_inventory(descriptor: int) -> public_release_check._TreeInventory:
                inventory_descriptors.append(descriptor)
                return original_inventory(descriptor)

            def record_ownership(
                descriptor: int,
                *,
                expected_records: Mapping[str, tuple[str, int]] | None = None,
                require_generated_gitignore: bool = True,
            ) -> list[str]:
                ownership_descriptors.append(descriptor)
                return original_ownership(
                    descriptor,
                    expected_records=expected_records,
                    require_generated_gitignore=require_generated_gitignore,
                )

            with (
                mock.patch.object(
                    public_release_check,
                    "_inventory_release_tree_descriptor",
                    side_effect=record_inventory,
                ),
                mock.patch.object(
                    public_release_check,
                    "public_export_ownership_descriptor_errors",
                    side_effect=record_ownership,
                ),
            ):
                public_release_check.check_public_release(
                    root,
                    tree_role=public_release_check.ReleaseTreeRole.PUBLIC_EXPORT,
                )

        self.assertGreaterEqual(len(inventory_descriptors), 2)
        self.assertGreaterEqual(len(ownership_descriptors), 1)
        self.assertEqual(
            1,
            len(set(inventory_descriptors + ownership_descriptors)),
        )

    def test_public_release_terminal_binding_rejects_ancestor_substitution(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            ancestor = base / "ancestor"
            root = ancestor / "public"
            root.mkdir(parents=True)
            _prepare_public_export_fixture(root)
            _write_public_export_marker(root)
            moved = base / "ancestor-moved"
            original_stability = public_release_check._tree_stability_errors

            def substitute_after_final_inventory(
                context: public_release_check._ReleaseCheckContext,
            ) -> None:
                original_stability(context)
                ancestor.rename(moved)
                root.mkdir(parents=True)

            with mock.patch.object(
                public_release_check,
                "_tree_stability_errors",
                side_effect=substitute_after_final_inventory,
            ):
                report = public_release_check.check_public_release(
                    root,
                    tree_role=public_release_check.ReleaseTreeRole.PUBLIC_EXPORT,
                )

        self.assertTrue(
            any(
                error.startswith("public release root pathname changed")
                for error in string_items(report["errors"])
            ),
            report,
        )

    def test_public_release_terminal_binding_rejects_root_mode_change(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "public"
            root.mkdir()
            _prepare_public_export_fixture(root)
            _write_public_export_marker(root)
            original_stability = public_release_check._tree_stability_errors

            def chmod_after_final_inventory(
                context: public_release_check._ReleaseCheckContext,
            ) -> None:
                original_stability(context)
                root.chmod(0o755)

            with mock.patch.object(
                public_release_check,
                "_tree_stability_errors",
                side_effect=chmod_after_final_inventory,
            ):
                report = public_release_check.check_public_release(
                    root,
                    tree_role=public_release_check.ReleaseTreeRole.PUBLIC_EXPORT,
                )

        self.assertTrue(
            any(
                error.startswith("public release root pathname changed")
                for error in string_items(report["errors"])
            ),
            report,
        )

    def test_public_release_binding_ignores_unrelated_sibling_creation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "public"
            root.mkdir()
            _prepare_public_export_fixture(root)
            _write_public_export_marker(root)
            original_stability = public_release_check._tree_stability_errors

            def create_sibling_after_final_inventory(
                context: public_release_check._ReleaseCheckContext,
            ) -> None:
                original_stability(context)
                (base / "unrelated-sibling").mkdir()

            with mock.patch.object(
                public_release_check,
                "_tree_stability_errors",
                side_effect=create_sibling_after_final_inventory,
            ):
                report = public_release_check.check_public_release(
                    root,
                    tree_role=public_release_check.ReleaseTreeRole.PUBLIC_EXPORT,
                )

        self.assertFalse(
            any(
                error.startswith("public release root pathname changed")
                for error in string_items(report["errors"])
            ),
            report,
        )

    def test_public_export_ownership_rejects_ancestor_substitution_after_read(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            ancestor = base / "ancestor"
            root = ancestor / "public"
            root.mkdir(parents=True)
            _prepare_public_export_fixture(root)
            _write_public_export_marker(root)
            moved = base / "ancestor-moved"
            original_ownership = (
                public_release_check.public_export_ownership_descriptor_errors
            )

            def substitute_after_read(
                descriptor: int,
                *,
                expected_records: Mapping[str, tuple[str, int]] | None = None,
                require_generated_gitignore: bool = True,
            ) -> list[str]:
                errors = original_ownership(
                    descriptor,
                    expected_records=expected_records,
                    require_generated_gitignore=require_generated_gitignore,
                )
                ancestor.rename(moved)
                root.mkdir(parents=True)
                return errors

            with mock.patch.object(
                public_release_check,
                "public_export_ownership_descriptor_errors",
                side_effect=substitute_after_read,
            ):
                errors = public_release_check.public_export_ownership_marker_errors(root)

        self.assertTrue(
            any("ownership root changed while it was checked" in error for error in errors),
            errors,
        )

    def test_stable_regular_reader_rejects_same_bytes_terminal_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "policy.json"
            moved = root / "policy-original.json"
            content = b'{"schema_version": 2}\n'
            target.write_bytes(content)
            target.chmod(0o640)
            original_current = public_release_check._RegularFileBinding.require_current
            checks = 0

            def substitute_before_terminal_check(
                binding: public_release_check._RegularFileBinding,
                *,
                description: str,
            ) -> None:
                nonlocal checks
                checks += 1
                if checks == 2:
                    target.rename(moved)
                    target.write_bytes(content)
                    target.chmod(0o640)
                original_current(binding, description=description)

            with (
                mock.patch.object(
                    public_release_check._RegularFileBinding,
                    "require_current",
                    side_effect=substitute_before_terminal_check,
                    autospec=True,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "pathname no longer identifies its bound file",
                ),
            ):
                public_release_check._read_stable_file_bytes(
                    target,
                    description="test policy",
                    max_bytes=1024,
                )

    def test_private_workflow_policy_translates_stable_reader_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            policy_path = root / public_release_check.PRIVATE_WORKFLOW_PATTERNS_PATH
            policy_path.parent.mkdir(parents=True)
            policy_path.write_bytes(b"{}\n")
            expected = policy_path.stat(follow_symlinks=False)
            errors: list[str] = []
            with mock.patch.object(
                public_release_check,
                "_read_stable_file_bytes",
                side_effect=ValueError(
                    "pathname no longer identifies its bound file"
                ),
            ):
                loaded = public_release_check.load_private_workflow_policy(
                    root,
                    errors,
                    required=True,
                    expected=expected,
                    inventory_bound=True,
                )

        self.assertIsNone(loaded)
        self.assertEqual(
            [
                "local private workflow pattern file must be a bounded regular file "
                "and must not use symlink path components: "
                f"{public_release_check.PRIVATE_WORKFLOW_PATTERNS_PATH}: "
                "pathname no longer identifies its bound file"
            ],
            errors,
        )

    def test_public_source_snapshots_reuse_one_root_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            readme = root / "README.md"
            readme.write_text("# Stable source\n", encoding="utf-8")
            expected_snapshot = public_release_check.stable_file_snapshot(readme)
            check_descriptors: list[int] = []
            inventory_descriptors: list[int] = []
            original_inventory = public_release_check._inventory_release_tree_descriptor
            retained_git_inventory = mock.Mock()

            def record_check(
                _root: Path,
                *,
                tree_role: public_release_check.ReleaseTreeRole,
                root_binding: safe_paths.OutputDirectoryBinding,
                _git_inventory: object | None = None,
                _retained_git_inventory_sink: list[object] | None = None,
            ) -> dict[str, object]:
                self.assertIs(
                    public_release_check.ReleaseTreeRole.AUTHORING_SOURCE,
                    tree_role,
                )
                check_descriptors.append(root_binding.descriptor)
                if _retained_git_inventory_sink is not None:
                    _retained_git_inventory_sink.append(retained_git_inventory)
                if _git_inventory is not None:
                    self.assertIs(retained_git_inventory, _git_inventory)
                return {"errors": []}

            def record_inventory(descriptor: int) -> public_release_check._TreeInventory:
                inventory_descriptors.append(descriptor)
                return original_inventory(descriptor)

            with (
                mock.patch.object(
                    public_release_check,
                    "_check_public_release_with_binding",
                    side_effect=record_check,
                ),
                mock.patch.object(
                    public_release_check,
                    "_inventory_release_tree_descriptor",
                    side_effect=record_inventory,
                ),
            ):
                snapshots = public_release_check.checked_public_source_snapshots(
                    root,
                    {"README.md"},
                )

        self.assertEqual(2, len(check_descriptors))
        self.assertGreaterEqual(len(inventory_descriptors), 2)
        self.assertEqual(
            1,
            len(set(check_descriptors + inventory_descriptors)),
        )
        self.assertEqual(
            expected_snapshot,
            snapshots["README.md"],
        )

    def test_authoring_source_rejects_public_export_marker_before_git_or_scanning(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".git").mkdir()
            (root / public_release_check.PUBLIC_EXPORT_OWNERSHIP_MARKER).write_text(
                "{}\n",
                encoding="utf-8",
            )
            with (
                mock.patch.object(public_release_check, "git_tracked_files") as git_discovery,
                mock.patch.object(public_release_check, "_load_release_inputs") as load_inputs,
            ):
                report = public_release_check.check_public_release(
                    root,
                    tree_role=public_release_check.ReleaseTreeRole.AUTHORING_SOURCE,
                )

        self.assertEqual(
            [
                "authoring-source tree contains reserved public-export ownership "
                "marker path: .mpa-public-export.json"
            ],
            string_items(report["errors"]),
        )
        git_discovery.assert_not_called()
        load_inputs.assert_not_called()

    def test_public_export_missing_and_stale_markers_fail_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "README.md").write_text("# Export\n", encoding="utf-8")
            _prepare_public_export_fixture(root)
            with mock.patch.object(public_release_check, "_load_release_inputs") as load_inputs:
                missing = public_release_check.check_public_release(
                    root,
                    tree_role=public_release_check.ReleaseTreeRole.PUBLIC_EXPORT,
                )
                _write_public_export_marker(root)
                (root / "README.md").write_text("# Mutated export\n", encoding="utf-8")
                stale = public_release_check.check_public_release(
                    root,
                    tree_role=public_release_check.ReleaseTreeRole.PUBLIC_EXPORT,
                )

        self.assertIn(
            "public export is missing ownership marker: .mpa-public-export.json",
            string_items(missing["errors"]),
        )
        self.assertIn(
            "public export ownership marker digest mismatch for: README.md",
            string_items(stale["errors"]),
        )
        load_inputs.assert_not_called()

    def test_public_export_marker_binds_posix_rwx_mode_with_schema_two(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _prepare_public_export_fixture(root)
            readme = root / "README.md"
            readme.chmod(0o640)
            _write_public_export_marker(root)
            marker = json.loads(
                (root / public_release_check.PUBLIC_EXPORT_OWNERSHIP_MARKER).read_text(
                    encoding="utf-8"
                )
            )

            self.assertEqual(2, marker["schema_version"])
            self.assertEqual(
                {"posix_mode", "sha256"},
                set(marker["files"]["README.md"]),
            )
            self.assertEqual(0o640, marker["files"]["README.md"]["posix_mode"])

            marker_path = root / public_release_check.PUBLIC_EXPORT_OWNERSHIP_MARKER
            self.assertEqual(
                public_release_check.PUBLIC_EXPORT_MARKER_MODE,
                stat.S_IMODE(marker_path.stat().st_mode),
            )
            marker_path.chmod(0o777)
            self.assertIn(
                "public export ownership marker POSIX rwx mode must equal "
                "0o644: .mpa-public-export.json",
                public_release_check.public_export_ownership_marker_errors(root),
            )
            marker_path.chmod(public_release_check.PUBLIC_EXPORT_MARKER_MODE)

            stale_schema_marker = json.loads(json.dumps(marker))
            stale_schema_marker["schema_version"] = 1
            marker_path.write_text(
                json.dumps(stale_schema_marker),
                encoding="utf-8",
            )
            self.assertIn(
                "public export ownership marker schema_version must equal 2",
                public_release_check.public_export_ownership_marker_errors(root),
            )

            invalid_marker = json.loads(json.dumps(marker))
            invalid_marker["files"]["README.md"]["posix_mode"] = 0o1000
            marker_path.write_text(
                json.dumps(invalid_marker),
                encoding="utf-8",
            )
            self.assertIn(
                "public export ownership marker has invalid digest/mode records for: README.md",
                public_release_check.public_export_ownership_marker_errors(root),
            )
            marker_path.write_text(json.dumps(marker), encoding="utf-8")

            readme.chmod(0o740)
            self.assertIn(
                "public export ownership marker POSIX rwx mode mismatch for: README.md",
                public_release_check.public_export_ownership_marker_errors(root),
            )

    def test_public_export_ownership_requires_exact_full_modes(self) -> None:
        mutations = (
            ("root-special", ".", 0o1700, "root mode must equal 0o700"),
            (
                "directory-special",
                "scripts",
                0o2755,
                "directory mode must equal 0o755: scripts",
            ),
            (
                "marker-special",
                public_release_check.PUBLIC_EXPORT_OWNERSHIP_MARKER,
                0o4644,
                "ownership marker POSIX rwx mode must equal 0o644",
            ),
            (
                "product-special",
                "README.md",
                0o4644,
                "POSIX rwx mode mismatch for: README.md",
            ),
            (
                "directory-rwx",
                "scripts",
                0o775,
                "directory mode must equal 0o755: scripts",
            ),
        )
        for label, relative, mode, expected in mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                _prepare_public_export_fixture(root)
                _write_public_export_marker(root)
                target = root if relative == "." else root / relative
                target.chmod(mode)

                errors = public_release_check.public_export_ownership_marker_errors(root)

                self.assertTrue(any(expected in error for error in errors), errors)

    def test_public_export_marker_payload_is_deterministic_from_expected_records(self) -> None:
        records = {
            relative_path: ("a" * 64, 0o640)
            for relative_path in sorted(
                public_release_check.PUBLIC_EXPORT_SENTINEL_FILES
            )
        }
        reversed_records = dict(reversed(tuple(records.items())))

        self.assertEqual(
            public_release_check.public_export_marker_payload(records),
            public_release_check.public_export_marker_payload(reversed_records),
        )

    def test_public_export_with_git_path_keeps_export_role_and_never_falls_back(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "README.md").write_text("# Export\n", encoding="utf-8")
            _prepare_public_export_fixture(root)
            _write_public_export_marker(root)
            (root / ".git").mkdir()
            with mock.patch.object(public_release_check, "git_tracked_files") as git_discovery:
                report = public_release_check.check_public_release(
                    root,
                    tree_role=public_release_check.ReleaseTreeRole.PUBLIC_EXPORT,
                )

        self.assertEqual("public-export", report["tree_role"])
        self.assertIn(
            "public export ownership tree has unrecorded directories: .git",
            string_items(report["errors"]),
        )
        git_discovery.assert_not_called()

    def test_public_release_git_runner_delegates_with_exact_policy(self) -> None:
        version_result = public_release_check.bounded_subprocess.BoundedProcessResult(
            args=("git", "--version"),
            returncode=0,
            stdout=b"git version 2.55.0\n",
            stderr=b"",
            timed_out=False,
            output_exceeded=False,
        )
        result = public_release_check.bounded_subprocess.BoundedProcessResult(
            args=("git", "ls-files", "-z"),
            returncode=9,
            stdout=b"tracked\0",
            stderr=b"diagnostic",
            timed_out=False,
            output_exceeded=False,
        )
        root = Path.cwd()
        gitdir = root / ".git"
        with mock.patch.object(
            public_release_check.bounded_subprocess,
            "run_bounded_process",
            side_effect=(version_result, result),
        ) as run:
            observed = public_release_check._bounded_git_ls_files(root, gitdir)

        self.assertEqual((9, b"tracked\0", b"diagnostic"), observed)
        expected_environment = {
            **public_release_check._sanitized_git_environment(),
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_OPTIONAL_LOCKS": "0",
        }
        expected_process_policy = {
            "cwd": root,
            "env": expected_environment,
            "pass_fds": (),
            "timeout_seconds": public_release_check.GIT_COMMAND_TIMEOUT_SECONDS,
            "max_output_bytes": public_release_check.GIT_COMMAND_MAX_OUTPUT_BYTES,
            "maximum_timeout_seconds": public_release_check.GIT_COMMAND_TIMEOUT_SECONDS,
            "maximum_output_bytes": public_release_check.GIT_COMMAND_MAX_OUTPUT_BYTES,
            "termination_grace_seconds": public_release_check.GIT_TERMINATION_GRACE_SECONDS,
        }
        expected_version_policy = {
            **expected_process_policy,
            "env": {**expected_environment, "LC_ALL": "C"},
        }
        self.assertEqual(
            mock.call(["git", "--version"], **expected_version_policy),
            run.call_args_list[0],
        )
        self.assertEqual(
            mock.call(
                [
                    "git",
                    "--no-optional-locks",
                    "-c",
                    "core.fsmonitor=false",
                    "-c",
                    "core.untrackedCache=false",
                    "-C",
                    str(root),
                    f"--git-dir={gitdir}",
                    f"--work-tree={root}",
                    "ls-files",
                    "--stage",
                    "--sparse",
                    "-z",
                ],
                **expected_process_policy,
            ),
            run.call_args_list[1],
        )

    def test_public_release_rejects_old_git_before_index_inspection(self) -> None:
        old_version = public_release_check.bounded_subprocess.BoundedProcessResult(
            args=("git", "--version"),
            returncode=0,
            stdout=b"git version 2.35.1\n",
            stderr=b"",
            timed_out=False,
            output_exceeded=False,
        )
        root = Path.cwd()
        with (
            mock.patch.object(
                public_release_check.bounded_subprocess,
                "run_bounded_process",
                return_value=old_version,
            ) as run,
            self.assertRaisesRegex(RuntimeError, "Git 2.36.0 or newer"),
        ):
            public_release_check._bounded_git_ls_files(root, root / ".git")

        run.assert_called_once()

    def test_authoring_release_rejects_concurrent_git_index_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "README.md").write_text("# Tracked\n", encoding="utf-8")
            candidate = root / "candidate.md"
            candidate.write_text(
                "# Present but initially untracked\n",
                encoding="utf-8",
            )
            run_bounded(["git", "init", "-q"], cwd=root, check=True)
            run_bounded(["git", "add", "README.md"], cwd=root, check=True)
            original_text_check = public_release_check._public_text_errors

            def mutate_index(context: public_release_check._ReleaseCheckContext) -> None:
                original_text_check(context)
                run_bounded(["git", "add", "candidate.md"], cwd=root, check=True)

            with mock.patch.object(
                public_release_check,
                "_public_text_errors",
                side_effect=mutate_index,
            ):
                report = public_release_check.check_public_release(
                    root,
                    tree_role=public_release_check.ReleaseTreeRole.AUTHORING_SOURCE,
                )

        self.assertTrue(
            any(
                error.startswith(
                    "Git-tracked inventory changed while the authoring-source "
                    "release tree was being checked"
                )
                for error in string_items(report["errors"])
            ),
            report,
        )

    def test_public_release_git_runner_preserves_failure_diagnostics(self) -> None:
        cases = (
            (
                True,
                False,
                "git ls-files timed out after 60s",
            ),
            (
                False,
                True,
                "git ls-files output exceeded the 4194304-byte limit",
            ),
        )
        for timed_out, output_exceeded, expected in cases:
            version_result = public_release_check.bounded_subprocess.BoundedProcessResult(
                args=("git", "--version"),
                returncode=0,
                stdout=b"git version 2.55.0\n",
                stderr=b"",
                timed_out=False,
                output_exceeded=False,
            )
            result = public_release_check.bounded_subprocess.BoundedProcessResult(
                args=("git", "ls-files", "-z"),
                returncode=-9,
                stdout=b"partial stdout",
                stderr=b"partial stderr",
                timed_out=timed_out,
                output_exceeded=output_exceeded,
            )
            with (
                self.subTest(expected=expected),
                mock.patch.object(
                    public_release_check.bounded_subprocess,
                    "run_bounded_process",
                    side_effect=(version_result, result),
                ),
                self.assertRaises(RuntimeError) as raised,
            ):
                public_release_check._bounded_git_ls_files(
                    Path.cwd(),
                    Path.cwd() / ".git",
                )
            self.assertEqual(expected, str(raised.exception))

        start_error = public_release_check.bounded_subprocess.BoundedSubprocessStartError(
            "bounded subprocess could not start: git unavailable"
        )
        start_error.__cause__ = OSError("git unavailable")
        with (
            mock.patch.object(
                public_release_check.bounded_subprocess,
                "run_bounded_process",
                side_effect=(
                    public_release_check.bounded_subprocess.BoundedProcessResult(
                        args=("git", "--version"),
                        returncode=0,
                        stdout=b"git version 2.55.0\n",
                        stderr=b"",
                        timed_out=False,
                        output_exceeded=False,
                    ),
                    start_error,
                ),
            ),
            self.assertRaises(RuntimeError) as raised,
        ):
            public_release_check._bounded_git_ls_files(
                Path.cwd(),
                Path.cwd() / ".git",
            )
        self.assertEqual("git ls-files could not start: git unavailable", str(raised.exception))

    def test_public_release_preserves_nonzero_and_nul_path_output_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_bounded(["git", "init", "-q"], cwd=root, check=True)
            (root / "seed.txt").write_text("seed\n", encoding="utf-8")
            run_bounded(["git", "add", "seed.txt"], cwd=root, check=True)
            inventory = public_release_check._inventory_release_tree(root)

            with mock.patch.object(
                    public_release_check,
                    "_bounded_git_ls_files",
                    return_value=(23, b"ignored", b" fatal \xff error \n"),
                ):
                with self.assertRaises(RuntimeError) as raised:
                    public_release_check.git_tracked_files(root, _inventory=inventory)
            self.assertEqual(
                "immutable Git index snapshot is unsupported or could not be "
                "parsed: fatal � error",
                str(raised.exception),
            )

            oid = b"0" * 40
            stdout = (
                b"100644 " + oid + b" 0\tdocs/line\nbreak.md\0"
                b"100644 " + oid + b" 0\tdocs/space name.md\0"
                b"100644 " + oid + b" 1\tdocs/line\nbreak.md\0"
            )
            with mock.patch.object(
                    public_release_check,
                    "_bounded_git_ls_files",
                    return_value=(0, stdout, b""),
                ):
                tracked = public_release_check.git_tracked_files(
                    root,
                    _inventory=inventory,
                )
            self.assertEqual(
                {"docs/line\nbreak.md", "docs/space name.md"},
                tracked,
            )

            with mock.patch.object(
                    public_release_check,
                    "_bounded_git_ls_files",
                    return_value=(
                        0,
                        b"100644 " + oid + b" 0\tdocs/\xff.md\0",
                        b"",
                    ),
                ):
                with self.assertRaisesRegex(RuntimeError, "not valid UTF-8"):
                    public_release_check.git_tracked_files(
                        root,
                        _inventory=inventory,
                    )

            with mock.patch.object(
                public_release_check,
                "_bounded_git_ls_files",
                return_value=(
                    0,
                    b"100644 " + oid + b" 0\tdocs/unterminated.md",
                    b"",
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "unterminated"):
                    public_release_check.git_tracked_files(
                        root,
                        _inventory=inventory,
                    )

    def test_source_deep_research_manual_template_is_declared_public(self) -> None:
        rel = "project_state_templates/SOURCE_DEEP_RESEARCH.md"

        self.assertIn(rel, public_surface.PUBLIC_REQUIRED_FILES)
        self.assertFalse(public_surface.is_public_excluded(rel))
        self.assertTrue(public_surface.is_public_excluded("SOURCE_DEEP_RESEARCH.md"))
        self.assertIn(
            "/SOURCE_DEEP_RESEARCH.md",
            public_surface.PUBLIC_GITIGNORE_PATTERNS,
        )
        self.assertFalse(
            any(
                rel in error
                for error in validate_framework.project_state_template_inventory_errors()
            )
        )

    def test_release_inventory_treats_git_metadata_as_opaque_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            metadata_root = root / ".git"
            metadata_root.mkdir()
            volatile = metadata_root / "fsmonitor--daemon.ipc"
            volatile.write_text("first", encoding="utf-8")

            first = public_release_check._inventory_release_tree(root)
            self.assertEqual((), first.errors)
            self.assertIn(".git", first.directories)
            self.assertNotIn(".git/fsmonitor--daemon.ipc", first.files)

            volatile.unlink()
            (metadata_root / "index.lock").write_text("second", encoding="utf-8")
            second = public_release_check._inventory_release_tree(root)
            self.assertEqual((), second.errors)
            self.assertEqual(
                public_release_check._inventory_signature(first),
                public_release_check._inventory_signature(second),
            )

    def test_release_inventory_binds_regular_gitfile_and_rejects_hardlinks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            gitfile = root / ".git"
            gitfile.write_text("gitdir: first\n", encoding="utf-8")
            first = public_release_check._inventory_release_tree(root)

            gitfile.write_text("gitdir: replacement-target\n", encoding="utf-8")
            second = public_release_check._inventory_release_tree(root)

            self.assertEqual((), first.errors)
            self.assertEqual((), second.errors)
            self.assertNotEqual(
                public_release_check._inventory_signature(first),
                public_release_check._inventory_signature(second),
            )

            alias = root / "gitfile-alias"
            alias.hardlink_to(gitfile)
            hardlinked = public_release_check._inventory_release_tree(root)
            with self.assertRaisesRegex(RuntimeError, "exactly one hard link"):
                public_release_check.git_tracked_files(root, _inventory=hardlinked)

    def test_git_inventory_binds_ordinary_and_registered_linked_worktrees(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            ordinary = base / "ordinary"
            linked = base / "linked"
            ordinary.mkdir()
            (ordinary / "tracked.txt").write_text("tracked\n", encoding="utf-8")
            run_bounded(["git", "init", "-q"], cwd=ordinary, check=True)
            run_bounded(["git", "add", "tracked.txt"], cwd=ordinary, check=True)
            run_bounded(
                [
                    "git",
                    "-c",
                    "user.name=Fixture",
                    "-c",
                    "user.email=fixture@example.invalid",
                    "commit",
                    "-qm",
                    "fixture",
                ],
                cwd=ordinary,
                check=True,
            )

            ordinary_tracked = public_release_check.git_tracked_files(ordinary)
            self.assertEqual({"tracked.txt"}, ordinary_tracked)

            run_bounded(
                [
                    "git",
                    "worktree",
                    "add",
                    "-q",
                    "-b",
                    "fixture-linked",
                    str(linked),
                ],
                cwd=ordinary,
                check=True,
            )
            linked_tracked = public_release_check.git_tracked_files(linked)
            self.assertEqual({"tracked.txt"}, linked_tracked)

    def test_git_inventory_parses_real_sha256_index_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "sha256.txt").write_text("tracked\n", encoding="utf-8")
            run_bounded(
                ["git", "init", "-q", "--object-format=sha256"],
                cwd=root,
                check=True,
            )
            run_bounded(["git", "add", "sha256.txt"], cwd=root, check=True)

            tracked = public_release_check.git_tracked_files(root)

        self.assertEqual({"sha256.txt"}, tracked)

    def test_git_inventory_rejects_split_index_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "tracked.txt").write_text("tracked\n", encoding="utf-8")
            run_bounded(["git", "init", "-q"], cwd=root, check=True)
            run_bounded(["git", "add", "tracked.txt"], cwd=root, check=True)
            run_bounded(["git", "update-index", "--split-index"], cwd=root, check=True)

            with self.assertRaisesRegex(
                RuntimeError,
                "immutable Git index snapshot is unsupported or could not be parsed",
            ):
                public_release_check.git_tracked_files(root)

    def test_git_inventory_rejects_real_sparse_index_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "keep").mkdir()
            (root / "omitted").mkdir()
            (root / "keep" / "tracked.txt").write_text(
                "tracked\n",
                encoding="utf-8",
            )
            (root / "omitted" / "hidden.txt").write_text(
                "hidden\n",
                encoding="utf-8",
            )
            run_bounded(["git", "init", "-q"], cwd=root, check=True)
            run_bounded(["git", "add", "."], cwd=root, check=True)
            run_bounded(
                [
                    "git",
                    "-c",
                    "user.name=Fixture",
                    "-c",
                    "user.email=fixture@example.invalid",
                    "commit",
                    "-qm",
                    "fixture",
                ],
                cwd=root,
                check=True,
            )
            run_bounded(
                ["git", "sparse-checkout", "init", "--cone", "--sparse-index"],
                cwd=root,
                check=True,
            )
            run_bounded(
                ["git", "sparse-checkout", "set", "keep"],
                cwd=root,
                check=True,
            )

            with self.assertRaisesRegex(
                RuntimeError,
                "immutable Git index snapshot is unsupported or could not be parsed",
            ):
                public_release_check.git_tracked_files(root)

    def test_git_stage_inventory_rejects_sparse_directory_entries(self) -> None:
        oid = b"0" * 40
        with self.assertRaisesRegex(RuntimeError, "sparse Git indexes are unsupported"):
            public_release_check._parse_git_stage_inventory(
                b"040000 " + oid + b" 0\tsparse-directory\0",
                object_format="sha1",
            )

    def test_git_inventory_cleanup_preserves_primary_and_closes_all_bindings(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "tracked.txt").write_text("tracked\n", encoding="utf-8")
            run_bounded(["git", "init", "-q"], cwd=root, check=True)
            run_bounded(["git", "add", "tracked.txt"], cwd=root, check=True)
            original_copy = public_release_check._copy_git_index_snapshot
            original_cleanup = public_release_check._close_git_inventory_resources
            later_descriptors: list[int] = []
            ambiguous_snapshot_descriptors: list[int] = []
            cleanup_calls: list[str] = []
            snapshot_close_calls: list[str] = []
            raw_close_calls: list[int] = []
            original_os_close = os.close
            primary_failure = RuntimeError("primary parse failure")

            def close_test_descriptor(descriptor: int) -> None:
                try:
                    original_os_close(descriptor)
                except OSError:
                    pass

            class FaultingSnapshot:
                def __init__(self, descriptor: int) -> None:
                    self._descriptor = descriptor

                def fileno(self) -> int:
                    raise AssertionError(
                        "cleanup must not inspect an ambiguously closed descriptor"
                    )

                def close(self) -> None:
                    snapshot_close_calls.append("close")
                    raise OSError("injected snapshot close failure")

            def copy_with_faulting_close(
                index: public_release_check._RegularFileBinding,
                *,
                temporary_root: Path | None = None,
            ) -> tuple[object, str]:
                snapshot, object_format = original_copy(
                    index,
                    temporary_root=temporary_root,
                )
                descriptor = os.dup(snapshot.fileno())
                snapshot.close()
                ambiguous_snapshot_descriptors.append(descriptor)
                self.addCleanup(close_test_descriptor, descriptor)
                return FaultingSnapshot(descriptor), object_format

            def observe_raw_close(descriptor: int) -> None:
                raw_close_calls.append(descriptor)
                original_os_close(descriptor)

            def observe_cleanup(
                snapshot: object,
                index: object,
                gitdir: object,
                *,
                primary: BaseException | None = None,
            ) -> None:
                cleanup_calls.append("called")
                if index is not None:
                    later_descriptors.append(index.descriptor)  # type: ignore[attr-defined]
                    later_descriptors.extend(index.parent.descriptors)  # type: ignore[attr-defined]
                later_descriptors.extend(gitdir.descriptors)  # type: ignore[attr-defined]
                original_cleanup(
                    snapshot,  # type: ignore[arg-type]
                    index,  # type: ignore[arg-type]
                    gitdir,  # type: ignore[arg-type]
                    primary=primary,
                )

            with (
                mock.patch.object(
                    public_release_check,
                    "_copy_git_index_snapshot",
                    side_effect=copy_with_faulting_close,
                ),
                mock.patch.object(
                    public_release_check,
                    "_tracked_files_from_git_index_snapshot",
                    side_effect=primary_failure,
                ),
                mock.patch.object(
                    public_release_check,
                    "_close_git_inventory_resources",
                    side_effect=observe_cleanup,
                ),
                mock.patch.object(
                    public_release_check.os,
                    "close",
                    side_effect=observe_raw_close,
                ),
                self.assertRaisesRegex(RuntimeError, "primary parse failure") as raised,
            ):
                public_release_check.git_tracked_files(root)

            self.assertEqual(["called"], cleanup_calls)
            self.assertIs(primary_failure, raised.exception)
            self.assertEqual(["close"], snapshot_close_calls)
            self.assertEqual(1, len(ambiguous_snapshot_descriptors))
            self.assertNotIn(ambiguous_snapshot_descriptors[0], raw_close_calls)
            self.assertIn(
                "injected snapshot close failure",
                "\n".join(getattr(raised.exception, "__notes__", ())),
            )
            for descriptor in set(later_descriptors):
                with self.subTest(descriptor=descriptor), self.assertRaises(OSError):
                    os.fstat(descriptor)

    def test_regular_binding_cleanup_preserves_interruption_and_closes_parent(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "input.txt"
            path.write_text("input\n", encoding="utf-8")
            interruption = KeyboardInterrupt("injected regular binding interruption")
            captured: list[int] = []
            file_descriptor: list[int] = []
            original_close = os.close
            close_faulted = False

            def interrupt_after_binding(
                binding: public_release_check._RegularFileBinding,
                *,
                description: str,
            ) -> None:
                del description
                file_descriptor.append(binding.descriptor)
                captured.append(binding.descriptor)
                captured.extend(binding.parent.descriptors)
                raise interruption

            def close_file_then_fault(descriptor: int) -> None:
                nonlocal close_faulted
                original_close(descriptor)
                if descriptor in file_descriptor and not close_faulted:
                    close_faulted = True
                    raise OSError("injected regular file close failure")

            with (
                mock.patch.object(
                    public_release_check._RegularFileBinding,
                    "require_current",
                    autospec=True,
                    side_effect=interrupt_after_binding,
                ),
                mock.patch.object(
                    public_release_check.os,
                    "close",
                    side_effect=close_file_then_fault,
                ),
                self.assertRaises(KeyboardInterrupt) as raised,
            ):
                public_release_check._open_regular_descriptor(
                    path,
                    description="test regular file",
                )

            self.assertIs(interruption, raised.exception)
            self.assertTrue(close_faulted)
            self.assertIn(
                "injected regular file close failure",
                "\n".join(getattr(raised.exception, "__notes__", ())),
            )
            for descriptor in set(captured):
                with self.subTest(descriptor=descriptor), self.assertRaises(OSError):
                    os.fstat(descriptor)

    def test_stable_reader_cleanup_cannot_mask_interruption(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "input.txt"
            path.write_text("input\n", encoding="utf-8")
            interruption = KeyboardInterrupt("injected stable read interruption")
            original_close = public_release_check._RegularFileBinding.close

            def close_then_fault(
                binding: public_release_check._RegularFileBinding,
            ) -> None:
                original_close(binding)
                raise OSError("injected stable reader close failure")

            with (
                mock.patch.object(
                    public_release_check.os,
                    "read",
                    side_effect=interruption,
                ),
                mock.patch.object(
                    public_release_check._RegularFileBinding,
                    "close",
                    autospec=True,
                    side_effect=close_then_fault,
                ),
                self.assertRaises(KeyboardInterrupt) as raised,
            ):
                public_release_check.stable_file_snapshot(path)

            self.assertIs(interruption, raised.exception)
            self.assertIn(
                "injected stable reader close failure",
                "\n".join(getattr(raised.exception, "__notes__", ())),
            )

    def test_directory_binding_traversal_owns_current_and_next_descriptors(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir)
            original_open = os.open
            original_close = os.close
            opened: list[int] = []
            close_faulted = False

            def record_open(*args: object, **kwargs: object) -> int:
                descriptor = original_open(*args, **kwargs)  # type: ignore[arg-type]
                opened.append(descriptor)
                return descriptor

            def close_then_fault(descriptor: int) -> None:
                nonlocal close_faulted
                original_close(descriptor)
                if not close_faulted:
                    close_faulted = True
                    raise OSError("injected directory traversal close failure")

            with (
                mock.patch.object(
                    public_release_check.os,
                    "open",
                    side_effect=record_open,
                ),
                mock.patch.object(
                    public_release_check.os,
                    "close",
                    side_effect=close_then_fault,
                ),
                self.assertRaisesRegex(
                    OSError,
                    "injected directory traversal close failure",
                ),
            ):
                public_release_check._open_directory_descriptor(
                    path,
                    description="test directory",
                )

            self.assertGreaterEqual(len(opened), 2)
            for descriptor in set(opened):
                with self.subTest(descriptor=descriptor), self.assertRaises(OSError):
                    os.fstat(descriptor)

    def test_git_inventory_immutable_snapshot_resists_index_aba_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "repo"
            root.mkdir()
            (root / "tracked.txt").write_text("tracked\n", encoding="utf-8")
            (root / "alternate.txt").write_text("alternate\n", encoding="utf-8")
            run_bounded(["git", "init", "-q"], cwd=root, check=True)
            run_bounded(["git", "add", "tracked.txt"], cwd=root, check=True)
            index_path = root / ".git" / "index"
            original_content = index_path.read_bytes()
            original_mode = stat.S_IMODE(index_path.stat().st_mode)
            run_bounded(["git", "add", "alternate.txt"], cwd=root, check=True)
            alternate_index = base / "alternate-index"
            alternate_index.write_bytes(index_path.read_bytes())
            alternate_index.chmod(original_mode)
            restored = base / "restored-index"
            restored.write_bytes(original_content)
            restored.chmod(original_mode)
            os.replace(restored, index_path)
            original_parser = (
                public_release_check._tracked_files_from_git_index_snapshot
            )
            observed_snapshot: list[frozenset[str]] = []

            def swap_during_snapshot_parse(
                parse_root: Path,
                snapshot: object,
                *,
                object_format: str,
                git_command: str = "git",
                git_pass_fds: tuple[int, ...] = (),
                temporary_root: Path | None = None,
                inherit_non_git_environment: bool = True,
            ) -> frozenset[str]:
                bound_original = base / "bound-original-index"
                replaced_alternate = base / "parsed-alternate-index"
                index_path.rename(bound_original)
                alternate_index.rename(index_path)
                try:
                    parsed = original_parser(
                        parse_root,
                        snapshot,  # type: ignore[arg-type]
                        object_format=object_format,
                        git_command=git_command,
                        git_pass_fds=git_pass_fds,
                        temporary_root=temporary_root,
                        inherit_non_git_environment=inherit_non_git_environment,
                    )
                    observed_snapshot.append(parsed)
                    return parsed
                finally:
                    index_path.rename(replaced_alternate)
                    replacement = base / "same-bytes-new-inode"
                    replacement.write_bytes(original_content)
                    replacement.chmod(original_mode)
                    os.replace(replacement, index_path)

            with (
                mock.patch.object(
                    public_release_check,
                    "_tracked_files_from_git_index_snapshot",
                    side_effect=swap_during_snapshot_parse,
                ),
                self.assertRaises((RuntimeError, ValueError)),
            ):
                public_release_check.git_tracked_files(root)

        self.assertEqual([frozenset({"tracked.txt"})], observed_snapshot)

    def test_git_inventory_ignores_ambient_git_control_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "root"
            foreign = base / "foreign"
            root.mkdir()
            foreign.mkdir()
            (root / "owned.txt").write_text("owned\n", encoding="utf-8")
            (foreign / "foreign.txt").write_text("foreign\n", encoding="utf-8")
            for repository, tracked in ((root, "owned.txt"), (foreign, "foreign.txt")):
                run_bounded(["git", "init", "-q"], cwd=repository, check=True)
                run_bounded(["git", "add", tracked], cwd=repository, check=True)

            with mock.patch.dict(
                os.environ,
                {
                    "GIT_DIR": str(foreign / ".git"),
                    "GIT_WORK_TREE": str(foreign),
                    "GIT_INDEX_FILE": str(foreign / ".git" / "index"),
                },
            ):
                tracked = public_release_check.git_tracked_files(root)

            self.assertEqual({"owned.txt"}, tracked)

    def test_git_inventory_rejects_empty_foreign_and_redirected_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)

            empty = base / "empty"
            (empty / ".git").mkdir(parents=True)
            with self.assertRaisesRegex(RuntimeError, "must not be empty"):
                public_release_check.git_tracked_files(empty)

            main = base / "main"
            linked = base / "linked"
            foreign = base / "foreign"
            main.mkdir()
            (main / "tracked.txt").write_text("tracked\n", encoding="utf-8")
            run_bounded(["git", "init", "-q"], cwd=main, check=True)
            run_bounded(["git", "add", "tracked.txt"], cwd=main, check=True)
            run_bounded(
                [
                    "git",
                    "-c",
                    "user.name=Fixture",
                    "-c",
                    "user.email=fixture@example.invalid",
                    "commit",
                    "-qm",
                    "fixture",
                ],
                cwd=main,
                check=True,
            )
            run_bounded(
                [
                    "git",
                    "worktree",
                    "add",
                    "-q",
                    "-b",
                    "fixture-foreign",
                    str(linked),
                ],
                cwd=main,
                check=True,
            )
            linked_gitdir = (linked / ".git").read_text(encoding="utf-8").split(": ", 1)[1].strip()
            foreign.mkdir()
            (foreign / ".git").write_text(
                f"gitdir: {linked_gitdir}\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "backlink does not identify"):
                public_release_check.git_tracked_files(foreign)

            redirected = base / "redirected"
            external_worktree = base / "external-worktree"
            redirected.mkdir()
            external_worktree.mkdir()
            run_bounded(["git", "init", "-q"], cwd=redirected, check=True)
            run_bounded(
                ["git", "config", "core.worktree", str(external_worktree)],
                cwd=redirected,
                check=True,
            )
            self.assertEqual(
                set(),
                public_release_check.git_tracked_files(redirected),
            )

    def test_public_release_scanner_covers_external_review_reference(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            private_reference = "external_" + "review/report.md"
            (root / "README.md").write_text(
                f"Use {private_reference} as release evidence.\n",
                encoding="utf-8",
            )

            report = _authoring_fixture_report(root)

        self.assertTrue(
            any(
                "private or generated local-state reference leaked into public release file: README.md:1"
                in error
                for error in string_items(report["errors"])
            ),
            report,
        )

    def test_public_release_scans_each_interactive_document_text_type(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            interactive = root / "docs" / "interactive"
            interactive.mkdir(parents=True)
            private_reference = "external_" + "review/report.md"
            for filename in ("index.html", "styles.css", "app.ts", "app.js"):
                (interactive / filename).write_text(
                    f"{private_reference}\n",
                    encoding="utf-8",
                )

            report = _authoring_fixture_report(root)

        errors = string_items(report["errors"])
        for filename in ("index.html", "styles.css", "app.ts", "app.js"):
            with self.subTest(filename=filename):
                self.assertTrue(
                    any(
                        "private or generated local-state reference leaked into public release file: "
                        f"docs/interactive/{filename}:1" in error
                        for error in errors
                    ),
                    report,
                )

    def test_public_release_allows_benign_key_property_access(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            interactive = root / "docs" / "interactive"
            interactive.mkdir(parents=True)
            (interactive / "app.js").write_text(
                'if (event.key === "Enter") handleInput();\n',
                encoding="utf-8",
            )

            report = _authoring_fixture_report(root)

        self.assertFalse(
            any(
                "secret or local credential reference leaked into public release file: "
                "docs/interactive/app.js" in error
                for error in string_items(report["errors"])
            ),
            report,
        )

    def test_every_required_public_file_is_scanned_or_explicitly_binary(self) -> None:
        self.assertEqual(
            public_release_check.required_public_content_classification_errors(),
            [],
        )

        with mock.patch.object(
            public_surface,
            "PUBLIC_REQUIRED_FILES",
            (*public_surface.PUBLIC_REQUIRED_FILES, "assets/unreviewed-format.bin"),
        ):
            self.assertEqual(
                public_release_check.required_public_content_classification_errors(),
                [
                    "public required file lacks a content-scan classification: "
                    "assets/unreviewed-format.bin"
                ],
            )

        private_required = "private" + "/secret.md"
        with mock.patch.object(
            public_surface,
            "PUBLIC_REQUIRED_FILES",
            (*public_surface.PUBLIC_REQUIRED_FILES, private_required),
        ):
            self.assertEqual(
                [
                    f"public required file is outside public roots: {private_required}",
                    f"public required file is excluded from publication: {private_required}",
                ],
                public_release_check.required_public_content_classification_errors(),
            )

    def test_release_tree_roles_separate_authoring_exclusions_from_public_export(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            authoring_root = Path(temp_dir) / "authoring"
            export_root = Path(temp_dir) / "export"
            for root in (authoring_root, export_root):
                refs = root / "private" / "references"
                refs.mkdir(parents=True)
                (refs / "sources.md").write_text("# Sources\n", encoding="utf-8")
                (root / "internal_framework_state.md").write_text(
                    "# Internal\n",
                    encoding="utf-8",
                )

            authoring = _authoring_fixture_report(authoring_root)
            strict = _public_export_fixture_report(export_root)

            self.assertEqual(2, authoring["tracked_file_count"])
            self.assertFalse(
                any(
                    "excluded private/local path" in error
                    for error in string_items(authoring["errors"])
                )
            )
            self.assertTrue(
                any(
                    "excluded private/local path exists" in error
                    for error in string_items(strict["errors"])
                )
            )
            self.assertTrue(public_release_check.is_public_excluded("internal_framework_state.md"))

    def test_public_surface_excludes_nested_state_files_except_templates(self) -> None:
        self.assertTrue(public_surface.is_public_excluded("practice_guides/TODO.md"))
        self.assertTrue(public_surface.is_public_excluded("scripts/DECISIONS.md"))
        self.assertTrue(public_surface.is_public_excluded("conformance/ARBITRATION.md"))

        self.assertFalse(public_surface.is_public_excluded("project_state_templates/TODO.md"))
        self.assertFalse(public_surface.is_public_excluded("project_state_templates/SOURCE_PACKS.md"))

    def test_authoring_instance_metadata_is_trackable_but_publicly_excluded(self) -> None:
        authoring_paths = (
            "PROJECT_INSTANCE.json",
            "private" + "/authoring/PROJECT_INPUT.json",
        )

        for relative in authoring_paths:
            with self.subTest(invariant="public-exclusion", relative=relative):
                self.assertTrue(public_surface.is_public_excluded(relative))
                self.assertNotIn(relative, public_surface.PUBLIC_REQUIRED_FILES)

        git_control = REPO_ROOT / ".git"
        if not git_control.exists():
            marker = REPO_ROOT / public_surface.PUBLIC_EXPORT_OWNERSHIP_MARKER
            self.assertTrue(
                marker.is_file(),
                "non-Git validation tree must be an owned generated public export",
            )
            self.assertEqual(
                public_surface.PUBLIC_EXPORT_GITIGNORE_TEXT,
                (REPO_ROOT / ".gitignore").read_text(encoding="utf-8"),
            )
            self.assertLessEqual(
                {"/PROJECT_INPUT.json", "/PROJECT_INSTANCE.json", "/private/**"},
                set(public_surface.PUBLIC_GITIGNORE_PATTERNS),
            )
            for relative in authoring_paths:
                with self.subTest(surface="public-export", relative=relative):
                    self.assertFalse((REPO_ROOT / relative).exists())
            return

        for relative in authoring_paths:
            with self.subTest(surface="authoring", relative=relative):
                ignored = run_bounded(
                    [
                        "git",
                        "check-ignore",
                        "--no-index",
                        "--quiet",
                        "--",
                        relative,
                    ],
                    cwd=REPO_ROOT,
                    check=False,
                )
                self.assertEqual(1, ignored.returncode)

    def test_public_release_rejects_tracked_files_outside_declared_surface(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "UNDECLARED.md").write_text("# Extra\n", encoding="utf-8")
            with mock.patch.object(
                public_release_check,
                "git_tracked_files",
                side_effect=retained_git_discovery({"UNDECLARED.md"}),
            ):
                (root / ".git").mkdir()
                report = public_release_check.check_public_release(
                    root,
                    tree_role=public_release_check.ReleaseTreeRole.AUTHORING_SOURCE,
                )

        self.assertTrue(
            any(
                "tracked file is outside public release surface: UNDECLARED.md" in error
                for error in string_items(report["errors"])
            )
        )

    def test_authoring_source_rejects_empty_git_inventory_before_scanning(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "README.md").write_text("# Public Tree\n", encoding="utf-8")
            (root / ".git").mkdir()

            with (
                mock.patch.object(
                    public_release_check,
                    "git_tracked_files",
                    side_effect=retained_git_discovery(set()),
                ),
                mock.patch.object(public_release_check, "_load_release_inputs") as load_inputs,
            ):
                report = public_release_check.check_public_release(
                    root,
                    tree_role=public_release_check.ReleaseTreeRole.AUTHORING_SOURCE,
                )

        self.assertEqual(
            ["authoring-source release check requires a nonempty Git-tracked inventory"],
            string_items(report["errors"]),
        )
        load_inputs.assert_not_called()

    def test_empty_git_inventory_close_fault_is_reported_without_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_bounded(["git", "init", "-q"], cwd=root, check=True)
            original_close = public_release_check._GitInventoryBinding.close

            def close_then_fault(
                binding: public_release_check._GitInventoryBinding,
            ) -> None:
                original_close(binding)
                raise OSError("injected retained-binding close failure")

            with mock.patch.object(
                public_release_check._GitInventoryBinding,
                "close",
                autospec=True,
                side_effect=close_then_fault,
            ):
                report = public_release_check.check_public_release(
                    root,
                    tree_role=public_release_check.ReleaseTreeRole.AUTHORING_SOURCE,
                )

        errors = string_items(report["errors"])
        self.assertTrue(any("nonempty Git-tracked inventory" in item for item in errors))
        self.assertTrue(
            any("Git inventory cleanup failed" in item for item in errors),
            errors,
        )

    def test_public_release_rejects_undeclared_file_inside_public_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            docs = root / "practice_guides" / "zz_temp_local"
            docs.mkdir(parents=True)
            (docs / "notes.md").write_text("# Local Notes\n", encoding="utf-8")

            report = _authoring_fixture_report(root)

        self.assertTrue(
            any(
                "undeclared public-surface file: practice_guides/zz_temp_local/notes.md" in error
                for error in string_items(report["errors"])
            )
        )

    def test_public_release_rejects_public_symlink_and_file_uri_host_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            readme = root / "README.md"
            outside = Path(temp_dir) / "outside.md"
            readme.write_text(
                "file:///" + "Users" + "/alice/workspace\n"
                + "file:///"
                + "C:"
                + "/"
                + "Users"
                + "/alice/workspace\n"
                + "/"
                + "tmp/public-export\n"
                + "/"
                + "private"
                + "/"
                + "tmp/public-export\n"
                + "/"
                + "workspace/project\n"
                + "/"
                + "workspaces/project\n"
                + "/"
                + "mnt/shared/project\n",
                encoding="utf-8",
            )
            outside.write_text("private" + "/source.md\n", encoding="utf-8")
            (root / "AGENTS.md").symlink_to(outside)

            report = _authoring_fixture_report(root)

            report_errors = string_items(report["errors"])
            self.assertTrue(any("host-specific absolute path" in error for error in report_errors))
            self.assertTrue(any("symlink path" in error for error in report_errors))
            self.assertFalse(any("AGENTS.md" in error and "private or generated" in error for error in report_errors))

    def test_public_release_rejects_generated_artifacts_and_local_path_references(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "scripts" / "__pycache__").mkdir(parents=True)
            (root / "README.md").write_text(
                "See "
                + "notes"
                + "/"
                + "source"
                + " for background.\nSee "
                + "scratch"
                + "/run.txt for local output.\nUse .env.local for secrets.\n"
                + "Nested public paths must still be caught: docs/private/source.md and public/tmp/session.\n",
                encoding="utf-8",
            )
            (root / "scripts" / "__pycache__" / "tool.cpython-313.pyc").write_bytes(b"pyc")
            (root / ".DS_Store").write_bytes(b"store")
            (root / "report.pdf").write_bytes(b"pdf")
            (root / "EXTRA.md").write_text("# Extra\n", encoding="utf-8")

            strict = _public_export_fixture_report(root)

            self.assertTrue(public_release_check.is_public_excluded("scripts/__pycache__/tool.cpython-313.pyc"))
            self.assertTrue(public_release_check.is_public_excluded(".DS_Store"))
            strict_errors = string_items(strict["errors"])
            self.assertTrue(
                any(
                    "excluded private/local path exists in public export: .DS_Store" in error
                    for error in strict_errors
                )
            )
            self.assertTrue(
                any(
                    "excluded private/local path exists in public export: report.pdf" in error
                    for error in strict_errors
                )
            )
            self.assertTrue(
                any(
                    "unexpected file outside public export surface: EXTRA.md" in error
                    for error in strict_errors
                )
            )
            self.assertTrue(
                any("local-only workspace path reference" in error for error in strict_errors)
            )
            self.assertTrue(
                any("private or generated local-state reference" in error for error in strict_errors)
            )
            self.assertTrue(
                any("secret or local credential reference" in error for error in strict_errors)
            )

    def test_public_release_scans_public_scripts_for_private_path_leaks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            scripts = root / "scripts"
            scripts.mkdir()
            (scripts / "leaky.py").write_text(
                'PATH = "private/source.md"\n'
                'WIN_PATH = "private\\\\source.md"\n'
                'CRED = "credentials.json"\n'
                'STATE = ".codex/config.json"\n'
                'WIN_STATE = ".aws\\\\credentials"\n'
                'CLIENT_SECRET = "client_secret-prod.json"\n'
                'KEY = "id_rsa.key"\n'
                'AWS = ".aws/credentials"\n',
                encoding="utf-8",
            )

            report = _authoring_fixture_report(root)

        self.assertTrue(
            any(
                "private or generated local-state reference leaked into public release file: scripts/leaky.py" in error
                for error in string_items(report["errors"])
            )
        )
        self.assertTrue(
            any(
                "secret or local credential reference leaked into public release file: scripts/leaky.py" in error
                for error in string_items(report["errors"])
            )
        )

    def test_public_release_rejects_high_confidence_credential_values_without_echoing_them(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            github = "ghp_" + "Ab3dEf6hJk9mNp2qRs5vWx8zYc4bTg7u"
            aws = "AKIA" + "A1B2C3D4E5F6G7H8"
            bearer = "Authorization: " + "Bearer " + "r4Nd0mizedTokenValue_987654321"
            jwt = "eyJhbGciOiJIUzI1NiJ9" + "." + "eyJzdWIiOiIxMjM0NTY3ODkwIn0" + "." + "c2lnbmF0dXJlMTIzNDU2"
            private_key = "-----BEGIN " + "PRIVATE KEY-----"
            credential_url = "https://" + "user:password@example.invalid/path"
            generic = "N7vQ2pLm8Xc4Rz6Ua9Kd3Tf5"
            (root / "README.md").write_text(
                "\n".join(
                    (
                        github,
                        aws,
                        bearer,
                        jwt,
                        private_key,
                        credential_url,
                        f'client_secret = "{generic}"',
                    )
                )
                + "\n",
                encoding="utf-8",
            )

            report = _public_export_fixture_report(root)

        secret_errors = [
            error
            for error in string_items(report["errors"])
            if "credential-like secret value" in error
        ]
        expected_diagnostics = {
            1: "provider-token value",
            2: "provider-token value",
            3: "authorization bearer value",
            4: "JWT-like value",
            5: "private-key header",
            6: "credential-bearing URL",
            7: "assigned secret-like value",
        }
        for line_no, secret_kind in expected_diagnostics.items():
            with self.subTest(line_no=line_no, secret_kind=secret_kind):
                self.assertIn(
                    "credential-like secret value "
                    f"({secret_kind}) leaked into public release file: README.md:{line_no}",
                    secret_errors,
                )
        for candidate in (
            github,
            aws,
            bearer,
            jwt,
            private_key,
            credential_url,
            generic,
        ):
            self.assertFalse(any(candidate in error for error in secret_errors), secret_errors)

    def test_public_release_rejects_structured_json_and_yaml_env_secret_assignments(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runtime = root / "runtime"
            runtime.mkdir()
            json_secret = "Q7mV2rK9xL4pT8nC6wF3sD5h"
            yaml_secret = "L8qN4vR7xK2mP9tC5wD3sF6j"
            env_secret = "T6pW3nK8rV5xQ2mL9cF4sD7h"
            quoted_yaml_secret = "R9xK4mT7pV2nL8qC5wF3sD6j"
            sensitive_key = "client_" + "secret"
            (runtime / "credential-fixture.json").write_text(
                json.dumps({"nested": [{sensitive_key: json_secret}]}),
                encoding="utf-8",
            )
            (root / "README.md").write_text(
                "api_" + "key: " + yaml_secret + "\n"
                + "ACCESS_" + "TOKEN=" + env_secret + "\n"
                + "'pass" + "word': '" + quoted_yaml_secret + "'\n",
                encoding="utf-8",
            )

            report = _public_export_fixture_report(root)

        secret_errors = [
            error
            for error in string_items(report["errors"])
            if "credential-like secret value" in error
        ]
        self.assertTrue(
            any("structured sensitive JSON key: client_secret" in error for error in secret_errors),
            secret_errors,
        )
        for line_no in range(1, 4):
            with self.subTest(line_no=line_no):
                self.assertIn(
                    "credential-like secret value (assigned secret-like value) "
                    f"leaked into public release file: README.md:{line_no}",
                    secret_errors,
                )
        for candidate in (json_secret, yaml_secret, env_secret, quoted_yaml_secret):
            self.assertFalse(any(candidate in error for error in secret_errors), secret_errors)

    def test_public_release_secret_assignment_scan_allows_references_and_placeholders(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runtime = root / "runtime"
            runtime.mkdir()
            sensitive_key = "client_" + "secret"
            (runtime / "placeholder-fixture.json").write_text(
                json.dumps(
                    {
                        "nested": {
                            sensitive_key: "REPLACE_WITH_APPROVED_SECRET_STORE_REFERENCE",
                            "password": "${PROJECT_PASSWORD}",
                            "auth_token": "vault://team/token-reference",
                        }
                    }
                ),
                encoding="utf-8",
            )
            (root / "README.md").write_text(
                "client_" + "secret: replace-with-secret-store\n"
                + "ACCESS_" + "TOKEN=${PROJECT_TOKEN}\n"
                + "pass" + "word: configured-via-keychain\n",
                encoding="utf-8",
            )

            report = _public_export_fixture_report(root)

        self.assertFalse(
            any(
                "credential-like secret value" in error
                for error in string_items(report["errors"])
            ),
            report["errors"],
        )

    def test_public_release_secret_value_scan_allows_policy_prose_and_placeholders(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "README.md").write_text(
                "Bearer tokens, private keys, JWTs, and provider credentials must never be committed.\n"
                'client_secret = "REPLACE_WITH_APPROVED_SECRET_STORE_REFERENCE"\n',
                encoding="utf-8",
            )

            report = _public_export_fixture_report(root)

        self.assertFalse(
            any("credential-like secret value" in error for error in string_items(report["errors"])),
            report["errors"],
        )

    def test_public_release_test_allowlist_does_not_hide_sensitive_assertion_content(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            tests = root / "tests"
            tests.mkdir()
            (tests / "test_validation_scripts.py").write_text(
                'public_release_note = "Use .' + 'aws/credentials here"\n'
                'public_surface_note = "Use .' + 'aws/credentials here"\n',
                encoding="utf-8",
            )

            report = _authoring_fixture_report(root)

        matching_errors = [
            error
            for error in string_items(report["errors"])
            if "secret or local credential reference leaked into public release file: tests/test_validation_scripts.py" in error
        ]
        self.assertEqual(2, len(matching_errors))

    def test_public_release_test_allowlist_does_not_hide_broad_variable_names(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            tests = root / "tests"
            tests.mkdir()
            (tests / "test_validation_scripts.py").write_text(
                'outputs = "' + "private" + '/customer.md"\n'
                'return_value = ".' + 'aws/credentials"\n',
                encoding="utf-8",
            )

            report = _authoring_fixture_report(root)

        errors = string_items(report["errors"])
        self.assertTrue(
            any(
                "private or generated local-state reference leaked into public release file: tests/test_validation_scripts.py:1"
                in error
                for error in errors
            )
        )
        self.assertTrue(
            any(
                "secret or local credential reference leaked into public release file: tests/test_validation_scripts.py:2"
                in error
                for error in errors
            )
        )

    def test_public_release_test_allowlist_does_not_hide_private_state_content(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            tests = root / "tests"
            tests.mkdir()
            (tests / "test_validation_scripts.py").write_text(
                'PRIVATE_REFERENCES = [\n    "See external_' + 'review/report.md"\n]\n',
                encoding="utf-8",
            )

            report = _authoring_fixture_report(root)

        self.assertTrue(
            any(
                "private or generated local-state reference leaked into public release file: tests/test_validation_scripts.py"
                in error
                for error in string_items(report["errors"])
            )
        )

    def test_public_release_rejects_directory_only_and_arbitrary_local_state_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            docs = root / "practice_guides"
            docs.mkdir()
            (docs / "leaky.md").write_text(
                "Scratch path: " + "t" + "mp" + "/\n"
                + "Scratch path: " + "scratch" + "/cache/\n"
                + "Scratch path: " + "local" + "/image.svg\n"
                + "Scratch path: " + "transcripts" + "/session.py\n",
                encoding="utf-8",
            )

            report = _authoring_fixture_report(root)

        errors = string_items(report["errors"])
        for line_no in range(1, 5):
            with self.subTest(line_no=line_no):
                self.assertIn(
                    "local-only workspace path reference leaked into public release file: "
                    f"practice_guides/leaky.md:{line_no}",
                    errors,
                )

    def test_public_release_allows_narrow_secret_warning_lines(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            annexes = root / "annexes"
            annexes.mkdir()
            (annexes / "security.md").write_text(
                "Never commit secret-bearing `.env` files, credential exports, local keyrings, vault tokens, OAuth tokens, private keys, or secret snapshots.\n",
                encoding="utf-8",
            )

            report = _authoring_fixture_report(root)

        self.assertFalse(
            any(
                "secret or local credential reference leaked into public release file: annexes/security.md" in error
                for error in string_items(report["errors"])
            )
        )

    def test_public_release_allowlist_is_line_scoped_for_string_literals(self) -> None:
        cases = (
            ("ordinary", 'UNRELATED = "' + "private" + '/secret.md"\n'),
            ("raw", 'UNRELATED = r"' + "private" + '/secret.md"\n'),
        )
        for literal_kind, assignment in cases:
            with (
                self.subTest(literal_kind=literal_kind),
                tempfile.TemporaryDirectory() as temp_dir,
            ):
                root = Path(temp_dir)
                scripts = root / "scripts"
                scripts.mkdir()
                (scripts / "public_release_check.py").write_text(
                    'PRIVATE_STATE_RE = re.compile("' + "private" + '/")\n'
                    + assignment,
                    encoding="utf-8",
                )

                report = _authoring_fixture_report(root)

            self.assertTrue(
                any(
                    "private or generated local-state reference leaked into public "
                    "release file: scripts/public_release_check.py:2" in error
                    for error in string_items(report["errors"])
                )
            )

    def test_public_release_scanner_raw_string_references_are_not_self_allowlisted(self) -> None:
        rel = "scripts/public_release_check.py"
        workflow_name = "private-runner-alpha"
        workflow_reference_re = re.compile(
            rf"(?<![\w-]){workflow_name}(?![\w-])"
        )
        cases = (
            (
                f'    r"{"private" + "/client.md"}",',
                None,
                (
                    "private or generated local-state reference leaked into public release file",
                ),
            ),
            (
                f'    r"{"/" + "Us" + "ers/alice/" + "private" + "/client.md"}",',
                None,
                (
                    "host-specific absolute path leaked into public release file",
                    "private or generated local-state reference leaked into public release file",
                ),
            ),
            (
                f'    r"{"." + "env.local"}",',
                None,
                (
                    "secret or local credential reference leaked into public release file",
                ),
            ),
            (
                f'    r"{workflow_name}",',
                workflow_reference_re,
                ("private workflow reference leaked into public release file",),
            ),
        )

        for line, private_workflow_reference_re, expected_errors in cases:
            with self.subTest(expected_errors=expected_errors):
                errors = public_release_check._line_leak_errors(
                    rel,
                    1,
                    line,
                    structured_secret_keys=set(),
                    private_workflow_reference_re=private_workflow_reference_re,
                )

                for expected in expected_errors:
                    self.assertIn(f"{expected}: {rel}:1", errors)

    def test_public_release_scanner_modeled_pattern_does_not_hide_mixed_leak(self) -> None:
        rel = "scripts/public_release_check.py"
        modeled_private_line = '        r"review_' + 'artifacts/",'
        mixed_private_line = (
            modeled_private_line[:-1]
            + ' + r" '
            + "private"
            + '/client.md",'
        )
        modeled_host_value = '"/' + "t" + 'mp/project"'
        modeled_host_line = f"        r'{modeled_host_value}',"
        mixed_host_line = (
            modeled_host_line[:-1]
            + ' + r"/'
            + "Us"
            + 'ers/alice/workspace",'
        )

        for modeled_line in (modeled_private_line, modeled_host_line):
            with self.subTest(control=modeled_line):
                self.assertEqual(
                    [],
                    public_release_check._line_leak_errors(
                        rel,
                        1,
                        modeled_line,
                        structured_secret_keys=set(),
                        private_workflow_reference_re=None,
                    ),
                )

        private_errors = public_release_check._line_leak_errors(
            rel,
            1,
            mixed_private_line,
            structured_secret_keys=set(),
            private_workflow_reference_re=None,
        )
        host_errors = public_release_check._line_leak_errors(
            rel,
            1,
            mixed_host_line,
            structured_secret_keys=set(),
            private_workflow_reference_re=None,
        )

        self.assertIn(
            f"private or generated local-state reference leaked into public release file: {rel}:1",
            private_errors,
        )
        self.assertIn(
            f"host-specific absolute path leaked into public release file: {rel}:1",
            host_errors,
        )

        swallowed_private_line = (
            '    "review_artifacts'
            + "/source_monitor/run.md "
            + "private"
            + '/client.md",'
        )
        swallowed_private_errors = public_release_check._line_leak_errors(
            "tests/validation_source_chain.py",
            1,
            swallowed_private_line,
            structured_secret_keys=set(),
            private_workflow_reference_re=None,
        )
        self.assertIn(
            "private or generated local-state reference leaked into public release "
            "file: tests/validation_source_chain.py:1",
            swallowed_private_errors,
        )

    def test_public_release_scanner_legitimate_self_references_remain_allowed(self) -> None:
        rel = "scripts/public_release_check.py"
        detector_lines = 0
        scanner_lines = (REPO_ROOT / rel).read_text(encoding="utf-8").splitlines()

        for line_no, line in enumerate(scanner_lines, 1):
            has_reference = any(
                detector.search(line) is not None
                for detector in (
                    public_release_check.HOST_PATH_RE,
                    public_release_check.PRIVATE_STATE_RE,
                    public_release_check.SENSITIVE_LOCAL_REFERENCE_RE,
                    public_release_check.LOCAL_STATE_PATH_RE,
                )
            )
            if not has_reference:
                continue
            detector_lines += 1
            with self.subTest(line_no=line_no):
                self.assertEqual(
                    [],
                    public_release_check._line_leak_errors(
                        rel,
                        line_no,
                        line,
                        structured_secret_keys=set(),
                        private_workflow_reference_re=None,
                    ),
                )

        self.assertGreater(detector_lines, 0)

    def test_public_release_scanner_workflow_self_references_are_exact(self) -> None:
        rel = "scripts/public_release_check.py"
        workflow_reference_re = re.compile("workflow", re.IGNORECASE)
        modeled_lines = (
            "PRIVATE_WORKFLOW_SCANNER_ALLOWLIST = {",
            "PRIVATE_WORKFLOW_PATTERNS_PATH = value",
            "def load_private_workflow_policy():",
            'errors.append("private workflow reference leaked")',
        )

        for line in modeled_lines:
            with self.subTest(line=line):
                self.assertEqual(
                    [],
                    public_release_check._line_leak_errors(
                        rel,
                        1,
                        line,
                        structured_secret_keys=set(),
                        private_workflow_reference_re=workflow_reference_re,
                    ),
                )

        mixed_line = modeled_lines[0] + " + WORKFLOW"
        self.assertIn(
            f"private workflow reference leaked into public release file: {rel}:1",
            public_release_check._line_leak_errors(
                rel,
                1,
                mixed_line,
                structured_secret_keys=set(),
                private_workflow_reference_re=workflow_reference_re,
            ),
        )

    def test_public_release_private_allowance_does_not_hide_same_line_leak(self) -> None:
        allowed_reference = "private" + "/references"
        leaked_reference = "private" + "/client.md"
        allowed_line = f'REFERENCE_DIRS = (Path("{allowed_reference}"),)'
        line = (
            f"{allowed_line}  # ignore {leaked_reference}"
        )

        self.assertEqual(
            [],
            public_release_check._line_leak_errors(
                "scripts/check_reference_freshness.py",
                1,
                allowed_line,
                structured_secret_keys=set(),
                private_workflow_reference_re=None,
            ),
        )
        errors = public_release_check._line_leak_errors(
            "scripts/check_reference_freshness.py",
            1,
            line,
            structured_secret_keys=set(),
            private_workflow_reference_re=None,
        )

        self.assertEqual(
            [
                "private or generated local-state reference leaked into public "
                "release file: scripts/check_reference_freshness.py:1"
            ],
            errors,
        )

    def test_public_release_host_allowance_does_not_hide_same_line_leak(self) -> None:
        allowed_path = "/" + "t" + "mp/out.md"
        leaked_path = "/" + "Us" + "ers/alice/workspace"
        allowed_line = f'outputs = ["{allowed_path}"]'
        line = f'{allowed_line}; checkout = "{leaked_path}"'

        self.assertEqual(
            [],
            public_release_check._line_leak_errors(
                "tests/validation_automation_state.py",
                1,
                allowed_line,
                structured_secret_keys=set(),
                private_workflow_reference_re=None,
            ),
        )
        errors = public_release_check._line_leak_errors(
            "tests/validation_automation_state.py",
            1,
            line,
            structured_secret_keys=set(),
            private_workflow_reference_re=None,
        )

        self.assertIn(
            "host-specific absolute path leaked into public release file: "
            "tests/validation_automation_state.py:1",
            errors,
        )

    def test_public_release_workflow_allowance_does_not_hide_same_line_leak(self) -> None:
        workflow_name = "private-runner-alpha"
        allowed_line = (
            "!/private/operator/environments/"
            f"{workflow_name}.json"
        )
        line = (
            f"{allowed_line} # duplicate through {workflow_name}"
        )
        workflow_reference_re = re.compile(
            rf"(?<![\w-]){workflow_name}(?![\w-])"
        )
        allowed_gitignore_lines = frozenset({allowed_line})

        self.assertEqual(
            [],
            public_release_check._line_leak_errors(
                ".gitignore",
                1,
                allowed_line,
                structured_secret_keys=set(),
                private_workflow_reference_re=workflow_reference_re,
                private_workflow_allowed_gitignore_lines=allowed_gitignore_lines,
            ),
        )
        errors = public_release_check._line_leak_errors(
            ".gitignore",
            1,
            line,
            structured_secret_keys=set(),
            private_workflow_reference_re=workflow_reference_re,
            private_workflow_allowed_gitignore_lines=allowed_gitignore_lines,
        )

        self.assertIn(
            "private workflow reference leaked into public release file: .gitignore:1",
            errors,
        )

    def test_public_release_rejects_private_workflow_references(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            private = root / "private" / "authoring" / "release"
            private.mkdir(parents=True)
            (private / "leak_patterns.json").write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "literal_terms": ["private-runner-alpha"],
                        "regexes": [],
                        "allowed_gitignore_lines": [],
                    }
                ),
                encoding="utf-8",
            )
            (root / "README.md").write_text(
                "Run this through the private container named private-runner-alpha.\n",
                encoding="utf-8",
            )

            report = _authoring_fixture_report(root)

        self.assertTrue(
            any(
                "private workflow reference leaked into public release file: README.md:1" in error
                for error in string_items(report["errors"])
            )
        )

    def test_public_release_rejects_static_private_workflow_string_expressions(
        self,
    ) -> None:
        cases = (
            ("split", 'RUNTIME = "private-" + "runner-alpha"\n'),
            ("adjacent", 'RUNTIME = "private-" "runner-alpha"\n'),
        )
        for expression_kind, expression in cases:
            with (
                self.subTest(expression_kind=expression_kind),
                tempfile.TemporaryDirectory() as temp_dir,
            ):
                root = Path(temp_dir)
                private = root / "private" / "authoring" / "release"
                private.mkdir(parents=True)
                (private / "leak_patterns.json").write_text(
                    json.dumps(
                        {
                            "schema_version": 2,
                            "literal_terms": ["private-runner-alpha"],
                            "regexes": [],
                            "allowed_gitignore_lines": [],
                        }
                    ),
                    encoding="utf-8",
                )
                scripts = root / "scripts"
                scripts.mkdir()
                (scripts / "example.py").write_text(
                    expression,
                    encoding="utf-8",
                )

                report = _authoring_fixture_report(root)

            self.assertIn(
                "private workflow reference reconstructed by static Python string "
                "expression in public release file: scripts/example.py:1",
                string_items(report["errors"]),
            )

    def test_public_release_rejects_exact_private_reviewer_terms_without_provider_wide_bans(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            private = root / "private" / "authoring" / "release"
            private.mkdir(parents=True)
            (private / "leak_patterns.json").write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "literal_terms": ["Atlas Review 9", "Quartz Lane 4"],
                        "regexes": [],
                        "allowed_gitignore_lines": [],
                    }
                ),
                encoding="utf-8",
            )
            (root / "README.md").write_text(
                "Use the Atlas Review 9 lane.\n"
                "Use Quartz Lane 4 for this private lane.\n"
                "Atlas is a model family that public doctrine may discuss.\n"
                "Quartz is a provider family that public doctrine may discuss.\n",
                encoding="utf-8",
            )

            report = _authoring_fixture_report(root)

        leak_errors = [
            error
            for error in string_items(report["errors"])
            if "private workflow reference leaked into public release file: README.md" in error
        ]
        self.assertEqual(
            [
                "private workflow reference leaked into public release file: README.md:1",
                "private workflow reference leaked into public release file: README.md:2",
            ],
            leak_errors,
        )

    def test_authoring_source_private_workflow_patterns_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            private = root / "private" / "authoring" / "release"
            private.mkdir(parents=True)

            missing_report = _authoring_fixture_report(root)
            self.assertTrue(
                any(
                    "authoring-tree release checks require the local private workflow pattern file"
                    in error
                    for error in string_items(missing_report["errors"])
                ),
                missing_report["errors"],
            )

            (private / "leak_patterns.json").write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "literal_terms": [],
                        "regexes": [],
                        "allowed_gitignore_lines": [],
                    }
                ),
                encoding="utf-8",
            )
            empty_report = _authoring_fixture_report(root)

        self.assertTrue(
            any(
                "must define at least one literal_terms or regexes entry" in error
                for error in string_items(empty_report["errors"])
            )
        )

    def test_public_release_private_workflow_patterns_reject_symlinked_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            outside = root / "outside"
            outside_release = outside / "release"
            outside_release.mkdir(parents=True)
            (outside_release / "leak_patterns.json").write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "literal_terms": ["outside-controlled-term"],
                        "regexes": [],
                        "allowed_gitignore_lines": [],
                    }
                ),
                encoding="utf-8",
            )
            private = root / "private"
            private.mkdir()
            (private / "authoring").symlink_to(outside, target_is_directory=True)

            errors: list[str] = []
            private_policy = public_release_check.load_private_workflow_policy(
                root,
                errors,
            )

        self.assertIsNone(private_policy)
        self.assertTrue(
            any("must not use symlink path components" in error for error in errors),
            errors,
        )

    def test_public_release_private_workflow_patterns_are_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            private = root / "private" / "authoring" / "release"
            private.mkdir(parents=True)
            (private / "leak_patterns.json").write_bytes(
                b" " * (safe_paths.DEFAULT_JSON_INPUT_MAX_BYTES + 1)
            )

            errors: list[str] = []
            private_policy = public_release_check.load_private_workflow_policy(
                root,
                errors,
            )

        self.assertIsNone(private_policy)
        self.assertTrue(any("exceeds the" in error for error in errors), errors)

    def test_public_release_private_workflow_pattern_schema_rejects_missing_and_unknown_keys(self) -> None:
        cases = {
            "missing": {
                "schema_version": 2,
                "regexes": ["private-runtime"],
                "allowed_gitignore_lines": [],
            },
            "typo": {
                "schema_version": 2,
                "literal_term": ["misspelled-key"],
                "regexes": ["private-runtime"],
                "allowed_gitignore_lines": [],
            },
            "boolean_version": {
                "schema_version": True,
                "literal_terms": ["private-runtime"],
                "regexes": [],
                "allowed_gitignore_lines": [],
            },
        }
        reports: dict[str, list[str]] = {}
        for case_id, payload in cases.items():
            with self.subTest(case_id=case_id), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                policy = root / "private" / "authoring" / "release" / "leak_patterns.json"
                policy.parent.mkdir(parents=True)
                policy.write_text(json.dumps(payload), encoding="utf-8")
                errors: list[str] = []
                self.assertIsNone(
                    public_release_check.load_private_workflow_policy(root, errors)
                )
                reports[case_id] = errors

        self.assertTrue(
            any("missing keys: literal_terms" in error for error in reports["missing"]),
            reports["missing"],
        )
        self.assertTrue(
            any("missing keys: literal_terms" in error for error in reports["typo"]),
            reports["typo"],
        )
        self.assertTrue(
            any("unknown keys: literal_term" in error for error in reports["typo"]),
            reports["typo"],
        )
        self.assertTrue(
            any("schema_version must be 2" in error for error in reports["boolean_version"]),
            reports["boolean_version"],
        )

    def test_public_release_gitignore_workflow_allowlist_is_exact(self) -> None:
        workflow_name = "private-runner-alpha"
        exact = f"!/private/operator/environments/{workflow_name}.json"
        unrelated = f"# Run the {workflow_name} workflow"
        reference_re = re.compile(rf"(?<![\w-]){workflow_name}(?![\w-])")
        allowed_gitignore_lines = frozenset({exact})

        self.assertTrue(
            public_release_check.allowed_private_workflow_reference(
                ".gitignore",
                exact,
                reference_re,
                allowed_gitignore_lines,
            )
        )
        self.assertFalse(
            public_release_check.allowed_private_workflow_reference(
                ".gitignore",
                unrelated,
                reference_re,
                allowed_gitignore_lines,
            )
        )

    def test_public_gitignore_scanner_rejects_private_reinclude_rules(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".gitignore").write_text("private" + "/\n!" + "private" + "/*.md\n", encoding="utf-8")

            errors = public_release_check.public_gitignore_reinclude_errors(root)

        self.assertTrue(
            any(
                "public .gitignore re-includes private/local authoring path" in error
                for error in errors
            )
        )

    def test_public_export_role_requires_generated_public_export_gitignore(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_required_public_files(root)
            (root / ".gitignore").write_text("# manually copied ignore file\n", encoding="utf-8")

            report = public_release_check.check_public_release(
                root,
                tree_role=public_release_check.ReleaseTreeRole.PUBLIC_EXPORT,
            )

        self.assertTrue(
            any("strict public export .gitignore does not match generated public-export marker" in error for error in string_items(report["errors"])),
            report["errors"],
        )
        self.assertIn(
            "public export is missing ownership marker: .mpa-public-export.json",
            string_items(report["errors"]),
        )

    def test_public_release_rejects_platform_metadata_sidecars_before_text_decode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_required_public_files(root)
            (root / ".gitignore").write_text(public_surface.PUBLIC_EXPORT_GITIGNORE_TEXT, encoding="utf-8")
            (root / "._README.md").write_bytes(b"\x00\x05\x16\x07binary")
            macosx = root / "__MACOSX"
            macosx.mkdir()
            (macosx / "._README.md").write_bytes(b"\x00\x05")

            report = _public_export_fixture_report(root)

        errors = string_items(report["errors"])
        self.assertTrue(
            any("platform metadata sidecar path is not allowed in public release" in error for error in errors),
            errors,
        )

    def test_public_release_requires_root_entrypoint_guards(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "AGENTS.md").write_text("# AGENTS.md\n", encoding="utf-8")
            (root / "CLAUDE.md").write_text("# CLAUDE.md\n\nDo more than import\n", encoding="utf-8")

            report = _authoring_fixture_report(root)

        errors = string_items(report["errors"])
        self.assertTrue(any("root AGENTS.md missing framework-maintenance guard" in error for error in errors))
        self.assertTrue(any("root CLAUDE.md must keep @AGENTS.md" in error for error in errors))

    def test_public_release_allows_only_exact_authoring_loader_lines(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            agents = root / "AGENTS.md"
            original = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
            agents.write_text(original, encoding="utf-8")
            allowed = _authoring_fixture_report(root)
            agents.write_text(
                original + "\nRead `private" + "/authoring/TODO.md` as another startup authority.\n",
                encoding="utf-8",
            )
            rejected = _authoring_fixture_report(root)

        self.assertFalse(
            any(
                "private or generated local-state reference leaked into public release file: AGENTS.md"
                in error
                for error in string_items(allowed["errors"])
            )
        )
        self.assertTrue(
            any(
                "private or generated local-state reference leaked into public release file: AGENTS.md"
                in error
                for error in string_items(rejected["errors"])
            )
        )

    def test_public_export_excludes_private_source_maintenance_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "repo"
            output = Path(temp_dir) / "public"
            refs = root / "private" / "references"
            refs.mkdir(parents=True)
            write_required_public_files(root)
            (refs / "sources.md").write_text("# Private Sources\n", encoding="utf-8")
            scripts = root / "scripts"
            (scripts / "__pycache__").mkdir()
            (scripts / "__pycache__" / "export.cpython-313.pyc").write_bytes(b"pyc")
            (root / "README.untracked.md").write_text("# Untracked\n", encoding="utf-8")
            (root / ".DS_Store").write_bytes(b"store")
            executable_rel = "scripts/recommend_stack.py"
            executable_source = root / executable_rel
            executable_source.chmod(0o755)
            source_mode = stat.S_IMODE(executable_source.stat().st_mode)
            run_bounded(["git", "init", "-q"], cwd=root, check=True)
            run_bounded(["git", "add", *public_surface.PUBLIC_REQUIRED_FILES], cwd=root, check=True)

            result = public_export.export_public_tree(root, output, force=False)

            self.assertIn("GETTING_STARTED.md", result.copied_files)
            self.assertIsNone(result.retained_previous_export)
            self.assertFalse((output / "private" / "references" / "sources.md").exists())
            self.assertFalse((output / ".DS_Store").exists())
            self.assertFalse((output / "README.untracked.md").exists())
            self.assertFalse((output / "scripts" / "__pycache__" / "export.cpython-313.pyc").exists())
            self.assertEqual(
                source_mode,
                stat.S_IMODE((output / executable_rel).stat().st_mode),
            )
            exported_gitignore = (output / ".gitignore").read_text(encoding="utf-8")
            self.assertIn("/.mpa-public-export.json", exported_gitignore)
            self.assertIn("private/", exported_gitignore)
            self.assertNotIn("!private/", exported_gitignore)
            self.assertNotIn("!review_artifacts/", exported_gitignore)
            required_local_security_ignores = {
                "/.mpa-bootstrap.lock",
                "/.mpa-bootstrap-recovery.json",
                "/.mpa-bootstrap-recovery.tmp",
                "/.mcp.json",
                "/.cursor/",
                "/.continue/",
                "/.aws/",
                "/.azure/",
                "/.gcloud/",
                "/.kube/",
            }
            authoring_gitignore_lines = set(
                (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
            )
            exported_gitignore_lines = set(exported_gitignore.splitlines())
            self.assertLessEqual(required_local_security_ignores, authoring_gitignore_lines)
            self.assertLessEqual(required_local_security_ignores, exported_gitignore_lines)
            required_generated_residue_ignores = {
                ".DS_Store",
                "Thumbs.db",
                "__pycache__/",
                "*.pyc",
                "*.pyo",
                "*.log",
                "*.tmp",
                ".pytest_cache/",
                ".ruff_cache/",
                ".mypy_cache/",
                ".venv/",
                ".coverage",
                ".coverage.*",
                "htmlcov/",
                "node_modules/",
                ".npm/",
                ".pnpm-store/",
                ".yarn/",
                "dist/",
                "build/",
            }
            self.assertLessEqual(
                required_generated_residue_ignores,
                exported_gitignore_lines,
            )
            run_bounded(["git", "init", "-q"], cwd=output, check=True)
            residue_paths = (
                ".DS_Store",
                "Thumbs.db",
                "scripts/__pycache__/tool.pyc",
                "run.log",
                "draft.tmp",
                ".pytest_cache/state",
                ".ruff_cache/state",
                ".mypy_cache/state",
                ".venv/bin/python",
                ".coverage",
                "htmlcov/index.html",
                "node_modules/pkg/index.js",
                ".npm/cache",
                ".pnpm-store/cache",
                ".yarn/cache",
                "dist/bundle.js",
                "build/artifact",
            )
            for residue_path in residue_paths:
                with self.subTest(residue_path=residue_path):
                    ignored = run_bounded(
                        [
                            "git",
                            "check-ignore",
                            "--no-index",
                            "--quiet",
                            "--",
                            residue_path,
                        ],
                        cwd=output,
                        check=False,
                    )
                    self.assertEqual(0, ignored.returncode)
            self.assertTrue(
                (
                    output
                    / public_release_check.PUBLIC_EXPORT_OWNERSHIP_MARKER
                ).is_file()
            )

    def test_public_export_replaces_only_its_intact_prior_export(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "repo"
            output = Path(temp_dir) / "public"
            prepare_export_source(root)

            first = public_export.export_public_tree(root, output, force=False)
            original_readme = (output / "README.md").read_text(encoding="utf-8")
            with mock.patch.object(
                public_export,
                "_write_planned_file",
                side_effect=OSError("copy failed"),
            ):
                with self.assertRaises(public_export.PublicExportFailure) as failure:
                    public_export.export_public_tree(root, output, force=True)
            self.assertTrue(failure.exception.retained_paths[0].is_dir())
            self.assertIn("copy failed", str(failure.exception))
            self.assertEqual(original_readme, (output / "README.md").read_text(encoding="utf-8"))
            self.assertEqual([], public_release_check.public_export_ownership_marker_errors(output))

            (root / "README.md").write_text("See " + "private" + "/source.md\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                public_export.export_public_tree(root, output, force=True)
            self.assertEqual(original_readme, (output / "README.md").read_text(encoding="utf-8"))
            self.assertEqual([], public_release_check.public_export_ownership_marker_errors(output))

            (root / "README.md").write_text("# Updated source sentinel\n", encoding="utf-8")
            second = public_export.export_public_tree(root, output, force=True)

            self.assertEqual(first.copied_files, second.copied_files)
            retained = second.retained_previous_export
            if retained is None:
                self.fail("replacement did not retain the previous export")
            self.assertTrue(retained.is_dir())
            self.assertEqual(original_readme, (retained / "README.md").read_text(encoding="utf-8"))
            self.assertEqual("# Updated source sentinel\n", (output / "README.md").read_text(encoding="utf-8"))
            self.assertEqual([], public_release_check.public_export_ownership_marker_errors(output))

    def test_failed_promotion_restores_previous_export_without_empty_backup_wrapper(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "repo"
            output = Path(temp_dir) / "public"
            prepare_export_source(root)
            public_export.export_public_tree(root, output, force=False)
            original_readme = (output / "README.md").read_text(encoding="utf-8")
            (root / "README.md").write_text("# Replacement\n", encoding="utf-8")
            original_rename = os.rename

            def fail_candidate_promotion(
                source: str,
                destination: str,
                *,
                src_dir_fd: int | None = None,
                dst_dir_fd: int | None = None,
            ) -> None:
                if ".public-export-" in source and destination == output.name:
                    raise OSError("induced candidate-promotion failure")
                original_rename(
                    source,
                    destination,
                    src_dir_fd=src_dir_fd,
                    dst_dir_fd=dst_dir_fd,
                )

            with (
                mock.patch.object(
                    public_export.os,
                    "rename",
                    side_effect=fail_candidate_promotion,
                ),
                self.assertRaises(public_export.PublicExportFailure) as failure,
            ):
                public_export.export_public_tree(root, output, force=True)

            self.assertEqual(
                original_readme,
                (output / "README.md").read_text(encoding="utf-8"),
            )
            wrappers = list(
                output.parent.glob(f".{output.name}.previous-export-*")
            )
            self.assertEqual(1, len(wrappers))
            self.assertEqual([], list(wrappers[0].iterdir()))
            self.assertTrue(failure.exception.retained_paths[0].is_dir())
            self.assertIn(
                "induced candidate-promotion failure",
                str(failure.exception),
            )

    def test_failed_promotion_restores_exact_empty_preimage(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "repo"
            output = Path(temp_dir) / "public"
            prepare_export_source(root)
            output.mkdir(mode=0o711)
            before = output.stat(follow_symlinks=False)
            original_rename = os.rename

            def fail_candidate_promotion(
                source: str,
                destination: str,
                *,
                src_dir_fd: int | None = None,
                dst_dir_fd: int | None = None,
            ) -> None:
                if ".public-export-" in source and destination == output.name:
                    raise OSError("injected empty-preimage promotion failure")
                original_rename(
                    source,
                    destination,
                    src_dir_fd=src_dir_fd,
                    dst_dir_fd=dst_dir_fd,
                )

            with (
                mock.patch.object(
                    public_export.os,
                    "rename",
                    side_effect=fail_candidate_promotion,
                ),
                self.assertRaises(public_export.PublicExportFailure) as failure,
            ):
                public_export.export_public_tree(root, output, force=False)

            after = output.stat(follow_symlinks=False)
            self.assertEqual((before.st_dev, before.st_ino), (after.st_dev, after.st_ino))
            self.assertEqual(stat.S_IMODE(before.st_mode), stat.S_IMODE(after.st_mode))
            self.assertEqual([], list(output.iterdir()))
            wrappers = list(
                output.parent.glob(f".{output.name}.previous-export-*")
            )
            self.assertEqual(1, len(wrappers))
            self.assertEqual([], list(wrappers[0].iterdir()))
            self.assertTrue(failure.exception.retained_paths[0].is_dir())

    def test_successful_empty_preimage_replacement_retains_exact_preimage(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "repo"
            output = Path(temp_dir) / "public"
            prepare_export_source(root)
            output.mkdir(mode=0o711)
            before = output.stat(follow_symlinks=False)

            result = public_export.export_public_tree(root, output, force=False)

            retained = result.retained_previous_export
            if retained is None:
                self.fail("empty destination preimage was not retained")
            after = retained.stat(follow_symlinks=False)
            self.assertEqual(
                (before.st_dev, before.st_ino),
                (after.st_dev, after.st_ino),
            )
            self.assertEqual(stat.S_IMODE(before.st_mode), stat.S_IMODE(after.st_mode))
            self.assertEqual([], list(retained.iterdir()))
            self.assertEqual([], public_release_check.public_export_ownership_marker_errors(output))

    def test_injected_empty_preimage_content_is_retained_not_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "repo"
            output = Path(temp_dir) / "public"
            prepare_export_source(root)
            output.mkdir()
            original_check = public_export._checked_bound_export
            checks = 0

            def inject_after_promoted_check(
                descriptor: int,
                records: Mapping[str, tuple[str, int]],
            ) -> public_release_check.PublicExportTreeSnapshot:
                nonlocal checks
                snapshot = original_check(descriptor, records)
                checks += 1
                if checks == 3:
                    trees = list(
                        output.parent.glob(
                            f".{output.name}.previous-export-*/tree"
                        )
                    )
                    self.assertEqual(1, len(trees))
                    (trees[0] / "injected.txt").write_text(
                        "preserve me\n",
                        encoding="utf-8",
                    )
                return snapshot

            with (
                mock.patch.object(
                    public_export,
                    "_checked_bound_export",
                    side_effect=inject_after_promoted_check,
                ),
                self.assertRaises(public_export.PublicExportFailure) as failure,
            ):
                public_export.export_public_tree(root, output, force=False)

            retained_tree = next(
                path
                for path in failure.exception.retained_paths
                if path.name == "tree"
            )
            self.assertEqual(
                "preserve me\n",
                (retained_tree / "injected.txt").read_text(encoding="utf-8"),
            )
            self.assertIn(output, failure.exception.retained_paths)

    def test_export_allocation_fsync_failures_report_bound_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "repo"
            output = Path(temp_dir) / "public"
            prepare_export_source(root)
            original_fsync = os.fsync
            failed = False

            def fail_first_export_parent_fsync(descriptor: int) -> None:
                nonlocal failed
                if not failed:
                    failed = True
                    raise OSError("injected staging allocation fsync failure")
                original_fsync(descriptor)

            with (
                mock.patch.object(
                    public_export.os,
                    "fsync",
                    side_effect=fail_first_export_parent_fsync,
                ),
                self.assertRaises(public_export.PublicExportFailure) as failure,
            ):
                public_export.export_public_tree(root, output, force=False)

            self.assertTrue(failed)
            self.assertEqual(1, len(failure.exception.retained_paths))
            self.assertTrue(failure.exception.retained_paths[0].is_dir())
            self.assertIn("staging allocation fsync failure", str(failure.exception))

    def test_backup_allocation_fsync_failure_reports_wrapper_and_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "repo"
            output = Path(temp_dir) / "public"
            prepare_export_source(root)
            public_export.export_public_tree(root, output, force=False)
            (root / "README.md").write_text("# Replacement\n", encoding="utf-8")
            parent_metadata = output.parent.stat(follow_symlinks=False)
            parent_identity = (parent_metadata.st_dev, parent_metadata.st_ino)
            original_fsync = os.fsync
            failed = False

            def fail_backup_parent_fsync(descriptor: int) -> None:
                nonlocal failed
                metadata = os.fstat(descriptor)
                backups = list(
                    output.parent.glob(f".{output.name}.previous-export-*")
                )
                if (
                    not failed
                    and backups
                    and (metadata.st_dev, metadata.st_ino) == parent_identity
                ):
                    failed = True
                    raise OSError("injected backup allocation fsync failure")
                original_fsync(descriptor)

            with (
                mock.patch.object(
                    public_export.os,
                    "fsync",
                    side_effect=fail_backup_parent_fsync,
                ),
                self.assertRaises(public_export.PublicExportFailure) as failure,
            ):
                public_export.export_public_tree(root, output, force=True)

            self.assertTrue(failed)
            self.assertEqual(2, len(failure.exception.retained_paths))
            self.assertTrue(any("public-export" in path.name for path in failure.exception.retained_paths))
            self.assertTrue(any("previous-export" in path.name for path in failure.exception.retained_paths))
            self.assertTrue(output.is_dir())

    def test_export_interruptions_keep_original_type_and_add_state_receipt(self) -> None:
        for interruption in (KeyboardInterrupt("stop"), SystemExit(7)):
            with (
                self.subTest(interruption=type(interruption).__name__),
                tempfile.TemporaryDirectory() as temp_dir,
            ):
                root = Path(temp_dir) / "repo"
                output = Path(temp_dir) / "public"
                prepare_export_source(root)

                with (
                    mock.patch.object(
                        public_export,
                        "_checked_bound_export",
                        side_effect=interruption,
                    ),
                    self.assertRaises(type(interruption)) as raised,
                ):
                    public_export.export_public_tree(root, output, force=False)

                if isinstance(interruption, SystemExit):
                    self.assertEqual(7, getattr(raised.exception, "code", None))
                notes = getattr(raised.exception, "__notes__", [])
                self.assertTrue(
                    any("verified retained paths" in note for note in notes),
                    notes,
                )
                retained = list(output.parent.glob(f".{output.name}.public-export-*"))
                self.assertEqual(1, len(retained))

    def test_export_cleanup_fault_cannot_mask_primary_failure_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "repo"
            output = Path(temp_dir) / "public"
            prepare_export_source(root)
            with (
                _inject_export_cleanup_fault(
                    when_primary=True,
                    message="injected terminal cleanup failure",
                ) as (injected, close_calls),
                mock.patch.object(
                    public_export,
                    "_checked_bound_export",
                    side_effect=OSError("primary export validation failure"),
                ),
                self.assertRaises(public_export.PublicExportFailure) as raised,
            ):
                public_export.export_public_tree(root, output, force=False)

            self.assertEqual([True], injected)
            self.assertGreaterEqual(len(close_calls), 2)
            self.assertIn("primary export validation failure", str(raised.exception))
            self.assertIn(
                "injected terminal cleanup failure",
                "\n".join(getattr(raised.exception, "__notes__", ())),
            )

    def test_export_nested_directory_is_owned_before_metadata_setup(self) -> None:
        for interruption in (
            OSError("injected nested directory metadata failure"),
            KeyboardInterrupt("injected nested directory interruption"),
        ):
            with (
                self.subTest(interruption=type(interruption).__name__),
                tempfile.TemporaryDirectory() as temp_dir,
            ):
                root = Path(temp_dir)
                root_descriptor = os.open(root, public_export._directory_open_flags())
                opened_child: list[int] = []
                original_open = os.open
                source = public_export.PublicSourceFile(
                    path=root / "source.txt",
                    relative_path="nested/file.txt",
                    content=b"content\n",
                    source_sha256="0" * 64,
                    sha256=hashlib.sha256(b"content\n").hexdigest(),
                    posix_mode=0o644,
                )

                def record_nested_open(
                    path: str | bytes,
                    flags: int,
                    mode: int = 0o777,
                    *,
                    dir_fd: int | None = None,
                ) -> int:
                    descriptor = original_open(path, flags, mode, dir_fd=dir_fd)
                    if os.fsdecode(path) == "nested":
                        opened_child.append(descriptor)
                    return descriptor

                try:
                    with (
                        mock.patch.object(
                            public_export.os,
                            "open",
                            side_effect=record_nested_open,
                        ),
                        mock.patch.object(
                            public_export.os,
                            "fchmod",
                            side_effect=interruption,
                        ),
                        self.assertRaises(type(interruption)) as raised,
                    ):
                        public_export._write_export_files(
                            root_descriptor,
                            [source],
                            b"{}\n",
                        )
                finally:
                    os.close(root_descriptor)

                self.assertIs(interruption, raised.exception)
                self.assertEqual(1, len(opened_child))
                with self.assertRaises(OSError):
                    os.fstat(opened_child[0])

    def test_successful_export_cleanup_fault_returns_typed_retention_receipt(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "repo"
            output = Path(temp_dir) / "public"
            prepare_export_source(root)
            with (
                _inject_export_cleanup_fault(
                    when_primary=False,
                    message="injected successful cleanup failure",
                ) as (injected, close_calls),
                self.assertRaises(public_export.PublicExportFailure) as raised,
            ):
                public_export.export_public_tree(root, output, force=False)

            self.assertEqual([True], injected)
            self.assertGreaterEqual(len(close_calls), 2)
            self.assertEqual((output,), raised.exception.retained_paths)
            self.assertEqual((), raised.exception.unverified_locations)
            self.assertTrue(output.is_dir())
            self.assertIn("injected successful cleanup failure", str(raised.exception))

    def test_export_allocation_interruptions_report_attempted_names(self) -> None:
        for phase in ("public-export", "previous-export"):
            for interruption in (KeyboardInterrupt("stop"), SystemExit(7)):
                with (
                    self.subTest(
                        phase=phase,
                        interruption=type(interruption).__name__,
                    ),
                    tempfile.TemporaryDirectory() as temp_dir,
                ):
                    root = Path(temp_dir) / "repo"
                    output = Path(temp_dir) / "public"
                    prepare_export_source(root)
                    if phase == "previous-export":
                        public_export.export_public_tree(root, output, force=False)
                        (root / "README.md").write_text(
                            "# Replacement\n",
                            encoding="utf-8",
                        )
                    original_mkdir = os.mkdir
                    interrupted_path: list[Path] = []

                    def create_then_interrupt(
                        path: str | bytes,
                        mode: int = 0o777,
                        *,
                        dir_fd: int | None = None,
                    ) -> None:
                        original_mkdir(path, mode, dir_fd=dir_fd)
                        rendered = os.fsdecode(path)
                        if f".{output.name}.{phase}-" in rendered:
                            interrupted_path.append(output.parent / rendered)
                            raise interruption

                    with (
                        mock.patch.object(
                            public_export.os,
                            "mkdir",
                            side_effect=create_then_interrupt,
                        ),
                        self.assertRaises(type(interruption)) as raised,
                    ):
                        public_export.export_public_tree(
                            root,
                            output,
                            force=phase == "previous-export",
                        )

                    self.assertIs(interruption, raised.exception)
                    if isinstance(interruption, SystemExit):
                        self.assertEqual(7, getattr(raised.exception, "code", None))
                    self.assertEqual(1, len(interrupted_path))
                    self.assertTrue(interrupted_path[0].is_dir())
                    notes = getattr(raised.exception, "__notes__", [])
                    self.assertTrue(
                        any(str(interrupted_path[0]) in note for note in notes),
                        notes,
                    )

    def test_export_failure_receipt_includes_created_output_parents(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "repo"
            output = base / "exports" / "nested" / "public"
            prepare_export_source(root)

            with (
                mock.patch.object(
                    public_export,
                    "public_source_files",
                    side_effect=OSError("induced source planning failure"),
                ),
                self.assertRaises(public_export.PublicExportFailure) as failure,
            ):
                public_export.export_public_tree(root, output, force=False)

            self.assertIn(base / "exports", failure.exception.retained_paths)
            self.assertIn(base / "exports" / "nested", failure.exception.retained_paths)
            self.assertIn("induced source planning failure", str(failure.exception))

    def test_recovery_probe_failure_cannot_mask_promotion_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "repo"
            output = Path(temp_dir) / "public"
            prepare_export_source(root)
            public_export.export_public_tree(root, output, force=False)
            (root / "README.md").write_text("# Replacement\n", encoding="utf-8")
            original_rename = os.rename
            original_exists = public_export._path_exists_at
            promotion_failed = False

            def fail_promotion(
                source: str,
                destination: str,
                *,
                src_dir_fd: int | None = None,
                dst_dir_fd: int | None = None,
            ) -> None:
                nonlocal promotion_failed
                if ".public-export-" in source and destination == output.name:
                    promotion_failed = True
                    raise OSError("primary candidate promotion failure")
                original_rename(
                    source,
                    destination,
                    src_dir_fd=src_dir_fd,
                    dst_dir_fd=dst_dir_fd,
                )

            def fail_recovery_probe(parent_descriptor: int, name: str) -> bool:
                if promotion_failed:
                    raise OSError("secondary recovery existence probe failure")
                return original_exists(parent_descriptor, name)

            with (
                mock.patch.object(
                    public_export.os,
                    "rename",
                    side_effect=fail_promotion,
                ),
                mock.patch.object(
                    public_export,
                    "_path_exists_at",
                    side_effect=fail_recovery_probe,
                ),
                self.assertRaises(public_export.PublicExportFailure) as failure,
            ):
                public_export.export_public_tree(root, output, force=True)

            cause = failure.exception.__cause__
            self.assertIsInstance(cause, OSError)
            self.assertIn("primary candidate promotion failure", str(cause))
            notes = getattr(cause, "__notes__", [])
            self.assertTrue(
                any("secondary recovery existence probe failure" in note for note in notes),
                notes,
            )
            self.assertFalse(output.exists())
            self.assertTrue(
                any("public-export" in path.name for path in failure.exception.retained_paths)
            )
            self.assertTrue(
                any("previous-export" in path.name for path in failure.exception.retained_paths)
            )

    def test_mutated_preimages_are_never_restored_during_failure_recovery(self) -> None:
        for preimage_kind in ("empty", "nonempty"):
            with self.subTest(preimage_kind=preimage_kind), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir) / "repo"
                output = Path(temp_dir) / "public"
                prepare_export_source(root)
                if preimage_kind == "empty":
                    output.mkdir()
                    force = False
                else:
                    public_export.export_public_tree(root, output, force=False)
                    (root / "README.md").write_text(
                        "# Replacement\n",
                        encoding="utf-8",
                    )
                    force = True
                original_rename = os.rename
                mutated_tree: list[Path] = []

                def mutate_after_backup_move(
                    source: str,
                    destination: str,
                    *,
                    src_dir_fd: int | None = None,
                    dst_dir_fd: int | None = None,
                ) -> None:
                    original_rename(
                        source,
                        destination,
                        src_dir_fd=src_dir_fd,
                        dst_dir_fd=dst_dir_fd,
                    )
                    if source == output.name and destination == "tree":
                        trees = list(
                            output.parent.glob(
                                f".{output.name}.previous-export-*/tree"
                            )
                        )
                        self.assertEqual(1, len(trees))
                        tree = trees[0]
                        mutated_tree.append(tree)
                        if preimage_kind == "empty":
                            (tree / "injected.txt").write_text(
                                "do not restore\n",
                                encoding="utf-8",
                            )
                        else:
                            (tree / "README.md").write_text(
                                "# Mutated retained preimage\n",
                                encoding="utf-8",
                            )

                with (
                    mock.patch.object(
                        public_export.os,
                        "rename",
                        side_effect=mutate_after_backup_move,
                    ),
                    self.assertRaises(public_export.PublicExportFailure) as failure,
                ):
                    public_export.export_public_tree(root, output, force=force)

                self.assertFalse(output.exists())
                self.assertEqual(1, len(mutated_tree))
                self.assertTrue(mutated_tree[0].is_dir())
                self.assertIn(mutated_tree[0], failure.exception.retained_paths)
                if preimage_kind == "empty":
                    self.assertTrue((mutated_tree[0] / "injected.txt").is_file())
                else:
                    self.assertEqual(
                        "# Mutated retained preimage\n",
                        (mutated_tree[0] / "README.md").read_text(encoding="utf-8"),
                    )
                cause = failure.exception.__cause__
                notes = getattr(cause, "__notes__", [])
                self.assertTrue(
                    any("could not be restored" in note for note in notes),
                    notes,
                )

    def test_rollback_rename_mutation_receipts_changed_output(self) -> None:
        for preimage_kind in ("empty", "nonempty"):
            with (
                self.subTest(preimage_kind=preimage_kind),
                tempfile.TemporaryDirectory() as temp_dir,
            ):
                root = Path(temp_dir) / "repo"
                output = Path(temp_dir) / "public"
                prepare_export_source(root)
                if preimage_kind == "empty":
                    output.mkdir()
                    force = False
                else:
                    public_export.export_public_tree(root, output, force=False)
                    (root / "README.md").write_text(
                        "# Replacement\n",
                        encoding="utf-8",
                    )
                    force = True
                original_rename = os.rename
                promotion_failed = False
                rollback_mutated = False

                def mutate_inside_rollback_rename(
                    source: str,
                    destination: str,
                    *,
                    src_dir_fd: int | None = None,
                    dst_dir_fd: int | None = None,
                ) -> None:
                    nonlocal promotion_failed, rollback_mutated
                    if ".public-export-" in source and destination == output.name:
                        promotion_failed = True
                        raise OSError("injected candidate promotion failure")
                    if promotion_failed and source == "tree" and destination == output.name:
                        wrapper = next(
                            output.parent.glob(f".{output.name}.previous-export-*")
                        )
                        tree = wrapper / "tree"
                        if preimage_kind == "empty":
                            (tree / "injected.txt").write_text(
                                "changed during rollback\n",
                                encoding="utf-8",
                            )
                        else:
                            (tree / "README.md").write_text(
                                "# Changed during rollback\n",
                                encoding="utf-8",
                            )
                        rollback_mutated = True
                    original_rename(
                        source,
                        destination,
                        src_dir_fd=src_dir_fd,
                        dst_dir_fd=dst_dir_fd,
                    )

                with (
                    mock.patch.object(
                        public_export.os,
                        "rename",
                        side_effect=mutate_inside_rollback_rename,
                    ),
                    self.assertRaises(public_export.PublicExportFailure) as failure,
                ):
                    public_export.export_public_tree(root, output, force=force)

                self.assertTrue(rollback_mutated)
                self.assertTrue(output.is_dir())
                self.assertIn(output, failure.exception.retained_paths)
                self.assertNotIn(output, failure.exception.unverified_locations)
                if preimage_kind == "empty":
                    self.assertEqual(
                        "changed during rollback\n",
                        (output / "injected.txt").read_text(encoding="utf-8"),
                    )
                else:
                    self.assertEqual(
                        "# Changed during rollback\n",
                        (output / "README.md").read_text(encoding="utf-8"),
                    )
                cause = failure.exception.__cause__
                self.assertIn(
                    "could not be restored intact",
                    "\n".join(getattr(cause, "__notes__", ())),
                )

    def test_terminal_export_checks_reject_backup_edge_substitution(self) -> None:
        for edge in ("wrapper", "tree"):
            with self.subTest(edge=edge), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir) / "repo"
                output = Path(temp_dir) / "public"
                prepare_export_source(root)
                public_export.export_public_tree(root, output, force=False)
                prior_readme = (output / "README.md").read_text(encoding="utf-8")
                (root / "README.md").write_text(
                    "# Replacement\n",
                    encoding="utf-8",
                )
                original_assertion = public_export._assert_bound_name
                moved: list[Path] = []
                substituted = False

                def substitute_after_final_check(
                    parent_descriptor: int,
                    name: str,
                    descriptor: int,
                    *,
                    description: str,
                ) -> None:
                    nonlocal substituted
                    original_assertion(
                        parent_descriptor,
                        name,
                        descriptor,
                        description=description,
                    )
                    target_description = (
                        "final previous-export wrapper"
                        if edge == "wrapper"
                        else "final retained previous public export"
                    )
                    if description != target_description or substituted:
                        return
                    wrapper = next(
                        output.parent.glob(
                            f".{output.name}.previous-export-*"
                        )
                    )
                    if edge == "wrapper":
                        original = wrapper
                        replacement = wrapper
                        destination = wrapper.with_name(wrapper.name + "-moved")
                    else:
                        original = wrapper / "tree"
                        replacement = wrapper / "tree"
                        destination = wrapper / "tree-moved"
                    original.rename(destination)
                    replacement.mkdir()
                    moved.append(destination)
                    substituted = True

                with (
                    mock.patch.object(
                        public_export,
                        "_assert_bound_name",
                        side_effect=substitute_after_final_check,
                    ),
                    self.assertRaises(public_export.PublicExportFailure),
                ):
                    public_export.export_public_tree(root, output, force=True)

                self.assertTrue(substituted)
                self.assertEqual(1, len(moved))
                retained_tree = moved[0] / "tree" if edge == "wrapper" else moved[0]
                self.assertEqual(
                    prior_readme,
                    (retained_tree / "README.md").read_text(encoding="utf-8"),
                )
                self.assertEqual(
                    "# Replacement\n",
                    (output / "README.md").read_text(encoding="utf-8"),
                )

    def test_public_export_cli_reports_typed_output_binding_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "repo"
            output = base / "exports" / "public"
            root.mkdir()
            binding_error = safe_paths.OutputDirectoryBindingError(
                output.parent,
                "exports",
                (output.parent,),
                OSError("induced binding failure"),
            )
            stderr = io.StringIO()

            with (
                mock.patch.dict(os.environ, {}, clear=True),
                mock.patch.object(
                    public_export.safe_paths,
                    "open_output_directory",
                    side_effect=binding_error,
                ),
                mock.patch.object(sys, "stderr", stderr),
                self.assertRaises(SystemExit) as raised,
            ):
                public_export.main(
                    ["--root", str(root), "--output", str(output)]
                )

        self.assertEqual(2, raised.exception.code)
        self.assertIn("induced binding failure", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_failure_receipt_probe_cannot_mask_primary_export_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "repo"
            output = Path(temp_dir) / "public"
            prepare_export_source(root)

            with (
                mock.patch.object(
                    public_export,
                    "_checked_bound_export",
                    side_effect=OSError("primary export validation failure"),
                ),
                mock.patch.object(
                    public_export,
                    "_transaction_failure_locations",
                    side_effect=OSError("secondary receipt probe failure"),
                ),
                self.assertRaisesRegex(
                    OSError,
                    "primary export validation failure",
                ) as raised,
            ):
                public_export.export_public_tree(root, output, force=False)

            notes = getattr(raised.exception, "__notes__", [])
            self.assertTrue(
                any("secondary receipt probe failure" in note for note in notes),
                notes,
            )

    def test_final_output_binding_rejects_post_snapshot_name_substitution(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "repo"
            output = Path(temp_dir) / "public"
            moved = Path(temp_dir) / "moved-public"
            prepare_export_source(root)
            original_check = public_export._checked_bound_export
            checks = 0

            def substitute_after_final_snapshot(
                descriptor: int,
                records: Mapping[str, tuple[str, int]],
            ) -> public_release_check.PublicExportTreeSnapshot:
                nonlocal checks
                snapshot = original_check(descriptor, records)
                checks += 1
                if checks == 4:
                    output.rename(moved)
                    output.mkdir()
                return snapshot

            with (
                mock.patch.object(
                    public_export,
                    "_checked_bound_export",
                    side_effect=substitute_after_final_snapshot,
                ),
                self.assertRaises(public_export.PublicExportFailure) as failure,
            ):
                public_export.export_public_tree(root, output, force=False)

            self.assertEqual((), failure.exception.retained_paths)
            self.assertEqual((output,), failure.exception.unverified_locations)
            self.assertTrue(moved.is_dir())

    def test_public_export_rejects_source_mutation_after_snapshot(self) -> None:
        cases = (
            (
                "bytes",
                "changed between release validation and export read",
            ),
            (
                "mode",
                "content or POSIX rwx mode changed between",
            ),
        )
        for mutation_kind, expected_diagnostic in cases:
            with (
                self.subTest(mutation_kind=mutation_kind),
                tempfile.TemporaryDirectory() as temp_dir,
            ):
                root = Path(temp_dir) / "repo"
                output = Path(temp_dir) / "public"
                prepare_export_source(root)
                original_read = public_release_check.stable_file_bytes

                def mutate_then_read(
                    source: Path,
                    *,
                    expected_snapshot: tuple[str, int],
                ) -> bytes:
                    if source.name == "README.md":
                        if mutation_kind == "bytes":
                            source.write_text(
                                "# Substituted after validation\n",
                                encoding="utf-8",
                            )
                        else:
                            source.chmod(
                                stat.S_IMODE(source.stat().st_mode)
                                ^ stat.S_IXUSR
                            )
                    return original_read(
                        source,
                        expected_snapshot=expected_snapshot,
                    )

                with (
                    mock.patch.object(
                        public_release_check,
                        "stable_file_bytes",
                        side_effect=mutate_then_read,
                    ),
                    self.assertRaises(ValueError) as failure,
                ):
                    public_export.export_public_tree(root, output, force=False)

                self.assertFalse(output.exists())
                self.assertIn(expected_diagnostic, str(failure.exception))

    def test_public_export_rejects_index_mutation_before_selected_source_read(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "repo"
            prepare_export_source(root)
            original_read = public_release_check.stable_file_bytes
            mutated = False

            def mutate_index_then_read(
                source: Path,
                *,
                expected_snapshot: tuple[str, int],
            ) -> bytes:
                nonlocal mutated
                if not mutated:
                    run_bounded(
                        ["git", "rm", "--cached", "--quiet", "--", "README.md"],
                        cwd=root,
                        check=True,
                    )
                    mutated = True
                return original_read(
                    source,
                    expected_snapshot=expected_snapshot,
                )

            with (
                mock.patch.object(
                    public_release_check,
                    "stable_file_bytes",
                    side_effect=mutate_index_then_read,
                ),
                self.assertRaises((RuntimeError, ValueError)) as failure,
            ):
                public_export.public_source_files(root)

            self.assertTrue(mutated)
            self.assertIn("Git ", str(failure.exception))

    def test_public_export_rejects_index_mutation_after_candidate_write(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "repo"
            output = Path(temp_dir) / "public"
            prepare_export_source(root)
            public_export.export_public_tree(root, output, force=False)
            original_readme = (output / "README.md").read_bytes()
            (root / "README.md").write_text(
                "# New valid source generation\n",
                encoding="utf-8",
            )
            run_bounded(["git", "add", "README.md"], cwd=root, check=True)
            original_write = public_export._write_export_files
            mutated = False

            def mutate_index_after_candidate_write(
                descriptor: int,
                sources: list[public_export.PublicSourceFile],
                marker_bytes: bytes,
            ) -> None:
                nonlocal mutated
                original_write(descriptor, sources, marker_bytes)
                run_bounded(
                    ["git", "rm", "--cached", "--quiet", "--", "README.md"],
                    cwd=root,
                    check=True,
                )
                mutated = True

            with (
                mock.patch.object(
                    public_export,
                    "_write_export_files",
                    side_effect=mutate_index_after_candidate_write,
                ),
                self.assertRaises(public_export.PublicExportFailure) as failure,
            ):
                public_export.export_public_tree(root, output, force=True)

            self.assertTrue(mutated)
            self.assertIn("Git ", str(failure.exception))
            self.assertEqual(original_readme, (output / "README.md").read_bytes())
            self.assertTrue(
                any(
                    path.name.startswith(".public.public-export-")
                    for path in failure.exception.retained_paths
                )
            )

    def test_public_export_terminal_index_mutation_retains_both_generations(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "repo"
            output = Path(temp_dir) / "public"
            prepare_export_source(root)
            public_export.export_public_tree(root, output, force=False)
            original_readme = (output / "README.md").read_bytes()
            replacement_readme = b"# Replacement source generation\n"
            (root / "README.md").write_bytes(replacement_readme)
            run_bounded(["git", "add", "README.md"], cwd=root, check=True)
            original_assertion = public_export._assert_bound_name
            mutated = False

            def mutate_index_at_terminal_boundary(
                parent_descriptor: int,
                name: str,
                descriptor: int,
                *,
                description: str,
            ) -> None:
                nonlocal mutated
                original_assertion(
                    parent_descriptor,
                    name,
                    descriptor,
                    description=description,
                )
                if description == "promoted public export" and not mutated:
                    run_bounded(
                        ["git", "rm", "--cached", "--quiet", "--", "README.md"],
                        cwd=root,
                        check=True,
                    )
                    mutated = True

            with (
                mock.patch.object(
                    public_export,
                    "_assert_bound_name",
                    side_effect=mutate_index_at_terminal_boundary,
                ),
                self.assertRaises(public_export.PublicExportFailure) as failure,
            ):
                public_export.export_public_tree(root, output, force=True)

            self.assertTrue(mutated)
            self.assertIn("Git ", str(failure.exception))
            self.assertEqual(replacement_readme, (output / "README.md").read_bytes())
            retained_previous = [
                path
                for path in failure.exception.retained_paths
                if path.name == "tree"
                and path.parent.name.startswith(".public.previous-export-")
            ]
            self.assertEqual(1, len(retained_previous))
            self.assertEqual(
                original_readme,
                (retained_previous[0] / "README.md").read_bytes(),
            )

    def test_public_export_normalizes_special_bits_and_does_not_copy_xattrs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "repo"
            output = Path(temp_dir) / "public"
            prepare_export_source(root)
            source = root / "README.md"
            xattr_name = "user.mpa-public-export-test"
            xattr_supported = hasattr(os, "setxattr") and hasattr(os, "listxattr")
            if xattr_supported:
                try:
                    os.setxattr(source, xattr_name, b"must-not-propagate")
                except OSError:
                    xattr_supported = False
            source.chmod(0o4644)

            public_export.export_public_tree(root, output, force=False)

            exported = output / "README.md"
            self.assertEqual(0o644, stat.S_IMODE(exported.stat().st_mode))
            self.assertFalse(exported.stat().st_mode & stat.S_ISUID)
            if xattr_supported:
                self.assertNotIn(xattr_name, os.listxattr(exported))
            marker = output / public_release_check.PUBLIC_EXPORT_OWNERSHIP_MARKER
            self.assertEqual(
                public_release_check.PUBLIC_EXPORT_MARKER_MODE,
                stat.S_IMODE(marker.stat().st_mode),
            )

    def test_descriptor_writer_rejects_same_bytes_name_substitution(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            content = b"same planned bytes\n"
            target = root / "artifact.txt"
            replacement = root / "replacement.txt"
            parent_descriptor = os.open(
                root,
                public_export._directory_open_flags(),
            )
            original_fsync = os.fsync
            swapped = False

            def swap_after_file_sync(descriptor: int) -> None:
                nonlocal swapped
                if descriptor != parent_descriptor and target.exists() and not swapped:
                    replacement.write_bytes(content)
                    replacement.chmod(0o640)
                    os.replace(replacement, target)
                    swapped = True
                original_fsync(descriptor)

            try:
                with (
                    mock.patch.object(
                        public_export.os,
                        "fsync",
                        side_effect=swap_after_file_sync,
                    ),
                    self.assertRaisesRegex(
                        ValueError,
                        "does not match its planned bytes/mode",
                    ),
                ):
                    public_export._write_planned_file(
                        parent_descriptor,
                        target.name,
                        content,
                        0o640,
                    )
            finally:
                os.close(parent_descriptor)

            self.assertTrue(swapped)
            self.assertEqual(content, target.read_bytes())

    def test_public_export_rejects_post_copy_bytes_and_mode_mutation(self) -> None:
        for mutation in ("bytes", "mode"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir) / "repo"
                output = Path(temp_dir) / "public"
                prepare_export_source(root)
                original_validation = public_export._checked_bound_export
                validation_count = 0

                def mutate_after_validation(
                    descriptor: int,
                    records: Mapping[str, tuple[str, int]],
                ) -> public_release_check.PublicExportTreeSnapshot:
                    nonlocal validation_count
                    snapshot = original_validation(descriptor, records)
                    validation_count += 1
                    if validation_count == 1:
                        candidates = list(
                            output.parent.glob(f".{output.name}.public-export-*")
                        )
                        self.assertEqual(1, len(candidates))
                        readme = candidates[0] / "README.md"
                        if mutation == "bytes":
                            readme.write_text("# Late mutation\n", encoding="utf-8")
                        else:
                            readme.chmod(0o777)
                    return snapshot

                with (
                    mock.patch.object(
                        public_export,
                        "_checked_bound_export",
                        side_effect=mutate_after_validation,
                    ),
                    self.assertRaises(public_export.PublicExportFailure) as failure,
                ):
                    public_export.export_public_tree(root, output, force=False)

                retained = failure.exception.retained_paths[0]
                self.assertTrue(retained.is_dir())
                self.assertIn("ownership validation failed", str(failure.exception))
                marker = json.loads(
                    (
                        retained
                        / public_release_check.PUBLIC_EXPORT_OWNERSHIP_MARKER
                    ).read_text(encoding="utf-8")
                )
                record = marker["files"]["README.md"]
                if mutation == "bytes":
                    self.assertNotEqual(
                        record["sha256"],
                        public_release_check.file_sha256(retained / "README.md"),
                    )
                else:
                    self.assertNotEqual(
                        record["posix_mode"],
                        public_release_check.posix_rwx_mode(
                            (retained / "README.md").stat()
                        ),
                    )

    def test_public_export_rejects_staging_root_substitution_and_reports_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "repo"
            output = Path(temp_dir) / "public"
            prepare_export_source(root)
            original_validation = public_export._checked_bound_export
            moved_paths: list[Path] = []
            validation_count = 0

            def substitute_staging(
                descriptor: int,
                records: Mapping[str, tuple[str, int]],
            ) -> public_release_check.PublicExportTreeSnapshot:
                nonlocal validation_count
                snapshot = original_validation(descriptor, records)
                validation_count += 1
                if validation_count == 1:
                    candidates = list(
                        output.parent.glob(f".{output.name}.public-export-*")
                    )
                    self.assertEqual(1, len(candidates))
                    path = candidates[0]
                    moved = path.with_name(path.name + "-moved")
                    path.rename(moved)
                    path.symlink_to(moved, target_is_directory=True)
                    moved_paths.append(moved)
                return snapshot

            with (
                mock.patch.object(
                    public_export,
                    "_checked_bound_export",
                    side_effect=substitute_staging,
                ),
                self.assertRaises(public_export.PublicExportFailure) as failure,
            ):
                public_export.export_public_tree(root, output, force=False)

            self.assertFalse(output.exists())
            self.assertEqual((), failure.exception.retained_paths)
            self.assertEqual(1, len(failure.exception.unverified_locations))
            self.assertTrue(failure.exception.unverified_locations[0].is_symlink())
            self.assertIsNotNone(failure.exception.candidate_identity)
            self.assertIn("bound candidate identity", str(failure.exception))
            self.assertEqual(1, len(moved_paths))
            self.assertTrue(moved_paths[0].is_dir())

    def test_public_export_rejects_output_parent_substitution_around_release_check(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "repo"
            output = base / "exports" / "public"
            prepare_export_source(root)
            original_check = public_export._checked_bound_export
            moved_parents: list[Path] = []
            validation_count = 0

            def substitute_parent(
                descriptor: int,
                records: Mapping[str, tuple[str, int]],
            ) -> public_release_check.PublicExportTreeSnapshot:
                nonlocal validation_count
                snapshot = original_check(descriptor, records)
                validation_count += 1
                if validation_count == 1:
                    parent = output.parent
                    moved = parent.with_name(parent.name + "-moved")
                    parent.rename(moved)
                    parent.mkdir()
                    moved_parents.append(moved)
                return snapshot

            with (
                mock.patch.object(
                    public_export,
                    "_checked_bound_export",
                    side_effect=substitute_parent,
                ),
                self.assertRaises(public_export.PublicExportFailure) as failure,
            ):
                public_export.export_public_tree(root, output, force=False)

            self.assertEqual(1, len(moved_parents))
            retained_candidates = list(
                moved_parents[0].glob(".public.public-export-*")
            )
            self.assertEqual(1, len(retained_candidates))
            self.assertTrue(retained_candidates[0].is_dir())
            self.assertEqual((), failure.exception.retained_paths)
            self.assertEqual(
                (
                    output.parent,
                    output.parent / retained_candidates[0].name,
                ),
                failure.exception.unverified_locations,
            )
            self.assertIsNotNone(failure.exception.parent_identity)
            self.assertIn("bound output-parent identity", str(failure.exception))
            self.assertIn(
                "output parent pathname component no longer identifies its bound directory",
                str(failure.exception),
            )

    def test_public_export_rejects_mutated_promoted_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "repo"
            output = Path(temp_dir) / "public"
            prepare_export_source(root)
            original_assertion = public_export._assert_bound_name
            mutated = False

            def mutate_after_promotion(
                parent_descriptor: int,
                name: str,
                descriptor: int,
                *,
                description: str,
            ) -> None:
                nonlocal mutated
                original_assertion(
                    parent_descriptor,
                    name,
                    descriptor,
                    description=description,
                )
                if description == "promoted public export" and not mutated:
                    (output / "README.md").write_text(
                        "# Mutated after promotion\n",
                        encoding="utf-8",
                    )
                    mutated = True

            with (
                mock.patch.object(
                    public_export,
                    "_assert_bound_name",
                    side_effect=mutate_after_promotion,
                ),
                self.assertRaises(public_export.PublicExportFailure) as failure,
            ):
                public_export.export_public_tree(root, output, force=False)

            self.assertTrue(mutated)
            self.assertEqual(output, failure.exception.retained_paths[0])
            self.assertIn("ownership marker digest mismatch", str(failure.exception))
            self.assertEqual(
                "# Mutated after promotion\n",
                (output / "README.md").read_text(encoding="utf-8"),
            )

    def test_public_export_success_matches_exact_expected_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "repo"
            output = Path(temp_dir) / "public"
            prepare_export_source(root)

            public_export.export_public_tree(root, output, force=False)

            marker_path = output / public_release_check.PUBLIC_EXPORT_OWNERSHIP_MARKER
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
            records = {
                relative_path: (record["sha256"], record["posix_mode"])
                for relative_path, record in marker["files"].items()
            }
            descriptor = os.open(output, public_export._directory_open_flags())
            try:
                actual = (
                    public_release_check.checked_public_export_ownership_descriptor(
                        descriptor,
                        expected_records=records,
                    )
                )
            finally:
                os.close(descriptor)
            self.assertEqual(public_release_check.PUBLIC_EXPORT_ROOT_MODE, actual.root_mode)
            self.assertTrue(
                all(
                    mode == public_release_check.PUBLIC_EXPORT_DIRECTORY_MODE
                    for _relative, mode in actual.directories
                )
            )
            self.assertEqual(len(records) + 1, len(actual.files))

    def test_closed_public_export_traversal_detects_late_root_and_nested_entries(self) -> None:
        for relative_directory in (".", "scripts"):
            with (
                self.subTest(relative_directory=relative_directory),
                tempfile.TemporaryDirectory() as temp_dir,
            ):
                root = Path(temp_dir)
                _prepare_public_export_fixture(root)
                _write_public_export_marker(root)
                target = root if relative_directory == "." else root / relative_directory
                target_identity = (target.stat().st_dev, target.stat().st_ino)
                original_names = public_release_check._fresh_directory_names
                injected = False

                def inject_after_initial_names(descriptor: int) -> tuple[str, ...]:
                    nonlocal injected
                    names = original_names(descriptor)
                    metadata = os.fstat(descriptor)
                    if not injected and (metadata.st_dev, metadata.st_ino) == target_identity:
                        (target / "late-entry.txt").write_text(
                            "late\n",
                            encoding="utf-8",
                        )
                        injected = True
                    return names

                with mock.patch.object(
                    public_release_check,
                    "_fresh_directory_names",
                    side_effect=inject_after_initial_names,
                ):
                    errors = (
                        public_release_check.public_export_ownership_marker_errors(
                            root
                        )
                    )

                self.assertTrue(injected)
                self.assertTrue(
                    any("directory entries changed" in error for error in errors),
                    errors,
                )

    def test_closed_public_export_traversal_detects_name_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "public"
            root.mkdir()
            _prepare_public_export_fixture(root)
            _write_public_export_marker(root)
            original_open = public_release_check.os.open
            moved = Path(temp_dir) / "original-readme.md"
            replaced = False

            def replace_after_open(
                path: str | bytes,
                flags: int,
                mode: int = 0o777,
                *,
                dir_fd: int | None = None,
            ) -> int:
                nonlocal replaced
                descriptor = original_open(path, flags, mode, dir_fd=dir_fd)
                if path == "README.md" and dir_fd is not None and not replaced:
                    content = (root / "README.md").read_bytes()
                    (root / "README.md").rename(moved)
                    (root / "README.md").write_bytes(content)
                    (root / "README.md").chmod(0o644)
                    replaced = True
                return descriptor

            with mock.patch.object(
                public_release_check.os,
                "open",
                side_effect=replace_after_open,
            ):
                errors = public_release_check.public_export_ownership_marker_errors(root)

            self.assertTrue(replaced)
            self.assertTrue(
                any(
                    "README.md" in error
                    and (
                        "file changed before inspection" in error
                        or "file name changed while inspected" in error
                    )
                    for error in errors
                ),
                errors,
            )

    def test_closed_public_export_traversal_detects_directory_name_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "public"
            root.mkdir()
            _prepare_public_export_fixture(root)
            _write_public_export_marker(root)
            original_open = public_release_check.os.open
            moved = Path(temp_dir) / "original-scripts"
            replaced = False

            def replace_directory_after_open(
                path: str | bytes,
                flags: int,
                mode: int = 0o777,
                *,
                dir_fd: int | None = None,
            ) -> int:
                nonlocal replaced
                descriptor = original_open(path, flags, mode, dir_fd=dir_fd)
                if path == "scripts" and dir_fd is not None and not replaced:
                    (root / "scripts").rename(moved)
                    shutil.copytree(moved, root / "scripts")
                    replaced = True
                return descriptor

            with mock.patch.object(
                public_release_check.os,
                "open",
                side_effect=replace_directory_after_open,
            ):
                errors = public_release_check.public_export_ownership_marker_errors(root)

            self.assertTrue(replaced)
            self.assertTrue(
                any(
                    "scripts" in error
                    and (
                        "directory changed before inspection" in error
                        or "directory name changed while inspected" in error
                    )
                    for error in errors
                ),
                errors,
            )

    def test_descriptor_ownership_detects_create_delete_aba_between_closed_reads(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _prepare_public_export_fixture(root)
            _write_public_export_marker(root)
            original_read = public_release_check._closed_public_export_read
            reads = 0

            def mutate_after_first_read(
                descriptor: int,
            ) -> object:
                nonlocal reads
                result = original_read(descriptor)
                reads += 1
                if reads == 1:
                    transient = root / ".transient-aba"
                    transient.write_text("temporary\n", encoding="utf-8")
                    transient.unlink()
                    root.chmod(0o711)
                    root.chmod(public_release_check.PUBLIC_EXPORT_ROOT_MODE)
                return result

            with mock.patch.object(
                public_release_check,
                "_closed_public_export_read",
                side_effect=mutate_after_first_read,
            ):
                errors = public_release_check.public_export_ownership_marker_errors(root)

            self.assertEqual(2, reads)
            self.assertIn(
                "public export ownership tree changed while it was being verified",
                errors,
            )

    def test_public_export_marker_requires_canonical_encoding(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _prepare_public_export_fixture(root)
            _write_public_export_marker(root)
            marker = root / public_release_check.PUBLIC_EXPORT_OWNERSHIP_MARKER
            payload = json.loads(marker.read_text(encoding="utf-8"))
            marker.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
            marker.chmod(public_release_check.PUBLIC_EXPORT_MARKER_MODE)

            errors = public_release_check.public_export_ownership_marker_errors(root)

            self.assertIn(
                "public export ownership marker does not use its canonical encoding",
                errors,
            )

    def test_public_export_failure_retains_late_injected_staging_content(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "repo"
            output = Path(temp_dir) / "public"
            prepare_export_source(root)

            original_validation = public_export._checked_bound_export
            injected = False

            def inject_before_validation(
                descriptor: int,
                records: Mapping[str, tuple[str, int]],
            ) -> public_release_check.PublicExportTreeSnapshot:
                nonlocal injected
                if not injected:
                    candidates = list(
                        output.parent.glob(f".{output.name}.public-export-*")
                    )
                    self.assertEqual(1, len(candidates))
                    (candidates[0] / "late-unowned-content.txt").write_text(
                        "must survive\n",
                        encoding="utf-8",
                    )
                    injected = True
                return original_validation(descriptor, records)

            with (
                mock.patch.object(
                        public_export,
                        "_checked_bound_export",
                        side_effect=inject_before_validation,
                ),
                self.assertRaises(public_export.PublicExportFailure) as failure,
            ):
                public_export.export_public_tree(root, output, force=False)

            retained = failure.exception.retained_paths[0]
            self.assertIn(str(retained), str(failure.exception))
            self.assertEqual(
                "must survive\n",
                (retained / "late-unowned-content.txt").read_text(encoding="utf-8"),
            )
            marker = json.loads(
                (
                    retained
                    / public_release_check.PUBLIC_EXPORT_OWNERSHIP_MARKER
                ).read_text(encoding="utf-8")
            )
            self.assertNotIn("late-unowned-content.txt", marker["files"])

    def test_public_export_force_never_recursively_deletes_late_backup_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "repo"
            output = Path(temp_dir) / "public"
            prepare_export_source(root)
            public_export.export_public_tree(root, output, force=False)
            (root / "README.md").write_text("# New export\n", encoding="utf-8")

            original_check = public_export._require_preimage_snapshot
            injected_path: Path | None = None

            def inject_after_backup_validation(
                descriptor: int,
                expected: public_export._PreimageSnapshot,
            ) -> None:
                nonlocal injected_path
                original_check(descriptor, expected)
                retained = list(
                    output.parent.glob(
                        f".{output.name}.previous-export-*/tree"
                    )
                )
                if retained and injected_path is None:
                    injected_path = retained[0] / "late-owner-file.txt"
                    injected_path.write_text(
                        "must survive\n",
                        encoding="utf-8",
                    )

            with (
                mock.patch.object(
                    public_export,
                    "_require_preimage_snapshot",
                    side_effect=inject_after_backup_validation,
                ),
                self.assertRaises(public_export.PublicExportFailure) as failure,
            ):
                public_export.export_public_tree(root, output, force=True)

            if injected_path is None:
                self.fail("late backup mutation was not injected")
            self.assertEqual(
                "must survive\n",
                injected_path.read_text(encoding="utf-8"),
            )
            self.assertIn(injected_path.parent, failure.exception.retained_paths)
            self.assertEqual("# New export\n", (output / "README.md").read_text(encoding="utf-8"))
            self.assertEqual([], public_release_check.public_export_ownership_marker_errors(output))

    def test_force_ownership_never_uses_path_reopen_authority(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "repo"
            output = Path(temp_dir) / "public"
            prepare_export_source(root)
            public_export.export_public_tree(root, output, force=False)
            (root / "README.md").write_text("# Replacement\n", encoding="utf-8")

            with mock.patch.object(
                public_release_check,
                "public_export_ownership_marker_errors",
                side_effect=AssertionError(
                    "path-based ownership authority must not be used"
                ),
            ):
                result = public_export.export_public_tree(root, output, force=True)

            self.assertIsNotNone(result.retained_previous_export)
            self.assertEqual(
                "# Replacement\n",
                (output / "README.md").read_text(encoding="utf-8"),
            )

    def test_public_export_force_refuses_unowned_fake_stale_and_mutated_destinations(self) -> None:
        def make_owned_tree(path: Path) -> None:
            for rel in public_release_check.PUBLIC_EXPORT_SENTINEL_FILES:
                target = path / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(f"sentinel: {rel}\n", encoding="utf-8")
            _write_public_export_marker(path)

        mutations = ("unowned", "fake-marker", "stale-file", "extra-empty-directory", "marker-symlink")
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir) / "repo"
                output = Path(temp_dir) / "public"
                root.mkdir()
                output.mkdir()
                keep = output / "keep.txt"
                if mutation == "unowned":
                    keep.write_text("keep\n", encoding="utf-8")
                else:
                    make_owned_tree(output)
                    if mutation == "fake-marker":
                        marker = output / public_release_check.PUBLIC_EXPORT_OWNERSHIP_MARKER
                        marker.write_text(
                            json.dumps({"files": {}, "generator": "unrelated-tool", "schema_version": 2}),
                            encoding="utf-8",
                        )
                    elif mutation == "stale-file":
                        (output / "README.md").write_text("changed after export\n", encoding="utf-8")
                    elif mutation == "extra-empty-directory":
                        (output / "personal-notes").mkdir()
                    elif mutation == "marker-symlink":
                        marker = output / public_release_check.PUBLIC_EXPORT_OWNERSHIP_MARKER
                        external_marker = Path(temp_dir) / "external-marker.json"
                        external_marker.write_text(marker.read_text(encoding="utf-8"), encoding="utf-8")
                        marker.unlink()
                        marker.symlink_to(external_marker)

                with self.assertRaises(ValueError) as ctx:
                    public_export.export_public_tree(root, output, force=True)

                self.assertIn("not an intact exporter-owned public tree", str(ctx.exception))
                self.assertTrue(output.exists())
                if mutation == "unowned":
                    self.assertEqual("keep\n", keep.read_text(encoding="utf-8"))

    def test_public_export_rejects_untracked_required_public_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "repo"
            output = Path(temp_dir) / "public"
            write_required_public_files(root)
            run_bounded(["git", "init", "-q"], cwd=root, check=True)
            tracked = [rel for rel in public_surface.PUBLIC_REQUIRED_FILES if rel != "runtime/finding_schema.json"]
            run_bounded(["git", "add", *tracked], cwd=root, check=True)

            with self.assertRaises(ValueError) as ctx:
                public_export.export_public_tree(root, output, force=False)

            self.assertIn("public required file is not tracked by Git: runtime/finding_schema.json", str(ctx.exception))

    def test_public_export_rejects_tracked_undeclared_public_root_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "repo"
            output = Path(temp_dir) / "public"
            write_required_public_files(root)
            extra = root / "practice_guides" / "new.md"
            extra.write_text("# Undeclared\n", encoding="utf-8")
            run_bounded(["git", "init", "-q"], cwd=root, check=True)
            run_bounded(["git", "add", *public_surface.PUBLIC_REQUIRED_FILES, "practice_guides/new.md"], cwd=root, check=True)

            with self.assertRaises(ValueError) as ctx:
                public_export.export_public_tree(root, output, force=False)

        self.assertIn("undeclared public-surface file: practice_guides/new.md", str(ctx.exception))

    def test_validate_framework_root_argument_validates_requested_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "public"
            if (REPO_ROOT / ".git").exists():
                public_export.export_public_tree(REPO_ROOT, output, force=False)
            else:
                shutil.copytree(
                    REPO_ROOT,
                    output,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                )
            (output / "README.md").unlink()

            result = run_bounded(
                [sys.executable, "-B", "scripts/validate_framework.py", "--root", str(output)],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("missing file: README.md", result.stdout)

    def test_public_export_rejects_output_symlink_and_repo_ancestor(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "repo"
            target = Path(temp_dir) / "target"
            link = Path(temp_dir) / "public-link"
            broken_link = Path(temp_dir) / "broken-public-link"
            root.mkdir()
            target.mkdir()
            (target / "keep.txt").write_text("keep\n", encoding="utf-8")
            link.symlink_to(target, target_is_directory=True)
            broken_link.symlink_to(Path(temp_dir) / "missing-target", target_is_directory=True)

            with self.assertRaises(ValueError):
                public_export.export_public_tree(root, link, force=True)
            with self.assertRaises(ValueError):
                public_export.export_public_tree(root, broken_link, force=True)
            nested = link / "nested"
            with self.assertRaises(ValueError):
                public_export.export_public_tree(root, nested, force=True)
            with self.assertRaises(ValueError):
                public_export.export_public_tree(root, root, force=True)
            with self.assertRaises(ValueError):
                public_export.export_public_tree(root, root / "public", force=True)
            with self.assertRaises(ValueError):
                public_export.export_public_tree(root, Path(temp_dir), force=True)

            self.assertTrue((target / "keep.txt").exists())

    def test_public_export_cli_reports_destination_boundary_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "repo"
            root.mkdir()
            with (
                mock.patch.dict(os.environ, {}, clear=True),
                mock.patch("sys.stderr", new_callable=io.StringIO) as stderr,
                self.assertRaises(SystemExit) as ctx,
            ):
                public_export.main(
                    ["--root", str(root), "--output", str(root / "public")]
                )

        self.assertEqual(2, ctx.exception.code)
        self.assertIn("must not be the repository root, inside it, or an ancestor", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_validate_framework_reports_public_symlink_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            outside = root / "outside.md"
            outside.write_text("# Outside\n", encoding="utf-8")
            (root / "AGENTS.md").symlink_to(outside)
            (root / "practice_guides").mkdir()
            (root / "practice_guides" / "linked.md").symlink_to(outside)

            errors = validate_framework.public_symlink_errors(root)

        self.assertIn("public surface contains symlink path: AGENTS.md", errors)
        self.assertIn("public surface contains symlink path: practice_guides/linked.md", errors)

    def test_public_export_rejects_symlinked_source_ancestor(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "repo"
            outside = Path(temp_dir) / "outside"
            root.mkdir()
            outside.mkdir()
            (outside / "operative_charter.md").write_text("# Leak\n", encoding="utf-8")
            (root / "runtime").symlink_to(outside, target_is_directory=True)

            with mock.patch.object(
                public_release_check,
                "git_tracked_files",
                side_effect=retained_git_discovery(
                    {"runtime/operative_charter.md"}
                ),
            ):
                with self.assertRaises(ValueError):
                    public_export.public_source_files(root)

    @unittest.skipUnless(sys.platform == "linux", "requires Linux procfs")
    def test_bound_git_inventory_ignores_poison_path_and_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "repo"
            poison = base / "poison"
            root.mkdir()
            poison.mkdir()
            (root / "tracked.txt").write_text("tracked\n", encoding="utf-8")
            run_bounded(["git", "init", "-q"], cwd=root, check=True)
            run_bounded(["git", "add", "tracked.txt"], cwd=root, check=True)
            real_git_text = shutil.which("git")
            if real_git_text is None:
                self.fail("focused Git-binding regression requires installed Git")
            real_git = Path(real_git_text).resolve(strict=True)
            expected_sha256 = hashlib.sha256(real_git.read_bytes()).hexdigest()
            fake_git = poison / "git"
            fake_git.write_text("#!/bin/sh\nexit 97\n", encoding="utf-8")
            fake_git.chmod(0o755)
            source_descriptor = os.open(real_git, os.O_RDONLY)
            binding = public_release_check.open_inherited_git_executable_binding(
                source_descriptor,
                expected_sha256=expected_sha256,
            )
            observed_environments: list[dict[str, str]] = []
            original_run = (
                public_release_check.bounded_subprocess.run_bounded_process
            )

            def observe_run(
                *args: object,
                **kwargs: object,
            ) -> object:
                environment = kwargs.get("env")
                if isinstance(environment, dict):
                    observed_environments.append(dict(environment))
                return original_run(*args, **kwargs)  # type: ignore[arg-type]

            try:
                with (
                    mock.patch.dict(
                        os.environ,
                        {
                            "PATH": str(poison),
                            "PYTHONPATH": str(poison),
                            "UNRELATED_POISON": "must-not-reach-git",
                        },
                    ),
                    mock.patch.object(
                        public_release_check.bounded_subprocess,
                        "run_bounded_process",
                        side_effect=observe_run,
                    ),
                ):
                    tracked = public_release_check.git_tracked_files(
                        root,
                        git_executable=binding,
                    )
            finally:
                binding.close()
                os.close(source_descriptor)

        self.assertEqual({"tracked.txt"}, tracked)
        self.assertGreaterEqual(len(observed_environments), 1)
        for environment in observed_environments:
            self.assertNotIn("PATH", environment)
            self.assertNotIn("PYTHONPATH", environment)
            self.assertNotIn("UNRELATED_POISON", environment)

    @unittest.skipUnless(sys.platform == "linux", "requires Linux procfs")
    def test_bound_git_rejects_alternate_executable_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fake_git = Path(temp_dir) / "git"
            fake_git.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            fake_git.chmod(0o755)
            source_descriptor = os.open(fake_git, os.O_RDONLY)
            try:
                with self.assertRaisesRegex(
                    ValueError,
                    "does not match the approved digest",
                ):
                    public_release_check.open_inherited_git_executable_binding(
                        source_descriptor,
                        expected_sha256="0" * 64,
                    )
            finally:
                os.close(source_descriptor)

    def test_isolated_release_launcher_ignores_poison_python_startup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            poison = Path(temp_dir)
            marker = poison / "sitecustomize-ran"
            (poison / "sitecustomize.py").write_text(
                "from pathlib import Path\n"
                f"Path({str(marker)!r}).write_text('ran', encoding='utf-8')\n",
                encoding="utf-8",
            )
            environment = {
                **os.environ,
                "PATH": str(poison),
                "PYTHONPATH": str(poison),
                "PYTHONUSERBASE": str(poison / "user-base"),
            }
            with mock.patch.dict(os.environ, environment, clear=True):
                control = run_bounded(
                    [sys.executable, "-B", "-c", "pass"],
                    cwd=REPO_ROOT,
                    check=False,
                )
            self.assertEqual(0, control.returncode)
            self.assertTrue(marker.is_file())
            marker.unlink()
            script = REPO_ROOT / "scripts" / "public_release_check.py"
            launcher = (
                "import runpy,sys\n"
                "script=sys.argv[1]\n"
                "script_dir,separator,_=script.rpartition('/')\n"
                "assert separator and script_dir\n"
                "sys.path.insert(0,script_dir)\n"
                "sys.argv=sys.argv[1:]\n"
                "runpy.run_path(script,run_name='__main__')\n"
            )
            with mock.patch.dict(os.environ, environment, clear=True):
                isolated = run_bounded(
                    [
                        sys.executable,
                        "-I",
                        "-S",
                        "-B",
                        "-X",
                        "utf8",
                        "-c",
                        launcher,
                        str(script),
                        "--help",
                    ],
                    cwd=REPO_ROOT,
                    capture_output=True,
                    text=True,
                    check=False,
                )
            self.assertEqual(0, isolated.returncode, isolated.stderr)
            self.assertFalse(marker.exists())

    def test_public_export_threads_bound_git_into_source_snapshot(self) -> None:
        binding = mock.Mock(spec=public_release_check.GitExecutableBinding)
        injected = RuntimeError("stop after binding observation")
        with (
            mock.patch.object(
                public_release_check,
                "checked_public_source_snapshots",
                side_effect=injected,
            ) as checked,
            self.assertRaisesRegex(RuntimeError, "binding observation"),
        ):
            public_export.public_source_files(
                Path.cwd(),
                git_executable=binding,
            )

        binding.require_current.assert_called_once_with()
        checked.assert_called_once_with(
            Path.cwd().resolve(),
            set(public_surface.PUBLIC_REQUIRED_FILES),
            git_executable=binding,
            _binding_sink=mock.ANY,
        )

    def test_publication_boundary_export_requires_bound_git_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "repo"
            output = Path(temp_dir) / "public"
            root.mkdir()
            with (
                mock.patch.dict(os.environ, {}, clear=True),
                mock.patch.object(sys, "stderr", io.StringIO()) as stderr,
                self.assertRaises(SystemExit) as raised,
            ):
                public_export.main(
                    [
                        "--root",
                        str(root),
                        "--output",
                        str(output),
                        "--publication-boundary",
                    ]
                )

        self.assertEqual(2, raised.exception.code)
        self.assertIn("requires one retained Git descriptor", stderr.getvalue())

    def test_bound_basedpyright_rejects_different_tool_reported_version(self) -> None:
        uv = mock.Mock(spec=public_release_check.GitExecutableBinding)
        uv.external_command = "/proc/123/fd/7"
        with mock.patch.object(
            framework_compliance,
            "run",
            return_value=(
                True,
                "basedpyright-version: PASS",
                "basedpyright 1.39.8\n",
            ),
        ) as checked:
            result = framework_compliance.run_bound_python_type_check(
                uv,
                repo_root=REPO_ROOT,
            )

        self.assertFalse(result[0])
        self.assertIn("expected tool-reported version", result[1])
        command = checked.call_args.args[1]
        self.assertEqual("/proc/123/fd/7", command[0])
        self.assertIn("--offline", command)
        self.assertIn("--isolated", command)
        self.assertIn("--no-env-file", command)
        self.assertIn("--no-python-downloads", command)
        self.assertIn("basedpyright==1.39.9", command)
        self.assertEqual(["basedpyright", "--version"], command[-2:])

    def test_bound_basedpyright_accepts_exact_version_line(self) -> None:
        uv = mock.Mock(spec=public_release_check.GitExecutableBinding)
        uv.external_command = "/proc/123/fd/7"
        with mock.patch.object(
            framework_compliance,
            "run",
            side_effect=(
                (
                    True,
                    "basedpyright-version: PASS",
                    "basedpyright 1.39.9\nbased on pyright 1.1.411\n",
                ),
                (True, "python-type-check: PASS", ""),
            ),
        ):
            result = framework_compliance.run_bound_python_type_check(
                uv,
                repo_root=REPO_ROOT,
            )

        self.assertTrue(result[0], result[1])
        self.assertIn("tool-reported version: basedpyright 1.39.9", result[1])

    def test_publication_child_environment_normalizes_umask_and_node_heap(
        self,
    ) -> None:
        uv = mock.Mock(spec=public_release_check.GitExecutableBinding)
        uv.external_command = "/proc/123/fd/7"
        uv.sha256 = "1" * 64
        original = os.umask(0o077)
        try:
            with framework_compliance._publication_child_environment(
                git_executable=None,
                uv_executable=uv,
            ):
                observed = os.umask(0o077)
                os.umask(observed)
                self.assertEqual(
                    framework_compliance.PUBLICATION_CHILD_UMASK,
                    observed,
                )
                self.assertEqual(
                    framework_compliance.PUBLICATION_NODE_OPTIONS,
                    os.environ.get("NODE_OPTIONS"),
                )
            restored = os.umask(0o077)
            os.umask(restored)
            self.assertEqual(0o077, restored)
        finally:
            os.umask(original)

    def test_release_guide_uses_resumable_controller_and_bound_tools(self) -> None:
        guide = (REPO_ROOT / "docs" / "maintenance_and_release.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("scripts/public_release.py", guide)
        for command in ("prepare", "status", "resume", "publish", "readback"):
            self.assertIn(command, guide)
        for argument in (
            "--git-executable <resolved-git>",
            "--uv-executable <resolved-uv>",
            "--python-executable <resolved-python>",
            "--remote-url <credential-free-lowercase-https-url>",
            "--approve-candidate <full-candidate-object-id>",
            "--approve-retry-event <publication-bound-event-sha256>",
        ):
            self.assertIn(argument, guide)
        self.assertIn("--force-with-lease", guide)
        self.assertIn("fresh ordinary clone", guide)
        self.assertIn("publication-bound", guide)
        self.assertNotIn("release_bound_executable_sha256", guide)
        self.assertNotIn("release_bound_git_sha256", guide)
        for script in (
            "framework_compliance.py",
            "public_export.py",
            "public_release_check.py",
            "conformance_check.py",
            "public_handoff_check.py",
            "public_handoff_lifecycle.py",
        ):
            self.assertIn(script, guide)

    def test_publication_cli_roots_reject_abbreviated_options(self) -> None:
        cases = (
            (
                framework_compliance.main,
                ["--tree-role", "public-export", "--publication-boundar"],
            ),
            (
                public_export.main,
                [
                    "--output",
                    str(REPO_ROOT / "unused-abbreviation-output"),
                    "--publication-boundar",
                ],
            ),
            (
                public_release_check.main,
                ["--tree-role", "public-export", "--publication-boundar"],
            ),
        )
        for entrypoint, arguments in cases:
            with (
                self.subTest(entrypoint=entrypoint.__module__),
                mock.patch.object(sys, "stderr", io.StringIO()) as stderr,
                self.assertRaises(SystemExit) as raised,
            ):
                entrypoint(arguments)
            self.assertEqual(2, raised.exception.code)
            self.assertIn("unrecognized arguments", stderr.getvalue())

    def test_publication_boundary_compliance_requires_bound_uv_identity(self) -> None:
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(sys, "stderr", io.StringIO()) as stderr,
            self.assertRaises(SystemExit) as raised,
        ):
            framework_compliance.main(
                ["--tree-role", "public-export", "--publication-boundary"]
            )

        self.assertEqual(2, raised.exception.code)
        self.assertIn("requires a retained uv descriptor", stderr.getvalue())
