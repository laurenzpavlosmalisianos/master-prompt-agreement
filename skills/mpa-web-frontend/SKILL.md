---
name: mpa-web-frontend
description: "Checks for website frontend verification, accessibility, and DOM security. Use when building or changing HTML, forms, ARIA/WCAG, CSS layout, iframes, XSS sanitization, or checking rendered pages, DOM output, or responsive behaviour. For metadata, sitemaps, or indexing, use mpa-seo."
---

# Web frontend

Where a standards, ARIA, or browser-support detail decides something, check the current HTML Standard, WAI-ARIA guidance, and compatibility data. One engine's release notes are not cross-browser support. Origin trials, flagged features, and relying on a single-engine feature need approval. For metadata and search indexing, see `mpa-seo`.

## Rendered result

- Reading source or getting a passing build is not a visual check when a browser is available. Render the page and look; if no renderer is available, say so.
- Judge the HTML the build emits, not the template. The parser repairs invalid nesting (interactive inside interactive, block content in `<p>`, broken table or form structure) into a different DOM.
- Dev server, preview build, and deployed output are different evidence; check a fresh production build.
- Check overlap, clipping, text leaving its container, invisible text, broken images, console errors, and failed requests. Test horizontal overflow at supported widths (`scrollWidth <= clientWidth`) and do not hide it with `overflow-x: hidden` on the root.
- Full-page screenshots of lazy-loaded, scroll-driven, canvas, or WebGL pages often show blank bands. Capture settled viewport slices and confirm lower content rendered.
- Judge against design tokens, reference screenshots, or measured geometry with a tolerance, and inspect computed values of dependent states after changing a token or theme input.

## Accessibility and CSS

- Follow the project's accessibility target (default: WCAG 2.2 Level AA; check for a newer version) and report issues by criterion.
- A clean automated audit is not conformance. Test keyboard operation, visible and unobscured focus, accessible name, role, and value, reflow at 320 CSS pixels, 200% zoom, text-spacing overrides, target size, reduced motion, and forced colours. Content shown on hover or focus must be dismissible, hoverable, and persistent.
- Move focus into overlays and dynamic content, restore it on dismissal, and give focus a sensible destination when the focused element is removed.
- When script intercepts Enter to submit, check `isComposing` so input-method users can confirm a candidate.
- Choose `alt` by the image's role: empty for decoration, the action or destination for a functional image.
- Masks, clipping, and fades hide pixels, not content; check focus, hit testing, and scroll reachability.
- Do not gate interaction state on `transitionend` or `animationend`; disabled or interrupted motion skips them.
- Do not clear a validator or audit warning by weakening semantics, accessibility, or what the page truthfully shows.
- Let an unsupported CSS or platform feature drop out only when it is purely additive; needed behaviour gets a tested fallback. `@supports` tests syntax only, not behaviour or fallback.

## Untrusted markup and scripts

- Escape for the exact context (text, attribute, URL, raw-text element), reject `javascript:` and other unsafe schemes in `href`, `src`, `action`, and `formaction`, and sanitize untrusted rich text with an allowlist on the final assembled fragment at insertion and after any transformation or re-parse.
- An injected `<iframe srcdoc>` inherits the parent's origin and policy; treat HTML injection into a privileged origin as script execution.
- Put untrusted documents in a sandboxed frame on a separate origin; `allow-scripts` with `allow-same-origin` on same-origin content lets the frame remove its own sandbox.
- Signing keys and long-lived credentials do not go in `localStorage`, `sessionStorage`, IndexedDB, or cookies readable by script.
- On login, billing, and admin routes, load only the third-party scripts the route needs, self-hosted or pinned with an integrity hash, and check cache, offline, and history-restore behaviour across logout and account switch.
- Do not remove an existing `rel` on `target="_blank"` links; add `noreferrer` only to suppress the referrer on purpose.
- Externally hosted fonts, scripts, images, and embeds carry privacy, policy, and licence consequences (`mpa-dependency-change`, `mpa-data-privacy`).
