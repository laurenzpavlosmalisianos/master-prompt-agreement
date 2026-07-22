# Python Coding Quality Practice Guide

Use this Practice Guide when a task touches Python code, `pyproject.toml`, Python version policy, virtual environments, package metadata, dependency resolution, CLI entry points, type boundaries, tests, or Python release migration. Do not load it for framework-script invocation alone unless Python source or tooling behavior is affected.

Before making source-sensitive recommendations, use project `SOURCE_PACKS.md` and `SOURCE_UPDATE.md` when present, then check current official Python, Python Packaging, typing, test, lint, selected package-manager/toolchain, and project-framework sources for the active surface, including `uv` only when it is the selected or affected toolchain. Treat Python minor-version behavior, package-manager semantics, linter defaults, and release-service features as source-sensitive.

## Workflow

1. Frame the active Python contract.

- read the project contract, Python version policy, `.python-version`, `pyproject.toml`, lockfile, package layout, entry points, test configuration, type-checker configuration, formatter and linter configuration, environment variables, and supported operating systems
- check current official Python sources before relying on unpinned language, standard-library, typing, packaging, or release behavior
- distinguish application code, libraries, one-off scripts, notebooks, generated code, migrations, and framework repository scripts; do not apply one category's packaging or runtime assumptions to another
- use the project-recorded Python invocation first; do not substitute `uv run` for plain `python` unless the workflow already uses `uv`, the repository instructions select `uv`, or the script depends on project-managed dependencies
- for repository-maintenance scripts, use the runner documented by the repository's prerequisite or setup check instead of guessing; mark any command that may create or update environments, download Python, resolve dependencies, or install packages as state-changing
- keep direct `python3 -E -S -B` or `py -3 -E -S -B` as a fallback for stdlib-only scripts only when the repository prerequisite or setup check reports a supported interpreter and no errors

2. Keep packaging, environments, and entry points reproducible.

- prefer `pyproject.toml` as the project metadata and tool-configuration home when the project uses modern packaging; keep build backend, `requires-python`, dependencies, optional dependencies, and script entry points explicit
- keep lockfiles, dependency groups, optional dependencies, source indexes, and workspace membership aligned with the package manager actually used by the project
- do not treat dependency groups as published install interfaces; use dependency groups for local, development, or non-distributed workflows, and use `project.optional-dependencies` only for extras that downstream installers should consume
- do not mix `pip`, `uv`, `poetry`, `pdm`, conda, system Python, and ad hoc virtual environments unless the SOW records the boundary and commands
- avoid installing packages or running lifecycle-like tooling during review unless the task, project contract, and approval allow it
- use `uvx` or `uv tool run` only for approved ephemeral tools and record when a command may download or install packages
- do not introduce global interpreter, user-site, shell-profile, or host-specific path assumptions into project files

3. Design types and APIs deliberately.

- annotate public functions, public classes, callbacks, protocol boundaries, fixtures used across modules, and ambiguous return values; allow local inference where it keeps code clearer
- prefer `Path`, structured dataclasses, enums, protocols, typed dictionaries, literals, and narrow domain types over unstructured dictionaries and sentinel strings when the boundary is reused
- treat untrusted input as `object` at the typed boundary, then narrow with explicit runtime checks such as `isinstance`, `TypeIs`, or `TypeGuard`; do not treat type annotations as runtime validation
- for enums, tagged unions, and `match` statements that define external behavior, add exhaustiveness checks such as `typing.assert_never` or equivalent checker diagnostics
- for typed libraries, ship `py.typed` and keep distributed type information synchronized with the runtime package
- avoid `Any`, blanket `cast`, `# type: ignore`, dynamic attributes, monkeypatch-heavy code, and broad exception swallowing unless the invariant or test seam is explicit
- keep public package imports, `__all__`, CLI argument contracts, config-file schemas, JSON schemas, and generated stubs synchronized when one changes

4. Handle I/O, parsing, processes, and concurrency as boundaries.

