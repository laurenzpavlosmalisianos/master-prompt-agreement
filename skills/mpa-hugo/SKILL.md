---
name: mpa-hugo
description: "Checks for Hugo templates, rendering security, and site builds. Use when changing Hugo layouts, shortcodes, Goldmark Markdown rendering, Hugo Pipes, Tailwind or JS asset builds, Hugo Modules, or site configuration. Pair with mpa-web-frontend for HTML/CSS/ARIA and mpa-seo for metadata or indexing."
---

# Hugo

Hugo config keys, template lookups, and defaults shift across minor releases, escalating deprecations from `INFO` to `WARN` to `ERROR`. Check the repo's pinned Hugo version and edition (standard or deploy; older pre-v0.170 pins may also use extended) against current official Hugo docs (`mpa-research`).

## Templates and build behaviour

- Match template paths to the pinned Hugo version: v0.146+ restructures `layouts/` and places shortcodes, partials, and render hooks under `_shortcodes`, `_partials`, and `_markup` rather than legacy `_default/`, `shortcodes/`, or `partials/` directories.
- Avoid removed or deprecated globals (such as `.Site.IsServer`), and check `hugo.IsProduction` and `hugo.IsServer` accurately instead of treating server mode as an environment check.
- Validate with a clean production build (`hugo --gc --minify --cleanDestinationDir`) rather than relying on `hugo server`, which runs in development mode and can mask stale files in `public/`, minification errors, or missing assets.
- Check Hugo Pipes builds (Sass/SCSS, Tailwind CSS, PostCSS, `js.Build`) against the edition and external tools the pinned Hugo version requires (such as Dart Sass on v0.170+, where separate extended editions and LibSass are discontinued and WebP encoding is built in), and verify CSS purging reads current `hugo_stats.json` output.
- Verify multilingual sites and non-HTML output formats (RSS, JSON), where template lookup precedence and escaping contexts differ from HTML.

## Content and rendering security

- Preserve Hugo's trust model: templates, config, assets, and data are trusted; Markdown content and untrusted frontmatter are untrusted.
- Keep `markup.goldmark.renderer.unsafe = false` and `security.enableInlineShortcodes = false` unless explicitly approved for trusted-author-only content; either setting lets Markdown authors inject scripts or execute templates.
- Audit `_markup` render hooks and `safeHTML`, `safeHTMLAttr`, `safeURL`, `safeJS`, and `safeCSS` casts so untrusted frontmatter or Markdown cannot bypass Go `html/template` auto-escaping, evade URL-scheme filtering, or inject scripts.
- Validate or context-escape shortcode parameters and `.Inner` interpolated into attributes, URLs, scripts, or styles instead of applying blanket `safe*` casts (`mpa-web-frontend`).

## Modules, pipelines, and configuration

- Pin Hugo Modules via `go.mod` and `go.sum`, and treat third-party themes and modules as privileged build code because their templates, mounts, and config run inside the trust boundary (`mpa-dependency-change`).
- Inspect `module.replacements` and `module.mounts`: only the main project may mount paths outside its root and downloaded Go modules strip symlinks, while broad mounts or local replacements can shadow templates or expose unintended files.
- Keep `security.exec.allow` and `security.funcs.getenv` (defaults `^HUGO_`, `^CI$`) narrow so templates, modules, and asset pipelines cannot run arbitrary binaries or leak CI secrets.
- Narrow `security.http.urls` (which permits public HTTP(S) URLs by default) when templates or modules call `resources.GetRemote` to prevent build-time SSRF or secret exfiltration (`mpa-secure-coding`).
- Verify `baseURL`, multilingual URLs, and enabled output formats against canonical, sitemap, and redirect expectations (`mpa-seo`).
- Fingerprint built CSS and JS with `resources.Fingerprint` and emit matching Subresource Integrity (`.Data.Integrity`) attributes where templates serve bundled or cross-origin assets.
