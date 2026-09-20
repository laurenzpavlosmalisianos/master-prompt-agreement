"""Evidence-scope selection validation tests."""

from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path
import shlex
import tempfile
import unittest
from typing import cast
from unittest import mock

from tests.validation_test_support import (
    SCRIPTS_DIR as _SCRIPTS_DIR,
    run_bounded,
)

import evidence_scope  # noqa: E402
import recommend_stack  # noqa: E402


class EvidenceScopeTests(unittest.TestCase):
    def test_evidence_scope_rejects_abbreviated_long_options(self) -> None:
        parser = evidence_scope.build_parser()
        with (
            mock.patch("sys.stderr", new_callable=io.StringIO) as stderr,
            self.assertRaises(SystemExit) as raised,
        ):
            parser.parse_args(["--impact-revie", "--path", "README.md"])

        self.assertEqual(2, raised.exception.code)
        self.assertIn("unrecognized arguments: --impact-revie", stderr.getvalue())

    def test_evidence_scope_rejects_option_like_diff_base(self) -> None:
        with self.assertRaises(SystemExit):
            evidence_scope.validate_diff_base("--output=/tmp/out")

    def test_evidence_scope_validates_explicit_paths_against_selected_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "docs").mkdir()
            (root / "docs" / "safe.md").write_text("safe\n", encoding="utf-8")
            self.assertEqual(
                ["docs/safe.md"],
                evidence_scope.validate_paths(["docs/safe.md"], root),
            )
            absolute_temp = "/" + "tmp" + "/escape.md"
            windows_temp = "C:" + "\\" + "tmp" + "\\" + "x"
            for unsafe in ("../escape.md", absolute_temp, "https://example.com/x", windows_temp):
                with self.subTest(unsafe=unsafe), self.assertRaises(SystemExit):
                    evidence_scope.validate_paths([unsafe], root)

    def test_evidence_scope_rejects_symlinked_path_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, tempfile.TemporaryDirectory() as outside_dir:
            root = Path(temp_dir)
            (root / "linked").symlink_to(Path(outside_dir), target_is_directory=True)
            for unsafe in ("linked", "linked/evidence.md"):
                with self.subTest(unsafe=unsafe), self.assertRaises(SystemExit):
                    evidence_scope.validate_paths([unsafe], root)

    def test_git_evidence_path_route_preserves_lexical_rejections(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            root_descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                for unsafe in (
                    "../escape.md",
                    str(root / "escape.md"),
                    "https://example.invalid/evidence",
                    "docs/line\nbreak.md",
                    "C:" + "\\" + "temp" + "\\" + "escape.md",
                ):
                    with (
                        self.subTest(unsafe=unsafe),
                        self.assertRaises(SystemExit),
                    ):
                        evidence_scope.validate_git_paths(
                            [unsafe],
                            root_descriptor,
                        )
            finally:
                os.close(root_descriptor)

    def test_evidence_scope_consumer_query_is_literal_and_option_safe(self) -> None:
        summary = evidence_scope.classify_path("docs/alpha beta;$(x).md")
        self.assertEqual("rg -n -F -- 'alpha beta;$(x)' .", summary["consumer_query"])

    def test_evidence_scope_impact_review_alone_widens_to_feature_slice(self) -> None:
        parser = evidence_scope.build_parser()
        args = parser.parse_args(["--impact-review", "--path", "README.md"])
        care = recommend_stack.choose_standard_of_care(args)
        base = recommend_stack.choose_evidentiary_scope(args, care)
        recommended, reasons = evidence_scope.escalate_scope(base, [], impact_review=args.impact_review)

        self.assertEqual("feature-slice", recommended)
        self.assertTrue(any("Impact review" in reason for reason in reasons))

    def test_evidence_scope_diff_base_includes_untracked_files_from_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_bounded(["git", "init", "-q"], cwd=root, check=True)
            tracked = root / "tracked.md"
            tracked.write_text("baseline\n", encoding="utf-8")
            run_bounded(["git", "add", "tracked.md"], cwd=root, check=True)
            run_bounded(
                [
                    "git",
                    "-c",
                    "user.name=Framework Test",
                    "-c",
                    "user.email=framework@example.invalid",
                    "commit",
                    "-qm",
                    "baseline",
                ],
                cwd=root,
                check=True,
            )
            tracked.write_text("changed\n", encoding="utf-8")
            (root / "untracked.md").write_text("new\n", encoding="utf-8")
            parser = evidence_scope.build_parser()
            args = parser.parse_args(["--diff-base", "HEAD", "--root", str(root)])

            self.assertEqual(
                ["tracked.md", "untracked.md"],
                evidence_scope.collect_paths(args, evidence_scope.validate_root(args.root)),
            )

    def test_evidence_scope_diff_base_reports_changed_tracked_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_bounded(["git", "init", "-q"], cwd=root, check=True)
            tracked_link = root / "tracked-link"
            tracked_link.symlink_to("first-missing-target")
            run_bounded(["git", "add", "tracked-link"], cwd=root, check=True)
            run_bounded(
                [
                    "git",
                    "-c",
                    "user.name=Framework Test",
                    "-c",
                    "user.email=framework@example.invalid",
                    "commit",
                    "-qm",
                    "baseline",
                ],
                cwd=root,
                check=True,
            )
            tracked_link.unlink()
            tracked_link.symlink_to("second-missing-target")
            args = evidence_scope.build_parser().parse_args(
                ["--diff-base", "HEAD", "--root", str(root)]
            )

            self.assertEqual(
                ["tracked-link"],
                evidence_scope.collect_paths(
                    args,
                    evidence_scope.validate_root(args.root),
                ),
            )

    def test_evidence_scope_diff_base_reports_untracked_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_bounded(["git", "init", "-q"], cwd=root, check=True)
            (root / "baseline.md").write_text("baseline\n", encoding="utf-8")
            run_bounded(["git", "add", "baseline.md"], cwd=root, check=True)
            run_bounded(
                [
                    "git",
                    "-c",
                    "user.name=Framework Test",
                    "-c",
                    "user.email=framework@example.invalid",
                    "commit",
                    "-qm",
                    "baseline",
                ],
                cwd=root,
                check=True,
            )
            (root / "untracked-link").symlink_to("../outside-repository")
            args = evidence_scope.build_parser().parse_args(
                ["--diff-base", "HEAD", "--root", str(root)]
            )

            self.assertEqual(
                ["untracked-link"],
                evidence_scope.collect_paths(
                    args,
                    evidence_scope.validate_root(args.root),
                ),
            )

    def test_evidence_scope_diff_base_rejects_symlink_ancestor(self) -> None:
        with (
            tempfile.TemporaryDirectory() as temp_dir,
            tempfile.TemporaryDirectory() as outside_dir,
        ):
            root = Path(temp_dir)
            nested = root / "nested"
            nested.mkdir()
            tracked = nested / "tracked.md"
            tracked.write_text("baseline\n", encoding="utf-8")
            run_bounded(["git", "init", "-q"], cwd=root, check=True)
            run_bounded(["git", "add", "nested/tracked.md"], cwd=root, check=True)
            run_bounded(
                [
                    "git",
                    "-c",
                    "user.name=Framework Test",
                    "-c",
                    "user.email=framework@example.invalid",
                    "commit",
                    "-qm",
                    "baseline",
                ],
                cwd=root,
                check=True,
            )
            tracked.unlink()
            nested.rmdir()
            outside = Path(outside_dir)
            (outside / "tracked.md").write_text("replacement\n", encoding="utf-8")
            nested.symlink_to(outside, target_is_directory=True)
            args = evidence_scope.build_parser().parse_args(
                ["--diff-base", "HEAD", "--root", str(root)]
            )

            with self.assertRaisesRegex(SystemExit, "symlink ancestors"):
                evidence_scope.collect_paths(
                    args,
                    evidence_scope.validate_root(args.root),
                )

    def test_evidence_scope_does_not_execute_repository_fsmonitor(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir)
            root = fixture / "repo"
            root.mkdir()
            run_bounded(["git", "init", "-q"], cwd=root, check=True)
            tracked = root / "tracked.md"
            tracked.write_text("baseline\n", encoding="utf-8")
            run_bounded(["git", "add", "tracked.md"], cwd=root, check=True)
            run_bounded(
                [
                    "git",
                    "-c",
                    "user.name=Framework Test",
                    "-c",
                    "user.email=framework@example.invalid",
                    "commit",
                    "-qm",
                    "baseline",
                ],
                cwd=root,
                check=True,
            )
            marker = fixture / "fsmonitor-executed"
            monitor = fixture / "fsmonitor.sh"
            monitor.write_text(
                "#!/bin/sh\nprintf executed > " + shlex.quote(str(marker)) + "\n",
                encoding="utf-8",
            )
            monitor.chmod(0o700)
            run_bounded(
                ["git", "config", "core.fsmonitor", str(monitor)],
                cwd=root,
                check=True,
            )
            outside_worktree = fixture / "outside-worktree"
            outside_worktree.mkdir()
            (outside_worktree / "outside-only.md").write_text(
                "outside\n",
                encoding="utf-8",
            )
            run_bounded(
                ["git", "config", "core.worktree", str(outside_worktree)],
                cwd=root,
                check=True,
            )
            tracked.write_text("changed\n", encoding="utf-8")
            (root / "untracked.md").write_text("untracked\n", encoding="utf-8")
            args = evidence_scope.build_parser().parse_args(
                ["--diff-base", "HEAD", "--root", str(root)]
            )

            self.assertEqual(
                ["tracked.md", "untracked.md"],
                evidence_scope.collect_paths(args, evidence_scope.validate_root(args.root)),
            )
            self.assertFalse(marker.exists())

    def test_git_query_rejects_unmaintained_or_unbounded_shapes(self) -> None:
        for arguments in (
            ["status", "--short"],
            ["diff", "--name-only", "-z", "HEAD", "--"],
            [
                "diff",
                "--no-ext-diff",
                "--no-textconv",
                "--name-only",
                "-z",
                "HEAD",
                "--",
            ],
            ["cat-file", "--batch"],
            ["check-ignore", "--", "unregistered/raw"],
        ):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                evidence_scope.git_query.closed_git_query_command(arguments)

    def test_git_query_ignores_ambient_path_and_requires_qualified_override(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            poison = Path(temp_dir)
            root = poison / "repo"
            root.mkdir()
            run_bounded(["git", "init", "-q"], cwd=root, check=True)
            fake_git = poison / "git"
            fake_git.write_text("#!/bin/sh\nexit 97\n", encoding="utf-8")
            fake_git.chmod(0o700)
            fake_git_path = fake_git.resolve(strict=True)
            with mock.patch.dict(
                os.environ,
                {
                    "PATH": str(poison),
                    "GIT_ALTERNATE_OBJECT_DIRECTORIES": str(poison),
                    "GIT_NAMESPACE": "foreign",
                    "GIT_OBJECT_DIRECTORY": str(poison),
                    "GIT_REPLACE_REF_BASE": "refs/foreign/",
                    "GIT_SHALLOW_FILE": str(poison / "shallow"),
                },
            ):
                command = evidence_scope.git_query.closed_git_query_command(
                    ["ls-files", "--others", "-z", "--"]
                )
                with evidence_scope.git_query.bind_git_repository(root) as binding:
                    environment = (
                        evidence_scope.git_query.closed_git_query_environment(binding)
                    )

        self.assertTrue(Path(command[0]).is_absolute())
        self.assertNotEqual(fake_git_path, Path(command[0]))
        self.assertEqual("--no-lazy-fetch", command[1])
        self.assertIn("core.fsmonitor=false", command)
        self.assertEqual(os.defpath, environment["PATH"])
        self.assertIn("/fd/", environment["GIT_OBJECT_DIRECTORY"])
        for forbidden in (
            "GIT_ALTERNATE_OBJECT_DIRECTORIES",
            "GIT_NAMESPACE",
            "GIT_REPLACE_REF_BASE",
            "GIT_SHALLOW_FILE",
        ):
            self.assertNotIn(forbidden, environment)
        with self.assertRaisesRegex(ValueError, "must be an absolute path"):
            evidence_scope.git_query.closed_git_query_command(
                ["ls-files", "--others", "-z", "--"],
                executable="git",
            )

    def test_evidence_scope_does_not_execute_ambient_path_git(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "repo"
            poison = base / "poison"
            root.mkdir()
            poison.mkdir()
            run_bounded(["git", "init", "-q"], cwd=root, check=True)
            (root / "untracked.md").write_text("new\n", encoding="utf-8")
            marker = base / "poison-git-executed"
            fake_git = poison / "git"
            fake_git.write_text(
                "#!/bin/sh\nprintf executed > "
                + shlex.quote(str(marker))
                + "\nexit 97\n",
                encoding="utf-8",
            )
            fake_git.chmod(0o700)

            with mock.patch.dict(os.environ, {"PATH": str(poison)}):
                paths = evidence_scope.run_git(
                    ["ls-files", "--others", "--exclude-standard", "-z", "--"],
                    root,
                )

        self.assertEqual(["untracked.md"], paths)
        self.assertFalse(marker.exists())

    def test_git_query_does_not_discover_an_enclosing_repository(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            outer = Path(temp_dir) / "outer:with-colon"
            selected = outer / "selected"
            selected.mkdir(parents=True)
            run_bounded(["git", "init", "-q"], cwd=outer, check=True)
            (outer / "outer-only.md").write_text("outer\n", encoding="utf-8")
            run_bounded(["git", "add", "outer-only.md"], cwd=outer, check=True)
            (selected / "selected-only.md").write_text(
                "selected\n",
                encoding="utf-8",
            )

            with (
                mock.patch.object(
                    evidence_scope.bounded_subprocess,
                    "run_bounded_process",
                ) as run,
                self.assertRaisesRegex(SystemExit, "no direct \\.git metadata entry"),
            ):
                evidence_scope._bounded_git(
                    ["ls-files", "--others", "-z", "--"],
                    selected,
                )
            run.assert_not_called()

    def test_git_query_rejects_foreign_git_metadata_before_spawn(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir)
            foreign = fixture / "foreign"
            foreign.mkdir()
            run_bounded(["git", "init", "-q"], cwd=foreign, check=True)

            cases = ("symlink", "gitfile", "special")
            for case in cases:
                with self.subTest(case=case):
                    selected = fixture / f"selected-{case}"
                    selected.mkdir()
                    if case == "symlink":
                        (selected / ".git").symlink_to(
                            foreign / ".git",
                            target_is_directory=True,
                        )
                    elif case == "gitfile":
                        (selected / ".git").write_text(
                            f"gitdir: {foreign / '.git'}\n",
                            encoding="utf-8",
                        )
                    else:
                        os.mkfifo(selected / ".git")
                    with (
                        mock.patch.object(
                            evidence_scope.bounded_subprocess,
                            "run_bounded_process",
                        ) as run,
                        self.assertRaisesRegex(
                            SystemExit,
                            "Git repository boundary rejected query",
                        ),
                    ):
                        evidence_scope._bounded_git(
                            ["ls-files", "--others", "-z", "--"],
                            selected,
                        )
                    run.assert_not_called()

    def test_git_query_supports_a_selected_linked_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir)
            primary = fixture / "primary"
            linked = fixture / "linked"
            primary.mkdir()
            run_bounded(["git", "init", "-q"], cwd=primary, check=True)
            (primary / "tracked.md").write_text("baseline\n", encoding="utf-8")
            run_bounded(["git", "add", "tracked.md"], cwd=primary, check=True)
            run_bounded(
                [
                    "git",
                    "-c",
                    "user.name=Framework Test",
                    "-c",
                    "user.email=framework@example.invalid",
                    "commit",
                    "-qm",
                    "baseline",
                ],
                cwd=primary,
                check=True,
            )
            run_bounded(
                ["git", "worktree", "add", "-q", "--detach", str(linked), "HEAD"],
                cwd=primary,
                check=True,
            )
            (linked / "tracked.md").write_text("changed\n", encoding="utf-8")
            args = evidence_scope.build_parser().parse_args(
                ["--diff-base", "HEAD", "--root", str(linked)]
            )

            self.assertEqual(
                ["tracked.md"],
                evidence_scope.collect_paths(
                    args,
                    evidence_scope.validate_root(args.root),
                ),
            )

            gitdir_text = (linked / ".git").read_text(encoding="utf-8").strip()
            admin = Path(gitdir_text.removeprefix("gitdir: "))
            if not admin.is_absolute():
                admin = linked / admin
            (admin / "gitdir").write_text(
                str(fixture / "different-worktree" / ".git") + "\n",
                encoding="utf-8",
            )
            with (
                mock.patch.object(
                    evidence_scope.bounded_subprocess,
                    "run_bounded_process",
                ) as run,
                self.assertRaisesRegex(SystemExit, "backlink does not exactly identify"),
            ):
                evidence_scope._bounded_git(
                    ["ls-files", "--others", "-z", "--"],
                    linked,
                )
            run.assert_not_called()

    def test_git_query_detects_repository_config_identity_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_bounded(["git", "init", "-q"], cwd=root, check=True)
            result = evidence_scope.bounded_subprocess.BoundedProcessResult(
                args=("git", "ls-files", "--others", "-z", "--"),
                returncode=0,
                stdout=b"",
                stderr=b"",
                timed_out=False,
                output_exceeded=False,
            )

            def replace_config(
                *_args: object,
                **_kwargs: object,
            ) -> evidence_scope.bounded_subprocess.BoundedProcessResult:
                config = root / ".git" / "config"
                replacement = root / ".git" / "replacement-config"
                replacement.write_bytes(config.read_bytes())
                os.replace(replacement, config)
                return result

            with (
                mock.patch.object(
                    evidence_scope.bounded_subprocess,
                    "run_bounded_process",
                    side_effect=replace_config,
                ),
                self.assertRaisesRegex(
                    SystemExit,
                    "Git common configuration pathname no longer identifies",
                ),
            ):
                evidence_scope._bounded_git(
                    ["ls-files", "--others", "-z", "--"],
                    root,
                )

    def test_git_query_closes_substituted_information_directory_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_bounded(["git", "init", "-q"], cwd=root, check=True)
            information = root / ".git" / "info"
            displaced = root / ".git" / "info-held"
            real_open = evidence_scope.git_query.safe_paths.open_output_directory
            captured_descriptor: int | None = None

            def substitute_information_directory(
                path: Path,
                *,
                create_missing: bool,
            ) -> object:
                nonlocal captured_descriptor
                if path == information:
                    information.rename(displaced)
                    information.mkdir()
                    binding = real_open(path, create_missing=create_missing)
                    captured_descriptor = binding.descriptor
                    return binding
                return real_open(path, create_missing=create_missing)

            with (
                mock.patch.object(
                    evidence_scope.git_query.safe_paths,
                    "open_output_directory",
                    side_effect=substitute_information_directory,
                ),
                mock.patch.object(
                    evidence_scope.bounded_subprocess,
                    "run_bounded_process",
                ) as run,
                self.assertRaisesRegex(
                    SystemExit,
                    "Git information directory changed while it was bound",
                ),
            ):
                evidence_scope._bounded_git(
                    ["ls-files", "--others", "-z", "--"],
                    root,
                )
            run.assert_not_called()
            self.assertIsNotNone(captured_descriptor)
            if captured_descriptor is None:
                self.fail("information-directory descriptor was not captured")
            with self.assertRaises(OSError):
                os.fstat(captured_descriptor)

    def test_path_collection_rejects_concurrent_staging_that_would_be_omitted(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_bounded(["git", "init", "-q"], cwd=root, check=True)
            tracked = root / "tracked.md"
            tracked.write_text("baseline\n", encoding="utf-8")
            run_bounded(["git", "add", "tracked.md"], cwd=root, check=True)
            run_bounded(
                [
                    "git",
                    "-c",
                    "user.name=Framework Test",
                    "-c",
                    "user.email=framework@example.invalid",
                    "commit",
                    "-qm",
                    "baseline",
                ],
                cwd=root,
                check=True,
            )
            concurrent = root / "concurrent.md"
            concurrent.write_text("must not be omitted\n", encoding="utf-8")
            args = evidence_scope.build_parser().parse_args(
                ["--diff-base", "HEAD", "--root", str(root)]
            )
            real_runner = evidence_scope.bounded_subprocess.run_bounded_process
            staged = False

            def stage_after_diff(
                *runner_args: object,
                **runner_kwargs: object,
            ) -> evidence_scope.bounded_subprocess.BoundedProcessResult:
                nonlocal staged
                result = real_runner(*runner_args, **runner_kwargs)  # type: ignore[arg-type]
                command = tuple(
                    str(value)
                    for value in cast(tuple[object, ...], runner_args[0])
                )
                if not staged and "diff" in command:
                    self.assertNotIn(b"concurrent.md\0", result.stdout)
                    run_bounded(["git", "add", "concurrent.md"], cwd=root, check=True)
                    staged = True
                return result

            with (
                mock.patch.object(
                    evidence_scope.bounded_subprocess,
                    "run_bounded_process",
                    side_effect=stage_after_diff,
                ),
                self.assertRaisesRegex(
                    SystemExit,
                    "Git index.*no longer identifies|Git index.*content changed",
                ),
            ):
                evidence_scope.collect_paths(
                    args,
                    evidence_scope.validate_root(args.root),
                )

            self.assertTrue(staged)
            staged_names = run_bounded(
                ["git", "diff", "--cached", "--name-only", "-z", "HEAD", "--"],
                cwd=root,
                check=True,
            ).stdout
            self.assertIn("concurrent.md\0", staged_names)

    def test_staged_diff_rejects_diff_base_ref_mutation_after_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_bounded(["git", "init", "-q"], cwd=root, check=True)
            tracked = root / "tracked.md"
            tracked.write_text("baseline\n", encoding="utf-8")
            run_bounded(["git", "add", "tracked.md"], cwd=root, check=True)
            commit = [
                "git",
                "-c",
                "user.name=Framework Test",
                "-c",
                "user.email=framework@example.invalid",
                "commit",
                "-qm",
            ]
            run_bounded([*commit, "baseline"], cwd=root, check=True)
            initial_oid = run_bounded(
                ["git", "rev-parse", "HEAD"], cwd=root, check=True
            ).stdout.strip()
            tracked.write_text("candidate\n", encoding="utf-8")
            run_bounded(["git", "add", "tracked.md"], cwd=root, check=True)
            run_bounded([*commit, "alternate"], cwd=root, check=True)
            alternate_oid = run_bounded(
                ["git", "rev-parse", "HEAD"], cwd=root, check=True
            ).stdout.strip()
            head_ref = run_bounded(
                ["git", "symbolic-ref", "HEAD"], cwd=root, check=True
            ).stdout.strip()
            run_bounded(
                ["git", "update-ref", head_ref, initial_oid],
                cwd=root,
                check=True,
            )
            loose_ref = root / ".git" / head_ref
            self.assertTrue(loose_ref.is_file())
            args = evidence_scope.build_parser().parse_args(
                ["--diff-base", "HEAD", "--root", str(root)]
            )
            real_runner = evidence_scope.bounded_subprocess.run_bounded_process
            switched = False
            restored = False

            def ref_aba_around_diff(
                *runner_args: object,
                **runner_kwargs: object,
            ) -> evidence_scope.bounded_subprocess.BoundedProcessResult:
                nonlocal switched, restored
                result = real_runner(*runner_args, **runner_kwargs)  # type: ignore[arg-type]
                command = tuple(
                    str(value)
                    for value in cast(tuple[object, ...], runner_args[0])
                )
                if not switched and "rev-parse" in command:
                    loose_ref.write_text(alternate_oid + "\n", encoding="ascii")
                    switched = True
                elif switched and not restored and "diff" in command:
                    self.assertIn(initial_oid, command)
                    self.assertIn(b"tracked.md\0", result.stdout)
                    loose_ref.write_text(initial_oid + "\n", encoding="ascii")
                    restored = True
                return result

            with (
                mock.patch.object(
                    evidence_scope.bounded_subprocess,
                    "run_bounded_process",
                    side_effect=ref_aba_around_diff,
                ),
                self.assertRaisesRegex(
                    SystemExit,
                    "reference namespace generation changed",
                ),
            ):
                evidence_scope.collect_paths(
                    args,
                    evidence_scope.validate_root(args.root),
                )

            self.assertTrue(switched)
            self.assertFalse(restored)
            self.assertEqual(alternate_oid + "\n", loose_ref.read_text(encoding="ascii"))

    def test_evidence_scope_worktree_comparison_never_executes_clean_or_process_filters(
        self,
    ) -> None:
        for filter_kind in ("clean", "process"):
            with self.subTest(filter_kind=filter_kind), tempfile.TemporaryDirectory() as temp_dir:
                fixture = Path(temp_dir)
                root = fixture / "repo"
                root.mkdir()
                run_bounded(["git", "init", "-q"], cwd=root, check=True)
                (root / ".gitattributes").write_text(
                    "*.md filter=boundary\n",
                    encoding="utf-8",
                )
                tracked = root / "tracked.md"
                tracked.write_text("baseline\n", encoding="utf-8")
                run_bounded(
                    ["git", "add", ".gitattributes", "tracked.md"],
                    cwd=root,
                    check=True,
                )
                run_bounded(
                    [
                        "git",
                        "-c",
                        "user.name=Framework Test",
                        "-c",
                        "user.email=framework@example.invalid",
                        "commit",
                        "-qm",
                        "baseline",
                    ],
                    cwd=root,
                    check=True,
                )
                marker = fixture / f"{filter_kind}-executed"
                filter_command = fixture / f"{filter_kind}-filter.sh"
                filter_command.write_text(
                    "#!/bin/sh\nprintf executed > "
                    + shlex.quote(str(marker))
                    + "\n"
                    + ("cat\n" if filter_kind == "clean" else "exit 1\n"),
                    encoding="utf-8",
                )
                filter_command.chmod(0o700)
                run_bounded(
                    [
                        "git",
                        "config",
                        f"filter.boundary.{filter_kind}",
                        str(filter_command),
                    ],
                    cwd=root,
                    check=True,
                )
                tracked.write_text("changed\n", encoding="utf-8")
                args = evidence_scope.build_parser().parse_args(
                    ["--diff-base", "HEAD", "--root", str(root)]
                )

                self.assertEqual(
                    ["tracked.md"],
                    evidence_scope.collect_paths(
                        args,
                        evidence_scope.validate_root(args.root),
                    ),
                )
                self.assertFalse(marker.exists())

    def test_worktree_comparison_rejects_parent_substitution_during_read(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            original_parent = root / "nested"
            original_parent.mkdir()
            content = b"baseline\n"
            (original_parent / "tracked.md").write_bytes(content)
            digest = hashlib.sha1(usedforsecurity=False)
            digest.update(f"blob {len(content)}\0".encode("ascii"))
            digest.update(content)
            entry = evidence_scope.GitIndexEntry(
                mode="100644",
                oid=digest.hexdigest(),
                stage=0,
                path="nested/tracked.md",
            )
            root_descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            real_read = os.read
            substituted = False

            def substitute_parent(descriptor: int, size: int) -> bytes:
                nonlocal substituted
                if not substituted:
                    substituted = True
                    original_parent.rename(root / "detached-nested")
                    replacement = root / "nested"
                    replacement.mkdir()
                    (replacement / "tracked.md").write_bytes(content)
                return real_read(descriptor, size)

            try:
                with (
                    mock.patch.object(
                        evidence_scope.os,
                        "read",
                        side_effect=substitute_parent,
                    ),
                    self.assertRaisesRegex(
                        SystemExit,
                        "worktree parent no longer identifies",
                    ),
                ):
                    evidence_scope._worktree_entry_matches_index(
                        root_descriptor,
                        entry,
                        remaining_bytes=1024,
                    )
            finally:
                os.close(root_descriptor)
            self.assertTrue(substituted)

    def test_worktree_comparison_uses_only_owner_execute_for_git_mode(self) -> None:
        cases = (
            ("100644", 0o654, True),
            ("100755", 0o654, False),
            ("100755", 0o744, True),
        )
        for index_mode, file_mode, expected_match in cases:
            with (
                self.subTest(
                    index_mode=index_mode,
                    file_mode=oct(file_mode),
                ),
                tempfile.TemporaryDirectory() as temp_dir,
            ):
                root = Path(temp_dir)
                content = b"mode fixture\n"
                tracked = root / "tracked.md"
                tracked.write_bytes(content)
                tracked.chmod(file_mode)
                digest = hashlib.sha1(usedforsecurity=False)
                digest.update(f"blob {len(content)}\0".encode("ascii"))
                digest.update(content)
                entry = evidence_scope.GitIndexEntry(
                    mode=index_mode,
                    oid=digest.hexdigest(),
                    stage=0,
                    path="tracked.md",
                )
                root_descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    matches, read_bytes = (
                        evidence_scope._worktree_entry_matches_index(
                            root_descriptor,
                            entry,
                            remaining_bytes=1024,
                        )
                    )
                finally:
                    os.close(root_descriptor)
                self.assertEqual(expected_match, matches)
                self.assertEqual(0 if not expected_match else len(content), read_bytes)

    def test_git_query_rejects_unbound_config_includes_before_spawn(self) -> None:
        cases = (
            ("plain", b"[include]"),
            ("conditional", b'[includeIf "gitdir:' + b"/" + b'fixture/**"]'),
            ("space", b" [include]"),
            ("tab", b"\t[include]"),
            ("vertical-tab", b"\v[include]"),
            ("form-feed", b"\f[include]"),
            ("carriage-return", b"\r[include]"),
            ("utf8-bom", b"\xef\xbb\xbf[include]"),
        )
        for label, section in cases:
            with self.subTest(case=label), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                run_bounded(["git", "init", "-q"], cwd=root, check=True)
                config = root / ".git" / "config"
                config.write_bytes(
                    config.read_bytes()
                    + b"\n"
                    + section
                    + b"\n\tpath = "
                    + os.fsencode(root / "unbound-git-config")
                    + b"\n"
                )
                with (
                    mock.patch.object(
                        evidence_scope.bounded_subprocess,
                        "run_bounded_process",
                    ) as run,
                    self.assertRaisesRegex(
                        SystemExit,
                        "include/includeIf.*not descriptor-bound|UTF-8 BOM",
                    ),
                ):
                    evidence_scope._bounded_git(
                        ["ls-files", "--others", "-z", "--"],
                        root,
                    )
                run.assert_not_called()

    def test_git_query_rejects_repository_namespace_configuration_before_spawn(
        self,
    ) -> None:
        cases = (
            (b"[extensions]\n\tpartialClone = origin\n", "partial clone"),
            (b'[remote "origin"]\n\tpromisor = true\n', "promisor remote"),
            (
                b'[remote "origin"]\n\tpartialCloneFilter = blob:none\n',
                "partial clone filter",
            ),
            (b"[extensions]\n\trefStorage = reftable\n", "reftable"),
            (
                b"[core]\n\talternateRefsCommand = printf unsafe\n",
                "alternate refs command",
            ),
        )
        for raw, label in cases:
            with self.subTest(case=label), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                run_bounded(["git", "init", "-q"], cwd=root, check=True)
                config = root / ".git" / "config"
                config.write_bytes(config.read_bytes() + b"\n" + raw)
                with (
                    mock.patch.object(
                        evidence_scope.bounded_subprocess,
                        "run_bounded_process",
                    ) as run,
                    self.assertRaisesRegex(
                        SystemExit,
                        "unsupported object/reference redirect",
                    ),
                ):
                    evidence_scope._bounded_git(
                        ["ls-files", "--others", "-z", "--"],
                        root,
                )
                run.assert_not_called()

    def test_git_query_rejects_nonlocal_revision_surfaces_before_spawn(self) -> None:
        cases = (
            ("shallow", ".git/shallow", "file", "shallow-boundary"),
            ("grafts", ".git/info/grafts", "file", "grafts file"),
            ("replace", ".git/refs/replace", "directory", "replace or namespace"),
            (
                "namespace",
                ".git/refs/namespaces",
                "directory",
                "replace or namespace",
            ),
            (
                "promisor",
                ".git/objects/pack/fixture.promisor",
                "file",
                "promisor state",
            ),
        )
        for label, relative, kind, expected in cases:
            with self.subTest(case=label), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                run_bounded(["git", "init", "-q"], cwd=root, check=True)
                target = root / relative
                if kind == "directory":
                    target.mkdir()
                else:
                    target.write_text("0" * 40 + "\n", encoding="ascii")
                with (
                    mock.patch.object(
                        evidence_scope.bounded_subprocess,
                        "run_bounded_process",
                    ) as run,
                    self.assertRaisesRegex(SystemExit, expected),
                ):
                    evidence_scope._bounded_git(
                        ["ls-files", "--others", "-z", "--"],
                        root,
                    )
                run.assert_not_called()

    def test_git_query_rejects_foreign_reference_namespace_during_query(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir)
            root = fixture / "repo"
            root.mkdir()
            run_bounded(["git", "init", "-q"], cwd=root, check=True)
            tracked = root / "tracked.md"
            tracked.write_text("first\n", encoding="utf-8")
            run_bounded(["git", "add", "tracked.md"], cwd=root, check=True)
            commit = [
                "git",
                "-c",
                "user.name=Framework Test",
                "-c",
                "user.email=framework@example.invalid",
                "commit",
                "-qm",
            ]
            run_bounded([*commit, "first"], cwd=root, check=True)
            first_oid = run_bounded(
                ["git", "rev-parse", "HEAD"], cwd=root, check=True
            ).stdout.strip()
            tracked.write_text("second\n", encoding="utf-8")
            run_bounded(["git", "add", "tracked.md"], cwd=root, check=True)
            run_bounded([*commit, "second"], cwd=root, check=True)
            second_oid = run_bounded(
                ["git", "rev-parse", "HEAD"], cwd=root, check=True
            ).stdout.strip()
            symbolic_ref = run_bounded(
                ["git", "symbolic-ref", "HEAD"], cwd=root, check=True
            ).stdout.strip()
            run_bounded(
                ["git", "update-ref", symbolic_ref, first_oid],
                cwd=root,
                check=True,
            )
            local_heads = root / ".git" / "refs" / "heads"
            held_heads = root / ".git" / "refs" / "heads-held"
            foreign_heads = fixture / "foreign-heads"
            foreign_heads.mkdir()
            (foreign_heads / Path(symbolic_ref).name).write_text(
                second_oid + "\n",
                encoding="ascii",
            )
            real_runner = evidence_scope.bounded_subprocess.run_bounded_process
            consumed_foreign_ref = False

            def redirect_refs(
                *runner_args: object,
                **runner_kwargs: object,
            ) -> evidence_scope.bounded_subprocess.BoundedProcessResult:
                nonlocal consumed_foreign_ref
                local_heads.rename(held_heads)
                local_heads.symlink_to(foreign_heads, target_is_directory=True)
                result = real_runner(*runner_args, **runner_kwargs)  # type: ignore[arg-type]
                self.assertEqual(second_oid + "\n", result.stdout.decode("ascii"))
                consumed_foreign_ref = True
                return result

            with (
                mock.patch.object(
                    evidence_scope.bounded_subprocess,
                    "run_bounded_process",
                    side_effect=redirect_refs,
                ),
                self.assertRaisesRegex(
                    SystemExit,
                    "reference namespace.*symbolic links|reference namespace generation changed",
                ),
            ):
                evidence_scope._bounded_git(
                    ["rev-parse", "--verify", "--end-of-options", "HEAD"],
                    root,
                )
            self.assertTrue(consumed_foreign_ref)

    def test_evidence_scope_git_runner_delegates_with_exact_policy(self) -> None:
        result = evidence_scope.bounded_subprocess.BoundedProcessResult(
            args=("git", "ls-files", "--others", "-z", "--"),
            returncode=7,
            stdout=b"stdout",
            stderr=b"stderr",
            timed_out=False,
            output_exceeded=False,
        )
        root = Path.cwd()
        with mock.patch.object(
            evidence_scope.bounded_subprocess,
            "run_bounded_process",
            return_value=result,
        ) as run:
            observed = evidence_scope._bounded_git(
                ["ls-files", "--others", "-z", "--"],
                root,
            )

        self.assertEqual((7, b"stdout", b"stderr"), observed)
        run.assert_called_once()
        call = run.call_args
        self.assertEqual(
            evidence_scope.git_query.closed_git_query_command(
                ["ls-files", "--others", "-z", "--"]
            )[1:],
            call.args[0][1:],
        )
        self.assertIn("/fd/", call.args[0][0])
        self.assertIn("/fd/", str(call.kwargs["cwd"]))
        self.assertEqual(
            str(call.kwargs["cwd"]),
            call.kwargs["env"]["GIT_WORK_TREE"],
        )
        self.assertIn("/fd/", call.kwargs["env"]["GIT_DIR"])
        self.assertIn("/fd/", call.kwargs["env"]["GIT_COMMON_DIR"])
        self.assertTrue(call.kwargs["pass_fds"])
        self.assertIn(
            int(Path(call.kwargs["cwd"]).name),
            call.kwargs["pass_fds"],
        )
        self.assertIn(
            int(Path(call.args[0][0]).name),
            call.kwargs["pass_fds"],
        )
        self.assertIn(
            int(Path(call.kwargs["env"]["GIT_OBJECT_DIRECTORY"]).name),
            call.kwargs["pass_fds"],
        )
        self.assertEqual(
            evidence_scope.GIT_COMMAND_TIMEOUT_SECONDS,
            call.kwargs["timeout_seconds"],
        )
        self.assertEqual(
            evidence_scope.GIT_COMMAND_MAX_OUTPUT_BYTES,
            call.kwargs["max_output_bytes"],
        )
        self.assertEqual(
            evidence_scope.GIT_COMMAND_TIMEOUT_SECONDS,
            call.kwargs["maximum_timeout_seconds"],
        )
        self.assertEqual(
            evidence_scope.GIT_COMMAND_MAX_OUTPUT_BYTES,
            call.kwargs["maximum_output_bytes"],
        )
        self.assertEqual(
            evidence_scope.GIT_TERMINATION_GRACE_SECONDS,
            call.kwargs["termination_grace_seconds"],
        )

    def test_git_version_gate_stops_old_or_fake_git_before_repository_query(self) -> None:
        cases = (
            (b"git version 2.44.9\n", "2.45.0 or newer"),
            (b"not a Git version\n", "unrecognized version line"),
        )
        for stdout, expected in cases:
            with self.subTest(stdout=stdout), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                run_bounded(["git", "init", "-q"], cwd=root, check=True)
                version_result = evidence_scope.bounded_subprocess.BoundedProcessResult(
                    args=("git", "--version"),
                    returncode=0,
                    stdout=stdout,
                    stderr=b"",
                    timed_out=False,
                    output_exceeded=False,
                )
                with (
                    mock.patch.object(
                        evidence_scope.git_query,
                        "_GIT_VERSION_CACHE",
                        None,
                    ),
                    mock.patch.object(
                        evidence_scope.git_query,
                        "_BOUNDED_GIT_VERSION_RUNNER",
                        return_value=version_result,
                    ) as version_run,
                    mock.patch.object(
                        evidence_scope.bounded_subprocess,
                        "run_bounded_process",
                    ) as repository_query,
                    self.assertRaisesRegex(SystemExit, expected),
                ):
                    evidence_scope._bounded_git(
                        ["ls-files", "--others", "-z", "--"],
                        root,
                    )
                repository_query.assert_not_called()
                version_run.assert_called_once()
                version_call = version_run.call_args
                self.assertEqual("--version", version_call.args[0][1])
                self.assertEqual(Path("/"), version_call.kwargs["cwd"])
                self.assertNotIn("GIT_DIR", version_call.kwargs["env"])
                self.assertNotIn("GIT_WORK_TREE", version_call.kwargs["env"])
                self.assertTrue(version_call.kwargs["pass_fds"])

    def test_git_version_gate_never_executes_an_untrusted_fake_git(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir)
            root = fixture / "repo"
            root.mkdir()
            run_bounded(["git", "init", "-q"], cwd=root, check=True)
            marker = fixture / "fake-git-executed"
            fake_git = fixture / "git"
            fake_git.write_text(
                "#!/bin/sh\nprintf executed > "
                + shlex.quote(str(marker))
                + "\nprintf 'git version 99.0.0\\n'\n",
                encoding="utf-8",
            )
            fake_git.chmod(0o775)
            with (
                mock.patch.object(
                    evidence_scope.git_query,
                    "default_path_git_executable",
                    return_value=str(fake_git),
                ),
                mock.patch.object(
                    evidence_scope.git_query,
                    "_BOUNDED_GIT_VERSION_RUNNER",
                ) as version_run,
                mock.patch.object(
                    evidence_scope.bounded_subprocess,
                    "run_bounded_process",
                ) as repository_query,
                self.assertRaisesRegex(
                    SystemExit,
                    "root-owned",
                ),
            ):
                evidence_scope._bounded_git(
                    ["ls-files", "--others", "-z", "--"],
                    root,
                )
            version_run.assert_not_called()
            repository_query.assert_not_called()
            self.assertFalse(marker.exists())

    def test_evidence_scope_git_runner_preserves_timeout_and_output_cap_diagnostics(self) -> None:
        cases = (
            (
                True,
                False,
                "git ls-files --others -z -- timed out after 10s",
            ),
            (
                False,
                True,
                "Git path collection output exceeded the 4194304-byte limit",
            ),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_bounded(["git", "init", "-q"], cwd=root, check=True)
            for timed_out, output_exceeded, expected in cases:
                result = evidence_scope.bounded_subprocess.BoundedProcessResult(
                    args=("git", "ls-files", "--others", "-z", "--"),
                    returncode=-9,
                    stdout=b"partial stdout",
                    stderr=b"partial stderr",
                    timed_out=timed_out,
                    output_exceeded=output_exceeded,
                )
                with (
                    self.subTest(expected=expected),
                    mock.patch.object(
                        evidence_scope.bounded_subprocess,
                        "run_bounded_process",
                        return_value=result,
                    ),
                    self.assertRaises(SystemExit) as raised,
                ):
                    evidence_scope._bounded_git(
                        ["ls-files", "--others", "-z", "--"],
                        root,
                    )
                self.assertEqual(expected, str(raised.exception))

    def test_evidence_scope_git_runner_preserves_start_and_nonzero_diagnostics(self) -> None:
        start_error = evidence_scope.bounded_subprocess.BoundedSubprocessStartError(
            "bounded subprocess could not start: git unavailable"
        )
        start_error.__cause__ = OSError("git unavailable")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_bounded(["git", "init", "-q"], cwd=root, check=True)
            with (
                mock.patch.object(
                    evidence_scope.bounded_subprocess,
                    "run_bounded_process",
                    side_effect=start_error,
                ),
                self.assertRaises(SystemExit) as raised,
            ):
                evidence_scope._bounded_git(
                    ["ls-files", "--others", "-z", "--"],
                    root,
                )
        self.assertEqual(
            "git ls-files --others -z -- could not start: git unavailable",
            str(raised.exception),
        )

        cases = (
            (b"ignored", b" fatal \xff error \n", "fatal � error"),
            (b"ignored", b" \n", "git ls-files --others -z -- failed"),
        )
        for stdout, stderr, expected in cases:
            with (
                self.subTest(expected=expected),
                mock.patch.object(
                    evidence_scope,
                    "_bounded_git",
                    return_value=(23, stdout, stderr),
                ),
                self.assertRaises(SystemExit) as nonzero,
            ):
                evidence_scope.run_git(
                    ["ls-files", "--others", "-z", "--"],
                    Path.cwd(),
                )
            self.assertEqual(expected, str(nonzero.exception))

    def test_evidence_scope_preserves_nul_path_framing_contract(self) -> None:
        valid_cases = (
            (b"", []),
            (b"docs/a.md\0docs/space name.md\0", ["docs/a.md", "docs/space name.md"]),
        )
        for stdout, expected in valid_cases:
            with self.subTest(stdout=stdout), mock.patch.object(
                evidence_scope,
                "_bounded_git",
                return_value=(0, stdout, b""),
            ):
                self.assertEqual(
                    expected,
                    evidence_scope.run_git(["ls-files", "-z"], Path.cwd()),
                )

        invalid_cases = (
            (b"\0", "empty NUL-delimited path"),
            (b"docs/a.md\0\0", "empty NUL-delimited path"),
            (b"docs/\xff.md\0", "non-UTF-8 path"),
        )
        for stdout, expected in invalid_cases:
            with (
                self.subTest(stdout=stdout),
                mock.patch.object(
                    evidence_scope,
                    "_bounded_git",
                    return_value=(0, stdout, b""),
                ),
                self.assertRaisesRegex(SystemExit, expected),
            ):
                evidence_scope.run_git(["ls-files", "-z"], Path.cwd())

    def test_evidence_scope_requires_terminal_nul_git_output(self) -> None:
        with mock.patch.object(
            evidence_scope,
            "_bounded_git",
            return_value=(0, b"docs/example.md\n", b""),
        ):
            with self.assertRaisesRegex(SystemExit, "terminal NUL"):
                evidence_scope.run_git(["ls-files", "-z"], Path.cwd())

    def test_evidence_scope_preserves_nul_delimited_control_bearing_path(self) -> None:
        with mock.patch.object(
            evidence_scope,
            "_bounded_git",
            return_value=(0, b"docs/line\nbreak.md\0", b""),
        ):
            paths = evidence_scope.run_git(["ls-files", "-z"], Path.cwd())
        with self.assertRaisesRegex(SystemExit, "plain path text"):
            evidence_scope.validate_paths(paths, Path.cwd())

    def test_evidence_scope_bounds_total_git_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_bounded(["git", "init", "-q"], cwd=root, check=True)
            (root / "long-untracked-name.md").write_text("new\n", encoding="utf-8")
            with mock.patch.object(
                evidence_scope,
                "GIT_COMMAND_MAX_OUTPUT_BYTES",
                8,
            ):
                with self.assertRaisesRegex(SystemExit, "output exceeded"):
                    evidence_scope.run_git(
                        ["ls-files", "--others", "--exclude-standard", "-z", "--"],
                        root,
                    )
