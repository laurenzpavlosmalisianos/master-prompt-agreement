---
name: mpa-rust
description: "Rust and Cargo release changes through Rust 1.100 and checks that are easy to miss. Use for any work on Rust code or Cargo manifests: dependencies and features, editions, unsafe or FFI code, tests that touch the environment, or a toolchain upgrade."
---

# Rust

Current to Rust 1.100.1 and Cargo 1.100, checked 2026-11-27. The entries are the changes that are easy to miss, not the full release notes: for a change they do not mention, and for anything newer than those versions, read the release notes (https://doc.rust-lang.org/stable/releases.html, https://doc.rust-lang.org/cargo/CHANGELOG.html) before relying on this file.

## Cargo

- Features unify across the workspace graph. Read `cargo tree -e features`; one member disabling a feature does not turn it off. From Rust 1.99, an edition 2024 or later member's `default-features = false` on a `workspace = true` dependency overrides the workspace entry for that member only; unification still enables the defaults if another member requests them. On earlier editions, or before 1.99, the member's setting leaves the defaults on unless the workspace entry also sets `default-features = false` (Cargo warns; edition 2024 before 1.99 errors).
- Do not locate intermediate build artifacts by their path under the build directory: the layout is not a stable interface and changed in Cargo 1.100. Read artifact paths from Cargo's JSON messages.
- From Cargo 1.100, `cargo install` builds with the `Cargo.lock` published in the package, and `--locked` no longer changes which versions it picks. `registry.global-min-publish-age` or `registries.<name>.min-publish-age` (for example `"7 days"`) makes the resolver skip versions published more recently, unless `Cargo.lock` already holds them.
- From Cargo 1.99, incremental compilation is off by default when the `CI` environment variable is set.

## Language

- 1.100 stabilizes the never type: `Infallible` is an alias of `!`, and the fallback for a diverging expression is `!` on every edition, which can change what is inferred. Closures capture variables used in `if let` more precisely, which can bring new errors, and `box` patterns no longer parse. In 1.100.0 some types are not seen as implementing `Iterator`; 1.100.1 fixes it.
- 1.99.0 miscompiles FFI functions that return `bool` on x86_64; 1.99.1 fixes it.

## Unsafe code

- Prefer `OnceLock`, `LazyLock` (1.80), or atomics to `static mut`. Never call `env::set_var` or `remove_var` while other threads (including parallel tests) run, and do not silence Rust 2024's `unsafe` requirement with an unjustified `unsafe` block.
- Report a memory-safety bug as confirmed only with a safe caller that reaches it or an executable witness; otherwise label it a hypothesis.

## Operating system boundaries

- `unwrap`, unchecked indexing, and unchecked arithmetic on attacker-controlled input are denial-of-service bugs.
