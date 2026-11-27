---
name: mpa-apache-httpd
description: "Apache HTTP Server release changes through 2.4.71 and easy-to-miss checks: security fixes with fixed versions, ETag and caching directives, and what .htaccess can set. Use for any work on .htaccess, httpd.conf, virtual hosts, rewrites, headers, caching, compression, or TLS, on shared hosting or your own server."
---

# Apache HTTP Server

Current to Apache HTTP Server 2.4.71, checked 2026-11-27. For a newer Apache release, read what changed after 2.4.71 in the release notes (https://downloads.apache.org/httpd/CHANGES_2.4, https://httpd.apache.org/security/vulnerabilities_24.html) before relying on this file. The entries are the changes that are easy to miss, not the full release notes.

## Find out what runs

- On managed hosting the host chooses the version and its patch level, and the site cannot upgrade it. Read the version before relying on a fix or a directive: the `Server` response header and `SERVER_SOFTWARE`, which carry the same string and are often cut down to `Apache`, the host's status page, or `apachectl -v` where a shell exists. A distribution package can carry a security fix under an older version number, so where the number decides, ask the host.
- A proxy or CDN in front of the server can add, strip, or rewrite `ETag`, `Vary`, `Content-Encoding`, and caching headers, and can compress on its own. Signs are `Via`, `Age`, or cache-status headers, or a `Server` value that is not Apache. Judge a header change by the response a client receives (`curl -sI`, once with `Accept-Encoding: gzip, br` and once without), not by what `.htaccess` says.
- Whether a directive is permitted shows only when it is tried. A directive that `AllowOverride` does not permit, or that is not valid in `.htaccess` at all, turns every request below that directory into a 500. Where the host set `AllowOverride Nonfatal`, the directive is ignored without an error, so after adding access rules, request a protected path and confirm that it is refused. Try a new directive in a scratch subdirectory first and keep the previous file. Inside `<IfModule>` a missing module fails silently: the block is skipped and nothing changes.

## What .htaccess can set

- Valid in `.htaccess` when the host allows the class. `FileInfo`: `Header`, `RequestHeader`, `RewriteEngine`, `RewriteCond`, `RewriteRule`, `RewriteBase`, `Redirect`, `ErrorDocument`, `FileETag`, `AddType`, `AddHandler`, `AddOutputFilterByType`, `SetOutputFilter`, `SetEnvIf`. `Indexes`: `ExpiresActive`, `ExpiresByType`, `ExpiresDefault`, `DirectoryIndex`, `FallbackResource`. `AuthConfig`: the authentication directives, `Require`, `SSLRequireSSL`. `Options`: `Options`.
- Server configuration only, so on shared hosting a request to the host: `DeflateAlterETag`, `BrotliAlterETag`, `RewriteMap`, `Protocols` (HTTP/2), `SSLProtocol`, `SSLEngine`, `SSLUseStapling`, `ServerTokens`, `TraceEnable`, `Alias`, module loading, `<VirtualHost>`, `<Directory>`, `<Location>`, and `AllowOverride` itself.

## ETag, compression, and conditional requests

- No release from 2.4.59 to 2.4.71 changes how ETags are built or sent. The directives that decide it are older, so the running version matters: `FileETag` defaults to `MTime Size`; its `Digest` keyword (first released in 2.4.48) builds the tag from the file's content, so the tag survives a deployment that resets file times and is the same on every server behind a balancer. 2.4.48 fixes a regression that stripped `ETag` from 304 responses.
- mod_deflate appends `-gzip` to the ETag of each response it compresses, so the tag a client sends back never matches and a conditional request for a compressed response gets the full body again, not a 304. `DeflateAlterETag` (2.4.58+; `AddSuffix` is the default, `NoChange` keeps the tag, `Remove` drops it) controls this, and mod_brotli has `BrotliAlterETag` with the same values. Both are server configuration only: in `.htaccess` they cause a 500, and below 2.4.58 `DeflateAlterETag` does not exist. From `.htaccess`, `FileETag None` removes the tag and leaves revalidation to `Last-Modified`.
- 2.4.66 fixes 304 responses that mod_cache hands to an HTTP/2 client. 2.4.70 stops mod_cache from storing a response whose `Vary: *` was set through `Header always`.

## Releases, newest first

- 2.4.71 (2026-11-11) fixes CVE-2026-119618 (mod_http2 heap corruption that can lead to remote code execution; 2.4.55 to 2.4.70), CVE-2026-109163 (mod_vhost_alias stack overwrite; 2.4.69 and 2.4.70), and CVE-2026-106023 (mod_md crash; 2.4.30 to 2.4.70).
- 2.4.70 (2026-11-06) fixes Windows crashes of mod_authnz_ldap introduced in 2.4.69 and raises the mod_cgid limits for environment variables, URI, and arguments.
- 2.4.69 (2026-10-01) fixes 20 vulnerabilities in releases up to 2.4.68. Those a site configuration can reach: CVE-2026-42356 (2.4.60 to 2.4.68: the target of some internal redirects from a CGI program is itself run as CGI when it lies in a CGI-enabled directory and has no extension mod_mime knows), CVE-2026-59797 (`SSLRequire` in `.htaccess` could use file-reading expression functions), CVE-2026-56154 (mod_rewrite use-after-free through `%{LA-U:HTTP:...}`), CVE-2026-57941 (mod_http2 use-after-free), CVE-2026-63718 (mod_proxy_uwsgi response smuggling through `Transfer-Encoding`), CVE-2026-47360 (mod_session cookie kept across an internal redirect), and three mod_auth_digest issues. It also turns `MDServerStatus` off by default, drops RFC 2069 support from mod_auth_digest, and rejects control characters in the reason phrase of an interim response.
- 2.4.68 (2026-06-08) fixes 13 vulnerabilities, among them CVE-2026-44119 (privilege escalation through expressions in `.htaccess`, in several modules), CVE-2026-49975 and CVE-2026-48913 (mod_http2), and CVE-2026-42535 (mod_dav_fs access to a protected directory). It adds OpenSSL 4.0 support and `%{m}t` (milliseconds) in `ErrorLogFormat`; mod_ssl sets the auth type to `ClientCert` when a client certificate authenticates the request.
- 2.4.67 (2026-05-04) fixes 11 vulnerabilities, among them CVE-2026-23918 (HTTP/2 double free with possible remote code execution on an early reset), CVE-2026-24072 (mod_rewrite privilege escalation through expressions), CVE-2026-33523 (response splitting in several modules), and four in mod_proxy_ajp.
- 2.4.66 (2025-12-04) fixes 5 vulnerabilities, among them CVE-2025-66200 (mod_userdir with suexec bypassed through `AllowOverride FileInfo`) and CVE-2025-58098 (Server Side Includes pass the query string to `#exec cmd`). It adds `SSLVHostSNIPolicy` (see 2.4.64 below) and `ListenTCPDeferAccept`.
- 2.4.65 (2025-07-23) fixes CVE-2025-54090: in 2.4.64 every `RewriteCond expr ...` test evaluates as true. A server that reports 2.4.64 needs this before any `RewriteCond expr` rule can be trusted.
- 2.4.64 (2025-07-10) fixes CVE-2025-23048 and widens an older check. A request whose `Host` names a virtual host with a TLS setup that is not compatible with the one its connection was opened for gets 421 Misdirected Request; before 2.4.64 that applied only when the client had sent SNI, and since 2.4.64 a connection without SNI is compared with the default virtual host. It shows up behind proxies that send no SNI or reuse a connection for another host. `SSLVHostSNIPolicy` (2.4.66+, server configuration only; `strict`, `secure` as the default, `authonly`, `insecure`) sets how strict the comparison is.

## When to ask the host

- Ask the host, with the directive or the CVE and the response headers that show the problem, when the fix is a server version, a directive from the server-configuration list, HTTP/2 or TLS protocol settings, or a header that the front proxy rewrites. Do not work around a missing security fix in `.htaccess` and report it as fixed.
- On shared hosting the fixes for what another customer's `.htaccess` can do are the host's to install: CVE-2025-66200 (2.4.66), CVE-2026-24072 (2.4.67), CVE-2026-44119 (2.4.68), and CVE-2026-59797 (2.4.69). A server that reports a release below 2.4.69 is a reason to ask which of them it carries.
