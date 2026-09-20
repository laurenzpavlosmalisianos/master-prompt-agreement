"""Source-registry access and bounded-input tests."""

from __future__ import annotations

from concurrent.futures import Executor, Future
from http.client import HTTPMessage
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any
import unittest
from unittest import mock
from urllib.error import HTTPError

from tests.validation_test_support import SCRIPTS_DIR as _SCRIPTS_DIR

import check_reference_freshness  # noqa: E402
import safe_paths  # noqa: E402
import source_registry_access_audit  # noqa: E402
import source_registry_files  # noqa: E402


class _FakeResponse:
    def __init__(
        self,
        url: str,
        *,
        status: int = 200,
        content_type: str = "text/plain",
        body: bytes = b"ok",
    ) -> None:
        self.url = url
        self.status = status
        self.headers = {"content-type": content_type}
        self.body = body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def geturl(self) -> str:
        return self.url

    def read(self, _size: int = -1) -> bytes:
        return self.body


class _DeterministicExecutor(Executor):
    """Store jobs until a patched deterministic wait function releases one."""

    def __init__(self, *, max_workers: int) -> None:
        self.max_workers = max_workers
        self.jobs: dict[
            Future[Any],
            tuple[Any, tuple[Any, ...], dict[str, Any]],
        ] = {}
        self.max_unresolved = 0
        self.cancelled_before_shutdown = 0
        self.shutdown_called = False

    def submit(self, fn: Any, /, *args: Any, **kwargs: Any) -> Future[Any]:
        future: Future[Any] = Future()
        self.jobs[future] = (fn, args, kwargs)
        self.max_unresolved = max(
            self.max_unresolved,
            sum(not item.done() for item in self.jobs),
        )
        return future

    def release_one(self, candidates: set[Future[Any]]) -> Future[Any]:
        future = next(item for item in candidates if not item.done())
        fn, args, kwargs = self.jobs[future]
        if future.set_running_or_notify_cancel():
            try:
                future.set_result(fn(*args, **kwargs))
            except BaseException as exc:
                future.set_exception(exc)
        return future

    def shutdown(self, wait: bool = True, *, cancel_futures: bool = False) -> None:
        del wait
        self.cancelled_before_shutdown = sum(
            item.cancelled() for item in self.jobs
        )
        if cancel_futures:
            for future in self.jobs:
                future.cancel()
        self.shutdown_called = True


