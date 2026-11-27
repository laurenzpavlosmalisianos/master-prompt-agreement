---
name: mpa-javascript-typescript
description: "TypeScript and Node.js release changes through TypeScript 7.0 and Node.js 26 and checks that are easy to miss. Use for any work on JavaScript or TypeScript: tsconfig, modules and exports, type stripping, browser extensions, or a compiler or runtime upgrade."
---

# JavaScript and TypeScript

Current to TypeScript 7.0.2 and Node.js 26.13.1, checked 2026-11-27. For a newer release of either, read what changed after it in the release notes (https://www.typescriptlang.org/docs/, https://nodejs.org/en/blog/release) before relying on this file; up to those versions no lookup is needed.

- A read followed by a write is not a lock, including across `await`; keep shared updates atomic and reconcile persisted markers with real state after a restart.
- Browser extensions: check each context's effective permissions and behaviour after the service worker restarts or a grant is revoked.

## TypeScript releases

- 7.0 is the native compiler. It reports the same errors as 6.0, and every option that 6.0 deprecated is gone: `target: es5`, `downlevelIteration`, `moduleResolution` of `node`, `node10`, or `classic`, `module` of `amd`, `umd`, `system`, or `none`, `baseUrl`, `outFile`, and `false` for `esModuleInterop`, `allowSyntheticDefaultImports`, or `alwaysStrict`. `"ignoreDeprecations": "6.0"` silences them in 6.0 only, so clear the 6.0 deprecation errors before moving to 7.0.
- Defaults since 6.0: `strict` is `true`, `module` is `esnext`, `target` is the newest ECMAScript version, `noUncheckedSideEffectImports` is `true`, `types` is `[]`, and `rootDir` is the folder of `tsconfig.json`. Globals such as `process` or `describe` going missing after an upgrade mean `types` needs entries such as `["node"]`; output landing in `dist/src` means `rootDir` needs setting.
- Errors since 6.0: `import ... assert { ... }` (write `with`), `module Name {}` for a namespace (write `namespace`), and `tsc file.ts` in a folder that has a `tsconfig.json` (TS5112; `--ignoreConfig` compiles the file alone).
- 7.0 checks JavaScript files by the TypeScript rules. Constructor functions, `@enum`, `@class`, Closure-style JSDoc types such as `function(string): void`, values used as types without `typeof`, and a file that assigns both `module.exports` and `module.exports.name` no longer work, and declaration output from `.js` input differs from 6.0.

## Node.js releases

- Supported lines on 2026-11-27: 26 (LTS since 26.13.0), 24, and 22, which ends on 2027-04-30; 20 ended on 2026-04-30. The security releases of 2026-11-11 are 26.13.1, 24.22.3, and 22.23.5 and fix HTTP/2 and TLS flaws rated high.
- 26 removes `--experimental-transform-types`: Node runs a `.ts` file only when its TypeScript syntax can be erased, so no `enum`, no `namespace` with runtime code, and no parameter properties (`erasableSyntaxOnly` in `tsconfig.json` reports them). It ignores `tsconfig.json`, so `paths` do not resolve, and refuses `.ts` files under `node_modules`.
- 26 also removes `http.Server.prototype.writeHeader()` (use `writeHead()`) and the `_stream_*` modules, deprecates `module.register()` at run time in favour of `module.registerHooks()`, turns on the `Temporal` global, and needs native addons rebuilt.
- 25 removed `SlowBuffer`, `fs.F_OK`, `fs.R_OK`, `fs.W_OK`, and `fs.X_OK` (use `fs.constants`), the `recursive` option of `fs.rmdir()` (use `fs.rm()`), and Corepack from the distribution; since 25 the official Linux binaries need `libatomic`.
