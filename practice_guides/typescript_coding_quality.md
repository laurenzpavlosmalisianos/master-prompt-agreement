# TypeScript Coding Quality Practice Guide

Use this Practice Guide when a task touches TypeScript, `tsconfig`, module resolution, declaration emit, type boundaries, package exports, runtime validation, or TypeScript release migration. Do not load it for plain JavaScript work unless TypeScript configuration or types are affected.

Before making source-sensitive recommendations, use project `SOURCE_PACKS.md` and `SOURCE_UPDATE.md` when present, then check current official TypeScript, runtime, package-manager, and framework sources for the active surface.

## Workflow

1. Frame the active TypeScript contract.

- read the project contract, pinned TypeScript version, runtime, package manager, framework, bundler, `tsconfig`, package `type`, exports, imports, and declaration settings
- check current official TypeScript sources before relying on unpinned compiler defaults, lib targets, module resolution, or release behavior
- for new or unpinned TypeScript work, use the current stable TypeScript line and current official defaults as the baseline; support older compiler behavior only when the project contract, runtime, dependency graph, or tooling evidence requires it, and record the reason and revalidation trigger
- distinguish TypeScript's static checks from runtime validation, bundler behavior, test behavior, and framework conventions

2. Keep module and config behavior explicit.

- for code executed directly by Node.js, use the Node module mode matching the supported Node and package semantics, such as `node18`, `node20`, or another project-pinned mode. Use `nodenext` only when the project intentionally accepts floating latest-stable Node semantics. Use `bundler` when the actual bundler, runtime, or TypeScript runner applies bundler-style module resolution; import transformation is not a prerequisite
- avoid `classic`, `node10`, and broad path aliases unless the runtime or bundler also resolves them
- keep `target`, `lib`, JSX mode, declaration emit, source maps, and incremental settings aligned with deployment and package consumers; choose `target` for emitted JavaScript syntax and `lib` for APIs supplied by the runtime or declared polyfills
- prefer `strict` type checking for new code; record legacy exceptions with scope, owner, reason, and removal or revalidation trigger instead of relying on implicit defaults
- treat compiler migration aids, declaration ordering changes, and native-compiler or major-version behavior as migration-specific, not permanent defaults
- for native-compiler or major-version migration work, distinguish stable, release-candidate, and nightly channels; treat non-stable channels as source-sensitive; inventory changed defaults, removed or no-op compiler options, compiler-API consumers, peer dependencies, embedded-language or editor tooling integrations, side-by-side compiler needs, and checker/builder parallelism, including reproducibility, CPU, and memory impact in CI and developer environments
- treat compiler-API consumers, custom language-service plugins, transformers, and compiler-host integrations as migration blockers until the target major exposes a supported API or the project approves a side-by-side compatibility plan
- use new `target` values only when the build pipeline and deployed runtimes accept the emitted syntax; use new `lib` values only when the APIs exist at runtime or are deliberately polyfilled

3. Design type boundaries for maintainability.

- infer local implementation details but annotate exported functions, public objects, callbacks, and ambiguous generics
- prefer discriminated unions, `unknown` plus narrowing, branded types only where useful, and `satisfies` for checked object literals
- avoid `any`, non-null assertions, unchecked indexed access, and type assertions unless the invariant is local and explained
- validate untrusted runtime data at boundaries; interfaces do not validate JSON, HTTP, storage, environment, or CLI input
- for asynchronous, I/O, workflow, or service-layer code, make success, expected failure, required dependencies, cancellation, retry, timeout, and resource-lifetime behavior explicit in the public contract or local boundary; do not hide recoverable failures behind thrown unknowns, ambient globals, or unbounded promises when callers need to handle them
- keep generated types, declaration files, API schemas, and runtime validators synchronized when one changes

4. Preserve source and package contracts.

- keep imports and exports stable for package consumers; verify package subpath imports and exports before changing them
- keep type-only imports and value imports accurate so bundlers and runtimes do not receive phantom values or missing side effects
- treat DOM, ES lib, Node, and framework types as versioned inputs, not universal truths
- treat emitted JavaScript and source maps as public artifacts when published or deployed; do not hand-edit generated output, and verify source-map settings do not expose inline sources, private paths, secrets, or internal code beyond the intended audience
- for bundled libraries, do not treat `moduleResolution: bundler` as proof of consumer compatibility; bundle declarations or validate preserved declaration imports under the intended consumer resolution modes
- avoid changing lint, formatter, transpiler, test, or bundler configuration as part of a feature unless that is the task

5. Verify with the actual toolchain.

- run `tsc --noEmit` or the project type-check command
- run tests, lint, formatting, and production build when affected
- verify declaration emit and package entry points for libraries
- verify runtime behavior for code paths where TypeScript cannot prove input shape, module loading, or environment behavior
- test success, expected-failure, cancellation, timeout, retry, and cleanup behavior for async or resourceful code when those semantics are part of the contract
- state clearly when dependencies, package manager, Node runtime, or framework tooling cannot be run

## Output

Provide:

1. TypeScript, runtime, module, lib, and official source facts used
2. affected `tsconfig`, package, module, type, and runtime contracts
3. static-type, runtime-validation, async/resource, package, migration, and declaration risks
4. type-check, test, lint, format, build, and declaration checks run
5. unverified runtime or toolchain states and residual risk

## Guardrails

- Do not treat type success as runtime validation.
- Do not paper over errors with `any`, assertion casts, or non-null assertions without proving the invariant.
- Do not migrate module resolution, package type, target, or strictness silently.
- Do not rely on compiler defaults when a project contract needs reproducible behavior.
- Do not adopt preview compiler behavior as default guidance without current official confirmation and project approval.
