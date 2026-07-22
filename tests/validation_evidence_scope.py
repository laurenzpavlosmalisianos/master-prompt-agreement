"""Evidence-scope selection validation tests."""

from __future__ import annotations

import io
import os
from pathlib import Path
import shlex
import tempfile
import unittest
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
            with self.assertRaises(SystemExit):
                evidence_scope.validate_paths(["linked/evidence.md"], root)

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
            ["cat-file", "--batch"],
            ["check-ignore", "--", "unregistered/raw"],
        ):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                evidence_scope.git_query.closed_git_query_command(arguments)

    def test_git_query_ignores_ambient_path_and_requires_qualified_override(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            poison = Path(temp_dir)
            fake_git = poison / "git"
            fake_git.write_text("#!/bin/sh\nexit 97\n", encoding="utf-8")
            fake_git.chmod(0o700)
            fake_git_path = fake_git.resolve(strict=True)
            with mock.patch.dict(os.environ, {"PATH": str(poison)}):
                command = evidence_scope.git_query.closed_git_query_command(
                    ["ls-files", "--others", "-z", "--"]
                )
                environment = (
                    evidence_scope.git_query.closed_git_query_environment(poison)
                )

        self.assertTrue(Path(command[0]).is_absolute())
        self.assertNotEqual(fake_git_path, Path(command[0]))
        self.assertEqual(os.defpath, environment["PATH"])
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

            returncode, stdout, _stderr = evidence_scope._bounded_git(
                ["ls-files", "--others", "-z", "--"],
                selected,
            )

        self.assertNotEqual(0, returncode)
        self.assertEqual(b"", stdout)

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
        run.assert_called_once_with(
            evidence_scope.git_query.closed_git_query_command(
                ["ls-files", "--others", "-z", "--"]
            ),
            cwd=root,
            env=evidence_scope.git_query.closed_git_query_environment(root),
            timeout_seconds=evidence_scope.GIT_COMMAND_TIMEOUT_SECONDS,
            max_output_bytes=evidence_scope.GIT_COMMAND_MAX_OUTPUT_BYTES,
            maximum_timeout_seconds=evidence_scope.GIT_COMMAND_TIMEOUT_SECONDS,
            maximum_output_bytes=evidence_scope.GIT_COMMAND_MAX_OUTPUT_BYTES,
            termination_grace_seconds=evidence_scope.GIT_TERMINATION_GRACE_SECONDS,
        )

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
                    Path.cwd(),
                )
            self.assertEqual(expected, str(raised.exception))

    def test_evidence_scope_git_runner_preserves_start_and_nonzero_diagnostics(self) -> None:
        start_error = evidence_scope.bounded_subprocess.BoundedSubprocessStartError(
            "bounded subprocess could not start: git unavailable"
        )
        start_error.__cause__ = OSError("git unavailable")
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
                Path.cwd(),
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
