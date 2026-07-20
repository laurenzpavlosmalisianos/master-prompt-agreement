"""Transactional project bootstrap tests."""

from __future__ import annotations

from contextlib import ExitStack
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
from typing import Any, cast

from tests.validation_test_support import REPO_ROOT, TEST_FRAMEWORK_RUNNER

import bootstrap_transaction  # noqa: E402
import project_bootstrap  # noqa: E402


def _write_minimal_answers(path: Path, **overrides: object) -> None:
    """Write the shared minimal bootstrap input with explicit scenario overrides."""

    answers: dict[str, object] = {
        "bootstrap_mode": "minimal",
        "agent": "Agent",
        "project_name": "Demo",
        "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
    }
    answers.update(overrides)
    path.write_text(json.dumps(answers), encoding="utf-8")


def _run_project_bootstrap(
    answers_path: Path,
    project_root: Path,
    *extra_arguments: str,
    runtime: str = "generic",
) -> tuple[int, str]:
    """Run the bootstrap CLI with common neutral arguments and captured output."""

    arguments = [
        "project_bootstrap.py",
        "--answers",
        str(answers_path),
        "--project-root",
        str(project_root),
        "--runtime",
        runtime,
        "--framework-ref",
        str(REPO_ROOT),
        "--framework-revision-policy",
        "live",
        *extra_arguments,
    ]
    with (
        mock.patch.object(sys, "argv", arguments),
        mock.patch("sys.stdout", new_callable=io.StringIO) as stdout,
    ):
        result = project_bootstrap.main()
    return result, stdout.getvalue()


def _write_plan_approval_arguments(report: dict[str, object]) -> tuple[str, ...]:
    return (
        "--approve-write-plan-sha256",
        cast(str, report["write_plan_sha256"]),
    )


def _run_approved_project_bootstrap(
    answers_path: Path,
    project_root: Path,
    *extra_arguments: str,
    runtime: str = "generic",
) -> tuple[int, str]:
    dry_result, dry_output = _run_project_bootstrap(
        answers_path,
        project_root,
        *extra_arguments,
        "--dry-run",
        runtime=runtime,
    )
    dry_report = json.loads(dry_output)
    if dry_result != 0:
        raise AssertionError(dry_report)
    return _run_project_bootstrap(
        answers_path,
        project_root,
        *extra_arguments,
        *_write_plan_approval_arguments(dry_report),
        runtime=runtime,
    )


def _run_project_bootstrap_with_warnings(
    answers_path: Path,
    project_root: Path,
    warnings: tuple[str, ...],
    *extra_arguments: str,
) -> tuple[int, str]:
    real_build = project_bootstrap.build_bootstrap_write_plan

    def build_with_warning_sequence(
        inputs: project_bootstrap.BootstrapInputs,
        answers: dict,
    ) -> project_bootstrap.BootstrapWritePlan:
        plan = real_build(inputs, answers)
        summary = dict(plan.summary)
        summary["warnings"] = list(warnings)
        summary["warnings_sha256"] = project_bootstrap.bootstrap_warnings_sha256(
            summary["warnings"]
        )
        return project_bootstrap.BootstrapWritePlan(
            summary=summary,
            errors=plan.errors,
            effective_date=plan.effective_date,
            framework_identity=plan.framework_identity,
        )

    with mock.patch.object(
        project_bootstrap,
        "build_bootstrap_write_plan",
        side_effect=build_with_warning_sequence,
    ):
        return _run_project_bootstrap(
            answers_path,
            project_root,
            *extra_arguments,
        )


