# Rust Coding Quality Practice Guide

Use this Practice Guide when a task touches Rust code, Cargo configuration, crate APIs, CLI behavior, unsafe code, platform targets, dependency features, or Rust release migration. Do not load it for unrelated language work.

Before making source-sensitive recommendations, use project `SOURCE_PACKS.md` and `SOURCE_UPDATE.md` when present, then check current official Rust, Cargo, Clippy, and platform sources for the active surface.

## Workflow

1. Frame the active Rust contract.

- read the project contract, `rust-toolchain` or `rust-toolchain.toml`, workspace and affected-member `Cargo.toml` files, edition, `rust-version`, `Cargo.lock`, workspace resolver and default members, feature flags, target triples, relevant `.cargo/config.toml`, build scripts that affect `cfg`, environment, linking, or targets, Cargo profiles, workspace or crate lint policy, crate-level lint attributes, formatter and Clippy configuration, and workspace layout
- check current official Rust sources before relying on unpinned language, standard-library, Cargo, Clippy, or platform-support facts
- distinguish stable Rust from beta, nightly, unstable flags, custom target work, and project-specific MSRV policy

2. Keep crate boundaries clear.

- model public APIs around ownership, borrowing, lifetimes, errors, and trait bounds at the call site
- make invalid states unrepresentable with enums, newtypes, validated constructors, and domain-specific wrapper types before relying on comments or sentinel values
- keep modules organized by responsibility rather than by temporary implementation history
- keep feature flags additive, documented, and covered by verification when they affect public behavior
- avoid exposing unstable implementation details, concrete dependency types, or avoidable allocation policy in public APIs
- prefer standard library and well-scoped crates before adding broad framework dependencies

3. Make error, concurrency, and unsafe boundaries explicit.

- return typed errors or contextual errors at recoverable boundaries; reserve `panic!` for invariant failure or tests
- avoid `unwrap` and `expect` outside tests, prototypes, or proven invariants with local explanation
- use `Send`, `Sync`, ownership transfer, and synchronization primitives deliberately when values cross threads or async tasks
- use interior mutability, `Arc<Mutex<_>>`, `Arc<RwLock<_>>`, atomics, and channels only after naming the ownership, aliasing, and blocking or ordering contract they are meant to express
- isolate `unsafe` into the smallest module, state the safety invariant, and test the safe API around it
- for every unsafe construct, including unsafe blocks, unsafe operations inside `unsafe fn`, unsafe functions, unsafe traits, unsafe impls, unsafe extern declarations, unsafe external statics, and unsafe attributes, record the proof obligation and who must uphold it
- include aliasing, provenance, lifetime, validity, layout, drop, unwind, symbol or linkage, and thread-safety assumptions when they apply
- judge unsafe wrappers by soundness: safe callers must not be able to cause undefined behavior through the public API, even when they call it in surprising but type-correct ways
- treat FFI, filesystem, process, network, parser, and serialization boundaries as trust boundaries when inputs are external
- when code projects into uninitialized, packed, intrusive, shared-ownership, FFI-owned, or custom-layout storage, avoid creating temporary references that would imply alignment, initialization, aliasing, or validity the storage does not yet have; use raw-pointer projection forms and document the invariant they preserve

4. Harden OS and compatibility boundaries.

- treat `Path` values and path strings as names, not stable filesystem identity. Map user choices to server-owned identifiers where possible. Otherwise use descriptor-relative or constrained-open APIs and authorize the opened handle
- do not validate a pathname and then reopen it through attacker-writable ancestors. Use `OpenOptions::create_new(true)` for atomic final-name create-if-absent and perform later operations through the returned handle
- set security-sensitive file and directory permissions at creation time with platform APIs such as `OpenOptionsExt::mode` or `DirBuilderExt::mode`; account for `umask` instead of relying on create-then-chmod
- when filesystem identity matters, compare metadata identity such as device/inode or the platform equivalent after opening handles. Canonicalization and device/inode comparisons are supporting checks, not substitutes for a race-resistant open
- preserve bytes at Unix boundaries: use `OsStr`/`OsString` or platform byte adapters for paths, arguments, and environment data, and use `&[u8]`, `Vec<u8>`, and `Write::write_all` for byte streams
- make lossy UTF-8 conversion explicit, justified, and covered by tests; do not let formatting macros silently define byte-stream behavior
- treat `panic!`, `unwrap`, `expect`, unchecked indexing, unchecked arithmetic, and unchecked casts as denial-of-service risks when input is attacker-controlled, file-derived, network-derived, or batch-critical
- do not discard meaningful `Result` values from I/O, filesystem, process, or batch operations; aggregate and report failures according to the command or API contract
- for reimplementations, CLI tools, protocol handlers, and compatibility layers, treat reference behavior, exit codes, option semantics, edge cases, and error handling as part of the safety contract
- design and verify identity, configuration, dynamic-loading, namespace or `chroot`, and privilege-drop ordering for the target operating system and workload. Resolve only data that becomes unavailable after the transition. Do not permit untrusted dynamic loading or configuration discovery while privileged

5. Use current Rust tools as evidence.

