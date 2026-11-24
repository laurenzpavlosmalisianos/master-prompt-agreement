---
name: mpa-javascript-typescript
description: "Checks for JavaScript and TypeScript package shape, type stripping, and untrusted input. Use when changing tsconfig, module format, exports, or the compiler version, publishing a package, or handling postMessage, object merging, parsed external data, or browser extensions."
---

# JavaScript and TypeScript

## Package shape

- Module format, package `type`, `exports`, entry points, compile target, and polyfill policy are consumer interfaces; change them only when the task calls for it and say so in the report.
- Changing `module`, `moduleResolution`, `target`, `lib`, strictness, or the TypeScript major version alters emitted code, implicit defaults (such as strictness, `types`, and legacy resolution), and consumer behaviour. List Compiler-API consumers, custom transformers, and language-service plugins before a major compiler upgrade.
- Pick the module mode the code really runs under: a Node mode for code Node executes directly, `bundler` only when a bundler or runner resolves imports. Path aliases must also resolve at run time.
- `moduleResolution: bundler` does not show that published declarations work for consumers; check them under consumers' resolution modes.
- Published source maps can include inline sources and internal paths; check what ships.

## Type stripping and traps

- Types do not validate data; parse JSON, HTTP, storage, environment, and command-line input with a run-time check at the boundary.
- Runtimes that strip types do not type-check, apply `tsconfig`, downlevel syntax, or rewrite `paths`. Keep a separate `tsc --noEmit` step, avoid non-erasable syntax (`enum`, value `namespace`, parameter properties, `import x = require()`), and enable `erasableSyntaxOnly` and `verbatimModuleSyntax` where supported.
- A successful parse, bundle, or lint does not show run-time behaviour; run the code in the target runtime when host APIs or module loading are involved.
- `postMessage`: send sensitive data to an exact `targetOrigin`, not `*`. On receipt, check `event.origin` against an exact allowlist and `event.source` against the expected window; never allowlist the opaque origin `"null"`.
- Merging untrusted objects must block `__proto__`, `constructor`, and `prototype` keys.
- A read followed by a write is not a lock, including across `await`; keep shared updates atomic and reconcile persisted markers with real state after a restart.
- Browser extensions: check each context's effective permissions and behaviour after the service worker restarts or a grant is revoked.
