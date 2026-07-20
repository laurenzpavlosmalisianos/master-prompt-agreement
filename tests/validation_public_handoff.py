"""Exact sanitized-export to public-Git handoff validation tests."""

from __future__ import annotations

import ast
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shlex
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
from typing import cast
import unittest
from unittest import mock

from tests.validation_test_support import REPO_ROOT, run_bounded

import bounded_subprocess  # noqa: E402
import public_handoff_check  # noqa: E402
import public_handoff_lifecycle  # noqa: E402
import public_release_check  # noqa: E402
import public_surface  # noqa: E402
import resource_cleanup  # noqa: E402
import safe_paths  # noqa: E402


def _required_executable(name: str) -> str:
    executable = shutil.which(name)
    if executable is None:
        raise RuntimeError(f"public handoff tests require the {name} executable")
    return executable


_ENV_EXECUTABLE = _required_executable("env")
_GIT_EXECUTABLE = str(Path(_required_executable("git")).resolve(strict=True))
_VERIFIER_SOURCE_MODULES = (
    ("public_handoff_check", "scripts/public_handoff_check.py", public_handoff_check),
    ("public_release_check", "scripts/public_release_check.py", public_release_check),
    ("public_surface", "scripts/public_surface.py", public_surface),
    ("resource_cleanup", "scripts/resource_cleanup.py", resource_cleanup),
    ("safe_paths", "scripts/safe_paths.py", safe_paths),
    ("bounded_subprocess", "scripts/bounded_subprocess.py", bounded_subprocess),
)


