#!/usr/bin/env python3

from __future__ import annotations

import http.client
import ipaddress
import math
import socket
import ssl
import threading
import time
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import (
    HTTPRedirectHandler,
    HTTPSHandler,
    ProxyHandler,
    Request,
    build_opener,
)


LOCAL_HOSTNAMES = {"localhost"}
LOCAL_USE_HOSTNAMES = {"home.arpa", "internal", "lan", "local"}
LOCAL_USE_SUFFIXES = tuple(f".{name}" for name in LOCAL_USE_HOSTNAMES)
ALLOWED_EXTERNAL_SCHEMES = {"https"}
SAFE_URLOPEN_LOCK = threading.Lock()
_RESOLVER_SLOT = threading.BoundedSemaphore(1)
DEFAULT_HOSTNAME_RESOLUTION_TIMEOUT_SECONDS = 5.0
MAX_HOSTNAME_RESOLUTION_TIMEOUT_SECONDS = 30.0

HostnameResolutionCache = dict[
    tuple[str, int | None],
    tuple[str, ...],
]
_HOSTNAME_RESOLUTION_TERMINAL_CACHE_KEY = ("\0", None)


class _NetworkDeadline:
    """One monotonic deadline shared by resolution, opening, and body reads."""

    def __init__(self, seconds: float, *, clock=time.monotonic) -> None:  # type: ignore[no-untyped-def]
        duration = float(seconds)
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("timeout must be a positive finite number")
        self.duration = duration
        self._clock = clock
        self._expires_at = clock() + duration
        self._lock = threading.Lock()
        self._sockets: set[socket.socket] = set()
        self._expired = False
        self._cancelled = False
        self._timer = threading.Timer(duration, self._expire)
        self._timer.daemon = True
        self._timer.start()

    def error(self) -> TimeoutError:
        return TimeoutError(
            f"total network deadline exceeded after {self.duration:g}s"
        )

    def _expire(self) -> None:
        with self._lock:
            if self._cancelled or self._expired:
                return
            self._expired = True
            sockets = tuple(self._sockets)
        for attached in sockets:
            try:
                attached.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                attached.close()
            except OSError:
                pass

    def expired(self) -> bool:
        if self._clock() >= self._expires_at:
            self._expire()
        with self._lock:
            return self._expired

    def remaining(self) -> float:
        remaining = self._expires_at - self._clock()
        if remaining <= 0:
            self._expire()
            raise self.error()
        with self._lock:
            if self._expired:
                raise self.error()
        return remaining

    def attach(self, attached: socket.socket) -> socket.socket:
        try:
            remaining = self.remaining()
        except Exception:
            attached.close()
            raise
        with self._lock:
            if self._expired or self._cancelled:
                attached.close()
                raise self.error()
            self._sockets.add(attached)
        try:
            attached.settimeout(remaining)
        except Exception:
            self.detach(attached)
            raise
        return attached

    def detach(self, attached: socket.socket) -> None:
        with self._lock:
            self._sockets.discard(attached)

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True
            self._sockets.clear()
        self._timer.cancel()
        if threading.current_thread() is not self._timer:
            self._timer.join()


