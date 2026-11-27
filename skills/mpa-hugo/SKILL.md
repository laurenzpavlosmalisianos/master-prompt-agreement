---
name: mpa-hugo
description: "Hugo release changes through v0.170 and checks that are easy to miss: changed defaults, security settings, layout folders, and build tools. Use for any work on a Hugo site: templates, shortcodes, configuration, asset pipelines, modules, or a Hugo version upgrade."
---

# Hugo

Current to Hugo v0.170.1, checked 2026-11-27. For a newer Hugo release, read what changed after v0.170.1 in the release notes (https://gohugo.io/news/) before relying on this file. The entries are the changes that are easy to miss, not the full release notes.

## Templates and build behaviour

- Match template paths to the pinned Hugo version: v0.146+ restructures `layouts/` and places shortcodes, partials, and render hooks under `_shortcodes`, `_partials`, and `_markup` rather than legacy `_default/`, `shortcodes/`, or `partials/` directories.
- Check Hugo Pipes builds (Sass/SCSS, Tailwind CSS, PostCSS, `js.Build`) against the edition and external tools the pinned Hugo version requires (such as Dart Sass on v0.170+, where separate extended editions and LibSass are discontinued and WebP encoding is built in), and verify CSS purging reads current `hugo_stats.json` output.

## Content and rendering security

- `security.allowContent` (v0.162+) limits the media types content files may have. Its default is `['! ^text/html$']` in v0.162 and `['! ^text/html$', '! ^text/org$']` from v0.166, because Hugo passes HTML files and Org export blocks through verbatim; `.html` and `.org` content files are refused until the list is changed. Keep the default for content that is not fully trusted.
- Keep `markup.goldmark.renderer.unsafe = false` and `security.enableInlineShortcodes = false` unless every content author is trusted; either setting lets Markdown authors inject scripts or execute templates. Say so in the report when a change turns one on.
- From v0.169, `pre` and `post` of menu entries defined in front matter are HTML-escaped unless `security.allowContent` allows `text/html`; entries in the project configuration are not affected. From v0.170, Goldmark passthrough content without a passthrough render hook is escaped unless `markup.goldmark.renderer.unsafe` is on; an older pin writes it to the page as raw HTML.
- Audit `_markup` render hooks and `safeHTML`, `safeHTMLAttr`, `safeURL`, `safeJS`, and `safeCSS` casts so untrusted frontmatter or Markdown cannot bypass Go `html/template` auto-escaping, evade URL-scheme filtering, or inject scripts.
- Validate or context-escape shortcode parameters and `.Inner` interpolated into attributes, URLs, scripts, or styles instead of applying blanket `safe*` casts.

## Modules, pipelines, and configuration

- On v0.161+, PostCSS, Babel, and Tailwind run under Node's permission model. Keep `security.node.permissions.disable = false` and keep `allowRead` (default `['.']`) and `allowWrite` (default empty) narrow; a build tool that fails to read or write a path needs that path added, not the model switched off.
- On v0.166+, keep the default `security.http.urls` where `resources.GetRemote` runs. The default allows `http` and `https` hosts that start with a letter or digit and denies numeric hosts, `localhost`, and URLs with user info; Hugo also rejects hosts that resolve to private, loopback, or metadata addresses, and an override of `urls` or `http.proxyFromEnvironment = true` turns that check off. On older pins (before v0.161 the default allows every URL), or where an override is needed, list only exact, anchored hosts.
- From v0.170, a command-line flag overrides the matching `HUGO_` environment variable, which overrides the configuration file. v0.168 ignores `module.replacements` set in a theme, and v0.170.0 confines vendored module paths to `_vendor`, a security fix.
- Verify `baseURL` (from v0.167 an unset one defaults to a placeholder on example.org), multilingual URLs, and enabled output formats against canonical, sitemap, and redirect expectations.
