"""Focused behavior tests for the resumable public-release controller."""

from __future__ import annotations

import argparse
from contextlib import nullcontext, redirect_stdout
from dataclasses import replace
import hashlib
import io
import os
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from tests.validation_test_support import REPO_ROOT, run_bounded  # noqa: F401

import public_release  # noqa: E402
import public_release_state  # noqa: E402


_PARENT = "a" * 40
_CANDIDATE = "b" * 40
_THIRD = "c" * 40
_OPERATION_ID = "controller-test-operation"
_CONTROLLER_SHA256 = "d" * 64
_REQUEST_SHA256 = "e" * 64
_TIMESTAMP = "2026-07-20T12:00:00+00:00"
_TEST_OPERATION_ROOT = Path(tempfile.gettempdir()) / "release-operation"
_TEST_GITHUB_CONFIG = Path(tempfile.gettempdir()) / "gh-config"


def _required_executable(name: str) -> Path:
    executable = shutil.which(name)
    if executable is None:
        raise RuntimeError(f"public release controller tests require {name}")
    return Path(executable).resolve(strict=True)


def _request(root: Path = REPO_ROOT) -> dict[str, object]:
    return {
        "schema_version": 1,
        "authoring_root": str(root),
        "git_executable": "/usr/bin/git",
        "uv_executable": "/usr/bin/uv",
        "python_executable": "/usr/bin/python3",
        "remote_name": "origin",
        "branch": "master",
        "remote_url": "https://github.com/example/framework.git",
        "public_name": "Release Fixture",
        "public_email": "release@example.invalid",
        "commit_message": "Publish verified framework update",
        "commit_timestamp": _TIMESTAMP,
    }


def _phase_payload(phase: str) -> dict[str, object]:
    if phase == "initialized":
        return {
            "request": _request(),
            "request_sha256": _REQUEST_SHA256,
            "controller_sha256": _CONTROLLER_SHA256,
        }
    if phase == "export-verified":
        return {
            "export_marker_sha256": "1" * 64,
            "git_sha256": "2" * 64,
            "python_sha256": "3" * 64,
            "uv_sha256": "4" * 64,
        }
    if phase == "staged-verified":
        return {
            "expected_parent": _PARENT,
            "staged_receipt": {"phase": "staged"},
            "commit_spec_sha256": "5" * 64,
        }
    if phase == "candidate-verified":
        return {
            "candidate_commit": _CANDIDATE,
            "committed_receipt": {"phase": "committed"},
            "staged_receipt_sha256": "6" * 64,
        }
    if phase == "publication-bound":
        return {
            "candidate_commit": _CANDIDATE,
            "expected_parent": _PARENT,
            "refspec_sha256": "7" * 64,
            "credential_boundary_sha256": "8" * 64,
            "mode": "controller-push",
        }
    if phase in {"push-observed", "readback-verified"}:
        return {"candidate_commit": _CANDIDATE}
    raise AssertionError(f"unsupported release phase fixture: {phase}")


def _snapshot(phase: str) -> public_release_state.ReleaseStateSnapshot:
    final_index = public_release_state.PHASES.index(phase)
    events = tuple(
        public_release_state.ReleaseEvent(
            schema_version=1,
            operation_id=_OPERATION_ID,
            sequence=index + 1,
            phase=event_phase,
            previous_event_sha256=("0" * 64 if index == 0 else str(index) * 64),
            payload=_phase_payload(event_phase),
            sha256=str(index + 1) * 64,
        )
        for index, event_phase in enumerate(
            public_release_state.PHASES[: final_index + 1]
        )
    )
    return public_release_state.ReleaseStateSnapshot(
        state_directory=_TEST_OPERATION_ROOT / "state",
        operation_id=_OPERATION_ID,
        request_sha256=_REQUEST_SHA256,
        request=_request(),
        controller_sha256=_CONTROLLER_SHA256,
        events=events,
    )


def _adoption_snapshot() -> public_release_state.ReleaseStateSnapshot:
    snapshot = _snapshot("publication-bound")
    publication = snapshot.events[-1]
    payload = dict(publication.payload)
    payload["mode"] = "adopt-observed-candidate"
    payload["credential_boundary_sha256"] = (
        public_release.NO_CREDENTIAL_BOUNDARY_SHA256
    )
    return replace(
        snapshot,
        events=(*snapshot.events[:-1], replace(publication, payload=payload)),
    )


def _git(root: Path, *arguments: str) -> str:
    result = run_bounded(["git", *arguments], cwd=root, check=True)
    return result.stdout.strip()


