# Swift Coding Quality Practice Guide

Use this Practice Guide when a task touches Swift, SwiftUI, Apple-platform app architecture, package resources, app persistence, localization, concurrency, or Apple framework integration. For SwiftPM libraries, command-line tools, server-side Swift, Linux Swift, or Windows Swift without Apple-platform app behavior, use the Swift.org language, package-manager, runtime, and server guidance first, then apply only the architecture, API, concurrency, resource, and verification rules that fit the target. Do not load it for unrelated frontend or backend work.

Before making source-sensitive recommendations, use project `SOURCE_PACKS.md` and `SOURCE_UPDATE.md` when present, then check current official Swift, Apple platform, SDK, and framework sources for the active surface.

## Workflow

1. Frame the active Swift contract.

- read the project contract, `swift-tools-version` or package manifest when applicable, pinned Swift/Xcode/SDK versions and release channel, target platforms and minimum deployment versions, language mode, strict-concurrency level, default actor isolation, upcoming or experimental features, interop settings, package or app structure, and local coding patterns
- check current Apple and Swift official sources, including applicable version-matched first-party guidance exposed by the selected toolchain, before relying on unpinned Swift, SwiftUI, SDK, HIG, or framework behavior
- record SDK versions separately from minimum deployment versions; gate newer APIs with `@available` or `#available`, preserve required fallbacks, and verify affected flows on the oldest supported OS version
- distinguish stable platform rules from project choices such as private app scope, branding, data format, or supported OS range

2. Keep architecture platform-native and inspectable.

- follow the project's established UI stack. For Apple-platform UI, use SwiftUI where it satisfies required platform behavior, deployment targets, accessibility, performance, and testability. Interoperate with UIKit or AppKit where needed
- for packages that claim multiple operating systems or runtime targets, keep platform-specific frameworks and system dependencies in platform-specific targets or adapters; prefer target-level separation over scattered conditional code; compile unsupported stubs and test that they fail closed with clear diagnostics
- keep the `App` entry point small; put coordination in an app model and domain work in models or services
- keep Views focused on presentation and user intent; move parsing, persistence, PDF, OCR, notifications, scoring, and external process work into services
- for representative-scale `ForEach` content inside `List` or `Table`, use stable inexpensive identifiers and keep each data element's emitted row count constant where practical. Derive filtered or visible collections before the row builder instead of conditionally emitting zero or one row, and avoid `AnyView` on a hot row path unless it is required and measured. This is performance and view-identity guidance, not a blanket prohibition on conditional view content; preserve the intended semantics and accessibility behavior, and use before/after profiles on representative data before claiming an improvement
- use Apple frameworks first, such as Foundation, SwiftUI, Observation, PDFKit, Vision, UserNotifications, Charts, and AppKit bridges where they fit
- use `NSViewRepresentable` or other bridges only when SwiftUI does not provide the needed platform behavior

3. Model state, resources, and data flow explicitly.

- use Observation only where supported by the minimum deployment targets; otherwise retain the appropriate `ObservableObject` path
- store a view-owned `@Observable` reference in `@State`, pass observable references normally for observation or direct mutation, and introduce `@Bindable` only where the view needs binding projections such as `$model.name`
- keep UI-owned mutable reference models on `@MainActor`
- prefer value types for durable payloads and add `Codable`, `Hashable`, and `Sendable` only when semantically correct
- do not treat synthesized `Codable` as a durable schema; stabilize coding keys and representations, define versioning, defaults, and migrations where data outlives the build, and test older decoding fixtures
- for durable JSON state, choose date and numeric representations deliberately; when event ordering, windows, or markers matter, test subsecond round trips and avoid encodings that collapse distinct times
- when touching SwiftData or Core Data, treat model definitions, schema versions, migration plans, persistent history, CloudKit or app-group containers, uniqueness or default constraints, and delete rules as durable data contracts; add or verify migrations and upgrade fixtures from prior released schemas before changing shipped models
- classify files as user documents, app-support data, recreatable cache data, or temporary data and use the corresponding container and backup policy; coordinate access to shared or ubiquitous documents
- access package resources through the correct bundle, not guessed file paths
- keep user-facing strings, status text, errors, notifications, and package resources on one localization strategy

4. Design APIs and compiler boundaries deliberately.