def _static_local_imports(
    source: Path,
    *,
    available_modules: frozenset[str],
) -> frozenset[str]:
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    imports: set[str] = set()

    def record(module_name: str) -> None:
        parts = module_name.split(".")
        if parts[0] in available_modules:
            imports.add(parts[0])
        elif (
            len(parts) > 1
            and parts[0] == "scripts"
            and parts[1] in available_modules
        ):
            imports.add(parts[1])

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                record(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                raise AssertionError(f"verifier source uses relative import: {source}")
            if node.module == "scripts":
                for alias in node.names:
                    if alias.name in available_modules:
                        imports.add(alias.name)
            elif node.module is not None:
                record(node.module)
    return frozenset(imports)


def _git(root: Path, *arguments: str) -> str:
    result = run_bounded(["git", *arguments], cwd=root, check=True)
    return result.stdout.strip()


def _release_git(
    root: Path,
    *arguments: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run the documented prefix-wide sanitized Git boundary."""

    return run_bounded(
        [
            _ENV_EXECUTABLE,
            "-i",
            "GIT_ATTR_NOSYSTEM=1",
            f"GIT_CEILING_DIRECTORIES={root.parent}",
            f"GIT_CONFIG_GLOBAL={os.devnull}",
            "GIT_CONFIG_NOSYSTEM=1",
            "GIT_NO_LAZY_FETCH=1",
            "GIT_NO_REPLACE_OBJECTS=1",
            "GIT_OPTIONAL_LOCKS=0",
            _GIT_EXECUTABLE,
            "-c",
            "core.fsmonitor=false",
            "-c",
            "hook.post-index-change.enabled=false",
            *arguments,
        ],
        cwd=root,
        check=check,
    )


def _release_ls_remote(
    root: Path,
    *,
    url: str,
    branch: str,
) -> subprocess.CompletedProcess[str]:
    return _release_git(
        root,
        "-c",
        "credential.helper=",
        "ls-remote",
        "--upload-pack=git-upload-pack",
        "--refs",
        "--exit-code",
        "--",
        url,
        f"refs/heads/{branch}",
    )


def _release_clone(
    root: Path,
    *,
    url: str,
    destination: Path,
    remote_name: str,
    branch: str,
) -> subprocess.CompletedProcess[str]:
    return _release_git(
        root,
        "-c",
        "credential.helper=",
        "-c",
        "init.templateDir=",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "hook.post-checkout.enabled=false",
        "-c",
        "hook.reference-transaction.enabled=false",
        "clone",
        "--upload-pack=git-upload-pack",
        "--no-local",
        "--no-tags",
        "--no-recurse-submodules",
        "--single-branch",
        "--branch",
        branch,
        "--origin",
        remote_name,
        "--",
        url,
        str(destination),
    )


def _object_file_identities(root: Path) -> set[tuple[int, int]]:
    return {
        (metadata.st_dev, metadata.st_ino)
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
        for metadata in (path.stat(),)
    }


def _expected_remote_target_sha256(
    *,
    remote_name: str,
    fetch_url: str,
    push_url: str,
    object_format: str,
) -> str:
    """Independently encode the documented schema-4 remote-target binding."""

    digest = hashlib.sha256(b"mpa-public-handoff-remote-target-v1\0")
    for label, value in (
        ("remote-name", remote_name),
        ("fetch-url", fetch_url),
        ("push-url", push_url),
        ("object-format", object_format),
    ):
        encoded = value.encode("utf-8")
        digest.update(label.encode("ascii"))
        digest.update(b"\0")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()


def _refresh_export_marker(root: Path) -> None:
    inventory = public_release_check._inventory_release_tree(root)
    records = {
        relative: public_release_check.stable_file_snapshot(
            root / relative,
            _expected=metadata,
        )
        for relative, metadata in inventory.files.items()
        if relative != public_surface.PUBLIC_EXPORT_OWNERSHIP_MARKER
    }
    marker = root / public_surface.PUBLIC_EXPORT_OWNERSHIP_MARKER
    marker.write_bytes(public_release_check.public_export_marker_bytes(records))
    marker.chmod(public_release_check.PUBLIC_EXPORT_MARKER_MODE)


def _write_export(root: Path) -> None:
    root.mkdir(mode=0o700)
    root.chmod(public_release_check.PUBLIC_EXPORT_ROOT_MODE)
    for relative in sorted(public_release_check.PUBLIC_EXPORT_SENTINEL_FILES):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# Export payload: {relative}\n", encoding="utf-8")
    (root / ".gitignore").write_text(
        public_surface.PUBLIC_EXPORT_GITIGNORE_TEXT,
        encoding="utf-8",
    )
    (root / "scripts" / "public_export.py").chmod(0o755)
    for _module_name, relative, _module in _VERIFIER_SOURCE_MODULES:
        source = REPO_ROOT / relative
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        target.chmod(stat.S_IMODE(source.stat().st_mode))
    for directory in sorted(
        (path for path in root.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
    ):
        directory.chmod(public_release_check.PUBLIC_EXPORT_DIRECTORY_MODE)
    _refresh_export_marker(root)
    with safe_paths.open_output_directory(root, create_missing=False) as binding:
        public_release_check.checked_public_export_ownership_descriptor(
            binding.descriptor
        )


def _verifier_origin_context(
    export_root: Path,
    overrides: dict[str, Path] | None = None,
) -> ExitStack:
    selected = {} if overrides is None else overrides
    stack = ExitStack()
    try:
        for module_name, relative, module in _VERIFIER_SOURCE_MODULES:
            origin = selected.get(module_name, export_root / relative)
            if module_name == "public_handoff_check":
                stack.enter_context(
                    mock.patch.object(module, "__file__", str(origin))
                )
                continue
            spec = module.__spec__
            if spec is None:
                raise RuntimeError(f"test module has no import spec: {module_name}")
            stack.enter_context(mock.patch.object(spec, "origin", str(origin)))
        return stack
    except BaseException:
        stack.close()
        raise


def _copy_export_payload(export_root: Path, public_root: Path) -> None:
    for entry in tuple(public_root.iterdir()):
        if entry.name == ".git":
            continue
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry)
        else:
            entry.unlink()
    for source in sorted(path for path in export_root.rglob("*") if path.is_file()):
        relative = source.relative_to(export_root)
        if relative.as_posix() == public_surface.PUBLIC_EXPORT_OWNERSHIP_MARKER:
            continue
        target = public_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        target.chmod(stat.S_IMODE(source.stat().st_mode))
    _release_git(
        public_root,
        "-c",
        "core.attributesFile=/dev/null",
        "-c",
        "core.hooksPath=/dev/null",
        "--no-optional-locks",
        "-C",
        str(public_root),
        "add",
        "--all",
        "--",
    )


def _commit_tree(
    root: Path,
    tree: str,
    *,
    message: str,
    parents: tuple[str, ...] = (),
) -> str:
    arguments = [
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit-tree",
        tree,
    ]
    for parent in parents:
        arguments.extend(("-p", parent))
    arguments.extend(("-m", message))
    return _git(root, *arguments)


def _remove_loose_blob(root: Path, relative: str) -> str:
    oid = _git(root, "hash-object", relative)
    object_path = root / ".git" / "objects" / oid[:2] / oid[2:]
    if not object_path.is_file():
        raise AssertionError("fixture candidate blob is not stored as a loose object")
    object_path.unlink()
    return oid


class _HandoffFixture:
    def __init__(self, root: Path, *, object_format: str) -> None:
        self.root = root
        self.export = root / "export"
        self.remote = root / "public-remote.git"
        self.public = root / "public-clone"
        self.authoring = root / "authoring"
        self.temporary = root / "handoff-temporary"
        self.temporary.mkdir()
        seed = root / "seed"
        _write_export(self.export)

        init_format = [f"--object-format={object_format}"]
        _git(root, "init", "--bare", "-q", *init_format, str(self.remote))
        seed.mkdir()
        _git(seed, "init", "-q", *init_format)
        (seed / "old-public.txt").write_text("old public state\n", encoding="utf-8")
        _git(seed, "add", "old-public.txt")
        _git(
            seed,
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "public baseline",
        )
        _git(seed, "branch", "-M", "main")
        _git(seed, "remote", "add", "origin", str(self.remote))
        _git(seed, "push", "-q", "-u", "origin", "main")
        _git(self.remote, "symbolic-ref", "HEAD", "refs/heads/main")
        _git(root, "clone", "--no-local", "-q", str(self.remote), str(self.public))
        self.transport_url = str(self.remote)
        self.remote_url = "https://public.example.invalid/framework.git"
        _git(self.public, "remote", "set-url", "origin", self.remote_url)

        self.authoring.mkdir()
        _git(self.authoring, "init", "-q")
        (self.authoring / "authoring.txt").write_text(
            "private authoring history\n",
            encoding="utf-8",
        )
        _git(self.authoring, "add", "authoring.txt")
        _git(
            self.authoring,
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "authoring baseline",
        )

        _copy_export_payload(self.export, self.public)
        self.expected_parent = _git(self.public, "rev-parse", "HEAD")

    def check(
        self,
        phase: public_handoff_check.HandoffPhase,
        *,
        verifier_origins: dict[str, Path] | None = None,
        **overrides: object,
    ) -> dict[str, object]:
        arguments: dict[str, object] = {
            "phase": phase,
            "export_root": self.export,
            "public_clone_root": self.public,
            "authoring_root": self.authoring,
            "git_executable": Path(_GIT_EXECUTABLE),
            "temporary_root": self.temporary,
            "remote_name": "origin",
            "branch": "main",
            "expected_fetch_url": self.remote_url,
            "expected_push_url": self.remote_url,
            "expected_parent_commit": self.expected_parent,
        }
        arguments.update(overrides)
        with _verifier_origin_context(self.export, verifier_origins):
            return public_handoff_check.check_public_handoff(**arguments)  # type: ignore[arg-type]

    def commit_candidate(self) -> str:
        _release_git(
            self.public,
            "-c",
            "core.attributesFile=/dev/null",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "hook.commit-msg.enabled=false",
            "-c",
            "hook.post-commit.enabled=false",
            "-c",
            "hook.pre-commit.enabled=false",
            "-c",
            "hook.prepare-commit-msg.enabled=false",
            "-c",
            "hook.reference-transaction.enabled=false",
            "-c",
            "commit.gpgSign=false",
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "--no-optional-locks",
            "-C",
            str(self.public),
            "commit",
            "--no-verify",
            "--no-gpg-sign",
            "--message",
            "candidate release",
        )
        return _git(self.public, "rev-parse", "HEAD")


def _errors(report: dict[str, object]) -> list[str]:
    value = report["errors"]
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise TypeError("handoff report returned invalid errors")
    return value


class PublicHandoffLifecycleTests(unittest.TestCase):
    def _operation_fixture(
        self,
        root: Path,
    ) -> tuple[Path, Path, Path, Path, Path, Path, Path]:
        operation = root / "operation"
        operation.mkdir(mode=0o700)
        operation.chmod(0o700)
        control = operation / "control"
        state = operation / "state"
        temporary = operation / "temporary"
        control.mkdir(mode=0o700)
        state.mkdir(mode=0o700)
        temporary.mkdir(mode=0o700)
        control.chmod(0o700)
        state.chmod(0o700)
        temporary.chmod(0o700)
        export = operation / "export"
        _write_export(export)
        public = operation / "public-clone"
        authoring = root / "authoring"
        authoring.mkdir()
        return operation, control, state, temporary, export, public, authoring

    def test_preflight_validates_closed_topology_before_network_use(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            operation, control, state, temporary, export, public, authoring = (
                self._operation_fixture(root)
            )
            report = public_handoff_lifecycle.preflight_network_inputs(
                operation_root=operation,
                control_root=control,
                state_root=state,
                temporary_root=temporary,
                export_root=export,
                public_clone_root=public,
                authoring_root=authoring,
                remote_name="origin",
                branch="main",
                fetch_url="https://public.example.invalid/framework.git",
                push_url="https://public.example.invalid/framework.git",
            )
            self.assertEqual("ready-for-network", report["status"])
            self.assertEqual("refs/heads/main", report["branch_ref"])

            with self.assertRaisesRegex(ValueError, "remote-helper"):
                public_handoff_lifecycle.preflight_network_inputs(
                    operation_root=operation,
                    control_root=control,
                    state_root=state,
                    temporary_root=temporary,
                    export_root=export,
                    public_clone_root=public,
                    authoring_root=authoring,
                    remote_name="origin",
                    branch="main",
                    fetch_url="ext::payload",
                    push_url="https://public.example.invalid/framework.git",
                )
            with self.assertRaisesRegex(ValueError, "exact 'control' child"):
                public_handoff_lifecycle.preflight_network_inputs(
                    operation_root=operation,
                    control_root=root / "other-control",
                    state_root=state,
                    temporary_root=temporary,
                    export_root=export,
                    public_clone_root=public,
                    authoring_root=authoring,
                    remote_name="origin",
                    branch="main",
                    fetch_url="https://public.example.invalid/framework.git",
                    push_url="https://public.example.invalid/framework.git",
                )

    def test_existing_clone_preflight_requires_and_binds_the_exact_clone(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            operation, control, state, temporary, export, public, authoring = (
                self._operation_fixture(root)
            )
            public.mkdir(mode=0o700)
            report = public_handoff_lifecycle.preflight_existing_clone_inputs(
                operation_root=operation,
                control_root=control,
                state_root=state,
                temporary_root=temporary,
                export_root=export,
                public_clone_root=public,
                authoring_root=authoring,
                remote_name="origin",
                branch="main",
                fetch_url="https://public.example.invalid/framework.git",
                push_url="https://public.example.invalid/framework.git",
            )
            self.assertEqual("ready-for-existing-clone-readback", report["status"])
            self.assertEqual("refs/heads/main", report["branch_ref"])

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            operation, control, state, temporary, export, public, authoring = (
                self._operation_fixture(root)
            )
            outside = root / "outside-clone"
            outside.mkdir()
            public.symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "public clone root"):
                public_handoff_lifecycle.preflight_existing_clone_inputs(
                    operation_root=operation,
                    control_root=control,
                    state_root=state,
                    temporary_root=temporary,
                    export_root=export,
                    public_clone_root=public,
                    authoring_root=authoring,
                    remote_name="origin",
                    branch="main",
                    fetch_url="https://public.example.invalid/framework.git",
                    push_url="https://public.example.invalid/framework.git",
                )
    def test_remote_parent_parser_requires_one_exact_full_ref_record(self) -> None:
        oid = "a" * 40
        self.assertEqual(
            oid,
            public_handoff_lifecycle.parse_remote_parent(
                branch="main",
                record=f"{oid}\trefs/heads/main",
            ),
        )
        for invalid in (
            f"{oid}\trefs/heads/other",
            f"{oid}\trefs/heads/main\n{oid}\trefs/heads/main",
            f" {oid}\trefs/heads/main",
            "short\trefs/heads/main",
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                public_handoff_lifecycle.parse_remote_parent(
                    branch="main",
                    record=invalid,
                )

    def test_lifecycle_cli_round_trip_matches_bash_command_substitution(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            operation, control, state, temporary, export, public, authoring = (
                self._operation_fixture(root)
            )
            lifecycle = REPO_ROOT / "scripts" / "public_handoff_lifecycle.py"
            command = [sys.executable, str(lifecycle)]
            preflight = run_bounded(
                [
                    *command,
                    "preflight",
                    "--operation-root",
                    str(operation),
                    "--control-root",
                    str(control),
                    "--state-root",
                    str(state),
                    "--temporary-root",
                    str(temporary),
                    "--export-root",
                    str(export),
                    "--public-clone-root",
                    str(public),
                    "--authoring-root",
                    str(authoring),
                    "--remote-name",
                    "origin",
                    "--branch",
                    "main",
                    "--fetch-url",
                    "https://public.example.invalid/framework.git",
                    "--push-url",
                    "https://public.example.invalid/framework.git",
                ],
                cwd=root,
                check=True,
            )
            self.assertEqual("ready-for-network", json.loads(preflight.stdout)["status"])
            self.assertEqual("", preflight.stderr)

            public.mkdir()
            (public / ".git").mkdir()
            (public / "obsolete.txt").write_text("obsolete\n", encoding="utf-8")
            materialized = run_bounded(
                [
                    *command,
                    "materialize",
                    "--operation-root",
                    str(operation),
                    "--control-root",
                    str(control),
                    "--state-root",
                    str(state),
                    "--temporary-root",
                    str(temporary),
                    "--export-root",
                    str(export),
                    "--public-clone-root",
                    str(public),
                    "--authoring-root",
                    str(authoring),
                ],
                cwd=root,
                check=True,
            )
            self.assertEqual("materialized", json.loads(materialized.stdout)["status"])
            self.assertEqual("", materialized.stderr)

            expected_parent = "a" * 40
            candidate = "b" * 40
            tag_oid = "c" * 40
            git_sha256 = "d" * 64
            continuity = {
                "schema_version": public_handoff_check.HANDOFF_SCHEMA_VERSION,
                "branch": "main",
                "expected_parent_commit": expected_parent,
                "export_marker_sha256": "e" * 64,
                "git_executable_sha256": git_sha256,
                "object_format": "sha1",
                "payload_file_count": 1,
                "remote_name": "origin",
                "remote_target_sha256": "f" * 64,
            }
            receipt_tail: dict[str, object] = {
                "errors": [],
                "notes": ["fixture"],
                "tag_object_type": None,
                "tag_oid": None,
                "tag_peeled_commit": None,
                "tag_ref": None,
            }
            staged = {
                **continuity,
                **receipt_tail,
                "candidate_commit": None,
                "phase": "staged",
            }
            committed = {
                **continuity,
                **receipt_tail,
                "candidate_commit": candidate,
                "phase": "committed",
            }
            tagged = {
                **committed,
                "tag_object_type": "tag",
                "tag_oid": tag_oid,
                "tag_peeled_commit": candidate,
                "tag_ref": "refs/tags/v2.0.0",
            }
            staged_json = json.dumps(staged, indent=2, sort_keys=True) + "\n"
            committed_json = json.dumps(committed, indent=2, sort_keys=True) + "\n"
            tagged_json = json.dumps(tagged, indent=2, sort_keys=True) + "\n"
            staged_sha256 = hashlib.sha256(staged_json.encode("utf-8")).hexdigest()
            branch_record = f"{expected_parent}\trefs/heads/main"
            bash = _required_executable("bash")
            bash_source = r'''
set -euo pipefail
parent="$("$1" "$2" parse-remote-parent --branch main --record "$3")"
[[ "$parent" == "$4" ]]
staged_digest="$("$1" "$2" validate-receipt --phase staged --receipt-json "$5" --expected-git-sha256 "$8" --emit receipt-sha256)"
[[ "$staged_digest" == "$9" ]]
committed_candidate="$("$1" "$2" validate-receipt --phase committed --receipt-json "$6" --baseline-json "$5" --expected-git-sha256 "$8" --emit candidate-commit)"
[[ "$committed_candidate" == "$7" ]]
shift 9
checked_tag_oid="$("$1" "$2" validate-receipt --phase committed --receipt-json "$3" --baseline-json "$4" --expected-git-sha256 "$5" --expected-tag-ref refs/tags/v2.0.0 --expected-tag-object-type tag --emit tag-oid)"
[[ "$checked_tag_oid" == "$6" ]]
branch_records="$7"$'\trefs/heads/main'
tag_records="$6"$'\trefs/tags/v2.0.0\n'"$7"$'\trefs/tags/v2.0.0^{}'
readback="$("$1" "$2" verify-remote-readback --branch main --branch-records "$branch_records" --candidate-commit "$7" --tag-ref refs/tags/v2.0.0 --tag-records "$tag_records" --tag-oid "$6" --tag-object-type tag)"
[[ "$readback" == *'"status": "branch-and-tag-readback-verified"'* ]]
printf '%s\n%s\n%s\n' "$8" "$7" "$checked_tag_oid"
'''
            round_trip = run_bounded(
                [
                    bash,
                    "-c",
                    bash_source,
                    "lifecycle-cli",
                    sys.executable,
                    str(lifecycle),
                    branch_record,
                    expected_parent,
                    staged_json,
                    committed_json,
                    candidate,
                    git_sha256,
                    staged_sha256,
                    sys.executable,
                    str(lifecycle),
                    tagged_json,
                    committed_json,
                    git_sha256,
                    tag_oid,
                    candidate,
                    expected_parent,
                ],
                cwd=root,
                check=True,
            )
            self.assertEqual(
                [expected_parent, candidate, tag_oid],
                round_trip.stdout.splitlines(),
            )
            self.assertEqual("", round_trip.stderr)

            invalid = run_bounded(
                [
                    *command,
                    "parse-remote-parent",
                    "--branch",
                    "main",
                    "--record",
                    "invalid",
                ],
                cwd=root,
            )
            self.assertEqual(2, invalid.returncode)
            self.assertEqual("", invalid.stdout)
            self.assertTrue(invalid.stderr.startswith("public handoff lifecycle failed:"))

    def test_materializer_replaces_only_payload_and_preserves_git_directory(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            operation, control, state, temporary, export, public, authoring = (
                self._operation_fixture(root)
            )
            remote = root / "remote.git"
            seed = root / "seed"
            _git(root, "init", "--bare", "-q", str(remote))
            seed.mkdir()
            _git(seed, "init", "-q")
            (seed / "obsolete.txt").write_text("obsolete\n", encoding="utf-8")
            _git(seed, "add", "obsolete.txt")
            _git(
                seed,
                "-c",
                "user.name=Fixture",
                "-c",
                "user.email=fixture@example.invalid",
                "commit",
                "-qm",
                "baseline",
            )
            _git(seed, "branch", "-M", "main")
            _git(seed, "remote", "add", "origin", str(remote))
            _git(seed, "push", "-q", "-u", "origin", "main")
            _git(remote, "symbolic-ref", "HEAD", "refs/heads/main")
            _git(root, "clone", "--no-local", "-q", str(remote), str(public))
            expected_parent = _git(public, "rev-parse", "HEAD")
            remote_url = "https://public.example.invalid/framework.git"
            _git(public, "remote", "set-url", "origin", remote_url)

            _git(authoring, "init", "-q")
            (authoring / "authoring.txt").write_text(
                "authoring source\n",
                encoding="utf-8",
            )
            _git(authoring, "add", "authoring.txt")
            _git(
                authoring,
                "-c",
                "user.name=Fixture",
                "-c",
                "user.email=fixture@example.invalid",
                "commit",
                "-qm",
                "authoring",
            )
            git_identity = (public / ".git").stat().st_dev, (public / ".git").stat().st_ino

            report = public_handoff_lifecycle.materialize_export(
                operation_root=operation,
                control_root=control,
                state_root=state,
                temporary_root=temporary,
                export_root=export,
                public_clone_root=public,
                authoring_root=authoring,
            )
            self.assertEqual("materialized", report["status"])
            self.assertEqual(
                git_identity,
                ((public / ".git").stat().st_dev, (public / ".git").stat().st_ino),
            )
            self.assertFalse((public / "obsolete.txt").exists())
            self.assertFalse(
                (public / public_surface.PUBLIC_EXPORT_OWNERSHIP_MARKER).exists()
            )
            _release_git(
                public,
                "-c",
                "core.attributesFile=/dev/null",
                "-c",
                "core.hooksPath=/dev/null",
                "--no-optional-locks",
                "-C",
                str(public),
                "add",
                "--all",
                "--",
            )
            with _verifier_origin_context(export):
                handoff = public_handoff_check.check_public_handoff(
                    phase=public_handoff_check.HandoffPhase.STAGED,
                    export_root=export,
                    public_clone_root=public,
                    authoring_root=authoring,
                    git_executable=Path(_GIT_EXECUTABLE),
                    temporary_root=temporary,
                    remote_name="origin",
                    branch="main",
                    expected_fetch_url=remote_url,
                    expected_push_url=remote_url,
                    expected_parent_commit=expected_parent,
                )
            self.assertEqual([], _errors(handoff), handoff)

    def test_materializer_rejects_oversized_payload_before_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            operation, control, state, temporary, export, public, authoring = (
                self._operation_fixture(root)
            )
            large_payload = export / "large-payload.bin"
            large_payload.write_bytes(
                b"x" * (public_release_check.PUBLIC_TEXT_INPUT_MAX_BYTES + 1)
            )
            large_payload.chmod(0o644)
            _refresh_export_marker(export)
            public.mkdir()
            git_directory = public / ".git"
            git_directory.mkdir()
            obsolete = public / "obsolete.txt"
            obsolete.write_text("obsolete\n", encoding="utf-8")
            git_identity = git_directory.stat().st_dev, git_directory.stat().st_ino

            with self.assertRaisesRegex(ValueError, "canonical 4 MiB"):
                public_handoff_lifecycle.materialize_export(
                    operation_root=operation,
                    control_root=control,
                    state_root=state,
                    temporary_root=temporary,
                    export_root=export,
                    public_clone_root=public,
                    authoring_root=authoring,
                )
            self.assertTrue(obsolete.is_file())
            self.assertEqual(
                git_identity,
                (git_directory.stat().st_dev, git_directory.stat().st_ino),
            )

    def test_materializer_rejects_git_name_swap_before_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            operation, control, state, temporary, export, public, authoring = (
                self._operation_fixture(root)
            )
            public.mkdir()
            (public / ".git").mkdir()
            (public / "obsolete.txt").write_text("obsolete\n", encoding="utf-8")
            real_open = os.open
            swapped = False

            def swap_git_name(
                path: str | bytes,
                flags: int,
                mode: int = 0o777,
                *,
                dir_fd: int | None = None,
            ) -> int:
                nonlocal swapped
                if path == ".git" and dir_fd is not None and not swapped:
                    os.rename(
                        ".git",
                        ".git-original",
                        src_dir_fd=dir_fd,
                        dst_dir_fd=dir_fd,
                    )
                    os.mkdir(".git", dir_fd=dir_fd)
                    swapped = True
                return real_open(path, flags, mode, dir_fd=dir_fd)

            try:
                with (
                    mock.patch.object(
                        public_handoff_lifecycle.os,
                        "open",
                        side_effect=swap_git_name,
                    ),
                    self.assertRaisesRegex(ValueError, r"\.git binding changed"),
                ):
                    public_handoff_lifecycle.materialize_export(
                        operation_root=operation,
                        control_root=control,
                        state_root=state,
                        temporary_root=temporary,
                        export_root=export,
                        public_clone_root=public,
                        authoring_root=authoring,
                    )
            finally:
                if swapped:
                    (public / ".git").rmdir()
                    (public / ".git-original").rename(public / ".git")

    def test_materializer_rejects_state_root_swap_during_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            operation, control, state, temporary, export, public, authoring = (
                self._operation_fixture(root)
            )
            public.mkdir()
            (public / ".git").mkdir()
            (public / "obsolete.txt").write_text("obsolete\n", encoding="utf-8")
            real_copy = public_handoff_lifecycle._copy_payload_file
            swapped = False

            def copy_then_swap_state(*args: object, **kwargs: object) -> None:
                nonlocal swapped
                real_copy(*args, **kwargs)  # type: ignore[arg-type]
                if not swapped:
                    state.rename(operation / "state-original")
                    state.mkdir(mode=0o700)
                    swapped = True

            with (
                mock.patch.object(
                    public_handoff_lifecycle,
                    "_copy_payload_file",
                    side_effect=copy_then_swap_state,
                ),
                self.assertRaisesRegex(ValueError, "state root"),
            ):
                public_handoff_lifecycle.materialize_export(
                    operation_root=operation,
                    control_root=control,
                    state_root=state,
                    temporary_root=temporary,
                    export_root=export,
                    public_clone_root=public,
                    authoring_root=authoring,
                )

    def test_materializer_rejects_nested_mount_before_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            operation, control, state, temporary, export, public, authoring = (
                self._operation_fixture(root)
            )
            public.mkdir()
            (public / ".git").mkdir()
            nested = public / "mounted"
            nested.mkdir()
            retained = nested / "retained.txt"
            retained.write_text("retain\n", encoding="utf-8")
            nested_identity = nested.stat().st_dev, nested.stat().st_ino
            real_mount_id = public_handoff_lifecycle._descriptor_mount_id

            def substituted_mount_id(descriptor: int) -> int:
                metadata = os.fstat(descriptor)
                mount_id = real_mount_id(descriptor)
                if (metadata.st_dev, metadata.st_ino) == nested_identity:
                    return mount_id + 1
                return mount_id

            with (
                mock.patch.object(
                    public_handoff_lifecycle,
                    "_descriptor_mount_id",
                    side_effect=substituted_mount_id,
                ),
                self.assertRaisesRegex(ValueError, "crossed a mount boundary"),
            ):
                public_handoff_lifecycle.materialize_export(
                    operation_root=operation,
                    control_root=control,
                    state_root=state,
                    temporary_root=temporary,
                    export_root=export,
                    public_clone_root=public,
                    authoring_root=authoring,
                )
            self.assertTrue(retained.is_file())

    def test_receipt_continuity_and_remote_readback_are_machine_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = _HandoffFixture(Path(temp_dir), object_format="sha1")
            staged = fixture.check(public_handoff_check.HandoffPhase.STAGED)
            staged_json = json.dumps(staged, indent=2, sort_keys=True) + "\n"
            git_sha256 = str(staged["git_executable_sha256"])
            staged_digest = public_handoff_lifecycle.validate_receipt(
                phase=public_handoff_check.HandoffPhase.STAGED,
                receipt_json=staged_json,
                expected_git_sha256=git_sha256,
                baseline_json=None,
                expected_tag_ref=None,
                emit="receipt-sha256",
            )
            self.assertRegex(staged_digest, r"^[0-9a-f]{64}$")
            floating_schema = dict(staged)
            floating_schema["schema_version"] = 4.0
            with self.assertRaisesRegex(ValueError, "schema version"):
                public_handoff_lifecycle.validate_receipt(
                    phase=public_handoff_check.HandoffPhase.STAGED,
                    receipt_json=(
                        json.dumps(floating_schema, indent=2, sort_keys=True) + "\n"
                    ),
                    expected_git_sha256=git_sha256,
                    baseline_json=None,
                    expected_tag_ref=None,
                    emit="receipt-sha256",
                )

            candidate = fixture.commit_candidate()
            committed = fixture.check(public_handoff_check.HandoffPhase.COMMITTED)
            committed_json = json.dumps(committed, indent=2, sort_keys=True) + "\n"
            self.assertEqual(
                candidate,
                public_handoff_lifecycle.validate_receipt(
                    phase=public_handoff_check.HandoffPhase.COMMITTED,
                    receipt_json=committed_json,
                    expected_git_sha256=git_sha256,
                    baseline_json=staged_json,
                    expected_tag_ref=None,
                    emit="candidate-commit",
                ),
            )
            changed = dict(committed)
            changed["remote_target_sha256"] = "f" * 64
            with self.assertRaisesRegex(ValueError, "continuity changed"):
                public_handoff_lifecycle.validate_receipt(
                    phase=public_handoff_check.HandoffPhase.COMMITTED,
                    receipt_json=json.dumps(changed, indent=2, sort_keys=True) + "\n",
                    expected_git_sha256=git_sha256,
                    baseline_json=staged_json,
                    expected_tag_ref=None,
                    emit="candidate-commit",
                )

            tag_ref = "refs/tags/v-lifecycle-test"
            _release_git(
                fixture.public,
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "tag.gpgSign=false",
                "-c",
                "user.name=Fixture",
                "-c",
                "user.email=fixture@example.invalid",
                "-C",
                str(fixture.public),
                "tag",
                "--annotate",
                "--no-sign",
                "--message",
                "lifecycle tag",
                "--",
                "v-lifecycle-test",
                candidate,
            )
            tag_oid = _git(fixture.public, "rev-parse", tag_ref)
            tagged_receipt = fixture.check(
                public_handoff_check.HandoffPhase.COMMITTED,
                tag_ref=tag_ref,
            )
            tagged_json = json.dumps(tagged_receipt, indent=2, sort_keys=True) + "\n"
            self.assertEqual(
                tag_oid,
                public_handoff_lifecycle.validate_receipt(
                    phase=public_handoff_check.HandoffPhase.COMMITTED,
                    receipt_json=tagged_json,
                    expected_git_sha256=git_sha256,
                    baseline_json=committed_json,
                    expected_tag_ref=tag_ref,
                    expected_tag_object_type="tag",
                    emit="tag-oid",
                ),
            )

            branch_record = f"{candidate}\trefs/heads/main"
            readback = public_handoff_lifecycle.verify_remote_readback(
                branch="main",
                branch_records=branch_record,
                candidate_commit=candidate,
                tag_ref=None,
                tag_records=None,
                tag_oid=None,
                tag_object_type=None,
            )
            self.assertEqual("branch-readback-verified", readback["status"])
            tagged = public_handoff_lifecycle.verify_remote_readback(
                branch="main",
                branch_records=branch_record,
                candidate_commit=candidate,
                tag_ref=tag_ref,
                tag_records=(
                    f"{tag_oid}\t{tag_ref}\n"
                    f"{candidate}\t{tag_ref}^{{}}"
                ),
                tag_oid=tag_oid,
                tag_object_type="tag",
            )
            self.assertEqual("branch-and-tag-readback-verified", tagged["status"])


class PublicHandoffTests(unittest.TestCase):
    def test_public_handoff_accepts_exact_staged_and_committed_candidates(self) -> None:
        for object_format in ("sha1", "sha256"):
            with self.subTest(object_format=object_format), tempfile.TemporaryDirectory() as temp_dir:
                fixture = _HandoffFixture(Path(temp_dir), object_format=object_format)
                staged = fixture.check(public_handoff_check.HandoffPhase.STAGED)
                self.assertEqual([], _errors(staged))
                self.assertIsNone(staged["candidate_commit"])
                expected_payload_count = len(
                    public_release_check.PUBLIC_EXPORT_SENTINEL_FILES
                    | {
                        relative
                        for _module_name, relative, _module in _VERIFIER_SOURCE_MODULES
                    }
                )
                self.assertEqual(expected_payload_count, staged["payload_file_count"])
                self.assertEqual(object_format, staged["object_format"])
                self.assertRegex(str(staged["git_executable_sha256"]), r"^[0-9a-f]{64}$")
                self.assertEqual([], list(fixture.temporary.iterdir()))
                self.assertEqual(
                    _expected_remote_target_sha256(
                        remote_name="origin",
                        fetch_url=fixture.remote_url,
                        push_url=fixture.remote_url,
                        object_format=object_format,
                    ),
                    staged["remote_target_sha256"],
                )

                candidate = fixture.commit_candidate()
                committed = fixture.check(public_handoff_check.HandoffPhase.COMMITTED)
                self.assertEqual([], _errors(committed))
                self.assertEqual(candidate, committed["candidate_commit"])
                self.assertEqual(fixture.expected_parent, committed["expected_parent_commit"])

    def test_verifier_source_table_and_static_local_import_closure_are_exact(
        self,
    ) -> None:
        expected_sources = tuple(
            (module_name, relative)
            for module_name, relative, _module in _VERIFIER_SOURCE_MODULES
        )
        self.assertEqual(
            expected_sources,
            public_handoff_check._LOCAL_VERIFIER_SOURCES,
        )
        scripts = REPO_ROOT / "scripts"
        available_modules = frozenset(
            path.stem
            for path in scripts.glob("*.py")
            if path.stem.isidentifier()
        )
        graph = {
            module_name: _static_local_imports(
                REPO_ROOT / relative,
                available_modules=available_modules,
            )
            for module_name, relative in expected_sources
        }
        declared_modules = {module_name for module_name, _relative in expected_sources}
        escaped = {
            (module_name, imported)
            for module_name, imports in graph.items()
            for imported in imports - declared_modules
        }
        self.assertEqual(set(), escaped)
        reachable: set[str] = set()
        pending = ["public_handoff_check"]
        while pending:
            module_name = pending.pop()
            if module_name in reachable:
                continue
            reachable.add(module_name)
            pending.extend(graph.get(module_name, ()))
        self.assertEqual(declared_modules, reachable)

    def test_handoff_rejects_loaded_verifier_origin_outside_export(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = _HandoffFixture(Path(temp_dir), object_format="sha1")
            outside = fixture.root / "outside-safe-paths.py"
            shutil.copyfile(REPO_ROOT / "scripts" / "safe_paths.py", outside)
            report = fixture.check(
                public_handoff_check.HandoffPhase.STAGED,
                verifier_origins={"safe_paths": outside},
            )
            self.assertIn(
                "loaded handoff verifier source origin does not match the verified export: safe_paths",
                _errors(report),
            )
            self.assertNotIn(str(outside), json.dumps(report, sort_keys=True))

    def test_documented_remote_probe_and_clone_are_exact_sanitized_and_independent(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = _HandoffFixture(Path(temp_dir), object_format="sha1")
            _git(
                fixture.remote,
                "tag",
                "remote-tag-not-for-release-clone",
                fixture.expected_parent,
            )
            redirect = fixture.root / "poisoned-fetch.git"
            _git(fixture.root, "init", "--bare", "-q", str(redirect))
            template = fixture.root / "poisoned-template"
            hooks = template / "hooks"
            hooks.mkdir(parents=True)
            hook_marker = fixture.root / "poisoned-template-hook-ran"
            post_checkout = hooks / "post-checkout"
            post_checkout.write_text(
                "#!/bin/sh\nprintf 'ran\\n' > "
                + shlex.quote(str(hook_marker))
                + "\n",
                encoding="utf-8",
            )
            post_checkout.chmod(0o755)
            global_config = fixture.root / "poisoned-global-config"
            _git(
                fixture.root,
                "config",
                "--file",
                str(global_config),
                "init.templateDir",
                str(template),
            )
            _git(
                fixture.root,
                "config",
                "--file",
                str(global_config),
                f"url.{redirect}.insteadOf",
                fixture.transport_url,
            )
            poisoned = dict(os.environ)
            poisoned.update(
                {
                    "GIT_CONFIG_GLOBAL": str(global_config),
                    "GIT_CONFIG_PARAMETERS": f"'init.templateDir={template}'",
                    "GIT_DIR": str(fixture.authoring / ".git"),
                    "GIT_TEMPLATE_DIR": str(template),
                    "GIT_WORK_TREE": str(fixture.authoring),
                }
            )
            destination = fixture.root / "fresh-release-clone"
            operation_root = fixture.root / "release-operation"
            control_root = operation_root / "control"
            control_root.mkdir(parents=True)
            _git(fixture.root, "init", "-q")
            _git(
                fixture.root,
                "config",
                f"url.{redirect}.insteadOf",
                fixture.transport_url,
            )
            self.assertFalse(destination.exists())
            with mock.patch.dict(os.environ, poisoned, clear=True):
                remote = _release_ls_remote(
                    control_root,
                    url=fixture.transport_url,
                    branch="main",
                )
                self.assertEqual(
                    f"{fixture.expected_parent}\trefs/heads/main",
                    remote.stdout.strip(),
                )
                _release_clone(
                    control_root,
                    url=fixture.transport_url,
                    destination=destination,
                    remote_name="public-upstream",
                    branch="main",
                )

            self.assertFalse(hook_marker.exists())
            self.assertFalse((destination / ".git" / "hooks" / "post-checkout").exists())
            self.assertEqual("main", _git(destination, "branch", "--show-current"))
            self.assertEqual(fixture.expected_parent, _git(destination, "rev-parse", "HEAD"))
            self.assertEqual("public-upstream", _git(destination, "remote"))
            self.assertEqual(
                fixture.transport_url,
                _git(destination, "remote", "get-url", "public-upstream"),
            )
            self.assertEqual(
                "--no-tags",
                _git(destination, "config", "--get", "remote.public-upstream.tagOpt"),
            )
            self.assertEqual(
                "",
                _git(destination, "for-each-ref", "--format=%(refname)", "refs/tags"),
            )
            remote_refs = set(
                _git(
                    destination,
                    "for-each-ref",
                    "--format=%(refname)",
                    "refs/remotes/public-upstream",
                ).splitlines()
            )
            self.assertIn("refs/remotes/public-upstream/main", remote_refs)
            self.assertTrue(
                remote_refs
                <= {
                    "refs/remotes/public-upstream/HEAD",
                    "refs/remotes/public-upstream/main",
                }
            )
            self.assertFalse((destination / ".git" / "objects" / "info" / "alternates").exists())
            self.assertFalse(
                _object_file_identities(fixture.remote / "objects")
                & _object_file_identities(destination / ".git" / "objects")
            )
            _git(
                destination,
                "remote",
                "set-url",
                "public-upstream",
                fixture.remote_url,
            )
            _copy_export_payload(fixture.export, destination)
            with _verifier_origin_context(fixture.export):
                handoff = public_handoff_check.check_public_handoff(
                    phase=public_handoff_check.HandoffPhase.STAGED,
                    export_root=fixture.export,
                    public_clone_root=destination,
                    authoring_root=fixture.authoring,
                    git_executable=Path(_GIT_EXECUTABLE),
                    temporary_root=fixture.temporary,
                    remote_name="public-upstream",
                    branch="main",
                    expected_fetch_url=fixture.remote_url,
                    expected_push_url=fixture.remote_url,
                    expected_parent_commit=fixture.expected_parent,
                )
            self.assertEqual([], _errors(handoff), handoff)

    def test_committed_handoff_preflights_lightweight_and_annotated_tags(self) -> None:
        for object_format in ("sha1", "sha256"):
            for annotated in (False, True):
                with (
                    self.subTest(
                        annotated=annotated,
                        object_format=object_format,
                    ),
                    tempfile.TemporaryDirectory() as temp_dir,
                ):
                    fixture = _HandoffFixture(
                        Path(temp_dir),
                        object_format=object_format,
                    )
                    self._assert_tag_preflight(fixture, annotated=annotated)

    def _assert_tag_preflight(
        self,
        fixture: _HandoffFixture,
        *,
        annotated: bool,
    ) -> None:
        candidate = fixture.commit_candidate()
        tag_ref = "refs/tags/v-test"
        if annotated:
            _release_git(
                fixture.public,
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "tag.gpgSign=false",
                "-c",
                "user.name=Fixture",
                "-c",
                "user.email=fixture@example.invalid",
                "-C",
                str(fixture.public),
                "tag",
                "--annotate",
                "--no-sign",
                "--message",
                "release tag",
                "--",
                "v-test",
                candidate,
            )
        else:
            _git(fixture.public, "tag", "v-test", candidate)
        tag_oid = _git(fixture.public, "rev-parse", tag_ref)

        report = fixture.check(
            public_handoff_check.HandoffPhase.COMMITTED,
            tag_ref=tag_ref,
        )

        self.assertEqual([], _errors(report), report)
        self.assertEqual(4, report["schema_version"])
        self.assertEqual(tag_ref, report["tag_ref"])
        self.assertEqual(tag_oid, report["tag_oid"])
        self.assertEqual(
            "tag" if annotated else "commit",
            report["tag_object_type"],
        )
        self.assertEqual(candidate, report["tag_peeled_commit"])

    def test_receipt_binds_distinct_remote_targets_without_disclosing_urls(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = _HandoffFixture(Path(temp_dir), object_format="sha1")
            first = fixture.check(public_handoff_check.HandoffPhase.STAGED)
            self.assertEqual([], _errors(first), first)
            second_url = "ssh://git@mirror.example.invalid/framework.git"
            _git(fixture.public, "remote", "set-url", "origin", second_url)
            second = fixture.check(
                public_handoff_check.HandoffPhase.STAGED,
                expected_fetch_url=second_url,
                expected_push_url=second_url,
            )
            self.assertEqual([], _errors(second), second)

            self.assertEqual("sha1", first["object_format"])
            self.assertEqual("sha1", second["object_format"])
            self.assertEqual(
                _expected_remote_target_sha256(
                    remote_name="origin",
                    fetch_url=fixture.remote_url,
                    push_url=fixture.remote_url,
                    object_format="sha1",
                ),
                first["remote_target_sha256"],
            )
            self.assertEqual(
                _expected_remote_target_sha256(
                    remote_name="origin",
                    fetch_url=second_url,
                    push_url=second_url,
                    object_format="sha1",
                ),
                second["remote_target_sha256"],
            )
            self.assertNotEqual(
                first["remote_target_sha256"],
                second["remote_target_sha256"],
            )
            first_json = json.dumps(first, sort_keys=True)
            second_json = json.dumps(second, sort_keys=True)
            for receipt in (first_json, second_json):
                self.assertNotIn(fixture.remote_url, receipt)
                self.assertNotIn(second_url, receipt)

    def test_tag_preflight_rejects_wrong_target_and_non_commit_object_before_push(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = _HandoffFixture(Path(temp_dir), object_format="sha1")
            fixture.commit_candidate()
            _git(fixture.public, "tag", "v-wrong", fixture.expected_parent)
            report = fixture.check(
                public_handoff_check.HandoffPhase.COMMITTED,
                tag_ref="refs/tags/v-wrong",
            )
            self.assertIn(
                "selected tag does not peel to the checked candidate commit",
                _errors(report),
            )
            self.assertNotEqual(
                0,
                run_bounded(
                    ["git", "rev-parse", "--verify", "refs/tags/v-wrong"],
                    cwd=fixture.remote,
                ).returncode,
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = _HandoffFixture(Path(temp_dir), object_format="sha1")
            fixture.commit_candidate()
            blob_oid = _git(fixture.public, "hash-object", "README.md")
            _git(fixture.public, "tag", "v-blob", blob_oid)
            report = fixture.check(
                public_handoff_check.HandoffPhase.COMMITTED,
                tag_ref="refs/tags/v-blob",
            )
            self.assertTrue(
                any("commit or tag object" in error for error in _errors(report)),
                report,
            )

    def test_tag_preflight_requires_committed_phase_and_full_tag_ref(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = _HandoffFixture(Path(temp_dir), object_format="sha1")
            staged = fixture.check(
                public_handoff_check.HandoffPhase.STAGED,
                tag_ref="refs/tags/v-test",
            )
            self.assertIn(
                "tag preflight is available only in committed phase",
                _errors(staged),
            )

            fixture.commit_candidate()
            malformed = fixture.check(
                public_handoff_check.HandoffPhase.COMMITTED,
                tag_ref="v-test",
            )
            self.assertIn(
                "tag ref must be one bounded canonical full refs/tags/... ref",
                _errors(malformed),
            )

    def test_public_handoff_rejects_exact_worktree_and_index_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = _HandoffFixture(Path(temp_dir), object_format="sha1")
            (fixture.public / ".DS_Store").write_text("ignored extra\n", encoding="utf-8")
            report = fixture.check(public_handoff_check.HandoffPhase.STAGED)
            self.assertTrue(
                any("files outside the export payload" in error for error in _errors(report))
            )
            self.assertEqual(len(_errors(report)), len(set(_errors(report))))

        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = _HandoffFixture(Path(temp_dir), object_format="sha1")
            readme = fixture.public / "README.md"
            original = readme.read_bytes()
            readme.write_bytes(b"staged tampering\n")
            _git(fixture.public, "add", "README.md")
            readme.write_bytes(original)
            report = fixture.check(public_handoff_check.HandoffPhase.STAGED)
            self.assertIn(
                "public clone index content differs from export: README.md",
                _errors(report),
            )

    def test_public_handoff_rejects_parent_remote_and_storage_misbinding(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = _HandoffFixture(Path(temp_dir), object_format="sha1")
            wrong_url = "https://example.invalid/different-repository.git"
            report = fixture.check(
                public_handoff_check.HandoffPhase.STAGED,
                expected_fetch_url=wrong_url,
                expected_parent_commit="0" * 40,
            )
            joined = "\n".join(_errors(report))
            self.assertIn("expected fetch URL", joined)
            self.assertIn("expected parent", joined)
            self.assertNotIn(wrong_url, json.dumps(report, sort_keys=True))

        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = _HandoffFixture(Path(temp_dir), object_format="sha1")
            alternates = fixture.public / ".git" / "objects" / "info" / "alternates"
            alternates.write_text(
                str(fixture.authoring / ".git" / "objects") + "\n",
                encoding="utf-8",
            )
            report = fixture.check(public_handoff_check.HandoffPhase.STAGED)
            self.assertTrue(
                any("alternate object-store" in error for error in _errors(report))
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = _HandoffFixture(Path(temp_dir), object_format="sha1")
            report = fixture.check(
                public_handoff_check.HandoffPhase.STAGED,
                authoring_root=fixture.public,
            )
            self.assertTrue(
                any("distinct non-nested directories" in error for error in _errors(report))
            )

            nested_temporary = fixture.authoring / "handoff-temporary"
            nested_temporary.mkdir()
            report = fixture.check(
                public_handoff_check.HandoffPhase.STAGED,
                temporary_root=nested_temporary,
            )
            self.assertTrue(
                any("distinct non-nested directories" in error for error in _errors(report))
            )

    def test_public_handoff_rejects_shared_or_external_local_config(self) -> None:
        for case in ("symlink", "hardlink", "include", "include-if"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temp_dir:
                fixture = _HandoffFixture(Path(temp_dir), object_format="sha1")
                public_config = fixture.public / ".git" / "config"
                authoring_config = fixture.authoring / ".git" / "config"
                if case == "symlink":
                    public_config.unlink()
                    public_config.symlink_to(authoring_config)
                elif case == "hardlink":
                    public_config.unlink()
                    os.link(authoring_config, public_config)
                else:
                    included = fixture.root / "external-git-config"
                    included.write_text(
                        "[http]\n\tproxy = http://127.0.0.1:9\n",
                        encoding="utf-8",
                    )
                    key = (
                        "include.path"
                        if case == "include"
                        else "includeIf.onbranch:never.path"
                    )
                    _git(fixture.public, "config", key, str(included))

                report = fixture.check(public_handoff_check.HandoffPhase.STAGED)
                self.assertTrue(_errors(report), report)
                joined = "\n".join(_errors(report))
                if case == "hardlink":
                    self.assertIn("exactly one hard link", joined)
                elif case in {"include", "include-if"}:
                    self.assertIn("must not include external configuration", joined)

    def test_public_handoff_rejects_clone_local_configured_hooks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = _HandoffFixture(Path(temp_dir), object_format="sha1")
            _git(
                fixture.public,
                "config",
                "hook.release-check.command",
                "/bin/true",
            )
            _git(
                fixture.public,
                "config",
                "--add",
                "hook.release-check.event",
                "post-commit",
            )

            report = fixture.check(public_handoff_check.HandoffPhase.STAGED)

            self.assertIn(
                "public Git local config must not configure hook commands",
                _errors(report),
            )

    def test_release_git_disables_configured_post_index_change_hook(self) -> None:
        version_parts = _git(REPO_ROOT, "--version").split()[2].split(".")
        try:
            version = tuple(int(part) for part in version_parts[:3])
        except ValueError:
            self.skipTest("installed Git version is not a numeric release")
        if version < (2, 54, 0):
            self.skipTest("configured Git hooks require Git 2.54.0 or newer")

        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = _HandoffFixture(Path(temp_dir), object_format="sha1")
            marker = fixture.root / "configured-post-index-change-ran"
            hook = fixture.root / "configured-post-index-change"
            hook.write_text(
                "#!/bin/sh\nprintf 'ran\\n' > "
                + shlex.quote(str(marker))
                + "\n",
                encoding="utf-8",
            )
            hook.chmod(0o755)
            _git(
                fixture.public,
                "config",
                "hook.release-check.command",
                str(hook),
            )
            _git(
                fixture.public,
                "config",
                "--add",
                "hook.release-check.event",
                "post-index-change",
            )

            readme = fixture.public / "README.md"
            readme.write_text("unsafe staging control\n", encoding="utf-8")
            _git(fixture.public, "add", "README.md")
            self.assertTrue(marker.is_file())
            marker.unlink()

            readme.write_text("bounded staging control\n", encoding="utf-8")
            _release_git(
                fixture.public,
                "-c",
                "core.attributesFile=/dev/null",
                "-c",
                "core.hooksPath=/dev/null",
                "--no-optional-locks",
                "-C",
                str(fixture.public),
                "add",
                "--all",
                "--",
            )
            self.assertFalse(marker.exists())

    def test_handoff_git_runner_pins_fsmonitor_disable_policy(self) -> None:
        git = mock.Mock()
        git.command = "/proc/self/fd/7"
        git.pass_fds = (7,)
        root = Path.cwd()
        gitdir = root / ".git"
        with mock.patch.object(
            public_release_check,
            "_bounded_git_command",
            return_value=(0, b"", b""),
        ) as run:
            observed = public_handoff_check._run_git(
                git,
                root,
                gitdir,
                ["status", "--short"],
                label="Git policy test",
            )

        self.assertEqual(b"", observed)
        command = run.call_args.args[1]
        self.assertEqual("/proc/self/fd/7", command[0])
        self.assertIn("core.fsmonitor=false", command)
        self.assertIn("core.untrackedCache=false", command)
        self.assertEqual((7,), run.call_args.kwargs["pass_fds"])
        self.assertEqual(2, git.require_current.call_count)

    def test_git_control_inventory_binds_exact_authoring_fsmonitor_enoent(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            descriptor = os.open(
                temp_dir,
                os.O_RDONLY
                | public_release_check._required_open_flag("O_DIRECTORY")
                | public_release_check._required_open_flag("O_NOFOLLOW"),
            )

            def inventory(
                *,
                allow_projection: bool,
            ) -> public_handoff_check._GitControlInventory:
                raw_entry = mock.Mock()
                raw_entry.name = "fsmonitor--daemon.ipc"
                raw_entry.stat.side_effect = FileNotFoundError(
                    2,
                    "projected socket is not stat-able through the directory descriptor",
                )
                scanner = mock.MagicMock()
                scanner.__enter__.return_value = iter(
                    (cast(os.DirEntry[str], raw_entry),)
                )
                scanner.__exit__.return_value = False
                with mock.patch.object(
                    public_handoff_check.os,
                    "scandir",
                    return_value=scanner,
                ):
                    return public_handoff_check._git_control_inventory_descriptor(
                        descriptor,
                        allow_opaque_authoring_fsmonitor_projection=allow_projection,
                    )

            try:
                authoring = inventory(allow_projection=True)
                strict = inventory(allow_projection=False)
            finally:
                os.close(descriptor)

        self.assertEqual((), authoring.tree.errors)
        self.assertEqual(
            ("fsmonitor--daemon.ipc",),
            authoring.opaque_entries,
        )
        self.assertEqual((), strict.opaque_entries)
        self.assertTrue(strict.tree.errors)
        self.assertIn("[Errno 2]", strict.tree.errors[0])

    def test_authoring_fsmonitor_enoent_exception_is_path_and_error_exact(
        self,
    ) -> None:
        def entry_with(error: OSError, *, name: str) -> os.DirEntry[str]:
            raw_entry = mock.Mock()
            raw_entry.name = name
            raw_entry.stat.side_effect = error
            return cast(os.DirEntry[str], raw_entry)

        accepted = public_handoff_check._git_control_entry_metadata(
            entry_with(
                FileNotFoundError(2, "projected socket"),
                name="fsmonitor--daemon.ipc",
            ),
            prefix="",
            allow_opaque_authoring_fsmonitor_projection=True,
        )
        self.assertIsNone(accepted)

        rejected = (
            ("refs", "fsmonitor--daemon.ipc", FileNotFoundError(2, "nested")),
            ("", "fsmonitor--daemon.ipc.other", FileNotFoundError(2, "other")),
            ("", "fsmonitor--daemon.ipc", PermissionError(13, "denied")),
        )
        for prefix, name, error in rejected:
            with self.subTest(prefix=prefix, name=name, error=type(error).__name__):
                with self.assertRaises(type(error)):
                    public_handoff_check._git_control_entry_metadata(
                        entry_with(error, name=name),
                        prefix=prefix,
                        allow_opaque_authoring_fsmonitor_projection=True,
                    )

    def test_git_control_inventory_does_not_hide_exact_regular_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            endpoint = root / "fsmonitor--daemon.ipc"
            endpoint.write_text("ordinary control file\n", encoding="utf-8")
            descriptor = os.open(
                root,
                os.O_RDONLY
                | public_release_check._required_open_flag("O_DIRECTORY")
                | public_release_check._required_open_flag("O_NOFOLLOW"),
            )
            try:
                observed = public_handoff_check._git_control_inventory_descriptor(
                    descriptor,
                    allow_opaque_authoring_fsmonitor_projection=True,
                )
            finally:
                os.close(descriptor)

        self.assertEqual((), observed.tree.errors)
        self.assertEqual((), observed.opaque_entries)
        self.assertIn("fsmonitor--daemon.ipc", observed.tree.files)

    def test_tolerated_fsmonitor_enoent_retains_directory_stability_guard(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            descriptor = os.open(
                root,
                os.O_RDONLY
                | public_release_check._required_open_flag("O_DIRECTORY")
                | public_release_check._required_open_flag("O_NOFOLLOW"),
            )
            baseline = os.fstat(descriptor)
            raw_entry = mock.Mock()
            raw_entry.name = "fsmonitor--daemon.ipc"

            def change_directory_then_fail(*, follow_symlinks: bool) -> os.stat_result:
                self.assertFalse(follow_symlinks)
                os.utime(
                    root,
                    ns=(baseline.st_atime_ns, baseline.st_mtime_ns + 1_000_000_000),
                )
                raise FileNotFoundError(2, "projected socket")

            raw_entry.stat.side_effect = change_directory_then_fail
            scanner = mock.MagicMock()
            scanner.__enter__.return_value = iter(
                (cast(os.DirEntry[str], raw_entry),)
            )
            scanner.__exit__.return_value = False
            try:
                with mock.patch.object(
                    public_handoff_check.os,
                    "scandir",
                    return_value=scanner,
                ):
                    observed = public_handoff_check._git_control_inventory_descriptor(
                        descriptor,
                        allow_opaque_authoring_fsmonitor_projection=True,
                    )
            finally:
                os.close(descriptor)

        self.assertEqual(("fsmonitor--daemon.ipc",), observed.opaque_entries)
        self.assertTrue(observed.tree.errors)
        self.assertIn("changed during enumeration: .", observed.tree.errors[0])

    def test_handoff_routes_opaque_fsmonitor_projection_only_to_authoring(
        self,
    ) -> None:
        original = public_handoff_check._git_control_entry_metadata

        def projected_metadata(
            entry: os.DirEntry[str],
            *,
            prefix: str,
            allow_opaque_authoring_fsmonitor_projection: bool,
        ) -> os.stat_result | None:
            if not prefix and entry.name == "fsmonitor--daemon.ipc":
                if allow_opaque_authoring_fsmonitor_projection:
                    return None
                raise FileNotFoundError(2, "projected socket")
            return original(
                entry,
                prefix=prefix,
                allow_opaque_authoring_fsmonitor_projection=(
                    allow_opaque_authoring_fsmonitor_projection
                ),
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = _HandoffFixture(Path(temp_dir), object_format="sha1")
            endpoint = fixture.authoring / ".git" / "fsmonitor--daemon.ipc"
            endpoint.write_text("projection stand-in\n", encoding="utf-8")
            with mock.patch.object(
                public_handoff_check,
                "_git_control_entry_metadata",
                side_effect=projected_metadata,
            ):
                authoring = fixture.check(public_handoff_check.HandoffPhase.STAGED)
            self.assertEqual([], _errors(authoring), authoring)

        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = _HandoffFixture(Path(temp_dir), object_format="sha1")
            endpoint = fixture.public / ".git" / "fsmonitor--daemon.ipc"
            endpoint.write_text("projection stand-in\n", encoding="utf-8")
            with mock.patch.object(
                public_handoff_check,
                "_git_control_entry_metadata",
                side_effect=projected_metadata,
            ):
                public = fixture.check(public_handoff_check.HandoffPhase.STAGED)
            self.assertTrue(
                any(
                    "Git control metadata could not be inspected" in error
                    for error in _errors(public)
                ),
                public,
            )

    def test_handoff_accepts_authoring_and_rejects_public_fsmonitor_socket(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = _HandoffFixture(Path(temp_dir), object_format="sha1")
            endpoint = fixture.authoring / ".git" / "fsmonitor--daemon.ipc"
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
                listener.bind(str(endpoint))
                authoring = fixture.check(public_handoff_check.HandoffPhase.STAGED)
            self.assertEqual([], _errors(authoring), authoring)

        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = _HandoffFixture(Path(temp_dir), object_format="sha1")
            endpoint = fixture.public / ".git" / "fsmonitor--daemon.ipc"
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
                listener.bind(str(endpoint))
                public = fixture.check(public_handoff_check.HandoffPhase.STAGED)
            self.assertIn(
                "public Git control metadata contains unsupported entries",
                _errors(public),
            )

    def test_authoring_fsmonitor_socket_exception_is_path_and_type_exact(
        self,
    ) -> None:
        for relative in (
            Path("refs") / "fsmonitor--daemon.ipc",
            Path("fsmonitor--daemon.ipc.other"),
        ):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as temp_dir:
                fixture = _HandoffFixture(Path(temp_dir), object_format="sha1")
                endpoint = fixture.authoring / ".git" / relative
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
                    listener.bind(str(endpoint))
                    report = fixture.check(public_handoff_check.HandoffPhase.STAGED)
                self.assertIn(
                    "authoring Git control metadata contains unsupported entries",
                    _errors(report),
                )

        for kind in ("symlink", "fifo"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp_dir:
                fixture = _HandoffFixture(Path(temp_dir), object_format="sha1")
                endpoint = fixture.authoring / ".git" / "fsmonitor--daemon.ipc"
                if kind == "symlink":
                    endpoint.symlink_to(fixture.authoring / ".git" / "config")
                    expected_error = (
                        "authoring Git control metadata contains symlink entries"
                    )
                else:
                    os.mkfifo(endpoint)
                    expected_error = (
                        "authoring Git control metadata contains unsupported entries"
                    )
                report = fixture.check(public_handoff_check.HandoffPhase.STAGED)
                self.assertIn(expected_error, _errors(report))

    def test_authoring_fsmonitor_opaque_marker_is_terminally_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = _HandoffFixture(Path(temp_dir), object_format="sha1")
            original = public_handoff_check._git_control_inventory_descriptor
            authoring_calls = 0

            def inventory_with_initial_marker(
                descriptor: int,
                *,
                allow_opaque_authoring_fsmonitor_projection: bool = False,
            ) -> public_handoff_check._GitControlInventory:
                nonlocal authoring_calls
                observed = original(
                    descriptor,
                    allow_opaque_authoring_fsmonitor_projection=(
                        allow_opaque_authoring_fsmonitor_projection
                    ),
                )
                if allow_opaque_authoring_fsmonitor_projection:
                    authoring_calls += 1
                    if authoring_calls == 1:
                        return public_handoff_check._GitControlInventory(
                            tree=observed.tree,
                            opaque_entries=("fsmonitor--daemon.ipc",),
                        )
                return observed

            with mock.patch.object(
                public_handoff_check,
                "_git_control_inventory_descriptor",
                side_effect=inventory_with_initial_marker,
            ):
                report = fixture.check(public_handoff_check.HandoffPhase.STAGED)

            self.assertEqual(2, authoring_calls)
            self.assertIn(
                "authoring Git control metadata changed during handoff verification",
                _errors(report),
            )

    def test_git_control_root_change_diagnostic_identifies_repository_role(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            descriptor = os.open(
                temp_dir,
                os.O_RDONLY
                | public_release_check._required_open_flag("O_DIRECTORY")
                | public_release_check._required_open_flag("O_NOFOLLOW"),
            )
            try:
                empty = public_handoff_check._GitControlInventory(
                    tree=public_release_check._TreeInventory(
                        files={},
                        directories={},
                        symlinks={},
                        special={},
                        root_metadata=os.fstat(descriptor),
                        errors=(),
                    ),
                    opaque_entries=(),
                )

                def changed(*, description: str) -> None:
                    raise ValueError(f"{description} root changed after it was bound")

                binding = mock.Mock(descriptor=descriptor)
                binding.require_unchanged_chain.side_effect = changed
                storage = mock.Mock(gitdir=binding, common=binding)
                for public, owner in (
                    (True, "public clone"),
                    (False, "authoring checkout"),
                ):
                    with (
                        self.subTest(owner=owner),
                        mock.patch.object(
                            public_handoff_check,
                            "_git_control_inventory_descriptor",
                            return_value=empty,
                        ),
                        self.assertRaisesRegex(
                            ValueError,
                            rf"{owner} gitdir Git control root changed",
                        ),
                    ):
                        public_handoff_check._git_control_snapshot(
                            storage,
                            public=public,
                            errors=[],
                        )
            finally:
                os.close(descriptor)

    def test_handoff_rejects_unsupported_git_before_repository_inspection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = _HandoffFixture(Path(temp_dir), object_format="sha1")
            with (
                mock.patch.object(
                    public_release_check,
                    "require_git_fsmonitor_boolean_support",
                    side_effect=RuntimeError(
                        "Git 2.36.0 or newer is required before core.fsmonitor=false"
                    ),
                ) as version_check,
                mock.patch.object(
                    public_release_check,
                    "_open_git_inventory_binding",
                ) as inventory,
            ):
                report = fixture.check(public_handoff_check.HandoffPhase.STAGED)

            self.assertTrue(
                any("Git 2.36.0 or newer" in error for error in _errors(report)),
                report,
            )
            version_check.assert_called_once()
            inventory.assert_not_called()

    def test_release_git_disables_and_handoff_rejects_local_fsmonitor(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = _HandoffFixture(Path(temp_dir), object_format="sha1")
            marker = fixture.root / "fsmonitor-ran"
            monitor = fixture.root / "fsmonitor"
            monitor.write_text(
                "#!/bin/sh\nprintf 'ran\\n' >> "
                + shlex.quote(str(marker))
                + "\n",
                encoding="utf-8",
            )
            monitor.chmod(0o755)
            _git(fixture.public, "config", "core.fsmonitor", str(monitor))

            _git(fixture.public, "status", "--short")
            self.assertTrue(marker.is_file())
            marker.unlink()

            _release_git(
                fixture.public,
                "-c",
                "core.attributesFile=/dev/null",
                "-c",
                "core.hooksPath=/dev/null",
                "--no-optional-locks",
                "-C",
                str(fixture.public),
                "add",
                "--all",
                "--",
            )
            self.assertFalse(marker.exists())
            staged = fixture.check(public_handoff_check.HandoffPhase.STAGED)
            self.assertIn(
                "public Git local config must not configure core.fsmonitor",
                _errors(staged),
            )
            self.assertFalse(marker.exists())

            fixture.commit_candidate()
            self.assertFalse(marker.exists())
            committed = fixture.check(public_handoff_check.HandoffPhase.COMMITTED)
            self.assertIn(
                "public Git local config must not configure core.fsmonitor",
                _errors(committed),
            )
            self.assertFalse(marker.exists())

    def test_public_handoff_rejects_shared_refs_shallow_state_and_unqueried_mutation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = _HandoffFixture(Path(temp_dir), object_format="sha1")
            authoring_ref = fixture.authoring / ".git" / "refs" / "heads" / "shared-control"
            authoring_ref.write_text(fixture.expected_parent + "\n", encoding="ascii")
            public_ref = fixture.public / ".git" / "refs" / "heads" / "unselected-control"
            os.link(authoring_ref, public_ref)
            report = fixture.check(public_handoff_check.HandoffPhase.STAGED)
            joined = "\n".join(_errors(report))
            self.assertIn("public clone shares Git control files with authoring", joined)
            self.assertIn("public Git control metadata contains multiply-linked files", joined)

        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = _HandoffFixture(Path(temp_dir), object_format="sha1")
            (fixture.public / ".git" / "shallow").write_text(
                fixture.expected_parent + "\n",
                encoding="ascii",
            )
            report = fixture.check(public_handoff_check.HandoffPhase.STAGED)
            self.assertIn(
                "public clone must be a full non-shallow clone",
                _errors(report),
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = _HandoffFixture(Path(temp_dir), object_format="sha1")
            original = public_handoff_check._git_state
            calls: list[int] = []

            def mutate_unqueried_ref(*args: object, **kwargs: object) -> object:
                state = original(*args, **kwargs)  # type: ignore[arg-type]
                calls.append(1)
                if len(calls) == 1:
                    unqueried_ref = (
                        fixture.public / ".git" / "refs" / "heads" / "unselected-control"
                    )
                    unqueried_ref.write_text(
                        fixture.expected_parent + "\n",
                        encoding="ascii",
                    )
                return state

            with mock.patch.object(
                public_handoff_check,
                "_git_state",
                side_effect=mutate_unqueried_ref,
            ):
                report = fixture.check(public_handoff_check.HandoffPhase.STAGED)
            self.assertIn(
                "public Git control metadata changed during handoff verification",
                _errors(report),
            )

    def test_public_handoff_rejects_authoring_control_aliases_and_cross_plane_links(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = _HandoffFixture(Path(temp_dir), object_format="sha1")
            authoring_alias = (
                fixture.authoring / ".git" / "refs" / "heads" / "public-alias"
            )
            authoring_alias.symlink_to(fixture.public / ".git" / "config")
            report = fixture.check(public_handoff_check.HandoffPhase.STAGED)
            self.assertIn(
                "authoring Git control metadata contains symlink entries",
                _errors(report),
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = _HandoffFixture(Path(temp_dir), object_format="sha1")
            public_ref = (
                fixture.public / ".git" / "refs" / "heads" / "unselected-control"
            )
            public_ref.write_text(fixture.expected_parent + "\n", encoding="ascii")
            nested_authoring_ref = (
                fixture.authoring
                / ".git"
                / "modules"
                / "nested"
                / "refs"
                / "heads"
                / "public-alias"
            )
            nested_authoring_ref.parent.mkdir(parents=True)
            os.link(public_ref, nested_authoring_ref)
            report = fixture.check(public_handoff_check.HandoffPhase.STAGED)
            self.assertIn(
                "public clone shares Git control files with authoring",
                _errors(report),
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = _HandoffFixture(Path(temp_dir), object_format="sha1")
            object_alias = fixture.authoring / ".git" / "objects" / "public-alias"
            object_alias.symlink_to(fixture.public / ".git" / "config")
            report = fixture.check(public_handoff_check.HandoffPhase.STAGED)
            self.assertIn(
                "authoring Git object store contains symlink entries",
                _errors(report),
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = _HandoffFixture(Path(temp_dir), object_format="sha1")
            public_ref = (
                fixture.public / ".git" / "refs" / "heads" / "unselected-control"
            )
            public_ref.write_text(fixture.expected_parent + "\n", encoding="ascii")
            authoring_object_alias = (
                fixture.authoring / ".git" / "objects" / "info" / "public-alias"
            )
            os.link(public_ref, authoring_object_alias)
            report = fixture.check(public_handoff_check.HandoffPhase.STAGED)
            self.assertIn(
                "public clone shares files across Git control metadata and authoring object storage",
                _errors(report),
            )

    def test_handoff_uses_the_bound_git_executable_not_ambient_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = _HandoffFixture(Path(temp_dir), object_format="sha1")
            fake_bin = fixture.root / "fake-bin"
            fake_bin.mkdir()
            marker = fixture.root / "ambient-git-ran"
            fake_git = fake_bin / "git"
            fake_git.write_text(
                "#!/bin/sh\nprintf 'ran\\n' > "
                + shlex.quote(str(marker))
                + "\nexit 99\n",
                encoding="utf-8",
            )
            fake_git.chmod(0o755)
            with mock.patch.dict(
                os.environ,
                {"PATH": str(fake_bin), "TMPDIR": str(fixture.authoring)},
                clear=False,
            ):
                report = fixture.check(public_handoff_check.HandoffPhase.STAGED)
            self.assertEqual([], _errors(report), report)
            self.assertFalse(marker.exists())
            self.assertEqual([], list(fixture.temporary.iterdir()))

    def test_handoff_accepts_one_inherited_git_descriptor_without_moving_its_offset(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = _HandoffFixture(Path(temp_dir), object_format="sha1")
            descriptor = os.open(_GIT_EXECUTABLE, os.O_RDONLY)
            expected_digest = hashlib.sha256(Path(_GIT_EXECUTABLE).read_bytes()).hexdigest()
            original_bounded_git = public_release_check._bounded_git_command
            child_bindings: list[tuple[int, tuple[int, ...]]] = []

            def record_bound_git(
                root: Path,
                command: list[str],
                **kwargs: object,
            ) -> tuple[int, bytes, bytes]:
                command_descriptor = int(PurePosixPath(command[0]).name)
                pass_fds = kwargs.get("pass_fds", ())
                if not isinstance(pass_fds, tuple):
                    raise TypeError("bounded Git pass_fds must be a tuple")
                child_bindings.append((command_descriptor, pass_fds))
                self.assertIn(command_descriptor, pass_fds)
                return original_bounded_git(root, command, **kwargs)  # type: ignore[arg-type]

            try:
                os.lseek(descriptor, 17, os.SEEK_SET)
                with mock.patch.object(
                    public_release_check,
                    "_bounded_git_command",
                    side_effect=record_bound_git,
                ):
                    report = fixture.check(
                        public_handoff_check.HandoffPhase.STAGED,
                        git_executable=None,
                        git_executable_fd=descriptor,
                    )
                self.assertEqual([], _errors(report), report)
                self.assertEqual(expected_digest, report["git_executable_sha256"])
                self.assertTrue(child_bindings)
                self.assertEqual(17, os.lseek(descriptor, 0, os.SEEK_CUR))
                os.fstat(descriptor)

                both = fixture.check(
                    public_handoff_check.HandoffPhase.STAGED,
                    git_executable_fd=descriptor,
                )
                self.assertIn(
                    "exactly one reviewed Git executable path or inherited descriptor is required",
                    _errors(both),
                )
                neither = fixture.check(
                    public_handoff_check.HandoffPhase.STAGED,
                    git_executable=None,
                )
                self.assertIn(
                    "exactly one reviewed Git executable path or inherited descriptor is required",
                    _errors(neither),
                )
            finally:
                os.close(descriptor)

    def test_closed_release_python_boundary_ignores_controls_and_preserves_git_fd(
        self,
    ) -> None:
        bash_executable = shutil.which("bash")
        uv_executable = shutil.which("uv")
        if (
            sys.platform != "linux"
            or not Path("/proc/self/fd").is_dir()
            or bash_executable is None
            or uv_executable is None
        ):
            self.skipTest("canonical handoff boundary requires Linux, procfs, Bash, and uv")

        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = _HandoffFixture(Path(temp_dir), object_format="sha1")
            poison = fixture.root / "python-poison"
            poison.mkdir()
            marker = fixture.root / "ambient-python-ran"
            (poison / "sitecustomize.py").write_text(
                "from pathlib import Path\n"
                f"Path({str(marker)!r}).write_text('ran\\n', encoding='utf-8')\n",
                encoding="utf-8",
            )
            python_executable = str(Path(sys.executable).resolve(strict=True))
            checker = fixture.export / "scripts" / "public_handoff_check.py"
            bash_source = r"""
set -euo pipefail
exec {release_env_fd}<"$1"
exec {release_uv_fd}<"$2"
exec {release_python_fd}<"$3"
exec {release_git_fd}<"$4"
release_env_command="/proc/self/fd/$release_env_fd"
release_uv_command="/proc/self/fd/$release_uv_fd"
release_python_command="/proc/$$/fd/$release_python_fd"
"$release_env_command" -i \
  "$release_uv_command" run \
  --no-project \
  --no-config \
  --no-env-file \
  --no-cache \
  --offline \
  --no-python-downloads \
  --python "$release_python_command" \
  python -I -S -B -X utf8 -c '
import runpy, subprocess, sys
probe = subprocess.run(
    [sys.executable, "-I", "-S", "-B", "-c", "print(\"nested-python-pass\")"],
    check=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
)
if probe.stdout != "nested-python-pass\n" or probe.stderr:
    raise SystemExit(
        "retained Python failed the nested-process probe: "
        f"stdout={probe.stdout!r} stderr={probe.stderr!r}"
    )
script = sys.argv[1]
script_dir, separator, _ = script.rpartition("/")
if not separator or not script_dir:
    raise SystemExit("handoff checker path must be absolute")
sys.path.insert(0, script_dir)
sys.argv = sys.argv[1:]
runpy.run_path(script, run_name="__main__")
' \
  "$5" \
  --git-executable-fd "$release_git_fd" \
  --phase staged \
  --export-root "$6" \
  --public-clone-root "$7" \
  --authoring-root "$8" \
  --temporary-root "$9" \
  --remote-name origin \
  --branch main \
  --expected-fetch-url "${10}" \
  --expected-push-url "${11}" \
  --expected-parent-commit "${12}"
"""
            result = run_bounded(
                [
                    _ENV_EXECUTABLE,
                    f"PYTHONPATH={poison}",
                    f"PYTHONHOME={poison}",
                    f"UV_PYTHON={poison / 'missing-python'}",
                    bash_executable,
                    "-c",
                    bash_source,
                    "release-boundary",
                    _ENV_EXECUTABLE,
                    uv_executable,
                    python_executable,
                    _GIT_EXECUTABLE,
                    str(checker),
                    str(fixture.export),
                    str(fixture.public),
                    str(fixture.authoring),
                    str(fixture.temporary),
                    fixture.remote_url,
                    fixture.remote_url,
                    fixture.expected_parent,
                ],
                cwd=fixture.root,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual([], _errors(report), report)
            self.assertFalse(marker.exists())
            self.assertEqual([], list(fixture.temporary.iterdir()))

            maintenance = (REPO_ROOT / "docs" / "maintenance_and_release.md").read_text(
                encoding="utf-8"
            )
            for required in (
                "public_release.py",
                "--python-executable",
                "--no-project --no-config --no-env-file --offline",
                "python -I -S -B",
            ):
                self.assertIn(required, maintenance)
            controller = (REPO_ROOT / "scripts" / "public_release.py").read_text(
                encoding="utf-8"
            )
            self.assertIn('f"/proc/{os.getpid()}/fd/{self.descriptor}"', controller)
            for required in (
                "tools.python.external_command",
                '"-I"',
                '"-S"',
                '"-B"',
                "_ISOLATED_SCRIPT_BOOTSTRAP",
            ):
                self.assertIn(required, controller)

    def test_public_handoff_rejects_linked_worktree_and_marker_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = _HandoffFixture(Path(temp_dir), object_format="sha1")
            linked = fixture.root / "linked-public"
            _git(fixture.public, "worktree", "add", "-q", "-b", "release-candidate", str(linked))
            _copy_export_payload(fixture.export, linked)
            report = fixture.check(
                public_handoff_check.HandoffPhase.STAGED,
                public_clone_root=linked,
                branch="release-candidate",
            )
            self.assertTrue(
                any("ordinary .git directory" in error for error in _errors(report))
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = _HandoffFixture(Path(temp_dir), object_format="sha1")
            marker = fixture.export / public_surface.PUBLIC_EXPORT_OWNERSHIP_MARKER
            marker.write_text("{}\n", encoding="utf-8")
            marker.chmod(public_release_check.PUBLIC_EXPORT_MARKER_MODE)
            report = fixture.check(public_handoff_check.HandoffPhase.STAGED)
            self.assertTrue(
                any("ownership validation failed" in error for error in _errors(report))
            )

    def test_committed_handoff_rejects_replacement_refs_and_uses_raw_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = _HandoffFixture(Path(temp_dir), object_format="sha1")
            good_candidate = fixture.commit_candidate()
            (fixture.public / "README.md").write_text(
                "raw candidate differs from export\n",
                encoding="utf-8",
            )
            _git(fixture.public, "add", "README.md")
            bad_tree = _git(fixture.public, "write-tree")
            bad_candidate = _commit_tree(
                fixture.public,
                bad_tree,
                message="raw mismatched candidate",
                parents=(fixture.expected_parent,),
            )
            _copy_export_payload(fixture.export, fixture.public)
            _git(fixture.public, "update-ref", "refs/heads/main", bad_candidate)
            _git(fixture.public, "replace", bad_candidate, good_candidate)

            report = fixture.check(public_handoff_check.HandoffPhase.COMMITTED)
            errors = _errors(report)
            self.assertIn("public clone contains forbidden Git replacement refs", errors)
            self.assertTrue(
                any("candidate commit tree" in error for error in errors),
                report,
            )
            self.assertEqual(bad_candidate, report["candidate_commit"])

    def test_committed_handoff_rejects_grafts_and_uses_raw_parents(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = _HandoffFixture(Path(temp_dir), object_format="sha1")
            tree = _git(fixture.public, "write-tree")
            parentless_candidate = _commit_tree(
                fixture.public,
                tree,
                message="raw parentless candidate",
            )
            _git(
                fixture.public,
                "update-ref",
                "refs/heads/main",
                parentless_candidate,
            )
            info = fixture.public / ".git" / "info"
            info.mkdir(exist_ok=True)
            (info / "grafts").write_text(
                f"{parentless_candidate} {fixture.expected_parent}\n",
                encoding="ascii",
            )
            _git(
                fixture.public,
                "config",
                "advice.graftFileDeprecated",
                "false",
            )

            report = fixture.check(public_handoff_check.HandoffPhase.COMMITTED)
            errors = _errors(report)
            self.assertIn("public clone contains a forbidden Git grafts file", errors)
            self.assertIn("candidate commit must have exactly one parent", errors)

    def test_handoff_accepts_absent_info_directory_but_rejects_other_types(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = _HandoffFixture(Path(temp_dir), object_format="sha1")
            info = fixture.public / ".git" / "info"
            shutil.rmtree(info)

            report = fixture.check(public_handoff_check.HandoffPhase.STAGED)
            self.assertEqual([], _errors(report), report)
            fixture.commit_candidate()
            self.assertFalse(info.exists())
            report = fixture.check(public_handoff_check.HandoffPhase.COMMITTED)
            self.assertEqual([], _errors(report), report)

        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = _HandoffFixture(Path(temp_dir), object_format="sha1")
            info = fixture.public / ".git" / "info"
            shutil.rmtree(info)
            info.write_text("not a directory\n", encoding="utf-8")

            report = fixture.check(public_handoff_check.HandoffPhase.STAGED)
            self.assertTrue(
                any(
                    "public handoff verification failed closed" in error
                    and "info" in error
                    for error in _errors(report)
                ),
                report,
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = _HandoffFixture(Path(temp_dir), object_format="sha1")
            info = fixture.public / ".git" / "info"
            shutil.rmtree(info)
            info.symlink_to(fixture.root / "missing-info-target")

            report = fixture.check(public_handoff_check.HandoffPhase.STAGED)
            self.assertIn(
                "public Git control metadata contains symlink entries",
                _errors(report),
            )

    def test_handoff_rejects_info_directory_created_during_verification(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = _HandoffFixture(Path(temp_dir), object_format="sha1")
            info = fixture.public / ".git" / "info"
            shutil.rmtree(info)
            original_snapshot = public_handoff_check._graft_info_snapshot
            snapshot_calls = 0

            def create_after_initial_snapshot(
                storage: public_handoff_check._GitStorageBinding,
                *,
                errors: list[str],
            ) -> tuple[object, ...] | None:
                nonlocal snapshot_calls
                snapshot = original_snapshot(storage, errors=errors)
                snapshot_calls += 1
                if snapshot_calls == 1:
                    info.mkdir()
                return snapshot

            with mock.patch.object(
                public_handoff_check,
                "_graft_info_snapshot",
                side_effect=create_after_initial_snapshot,
            ):
                report = fixture.check(public_handoff_check.HandoffPhase.STAGED)

            self.assertTrue(
                any(
                    "public handoff verification failed closed" in error
                    and "directory root changed" in error
                    for error in _errors(report)
                ),
                report,
            )

    def test_handoff_rejects_noncommit_branch_ref_and_missing_candidate_blobs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = _HandoffFixture(Path(temp_dir), object_format="sha1")
            _git(
                fixture.public,
                "-c",
                "user.name=Fixture",
                "-c",
                "user.email=fixture@example.invalid",
                "tag",
                "-a",
                "-m",
                "not a branch commit",
                "corrupt-branch-target",
                fixture.expected_parent,
            )
            tag_oid = _git(
                fixture.public,
                "rev-parse",
                "refs/tags/corrupt-branch-target",
            )
            branch_ref = fixture.public / ".git" / "refs" / "heads" / "main"
            branch_ref.parent.mkdir(parents=True, exist_ok=True)
            branch_ref.write_text(tag_oid + "\n", encoding="ascii")
            report = fixture.check(public_handoff_check.HandoffPhase.STAGED)
            self.assertTrue(
                any("directly identify a commit" in error for error in _errors(report)),
                report,
            )

        for phase in (
            public_handoff_check.HandoffPhase.STAGED,
            public_handoff_check.HandoffPhase.COMMITTED,
        ):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as temp_dir:
                fixture = _HandoffFixture(Path(temp_dir), object_format="sha1")
                if phase is public_handoff_check.HandoffPhase.COMMITTED:
                    fixture.commit_candidate()
                removed_oid = _remove_loose_blob(fixture.public, "README.md")
                report = fixture.check(phase)
                self.assertTrue(
                    any("candidate-blob inspection" in error for error in _errors(report)),
                    {"removed_oid": removed_oid, "report": report},
                )

    def test_handoff_rejects_url_credentials_and_unsafe_push_routing(self) -> None:
        embedded = "".join(
            (
                "https://",
                "user",
                ":",
                "credential-value",
                "@",
                "example.invalid/repository.git",
            )
        )
        provider_token = "".join(("gh", "p_", "A" * 24))
        token_userinfo = f"https://{provider_token}@example.invalid/repository.git"
        token_path = f"https://example.invalid/{provider_token}/repository.git"
        hostname_token = "".join(("gl", "pat-", "A" * 24))
        token_hostname = f"https://{hostname_token}.example.invalid/repository.git"
        username_userinfo = "https://user@example.invalid/repository.git"
        bearer_userinfo = (
            "https://Bearer%20" + "B" * 20 + "@example.invalid/repository.git"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = _HandoffFixture(Path(temp_dir), object_format="sha1")
            for credential_kind, credential_url in (
                ("password", embedded),
                ("http-username", username_userinfo),
                ("provider-token", token_userinfo),
                ("provider-token-path", token_path),
                ("provider-token-hostname", token_hostname),
                ("bearer", bearer_userinfo),
            ):
                with self.subTest(credential_url_kind=credential_kind):
                    report = fixture.check(
                        public_handoff_check.HandoffPhase.STAGED,
                        expected_fetch_url=credential_url,
                        expected_push_url=credential_url,
                    )
                    joined = "\n".join(_errors(report))
                    self.assertIn(
                        "expected fetch URL must not contain embedded credentials",
                        joined,
                    )
                    self.assertIn(
                        "expected push URL must not contain embedded credentials",
                        joined,
                    )
                    self.assertNotIn(credential_url, json.dumps(report, sort_keys=True))

        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = _HandoffFixture(Path(temp_dir), object_format="sha1")
            for ssh_url in (
                "git@example.invalid:public/repository.git",
                "ssh://git@example.invalid/public/repository.git",
            ):
                with self.subTest(ssh_url=ssh_url):
                    _git(fixture.public, "remote", "set-url", "origin", ssh_url)
                    report = fixture.check(
                        public_handoff_check.HandoffPhase.STAGED,
                        expected_fetch_url=ssh_url,
                        expected_push_url=ssh_url,
                    )
                    self.assertEqual([], _errors(report))

        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = _HandoffFixture(Path(temp_dir), object_format="sha1")
            for helper_url in (
                "ext::sh -c 'exit 0'",
                "mpaunknown://example.invalid/repository.git",
                "HTTPS://example.invalid/repository.git",
            ):
                with self.subTest(helper_url=helper_url):
                    report = fixture.check(
                        public_handoff_check.HandoffPhase.STAGED,
                        expected_fetch_url=helper_url,
                        expected_push_url=helper_url,
                    )
                    joined = "\n".join(_errors(report))
                    self.assertIn(
                        "expected fetch URL must not use an executable Git remote-helper URL form",
                        joined,
                    )
                    self.assertIn(
                        "expected push URL must not use an executable Git remote-helper URL form",
                        joined,
                    )

        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = _HandoffFixture(Path(temp_dir), object_format="sha1")
            for noncanonical_url in (
                "ssh://-oProxyCommand=touch%20x/repository.git",
                "ssh://host name/repository.git",
                "https://host name/repository.git",
                "ssh://example.invalid/%00repository.git",
            ):
                with self.subTest(noncanonical_url=noncanonical_url):
                    report = fixture.check(
                        public_handoff_check.HandoffPhase.STAGED,
                        expected_fetch_url=noncanonical_url,
                        expected_push_url=noncanonical_url,
                    )
                    self.assertTrue(_errors(report), report)
                    self.assertNotIn(
                        noncanonical_url,
                        json.dumps(report, sort_keys=True),
                    )

        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = _HandoffFixture(Path(temp_dir), object_format="sha1")
            temp_component = "t" + "mp"
            local_path = "/" + temp_component + "/repository.git"
            for unsupported_url in (
                "http://example.invalid/repository.git",
                "file://" + local_path,
                local_path,
            ):
                with self.subTest(unsupported_url=unsupported_url):
                    report = fixture.check(
                        public_handoff_check.HandoffPhase.STAGED,
                        expected_fetch_url=unsupported_url,
                        expected_push_url=unsupported_url,
                    )
                    joined = "\n".join(_errors(report))
                    self.assertIn(
                        "expected fetch URL must use a reviewed HTTPS, SSH URL, or scp-style SSH form",
                        joined,
                    )
                    self.assertIn(
                        "expected push URL must use a reviewed HTTPS, SSH URL, or scp-style SSH form",
                        joined,
                    )

        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = _HandoffFixture(Path(temp_dir), object_format="sha1")
            _git(fixture.public, "remote", "set-url", "origin", embedded)
            report = fixture.check(public_handoff_check.HandoffPhase.STAGED)
            joined = "\n".join(_errors(report))
            self.assertIn("fetch URL contains embedded credentials", joined)
            self.assertIn("push URL contains embedded credentials", joined)
            self.assertNotIn(embedded, json.dumps(report, sort_keys=True))

        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = _HandoffFixture(Path(temp_dir), object_format="sha1")
            _git(
                fixture.public,
                "branch",
                "private-not-for-public",
                fixture.expected_parent,
            )
            control = fixture.check(public_handoff_check.HandoffPhase.STAGED)
            self.assertEqual([], _errors(control))
            for key, value in (
                ("branch.main.pushRemote", "origin"),
                ("remote.pushDefault", "origin"),
                ("remote.origin.push", "refs/heads/*:refs/heads/*"),
                ("remote.origin.mirror", "true"),
                ("push.default", "matching"),
                ("push.followTags", "true"),
            ):
                _git(fixture.public, "config", "--add", key, value)
            report = fixture.check(public_handoff_check.HandoffPhase.STAGED)
            joined = "\n".join(_errors(report))
            for expected in (
                "branch pushRemote must be unset",
                "remote.pushDefault must be unset",
                "must not configure default push refspecs",
                "must not enable mirror publication",
                "push.default configuration can broaden publication",
                "must not enable automatic tag publication",
            ):
                self.assertIn(expected, joined)

        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = _HandoffFixture(Path(temp_dir), object_format="sha1")
            redirect = fixture.root / "local-routing-target.git"
            _git(fixture.root, "init", "--bare", "-q", str(redirect))
            _git(
                fixture.public,
                "config",
                f"url.{redirect}.pushInsteadOf",
                fixture.remote_url,
            )
            report = fixture.check(public_handoff_check.HandoffPhase.STAGED)
            self.assertIn(
                "public clone does not have exactly the expected push URL",
                _errors(report),
            )

    def test_handoff_rejects_clone_local_transport_and_push_side_effect_controls(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = _HandoffFixture(Path(temp_dir), object_format="sha1")
            _git(
                fixture.public,
                "remote",
                "set-url",
                "origin",
                fixture.transport_url,
            )
            marker = fixture.root / "configured-receivepack-ran"
            wrapper = fixture.root / "configured-receivepack"
            receive_pack = _required_executable("git-receive-pack")
            wrapper.write_text(
                "#!/bin/sh\nprintf 'ran\\n' > "
                + shlex.quote(str(marker))
                + "\nexec "
                + shlex.quote(receive_pack)
                + " \"$@\"\n",
                encoding="utf-8",
            )
            wrapper.chmod(0o755)
            _git(
                fixture.public,
                "config",
                "remote.origin.receivepack",
                str(wrapper),
            )
            _git(
                fixture.public,
                "push",
                "origin",
                f"{fixture.expected_parent}:refs/heads/unsafe-wrapper-control",
            )
            self.assertTrue(marker.is_file())
            _git(
                fixture.public,
                "remote",
                "set-url",
                "origin",
                fixture.remote_url,
            )

            for key, value in (
                ("remote.origin.vcs", "ext"),
                ("remote.origin.proxy", "http://127.0.0.1:9"),
                ("core.sshCommand", str(wrapper)),
                ("core.askPass", str(wrapper)),
                ("core.attributesFile", str(fixture.root / "attributes")),
                ("core.gitProxy", str(wrapper)),
                ("core.hooksPath", str(fixture.root / "hooks")),
                ("core.whitespace", "-trailing-space"),
                ("push.gpgSign", "true"),
                ("push.pushOption", "unexpected-option"),
            ):
                _git(fixture.public, "config", "--add", key, value)
            report = fixture.check(public_handoff_check.HandoffPhase.STAGED)
            joined = "\n".join(_errors(report))
            for expected in (
                "selected remote receivepack must be unset",
                "selected remote VCS helper must be unset",
                "selected remote proxy must be unset",
                "core.sshCommand must be unset",
                "core.askPass must be unset",
                "core.attributesFile must be unset",
                "core.gitProxy must be unset",
                "core.hooksPath must be unset",
                "core.whitespace must be unset",
                "must not enable or conditionally request signed pushes",
                "must not configure default push options",
            ):
                self.assertIn(expected, joined)

        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = _HandoffFixture(Path(temp_dir), object_format="sha1")
            https_url = "https://example.invalid/public-framework.git"
            _git(fixture.public, "remote", "set-url", "origin", https_url)
            _git(
                fixture.public,
                "config",
                "http.proxy",
                "http://127.0.0.1:9",
            )
            report = fixture.check(
                public_handoff_check.HandoffPhase.STAGED,
                expected_fetch_url=https_url,
                expected_push_url=https_url,
            )
            self.assertIn(
                "public clone must not configure an effective HTTP proxy",
                _errors(report),
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = _HandoffFixture(Path(temp_dir), object_format="sha1")
            for key, value in (
                ("http.curloptResolve", "+example.invalid:443:127.0.0.1"),
                ("http.sslVerify", "false"),
                ("http.extraHeader", "X-Review: configured"),
                ("http.cookieFile", str(fixture.root / "cookies.txt")),
            ):
                _git(fixture.public, "config", "--add", key, value)
            report = fixture.check(public_handoff_check.HandoffPhase.STAGED)
            self.assertIn(
                "public clone must not contain effective HTTP transport configuration",
                _errors(report),
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = _HandoffFixture(Path(temp_dir), object_format="sha1")
            _git(
                fixture.public,
                "config",
                "extensions.worktreeConfig",
                "true",
            )
            _git(
                fixture.public,
                "config",
                "--worktree",
                "http.curloptResolve",
                "+example.invalid:443:127.0.0.1",
            )
            report = fixture.check(public_handoff_check.HandoffPhase.STAGED)
            self.assertIn(
                "public clone must not contain effective HTTP transport configuration",
                _errors(report),
            )

    def test_documented_diff_boundary_clears_git_environment_and_binds_clone(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = _HandoffFixture(Path(temp_dir), object_format="sha1")
            readme = fixture.public / "README.md"
            readme.write_text("staged trailing whitespace  \n", encoding="utf-8")
            _git(fixture.public, "add", "README.md")
            poisoned = dict(os.environ)
            poisoned.update(
                {
                    "GIT_CONFIG_PARAMETERS": "'core.abbrev=7'",
                    "GIT_DIR": str(fixture.authoring / ".git"),
                    "GIT_WORK_TREE": str(fixture.authoring),
                }
            )
            with mock.patch.dict(os.environ, poisoned, clear=True):
                result = _release_git(
                    fixture.root,
                    "--no-optional-locks",
                    "-c",
                    "core.attributesFile=/dev/null",
                    "-c",
                    "core.whitespace=blank-at-eol,blank-at-eof,space-before-tab",
                    "-C",
                    str(fixture.public),
                    "diff",
                    "--cached",
                    "--check",
                    check=False,
                )
            self.assertNotEqual(0, result.returncode)
            self.assertIn("README.md", result.stdout)

            info_attributes = fixture.public / ".git" / "info" / "attributes"
            info_attributes.write_text("README.md binary\n", encoding="utf-8")
            report = fixture.check(public_handoff_check.HandoffPhase.STAGED)
            self.assertIn(
                "public clone contains a forbidden Git info/attributes entry",
                _errors(report),
            )

    def test_documented_push_boundary_clears_git_environment_and_bypasses_hook(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = _HandoffFixture(Path(temp_dir), object_format="sha1")
            _git(
                fixture.public,
                "remote",
                "set-url",
                "origin",
                fixture.transport_url,
            )
            redirect = fixture.root / "global-routing-target.git"
            _git(fixture.root, "init", "--bare", "-q", str(redirect))
            injected_redirect = fixture.root / "injected-routing-target.git"
            _git(
                fixture.root,
                "init",
                "--bare",
                "-q",
                str(injected_redirect),
            )
            global_config = fixture.root / "temporary-global-gitconfig"
            _git(
                fixture.root,
                "config",
                "--file",
                str(global_config),
                f"url.{redirect}.pushInsteadOf",
                fixture.transport_url,
            )
            hook_marker = fixture.root / "pre-push-ran"
            hook = fixture.public / ".git" / "hooks" / "pre-push"
            hook.write_text(
                "#!/bin/sh\nprintf 'ran\\n' > "
                + shlex.quote(str(hook_marker))
                + "\n",
                encoding="utf-8",
            )
            hook.chmod(0o755)
            candidate = fixture.commit_candidate()

            ambient = dict(os.environ)
            ambient["GIT_CONFIG_GLOBAL"] = str(global_config)
            ambient.pop("GIT_CONFIG_NOSYSTEM", None)
            ambient.pop("GIT_CONFIG_COUNT", None)
            with mock.patch.dict(os.environ, ambient, clear=True):
                _git(
                    fixture.public,
                    "push",
                    "origin",
                    f"{candidate}:refs/heads/ambient-control",
                )
            self.assertTrue(hook_marker.is_file())
            self.assertEqual(
                candidate,
                _git(redirect, "rev-parse", "refs/heads/ambient-control"),
            )
            self.assertNotEqual(
                0,
                run_bounded(
                    ["git", "rev-parse", "--verify", "refs/heads/ambient-control"],
                    cwd=fixture.remote,
                ).returncode,
            )

            hook_marker.unlink()
            poisoned = dict(ambient)
            poisoned.update(
                {
                    "GIT_CONFIG_PARAMETERS": "'core.abbrev=7'",
                    "GIT_DIR": str(fixture.authoring / ".git"),
                    "GIT_WORK_TREE": str(fixture.authoring),
                    "GIT_CONFIG_COUNT": "1",
                    "GIT_CONFIG_KEY_0": (
                        f"url.{injected_redirect}.pushInsteadOf"
                    ),
                    "GIT_CONFIG_VALUE_0": fixture.transport_url,
                }
            )
            with mock.patch.dict(os.environ, poisoned, clear=True):
                _release_git(
                    fixture.root,
                    "-c",
                    "credential.helper=",
                    "-c",
                    "core.hooksPath=/dev/null",
                    "-c",
                    "hook.pre-push.enabled=false",
                    "-c",
                    "hook.reference-transaction.enabled=false",
                    "-C",
                    str(fixture.public),
                    "push",
                    "--receive-pack=git-receive-pack",
                    "--no-verify",
                    "--no-follow-tags",
                    "--no-tags",
                    "--no-recurse-submodules",
                    "--no-mirror",
                    "--no-signed",
                    "--no-push-option",
                    "origin",
                    f"{candidate}:refs/heads/release-safe",
                )
            self.assertFalse(hook_marker.exists())
            self.assertEqual(
                candidate,
                _git(fixture.remote, "rev-parse", "refs/heads/release-safe"),
            )
            self.assertNotEqual(
                0,
                run_bounded(
                    ["git", "rev-parse", "--verify", "refs/heads/release-safe"],
                    cwd=redirect,
                ).returncode,
            )
            self.assertNotEqual(
                0,
                run_bounded(
                    ["git", "rev-parse", "--verify", "refs/heads/release-safe"],
                    cwd=injected_redirect,
                ).returncode,
            )

            _release_git(
                fixture.public,
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "hook.reference-transaction.enabled=false",
                "-c",
                "tag.gpgSign=false",
                "-c",
                "user.name=Fixture",
                "-c",
                "user.email=fixture@example.invalid",
                "-C",
                str(fixture.public),
                "tag",
                "--annotate",
                "--no-sign",
                "--message",
                "release tag",
                "--",
                "v-test",
                candidate,
            )
            _git(
                fixture.public,
                "remote",
                "set-url",
                "origin",
                fixture.remote_url,
            )
            tag_report = fixture.check(
                public_handoff_check.HandoffPhase.COMMITTED,
                tag_ref="refs/tags/v-test",
            )
            self.assertEqual([], _errors(tag_report), tag_report)
            tag_oid = tag_report["tag_oid"]
            self.assertIsInstance(tag_oid, str)
            _git(
                fixture.public,
                "remote",
                "set-url",
                "origin",
                fixture.transport_url,
            )
            with mock.patch.dict(os.environ, poisoned, clear=True):
                _release_git(
                    fixture.root,
                    "-c",
                    "credential.helper=",
                    "-c",
                    "core.hooksPath=/dev/null",
                    "-c",
                    "hook.pre-push.enabled=false",
                    "-c",
                    "hook.reference-transaction.enabled=false",
                    "-C",
                    str(fixture.public),
                    "push",
                    "--atomic",
                    "--receive-pack=git-receive-pack",
                    "--no-verify",
                    "--no-follow-tags",
                    "--no-tags",
                    "--no-recurse-submodules",
                    "--no-mirror",
                    "--no-signed",
                    "--no-push-option",
                    "origin",
                    f"{candidate}:refs/heads/main",
                    f"{tag_oid}:refs/tags/v-test",
                )
            self.assertFalse(hook_marker.exists())
            self.assertEqual(
                tag_oid,
                _git(fixture.remote, "rev-parse", "refs/tags/v-test"),
            )
            self.assertEqual(
                candidate,
                _git(fixture.remote, "rev-parse", "refs/heads/main"),
            )
            for unintended in (redirect, injected_redirect):
                self.assertNotEqual(
                    0,
                    run_bounded(
                        ["git", "rev-parse", "--verify", "refs/tags/v-test"],
                        cwd=unintended,
                    ).returncode,
                )

    def test_handoff_closes_git_inventory_when_index_validation_cannot_start(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = _HandoffFixture(Path(temp_dir), object_format="sha1")
            (fixture.public / ".git" / "index").unlink()
            closed: list[public_release_check._GitInventoryBinding] = []
            original_close = public_release_check._GitInventoryBinding.close

            def record_close(binding: public_release_check._GitInventoryBinding) -> None:
                closed.append(binding)
                original_close(binding)

            with mock.patch.object(
                public_release_check._GitInventoryBinding,
                "close",
                record_close,
            ):
                report = fixture.check(public_handoff_check.HandoffPhase.STAGED)
            self.assertTrue(
                any("nonempty Git index" in error for error in _errors(report)),
                report,
            )
            self.assertEqual(1, len(closed))
            self.assertTrue(closed[0]._closed)

    def test_public_handoff_detects_terminal_ref_or_configuration_change(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = _HandoffFixture(Path(temp_dir), object_format="sha1")
            original = public_handoff_check._git_state
            calls: list[int] = []

            def mutate_after_initial(*args: object, **kwargs: object) -> object:
                state = original(*args, **kwargs)  # type: ignore[arg-type]
                calls.append(1)
                if len(calls) == 1:
                    _git(
                        fixture.public,
                        "config",
                        "branch.main.pushRemote",
                        "unexpected",
                    )
                return state

            with mock.patch.object(
                public_handoff_check,
                "_git_state",
                side_effect=mutate_after_initial,
            ):
                report = fixture.check(public_handoff_check.HandoffPhase.STAGED)
            self.assertTrue(
                any("changed" in error for error in _errors(report)),
                report,
            )

    def test_public_handoff_cli_uses_canonical_json_and_exit_two_for_bad_input(self) -> None:
        result = run_bounded(
            [sys.executable, "-B", "scripts/public_handoff_check.py"],
            cwd=REPO_ROOT,
        )
        self.assertEqual(2, result.returncode)
        self.assertEqual("", result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            result.stdout,
        )
        self.assertTrue(payload["errors"])

        nonexistent_home = "~mpa-user-that-does-not-exist/export"
        path_result = run_bounded(
            [
                sys.executable,
                "-B",
                "scripts/public_handoff_check.py",
                "--phase",
                "staged",
                "--export-root",
                nonexistent_home,
                "--public-clone-root",
                str(REPO_ROOT),
                "--authoring-root",
                str(REPO_ROOT),
                "--git-executable",
                _GIT_EXECUTABLE,
                "--temporary-root",
                str(REPO_ROOT),
                "--remote-name",
                "origin",
                "--branch",
                "main",
                "--expected-fetch-url",
                "https://example.invalid/repository.git",
                "--expected-push-url",
                "https://example.invalid/repository.git",
                "--expected-parent-commit",
                "0" * 40,
            ],
            cwd=REPO_ROOT,
        )
        self.assertEqual(2, path_result.returncode)
        self.assertEqual("", path_result.stderr)
        self.assertIn(
            "public export root must use an absolute path",
            json.loads(path_result.stdout)["errors"],
        )

    def test_argument_validation_rejects_noncanonical_git_identifiers(self) -> None:
        common = {
            "phase": public_handoff_check.HandoffPhase.STAGED,
            "remote_name": "origin",
            "branch": "main",
            "expected_fetch_url": "https://example.invalid/repository.git",
            "expected_push_url": "https://example.invalid/repository.git",
            "expected_parent_commit": "0" * 40,
            "tag_ref": None,
        }
        for branch in ("HEAD", "foo/.bar", "foo.lock/bar"):
            with self.subTest(branch=branch):
                errors = public_handoff_check._cli_validation_errors(
                    **{**common, "branch": branch},
                )
                self.assertIn(
                    "branch must be a canonical bounded Git branch name",
                    errors,
                )
        for remote_name in ("origin..mirror", "origin.lock"):
            with self.subTest(remote_name=remote_name):
                errors = public_handoff_check._cli_validation_errors(
                    **{**common, "remote_name": remote_name},
                )
                self.assertIn(
                    "remote name must use a bounded simple Git remote spelling",
                    errors,
                )

    def test_handoff_reports_linux_container_requirement_before_inspection(self) -> None:
        with mock.patch.object(public_handoff_check.sys, "platform", "darwin"):
            report = public_handoff_check.check_public_handoff(
                phase=public_handoff_check.HandoffPhase.STAGED,
                export_root=Path("/unopened-export"),
                public_clone_root=Path("/unopened-clone"),
                authoring_root=Path("/unopened-authoring"),
                git_executable=Path("/unopened-git"),
                temporary_root=Path("/unopened-temporary"),
                remote_name="origin",
                branch="main",
                expected_fetch_url="https://example.invalid/repository.git",
                expected_push_url="https://example.invalid/repository.git",
                expected_parent_commit="0" * 40,
            )

        self.assertEqual(
            [
                "public handoff verification requires the qualified Linux container boundary"
            ],
            _errors(report),
        )


if __name__ == "__main__":
    unittest.main()
