---
name: mpa-go
description: "Checks for Go modules, toolchains, concurrency, and unsafe code. Use when changing go.mod, the go or toolchain directive, or a published module's API, or when writing goroutines and channels, cgo or unsafe code, or file access under a root directory."
---

# Go

- A `go` command can download and run a different toolchain through `GOTOOLCHAIN` and the `toolchain` directive; confirm which toolchain runs.
- Raising the `go` directive changes language semantics and `GODEBUG` defaults for the module and raises the floor for consumers. Do it only when the task calls for it, and check the release notes for changed defaults and removed compatibility settings.
- A breaking change to a published module at v1 or later requires a new major version with a `/v2` or later import path; v0 modules carry no such rule.
- Run `go test -race` on changed concurrent code; the race detector finds only races the tests execute.
- Give every goroutine explicit ownership and shutdown; one blocked on a channel send or receive, or an uncanceled context, leaks silently.
- For filesystem containment, open through a root-relative handle such as `os.Root` (1.24+); `mpa-secure-coding` covers the check-then-reopen race. A directory root is not a sandbox.
- Changing a serializer's version or options can change wire bytes, duplicate-key handling, and error text while compiling cleanly; compare wire output.
- For cgo and `unsafe`, document pointer ownership, lifetime, and alignment assumptions and follow cgo pointer-passing rules.
- Run `govulncheck` or the project's equivalent when dependencies or exposed parsers change; it reports by reachability.
