# Visual Verification Practice Guide

Use this Practice Guide when a task changes rendered UI, screenshots, layout, responsive behavior, browser-visible content, generated static pages, images, canvas, or visual regressions. It turns "looks right" into concrete evidence. Do not load it for pure backend or text-only changes.

## Workflow

0. Confirm the mode.
- `verify-only`: inspect rendered output and report findings without editing files.
- `implementation-authorized`: make the requested visual change and verify it.

Default to `verify-only` when the caller did not authorize implementation.

1. Define the visual surfaces.
- pages, routes, components, templates, generated artifacts, screenshots, images, or canvases
- required viewports, themes, locales, content states, auth states, and browser targets
- critical user-facing flows and accessibility-sensitive areas
- approved evidence runtime, account or region limits, side-effect scope, screenshot policy, redaction, artifact location, retention, and egress boundary

2. Establish a baseline before editing when risk is non-trivial.
- capture screenshots or rendered HTML for affected views when tooling exists
- record command, URL, viewport, data state, and timestamp
- if no renderer or browser access exists, state the limitation and define a manual acceptance item
- do not claim visual correctness from source inspection alone when rendering can be checked

3. Apply the smallest visual change that satisfies the task only in `implementation-authorized` mode.
- preserve existing design-system tokens, spacing scale, components, and responsive breakpoints
- avoid broad redesign when the task is a local fix
- keep text within containers at supported viewports
- keep generated assets and source assets synchronized

4. Verify rendered output.
- run the project build or static generator when visual artifacts are generated
- inspect screenshots or rendered pages at required desktop and mobile viewports
- check for overlap, clipping, invisible text, blank canvases, broken images, broken icons, hydration errors, and layout shift
- when visual text is material, verify labels, legends, axis text, callouts, OCR-derived text, and transcribed content against the source or rendered artifact; treat model visual judgments as reviewer observations until locally checked
- for charts, diagrams, and data visualizations, verify that meaning does not rely on hue alone; use labels, ordering, symbols, line styles, patterns, direct annotation, or another non-color cue when color encodes status or comparison
- for canvas, 3D, or DOM-overlay surfaces, verify fallback behavior, hit testing, focus, keyboard interaction, accessibility-tree exposure, device-pixel-ratio sizing, and cross-origin or privacy limitations
- for public web UI, route accessibility target selection through `website_frontend_quality.md`; use this guide to verify rendered evidence such as text scaling, reflow, keyboard focus, contrast, labels, semantic structure, overlap, clipping, and visible state
- for scroll-heavy, lazy-loaded, reveal-driven, canvas, or WebGL pages, do not trust a single native full-page screenshot when it shows blank bands, sparse content, or disagreement with observed scrolling or motion. Capture settled viewport slices or representative frames, validate that lower-page content rendered, then stitch or crop only from verified evidence and record the capture method
- triage rendered HTML validation output before treating visual or HTML work as complete
- for interactive views, exercise the changed state, not just the initial page
- when motion matters, verify the named motion requirement, interaction correctness, reduced-motion behavior, and any stated timing or performance threshold
- inspect generated or heavily processed visuals for artifacts, crop failures, unreadable details, and responsive degradation

5. Use measurable layout contracts for shared or fragile surfaces.
- define the invariant before measuring it, such as token-to-element size, shell stability, sticky offset, grid slot size, image candidate choice, or layout-shift budget
- measure rendered geometry through the browser when the invariant is pixel-sensitive
- sample representative viewport widths, breakpoints, and device pixel ratios when responsive layout, density, or image selection matters
- use explicit tolerances for browser geometry; require exact equality only when the runtime and invariant justify it

6. Use the visual asset QA template when visual risk warrants a durable evidence record.
- Create a durable QA artifact from `project_state_templates/VISUAL_ASSET_QA.md` only when artifact creation is separately authorized. In `verify-only` mode, report the same evidence inline or provide a candidate record without writing the workspace.
- Record both the source asset and the embedding surface. For example, render the SVG directly and render the README or document that embeds it when that surface is part of the deliverable.
- Record the renderer or approved container runtime, command, output artifact, viewport or output size, unverified states, and closeout status.
- Define a measured geometry contract before claiming that a fragile visual is final. Examples include "all labels remain within declared boxes", "arrow path does not intersect panel interiors", "image natural width is non-zero", or "no horizontal overflow at supported widths".
- Prefer deterministic checks only when they enforce explicit contracts. Do not add generic visual scores, broad pixel-diff gates, or model taste checks as release criteria.

7. Route source-architecture findings to owning guides.
- CSS ownership, cascade, selectors, tokens, modern features, and dead declarations belong in `css_quality.md`
- semantic HTML source, generated HTML semantics, forms, links, media, and accessibility-tree parity belong in `html_quality.md`
- search metadata, canonical links, structured data, crawl/indexing signals, and preview metadata belong in `seo.md`
- video briefs, scripts, rights, captions, audio, temporal review, encoding, target playback, and delivery packages belong in `video_creation_quality.md`; use this guide for rendered frame evidence, not whole-video acceptance
- shared frontend architecture, source ownership, generated website output, and browser-behavior evidence belong in `website_frontend_quality.md`
- this guide may report rendered symptoms and evidence, but should not duplicate those guides' architecture rules

8. Report visual evidence.
- list checked URLs or artifacts, viewports, commands, and screenshots
- state what was not checked and why
- separate visual findings from implementation guesses
- leave follow-up TODOs only for accepted unresolved issues

## Output

Provide:

1. mode
2. affected visual surfaces
3. baseline evidence when captured
4. verification commands, URLs, artifacts, and viewports
5. motion, interaction, visual, and semantic HTML findings; include fixes only in `implementation-authorized` mode
6. unverified states and residual risk

## Guardrails

- Do not treat a passing build as proof that the UI looks correct.
- Do not demote rendered HTML semantic warnings merely because they are non-fatal or absent from Lighthouse output.
- Do not treat static source inspection as visual verification when browser or renderer evidence is available.
- Do not invent screenshot results. If a screenshot or browser check was not run, say so.
- Do not treat OCR or visual-transcription output from a model as authoritative without source, rendered-artifact, or deterministic corroboration.
- Do not expand visual work into a redesign unless the User approved that scope.
- Do not store large screenshots in project docs unless the project has an explicit artifact policy.
- Do not store or embed secret-bearing, private-account, unreleased, or personal-data screenshots in durable project files.
- Do not call a layout pixel-perfect unless a measured invariant, browser/runtime boundary, and tolerance make that claim meaningful.
- Do not claim full WCAG AAA conformance merely because text contrast reaches the WCAG 2.2 Level AAA contrast threshold.
