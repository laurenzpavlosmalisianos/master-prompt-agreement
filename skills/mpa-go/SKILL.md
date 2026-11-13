---
name: mpa-go
description: Checks for Go modules, toolchains, concurrency, and unsafe code. Use when changing go.mod, the go or toolchain directive, or a published module's API, or when writing goroutines and channels, cgo or unsafe code, or file access under a root directory.
---

# Go

- A `go` command can download and run a different toolchain through `GOTOOLCHAIN` and the `toolchain` directive. Know which toolchain runs.
- Raising the `go` directive changes language semantics and `GODEBUG` defaults for the module and raises the floor for its consumers. Do it only when the task calls for it, and check the release notes for changed defaults and removed compatibility settings.
- A breaking change to a published module at v1 or later needs a new major version with a `/v2` or later import path. A v0 module carries no such rule.
- Run `go test -race` on changed concurrent code. The race detector finds only the races the tests execute.
- Make goroutine ownership and shutdown explicit. A goroutine blocked on a channel or a context nobody cancels leaks without any error.
- For filesystem containment, open through a root-relative handle such as `os.Root`; the `mpa-secure-coding` skill covers the check-then-reopen race. A directory root is not a sandbox.
- Changing a serializer's version or options can change output bytes, duplicate-key handling, and error text while the code still compiles. Compare the wire output.
- For cgo and `unsafe`, state pointer ownership, lifetime, and alignment assumptions, and follow the cgo pointer-passing rules.
- Run `govulncheck` or the project's equivalent when dependencies or exposed parsers change. It reports by reachability.
