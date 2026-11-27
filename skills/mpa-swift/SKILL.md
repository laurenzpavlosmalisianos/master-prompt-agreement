---
name: mpa-swift
description: "Swift release changes through 6.4 and checks that are easy to miss. Use for any work on Swift code: concurrency and actor isolation, Codable and SwiftData models, tests, SwiftPM plugins, or a language-mode or toolchain upgrade."
---

# Swift and Apple platforms

Current to Swift 6.4.3, checked 2026-11-27. For a newer Swift release, read what changed after 6.4.3 in the release notes (https://raw.githubusercontent.com/swiftlang/swift/main/CHANGELOG.md) before relying on this file. The entries are the changes that are easy to miss, not the full release notes.

- In Swift 6 mode, or with the `DynamicActorIsolation` upcoming feature, the compiler adds run-time checks of actor isolation where Objective-C or pre-concurrency code calls in, including synchronous isolated witnesses of `@preconcurrency` protocol conformances, so a delegate method or callback that arrives off the expected actor traps. A clean build does not show these entry points are safe; after raising the language mode or enabling the feature, exercise them.
- 6.4: a `Task { try ... }` whose result is neither stored nor explicitly ignored warns (`NoUseUnstructuredThrowingTask`), because the unstructured task initializers now use typed throws. A closure can no longer refer to a local variable declared below it from a `lazy` variable or a macro-rewritten initializer, nor to a local computed variable declared below it. With library evolution, module interfaces use module selectors by default, and the flags that worked around name collisions there can go. `defer` may contain `await`, and `withTaskCancellationShield` lets cleanup run to completion in a cancelled task.
- 6.3: `Span.bytes`, `MutableSpan.mutableBytes`, and the generic `OutputRawSpan.append()` methods are `@unsafe`, which shows under strict memory safety. `DecodingError` and `EncodingError` descriptions changed their text, so a test that compares them needs updating. `Module::name` picks a declaration from a named module.
- Actor methods interleave at every `await`, so state read before a suspension may differ after it. Restore invariants before suspending, re-check state on resuming, and let concurrent callers await one in-flight task rather than each repeating the work.
- Give every unstructured task an owner and cancellation path; `Task.detached` drops actor context and priority.
- A SwiftData or Core Data model change is a data migration: add a migration plan and test upgrades from shipped schemas.
- Keep unsafe pointers inside scoped closures and state ownership and nullability across C/Objective-C bridges.
- SwiftPM plugins, macros, and package build tools run code on the build machine.
- Swift Testing runs tests concurrently inside one process unless told otherwise; XCTest's default is sequential. Isolate shared statics, files, and `UserDefaults`; `.serialized` orders only the tests inside the suite it marks, not that suite against others. In suites mixing both frameworks, confirm with a deliberately failing probe that a failure under either fails the run.