class BootstrapTransactionTests(unittest.TestCase):
    def test_bootstrap_transaction_public_api_is_narrow(self) -> None:
        self.assertEqual(
            (
                "BootstrapRecoveryStatus",
                "BootstrapTransactionError",
                "BootstrapWriteResult",
                "finalize_interrupted_transaction",
                "is_reserved_transaction_output",
                "rollback_interrupted_transaction",
                "transaction_capability_errors",
                "transaction_recovery_status",
                "transactional_write_outputs",
            ),
            bootstrap_transaction.__all__,
        )

    def test_bootstrap_transaction_capability_report_tracks_dirfd_support(self) -> None:
        available = bootstrap_transaction.transaction_capability_errors()
        with mock.patch.object(
            bootstrap_transaction.os,
            "supports_dir_fd",
            set(),
        ):
            unavailable = bootstrap_transaction.transaction_capability_errors()

        self.assertEqual((), available)
        self.assertTrue(
            any("descriptor-relative support" in error for error in unavailable),
            unavailable,
        )

    def test_close_binding_transfers_descriptor_before_its_single_close_attempt(
        self,
    ) -> None:
        binding = bootstrap_transaction._DirectoryBinding(
            descriptor=41,
            parent=None,
            entry_name=None,
            identity=(),
            label="fault fixture",
        )
        close_error = OSError("injected ambiguous close result")
        with mock.patch.object(
            bootstrap_transaction.os,
            "close",
            side_effect=close_error,
        ) as close:
            with self.assertRaises(OSError) as caught:
                bootstrap_transaction._close_binding(binding)
            bootstrap_transaction._close_binding(binding)

        self.assertIs(close_error, caught.exception)
        self.assertIsNone(binding.descriptor)
        close.assert_called_once_with(41)

    def test_bootstrap_creation_cleanup_attempts_every_distinct_action(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            metadata = Path(temp_dir).stat()
        parent = bootstrap_transaction._DirectoryBinding(
            descriptor=71,
            parent=None,
            entry_name=None,
            identity=bootstrap_transaction._directory_identity(metadata),
            label="project root",
            project_relative_parts=(),
        )
        for mechanism in ("bound-directory", "transaction-directory"):
            with self.subTest(mechanism=mechanism):
                events: list[str] = []
                primary = KeyboardInterrupt(
                    f"injected {mechanism} initialization interruption"
                )
                close_error = OSError(
                    f"injected {mechanism} ambiguous close result"
                )

                def fail_close(descriptor: int) -> None:
                    self.assertEqual(72, descriptor)
                    events.append("close")
                    raise close_error

                def record_rmdir(
                    name: str,
                    *,
                    dir_fd: int | None = None,
                ) -> None:
                    self.assertEqual(71, dir_fd)
                    events.append("rmdir")

                def record_fsync(descriptor: int) -> None:
                    self.assertEqual(71, descriptor)
                    events.append("fsync")

                open_results: list[object] = (
                    [FileNotFoundError(), 72]
                    if mechanism == "bound-directory"
                    else [72]
                )
                with (
                    mock.patch.object(
                        bootstrap_transaction.os,
                        "open",
                        side_effect=open_results,
                    ),
                    mock.patch.object(bootstrap_transaction.os, "mkdir"),
                    mock.patch.object(
                        bootstrap_transaction.os,
                        "fstat",
                        return_value=metadata,
                    ),
                    mock.patch.object(
                        bootstrap_transaction.os,
                        "fchmod",
                        side_effect=primary,
                    ),
                    mock.patch.object(
                        bootstrap_transaction.os,
                        "close",
                        side_effect=fail_close,
                    ),
                    mock.patch.object(
                        bootstrap_transaction.os,
                        "rmdir",
                        side_effect=record_rmdir,
                    ),
                    mock.patch.object(
                        bootstrap_transaction.os,
                        "fsync",
                        side_effect=record_fsync,
                    ),
                    self.assertRaises(KeyboardInterrupt) as caught,
                ):
                    if mechanism == "bound-directory":
                        bootstrap_transaction._open_bound_directory(
                            parent,
                            "nested",
                            label="test nested directory",
                            create=True,
                            require_owner=False,
                            created_bindings=[],
                            all_bindings=[],
                            create_mode=0o700,
                        )
                    else:
                        bootstrap_transaction._create_transaction_directory(
                            parent,
                            entry_name=(
                                ".mpa-bootstrap-transaction-"
                                + "0" * 32
                            ),
                            all_bindings=[],
                        )

                self.assertIs(primary, caught.exception)
                self.assertEqual(["close", "rmdir", "fsync"], events)
                self.assertTrue(
                    any(
                        "ambiguous close result" in note
                        for note in getattr(primary, "__notes__", ())
                    ),
                    getattr(primary, "__notes__", ()),
                )

        with self.subTest(mechanism="recovery-journal-temporary"):
            events = []
            primary = KeyboardInterrupt("injected recovery journal write interruption")
            close_error = OSError("injected journal temporary ambiguous close result")
            payload: dict[str, object] = {
                "schema_version": (
                    bootstrap_transaction.RECOVERY_JOURNAL_SCHEMA_VERSION
                ),
                "transaction_id": "a" * 32,
                "phase": "preparing",
                "applied_count": 0,
                "created_directories": [],
                "retired_directories": [],
                "operations": [
                    {
                        "path": "file.md",
                        "action": "write",
                        "transaction_directory": (
                            ".mpa-bootstrap-transaction-" + "b" * 32
                        ),
                        "stage_name": "stage-0",
                        "backup_name": None,
                        "original": None,
                        "candidate": {
                            "sha256": hashlib.sha256(b"x").hexdigest(),
                            "mode": None,
                            "size": 1,
                        },
                    }
                ],
            }
            self.assertEqual(
                [],
                bootstrap_transaction._validate_journal_payload(payload),
            )

            def fail_journal_close(descriptor: int) -> None:
                self.assertEqual(72, descriptor)
                events.append("close")
                raise close_error

            def record_temporary_retirement(
                root: bootstrap_transaction._DirectoryBinding,
                *,
                expected_object_identity: tuple[int, ...] | None = None,
            ) -> None:
                self.assertIs(parent, root)
                self.assertEqual(
                    bootstrap_transaction._inode_object_identity(metadata),
                    expected_object_identity,
                )
                events.append("retire")

            with (
                mock.patch.object(
                    bootstrap_transaction,
                    "_journal_metadata",
                    return_value=None,
                ),
                mock.patch.object(
                    bootstrap_transaction,
                    "_journal_temporary_metadata",
                    side_effect=[None, metadata],
                ),
                mock.patch.object(
                    bootstrap_transaction.os,
                    "open",
                    return_value=72,
                ),
                mock.patch.object(bootstrap_transaction.os, "fchmod"),
                mock.patch.object(
                    bootstrap_transaction.os,
                    "fstat",
                    return_value=metadata,
                ),
                mock.patch.object(
                    bootstrap_transaction,
                    "_write_all",
                    side_effect=primary,
                ),
                mock.patch.object(
                    bootstrap_transaction.os,
                    "close",
                    side_effect=fail_journal_close,
                ),
                mock.patch.object(
                    bootstrap_transaction,
                    "_remove_recovery_journal_temporary",
                    side_effect=record_temporary_retirement,
                ),
                self.assertRaises(KeyboardInterrupt) as caught,
            ):
                bootstrap_transaction._write_recovery_journal(
                    parent,
                    payload,
                    require_absent=True,
                )

            self.assertIs(primary, caught.exception)
            self.assertEqual(["close", "retire"], events)
            self.assertTrue(
                any(
                    "ambiguous close result" in note
                    for note in getattr(primary, "__notes__", ())
                ),
                getattr(primary, "__notes__", ()),
            )

    @unittest.skipIf(bootstrap_transaction.fcntl is None, "requires POSIX flock")
    def test_project_lock_cleanup_attempts_later_actions_without_masking_primary(
        self,
    ) -> None:
        fcntl_module = bootstrap_transaction.fcntl
        if fcntl_module is None:
            self.skipTest("requires POSIX flock")
        root_descriptor = 51
        transaction_descriptor = 52
        root = bootstrap_transaction._DirectoryBinding(
            descriptor=root_descriptor,
            parent=None,
            entry_name=None,
            identity=(),
            label="project root",
        )
        close_error = OSError("injected transaction-lock close failure")

        with self.subTest(path="release"):
            events: list[tuple[str, int, int | None]] = []

            def record_flock(descriptor: int, operation: int) -> None:
                events.append(("flock", descriptor, operation))

            def fail_close(descriptor: int) -> None:
                events.append(("close", descriptor, None))
                raise close_error

            with (
                mock.patch.object(
                    fcntl_module,
                    "flock",
                    side_effect=record_flock,
                ),
                mock.patch.object(
                    bootstrap_transaction.os,
                    "close",
                    side_effect=fail_close,
                ),
                self.assertRaises(OSError) as caught,
            ):
                bootstrap_transaction._release_project_lock(
                    root,
                    transaction_descriptor,
                )

            self.assertIs(close_error, caught.exception)
            self.assertEqual(
                [
                    ("flock", transaction_descriptor, fcntl_module.LOCK_UN),
                    ("close", transaction_descriptor, None),
                    ("flock", root_descriptor, fcntl_module.LOCK_UN),
                ],
                events,
            )

        with self.subTest(path="acquire-failure"):
            events = []
            primary = KeyboardInterrupt("injected acquisition interruption")

            def record_acquire_flock(descriptor: int, operation: int) -> None:
                events.append(("flock", descriptor, operation))

            def fail_acquire_close(descriptor: int) -> None:
                events.append(("close", descriptor, None))
                raise close_error

            with (
                mock.patch.object(
                    fcntl_module,
                    "flock",
                    side_effect=record_acquire_flock,
                ),
                mock.patch.object(
                    bootstrap_transaction.os,
                    "open",
                    return_value=transaction_descriptor,
                ),
                mock.patch.object(
                    bootstrap_transaction.os,
                    "fchmod",
                    side_effect=primary,
                ),
                mock.patch.object(
                    bootstrap_transaction.os,
                    "close",
                    side_effect=fail_acquire_close,
                ),
                mock.patch.object(
                    bootstrap_transaction,
                    "_lstat_at",
                    return_value=None,
                ),
                self.assertRaises(KeyboardInterrupt) as caught,
            ):
                bootstrap_transaction._acquire_project_lock(
                    root,
                    exclusive=True,
                )

            self.assertIs(primary, caught.exception)
            self.assertTrue(
                any(
                    "transaction-lock close failure" in note
                    for note in getattr(primary, "__notes__", ())
                ),
                getattr(primary, "__notes__", ()),
            )
            self.assertEqual(
                [
                    (
                        "flock",
                        root_descriptor,
                        fcntl_module.LOCK_EX | fcntl_module.LOCK_NB,
                    ),
                    ("flock", transaction_descriptor, fcntl_module.LOCK_UN),
                    ("close", transaction_descriptor, None),
                    ("flock", root_descriptor, fcntl_module.LOCK_UN),
                ],
                events,
            )

    def test_terminal_transaction_cleanup_attempts_all_actions_and_preserves_policy(
        self,
    ) -> None:
        ordinary_cases = [
            (mode, failure_index)
            for mode in ("raise", "primary", "committed-warning")
            for failure_index in (0, 1)
        ]
        for mode, failure_index in [
            *ordinary_cases,
            ("committed-interruption", 1),
        ]:
            with self.subTest(mode=mode, failure_index=failure_index):
                bindings = [
                    bootstrap_transaction._DirectoryBinding(
                        descriptor=index,
                        parent=None,
                        entry_name=None,
                        identity=(),
                        label=label,
                    )
                    for index, label in ((61, "first"), (62, "second"))
                ]
                expected_events = ["release", "close:second", "close:first"]
                events: list[str] = []
                cleanup_error: BaseException = (
                    KeyboardInterrupt("injected post-commit cleanup interruption")
                    if mode == "committed-interruption"
                    else OSError(f"injected terminal cleanup failure {failure_index}")
                )

                def record_action(event: str) -> None:
                    events.append(event)
                    if len(events) - 1 == failure_index:
                        raise cleanup_error

                primary = (
                    KeyboardInterrupt("injected active primary")
                    if mode == "primary"
                    else None
                )
                warnings: list[str] | None = (
                    []
                    if mode in {"committed-warning", "committed-interruption"}
                    else None
                )
                with (
                    mock.patch.object(
                        bootstrap_transaction,
                        "_release_project_lock",
                        side_effect=lambda root, descriptor: record_action("release"),
                    ),
                    mock.patch.object(
                        bootstrap_transaction,
                        "_close_binding",
                        side_effect=lambda binding: record_action(
                            f"close:{binding.label}"
                        ),
                    ),
                ):
                    if mode in {"raise", "committed-interruption"}:
                        expected_exception = (
                            KeyboardInterrupt
                            if mode == "committed-interruption"
                            else OSError
                        )
                        with self.assertRaises(expected_exception) as caught:
                            bootstrap_transaction._cleanup_transaction_resources(
                                None,
                                None,
                                bindings,
                                committed_cleanup_warnings=warnings,
                            )
                        self.assertIs(cleanup_error, caught.exception)
                    else:
                        bootstrap_transaction._cleanup_transaction_resources(
                            None,
                            None,
                            bindings,
                            primary=primary,
                            committed_cleanup_warnings=warnings,
                        )

                self.assertEqual(expected_events, events)
                if primary is not None:
                    self.assertTrue(
                        any(
                            "terminal cleanup failure" in note
                            for note in getattr(primary, "__notes__", ())
                        ),
                        getattr(primary, "__notes__", ()),
                    )
                if warnings is not None:
                    if mode == "committed-interruption":
                        self.assertEqual([], warnings)
                        self.assertTrue(
                            any(
                                "durably committed" in note
                                for note in getattr(cleanup_error, "__notes__", ())
                            ),
                            getattr(cleanup_error, "__notes__", ()),
                        )
                    else:
                        self.assertTrue(
                            any(
                                "terminal cleanup failure" in warning
                                for warning in warnings
                            ),
                            warnings,
                        )

    def test_project_bootstrap_dry_run_rejects_whole_plan_ancestor_collision(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "project"
            project_root.mkdir()
            answers_path = root / "answers.json"
            _write_minimal_answers(answers_path)
            result, output = _run_project_bootstrap(
                answers_path,
                project_root,
                "--create-contract-root",
                "--contract-root",
                "AGENTS.md",
                "--dry-run",
            )

        report = json.loads(output)
        self.assertEqual(1, result)
        self.assertTrue(
            any("both a file and an ancestor directory" in error for error in report["errors"]),
            report,
        )

    def test_project_bootstrap_preserves_disabled_unmarked_optional_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "project"
            project_root.mkdir()
            findings_path = project_root / "FINDINGS.md"
            project_owned = b"# Findings\n\n- Existing project-owned state.\n"
            findings_path.write_bytes(project_owned)
            findings_path.chmod(0o640)
            answers_path = root / "answers.json"
            _write_minimal_answers(answers_path)
            result, output = _run_approved_project_bootstrap(
                answers_path,
                project_root,
            )
            receipt_path = project_root / project_bootstrap.INSTANCE_MANIFEST
            receipt = (
                json.loads(receipt_path.read_text(encoding="utf-8"))
                if receipt_path.is_file()
                else None
            )
            preserved = findings_path.read_bytes()
            preserved_mode = findings_path.stat().st_mode & 0o777

        report = json.loads(output)
        self.assertEqual(0, result, report)
        self.assertEqual(project_owned, preserved)
        self.assertEqual(0o640, preserved_mode)
        self.assertIsInstance(receipt, dict)
        assert isinstance(receipt, dict)
        self.assertNotIn("FINDINGS.md", receipt["managed_files"])

    def test_project_bootstrap_rejects_disabled_marked_optional_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "project"
            project_root.mkdir()
            findings_path = project_root / "FINDINGS.md"
            marked = project_bootstrap.state_template_content("FINDINGS.md")
            findings_path.write_text(marked, encoding="utf-8")
            answers_path = root / "answers.json"
            _write_minimal_answers(answers_path)
            result, output = _run_project_bootstrap(
                answers_path,
                project_root,
                "--dry-run",
            )

        report = json.loads(output)
        self.assertEqual(1, result)
        self.assertTrue(
            any(
                "outside the requested output graph" in error
                and "FINDINGS.md" in error
                for error in report["errors"]
            ),
            report,
        )

    def test_create_only_discovers_mpa_surfaces_outside_requested_graph(self) -> None:
        cases = (
            ("alternate runtime entrypoint", "CLAUDE.md"),
            (
                "omitted registered wrapper",
                ".agents/skills/security-audit/SKILL.md",
            ),
            (
                "alternate contract root",
                "governance/previous/STATEMENT_OF_WORK.md",
            ),
            ("alternate retained input", "governance/previous/PROJECT_INPUT.json"),
            ("alternate instance receipt", "governance/previous/PROJECT_INSTANCE.json"),
        )
        for label, expected_path in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                project_root = root / "project"
                project_root.mkdir()
                answers_path = root / "answers.json"
                _write_minimal_answers(answers_path)
                if label == "alternate runtime entrypoint":
                    _name, content = project_bootstrap.render_entrypoint(
                        "claude-code",
                        str(REPO_ROOT),
                    )
                    target = project_root / expected_path
                    target.write_text(content, encoding="utf-8")
                    runtime = "generic"
                elif label == "omitted registered wrapper":
                    rendered = (
                        project_bootstrap.integration_registry.render_wrapper_outputs(
                            "codex",
                            ["security_audit"],
                            str(REPO_ROOT),
                            ".",
                            REPO_ROOT,
                        )
                    )
                    target = project_root / expected_path
                    target.parent.mkdir(parents=True)
                    target.write_text(rendered[expected_path], encoding="utf-8")
                    runtime = "codex"
                elif label == "alternate contract root":
                    target = project_root / expected_path
                    target.parent.mkdir(parents=True)
                    target.write_text(
                        project_bootstrap.contract_model.CONTRACT_FORMAT_MARKER
                        + "\nStatement of Work — Previous\n",
                        encoding="utf-8",
                    )
                    runtime = "generic"
                elif label == "alternate retained input":
                    target = project_root / expected_path
                    target.parent.mkdir(parents=True)
                    target.write_text(
                        json.dumps(
                            {
                                "answers": {},
                                "contract_root": "governance/previous",
                                "framework_reference": "$FRAMEWORK",
                                "framework_revision_policy": "live",
                                "runtime_wrappers": [],
                            }
                        ),
                        encoding="utf-8",
                    )
                    runtime = "generic"
                else:
                    target = project_root / expected_path
                    target.parent.mkdir(parents=True)
                    target.write_text(
                        json.dumps(
                            {
                                "input_source": "governance/previous/PROJECT_INPUT.json",
                                "managed_files": [],
                                "project_contract_format": 1,
                                "project_input_schema_version": 1,
                            }
                        ),
                        encoding="utf-8",
                    )
                    runtime = "generic"

                result, output = _run_project_bootstrap(
                    answers_path,
                    project_root,
                    "--dry-run",
                    runtime=runtime,
                )

                report = json.loads(output)
                self.assertEqual(1, result, report)
                self.assertTrue(
                    any(
                        "outside the requested output graph" in error
                        and expected_path in error
                        and "reviewed project-specific manual update" in error
                        for error in report["errors"]
                    ),
                    report,
                )
                self.assertEqual(
                    {expected_path},
                    {
                        path.relative_to(project_root).as_posix()
                        for path in project_root.rglob("*")
                        if path.is_file()
                    },
                )

    def test_create_only_discovers_state_only_residue_outside_requested_contract_root(
        self,
    ) -> None:
        for state_name in sorted(project_bootstrap.STATE_TEMPLATES):
            relative = f"governance/previous/{state_name}"
            with self.subTest(state_name=state_name), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                project_root = root / "project"
                target = project_root / relative
                target.parent.mkdir(parents=True)
                state_content = project_bootstrap.state_template_content(state_name)
                if state_name == "AUTOMATION_ORDERS.json":
                    payload = json.loads(state_content)
                    origin = payload.pop(
                        project_bootstrap.project_state_identity.JSON_STATE_ORIGIN_KEY
                    )
                    payload[
                        project_bootstrap.project_state_identity.JSON_STATE_ORIGIN_KEY
                    ] = origin
                    state_content = json.dumps(payload, indent=2) + "\n"
                target.write_text(state_content, encoding="utf-8")
                answers_path = root / "answers.json"
                _write_minimal_answers(answers_path)

                result, output = _run_project_bootstrap(
                    answers_path,
                    project_root,
                    "--create-contract-root",
                    "--contract-root",
                    ".mpa/new",
                    "--dry-run",
                )

                report = json.loads(output)
                self.assertEqual(1, result, report)
                self.assertTrue(
                    any(
                        "outside the requested output graph" in error
                        and relative in error
                        and "reviewed project-specific manual update" in error
                        for error in report["errors"]
                    ),
                    report,
                )

    def test_existing_surface_discovery_does_not_reserve_unmarked_state_names(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "project"
            project_root.mkdir()
            for state_name in sorted(project_bootstrap.STATE_TEMPLATES):
                target = project_root / "ordinary" / state_name
                target.parent.mkdir(parents=True, exist_ok=True)
                if state_name.endswith(".json"):
                    target.write_text(
                        json.dumps(
                            {
                                "note": project_bootstrap.project_state_identity.GENERATED_STATE_ORIGIN,
                                "project_owned": True,
                            }
                        )
                        + "\n",
                        encoding="utf-8",
                    )
                else:
                    target.write_text(
                        f"# Project-owned {state_name}\n\n"
                        + project_bootstrap.project_state_identity.GENERATED_STATE_ORIGIN
                        + "\n",
                        encoding="utf-8",
                    )
            answers_path = root / "answers.json"
            _write_minimal_answers(answers_path)

            result, output = _run_project_bootstrap(
                answers_path,
                project_root,
                "--create-contract-root",
                "--contract-root",
                ".mpa/new",
                "--dry-run",
            )

        report = json.loads(output)
        self.assertEqual(0, result, report)
        self.assertEqual([], report.get("errors", []), report)

    def test_framework_authoring_discovery_excludes_only_owned_state_template_sources(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / "framework"
            owned_source = project_root / "project_state_templates" / "TODO.md"
            owned_source.parent.mkdir(parents=True)
            owned_source.write_text(
                project_bootstrap.state_template_content("TODO.md"),
                encoding="utf-8",
            )

            clean_errors = (
                project_bootstrap.outside_requested_generated_surface_errors(
                    project_root,
                    set(),
                    project_kind="framework-authoring",
                    framework_root=project_root,
                )
            )

            unowned_source = (
                project_root / "project_state_templates" / "nested" / "TODO.md"
            )
            unowned_source.parent.mkdir()
            unowned_source.write_text(
                project_bootstrap.state_template_content("TODO.md"),
                encoding="utf-8",
            )
            residue_errors = (
                project_bootstrap.outside_requested_generated_surface_errors(
                    project_root,
                    set(),
                    project_kind="framework-authoring",
                    framework_root=project_root,
                )
            )

        self.assertEqual([], clean_errors)
        self.assertTrue(
            any(
                "project_state_templates/nested/TODO.md" in error
                and "outside the requested output graph" in error
                for error in residue_errors
            ),
            residue_errors,
        )

    def test_unmarked_state_names_do_not_consume_generated_candidate_bound(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "project"
            project_root.mkdir()
            for index in range(
                project_bootstrap.GENERATED_SURFACE_DISCOVERY_MAX_CANDIDATES + 1
            ):
                target = project_root / "ordinary" / str(index) / "TODO.md"
                target.parent.mkdir(parents=True)
                target.write_text("# Project-owned task list\n", encoding="utf-8")
            answers_path = root / "answers.json"
            _write_minimal_answers(answers_path)

            result, output = _run_project_bootstrap(
                answers_path,
                project_root,
                "--create-contract-root",
                "--contract-root",
                ".mpa/new",
                "--dry-run",
            )

        report = json.loads(output)
        self.assertEqual(0, result, report)
        self.assertEqual([], report.get("errors", []), report)

    def test_create_only_rejects_unmarked_hardlinked_state_basename(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "project"
            state_path = project_root / "governance" / "previous" / "TODO.md"
            state_path.parent.mkdir(parents=True)
            state_path.write_text("# Project-owned task list\n", encoding="utf-8")
            linked_path = project_root / "ordinary-hardlink-copy.md"
            os.link(state_path, linked_path)
            answers_path = root / "answers.json"
            _write_minimal_answers(answers_path)

            result, output = _run_project_bootstrap(
                answers_path,
                project_root,
                "--create-contract-root",
                "--contract-root",
                ".mpa/new",
                "--dry-run",
            )
            self.assertEqual(
                "# Project-owned task list\n",
                state_path.read_text(encoding="utf-8"),
            )
            self.assertTrue(state_path.samefile(linked_path))

        report = json.loads(output)
        self.assertEqual(1, result, report)
        self.assertTrue(
            any(
                "could not complete bounded existing-surface discovery" in error
                and "governance/previous/TODO.md" in error
                and "exactly one hard link" in error
                for error in report["errors"]
            ),
            report,
        )

    def test_create_only_rejects_uninspectable_json_state_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "project"
            state_path = (
                project_root
                / "governance"
                / "previous"
                / "AUTOMATION_ORDERS.json"
            )
            state_path.parent.mkdir(parents=True)
            state_path.write_text("{not-json\n", encoding="utf-8")
            answers_path = root / "answers.json"
            _write_minimal_answers(answers_path)

            result, output = _run_project_bootstrap(
                answers_path,
                project_root,
                "--create-contract-root",
                "--contract-root",
                ".mpa/new",
                "--dry-run",
            )

        report = json.loads(output)
        self.assertEqual(1, result, report)
        self.assertTrue(
            any(
                "could not complete bounded existing-surface discovery" in error
                and "governance/previous/AUTOMATION_ORDERS.json" in error
                and "JSON identity is not inspectable" in error
                for error in report["errors"]
            ),
            report,
        )

    def test_existing_surface_discovery_reserves_identity_basenames(self) -> None:
        cases = {
            "archive/malformed-input/PROJECT_INPUT.json": b"{not-json",
            "archive/partial-input/PROJECT_INPUT.json": json.dumps(
                {"framework_reference": "$FRAMEWORK"}
            ).encode("utf-8"),
            "archive/malformed-instance/PROJECT_INSTANCE.json": b"[",
            "archive/partial-instance/PROJECT_INSTANCE.json": json.dumps(
                {"project_contract_format": 1}
            ).encode("utf-8"),
        }
        for relative, raw in cases.items():
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                project_root = root / "project"
                target = project_root / relative
                target.parent.mkdir(parents=True)
                target.write_bytes(raw)
                answers_path = root / "answers.json"
                _write_minimal_answers(answers_path)

                result, output = _run_project_bootstrap(
                    answers_path,
                    project_root,
                    "--dry-run",
                )

                report = json.loads(output)
                self.assertEqual(1, result, report)
                self.assertTrue(
                    any(
                        "outside the requested output graph" in error
                        and relative in error
                        and "reviewed project-specific manual update" in error
                        for error in report["errors"]
                    ),
                    report,
                )

    def test_existing_surface_discovery_ignores_nonreserved_json_lookalikes(
        self,
    ) -> None:
        lookalikes = {
            "archive/project-input-policy.json": {
                "notes": [
                    "framework_reference",
                    "framework_revision_policy",
                    "runtime_wrappers",
                ]
            },
            "archive/project-instance-notes.json": {
                "notes": [
                    "generation_sources",
                    "project_contract_format",
                    "project_input_schema_version",
                ]
            },
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "project"
            project_root.mkdir()
            for relative, payload in lookalikes.items():
                target = project_root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(payload), encoding="utf-8")
            answers_path = root / "answers.json"
            _write_minimal_answers(answers_path)

            result, output = _run_project_bootstrap(
                answers_path,
                project_root,
                "--dry-run",
            )

        report = json.loads(output)
        self.assertEqual(0, result, report)
        self.assertEqual([], report.get("errors", []), report)

    def test_existing_surface_discovery_fails_closed_on_candidate_rebinding(
        self,
    ) -> None:
        mutations = ("vanish", "replacement", "symlink")
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temp_dir:
                project_root = Path(temp_dir) / "project"
                target = project_root / "archive" / "STATEMENT_OF_WORK.md"
                target.parent.mkdir(parents=True)
                target.write_text(
                    project_bootstrap.contract_model.CONTRACT_FORMAT_MARKER
                    + "\nStatement of Work — Previous\n",
                    encoding="utf-8",
                )
                replacement_source = project_root / "replacement.md"
                replacement_source.write_text("replacement\n", encoding="utf-8")
                original_open = project_bootstrap.os.open
                original_supports_dir_fd = set(project_bootstrap.os.supports_dir_fd)
                mutated = False

                def mutate_candidate_open(
                    path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
                    flags: int,
                    mode: int = 0o777,
                    *,
                    dir_fd: int | None = None,
                ) -> int:
                    nonlocal mutated
                    if (
                        not mutated
                        and path == "STATEMENT_OF_WORK.md"
                        and dir_fd is not None
                    ):
                        mutated = True
                        if mutation == "vanish":
                            target.unlink()
                        elif mutation == "replacement":
                            target.replace(project_root / "observed-contract.md")
                            target.write_text("unrelated replacement\n", encoding="utf-8")
                        else:
                            target.unlink()
                            target.symlink_to(replacement_source)
                    return original_open(path, flags, mode, dir_fd=dir_fd)

                with mock.patch.object(
                    project_bootstrap.os,
                    "open",
                    side_effect=mutate_candidate_open,
                ) as patched_open:
                    with mock.patch.object(
                        project_bootstrap.os,
                        "supports_dir_fd",
                        original_supports_dir_fd | {patched_open},
                    ):
                        errors = (
                            project_bootstrap.outside_requested_generated_surface_errors(
                                project_root,
                                set(),
                                project_kind="downstream",
                            )
                        )

                self.assertTrue(mutated)
                self.assertTrue(
                    any(
                        "could not complete bounded existing-surface discovery"
                        in error
                        and "STATEMENT_OF_WORK.md" in error
                        for error in errors
                    ),
                    errors,
                )

    def test_registered_runtime_target_read_rejects_name_rebinding(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / "project"
            project_root.mkdir()
            target = project_root / "CLAUDE.md"
            _name, content = project_bootstrap.render_entrypoint(
                "claude-code",
                str(REPO_ROOT),
            )
            target.write_text(content, encoding="utf-8")
            original_open = project_bootstrap.os.open
            original_supports_dir_fd = set(project_bootstrap.os.supports_dir_fd)
            mutated = False

            def replace_registered_target(
                path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
                flags: int,
                mode: int = 0o777,
                *,
                dir_fd: int | None = None,
            ) -> int:
                nonlocal mutated
                if not mutated and path == "CLAUDE.md" and dir_fd is not None:
                    mutated = True
                    target.replace(project_root / "observed-claude.md")
                    target.write_text("unrelated replacement\n", encoding="utf-8")
                return original_open(path, flags, mode, dir_fd=dir_fd)

            with mock.patch.object(
                project_bootstrap.os,
                "open",
                side_effect=replace_registered_target,
            ) as patched_open:
                with mock.patch.object(
                    project_bootstrap.os,
                    "supports_dir_fd",
                    original_supports_dir_fd | {patched_open},
                ):
                    raw, error = project_bootstrap._read_existing_surface_candidate(
                        "CLAUDE.md",
                        project_root,
                        label="registered runtime target",
                    )

        self.assertTrue(mutated)
        self.assertIsNone(raw)
        self.assertIsNotNone(error)
        self.assertIn("changed while it was opened", error or "")

    def test_registered_runtime_target_read_rejects_absent_target_appearing(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / "project"
            project_root.mkdir()
            target = project_root / "CLAUDE.md"
            original_stat = project_bootstrap.os.stat
            original_supports_dir_fd = set(project_bootstrap.os.supports_dir_fd)
            original_supports_follow = set(
                project_bootstrap.os.supports_follow_symlinks
            )
            appeared = False

            def create_after_absence(
                path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
                *,
                dir_fd: int | None = None,
                follow_symlinks: bool = True,
            ) -> os.stat_result:
                nonlocal appeared
                try:
                    return original_stat(
                        path,
                        dir_fd=dir_fd,
                        follow_symlinks=follow_symlinks,
                    )
                except FileNotFoundError:
                    if not appeared and path == "CLAUDE.md" and dir_fd is not None:
                        appeared = True
                        target.write_text("new framework entrypoint\n", encoding="utf-8")
                    raise

            with mock.patch.object(
                project_bootstrap.os,
                "stat",
                side_effect=create_after_absence,
            ) as patched_stat:
                with (
                    mock.patch.object(
                        project_bootstrap.os,
                        "supports_dir_fd",
                        original_supports_dir_fd | {patched_stat},
                    ),
                    mock.patch.object(
                        project_bootstrap.os,
                        "supports_follow_symlinks",
                        original_supports_follow | {patched_stat},
                    ),
                ):
                    raw, error = project_bootstrap._read_existing_surface_candidate(
                        "CLAUDE.md",
                        project_root,
                        label="registered runtime target",
                    )

        self.assertTrue(appeared)
        self.assertIsNone(raw)
        self.assertIsNotNone(error)
        self.assertIn("appeared during discovery", error or "")

    def test_registered_target_cleanup_preserves_diagnostic_and_attempts_every_descriptor(
        self,
    ) -> None:
        """A close-then-raise model still avoids an oracle for the failed FD state."""

        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / "project"
            target = project_root / ".agents" / "skills" / "example" / "SKILL.md"
            target.mkdir(parents=True)
            real_open = project_bootstrap.os.open
            real_close = project_bootstrap.os.close
            opened: list[int] = []
            attempted: list[int] = []

            def record_open(
                path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
                flags: int,
                mode: int = 0o777,
                *,
                dir_fd: int | None = None,
            ) -> int:
                descriptor = real_open(path, flags, mode, dir_fd=dir_fd)
                opened.append(descriptor)
                return descriptor

            def close_then_fail_first(descriptor: int) -> None:
                attempted.append(descriptor)
                real_close(descriptor)
                if len(attempted) == 1:
                    raise OSError("injected first descriptor cleanup failure")

            original_supports_dir_fd = set(project_bootstrap.os.supports_dir_fd)
            with (
                mock.patch.object(
                    project_bootstrap.os,
                    "open",
                    side_effect=record_open,
                ) as patched_open,
                mock.patch.object(
                    project_bootstrap.os,
                    "close",
                    side_effect=close_then_fail_first,
                ),
                mock.patch.object(
                    project_bootstrap.os,
                    "supports_dir_fd",
                    original_supports_dir_fd | {patched_open},
                ),
            ):
                raw, error = project_bootstrap._read_existing_surface_candidate(
                    ".agents/skills/example/SKILL.md",
                    project_root,
                    label="registered runtime target",
                )

            failed_descriptor = attempted[0]
            live_later_descriptors: list[int] = []
            for descriptor in (item for item in opened if item != failed_descriptor):
                try:
                    os.fstat(descriptor)
                except OSError:
                    continue
                live_later_descriptors.append(descriptor)
                os.close(descriptor)

        self.assertIsNone(raw)
        self.assertIsNotNone(error)
        self.assertIn("must be a regular non-link file", error or "")
        self.assertIn("descriptor cleanup failed", error or "")
        self.assertEqual(list(reversed(opened)), attempted)
        self.assertEqual([], live_later_descriptors)

    def test_existing_surface_discovery_bounds_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "project"
            project_root.mkdir()
            (project_root / "ordinary.txt").write_text("ordinary\n", encoding="utf-8")
            answers_path = root / "answers.json"
            _write_minimal_answers(answers_path)
            with mock.patch.object(
                project_bootstrap,
                "GENERATED_SURFACE_DISCOVERY_MAX_ENTRIES",
                0,
            ):
                result, output = _run_project_bootstrap(
                    answers_path,
                    project_root,
                    "--dry-run",
                )

        report = json.loads(output)
        self.assertEqual(1, result, report)
        self.assertTrue(
            any(
                "could not complete bounded existing-surface discovery" in error
                and "exceeded its entry bound" in error
                for error in report["errors"]
            ),
            report,
        )

    def test_transaction_preflight_precedes_all_bootstrap_input_loading(self) -> None:
        statuses = (
            bootstrap_transaction.BootstrapRecoveryStatus(
                state="active",
                transaction_id=None,
                phase=None,
                operation_paths=(),
                can_rollback=False,
                can_finalize=False,
                errors=(),
            ),
            bootstrap_transaction.BootstrapRecoveryStatus(
                state="recovery-required",
                transaction_id="1" * 32,
                phase="applying",
                operation_paths=("AGENT_PROJECT.md",),
                can_rollback=True,
                can_finalize=False,
                errors=(),
            ),
            bootstrap_transaction.BootstrapRecoveryStatus(
                state="verified",
                transaction_id="2" * 32,
                phase="verified",
                operation_paths=("AGENT_PROJECT.md",),
                can_rollback=False,
                can_finalize=True,
                errors=(),
            ),
            bootstrap_transaction.BootstrapRecoveryStatus(
                state="invalid",
                transaction_id=None,
                phase=None,
                operation_paths=(),
                can_rollback=False,
                can_finalize=False,
                errors=("lock exists without a recovery journal",),
            ),
            bootstrap_transaction.BootstrapRecoveryStatus(
                state="invalid",
                transaction_id=None,
                phase=None,
                operation_paths=(),
                can_rollback=False,
                can_finalize=False,
                errors=("temporary journal exists without a canonical journal",),
            ),
        )
        for recovery in statuses:
            with self.subTest(state=recovery.state, errors=recovery.errors):
                with tempfile.TemporaryDirectory() as temp_dir:
                    project_root = Path(temp_dir) / "project"
                    project_root.mkdir()
                    argv = [
                        "project_bootstrap.py",
                        "--answers",
                        str(project_root / "missing-answers.json"),
                        "--setup-profile",
                        str(project_root / "missing-profile.json"),
                        "--project-root",
                        str(project_root),
                        "--runtime",
                        "generic",
                        "--framework-revision-policy",
                        "live",
                    ]
                    with (
                        mock.patch.object(sys, "argv", argv),
                        mock.patch.object(
                            bootstrap_transaction,
                            "transaction_recovery_status",
                            return_value=recovery,
                        ),
                        mock.patch.object(
                            project_bootstrap,
                            "load_json_input",
                            side_effect=AssertionError(
                                "bootstrap input loaded before transaction preflight"
                            ),
                        ) as load_json,
                        mock.patch.object(
                            project_bootstrap,
                            "existing_instance_bootstrap_errors",
                            side_effect=AssertionError(
                                "collision classification ran before transaction preflight"
                            ),
                        ) as classify,
                        mock.patch("sys.stdout", new_callable=io.StringIO) as stdout,
                    ):
                        result = project_bootstrap.main()

                report = json.loads(stdout.getvalue())
                self.assertEqual(project_bootstrap.EXIT_RECOVERY_REQUIRED, result, report)
                self.assertEqual("recovery-required", report["status"])
                self.assertEqual(recovery.state, report["transaction_state"])
                self.assertEqual(
                    recovery.transaction_id,
                    report["transaction_id"],
                )
                if recovery.can_rollback:
                    self.assertEqual("rollback", report["recovery_route"]["action"])
                elif recovery.can_finalize:
                    self.assertEqual("finalize", report["recovery_route"]["action"])
                else:
                    self.assertIsNone(report["recovery_route"])
                load_json.assert_not_called()
                classify.assert_not_called()
                self.assertNotIn("bootstrap_mode", report)

    def test_transaction_control_artifacts_precede_malformed_answers(self) -> None:
        controls = (
            bootstrap_transaction.TRANSACTION_LOCK_NAME,
            bootstrap_transaction._RECOVERY_JOURNAL_TEMP_NAME,
        )
        for control_name in controls:
            with self.subTest(control=control_name), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                project_root = root / "project"
                project_root.mkdir()
                control = project_root / control_name
                control.write_bytes(b"")
                control.chmod(0o600)
                malformed_answers = root / "answers.json"
                malformed_answers.write_text("{not-json", encoding="utf-8")

                result, output = _run_project_bootstrap(
                    malformed_answers,
                    project_root,
                )

                report = json.loads(output)
                self.assertEqual(
                    project_bootstrap.EXIT_RECOVERY_REQUIRED,
                    result,
                    report,
                )
                self.assertEqual("recovery-required", report["status"])
                self.assertNotEqual("clean", report["transaction_state"])
                self.assertNotIn("bootstrap_mode", report)
                self.assertFalse(
                    any("bootstrap answers file" in error for error in report["errors"]),
                    report,
                )

    def test_uninspectable_project_root_precedes_all_bootstrap_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "project-loop"
            project_root.symlink_to(project_root.name)
            argv = [
                "project_bootstrap.py",
                "--answers",
                str(root / "missing-answers.json"),
                "--setup-profile",
                str(root / "missing-profile.json"),
                "--project-root",
                str(project_root),
                "--runtime",
                "generic",
                "--framework-revision-policy",
                "live",
            ]
            guarded_helpers = (
                "load_json_input",
                "referenced_project_file_errors",
                "outside_requested_generated_surface_errors",
                "existing_instance_bootstrap_errors",
            )
            patches = [
                mock.patch.object(
                    project_bootstrap,
                    name,
                    side_effect=AssertionError(
                        f"{name} ran before target-root transaction preflight"
                    ),
                )
                for name in guarded_helpers
            ]
            started = [patcher.start() for patcher in patches]
            try:
                with (
                    mock.patch.object(sys, "argv", argv),
                    mock.patch("sys.stdout", new_callable=io.StringIO) as stdout,
                ):
                    result = project_bootstrap.main()
            finally:
                for patcher in reversed(patches):
                    patcher.stop()

        report = json.loads(stdout.getvalue())
        self.assertEqual(project_bootstrap.EXIT_RECOVERY_REQUIRED, result, report)
        self.assertEqual("invalid", report["transaction_state"])
        self.assertNotIn("bootstrap_mode", report)
        self.assertTrue(report["errors"], report)
        for helper in started:
            helper.assert_not_called()

    def test_project_root_resolution_drift_precedes_bootstrap_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first_root = root / "first-project"
            second_root = root / "second-project"
            first_root.mkdir()
            second_root.mkdir()
            real_resolve = project_bootstrap.resolve_user_path
            target_resolutions = 0

            def drift_target_resolution(
                raw_path: str,
                label: str,
            ) -> tuple[Path, Path, list[str]]:
                nonlocal target_resolutions
                if label != "target project root":
                    return real_resolve(raw_path, label)
                target_resolutions += 1
                return (
                    first_root,
                    first_root if target_resolutions == 1 else second_root,
                    [],
                )

            argv = [
                "project_bootstrap.py",
                "--answers",
                str(root / "missing-answers.json"),
                "--project-root",
                str(first_root),
                "--runtime",
                "generic",
                "--framework-revision-policy",
                "live",
            ]
            with (
                mock.patch.object(sys, "argv", argv),
                mock.patch.object(
                    project_bootstrap,
                    "resolve_user_path",
                    side_effect=drift_target_resolution,
                ),
                mock.patch.object(
                    project_bootstrap,
                    "load_json_input",
                    side_effect=AssertionError(
                        "bootstrap input loaded after project-root resolution drift"
                    ),
                ) as load_json,
                mock.patch("sys.stdout", new_callable=io.StringIO) as stdout,
            ):
                result = project_bootstrap.main()

        report = json.loads(stdout.getvalue())
        self.assertEqual(project_bootstrap.EXIT_RECOVERY_REQUIRED, result, report)
        self.assertEqual("invalid", report["transaction_state"])
        self.assertTrue(
            any("resolved to a different location" in error for error in report["errors"]),
            report,
        )
        load_json.assert_not_called()

    def test_project_root_identity_drift_stops_before_collision_checks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "project"
            displaced_root = root / "displaced-project"
            project_root.mkdir()
            answers_path = root / "answers.json"
            _write_minimal_answers(answers_path)
            real_load_json = project_bootstrap.load_json_input
            mutated = False

            def replace_root_after_answers(
                raw_path: str,
                label: str,
            ) -> tuple[Path, bytes | None, object | None, list[str]]:
                nonlocal mutated
                result = real_load_json(raw_path, label)
                if not mutated and label == "bootstrap answers file":
                    mutated = True
                    project_root.rename(displaced_root)
                    project_root.mkdir()
                return result

            argv = [
                "project_bootstrap.py",
                "--answers",
                str(answers_path),
                "--project-root",
                str(project_root),
                "--runtime",
                "generic",
                "--framework-ref",
                str(REPO_ROOT),
                "--framework-revision-policy",
                "live",
            ]
            with (
                mock.patch.object(sys, "argv", argv),
                mock.patch.object(
                    project_bootstrap,
                    "load_json_input",
                    side_effect=replace_root_after_answers,
                ),
                mock.patch.object(
                    project_bootstrap,
                    "existing_instance_bootstrap_errors",
                    side_effect=AssertionError(
                        "collision classification ran after project-root drift"
                    ),
                ) as classify,
                mock.patch("sys.stdout", new_callable=io.StringIO) as stdout,
            ):
                result = project_bootstrap.main()

        report = json.loads(stdout.getvalue())
        self.assertTrue(mutated)
        self.assertEqual(project_bootstrap.EXIT_RECOVERY_REQUIRED, result, report)
        self.assertEqual("invalid", report["transaction_state"])
        self.assertTrue(
            any("binding changed" in error for error in report["errors"]),
            report,
        )
        classify.assert_not_called()

    def test_transaction_control_appearing_during_input_load_stops_classification(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "project"
            project_root.mkdir()
            answers_path = root / "answers.json"
            _write_minimal_answers(answers_path)
            control = project_root / bootstrap_transaction.TRANSACTION_LOCK_NAME
            real_load_json = project_bootstrap.load_json_input
            created = False

            def add_control_after_answers(
                raw_path: str,
                label: str,
            ) -> tuple[Path, bytes | None, object | None, list[str]]:
                nonlocal created
                result = real_load_json(raw_path, label)
                if not created and label == "bootstrap answers file":
                    created = True
                    control.write_bytes(b"")
                    control.chmod(0o600)
                return result

            argv = [
                "project_bootstrap.py",
                "--answers",
                str(answers_path),
                "--project-root",
                str(project_root),
                "--runtime",
                "generic",
                "--framework-ref",
                str(REPO_ROOT),
                "--framework-revision-policy",
                "live",
            ]
            with (
                mock.patch.object(sys, "argv", argv),
                mock.patch.object(
                    project_bootstrap,
                    "load_json_input",
                    side_effect=add_control_after_answers,
                ),
                mock.patch.object(
                    project_bootstrap,
                    "existing_instance_bootstrap_errors",
                    side_effect=AssertionError(
                        "collision classification ran after transaction control appeared"
                    ),
                ) as classify,
                mock.patch("sys.stdout", new_callable=io.StringIO) as stdout,
            ):
                result = project_bootstrap.main()

        report = json.loads(stdout.getvalue())
        self.assertTrue(created)
        self.assertEqual(project_bootstrap.EXIT_RECOVERY_REQUIRED, result, report)
        self.assertNotEqual("clean", report["transaction_state"])
        self.assertTrue(report["errors"], report)
        classify.assert_not_called()

    def test_project_bootstrap_retains_instance_receipt_and_refuses_rerender(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "project"
            project_root.mkdir()
            answers_path = root / "answers.json"
            _write_minimal_answers(answers_path)
            initial_result, initial_output = _run_approved_project_bootstrap(
                answers_path,
                project_root,
            )
            self.assertEqual(0, initial_result, initial_output)
            input_path = project_root / "PROJECT_INPUT.json"
            manifest_path = project_root / "PROJECT_INSTANCE.json"
            retained_input = input_path.read_bytes()
            retained_manifest = manifest_path.read_bytes()
            custom_todo = (
                "state_schema_version: 1\n"
                "active_count: 1\n\n"
                "# TODO\n\n"
                "- [ ] TODO-2026-07-10-01 Preserve this live state.\n"
            )
            (project_root / "TODO.md").write_text(custom_todo, encoding="utf-8")
            _write_minimal_answers(
                answers_path,
                project_name="Changed",
            )
            rerender_result, rerender_output = _run_project_bootstrap(
                answers_path,
                project_root,
            )

            rerender_report = json.loads(rerender_output)
            preserved_todo = (project_root / "TODO.md").read_text(encoding="utf-8")
            sow = (project_root / "STATEMENT_OF_WORK.md").read_text(encoding="utf-8")
            input_payload = json.loads(retained_input)
            manifest_payload = json.loads(retained_manifest)
            input_after = input_path.read_bytes()
            manifest_after = manifest_path.read_bytes()

        self.assertEqual(1, rerender_result, rerender_report)
        self.assertTrue(
            any(
                "initial bootstrap cannot overwrite an existing project instance"
                in error
                for error in rerender_report["errors"]
            ),
            rerender_report,
        )
        message = " ".join(rerender_report["errors"])
        self.assertIn("inspect to classify", message)
        self.assertIn(
            "complete current-format retained-input/receipt pair with an intact "
            "recorded preimage may enter refresh planning",
            message,
        )
        self.assertIn("closed transaction-control state", message)
        self.assertIn("exact-ID recovery action", message)
        self.assertIn("reviewed project-specific manual update", message)
        self.assertIn("supporting framework checkout", message)
        self.assertEqual(custom_todo, preserved_todo)
        self.assertIn("Statement of Work — Demo", sow)
        self.assertEqual(retained_input, input_after)
        self.assertEqual(retained_manifest, manifest_after)
        self.assertEqual("Demo", input_payload["answers"]["project_name"])
        self.assertEqual("downstream", manifest_payload["project_kind"])

    def test_root_receipt_blocks_alternate_contract_root_after_entrypoint_loss(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "project"
            project_root.mkdir()
            answers_path = root / "answers.json"
            _write_minimal_answers(answers_path)
            old_contract_root = ".mpa/old"
            new_contract_root = ".mpa/new"

            initial_result, initial_output = _run_approved_project_bootstrap(
                answers_path,
                project_root,
                "--contract-root",
                old_contract_root,
                "--create-contract-root",
            )
            self.assertEqual(0, initial_result, initial_output)
            (project_root / "AGENTS.md").unlink()
            candidate_contract_root = project_root / new_contract_root
            candidate_contract_root.mkdir(parents=True)
            candidate_input = candidate_contract_root / "PROJECT_INPUT.json"
            candidate_input.write_text(
                "unmanaged alternate-root bytes\n",
                encoding="utf-8",
            )
            before = {
                path.relative_to(project_root).as_posix(): path.read_bytes()
                for path in project_root.rglob("*")
                if path.is_file()
            }

            rerender_result, rerender_output = _run_project_bootstrap(
                answers_path,
                project_root,
                "--contract-root",
                new_contract_root,
                "--create-contract-root",
            )
            after = {
                path.relative_to(project_root).as_posix(): path.read_bytes()
                for path in project_root.rglob("*")
                if path.is_file()
            }

        report = json.loads(rerender_output)
        self.assertEqual(1, rerender_result, report)
        self.assertTrue(
            any(
                "root-scoped lifecycle receipt" in error
                and "PROJECT_INSTANCE.json" in error
                for error in report["errors"]
            ),
            report,
        )
        self.assertFalse(
            any(new_contract_root in error for error in report["errors"]),
            report,
        )
        self.assertEqual(before, after)

    def test_project_bootstrap_cli_has_no_update_reset_or_legacy_approval_flags(
        self,
    ) -> None:
        help_text = project_bootstrap.build_parser().format_help()

        self.assertNotIn("--force", help_text)
        self.assertNotIn("--reset-state", help_text)
        self.assertNotIn("--approve-warnings-sha256", help_text)
        self.assertIn("--approve-write-plan-sha256", help_text)

    def test_project_bootstrap_cli_rejects_invalid_layout_topologies_without_writes(self) -> None:
        cases = (
            (
                "downstream requires runtime",
                (),
                "downstream project kind requires --runtime",
            ),
            (
                "framework authoring rejects runtime",
                (
                    "--project-kind",
                    "framework-authoring",
                    "--runtime",
                    "generic",
                    "--contract-root",
                    "contracts/authoring",
                ),
                "framework-authoring project kind must not set --runtime because it preserves the root maintainer entrypoint",
            ),
            (
                "framework authoring requires contract root",
                ("--project-kind", "framework-authoring"),
                "framework-authoring project kind requires --contract-root",
            ),
            (
                "nested contract creation requires confirmation",
                ("--runtime", "generic", "--contract-root", "contracts"),
                "contract root does not exist:",
            ),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for index, (label, extra_arguments, expected_error) in enumerate(cases):
                with self.subTest(label=label):
                    project_root = root / f"project-{index}"
                    project_root.mkdir()
                    answers_path = root / f"answers-{index}.json"
                    _write_minimal_answers(answers_path, date="2026-07-13")
                    before = sorted(
                        path.relative_to(project_root).as_posix()
                        for path in project_root.rglob("*")
                    )
                    arguments = [
                        "project_bootstrap.py",
                        "--answers",
                        str(answers_path),
                        "--project-root",
                        str(project_root),
                        "--framework-ref",
                        "$FRAMEWORK",
                        "--framework-revision-policy",
                        "live",
                        *extra_arguments,
                    ]
                    with (
                        mock.patch.object(sys, "argv", arguments),
                        mock.patch("sys.stdout", new_callable=io.StringIO) as stdout,
                    ):
                        result = project_bootstrap.main()
                    report = json.loads(stdout.getvalue())
                    after = sorted(
                        path.relative_to(project_root).as_posix()
                        for path in project_root.rglob("*")
                    )

                    self.assertEqual(1, result, report)
                    self.assertTrue(
                        any(expected_error in error for error in report["errors"]),
                        report,
                    )
                    self.assertEqual(before, after)

    def test_project_bootstrap_dry_run_requires_existing_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "missing" / "project"
            answers_path = root / "answers.json"
            _write_minimal_answers(answers_path)

            result, output = _run_project_bootstrap(
                answers_path,
                project_root,
                "--dry-run",
            )
            project_root_created = project_root.exists()
            project_parent_created = project_root.parent.exists()

        report = json.loads(output)
        self.assertEqual(1, result, report)
        self.assertTrue(
            any("target project root does not exist" in error for error in report["errors"]),
            report,
        )
        self.assertFalse(project_root_created)
        self.assertFalse(project_parent_created)

    def test_project_bootstrap_dry_run_requires_nested_root_creation_confirmation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "project"
            project_root.mkdir()
            contract_root = project_root / "contracts" / "authoring"
            answers_path = root / "answers.json"
            _write_minimal_answers(answers_path)

            refused_result, refused_output = _run_project_bootstrap(
                answers_path,
                project_root,
                "--contract-root",
                "contracts/authoring",
                "--dry-run",
            )
            accepted_result, accepted_output = _run_project_bootstrap(
                answers_path,
                project_root,
                "--contract-root",
                "contracts/authoring",
                "--create-contract-root",
                "--dry-run",
            )
            contract_root_created = contract_root.exists()

        refused_report = json.loads(refused_output)
        accepted_report = json.loads(accepted_output)
        self.assertEqual(1, refused_result, refused_report)
        self.assertTrue(
            any("contract root does not exist" in error for error in refused_report["errors"]),
            refused_report,
        )
        self.assertEqual(0, accepted_result, accepted_report)
        self.assertFalse(contract_root_created)

    def test_project_bootstrap_requires_the_exact_write_plan_even_without_warnings(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "project"
            project_root.mkdir()
            answers_path = root / "bootstrap_answers.json"
            _write_minimal_answers(answers_path)

            dry_result, dry_output = _run_project_bootstrap_with_warnings(
                answers_path,
                project_root,
                (),
                "--dry-run",
            )
            dry_report = json.loads(dry_output)
            refused_result, refused_output = _run_project_bootstrap_with_warnings(
                answers_path,
                project_root,
                (),
            )
            refused_report = json.loads(refused_output)
            outputs_after_refusal = {
                name: (project_root / name).exists()
                for name in (
                    "AGENTS.md",
                    "AGENT_PROJECT.md",
                    "DECISIONS.md",
                    "STATEMENT_OF_WORK.md",
                    "TODO.md",
                )
            }
            accepted_result, accepted_output = _run_project_bootstrap_with_warnings(
                answers_path,
                project_root,
                (),
                *_write_plan_approval_arguments(dry_report),
            )
            accepted_report = json.loads(accepted_output)
            accepted_output_exists = (project_root / "STATEMENT_OF_WORK.md").is_file()

        self.assertEqual(0, dry_result, dry_report)
        self.assertEqual([], dry_report["warnings"])
        self.assertRegex(dry_report["warnings_sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(dry_report["write_plan_sha256"], r"^[0-9a-f]{64}$")
        self.assertIn("answers_sha256", dry_report)
        self.assertIn("framework_identity", dry_report)
        self.assertIn("rendered_output_digests", dry_report)
        self.assertEqual(1, refused_result, refused_report)
        self.assertEqual(
            dry_report["write_plan_sha256"],
            refused_report["write_plan_sha256"],
        )
        self.assertIn(
            "bootstrap writes require exact rendered-plan approval; rerun the write command with --approve-write-plan-sha256 <write_plan_sha256> after reviewing the dry run",
            refused_report["errors"],
        )
        self.assertEqual({name: False for name in outputs_after_refusal}, outputs_after_refusal)
        self.assertEqual(0, accepted_result, accepted_report)
        self.assertTrue(accepted_output_exists)

    def test_bootstrap_write_plan_approval_rejects_every_material_plan_drift(
        self,
    ) -> None:
        for name in (
            "answers-bytes",
            "setup-profile-bytes",
            "target",
            "warnings",
            "framework-identity",
            "rendered-output",
        ):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                project_root = root / "project-a"
                project_root.mkdir()
                alternate_root = root / "project-b"
                alternate_root.mkdir()
                answers_path = root / "answers.json"
                _write_minimal_answers(answers_path)
                profile_path = root / "profile.json"
                profile_payload = {
                    "schema_version": 1,
                    "defaults": {
                        "dependency_posture": "no-external-dependencies",
                    },
                }
                profile_path.write_text(
                    json.dumps(profile_payload, sort_keys=True),
                    encoding="utf-8",
                )
                profile_arguments = (
                    ("--setup-profile", str(profile_path))
                    if name == "setup-profile-bytes"
                    else ()
                )
                reviewed_warnings = ("reviewed warning",)
                if name == "warnings":
                    dry_result, dry_output = _run_project_bootstrap_with_warnings(
                        answers_path,
                        project_root,
                        reviewed_warnings,
                        *profile_arguments,
                        "--dry-run",
                    )
                else:
                    dry_result, dry_output = _run_project_bootstrap(
                        answers_path,
                        project_root,
                        *profile_arguments,
                        "--dry-run",
                    )
                dry_report = json.loads(dry_output)
                self.assertEqual(0, dry_result, dry_report)
                approval = _write_plan_approval_arguments(dry_report)

                write_root = project_root
                warning_sequence = reviewed_warnings
                render_patch: object | None = None
                identity_patch: object | None = None
                if name == "answers-bytes":
                    answers_path.write_text(
                        json.dumps(
                            {
                                "bootstrap_mode": "minimal",
                                "agent": "Agent",
                                "project_name": "Demo",
                                "framework_verification_runner": TEST_FRAMEWORK_RUNNER,
                            },
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                elif name == "setup-profile-bytes":
                    profile_path.write_text(
                        json.dumps(profile_payload, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                elif name == "target":
                    write_root = alternate_root
                elif name == "warnings":
                    warning_sequence = ("changed warning",)
                elif name == "framework-identity":
                    identity = project_bootstrap.capture_framework_identity(REPO_ROOT)
                    changed_identity = project_bootstrap.FrameworkIdentity(
                        content_sha256="0" * 64,
                        effective_file_digests=identity.effective_file_digests,
                        distribution_sha256=identity.distribution_sha256,
                    )
                    identity_patch = mock.patch.object(
                        project_bootstrap,
                        "capture_framework_identity",
                        return_value=changed_identity,
                    )
                elif name == "rendered-output":
                    real_render = project_bootstrap.render_bootstrap_write_outputs

                    def render_changed_output(*args: Any, **kwargs: Any) -> dict[str, str]:
                        rendered = real_render(*args, **kwargs)
                        first = next(iter(rendered))
                        rendered[first] += "\nplan-drift fixture\n"
                        return rendered

                    render_patch = mock.patch.object(
                        project_bootstrap,
                        "render_bootstrap_write_outputs",
                        side_effect=render_changed_output,
                    )

                with ExitStack() as stack:
                    if identity_patch is not None:
                        stack.enter_context(cast(Any, identity_patch))
                    if render_patch is not None:
                        stack.enter_context(cast(Any, render_patch))
                    writer = stack.enter_context(
                        mock.patch.object(
                            project_bootstrap,
                            "write_bootstrap_outputs",
                            side_effect=AssertionError(
                                "writer called for stale plan approval"
                            ),
                        )
                    )
                    if name == "warnings":
                        write_result, write_output = _run_project_bootstrap_with_warnings(
                            answers_path,
                            write_root,
                            warning_sequence,
                            *profile_arguments,
                            *approval,
                        )
                    else:
                        write_result, write_output = _run_project_bootstrap(
                            answers_path,
                            write_root,
                            *profile_arguments,
                            *approval,
                        )
                write_report = json.loads(write_output)

                self.assertEqual(1, write_result, write_report)
                self.assertNotEqual(
                    dry_report["write_plan_sha256"],
                    write_report["write_plan_sha256"],
                )
                self.assertTrue(
                    any(
                        "does not match the complete rendered" in error
                        for error in write_report["errors"]
                    ),
                    write_report,
                )
                writer.assert_not_called()

    def test_bootstrap_write_plan_rejects_invalid_or_dry_run_approvals_before_write(
        self,
    ) -> None:
        for name, approval_builder, dry_run, expected_error in (
            (
                "missing",
                lambda digest: (),
                False,
                "require exact rendered-plan approval",
            ),
            (
                "malformed",
                lambda digest: ("--approve-write-plan-sha256", "bad"),
                False,
                "64 lowercase hexadecimal",
            ),
            (
                "unknown",
                lambda digest: ("--approve-write-plan-sha256", "0" * 64),
                False,
                "does not match the complete rendered",
            ),
            (
                "repeated",
                lambda digest: (
                    "--approve-write-plan-sha256",
                    digest,
                    "--approve-write-plan-sha256",
                    digest,
                ),
                False,
                "supplied exactly once",
            ),
            (
                "dry-run",
                lambda digest: ("--approve-write-plan-sha256", digest),
                True,
                "valid only on the write command",
            ),
        ):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                project_root = root / "project"
                project_root.mkdir()
                answers_path = root / "answers.json"
                _write_minimal_answers(answers_path)
                dry_result, dry_output = _run_project_bootstrap_with_warnings(
                    answers_path,
                    project_root,
                    (),
                    "--dry-run",
                )
                dry_report = json.loads(dry_output)
                with mock.patch.object(
                    project_bootstrap,
                    "write_bootstrap_outputs",
                    side_effect=AssertionError("writer called for invalid approval"),
                ) as writer:
                    write_result, write_output = _run_project_bootstrap_with_warnings(
                        answers_path,
                        project_root,
                        (),
                        *approval_builder(cast(str, dry_report["write_plan_sha256"])),
                        *(("--dry-run",) if dry_run else ()),
                    )
                write_report = json.loads(write_output)

            self.assertEqual(0, dry_result, dry_report)
            self.assertEqual(1, write_result, write_report)
            self.assertTrue(
                any(expected_error in error for error in write_report["errors"]),
                write_report,
            )
            writer.assert_not_called()

    def test_project_bootstrap_refuses_existing_mutable_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "project"
            project_root.mkdir()
            (project_root / "TODO.md").write_text("# Existing state\n", encoding="utf-8")
            answers_path = root / "answers.json"
            _write_minimal_answers(answers_path)
            result, output = _run_project_bootstrap(
                answers_path,
                project_root,
            )
            sow_exists = (project_root / "STATEMENT_OF_WORK.md").exists()

        report = json.loads(output)
        self.assertEqual(1, result)
        self.assertTrue(
            any(
                "initial bootstrap is create-only and cannot overwrite or reconstruct existing project surfaces"
                in error
                and "TODO.md" in error
                for error in report["errors"]
            ),
            report,
        )
        self.assertFalse(sow_exists)

    def test_project_bootstrap_rejects_existing_project_surfaces(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "project"
            project_root.mkdir()
            answers_path = root / "answers.json"
            _write_minimal_answers(answers_path)
            sow_path = project_root / "STATEMENT_OF_WORK.md"
            sow_path.write_text("sentinel\n", encoding="utf-8")
            (project_root / "AGENT_PROJECT.md").mkdir()
            result, output = _run_project_bootstrap(
                answers_path,
                project_root,
            )
            report = json.loads(output)
            preserved_sow = sow_path.read_text(encoding="utf-8")
            preserved_directory = (project_root / "AGENT_PROJECT.md").is_dir()

        self.assertEqual(1, result)
        self.assertTrue(
            any(
                "initial bootstrap is create-only and cannot overwrite or reconstruct existing project surfaces"
                in error
                for error in report["errors"]
            ),
            report,
        )
        self.assertEqual("sentinel\n", preserved_sow)
        self.assertTrue(preserved_directory)

    def test_project_bootstrap_transaction_stages_every_output_before_install(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / "project"
            project_root.mkdir()
            first = project_root / "first.md"
            second = project_root / "second.md"
            first.write_text("old first\n", encoding="utf-8")
            second.write_text("old second\n", encoding="utf-8")
            real_write = bootstrap_transaction.os.write

            def fail_late_stage_write(descriptor: int, payload: bytes) -> int:
                if bytes(payload) == b"new second\n":
                    raise OSError("injected late staging failure")
                return real_write(descriptor, payload)

            with (
                mock.patch.object(
                    bootstrap_transaction.os,
                    "write",
                    side_effect=fail_late_stage_write,
                ),
                self.assertRaisesRegex(
                    bootstrap_transaction.BootstrapTransactionError,
                    "injected late staging failure",
                ),
            ):
                bootstrap_transaction.transactional_write_outputs(
                    project_root,
                    [("first.md", "new first\n"), ("second.md", "new second\n")],
                    force=True,
                )

            self.assertEqual("old first\n", first.read_text(encoding="utf-8"))
            self.assertEqual("old second\n", second.read_text(encoding="utf-8"))
            self.assertEqual(
                [],
                list(project_root.rglob(".mpa-bootstrap-transaction-*")),
            )

    def test_project_bootstrap_transaction_requires_existing_root_without_mutation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            parent = Path(temp_dir)
            sentinel = parent / "sentinel.bin"
            sentinel.write_bytes(b"preserve\x00me\n")
            sentinel.chmod(0o640)
            project_root = parent / "new" / "project"
            before = (sentinel.read_bytes(), sentinel.stat().st_mode & 0o777)

            with self.assertRaisesRegex(
                bootstrap_transaction.BootstrapTransactionError,
                "target project root does not exist",
            ):
                bootstrap_transaction.transactional_write_outputs(
                    project_root,
                    [("nested/first.md", "new first\n")],
                    force=False,
                )

            self.assertFalse(project_root.exists())
            self.assertFalse((parent / "new").exists())
            self.assertEqual(
                before,
                (sentinel.read_bytes(), sentinel.stat().st_mode & 0o777),
            )
            self.assertEqual(["sentinel.bin"], [path.name for path in parent.iterdir()])

    def test_transaction_rejects_hardlinked_replacement_preimage(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            output = project_root / "STATEMENT_OF_WORK.md"
            alias = project_root / "shared-alias.md"
            original = b"sentinel\x00bytes\n"
            output.write_bytes(original)
            os.link(output, alias)

            with self.assertRaisesRegex(
                bootstrap_transaction.BootstrapTransactionError,
                "must have exactly one hard link",
            ):
                bootstrap_transaction.transactional_write_outputs(
                    project_root,
                    [("STATEMENT_OF_WORK.md", "replacement\n")],
                    force=True,
                )

            self.assertEqual(original, output.read_bytes())
            self.assertEqual(original, alias.read_bytes())
            self.assertEqual(
                ["STATEMENT_OF_WORK.md", "shared-alias.md"],
                sorted(path.name for path in project_root.iterdir()),
            )

    def test_project_bootstrap_transaction_rolls_back_late_install_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / "project"
            project_root.mkdir()
            first = project_root / "first.md"
            second = project_root / "second.md"
            first.write_text("old first\n", encoding="utf-8")
            second.write_text("old second\n", encoding="utf-8")
            real_link = bootstrap_transaction.os.link

            def fail_second_install(
                source: str,
                destination: str,
                *,
                src_dir_fd: int | None = None,
                dst_dir_fd: int | None = None,
            ) -> None:
                if source == "stage-1":
                    raise OSError("injected late install failure")
                real_link(
                    source,
                    destination,
                    src_dir_fd=src_dir_fd,
                    dst_dir_fd=dst_dir_fd,
                )

            with (
                mock.patch.object(
                    bootstrap_transaction.os,
                    "link",
                    side_effect=fail_second_install,
                ),
                self.assertRaisesRegex(
                    bootstrap_transaction.BootstrapTransactionError,
                    "injected late install failure",
                ),
            ):
                bootstrap_transaction.transactional_write_outputs(
                    project_root,
                    [("first.md", "new first\n"), ("second.md", "new second\n")],
                    force=True,
                )

            self.assertEqual("old first\n", first.read_text(encoding="utf-8"))
            self.assertEqual("old second\n", second.read_text(encoding="utf-8"))
            self.assertEqual(
                [],
                list(project_root.rglob(".mpa-bootstrap-transaction-*")),
            )

    def test_project_bootstrap_transaction_rolls_back_new_output_and_parent_after_late_install_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / "project"
            project_root.mkdir()
            existing = project_root / "existing.md"
            existing.write_text("old existing\n", encoding="utf-8")
            real_link = bootstrap_transaction.os.link

            def fail_second_install(
                source: str,
                destination: str,
                *,
                src_dir_fd: int | None = None,
                dst_dir_fd: int | None = None,
            ) -> None:
                if source == "stage-1":
                    raise OSError("injected late install failure after new output")
                real_link(
                    source,
                    destination,
                    src_dir_fd=src_dir_fd,
                    dst_dir_fd=dst_dir_fd,
                )

            with (
                mock.patch.object(
                    bootstrap_transaction.os,
                    "link",
                    side_effect=fail_second_install,
                ),
                self.assertRaisesRegex(
                    bootstrap_transaction.BootstrapTransactionError,
                    "injected late install failure after new output",
                ),
            ):
                bootstrap_transaction.transactional_write_outputs(
                    project_root,
                    [
                        ("new-parent/new.md", "new output\n"),
                        ("existing.md", "new existing\n"),
                    ],
                    force=True,
                )

            self.assertFalse((project_root / "new-parent").exists())
            self.assertEqual("old existing\n", existing.read_text(encoding="utf-8"))
            self.assertEqual(
                [],
                list(project_root.rglob(".mpa-bootstrap-transaction-*")),
            )

    def test_project_bootstrap_transaction_successful_force_preserves_existing_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / "project"
            project_root.mkdir()
            target = project_root / "restricted.md"
            target.write_text("old\n", encoding="utf-8")
            target.chmod(0o640)

            result = bootstrap_transaction.transactional_write_outputs(
                project_root,
                [("restricted.md", "new\n")],
                force=True,
                create_file_mode=0o600,
                create_directory_mode=0o700,
            )
            installed = target.read_text(encoding="utf-8")
            installed_mode = target.stat().st_mode & 0o777
            lock_exists = (
                project_root / bootstrap_transaction.TRANSACTION_LOCK_NAME
            ).exists()

        self.assertEqual(["restricted.md"], result.written)
        self.assertEqual("new\n", installed)
        self.assertEqual(0o640, installed_mode)
        self.assertFalse(lock_exists)

    def test_project_bootstrap_target_modes_apply_exactly_per_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / "project"
            project_root.mkdir()
            existing = project_root / "existing.md"
            created = project_root / "created.md"
            existing.write_text("old\n", encoding="utf-8")
            existing.chmod(0o640)

            result = bootstrap_transaction.transactional_write_outputs(
                project_root,
                [
                    ("existing.md", "new existing\n"),
                    ("created.md", "new created\n"),
                ],
                force=True,
                target_modes={
                    "existing.md": 0o750,
                    "created.md": 0o440,
                },
            )

            self.assertEqual(["existing.md", "created.md"], result.written)
            self.assertEqual("new existing\n", existing.read_text(encoding="utf-8"))
            self.assertEqual("new created\n", created.read_text(encoding="utf-8"))
            self.assertEqual(0o750, existing.stat().st_mode & 0o777)
            self.assertEqual(0o440, created.stat().st_mode & 0o777)
            self.assertEqual([], result.cleanup_warnings)

    def test_project_bootstrap_explicit_create_modes_secure_new_nested_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / "project"
            project_root.mkdir()
            project_root.chmod(0o750)
            target = project_root / "private" / "backout" / "original.md"
            sensitive_output = "private" + "/backout/original.md"

            result = bootstrap_transaction.transactional_write_outputs(
                project_root,
                [(sensitive_output, "sensitive preimage\n")],
                force=False,
                create_file_mode=0o600,
                create_directory_mode=0o700,
            )

            modes = {
                path: path.stat().st_mode & 0o777
                for path in (
                    project_root,
                    project_root / "private",
                    project_root / "private" / "backout",
                    target,
                )
            }
            installed = target.read_text(encoding="utf-8")

        self.assertEqual([sensitive_output], result.written)
        self.assertEqual("sensitive preimage\n", installed)
        self.assertEqual(0o750, modes[project_root])
        self.assertEqual(0o700, modes[project_root / "private"])
        self.assertEqual(0o700, modes[project_root / "private" / "backout"])
        self.assertEqual(0o600, modes[target])

    def test_project_bootstrap_default_create_modes_remain_umask_governed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / "project"
            project_root.mkdir()
            target = project_root / "nested" / "output.md"
            previous_umask = os.umask(0o027)
            try:
                bootstrap_transaction.transactional_write_outputs(
                    project_root,
                    [("nested/output.md", "ordinary output\n")],
                    force=False,
                )
            finally:
                os.umask(previous_umask)
            directory_mode = target.parent.stat().st_mode & 0o777
            file_mode = target.stat().st_mode & 0o777

        self.assertEqual(0o750, directory_mode)
        self.assertEqual(0o640, file_mode)

    def test_transaction_retires_only_the_exact_empty_directory_forest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            target = project_root / ".agents" / "skills" / "seo" / "SKILL.md"
            target.parent.mkdir(parents=True)
            target.write_text("managed wrapper\n", encoding="utf-8")

            result = bootstrap_transaction.transactional_write_outputs(
                project_root,
                [],
                force=True,
                remove_outputs=[".agents/skills/seo/SKILL.md"],
                retire_empty_directories=[
                    ".agents",
                    ".agents/skills",
                    ".agents/skills/seo",
                ],
            )

            self.assertEqual([], result.written)
            self.assertEqual([".agents/skills/seo/SKILL.md"], result.removed)
            self.assertEqual([], result.cleanup_warnings)
            self.assertFalse((project_root / ".agents").exists())
            self.assertEqual([], list(project_root.iterdir()))

    def test_transaction_rejects_unlisted_retirement_sibling_before_mutation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            target = project_root / ".agents" / "skills" / "seo" / "SKILL.md"
            target.parent.mkdir(parents=True)
            target.write_text("managed wrapper\n", encoding="utf-8")
            sibling = project_root / ".agents" / "owner-note.txt"
            sibling.write_text("preserve\n", encoding="utf-8")

            with self.assertRaisesRegex(
                bootstrap_transaction.BootstrapTransactionError,
                "exceed the approved topology",
            ):
                bootstrap_transaction.transactional_write_outputs(
                    project_root,
                    [],
                    force=True,
                    remove_outputs=[".agents/skills/seo/SKILL.md"],
                    retire_empty_directories=[
                        ".agents",
                        ".agents/skills",
                        ".agents/skills/seo",
                    ],
                )

            self.assertEqual("managed wrapper\n", target.read_text(encoding="utf-8"))
            self.assertEqual("preserve\n", sibling.read_text(encoding="utf-8"))
            self.assertFalse(
                (project_root / bootstrap_transaction.RECOVERY_JOURNAL_NAME).exists()
            )
            self.assertFalse(
                (project_root / bootstrap_transaction.TRANSACTION_LOCK_NAME).exists()
            )

    def test_transaction_rejects_retirement_mode_drift_before_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            target = project_root / ".agents" / "skills" / "seo" / "SKILL.md"
            target.parent.mkdir(parents=True)
            target.write_text("managed wrapper\n", encoding="utf-8")
            retirement_paths = (
                ".agents",
                ".agents/skills",
                ".agents/skills/seo",
            )
            retirement_modes = {
                path: (project_root / path).stat().st_mode & 0o777
                for path in retirement_paths
            }
            original_verify = bootstrap_transaction._verify_retirement_inventory
            verify_calls = 0

            def drift_before_repeat_check(
                bindings: object,
                expected_children: object,
                expected_modes: object = None,
            ) -> None:
                nonlocal verify_calls
                verify_calls += 1
                if verify_calls == 2:
                    original_mode = target.parent.stat().st_mode & 0o777
                    target.parent.chmod(0o700 if original_mode != 0o700 else 0o750)
                original_verify(
                    cast(Any, bindings),
                    cast(Any, expected_children),
                    cast(Any, expected_modes),
                )

            with (
                mock.patch.object(
                    bootstrap_transaction,
                    "_verify_retirement_inventory",
                    side_effect=drift_before_repeat_check,
                ),
                self.assertRaisesRegex(
                    bootstrap_transaction.BootstrapTransactionError,
                    "retired bootstrap directory mode changed",
                ),
            ):
                bootstrap_transaction.transactional_write_outputs(
                    project_root,
                    [],
                    force=True,
                    remove_outputs=[".agents/skills/seo/SKILL.md"],
                    retire_empty_directories=list(retirement_paths),
                    retired_directory_modes=retirement_modes,
                )

            self.assertEqual(2, verify_calls)
            self.assertEqual("managed wrapper\n", target.read_text(encoding="utf-8"))
            self.assertFalse(
                (project_root / bootstrap_transaction.RECOVERY_JOURNAL_NAME).exists()
            )
            self.assertFalse(
                (project_root / bootstrap_transaction.TRANSACTION_LOCK_NAME).exists()
            )

    def test_transaction_rollback_restores_files_without_retiring_parents(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            target = project_root / ".agents" / "skills" / "seo" / "SKILL.md"
            target.parent.mkdir(parents=True)
            target.write_text("managed wrapper\n", encoding="utf-8")

            def reject_installed_project() -> None:
                raise RuntimeError("injected verification failure")

            with self.assertRaisesRegex(
                bootstrap_transaction.BootstrapTransactionError,
                "injected verification failure",
            ):
                bootstrap_transaction.transactional_write_outputs(
                    project_root,
                    [],
                    force=True,
                    remove_outputs=[".agents/skills/seo/SKILL.md"],
                    retire_empty_directories=[
                        ".agents",
                        ".agents/skills",
                        ".agents/skills/seo",
                    ],
                    post_install_verifier=reject_installed_project,
                )

            self.assertEqual("managed wrapper\n", target.read_text(encoding="utf-8"))
            self.assertTrue(target.parent.is_dir())
            self.assertTrue(target.parent.parent.is_dir())
            self.assertTrue(target.parent.parent.parent.is_dir())
            self.assertFalse(
                (project_root / bootstrap_transaction.RECOVERY_JOURNAL_NAME).exists()
            )

    def test_project_bootstrap_rejects_unsafe_create_modes_before_mutation(self) -> None:
        invalid_file_modes: tuple[tuple[object, str], ...] = (
            (True, "integer from 0 through 511"),
            (0o666, "group or world write access"),
            (0o700, "must not grant execute access"),
            (0o400, "owner read and write access"),
        )
        invalid_directory_modes: tuple[tuple[object, str], ...] = (
            (False, "integer from 0 through 511"),
            (0o777, "group or world write access"),
            (0o600, "owner read, write, and execute access"),
            (0o1000, "integer from 0 through 511"),
        )
        sensitive_output = "private" + "/original.md"
        with tempfile.TemporaryDirectory() as temp_dir:
            for index, (mode, message) in enumerate(invalid_file_modes):
                with self.subTest(kind="file", mode=mode):
                    project_root = Path(temp_dir) / f"file-mode-{index}"
                    project_root.mkdir()
                    with self.assertRaisesRegex(ValueError, message):
                        bootstrap_transaction.transactional_write_outputs(
                            project_root,
                            [(sensitive_output, "sensitive preimage\n")],
                            force=False,
                            create_file_mode=cast(int, mode),
                            create_directory_mode=0o700,
                        )
                    self.assertEqual([], list(project_root.iterdir()))
            for index, (mode, message) in enumerate(invalid_directory_modes):
                with self.subTest(kind="directory", mode=mode):
                    project_root = Path(temp_dir) / f"directory-mode-{index}"
                    project_root.mkdir()
                    with self.assertRaisesRegex(ValueError, message):
                        bootstrap_transaction.transactional_write_outputs(
                            project_root,
                            [(sensitive_output, "sensitive preimage\n")],
                            force=False,
                            create_file_mode=0o600,
                            create_directory_mode=cast(int, mode),
                        )
                    self.assertEqual([], list(project_root.iterdir()))

    def test_project_bootstrap_invalid_transaction_contracts_change_nothing(self) -> None:
        digest = hashlib.sha256(b"old\n").hexdigest()
        cases: tuple[tuple[str, dict[str, object], str], ...] = (
            (
                "missing expected preimage",
                {
                    "ordered_outputs": [("first.md", "new\n"), ("second.md", "new\n")],
                    "expected_preimages": {"first.md": digest},
                },
                "exactly cover",
            ),
            (
                "unexpected expected preimage",
                {
                    "ordered_outputs": [("first.md", "new\n")],
                    "expected_preimages": {"first.md": digest, "extra.md": None},
                },
                "exactly cover",
            ),
            (
                "invalid expected digest",
                {
                    "ordered_outputs": [("first.md", "new\n")],
                    "expected_preimages": {"first.md": "not-a-digest"},
                },
                "one lowercase SHA-256 digest",
            ),
            (
                "missing expected preimage mode",
                {
                    "ordered_outputs": [("first.md", "new\n")],
                    "expected_preimages": {"first.md": digest},
                    "expected_preimage_modes": {},
                },
                "must exactly cover its companion path set",
            ),
            (
                "present expected preimage with absent mode",
                {
                    "ordered_outputs": [("first.md", "new\n")],
                    "expected_preimages": {"first.md": digest},
                    "expected_preimage_modes": {"first.md": None},
                },
                "must use null exactly for an absent preimage",
            ),
            (
                "absent expected preimage with present mode",
                {
                    "ordered_outputs": [("first.md", "new\n")],
                    "expected_preimages": {"first.md": None},
                    "expected_preimage_modes": {"first.md": 0o600},
                },
                "must use null exactly for an absent preimage",
            ),
            (
                "assertion overlap",
                {
                    "ordered_outputs": [("first.md", "new\n")],
                    "assert_preimages": {"first.md": digest},
                },
                "must be disjoint",
            ),
            (
                "invalid asserted digest",
                {
                    "ordered_outputs": [("first.md", "new\n")],
                    "assert_preimages": {"sentinel.bin": "not-a-digest"},
                },
                "one lowercase SHA-256 digest",
            ),
            (
                "invalid asserted mode",
                {
                    "ordered_outputs": [("first.md", "new\n")],
                    "assert_preimages": {"sentinel.bin": digest},
                    "assert_preimage_modes": {"sentinel.bin": True},
                },
                "integer from 0 through 511",
            ),
            (
                "missing target mode",
                {
                    "ordered_outputs": [("first.md", "new\n")],
                    "target_modes": {},
                },
                "must exactly cover its companion path set",
            ),
            (
                "invalid target mode",
                {
                    "ordered_outputs": [("first.md", "new\n")],
                    "target_modes": {"first.md": 0o1000},
                },
                "integer from 0 through 511",
            ),
            (
                "reserved write",
                {"ordered_outputs": [(".mpa-bootstrap.lock", "new\n")]},
                "reserved transaction path",
            ),
            (
                "reserved removal",
                {
                    "ordered_outputs": [],
                    "remove_outputs": [".mpa-bootstrap-recovery.json"],
                },
                "reserved transaction path",
            ),
            (
                "reserved assertion",
                {
                    "ordered_outputs": [("first.md", "new\n")],
                    "assert_preimages": {
                        ".mpa-bootstrap-transaction-deadbeef": digest
                    },
                },
                "reserved transaction path",
            ),
            (
                "ancestor collision",
                {
                    "ordered_outputs": [
                        ("nested", "new\n"),
                        ("nested/child.md", "new\n"),
                    ]
                },
                "cannot be ancestors",
            ),
            (
                "retirement without removal",
                {
                    "ordered_outputs": [("first.md", "new\n")],
                    "retire_empty_directories": ["nested"],
                },
                "requires at least one planned removal",
            ),
            (
                "write beneath retirement",
                {
                    "ordered_outputs": [("nested/new.md", "new\n")],
                    "remove_outputs": ["nested/old.md"],
                    "retire_empty_directories": ["nested"],
                },
                "contains a planned write",
            ),
            (
                "unnamed intervening retirement directory",
                {
                    "ordered_outputs": [],
                    "remove_outputs": ["nested/deeper/old.md"],
                    "retire_empty_directories": ["nested"],
                },
                "must name every intervening directory",
            ),
            (
                "missing retired directory mode",
                {
                    "ordered_outputs": [],
                    "remove_outputs": ["nested/old.md"],
                    "retire_empty_directories": ["nested"],
                    "retired_directory_modes": {},
                },
                "must exactly cover its companion path set",
            ),
            (
                "reserved retirement",
                {
                    "ordered_outputs": [],
                    "remove_outputs": ["nested/old.md"],
                    "retire_empty_directories": [
                        ".mpa-bootstrap-transaction-deadbeef"
                    ],
                },
                "reserved transaction path",
            ),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            for index, (label, arguments, message) in enumerate(cases):
                with self.subTest(label=label):
                    project_root = base / f"case-{index}"
                    project_root.mkdir()
                    sentinel = project_root / "sentinel.bin"
                    sentinel.write_bytes(b"preserve\x00me\n")
                    sentinel.chmod(0o640)
                    before = (
                        tuple(path.name for path in project_root.iterdir()),
                        sentinel.read_bytes(),
                        sentinel.stat().st_mode & 0o777,
                    )
                    call_arguments: Any = dict(arguments)
                    ordered_outputs = call_arguments.pop("ordered_outputs")
                    with self.assertRaisesRegex(ValueError, message):
                        bootstrap_transaction.transactional_write_outputs(
                            project_root,
                            cast(list[tuple[str, str]], ordered_outputs),
                            force=True,
                            **call_arguments,
                        )
                    after = (
                        tuple(path.name for path in project_root.iterdir()),
                        sentinel.read_bytes(),
                        sentinel.stat().st_mode & 0o777,
                    )
                    self.assertEqual(before, after)

    def test_project_bootstrap_journal_bounds_reject_without_orphan_controls(self) -> None:
        def payload(operation_count: int) -> dict[str, object]:
            return {
                "schema_version": bootstrap_transaction.RECOVERY_JOURNAL_SCHEMA_VERSION,
                "transaction_id": "a" * 32,
                "phase": "preparing",
                "applied_count": 0,
                "created_directories": [],
                "retired_directories": [],
                "operations": [
                    {
                        "path": f"file-{index}.md",
                        "action": "write",
                        "transaction_directory": (
                            ".mpa-bootstrap-transaction-" + "b" * 32
                        ),
                        "stage_name": f"stage-{index}",
                        "backup_name": None,
                        "original": None,
                        "candidate": {
                            "sha256": hashlib.sha256(b"x").hexdigest(),
                            "mode": None,
                            "size": 1,
                        },
                    }
                    for index in range(operation_count)
                ],
            }

        with mock.patch.object(
            bootstrap_transaction,
            "_RECOVERY_JOURNAL_MAX_OPERATIONS",
            2,
        ):
            self.assertFalse(
                any(
                    "operation limit" in error
                    for error in bootstrap_transaction._validate_journal_payload(
                        payload(2)
                    )
                )
            )
            self.assertTrue(
                any(
                    "operation limit" in error
                    for error in bootstrap_transaction._validate_journal_payload(
                        payload(3)
                    )
                )
            )

        exact_payload = payload(1)
        exact_size = len(bootstrap_transaction._journal_bytes(exact_payload))
        with mock.patch.object(
            bootstrap_transaction,
            "_RECOVERY_JOURNAL_MAX_BYTES",
            exact_size,
        ):
            self.assertFalse(bootstrap_transaction._validate_journal_payload(exact_payload))
        with mock.patch.object(
            bootstrap_transaction,
            "_RECOVERY_JOURNAL_MAX_BYTES",
            exact_size - 1,
        ):
            self.assertTrue(
                any(
                    "byte limit" in error
                    for error in bootstrap_transaction._validate_journal_payload(
                        exact_payload
                    )
                )
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / "project"
            project_root.mkdir()
            sentinel = project_root / "sentinel.bin"
            sentinel.write_bytes(b"preserve\n")
            for label, patched_name, patched_limit, outputs in (
                (
                    "operations",
                    "_RECOVERY_JOURNAL_MAX_OPERATIONS",
                    2,
                    [(f"nested/file-{index}.md", "x") for index in range(3)],
                ),
                (
                    "bytes",
                    "_RECOVERY_JOURNAL_MAX_BYTES",
                    1,
                    [("nested/file.md", "x")],
                ),
            ):
                with self.subTest(bound=label), mock.patch.object(
                    bootstrap_transaction,
                    patched_name,
                    patched_limit,
                ), self.assertRaisesRegex(
                    bootstrap_transaction.BootstrapTransactionError,
                    "bounded operation limit|byte limit",
                ):
                    bootstrap_transaction.transactional_write_outputs(
                        project_root,
                        outputs,
                        force=False,
                    )
                self.assertEqual(b"preserve\n", sentinel.read_bytes())
                self.assertEqual(["sentinel.bin"], [path.name for path in project_root.iterdir()])

    def test_project_bootstrap_all_journal_phases_match_the_closed_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / "project"
            retired_target = (
                project_root / ".agents" / "skills" / "seo" / "SKILL.md"
            )
            retired_target.parent.mkdir(parents=True)
            retired_target.write_text("managed wrapper\n", encoding="utf-8")
            captured_payloads: list[dict[str, object]] = []
            real_write_journal = bootstrap_transaction._write_recovery_journal

            def capture_write(
                root: Any,
                payload: dict[str, object],
                *,
                require_absent: bool,
            ) -> None:
                captured_payloads.append(
                    cast(
                        dict[str, object],
                        json.loads(
                            bootstrap_transaction._journal_bytes(payload).decode(
                                "utf-8"
                            )
                        ),
                    )
                )
                real_write_journal(
                    root,
                    payload,
                    require_absent=require_absent,
                )

            with mock.patch.object(
                bootstrap_transaction,
                "_write_recovery_journal",
                side_effect=capture_write,
            ):
                result = bootstrap_transaction.transactional_write_outputs(
                    project_root,
                    [("generated/nested/output.md", "new output\n")],
                    force=True,
                    remove_outputs=[".agents/skills/seo/SKILL.md"],
                    retire_empty_directories=[
                        ".agents",
                        ".agents/skills",
                        ".agents/skills/seo",
                    ],
                )

        self.assertEqual(["generated/nested/output.md"], result.written)
        self.assertEqual([".agents/skills/seo/SKILL.md"], result.removed)
        self.assertEqual([], result.cleanup_warnings)
        self.assertGreaterEqual(len(captured_payloads), 4)
        phases = [payload["phase"] for payload in captured_payloads]
        self.assertEqual(
            ["preparing", "prepared", "applying", "verified"],
            list(dict.fromkeys(phases)),
        )
        for payload in captured_payloads:
            self.assertEqual(
                bootstrap_transaction._RECOVERY_JOURNAL_KEYS,
                set(payload),
            )
            self.assertEqual(
                [],
                bootstrap_transaction._validate_journal_payload(payload),
                payload,
            )

        retired_snapshots = [
            payload["retired_directories"] for payload in captured_payloads
        ]
        self.assertTrue(
            all(snapshot == retired_snapshots[0] for snapshot in retired_snapshots)
        )
        self.assertEqual(
            [".agents", ".agents/skills", ".agents/skills/seo"],
            [
                entry["path"]
                for entry in cast(
                    list[dict[str, object]],
                    retired_snapshots[0],
                )
            ],
        )
        self.assertTrue(
            all(
                isinstance(entry["identity"], list)
                for entry in cast(list[dict[str, object]], retired_snapshots[0])
            )
        )

        preparing_payloads = [
            payload for payload in captured_payloads if payload["phase"] == "preparing"
        ]
        self.assertGreaterEqual(len(preparing_payloads), 2)
        first_created = cast(
            list[dict[str, object]],
            preparing_payloads[0]["created_directories"],
        )
        last_preparing_created = cast(
            list[dict[str, object]],
            preparing_payloads[-1]["created_directories"],
        )
        self.assertEqual(
            ["generated", "generated/nested"],
            [entry["path"] for entry in first_created],
        )
        self.assertTrue(all(entry["identity"] is None for entry in first_created))
        self.assertTrue(
            all(isinstance(entry["identity"], list) for entry in last_preparing_created)
        )

    def test_project_bootstrap_clean_recovery_status_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / "project"
            project_root.mkdir()

            status = bootstrap_transaction.transaction_recovery_status(project_root)

            self.assertEqual("clean", status.state, status)
            self.assertEqual([], list(project_root.iterdir()))

    def test_project_bootstrap_temporary_journal_only_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / "project"
            project_root.mkdir()
            temporary = (
                project_root / bootstrap_transaction._RECOVERY_JOURNAL_TEMP_NAME
            )
            original = b"partial journal\x00bytes\n"
            temporary.write_bytes(original)
            temporary.chmod(0o600)

            status = bootstrap_transaction.transaction_recovery_status(project_root)
            with self.assertRaisesRegex(
                bootstrap_transaction.BootstrapTransactionError,
                "requires inspection",
            ):
                bootstrap_transaction.transactional_write_outputs(
                    project_root,
                    [("first.md", "new first\n")],
                    force=False,
                )

            self.assertEqual("invalid", status.state, status)
            self.assertTrue(
                any("without a canonical journal" in error for error in status.errors),
                status,
            )
            self.assertEqual(original, temporary.read_bytes())
            self.assertEqual(0o600, temporary.stat().st_mode & 0o777)
            self.assertEqual(
                [bootstrap_transaction._RECOVERY_JOURNAL_TEMP_NAME],
                [path.name for path in project_root.iterdir()],
            )

    def test_project_bootstrap_initialization_cleanup_rejects_transaction_artifacts(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / "project"
            project_root.mkdir()
            lock = project_root / bootstrap_transaction.TRANSACTION_LOCK_NAME
            lock.write_bytes(b"")
            lock.chmod(0o600)
            artifact = (
                project_root
                / "nested"
                / (".mpa-bootstrap-transaction-" + "a" * 32)
            )
            artifact.mkdir(parents=True)

            status = bootstrap_transaction.transaction_recovery_status(project_root)

            self.assertEqual("invalid", status.state, status)
            self.assertFalse(status.can_rollback, status)
            self.assertTrue(
                any("transaction artifacts" in error for error in status.errors),
                status,
            )
            transaction_id = status.transaction_id
            if transaction_id is None:
                self.fail("initialization inspection omitted its exact lock identity")
            with self.assertRaisesRegex(
                bootstrap_transaction.BootstrapTransactionError,
                "transaction artifacts",
            ):
                bootstrap_transaction.rollback_interrupted_transaction(
                    project_root,
                    expected_transaction_id=transaction_id,
                )
            self.assertTrue(lock.is_file())
            self.assertTrue(artifact.is_dir())

    @unittest.skipUnless(
        hasattr(os, "fork"),
        "requires fork for hard-exit recovery",
    )
    def test_project_bootstrap_initialization_hard_exits_have_exact_cleanup(
        self,
    ) -> None:
        cases = (("lock", 21), ("first-journal-temporary", 22))
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            for label, expected_exit in cases:
                with self.subTest(point=label):
                    project_root = base / label
                    project_root.mkdir()
                    sentinel = project_root / "sentinel.bin"
                    sentinel.write_bytes(b"preserve\x00project\n")
                    sentinel.chmod(0o640)
                    child = os.fork()
                    if child == 0:
                        if label == "lock":
                            real_acquire = bootstrap_transaction._acquire_project_lock

                            def exit_after_lock(*args: Any, **kwargs: Any) -> Any:
                                result = real_acquire(*args, **kwargs)
                                if result[1]:
                                    os._exit(expected_exit)
                                return result

                            patcher = mock.patch.object(
                                bootstrap_transaction,
                                "_acquire_project_lock",
                                side_effect=exit_after_lock,
                            )
                        else:
                            real_write_all = bootstrap_transaction._write_all

                            def exit_during_first_journal(
                                descriptor: int,
                                payload: bytes,
                            ) -> None:
                                try:
                                    decoded = json.loads(payload.decode("utf-8"))
                                except (UnicodeDecodeError, json.JSONDecodeError):
                                    decoded = None
                                if (
                                    isinstance(decoded, dict)
                                    and "transaction_id" in decoded
                                ):
                                    os.write(
                                        descriptor,
                                        payload[: max(1, len(payload) // 2)],
                                    )
                                    os._exit(expected_exit)
                                real_write_all(descriptor, payload)

                            patcher = mock.patch.object(
                                bootstrap_transaction,
                                "_write_all",
                                side_effect=exit_during_first_journal,
                            )
                        with patcher:
                            bootstrap_transaction.transactional_write_outputs(
                                project_root,
                                [("nested/output.md", "new output\n")],
                                force=False,
                                create_file_mode=0o600,
                                create_directory_mode=0o700,
                            )
                        os._exit(99)
                    _, child_status = os.waitpid(child, 0)
                    self.assertEqual(
                        expected_exit,
                        os.waitstatus_to_exitcode(child_status),
                    )
                    before_wrong_id = {
                        path.name: (
                            path.read_bytes() if path.is_file() else None,
                            path.stat().st_mode & 0o777,
                        )
                        for path in project_root.iterdir()
                    }
                    recovery = bootstrap_transaction.transaction_recovery_status(
                        project_root
                    )
                    self.assertEqual("recovery-required", recovery.state, recovery)
                    self.assertEqual("initializing", recovery.phase, recovery)
                    self.assertTrue(recovery.can_rollback, recovery)
                    self.assertFalse(recovery.can_finalize, recovery)
                    self.assertEqual((), recovery.operation_paths)
                    transaction_id = recovery.transaction_id
                    if transaction_id is None:
                        self.fail("initialization recovery omitted its lock identity")
                    wrong_id = "0" * 32 if transaction_id != "0" * 32 else "1" * 32
                    with self.assertRaisesRegex(
                        bootstrap_transaction.BootstrapTransactionError,
                        "identity changed",
                    ):
                        bootstrap_transaction.rollback_interrupted_transaction(
                            project_root,
                            expected_transaction_id=wrong_id,
                        )
                    after_wrong_id = {
                        path.name: (
                            path.read_bytes() if path.is_file() else None,
                            path.stat().st_mode & 0o777,
                        )
                        for path in project_root.iterdir()
                    }
                    self.assertEqual(before_wrong_id, after_wrong_id)

                    recovered = (
                        bootstrap_transaction.rollback_interrupted_transaction(
                            project_root,
                            expected_transaction_id=transaction_id,
                        )
                    )

                    self.assertEqual("clean", recovered.state, recovered)
                    self.assertEqual(b"preserve\x00project\n", sentinel.read_bytes())
                    self.assertEqual(0o640, sentinel.stat().st_mode & 0o777)
                    self.assertEqual(
                        ["sentinel.bin"],
                        [path.name for path in project_root.iterdir()],
                    )

    @unittest.skipUnless(
        hasattr(os, "fork"),
        "requires fork for hard-exit recovery",
    )
    def test_project_bootstrap_initialization_cleanup_is_crash_resumable(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / "project"
            project_root.mkdir()
            sentinel = project_root / "sentinel.bin"
            sentinel.write_bytes(b"preserve\x00project\n")
            sentinel.chmod(0o640)
            lock = project_root / bootstrap_transaction.TRANSACTION_LOCK_NAME
            lock.write_bytes(b"")
            lock.chmod(0o600)
            temporary = (
                project_root / bootstrap_transaction._RECOVERY_JOURNAL_TEMP_NAME
            )
            temporary.write_bytes(b"partial journal\x00bytes\n")
            temporary.chmod(0o600)
            inspected = bootstrap_transaction.transaction_recovery_status(project_root)
            transaction_id = inspected.transaction_id
            if transaction_id is None:
                self.fail("initialization inspection omitted its exact lock identity")

            expected_exit = 24
            child = os.fork()
            if child == 0:
                with mock.patch.object(
                    bootstrap_transaction,
                    "_remove_project_lock",
                    side_effect=lambda *_args, **_kwargs: os._exit(expected_exit),
                ):
                    bootstrap_transaction.rollback_interrupted_transaction(
                        project_root,
                        expected_transaction_id=transaction_id,
                    )
                os._exit(99)
            _, child_status = os.waitpid(child, 0)
            self.assertEqual(expected_exit, os.waitstatus_to_exitcode(child_status))
            self.assertFalse(temporary.exists())
            self.assertTrue(lock.is_file())
            resumed = bootstrap_transaction.transaction_recovery_status(project_root)
            self.assertEqual("recovery-required", resumed.state, resumed)
            self.assertEqual(transaction_id, resumed.transaction_id)

            recovered = bootstrap_transaction.rollback_interrupted_transaction(
                project_root,
                expected_transaction_id=transaction_id,
            )

            self.assertEqual("clean", recovered.state, recovered)
            self.assertEqual(b"preserve\x00project\n", sentinel.read_bytes())
            self.assertEqual(
                ["sentinel.bin"],
                [path.name for path in project_root.iterdir()],
            )

    def test_failed_journal_temp_cleanup_retains_exact_recovery_identity(
        self,
    ) -> None:
        cases = (("first-write", 1), ("later-rewrite", 3))
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            for label, failing_journal_write in cases:
                with self.subTest(point=label):
                    project_root = base / label
                    project_root.mkdir()
                    sentinel = project_root / "sentinel.bin"
                    sentinel.write_bytes(b"preserve\x00project\n")
                    sentinel.chmod(0o640)
                    real_write_all = bootstrap_transaction._write_all
                    journal_writes = 0

                    def fail_selected_journal_write(
                        descriptor: int,
                        payload: bytes,
                    ) -> None:
                        nonlocal journal_writes
                        try:
                            decoded = json.loads(payload.decode("utf-8"))
                        except (UnicodeDecodeError, json.JSONDecodeError):
                            decoded = None
                        if isinstance(decoded, dict) and "transaction_id" in decoded:
                            journal_writes += 1
                            if journal_writes == failing_journal_write:
                                os.write(
                                    descriptor,
                                    payload[: max(1, len(payload) // 2)],
                                )
                                raise OSError("injected journal write failure")
                        real_write_all(descriptor, payload)

                    with (
                        mock.patch.object(
                            bootstrap_transaction,
                            "_write_all",
                            side_effect=fail_selected_journal_write,
                        ),
                        mock.patch.object(
                            bootstrap_transaction,
                            "_remove_recovery_journal_temporary",
                            side_effect=OSError("injected temporary cleanup failure"),
                        ),
                        self.assertRaisesRegex(
                            bootstrap_transaction.BootstrapTransactionError,
                            "temporary file remains after rollback",
                        ),
                    ):
                        bootstrap_transaction.transactional_write_outputs(
                            project_root,
                            [("nested/output.md", "new output\n")],
                            force=False,
                            create_file_mode=0o600,
                            create_directory_mode=0o700,
                        )

                    lock = project_root / bootstrap_transaction.TRANSACTION_LOCK_NAME
                    temporary = (
                        project_root
                        / bootstrap_transaction._RECOVERY_JOURNAL_TEMP_NAME
                    )
                    self.assertTrue(lock.is_file())
                    self.assertTrue(temporary.is_file())
                    recovery = bootstrap_transaction.transaction_recovery_status(
                        project_root
                    )
                    self.assertEqual("recovery-required", recovery.state, recovery)
                    self.assertTrue(recovery.can_rollback, recovery)
                    self.assertFalse(recovery.can_finalize, recovery)
                    transaction_id = recovery.transaction_id
                    if transaction_id is None:
                        self.fail("retained controls omitted their exact transaction ID")

                    recovered = (
                        bootstrap_transaction.rollback_interrupted_transaction(
                            project_root,
                            expected_transaction_id=transaction_id,
                        )
                    )

                    self.assertEqual("clean", recovered.state, recovered)
                    self.assertEqual(b"preserve\x00project\n", sentinel.read_bytes())
                    self.assertEqual(0o640, sentinel.stat().st_mode & 0o777)
                    self.assertEqual(
                        ["sentinel.bin"],
                        [path.name for path in project_root.iterdir()],
                    )

    def test_directory_removal_keeps_binding_open_through_rmdir(self) -> None:
        cases = (
            "transaction-directory",
            "created-directory",
            "retired-directory",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            for label in cases:
                with self.subTest(helper=label):
                    project_root = base / label
                    project_root.mkdir()
                    target = project_root / "managed"
                    target.mkdir()
                    all_bindings: list[
                        bootstrap_transaction._DirectoryBinding
                    ] = []
                    root = bootstrap_transaction._open_project_root_transaction(
                        project_root,
                        all_bindings=all_bindings,
                    )
                    binding = bootstrap_transaction._open_bound_directory(
                        root,
                        "managed",
                        label=label,
                        create=False,
                        require_owner=True,
                        created_bindings=[],
                        all_bindings=all_bindings,
                    )
                    real_close = bootstrap_transaction._close_binding
                    replacement_created = False

                    def replace_at_former_close_point(
                        current: bootstrap_transaction._DirectoryBinding,
                    ) -> None:
                        nonlocal replacement_created
                        if current is binding and not replacement_created:
                            self.assertIsNotNone(current.descriptor)
                            self.assertFalse(target.exists())
                            target.mkdir()
                            replacement_created = True
                        real_close(current)

                    try:
                        with mock.patch.object(
                            bootstrap_transaction,
                            "_close_binding",
                            side_effect=replace_at_former_close_point,
                        ):
                            if label == "transaction-directory":
                                errors = bootstrap_transaction._remove_empty_transaction_directories(
                                    [
                                        bootstrap_transaction._TransactionDirectory(
                                            parent=root,
                                            binding=binding,
                                            relative_path="managed",
                                        )
                                    ]
                                )
                            elif label == "created-directory":
                                errors = bootstrap_transaction._remove_created_directories(
                                    [binding]
                                )
                            else:
                                errors = bootstrap_transaction._retire_empty_directories(
                                    [binding]
                                )
                    finally:
                        for retained in reversed(all_bindings):
                            real_close(retained)

                    self.assertEqual([], errors)
                    self.assertTrue(replacement_created)
                    self.assertTrue(target.is_dir())

    @unittest.skipUnless(hasattr(os, "fork"), "requires cross-process flock")
    def test_project_bootstrap_transaction_lock_blocks_status_and_writer(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / "project"
            project_root.mkdir()
            target = project_root / "first.md"
            target.write_bytes(b"old first\n")
            ready_read, ready_write = os.pipe()
            release_read, release_write = os.pipe()
            child = os.fork()
            if child == 0:
                os.close(ready_read)
                os.close(release_write)
                descriptor = os.open(
                    project_root,
                    os.O_RDONLY | os.O_DIRECTORY,
                )
                bootstrap_transaction.fcntl.flock(
                    descriptor,
                    bootstrap_transaction.fcntl.LOCK_EX,
                )
                os.write(ready_write, b"1")
                os.read(release_read, 1)
                bootstrap_transaction.fcntl.flock(
                    descriptor,
                    bootstrap_transaction.fcntl.LOCK_UN,
                )
                os.close(descriptor)
                os._exit(0)
            os.close(ready_write)
            os.close(release_read)
            try:
                self.assertEqual(b"1", os.read(ready_read, 1))
                status = bootstrap_transaction.transaction_recovery_status(
                    project_root
                )
                self.assertEqual("active", status.state, status)
                with self.assertRaisesRegex(
                    bootstrap_transaction.BootstrapTransactionError,
                    "another bootstrap transaction holds the project lock",
                ):
                    bootstrap_transaction.transactional_write_outputs(
                        project_root,
                        [("first.md", "new first\n")],
                        force=True,
                    )
            finally:
                os.write(release_write, b"1")
                os.close(release_write)
                os.close(ready_read)
                _, child_status = os.waitpid(child, 0)
                self.assertEqual(0, os.waitstatus_to_exitcode(child_status))

            self.assertEqual(b"old first\n", target.read_bytes())
            self.assertEqual(
                "clean",
                bootstrap_transaction.transaction_recovery_status(project_root).state,
            )
            self.assertFalse(
                (project_root / bootstrap_transaction.RECOVERY_JOURNAL_NAME).exists()
            )
            self.assertFalse(
                (project_root / bootstrap_transaction.TRANSACTION_LOCK_NAME).exists()
            )

    def test_project_bootstrap_expected_preimage_mismatch_changes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / "project"
            project_root.mkdir()
            target = project_root / "first.md"
            original = b"unexpected current bytes\x00\n"
            target.write_bytes(original)
            approved_digest = hashlib.sha256(b"approved old bytes\n").hexdigest()

            with self.assertRaisesRegex(
                bootstrap_transaction.BootstrapTransactionError,
                "bootstrap output preimage changed",
            ):
                bootstrap_transaction.transactional_write_outputs(
                    project_root,
                    [("first.md", "new first\n")],
                    force=True,
                    expected_preimages={"first.md": approved_digest},
                )

            self.assertEqual(original, target.read_bytes())
            self.assertEqual(
                ["first.md"],
                sorted(path.name for path in project_root.iterdir()),
            )

    def test_project_bootstrap_expected_and_asserted_modes_reject_chmod_only_drift(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / "expected"
            project_root.mkdir()
            target = project_root / "first.md"
            original = b"unchanged bytes\n"
            target.write_bytes(original)
            target.chmod(0o600)

            with self.assertRaisesRegex(
                bootstrap_transaction.BootstrapTransactionError,
                "bootstrap output preimage changed",
            ):
                bootstrap_transaction.transactional_write_outputs(
                    project_root,
                    [("first.md", "new first\n")],
                    force=True,
                    expected_preimages={
                        "first.md": hashlib.sha256(original).hexdigest(),
                    },
                    expected_preimage_modes={"first.md": 0o640},
                )

            self.assertEqual(original, target.read_bytes())
            self.assertEqual(0o600, target.stat().st_mode & 0o777)

        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / "asserted"
            project_root.mkdir()
            target = project_root / "first.md"
            preserved = project_root / "TODO.md"
            target_original = b"old first\n"
            preserved_original = b"preserved state\n"
            target.write_bytes(target_original)
            target.chmod(0o640)
            preserved.write_bytes(preserved_original)
            preserved.chmod(0o640)

            def change_only_asserted_mode() -> None:
                preserved.chmod(0o600)

            with self.assertRaisesRegex(
                bootstrap_transaction.BootstrapTransactionError,
                "asserted preimage changed",
            ):
                bootstrap_transaction.transactional_write_outputs(
                    project_root,
                    [("first.md", "new first\n")],
                    force=True,
                    assert_preimages={
                        "TODO.md": hashlib.sha256(preserved_original).hexdigest(),
                    },
                    assert_preimage_modes={"TODO.md": 0o640},
                    post_install_verifier=change_only_asserted_mode,
                )

            self.assertEqual(target_original, target.read_bytes())
            self.assertEqual(0o640, target.stat().st_mode & 0o777)
            self.assertEqual(preserved_original, preserved.read_bytes())
            self.assertEqual(0o600, preserved.stat().st_mode & 0o777)

    def test_project_bootstrap_verifier_rollback_restores_original_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / "project"
            project_root.mkdir()
            target = project_root / "first.md"
            original = b"old first\n"
            target.write_bytes(original)
            target.chmod(0o640)

            def reject_exact_mode_candidate() -> None:
                self.assertEqual(b"new first\n", target.read_bytes())
                self.assertEqual(0o600, target.stat().st_mode & 0o777)
                raise RuntimeError("injected exact-mode verification failure")

            with self.assertRaisesRegex(
                bootstrap_transaction.BootstrapTransactionError,
                "injected exact-mode verification failure",
            ):
                bootstrap_transaction.transactional_write_outputs(
                    project_root,
                    [("first.md", "new first\n")],
                    force=True,
                    target_modes={"first.md": 0o600},
                    post_install_verifier=reject_exact_mode_candidate,
                )

            self.assertEqual(original, target.read_bytes())
            self.assertEqual(0o640, target.stat().st_mode & 0o777)
            self.assertEqual(
                "clean",
                bootstrap_transaction.transaction_recovery_status(project_root).state,
            )

    def test_project_bootstrap_post_install_verifier_failure_rolls_back(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / "project"
            project_root.mkdir()
            target = project_root / "first.md"
            original = b"old first\x00\n"
            target.write_bytes(original)

            def reject_candidate() -> None:
                self.assertEqual(b"new first\n", target.read_bytes())
                raise RuntimeError("injected post-install verification failure")

            with self.assertRaisesRegex(
                bootstrap_transaction.BootstrapTransactionError,
                "injected post-install verification failure",
            ):
                bootstrap_transaction.transactional_write_outputs(
                    project_root,
                    [("first.md", "new first\n")],
                    force=True,
                    post_install_verifier=reject_candidate,
                )

            self.assertEqual(original, target.read_bytes())
            self.assertEqual(
                "clean",
                bootstrap_transaction.transaction_recovery_status(project_root).state,
            )
            self.assertEqual(
                [],
                list(project_root.rglob(".mpa-bootstrap-transaction-*")),
            )

    def test_project_bootstrap_explicit_removal_rolls_back_on_later_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / "project"
            project_root.mkdir()
            first = project_root / "first.md"
            second = project_root / "second.md"
            first_original = b"old first\x00\n"
            second_original = b"old second\x00\n"
            first.write_bytes(first_original)
            second.write_bytes(second_original)
            real_install = bootstrap_transaction._install_staged_output

            def fail_second_removal(
                record: bootstrap_transaction._OutputTransactionRecord,
                index: int,
                bindings: list[bootstrap_transaction._DirectoryBinding],
            ) -> None:
                if index == 1:
                    raise OSError("injected later removal failure")
                real_install(record, index, bindings)

            with (
                mock.patch.object(
                    bootstrap_transaction,
                    "_install_staged_output",
                    side_effect=fail_second_removal,
                ),
                self.assertRaisesRegex(
                    bootstrap_transaction.BootstrapTransactionError,
                    "injected later removal failure",
                ),
            ):
                bootstrap_transaction.transactional_write_outputs(
                    project_root,
                    [],
                    force=True,
                    remove_outputs=["first.md", "second.md"],
                )

            self.assertEqual(first_original, first.read_bytes())
            self.assertEqual(second_original, second.read_bytes())
            self.assertEqual(
                "clean",
                bootstrap_transaction.transaction_recovery_status(project_root).state,
            )
            self.assertFalse(
                (project_root / bootstrap_transaction.TRANSACTION_LOCK_NAME).exists()
            )

    def test_project_bootstrap_asserted_preimage_drift_prevents_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / "project"
            project_root.mkdir()
            target = project_root / "first.md"
            preserved = project_root / "TODO.md"
            target_original = b"old first\n"
            preserved_original = b"preserved mutable state\n"
            target.write_bytes(target_original)
            preserved.write_bytes(preserved_original)

            def change_preserved_file() -> None:
                preserved.write_bytes(b"concurrent mutable change\n")

            with self.assertRaisesRegex(
                bootstrap_transaction.BootstrapTransactionError,
                "asserted preimage changed",
            ):
                bootstrap_transaction.transactional_write_outputs(
                    project_root,
                    [("first.md", "new first\n")],
                    force=True,
                    expected_preimages={
                        "first.md": hashlib.sha256(target_original).hexdigest(),
                    },
                    assert_preimages={
                        "TODO.md": hashlib.sha256(preserved_original).hexdigest(),
                    },
                    post_install_verifier=change_preserved_file,
                )

            self.assertEqual(target_original, target.read_bytes())
            self.assertEqual(b"concurrent mutable change\n", preserved.read_bytes())
            self.assertEqual(
                "clean",
                bootstrap_transaction.transaction_recovery_status(project_root).state,
            )

    @unittest.skipUnless(hasattr(os, "fork"), "requires fork for hard-exit recovery")
    def test_project_bootstrap_crash_during_journal_rewrite_cleans_exact_temp(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / "project"
            project_root.mkdir()
            expected_exit = 23
            child = os.fork()
            if child == 0:
                real_write_all = bootstrap_transaction._write_all
                journal_writes = 0

                def exit_during_later_journal_write(
                    descriptor: int,
                    payload: bytes,
                ) -> None:
                    nonlocal journal_writes
                    try:
                        decoded = json.loads(payload.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        decoded = None
                    if isinstance(decoded, dict) and "transaction_id" in decoded:
                        journal_writes += 1
                        # The second preparing write is the first durable
                        # journal of created-directory identities. Interrupt a
                        # later rewrite so this test exercises resumable temp
                        # cleanup without relying on an unknown directory ID.
                        if journal_writes == 3:
                            os.write(descriptor, payload[: max(1, len(payload) // 2)])
                            os._exit(expected_exit)
                    real_write_all(descriptor, payload)

                with mock.patch.object(
                    bootstrap_transaction,
                    "_write_all",
                    side_effect=exit_during_later_journal_write,
                ):
                    bootstrap_transaction.transactional_write_outputs(
                        project_root,
                        [("nested/deeper/output.md", "new output\n")],
                        force=False,
                        create_file_mode=0o600,
                        create_directory_mode=0o700,
                    )
                os._exit(99)
            _, child_status = os.waitpid(child, 0)
            self.assertEqual(expected_exit, os.waitstatus_to_exitcode(child_status))
            temporary = (
                project_root / bootstrap_transaction._RECOVERY_JOURNAL_TEMP_NAME
            )
            self.assertTrue(temporary.is_file())
            self.assertTrue((project_root / "nested" / "deeper").is_dir())
            self.assertFalse(
                (project_root / "nested" / "deeper" / "output.md").exists()
            )

            recovery = bootstrap_transaction.transaction_recovery_status(project_root)
            self.assertEqual("recovery-required", recovery.state, recovery)
            transaction_id = recovery.transaction_id
            if transaction_id is None:
                self.fail("journal-rewrite recovery omitted its transaction identity")
            recovered = bootstrap_transaction.rollback_interrupted_transaction(
                project_root,
                expected_transaction_id=transaction_id,
            )

            self.assertEqual("clean", recovered.state, recovered)
            self.assertEqual([], list(project_root.iterdir()))

    @unittest.skipUnless(hasattr(os, "fork"), "requires fork for hard-exit recovery")
    def test_project_bootstrap_unknown_created_directory_identity_is_retained(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / "project"
            project_root.mkdir()
            expected_exit = 30
            child = os.fork()
            if child == 0:
                real_open = bootstrap_transaction._open_bound_directory

                def exit_after_parent(*args: Any, **kwargs: Any) -> Any:
                    binding = real_open(*args, **kwargs)
                    if kwargs.get("create") and binding.created:
                        os._exit(expected_exit)
                    return binding

                with mock.patch.object(
                    bootstrap_transaction,
                    "_open_bound_directory",
                    side_effect=exit_after_parent,
                ):
                    bootstrap_transaction.transactional_write_outputs(
                        project_root,
                        [("nested/deeper/output.md", "new output\n")],
                        force=False,
                        create_file_mode=0o600,
                        create_directory_mode=0o700,
                    )
                os._exit(99)
            _, child_status = os.waitpid(child, 0)
            self.assertEqual(expected_exit, os.waitstatus_to_exitcode(child_status))
            journal = json.loads(
                (project_root / bootstrap_transaction.RECOVERY_JOURNAL_NAME).read_text(
                    encoding="utf-8"
                )
            )
            created = cast(list[dict[str, object]], journal["created_directories"])
            self.assertTrue(all(entry["identity"] is None for entry in created))

            original_created = project_root / "nested"
            displaced = project_root / "displaced-created-directory"
            original_created.rename(displaced)
            replacement = project_root / "nested"
            replacement.mkdir(mode=0o700)
            unrelated = replacement / "owner-content.bin"
            unrelated.write_bytes(b"must remain\x00untouched\n")
            recovery = bootstrap_transaction.transaction_recovery_status(project_root)
            self.assertEqual("invalid", recovery.state, recovery)
            self.assertFalse(recovery.can_rollback, recovery)
            self.assertTrue(
                any("journaled identity is unknown" in error for error in recovery.errors),
                recovery,
            )
            transaction_id = recovery.transaction_id
            if transaction_id is None:
                self.fail("preparing recovery omitted its transaction identity")

            with self.assertRaisesRegex(
                bootstrap_transaction.BootstrapTransactionError,
                "journaled identity is unknown",
            ):
                bootstrap_transaction.rollback_interrupted_transaction(
                    project_root,
                    expected_transaction_id=transaction_id,
                )

            self.assertEqual(b"must remain\x00untouched\n", unrelated.read_bytes())
            self.assertTrue(replacement.is_dir())
            self.assertTrue(displaced.is_dir())
            self.assertTrue(
                (project_root / bootstrap_transaction.TRANSACTION_LOCK_NAME).is_file()
            )
            self.assertTrue(
                (project_root / bootstrap_transaction.RECOVERY_JOURNAL_NAME).is_file()
            )

    @unittest.skipUnless(hasattr(os, "fork"), "requires fork for hard-exit recovery")
    def test_project_bootstrap_preparing_hard_exits_are_exactly_recoverable(self) -> None:
        cases = (("transaction-directory", 32), ("stage", 33))
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            for label, expected_exit in cases:
                with self.subTest(point=label):
                    project_root = base / label
                    project_root.mkdir()
                    child = os.fork()
                    if child == 0:
                        if label == "transaction-directory":
                            real_create = bootstrap_transaction._create_transaction_directory

                            def exit_after_transaction_directory(
                                *args: Any,
                                **kwargs: Any,
                            ) -> Any:
                                result = real_create(*args, **kwargs)
                                os._exit(expected_exit)

                            patcher = mock.patch.object(
                                bootstrap_transaction,
                                "_create_transaction_directory",
                                side_effect=exit_after_transaction_directory,
                            )
                        else:
                            real_write_all = bootstrap_transaction._write_all

                            def exit_during_stage(
                                descriptor: int,
                                payload: bytes,
                            ) -> None:
                                if payload == b"new output\n":
                                    os.write(descriptor, payload[:3])
                                    os._exit(expected_exit)
                                real_write_all(descriptor, payload)

                            patcher = mock.patch.object(
                                bootstrap_transaction,
                                "_write_all",
                                side_effect=exit_during_stage,
                            )
                        with patcher:
                            bootstrap_transaction.transactional_write_outputs(
                                project_root,
                                [("nested/deeper/output.md", "new output\n")],
                                force=False,
                                create_file_mode=0o600,
                                create_directory_mode=0o700,
                            )
                        os._exit(99)
                    _, child_status = os.waitpid(child, 0)
                    self.assertEqual(
                        expected_exit,
                        os.waitstatus_to_exitcode(child_status),
                    )
                    journal_path = (
                        project_root / bootstrap_transaction.RECOVERY_JOURNAL_NAME
                    )
                    journal = json.loads(journal_path.read_text(encoding="utf-8"))
                    self.assertEqual("preparing", journal["phase"])
                    recovery = bootstrap_transaction.transaction_recovery_status(
                        project_root
                    )
                    self.assertEqual("recovery-required", recovery.state, recovery)
                    self.assertEqual(
                        ("nested/deeper/output.md",),
                        recovery.operation_paths,
                    )
                    transaction_id = recovery.transaction_id
                    if transaction_id is None:
                        self.fail("preparing recovery omitted its transaction identity")
                    wrong_id = "0" * 32 if transaction_id != "0" * 32 else "1" * 32
                    with self.assertRaisesRegex(
                        bootstrap_transaction.BootstrapTransactionError,
                        "identity changed",
                    ):
                        bootstrap_transaction.rollback_interrupted_transaction(
                            project_root,
                            expected_transaction_id=wrong_id,
                        )
                    unchanged = bootstrap_transaction.transaction_recovery_status(
                        project_root
                    )
                    self.assertEqual(transaction_id, unchanged.transaction_id)
                    recovered = bootstrap_transaction.rollback_interrupted_transaction(
                        project_root,
                        expected_transaction_id=transaction_id,
                    )
                    self.assertEqual("clean", recovered.state, recovered)
                    self.assertEqual([], list(project_root.iterdir()))

    @unittest.skipUnless(hasattr(os, "fork"), "requires fork for hard-exit recovery")
    def test_project_bootstrap_mixed_hard_exit_rollback_restores_bytes_and_modes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / "project"
            project_root.mkdir()
            write_target = project_root / "write.md"
            remove_target = project_root / "remove.md"
            write_original = b"old write\x00\n"
            remove_original = b"old remove\x00\n"
            write_target.write_bytes(write_original)
            remove_target.write_bytes(remove_original)
            write_target.chmod(0o640)
            remove_target.chmod(0o600)

            child = os.fork()
            if child == 0:
                bootstrap_transaction.transactional_write_outputs(
                    project_root,
                    [("write.md", "new write\n")],
                    force=True,
                    remove_outputs=["remove.md"],
                    post_install_verifier=lambda: os._exit(23),
                )
                os._exit(99)
            _, child_status = os.waitpid(child, 0)
            self.assertEqual(23, os.waitstatus_to_exitcode(child_status))
            self.assertEqual(b"new write\n", write_target.read_bytes())
            self.assertEqual(0o640, write_target.stat().st_mode & 0o777)
            self.assertFalse(remove_target.exists())

            recovery = bootstrap_transaction.transaction_recovery_status(project_root)
            self.assertEqual("recovery-required", recovery.state, recovery)
            self.assertTrue(recovery.can_rollback, recovery)
            self.assertFalse(recovery.can_finalize, recovery)
            self.assertEqual(("write.md", "remove.md"), recovery.operation_paths)
            self.assertIsNotNone(recovery.transaction_id)
            transaction_id = recovery.transaction_id
            if transaction_id is None:
                self.fail("recovery status omitted its transaction identity")

            recovered = bootstrap_transaction.rollback_interrupted_transaction(
                project_root,
                expected_transaction_id=transaction_id,
            )

            self.assertEqual("clean", recovered.state, recovered)
            self.assertEqual(write_original, write_target.read_bytes())
            self.assertEqual(remove_original, remove_target.read_bytes())
            self.assertEqual(0o640, write_target.stat().st_mode & 0o777)
            self.assertEqual(0o600, remove_target.stat().st_mode & 0o777)
            self.assertFalse(
                (project_root / bootstrap_transaction.RECOVERY_JOURNAL_NAME).exists()
            )
            self.assertFalse(
                (project_root / bootstrap_transaction.TRANSACTION_LOCK_NAME).exists()
            )
            self.assertEqual(
                [],
                list(project_root.rglob(".mpa-bootstrap-transaction-*")),
            )

    @unittest.skipUnless(hasattr(os, "fork"), "requires fork for hard-exit recovery")
    def test_project_bootstrap_cleanup_hard_exit_leaves_exact_finalize_journal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / "project"
            project_root.mkdir()
            target = project_root / "first.md"
            target.write_bytes(b"old\x00bytes\n")
            target.chmod(0o640)

            child = os.fork()
            if child == 0:
                with mock.patch.object(
                    bootstrap_transaction,
                    "_remove_recovery_journal",
                    side_effect=lambda _root: os._exit(23),
                ):
                    bootstrap_transaction.transactional_write_outputs(
                        project_root,
                        [("first.md", "new bytes\n")],
                        force=True,
                    )
                os._exit(99)
            _, child_status = os.waitpid(child, 0)
            self.assertEqual(23, os.waitstatus_to_exitcode(child_status))
            self.assertEqual(b"new bytes\n", target.read_bytes())
            self.assertEqual(0o640, target.stat().st_mode & 0o777)
            self.assertFalse(
                (project_root / bootstrap_transaction.TRANSACTION_LOCK_NAME).exists()
            )
            self.assertTrue(
                (project_root / bootstrap_transaction.RECOVERY_JOURNAL_NAME).is_file()
            )

            recovery = bootstrap_transaction.transaction_recovery_status(project_root)
            self.assertEqual("verified", recovery.state, recovery)
            self.assertFalse(recovery.can_rollback, recovery)
            self.assertTrue(recovery.can_finalize, recovery)
            transaction_id = recovery.transaction_id
            if transaction_id is None:
                self.fail("verified recovery omitted its transaction identity")
            wrong_id = "0" * 32 if transaction_id != "0" * 32 else "1" * 32
            with self.assertRaisesRegex(
                bootstrap_transaction.BootstrapTransactionError,
                "identity changed",
            ):
                bootstrap_transaction.finalize_interrupted_transaction(
                    project_root,
                    expected_transaction_id=wrong_id,
                )
            self.assertFalse(
                (project_root / bootstrap_transaction.TRANSACTION_LOCK_NAME).exists()
            )
            self.assertTrue(
                (project_root / bootstrap_transaction.RECOVERY_JOURNAL_NAME).is_file()
            )

            finalized = bootstrap_transaction.finalize_interrupted_transaction(
                project_root,
                expected_transaction_id=transaction_id,
            )
            self.assertEqual("clean", finalized.state, finalized)
            self.assertEqual(b"new bytes\n", target.read_bytes())
            self.assertEqual(0o640, target.stat().st_mode & 0o777)
            self.assertEqual(["first.md"], [path.name for path in project_root.iterdir()])

    @unittest.skipUnless(hasattr(os, "fork"), "requires fork for hard-exit recovery")
    def test_verified_directory_retirement_is_exactly_resumable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / "project"
            target = project_root / ".agents" / "skills" / "seo" / "SKILL.md"
            target.parent.mkdir(parents=True)
            target.write_text("managed wrapper\n", encoding="utf-8")
            expected_exit = 31

            child = os.fork()
            if child == 0:
                real_rmdir = bootstrap_transaction.os.rmdir

                def exit_after_first_retirement(
                    path: str,
                    *,
                    dir_fd: int | None = None,
                ) -> None:
                    real_rmdir(path, dir_fd=dir_fd)
                    if path == "seo":
                        os._exit(expected_exit)

                with mock.patch.object(
                    bootstrap_transaction.os,
                    "rmdir",
                    side_effect=exit_after_first_retirement,
                ):
                    bootstrap_transaction.transactional_write_outputs(
                        project_root,
                        [],
                        force=True,
                        remove_outputs=[".agents/skills/seo/SKILL.md"],
                        retire_empty_directories=[
                            ".agents",
                            ".agents/skills",
                            ".agents/skills/seo",
                        ],
                    )
                os._exit(99)
            _, child_status = os.waitpid(child, 0)
            self.assertEqual(expected_exit, os.waitstatus_to_exitcode(child_status))
            self.assertFalse(target.exists())
            self.assertFalse(target.parent.exists())
            self.assertTrue((project_root / ".agents" / "skills").is_dir())

            recovery = bootstrap_transaction.transaction_recovery_status(project_root)
            self.assertEqual("verified", recovery.state, recovery)
            self.assertFalse(recovery.can_rollback, recovery)
            self.assertTrue(recovery.can_finalize, recovery)
            transaction_id = recovery.transaction_id
            if transaction_id is None:
                self.fail("verified retirement recovery omitted its transaction identity")

            finalized = bootstrap_transaction.finalize_interrupted_transaction(
                project_root,
                expected_transaction_id=transaction_id,
            )

            self.assertEqual("clean", finalized.state, finalized)
            self.assertFalse((project_root / ".agents").exists())
            self.assertEqual([], list(project_root.iterdir()))

    @unittest.skipUnless(hasattr(os, "fork"), "requires fork for hard-exit recovery")
    def test_project_bootstrap_created_directory_rollback_is_crash_resumable(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / "project"
            project_root.mkdir()
            expected_exit = 29
            child = os.fork()
            if child == 0:
                def reject_installed_project() -> None:
                    raise RuntimeError("injected verifier rejection")

                with mock.patch.object(
                    bootstrap_transaction,
                    "_remove_recovery_journal",
                    side_effect=lambda _root: os._exit(expected_exit),
                ):
                    bootstrap_transaction.transactional_write_outputs(
                        project_root,
                        [("nested/deeper/new.md", "new output\n")],
                        force=False,
                        create_file_mode=0o600,
                        create_directory_mode=0o700,
                        post_install_verifier=reject_installed_project,
                    )
                os._exit(99)
            _, child_status = os.waitpid(child, 0)
            self.assertEqual(expected_exit, os.waitstatus_to_exitcode(child_status))
            self.assertFalse((project_root / "nested").exists())
            self.assertFalse(
                (project_root / bootstrap_transaction.TRANSACTION_LOCK_NAME).exists()
            )
            self.assertTrue(
                (project_root / bootstrap_transaction.RECOVERY_JOURNAL_NAME).is_file()
            )

            recovery = bootstrap_transaction.transaction_recovery_status(project_root)
            self.assertEqual("recovery-required", recovery.state, recovery)
            transaction_id = recovery.transaction_id
            if transaction_id is None:
                self.fail("resumable rollback omitted its transaction identity")
            recovered = bootstrap_transaction.rollback_interrupted_transaction(
                project_root,
                expected_transaction_id=transaction_id,
            )

            self.assertEqual("clean", recovered.state, recovered)
            self.assertEqual([], list(project_root.iterdir()))

    @unittest.skipUnless(hasattr(os, "fork"), "requires fork for hard-exit recovery")
    def test_project_bootstrap_hard_exit_rollback_removes_created_nested_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / "project"
            project_root.mkdir()
            target = project_root / "nested" / "deeper" / "new.md"

            child = os.fork()
            if child == 0:
                bootstrap_transaction.transactional_write_outputs(
                    project_root,
                    [("nested/deeper/new.md", "new output\n")],
                    force=False,
                    create_file_mode=0o600,
                    create_directory_mode=0o700,
                    post_install_verifier=lambda: os._exit(23),
                )
                os._exit(99)
            _, child_status = os.waitpid(child, 0)
            self.assertEqual(23, os.waitstatus_to_exitcode(child_status))
            self.assertEqual(b"new output\n", target.read_bytes())

            journal = json.loads(
                (project_root / bootstrap_transaction.RECOVERY_JOURNAL_NAME).read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(0o600, journal["operations"][0]["candidate"]["mode"])
            self.assertEqual(
                {0o700},
                {
                    entry["identity"][2] & 0o777
                    for entry in journal["created_directories"]
                },
            )
            self.assertEqual(0o600, target.stat().st_mode & 0o777)
            self.assertEqual(0o700, target.parent.stat().st_mode & 0o777)
            self.assertEqual(0o700, target.parent.parent.stat().st_mode & 0o777)

            target.chmod(0o640)
            tampered_file = bootstrap_transaction.transaction_recovery_status(project_root)
            self.assertEqual("invalid", tampered_file.state, tampered_file)
            target.chmod(0o600)
            target.parent.chmod(0o750)
            tampered_directory = bootstrap_transaction.transaction_recovery_status(
                project_root
            )
            self.assertEqual("invalid", tampered_directory.state, tampered_directory)
            target.parent.chmod(0o700)

            recovery = bootstrap_transaction.transaction_recovery_status(project_root)
            self.assertEqual("recovery-required", recovery.state, recovery)
            transaction_id = recovery.transaction_id
            if transaction_id is None:
                self.fail("recovery status omitted its transaction identity")

            recovered = bootstrap_transaction.rollback_interrupted_transaction(
                project_root,
                expected_transaction_id=transaction_id,
            )

            self.assertEqual("clean", recovered.state, recovered)
            self.assertTrue(project_root.is_dir())
            self.assertFalse((project_root / "nested").exists())
            self.assertEqual([], list(project_root.iterdir()))

    def test_project_bootstrap_verified_recovery_can_only_be_finalized(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / "project"
            project_root.mkdir()
            target = project_root / "first.md"
            target.write_text("old first\n", encoding="utf-8")

            with mock.patch.object(
                bootstrap_transaction,
                "_cleanup_committed_outputs",
                return_value=["injected retained cleanup"],
            ):
                result = bootstrap_transaction.transactional_write_outputs(
                    project_root,
                    [("first.md", "new first\n")],
                    force=True,
                )

            self.assertEqual(["injected retained cleanup"], result.cleanup_warnings)
            recovery = bootstrap_transaction.transaction_recovery_status(project_root)
            self.assertEqual("verified", recovery.state, recovery)
            self.assertFalse(recovery.can_rollback, recovery)
            self.assertTrue(recovery.can_finalize, recovery)
            transaction_id = recovery.transaction_id
            if transaction_id is None:
                self.fail("verified recovery status omitted its transaction identity")
            with self.assertRaisesRegex(
                bootstrap_transaction.BootstrapTransactionError,
                "does not permit rollback",
            ):
                bootstrap_transaction.rollback_interrupted_transaction(
                    project_root,
                    expected_transaction_id=transaction_id,
                )

            finalized = bootstrap_transaction.finalize_interrupted_transaction(
                project_root,
                expected_transaction_id=transaction_id,
            )
            self.assertEqual("clean", finalized.state, finalized)
            self.assertEqual("new first\n", target.read_text(encoding="utf-8"))
            self.assertEqual(
                [],
                list(project_root.rglob(".mpa-bootstrap-transaction-*")),
            )

    def test_bootstrap_cli_never_reports_success_with_verified_recovery_controls(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "project"
            project_root.mkdir()
            answers_path = root / "answers.json"
            _write_minimal_answers(answers_path)
            with (
                mock.patch.object(
                    bootstrap_transaction,
                    "_cleanup_committed_outputs",
                    return_value=["injected retained cleanup"],
                ),
                mock.patch(
                    "conformance_check.run_profiles",
                    return_value={"status": "pass", "errors": [], "warnings": []},
                ),
            ):
                code, stdout = _run_approved_project_bootstrap(
                    answers_path,
                    project_root,
                )
            payload = json.loads(stdout)
            recovery = bootstrap_transaction.transaction_recovery_status(project_root)
            transaction_id = recovery.transaction_id
            if transaction_id is None:
                self.fail("verified recovery state omitted its transaction identity")
            finalized = bootstrap_transaction.finalize_interrupted_transaction(
                project_root,
                expected_transaction_id=transaction_id,
            )

        self.assertEqual(project_bootstrap.EXIT_RECOVERY_REQUIRED, code, payload)
        self.assertEqual("recovery-required", payload["status"])
        self.assertEqual(transaction_id, payload["transaction_id"])
        self.assertTrue(payload["can_finalize"])
        self.assertEqual("finalize", payload["recovery_route"]["action"])
        self.assertEqual(
            transaction_id,
            payload["recovery_route"]["approve_transaction_id"],
        )
        self.assertIn("injected retained cleanup", payload["cleanup_warnings"])
        self.assertEqual(
            project_bootstrap.bootstrap_warnings_sha256(payload["warnings"]),
            payload["warnings_sha256"],
        )
        self.assertEqual("clean", finalized.state, finalized)

    def test_verified_retirement_rejects_a_late_unrelated_sibling(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            target = project_root / ".agents" / "skills" / "seo" / "SKILL.md"
            target.parent.mkdir(parents=True)
            target.write_text("managed wrapper\n", encoding="utf-8")

            with mock.patch.object(
                bootstrap_transaction,
                "_retire_empty_directories",
                return_value=["injected retained retirement"],
            ):
                result = bootstrap_transaction.transactional_write_outputs(
                    project_root,
                    [],
                    force=True,
                    remove_outputs=[".agents/skills/seo/SKILL.md"],
                    retire_empty_directories=[
                        ".agents",
                        ".agents/skills",
                        ".agents/skills/seo",
                    ],
                )
            self.assertEqual(["injected retained retirement"], result.cleanup_warnings)
            sibling = target.parent / "owner-note.txt"
            sibling.write_text("preserve\n", encoding="utf-8")

            recovery = bootstrap_transaction.transaction_recovery_status(project_root)

            self.assertEqual("invalid", recovery.state, recovery)
            self.assertTrue(
                any("unrelated entries" in error for error in recovery.errors),
                recovery,
            )
            self.assertEqual("preserve\n", sibling.read_text(encoding="utf-8"))
            self.assertTrue(
                (project_root / bootstrap_transaction.RECOVERY_JOURNAL_NAME).is_file()
            )

    def test_verified_retirement_rejects_directory_identity_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            target = project_root / ".agents" / "skills" / "seo" / "SKILL.md"
            target.parent.mkdir(parents=True)
            target.write_text("managed wrapper\n", encoding="utf-8")

            with mock.patch.object(
                bootstrap_transaction,
                "_retire_empty_directories",
                return_value=["injected retained retirement"],
            ):
                bootstrap_transaction.transactional_write_outputs(
                    project_root,
                    [],
                    force=True,
                    remove_outputs=[".agents/skills/seo/SKILL.md"],
                    retire_empty_directories=[
                        ".agents",
                        ".agents/skills",
                        ".agents/skills/seo",
                    ],
                )
            displaced = target.parent.with_name("displaced-seo")
            target.parent.rename(displaced)
            target.parent.mkdir()

            recovery = bootstrap_transaction.transaction_recovery_status(project_root)

            self.assertEqual("invalid", recovery.state, recovery)
            self.assertTrue(
                any("identity changed" in error for error in recovery.errors),
                recovery,
            )
            self.assertTrue(target.parent.is_dir())
            self.assertTrue(displaced.is_dir())

    def test_project_bootstrap_transaction_reports_post_commit_backup_cleanup_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / "project"
            project_root.mkdir()
            target = project_root / "first.md"
            target.write_text("old first\n", encoding="utf-8")
            real_lstat_at = bootstrap_transaction._lstat_at
            backup_lookups = 0

            def fail_post_commit_backup_lookup(
                directory: bootstrap_transaction._DirectoryBinding,
                name: str,
            ) -> os.stat_result | None:
                nonlocal backup_lookups
                if name == "backup-0":
                    backup_lookups += 1
                    if backup_lookups == 2:
                        raise OSError("injected post-commit backup cleanup failure")
                return real_lstat_at(directory, name)

            with mock.patch.object(
                bootstrap_transaction,
                "_lstat_at",
                side_effect=fail_post_commit_backup_lookup,
            ):
                result: bootstrap_transaction.BootstrapWriteResult = (
                    bootstrap_transaction.transactional_write_outputs(
                        project_root,
                        [("first.md", "new first\n")],
                        force=True,
                    )
                )

            installed = target.read_text(encoding="utf-8")

        self.assertEqual(2, backup_lookups)
        self.assertEqual(["first.md"], result.written)
        self.assertEqual("new first\n", installed)
        self.assertTrue(
            any(
                "injected post-commit backup cleanup failure" in warning
                for warning in result.cleanup_warnings
            ),
            result.cleanup_warnings,
        )

    def test_project_bootstrap_transaction_refuses_late_target_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / "project"
            project_root.mkdir()
            target = project_root / "first.md"
            displaced = project_root / "externally-displaced-first.md"
            target.write_text("old first\n", encoding="utf-8")
            real_verify = bootstrap_transaction._verify_target_snapshot
            replaced = False

            def replace_before_verify(record: object) -> None:
                nonlocal replaced
                if not replaced:
                    replaced = True
                    target.rename(displaced)
                    target.write_text("external replacement\n", encoding="utf-8")
                real_verify(cast(bootstrap_transaction._OutputTransactionRecord, record))

            with (
                mock.patch.object(
                    bootstrap_transaction,
                    "_verify_target_snapshot",
                    side_effect=replace_before_verify,
                ),
                self.assertRaisesRegex(
                    bootstrap_transaction.BootstrapTransactionError,
                    "changed or was replaced after preflight",
                ),
            ):
                bootstrap_transaction.transactional_write_outputs(
                    project_root,
                    [("first.md", "new first\n")],
                    force=True,
                )

            self.assertTrue(replaced)
            self.assertEqual("external replacement\n", target.read_text(encoding="utf-8"))
            self.assertEqual("old first\n", displaced.read_text(encoding="utf-8"))
            self.assertEqual(
                [],
                list(project_root.rglob(".mpa-bootstrap-transaction-*")),
            )

    def test_project_bootstrap_transaction_refuses_late_parent_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / "project"
            project_root.mkdir()
            parent = project_root / "nested"
            moved_parent = project_root / "externally-moved-nested"
            parent.mkdir()
            (parent / "first.md").write_text("old first\n", encoding="utf-8")
            real_install = bootstrap_transaction._install_staged_output
            replaced = False

            def replace_parent_before_install(
                record: object,
                index: int,
                bindings: list[bootstrap_transaction._DirectoryBinding],
            ) -> None:
                nonlocal replaced
                if not replaced:
                    replaced = True
                    parent.rename(moved_parent)
                    parent.mkdir()
                    (parent / "first.md").write_text(
                        "external replacement\n",
                        encoding="utf-8",
                    )
                real_install(
                    cast(bootstrap_transaction._OutputTransactionRecord, record),
                    index,
                    bindings,
                )

            with (
                mock.patch.object(
                    bootstrap_transaction,
                    "_install_staged_output",
                    side_effect=replace_parent_before_install,
                ),
                self.assertRaisesRegex(
                    bootstrap_transaction.BootstrapTransactionError,
                    "bound output directory was replaced",
                ),
            ):
                bootstrap_transaction.transactional_write_outputs(
                    project_root,
                    [("nested/first.md", "new first\n")],
                    force=True,
                )

            self.assertTrue(replaced)
            self.assertEqual(
                "external replacement\n",
                (parent / "first.md").read_text(encoding="utf-8"),
            )
            self.assertEqual(
                "old first\n",
                (moved_parent / "first.md").read_text(encoding="utf-8"),
            )
            self.assertEqual(
                [],
                list(project_root.rglob(".mpa-bootstrap-transaction-*")),
            )

    def test_project_bootstrap_transaction_requires_output_ownership(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "owned.md"
            target.write_text("existing\n", encoding="utf-8")
            metadata = target.stat()

            with (
                mock.patch.object(
                    bootstrap_transaction.os,
                    "geteuid",
                    return_value=metadata.st_uid + 1,
                ),
                self.assertRaisesRegex(ValueError, "must be owned by the bootstrap user"),
            ):
                bootstrap_transaction._require_owned_regular_output(
                    metadata,
                    description="existing bootstrap output owned.md",
                    require_single_link=True,
                )
