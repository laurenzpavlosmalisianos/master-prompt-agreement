---
name: mpa-web-frontend
description: Checks for website frontend code. Use when building or changing HTML, forms, ARIA, CSS layout, or untrusted markup, and when checking the rendered page, accessibility, or responsive behaviour.
---

# Web frontend

Where a standards, ARIA, or browser-support detail decides something, check the current HTML Standard, WAI-ARIA guidance, and compatibility data. One engine's release notes are not cross-browser support.

## Rendered result

- Reading source or getting a passing build is not a visual check when a browser is available. Render the page and look. If no renderer is available, say so, and do not report results that were not captured.
- Judge the HTML the build emits, not the template. The parser repairs invalid nesting (interactive inside interactive, block content in `<p>`, broken table or form structure) into a different DOM.
- Dev server, preview build, and deployed output are different evidence. Check a fresh production build.
- Check for overlap, clipping, text leaving its container, invisible text, broken images, console errors, and failed requests. Test horizontal overflow at supported widths (`scrollWidth <= clientWidth`) and do not hide it with `overflow-x: hidden` on the root.
- Full-page screenshots of lazy-loaded, scroll-driven, canvas, or WebGL pages often show blank bands. Capture settled viewport slices and confirm that lower content rendered.
- Judge against design tokens, reference screenshots, or measured geometry with a tolerance, not against an impression that it looks clean.
- After changing a token or theme input, inspect the computed values of the states that depend on it.

## Accessibility

- Follow the project's accessibility target. Without one, WCAG 2.2 Level AA is the working minimum; check for a newer version. Report issues by criterion.
- Test keyboard operation, visible and unobscured focus, accessible name, role, and value, reflow at 320 CSS pixels, 200% zoom, text-spacing overrides, target size, reduced motion, and forced colours. Content shown on hover or focus is dismissible, hoverable, and persistent.
- For overlays and dynamic content, move focus in, restore it on dismissal, and give it a sensible destination when the focused element is removed.
- When script intercepts Enter to submit, check `isComposing`, so that input-method users can confirm a candidate.
- Choose `alt` by the image's role: empty for decoration, the action or destination for a functional image.
- Masks, clipping, and fades hide pixels, not content. Check focus, hit testing, and scroll reachability.
- Interaction state must not depend on `transitionend` or `animationend`. They may never fire when motion is disabled or interrupted.
- Do not clear a validator or audit warning by weakening semantics, accessibility, or what the page truthfully shows.

## CSS

- Adopt limited-availability features with progressive enhancement and a tested fallback. `@supports` tests syntax only; it does not show that the feature behaves or that the fallback works.
- `!important`, deep selectors, and page-local overrides hide a cascade ownership problem. Find which layer owns the rule.

## Untrusted markup and scripts

- Escape for the exact context: text, attribute, URL, raw-text element. Reject `javascript:` and other unsafe schemes in `href`, `src`, `action`, and `formaction`.
- Sanitize untrusted rich text with an allowlist on the final assembled fragment at insertion, and again after any transformation or re-parse.
- An injected `<iframe srcdoc>` inherits the parent's origin and policy. Treat any HTML injection into a privileged origin as script execution.
- Put untrusted documents in a sandboxed frame on a separate origin. `allow-scripts` together with `allow-same-origin` on same-origin content lets the frame remove its own sandbox.
- Signing keys and long-lived credentials do not go in `localStorage`, `sessionStorage`, IndexedDB, or cookies readable by script.
- On login, billing, and admin routes, load only the third-party scripts the route needs, self-hosted or pinned with an integrity hash.
- Check cache, offline, and history-restore behaviour across logout and account switch.
- `target="_blank"` implies `noopener` in current browsers. Do not remove an existing `rel`; add `noreferrer` only to suppress the referrer on purpose.
- Externally hosted fonts, scripts, images, and embeds carry privacy, policy, and licence consequences. Adding one is a dependency change.

Related skill: `mpa-seo` for metadata and indexing.
