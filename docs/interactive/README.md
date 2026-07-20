# Interactive Documentation

This folder contains a human-facing static presentation layer for Master Prompt
Agreement. It illustrates the framework architecture and links back to the
canonical markdown files.

Agents may use this page when explaining the framework to a human. They should
still ground decisions, setup, verification, and framework changes in the
canonical markdown and runtime files.

The source of truth remains the markdown framework:

- `README.md`
- `docs/*.md`
- `master_service_agreement.md`
- `runtime/`
- `task_orders/`
- `practice_guides/`
- `project_state_templates/`

The interactive page must not introduce doctrine, setup rules, source-monitoring
rules, or project-specific guidance that is absent from the canonical framework
files.

## Files

- `index.html` is the static entry point.
- `styles.css` owns local presentation styles.
- `app.ts` is the TypeScript source.
- `app.js` is the generated deferred browser script. It is intentionally loaded
  as a classic local script so the guide works from both `file://` and HTTP
  origins without imports or a build server.
- `tsconfig.json` records the TypeScript verification contract.

The table of contents and inline SVG diagram are explanatory aids. They may help
an agent walk a human through the framework, but they must stay grounded in the
linked canonical files and must not become a second rule layer.

## Verification

The checked-in `app.js` is byte-for-byte reproducible from `app.ts` with
TypeScript 7.0.2 and the committed `tsconfig.json`. Use an already available,
approved compiler at that recorded baseline; do not fetch a compiler or run a
package-manager installer merely to verify this presentation layer.

First type-check without writing generated files:

```bash
tsc --version
tsc --project docs/interactive/tsconfig.json --noEmit
```

The version command must report `Version 7.0.2`; another compiler cannot prove
the recorded byte-reproducibility contract.

When `app.ts` changes, compile into a new empty review directory and compare the
result before replacing the tracked script:

```bash
tsc --project docs/interactive/tsconfig.json --outDir <new-empty-review-dir>
diff -u docs/interactive/app.js <new-empty-review-dir>/app.js
```

Replacing `app.js`, changing the compiler baseline, or changing the target is a
reviewed source change. If the recorded compiler is unavailable, disclose the
verification gap instead of downloading a different version or overwriting the
tracked script with unreviewed output.

Then run the framework suite:

```bash
uv run python -B scripts/framework_compliance.py --tree-role authoring-source
```

Also inspect the rendered page in a browser before treating visual changes as
final.
