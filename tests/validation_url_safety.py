"""External URL safety and redirect-gating tests."""

from __future__ import annotations

from http.client import HTTPMessage
import io
import socket
import threading
import time
import unittest
from unittest import mock

from tests.validation_test_support import SCRIPTS_DIR as _SCRIPTS_DIR

import link_check  # noqa: E402
import url_safety  # noqa: E402


class UrlSafetyTests(unittest.TestCase):
    def _assert_fixture_threads_stopped(
        self,
        workers: list[threading.Thread],
    ) -> None:
        for worker in workers:
            worker.join(timeout=1.0)
            self.assertFalse(
                worker.is_alive(),
                f"fixture worker did not stop: {worker.name}",
            )

    def test_network_deadline_cancel_joins_owned_watchdog(self) -> None:
        timer = mock.MagicMock()
        with mock.patch.object(
            url_safety.threading,
            "Timer",
            return_value=timer,
        ):
            deadline = url_safety._NetworkDeadline(1.0)
            deadline.cancel()

        self.assertEqual(
            [mock.call.start(), mock.call.cancel(), mock.call.join()],
            timer.method_calls,
        )

        owner_timer = mock.MagicMock()
        with (
            mock.patch.object(
                url_safety.threading,
                "Timer",
                return_value=owner_timer,
            ),
            mock.patch.object(
                url_safety.threading,
                "current_thread",
                return_value=owner_timer,
            ),
        ):
            deadline = url_safety._NetworkDeadline(1.0)
            deadline.cancel()

        self.assertEqual(
            [mock.call.start(), mock.call.cancel()],
            owner_timer.method_calls,
        )

    def test_optional_hostname_resolution_is_bounded_cached_and_cancelled(
        self,
    ) -> None:
        release = threading.Event()
        started = threading.Event()
        resolver_slot = threading.BoundedSemaphore(1)
        resolver_workers: list[threading.Thread] = []
        created_deadlines: list[TrackingDeadline] = []
        real_deadline_type = url_safety._NetworkDeadline

        class TrackingDeadline(real_deadline_type):
            def __init__(self, seconds: float) -> None:
                self.cancelled_by_owner = False
                super().__init__(seconds)
                created_deadlines.append(self)

            def cancel(self) -> None:
                self.cancelled_by_owner = True
                super().cancel()

        def assert_resolver_stopped() -> None:
            self._assert_fixture_threads_stopped(resolver_workers)
            acquired = resolver_slot.acquire(blocking=False)
            if acquired:
                resolver_slot.release()
            self.assertTrue(acquired)

        self.addCleanup(assert_resolver_stopped)
        self.addCleanup(release.set)

        def blocked_resolution(*_args):  # type: ignore[no-untyped-def]
            resolver_workers.append(threading.current_thread())
            started.set()
            if not release.wait(timeout=1.0):
                raise TimeoutError(
                    "blocked resolver fixture exceeded its independent escape"
                )
            return [
                (
                    url_safety.socket.AF_INET,
                    url_safety.socket.SOCK_STREAM,
                    6,
                    "",
                    ("93.184.216.34", 443),
                )
            ]

        cache: url_safety.HostnameResolutionCache = {}
        with (
            mock.patch.object(
                url_safety.socket,
                "getaddrinfo",
                side_effect=blocked_resolution,
            ) as resolver,
            mock.patch.object(url_safety, "_RESOLVER_SLOT", resolver_slot),
            mock.patch.object(url_safety, "_NetworkDeadline", TrackingDeadline),
        ):
            first_issue = url_safety.blocked_external_url_reason(
                "https://example.com/one",
                resolve_hostname=True,
                hostname_resolution_timeout_seconds=0.04,
                hostname_resolution_cache=cache,
            )
            second_issue = url_safety.blocked_external_url_reason(
                "https://example.com/two",
                resolve_hostname=True,
                hostname_resolution_timeout_seconds=0.04,
                hostname_resolution_cache=cache,
            )

        self.assertTrue(started.is_set())
        self.assertTrue(resolver_workers[0].is_alive())
        self.assertIn("total network deadline exceeded", first_issue or "")
        self.assertEqual(first_issue, second_issue)
        resolver.assert_called_once()
        self.assertEqual(1, len(created_deadlines))
        self.assertTrue(created_deadlines[0].cancelled_by_owner)
        with self.assertRaisesRegex(ValueError, "at most 30s"):
            url_safety.blocked_external_url_reason(
                "https://example.com/three",
                resolve_hostname=True,
                hostname_resolution_timeout_seconds=30.01,
                hostname_resolution_cache=cache,
            )

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
        response = mock.MagicMock()
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

        self.assertIs(response, result._response)
        proxy_handler, redirect_handler, deadline_handler = build_opener.call_args.args
        self.assertEqual({}, proxy_handler.proxies)
        self.assertEqual(2, redirect_handler.max_redirections)
        self.assertIsInstance(deadline_handler, url_safety._DeadlineHTTPSHandler)
        result.close()
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

    def test_url_safety_rejects_site_local_ipv6_and_controls(self) -> None:
        self.assertIn(
            "non-public address",
            url_safety.blocked_external_url_reason("https://[fec0::1]/status") or "",
        )
        records = [
            (
                url_safety.socket.AF_INET6,
                url_safety.socket.SOCK_STREAM,
                6,
                "",
                ("fec0::1", 443, 0, 0),
            )
        ]
        self.assertIn(
            "resolves to non-public address",
            "; ".join(url_safety.resolved_address_issues_from_records(records)),
        )
        self.assertIsNone(
            url_safety.non_public_address_reason(
                "2606:4700:4700::1111",
                resolved=False,
            )
        )
        for control in ("\x00", "\x1b", "\x7f", "\x9b"):
            with self.subTest(control=repr(control)):
                self.assertIn(
                    "control or format characters",
                    url_safety.blocked_external_url_reason(
                        f"https://example.com/a{control}b"
                    )
                    or "",
                )
        for formatting in ("\u2028", "\u202e"):
            with self.subTest(formatting=repr(formatting)):
                self.assertIn(
                    "control or format characters",
                    url_safety.blocked_external_url_reason(
                        f"https://example.com/a{formatting}b"
                    )
                    or "",
                )

    def test_url_safety_rejects_multicast_literals_and_dns_answers(self) -> None:
        literal_cases = (
            "https://224.0.0.1/status",
            "https://[ff02::1]/status",
        )
        for url in literal_cases:
            with self.subTest(url=url):
                self.assertIn(
                    "points to multicast address",
                    url_safety.blocked_external_url_reason(url) or "",
                )

        record_cases = (
            (
                url_safety.socket.AF_INET,
                url_safety.socket.SOCK_STREAM,
                6,
                "",
                ("239.255.255.250", 443),
            ),
            (
                url_safety.socket.AF_INET6,
                url_safety.socket.SOCK_STREAM,
                6,
                "",
                ("ff0e::1", 443, 0, 0),
            ),
        )
        for record in record_cases:
            with self.subTest(record=record):
                self.assertIn(
                    "resolves to multicast address",
                    "; ".join(
                        url_safety.resolved_address_issues_from_records([record])
                    ),
                )
                with (
                    mock.patch.object(
                        url_safety.socket,
                        "getaddrinfo",
                        return_value=[record],
                    ),
                    self.assertRaisesRegex(
                        ValueError,
                        "resolves to multicast address",
                    ),
                ):
                    url_safety.safe_urlopen(
                        link_check.Request("https://example.com/status"),
                        timeout=0.25,
                    )

    def test_url_safety_enforces_total_deadline_during_headers(self) -> None:
        writer_workers: list[threading.Thread] = []
        self.addCleanup(self._assert_fixture_threads_stopped, writer_workers)
        public_dns = [
            (
                url_safety.socket.AF_INET,
                url_safety.socket.SOCK_STREAM,
                6,
                "",
                ("93.184.216.34", 443),
            )
        ]

        class SlowHeaderOpener:
            def __init__(self, deadline: url_safety._NetworkDeadline) -> None:
                self.deadline = deadline

            def open(self, _request, timeout):  # type: ignore[no-untyped-def]
                client, server = socket.socketpair()
                self.deadline.attach(client)

                def drip() -> None:
                    try:
                        for byte in b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n":
                            server.sendall(bytes((byte,)))
                            time.sleep(0.02)
                    except OSError:
                        pass
                    finally:
                        server.close()

                worker = threading.Thread(target=drip, daemon=True)
                writer_workers.append(worker)
                worker.start()
                response = url_safety.http.client.HTTPResponse(client)
                try:
                    response.begin()
                finally:
                    client.close()
                return response

        def build_slow_opener(*handlers):  # type: ignore[no-untyped-def]
            return SlowHeaderOpener(handlers[2]._deadline)

        started = time.monotonic()
        with (
            mock.patch.object(url_safety.socket, "getaddrinfo", return_value=public_dns),
            mock.patch.object(url_safety, "build_opener", side_effect=build_slow_opener),
            self.assertRaisesRegex(TimeoutError, "total network deadline"),
        ):
            url_safety.safe_urlopen(
                link_check.Request("https://example.com/status"),
                timeout=0.08,
            )
        self.assertLess(time.monotonic() - started, 0.5)

    def test_url_safety_enforces_total_deadline_during_body_and_preserves_fast_body(self) -> None:
        writer_workers: list[threading.Thread] = []
        self.addCleanup(self._assert_fixture_threads_stopped, writer_workers)
        public_dns = [
            (
                url_safety.socket.AF_INET,
                url_safety.socket.SOCK_STREAM,
                6,
                "",
                ("93.184.216.34", 443),
            )
        ]

        class BodyOpener:
            def __init__(self, deadline: url_safety._NetworkDeadline, *, slow: bool) -> None:
                self.deadline = deadline
                self.slow = slow

            def open(self, _request, timeout):  # type: ignore[no-untyped-def]
                client, server = socket.socketpair()
                self.deadline.attach(client)

                def write_response() -> None:
                    try:
                        server.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 6\r\n\r\n")
                        if self.slow:
                            for byte in b"abcdef":
                                server.sendall(bytes((byte,)))
                                time.sleep(0.03)
                        else:
                            server.sendall(b"abcdef")
                    except OSError:
                        pass
                    finally:
                        server.close()

                worker = threading.Thread(target=write_response, daemon=True)
                writer_workers.append(worker)
                worker.start()
                response = url_safety.http.client.HTTPResponse(client)
                response.begin()
                client.close()
                return response

        def slow_builder(*handlers):  # type: ignore[no-untyped-def]
            return BodyOpener(handlers[2]._deadline, slow=True)

        with (
            mock.patch.object(url_safety.socket, "getaddrinfo", return_value=public_dns),
            mock.patch.object(url_safety, "build_opener", side_effect=slow_builder),
        ):
            response = url_safety.safe_urlopen(
                link_check.Request("https://example.com/status"),
                timeout=0.08,
            )
            with response, self.assertRaisesRegex(TimeoutError, "total network deadline"):
                response.read(6)

        def fast_builder(*handlers):  # type: ignore[no-untyped-def]
            return BodyOpener(handlers[2]._deadline, slow=False)

        with (
            mock.patch.object(url_safety.socket, "getaddrinfo", return_value=public_dns),
            mock.patch.object(url_safety, "build_opener", side_effect=fast_builder),
        ):
            with url_safety.safe_urlopen(
                link_check.Request("https://example.com/status"),
                timeout=1.0,
            ) as response:
                payload = bytearray(6)
                self.assertEqual(6, response.readinto1(payload))
                self.assertEqual(b"abcdef", bytes(payload))

    def test_url_safety_bounds_hostname_resolution_by_total_deadline(self) -> None:
        finished = threading.Event()
        resolver_slot = threading.BoundedSemaphore(1)
        resolver_workers: list[threading.Thread] = []

        def assert_resolver_stopped() -> None:
            self._assert_fixture_threads_stopped(resolver_workers)
            acquired = resolver_slot.acquire(blocking=False)
            if acquired:
                resolver_slot.release()
            self.assertTrue(acquired)

        self.addCleanup(assert_resolver_stopped)

        def slow_resolution(*_args):  # type: ignore[no-untyped-def]
            resolver_workers.append(threading.current_thread())
            try:
                time.sleep(0.25)
                return [
                    (
                        url_safety.socket.AF_INET,
                        url_safety.socket.SOCK_STREAM,
                        6,
                        "",
                        ("93.184.216.34", 443),
                    )
                ]
            finally:
                finished.set()

        started = time.monotonic()
        with (
            mock.patch.object(url_safety.socket, "getaddrinfo", side_effect=slow_resolution),
            mock.patch.object(url_safety, "_RESOLVER_SLOT", resolver_slot),
            self.assertRaisesRegex(TimeoutError, "total network deadline"),
        ):
            url_safety.safe_urlopen(
                link_check.Request("https://example.com/status"),
                timeout=0.05,
            )
        self.assertLess(time.monotonic() - started, 0.2)
        self.assertTrue(finished.wait(1.0))

    def test_url_safety_bounds_abandoned_resolver_threads(self) -> None:
        release = threading.Event()
        first_started = threading.Event()
        resolver_slot = threading.BoundedSemaphore(1)
        resolver_workers: list[threading.Thread] = []
        call_count = 0

        def assert_resolver_stopped() -> None:
            self._assert_fixture_threads_stopped(resolver_workers)
            acquired = resolver_slot.acquire(blocking=False)
            if acquired:
                resolver_slot.release()
            self.assertTrue(acquired)

        self.addCleanup(assert_resolver_stopped)
        self.addCleanup(release.set)

        def stuck_resolution(*_args):  # type: ignore[no-untyped-def]
            nonlocal call_count
            resolver_workers.append(threading.current_thread())
            call_count += 1
            first_started.set()
            release.wait(1.0)
            return [
                (
                    url_safety.socket.AF_INET,
                    url_safety.socket.SOCK_STREAM,
                    6,
                    "",
                    ("93.184.216.34", 443),
                )
            ]

        with mock.patch.object(
            url_safety.socket,
            "getaddrinfo",
            side_effect=stuck_resolution,
        ), mock.patch.object(url_safety, "_RESOLVER_SLOT", resolver_slot):
            for _attempt in range(2):
                with self.assertRaisesRegex(
                    TimeoutError,
                    "total network deadline",
                ):
                    url_safety.safe_urlopen(
                        link_check.Request("https://example.com/status"),
                        timeout=0.04,
                    )
            self.assertTrue(first_started.is_set())
            self.assertEqual(1, call_count)

    def test_deadline_https_connection_arms_watchdog_before_handshake(self) -> None:
        deadline = mock.MagicMock(spec=url_safety._NetworkDeadline)
        deadline.remaining.return_value = 1.0
        deadline.expired.return_value = False
        raw_socket = mock.MagicMock(spec=socket.socket)
        wrapped_socket = mock.MagicMock()
        context = mock.MagicMock()
        context.wrap_socket.return_value = wrapped_socket
        connection = url_safety._DeadlineHTTPSConnection(
            "example.com",
            deadline=deadline,
            context=context,
        )

        def establish(instance):  # type: ignore[no-untyped-def]
            instance.sock = raw_socket

        with mock.patch.object(
            url_safety.http.client.HTTPConnection,
            "connect",
            autospec=True,
            side_effect=establish,
        ):
            connection.connect()

        context.wrap_socket.assert_called_once_with(
            raw_socket,
            server_hostname="example.com",
            do_handshake_on_connect=False,
        )
        deadline.detach.assert_called_once_with(raw_socket)
        deadline.attach.assert_called_once_with(wrapped_socket)
        wrapped_socket.do_handshake.assert_called_once_with()
        self.assertIs(wrapped_socket, connection.sock)

    def test_url_safety_feeds_one_vetted_resolution_to_socket_connect(self) -> None:
        resolver_calls: list[tuple[object, ...]] = []
        connect_calls: list[tuple[str, int]] = []
        vetted_record = (
            url_safety.socket.AF_INET,
            url_safety.socket.SOCK_STREAM,
            6,
            "",
            ("93.184.216.34", 443),
        )

        def one_shot_getaddrinfo(
            host,
            port,
            family=0,
            type=0,
            proto=0,
            flags=0,
        ):  # type: ignore[no-untyped-def]
            resolver_calls.append((host, port, family, type, proto, flags))
            if len(resolver_calls) > 1:
                raise AssertionError(
                    "connection attempted a second raw hostname resolution"
                )
            return [vetted_record]

        class ConnectedSocket:
            def __init__(self, family: int, socktype: int, proto: int) -> None:
                self.family = family
                self.socktype = socktype
                self.proto = proto
                self.closed = False
                self.timeout: float | None = None

            def settimeout(self, timeout: float) -> None:
                self.timeout = timeout

            def bind(self, _address: tuple[str, int]) -> None:
                raise AssertionError("test connection unexpectedly bound a source address")

            def connect(self, address: tuple[str, int]) -> None:
                connect_calls.append(address)

            def shutdown(self, _how: int) -> None:
                pass

            def close(self) -> None:
                self.closed = True

        sockets: list[ConnectedSocket] = []

        def socket_factory(
            family: int,
            socktype: int,
            proto: int,
        ) -> ConnectedSocket:
            connected = ConnectedSocket(family, socktype, proto)
            sockets.append(connected)
            return connected

        class ConnectingOpener:
            def __init__(self, deadline: url_safety._NetworkDeadline) -> None:
                self.deadline = deadline

            def open(self, _request, timeout):  # type: ignore[no-untyped-def]
                connection = url_safety._DeadlineHTTPSConnection(
                    "example.com",
                    deadline=self.deadline,
                    context=mock.MagicMock(),
                )
                connected = connection._create_connection(
                    ("example.com", 443),
                    timeout,
                    None,
                )
                response = mock.MagicMock()
                response.connected_socket = connected
                response.close.side_effect = connected.close
                return response

        def build_connecting_opener(*handlers):  # type: ignore[no-untyped-def]
            deadline_handler = handlers[2]
            self.assertIsInstance(
                deadline_handler,
                url_safety._DeadlineHTTPSHandler,
            )
            return ConnectingOpener(deadline_handler._deadline)

        with (
            mock.patch.object(
                url_safety.socket,
                "getaddrinfo",
                side_effect=one_shot_getaddrinfo,
            ),
            mock.patch.object(
                url_safety.socket,
                "socket",
                side_effect=socket_factory,
            ),
            mock.patch.object(
                url_safety,
                "build_opener",
                side_effect=build_connecting_opener,
            ),
        ):
            result = url_safety.safe_urlopen(
                link_check.Request("https://example.com/status"),
                timeout=0.25,
            )

        self.assertEqual(1, len(resolver_calls))
        self.assertEqual([vetted_record[4]], connect_calls)
        self.assertEqual(1, len(sockets))
        self.assertIs(sockets[0], result._response.connected_socket)
        result.close()
        self.assertTrue(sockets[0].closed)
