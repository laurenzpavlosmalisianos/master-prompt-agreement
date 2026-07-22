"""Source-registry access and bounded-input tests."""

from __future__ import annotations

from http.client import HTTPMessage
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
from urllib.error import HTTPError

from tests.validation_test_support import SCRIPTS_DIR as _SCRIPTS_DIR

import check_reference_freshness  # noqa: E402
import safe_paths  # noqa: E402
import source_registry_access_audit  # noqa: E402


class SourceRegistryAccessTests(unittest.TestCase):
    def test_source_registry_access_has_no_private_reference_default(self) -> None:
        args = source_registry_access_audit.build_parser().parse_args([])
        self.assertIsNone(args.reference_dir)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            private_refs = root / "private" / "references"
            private_refs.mkdir(parents=True)
            (private_refs / "private.md").write_text(
                "https://private.example.invalid/source\n",
                encoding="utf-8",
            )
            (root / "SOURCE_PACKS.md").write_text(
                "https://example.com/public\n",
                encoding="utf-8",
            )

            snapshots = source_registry_access_audit.registry_snapshots(root, ())

        self.assertEqual(["SOURCE_PACKS.md"], [item.path.name for item in snapshots])

    def test_source_registry_access_audit_collects_monitor_and_strips_backticks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            refs = root / "references"
            refs.mkdir(parents=True)
            source = refs / "sources.md"
            source.write_text(
                "\n".join(
                    [
                        "# Sources",
                        "",
                        "- Example",
                        "  https://example.com/exact`",
                        "  Monitor root: https://example.com/feed.xml`",
                        "",
                        "```",
                        "https://example.com/example-only",
                        "Monitor root: https://example.com/fenced-feed.xml",
                        "```",
                    ]
                ),
                encoding="utf-8",
            )
            source_update = root / "SOURCE_UPDATE.md"
            source_update.write_text(
                "\n".join(
                    [
                        "# Source Update Plan",
                        "",
                        "## Source Registry",
                        "",
                        "| Surface | Source | Kind | Tier | Scope | Volatility | Check Method | Access Policy | Monitoring Mode | Cadence | Last Checked | Allowed Use | Action Rule |",
                        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
                        "| security | https://example.com/releases | release notes | [vendor-doc] | current | version-sensitive | repository releases | not applicable | recurring | release-triggered | 2026-06-19 | normative after verification | review |",
                        "| reference | https://example.com/static-paper | paper | [research] | fixed | stable | manual | not applicable | one_off | manual | 2026-06-19 | evidence-only | keep |",
                        "",
                        "## Feed Watchers",
                        "",
                        "| Surface | Feed | Tier | Scope | Check Method | Access Policy | Conditional State | Dedupe Key | Last Checked | Last Seen | Allowed Use | Triage Rule | Output |",
                        "|---|---|---|---|---|---|---|---|---|---|---|---|",
                        "| security | https://example.com/feed.xml | [vendor-doc] | current | RSS | not applicable | ETag | GUID | none | source discovery only | triage | report |",
                    ]
                ),
                encoding="utf-8",
            )

            all_urls = source_registry_access_audit.collect_urls(root, Path("references"), False)
            monitor_urls = source_registry_access_audit.collect_urls(root, Path("references"), True)

        self.assertIn("https://example.com/exact", all_urls)
        self.assertNotIn("https://example.com/example-only", all_urls)
        self.assertNotIn("https://example.com/fenced-feed.xml", all_urls)
        self.assertIn("https://example.com/feed.xml", all_urls)
        self.assertEqual(
            [
                "https://example.com/feed.xml",
                "https://example.com/releases",
            ],
            sorted(monitor_urls),
        )

    def test_source_registry_access_audit_recurses_reference_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            refs = root / "references" / "nested"
            refs.mkdir(parents=True)
            (refs / "sources.md").write_text(
                "# Nested Sources\n\n- Example\n  https://example.com/nested\n",
                encoding="utf-8",
            )

            urls = source_registry_access_audit.collect_urls(root, Path("references"), False)

        self.assertIn("https://example.com/nested", urls)

    def test_source_registry_access_audit_rejects_empty_url_work(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            refs = root / "references"
            refs.mkdir(parents=True)
            (refs / "sources.md").write_text("# Sources\n\nNo URLs here.\n", encoding="utf-8")

            urls = source_registry_access_audit.collect_urls(root, Path("references"), False)
            errors = source_registry_access_audit.audit_errors([], len(source_registry_access_audit.reference_files(root, Path("references"))))

        self.assertEqual({}, urls)
        self.assertIn("source registry access audit found no URLs to check", errors)

    def test_source_registry_access_audit_bounds_cli_resources_and_headers(self) -> None:
        parser = source_registry_access_audit.build_parser()
        invalid_argv = (
            ["--workers", "0"],
            ["--workers", "65"],
            ["--max-read-bytes", "0"],
            ["--max-read-bytes", "1000001"],
            ["--timeout", "0"],
            ["--timeout", "301"],
            ["--user-agent", "unsafe\nheader"],
        )

        for argv in invalid_argv:
            with self.subTest(argv=argv), mock.patch("sys.stderr", new_callable=io.StringIO):
                with self.assertRaises(SystemExit):
                    parser.parse_args(argv)

    def test_source_registry_access_audit_returns_successful_fetch_result(self) -> None:
        response = mock.MagicMock()
        response.__enter__.return_value.status = 200
        response.__enter__.return_value.geturl.return_value = "https://example.com/final"
        response.__enter__.return_value.headers = {"content-type": "text/plain"}
        response.__enter__.return_value.read.return_value = b"ok"

        with mock.patch.object(source_registry_access_audit, "safe_urlopen", return_value=response):
            result = source_registry_access_audit.request_with_redirects(
                "https://example.com/start",
                "GET",
                1.0,
                32,
                "test-agent",
            )

        self.assertTrue(result.ok)
        self.assertEqual(200, result.status)
        self.assertEqual("https://example.com/final", result.final_url)
        response.__enter__.return_value.read.assert_called_once_with(32)

    def test_source_registry_text_output_escapes_every_untrusted_field(self) -> None:
        result = source_registry_access_audit.FetchResult(
            False,
            None,
            "https://example.com/\u202efinal",
            "text/plain\x9b31m",
            "Grüße failure\x1b]52;c;payload\x07\nforged",
        )
        row = source_registry_access_audit.AuditRow(
            "https://example.com/\x1b]52;c;payload\x07",
            (
                source_registry_access_audit.UrlRef(
                    "fixture/source-registry/source\nforged.md",
                    7,
                    True,
                ),
            ),
            result,
            result,
            "disallow\u2028forged",
        )
        with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
            source_registry_access_audit.print_text(
                [row],
                1,
                ("rejected\tinput\u202e",),
            )

        rendered = stdout.getvalue()
        self.assertIn(r"input_error: rejected\x09input\u202e", rendered)
        self.assertIn(r"\x1b]52;c;payload\x07", rendered)
        self.assertIn(r"source\x0aforged.md:7", rendered)
        self.assertIn(r"\u202efinal", rendered)
        self.assertIn(r"\x9b31m", rendered)
        self.assertIn(r"\u2028forged", rendered)
        self.assertIn("Grüße", rendered)
        for forbidden in ("\x00", "\x07", "\x1b", "\x7f", "\x9b", "\u2028", "\u202e"):
            self.assertNotIn(forbidden, rendered)

    def test_source_registry_access_audit_does_not_report_an_unsafe_redirect_target(self) -> None:
        headers = HTTPMessage()
        headers["Location"] = "http://localhost/private?token=secret"
        redirect = HTTPError(
            "https://example.com/start",
            302,
            "Found",
            headers,
            None,
        )
        with mock.patch.object(
            source_registry_access_audit,
            "safe_urlopen",
            side_effect=redirect,
        ):
            result = source_registry_access_audit.request_with_redirects(
                "https://example.com/start",
                "GET",
                1.0,
                32,
                "test-agent",
            )

        self.assertFalse(result.ok)
        self.assertEqual("https://example.com/start", result.final_url)
        self.assertNotIn("token=secret", result.error)
        self.assertIn("redirect target rejected", result.error)

    def test_reference_source_tools_reject_unsafe_reference_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "repo"
            outside = Path(temp_dir) / "outside"
            root.mkdir()
            outside.mkdir()
            (root / "references").mkdir()
            linked = root / "linked"
            linked.symlink_to(outside, target_is_directory=True)

            bad_dirs = [root / "references", Path("../references"), Path("linked")]

            for reference_dir in bad_dirs:
                with self.subTest(reference_dir=reference_dir.as_posix()):
                    with self.assertRaises(ValueError):
                        source_registry_access_audit.reference_files(root, reference_dir)
                    with self.assertRaises(ValueError):
                        check_reference_freshness.reference_markdown_files(root, (reference_dir,))

            child_link = root / "references" / "linked.md"
            outside_file = outside / "sources.md"
            outside_file.write_text("# Outside\n", encoding="utf-8")
            child_link.symlink_to(outside_file)

            with self.assertRaises(ValueError):
                source_registry_access_audit.reference_files(root, Path("references"))
            with self.assertRaises(ValueError):
                check_reference_freshness.reference_markdown_files(root, (Path("references"),))

    def test_source_registry_inputs_fail_closed_before_network_access(self) -> None:
        cases = ("invalid-utf8", "oversize", "hardlink", "fifo")
        for case_id in cases:
            with self.subTest(case_id=case_id), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                references = root / "fixture" / "source-registry"
                references.mkdir(parents=True)
                registry = references / "sources.md"
                if case_id == "invalid-utf8":
                    registry.write_bytes(b"Reviewed: \xff\nhttps://example.com/releases\n")
                elif case_id == "oversize":
                    registry.write_bytes(
                        b"x" * (safe_paths.DEFAULT_JSON_INPUT_MAX_BYTES + 1)
                    )
                elif case_id == "hardlink":
                    seed = root / "seed.md"
                    seed.write_text(
                        "Reviewed: 2026-07-12\nhttps://example.com/releases\n",
                        encoding="utf-8",
                    )
                    os.link(seed, registry)
                else:
                    if not hasattr(os, "mkfifo"):
                        self.skipTest("FIFO creation is unavailable")
                    os.mkfifo(registry)

                with (
                    mock.patch.object(sys, "argv", [
                        "source_registry_access_audit.py",
                        "--root",
                        str(root),
                        "--reference-dir",
                        "fixture/source-registry",
                        "--check-robots",
                    ]),
                    mock.patch.object(
                        source_registry_access_audit,
                        "safe_urlopen",
                    ) as safe_urlopen,
                    mock.patch("sys.stdout", new_callable=io.StringIO) as stdout,
                ):
                    result = source_registry_access_audit.main()

                self.assertEqual(1, result)
                self.assertIn("source registry input rejected", stdout.getvalue())
                safe_urlopen.assert_not_called()
