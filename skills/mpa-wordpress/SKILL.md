---
name: mpa-wordpress
description: "Checks for WordPress plugins, themes, blocks, REST APIs, and hardening. Use when writing or changing hooks, AJAX or custom REST routes, $wpdb queries, wp-config.php, or WordPress server and supply-chain security. Pair with mpa-php for general PHP/Composer checks and mpa-web-frontend for HTML/CSS/ARIA."
---

# WordPress

WordPress APIs, block schemas, SQL placeholders, and PHP requirements shift across core releases. Check the site's pinned WordPress and PHP versions against current official WordPress developer docs before relying on a hook, helper, or hardening constant (`mpa-research`).

## Plugins, themes, and APIs

- `is_admin()` checks only that a request targets `/wp-admin/` (including `admin-ajax.php`) and is not an authorization check.
- Nonces (`wp_verify_nonce()`, `check_admin_referer()`, `check_ajax_referer()`, `X-WP-Nonce`) verify request intent only and never replace authorization.
- `wp_ajax_*` fires for any logged-in user (including subscribers). Pair every privileged action, admin handler, and `wp_ajax_*` callback with `current_user_can()`, and never register `wp_ajax_nopriv_*` for privileged operations.
- Require an explicit `permission_callback` (`current_user_can(...)`, or intentional `__return_true` for public routes) plus argument validation and sanitization (`validate_callback`, `sanitize_callback`) on every `register_rest_route()`.
- Parameterize all custom SQL via `$wpdb->prepare()`: use `%i` for dynamic identifiers on WordPress 6.2+ (still allowlisting user-influenced names) and `$wpdb->esc_like()` for `LIKE` clauses (`mpa-database`).
- Use `wp_safe_remote_get()` (or `wp_safe_remote_request()`) for user-influenced URLs to guard against SSRF (`mpa-secure-coding`), and `wp_safe_redirect()` followed immediately by `exit` to prevent open redirects.
- Sanitize on input and escape late by output context (`esc_html()`, `esc_attr()`, `esc_url()`, `wp_kses()`), including in dynamic block `render.php` and `render_callback` output (`mpa-web-frontend`).
- Reject `unserialize()` and `maybe_unserialize()` on untrusted data to prevent PHP object injection; decode JSON instead (`mpa-php`).

## Site and server hardening

- Protect `wp-config.php`: place it above the web root where supported or block HTTP access at the web server, restrict permissions (`600` or `440`), set unique salts, set `WP_DEBUG_DISPLAY = false`, and avoid `WP_DEBUG_LOG = true` writing to `/wp-content/debug.log` unless relocated outside the web root or blocked at the web server.
- Set `DISALLOW_FILE_EDIT = true`. When setting `DISALLOW_FILE_MODS = true` on immutable or CI deploys, note that it also stops automatic core and security updates, so a deploy-side update pipeline is required.
- Block `xmlrpc.php` at the web server when unused, and disable PHP execution inside `wp-content/uploads/`.
- Enforce least-privilege ownership and permissions (`755` directories, `644` files, code owned by the deploy user rather than the web server daemon).
- Replace public `wp-cron.php` (`DISABLE_WP_CRON = true`) with system cron on hardened hosts.
- Require explicit approval and restore-tested backups before live database, `wp-config.php`, salt, or core, plugin, and theme changes (`mpa-migration`).

## Supply chain and integrity

- Treat third-party plugins and themes as privileged code with full application and database access (`mpa-dependency-change`).
- Remove inactive plugins and themes rather than leaving deactivated PHP files reachable on disk.
- Pin exact versions when managed via Composer (`composer.lock`) or scripted WP-CLI install lists (`mpa-php`).
- Verify integrity with `wp core verify-checksums` and `wp plugin verify-checksums`, noting plugin checksums cover WordPress.org repository plugins only.
