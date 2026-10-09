# Go Coding Quality Practice Guide

Use this Practice Guide when a task touches Go source, `go.mod`, `go.sum`, `go.work`, package APIs, command-line programs, build tags, generated Go, cgo, tests, fuzzing, race-sensitive code, module publishing, or Go release migration. Pair it with `dependency_risk.md` for module changes and `secure_development.md` when security-sensitive code, parsers, cryptography, auth, or network boundaries are in scope.

Before source-sensitive Go recommendations, use project `SOURCE_PACKS.md` and `SOURCE_UPDATE.md` when present, then check current official Go sources such as `go.dev/doc`, `go.dev/ref/spec`, `go.dev/ref/mod`, `go.dev/doc/devel/release`, `go.dev/doc/security`, `pkg.go.dev`, command docs, diagnostics docs, vulnerability management docs, and active tool docs. Treat Go version behavior, standard-library APIs, module proxy behavior, vet analyzers, fuzzing behavior, and vulnerability data as volatile.

## Workflow

1. Frame the active Go contract.

- read `go.mod`, `go.sum`, `go.work`, toolchain directive, supported Go version, module path, package layout, commands, build tags, generated-code markers, test configuration, target `GOOS` and `GOARCH`, and project commands
- distinguish the bundled toolchain from the effective toolchain selected by `GOTOOLCHAIN` and module or workspace directives; establish whether a command may download another toolchain before execution
- distinguish library packages, command packages, internal packages, generated code, examples, tests, tools, and one-off scripts
- keep module path, package names, public API, command behavior, config, environment variables, and file layout stable unless the task explicitly changes them
- do not generalize Effective Go-era guidance over newer project, release, module, or standard-library facts

2. Keep packages and APIs idiomatic and narrow.

- keep package names short, specific, lower-case, and aligned with the import path; avoid stutter and catch-all utility packages
- keep exported identifiers, interfaces, errors, and behavior documented when they form a public API; keep implementation details unexported or under `internal/`, and do not export solely for tests or cross-package convenience
- accept interfaces at boundaries where they reduce coupling; return concrete types unless an interface is the actual contract
- prefer clear error returns with context over panics, logging-only failures, or swallowed errors; preserve inspectable causes with `fmt.Errorf("%w", err)`, `errors.Is`, `errors.As`, or `errors.Join` where those semantics matter
- define nil, zero-value, empty-slice, context-cancellation, timeout, and cleanup behavior for public APIs and reusable helpers
- use generics only when type parameters, constraints, and inference produce a clearer API than concrete code or a small interface
- keep structured logging conventions consistent with the project and standard-library `log/slog` where that is the active logging contract
- avoid global mutable state, hidden goroutine ownership, implicit environment dependencies, and test-only behavior in production code

3. Handle concurrency, I/O, and platform boundaries deliberately.

- pass `context.Context` through cancellable, blocking, network, database, subprocess, and long-running operations; do not store contexts in structs without a project-specific reason
- close files and response bodies, close only sender-owned channels, stop timers and tickers, coordinate shutdown and wait for goroutines, and terminate plus wait for subprocesses at the owning boundary
- check for goroutine leaks, data races, unbounded fan-out, blocked sends, timer leaks, and forgotten cancellation
- validate untrusted paths, URLs, archives, JSON, YAML, templates, and network inputs at the boundary; parameterize SQL and pass subprocess arguments without shell interpolation
- for filesystem containment, prefer supported root-relative handle APIs over checking a pathname and reopening it; verify the chosen operation's platform, symlink, mount, and special-file limits rather than treating a directory root as an OS sandbox
- when changing serializers or their compatibility options, verify wire behavior for duplicate keys, invalid text, nil values, field matching, ordering, custom methods, and error handling where relevant; API compatibility does not establish identical output bytes or error strings
- for cgo, unsafe, syscalls, plugins, signals, or platform-specific files, state ownership, lifetime, alignment, pointer, thread, OS, architecture, and build-tag assumptions
- treat generated code and code generation tools as supply-chain and review surfaces when they affect committed output

4. Manage modules and dependencies with Go tools.

- use `go` commands to maintain module files; keep `go.mod` and `go.sum` committed and synchronized
- run `go mod tidy`, `go mod verify`, or the project-approved equivalents when module graph, checksum, or release changes are in scope
- review direct versus indirect dependencies, replacements, excludes, private module settings, vendoring, proxies, and checksum database behavior
- do not add a dependency when the standard library or a small local function is sufficient and clearer
- for published modules, verify semantic import versioning, `/v2+` module path requirements, tags, release notes, and backward-compatibility promises before changing major-version or public API behavior
- run `govulncheck` or the project-approved vulnerability check when dependencies, networked services, parsers, auth, crypto, or release posture are in scope
- record when dependency, proxy, private module, or network constraints prevent module or vulnerability verification

5. Verify with the actual project toolchain.

- for release migration, check language and library minimum versions, removed compatibility switches, `GODEBUG`, `GOEXPERIMENT`, target support, and changed analyzer defaults; test the affected configurations without silently raising the supported Go version
- run `gofmt` or `go fmt` and the project formatter policy before claiming source-format correctness
- run `go test ./...` or the project-recorded test command for changed packages
- run targeted `go test -race` when concurrency, shared state, handlers, caches, or background workers are affected and the platform supports it
- run fuzz tests when parsers, decoders, protocol handling, or attacker-controlled inputs are in scope and the project has fuzz targets or approves adding them
- run `go vet` and any configured project analyzers such as Staticcheck or `golangci-lint`; do not silently weaken analyzer configuration
- verify command-line behavior, flags, stdin/stdout/stderr, exit codes, environment variables, and files when command packages change

## Output

Provide:

1. Go version, module, workspace, target platform, package, and official source facts used
2. affected API, command, module, dependency, concurrency, I/O, and platform contracts
3. error-handling, context, race, goroutine, dependency, generated-code, and native-boundary risks
4. format, test, race, fuzz, vet, vulnerability, command, and platform checks run
5. unverified Go version, module proxy, dependency, platform, or toolchain states plus residual risk

## Guardrails

- Do not treat `gofmt` as sufficient verification.
- Do not hide errors behind logs, panics, blank identifiers, or broad retries.
- Do not introduce broad interfaces, global state, goroutines, or dependencies without a concrete boundary benefit.
- Do not claim race safety without design reasoning and targeted race or concurrency evidence where feasible.
- Do not publish or release modules from source-tree tests alone when package, module, or CLI distribution behavior is in scope.
