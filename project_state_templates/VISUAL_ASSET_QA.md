# Visual Asset QA

Use this task-local evidence template when a visual deliverable needs durable proof that it rendered correctly. It applies to SVG diagrams, README visuals, charts, screenshots, generated images, HTML pages, PDFs, slide decks, and bounded UI surfaces. Do not load it by default.

Store a filled copy only in an approved evidence artifact path for the project. Do not store raw account screenshots, personal data, secrets, local absolute paths, browser profile names, transcript dumps, or private account details in this file.

visual_qa_schema_version: 1
surface_count: [number]
closeout_status: [not-started / passed / passed-with-unverified-states / blocked]

## Use

Use this record when any of the following is true:

- the asset is embedded in a public or project-facing document
- text, labels, arrows, legends, or callouts could overflow, overlap, or be clipped
- the deliverable depends on a generated or transformed visual
- the asset was revised after visual feedback
- the task claims a visual artifact is final

Do not use this record for pure prose edits or trivial unchanged assets.

## Visual Surfaces

| Surface ID | Source Asset Or Page | Embedding Surface | Renderer Or Runtime | Output Artifact | Viewport Or Output Size | Required |
|---|---|---|---|---|---|---|
| [id] | [path or URL] | [README, page, PDF, slide, direct asset, etc.] | [browser, SVG renderer, approved container, etc.] | [artifact path or inspected live surface] | [width x height, viewport, or page] | [yes/no] |

## Render Commands

| Surface ID | Command | Working Directory | Runtime Boundary | Result |
|---|---|---|---|---|
| [id] | `[command]` | `[repo or project root]` | [approved container / browser / renderer] | [passed / failed / not run] |

## Inspection Checklist

- [ ] Source asset parses without errors.
- [ ] Embedded surface renders the expected asset.
- [ ] Text stays inside its intended containers.
- [ ] Arrows, lines, and connectors do not obscure labels or critical content.
- [ ] Panels, cards, callouts, legends, and axes do not overlap.
- [ ] Material visual text, chart labels, legends, callouts, OCR text, and transcribed content match the source or rendered artifact.
- [ ] Contrast meets the task's stated target.
- [ ] Images are non-empty and loaded at non-zero natural dimensions.
- [ ] Mobile and desktop viewports are checked when the surface is responsive.
- [ ] Generated bitmap output is inspected for crop, blur, compression, and unreadable-detail defects.
- [ ] No secret, credential, account, or local machine detail is visible.

## Geometry Contracts

Record explicit measurable invariants before claiming a fragile visual is final.

| Surface ID | Contract | Measurement Method | Tolerance | Result |
|---|---|---|---|---|
| [id] | [example: all node labels remain within node bounds] | [browser box measurement, SVG render, screenshot inspection, etc.] | [exact or numeric tolerance] | [passed / failed / not checked] |

## Deterministic Check Candidates

Use deterministic checks only when they validate a declared contract.

Suitable checks:

- SVG parseability, viewBox presence, and rendered output size
- output artifact exists and is non-empty
- browser image `complete` state and non-zero natural dimensions
- horizontal overflow at declared responsive widths
- declared text or container bounding boxes
- source-to-rendered text checks for labels, chart text, callouts, and OCR-derived claims
- privacy scan for disallowed visible strings

Do not use generic visual scores, model taste judgments, broad pixel-diff gates, model-only OCR, or cross-browser matrices unless the task defines a stable baseline, renderer, viewport, source text, and tolerance.

## Defects And Fixes

| Surface ID | Defect | Evidence | Fix | Recheck |
|---|---|---|---|---|
| [id] | [what was wrong] | [artifact or observation] | [change made] | [passed / failed / pending] |

## Unverified States

List any visual state that was not checked and why.

- [surface/state]:

## Closeout Rules

Use `passed` only when every required surface rendered, required geometry contracts passed, and no required state remains unverified.

Use `passed-with-unverified-states` when the required rendered evidence passed but optional states could not be checked.

Use `blocked` when a required renderer, file, browser surface, approval, or runtime is missing.
