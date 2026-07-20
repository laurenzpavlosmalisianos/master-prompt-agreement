"""Local and external link-checking tests."""

from __future__ import annotations

import io
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tests.validation_test_support import dict_items

import link_check  # noqa: E402


class LinkCheckTests(unittest.TestCase):
    def test_link_check_detects_missing_files_and_bad_anchors(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            doc = root / "doc.md"
            doc.write_text(
                "\n".join(
                    [
                        "# Good Header",
                        "[ok](doc.md#good-header)",
                        "[missing](missing.md)",
                        "[bad anchor](doc.md#missing-anchor)",
                        "```md",
                        "[ignored](also-missing.md)",
                        "```",
                    ]
                ),
                encoding="utf-8",
            )

            report = link_check.check_links(root, [doc], False, True, 1.0)
            report_errors = dict_items(report["errors"])
            errors = {(item["target"], item["message"]) for item in report_errors}

            self.assertIn(
                ("missing.md", "local target does not exist: missing.md"),
                errors,
            )
            self.assertIn(
                ("doc.md#missing-anchor", "anchor not found: missing-anchor"),
                errors,
            )
            self.assertFalse(
                any(item["target"] == "also-missing.md" for item in report_errors)
            )

    def test_link_check_strips_backtick_from_bare_url(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            doc = root / "doc.md"
            doc.write_text("Checked `https://example.com/feed.xml` today.\n", encoding="utf-8")

            self.assertIn((1, "https://example.com/feed.xml"), link_check.links_in_file(doc))

    def test_link_check_rejects_local_targets_outside_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            root = temp_path / "repo"
            nested = root / "nested"
            nested.mkdir(parents=True)
            outside = temp_path / "outside.md"
            outside.write_text("# Outside\n", encoding="utf-8")
            doc = nested / "doc.md"
            doc.write_text("[escape](../../outside.md)\n", encoding="utf-8")

            report = link_check.check_links(root, [doc], False, True, 1.0)

            self.assertEqual(
                [
                    {
                        "file": "nested/doc.md",
                        "line": 1,
                        "message": "local link escapes the checked root",
                        "target": "../../outside.md",
                    }
                ],
                report["errors"],
            )

    def test_link_check_blocks_external_local_and_private_targets(self) -> None:
        self.assertEqual(
            "external URL must use https",
            link_check.blocked_external_url_reason("http://example.com/status"),
        )
        self.assertEqual(
            "external URL points to localhost",
            link_check.blocked_external_url_reason("https://localhost/status"),
        )
        self.assertEqual(
            "external URL points to non-public address: 169.254.169.254",
            link_check.blocked_external_url_reason("https://169.254.169.254/latest/meta-data"),
        )
        self.assertEqual(
            "external URL points to non-public address: 127.0.0.1",
            link_check.blocked_external_url_reason("https://2130706433/status"),
        )
        self.assertEqual(
            "external URL points to non-public address: 127.0.0.1",
            link_check.blocked_external_url_reason("https://0x7f000001/status"),
        )
        self.assertEqual(
            "external URL points to non-public address: 169.254.169.254",
            link_check.blocked_external_url_reason("https://0251.0376.0251.0376/latest/meta-data"),
        )
        self.assertEqual(
            "external URL uses unsupported legacy IPv4 literal: 0x5db8d822",
            link_check.blocked_external_url_reason("https://0x5db8d822/status"),
        )
        self.assertEqual(
            "external URL must not contain credentials",
            link_check.blocked_external_url_reason("https://user:" + "pass@example.com/"),
        )
        self.assertIn(
            "malformed external URL",
            link_check.blocked_external_url_reason("http://[::1") or "",
        )
        self.assertIn(
            "malformed external URL",
            link_check.blocked_external_url_reason("https://example.com:abc") or "",
        )

    def test_link_check_external_timeout_fails_fast_per_url(self) -> None:
        calls = []

        def fake_urlopen(request, timeout):  # type: ignore[no-untyped-def]
            calls.append((request.get_method(), timeout))
            raise TimeoutError()

        with mock.patch.object(link_check, "safe_urlopen", fake_urlopen):
            error = link_check.check_external_url("https://example.com/status", 0.25)

        self.assertEqual("timed out after 0.25s", error)
        self.assertEqual([("HEAD", 0.25)], calls)

    def test_link_check_single_file_root_uses_parent_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            doc = root / "doc.md"
            other = root / "other.md"
            doc.write_text("[other](other.md)\n", encoding="utf-8")
            other.write_text("# Other\n", encoding="utf-8")

            report = link_check.check_links(root, [doc], False, True, 1.0)

            self.assertEqual(["doc.md"], report["checked_files"])
            self.assertEqual([], report["errors"])

    def test_link_check_excludes_local_authoring_files_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "private").mkdir()
            (root / "docs").mkdir()
            (root / "docs" / "notes").mkdir()
            public_doc = root / "public.md"
            private_doc = root / "private" / "notes.md"
            local_note = root / ("internal" + "_notes.md")
            nested_internal_doc = root / "docs" / ("internal" + "_reference.md")
            nested_notes_doc = root / "docs" / "notes" / "guide.md"

            public_doc.write_text("[ok](public.md)\n", encoding="utf-8")
            private_doc.write_text("[missing](missing.md)\n", encoding="utf-8")
            local_note.write_text("[missing](missing.md)\n", encoding="utf-8")
            nested_internal_doc.write_text("[ok](internal_reference.md)\n", encoding="utf-8")
            nested_notes_doc.write_text("[ok](../../public.md)\n", encoding="utf-8")

            files = link_check.markdown_files(root, ["**/*.md"], set(link_check.DEFAULT_EXCLUDED_DIRS))
            report = link_check.check_links(root, files, False, True, 1.0)

            self.assertEqual({public_doc, nested_internal_doc, nested_notes_doc}, set(files))
            self.assertEqual([], report["errors"])

    def test_link_check_excludes_root_dirs_from_ignore_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".git" / "info").mkdir(parents=True)
            (root / "drafts").mkdir()
            (root / "local_review").mkdir()
            public_doc = root / "public.md"
            draft_doc = root / "drafts" / "notes.md"
            review_doc = root / "local_review" / "notes.md"

            (root / ".gitignore").write_text("drafts/\n# comment\n*.tmp\n!keep/\n", encoding="utf-8")
            (root / ".git" / "info" / "exclude").write_text("local_review/\n", encoding="utf-8")
            public_doc.write_text("[ok](public.md)\n", encoding="utf-8")
            draft_doc.write_text("[missing](missing.md)\n", encoding="utf-8")
            review_doc.write_text("[missing](missing.md)\n", encoding="utf-8")

            root_excluded_dirs = set(link_check.DEFAULT_ROOT_EXCLUDED_DIRS) | link_check.root_ignored_dirs(root)
            files = link_check.markdown_files(
                root,
                ["**/*.md"],
                set(link_check.DEFAULT_EXCLUDED_DIRS),
                root_excluded_dirs,
            )
            report = link_check.check_links(root, files, False, True, 1.0)

            self.assertEqual([public_doc], files)
            self.assertEqual([], report["errors"])

    def test_link_check_excludes_private_source_maintenance_path_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            refs = root / "private" / "references"
            refs.mkdir(parents=True)
            public_doc = root / "public.md"
            private_doc = refs / "sources.md"
            public_doc.write_text("[ok](public.md)\n", encoding="utf-8")
            private_doc.write_text("[missing](missing.md)\n", encoding="utf-8")

            files = link_check.markdown_files(root, ["**/*.md"], set(link_check.DEFAULT_EXCLUDED_DIRS))
            report = link_check.check_links(root, files, False, True, 1.0)

            self.assertEqual([public_doc], files)
            self.assertEqual([], report["errors"])

    def test_link_check_includes_only_explicit_excluded_root_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            private_refs = root / "private" / "references"
            private_sibling = root / "private" / "operator"
            review = root / "review_artifacts"
            private_refs.mkdir(parents=True)
            private_sibling.mkdir(parents=True)
            review.mkdir()
            included = private_refs / "sources.md"
            sibling = private_sibling / "runbook.md"
            excluded = review / "report.md"
            included.write_text("# Included\n", encoding="utf-8")
            sibling.write_text("[missing](missing.md)\n", encoding="utf-8")
            excluded.write_text("[missing](missing.md)\n", encoding="utf-8")

            files = link_check.markdown_files(
                root,
                ["private" + "/**/*.md", "review_" + "artifacts/**/*.md"],
                set(link_check.DEFAULT_EXCLUDED_DIRS),
                set(link_check.DEFAULT_ROOT_EXCLUDED_DIRS),
                set(),
                {("private", "references")},
            )
            report = link_check.check_links(root, files, False, True, 1.0)

            self.assertEqual([included], files)
            self.assertEqual([], report["errors"])

    def test_link_check_include_root_path_preserves_deeper_ignore(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            private = root / "private"
            raw = private / "raw_runs"
            raw.mkdir(parents=True)
            maintained = private / "README.md"
            ignored = raw / "session.md"
            maintained.write_text("# Maintained\n", encoding="utf-8")
            ignored.write_text("[missing](missing.md)\n", encoding="utf-8")
            (root / ".gitignore").write_text(
                "private" + "/\nprivate" + "/raw_runs/\n",
                encoding="utf-8",
            )

            files = link_check.markdown_files(
                root,
                ["private" + "/**/*.md"],
                set(link_check.DEFAULT_EXCLUDED_DIRS),
                set(link_check.DEFAULT_ROOT_EXCLUDED_DIRS) | link_check.root_ignored_dirs(root),
                link_check.root_ignored_path_prefixes(root),
                {("private",)},
            )

        self.assertEqual([maintained], files)

    def test_link_check_cli_include_root_path_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            private = root / "private"
            private.mkdir()
            (private / "sources.md").write_text("# Sources\n", encoding="utf-8")
            linked = root / "linked"
            linked.symlink_to(private, target_is_directory=True)
            cases = (
                "missing",
                "../outside",
                "private" + "/../review_" + "artifacts",
                "private" + "/*.md",
                str(private),
                "linked",
            )

            for value in cases:
                with self.subTest(value=value):
                    with mock.patch(
                        "sys.argv",
                        ["link_check.py", "--root", str(root), "--include-root-path", value],
                    ):
                        with mock.patch("sys.stderr", new_callable=io.StringIO):
                            with self.assertRaises(SystemExit):
                                link_check.main()
    def test_link_check_rejects_explicit_symlinked_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            outside = Path(temp_dir) / "outside.md"
            linked = root / "linked.md"
            outside.write_text("[missing](missing.md)\n", encoding="utf-8")
            linked.symlink_to(outside)

            report = link_check.check_links(root, [linked], False, True, 1.0)

            report_errors = dict_items(report["errors"])
            self.assertEqual("refusing to read symlinked Markdown source", report_errors[0]["message"])

    def test_link_check_cli_rejects_invalid_roots_patterns_and_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            non_markdown = root / "data.txt"
            non_markdown.write_text("data\n", encoding="utf-8")
            cases = (
                ["--root", str(root / "missing")],
                ["--root", str(non_markdown)],
                ["--root", str(root), "--include", "../*.md"],
                ["--root", str(root), "--include", "docs//*.md"],
                ["--root", str(root), "--include", "https://example.com/*.md"],
                ["--root", str(root), "--timeout", "0"],
            )

            for argv in cases:
                with self.subTest(argv=argv):
                    with mock.patch("sys.argv", ["link_check.py", *argv]):
                        with mock.patch("sys.stderr", new_callable=io.StringIO):
                            with self.assertRaises(SystemExit):
                                link_check.main()
