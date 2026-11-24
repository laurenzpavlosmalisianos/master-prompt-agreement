---
name: mpa-rust
description: "Checks for Cargo manifests, unsafe Rust, and operating-system boundaries. Use when changing rust-version, edition, or features, adding a build script or procedural macro, writing or reviewing unsafe or FFI code, or handling paths and attacker-controlled input."
---

# Rust

## Cargo

- Raising `rust-version`, changing the edition, or changing default features affects every consumer. Do it only when the task calls for it, and check new APIs against the minimum supported version.
- Features unify across the workspace graph. Read `cargo tree -e features`; one member disabling a feature does not turn it off.
- Build scripts and procedural macros run code on the build machine (`mpa-dependency-change`).

## Unsafe code

- A safe API must not let any type-correct caller cause undefined behaviour. Tests and Miri support soundness but do not prove it.
- For each `unsafe` block, function, trait, or impl, document what must hold (aliasing, provenance, initialization, alignment, layout, drop, unwind, thread safety) and who upholds it.
- Prefer `OnceLock`, `LazyLock` (1.80), or atomics to `static mut`. Never call `env::set_var` or `remove_var` while other threads (including parallel tests) run, and do not silence Rust 2024's `unsafe` requirement with an unjustified `unsafe` block.
- For uninitialized, packed, or foreign-owned storage, project with raw pointers (`&raw const`, `&raw mut`, 1.82); creating a reference asserts validity that the storage may not have.
- Run Miri when unsafe code changes, and report the paths it could not execute.
- Report a memory-safety bug as confirmed only with a safe caller that reaches it or an executable witness; otherwise label it a hypothesis.
- Free foreign-allocated memory with that library's allocator.

## Operating system boundaries

- A path is a name, not an identity. Use `create_new(true)`, operate through the handle, and set permissions at creation (`mpa-secure-coding`).
- Keep paths, arguments, and environment values as `OsStr` or bytes; make lossy UTF-8 conversions explicit.
- `unwrap`, unchecked indexing, and unchecked arithmetic on attacker-controlled input are denial-of-service bugs.
- Do not enable Clippy `restriction` lints wholesale.
