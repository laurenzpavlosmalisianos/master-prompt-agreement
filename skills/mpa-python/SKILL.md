---
name: mpa-python
description: "Checks for Python packaging, threads, archives, annotations, and untrusted input. Use when changing pyproject.toml or supported versions, building wheels, extracting tarfile/zipfile archives, inspecting annotations, writing free-threaded Python, or running in an untrusted directory."
---

# Python

- Type annotations, `TypedDict`, standard-library `@dataclass`, and unvalidated constructors (such as `model_construct`) do not validate untrusted input at run time.
- Archives: validate member paths, link targets, member counts, and total uncompressed sizes against the extraction root before extracting. Pass `filter="data"` to `tarfile` extraction where supported (3.12+ and backported 3.8.17+/3.9.17+/3.10.12+/3.11.4+; default from 3.14) alongside path and size checks, because filters do not stop decompression bombs and unpatched builds have had filter bypasses. `zipfile` has no `filter` parameter and `zipfile.Path` does not sanitize.
- `urljoin(base, untrusted)` can replace the host (`mpa-secure-coding` covers SSRF controls).
- Evaluating annotations or forward references from untrusted code—including `get_type_hints()` and `annotationlib` in 3.14+ (even `Format.STRING` executes `__annotate__`)—can execute arbitrary code; parse untrusted source statically (such as with `ast.parse`) instead of importing or introspecting live objects.
- When running Python inside a directory that others control, pass `-I` (or `-P`, 3.11+). Without it the interpreter imports modules planted next to the script or in the working directory.
- Do not rely on the global interpreter lock for thread safety; free-threaded builds run without it.
- For a library, test the built wheel and sdist installed into a clean environment; importing from the source tree hides missing files and packaging errors.
- Do not widen or drop supported Python versions as a side effect.
