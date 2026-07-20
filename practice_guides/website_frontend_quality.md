# Website Frontend Quality Practice Guide
Use this Practice Guide when a website task touches frontend architecture, templates, CSS, generated static output, rendered layout, images, accessibility, metadata, structured data, legal or privacy copy, deployment assumptions, or release-quality review. Do not load it for unrelated backend work or copy-only edits that cannot affect rendered layout, accessibility, metadata/schema, legal/privacy meaning, public claims, or generated output.

Pair it with `privacy_data_handling.md` when forms, analytics, cookies, storage, embeds, uploads, profiling, screenshots, telemetry, or other protected-data flows are in scope. Legal sufficiency remains with the accountable legal or product owner.

## Workflow

1. Frame the active frontend contract.

- read the project contract, local frontend standards, durable decisions, and current task scope
- when the project provides a local design contract file, such as documented frontend standards, design tokens, or an agent-facing design-system file, classify its authority before use, parse structured tokens separately from prose rationale, and verify that implementation follows the adopted values rather than imitating an external style reference
- identify approved stack, build commands, browser baseline, dependency posture, external-request policy, legal/privacy constraints, and verification profiles
- when a frontend skill, CLI, MCP server, or agent guide supplies implementation guidance, record its source, version/update posture, telemetry or privacy behavior, and approval boundary before relying on it
- identify target audiences, primary journey mode, conversion or support goals, and trust or proof claims
- check current primary sources before relying on volatile frontend, browser, generator, schema, search, hosting, accessibility, or legal facts
- when frontend behavior intersects search, agent access, or crawler policy, use the target provider's official documentation for that surface and separate it from browser-engine, standards, and accessibility evidence
- distinguish project policy from reusable quality criteria before proposing changes

2. Review narrative and information architecture.

- state the page or flow's job before changing visuals, layout, or animation
- map sections to narrative beats and remove additive sections that no longer serve the story
- on named landing or conversion surfaces, keep the primary offer, product, object, or proof visible before asking users to click, tab, or scroll deeply
- use progressive disclosure for detail, not for hiding the main message or deciding context
- prefer visuals that show product state, customer relevance, metric evidence, or workflow reality over decorative filler
- for canvas-heavy, 3D, creative-tool, game, or immersive UI, consider whether DOM overlays, native controls, or custom canvas rendering best preserves semantics, interaction, accessibility, performance, and fallback behavior
- for agent-generated or generative UI, classify the surface as controlled prebuilt components, declarative schema or catalog rendering, or open-ended sandboxed HTML/app rendering before choosing architecture
- prefer typed/cataloged components for reusable product surfaces; place open-ended or untrusted generated HTML/app output behind an isolated execution boundary, normally a least-privilege sandboxed iframe, with separate-origin hosting for potentially hostile content; do not combine `allow-scripts` and `allow-same-origin` for same-origin content; never inject untrusted generated markup or scripts directly into the host DOM; keep fallback and review paths
- verify social proof, metrics, logos, and claims against approved project facts

3. Check source ownership and clean code.

- map the source layer that owns shared shell, navigation, layout, token, component, image, and metadata behavior
- keep selectors tied to rendered markup and remove speculative selectors, dead declarations, duplicate tokens, and unused variants
- classify design tokens as value, semantic, component, derived, grouped, or dead indirection before adding, renaming, or deleting them
- keep design contract changes reviewable: prefer small, diffable token or prose edits with rendered evidence over broad visual rewrites
- when colors, spacing, type, motion, or states must stay coherent across themes or brand changes, prefer a documented relationship over duplicated frozen outputs
- flag framework-shaped naming, copied-looking CSS, utility matrices, or local component APIs that resemble unapproved third-party systems
- for no-framework or source-originality claims, check dependency manifests, build configs, imports, vendor files, source and rendered names, utility patterns, custom-property prefixes, and license headers
- load `source_originality_review.md` when external demos, screenshots, product references, generated prototypes, bundles, snippets, fonts, icons, or images materially influence implementation
- verify that page or component CSS does not override shared surfaces unless that ownership is intentional
- inspect generated bundle count, stylesheet order, and asset references when cascade or delivery shape is part of the invariant