@unittest.skipUnless(
    os.name == "posix" and Path("/proc/self/fd").is_dir(),
    "public release controller requires qualified Linux procfs",
)
class PublicReleaseControllerTests(unittest.TestCase):
    @unittest.skipUnless(
        Path("/proc/self/fd").is_dir(),
        "descriptor-pinned release commands require Linux procfs",
    )
    def test_documented_isolated_controller_launch_loads_local_modules(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            poison = Path(temporary).resolve()
            marker = poison / "json-imported"
            (poison / "json.py").write_text(
                "from pathlib import Path\n"
                f"Path({str(marker)!r}).write_text('imported', encoding='utf-8')\n",
                encoding="utf-8",
            )
            nonisolated = run_bounded(
                [
                    "/usr/bin/env",
                    f"PYTHONPATH={poison}",
                    sys.executable,
                    "-B",
                    str(REPO_ROOT / "scripts" / "public_release.py"),
                    "--help",
                ],
                cwd=REPO_ROOT,
            )
            self.assertEqual(2, nonisolated.returncode)
            self.assertIn("requires Python -I -S -B", nonisolated.stderr)
            self.assertFalse(marker.exists())

        result = run_bounded(
            [
                sys.executable,
                "-I",
                "-S",
                "-B",
                str(REPO_ROOT / "scripts" / "public_release.py"),
                "--help",
            ],
            cwd=REPO_ROOT,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("prepare", result.stdout)
        self.assertIn("publish", result.stdout)

        delegated = run_bounded(
            [
                sys.executable,
                "-I",
                "-S",
                "-B",
                "-c",
                public_release._ISOLATED_SCRIPT_BOOTSTRAP,
                str(REPO_ROOT / "scripts" / "conformance_check.py"),
                "--help",
            ],
            cwd=REPO_ROOT,
        )
        self.assertEqual(0, delegated.returncode, delegated.stderr)
        self.assertIn("master prompt agreement conformance", delegated.stdout.lower())

    def test_request_validation_uses_a_closed_canonical_schema(self) -> None:
        request = _request()
        self.assertEqual(request, public_release._validate_request(request))
        private_host_path = str(
            Path("/", "Users", "example", "private", "release")
        )
        credential_prefix = bytes((103, 104, 112, 95)).decode("ascii")

        cases: tuple[tuple[str, dict[str, object], str], ...] = (
            (
                "unknown field",
                {**request, "extra": True},
                "closed schema",
            ),
            (
                "missing field",
                {key: value for key, value in request.items() if key != "branch"},
                "closed schema",
            ),
            (
                "boolean schema version",
                {**request, "schema_version": True},
                "schema version",
            ),
            (
                "relative authoring root",
                {**request, "authoring_root": "relative/source"},
                "canonical absolute path",
            ),
            (
                "parent traversal",
                {
                    **request,
                    "authoring_root": str(
                        Path(tempfile.gettempdir()) / "source" / ".." / "private"
                    ),
                },
                "canonical absolute path",
            ),
            (
                "different authoring checkout",
                {
                    **request,
                    "authoring_root": str(
                        Path(tempfile.gettempdir()) / "other-framework"
                    ),
                },
                "controller's exact framework checkout",
            ),
            (
                "timestamp without offset",
                {**request, "commit_timestamp": "2026-07-20T12:00:00"},
                "explicit UTC offset",
            ),
            (
                "multiline public name",
                {**request, "public_name": "Release\nFixture"},
                "single-line text",
            ),
            (
                "SSH transport",
                {
                    **request,
                    "remote_url": "git@github.com:example/framework.git",
                },
                "lowercase HTTPS remote URL",
            ),
            (
                "private host path in commit message",
                {
                    **request,
                    "commit_message": f"Publish from {private_host_path}",
                },
                "metadata failed private-path or credential screening",
            ),
            (
                "credential-shaped value in commit message",
                {
                    **request,
                    "commit_message": (
                        "Publish token "
                        f"{credential_prefix}1234567890abcdefghijklmnop"
                    ),
                },
                "metadata failed private-path or credential screening",
            ),
        )
        for label, candidate, expected in cases:
            with self.subTest(label=label), self.assertRaisesRegex(
                ValueError,
                expected,
            ):
                public_release._validate_request(candidate)

        with tempfile.TemporaryDirectory() as temporary:
            alias = Path(temporary).resolve() / "framework-alias"
            alias.symlink_to(REPO_ROOT, target_is_directory=True)
            with self.assertRaisesRegex(
                ValueError,
                "controller's exact framework checkout",
            ):
                public_release._validate_request(
                    {**request, "authoring_root": str(alias)}
                )

    def test_optional_private_metadata_policy_may_be_absent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            public_root = Path(temp_dir) / "public"
            scripts_root = public_root / "scripts"
            scripts_root.mkdir(parents=True)
            with mock.patch.object(
                public_release,
                "_SCRIPT_DIRECTORY",
                scripts_root,
            ):
                public_release._require_public_metadata_safe(
                    {
                        "public_name": "Release Fixture",
                        "public_email": "release@example.invalid",
                        "commit_message": "Publish verified framework update",
                    }
                )

    def test_export_conformance_requests_duplicate_free_json(self) -> None:
        paths = public_release._release_paths(_TEST_OPERATION_ROOT)
        tools = mock.Mock()
        tools.git.sha256 = "1" * 64
        with (
            mock.patch.object(
                public_release.public_release_check,
                "check_public_release",
                return_value={"errors": [], "warnings": []},
            ),
            mock.patch.object(
                public_release,
                "_run_python",
                return_value=(b'{"errors":[],"warnings":[]}', b""),
            ) as run_python,
            mock.patch.object(
                public_release.public_release_check,
                "stable_file_snapshot",
                return_value=(
                    "2" * 64,
                    public_release.public_release_check.PUBLIC_EXPORT_MARKER_MODE,
                ),
            ),
        ):
            marker_sha256 = public_release._verify_export(paths, tools)

        self.assertEqual("2" * 64, marker_sha256)
        arguments = run_python.call_args.args[2]
        self.assertIn("--format", arguments)
        self.assertEqual("json", arguments[arguments.index("--format") + 1])

    def test_transient_handoff_failure_resumes_from_the_retained_clone(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths = public_release._release_paths(
                Path(temporary).resolve() / "operation"
            )
            paths.clone.mkdir(parents=True)
            snapshot = _snapshot("export-verified")
            staged = _snapshot("staged-verified")
            tools = mock.Mock()
            tools.git.sha256 = "2" * 64
            receipt: dict[str, object] = {"phase": "staged", "errors": []}
            with (
                mock.patch.object(
                    public_release,
                    "_verify_export",
                    return_value="1" * 64,
                ),
                mock.patch.object(
                    public_release.public_handoff_lifecycle,
                    "preflight_existing_clone_inputs",
                ) as existing_preflight,
                mock.patch.object(
                    public_release.public_handoff_lifecycle,
                    "preflight_network_inputs",
                ) as new_preflight,
                mock.patch.object(
                    public_release.public_handoff_lifecycle,
                    "materialize_export",
                ) as materialize,
                mock.patch.object(
                    public_release,
                    "_remote_parent",
                    return_value=_PARENT,
                ),
                mock.patch.object(public_release, "_git") as run_git,
                mock.patch.object(
                    public_release,
                    "_handoff_receipt",
                    side_effect=(
                        ValueError("authoring checkout changed transiently"),
                        receipt,
                    ),
                ) as handoff,
                mock.patch.object(
                    public_release.public_handoff_lifecycle,
                    "validate_receipt",
                ),
                mock.patch.object(
                    public_release.public_release_state,
                    "append_event",
                    return_value=staged,
                ) as append_event,
            ):
                with self.assertRaisesRegex(ValueError, "changed transiently"):
                    public_release._prepare_staged_candidate(
                        paths,
                        snapshot,
                        _request(),
                        tools,
                    )
                result = public_release._prepare_staged_candidate(
                    paths,
                    snapshot,
                    _request(),
                    tools,
                )

            self.assertIs(staged, result)
            self.assertEqual(2, existing_preflight.call_count)
            new_preflight.assert_not_called()
            materialize.assert_not_called()
            self.assertEqual(2, handoff.call_count)
            self.assertEqual(2, run_git.call_count)
            for call in run_git.call_args_list:
                arguments = call.args[2]
                self.assertIn("diff", arguments)
                self.assertNotIn("clone", arguments)
                self.assertNotIn("add", arguments)
            append_event.assert_called_once()

    def test_status_reports_each_phase_and_nominal_next_action(self) -> None:
        expected_actions = {
            "initialized": "resume",
            "export-verified": "resume",
            "staged-verified": "resume",
            "candidate-verified": "publish",
            "publication-bound": "publish-reconcile",
            "push-observed": "readback",
            "readback-verified": "complete",
        }
        for phase, next_action in expected_actions.items():
            with self.subTest(phase=phase):
                report = public_release._status_payload(_snapshot(phase))
                self.assertEqual(phase, report["phase"])
                self.assertEqual(next_action, report["nominal_next_action"])
                self.assertEqual(
                    "complete" if phase == "readback-verified" else "in-progress",
                    report["status"],
                )
                self.assertEqual(
                    public_release_state.PHASES.index(phase) + 1,
                    report["event_count"],
                )
                expected_candidate = (
                    _CANDIDATE
                    if public_release_state.PHASES.index(phase)
                    >= public_release_state.PHASES.index("candidate-verified")
                    else None
                )
                self.assertEqual(expected_candidate, report["candidate_commit"])

    def test_initialized_state_round_trips_through_status_command(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths = public_release._release_paths(
                Path(temporary).resolve() / "operation"
            )
            paths.operation.mkdir(mode=0o700)
            paths.control.mkdir(mode=0o700)
            paths.temporary.mkdir(mode=0o700)
            request = _request()
            state = public_release_state.init_state(
                paths.state,
                operation_id=_OPERATION_ID,
                request=request,
                controller_sha256=public_release._controller_sha256(),
            )

            inspected, retained = public_release._inspect(paths)
            self.assertEqual(state.request_sha256, inspected.request_sha256)
            self.assertEqual(request, retained)

            with mock.patch.object(
                public_release,
                "_require_public_metadata_safe",
                side_effect=ValueError("changed private policy"),
            ) as rescreen:
                repeated, repeated_request = public_release._inspect(paths)
            self.assertEqual(inspected, repeated)
            self.assertEqual(retained, repeated_request)
            rescreen.assert_not_called()

            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = public_release.main(
                    ["status", "--release-root", str(paths.operation)]
                )
            self.assertEqual(0, exit_code)
            self.assertIn('"phase": "initialized"', output.getvalue())

    def test_controller_bundle_digest_rejects_concurrent_member_change(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            scripts = Path(temporary).resolve() / "scripts"
            scripts.mkdir()
            target = scripts / "a.py"
            target.write_text("VALUE = 1\n", encoding="utf-8")
            (scripts / "public_release.py").write_text(
                "ENTRYPOINT = True\n",
                encoding="utf-8",
            )
            original = public_release._descriptor_sha256
            changed = False

            def mutate_after_hash(descriptor: int) -> str:
                nonlocal changed
                digest = original(descriptor)
                linked = Path(f"/proc/self/fd/{descriptor}").resolve()
                if linked == target and not changed:
                    changed = True
                    target.write_text("VALUE = 2\n", encoding="utf-8")
                return digest

            with (
                mock.patch.object(public_release, "_SCRIPT_DIRECTORY", scripts),
                mock.patch.object(
                    public_release,
                    "_descriptor_sha256",
                    side_effect=mutate_after_hash,
                ),
                self.assertRaisesRegex(ValueError, "changed while hashed"),
            ):
                public_release._controller_sha256()

    def test_operation_root_install_fsyncs_child_then_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary).resolve()
            paths = public_release._release_paths(parent / "operation")
            parent_identity = (parent.stat().st_dev, parent.stat().st_ino)
            observed: list[tuple[int, int]] = []
            real_fsync = os.fsync

            def record_fsync(descriptor: int) -> None:
                metadata = os.fstat(descriptor)
                observed.append((metadata.st_dev, metadata.st_ino))
                real_fsync(descriptor)

            with mock.patch.object(
                public_release.os,
                "fsync",
                side_effect=record_fsync,
            ):
                public_release._initialize_operation(paths)

            operation_identity = (
                paths.operation.stat().st_dev,
                paths.operation.stat().st_ino,
            )
            self.assertIn(operation_identity, observed)
            self.assertIn(parent_identity, observed)
            self.assertLess(
                observed.index(operation_identity),
                observed.index(parent_identity),
            )

    def test_executable_and_github_config_paths_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            executable = root / "tool"
            executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            executable.chmod(0o700)

            retained = public_release._open_executable(
                executable,
                description="fixture tool",
            )
            self.assertEqual(executable, retained.path)
            self.assertEqual(64, len(retained.sha256))
            retained.close()

            executable.chmod(0o722)
            with self.assertRaisesRegex(ValueError, "group/world write"):
                public_release._open_executable(
                    executable,
                    description="fixture tool",
                )
            executable.chmod(0o700)

            symlink = root / "tool-link"
            symlink.symlink_to(executable)
            with self.assertRaisesRegex(ValueError, "resolved path"):
                public_release._open_executable(
                    symlink,
                    description="fixture tool",
                )

            config = root / "gh-config"
            config.mkdir(mode=0o700)
            hosts = config / "hosts.yml"
            hosts.write_text("github.com: {}\n", encoding="utf-8")
            hosts.chmod(0o600)
            self.assertEqual(config, public_release._validate_github_config(config))

            hosts.chmod(0o644)
            with self.assertRaisesRegex(ValueError, "owner-only regular file"):
                public_release._validate_github_config(config)

    @unittest.skipUnless(
        Path("/proc/self/fd").is_dir(),
        "descriptor-pinned credential helper requires Linux procfs",
    )
    def test_git_credential_helper_forwards_the_protocol_operation(self) -> None:
        git = _required_executable("git")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            helper_path = root / "credential-helper"
            helper_path.write_text(
                "#!/bin/sh\n"
                "test \"$1\" = auth || exit 41\n"
                "test \"$2\" = git-credential || exit 42\n"
                "test \"$3\" = get || exit 43\n"
                "printf 'username=fixture\\npassword=fixture\\n'\n",
                encoding="utf-8",
            )
            helper_path.chmod(0o700)
            descriptor = os.open(helper_path, os.O_RDONLY)
            try:
                helper = public_release._github_credential_helper(descriptor)
                result = public_release.bounded_subprocess.run_bounded_process(
                    [
                        "/bin/sh",
                        "-c",
                        (
                            "printf 'protocol=https\\nhost=example.invalid\\n\\n' | "
                            '"$1" -c credential.helper= '
                            '-c "credential.helper=$2" credential fill'
                        ),
                        "credential-helper-test",
                        str(git),
                        helper,
                    ],
                    cwd=root,
                    env={"LC_ALL": "C", "PATH": "/usr/sbin:/usr/bin:/bin"},
                    pass_fds=(descriptor,),
                    timeout_seconds=10.0,
                    max_output_bytes=1024 * 1024,
                    maximum_timeout_seconds=10.0,
                    maximum_output_bytes=1024 * 1024,
                    termination_grace_seconds=0.25,
                )
            finally:
                os.close(descriptor)
            self.assertEqual(0, result.returncode, result.stderr.decode())
            self.assertIn(b"username=fixture", result.stdout)
            self.assertIn(b"password=fixture", result.stdout)

    def test_open_executable_detects_content_change_before_close(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary).resolve() / "tool"
            executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            executable.chmod(0o700)
            retained = public_release._open_executable(
                executable,
                description="fixture tool",
            )
            executable.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "content changed"):
                retained.close()

    def test_running_python_must_equal_the_retained_executable_inode(self) -> None:
        running = Path("/proc/self/exe").resolve(strict=True)
        retained = public_release._open_executable(
            running,
            description="running Python fixture",
        )
        try:
            public_release._require_running_python(retained)
        finally:
            retained.close()

        with tempfile.TemporaryDirectory() as temporary:
            replacement = Path(temporary).resolve() / "python-replacement"
            shutil.copyfile(running, replacement)
            replacement.chmod(0o700)
            different = public_release._open_executable(
                replacement,
                description="replacement Python fixture",
            )
            try:
                with self.assertRaisesRegex(ValueError, "running Python image"):
                    public_release._require_running_python(different)
            finally:
                different.close()

    def test_publish_rejects_candidate_approval_mismatch_before_remote_use(self) -> None:
        paths = public_release._release_paths(_TEST_OPERATION_ROOT)
        snapshot = _snapshot("candidate-verified")
        with (
            mock.patch.object(
                public_release,
                "_revalidate_candidate",
                return_value=(_CANDIDATE, _PARENT),
            ),
            mock.patch.object(public_release, "_remote_parent") as remote_parent,
        ):
            with self.assertRaisesRegex(ValueError, "approved candidate"):
                public_release._publish(
                    paths,
                    snapshot,
                    _request(),
                    mock.sentinel.tools,
                    approved_candidate=_THIRD,
                    github_cli_path=None,
                    github_config_directory=None,
                )
        remote_parent.assert_not_called()

    def test_publish_when_remote_is_candidate_performs_readback_without_push(self) -> None:
        paths = public_release._release_paths(_TEST_OPERATION_ROOT)
        snapshot = _snapshot("candidate-verified")
        completed = _snapshot("readback-verified")
        with (
            mock.patch.object(
                public_release,
                "_revalidate_candidate",
                return_value=(_CANDIDATE, _PARENT),
            ),
            mock.patch.object(
                public_release,
                "_remote_parent",
                return_value=_CANDIDATE,
            ),
            mock.patch.object(
                public_release,
                "_append_reconciliation_binding",
                return_value=_snapshot("publication-bound"),
            ) as append_binding,
            mock.patch.object(
                public_release,
                "_append_push_observed",
                return_value=_snapshot("push-observed"),
            ) as append_observed,
            mock.patch.object(
                public_release,
                "_complete_readback",
                return_value=completed,
            ) as complete_readback,
            mock.patch.object(public_release, "_git") as run_git,
            mock.patch.object(public_release, "_open_executable") as open_helper,
        ):
            result = public_release._publish(
                paths,
                snapshot,
                _request(),
                mock.sentinel.tools,
                approved_candidate=_CANDIDATE,
                github_cli_path=None,
                github_config_directory=None,
            )

        self.assertIs(completed, result)
        append_binding.assert_called_once_with(
            paths,
            snapshot,
            _request(),
            _CANDIDATE,
            _PARENT,
        )
        append_observed.assert_called_once_with(
            paths,
            _snapshot("publication-bound"),
            _CANDIDATE,
        )
        complete_readback.assert_called_once()
        run_git.assert_not_called()
        open_helper.assert_not_called()

    def test_remote_candidate_reconciliation_records_the_complete_phase_chain(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths = public_release._release_paths(
                Path(temporary).resolve() / "operation"
            )
            paths.operation.mkdir(mode=0o700)
            paths.control.mkdir(mode=0o700)
            paths.temporary.mkdir(mode=0o700)
            request = _request()
            snapshot = public_release_state.init_state(
                paths.state,
                operation_id=_OPERATION_ID,
                request=request,
                controller_sha256=public_release._controller_sha256(),
            )
            snapshot = public_release_state.append_event(
                paths.state,
                operation_id=snapshot.operation_id,
                request_sha256=snapshot.request_sha256,
                phase="export-verified",
                payload={
                    "export_marker_sha256": "1" * 64,
                    "git_sha256": "2" * 64,
                    "python_sha256": "3" * 64,
                    "uv_sha256": "4" * 64,
                },
            )
            staged_receipt: dict[str, object] = {"phase": "staged"}
            snapshot = public_release_state.append_event(
                paths.state,
                operation_id=snapshot.operation_id,
                request_sha256=snapshot.request_sha256,
                phase="staged-verified",
                payload={
                    "expected_parent": _PARENT,
                    "staged_receipt": staged_receipt,
                    "commit_spec_sha256": public_release_state.canonical_json_sha256(
                        public_release._commit_spec(request)
                    ),
                },
            )
            snapshot = public_release_state.append_event(
                paths.state,
                operation_id=snapshot.operation_id,
                request_sha256=snapshot.request_sha256,
                phase="candidate-verified",
                payload={
                    "candidate_commit": _CANDIDATE,
                    "committed_receipt": {"phase": "committed"},
                    "staged_receipt_sha256": (
                        public_release_state.canonical_json_sha256(staged_receipt)
                    ),
                },
            )

            with (
                mock.patch.object(
                    public_release,
                    "_revalidate_candidate",
                    return_value=(_CANDIDATE, _PARENT),
                ),
                mock.patch.object(
                    public_release,
                    "_remote_parent",
                    side_effect=(_CANDIDATE, _CANDIDATE),
                ),
                mock.patch.object(public_release, "_git") as run_git,
                mock.patch.object(public_release, "_open_executable") as open_helper,
            ):
                completed = public_release._publish(
                    paths,
                    snapshot,
                    request,
                    mock.sentinel.tools,
                    approved_candidate=_CANDIDATE,
                    github_cli_path=None,
                    github_config_directory=None,
                )

            self.assertEqual("readback-verified", completed.phase)
            self.assertEqual(
                (
                    "initialized",
                    "export-verified",
                    "staged-verified",
                    "candidate-verified",
                    "publication-bound",
                    "push-observed",
                    "readback-verified",
                ),
                tuple(event.phase for event in completed.events),
            )
            publication = completed.events[4]
            self.assertEqual(
                public_release.NO_CREDENTIAL_BOUNDARY_SHA256,
                publication.payload["credential_boundary_sha256"],
            )
            run_git.assert_not_called()
            open_helper.assert_not_called()

    def test_publish_when_remote_is_parent_requires_credential_boundary(self) -> None:
        paths = public_release._release_paths(_TEST_OPERATION_ROOT)
        snapshot = _snapshot("candidate-verified")
        with (
            mock.patch.object(
                public_release,
                "_revalidate_candidate",
                return_value=(_CANDIDATE, _PARENT),
            ),
            mock.patch.object(
                public_release,
                "_remote_parent",
                return_value=_PARENT,
            ),
            mock.patch.object(public_release, "_git") as run_git,
        ):
            with self.assertRaisesRegex(ValueError, "credential boundary"):
                public_release._publish(
                    paths,
                    snapshot,
                    _request(),
                    mock.sentinel.tools,
                    approved_candidate=_CANDIDATE,
                    github_cli_path=None,
                    github_config_directory=None,
                )
        run_git.assert_not_called()

    def test_publish_from_parent_records_binding_before_one_cas_push(self) -> None:
        paths = public_release._release_paths(_TEST_OPERATION_ROOT)
        snapshot = _snapshot("candidate-verified")
        completed = _snapshot("readback-verified")
        helper = mock.Mock()
        helper.descriptor = 91
        helper.sha256 = "9" * 64
        helper.pass_fds = (91,)
        appended: list[dict[str, object]] = []

        def append_event(
            _state: Path,
            **arguments: object,
        ) -> public_release_state.ReleaseStateSnapshot:
            appended.append(arguments)
            return snapshot

        with (
            mock.patch.object(
                public_release,
                "_revalidate_candidate",
                return_value=(_CANDIDATE, _PARENT),
            ),
            mock.patch.object(
                public_release,
                "_remote_parent",
                side_effect=(_PARENT, _CANDIDATE),
            ),
            mock.patch.object(
                public_release,
                "_validate_github_config",
                return_value=_TEST_GITHUB_CONFIG,
            ),
            mock.patch.object(
                public_release,
                "_open_executable",
                return_value=helper,
            ),
            mock.patch.object(
                public_release.public_release_state,
                "append_event",
                side_effect=append_event,
            ),
            mock.patch.object(public_release, "_git", return_value="") as run_git,
            mock.patch.object(
                public_release,
                "_append_push_observed",
                return_value=_snapshot("push-observed"),
            ),
            mock.patch.object(
                public_release,
                "_complete_readback",
                return_value=completed,
            ),
        ):
            result = public_release._publish(
                paths,
                snapshot,
                _request(),
                mock.sentinel.tools,
                approved_candidate=_CANDIDATE,
                github_cli_path=Path("/usr/bin/gh"),
                github_config_directory=_TEST_GITHUB_CONFIG,
            )

        self.assertIs(completed, result)
        self.assertEqual(1, len(appended))
        self.assertEqual("publication-bound", appended[0]["phase"])
        self.assertEqual(
            {
                "candidate_commit": _CANDIDATE,
                "expected_parent": _PARENT,
                "refspec_sha256": hashlib.sha256(
                    f"{_CANDIDATE}:refs/heads/master".encode("utf-8")
                ).hexdigest(),
                "credential_boundary_sha256": helper.sha256,
                "mode": "controller-push",
            },
            appended[0]["payload"],
        )
        run_git.assert_called_once()
        push_arguments = run_git.call_args.args[2]
        self.assertIn(
            f"--force-with-lease=refs/heads/master:{_PARENT}",
            push_arguments,
        )
        self.assertIn(f"{_CANDIDATE}:refs/heads/master", push_arguments)
        helper.close.assert_called_once_with()

    def test_existing_controller_push_binding_requires_exact_retry_approval(self) -> None:
        paths = public_release._release_paths(_TEST_OPERATION_ROOT)
        snapshot = _snapshot("publication-bound")
        with (
            mock.patch.object(
                public_release,
                "_revalidate_candidate",
                return_value=(_CANDIDATE, _PARENT),
            ),
            mock.patch.object(
                public_release,
                "_remote_parent",
                return_value=_PARENT,
            ),
            mock.patch.object(public_release, "_git") as run_git,
            mock.patch.object(public_release, "_open_executable") as open_helper,
        ):
            with self.assertRaisesRegex(ValueError, "exact approval"):
                public_release._publish(
                    paths,
                    snapshot,
                    _request(),
                    mock.sentinel.tools,
                    approved_candidate=_CANDIDATE,
                    github_cli_path=Path("/usr/bin/gh"),
                    github_config_directory=_TEST_GITHUB_CONFIG,
                )
        run_git.assert_not_called()
        open_helper.assert_not_called()

        helper = mock.Mock()
        helper.descriptor = 92
        helper.sha256 = "8" * 64
        helper.pass_fds = (92,)
        publication = snapshot.events[-1]
        snapshot = replace(
            snapshot,
            events=(
                *snapshot.events[:-1],
                replace(
                    publication,
                    payload={
                        "candidate_commit": _CANDIDATE,
                        "expected_parent": _PARENT,
                        "refspec_sha256": hashlib.sha256(
                            f"{_CANDIDATE}:refs/heads/master".encode("utf-8")
                        ).hexdigest(),
                        "credential_boundary_sha256": helper.sha256,
                        "mode": "controller-push",
                    },
                ),
            ),
        )
        completed = _snapshot("readback-verified")
        with (
            mock.patch.object(
                public_release,
                "_revalidate_candidate",
                return_value=(_CANDIDATE, _PARENT),
            ),
            mock.patch.object(
                public_release,
                "_remote_parent",
                side_effect=(_PARENT, _CANDIDATE),
            ),
            mock.patch.object(
                public_release,
                "_validate_github_config",
                return_value=_TEST_GITHUB_CONFIG,
            ),
            mock.patch.object(
                public_release,
                "_open_executable",
                return_value=helper,
            ),
            mock.patch.object(
                public_release.public_release_state,
                "append_event",
            ) as append_event,
            mock.patch.object(public_release, "_git", return_value="") as run_git,
            mock.patch.object(
                public_release,
                "_append_push_observed",
                return_value=_snapshot("push-observed"),
            ),
            mock.patch.object(
                public_release,
                "_complete_readback",
                return_value=completed,
            ),
        ):
            result = public_release._publish(
                paths,
                snapshot,
                _request(),
                mock.sentinel.tools,
                approved_candidate=_CANDIDATE,
                github_cli_path=Path("/usr/bin/gh"),
                github_config_directory=_TEST_GITHUB_CONFIG,
                approved_retry_event=snapshot.events[-1].sha256,
            )

        self.assertIs(completed, result)
        append_event.assert_not_called()
        run_git.assert_called_once()
        helper.close.assert_called_once_with()

    def test_readback_rejects_parent_after_push_was_observed(self) -> None:
        paths = public_release._release_paths(_TEST_OPERATION_ROOT)
        for phase in ("push-observed", "readback-verified"):
            with self.subTest(phase=phase):
                snapshot = _snapshot(phase)
                with (
                    mock.patch.object(
                        public_release,
                        "_inspect",
                        return_value=(snapshot, _request()),
                    ),
                    mock.patch.object(
                        public_release.public_release_state,
                        "operation_lease",
                        return_value=nullcontext(),
                    ),
                    mock.patch.object(public_release, "_require_controller_generation"),
                    mock.patch.object(public_release, "_open_tools") as open_tools,
                    mock.patch.object(
                        public_release,
                        "_revalidate_candidate",
                        return_value=(_CANDIDATE, _PARENT),
                    ),
                    mock.patch.object(
                        public_release,
                        "_remote_parent",
                        return_value=_PARENT,
                    ),
                ):
                    open_tools.return_value.close.return_value = None
                    with self.assertRaisesRegex(
                        ValueError,
                        "after the candidate was observed",
                    ):
                        public_release._readback_command(
                            argparse.Namespace(release_root=paths.operation)
                        )

        adoption = _adoption_snapshot()
        with (
            mock.patch.object(
                public_release,
                "_revalidate_candidate",
                return_value=(_CANDIDATE, _PARENT),
            ),
            mock.patch.object(
                public_release,
                "_remote_parent",
                return_value=_PARENT,
            ),
            mock.patch.object(public_release, "_git") as run_git,
            mock.patch.object(public_release, "_open_executable") as open_helper,
        ):
            with self.assertRaisesRegex(ValueError, "candidate was observed"):
                public_release._publish(
                    paths,
                    adoption,
                    _request(),
                    mock.sentinel.tools,
                    approved_candidate=_CANDIDATE,
                    github_cli_path=Path("/usr/bin/gh"),
                    github_config_directory=_TEST_GITHUB_CONFIG,
                )
        run_git.assert_not_called()
        open_helper.assert_not_called()

    def test_publish_blocks_when_remote_is_a_third_object(self) -> None:
        paths = public_release._release_paths(_TEST_OPERATION_ROOT)
        snapshot = _snapshot("candidate-verified")
        with (
            mock.patch.object(
                public_release,
                "_revalidate_candidate",
                return_value=(_CANDIDATE, _PARENT),
            ),
            mock.patch.object(
                public_release,
                "_remote_parent",
                return_value=_THIRD,
            ),
            mock.patch.object(public_release, "_git") as run_git,
            mock.patch.object(public_release, "_open_executable") as open_helper,
        ):
            with self.assertRaisesRegex(ValueError, "remote conflict"):
                public_release._publish(
                    paths,
                    snapshot,
                    _request(),
                    mock.sentinel.tools,
                    approved_candidate=_CANDIDATE,
                    github_cli_path=Path("/usr/bin/gh"),
                    github_config_directory=_TEST_GITHUB_CONFIG,
                )
        run_git.assert_not_called()
        open_helper.assert_not_called()

    @unittest.skipUnless(
        Path("/proc/self/fd").is_dir(),
        "descriptor-pinned release commands require Linux procfs",
    )
    def test_real_git_candidate_checkpoint_resumes_without_second_commit(self) -> None:
        git_executable = _required_executable("git")
        git_sha256 = hashlib.sha256(git_executable.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            remote = root / "public.git"
            seed = root / "seed"
            operation = root / "operation"
            paths = public_release._release_paths(operation)
            for directory in (
                operation,
                paths.control,
                paths.temporary,
                paths.export,
            ):
                directory.mkdir(mode=0o700)

            _git(root, "init", "--bare", "-q", str(remote))
            seed.mkdir()
            _git(seed, "init", "-q")
            (seed / "README.md").write_text("public baseline\n", encoding="utf-8")
            _git(seed, "add", "README.md")
            _git(
                seed,
                "-c",
                "user.name=Baseline Fixture",
                "-c",
                "user.email=baseline@example.invalid",
                "commit",
                "-qm",
                "Public baseline",
            )
            _git(seed, "branch", "-M", "master")
            _git(seed, "remote", "add", "origin", str(remote))
            _git(seed, "push", "-q", "origin", "master")
            _git(remote, "symbolic-ref", "HEAD", "refs/heads/master")
            _git(root, "clone", "-q", "--no-local", str(remote), str(paths.clone))

            parent = _git(paths.clone, "rev-parse", "HEAD")
            (paths.clone / "README.md").write_text(
                "public candidate\n",
                encoding="utf-8",
            )
            _git(paths.clone, "add", "README.md")

            request = _request(root / "authoring")
            request["git_executable"] = str(git_executable)
            state = public_release_state.init_state(
                paths.state,
                operation_id=_OPERATION_ID,
                request=request,
                controller_sha256=_CONTROLLER_SHA256,
            )
            state = public_release_state.append_event(
                paths.state,
                operation_id=state.operation_id,
                request_sha256=state.request_sha256,
                phase="export-verified",
                payload={
                    "export_marker_sha256": "1" * 64,
                    "git_sha256": git_sha256,
                    "python_sha256": "3" * 64,
                    "uv_sha256": "4" * 64,
                },
            )
            staged_receipt: dict[str, object] = {
                "phase": "staged",
                "fixture": "verified",
            }
            state = public_release_state.append_event(
                paths.state,
                operation_id=state.operation_id,
                request_sha256=state.request_sha256,
                phase="staged-verified",
                payload={
                    "expected_parent": parent,
                    "staged_receipt": staged_receipt,
                    "commit_spec_sha256": public_release_state.canonical_json_sha256(
                        public_release._commit_spec(request)
                    ),
                },
            )

            retained_git = public_release._open_executable(
                git_executable,
                description="Git fixture",
            )
            tools = SimpleNamespace(
                git=retained_git,
                python=SimpleNamespace(sha256="3" * 64),
                uv=SimpleNamespace(sha256="4" * 64),
            )
            committed_receipt: dict[str, object] = {
                "phase": "committed",
                "fixture": "verified",
            }

            def receipt(
                *,
                phase: object,
                **_arguments: object,
            ) -> dict[str, object]:
                if str(getattr(phase, "value", phase)) == "staged":
                    return staged_receipt
                return committed_receipt

            def candidate_from_head(**_arguments: object) -> str:
                return _git(paths.clone, "rev-parse", "HEAD")

            try:
                try:
                    with (
                        mock.patch.object(
                            public_release,
                            "_handoff_receipt",
                            side_effect=receipt,
                        ),
                        mock.patch.object(
                            public_release.public_handoff_lifecycle,
                            "validate_receipt",
                            side_effect=candidate_from_head,
                        ),
                    ):
                        state = public_release._commit_candidate(
                            paths,
                            state,
                            request,
                            tools,  # type: ignore[arg-type]
                        )
                except ValueError as exc:
                    metadata = _git(
                        paths.clone,
                        "show",
                        "--no-patch",
                        "--format=%H%n%P%n%an%n%ae%n%aI%n%cn%n%ce%n%cI%n%B",
                        "HEAD",
                    )
                    self.fail(f"candidate metadata validation failed: {exc}; {metadata!r}")
                candidate = _git(paths.clone, "rev-parse", "HEAD")
                self.assertNotEqual(parent, candidate)
                self.assertEqual("candidate-verified", state.phase)
                self.assertEqual(
                    candidate,
                    state.events[-1].payload["candidate_commit"],
                )

                resumed = public_release_state.inspect_state(
                    paths.state,
                    operation_id=state.operation_id,
                    request_sha256=state.request_sha256,
                )
                with (
                    mock.patch.object(
                        public_release,
                        "_commit_candidate",
                        side_effect=AssertionError("candidate must not be recommitted"),
                    ) as recommit,
                    mock.patch.object(
                        public_release,
                        "_revalidate_candidate",
                        return_value=(candidate, parent),
                    ) as revalidate,
                ):
                    result = public_release._advance_to_candidate(
                        paths,
                        resumed,
                        request,
                        tools,  # type: ignore[arg-type]
                    )
                self.assertEqual(candidate, _git(paths.clone, "rev-parse", "HEAD"))
                self.assertEqual(resumed.events, result.events)
                recommit.assert_not_called()
                revalidate.assert_called_once()
            finally:
                retained_git.close()


if __name__ == "__main__":
    unittest.main()
