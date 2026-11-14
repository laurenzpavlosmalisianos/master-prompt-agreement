---
name: mpa-python
description: Checks for Python packaging, threads, and untrusted input. Use when changing pyproject.toml or supported Python versions, building wheels, extracting archives, joining URLs, or running Python in a directory that others control.
---

# Python

- Use the interpreter, package manager, and commands the project already has; `uv`, `pip`, and `poetry` resolve and lock differently and are not interchangeable.
- Type annotations, dataclasses, and validation-model types do not validate untrusted input at run time unless a validator actually runs on it.
- Archives: check member names, sizes, and link targets before extracting. `tarfile` defaults differ between Python versions, and an extraction filter is an extra safeguard, not the control. `zipfile.Path` does not sanitize.
- `urljoin(base, untrusted)` can replace the host. A successful `urlparse` is not validation.
- Evaluating annotations or forward references that come from untrusted code can execute it.
- When running Python inside a directory that others control, pass `-I` (or `-P`, 3.11+). Without it the interpreter imports modules planted next to the script or in the working directory.
- Do not rely on the global interpreter lock for thread safety. Free-threaded builds run without it.
- For a library, test the built wheel and sdist installed into a clean environment. An import from the source tree hides missing files and packaging errors.
- Do not widen or drop supported Python versions as a side effect.
