---
name: mpa-php
description: Security checks for PHP and Laravel. Use when changing code that compares tokens, unserializes data, opens user-influenced paths, runs processes, or handles uploads, or Laravel mass assignment, raw queries, route binding, proxies, or signed URLs.
---

# PHP and Laravel

## PHP

- Compare secrets (tokens, MACs, digests) with `hash_equals()`. For other checks at a security boundary use strict comparison: `===`, and `in_array($v, $allowed, true)`. Loose comparison treats `"0e1" == "0"` as true.
- Do not pass untrusted input to `unserialize()`, even with `allowed_classes => false`; parser bugs stay reachable. Use `json_decode` with `JSON_THROW_ON_ERROR` and a depth limit.
- Reject stream wrappers (`phar://`, `php://filter`, `data://`, `expect://`) in paths a user can influence. Before PHP 8.0 any filesystem call on a `phar://` path unserializes its metadata; from 8.0 `Phar::getMetadata()` still does.
- Resolve with `realpath()`, check containment, and open the resolved path. `open_basedir` is a backstop.
- Run processes with `proc_open` and an argument array, and keep user-influenced arguments away from `.bat` and `.cmd` files on Windows (see the `mpa-secure-coding` skill).
- Long-lived workers (FrankenPHP, RoadRunner, Swoole, Octane) keep statics and singletons alive between requests. Reset request state and recycle workers after a bounded number of requests.
- Keep `post_max_size` well below `memory_limit`, so that request parsing cannot exhaust memory before application code runs.
- `#[\SensitiveParameter]` needs the leading backslash or a `use` import inside a namespace. Without it the name resolves to a local attribute that does not exist and nothing is redacted, with no error.
- Set `opcache.validate_timestamps = 0` only for immutable deployments. PHP then runs the cached code until the cache is reset or the workers restart, so a deploy includes that step.
- Stage a self-updater's files outside the web root, so that installer endpoints are not reachable mid-upgrade.

## Laravel

- `trustProxies` lists exact proxy addresses, not `*`. The `mpa-secure-coding` skill covers proxy trust.
- `$guarded = []`, `Model::unguard()`, `forceFill()`, and `$request->all()` passed to `create`, `update`, or `fill` allow mass assignment. Declare `$fillable` and pass `$request->validated()`.
- Raw query methods (`whereRaw`, `selectRaw`, `orderByRaw`, `havingRaw`, `groupByRaw`) need bindings. Column names and sort directions cannot be bound; allowlist them. `whereIntegerInRaw` inlines its values.
- Nested route model binding scopes the child to the parent only when the child parameter uses a custom key, as in `{post:slug}`. For other nested routes call `scopeBindings()`.
- A Form Request whose `authorize()` returns `true` performs no authorization.
- Sanctum and Passport token abilities are client scopes. Gates and policies still apply; see the `mpa-secure-coding` skill.
- `URL::signedRoute` signs only the parameters it is given and sets no expiry. Pass the target user's ID as a parameter and use `temporarySignedRoute` when the link should expire.
- Rotate the application key through `APP_PREVIOUS_KEYS`, so that sessions, cookies, and encrypted attributes survive the rotation.
- Store uploads on a private disk under `hashName()` and serve them through an authorized controller. SVG is not a safe image type.
