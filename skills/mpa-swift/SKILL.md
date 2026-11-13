---
name: mpa-swift
description: Checks for Swift concurrency, API availability, persistence, and build plugins. Use when changing language mode or deployment targets, Sendable or actor isolation, Codable or SwiftData models, unsafe pointers, or SwiftPM plugins and macros.
---

# Swift and Apple platforms

- Check that a language feature ships in the toolchain the project pins. An accepted evolution proposal is not necessarily a shipped feature.
- Build and test with the project's scheme, destination, and test plan. A host-only package build does not verify app or device behaviour.
- Language mode, strict-concurrency level, default actor isolation, and deployment targets change how the whole module compiles and behaves. Change them only when the task calls for it.
- The SDK version is not the deployment target. Gate newer APIs with `#available` or `@available`, keep a fallback, and test on the oldest supported OS where possible.
- `@unchecked Sendable`, `nonisolated(unsafe)`, and `@preconcurrency` silence diagnostics without making code safe. Where one is needed, scope it narrowly and state the synchronization invariant next to it.
- Give every unstructured task an owner and a way to cancel it. `Task.detached` drops actor context and priority.
- Synthesized `Codable` is not a durable schema. For persisted data, fix the coding keys and date encoding, and test decoding of older fixtures.
- A SwiftData or Core Data model change is a data migration. Add a migration plan and test upgrades from schemas that shipped. See the `mpa-migration` skill.
- Keep unsafe pointers inside their scoped closures, and state ownership and nullability across C and Objective-C bridges.
- SwiftPM plugins, macros, and package build tools run code on the build machine. Running them from a new dependency is code execution.
- In suites that mix XCTest and Swift Testing, confirm with a deliberately failing probe that a failure raised under one framework fails the run under the other.
