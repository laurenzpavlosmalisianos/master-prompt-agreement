---
name: mpa-web-frontend
description: "Checks for website frontend verification, accessibility, and DOM security. Use when building or changing HTML, forms, ARIA/WCAG, CSS layout, iframes, XSS sanitization, or checking rendered pages, DOM output, or responsive behaviour. For metadata, sitemaps, or indexing, use mpa-seo."
---

# Web frontend

Where a standards, ARIA, or browser-support detail decides something, check the current HTML Standard, WAI-ARIA guidance, and compatibility data. One engine's release notes are not cross-browser support. Say so when a change relies on an origin trial, a flagged feature, or a feature of a single engine.

## Rendered result

- Check overlap, clipping, text leaving its container, invisible text, broken images, console errors, and failed requests. Test horizontal overflow at supported widths (`scrollWidth <= clientWidth`) and do not hide it with `overflow-x: hidden` on the root.
- Full-page screenshots of lazy-loaded, scroll-driven, canvas, or WebGL pages often show blank bands. Capture settled viewport slices and confirm lower content rendered.

## Accessibility and CSS

- A clean automated audit is not conformance. Test keyboard operation, visible and unobscured focus, accessible name, role, and value, reflow at 320 CSS pixels, 200% zoom, text-spacing overrides, target size, reduced motion, and forced colours. Content shown on hover or focus must be dismissible, hoverable, and persistent.
- Move focus into overlays and dynamic content, restore it on dismissal, and give focus a sensible destination when the focused element is removed.
- Screen readers voice changes to a live region that is already in the page and often skip one that arrives holding its message. Add the region empty, ideally in the initial markup, and set its content only after assistive technology has had time to register it.
- Choose `alt` by the image's role: empty for decoration, the action or destination for a functional image.

## Untrusted markup and scripts

- Signing keys and long-lived credentials do not go in `localStorage`, `sessionStorage`, IndexedDB, or cookies readable by script.
- Do not remove an existing `rel` on `target="_blank"` links; add `noreferrer` only to suppress the referrer on purpose.
