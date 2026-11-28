---
name: mpa-go
description: "Go release changes through 1.27 and checks that are easy to miss. Use for any work on Go code: go.mod and toolchain directives, goroutines, serialization, unsafe or cgo code, or a Go version upgrade."
---

# Go

Current to Go 1.27.4, checked 2026-11-27. The entries are the changes that are easy to miss, not the full release notes: for a change they do not mention, and for anything newer than 1.27.4, read the release notes (https://go.dev/doc/devel/release) before relying on this file.

- Raising the `go` directive changes language semantics and `GODEBUG` defaults for the module and raises the floor for consumers. Do it only when the task calls for it, and check the release notes for changed defaults and removed compatibility settings.
- Run `go test -race` on changed concurrent code; the race detector finds only races the tests execute.
- From 1.27 the `goroutineleak` profile in `runtime/pprof` finds goroutines that are blocked for good; it can miss one whose blocking channel or lock is still referenced from a global or a runnable goroutine.
- Changing a serializer's version or options can change wire bytes, duplicate-key handling, and error text while compiling cleanly; compare wire output. From 1.27 `encoding/json` runs on the v2 implementation, so a toolchain upgrade alone can change its error text.
- Security fixes after 1.27.0 are in 1.27.2 (the go command, `crypto/tls`, `html/template`, `net/http`, `net/textproto`, `os`), 1.27.3 (`crypto/x509`), and 1.27.4 (cgo, the go command, the compiler, the linker, `net/http`). Go 1.26 has the same fixes in 1.26.9, 1.26.10, and 1.26.11; 1.25 and older receive none.
