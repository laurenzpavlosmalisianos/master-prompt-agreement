# Interactive Documentation

This directory contains the human-facing static presentation layer for Master
Prompt Agreement. It illustrates framework architecture and links back to the
canonical Markdown and runtime surfaces. This presentation layer
does not create a second source of framework authority.

Open the downloaded HTML guide at
[`/docs/interactive/index.html`](index.html). It is a presentation layer, not a
hosted or canonical framework surface.

Agents may use the page to explain the framework to a human, but decisions,
setup, verification, and framework changes remain grounded in the canonical
files:

- [`/README.md`](../../README.md)
- [`/docs/`](../README.md)
- [`/master_service_agreement.md`](../../master_service_agreement.md)
- [`/runtime/`](../../runtime/)
- [`/task_orders/`](../../task_orders/)
- [`/practice_guides/`](../../practice_guides/)
- [`/project_state_templates/`](../../project_state_templates/)

## Structure

```text
docs/interactive/
├── README.md
├── index.html
├── styles.css
├── tsconfig.json
├── src/
│   └── app.ts
└── generated/
    └── app.js
```

- `index.html` owns all first-paint content and document semantics. The guide is
  readable before JavaScript runs, and the inline diagram has intrinsic width,
  height, and view-box dimensions.
- `styles.css` owns the single semantic token vocabulary used in light, dark,
  high-contrast, and forced-color environments.
- `src/app.ts` progressively enhances the existing diagram controls and turns
  the link-based framework map into reciprocal tab/tabpanel relationships. It
  must not construct initial content. The diagram-control grid reserves its
  final geometry before the deferred script runs, but remains visually hidden,
  disabled, and absent from the accessibility tree unless setup succeeds. A
  scripting-disabled load omits that inert grid during its initial layout.
- `generated/app.js` is checked-in compiler output. It is a deferred classic
  script with no module imports or build-server dependency, a design intended
  for downloaded-directory and HTTP loading. Actual `file://` and HTTP behavior
  remains a rendered acceptance check, not a source-only guarantee.
- `tsconfig.json` records the exact source, output, language, and strictness
  contract.

The table of contents, inline SVG, and tabs are explanatory aids. They must stay
grounded in linked canonical files and must not introduce doctrine, setup rules,
source-monitoring rules, or project-specific guidance absent from the framework.

## Verification

The checked-in `generated/app.js` is byte-for-byte reproducible from
`src/app.ts` with TypeScript 7.0.2 and the committed `tsconfig.json`. Use an
already available, approved compiler at that recorded baseline; do not fetch a
compiler or run a package-manager installer merely to verify this presentation
layer.

Use the commands below to verify the compiler version, type-check without
writing files, and compare a fresh temporary emit with the checked-in script.
The sole emitted file must be `app.js`; the tracked tree is never a verification
emit destination. A missing or different compiler, failed compile, unexpected
output, or byte drift fails verification.

The compiler version and JavaScript target answer different questions.
TypeScript 7.0.2 is the source-analysis and reproducibility baseline;
`target: ES2025` is the reviewed emitted-syntax policy and is not a quality
ranking over older targets. The current source deliberately avoids a dependency
on an ES2025-only feature. Change the target only with an explicit browser
compatibility baseline and rendered regression evidence.

For focused diagnosis, first type-check without writing generated files:

```bash
tsc --version
tsc --project docs/interactive/tsconfig.json --noEmit
```

The version command must report `Version 7.0.2`; another compiler cannot prove
the recorded byte-reproducibility contract.

When `src/app.ts` changes, compile into a new empty review directory and compare
the result before replacing the tracked script:

```bash
tsc --project docs/interactive/tsconfig.json --outDir <new-empty-review-dir>
diff -u docs/interactive/generated/app.js <new-empty-review-dir>/app.js
```

Replacing `generated/app.js`, changing the compiler baseline, or changing the
target is a reviewed source change. If the recorded compiler is unavailable,
disclose the verification gap instead of downloading a different version or
overwriting the tracked script with unreviewed output.

Then run the applicable repository checks described in
[`CONFORMANCE.md`](../../CONFORMANCE.md).

Before treating a visual change as final, inspect both `file://` and HTTP loads
at 320, 375, 768, 1280, and 1920 CSS-pixel widths. Check light, dark, increased
contrast, forced colors where available, keyboard-only operation, and a
JavaScript-disabled load. For the framework-map tabs, check a direct panel
fragment load, pointer and Enter activation, Arrow/Home/End/Space activation,
copy and reload, Back and Forward traversal, an empty fragment, an unknown
fragment, and a valid fragment outside the tab panels. Confirm that every panel
fragment, selected tab, visible tabpanel, focus, and history entry agree without
an unexpected scroll. Empty and unknown fragments must be replaced in place by
the default tab fragment; a valid fragment outside the tab panels must remain
intact without changing the current tab. Also confirm that the page has no
body-level horizontal overflow, console or policy errors, failed local
resources, or layout shift during initial rendering.