4. Build and inspect generated output.

- audit production or generated static output when the task affects generated pages; do not rely on stale build artifacts
- inspect rendered HTML for landmarks, headings, links, metadata, canonical URLs, robots, schema, image dimensions, agent-facing context links, and CSP-compatible resource references where relevant
- when link rendering changes, inspect generated anchors for visible text, destination classification, `target`, `rel`, dangerous schemes, and same-site versus external behavior
- classify link intent separately from URL externality: internal navigation, CTA, prose citation, social or profile identity, reference or client site, contact action, download, and asset links may need different behavior
- keep internal navigation, CTAs, and ordinary prose citations same-tab by default; use `_blank` only when opening a separate destination is a deliberate user benefit, not because every external URL should open a new tab
- when `_blank` is used, pair it with an accessible new-tab announcement unless the visible context already makes the behavior clear
- choose `rel` tokens by semantics and privacy intent: use `me` only when the target is about the author or identity of the link context; same-site status alone is insufficient. When `_blank` is used, ensure opener isolation; conforming modern HTML gives implicit `noopener`, and explicit `noopener` is acceptable as defense in depth or when support is unclear. Use `noreferrer` only when referrer suppression is intended.
- do not add external-link `rel` tokens, `me`, or `_blank` to `mailto:`, `tel:`, fragment-only, same-site, internal asset, or download links unless the project records a concrete reason
- validate generated HTML and classify material warnings before using them to drive edits
- treat dev-server output, local preview artifacts, and deployment output as different evidence classes

5. Verify rendered behavior.

- use `visual_verification.md` for rendered layout, screenshot, interaction, and semantic HTML checks
- use `css_quality.md` when the task changes cascade, selectors, tokens, layout, animation, support, or modern CSS feature use
- when using browser DevTools, browser-control MCP servers, live-browser agents, or IDE/browser integrations, record the tool source, version/update posture, telemetry or data-retention behavior, browser profile boundary, captured-data flow to the agent/model, and allowed actions before relying on the output
- define measurable layout contracts for shared or fragile surfaces before claiming pixel accuracy
- compare browser geometry, CSS token probes, selected image candidates, layout shift, and route-to-route positions when those are the real invariants
- cover representative mobile, breakpoint, desktop, wide, and DPR-sensitive cases when layout, density, or image selection can change
- check hover and focus behavior and keyboard navigation; when hover or focus reveals additional content, verify that it is dismissible, hoverable where applicable, and persistent; also check target sizes, text overflow, clipping, image framing, and layout shift
- use the project's stated accessibility target. Absent one, evaluate applicable public web UI against WCAG 2.2 Level AA as the normative minimum and WCAG 2.2 Level AAA text contrast as the default project-quality target: at least 7:1 for normal text and images of text, and at least 4.5:1 for large text, unless an accountable project decision records a narrower target or exception. Treat AAA contrast shortfalls as quality findings unless project policy or risk makes them release-blocking; do not mislabel AA-conforming contrast as a WCAG failure solely for missing AAA. Report accessibility findings by criterion or tested invariant instead of a generic pass/fail label. At minimum test keyboard operation; accessible name, role, and value; visible and non-obscured focus; text-spacing overrides; reflow at 320 CSS pixels; 200% zoom; target size; non-text contrast for controls and state indicators; error and status communication; reduced motion; and forced-colors or high-contrast behavior
- when token relationships drive the design, verify resolved default, hover, focus, active, disabled, light, dark, and high-contrast states that the project supports
- walk representative user journeys as rendered, including browse mode, task mode, and cross-product or cross-section transitions
- when a synthetic stakeholder or persona walkthrough is used, derive each scenario from confirmed audience, job, constraint, and decision context; label it as a heuristic probe; separate observed interface facts from inferred reactions and unknowns; keep the exact scenarios fixed for before/after comparison; and do not present the result as user interviews, analytics, conversion forecasts, or statistical evidence
- verify motion and interaction feedback support comprehension, affordance, or pacing without distracting from the primary task