- validate untrusted files, paths, URLs, archive entries, environment variables, CLI arguments, JSON, YAML, HTML, XML, CSV, regex captures, and subprocess arguments at the boundary
- do not assume standard-library path, archive, or URL helpers validate safety; inspect archive member names, sizes, symlinks, and extraction targets before extraction, do not rely on `tarfile` defaults across Python versions, do not trust `zipfile.Path` sanitization, do not use `urljoin(base, untrusted)`, and do not treat `urlsplit` or `urlparse` success as validation
- default denylist for untrusted input: no `pickle` or `shelve` loads, no `multiprocessing.Connection.recv()` across untrusted boundaries, no `tempfile.mktemp`, and no `random` for tokens or secrets
- use structured APIs for paths, URLs, subprocesses, serialization, SQL, HTTP, and temporary files
- when Python scripts enforce cross-cutting policy such as path-leak detection, URL safety, source classification, or release boundaries, route each policy family through one declared owner such as a helper module, schema, manifest, or registry with focused tests; do not scatter equivalent regexes, path prefixes, or deny-lists across scripts
- for validation scripts, check declared product surfaces, schemas, generated artifacts, and release invariants; do not enforce layout or content rules for scratch folders, source inboxes, local review artifacts, or other excluded workspace roots unless they have been explicitly promoted into the product surface
- for subprocesses, pass argv as a sequence, use fully qualified executable paths or `shutil.which`, prefer `sys.executable -m <module>` for Python tools, set `cwd`, `env`, `timeout`, and `check` deliberately, and treat `shell=True` as an exception requiring a documented reason
- when executing Python in untrusted or workspace-owned directories, prefer `python -I` where compatible; otherwise use `-P` or `PYTHONSAFEPATH` to avoid importing from unsafe implicit paths
- bound input size, decompressed size, recursion, regex complexity, concurrency, timeouts, retries, memory, file descriptors, and paid-service calls when external input can drive work
- keep async, threads, multiprocessing, signal handling, cancellation, and cleanup paths explicit; avoid hiding blocking work inside async functions
- do not rely on the GIL for correctness; protect shared mutable state explicitly and document thread-safety assumptions separately from CPython implementation details, especially for code intended to run on free-threaded builds
- for text files with a known format, specify the encoding explicitly instead of relying on process defaults
- use context managers for files, locks, network clients, temporary directories, transactions, and resources with cleanup obligations
- for C extensions, `ctypes`, `cffi`, native wheels, buffer protocols, memory views, or FFI wrappers, state ownership, lifetime, alignment, encoding, platform, and ABI assumptions before treating the boundary as safe

5. Verify with the actual project toolchain.

- run the project-recorded test command, such as `uv run pytest`, `uv run python -m unittest`, or the SOW's equivalent
- for packages and libraries, prefer a `src` layout and pytest `--import-mode=importlib` unless the project documents a different import contract; validate packaging behavior against installed artifacts, not only source-tree imports
- run the project-recorded type checker, such as BasedPyright, Pyright, mypy, pyrefly, or ty, with the configured strictness; do not claim strict typing from editor hints alone
- run the configured formatter and linter, such as Ruff or a project-approved alternative, without silently changing rule sets
- do not rely on tool defaults or working-directory inference for policy-critical checks; keep `requires-python`, Ruff `target-version`, and the active config path explicit when consistency matters, and treat invalid type-checker or linter configuration as a failed check
- run `uv lock`, `uv sync --locked`, dependency audit, or package-build checks only when dependency, packaging, or release behavior is in scope and approved
- for libraries, verify import behavior, package data, entry points, wheel and sdist builds, supported Python versions, and declared public API
- for packages and libraries, validate the built artifacts: build both sdist and wheel, install the built wheel into a clean environment, import the package from that environment, and smoke-test declared console entry points there
- for automated PyPI releases, prefer Trusted Publishing over stored API tokens; if publish automation is in scope, verify the repository-to-project trust binding and protect the workflow as a release credential
- state clearly when dependencies, network access, package installation, optional services, platform targets, or project tools cannot be run

## Output

Provide:

1. Python version, package manager, environment, and official source facts used
2. affected package, module, API, CLI, type, dependency, and runtime contracts
3. validation, I/O, subprocess, concurrency, dependency, packaging, and native-boundary risks
4. test, type-check, lint, format, lock, dependency, package-build, and runtime checks run
5. volatile Python minor-version, package-manager, linter, type-checker, release-service, and runtime assumptions
6. unverified interpreter, platform, dependency, or toolchain states and residual risk

## Guardrails

- Do not treat annotations, dataclasses, Pydantic models, or type-check success as proof that runtime input was validated.
- Do not add dependencies, install packages, or change package-manager state merely to satisfy a local convenience.
- Do not treat `uv` as a harmless wrapper around `python` or `pip`; project and script execution semantics can differ materially from plain interpreter invocation.
- Do not treat dependency groups, optional dependencies, and development dependencies as interchangeable.
- Do not hide type failures with `Any`, broad ignores, casts, or dynamic attribute access without a local invariant and follow-up check.
- Do not replace project commands with personal aliases, global tools, host paths, or editor-only diagnostics.
- Do not silently widen supported Python versions, drop supported versions, or adopt preview interpreter behavior.
- Do not rely on tests alone for parser, subprocess, filesystem, native, archive, or network security boundaries.
- Do not claim package release readiness from source-tree-only tests; verify the built and installed artifact when packaging is in scope.
