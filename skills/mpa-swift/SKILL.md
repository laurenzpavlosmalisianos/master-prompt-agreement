---
name: mpa-swift
description: "Checks for Swift concurrency, API availability, persistence, and build plugins. Use when changing language mode or deployment targets, Sendable or actor isolation, Codable or SwiftData models, unsafe pointers, or SwiftPM plugins and macros."
---

# Swift and Apple platforms

- Check that a language feature ships in the toolchain the project pins; an accepted evolution proposal is not necessarily shipped.
- Build and test with the project's scheme, destination, and test plan; a host-only package build does not verify app or device behaviour.
- Language mode, strict-concurrency level, default actor isolation, `NonisolatedNonsendingByDefault` (6.2+), and deployment targets change how the whole module compiles and runs. Change them only when the task calls for it; under `NonisolatedNonsendingByDefault`, `nonisolated async` runs on the caller's actor (blocking `MainActor` if assumed to hop off-actor) unless marked `@concurrent`.
- The SDK version is not the deployment target. Gate newer APIs with `#available` or `@available`, keep a fallback, and test on the oldest supported OS where possible.
- `@unchecked Sendable`, `nonisolated(unsafe)`, and `@preconcurrency` silence diagnostics without making code safe; scope narrowly and state the synchronization invariant next to each use.
- Give every unstructured task an owner and cancellation path; `Task.detached` drops actor context and priority.
- Synthesized `Codable` is not a durable schema; fix coding keys and date encoding for persisted data and test decoding older fixtures.
- A SwiftData or Core Data model change is a data migration: add a migration plan and test upgrades from shipped schemas (`mpa-migration`).
- Keep unsafe pointers inside scoped closures and state ownership and nullability across C/Objective-C bridges.
- SwiftPM plugins, macros, and package build tools run code on the build machine (`mpa-dependency-change`).
- In suites mixing XCTest and Swift Testing, confirm with a deliberately failing probe that a failure under either framework fails the run.