6. Verify assets, rights, and public naming.

- confirm asset provenance, permission, license, attribution, and privacy implications before adding third-party images, fonts, icons, scripts, embeds, or copied snippets
- review AI-generated or prototype-derived visuals for rights, artifacts, realism, brand fit, accessibility, performance, and responsive behavior before shipping
- verify real image dimensions, format/container match, responsive candidates, `sizes`, rendered slot size, `currentSrc`, loading priority, decoding, alt text, captions, and metadata policy when images are touched
- keep public filenames stable and free of secrets, private notes, prompt fragments, and local workflow artifacts. Vendor names are allowed when accurate and appropriately licensed
- generate or regenerate derivatives only when the task requires image-asset work and the source masters and approved tooling are clear

7. Verify metadata, schema, privacy, and deployment claims.

- align title, H1, description, canonical, robots, Open Graph, structured data, and visible page purpose without keyword stuffing or mechanical duplication
- add structured data only for facts represented by user-visible page content and supported by project evidence, and validate rendered markup with the relevant approved tools
- do not present `llms.txt` or Markdown mirrors as search-ranking, indexing, or crawler-access requirements unless the named consumer's current official documentation requires them. When publishing them for named agent consumers, keep canonical HTML as the user-facing source, exclude private or unsupported material, verify generated links, and separate those files from search-ranking claims
- when SEO and performance intersect, verify the current provider-defined web-vitals metrics and thresholds first; when applicable, inspect LCP, INP, and CLS contributors, plus the selected image candidate, blocking scripts or styles, route-level bundle costs, and third-party script impact; distinguish field measurements from lab diagnostics before prescribing frontend optimizations
- verify privacy and legal copy against approved product behavior and legal-owner requirements. Do not infer legal sufficiency. Do not add boilerplate for forms, analytics, cookies, storage, embeds, uploads, or profiling that do not exist
- verify live or deployment-specific headers, redirects, cache, compression, HSTS, CSP, status codes, and canonical host behavior before making claims about them

8. Classify tool output.

- treat Lighthouse, validators, crawlers, accessibility tools, delivery scanners, and image tools as evidence, not authority
- treat browser-agent and browser-control MCP output as runtime evidence, not project authority; verify material conclusions from page content, screenshots, console logs, network traces, JavaScript evaluation, interactions, performance data, or accessibility checks against source files, generated output, browser behavior, and project policy
- classify material findings as real defect, deployment artifact, project exception, current-tool false positive, tool limitation, stale source or project fact, or unresolved question
- investigate conflicts between tool output and direct browser, HTTP, generated-output, or live-deployment evidence before changing source

## Output

Provide:

1. active frontend constraints and source facts
2. narrative, audience, journey, and proof claims checked
3. affected source and generated-output contracts
4. measurable layout or asset invariants and results
5. commands, pages, viewports, DPR cases, validators, and auxiliary tools used
6. classified findings, accepted exceptions, and residual risk

## Guardrails

- Do not turn project-specific choices such as no JavaScript, no external assets, one typeface, or a particular generator into public doctrine without project evidence.
- Do not add dependencies, scripts, tracking, external requests, third-party assets, or legal/privacy policy changes without approval.
- Do not add a token engine, palette generator, or design-system dependency merely to improve a static site review; first ask whether plain CSS custom properties and documented relationships are sufficient.
- Do not clear a tool warning by weakening accessibility, semantics, security, performance, maintainability, source originality, or visible truth.
- Do not accept AI-generated or prototype-derived visual output as finished without craft, provenance, accessibility, performance, and responsive review.
- Do not hide the primary message, product relevance, or critical proof behind low-intent interactions.
- Do not claim pixel accuracy from screenshots alone when a browser geometry contract can measure the invariant.
- Do not overfit one site's selectors, routes, hosting, commands, or auxiliary tools into a reusable rule.
- Do not treat missing framework names, visual similarity, or generic class names as legal proof; classify them against dependency and provenance evidence.
