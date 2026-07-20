"""External URL safety and redirect-gating tests."""

from __future__ import annotations

from http.client import HTTPMessage
import io
import unittest
from unittest import mock

from tests.validation_test_support import SCRIPTS_DIR as _SCRIPTS_DIR

import link_check  # noqa: E402
import url_safety  # noqa: E402


class UrlSafetyTests(unittest.TestCase):
    def test_url_safety_rejects_private_dns_resolution_and_redirects(self) -> None:
        request = link_check.Request("https://example.com/status")
        with mock.patch.object(
            url_safety.socket,
            "getaddrinfo",
            return_value=[(url_safety.socket.AF_INET, url_safety.socket.SOCK_STREAM, 6, "", ("10.0.0.8", 443))],
        ):
            with self.assertRaises(ValueError) as exc:
                url_safety.safe_urlopen(request, timeout=0.25)
        self.assertIn("resolves to non-public address", str(exc.exception))

        handler = url_safety.SafeRedirectHandler()
        with self.assertRaises(url_safety.HTTPError) as redirect_exc:
            handler.redirect_request(
                link_check.Request("https://example.com/status"),
                io.BytesIO(),
                302,
                "Found",
                HTTPMessage(),
                "https://169.254.169.254/latest/meta-data",
            )
        self.assertIn("unsafe redirect target", str(redirect_exc.exception))
        redirect_exc.exception.close()

    def test_url_safety_resolves_redirect_locations_only_through_the_safe_target_gate(self) -> None:
        target, error = url_safety.safe_redirect_target(
            "https://example.com/a/start",
            "../next",
        )
        self.assertEqual("https://example.com/next", target)
        self.assertIsNone(error)

        for location in (
            "http://example.com/plaintext",
            "https://localhost/private",
            "https://" + "user:" + "password@" + "example.com/private",
        ):
            with self.subTest(location=location):
                target, error = url_safety.safe_redirect_target(
                    "https://example.com/start",
                    location,
                )
                self.assertIsNone(target)
                self.assertIsNotNone(error)

    def test_url_safety_propagates_redirect_bound_to_opener(self) -> None:
        opener = mock.MagicMock()
        response = object()
        opener.open.return_value = response
        public_dns = [
            (
                url_safety.socket.AF_INET,
                url_safety.socket.SOCK_STREAM,
                6,
                "",
                ("93.184.216.34", 443),
            )
        ]

        with (
            mock.patch.object(url_safety.socket, "getaddrinfo", return_value=public_dns),
            mock.patch.object(url_safety, "build_opener", return_value=opener) as build_opener,
        ):
            result = url_safety.safe_urlopen(
                link_check.Request("https://example.com/status"),
                timeout=0.25,
                max_redirects=2,
            )

        self.assertIs(response, result)
        proxy_handler, redirect_handler = build_opener.call_args.args
        self.assertEqual({}, proxy_handler.proxies)
        self.assertEqual(2, redirect_handler.max_redirections)
        with self.assertRaisesRegex(ValueError, "max_redirects must be non-negative"):
            url_safety.safe_urlopen(
                link_check.Request("https://example.com/status"),
                timeout=0.25,
                max_redirects=-1,
            )

    def test_url_safety_rejects_local_use_hostname_suffixes_without_resolution(self) -> None:
        cases = (
            "https://service.internal/status",
            "https://printer.lan/status",
            "https://device.local/status",
            "https://gateway.home.arpa/status",
        )
        for url in cases:
            with self.subTest(url=url):
                self.assertIn("local-use hostname", url_safety.blocked_external_url_reason(url) or "")

    def test_url_safety_uses_vetted_resolution_for_actual_connection(self) -> None:
        calls = []
        lock_events = []

        def fake_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):  # type: ignore[no-untyped-def]
            calls.append((host, port))
            return [(url_safety.socket.AF_INET, url_safety.socket.SOCK_STREAM, 6, "", ("93.184.216.34", port or 443))]

        class FakeOpener:
            def open(self, _request, timeout):  # type: ignore[no-untyped-def]
                return url_safety.socket.getaddrinfo("example.com", 443)

        class FakeLock:
            def __enter__(self):  # type: ignore[no-untyped-def]
                lock_events.append("enter")
                return self

            def __exit__(self, exc_type, exc, tb):  # type: ignore[no-untyped-def]
                lock_events.append("exit")
                return False

        with mock.patch.object(url_safety.socket, "getaddrinfo", fake_getaddrinfo):
            with mock.patch.object(url_safety, "build_opener", return_value=FakeOpener()):
                with mock.patch.object(url_safety, "SAFE_URLOPEN_LOCK", FakeLock()):
                    result = url_safety.safe_urlopen(link_check.Request("https://example.com/status"), timeout=0.25)

        self.assertEqual([(url_safety.socket.AF_INET, url_safety.socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))], result)
        self.assertEqual([("example.com", 443)], calls)
        self.assertEqual(["enter", "exit"], lock_events)