class _FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class SourceRegistryAccessTests(unittest.TestCase):
    def test_source_registry_access_has_no_private_reference_default(self) -> None:
        args = source_registry_access_audit.build_parser().parse_args([])
        self.assertIsNone(args.reference_dir)
        self.assertEqual(4_096, args.max_source_entries)
        self.assertEqual(512, args.max_source_files)
        self.assertEqual(32 * 1024 * 1024, args.max_source_bytes)
        self.assertEqual(2_048, args.max_unique_urls)
        self.assertEqual(16_384, args.max_url_references)
        self.assertEqual(8_192, args.max_transport_requests)
        self.assertEqual(300.0, args.run_deadline)
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
            ["--max-source-entries", "0"],
            ["--max-source-entries", "1000001"],
            ["--max-source-files", "0"],
            ["--max-source-files", "100001"],
            ["--max-source-bytes", "0"],
            ["--max-source-bytes", str(1024 * 1024 * 1024 + 1)],
            ["--max-unique-urls", "0"],
            ["--max-unique-urls", "100001"],
            ["--max-url-references", "0"],
            ["--max-url-references", "1000001"],
            ["--max-transport-requests", "0"],
            ["--max-transport-requests", "1000001"],
            ["--run-deadline", "0"],
            ["--run-deadline", "3601"],
            ["--user-agent", "unsafe\nheader"],
        )

        for argv in invalid_argv:
            with self.subTest(argv=argv), mock.patch("sys.stderr", new_callable=io.StringIO):
                with self.assertRaises(SystemExit):
                    parser.parse_args(argv)

    def test_run_audit_revalidates_every_programmatic_scalar_before_work(self) -> None:
        invalid_values = (
            ("workers", 0),
            ("timeout", float("nan")),
            ("max_read_bytes", source_registry_access_audit.MAX_READ_BYTES + 1),
            ("user_agent", "unsafe\nheader"),
            ("max_source_entries", 0),
            ("max_source_files", 0),
            ("max_source_bytes", 0),
            ("max_unique_urls", 0),
            ("max_url_references", 0),
            ("max_transport_requests", 0),
            ("run_deadline", float("inf")),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for field, value in invalid_values:
                with self.subTest(field=field, value=value):
                    args = source_registry_access_audit.build_parser().parse_args(
                        ["--root", str(root)]
                    )
                    setattr(args, field, value)
                    with (
                        mock.patch.object(
                            source_registry_access_audit,
                            "safe_urlopen",
                        ) as transport,
                        mock.patch.object(
                            source_registry_access_audit,
                            "ThreadPoolExecutor",
                        ) as executor,
                        self.assertRaises((TypeError, ValueError)),
                    ):
                        source_registry_access_audit.run_audit(
                            args,
                            snapshots=(),
                        )
                    transport.assert_not_called()
                    executor.assert_not_called()

    def test_direct_network_helpers_reject_invalid_redirect_and_status_values(self) -> None:
        with (
            mock.patch.object(
                source_registry_access_audit,
                "safe_urlopen",
            ) as transport,
            self.assertRaisesRegex(ValueError, "max_redirects"),
        ):
            source_registry_access_audit.request_with_redirects(
                "https://example.com/source",
                "GET",
                1.0,
                32,
                "test-agent",
                max_redirects=source_registry_access_audit.MAX_REDIRECTS + 1,
            )
        transport.assert_not_called()

        response = mock.MagicMock()
        response.__enter__.return_value.status = "200"
        response.__enter__.return_value.geturl.return_value = (
            "https://example.com/source"
        )
        response.__enter__.return_value.headers = {"content-type": "text/plain"}
        with mock.patch.object(
            source_registry_access_audit,
            "safe_urlopen",
            return_value=response,
        ):
            result = source_registry_access_audit.request_with_redirects(
                "https://example.com/source",
                "GET",
                1.0,
                32,
                "test-agent",
            )
        self.assertFalse(result.ok)
        self.assertIsNone(result.status)
        self.assertIn("invalid HTTP status", result.error)
        response.__enter__.return_value.read.assert_not_called()

    def test_supplied_deadline_and_request_budget_cannot_expand_selected_limits(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            args = source_registry_access_audit.build_parser().parse_args(
                ["--root", temp_dir]
            )
            limits = source_registry_access_audit.AuditLimits(
                max_transport_requests=1,
                run_deadline_seconds=1.0,
            )
            with self.assertRaisesRegex(ValueError, "run deadline"):
                source_registry_access_audit.run_audit(
                    args,
                    snapshots=(),
                    limits=limits,
                    deadline=source_registry_access_audit.MonotonicDeadline(2.0),
                )
            with self.assertRaisesRegex(ValueError, "transport request limit"):
                source_registry_access_audit.run_audit(
                    args,
                    snapshots=(),
                    limits=limits,
                    request_budget=source_registry_access_audit.TransportRequestBudget(2),
                )

    def test_source_registry_file_limit_fails_structured_before_network(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            references = root / "references"
            references.mkdir()
            (references / "one.md").write_text(
                "https://example.com/one\n",
                encoding="utf-8",
            )
            (references / "two.md").write_text(
                "https://example.com/two\n",
                encoding="utf-8",
            )
            with (
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "source_registry_access_audit.py",
                        "--root",
                        str(root),
                        "--reference-dir",
                        "references",
                        "--max-source-files",
                        "1",
                        "--format",
                        "json",
                    ],
                ),
                mock.patch.object(source_registry_access_audit, "safe_urlopen") as transport,
                mock.patch.object(source_registry_access_audit, "ThreadPoolExecutor") as executor,
                mock.patch("sys.stdout", new_callable=io.StringIO) as stdout,
            ):
                result = source_registry_access_audit.main()

        payload = json.loads(stdout.getvalue())
        self.assertEqual(1, result)
        self.assertEqual(
            "source_registry_file_limit_exceeded",
            payload["diagnostics"][0]["code"],
        )
        self.assertEqual(1, payload["diagnostics"][0]["limit"])
        self.assertEqual(2, payload["diagnostics"][0]["observed"])
        transport.assert_not_called()
        executor.assert_not_called()

    def test_source_registry_visited_entry_limit_counts_non_markdown_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            references = root / "references"
            references.mkdir()
            (references / "one.bin").write_bytes(b"one")
            (references / "two.bin").write_bytes(b"two")
            with (
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "source_registry_access_audit.py",
                        "--root",
                        str(root),
                        "--reference-dir",
                        "references",
                        "--max-source-entries",
                        "2",
                        "--format",
                        "json",
                    ],
                ),
                mock.patch.object(
                    source_registry_access_audit,
                    "safe_urlopen",
                ) as transport,
                mock.patch.object(
                    source_registry_access_audit,
                    "ThreadPoolExecutor",
                ) as executor,
                mock.patch("sys.stdout", new_callable=io.StringIO) as stdout,
            ):
                result = source_registry_access_audit.main()

        payload = json.loads(stdout.getvalue())
        self.assertEqual(1, result)
        self.assertEqual(
            "source_registry_entry_limit_exceeded",
            payload["diagnostics"][0]["code"],
        )
        self.assertEqual(2, payload["diagnostics"][0]["limit"])
        self.assertEqual(3, payload["diagnostics"][0]["observed"])
        transport.assert_not_called()
        executor.assert_not_called()

    def test_source_registry_rejects_scanned_file_substitution_before_open(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            references = root / "references"
            references.mkdir()
            candidate = references / "one.md"
            candidate.write_text("trusted\n", encoding="utf-8")
            displaced = references / "one-held.md"
            replacement = root / "private-sentinel.md"
            replacement.write_text("private sentinel\n", encoding="utf-8")
            real_open = source_registry_files.os.open
            swapped = False

            def swap_before_open(
                path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
                flags: int,
                mode: int = 0o777,
                *,
                dir_fd: int | None = None,
            ) -> int:
                nonlocal swapped
                if path == "one.md" and dir_fd is not None and not swapped:
                    swapped = True
                    candidate.rename(displaced)
                    replacement.rename(candidate)
                return real_open(path, flags, mode, dir_fd=dir_fd)

            with (
                mock.patch.object(
                    source_registry_files.os,
                    "open",
                    side_effect=swap_before_open,
                ),
                self.assertRaisesRegex(ValueError, "changed before it was opened"),
            ):
                source_registry_files.reference_directory_markdown_snapshots(
                    root,
                    Path("references"),
                )

        self.assertTrue(swapped)

    def test_source_registry_rejects_scanned_directory_substitution_before_descent(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            references = root / "references"
            nested = references / "nested"
            nested.mkdir(parents=True)
            (nested / "trusted.md").write_text("trusted\n", encoding="utf-8")
            displaced = references / "nested-held"
            replacement = root / "outside"
            replacement.mkdir()
            (replacement / "private.md").write_text(
                "private sentinel\n",
                encoding="utf-8",
            )
            real_open = source_registry_files.os.open
            swapped = False

            def swap_before_descent(
                path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
                flags: int,
                mode: int = 0o777,
                *,
                dir_fd: int | None = None,
            ) -> int:
                nonlocal swapped
                if path == "nested" and dir_fd is not None and not swapped:
                    swapped = True
                    nested.rename(displaced)
                    replacement.rename(nested)
                return real_open(path, flags, mode, dir_fd=dir_fd)

            with (
                mock.patch.object(
                    source_registry_files.os,
                    "open",
                    side_effect=swap_before_descent,
                ),
                self.assertRaisesRegex(ValueError, "changed before descent"),
            ):
                source_registry_files.reference_directory_markdown_snapshots(
                    root,
                    Path("references"),
                )

        self.assertTrue(swapped)

    def test_source_registry_aggregate_byte_limit_fails_before_network(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            references = root / "references"
            references.mkdir()
            (references / "one.md").write_text(
                "https://example.com/one\n",
                encoding="utf-8",
            )
            (references / "two.md").write_text(
                "https://example.com/two\n",
                encoding="utf-8",
            )
            with (
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "source_registry_access_audit.py",
                        "--root",
                        str(root),
                        "--reference-dir",
                        "references",
                        "--max-source-bytes",
                        "30",
                        "--format",
                        "json",
                    ],
                ),
                mock.patch.object(source_registry_access_audit, "safe_urlopen") as transport,
                mock.patch.object(source_registry_access_audit, "ThreadPoolExecutor") as executor,
                mock.patch("sys.stdout", new_callable=io.StringIO) as stdout,
            ):
                result = source_registry_access_audit.main()

        payload = json.loads(stdout.getvalue())
        self.assertEqual(1, result)
        self.assertEqual(
            "source_registry_byte_limit_exceeded",
            payload["diagnostics"][0]["code"],
        )
        self.assertEqual(30, payload["diagnostics"][0]["limit"])
        self.assertGreater(payload["diagnostics"][0]["observed"], 30)
        transport.assert_not_called()
        executor.assert_not_called()

    def test_source_registry_unique_url_limit_fails_before_executor_or_network(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            references = root / "references"
            references.mkdir()
            (references / "sources.md").write_text(
                "https://example.com/one\nhttps://example.com/two\n",
                encoding="utf-8",
            )
            with (
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "source_registry_access_audit.py",
                        "--root",
                        str(root),
                        "--reference-dir",
                        "references",
                        "--max-unique-urls",
                        "1",
                        "--format",
                        "json",
                    ],
                ),
                mock.patch.object(source_registry_access_audit, "safe_urlopen") as transport,
                mock.patch.object(source_registry_access_audit, "ThreadPoolExecutor") as executor,
                mock.patch("sys.stdout", new_callable=io.StringIO) as stdout,
            ):
                result = source_registry_access_audit.main()

        payload = json.loads(stdout.getvalue())
        self.assertEqual(1, result)
        self.assertEqual(
            "unique_url_limit_exceeded",
            payload["diagnostics"][0]["code"],
        )
        self.assertEqual(2, payload["diagnostics"][0]["observed"])
        transport.assert_not_called()
        executor.assert_not_called()

    def test_injected_snapshots_cannot_bypass_file_or_byte_limits(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            snapshots = (
                source_registry_files.MarkdownSnapshot(
                    root / "one.md",
                    "https://example.com/one\n",
                ),
                source_registry_files.MarkdownSnapshot(
                    root / "two.md",
                    "https://example.com/two\n",
                ),
            )
            file_limits = source_registry_access_audit.AuditLimits(
                max_source_files=1,
            )
            with self.assertRaises(
                source_registry_access_audit.AuditLimitError
            ) as file_failure:
                source_registry_access_audit.collect_urls(
                    root,
                    (),
                    False,
                    snapshots=snapshots,
                    limits=file_limits,
                )
            self.assertEqual(
                "source_registry_file_limit_exceeded",
                file_failure.exception.code,
            )

            byte_limits = source_registry_access_audit.AuditLimits(
                max_source_bytes=30,
            )
            with self.assertRaises(
                source_registry_access_audit.AuditLimitError
            ) as byte_failure:
                source_registry_access_audit.collect_urls(
                    root,
                    (),
                    False,
                    snapshots=snapshots,
                    limits=byte_limits,
                )
            self.assertEqual(
                "source_registry_byte_limit_exceeded",
                byte_failure.exception.code,
            )

    def test_injected_snapshot_rejects_huge_text_before_utf8_allocation(self) -> None:
        class EncodeMustNotRun(str):
            def encode(self, *_args: object, **_kwargs: object) -> bytes:
                raise AssertionError("oversized injected text reached UTF-8 encoding")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            snapshot = source_registry_files.MarkdownSnapshot(
                root / "oversized.md",
                EncodeMustNotRun(
                    "x" * (safe_paths.DEFAULT_JSON_INPUT_MAX_BYTES + 1)
                ),
            )

            with self.assertRaises(
                source_registry_access_audit.AuditLimitError
            ) as failure:
                source_registry_access_audit.collect_urls(
                    root,
                    (),
                    False,
                    snapshots=(snapshot,),
                )

        self.assertEqual("source_registry_byte_limit_exceeded", failure.exception.code)
        self.assertEqual(
            safe_paths.DEFAULT_JSON_INPUT_MAX_BYTES,
            failure.exception.limit,
        )
        self.assertEqual(
            safe_paths.DEFAULT_JSON_INPUT_MAX_BYTES + 1,
            failure.exception.observed,
        )

    def test_injected_snapshot_enforces_exact_utf8_byte_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            text = "é" * (safe_paths.DEFAULT_JSON_INPUT_MAX_BYTES // 2 + 1)
            snapshot = source_registry_files.MarkdownSnapshot(
                root / "multibyte.md",
                text,
            )

            with self.assertRaises(
                source_registry_access_audit.AuditLimitError
            ) as failure:
                source_registry_access_audit.collect_urls(
                    root,
                    (),
                    False,
                    snapshots=(snapshot,),
                )

        self.assertEqual("source_registry_byte_limit_exceeded", failure.exception.code)
        self.assertEqual(
            safe_paths.DEFAULT_JSON_INPUT_MAX_BYTES,
            failure.exception.limit,
        )
        self.assertEqual(
            safe_paths.DEFAULT_JSON_INPUT_MAX_BYTES + 2,
            failure.exception.observed,
        )

    def test_registry_inventory_progress_check_observes_non_markdown_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            references = root / "references"
            references.mkdir()
            (references / "padding.bin").write_bytes(b"padding")
            checks = 0

            def stop_after_directory() -> None:
                nonlocal checks
                checks += 1
                if checks == 2:
                    raise source_registry_access_audit.AuditLimitError(
                        "run_deadline_exceeded",
                        "whole-run monotonic deadline",
                        1.0,
                        1.0,
                        phase="source registry inventory",
                    )

            with self.assertRaises(
                source_registry_access_audit.AuditLimitError
            ):
                source_registry_files.registry_markdown_snapshots(
                    root,
                    Path("references"),
                    progress_check=stop_after_directory,
                )

        self.assertEqual(2, checks)

    def test_repeated_urls_cannot_bypass_total_reference_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            snapshot = source_registry_files.MarkdownSnapshot(
                root / "sources.md",
                "\n".join("https://example.com/same" for _ in range(3)),
            )
            limits = source_registry_access_audit.AuditLimits(
                max_unique_urls=1,
                max_url_references=2,
            )

            with self.assertRaises(
                source_registry_access_audit.AuditLimitError
            ) as failure:
                source_registry_access_audit.collect_urls(
                    root,
                    (),
                    False,
                    snapshots=(snapshot,),
                    limits=limits,
                )

        self.assertEqual("url_reference_limit_exceeded", failure.exception.code)
        self.assertEqual(3, failure.exception.observed)

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

    def test_redirect_attempts_consume_budget_before_transport(self) -> None:
        attempts: list[str] = []

        def redirecting_transport(request: Any, **_kwargs: object) -> _FakeResponse:
            attempts.append(request.full_url)
            headers = HTTPMessage()
            headers["Location"] = "/next"
            raise HTTPError(request.full_url, 302, "Found", headers, None)

        budget = source_registry_access_audit.TransportRequestBudget(1)
        with (
            mock.patch.object(
                source_registry_access_audit,
                "safe_urlopen",
                side_effect=redirecting_transport,
            ),
            self.assertRaises(source_registry_access_audit.AuditLimitError) as raised,
        ):
            source_registry_access_audit.request_with_redirects(
                "https://example.com/start",
                "GET",
                1.0,
                32,
                "test-agent",
                request_budget=budget,
            )

        self.assertEqual("transport_request_limit_exceeded", raised.exception.code)
        self.assertEqual(["https://example.com/start"], attempts)
        self.assertEqual(1, budget.used)

    def test_head_get_and_robots_each_consume_transport_budget(self) -> None:
        attempts: list[tuple[str, str]] = []

        def fake_transport(request: Any, **_kwargs: object) -> _FakeResponse:
            method = request.get_method()
            attempts.append((method, request.full_url))
            if method == "HEAD":
                raise HTTPError(request.full_url, 405, "Method Not Allowed", HTTPMessage(), None)
            if request.full_url.endswith("/robots.txt"):
                return _FakeResponse(
                    request.full_url,
                    body=b"User-agent: *\nAllow: /\n",
                )
            return _FakeResponse(request.full_url)

        refs = [source_registry_access_audit.UrlRef("sources.md", 1, True)]
        budget = source_registry_access_audit.TransportRequestBudget(3)
        with mock.patch.object(
            source_registry_access_audit,
            "safe_urlopen",
            side_effect=fake_transport,
        ):
            row = source_registry_access_audit.audit_url(
                "https://example.com/source",
                refs,
                1.0,
                32,
                "test-agent",
                True,
                request_budget=budget,
            )

        self.assertTrue(row.ok)
        self.assertEqual("allow", row.robots)
        self.assertEqual(3, budget.used)
        self.assertEqual(
            [
                ("HEAD", "https://example.com/source"),
                ("GET", "https://example.com/source"),
                ("GET", "https://example.com/robots.txt"),
            ],
            attempts,
        )

        attempts.clear()
        limited_budget = source_registry_access_audit.TransportRequestBudget(2)
        with (
            mock.patch.object(
                source_registry_access_audit,
                "safe_urlopen",
                side_effect=fake_transport,
            ),
            self.assertRaises(source_registry_access_audit.AuditLimitError) as raised,
        ):
            source_registry_access_audit.audit_url(
                "https://example.com/source",
                refs,
                1.0,
                32,
                "test-agent",
                True,
                request_budget=limited_budget,
            )
        self.assertEqual("transport_request_limit_exceeded", raised.exception.code)
        self.assertEqual(2, len(attempts))
        self.assertEqual(2, limited_budget.used)

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

    def test_source_registry_cli_normalizes_path_binding_failure(self) -> None:
        binding_error = safe_paths.OutputDirectoryBindingError(
            Path("/fixture/references"),
            "references",
            (),
            RuntimeError("unsafe\n" + "x" * 2_000),
        )
        with (
            mock.patch.object(
                source_registry_access_audit,
                "registry_snapshots",
                side_effect=binding_error,
            ),
            mock.patch.object(
                sys,
                "argv",
                ["source_registry_access_audit.py", "--format", "json"],
            ),
            mock.patch.object(
                source_registry_access_audit,
                "safe_urlopen",
            ) as transport,
            mock.patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            result = source_registry_access_audit.main()

        payload = json.loads(stdout.getvalue())
        self.assertEqual(1, result)
        self.assertEqual([], payload["rows"])
        self.assertEqual(
            "source_registry_path_binding_rejected",
            payload["diagnostics"][0]["code"],
        )
        diagnostic = payload["diagnostics"][0]["message"]
        self.assertTrue(
            diagnostic.startswith("source registry path binding rejected:")
        )
        self.assertLessEqual(
            len(diagnostic),
            source_registry_access_audit.MAX_INPUT_DIAGNOSTIC_CHARS,
        )
        self.assertNotIn("\n", diagnostic)
        transport.assert_not_called()

    def test_source_registry_cli_normalizes_late_audit_binding_failure(self) -> None:
        binding_error = safe_paths.OutputDirectoryBindingError(
            Path("/fixture/references"),
            "references",
            (),
            RuntimeError("late binding failure"),
        )
        snapshot = source_registry_files.MarkdownSnapshot(
            Path("/fixture/SOURCE_PACKS.md"),
            "https://example.com/source\n",
        )
        with (
            mock.patch.object(
                source_registry_access_audit,
                "registry_snapshots",
                return_value=(snapshot,),
            ),
            mock.patch.object(
                source_registry_access_audit,
                "run_audit",
                side_effect=binding_error,
            ),
            mock.patch.object(
                sys,
                "argv",
                ["source_registry_access_audit.py", "--format", "json"],
            ),
            mock.patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            result = source_registry_access_audit.main()

        payload = json.loads(stdout.getvalue())
        self.assertEqual(1, result)
        self.assertEqual(
            "source_registry_path_binding_rejected",
            payload["diagnostics"][0]["code"],
        )
        self.assertEqual(
            "source registry audit setup",
            payload["diagnostics"][0]["phase"],
        )

    def test_source_registry_audit_bounds_pending_future_submissions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            snapshot = source_registry_files.MarkdownSnapshot(
                root / "sources.md",
                "\n".join(
                    f"https://example.com/source-{index}"
                    for index in range(9)
                ),
            )
            args = source_registry_access_audit.build_parser().parse_args(
                ["--root", str(root), "--workers", "2"]
            )
            executors: list[_DeterministicExecutor] = []
            pending_seen: list[int] = []

            def executor_factory(*, max_workers: int) -> Executor:
                executor = _DeterministicExecutor(max_workers=max_workers)
                executors.append(executor)
                return executor

            def deterministic_wait(
                futures: set[Future[Any]],
                **_kwargs: object,
            ) -> tuple[set[Future[Any]], set[Future[Any]]]:
                pending_seen.append(len(futures))
                completed = executors[0].release_one(futures)
                return {completed}, futures - {completed}

            with (
                mock.patch.object(
                    source_registry_access_audit,
                    "wait",
                    side_effect=deterministic_wait,
                ),
                mock.patch.object(
                    source_registry_access_audit,
                    "ThreadPoolExecutor",
                    side_effect=executor_factory,
                ),
                mock.patch.object(
                    source_registry_access_audit,
                    "safe_urlopen",
                    side_effect=lambda request, **_kwargs: _FakeResponse(
                        request.full_url
                    ),
                ),
            ):
                rows = source_registry_access_audit.run_audit(
                    args,
                    snapshots=(snapshot,),
                )

        self.assertEqual(9, len(rows))
        self.assertEqual(4, max(pending_seen))
        self.assertEqual(4, executors[0].max_unresolved)
        self.assertTrue(executors[0].shutdown_called)

    def test_whole_run_deadline_cancels_unstarted_bounded_work(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            snapshot = source_registry_files.MarkdownSnapshot(
                root / "sources.md",
                "\n".join(
                    f"https://example.com/source-{index}"
                    for index in range(5)
                ),
            )
            args = source_registry_access_audit.build_parser().parse_args(
                ["--root", str(root), "--workers", "1"]
            )
            fake_clock = _FakeClock()
            deadline = source_registry_access_audit.MonotonicDeadline(
                1.0,
                clock=fake_clock,
            )
            executors: list[_DeterministicExecutor] = []
            transport_attempts = 0

            def executor_factory(*, max_workers: int) -> Executor:
                executor = _DeterministicExecutor(max_workers=max_workers)
                executors.append(executor)
                return executor

            def deterministic_wait(
                futures: set[Future[Any]],
                **_kwargs: object,
            ) -> tuple[set[Future[Any]], set[Future[Any]]]:
                completed = executors[0].release_one(futures)
                return {completed}, futures - {completed}

            def advancing_transport(request: Any, **_kwargs: object) -> _FakeResponse:
                nonlocal transport_attempts
                transport_attempts += 1
                fake_clock.advance(2.0)
                return _FakeResponse(request.full_url)

            with (
                mock.patch.object(
                    source_registry_access_audit,
                    "wait",
                    side_effect=deterministic_wait,
                ),
                mock.patch.object(
                    source_registry_access_audit,
                    "ThreadPoolExecutor",
                    side_effect=executor_factory,
                ),
                mock.patch.object(
                    source_registry_access_audit,
                    "safe_urlopen",
                    side_effect=advancing_transport,
                ),
                self.assertRaises(source_registry_access_audit.AuditLimitError) as raised,
            ):
                source_registry_access_audit.run_audit(
                    args,
                    snapshots=(snapshot,),
                    deadline=deadline,
                )

        self.assertEqual("run_deadline_exceeded", raised.exception.code)
        self.assertEqual(2, len(executors[0].jobs))
        self.assertEqual(1, executors[0].cancelled_before_shutdown)
        self.assertEqual(1, transport_attempts)
