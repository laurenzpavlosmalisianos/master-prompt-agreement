---
name: mpa-javascript-typescript
description: Checks for JavaScript and TypeScript package shape, type stripping, and untrusted input. Use when changing tsconfig, module format, exports, or the compiler version, publishing a package, or handling postMessage, object merging, or parsed external data.
---

# JavaScript and TypeScript

## Package shape

- Module format, package `type`, `exports`, entry points, compile target, and polyfill policy are an interface that consumers depend on. Change them only when the task calls for it, and say so in the report.
- In TypeScript, `module`, `moduleResolution`, `target`, `lib`, and strictness change emitted code and consumer behaviour. Upgrading the compiler does too.
- Pick the module mode the code really runs under: a Node mode for code Node executes directly, `bundler` only when a bundler or runner resolves imports. Path aliases must also resolve at run time.
- `moduleResolution: bundler` does not show that published declarations work for consumers. Check them under the consumers' resolution modes.
- Published source maps can include inline sources and internal paths. Check what ships.

## Types and run time

- Types do not validate data. Parse JSON, HTTP, storage, environment, and command-line input with a run-time check at the boundary.
- Runtimes that strip types do not type-check, apply `tsconfig`, downlevel syntax, or rewrite `paths`. Keep a separate `tsc --noEmit` step, and avoid syntax that cannot be erased: `enum`, value `namespace`, parameter properties, `import x = require()`. Where the compiler version has `erasableSyntaxOnly`, turn it on to enforce this.
- Keep type-only and value imports accurate, so that a bundler neither drops a side effect nor emits an import for a type.
- A successful parse, bundle, or lint does not show run-time behaviour. Run the code in the target runtime when host APIs or module loading are involved.

## Traps

- `postMessage`: send sensitive data to an exact `targetOrigin`, not `*`. On receipt, check `event.origin` against an exact allowlist and `event.source` against the expected window. Do not allowlist the opaque origin `"null"`.
- Merging untrusted objects needs `__proto__`, `constructor`, and `prototype` keys blocked.
- A read followed by a write is not a lock, also across `await`. Check that shared updates are atomic, and reconcile persisted markers with real state after a restart.
- Timestamp precision implies neither uniqueness nor order. Keep instants, zoned local times, and durations apart.
- Browser extensions: check each context's effective permissions, and behaviour after the service worker restarts or a grant is revoked.
- Compiler-API consumers, transformers, and language-service plugins can block a major compiler upgrade. List them before starting one.