- follow Swift API Design Guidelines: optimize names for call-site clarity, not abbreviation
- document public and reusable API surfaces enough that call-site behavior, complexity, and ownership are clear
- keep access control compatible with visible signatures; do not expose private parameter or return types through wider APIs
- make actor and `Sendable` boundaries explicit when values cross async tasks or service layers
- prefer structured concurrency. Use `async let` for a fixed set of child operations and task groups for a dynamic set. Give unstructured tasks an explicit owner, lifetime, cancellation path, and error-handling policy. Use `Task.detached` only when losing inherited context is intentional, and propagate or check cancellation around expensive or long-running work
- for C, Objective-C, C++, Core Foundation, or byte-level parser interop, make unsafe pointer and buffer lifetimes, nullability bridges, ownership transfers, copy boundaries, and error states explicit
- for binary or byte-level protocol parsers, parse every flagged field or reject the packet; add tests for each material flag combination, truncated optional fields, extra bytes, endian behavior, and normative bit masks from the governing specification
- for command-line tools, fail closed when a value-taking flag is missing, malformed, non-finite, or consumes another flag token; add negative tests for numeric and string flags
- include initialization and deinitialization, alignment, memory binding or rebinding, and scoped-pointer nonescape obligations; when supported, record whether Strict Memory Safety is enabled and review each explicit unsafe acknowledgement
- avoid shared non-sendable global state and formatter singletons unless isolated by design
- prefer explicit types around complex closures, optionals, and generics when inference becomes fragile

5. Verify platform behavior.

- for Xcode projects, record the project or workspace, shared scheme, action, configuration, destination and OS version, and test plan used; for standalone packages, record the SwiftPM configuration and target triple
- run the configured primary build and test gate when available: `swift build` and `swift test` or the project-specific SwiftPM commands for packages, and the project-recorded `xcodebuild build` and `xcodebuild test` commands for app schemes
- run configured formatting or linting tools such as SwiftFormat, SwiftLint, package plugins, or project-specific checks when they are part of the project contract
- respect the project's XCTest/Swift Testing mix. Use Swift Testing for new unit tests only where the project and toolchain support it, migrate incrementally, keep XCTest for UI automation, performance metrics, and Objective-C exception cases, and avoid mixing assertions across frameworks unless the project has an explicit interoperability policy
- do not claim app or platform coverage from a host-only package build
- treat Swift warnings and deprecations as material until classified
- verify `.strings` or string-catalog resources, JSON resources, asset references, file paths, and package resource inclusion when touched
- verify first-run, settings, navigation, import/export, file-write backup, and localization flows when user-visible behavior changes
- for Xcode build-performance work, capture clean and incremental baselines before edits, classify project-file changes through shared change-control, and re-run the same benchmarks after changes
- for Swift rewrites of parsers, protocols, interpreters, or legacy systems, use reference-output corpora, differential tests, fuzz or corpus replay where available, applicable Address, undefined-behavior, or Thread Sanitizer checks, and performance baselines only after compatibility and safety are checked
- for long-running local services, agent-tool servers, sessions, streams, or markers, define retention caps and round-trip ordering tests before claiming durable state is bounded and recoverable
- when UI changes, run applicable accessibility audits and inspect the changed flow for labels, actions, reading order, Dynamic Type, contrast, reduced motion, keyboard or focus behavior, and relevant assistive technology
- state clearly when the current environment cannot run Xcode, `swift build`, or the target app

## Output

Provide:

1. Swift version, SDK, platform, and source facts used
2. affected app, model, service, resource, and UI contracts
3. compiler, concurrency, interop, unsafe-code, parser, localization, persistence, and resource risks
4. build, test, lint, resource, and manual app checks run
5. unverified Apple-platform states and residual risk

## Guardrails

- Do not add third-party packages when an Apple framework is sufficient.
- Do not hide product configuration, paths, theme values, or operational settings in View code.
- Do not claim Apple-platform verification from source inspection alone when the toolchain or app can be run.
- Do not add `@unchecked Sendable` or `@preconcurrency` merely to silence diagnostics; document the synchronization or compatibility invariant, scope the annotation narrowly, and record when it should be reviewed or removed.
- Do not convert project-specific private app assumptions into public Swift doctrine.
- Do not treat a Swift rewrite as safe from language choice alone when it crosses unsafe, FFI, parser, filesystem, process, or privilege boundaries.
- Do not run SwiftPM plugins, package-provided tools, code generators, build scripts, macros with external tooling, or external processes from a new or untrusted dependency without the project's tool-execution policy, package or tool identity, requested permissions, and current authority for any write, network, destructive, or user-data access.
- Do not perform destructive file writes, PDF edits, migrations, or user-data changes without backup or current authority.