- run `cargo fmt` before completion when formatting is in scope
- run `cargo clippy` with the project-approved lint level; do not enable all `restriction` lints wholesale
- treat Cargo profiles, lint baselines, lint exceptions, and disallowed-method/type/macro rules as design evidence when they encode ABI, unwind, overflow, debug-assertion, linking, platform-wrapper, unsafe, FFI, or performance assumptions; do not silently weaken them
- run `cargo test` and targeted integration or doc tests for changed behavior
- state the package scope of each Cargo command; use `-p` for affected packages, `--workspace` for workspace-wide coverage, and record intentionally omitted members, targets, features, examples, benches, and doctests
- run feature, target, and no-default-feature checks when the change affects conditional compilation
- for test-suite audits, inventory before judging quality. Useful inventory commands include `cargo test -- --list`, relevant feature variants such as `cargo test --no-default-features -- --list`, and source scans for `#[test]`, `#[ignore]`, `should_panic`, `unwrap`, and `expect`
- classify Rust tests by contract and risk, not raw count: public API and documented behavior; private parser, sanitizer, deserializer, or security boundary; protocol, byte, wire-format, or fail-closed behavior; environment-gated live behavior; generated policy, config, or CLI output; compiler-derived or trivial implementation mechanics
- review duplicate short test names, ignored-test reasons, feature-gated counts, doctest coverage, integration-test target layout, and no-default-feature deltas before concluding that a suite is inflated
- prefer table-driven tests for large accept/reject matrices, generated-output inventories, CLI option variants, scanner or parser token lists, and policy or config output assertions. Keep separate named tests when the scenario has distinct security history, failure mode, regression value, or diagnostic value
- do not delete parser, sanitizer, browser, sandbox, protocol, byte/wire-format, fail-closed, or security-regression tests merely to reduce count; require a contract or risk-based reason
- for broad Rust test audits, keep a compact ledger: inventory method, duplicate and ignored-test review, subsystem lanes reviewed, claims accepted or rejected, edits made, deterministic commands run, and residual gaps
- run `cargo tree -e features` or an equivalent feature-resolution check when dependency features, default features, or workspace resolver behavior changes
- after source, dependency, feature, resolver, or lockfile changes, build and test affected packages on their declared `rust-version` where feasible; treat Rust-version-aware dependency resolution as an aid, not proof of MSRV compatibility
- run targeted Miri checks under a separately pinned supported nightly when changes touch unsafe code, raw pointers, layout, Rust-side FFI wrappers, aliasing, or concurrency; gate unsupported native/platform calls, use layout randomization or multiple seeds when relevant, and report unsupported paths and unexecuted inputs
- when build or verification output is cached in CI, apply the cache confidentiality and trust-boundary checks in [Build Pipeline Integrity](build_pipeline_integrity.md)
- when Rust checks depend on generated source, bindgen or codegen output, vendored path dependencies, cross-language artifacts, environment variables, or generated include directories, record and run the exact preflight or generator that makes the check meaningful before claiming format, lint, type, Miri, or test coverage
- for unsafe-code audits, classify an AI-identified memory-safety issue as reportable when it has either a conclusive code-level soundness proof that traces a reachable safe caller to a violated unsafe invariant, or an executable witness such as a focused Miri, sanitizer, or platform-specific reproducer where that path is supported. Otherwise report it only as an explicitly unverified hypothesis or proof gap with the missing invariant or reachability evidence. Runtime tools corroborate but do not replace a complete static proof, and unsupported FFI, syscall, or platform paths must not be described as cleared. Convert confirmed defects into regression tests before or alongside the fix when feasible
- route dependency additions, upgrades, advisories, or supply-chain changes through `practice_guides/dependency_risk.md` and project-approved Rust security tools rather than hardcoding one audit command
- treat external test runners, mutation testers, fuzzers, and coverage tools as developer tools or Verification Profile entries that require project approval. They do not imply new `[dependencies]` or `[dev-dependencies]`, and no-dependency projects must not gain them implicitly
- inspect the earliest unique compiler error first; repeated Rust diagnostics often stem from one cause

6. Handle release and edition changes conservatively.

- adopt new stable language features only when the project MSRV allows them
- check Rust release notes before using newly stabilized APIs or compiler behavior
- treat custom JSON target specs, `build-std`, and target-spec experiments as unstable even on nightly; require an explicitly pinned Cargo/rustc toolchain and validate custom target files against that compiler version
- keep edition migration separate from unrelated feature work unless explicitly approved
- run edition migration tools on a clean tree for each relevant package, feature set, and target configuration before changing manifest editions; review generated changes manually and rerun the verification matrix
- record compatibility notes when changing `rust-version`, edition, target support, or feature defaults

## Output

Provide:

1. Rust version, edition, MSRV, target, and official source facts used
2. affected crates, modules, features, APIs, compatibility contracts, and trust boundaries
3. error, concurrency, unsafe, dependency, and platform risks, including unsafe contract assumptions when relevant
4. `cargo fmt`, `cargo clippy`, `cargo test`, feature, target, dependency-risk, and Miri checks run when applicable
5. for test-suite audits, the test inventory, contract/risk classification, duplicate or ignored-test review, accepted deletions or consolidations, and residual gaps
6. unverified target or toolchain states and residual risk

## Guardrails

- Do not silently raise MSRV, edition, target requirements, or dependency features.
- Do not add `unsafe` without a documented safety invariant and explicit API boundary; expose a safe wrapper only when it enforces every required invariant.
- Do not use `unsafe`, interior mutability, or shared locks as a shortcut around an unstated ownership model.
- Do not rely on tests alone to justify unsafe soundness; inspect the API shape and invariants that safe callers can exercise.
- Do not make Clippy output the design authority; classify lints against the project contract.
- Do not hide panics, lossy conversions, or unchecked input assumptions behind helper APIs.
- Do not treat memory safety as proof of syscall ordering, filesystem identity, byte-preservation, or compatibility correctness.
- Do not treat nightly or beta behavior as stable project guidance.
- Do not treat test count as test quality. A small suite can miss critical contracts, and a large suite can be justified when it preserves compatibility, security, fail-closed behavior, or diagnostics.
