# JavaScript Coding Quality Practice Guide

Use this Practice Guide when a task touches plain JavaScript source, module semantics, runtime APIs, package entry points, generated JavaScript, browser/server/worker behavior, async control flow, or JavaScript release migration. Pair it with `html_quality.md`, `css_quality.md`, and `website_frontend_quality.md` for browser-facing UI work. Use `typescript_coding_quality.md` when TypeScript configuration, declaration emit, type boundaries, or `.ts`/`.tsx` source are affected.

Before making source-sensitive recommendations, use project `SOURCE_PACKS.md` and `SOURCE_UPDATE.md` when present, then check current official ECMAScript, runtime, browser, compatibility, package, and framework sources for the active surface.

## Workflow

1. Frame the active JavaScript contract.

- read the project contract, supported runtimes, module format, package metadata, browser or server baseline, worker or embedded runtime constraints, generated-output path, build pipeline, and test surface
- distinguish authored source from generated JavaScript, host APIs from language semantics, module loading from bundling, and static checks from runtime validation
- check current official language, runtime, and compatibility sources before relying on unpinned syntax, module, host API, or package behavior

2. Keep module and package behavior explicit.

- preserve the project's declared module contract; do not migrate between module systems, file extensions, package type, import style, or entry points silently
- verify that package exports, imports, side effects, conditional branches, subpath availability, CJS/ESM import/require shapes, and generated bundles match the intended consumers
- avoid broad path aliases, implicit resolution assumptions, and environment-specific globals unless the runtime or build contract supplies them
- keep generated JavaScript, source maps, minification, polyfills, and transpilation aligned with the supported runtime and debugging needs

3. Make runtime data and async behavior concrete.

- validate untrusted JSON, HTTP, storage, environment, message payloads, postMessage origin/source/targetOrigin, URL, and CLI input at boundaries
- make expected failure, cancellation, timeout, retry, cleanup, ordering, and idempotency behavior explicit when callers depend on it
- distinguish persistence from concurrency control: verify atomicity of shared updates or exclusive operations, and reconcile durable markers with actual resources after interruption or restart; a read-then-write sequence is not itself a lock
- avoid unbounded promises, swallowed rejections, ambient mutable globals, prototype mutation, and monkey patches unless the project explicitly owns the invariant
- handle time, locale, encoding, floating-point, equality/coercion, optional values, iterator exhaustion, and mutation aliasing deliberately
- distinguish calendar values, zoned local times, instants, and elapsed durations; choose ambiguity and recurrence rules from the domain contract. Timestamp precision does not establish clock resolution, monotonicity, uniqueness, or causal order

4. Preserve security and host boundaries.

- route DOM injection, template injection, eval-like execution, dynamic code loading, prototype pollution, deserialization, credential exposure, or cross-origin behavior through the applicable security guide
- treat browser APIs, server APIs, worker APIs, and embedded runtimes as separate host contracts
- for browser extensions, verify each execution context's effective permissions, target identity, activation requirements, message authority, and lifetime; exercise withheld or revoked grants, restricted targets, worker restart, UI closure, and update paths when affected
- do not trust generated code, dependencies, remote examples, or package scripts without provenance and execution-boundary review

5. Verify in the actual runtime.

- run the project JavaScript syntax, lint, format, test, build, bundle, and package checks when available
- execute representative success, expected-failure, async, cancellation, timeout, cleanup, and environment-specific paths
- when capability detection or fallback loading controls behavior, check native, fallback, unavailable, and failed paths; initialize consumers once their required dependencies are ready, and make reduced fallback semantics explicit
- inspect generated output when the task changes source transforms, entry points, import/export behavior, minification, source maps, or browser/server delivery
- verify target browser, server, worker, or embedded runtime behavior where static checks cannot prove host API, module loading, or environment assumptions
- state clearly when the runtime, dependency graph, package manager, browser, build, or test tooling cannot be run

## Output

Provide:

1. JavaScript, runtime, module, package, and official source facts used
2. affected source, generated-output, module, host API, package, and async/resource contracts
3. runtime-validation, package, security-boundary, migration, and generated-output risks
4. syntax, lint, format, test, build, bundle, package, and runtime checks run
5. unverified runtime or host states and residual risk

## Guardrails

- Do not treat successful parsing, bundling, or linting as runtime validation.
- Do not migrate module format, package type, entry points, transpilation target, or polyfill policy without explicit project evidence.
- Do not adopt proposal-stage language features, experimental host APIs, or runtime-specific behavior as default guidance without current official confirmation and project approval.
- Do not hide recoverable failures behind swallowed rejections, vague exceptions, or implicit globals when callers need a contract.
- Do not use generated JavaScript as the sole source of intent when authored source or a governing design contract exists.
