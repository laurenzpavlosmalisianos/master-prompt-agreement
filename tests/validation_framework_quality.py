"""Framework quality, doctrine-routing, and conformance validation tests."""

from __future__ import annotations

import errno
from html.parser import HTMLParser
import io
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from typing import Any
import unittest
from unittest import mock
import xml.etree.ElementTree as ET

from tests.validation_test_support import (
    REPO_ROOT,
    SCRIPTS_DIR,
    TestSubprocessOutputLimit,
    run_bounded,
)

import check_prereqs  # noqa: E402
import conformance_check  # noqa: E402
import framework_compliance  # noqa: E402
import framework_consistency  # noqa: E402
import framework_quality_lint  # noqa: E402
import integration_registry  # noqa: E402
import prompt_load_report  # noqa: E402
import project_bootstrap  # noqa: E402
import project_contract_sync  # noqa: E402
import public_surface  # noqa: E402
import query_clause_map  # noqa: E402
import recommend_stack  # noqa: E402
import safe_paths  # noqa: E402
import validate_framework  # noqa: E402
import verification_registry  # noqa: E402
import bounded_subprocess  # noqa: E402
from tests import validation_test_support as test_support


class ReadmeImageParser(HTMLParser):
    """Collect README image candidates with enough structure to model selection."""

    def __init__(self) -> None:
        super().__init__()
        self.images: list[dict[str, object]] = []
        self._picture_sources: list[dict[str, str]] | None = None

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attributes = {key: value or "" for key, value in attrs}
        if tag == "picture":
            self._picture_sources = []
        elif tag == "source" and self._picture_sources is not None:
            self._picture_sources.append(attributes)
        elif tag == "img":
            self.images.append(
                {
                    "img": attributes,
                    "sources": tuple(self._picture_sources or ()),
                }
            )

    def handle_endtag(self, tag: str) -> None:
        if tag == "picture":
            self._picture_sources = None


class ElementsByIdParser(HTMLParser):
    """Collect element names and attributes keyed by non-empty HTML IDs."""

    def __init__(self) -> None:
        super().__init__()
        self.elements: dict[str, list[tuple[str, dict[str, str]]]] = {}

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attributes = {key: value or "" for key, value in attrs}
        element_id = attributes.get("id")
        if element_id:
            self.elements.setdefault(element_id, []).append((tag, attributes))


def css_declarations(stylesheet: str, selector: str) -> dict[str, str]:
    """Return declarations from one top-level selector block."""

    block = re.search(
        rf"(?ms)^{re.escape(selector)}\s*\{{(?P<body>.*?)^\}}",
        stylesheet,
    )
    if block is None:
        raise AssertionError(f"missing CSS selector: {selector}")
    return {
        name: value.strip()
        for name, value in re.findall(
            r"(?m)^\s*([\w-]+)\s*:\s*([^;]+);",
            block.group("body"),
        )
    }


