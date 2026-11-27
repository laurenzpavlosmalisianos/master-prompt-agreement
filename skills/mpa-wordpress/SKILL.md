---
name: mpa-wordpress
description: "WordPress release changes through 7.1 and checks that are easy to miss. Use for any work on WordPress plugins, themes, blocks, REST or AJAX endpoints, abilities, $wpdb queries, wp-config.php, hardening, or a core upgrade."
---

# WordPress

Current to WordPress 7.1.5, checked 2026-11-27. For a newer WordPress release, read what changed after 7.1.5 in the release notes (https://wordpress.org/news/category/releases/) before relying on this file; up to 7.1.5 no lookup is needed.

## Plugins, themes, and APIs

- Require an explicit `permission_callback` (`current_user_can(...)`, or intentional `__return_true` for public routes) plus argument validation and sanitization (`validate_callback`, `sanitize_callback`) on every `register_rest_route()`.
- On 6.9+, give every `wp_register_ability()` a capability-checking `permission_callback` (or intentional `__return_true` for an ability anyone may run) and an `input_schema` for any input. Set `meta.show_in_rest` (or, on 7.1+, `meta.public`, which also turns on `show_in_rest` by default and marks the ability for MCP and agent clients) only on purpose.
- Parameterize all custom SQL via `$wpdb->prepare()`: use `%i` for dynamic identifiers on WordPress 6.2+ (still allowlisting user-influenced names) and `$wpdb->esc_like()` for `LIKE` clauses.
- Reject `unserialize()` and `maybe_unserialize()` on untrusted data to prevent PHP object injection; decode JSON instead.

## Site and server hardening

- Security releases after 7.1: 7.1.1 (2026-09-17), 7.1.2 (2026-09-22; an unauthenticated visitor could make template resolution include a local PHP file, CVE-2026-87902), 7.1.3 (2026-10-06), 7.1.4 (2026-10-28; code execution during the upgrade window, stored XSS in blocks and the Interactivity API), and 7.1.5 (2026-11-18; unauthenticated privilege escalation through Template Part block attributes, SQL injection in `WP_Meta_Query` and in Customizer previews, stored XSS through shortcode attributes in comments). Branches from 4.7 on receive the fixes as backports; a site below the newest release of its branch needs that update first.
- Protect `wp-config.php`: place it above the web root where supported or block HTTP access at the web server, restrict permissions (`440` with the web server's group, or `400` when PHP runs as the file's owner), set unique salts, set `WP_DEBUG_DISPLAY = false`, and avoid `WP_DEBUG_LOG = true` writing to `/wp-content/debug.log` unless relocated outside the web root or blocked at the web server.
- Set `DISALLOW_FILE_EDIT = true`. When setting `DISALLOW_FILE_MODS = true` on immutable or CI deploys, note that it also stops automatic core and security updates, so a deploy-side update pipeline is required.
- Enforce least-privilege ownership and permissions (`755` directories, `644` files, code owned by the deploy user rather than the web server daemon).
