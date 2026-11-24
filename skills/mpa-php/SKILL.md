---
name: mpa-php
description: "Security and packaging checks for PHP, Composer, and Laravel. Use when changing composer.json/lock, token comparisons, unserialization, paths, processes, long-lived workers (Octane, FrankenPHP), uploads, Eloquent mass assignment, raw SQL, Form Requests, route binding, proxies, or signed URLs."
---

# PHP and Laravel

## PHP

- Compare secrets (tokens, MACs, digests) with `hash_equals()`; for other security-boundary checks use strict `===` and `in_array($v, $allowed, true)`.
- Do not pass untrusted input to `unserialize()`, even with `allowed_classes => false`; parser bugs stay reachable. Use `json_decode` with `JSON_THROW_ON_ERROR` and a depth limit.
- Reject stream wrappers (`phar://`, `php://filter`, `data://`, `expect://`) in user-influenced paths, and never call `Phar::getMetadata()` or `PharFileInfo::getMetadata()` on untrusted archives because both unserialize archive metadata.
- When validating paths with `realpath()`, check containment against `rtrim($base, DIRECTORY_SEPARATOR) . DIRECTORY_SEPARATOR` (or exact equality when `$base` itself is valid) to prevent `/base_evil` prefix matches, and resolve the existing parent directory when creating new files (`realpath()` returns `false` on missing paths). `open_basedir` is a backstop; note the residual check-then-open race where PHP lacks handle-relative opens (`mpa-secure-coding`).
- Run processes with `proc_open` and an argument array (`mpa-secure-coding` covers Windows `.bat`/`.cmd` pitfalls).
- Long-lived workers (FrankenPHP, RoadRunner, Swoole, Octane) keep statics and singletons alive between requests; reset request state and recycle workers after a bounded request count.
- Keep `post_max_size` well below `memory_limit` so request parsing cannot exhaust memory before application code runs.
- `#[\SensitiveParameter]` needs the leading backslash or a `use` import inside a namespace; without it, the attribute resolves to a nonexistent local class and redacts nothing silently.
- Set `opcache.validate_timestamps = 0` only for immutable deployments, and reset OPcache or restart workers as part of deploy.
- Stage a self-updater's files outside the web root so installer endpoints are not reachable mid-upgrade.
- Check the repository's supported PHP version floor in `composer.json` (`require.php` and `config.platform.php`) before using newer language features or runtime behaviour.
- Commit `composer.lock` for applications so installs resolve deterministically, and omit it for libraries tested across supported ranges.
- Run `composer audit` for known advisories alongside the project's static analysis (`phpstan` or `psalm`) and tests.

## Laravel

- `trustProxies` lists exact proxy addresses, not `*` (`mpa-secure-coding`).
- Avoid `$guarded = []`, `Model::unguard()`, `forceFill()`, and passing `$request->all()` into `create`/`update`/`fill`; declare `$fillable` and pass `$request->validated()`.
- Raw query methods (`whereRaw`, `selectRaw`, `orderByRaw`, `havingRaw`, `groupByRaw`) need bindings, and dynamic columns or sort directions must be allowlisted (`mpa-database`). `whereIntegerInRaw` inlines values cast to `int` (silently coercing non-numeric strings) and, like other query-builder methods, does not bind dynamic column names.
- Nested route model binding scopes the child to the parent only when the child uses a custom key (`{post:slug}`); for other nested routes call `scopeBindings()`.
- A Form Request whose `authorize()` returns `true` performs no authorization.
- Sanctum and Passport token abilities are client scopes; gates and policies still apply (`mpa-secure-coding`).
- `URL::signedRoute` sets no expiry by default and does not bind the authenticated session; pass the target user's ID and an expiry (or use `temporarySignedRoute`) when links should expire (`mpa-secure-coding`).
- Rotate the application key through `APP_PREVIOUS_KEYS` so sessions, cookies, and encrypted attributes survive rotation.
- Store uploads on a private disk under `hashName()` and serve them through an authorized controller; SVG is active content, not a safe image type.
