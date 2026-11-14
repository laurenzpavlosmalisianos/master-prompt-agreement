---
name: mpa-rust
description: Checks for Cargo manifests, unsafe Rust, and operating-system boundaries. Use when changing rust-version, edition, or features, adding a build script or procedural macro, writing or reviewing unsafe or FFI code, or handling paths and attacker-controlled input.
---

# Rust

## Cargo

- Raising `rust-version`, changing the edition, or changing default features affects every consumer. Do it only when the task calls for it. Check newly used APIs against the minimum supported version.
- Features unify across the workspace graph. Read `cargo tree -e features`; one member turning a feature off does not disable it.
- Build scripts and procedural macros run code on the build machine. A new dependency that brings one is a dependency change with code execution.

## Unsafe code

- A safe API must not let any type-correct caller cause undefined behaviour. Tests and Miri support soundness but do not prove it.
- For each `unsafe` block, function, trait, or impl, write down what must hold (aliasing, provenance, initialization, alignment, layout, drop, unwind, thread safety) and who upholds it.
- Prefer `OnceLock`, `LazyLock` (1.80), or atomics to `static mut`. `env::set_var` and `remove_var` are unsafe while other threads run.
- For uninitialized, packed, or foreign-owned storage, project with raw pointers (`&raw const`, `&raw mut`, 1.82). Creating a reference asserts validity that the storage may not have.
- Run Miri when unsafe code changes, and report the paths it could not execute.
- Report a memory-safety bug as confirmed only with a safe caller that reaches it or an executable witness. Otherwise label it a hypothesis.
- Memory allocated by a foreign library is freed by that library's allocator.

## Operating system boundaries

- A path is a name, not an identity. Use `create_new(true)`, operate through the handle, and set permissions at creation; the `mpa-secure-coding` skill covers the check-then-reopen race.
- Keep paths, arguments, and environment values as `OsStr` or bytes. Make a lossy UTF-8 conversion explicit.
- `unwrap`, indexing, and unchecked arithmetic on attacker-controlled input are denial-of-service bugs.
- Do not enable Clippy `restriction` lints wholesale.
