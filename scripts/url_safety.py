#!/usr/bin/env python3

from __future__ import annotations

import ipaddress
import socket
import threading
from urllib.error import URLError
from urllib.error import HTTPError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


LOCAL_HOSTNAMES = {"localhost"}
LOCAL_USE_HOSTNAMES = {"home.arpa", "internal", "lan", "local"}
LOCAL_USE_SUFFIXES = tuple(f".{name}" for name in LOCAL_USE_HOSTNAMES)
ALLOWED_EXTERNAL_SCHEMES = {"https"}
SAFE_URLOPEN_LOCK = threading.Lock()


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
    if address.is_global:
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


def resolved_address_issues(hostname: str, port: int | None) -> list[str]:
    try:
        records = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        return [f"external URL hostname resolution failed: {exc}"]
    return resolved_address_issues_from_records(records)


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


def blocked_external_url_reason(url: str, *, resolve_hostname: bool = False) -> str | None:
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
        issues = resolved_address_issues(normalized_host, parsed.port)
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
    with SAFE_URLOPEN_LOCK:
        original_getaddrinfo = socket.getaddrinfo
        cache: dict[tuple[str, int | str | None], list[tuple]] = {}

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
            cache_key = (hostname, port)
            if cache_key not in cache:
                records = original_getaddrinfo(host, port, family, type, proto, flags)
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
        opener = build_opener(ProxyHandler({}), redirect_handler)
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
            return opener.open(request, timeout=timeout)
        except URLError as exc:
            if isinstance(exc.reason, OSError) and str(exc.reason):
                raise ValueError(str(exc.reason)) from exc
            raise
        finally:
            socket.getaddrinfo = original_getaddrinfo  # type: ignore[assignment]
