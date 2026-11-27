---
name: mpa-nginx
description: "nginx release changes through stable 1.30.8 and mainline 1.31.10 and checks that are easy to miss: security fixes with fixed versions, changed proxy, header, and HTTP/2 defaults. Use for any work on nginx.conf, server and location blocks, reverse proxying, caching, TLS, HTTP/2 or HTTP/3, or an nginx upgrade."
---

# nginx

Current to nginx stable 1.30.8 and mainline 1.31.10, checked 2026-11-27. For a newer release of either, read what changed after it in the release notes (https://nginx.org/en/CHANGES, https://nginx.org/en/security_advisories.html) before relying on this file. The entries are the changes that are easy to miss, not the full release notes.

## Find out what runs

- `nginx -v` gives the version, `nginx -V` the build options and modules, and `nginx -T` the configuration nginx loads with every include resolved. Read the loaded configuration, not one file of it.
- Stable 1.30 was branched after mainline 1.29.8, so it has every change listed below up to 1.29.8. Of the 1.31 changes it receives the security fixes; a 1.31 behaviour change below is not in 1.30 unless the notes of a later stable release say so.
- On managed hosting nginx is often the proxy in front of another server, outside the customer's reach. There it shows as `Server: nginx` and in what it does to headers and compression; changes to it are a request to the host. A distribution package can carry a security fix under an older version number.

## Changed defaults and behaviour, newest first

- 1.31.9: a request header line without a colon is rejected, and so is a chunked request body with too much framing overhead.
- 1.31.8: the path in `working_directory` is relative to the nginx prefix directory, not to the current directory.
- 1.31.7: HTTP/2 uses the RFC 9218 priority scheme and ignores RFC 7540 priority signals. The GeoIP modules read MaxMind DB (MMDB) files. A backend certificate can be verified by IP address.
- 1.31.5: adds the control API, predicate locations, the JSON module, and `client_body_early_read`.
- 1.31.4: HTTP/2 and gRPC requests to backends always carry `:authority`, and HTTP/1.1 requests always carry `Host`. `proxy_protocol` in the stream and mail modules supports PROXY protocol version 2.
- 1.31.3: the XSLT filter no longer loads external entities; `xml_external_entities` allows it again. Headers and trailers of HTTP/2 responses from backends are limited by `proxy_buffer_size` and `grpc_buffer_size`.
- 1.31.0: HTTP/2 and HTTP/3 requests that carry `Connection`, `Proxy-Connection`, `Keep-Alive`, `Transfer-Encoding`, `Upgrade`, or `TE` with a value other than `trailers` are rejected.
- 1.29.8: adds `max_headers` and OpenSSL 4.0 compatibility.
- 1.29.7: `keepalive` in an `upstream` block is on by default, `proxy_http_version` defaults to `1.1`, and the `Connection` header is no longer sent to the backend by default. Configuration that set these by hand to get keepalive is now redundant, and a backend that relied on `Connection: close` no longer receives it.
- 1.29.4: the proxy module can speak HTTP/2 to backends. Host and port in the request line, `Host`, and `:authority` are validated as RFC 3986 defines them. A bare LF as a line end in a chunked request or response body is an error.
- 1.29.3: `add_header_inherit` and `add_trailer_inherit` (`on`, `off`, `merge`). Without them the old rule holds: a level that has any `add_header` of its own inherits none from the level above, so a header set in `server` disappears in a `location` that adds another. `merge` appends the outer values and is itself inherited.
- 1.29.1: TLS 1.3 certificate compression is off by default; `ssl_certificate_compression` turns it on.
- 1.29.0: `early_hints` passes 103 responses from proxy and gRPC backends to the client.

## Security fixes

- Every 2026 advisory is fixed in stable 1.30.8 and mainline 1.31.10. Advisories from May 2026 on name fixed releases in 1.30 and 1.31 only; 1.28 received its last listed fixes in 1.28.3.
- `alias`: CVE-2026-125283 (with `try_files`; fixed in 1.30.7 and 1.31.9), CVE-2026-15176 (with `rewrite`; 1.30.6, 1.31.7), CVE-2026-27654 (DAV `COPY` and `MOVE`; 1.28.3, 1.29.7). All three are buffer overflows.
- Rewrite and variables: CVE-2026-42945 (1.30.1, 1.31.0) and CVE-2026-9256 (1.30.2, 1.31.1), both possible code execution in the rewrite module; CVE-2026-42533 (`map` with regex; 1.30.4, 1.31.3); CVE-2026-93479 (string expressions; 1.30.6, 1.31.7).
- HTTP/2 and HTTP/3: CVE-2026-123007 and CVE-2026-123633 (HTTP/2; 1.30.7, 1.31.9); CVE-2026-121810 (HTTP/3; 1.30.7, 1.31.9); CVE-2026-95101 (HTTP/3 request body injection past `client_max_body_size`; 1.30.6, 1.31.7); CVE-2026-90439 (HTTP/3 with OpenSSL 3.5.0 or older; 1.30.5, 1.31.6); CVE-2026-40460 (HTTP/3 address spoofing; 1.30.1, 1.31.0).
- TLS: CVE-2026-132779 (`ssl_early_data`, CPU exhaustion; 1.30.8, 1.31.10); CVE-2026-97629 (session ticket key rotation, session forgery; 1.30.6, 1.31.7); CVE-2026-118899 (endless loop reading a request body over TLS 1.3; 1.30.7, 1.31.9).
- Proxying: CVE-2026-1642 (data injected into the response from an SSL backend; 1.28.2, 1.29.5); CVE-2026-42926 (`proxy_set_body` with an HTTP/2 backend; 1.30.1, 1.31.0); CVE-2026-123634 (`resolver`; 1.30.7, 1.31.9); CVE-2026-42055 (HTTP/2 and gRPC backends; 1.30.3, 1.31.2).