def css_hex_contrast(first: str, second: str) -> float:
    """Calculate the WCAG contrast ratio for two six-digit sRGB colors."""

    def luminance(value: str) -> float:
        match = re.fullmatch(r"#([0-9a-fA-F]{6})", value)
        if match is None:
            raise AssertionError(f"expected a six-digit sRGB color, got {value!r}")
        channels = [
            int(match.group(1)[offset : offset + 2], 16) / 255
            for offset in (0, 2, 4)
        ]
        linear = [
            channel / 12.92
            if channel <= 0.04045
            else ((channel + 0.055) / 1.055) ** 2.4
            for channel in channels
        ]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    lighter, darker = sorted((luminance(first), luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def selected_readme_image(
    image: dict[str, object],
    viewport_width: int,
) -> str:
    """Resolve the simple viewport media query used by repository docs."""

    sources = image["sources"]
    if not isinstance(sources, tuple):
        raise AssertionError("invalid parsed README source list")
    for source in sources:
        if not isinstance(source, dict):
            raise AssertionError("invalid parsed README source")
        match = re.fullmatch(r"\(max-width:\s*(\d+)px\)", source.get("media", ""))
        if match and viewport_width <= int(match.group(1)):
            return source.get("srcset", "").split()[0]
    fallback = image["img"]
    if not isinstance(fallback, dict):
        raise AssertionError("invalid parsed README image")
    return fallback.get("src", "")


class FrameworkQualityTests(unittest.TestCase):
    def test_bounded_test_subprocess_terms_kills_and_reaps_leader(self) -> None:
        process = mock.Mock()
        process.pid = 4242
        process.returncode = -signal.SIGKILL
        process.wait.return_value = -signal.SIGKILL
        with (
            mock.patch.object(bounded_subprocess, "_is_linux", return_value=False),
            mock.patch.object(
                bounded_subprocess,
                "_signal_process_group",
            ) as signal_group,
            mock.patch.object(bounded_subprocess.time, "sleep"),
        ):
            returncode = bounded_subprocess._terminate_failed_process(
                process,
                leader=None,
                grace_seconds=0.25,
            )
        self.assertEqual(-signal.SIGKILL, returncode)
        self.assertEqual(
            [
                mock.call(process, None, signal.SIGTERM),
                mock.call(process, None, signal.SIGKILL),
            ],
            signal_group.call_args_list,
        )
        process.wait.assert_called_once_with(timeout=0.25)

    def test_bounded_test_subprocess_surfaces_cleanup_failure(self) -> None:
        process = mock.Mock()
        process.pid = 4242
        process.returncode = None
        process.wait.side_effect = subprocess.TimeoutExpired(["fixture"], 0.25)
        with (
            mock.patch.object(bounded_subprocess, "_is_linux", return_value=False),
            mock.patch.object(bounded_subprocess, "_signal_process_group"),
            mock.patch.object(bounded_subprocess.time, "sleep"),
            self.assertRaises(test_support.TestSubprocessCleanupError),
        ):
            bounded_subprocess._terminate_failed_process(
                process,
                leader=None,
                grace_seconds=0.25,
            )

    def test_linux_subreaper_refuses_unsafe_preconditions_before_prctl(self) -> None:
        for task_ids, child_pids in (
            ((4242, 4243), ()),
            ((4242,), (9001,)),
        ):
            with (
                self.subTest(task_ids=task_ids, child_pids=child_pids),
                mock.patch.object(bounded_subprocess.os, "getpid", return_value=4242),
                mock.patch.object(
                    bounded_subprocess,
                    "_linux_task_ids",
                    return_value=task_ids,
                ),
                mock.patch.object(
                    bounded_subprocess,
                    "_linux_direct_child_pids",
                    return_value=child_pids,
                ),
                mock.patch.object(
                    bounded_subprocess,
                    "_assert_linux_pidfd_support",
                ),
                mock.patch.object(
                    bounded_subprocess,
                    "_linux_prctl_set_subreaper",
                ) as set_subreaper,
                self.assertRaises(
                    bounded_subprocess.BoundedSubprocessPreconditionError
                ),
            ):
                bounded_subprocess._LinuxSubreaperScope().activate()
            set_subreaper.assert_not_called()

    def test_linux_subreaper_restores_prior_state_after_empty_child_proof(self) -> None:
        scope = bounded_subprocess._LinuxSubreaperScope()
        with (
            mock.patch.object(bounded_subprocess.os, "getpid", return_value=4242),
            mock.patch.object(
                bounded_subprocess,
                "_linux_task_ids",
                return_value=(4242,),
            ),
            mock.patch.object(
                bounded_subprocess.signal,
                "getsignal",
                return_value=signal.SIG_DFL,
            ),
            mock.patch.object(bounded_subprocess, "_assert_linux_pidfd_support"),
            mock.patch.object(
                bounded_subprocess,
                "_linux_direct_child_pids",
                return_value=(),
            ),
            mock.patch.object(
                bounded_subprocess,
                "_linux_prctl_get_subreaper",
                side_effect=(0, 0),
            ),
            mock.patch.object(
                bounded_subprocess,
                "_linux_prctl_set_subreaper",
            ) as set_subreaper,
        ):
            scope.activate()
            scope.restore()
        self.assertEqual([mock.call(1), mock.call(0)], set_subreaper.call_args_list)

    def test_linux_child_signals_use_revalidated_pidfd_identity(self) -> None:
        record = bounded_subprocess._LinuxProcessRecord(9001, 4242, 9001, 9001, 7)
        with (
            mock.patch.object(bounded_subprocess.os, "getpid", return_value=4242),
            mock.patch.object(
                bounded_subprocess.os,
                "pidfd_open",
                return_value=77,
                create=True,
            ) as pidfd_open,
            mock.patch.object(
                bounded_subprocess,
                "_linux_read_process",
                return_value=record,
            ),
            mock.patch.object(
                bounded_subprocess.signal,
                "pidfd_send_signal",
                create=True,
            ) as pidfd_signal,
            mock.patch.object(bounded_subprocess.os, "close") as close,
        ):
            bounded_subprocess._signal_linux_child(record, signal.SIGKILL)
        pidfd_open.assert_called_once_with(9001, 0)
        pidfd_signal.assert_called_once_with(77, signal.SIGKILL)
        close.assert_called_once_with(77)

    def test_linux_child_inventory_uses_stable_proc_scan_without_children_file(self) -> None:
        record = bounded_subprocess._LinuxProcessRecord(9001, 4242, 9001, 9001, 7)
        with (
            mock.patch.object(
                bounded_subprocess,
                "_linux_children_file_pids",
                return_value=None,
            ),
            mock.patch.object(
                bounded_subprocess,
                "_linux_proc_direct_children_snapshot",
                side_effect=((record,), (record,)),
            ) as scan,
        ):
            child_pids = bounded_subprocess._linux_direct_child_pids()
        self.assertEqual((9001,), child_pids)
        self.assertEqual(2, scan.call_count)

    def test_linux_process_identity_treats_esrch_as_transient_disappearance(self) -> None:
        with mock.patch.object(
            Path,
            "read_bytes",
            side_effect=ProcessLookupError(errno.ESRCH, "process disappeared"),
        ):
            self.assertIsNone(bounded_subprocess._linux_read_process(9001))

        with (
            mock.patch.object(
                Path,
                "read_bytes",
                side_effect=PermissionError(errno.EACCES, "permission denied"),
            ),
            self.assertRaisesRegex(
                bounded_subprocess.BoundedSubprocessCleanupError,
                "could not inspect Linux process identity",
            ),
        ):
            bounded_subprocess._linux_read_process(9001)

        vanished_entry = mock.Mock()
        vanished_entry.name = "9001"
        proc_entries = mock.MagicMock()
        proc_entries.__enter__.return_value = [vanished_entry]
        with (
            mock.patch.object(
                bounded_subprocess.os,
                "scandir",
                return_value=proc_entries,
            ),
            mock.patch.object(
                bounded_subprocess,
                "_linux_read_process",
                return_value=None,
            ),
        ):
            self.assertEqual((), bounded_subprocess._linux_proc_direct_children_snapshot())

    def test_linux_process_identity_ignores_non_ascii_process_name_bytes(self) -> None:
        stat_record = (
            b"9001 (worker-\xff) S 4242 9001 9001 "
            + (b"0 " * 15)
            + b"7\n"
        )
        with mock.patch.object(Path, "read_bytes", return_value=stat_record):
            record = bounded_subprocess._linux_read_process(9001)
        self.assertEqual(
            bounded_subprocess._LinuxProcessRecord(9001, 4242, 9001, 9001, 7),
            record,
        )

    def test_bounded_test_subprocess_rejects_invalid_limits_before_spawn(self) -> None:
        invalid: tuple[dict[str, Any], ...] = (
            {"timeout_seconds": True},
            {"timeout_seconds": float("nan")},
            {"timeout_seconds": float("inf")},
            {"timeout_seconds": 10**10000},
            {"timeout_seconds": test_support.TEST_SUBPROCESS_MAX_TIMEOUT_SECONDS + 1},
            {"max_output_bytes": True},
            {"max_output_bytes": 1.5},
            {
                "max_output_bytes": (
                    test_support.TEST_SUBPROCESS_MAX_OUTPUT_LIMIT_BYTES + 1
                )
            },
        )
        with mock.patch.object(bounded_subprocess.subprocess, "Popen") as popen:
            for overrides in invalid:
                with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                    run_bounded(
                        [sys.executable, "-c", "pass"],
                        cwd=REPO_ROOT,
                        **overrides,
                    )
        popen.assert_not_called()

    def test_bounded_subprocess_rejects_invalid_invocations_before_spawn(self) -> None:
        command = [sys.executable, "-c", "pass"]
        valid_kwargs: dict[str, Any] = {
            "cwd": REPO_ROOT,
            "timeout_seconds": 1.0,
            "max_output_bytes": 1024,
            "maximum_timeout_seconds": 5.0,
            "maximum_output_bytes": 4096,
            "termination_grace_seconds": 0.25,
        }
        cases: tuple[tuple[str, Any, dict[str, Any]], ...] = (
            (
                "maximum-timeout-nan",
                command,
                {"maximum_timeout_seconds": float("nan")},
            ),
            (
                "maximum-timeout-infinite",
                command,
                {"maximum_timeout_seconds": float("inf")},
            ),
            (
                "maximum-timeout-unrepresentable",
                command,
                {"maximum_timeout_seconds": 10**10000},
            ),
            (
                "maximum-timeout-above-hard-limit",
                command,
                {
                    "maximum_timeout_seconds": (
                        bounded_subprocess.HARD_MAX_TIMEOUT_SECONDS + 1
                    )
                },
            ),
            (
                "maximum-output-boolean",
                command,
                {"maximum_output_bytes": True},
            ),
            (
                "maximum-output-above-hard-limit",
                command,
                {
                    "maximum_output_bytes": (
                        bounded_subprocess.HARD_MAX_OUTPUT_BYTES + 1
                    )
                },
            ),
            (
                "termination-grace-infinite",
                command,
                {"termination_grace_seconds": float("inf")},
            ),
            (
                "termination-grace-unrepresentable",
                command,
                {"termination_grace_seconds": 10**10000},
            ),
            ("environment-non-string-value", command, {"env": {"VALID": 7}}),
            ("environment-invalid-key", command, {"env": {"BAD=KEY": "value"}}),
            (
                "environment-null-byte",
                command,
                {"env": {"VALID": "bad\0value"}},
            ),
            ("command-is-string", "python -c pass", {}),
            ("command-has-non-string-argument", [sys.executable, 7], {}),
            ("command-has-null-byte", [sys.executable, "bad\0argument"], {}),
        )

        with mock.patch.object(bounded_subprocess.subprocess, "Popen") as popen:
            for name, candidate_command, overrides in cases:
                with self.subTest(name=name), self.assertRaises(ValueError):
                    bounded_subprocess.run_bounded_process(
                        candidate_command,
                        **{**valid_kwargs, **overrides},
                    )
                popen.assert_not_called()
                popen.reset_mock()

    def test_bounded_subprocess_passes_live_descriptor_to_child(self) -> None:
        payload = b"descriptor-bound payload\x00with raw bytes\xff\n"
        read_descriptor, write_descriptor = os.pipe()
        try:
            self.assertGreaterEqual(read_descriptor, 3)
            self.assertEqual(len(payload), os.write(write_descriptor, payload))
            os.close(write_descriptor)
            write_descriptor = -1

            result = bounded_subprocess.run_bounded_process(
                [
                    sys.executable,
                    "-I",
                    "-S",
                    "-B",
                    "-c",
                    (
                        "import os, sys; "
                        "payload = os.read(int(sys.argv[1]), 4096); "
                        "os.write(1, payload)"
                    ),
                    str(read_descriptor),
                ],
                cwd=REPO_ROOT,
                pass_fds=(read_descriptor,),
                timeout_seconds=2.0,
                max_output_bytes=4096,
                maximum_timeout_seconds=5.0,
                maximum_output_bytes=8192,
                termination_grace_seconds=0.25,
            )
        finally:
            os.close(read_descriptor)
            if write_descriptor >= 0:
                os.close(write_descriptor)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(payload, result.stdout)
        self.assertEqual(b"", result.stderr)
        self.assertFalse(result.timed_out)
        self.assertFalse(result.output_exceeded)

    def test_bounded_subprocess_rejects_stdio_descriptor_before_spawn(self) -> None:
        with (
            mock.patch.object(bounded_subprocess.subprocess, "Popen") as popen,
            self.assertRaisesRegex(ValueError, "integers >= 3"),
        ):
            bounded_subprocess.run_bounded_process(
                [sys.executable, "-c", "pass"],
                cwd=REPO_ROOT,
                pass_fds=(2,),
                timeout_seconds=1.0,
                max_output_bytes=1024,
                maximum_timeout_seconds=5.0,
                maximum_output_bytes=4096,
                termination_grace_seconds=0.25,
            )
        popen.assert_not_called()

    def test_bounded_subprocess_rejects_duplicate_descriptors_before_spawn(self) -> None:
        read_descriptor, write_descriptor = os.pipe()
        try:
            with (
                mock.patch.object(bounded_subprocess.subprocess, "Popen") as popen,
                self.assertRaisesRegex(ValueError, "must not contain duplicates"),
            ):
                bounded_subprocess.run_bounded_process(
                    [sys.executable, "-c", "pass"],
                    cwd=REPO_ROOT,
                    pass_fds=(read_descriptor, read_descriptor),
                    timeout_seconds=1.0,
                    max_output_bytes=1024,
                    maximum_timeout_seconds=5.0,
                    maximum_output_bytes=4096,
                    termination_grace_seconds=0.25,
                )
            popen.assert_not_called()
        finally:
            os.close(read_descriptor)
            os.close(write_descriptor)

    def test_bounded_subprocess_rejects_closed_descriptor_before_spawn(self) -> None:
        closed_descriptor, peer_descriptor = os.pipe()
        os.close(closed_descriptor)
        try:
            with (
                mock.patch.object(bounded_subprocess.subprocess, "Popen") as popen,
                self.assertRaisesRegex(ValueError, "invalid descriptor"),
            ):
                bounded_subprocess.run_bounded_process(
                    [sys.executable, "-c", "pass"],
                    cwd=REPO_ROOT,
                    pass_fds=(closed_descriptor,),
                    timeout_seconds=1.0,
                    max_output_bytes=1024,
                    maximum_timeout_seconds=5.0,
                    maximum_output_bytes=4096,
                    termination_grace_seconds=0.25,
                )
            popen.assert_not_called()
        finally:
            os.close(peer_descriptor)

    def test_bounded_test_subprocess_terminates_hanging_child(self) -> None:
        started = time.monotonic()
        with self.assertRaises(subprocess.TimeoutExpired):
            run_bounded(
                [sys.executable, "-I", "-S", "-B", "-c", "import time; time.sleep(30)"],
                cwd=REPO_ROOT,
                timeout_seconds=0.2,
                max_output_bytes=1024,
            )
        self.assertLess(time.monotonic() - started, 2.0)

    def test_bounded_test_subprocess_terminates_output_flood(self) -> None:
        child_timeout_seconds = 2.0
        # The output-limit exception is the semantic oracle. This looser bound
        # only guards cleanup liveness and therefore includes the configured
        # 0.25-second termination grace plus scheduler allowance.
        cleanup_scheduler_bound_seconds = (
            child_timeout_seconds
            + test_support.TEST_SUBPROCESS_TERMINATION_GRACE_SECONDS
            + 1.0
        )
        started = time.monotonic()
        with self.assertRaises(TestSubprocessOutputLimit):
            run_bounded(
                [
                    sys.executable,
                    "-I",
                    "-S",
                    "-B",
                    "-c",
                    "import os; os.write(1, b'x' * 1048576)",
                ],
                cwd=REPO_ROOT,
                timeout_seconds=child_timeout_seconds,
                max_output_bytes=1024,
            )
        self.assertLess(
            time.monotonic() - started,
            cleanup_scheduler_bound_seconds,
        )

    def test_bounded_test_subprocess_caps_combined_stdout_and_stderr(self) -> None:
        with self.assertRaises(TestSubprocessOutputLimit):
            run_bounded(
                [
                    sys.executable,
                    "-I",
                    "-S",
                    "-B",
                    "-c",
                    "import os; os.write(1, b'x' * 700); os.write(2, b'y' * 700)",
                ],
                cwd=REPO_ROOT,
                timeout_seconds=2.0,
                max_output_bytes=1024,
            )

    def test_framework_consistency_schema_versions_require_exact_json_integers(self) -> None:
        self.assertTrue(framework_consistency.exact_schema_version(1, 1))
        self.assertTrue(framework_consistency.exact_schema_version(2, 2))
        for value in (True, False, 0, 2, 1.0, "1", None):
            with self.subTest(value=value):
                self.assertFalse(
                    framework_consistency.exact_schema_version(value, 1)
                )

    def test_framework_quality_lint_accepts_current_contract(self) -> None:
        errors = framework_quality_lint.validate(
            REPO_ROOT,
            REPO_ROOT / "runtime" / "framework_quality_contract.json",
        )
        self.assertEqual([], errors)

    def test_framework_improvement_is_a_required_public_quality_surface(self) -> None:
        rel = "task_orders/framework_improvement.md"
        contract = validate_framework.load_json(
            REPO_ROOT / "runtime" / "framework_quality_contract.json"
        )

        with self.subTest(owner="framework quality contract"):
            self.assertIn(rel, contract["required_task_orders"])
        with self.subTest(owner="public required surface"):
            self.assertIn(rel, public_surface.PUBLIC_REQUIRED_FILES)

    def test_claim_grade_contract_distinguishes_exact_and_inferential_evidence(self) -> None:
        improvement = (
            REPO_ROOT / "task_orders" / "framework_improvement.md"
        ).read_text(encoding="utf-8")
        normalized_improvement = " ".join(improvement.split())
        for required in (
            "public inferential or estimated quantitative claim",
            "exact deterministic quantity",
            "prospectively fixed analysis or inference method",
            "before the first confirmatory access",
            "Authorized role-bounded evaluation delivery is not contamination",
            "separately stated independence, treatment masking, and calibration",
        ):
            self.assertIn(required, normalized_improvement)
        self.assertNotIn("before final confirmation", normalized_improvement)

        insights = (REPO_ROOT / "task_orders" / "insights.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("owned by `task_orders/framework_improvement.md`", insights)
        self.assertNotIn("matched or ablation protocol with fixed evidence", insights)

        orchestration = (REPO_ROOT / "task_orders" / "orchestrate.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("correlation label, not proof", orchestration)
        self.assertIn("actual context inheritance", orchestration)
        self.assertIn("correlated or non-blind", orchestration)

    def test_framework_quality_lint_rejects_missing_guide_owner(self) -> None:
        contract_path = REPO_ROOT / "runtime" / "framework_quality_contract.json"
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        contract["guide_surface_roles"] = [
            item
            for item in contract["guide_surface_roles"]
            if item["path"] != "practice_guides/prompt_agent_quality.md"
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            candidate = Path(temp_dir) / "framework_quality_contract.json"
            candidate.write_text(json.dumps(contract), encoding="utf-8")
            errors = framework_quality_lint.validate(REPO_ROOT, candidate)

        self.assertTrue(
            any("practice guides missing ownership map entries" in error for error in errors),
            errors,
        )

    def test_framework_quality_lint_rejects_duplicate_owned_concepts(self) -> None:
        contract_path = REPO_ROOT / "runtime" / "framework_quality_contract.json"
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        duplicate_owner = "duplicated invariant owner"
        contract["guide_surface_roles"][0]["owns"] = [duplicate_owner]
        contract["guide_surface_roles"][1]["owns"] = [duplicate_owner]

        with tempfile.TemporaryDirectory() as temp_dir:
            candidate = Path(temp_dir) / "framework_quality_contract.json"
            candidate.write_text(json.dumps(contract), encoding="utf-8")
            errors = framework_quality_lint.validate(REPO_ROOT, candidate)

        self.assertTrue(
            any("duplicate owned quality concepts" in error for error in errors),
            errors,
        )

    def test_framework_quality_lint_rejects_missing_required_task_order(self) -> None:
        contract_path = REPO_ROOT / "runtime" / "framework_quality_contract.json"
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        contract["required_task_orders"] = ["task_orders/not-a-real-order.md"]

        with tempfile.TemporaryDirectory() as temp_dir:
            candidate = Path(temp_dir) / "framework_quality_contract.json"
            candidate.write_text(json.dumps(contract), encoding="utf-8")
            errors = framework_quality_lint.validate(REPO_ROOT, candidate)

        self.assertTrue(any("required quality task order missing" in error for error in errors), errors)
        self.assertTrue(any("missing from workflow catalog" in error for error in errors), errors)

    def test_framework_quality_lint_rejects_invalid_guard_metadata(self) -> None:
        contract_path = REPO_ROOT / "runtime" / "framework_quality_contract.json"
        original = json.loads(contract_path.read_text(encoding="utf-8"))
        cases = (
            ("unknown guard kind", "guard_kind", "automatic", "must define guard_kind as one of"),
            ("blank guard", "guard", " ", "must define guard"),
        )

        for label, field, value, expected_error in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temp_dir:
                contract = json.loads(json.dumps(original))
                contract["repeated_mistake_classes"][0][field] = value
                candidate = Path(temp_dir) / "framework_quality_contract.json"
                candidate.write_text(json.dumps(contract), encoding="utf-8")
                errors = framework_quality_lint.validate(REPO_ROOT, candidate)

            self.assertTrue(any(expected_error in error for error in errors), errors)

    def test_framework_quality_lint_rejects_guard_kind_overclaims(self) -> None:
        contract_path = REPO_ROOT / "runtime" / "framework_quality_contract.json"
        original = json.loads(contract_path.read_text(encoding="utf-8"))
        cases = (
            ("vendor-specific-public-doctrine", "deterministic"),
            ("unbounded-reviewer-lane", "structural_presence"),
        )

        for class_id, overclaim in cases:
            with self.subTest(class_id=class_id), tempfile.TemporaryDirectory() as temp_dir:
                contract = json.loads(json.dumps(original))
                mistake_class = next(
                    item
                    for item in contract["repeated_mistake_classes"]
                    if item["id"] == class_id
                )
                mistake_class["guard_kind"] = overclaim
                candidate = Path(temp_dir) / "framework_quality_contract.json"
                candidate.write_text(json.dumps(contract), encoding="utf-8")
                errors = framework_quality_lint.validate(REPO_ROOT, candidate)

            self.assertIn(
                f"repeated_mistake_classes {class_id} "
                "guard_kind must be semantic_review",
                errors,
            )

    def test_framework_quality_lint_rejects_each_missing_required_mistake_class(
        self,
    ) -> None:
        contract_path = REPO_ROOT / "runtime" / "framework_quality_contract.json"
        original = json.loads(contract_path.read_text(encoding="utf-8"))

        for class_id in sorted(framework_quality_lint.REQUIRED_MISTAKE_CLASS_IDS):
            with self.subTest(class_id=class_id), tempfile.TemporaryDirectory() as temp_dir:
                contract = json.loads(json.dumps(original))
                contract["repeated_mistake_classes"] = [
                    item
                    for item in contract["repeated_mistake_classes"]
                    if item["id"] != class_id
                ]
                candidate = Path(temp_dir) / "framework_quality_contract.json"
                candidate.write_text(json.dumps(contract), encoding="utf-8")
                errors = framework_quality_lint.validate(REPO_ROOT, candidate)

            self.assertIn(f"missing repeated mistake classes: {class_id}", errors)

    def test_prompt_load_budget_uses_bytes_only_for_loaded_surfaces(self) -> None:
        budgets = prompt_load_report.loaded_surface_byte_budgets(REPO_ROOT)
        self.assertFalse(
            any(path.startswith("practice_guides/") for path in budgets),
            budgets,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "entrypoint.md").write_text("x" * 9, encoding="utf-8")
            errors = prompt_load_report.loaded_surface_budget_errors(
                root,
                {"entrypoint.md": 8},
            )

        self.assertEqual(
            [
                "configured loaded-surface file-size ceiling exceeded: entrypoint.md has "
                "9 UTF-8 bytes, limit is 8"
            ],
            errors,
        )

    def test_root_agents_md_is_validated_as_public_template_surface(self) -> None:
        self.assertIn("AGENTS.md", validate_framework.PUBLIC_ROOTS)
        self.assertIn("AGENTS.md", validate_framework.PUBLIC_TEMPLATE_ROOTS)
        self.assertIn("CLAUDE.md", validate_framework.PUBLIC_ROOTS)
        self.assertIn("CLAUDE.md", validate_framework.PUBLIC_TEMPLATE_ROOTS)
        self.assertIn(
            ".agents/skills/master-prompt-refresh-project",
            validate_framework.PUBLIC_TEMPLATE_ROOTS,
        )
        self.assertIn(".gitignore", validate_framework.PUBLIC_ROOTS)
        self.assertIn("scripts", validate_framework.PUBLIC_ROOTS)
        self.assertIn("tests", validate_framework.PUBLIC_ROOTS)

    def test_security_wording_guard_ignores_warnings_and_fenced_examples(
        self,
    ) -> None:
        sample = REPO_ROOT / "README.md"

        def errors_for(text: str) -> list[str]:
            with (
                mock.patch.object(validate_framework, "STANDARD_SURFACE_LINKS", {}),
                mock.patch.object(validate_framework, "SECURITY_REQUIRED_HEADINGS", ()),
                mock.patch.object(
                    validate_framework,
                    "public_text_files",
                    return_value=[sample],
                ),
                mock.patch.object(
                    validate_framework,
                    "read_text_if_file",
                    return_value=text,
                ),
            ):
                return validate_framework.standards_surface_errors()

        self.assertEqual(
            [],
            errors_for("Do not claim that this guarantees security.\n"),
        )
        self.assertEqual(
            [],
            errors_for("```markdown\nThis framework guarantees security.\n```\n"),
        )
        self.assertEqual(
            [
                "security affirmative-wording guard matched phrase "
                "'guarantees security' in public file: README.md"
            ],
            errors_for("This framework guarantees security.\n"),
        )

    def test_interactive_docs_current_surface_passes_boundary_checks(self) -> None:
        self.assertEqual([], validate_framework.interactive_docs_errors(REPO_ROOT))

        for rel in ("docs/interactive/app.ts", "docs/interactive/app.js"):
            script = (REPO_ROOT / rel).read_text(encoding="utf-8")
            learning_match = re.search(
                r'id: "learning",(?P<body>.*?)caption:',
                script,
                flags=re.DOTALL,
            )
            self.assertIsNotNone(learning_match, rel)
            learning = learning_match.group("body") if learning_match else ""
            labels = (
                "candidate evidence",
                "semantic audit",
                "accepted improvement",
                "verified disposition",
            )
            for label in labels:
                self.assertIn(label, learning, rel)
            positions = [learning.index(label) for label in labels]
            self.assertEqual(sorted(positions), positions, rel)
            learning_step_match = re.search(
                r'title: "Learning",\s*body: "(?P<body>[^"]+)",',
                script,
            )
            self.assertIsNotNone(learning_step_match, rel)
            learning_step = (
                learning_step_match.group("body") if learning_step_match else ""
            )
            route_paths = (
                "task_orders/framework_semantic_audit.md",
                "task_orders/framework_improvement.md",
            )
            for route_path in route_paths:
                self.assertIn(route_path, learning_step, rel)
            route_positions = [learning_step.index(path) for path in route_paths]
            self.assertEqual(sorted(route_positions), route_positions, rel)

    def test_interactive_diagram_uses_conforming_group_naming(self) -> None:
        parser = ElementsByIdParser()
        parser.feed(
            (REPO_ROOT / "docs" / "interactive" / "index.html").read_text(
                encoding="utf-8"
            )
        )

        architecture_matches = parser.elements.get("architecture-diagram", [])
        controls_matches = parser.elements.get("diagram-controls", [])
        self.assertEqual(1, len(architecture_matches))
        self.assertEqual(1, len(controls_matches))

        architecture_tag, architecture_attrs = architecture_matches[0]
        controls_tag, controls_attrs = controls_matches[0]
        self.assertEqual("div", architecture_tag)
        self.assertNotIn("aria-label", architecture_attrs)
        self.assertNotIn("aria-labelledby", architecture_attrs)
        self.assertEqual("div", controls_tag)
        self.assertEqual("group", controls_attrs.get("role"))
        self.assertTrue((controls_attrs.get("aria-label") or "").strip())

    def test_interactive_diagram_functional_boundaries_meet_non_text_contrast(
        self,
    ) -> None:
        stylesheet = (
            REPO_ROOT / "docs" / "interactive" / "styles.css"
        ).read_text(encoding="utf-8")
        palette = css_declarations(stylesheet, ":root")
        functional_border = palette["--functional-border"]

        self.assertNotEqual(palette["--border"], functional_border)
        self.assertEqual(
            "var(--functional-border)",
            css_declarations(stylesheet, ".diagram-node rect")["stroke"],
        )
        self.assertEqual(
            "var(--functional-border)",
            css_declarations(stylesheet, ".diagram-button")["border"].split()[-1],
        )
        for adjacent_surface in ("--surface", "--surface-strong"):
            with self.subTest(adjacent_surface=adjacent_surface):
                self.assertGreaterEqual(
                    css_hex_contrast(
                        functional_border,
                        palette[adjacent_surface],
                    ),
                    3.0,
                )

    def test_interactive_navigation_requires_exported_files_and_valid_fragments(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            interactive = root / "docs" / "interactive"
            task_orders = root / "task_orders"
            practice_guides = root / "practice_guides"
            interactive.mkdir(parents=True)
            task_orders.mkdir()
            practice_guides.mkdir()
            (task_orders / "README.md").write_text("# Task Orders\n", encoding="utf-8")
            script = (
                'href: "../../practice_guides/"\n'
                'href: "../../task_orders/README.md#missing-section"\n'
            )

            errors = validate_framework.interactive_navigation_errors(
                root,
                "docs/interactive/app.ts",
                script,
            )

        self.assertIn(
            "docs/interactive/app.ts navigation href must resolve to a regular public file: "
            "../../practice_guides/",
            errors,
        )
        self.assertIn(
            "docs/interactive/app.ts navigation href points to a missing fragment: "
            "../../task_orders/README.md#missing-section",
            errors,
        )

    def test_interactive_docs_rejects_drift_and_external_resources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            interactive = root / "docs" / "interactive"
            interactive.mkdir(parents=True)
            (interactive / "README.md").write_text("# Interactive\n", encoding="utf-8")
            (interactive / "index.html").write_text(
                '<link rel="stylesheet" href="https://cdn.example/style.css">\n'
                '<a href="#missing">Missing</a>\n'
                '<script type="module" src="https://cdn.example/app.js"></script>\n',
                encoding="utf-8",
            )
            (interactive / "styles.css").write_text('@import "https://cdn.example/base.css";\n', encoding="utf-8")
            (interactive / "app.ts").write_text('fetch("https://example.com/data.json");\n', encoding="utf-8")
            (interactive / "app.js").write_text('fetch("https://example.com/data.json");\n', encoding="utf-8")
            (interactive / "tsconfig.json").write_text("{}\n", encoding="utf-8")

            errors = validate_framework.interactive_docs_errors(root)

        self.assertTrue(any("source-of-truth boundary" in error for error in errors), errors)
        self.assertTrue(any("allowed human-explanation use" in error for error in errors), errors)
        self.assertTrue(any("fragment link points to missing id" in error for error in errors), errors)
        self.assertTrue(any("must not load external or file resource" in error for error in errors), errors)
        self.assertTrue(any("must not import or reference remote resources" in error for error in errors), errors)
        self.assertTrue(any("must not fetch or import remote resources" in error for error in errors), errors)
        self.assertTrue(any("must build SVG through DOM namespace APIs" in error for error in errors), errors)

    def test_interactive_docs_rejects_unpinned_compiler_and_target_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            interactive = root / "docs" / "interactive"
            shutil.copytree(REPO_ROOT / "docs" / "interactive", interactive)
            readme = interactive / "README.md"
            readme.write_text(
                readme.read_text(encoding="utf-8").replace(
                    "TypeScript 7.0.2",
                    "typescript@latest via npm exec --package",
                ),
                encoding="utf-8",
            )
            tsconfig_path = interactive / "tsconfig.json"
            tsconfig = json.loads(tsconfig_path.read_text(encoding="utf-8"))
            tsconfig["compilerOptions"]["target"] = "ES2025"
            tsconfig_path.write_text(json.dumps(tsconfig), encoding="utf-8")

            errors = validate_framework.interactive_docs_errors(root)

        self.assertTrue(any("pinned non-mutating compiler" in error for error in errors), errors)
        self.assertTrue(any("must not fetch or select an unpinned compiler" in error for error in errors), errors)
        self.assertIn("docs/interactive/tsconfig.json target must be ES2022", errors)

    def test_check_prereqs_no_uv_warning_uses_no_bytecode_fallback(self) -> None:
        def fake_which(tool: str) -> str | None:
            return None if tool == "uv" else f"/usr/bin/{tool}"

        with mock.patch("check_prereqs.shutil.which", side_effect=fake_which):
            with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                result = check_prereqs.main()

        report = json.loads(stdout.getvalue())
        self.assertEqual(0, result)
        qualified_runner = shlex.join((str(Path(sys.executable).resolve()), "-B"))
        self.assertEqual(qualified_runner, report["runner"])
        self.assertTrue(report["runner_usable"])
        self.assertIn("remain unqualified", report["warnings"][0])
        self.assertIn(
            qualified_runner,
            report["commands"]["normal_framework_commands"],
        )
        self.assertNotIn("framework_compliance", report["commands"])
        self.assertTrue(
            report["commands"]["framework_compliance_authoring_source"].endswith(
                "scripts/framework_compliance.py --tree-role authoring-source"
            )
        )
        self.assertTrue(
            report["commands"]["framework_compliance_public_export"].endswith(
                "scripts/framework_compliance.py --tree-role public-export"
            )
        )
        self.assertFalse(public_surface.is_public_excluded("pyrightconfig.json"))
        self.assertIn("pyrightconfig.json", public_surface.PUBLIC_ROOTS)
        self.assertIn("pyrightconfig.json", public_surface.PUBLIC_REQUIRED_FILES)
        self.assertTrue(
            safe_paths.contains_local_absolute_path("/" + "workspace" + "/project-set/example/repo")
        )
        self.assertTrue(safe_paths.contains_local_absolute_path("/" + "Volumes" + "/Drive/repo"))
        self.assertTrue(safe_paths.contains_local_absolute_path("/" + "opt/company/repo"))
        self.assertTrue(safe_paths.contains_local_absolute_path("/" + "tmp/example"))
        self.assertTrue(safe_paths.contains_local_absolute_path("/" + "workspace/example"))
        self.assertTrue(safe_paths.contains_local_absolute_path("/" + "mnt/example"))
        self.assertTrue(
            safe_paths.contains_local_absolute_path("C:" + "/" + "Users" + "/" + "example" + "/" + "repo")
        )
        self.assertTrue(safe_paths.contains_local_absolute_path("D:" + "\\" + "work" + "\\" + "repo"))

    def test_check_prereqs_requires_transaction_platform_primitives(self) -> None:
        self.assertTrue(check_prereqs.descriptor_safe_io_supported())

        with mock.patch(
            "check_prereqs.bootstrap_transaction.transaction_capability_errors",
            return_value=("missing os.open dir_fd support",),
        ):
            self.assertFalse(check_prereqs.descriptor_safe_io_supported())

        with (
            mock.patch(
                "check_prereqs.bootstrap_transaction.transaction_capability_errors",
                return_value=("missing os.open dir_fd support",),
            ),
            mock.patch("check_prereqs.shutil.which", return_value="/usr/bin/tool"),
            mock.patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            result = check_prereqs.main()

        report = json.loads(stdout.getvalue())
        self.assertEqual(1, result)
        self.assertFalse(report["runner_usable"])
        self.assertFalse(
            report["platform_capabilities"]["native_windows_supported"]
        )
        self.assertFalse(
            report["platform_capabilities"]["transaction_platform_primitives"]
        )
        self.assertEqual(
            ["missing os.open dir_fd support"],
            report["platform_capabilities"]["transaction_capability_errors"],
        )
        self.assertTrue(
            any(
                "transaction primitives" in error
                for error in report["errors"]
            ),
            report["errors"],
        )
        self.assertIn(
            "selected project filesystem",
            report["platform_capabilities"]["qualification_scope"],
        )

    def test_check_prereqs_advertises_a_parseable_bootstrap_dry_run(self) -> None:
        with (
            mock.patch("check_prereqs.shutil.which", return_value="/usr/bin/tool"),
            mock.patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            result = check_prereqs.main()

        self.assertEqual(0, result)
        report = json.loads(stdout.getvalue())
        command = report["commands"]["project_bootstrap_dry_run"]
        argv = shlex.split(command)
        script_index = next(
            index
            for index, argument in enumerate(argv)
            if argument.endswith("/scripts/project_bootstrap.py")
        )
        self.assertTrue(
            argv[script_index].startswith("<framework-checkout-as-visible-to-runner>/")
        )
        parser_args = [
            {
                "<temporary-answers-json>": "answers.json",
                "/path/to/project": "project",
                "<codex|claude-code|generic>": "codex",
                "<live|pinned>": "live",
            }.get(argument, argument)
            for argument in argv[script_index + 1 :]
        ]

        options = project_bootstrap.build_parser().parse_args(parser_args)

        self.assertTrue(options.dry_run)
        self.assertEqual("live", options.framework_revision_policy)

    def test_check_prereqs_does_not_promote_an_unexecuted_candidate_launcher(self) -> None:
        def fake_which(tool: str) -> str | None:
            if tool in {"uv", "python3"}:
                return None
            return f"/usr/bin/{tool}"

        with mock.patch("check_prereqs.shutil.which", side_effect=fake_which):
            with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                result = check_prereqs.main()

        report = json.loads(stdout.getvalue())
        self.assertEqual(0, result)
        self.assertEqual(
            shlex.join((str(Path(sys.executable).resolve()), "-B")),
            report["runner"],
        )
        self.assertNotEqual("/usr/bin/py -3 -B", report["runner"])
        self.assertIn(
            "py -3 -B",
            report["runners"]["unqualified_candidate_order"],
        )
        self.assertIn(
            "exact Python executable",
            report["runners"]["qualification_basis"],
        )
        self.assertIn("project-recorded runner", report["runners"]["project_command_policy"])
        for rel in (
            ".env",
            ".env.local",
            ".envrc",
            ".netrc",
            ".npmrc",
            ".pypirc",
            "pip.conf",
            "credentials.json",
            "token.json",
            "FRAMEWORK_FEEDBACK.md",
            "REVIEWER_LANE_FEEDBACK.md",
            "SECURITY_VERIFICATION.md",
            "client_secret-prod.json",
            "service-account-prod.json",
            "google-credentials-prod.json",
            "id_rsa",
            "id_rsa.key",
            "id_rsa.pub",
            "id_ed25519",
            "id_ed25519.pub",
            "vault.kdbx",
            "project_state_templates/.env",
            "project_state_templates/.env.local",
            "scripts/credentials.json",
            "practice_guides/token.json",
            ".direnv/allow",
        ):
            self.assertTrue(public_surface.is_public_excluded(rel), rel)
        for rel in integration_registry.required_template_files(REPO_ROOT):
            self.assertIn(rel, public_surface.PUBLIC_REQUIRED_FILES)
        text = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertFalse(validate_framework.contains_internal_local_state_reference(text))
        claude_lines = [
            line.strip()
            for line in (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        self.assertEqual(["@AGENTS.md"], claude_lines)
        synthetic_local_note = "internal" + "_update_notes.md"
        synthetic_state_note = "LOCAL" + "_STATE" + "_NOTE.md"
        synthetic_commit_note = "Local" + "_Commit.md"
        self.assertTrue(validate_framework.contains_internal_local_state_reference(f"see {synthetic_local_note}"))
        self.assertTrue(validate_framework.contains_internal_local_state_reference(f"see {synthetic_state_note}"))
        self.assertTrue(validate_framework.contains_internal_local_state_reference(f"see {synthetic_commit_note}"))
        self.assertFalse(validate_framework.contains_internal_local_state_reference("see internal_reference.md"))

    def test_repository_entrypoint_loads_charter_then_guards_authoring_authority(self) -> None:
        text = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
        authoring_projection_marker = (
            "If `" + "private" + "/authoring/AGENT_PROJECT.md` exists"
        )
        self.assertEqual(1, text.count(integration_registry.RECOVERY_GUARD_MARKER))
        self.assertEqual(1, text.count(integration_registry.RECOVERY_GUARD_CLAUSE))
        self.assertLess(
            text.index("Read `runtime/operative_charter.md` before acting."),
            text.index(integration_registry.RECOVERY_GUARD_CLAUSE),
        )
        self.assertLess(
            text.index(integration_registry.RECOVERY_GUARD_CLAUSE),
            text.index(authoring_projection_marker),
        )

    def test_visual_asset_qa_template_is_routed_from_visual_verification(self) -> None:
        guide = (REPO_ROOT / "practice_guides" / "visual_verification.md").read_text(encoding="utf-8")
        template = (REPO_ROOT / "project_state_templates" / "VISUAL_ASSET_QA.md").read_text(encoding="utf-8")
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("project_state_templates/VISUAL_ASSET_QA.md", guide)
        self.assertIn("visual_qa_schema_version: 1", template)
        self.assertIn("project_state_templates/VISUAL_ASSET_QA.md", readme)
        self.assertIn(
            "project_state_templates/VISUAL_ASSET_QA.md",
            public_surface.PUBLIC_REQUIRED_FILES,
        )

    def test_specialized_delivery_templates_are_public_and_routed(self) -> None:
        cases = (
            (
                "practice_guides/video_creation_quality.md",
                "project_state_templates/VIDEO_DELIVERABLE_QA.md",
                (
                    "video.brief-delivery-contract",
                    "video.rights-accessibility-plan",
                    "video.temporal-technical-playback",
                ),
            ),
            (
                "practice_guides/delegated_communications.md",
                "project_state_templates/DELEGATED_COMMUNICATIONS_COVERAGE.md",
                (
                    "communications.grant-activation-boundary",
                    "communications.disclosure-effect-gate",
                    "communications.expiry-revocation-audit-loop",
                ),
            ),
        )
        quality_contract = validate_framework.load_json(
            REPO_ROOT / "runtime" / "framework_quality_contract.json"
        )
        owned_guides = {
            item["path"] for item in quality_contract["guide_surface_roles"]
        }

        for guide_rel, template_rel, check_ids in cases:
            with self.subTest(guide=guide_rel):
                guide = (REPO_ROOT / guide_rel).read_text(encoding="utf-8")
                template = (REPO_ROOT / template_rel).read_text(encoding="utf-8")
                self.assertIn(template_rel, guide)
                for check_id in check_ids:
                    self.assertIn(check_id, guide)
                self.assertTrue(
                    template.startswith(
                        "<!-- mpa-generated-state-origin: "
                        "master-prompt-agreement/project-state/v1 -->\n"
                    )
                )
                self.assertIn(guide_rel, public_surface.PUBLIC_REQUIRED_FILES)
                self.assertIn(template_rel, public_surface.PUBLIC_REQUIRED_FILES)
                self.assertIn(guide_rel, owned_guides)

    def test_framework_feedback_recurrence_is_incident_based(self) -> None:
        template = (
            REPO_ROOT / "project_state_templates" / "FRAMEWORK_FEEDBACK.md"
        ).read_text(encoding="utf-8")
        intake = (
            REPO_ROOT / "task_orders" / "framework_feedback_intake.md"
        ).read_text(encoding="utf-8")

        _, separator, remainder = template.partition("```md\n")
        self.assertEqual("```md\n", separator)
        example, separator, _ = remainder.partition("\n```")
        self.assertEqual("\n```", separator)
        self.assertIn("Evidence Basis: single-observation", example)
        self.assertNotIn("Evidence Basis: repeated-in-project", example)

        for surface in (template, intake):
            with self.subTest(surface=surface.splitlines()[0]):
                normalized = " ".join(surface.split())
                self.assertIn(
                    "one incident even when it appears in several fields, files, "
                    "checks, messages, or surfaces",
                    normalized.replace("one incident, even", "one incident even"),
                )
                self.assertIn(
                    "at least two independent, comparably scoped incidents in one project",
                    normalized,
                )
                self.assertIn(
                    "independent, comparably scoped incidents in at least two projects",
                    normalized,
                )

    def test_readme_visuals_are_public_structurally_labelled_and_meet_text_geometry(self) -> None:
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        diagrams = (
            (
                "assets/framework_runtime_loop_mobile.svg",
                "assets/framework_runtime_loop.svg",
                ("authority", "recovery gate", "verification", "accepted framework"),
            ),
            (
                "assets/reviewer_lane_feedback_loop_mobile.svg",
                "assets/reviewer_lane_feedback_loop.svg",
                ("coordinator", "reviewers", "verifies", "authority"),
            ),
        )

        parser = ReadmeImageParser()
        parser.feed(readme)
        images_by_src: dict[str, dict[str, object]] = {}
        for image in parser.images:
            img = image["img"]
            if isinstance(img, dict) and img.get("src"):
                images_by_src[str(img["src"])] = image

        for mobile_path, desktop_path, alt_terms in diagrams:
            with self.subTest(diagram=desktop_path):
                self.assertIn(desktop_path, images_by_src)
                image = images_by_src[desktop_path]
                img = image["img"]
                if not isinstance(img, dict):
                    self.fail(f"{desktop_path} README image attributes are not a mapping")
                alt = str(img.get("alt", "")).lower()
                for term in alt_terms:
                    self.assertIn(term, alt)
                for asset_path in (mobile_path, desktop_path):
                    self.assertIn(asset_path, readme)
                    self.assertIn(asset_path, public_surface.PUBLIC_REQUIRED_FILES)

                    root = ET.parse(REPO_ROOT / asset_path).getroot()
                    self.assertEqual("img", root.get("role"))
                    labelled_by = (root.get("aria-labelledby") or "").split()
                    element_ids = {
                        value
                        for element in root.iter()
                        if (value := element.get("id")) is not None
                    }
                    self.assertEqual(["title", "desc"], labelled_by)
                    self.assertTrue(set(labelled_by).issubset(element_ids))

                    local_names = {
                        element.tag.rsplit("}", 1)[-1] for element in root.iter()
                    }
                    self.assertNotIn("script", local_names)
                    self.assertNotIn("foreignObject", local_names)
                    styles = [
                        element
                        for element in root.iter()
                        if element.tag.rsplit("}", 1)[-1] == "style"
                    ]
                    self.assertEqual(1, len(styles))
                    style_text = styles[0].text or ""
                    self.assertNotIn("prefers-color-scheme", style_text)
                    self.assertIn("@media (forced-colors: active)", style_text)
                    backgrounds = [
                        element
                        for element in root.iter()
                        if element.tag.rsplit("}", 1)[-1] == "rect"
                        and element.get("class") == "bg"
                    ]
                    self.assertEqual(1, len(backgrounds))
                    self.assertEqual("0", backgrounds[0].get("x"))
                    self.assertEqual("0", backgrounds[0].get("y"))
                    self.assertEqual(root.get("width"), backgrounds[0].get("width"))
                    self.assertEqual(root.get("height"), backgrounds[0].get("height"))
                    if "framework_runtime_loop" in asset_path:
                        visible_text = " ".join(
                            (element.text or "").strip()
                            for element in root.iter()
                            if (element.text or "").strip()
                        ).lower()
                        self.assertIn("transaction control", visible_text.replace("-", " "))
                        self.assertIn("stop", visible_text)
                        self.assertIn("exact-id", visible_text)
                        load_order_labels = (
                            "contract + authority if set",
                            "relevant state records",
                            "runtime task module",
                            "applicable practice guide",
                        )
                        diagram_labels = " ".join(
                            (element.text or "").strip()
                            for element in root.iter()
                            if element.tag.rsplit("}", 1)[-1] in {"text", "tspan"}
                            and (element.text or "").strip()
                        ).lower()
                        for authority_label in (
                            "agreement",
                            "statement of work",
                            "project contract",
                        ):
                            self.assertIn(authority_label, diagram_labels)
                        self.assertNotIn("agent_project.md", diagram_labels)
                        for label in load_order_labels:
                            self.assertIn(label, diagram_labels)
                        positions = [diagram_labels.index(label) for label in load_order_labels]
                        self.assertEqual(sorted(positions), positions)
                        self.assertIn("recover if permitted", diagram_labels)
                        self.assertIn("semantic and judgment review", diagram_labels)
                        admission_labels = (
                            "candidate evidence",
                            "semantic audit",
                            "accepted improvement",
                            "exact-candidate review",
                            "verified disposition",
                        )
                        for label in admission_labels:
                            self.assertIn(label, diagram_labels)
                        admission_positions = [
                            diagram_labels.index(label) for label in admission_labels
                        ]
                        self.assertEqual(sorted(admission_positions), admission_positions)
                        self.assertIn("retained framework product", diagram_labels)
                        if asset_path == desktop_path:
                            def svg_element(
                                local_name: str,
                                *,
                                css_class: str | None = None,
                                text: str | None = None,
                            ) -> ET.Element:
                                matches = [
                                    element
                                    for element in root.iter()
                                    if element.tag.rsplit("}", 1)[-1] == local_name
                                    and (
                                        css_class is None
                                        or element.get("class") == css_class
                                    )
                                    and (
                                        text is None
                                        or (element.text or "").strip() == text
                                    )
                                ]
                                self.assertEqual(
                                    1,
                                    len(matches),
                                    f"{asset_path} {css_class or local_name} {text or ''}",
                                )
                                return matches[0]

                            runtime_rect = svg_element("rect", css_class="runtime")
                            stop_rect = svg_element("rect", css_class="stop")
                            admission_rect = max(
                                (
                                    element
                                    for element in root.iter()
                                    if element.tag.rsplit("}", 1)[-1] == "rect"
                                    and element.get("class") == "feedback"
                                ),
                                key=lambda element: float(element.get("x") or "0"),
                            )
                            present = svg_element(
                                "text",
                                css_class="branch-red",
                                text="present",
                            )
                            evidence = svg_element(
                                "text",
                                css_class="branch-blue",
                                text="evidence",
                            )

                            runtime_right = float(runtime_rect.get("x") or "0") + float(
                                runtime_rect.get("width") or "0"
                            )
                            stop_left = float(stop_rect.get("x") or "0")
                            stop_right = stop_left + float(stop_rect.get("width") or "0")
                            admission_left = float(admission_rect.get("x") or "0")
                            present_x = float(present.get("x") or "0")
                            evidence_x = float(evidence.get("x") or "0")

                            self.assertEqual("middle", present.get("text-anchor"))
                            self.assertGreaterEqual(stop_left - runtime_right, 72.0)
                            self.assertAlmostEqual(
                                (runtime_right + stop_left) / 2,
                                present_x,
                                delta=2.0,
                            )
                            self.assertEqual("middle", evidence.get("text-anchor"))
                            self.assertGreaterEqual(admission_left - stop_right, 88.0)
                            self.assertAlmostEqual(
                                (stop_right + admission_left) / 2,
                                evidence_x,
                                delta=2.0,
                            )

                            segment = svg_element("path", css_class="blue-segment")
                            segment_match = re.fullmatch(
                                r"M([0-9.]+) ([0-9.]+) V([0-9.]+)",
                                segment.get("d") or "",
                            )
                            self.assertIsNotNone(segment_match)
                            arrow_paths = [
                                element
                                for element in root.iter()
                                if element.tag.rsplit("}", 1)[-1] == "path"
                                and element.get("class") == "blue-line"
                                and (element.get("d") or "").startswith(
                                    f"M{evidence_x:g} "
                                )
                            ]
                            self.assertEqual(1, len(arrow_paths))
                            arrow_match = re.fullmatch(
                                r"M([0-9.]+) ([0-9.]+) V([0-9.]+)",
                                arrow_paths[0].get("d") or "",
                            )
                            self.assertIsNotNone(arrow_match)
                            if segment_match is not None and arrow_match is not None:
                                self.assertEqual(evidence_x, float(segment_match.group(1)))
                                self.assertEqual(evidence_x, float(arrow_match.group(1)))
                                self.assertLess(
                                    float(segment_match.group(3)),
                                    float(evidence.get("y") or "0"),
                                )
                                self.assertGreater(
                                    float(arrow_match.group(2)),
                                    float(evidence.get("y") or "0"),
                                )
                    elif "reviewer_lane_feedback_loop" in asset_path:
                        diagram_labels = " ".join(
                            (element.text or "").strip()
                            for element in root.iter()
                            if element.tag.rsplit("}", 1)[-1] in {"text", "tspan"}
                            and (element.text or "").strip()
                        ).lower()
                        closeout_labels = (
                            "feedback file maintained?",
                            "receipt-declared feedback file",
                            "ordinary closeout report",
                        )
                        for label in closeout_labels:
                            self.assertIn(label, diagram_labels)
                        closeout_positions = [
                            diagram_labels.index(label) for label in closeout_labels
                        ]
                        self.assertEqual(sorted(closeout_positions), closeout_positions)
                        self.assertIn("structural linter", diagram_labels)
                        self.assertIn("do not create", diagram_labels)

                        if asset_path == desktop_path:
                            rectangles = {
                                element.get("class"): element
                                for element in root.iter()
                                if element.tag.rsplit("}", 1)[-1] == "rect"
                                and element.get("class") in {"trigger", "marker"}
                            }
                            self.assertEqual({"trigger", "marker"}, set(rectangles))
                            trigger = rectangles["trigger"]
                            marker = rectangles["marker"]
                            trigger_right = float(trigger.get("x") or "0") + float(
                                trigger.get("width") or "0"
                            )
                            marker_left = float(marker.get("x") or "0")
                            trigger_top = float(trigger.get("y") or "0")
                            trigger_bottom = trigger_top + float(
                                trigger.get("height") or "0"
                            )
                            connector_paths = [
                                element
                                for element in root.iter()
                                if element.tag.rsplit("}", 1)[-1] == "path"
                                and element.get("class") == "blue-line"
                                and re.fullmatch(
                                    rf"M{trigger_right:g} ([0-9.]+) H([0-9.]+)",
                                    element.get("d") or "",
                                )
                            ]
                            self.assertEqual(1, len(connector_paths))
                            connector_match = re.fullmatch(
                                r"M([0-9.]+) ([0-9.]+) H([0-9.]+)",
                                connector_paths[0].get("d") or "",
                            )
                            self.assertIsNotNone(connector_match)
                            if connector_match is not None:
                                connector_y = float(connector_match.group(2))
                                connector_end = float(connector_match.group(3))
                                self.assertLess(connector_end, marker_left)
                                self.assertGreater(connector_end, trigger_right)

                                # The inter-card gutter is too narrow to host a
                                # readable label. Keep a full 16px text-height
                                # corridor around the connector free of text
                                # anchors so labels cannot cross either card.
                                font_clearance = 16.0
                                intersecting_labels = []
                                for element in root.iter():
                                    if element.tag.rsplit("}", 1)[-1] != "text":
                                        continue
                                    x = float(element.get("x") or "-inf")
                                    y = float(element.get("y") or "-inf")
                                    if (
                                        trigger_right - font_clearance <= x <= marker_left
                                        and max(trigger_top, connector_y - font_clearance)
                                        <= y
                                        <= min(trigger_bottom, connector_y + font_clearance)
                                    ):
                                        intersecting_labels.append(
                                            ((element.text or "").strip(), x, y)
                                        )
                                self.assertEqual([], intersecting_labels)

                sources = image["sources"]
                self.assertIsInstance(sources, tuple)
                if not isinstance(sources, tuple) or len(sources) != 1:
                    self.fail(f"{desktop_path} must have one responsive source")
                source = sources[0]
                self.assertIsInstance(source, dict)
                if not isinstance(source, dict):
                    self.fail(f"{desktop_path} source attributes are not a mapping")
                media_match = re.fullmatch(
                    r"\(max-width:\s*(\d+)px\)",
                    source.get("media", ""),
                )
                self.assertIsNotNone(media_match)
                if media_match is None:
                    self.fail(f"{desktop_path} has an unsupported media query")
                breakpoint = int(media_match.group(1))

                # Picture media queries use viewport width, while the SVG is
                # scaled to the narrower README content column. Model those as
                # distinct quantities. At narrow widths, GitHub-style host
                # padding leaves at least viewport - 32 px for content; at wide
                # widths the README column is capped at 1012 px.
                viewport_widths = (
                    320,
                    360,
                    375,
                    390,
                    breakpoint - 1,
                    breakpoint,
                    breakpoint + 1,
                    breakpoint + 32,
                    1044,
                    1280,
                )
                for viewport_width in viewport_widths:
                    content_width = min(max(viewport_width - 32, 1), 1012)
                    selected_path = selected_readme_image(
                        image,
                        viewport_width,
                    )
                    expected_path = (
                        mobile_path if viewport_width <= breakpoint else desktop_path
                    )
                    self.assertEqual(expected_path, selected_path)
                    root = ET.parse(REPO_ROOT / selected_path).getroot()
                    view_box = [
                        float(value) for value in (root.get("viewBox") or "").split()
                    ]
                    self.assertEqual(4, len(view_box))
                    intrinsic_width = float(root.get("width") or "0")
                    intrinsic_height = float(root.get("height") or "0")
                    self.assertEqual(intrinsic_width, view_box[2])
                    self.assertEqual(intrinsic_height, view_box[3])

                    style_text = "".join(
                        element.text or ""
                        for element in root.iter()
                        if element.tag.rsplit("}", 1)[-1] == "style"
                    )
                    font_sizes = [
                        float(value)
                        for value in re.findall(
                            r"font:\s+\d+\s+([0-9.]+)px",
                            style_text,
                        )
                    ]
                    self.assertTrue(font_sizes, selected_path)
                    rendered_width = min(float(content_width), intrinsic_width)
                    minimum_effective_size = (
                        min(font_sizes) * rendered_width / intrinsic_width
                    )
                    self.assertGreaterEqual(
                        minimum_effective_size,
                        11.0,
                        (
                            f"{selected_path} renders {minimum_effective_size:.2f}px "
                            f"text at viewport {viewport_width}px and README "
                            f"content width {content_width}px"
                        ),
                    )

                mobile_root = ET.parse(REPO_ROOT / mobile_path).getroot()
                width = float(mobile_root.get("width") or "0")
                height = float(mobile_root.get("height") or "0")
                self.assertEqual("img", mobile_root.get("role"))
                self.assertGreater(height, width)

    def test_validate_framework_does_not_inspect_excluded_workspace_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_state_templates = root / "project_state_templates"
            external_root = "external" + "_review"
            external = root / external_root
            unlisted = root / "unlisted_workspace_notes"
            project_state_templates.mkdir()
            external.mkdir()
            unlisted.mkdir()
            (project_state_templates / "keep.md").write_text("# Keep\n", encoding="utf-8")
            (project_state_templates / ("token" + ".json")).write_text('{"token": "secret"}\n', encoding="utf-8")
            (external / "leak.md").write_text("# Local artifact\n", encoding="utf-8")
            (unlisted / "would_fail_if_scanned.md").write_text("internal" + "_update_notes.md\n", encoding="utf-8")

            with mock.patch.object(validate_framework, "REPO_ROOT", root):
                with mock.patch.object(public_surface, "PUBLIC_ROOTS", ("project_state_templates", external_root)):
                    files = {
                        path.relative_to(root).as_posix()
                        for path in validate_framework.public_text_files()
                    }

        self.assertEqual({"project_state_templates/keep.md"}, files)

    def test_repo_local_agents_surface_is_limited_to_declared_launcher(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launcher = root / ".agents" / "skills" / "master-prompt-new-project"
            local_skill = root / ".agents" / "skills" / "private-local-test"
            launcher.mkdir(parents=True)
            local_skill.mkdir(parents=True)
            (launcher / "SKILL.md").write_text("---\nname: launcher\n---\n", encoding="utf-8")
            (local_skill / "SKILL.md").write_text("internal" + "_update_notes.md\n", encoding="utf-8")

            public_files = {
                path.relative_to(root).as_posix()
                for path in public_surface.iter_public_root_files(
                    root,
                    public_roots=(".agents/skills/master-prompt-new-project",),
                )
            }

            with mock.patch.object(validate_framework, "REPO_ROOT", root):
                with mock.patch.object(
                    validate_framework,
                    "PUBLIC_TEMPLATE_ROOTS",
                    (".agents/skills/master-prompt-new-project",),
                ):
                    template_files = {
                        path.relative_to(root).as_posix()
                        for path in validate_framework.public_template_files()
                    }

        self.assertEqual({".agents/skills/master-prompt-new-project/SKILL.md"}, public_files)
        self.assertEqual({".agents/skills/master-prompt-new-project/SKILL.md"}, template_files)

    def test_conformance_profile_registry_is_valid(self) -> None:
        registry, errors = conformance_check.load_profiles()

        self.assertEqual([], errors)
        if registry is None:
            self.fail("current conformance profile registry did not load")
        profile_ids = {profile["id"] for profile in registry["profiles"]}
        self.assertIn("framework-authoring-release", profile_ids)
        self.assertIn("framework-public-release", profile_ids)
        self.assertIn("core-project", profile_ids)
        self.assertIn("reviewer-lane-managed", profile_ids)

    def test_framework_consistency_current_contract_has_no_issues(self) -> None:
        errors, warnings = framework_consistency.collect_consistency_issues()

        self.assertEqual([], errors)
        self.assertEqual([], warnings)

    def test_conformance_profile_registry_rejects_unknown_top_level_fields(self) -> None:
        registry = json.loads(
            (REPO_ROOT / "conformance" / "profiles.json").read_text(encoding="utf-8")
        )
        registry["shadow_policy"] = {"enabled": True}

        conformance_errors = conformance_check.validate_profile_metadata(registry)
        consistency_errors: list[str] = []
        framework_consistency.validate_conformance_profiles(registry, consistency_errors)

        for errors in (conformance_errors, consistency_errors):
            self.assertTrue(
                any("unknown top-level fields: shadow_policy" in error for error in errors),
                errors,
            )

    def test_conformance_profile_registry_rejects_malformed_lists_without_crashing(self) -> None:
        registry = json.loads(
            (REPO_ROOT / "conformance" / "profiles.json").read_text(encoding="utf-8")
        )
        profile = registry["profiles"][0]
        profile["required_checks"] = "not-a-list"
        profile["extends"] = 7
        errors: list[str] = []

        framework_consistency.validate_conformance_profiles(registry, errors)

        self.assertIn(
            f"conformance profile {profile['id']} required_checks must be a string list",
            errors,
        )
        self.assertIn(
            f"conformance profile {profile['id']} extends must be a string list",
            errors,
        )

    def test_workflow_catalog_rejects_non_object_sequence_without_crashing(self) -> None:
        catalog = json.loads(
            (REPO_ROOT / "runtime" / "workflow_catalog.json").read_text(encoding="utf-8")
        )
        catalog["common_sequences"] = [None]
        errors: list[str] = []

        sequences = framework_consistency.validated_common_sequences(catalog, [], errors)

        self.assertEqual([], sequences)
        self.assertEqual(
            ["workflow catalog common_sequences[0] must be an object"],
            errors,
        )

    def test_conformance_profile_registry_rejects_duplicate_lists_and_lexical_paths(self) -> None:
        registry = json.loads(
            (REPO_ROOT / "conformance" / "profiles.json").read_text(encoding="utf-8")
        )
        profile = registry["profiles"][0]
        profile["required_checks"] = [profile["required_checks"][0]] * 2
        profile["required_files"] = ["docs//concepts.md"]
        profile["required_directories"] = ["docs/./interactive"]
        profile["extends"] = ["core-project", "core-project"]

        errors = conformance_check.validate_profile_metadata(registry)

        self.assertTrue(any("required_checks must not contain duplicates" in error for error in errors), errors)
        self.assertTrue(any("required file must not contain empty" in error for error in errors), errors)
        self.assertTrue(any("required directory must not contain empty" in error for error in errors), errors)
        self.assertTrue(any("extends must not contain duplicates" in error for error in errors), errors)

    def test_conformance_security_verification_requires_exact_unfenced_unique_content(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            security = root / "SECURITY_VERIFICATION.md"
            security.write_text(
                "# Security Verification\n\n"
                "```md\n## Scope\nfenced spoof\n```\n\n"
                "## Scope\n\n"
                "## Profiles\nprofile details\n\n"
                "## Profiles\nduplicate details\n\n"
                "## Authorization Boundaries\nauthorized local targets\n\n"
                "### Tool Output Triage\nwrong heading level\n",
                encoding="utf-8",
            )

            errors = conformance_check.check_security_verification_file(root)

        self.assertIn("SECURITY_VERIFICATION.md section has no substantive content: ## Scope", errors)
        self.assertIn("SECURITY_VERIFICATION.md duplicate section: ## Profiles", errors)
        self.assertIn("SECURITY_VERIFICATION.md missing section: ## Tool Output Triage", errors)

    def test_conformance_list_profiles_does_not_require_profile(self) -> None:
        result = run_bounded(
            [sys.executable, "-B", str(SCRIPTS_DIR / "conformance_check.py"), "--list"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("framework-authoring-release", result.stdout)
        self.assertIn("framework-public-release", result.stdout)

    def test_conformance_rejects_unknown_profile_as_invocation_error(self) -> None:
        result = run_bounded(
            [sys.executable, "-B", str(SCRIPTS_DIR / "conformance_check.py"), "--profile", "missing-profile"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(conformance_check.EXIT_INVALID_INVOCATION, result.returncode)
        self.assertIn("unknown profile: missing-profile", result.stdout)

    def test_conformance_rejects_unresolved_entrypoint_framework_reference(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            entrypoint_name, entrypoint = project_bootstrap.render_entrypoint(
                "generic",
                "$MPA_TEST_UNRESOLVED_FRAMEWORK_ROOT",
            )
            (root / entrypoint_name).write_text(
                entrypoint,
                encoding="utf-8",
            )
            (root / "AGENT_PROJECT.md").write_text("# Project Contract\n", encoding="utf-8")

            with mock.patch.dict(
                "os.environ",
                {"MPA_TEST_UNRESOLVED_FRAMEWORK_ROOT": ""},
            ):
                errors = conformance_check.check_project_entrypoint_resolves(root)

        self.assertTrue(
            any("not concretely resolvable" in error for error in errors),
            errors,
        )

    def test_downstream_checkers_reject_symlinked_inputs_and_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "project"
            outside = base / "outside"
            root.mkdir()
            outside.mkdir()
            outside_file = outside / "external.md"
            outside_file.write_bytes(b"\xff\xfeexternal")
            outside_directory = outside / "conformance"
            outside_directory.mkdir()

            for rel in (
                "STATEMENT_OF_WORK.md",
                "AGENT_PROJECT.md",
                "AGENTS.md",
                "TODO.md",
                "SECURITY_VERIFICATION.md",
            ):
                (root / rel).symlink_to(outside_file)

            for rel in (
                "STATEMENT_OF_WORK.md",
                "AGENT_PROJECT.md",
                "AGENTS.md",
                "TODO.md",
                "SECURITY_VERIFICATION.md",
            ):
                errors = safe_paths.bounded_input_errors(
                    root / rel,
                    root,
                    description=f"{rel} input",
                )
                self.assertTrue(any("symlink" in error for error in errors), errors)

            required_file_errors = conformance_check.check_required_files(
                root,
                ["SECURITY_VERIFICATION.md"],
            )
            self.assertTrue(
                any("symlink" in error for error in required_file_errors),
                required_file_errors,
            )
            entrypoint_roots, entrypoint_errors = conformance_check.entrypoint_framework_roots(root)
            self.assertEqual([], entrypoint_roots)
            self.assertTrue(any("symlink" in error for error in entrypoint_errors), entrypoint_errors)

            (root / "conformance").symlink_to(outside_directory, target_is_directory=True)
            required_directory_errors = conformance_check.check_required_directories(
                root,
                ["conformance"],
            )
            self.assertTrue(
                any("symlink" in error for error in required_directory_errors),
                required_directory_errors,
            )

            contract_result = run_bounded(
                [
                    sys.executable,
                    "-B",
                    str(SCRIPTS_DIR / "project_contract_sync.py"),
                    str(root),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(0, contract_result.returncode)
            self.assertIn("symlink", contract_result.stdout)

            (root / "DECISIONS.md").write_text("# Decisions\n", encoding="utf-8")
            state_result = run_bounded(
                [
                    sys.executable,
                    "-B",
                    str(SCRIPTS_DIR / "project_state_lint.py"),
                    "--root",
                    str(root),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(0, state_result.returncode)
            self.assertIn("symlink", state_result.stdout)

    def test_conformance_source_metadata_uses_monitor_root_audit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "SOURCE_PACKS.md").write_text("# Source Packs\n", encoding="utf-8")
            (root / "SOURCE_UPDATE.md").write_text("# Source Update\n", encoding="utf-8")

            with mock.patch(
                "conformance_check.run_command_capture",
                return_value=conformance_check.CommandCapture(
                    ok=True,
                    stdout=json.dumps({"errors": [], "warnings": []}),
                    returncode=0,
                ),
            ) as run_command:
                outcome = conformance_check.check_source_freshness_metadata(root)

        self.assertIsInstance(outcome, conformance_check.CheckOutcome)
        if not isinstance(outcome, conformance_check.CheckOutcome):
            self.fail("source freshness conformance did not return a structured outcome")
        self.assertEqual((), outcome.errors)
        self.assertEqual((), outcome.warnings)
        self.assertIsNone(outcome.protocol_failure)
        args = run_command.call_args.args[1]
        self.assertIn("--audit-monitor-roots", args)
        self.assertIn("--warnings-as-errors", args)

    def test_conformance_subprocesses_bound_runtime_and_output(self) -> None:
        timed_ok, timed_output = conformance_check.run_command(
            "slow-check",
            [sys.executable, "-c", "import time; time.sleep(5)"],
            REPO_ROOT,
            timeout_seconds=0.05,
            max_output_bytes=1024,
        )
        self.assertFalse(timed_ok)
        self.assertIn("slow-check timed out after", timed_output)

        oversized_ok, oversized_output = conformance_check.run_command(
            "noisy-check",
            [sys.executable, "-c", "print('x' * 256)"],
            REPO_ROOT,
            timeout_seconds=5,
            max_output_bytes=32,
        )
        self.assertFalse(oversized_ok)
        self.assertIn("noisy-check output exceeded the 32-byte limit", oversized_output)
        self.assertLessEqual(len(oversized_output.encode("utf-8")), 128)

        failed_ok, failed_output = conformance_check.run_command(
            "failed-check",
            [
                sys.executable,
                "-c",
                "import sys; print('causal stderr', file=sys.stderr); raise SystemExit(7)",
            ],
            REPO_ROOT,
            timeout_seconds=5,
            max_output_bytes=1024,
        )
        self.assertFalse(failed_ok)
        self.assertIn("causal stderr", failed_output)

        compliance_ok, compliance_message, compliance_output = (
            framework_compliance.run(
                "noisy-compliance-check",
                [sys.executable, "-c", "print('x' * 256)"],
                REPO_ROOT,
                timeout_seconds=5,
                max_output_bytes=32,
            )
        )
        self.assertFalse(compliance_ok)
        self.assertIn("output exceeded the 32-byte limit", compliance_message)
        self.assertLessEqual(len(compliance_output.encode("utf-8")), 128)

    @unittest.skipUnless(
        sys.platform.startswith("linux"),
        "detached-descendant containment requires the Linux subreaper contract",
    )
    def test_conformance_timeout_reaps_setsid_descendant_after_leader_exit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ready = root / "ready"
            survived = root / "survived"
            timeout_seconds = 0.5
            child_code = (
                "import os, signal, time\n"
                "from pathlib import Path\n"
                "os.setsid()\n"
                "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                f"Path({str(ready)!r}).write_text('ready', encoding='utf-8')\n"
                f"time.sleep({timeout_seconds + conformance_check.COMMAND_TERMINATION_GRACE_SECONDS + 0.25!r})\n"
                f"Path({str(survived)!r}).write_text('survived', encoding='utf-8')\n"
            )
            parent_code = (
                "import subprocess, sys, time\n"
                "from pathlib import Path\n"
                f"child = subprocess.Popen([sys.executable, '-c', {child_code!r}])\n"
                "deadline = time.monotonic() + 2\n"
                f"while not Path({str(ready)!r}).exists() and time.monotonic() < deadline:\n"
                "    time.sleep(0.005)\n"
                f"if not Path({str(ready)!r}).exists():\n"
                "    raise SystemExit(9)\n"
                "print(child.pid, flush=True)\n"
            )

            ok, output = conformance_check.run_command(
                "descendant-check",
                [sys.executable, "-c", parent_code],
                REPO_ROOT,
                timeout_seconds=timeout_seconds,
                max_output_bytes=1024,
            )
            self.assertFalse(ok)
            self.assertIn("descendant-check timed out after", output)
            time.sleep(0.35)
            self.assertFalse(survived.exists())

    def test_conformance_collection_failure_cleans_up_and_returns_cause(self) -> None:
        with self.assertRaisesRegex(ValueError, "cmd must not be empty"):
            conformance_check.run_command("empty-check", [], REPO_ROOT)

        real_terminate = bounded_subprocess._terminate_failed_process
        with (
            mock.patch.object(
                bounded_subprocess.selectors.DefaultSelector,
                "register",
                side_effect=OSError("synthetic selector failure"),
            ),
            mock.patch.object(
                bounded_subprocess,
                "_terminate_failed_process",
                wraps=real_terminate,
            ) as terminate,
        ):
            ok, output = conformance_check.run_command(
                "collector-check",
                [sys.executable, "-c", "import time; time.sleep(30)"],
                REPO_ROOT,
                timeout_seconds=5,
                max_output_bytes=1024,
            )

        self.assertFalse(ok)
        self.assertIn("collector-check output collection failed", output)
        self.assertIn("synthetic selector failure", output)
        terminate.assert_called_once()

    def test_json_output_writers_reject_nonfinite_values(self) -> None:
        report = {"checks": [], "errors": [], "value": float("nan")}
        with self.assertRaises(ValueError):
            conformance_check.print_report(report, "json")

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(ValueError):
                framework_compliance.write_json(
                    Path(temp_dir) / "report.json",
                    report,
                )

    def test_conformance_reviewer_lane_profile_runs_lint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "REVIEWER_LANE_FEEDBACK.md").write_text("# Reviewer Lane Feedback\n", encoding="utf-8")

            with mock.patch(
                "conformance_check.run_command_capture",
                return_value=conformance_check.CommandCapture(
                    ok=True,
                    stdout=json.dumps({"errors": [], "warnings": []}),
                    returncode=0,
                ),
            ) as run_command:
                outcome = conformance_check.check_reviewer_lane_feedback_lint(root)

        self.assertIsInstance(outcome, conformance_check.CheckOutcome)
        if not isinstance(outcome, conformance_check.CheckOutcome):
            self.fail("reviewer lane conformance did not return a structured outcome")
        self.assertEqual((), outcome.errors)
        self.assertEqual((), outcome.warnings)
        self.assertIsNone(outcome.protocol_failure)
        args = run_command.call_args.args[1]
        self.assertIn("lint_reviewer_lane_feedback.py", args[2])
        self.assertIn("--path", args)

    def test_internal_local_state_guards_are_consistent_and_not_overbroad(self) -> None:
        leak = "see " + "internal" + "_update_notes.md"
        benign = "see internal_reference.md"

        self.assertTrue(validate_framework.contains_internal_local_state_reference(leak))
        self.assertFalse(validate_framework.contains_internal_local_state_reference(benign))
        self.assertNotEqual([], project_bootstrap.find_internal_leaks({"note": leak}))
        self.assertEqual([], project_bootstrap.find_internal_leaks({"note": benign}))
        self.assertNotEqual([], project_contract_sync.internal_tracking_leaks("SOW", leak))
        self.assertEqual([], project_contract_sync.internal_tracking_leaks("SOW", benign))

    def test_project_contract_sync_ignores_indented_and_fenced_section_markers(self) -> None:
        sow_text = (
            "Definitions\n"
            "- Agent: Agent\n"
            "  Annexes\n"
            "```text\n"
            "Annexes\n"
            "```\n"
            "Annexes   \n"
            "None\n"
        )
        sow_sections = project_contract_sync.plain_sections(sow_text, project_contract_sync.SOW_TITLES)

        self.assertIn("  Annexes", sow_sections["Definitions"])
        self.assertNotIn("Annexes", sow_sections["Definitions"])
        self.assertEqual(["None"], sow_sections["Annexes"])

        project_text = (
            "## Definitions\n"
            "```md\n"
            "## Critical Surfaces\n"
            "```\n"
            "- Agent: Agent\n"
            "  ## Common Commands\n"
            "## Active Stack\n"
            "- Python\n"
        )
        project_sections = project_contract_sync.markdown_sections(project_text)

        self.assertNotIn("Critical Surfaces", project_sections)
        self.assertNotIn("Common Commands", project_sections)
        self.assertNotIn("## Critical Surfaces", project_sections["Definitions"])
        self.assertIn("  ## Common Commands", project_sections["Definitions"])
        self.assertEqual(["- Python"], project_sections["Active Stack"])

    def test_task_orders_have_catalog_entries_and_heading_convention(self) -> None:
        catalog = validate_framework.load_json(REPO_ROOT / "runtime" / "workflow_catalog.json")
        catalog_paths = {item["path"] for item in catalog["task_orders"]}
        task_order_paths = {
            path.relative_to(REPO_ROOT).as_posix()
            for path in (REPO_ROOT / "task_orders").glob("*.md")
            if path.name != "README.md"
        }

        self.assertEqual(task_order_paths, catalog_paths)
        for rel in task_order_paths:
            first_line = (REPO_ROOT / rel).read_text(encoding="utf-8").splitlines()[0]
            self.assertTrue(first_line.startswith(validate_framework.TASK_ORDER_HEADING_PREFIX), rel)

    def test_clause_map_is_versioned_and_queryable_by_disposition(self) -> None:
        document = query_clause_map.load_clause_map(REPO_ROOT)

        self.assertEqual(4, document["schema_version"])
        self.assertRegex(document["msa_version"], r"^\d+\.\d+\.\d+$")
        self.assertEqual(
            framework_consistency.MSA_DIGEST_ALGORITHM,
            document["msa_digest_algorithm"],
        )
        self.assertEqual(
            framework_consistency.normalized_file_digest(REPO_ROOT / "master_service_agreement.md"),
            document["msa_digest_sha256"],
        )
        projected = [
            row for row in document["clauses"] if "projected" in row["dispositions"]
        ]
        self.assertTrue(projected)
        self.assertTrue(all(row.get("projection_id") for row in projected))
        self.assertTrue(all(row.get("target_markers") for row in projected))
        self.assertTrue(
            any("runtime/operative_charter.md" in row["operative_home"] for row in projected)
        )
        covered_ids = [
            clause_id
            for row in document["clauses"]
            for clause_id in row["source_clause_ids"]
        ]
        self.assertEqual(len(covered_ids), len(set(covered_ids)))
        self.assertEqual(set(framework_consistency.msa_clause_ids()), set(covered_ids))

    def test_msa_digest_algorithm_has_fixed_known_answer_vectors(self) -> None:
        vectors = (
            (
                "crlf",
                b"alpha\r\nbeta\r\n",
                b"alpha\nbeta\n",
                "e49c81e2d2f84e259d40e2fb8192f3bcd198b355184845d76d8f58807d0d78ee",
            ),
            (
                "bare-cr",
                b"alpha\rbeta\r",
                b"alpha\nbeta\n",
                "e49c81e2d2f84e259d40e2fb8192f3bcd198b355184845d76d8f58807d0d78ee",
            ),
            (
                "ascii-sp-htab-trailing-only",
                b"alpha \t\r\nbeta\t \n",
                b"alpha\nbeta\n",
                "e49c81e2d2f84e259d40e2fb8192f3bcd198b355184845d76d8f58807d0d78ee",
            ),
            (
                "internal-sp-htab",
                b"alpha beta\tgamma \t",
                b"alpha beta\tgamma\n",
                "8f7b325e367e142c4a2f00d4d92fa98450315e3711b7b87ad5c78cdd537a1cee",
            ),
            (
                "internal-empty-line",
                b"alpha\r\n\r\nbeta\r\n",
                b"alpha\n\nbeta\n",
                "0e937c34625ef864d694878f01fd96318893d29014a51536006dacd150d809ec",
            ),
            (
                "terminal-empty-lines",
                b"alpha\n\n \t\r\n\t \n",
                b"alpha\n",
                "b6a98d9ce9a2d9149288fa3df42d377c3e42737afdcdaf714e33c0a100b51060",
            ),
            (
                "empty-input",
                b"",
                b"\n",
                "01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b",
            ),
            (
                "missing-final-lf",
                b"alpha",
                b"alpha\n",
                "b6a98d9ce9a2d9149288fa3df42d377c3e42737afdcdaf714e33c0a100b51060",
            ),
            (
                "many-final-lfs",
                b"alpha\n\n\n",
                b"alpha\n",
                "b6a98d9ce9a2d9149288fa3df42d377c3e42737afdcdaf714e33c0a100b51060",
            ),
            (
                "non-ascii-whitespace-preserved",
                b"alpha\xc2\xa0 \t",
                b"alpha\xc2\xa0\n",
                "12cc692615433677f126ae32e3770e393d816c0dbdc47d50455753453d53960f",
            ),
        )

        for name, raw, canonical, digest in vectors:
            with self.subTest(name=name):
                self.assertEqual(
                    canonical,
                    framework_consistency.normalize_msa_digest_input(raw),
                )
                self.assertEqual(
                    digest,
                    framework_consistency.normalized_bytes_digest(raw),
                )

        with self.assertRaises(UnicodeDecodeError):
            framework_consistency.normalize_msa_digest_input(b"\xff")

    def test_project_authority_loading_requires_clear_transaction_control_gate(
        self,
    ) -> None:
        msa = (REPO_ROOT / "master_service_agreement.md").read_text(encoding="utf-8")
        charter = (REPO_ROOT / "runtime" / "operative_charter.md").read_text(
            encoding="utf-8"
        )
        control_set = (
            ".mpa-bootstrap-recovery.json",
            ".mpa-bootstrap.lock",
            ".mpa-bootstrap-recovery.tmp",
        )

        for surface in (msa, charter):
            with self.subTest(surface=surface.splitlines()[0]):
                for member in control_set:
                    self.assertIn(f"`{member}`", surface)
                self.assertIn(
                    "Only when no member exists is the gate clear; then read the project contract before acting.",
                    surface,
                )

        self.assertLess(
            msa.index("load the Operative Charter"),
            msa.index("Before loading the project contract"),
        )
        self.assertLess(
            msa.index("Before loading the project contract"),
            msa.index("Only when no member exists is the gate clear"),
        )
        self.assertLess(
            charter.index("after loading this charter"),
            charter.index("before loading the project contract"),
        )
        self.assertLess(
            charter.index("before loading the project contract"),
            charter.index("Only when no member exists is the gate clear"),
        )

    def test_clause_map_digest_and_projection_marker_guards_reject_drift(self) -> None:
        document = query_clause_map.load_clause_map(REPO_ROOT)
        errors: list[str] = []
        drifted = dict(document)
        drifted["msa_digest_sha256"] = "0" * 64

        framework_consistency.validate_msa_digest(drifted, errors)

        self.assertIn(
            "clause map msa_digest_sha256 does not match master_service_agreement.md",
            errors,
        )

        projected = next(row for row in document["clauses"] if "projected" in row["dispositions"])
        errors = []
        missing_marker = dict(projected)
        missing_marker["target_markers"] = {}

        framework_consistency.validate_clause_projection_markers(missing_marker, errors)

        self.assertIn(f"projected clause lacks target_markers: {projected['source']}", errors)

        errors = []
        bad_marker = dict(projected)
        bad_marker["target_markers"] = {
            projected["operative_home"][0]: ["msa-99-99"]
        }

        framework_consistency.validate_clause_projection_markers(bad_marker, errors)

        self.assertTrue(any("target_markers" in error or "target marker missing" in error for error in errors), errors)

        unknown_field = dict(projected)
        unknown_field["unexpected_projection_field"] = "not in the current schema"
        errors = framework_consistency.unknown_field_errors(
            f"clause map {projected['source']}",
            unknown_field,
            framework_consistency.CLAUSE_ROW_FIELDS,
        )

        self.assertTrue(any("unknown fields: unexpected_projection_field" in error for error in errors), errors)

        guide_errors = framework_consistency.unknown_field_errors(
            "operative schedule example",
            {
                "name": "example",
                "path": "practice_guides/example.md",
                "category": "review",
                "trigger_flags": [],
                "wrapper_status": "not-applicable",
                "unexpected_guide_field": True,
            },
            framework_consistency.PRACTICE_GUIDE_FIELDS,
        )
        self.assertEqual(
            ["operative schedule example has unknown fields: unexpected_guide_field"],
            guide_errors,
        )

    def test_clause_map_digest_guard_rejects_unknown_transform(self) -> None:
        document = query_clause_map.load_clause_map(REPO_ROOT)
        drifted = dict(document)
        drifted["msa_digest_algorithm"] = "sha256-v2-unknown-transform"
        errors: list[str] = []

        framework_consistency.validate_msa_digest(drifted, errors)

        self.assertEqual(
            [
                "clause map msa_digest_algorithm is unsupported; expected "
                f"{framework_consistency.MSA_DIGEST_ALGORITHM}"
            ],
            errors,
        )

    def test_clause_map_rejects_missing_duplicate_and_human_row_drift(self) -> None:
        document = query_clause_map.load_clause_map(REPO_ROOT)
        rows = [dict(row) for row in document["clauses"]]
        errors: list[str] = []
        rows[0]["source_clause_ids"] = rows[0]["source_clause_ids"][1:]

        framework_consistency.validate_clause_id_coverage(rows, errors)

        self.assertTrue(any("clause map missing MSA clause ids" in error for error in errors))

        rows = [dict(row) for row in document["clauses"]]
        rows[1]["source_clause_ids"] = rows[1]["source_clause_ids"] + [rows[0]["source_clause_ids"][0]]
        errors = []

        framework_consistency.validate_clause_id_coverage(rows, errors)

        self.assertTrue(any("clause map duplicates MSA clause id" in error for error in errors))

        human_text = (REPO_ROOT / "runtime" / "clause_classification.md").read_text(encoding="utf-8")
        drifted_human_text = human_text.replace(
            "| Article 1 Definitions | canonical-only |",
            "| Article 1 Definitions | projected |",
            1,
        )
        errors = []

        framework_consistency.validate_human_clause_table(document["clauses"], drifted_human_text, errors)

        self.assertTrue(
            any("human-readable clause classification disposition drift" in error for error in errors)
        )

    def test_workflow_catalog_models_actions_and_evaluate_branches(self) -> None:
        catalog = validate_framework.load_json(REPO_ROOT / "runtime" / "workflow_catalog.json")
        sequences = {item["name"]: item for item in catalog["common_sequences"]}
        entries = {item["name"]: item for item in catalog["task_orders"]}

        feature_steps = sequences["feature_hardening"]["steps"]
        self.assertEqual(
            "downstream_or_project_local",
            sequences["feature_hardening"]["ownership_scope"],
        )
        self.assertIn(
            {"action": "implementation", "requires_authorization": True},
            feature_steps,
        )
        ownership_route = [
            {
                "action": "classify candidate ownership",
                "outcome_branches": {
                    "downstream_or_project_local": [
                        {
                            "order": "plan",
                            "requires": "planning is separately authorized",
                        }
                    ],
                    "shared_or_reusable_framework": [
                        {"order": "framework_semantic_audit"}
                    ],
                },
            }
        ]
        self.assertEqual(
            ownership_route,
            entries["evaluate"]["outcome_next_steps"]["Adopt"],
        )
        self.assertEqual(
            ownership_route,
            sequences["external_proposal_review"]["outcome_branches"]["Adopt"],
        )
        self.assertEqual(
            ownership_route,
            sequences["external_proposal_review"]["outcome_branches"]["Adapt"],
        )
        self.assertEqual([], sequences["external_proposal_review"]["outcome_branches"]["Reject"])

        for outcome in (
            "Approve recommendation",
            "Reimplement recommendation",
            "Partial adoption recommendation",
        ):
            steps = entries["pull_request"]["outcome_next_steps"][outcome]
            branches = steps[0]["outcome_branches"]
            self.assertEqual(
                [{"order": "framework_semantic_audit"}],
                branches["shared_or_reusable_framework"],
            )
            self.assertEqual(
                "plan",
                branches["downstream_or_project_local"][0]["order"],
            )
            self.assertEqual(
                steps,
                sequences["external_contribution"]["outcome_branches"][outcome],
            )

        errors: list[str] = []
        referenced_orders = list(
            framework_consistency.iter_step_orders(feature_steps, errors, "feature_hardening")
        )
        self.assertFalse(errors)
        self.assertIn("plan", referenced_orders)
        self.assertIn("review", referenced_orders)

        self.assertIn("optional reviewer lane plan", entries["orchestrate"]["primary_outputs"])
        self.assertIn("bounded reviewer lanes", entries["orchestrate"]["use_when"])

        arbitrate_outcomes = entries["arbitrate"]["outcome_next_steps"]
        self.assertEqual(
            {
                "validated_recommendation",
                "ratified_decision",
                "no_majority_no_decision",
                "insufficient_evidence_no_decision",
                "abstain_no_decision",
            },
            set(entries["arbitrate"]["outcome_enum"]),
        )
        self.assertEqual(
            framework_consistency.ARBITRATION_RATIFIED_NEXT_STEPS,
            arbitrate_outcomes["ratified_decision"],
        )
        self.assertEqual(
            [
                {"action": "collect missing evidence", "requires_authorization": True},
                {"action": "reconstitute panel", "requires_authorization": True},
                {"action": "request User or SOW owner decision", "requires_authorization": True},
            ],
            arbitrate_outcomes["no_majority_no_decision"],
        )

    def test_framework_candidate_routes_require_semantic_audit_before_improvement(
        self,
    ) -> None:
        catalog = validate_framework.load_json(
            REPO_ROOT / "runtime" / "workflow_catalog.json"
        )
        entries = {item["name"]: item for item in catalog["task_orders"]}
        sequences = {item["name"]: item for item in catalog["common_sequences"]}
        audit_route = [{"order": "framework_semantic_audit"}]
        improvement_route = [{"order": "framework_improvement"}]

        expected_feedback_branches = {
            "promote": audit_route,
            "adapt": audit_route,
            "reject": [],
            "no-action": [],
        }
        intake = entries["framework_feedback_intake"]
        self.assertEqual(
            set(expected_feedback_branches),
            set(intake["outcome_enum"]),
        )
        self.assertEqual(
            expected_feedback_branches,
            intake["outcome_next_steps"],
        )
        self.assertEqual(
            expected_feedback_branches,
            sequences["framework_feedback_review"]["outcome_branches"],
        )

        audit = entries["framework_semantic_audit"]
        expected_audit_branches = {
            "approve": improvement_route,
            "approve-with-edits": improvement_route,
            "reject": [],
            "needs-evidence": [{"action": "collect missing evidence"}],
        }
        self.assertEqual(
            set(expected_audit_branches),
            set(audit["outcome_enum"]),
        )
        self.assertEqual(expected_audit_branches, audit["outcome_next_steps"])
        self.assertIn(
            "binding proportional evaluation class",
            audit["primary_outputs"],
        )

        candidate_sequence = sequences["framework_candidate_improvement"]
        self.assertEqual(audit_route, candidate_sequence["steps"])
        self.assertEqual(
            expected_audit_branches,
            candidate_sequence["outcome_branches"],
        )

    def test_framework_improvement_route_safety_is_explicit(self) -> None:
        catalog = validate_framework.load_json(
            REPO_ROOT / "runtime" / "workflow_catalog.json"
        )
        entries = {item["name"]: item for item in catalog["task_orders"]}
        improvement = entries["framework_improvement"]

        expected_branches = {
            "ready-for-act": [
                {
                    "action": (
                        "obtain explicit framework-maintainer act authority for "
                        "the bound candidate and evaluation contract"
                    ),
                    "requires_authorization": True,
                },
                {
                    "order": "framework_improvement",
                    "mode": "act",
                    "requires": (
                        "framework-maintainer act authority is bound to the "
                        "exact candidate and evaluation contract"
                    ),
                },
            ],
            "retain": [
                {"order": "commit", "requires_authorization": True},
            ],
            "revise": [
                {
                    "order": "framework_improvement",
                    "mode": "act",
                    "requires": (
                        "existing act authority covers the revision without a "
                        "scope, class, or effect expansion and the predeclared "
                        "evaluation is repeated"
                    ),
                }
            ],
            "revert": [{"order": "backout"}],
            "needs-evidence": [
                {
                    "action": "collect missing evidence",
                    "requires": "no unaccepted candidate effects remain active",
                }
            ],
            "no-action": [],
        }

        self.assertEqual(
            "task_orders/framework_improvement.md",
            improvement["path"],
        )
        self.assertIsNone(improvement["runtime_task_module"])
        self.assertEqual("task_order", improvement["effect_owner"])
        self.assertEqual(
            "shared_or_reusable_framework_product",
            improvement["effect_scope"],
        )
        self.assertEqual(
            ["framework-improvement-authorized-change"],
            improvement["owned_effect_action_ids"],
        )
        self.assertEqual(
            ["authorized framework candidate changes"],
            improvement["owned_effect_actions"],
        )
        self.assertEqual(set(expected_branches), set(improvement["outcome_enum"]))
        self.assertEqual(expected_branches, improvement["outcome_next_steps"])

        self.assertEqual("assess", improvement["default_invocation_mode"])
        self.assertIn("no-action", improvement["allowed_outcomes_by_mode"]["act"])
        self.assertEqual(
            "zero-effects",
            improvement["effect_state_by_outcome"]["no-action"],
        )
        self.assertEqual(
            "restoration-required",
            improvement["effect_state_by_outcome"]["revert"],
        )

    def test_framework_improvement_interface_rejects_illegal_combinations(self) -> None:
        catalog = validate_framework.load_json(
            REPO_ROOT / "runtime" / "workflow_catalog.json"
        )
        original = catalog["task_orders"]

        cases: tuple[tuple[str, Any, str], ...] = (
            (
                "producer-class-drift",
                lambda entries: next(
                    item
                    for item in entries
                    if item["name"] == "framework_semantic_audit"
                )["produced_evaluation_class_enum"].pop(),
                "produced_evaluation_class_enum must match",
            ),
            (
                "consumer-class-drift",
                lambda entries: next(
                    item
                    for item in entries
                    if item["name"] == "framework_improvement"
                )["accepted_evaluation_class_enum"].pop(),
                "accepted_evaluation_class_enum must match",
            ),
            (
                "illegal-assess-retain",
                lambda entries: next(
                    item
                    for item in entries
                    if item["name"] == "framework_improvement"
                )["allowed_outcomes_by_mode"]["assess"].append("retain"),
                "illegal mode/outcome pairing",
            ),
            (
                "illegal-act-ready-for-act",
                lambda entries: next(
                    item
                    for item in entries
                    if item["name"] == "framework_improvement"
                )["allowed_outcomes_by_mode"]["act"].append("ready-for-act"),
                "illegal mode/outcome pairing",
            ),
            (
                "wrong-default-mode",
                lambda entries: next(
                    item
                    for item in entries
                    if item["name"] == "framework_improvement"
                ).__setitem__("default_invocation_mode", "act"),
                "default_invocation_mode must be assess",
            ),
            (
                "premature-zero-effect-revert",
                lambda entries: next(
                    item
                    for item in entries
                    if item["name"] == "framework_improvement"
                )["effect_state_by_outcome"].__setitem__("revert", "zero-effects"),
                "effect_state_by_outcome must match",
            ),
            (
                "nonzero-no-action",
                lambda entries: next(
                    item
                    for item in entries
                    if item["name"] == "framework_improvement"
                )["effect_state_by_outcome"].__setitem__(
                    "no-action",
                    "accepted-effects-active",
                ),
                "effect_state_by_outcome must match",
            ),
        )

        for name, mutate, expected_error in cases:
            with self.subTest(name=name):
                entries = json.loads(json.dumps(original))
                mutate(entries)
                errors: list[str] = []
                framework_consistency.validate_framework_improvement_interface(
                    entries,
                    errors,
                )
                self.assertTrue(
                    any(expected_error in error for error in errors),
                    errors,
                )

    def test_plan_effect_route_excludes_shared_framework_candidates(self) -> None:
        catalog = validate_framework.load_json(
            REPO_ROOT / "runtime" / "workflow_catalog.json"
        )
        entries = {item["name"]: item for item in catalog["task_orders"]}
        plan = entries["plan"]

        self.assertEqual([], plan["common_next_orders"])
        self.assertEqual(
            ["shared or reusable framework candidate implementation"],
            plan["effect_exclusions"],
        )
        self.assertEqual(
            [
                {
                    "action": "classify planned work ownership",
                    "outcome_branches": {
                        "downstream_or_project_local": [
                            {
                                "action": "implementation",
                                "requires_authorization": True,
                            },
                            {"order": "review"},
                            {"order": "audit"},
                            {"order": "commit", "requires_authorization": True},
                        ],
                        "shared_or_reusable_framework_candidate": [
                            {
                                "order": "framework_semantic_audit",
                                "requires": (
                                    "framework candidate has not already entered "
                                    "framework_improvement"
                                ),
                            }
                        ],
                    },
                }
            ],
            plan["common_next_steps"],
        )

    def test_ideate_and_independent_assessment_route_by_ownership(self) -> None:
        catalog = validate_framework.load_json(
            REPO_ROOT / "runtime" / "workflow_catalog.json"
        )
        entries = {item["name"]: item for item in catalog["task_orders"]}
        sequences = {item["name"]: item for item in catalog["common_sequences"]}

        ideate = entries["ideate"]
        self.assertEqual([], ideate["common_next_orders"])
        self.assertEqual(
            [
                {"order": "ideate"},
                *ideate["common_next_steps"],
            ],
            sequences["exploratory_mandate"]["steps"],
        )

        assessment = entries["independent_assessment"]
        self.assertEqual(
            assessment["outcome_next_steps"],
            sequences["technical_uncertainty"]["outcome_branches"],
        )

        direct_plan = json.loads(json.dumps(catalog["task_orders"]))
        direct_assessment = next(
            item for item in direct_plan if item["name"] == "independent_assessment"
        )
        direct_assessment["outcome_next_steps"]["actionable_assessment"] = [
            {
                "order": "plan",
                "requires": "assessment validated and User or SOW authorization to proceed",
            }
        ]
        errors: list[str] = []
        framework_consistency.validate_guarded_workflow_transitions(
            direct_plan,
            errors,
        )
        self.assertTrue(
            any(
                "actionable_assessment must route by ownership" in error
                for error in errors
            ),
            errors,
        )

    def test_common_next_orders_project_only_unguarded_structured_orders(self) -> None:
        catalog = validate_framework.load_json(
            REPO_ROOT / "runtime" / "workflow_catalog.json"
        )
        original = next(
            item for item in catalog["task_orders"] if item["name"] == "backout"
        )
        catalog_names = [item["name"] for item in catalog["task_orders"]]

        self.assertEqual(["review", "audit"], original["common_next_orders"])
        self.assertEqual(
            {"order": "commit", "requires_authorization": True},
            original["common_next_steps"][-1],
        )

        cases = (
            (
                "guarded-order-leaks-into-unconditional-projection",
                lambda entry: entry["common_next_orders"].append("commit"),
            ),
            (
                "newly-unguarded-order-missing-from-projection",
                lambda entry: entry["common_next_steps"][-1].pop(
                    "requires_authorization"
                ),
            ),
        )
        for name, mutate in cases:
            with self.subTest(name=name):
                entry = json.loads(json.dumps(original))
                mutate(entry)
                errors: list[str] = []
                framework_consistency.validate_catalog_transitions(
                    entry,
                    "backout",
                    catalog_names,
                    errors,
                )
                self.assertTrue(
                    any(
                        "common_next_orders must match unguarded direct "
                        "common_next_steps orders" in error
                        for error in errors
                    ),
                    errors,
                )

    def test_workflow_catalog_closed_schema_accepts_all_flags_profile(self) -> None:
        catalog = validate_framework.load_json(
            REPO_ROOT / "runtime" / "workflow_catalog.json"
        )
        all_flags_catalog = json.loads(json.dumps(catalog))
        ideate = next(
            item for item in all_flags_catalog["task_orders"] if item["name"] == "ideate"
        )
        condition = ideate["runtime_task_module"]["use_full_when_conditions"][0]
        condition["all_flags"] = condition.pop("any_flags")
        all_flags_errors: list[str] = []
        framework_consistency.validate_workflow_catalog_schema(
            all_flags_catalog,
            all_flags_errors,
        )
        self.assertEqual([], all_flags_errors)

    def test_workflow_catalog_rejects_alias_task_order_path(self) -> None:
        catalog = validate_framework.load_json(
            REPO_ROOT / "runtime" / "workflow_catalog.json"
        )
        malformed = json.loads(json.dumps(catalog))
        alias = json.loads(
            json.dumps(
                next(
                    entry
                    for entry in malformed["task_orders"]
                    if entry["name"] == "commit"
                )
            )
        )
        alias["name"] = "commit_alias"
        malformed["task_orders"].append(alias)
        errors: list[str] = []

        framework_consistency.validate_workflow_catalog_contract(
            malformed,
            validate_framework.load_json(
                REPO_ROOT / "runtime" / "task_module_obligations.json"
            ),
            errors,
        )

        self.assertTrue(
            any(
                "task order path task_orders/commit.md has multiple owners: "
                "commit, commit_alias" in error
                for error in errors
            ),
            errors,
        )
        self.assertIn(
            "workflow catalog task order path cardinality must match the "
            "task_orders inventory",
            errors,
        )
        self.assertIn(
            "workflow catalog commit_alias path must be task_orders/commit_alias.md",
            errors,
        )

    def test_workflow_catalog_rejects_duplicate_runtime_module_owner(self) -> None:
        catalog = validate_framework.load_json(
            REPO_ROOT / "runtime" / "workflow_catalog.json"
        )
        malformed = json.loads(json.dumps(catalog))
        ideate = next(
            entry for entry in malformed["task_orders"] if entry["name"] == "ideate"
        )
        compliance = next(
            entry
            for entry in malformed["task_orders"]
            if entry["name"] == "compliance"
        )
        compliance["runtime_task_module"] = json.loads(
            json.dumps(ideate["runtime_task_module"])
        )
        compliance["runtime_task_module"]["canonical_task_order"] = compliance["path"]
        errors: list[str] = []

        framework_consistency.validate_workflow_catalog_contract(
            malformed,
            validate_framework.load_json(
                REPO_ROOT / "runtime" / "task_module_obligations.json"
            ),
            errors,
        )

        self.assertIn(
            "workflow catalog runtime module name ideate has multiple owners: "
            "compliance, ideate",
            errors,
        )
        self.assertIn(
            "workflow catalog runtime module path runtime/task_modules/ideate.md "
            "has multiple owners: compliance, ideate",
            errors,
        )
        self.assertIn(
            "workflow catalog runtime module name cardinality must match the runtime "
            "module inventory",
            errors,
        )
        self.assertIn(
            "workflow catalog runtime module path cardinality must match the runtime "
            "module inventory",
            errors,
        )

    def test_workflow_catalog_rejects_duplicate_common_sequence_name(self) -> None:
        catalog = validate_framework.load_json(
            REPO_ROOT / "runtime" / "workflow_catalog.json"
        )
        malformed = json.loads(json.dumps(catalog))
        malformed["common_sequences"].append(
            json.loads(json.dumps(malformed["common_sequences"][0]))
        )
        errors: list[str] = []

        framework_consistency.validate_workflow_catalog_contract(
            malformed,
            validate_framework.load_json(
                REPO_ROOT / "runtime" / "task_module_obligations.json"
            ),
            errors,
        )

        self.assertTrue(
            any(
                "workflow catalog common sequence name " in error
                and "has multiple owners" in error
                for error in errors
            ),
            errors,
        )

    def test_workflow_catalog_closed_lists_reject_duplicate_values(self) -> None:
        catalog = validate_framework.load_json(
            REPO_ROOT / "runtime" / "workflow_catalog.json"
        )
        cases = (
            (
                "selection-provenance",
                lambda document: document["workflow_selection"][
                    "known_workflow_provenance"
                ].append(
                    document["workflow_selection"]["known_workflow_provenance"][0]
                ),
                "workflow_selection.known_workflow_provenance",
            ),
            (
                "ambiguous-route-condition",
                lambda document: document["workflow_selection"][
                    "ambiguous_workflow_route"
                ]["conditions"].append(
                    document["workflow_selection"]["ambiguous_workflow_route"][
                        "conditions"
                    ][0]
                ),
                "ambiguous_workflow_route.conditions",
            ),
            (
                "ambiguous-route-fallback",
                lambda document: document["workflow_selection"][
                    "ambiguous_workflow_route"
                ]["fallback_references"].append(
                    document["workflow_selection"]["ambiguous_workflow_route"][
                        "fallback_references"
                    ][0]
                ),
                "ambiguous_workflow_route.fallback_references",
            ),
            (
                "escalation-condition-flags",
                lambda document: next(
                    entry
                    for entry in document["task_orders"]
                    if entry["name"] == "ideate"
                )["runtime_task_module"]["use_full_when_conditions"][0][
                    "any_flags"
                ].append(
                    next(
                        entry
                        for entry in document["task_orders"]
                        if entry["name"] == "ideate"
                    )["runtime_task_module"]["use_full_when_conditions"][0][
                        "any_flags"
                    ][0]
                ),
                "use_full_when_conditions[0].any_flags",
            ),
        )

        for name, mutate, expected_label in cases:
            with self.subTest(name=name):
                malformed = json.loads(json.dumps(catalog))
                mutate(malformed)
                errors: list[str] = []
                framework_consistency.validate_workflow_catalog_schema(
                    malformed,
                    errors,
                )
                self.assertTrue(
                    any(
                        expected_label in error
                        and "must not contain duplicate values" in error
                        for error in errors
                    ),
                    errors,
                )

    def test_workflow_catalog_rejects_runtime_condition_identity_drift(self) -> None:
        catalog = validate_framework.load_json(
            REPO_ROOT / "runtime" / "workflow_catalog.json"
        )
        cases = (
            (
                "duplicate-use-full-description",
                lambda module: module["use_full_when"].append(
                    module["use_full_when"][0]
                ),
                "use_full_when must not contain duplicate values",
            ),
            (
                "duplicate-condition-id",
                lambda module: module["use_full_when_conditions"][1].__setitem__(
                    "id",
                    module["use_full_when_conditions"][0]["id"],
                ),
                "use_full_when_conditions must define unique condition IDs",
            ),
            (
                "duplicate-condition-description",
                lambda module: module["use_full_when_conditions"][1].__setitem__(
                    "description",
                    module["use_full_when_conditions"][0]["description"],
                ),
                "use_full_when_conditions must define unique condition descriptions",
            ),
            (
                "description-inventory-drift",
                lambda module: module["use_full_when"].__setitem__(
                    0,
                    "a description with no machine condition",
                ),
                "use_full_when descriptions must exactly match "
                "use_full_when_conditions descriptions",
            ),
            (
                "unknown-condition-flag",
                lambda module: module["use_full_when_conditions"][0][
                    "any_flags"
                ].append(
                    "nonexistent_runtime_flag"
                ),
                "uses unknown runtime condition flags: nonexistent_runtime_flag",
            ),
            (
                "invalid-delegated-obligation-id",
                lambda module: module["use_full_when_conditions"][1].__setitem__(
                    "delegated_obligation_id",
                    "",
                ),
                "delegated_obligation_id must be a non-empty string",
            ),
            (
                "removed-identity-mirror",
                lambda module: module.__setitem__(
                    "use_full_when_ids",
                    {
                        "IDEATE-project-files": "the decision changes project files"
                    },
                ),
                "runtime_task_module has unknown fields: use_full_when_ids",
            ),
        )

        for name, mutate, expected_error in cases:
            with self.subTest(name=name):
                malformed = json.loads(json.dumps(catalog))
                module = next(
                    entry
                    for entry in malformed["task_orders"]
                    if entry["name"] == "ideate"
                )["runtime_task_module"]
                mutate(module)
                errors: list[str] = []

                framework_consistency.validate_workflow_catalog_schema(
                    malformed,
                    errors,
                )

                self.assertTrue(
                    any(expected_error in error for error in errors),
                    errors,
                )

    def test_obligation_binding_uses_actual_runtime_condition_identity(self) -> None:
        catalog = validate_framework.load_json(
            REPO_ROOT / "runtime" / "workflow_catalog.json"
        )
        manifest = validate_framework.load_json(
            REPO_ROOT / "runtime" / "task_module_obligations.json"
        )

        def assert_binding_rejected(
            name: str,
            candidate_manifest: dict[str, Any],
            candidate_entries: list[dict[str, Any]],
            expected_error: str,
        ) -> None:
            with self.subTest(name=name):
                errors: list[str] = []
                framework_consistency.validate_runtime_task_module_obligations(
                    candidate_manifest,
                    candidate_entries,
                    errors,
                )
                self.assertTrue(
                    any(expected_error in error for error in errors),
                    errors,
                )

        unknown_condition_manifest = json.loads(json.dumps(manifest))
        ideate_rule = unknown_condition_manifest["modules"][
            "runtime/task_modules/ideate.md"
        ]
        delegated = next(
            coverage
            for coverage in ideate_rule["runtime_coverage"].values()
            if coverage["status"] == "delegates_to_full_order"
        )
        delegated["catalog_condition_id"] = "IDEATE-nonexistent"
        assert_binding_rejected(
            "unknown-condition-id",
            unknown_condition_manifest,
            catalog["task_orders"],
            "delegates without catalog condition id",
        )

        duplicate_identity_catalog = json.loads(json.dumps(catalog))
        duplicate_conditions = next(
            entry
            for entry in duplicate_identity_catalog["task_orders"]
            if entry["name"] == "ideate"
        )["runtime_task_module"]["use_full_when_conditions"]
        duplicate_conditions[0]["id"] = "IDEATE-escalate-source-or-safety"
        assert_binding_rejected(
            "duplicate-condition-id",
            manifest,
            duplicate_identity_catalog["task_orders"],
            "delegates without catalog condition id",
        )

        swapped_identity_catalog = json.loads(json.dumps(catalog))
        swapped_conditions = next(
            entry
            for entry in swapped_identity_catalog["task_orders"]
            if entry["name"] == "ideate"
        )["runtime_task_module"]["use_full_when_conditions"]
        swapped_conditions[0]["id"], swapped_conditions[1]["id"] = (
            swapped_conditions[1]["id"],
            swapped_conditions[0]["id"],
        )
        assert_binding_rejected(
            "swapped-condition-identity",
            manifest,
            swapped_identity_catalog["task_orders"],
            "delegated condition-obligation identity mismatch",
        )

    def test_direct_full_routing_collisions_preserve_first_owner(self) -> None:
        catalog = validate_framework.load_json(
            REPO_ROOT / "runtime" / "workflow_catalog.json"
        )
        entries = json.loads(json.dumps(catalog["task_orders"]))
        for entry in entries:
            entry.pop("direct_full_when_flags", None)
        owners = [
            entry
            for entry in entries
            if entry.get("runtime_task_module") is None
        ][:3]
        self.assertEqual(3, len(owners))
        for entry in owners:
            entry["direct_full_when_flags"] = ["incident"]
        errors: list[str] = []

        framework_consistency.validate_catalog_entries(
            entries,
            validate_framework.load_json(
                REPO_ROOT / "runtime" / "task_module_obligations.json"
            ),
            errors,
        )

        first_owner = owners[0]["name"]
        collision_errors = [
            error
            for error in errors
            if "direct full routing flag incident has multiple owners" in error
        ]
        self.assertEqual(
            [
                "workflow catalog direct full routing flag incident has multiple "
                f"owners: {first_owner}, {owner['name']}"
                for owner in owners[1:]
            ],
            collision_errors,
        )

    def test_workflow_authorization_requires_an_exact_boolean(self) -> None:
        catalog = validate_framework.load_json(
            REPO_ROOT / "runtime" / "workflow_catalog.json"
        )
        malformed = json.loads(json.dumps(catalog))
        backout = next(
            item for item in malformed["task_orders"] if item["name"] == "backout"
        )
        backout["common_next_steps"][-1]["requires_authorization"] = "false"

        errors: list[str] = []
        framework_consistency.validate_workflow_catalog_contract(
            malformed,
            validate_framework.load_json(
                REPO_ROOT / "runtime" / "task_module_obligations.json"
            ),
            errors,
        )
        self.assertTrue(
            any(
                "requires_authorization must be a boolean" in error
                for error in errors
            ),
            errors,
        )
        self.assertTrue(
            any(
                "common_next_orders must match unguarded direct "
                "common_next_steps orders" in error
                for error in errors
            ),
            errors,
        )

    def test_workflow_catalog_closed_schema_rejects_malformed_nested_shapes(
        self,
    ) -> None:
        catalog = validate_framework.load_json(
            REPO_ROOT / "runtime" / "workflow_catalog.json"
        )

        cases: tuple[tuple[str, Any, str], ...] = (
            (
                "unknown-step-field",
                lambda document: document["common_sequences"][0]["steps"].__setitem__(
                    0,
                    {"order": "init", "approval_guard": True},
                ),
                "common_sequences[0].steps[0] has unknown fields: approval_guard",
            ),
            (
                "branch-value-is-not-a-step-list",
                lambda document: next(
                    item
                    for item in document["task_orders"]
                    if item["name"] == "evaluate"
                )["outcome_next_steps"].__setitem__("Adopt", {"order": "plan"}),
                "outcome_next_steps.Adopt must be a workflow-step list",
            ),
            (
                "condition-flags-are-not-a-list",
                lambda document: next(
                    item
                    for item in document["task_orders"]
                    if item["name"] == "review"
                )["runtime_task_module"]["use_full_when_conditions"][0].__setitem__(
                    "any_flags",
                    "security",
                ),
                "use_full_when_conditions[0].any_flags must be a list of non-empty strings",
            ),
            (
                "nested-branch-step-has-two-selectors",
                lambda document: next(
                    item
                    for item in document["task_orders"]
                    if item["name"] == "source_update"
                )["mode_next_steps"]["act"][0].__setitem__(
                    "action",
                    "also act",
                ),
                "mode_next_steps.act[0] must define exactly one of order or action",
            ),
        )

        for name, mutate, expected_error in cases:
            with self.subTest(name=name):
                malformed = json.loads(json.dumps(catalog))
                mutate(malformed)
                errors: list[str] = []
                framework_consistency.validate_workflow_catalog_schema(
                    malformed,
                    errors,
                )
                self.assertTrue(
                    any(expected_error in error for error in errors),
                    errors,
                )

    def test_review_and_audit_route_active_improvement_before_shared_framework(self) -> None:
        catalog = validate_framework.load_json(
            REPO_ROOT / "runtime" / "workflow_catalog.json"
        )
        entries = {item["name"]: item for item in catalog["task_orders"]}

        for name in ("review", "audit"):
            with self.subTest(name=name):
                branches = entries[name]["common_next_steps"][0]["outcome_branches"]
                self.assertEqual(
                    "active_framework_improvement",
                    next(iter(branches)),
                )
                self.assertIn(
                    "shared_or_reusable_framework_outside_active_framework_improvement",
                    branches,
                )
                self.assertNotIn("shared_or_reusable_framework", branches)

    def test_workflow_catalog_branch_contracts_reject_drift(self) -> None:
        catalog = validate_framework.load_json(REPO_ROOT / "runtime" / "workflow_catalog.json")
        entries = json.loads(json.dumps(catalog["task_orders"]))
        sequences = json.loads(json.dumps(catalog["common_sequences"]))

        body_drift_sequences = json.loads(json.dumps(sequences))
        external_proposal = next(
            sequence
            for sequence in body_drift_sequences
            if sequence["name"] == "external_proposal_review"
        )
        external_proposal["outcome_branches"]["Adopt"][0]["outcome_branches"][
            "downstream_or_project_local"
        ][0]["requires"] = "a drifted authorization guard"
        body_drift_errors: list[str] = []
        framework_consistency.validate_workflow_branch_contracts(
            entries,
            body_drift_sequences,
            body_drift_errors,
        )
        self.assertIn(
            "workflow sequence external_proposal_review outcome branches must "
            "match evaluate branch contract",
            body_drift_errors,
        )

        pull_request = next(entry for entry in entries if entry["name"] == "pull_request")
        pull_request["outcome_next_steps"]["not-an-emitted-outcome"] = pull_request[
            "outcome_next_steps"
        ].pop("Comment")
        errors = []
        framework_consistency.validate_workflow_branch_contracts(entries, sequences, errors)
        self.assertTrue(
            any("pull_request outcome_next_steps keys must match outcome_enum" in error for error in errors),
            errors,
        )

        marker_drift_entries = json.loads(json.dumps(catalog["task_orders"]))
        evaluate = next(
            entry for entry in marker_drift_entries if entry["name"] == "evaluate"
        )
        evaluate["outcome_enum"][-1] = "defer"
        marker_errors: list[str] = []
        framework_consistency.validate_workflow_branch_contracts(
            marker_drift_entries,
            sequences,
            marker_errors,
        )
        self.assertTrue(
            any(
                "workflow task order evaluate mpa-workflow-contract marker must match"
                in error
                for error in marker_errors
            ),
            marker_errors,
        )

    def test_workflow_contract_marker_rejects_missing_duplicate_and_malformed(self) -> None:
        valid = '<!-- mpa-workflow-contract: {"outcome_enum":["one"]} -->'
        malformed = '<!-- mpa-workflow-contract: {"outcome_enum":[} -->'
        array_payload = '<!-- mpa-workflow-contract: ["one"] -->'
        truncated = '<!-- mpa-workflow-contract: {"outcome_enum":["one"]'
        cases = (
            ("missing", "Task Order", "exactly one"),
            ("duplicate", f"{valid}\n{valid}", "found 2"),
            (
                "malformed",
                malformed,
                "invalid JSON",
            ),
            ("valid-plus-malformed", f"{valid}\n{malformed}", "found 2"),
            ("valid-plus-array", f"{valid}\n{array_payload}", "found 2"),
            ("valid-plus-truncated", f"{valid}\n{truncated}", "found 2"),
            (
                "unknown-field",
                '<!-- mpa-workflow-contract: {"unknown_enum":["one"]} -->',
                "unknown fields",
            ),
        )

        for name, text, expected_error in cases:
            with self.subTest(name=name):
                errors: list[str] = []
                framework_consistency.parse_workflow_contract_marker(
                    text,
                    "test task order",
                    errors,
                )
                self.assertTrue(
                    any(expected_error in error for error in errors),
                    errors,
                )

    def test_workflow_contract_marker_rejects_duplicate_json_key(self) -> None:
        marker = (
            '<!-- mpa-workflow-contract: {"outcome_enum":["shadowed"],'
            '"outcome_enum":["one"]} -->'
        )
        errors: list[str] = []

        payload = framework_consistency.parse_workflow_contract_marker(
            marker,
            "test task order",
            errors,
        )

        self.assertIsNone(payload)
        self.assertTrue(
            any("duplicate JSON key: outcome_enum" in error for error in errors),
            errors,
        )

    def test_workflow_catalog_rejects_duplicate_task_order_owned_effects(self) -> None:
        catalog = validate_framework.load_json(REPO_ROOT / "runtime" / "workflow_catalog.json")
        entries = json.loads(json.dumps(catalog["task_orders"]))
        sequences = json.loads(json.dumps(catalog["common_sequences"]))
        source_sequence = next(
            sequence for sequence in sequences if sequence["name"] == "source_sensitive_project_update"
        )
        source_entry = next(entry for entry in entries if entry["name"] == "source_update")
        owned_effect_id = source_entry["owned_effect_action_ids"][0]
        source_sequence["outcome_branches"]["act"].insert(
            0,
            {
                "action": "perform the separately authorized project update",
                "effect_action_id": owned_effect_id,
            },
        )
        errors: list[str] = []

        framework_consistency.validate_workflow_branch_contracts(entries, sequences, errors)

        self.assertTrue(
            any(
                "source_update repeats task-order-owned effect id" in error
                and owned_effect_id in error
                for error in errors
            ),
            errors,
        )

    def test_source_update_excludes_shared_framework_product_effects(self) -> None:
        catalog = validate_framework.load_json(
            REPO_ROOT / "runtime" / "workflow_catalog.json"
        )
        entries = {item["name"]: item for item in catalog["task_orders"]}
        sequences = {item["name"]: item for item in catalog["common_sequences"]}
        source_update = entries["source_update"]
        expected_act = [
            {"order": "review"},
            {"order": "audit"},
            {"order": "commit", "requires_authorization": True},
        ]
        expected_propose = [
            {
                "action": "classify proposal ownership",
                "outcome_branches": {
                    "downstream_or_project_local": [
                        {"action": "stop after the approved proposal or report artifact"}
                    ],
                    "shared_or_reusable_framework": [
                        {"order": "framework_semantic_audit"}
                    ],
                },
            }
        ]

        self.assertEqual(
            ["shared or reusable framework product changes"],
            source_update["effect_exclusions"],
        )
        self.assertEqual("task_order", source_update["effect_owner"])
        self.assertEqual(
            "downstream_or_project_local",
            source_update["effect_scope"],
        )
        self.assertEqual(
            ["source-update-authorized-change"],
            source_update["owned_effect_action_ids"],
        )
        self.assertEqual(
            expected_propose,
            source_update["mode_next_steps"]["propose"],
        )
        self.assertEqual(expected_act, source_update["mode_next_steps"]["act"])
        self.assertEqual(
            expected_propose,
            sequences["source_sensitive_project_update"]["outcome_branches"][
                "propose"
            ],
        )
        self.assertEqual(
            expected_act,
            sequences["source_sensitive_project_update"]["outcome_branches"]["act"],
        )

    def test_catalog_transition_validation_covers_mode_next_steps(self) -> None:
        catalog = validate_framework.load_json(
            REPO_ROOT / "runtime" / "workflow_catalog.json"
        )
        entry = next(
            json.loads(json.dumps(item))
            for item in catalog["task_orders"]
            if item["name"] == "source_update"
        )
        entry["mode_next_steps"]["act"][0]["order"] = "unknown-order"
        errors: list[str] = []

        framework_consistency.validate_catalog_transitions(
            entry,
            "source_update",
            [item["name"] for item in catalog["task_orders"]],
            errors,
        )

        self.assertIn(
            "workflow catalog source_update mode act references unknown next order: "
            "unknown-order",
            errors,
        )

    def test_arbitration_ratification_separates_records_from_implementation(
        self,
    ) -> None:
        catalog = validate_framework.load_json(
            REPO_ROOT / "runtime" / "workflow_catalog.json"
        )
        original_entries = catalog["task_orders"]

        cases = (
            (
                "unscoped-record-commit",
                lambda steps: steps[0].pop("scope"),
            ),
            (
                "shared-framework-direct-commit",
                lambda steps: steps[1]["outcome_branches"].__setitem__(
                    "shared_or_reusable_framework_outside_active_framework_improvement",
                    [{"order": "commit", "requires_authorization": True}],
                ),
            ),
        )
        for name, mutate in cases:
            with self.subTest(name=name):
                entries = json.loads(json.dumps(original_entries))
                mutated_arbitrate = next(
                    entry for entry in entries if entry["name"] == "arbitrate"
                )
                mutate(mutated_arbitrate["outcome_next_steps"]["ratified_decision"])
                errors: list[str] = []
                framework_consistency.validate_guarded_workflow_transitions(
                    entries,
                    errors,
                )
                self.assertTrue(
                    any(
                        "must separate decision-record commit from ownership-routed "
                        "implementation follow-up" in error
                        for error in errors
                    ),
                    errors,
                )

    def test_arbitration_compact_route_preserves_neutral_coordinator_safeguard(self) -> None:
        module_text = (REPO_ROOT / "runtime" / "task_modules" / "arbitrate.md").read_text(
            encoding="utf-8"
        )
        obligations = validate_framework.load_json(
            REPO_ROOT / "runtime" / "task_module_obligations.json"
        )
        catalog = validate_framework.load_json(REPO_ROOT / "runtime" / "workflow_catalog.json")
        arbitrate = next(entry for entry in catalog["task_orders"] if entry["name"] == "arbitrate")

        self.assertEqual(1, module_text.count("mpa-obligation: ARB-neutral-coordinator"))
        self.assertIn(
            "ARB-neutral-coordinator",
            obligations["modules"]["runtime/task_modules/arbitrate.md"]["critical_obligations"],
        )
        self.assertTrue(
            any(
                condition["id"] == "ARB-interested-coordinator"
                for condition in arbitrate["runtime_task_module"]["use_full_when_conditions"]
            )
        )

    def test_getting_started_discovers_then_uses_the_project_runner(self) -> None:
        text = (REPO_ROOT / "GETTING_STARTED.md").read_text(encoding="utf-8")
        normalized = " ".join(text.split())
        bootstrap_line = next(
            line.strip()
            for line in text.splitlines()
            if line.strip().startswith("<runner> ")
            and "scripts/project_bootstrap.py --dry-run" in line
        )

        self.assertIn(
            "python3 -B <framework-checkout-on-diagnostic-host>/scripts/check_prereqs.py",
            normalized,
        )
        self.assertIn(
            "python3 -B`, `py -3 -B`, and `uv run python -B` are candidate invocation spellings",
            normalized,
        )
        for bare_command in (
            "python3 -B scripts/check_prereqs.py",
            "py -3 -B scripts/check_prereqs.py",
            "uv run python -B scripts/check_prereqs.py",
        ):
            self.assertNotIn(bare_command, normalized)
        self.assertTrue(bootstrap_line.startswith("<runner> "), bootstrap_line)
        self.assertIn(
            "<framework-checkout-as-visible-to-runner>/scripts/project_bootstrap.py",
            bootstrap_line,
        )
        self.assertNotIn("uv run python -B scripts/project_bootstrap.py --dry-run", text)

    def test_bootstrap_public_guidance_requires_a_preexisting_project_root(self) -> None:
        getting_started = (REPO_ROOT / "GETTING_STARTED.md").read_text(encoding="utf-8")
        init_order = (REPO_ROOT / "task_orders" / "init.md").read_text(encoding="utf-8")
        scripts_readme = (REPO_ROOT / "scripts" / "README.md").read_text(encoding="utf-8")

        normalized_getting_started = " ".join(getting_started.split())
        normalized_init_order = " ".join(init_order.split())
        normalized_scripts_readme = " ".join(scripts_readme.split())

        for text in (getting_started, init_order, scripts_readme):
            self.assertNotIn("--create-project-root", text)

        self.assertIn(
            "Bootstrap does not create the governed project root",
            normalized_getting_started,
        )
        self.assertIn(
            "Bootstrap requires a pre-existing target project root",
            normalized_init_order,
        )
        self.assertIn(
            "Bootstrap never creates the governed project root",
            normalized_scripts_readme,
        )
        self.assertIn("--create-contract-root", scripts_readme)

    def test_commit_order_requires_staged_whitespace_gate_after_staging(self) -> None:
        commit_text = (REPO_ROOT / "task_orders" / "commit.md").read_text(encoding="utf-8")
        stage_index = commit_text.index("7. Stage only approved files or hunks.")
        staged_check_index = commit_text.index("Run `git diff --cached --check`.")
        commit_index = commit_text.index("12. Commit.")

        self.assertLess(stage_index, staged_check_index)
        self.assertLess(staged_check_index, commit_index)
        self.assertIn("Review `git diff --cached`, the staged file list", commit_text)

    def test_workflow_catalog_rejects_no_decision_order_transition(self) -> None:
        catalog = validate_framework.load_json(REPO_ROOT / "runtime" / "workflow_catalog.json")
        entries = json.loads(json.dumps(catalog["task_orders"]))
        arbitrate = next(entry for entry in entries if entry["name"] == "arbitrate")
        arbitrate["outcome_next_steps"]["insufficient_evidence_no_decision"] = [
            {"order": "commit", "requires_authorization": True}
        ]
        errors: list[str] = []

        framework_consistency.validate_guarded_workflow_transitions(entries, errors)

        self.assertTrue(
            any("insufficient_evidence_no_decision" in error and "must not route to operative order" in error for error in errors),
            errors,
        )

    def test_workflow_catalog_rejects_unguarded_no_decision_action(self) -> None:
        catalog = validate_framework.load_json(REPO_ROOT / "runtime" / "workflow_catalog.json")
        entries = json.loads(json.dumps(catalog["task_orders"]))
        arbitrate = next(entry for entry in entries if entry["name"] == "arbitrate")
        arbitrate["outcome_next_steps"]["abstain_no_decision"] = [{"action": "reconstitute panel"}]
        errors: list[str] = []

        framework_consistency.validate_guarded_workflow_transitions(entries, errors)

        self.assertTrue(
            any("abstain_no_decision" in error and "lacks requires_authorization" in error for error in errors),
            errors,
        )


    def test_every_recommended_check_has_explicit_verification_phase(self) -> None:
        schedule = recommend_stack.load_schedule()
        registered = set(verification_registry.CHECKS_BY_ID)
        scheduled = {
            check_id
            for evidence_rule in schedule["minimum_evidence_by_risk"].values()
            for check_id in evidence_rule["required_checks"]
        }

        self.assertTrue(scheduled <= registered)
        self.assertTrue(
            all(check.phase in verification_registry.PHASES for check in verification_registry.CHECKS)
        )

    def test_verification_plan_rejects_unmapped_required_checks(self) -> None:
        with self.assertRaisesRegex(KeyError, "new-unmapped-check"):
            verification_registry.resolve_check_ids(["new-unmapped-check"])
