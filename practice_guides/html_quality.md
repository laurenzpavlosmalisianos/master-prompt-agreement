# HTML Quality Practice Guide

Use this Practice Guide when a task touches authored HTML, generated HTML, templates that emit HTML, Markdown render hooks, forms, links, tables, media, embeds, document-owned metadata, landmarks, headings, accessible names, ARIA use, parser or validator warnings, or semantic markup review. Pair it with `website_frontend_quality.md` for whole-page frontend quality, `css_quality.md` for cascade and layout, `visual_verification.md` for rendered evidence, and `seo.md` for search ranking, structured data, social/search metadata, and canonical strategy.

Before source-sensitive HTML recommendations, use project `SOURCE_PACKS.md` and `SOURCE_UPDATE.md` when present, then check the relevant section of the WHATWG HTML Standard, MDN reference docs, W3C/Nu validator behavior, WCAG/WAI guidance, and generator-specific docs for the active surface. Check browser compatibility data only when support, behavior, or fallback semantics materially affect the task. Treat browser support, validator diagnostics, ARIA guidance, document-owned metadata behavior, and generated-output rules as source-sensitive.

## Workflow

1. Frame the source and generated-output contract.

- identify the source layer that emits the markup: static HTML, framework component, template, render hook, Markdown processor, CMS, sanitizer, or generated bundle
- inspect generated HTML when templates or generators are involved; do not infer final semantics from source templates alone
- verify document-level requirements such as `doctype`, `html lang`, character encoding, viewport policy, title, and document-owned metadata only where the page surface owns them
- distinguish HTML semantics from CSS visual treatment and JavaScript behavior; route those concerns to their guides when they drive the change
- define what users, assistive technologies, forms, scripts, and approved downstream consumers are expected to read or activate

2. Use native semantics first.

- prefer the native element that matches the meaning and interaction before adding ARIA, roles, keyboard handlers, or custom widgets
- verify landmarks, headings, sections, navigation, main content, lists, tables, figures, captions, addresses, quotes, code, time, and data elements against their real content role
- keep heading order and sectioning meaningful without using heading levels as purely visual sizing controls
- ensure IDs are unique, fragment targets exist, labels reference existing controls, and generated names stay stable
- remove redundant or misleading roles, labels, `aria-*`, `tabindex`, hidden states, and inert or disabled behavior that conflict with native semantics

3. Review links, buttons, forms, and states.

- use links for navigation and buttons for actions unless the project records a reason to diverge
- classify link intent: internal navigation, prose citation, external reference, profile identity, contact action, download, asset, or application action
- verify `href`, schemes, target behavior, `rel`, referrer policy intent, download behavior, accessible link text, and markup-owned new-tab or download affordances where applicable
- for forms, verify label association, grouped controls with `fieldset` and `legend` where needed, button `type`, labelable elements, submitter-specific form attributes, name/value submission, required fields, input types, autocomplete, validation, error summary, inline errors, status messages, disabled/read-only behavior, and successful/failed submission flows
- keep error, loading, success, and live status communication available to keyboard and assistive-technology users

4. Review tables, media, embeds, parser behavior, and generated content.

- use tables for tabular data and provide headers, captions, scope or associations, and markup-owned data contracts; route layout responsiveness to `css_quality.md` or `visual_verification.md`
- classify each image by its purpose in the rendered context before judging or generating text alternatives: decorative or nearby-text-redundant images use an empty `alt`; functional images communicate the action or destination; informative images convey the context-relevant meaning; and complex images provide a concise label plus an equivalent adjacent or programmatically associated explanation. Verify any model- or tool-suggested text against the actual image, surrounding content, accessible name, and intended function before acceptance; also check width/height attributes, responsive candidates, captions, lazy loading, decoding, and privacy-sensitive metadata policy when images are in scope
- verify audio, video, captions, transcripts, controls, autoplay, reduced-motion, and fallback behavior when media is in scope
- review invalid nesting and parser-repair risks: nested interactive controls, invalid list/table/form structure, invalid descendants, duplicate attributes, void-element misuse, raw-text escaping, and template output that the browser reparses differently from source
- escape generated content for its exact text, attribute, URL, raw-text, Markdown-rendered, or template context; reject unsafe schemes and review `href`, `src`, `srcdoc`, `action`, and `formaction` as generated-output sinks
- isolate untrusted or open-ended generated HTML behind an approved sandbox boundary; do not inject untrusted markup or scripts directly into the host DOM
- for iframes and embeds, review sandbox, permissions policy, referrer policy, title, loading, dimensions, fallback, and third-party privacy behavior
- for browser-mediated capability controls that request or deliver powerful data, verify standards maturity and actual target-browser support, secure-context and permissions-policy preconditions, genuine user activation, fallback semantics, data minimization, success/cancel/error states, active-use indication, revocation or stream shutdown, and anti-spoofing constraints; browser-owned prompting does not by itself prove privacy, accessibility, lifecycle, or fallback quality

5. Validate and classify diagnostics.

- run the project's HTML validation, parser, accessibility-tree, component, or generated-output checks when configured
- use W3C/Nu validator output and browser parser behavior as diagnostics to classify, not as automatic edit instructions
- classify each material diagnostic as real defect, project exception, generator limitation, current-tool false positive, stale output, or unresolved question
- verify semantics through source, generated HTML, browser behavior, and accessibility tree when the change affects meaning or interaction
- do not clear warnings by weakening semantics, accessibility, security, privacy, maintainability, or visible truth

## Output

Provide:

1. source layer, generated-output path, standards, validator, browser, and generator facts used
2. affected document, landmark, heading, link, form, table, media, metadata, ARIA, and embed contracts
3. semantic, accessibility, parser, validator, privacy, and generated-output risks
4. validation, accessibility-tree, browser, source, generated-output, and interaction checks run
5. unresolved browser, generator, validator, ARIA, or assistive-technology gaps and residual risk

## Guardrails

- Do not use ARIA to paper over an available native element.
- Do not infer accessibility from visual appearance or CSS class names.
- Do not treat generated HTML as correct until inspected after the active build or render step.
- Do not add `_blank`, `rel`, structured data, metadata, or hidden text mechanically across all links or pages.
- Do not inject untrusted generated markup into the host DOM without an isolation boundary.
