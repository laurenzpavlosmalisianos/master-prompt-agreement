# CSS Quality Practice Guide

Use this Practice Guide when a task touches CSS architecture, cascade behavior, selectors, responsive layout, design tokens, browser support, animation, visual states, or modern CSS feature adoption. Pair it with `website_frontend_quality.md` and `visual_verification.md` for website work.

Before making source-sensitive recommendations, use project `SOURCE_PACKS.md` and `SOURCE_UPDATE.md` when present, then check current CSS, browser, Baseline, accessibility, and compatibility sources for the active surface.

## Workflow

1. Frame the active CSS contract.

- read the project contract, browser baseline, design tokens, CSS ownership model, build pipeline, generated output, local frontend standards, and any adopted project-local design contract file
- check W3C, CSSWG, MDN, Web Platform Baseline (WebDX), and compatibility data before relying on unpinned browser-support or newly available feature facts
- treat agent-returned modern web guidance as a source-freshness aid; verify feature status, fallback need, and support policy against primary sources and rendered behavior before adoption
- distinguish CSS specification status from browser availability, accessibility, performance, and project support policy
- record feature status on separate axes: Baseline availability, experimental or standards maturity, and project support policy; record the exact Baseline target or status, name the year for a Baseline year target, and record the evaluation date or data-package version for moving targets
- classify design tokens by role: raw value, semantic alias, component token, derived relationship, grouped treatment, or dead indirection
- when a design contract mixes structured tokens and prose guidance, treat token values as implementation evidence and prose as application rationale; reconcile conflicts explicitly before editing CSS

2. Control the cascade deliberately.

- map source ownership for shared tokens, reset/base rules, utilities, components, page overrides, and generated CSS
- use custom properties for semantic design tokens and stateful values that need cascade control
- keep token relationships explicit when the relationship is the invariant, such as surface/on-surface, accent/on-accent, hover, focus, subtle border, spacing rhythm, type scale, or motion duration
- prefer static aliases for simple choices; use derived tokens or CSS functions only when they reduce duplicated decisions or preserve coherence across theme, brand, state, or scale changes
- remove tokens that only rename one-off values without improving ownership, reuse, or verification
- use cascade layers to make reset, base, component, utility, and override order explicit when the project has enough CSS surface to justify them
- use `:where()` to lower selector weight and `:is()` or `:has()` only when their specificity and support are intentional
- consider `@scope` for precise subtree styling, but verify current browser behavior and specificity interactions before adopting it broadly
- scan selector systems and custom-property prefixes for framework-shaped naming when source originality, licensing, or no-framework claims are in scope

3. Prefer layout primitives that match the invariant.

- use grid, subgrid, flexbox, logical properties, and intrinsic sizing before fixed pixel compensation
- use container queries for component-size-driven layout instead of viewport media queries when the container is the real invariant
- keep breakpoint, container, and spacing tokens stable enough that hover, focus, content changes, and localization do not shift unrelated layout
- define measurable layout contracts for shared or fragile surfaces and verify them through browser geometry where appropriate

4. Consider modern CSS features with fallbacks.

- a new CSS feature must solve a named layout, cascade, color, typography, motion, or interaction invariant and have project-specific support and fallback evidence
- keep browser-release facts, feature-introduction versions, and feature-specific adoption examples in a versioned source pack
- use `@supports` only as a syntax or capability gate. Independently verify semantics, accessibility, and fallback behavior in supported browsers
- treat newly available, draft, limited-availability, experimental, or single-engine features as requiring project support and fallback checks

5. Verify rendered and accessible behavior.

- run the project CSS build, formatter, linter, and generated-output inspection when available
- inspect computed styles, cascade layer order, selected image candidates, layout shift, focus states, hover states, and reduced-motion states
- when tokens encode relationships, inspect resolved values and representative dependent states after changing the controlling source token or theme input in a disposable browser or source probe
- when a token file, design contract, or exported theme drives CSS, verify both the source token diff and the rendered computed styles for affected components
- verify representative mobile, breakpoint, desktop, wide, zoom, and DPR cases when layout or image selection can change
- for tables and dense data layouts, route header associations, DOM reading order, and semantic table structure to `html_quality.md`; in this guide verify CSS-owned reflow or horizontal-scroll strategy, sticky positioning, clipping, visual order, focus visibility, and zoom behavior instead of fixing overflow with arbitrary width compensation
- check color contrast, non-color state cues, keyboard focus visibility, text clipping, and user preference media features
- use the project's stated accessibility target. Absent one, apply the public-web default from `website_frontend_quality.md`; use this guide to verify the CSS-specific evidence behind that target, such as contrast tokens, focus styles, forced-colors behavior, text spacing, reflow, zoom, target size, reduced motion, and non-color state cues
- classify validator, Lighthouse, browser console, and compatibility-tool output before using it to drive edits

## Output

Provide:

1. browser baseline, CSS support, and source facts used
2. affected token roles, token relationships, cascade, selector, layout, animation, and generated-output contracts
3. modern CSS features considered, adopted, deferred, and fallback decisions
4. build, lint, browser, viewport, accessibility, and compatibility checks run
5. unsupported browsers, unverified states, and residual risk

## Guardrails

- Do not add modern CSS merely because it is new; tie it to a concrete layout, cascade, color, or interaction invariant.
- Do not turn every value into a token; tokenization should clarify a decision, relationship, or reuse contract.
- Do not use `!important`, deep selectors, page-local overrides, or child compensation to hide ownership problems.
- Do not claim Baseline support proves accessibility, performance, visual quality, or support for embedded web views.
- Do not treat one browser's release notes or ChromeStatus entry as cross-browser support.
- Do not adopt limited-availability or experimental features without progressive enhancement and project approval.
- Do not introduce externally hosted CSS, fonts, images, cursors, masks, or other CSS-loaded assets unless project policy, licensing, privacy, CSP, and egress expectations allow them.
- Do not clear a visual defect by weakening semantics, source ownership, accessibility, or maintainability.
