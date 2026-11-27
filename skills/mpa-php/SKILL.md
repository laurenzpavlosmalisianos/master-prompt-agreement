---
name: mpa-php
description: "PHP and Laravel release changes through PHP 8.6 and Laravel 13 and checks that are easy to miss. Use for any work on PHP code: sessions, serialization, file paths, Composer, Eloquent, or a PHP or framework upgrade."
---

# PHP and Laravel

Current to PHP 8.6.0 and Laravel 13.44.1, checked 2026-11-27. For a newer release of either, read what changed after it in the release notes (https://www.php.net/ChangeLog-8.php, https://laravel.com/docs/releases) before relying on this file. The entries are the changes that are easy to miss, not the full release notes.

## PHP

- Do not pass untrusted input to `unserialize()`, even with `allowed_classes => false`; parser bugs stay reachable. Use `json_decode` with `JSON_THROW_ON_ERROR` and a depth limit.
- Reject stream wrappers (`phar://`, `php://filter`, `data://`, `expect://`) in user-influenced paths, and never call `Phar::getMetadata()` or `PharFileInfo::getMetadata()` on untrusted archives because both unserialize archive metadata.
- When validating paths with `realpath()`, check containment against `rtrim($base, DIRECTORY_SEPARATOR) . DIRECTORY_SEPARATOR` (or exact equality when `$base` itself is valid) to prevent `/base_evil` prefix matches, and resolve the existing parent directory when creating new files (`realpath()` returns `false` on missing paths). `open_basedir` is a backstop; note the residual check-then-open race where PHP lacks handle-relative opens.
- Long-lived workers (FrankenPHP, RoadRunner, Swoole, Octane) keep statics and singletons alive between requests; reset request state and recycle workers after a bounded request count.
- PHP 8.6 turns on `session.use_strict_mode` and `session.cookie_httponly` and sets `session.cookie_samesite` to `Lax` by default; on upgrade, test flows that need the session cookie on a cross-site POST (payment or SSO returns) and custom session handlers that accept unknown IDs.
- PHP 8.6: `file_exists()`, `is_file()`, `stat()` and the other file-status functions, `getenv()`, and `parse_str()` throw `ValueError` when the argument holds a NUL byte. `trim()`, `ltrim()`, and `rtrim()` also strip form feed by default, and `preg_grep()` returns false on a PCRE error instead of a partial array.
- Security releases of 2026-11-19: 8.5.13, 8.4.28, 8.3.37, and 8.2.36 (8.2 gets security fixes until 2026-12-31); 8.6.0 carries the same fixes. Among them are remote code execution through partially overwritten session files and through a session serializer mismatch (CVE-2026-126714, CVE-2026-115560), PHP-FPM request smuggling through an unread request body (CVE-2026-129289), a PHAR signature bypass (CVE-2026-128090), and `HTTPS` or `FTPS` URL schemes in mixed case sent in plaintext (CVE-2026-128064).
- Run `composer audit` for known advisories alongside the project's static analysis (`phpstan` or `psalm`) and tests.

## Laravel

- The Laravel support table lists PHP 8.3 to 8.5 for Laravel 13, while the framework's Composer constraint (`^8.3`) admits 8.6; run the application's tests on 8.6 before raising its PHP version.
- Avoid `$guarded = []` (or `#[Guarded([])]` and `#[Unguarded]`, Laravel 13+), `Model::unguard()`, `forceFill()`, and passing `$request->all()` into `create`/`update`/`fill`; declare `$fillable` (or `#[Fillable]`, 13+) and pass `$request->validated()`.
- Keep the cache `serializable_classes` allowlist explicit (`false` in the Laravel 13 skeleton) and session serialization at `json`; with a leaked `APP_KEY`, PHP-serialized cache or session data is an unserialize gadget path. Switching sessions from `php` to `json` logs users out.