class _DeadlineResponse:
    """Delegate an HTTP response while enforcing its opener's total deadline."""

    def __init__(self, response, deadline: _NetworkDeadline) -> None:  # type: ignore[no-untyped-def]
        self._response = response
        self._deadline = deadline

    def __getattr__(self, name: str):  # type: ignore[no-untyped-def]
        return getattr(self._response, name)

    def __enter__(self):  # type: ignore[no-untyped-def]
        self._deadline.remaining()
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:  # type: ignore[no-untyped-def]
        self.close()
        return False

    def close(self) -> None:
        try:
            self._response.close()
        finally:
            self._deadline.cancel()

    def _read(self, method: str, *args, **kwargs):  # type: ignore[no-untyped-def]
        self._deadline.remaining()
        try:
            result = getattr(self._response, method)(*args, **kwargs)
        except Exception as exc:
            if self._deadline.expired():
                raise self._deadline.error() from exc
            raise
        self._deadline.remaining()
        return result

    def read(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return self._read("read", *args, **kwargs)

    def read1(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return self._read("read1", *args, **kwargs)

    def readinto(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return self._read("readinto", *args, **kwargs)

    def readinto1(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return self._read("readinto1", *args, **kwargs)

    def readline(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return self._read("readline", *args, **kwargs)

    def readlines(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return self._read("readlines", *args, **kwargs)

    def peek(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return self._read("peek", *args, **kwargs)

    def __iter__(self):  # type: ignore[no-untyped-def]
        return self

    def __next__(self):  # type: ignore[no-untyped-def]
        line = self.readline()
        if line:
            return line
        raise StopIteration


def _resolve_with_deadline(
    resolver,  # type: ignore[no-untyped-def]
    arguments: tuple[object, ...],
    deadline: _NetworkDeadline,
) -> list[tuple]:
    result: list[list[tuple]] = []
    failure: list[Exception] = []
    resolver_slot = _RESOLVER_SLOT

    def resolve() -> None:
        try:
            result.append(resolver(*arguments))
        except Exception as exc:
            failure.append(exc)
        finally:
            resolver_slot.release()

    if not resolver_slot.acquire(timeout=deadline.remaining()):
        deadline._expire()
        raise deadline.error()
    try:
        worker = threading.Thread(target=resolve, daemon=True)
        worker.start()
    except Exception:
        resolver_slot.release()
        raise
    worker.join(deadline.remaining())
    if worker.is_alive():
        deadline._expire()
        raise deadline.error()
    deadline.remaining()
    if failure:
        raise failure[0]
    if not result:
        raise RuntimeError("hostname resolver exited without a result")
    return result[0]


def validated_hostname_resolution_timeout_seconds(value: object) -> float:
    """Return a finite hostname-resolution timeout within the hard bound."""

    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(
            "hostname resolution timeout must be a positive finite number "
            f"at most {MAX_HOSTNAME_RESOLUTION_TIMEOUT_SECONDS:g}s"
        )
    try:
        normalized = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise ValueError(
            "hostname resolution timeout must be a positive finite number "
            f"at most {MAX_HOSTNAME_RESOLUTION_TIMEOUT_SECONDS:g}s"
        ) from exc
    if (
        not math.isfinite(normalized)
        or normalized <= 0
        or normalized > MAX_HOSTNAME_RESOLUTION_TIMEOUT_SECONDS
    ):
        raise ValueError(
            "hostname resolution timeout must be a positive finite number "
            f"at most {MAX_HOSTNAME_RESOLUTION_TIMEOUT_SECONDS:g}s"
        )
    return normalized


def _deadline_create_connection(
    address: tuple[str, int],
    _timeout: object,
    source_address: tuple[str, int] | None,
    *,
    deadline: _NetworkDeadline,
) -> socket.socket:
    host, port = address
    last_error: OSError | None = None
    records = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)
    for family, socktype, proto, _canonical_name, sockaddr in records:
        candidate: socket.socket | None = None
        try:
            candidate = socket.socket(family, socktype, proto)
            deadline.attach(candidate)
            if source_address:
                candidate.bind(source_address)
            candidate.connect(sockaddr)
            deadline.remaining()
            return candidate
        except OSError as exc:
            last_error = exc
            if candidate is not None:
                deadline.detach(candidate)
                candidate.close()
            if deadline.expired():
                raise deadline.error() from exc
    if last_error is not None:
        raise last_error
    raise OSError("getaddrinfo returned an empty address list")


class _DeadlineHTTPSConnection(http.client.HTTPSConnection):
    _context: ssl.SSLContext
    _tunnel_host: str | None

    def __init__(self, host, port=None, *, deadline: _NetworkDeadline, **kwargs):  # type: ignore[no-untyped-def]
        self._deadline = deadline
        kwargs["timeout"] = deadline.remaining()
        super().__init__(host, port, **kwargs)
        self._create_connection = lambda address, timeout, source_address: (
            _deadline_create_connection(
                address,
                timeout,
                source_address,
                deadline=self._deadline,
            )
        )

    def connect(self) -> None:
        http.client.HTTPConnection.connect(self)
        if self.sock is None:
            raise OSError("HTTPS connection did not create a socket")
        raw_socket = self.sock
        server_hostname = self._tunnel_host or self.host
        try:
            wrapped_socket = self._context.wrap_socket(
                raw_socket,
                server_hostname=server_hostname,
                do_handshake_on_connect=False,
            )
            self._deadline.detach(raw_socket)
            self.sock = wrapped_socket
            self._deadline.attach(wrapped_socket)
            wrapped_socket.do_handshake()
            self._deadline.remaining()
        except Exception as exc:
            if self._deadline.expired():
                raise self._deadline.error() from exc
            raise


class _DeadlineHTTPSHandler(HTTPSHandler):
    _context: ssl.SSLContext

    def __init__(self, deadline: _NetworkDeadline) -> None:
        super().__init__()
        self._deadline = deadline

    def https_open(self, request):  # type: ignore[no-untyped-def]
        def connection(host, port=None, **kwargs):  # type: ignore[no-untyped-def]
            return _DeadlineHTTPSConnection(
                host,
                port,
                deadline=self._deadline,
                **kwargs,
            )

        return self.do_open(connection, request, context=self._context)


def _legacy_ipv4_part(part: str) -> int | None:
    if not part:
        return None
    lowered = part.casefold()
    if lowered.startswith(("+", "-")):
        return None
    if lowered.startswith("0x"):
        digits = lowered[2:]
        if not digits or not all(char in "0123456789abcdef" for char in digits):
            return None
        return int(digits, 16)
    if len(lowered) > 1 and lowered.startswith("0"):
        digits = lowered[1:]
        if not all(char in "01234567" for char in digits):
            return None
        return int(digits, 8)
    if not lowered.isdecimal():
        return None
    return int(lowered, 10)


def legacy_ipv4_address(hostname: str) -> ipaddress.IPv4Address | None:
    parts = hostname.split(".")
    if not 1 <= len(parts) <= 4:
        return None
    octets: list[int] = []
    for part in parts:
        value = _legacy_ipv4_part(part)
        if value is None:
            return None
        octets.append(value)
    if len(octets) == 1:
        if octets[0] > 0xFFFFFFFF:
            return None
        address_int = octets[0]
    elif len(octets) == 2:
        if octets[0] > 0xFF or octets[1] > 0xFFFFFF:
            return None
        address_int = (octets[0] << 24) | octets[1]
    elif len(octets) == 3:
        if octets[0] > 0xFF or octets[1] > 0xFF or octets[2] > 0xFFFF:
            return None
        address_int = (octets[0] << 24) | (octets[1] << 16) | octets[2]
    else:
        if any(octet > 0xFF for octet in octets):
            return None
        address_int = (octets[0] << 24) | (octets[1] << 16) | (octets[2] << 8) | octets[3]
    address = ipaddress.IPv4Address(address_int)
    if hostname == str(address):
        return None
    return address


def legacy_ipv4_literal_reason(hostname: str) -> str | None:
    address = legacy_ipv4_address(hostname)
    if address is None:
        return None
    if address.is_global:
        return f"external URL uses unsupported legacy IPv4 literal: {hostname}"
    return f"external URL points to non-public address: {address}"


def non_public_address_reason(address_text: str, *, resolved: bool) -> str | None:
    try:
        address = ipaddress.ip_address(address_text)
    except ValueError:
        return None
    if address.is_multicast:
        if resolved:
            return f"external URL resolves to multicast address: {address}"
        return f"external URL points to multicast address: {address}"
    site_local_ipv6 = (
        isinstance(address, ipaddress.IPv6Address) and address.is_site_local
    )
    if address.is_global and not site_local_ipv6:
        return None
    if resolved:
        return f"external URL resolves to non-public address: {address}"
    return f"external URL points to non-public address: {address}"


def resolved_address_issues_from_records(records: list[tuple]) -> list[str]:
    issues: list[str] = []
    for record in records:
        sockaddr = record[4]
        address_text = str(sockaddr[0])
        reason = non_public_address_reason(address_text, resolved=True)
        if reason:
            issues.append(reason)
    return sorted(set(issues))


def resolved_address_issues(
    hostname: str,
    port: int | None,
    *,
    timeout_seconds: float = DEFAULT_HOSTNAME_RESOLUTION_TIMEOUT_SECONDS,
    cache: HostnameResolutionCache | None = None,
) -> list[str]:
    timeout = validated_hostname_resolution_timeout_seconds(timeout_seconds)
    normalized_host = hostname.rstrip(".").casefold()
    cache_key = (normalized_host, port)
    if cache is not None:
        if _HOSTNAME_RESOLUTION_TERMINAL_CACHE_KEY in cache:
            return list(cache[_HOSTNAME_RESOLUTION_TERMINAL_CACHE_KEY])
        if cache_key in cache:
            return list(cache[cache_key])

    deadline = _NetworkDeadline(timeout)
    try:
        records = _resolve_with_deadline(
            socket.getaddrinfo,
            (hostname, port, 0, socket.SOCK_STREAM, 0, 0),
            deadline,
        )
    except TimeoutError as exc:
        issues = [f"external URL hostname resolution failed: {exc}"]
        if cache is not None:
            # A resolver that outlives its deadline retains the sole bounded
            # worker slot.  Fail the rest of this audit immediately instead
            # of charging the same capacity timeout to every distinct host.
            cache[_HOSTNAME_RESOLUTION_TERMINAL_CACHE_KEY] = tuple(issues)
    except OSError as exc:
        issues = [f"external URL hostname resolution failed: {exc}"]
    else:
        issues = resolved_address_issues_from_records(records)
    finally:
        deadline.cancel()
    if cache is not None:
        cache[cache_key] = tuple(issues)
    return issues


def safe_urlsplit(url: str):
    try:
        parsed = urlsplit(url)
    except ValueError as exc:
        return None, f"malformed external URL: {exc}"
    try:
        _port = parsed.port
    except ValueError as exc:
        return None, f"malformed external URL: {exc}"
    return parsed, None


def blocked_external_url_reason(
    url: str,
    *,
    resolve_hostname: bool = False,
    hostname_resolution_timeout_seconds: float = (
        DEFAULT_HOSTNAME_RESOLUTION_TIMEOUT_SECONDS
    ),
    hostname_resolution_cache: HostnameResolutionCache | None = None,
) -> str | None:
    if any(
        unicodedata.category(character) in {"Cc", "Cf", "Cs", "Zl", "Zp"}
        for character in url
    ):
        return "external URL contains control or format characters"
    parsed, parse_error = safe_urlsplit(url)
    if parse_error:
        return parse_error
    if parsed is None:
        return "external URL parser returned no result"
    if parsed.scheme.casefold() not in ALLOWED_EXTERNAL_SCHEMES:
        return "external URL must use https"
    hostname = parsed.hostname
    if not hostname:
        return "external URL has no hostname"
    if parsed.username or parsed.password:
        return "external URL must not contain credentials"
    normalized_host = hostname.rstrip(".").casefold()
    if normalized_host in LOCAL_HOSTNAMES or normalized_host.endswith(".localhost"):
        return "external URL points to localhost"
    if normalized_host in LOCAL_USE_HOSTNAMES or normalized_host.endswith(LOCAL_USE_SUFFIXES):
        return f"external URL uses local-use hostname: {normalized_host}"
    legacy_reason = legacy_ipv4_literal_reason(normalized_host)
    if legacy_reason:
        return legacy_reason
    literal_reason = non_public_address_reason(normalized_host, resolved=False)
    if literal_reason:
        return literal_reason
    if resolve_hostname:
        issues = resolved_address_issues(
            normalized_host,
            parsed.port or 443,
            timeout_seconds=hostname_resolution_timeout_seconds,
            cache=hostname_resolution_cache,
        )
        if issues:
            return "; ".join(issues)
    return None


def safe_redirect_target(base_url: str, location: str) -> tuple[str | None, str | None]:
    """Resolve an untrusted redirect location and validate the complete target."""

    candidate = urljoin(base_url, location)
    blocked = blocked_external_url_reason(candidate, resolve_hostname=False)
    if blocked:
        return None, blocked
    return candidate, None


class SafeRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        blocked = blocked_external_url_reason(newurl, resolve_hostname=False)
        if blocked:
            raise HTTPError(req.full_url, code, f"unsafe redirect target: {blocked}", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def safe_urlopen(request: Request, *, timeout: float, max_redirects: int = 5):
    blocked = blocked_external_url_reason(request.full_url, resolve_hostname=False)
    if blocked:
        raise ValueError(blocked)
    if max_redirects < 0:
        raise ValueError("max_redirects must be non-negative")
    deadline = _NetworkDeadline(timeout)
    acquired = SAFE_URLOPEN_LOCK.acquire(timeout=deadline.remaining())
    if not acquired:
        deadline.cancel()
        raise deadline.error()
    succeeded = False
    try:
        original_getaddrinfo = socket.getaddrinfo
        cache: dict[tuple[object, ...], list[tuple]] = {}

        def guarded_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):  # type: ignore[no-untyped-def]
            hostname = str(host).rstrip(".").casefold()
            if hostname in LOCAL_HOSTNAMES or hostname.endswith(".localhost"):
                raise OSError("external URL points to localhost")
            legacy_reason = legacy_ipv4_literal_reason(hostname)
            if legacy_reason:
                raise OSError(legacy_reason)
            literal_reason = non_public_address_reason(hostname, resolved=False)
            if literal_reason:
                raise OSError(literal_reason)
            cache_key = (hostname, port, family, type, proto, flags)
            if cache_key not in cache:
                records = _resolve_with_deadline(
                    original_getaddrinfo,
                    (host, port, family, type, proto, flags),
                    deadline,
                )
                issues = resolved_address_issues_from_records(records)
                if issues:
                    raise OSError("; ".join(issues))
                cache[cache_key] = records
            return cache[cache_key]

        redirect_handler_type = type(
            "BoundedSafeRedirectHandler",
            (SafeRedirectHandler,),
            {"max_redirections": max_redirects},
        )
        redirect_handler = redirect_handler_type()
        # Process-level proxies resolve or fetch outside this guarded resolver.
        # This bounded primitive therefore uses a direct connection; a
        # proxy-backed acquisition needs its own explicit transport review.
        opener = build_opener(
            ProxyHandler({}),
            redirect_handler,
            _DeadlineHTTPSHandler(deadline),
        )
        try:
            socket.getaddrinfo = guarded_getaddrinfo  # type: ignore[assignment]
            parsed, parse_error = safe_urlsplit(request.full_url)
            if parse_error:
                raise ValueError(parse_error)
            if parsed is None:
                raise ValueError("external URL parser returned no result")
            default_port = 443 if parsed.scheme.casefold() == "https" else 80
            try:
                guarded_getaddrinfo(parsed.hostname, parsed.port or default_port, type=socket.SOCK_STREAM)
            except OSError as exc:
                raise ValueError(str(exc)) from exc
            response = opener.open(request, timeout=deadline.remaining())
            deadline.remaining()
            succeeded = True
            return _DeadlineResponse(response, deadline)
        except URLError as exc:
            if deadline.expired():
                raise deadline.error() from exc
            if isinstance(exc.reason, OSError) and str(exc.reason):
                raise ValueError(str(exc.reason)) from exc
            raise
        except Exception as exc:
            if deadline.expired():
                raise deadline.error() from exc
            raise
        finally:
            socket.getaddrinfo = original_getaddrinfo  # type: ignore[assignment]
    finally:
        SAFE_URLOPEN_LOCK.release()
        if not succeeded:
            deadline.cancel()
