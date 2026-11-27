---
name: mpa-python
description: "Python release changes through 3.15 and checks that are easy to miss. Use for any work on Python code or packaging: pyproject.toml, supported versions, archive extraction, untrusted input, or a Python version upgrade."
---

# Python

Current to Python 3.15.2, checked 2026-11-27. For a newer Python release, read what changed after 3.15.2 in the release notes (https://docs.python.org/3/whatsnew/) before relying on this file. The entries are the changes that are easy to miss, not the full release notes.

- Archives: validate member paths, link targets, member counts, and total uncompressed sizes against the extraction root before extracting. Pass `filter="data"` to `tarfile` extraction where supported (test `hasattr(tarfile, "data_filter")`, not the version number; default from 3.14) alongside path and size checks, because filters do not stop decompression bombs and unpatched builds have had filter bypasses. `zipfile` has no `filter` parameter and `zipfile.Path` does not sanitize.
- `urljoin(base, untrusted)` can replace the host.
- Do not rely on the global interpreter lock for thread safety; free-threaded builds run without it.
- 3.15 reads and writes text as UTF-8 when no `encoding` is given, whatever the locale (PEP 686). Pass `encoding` in code that runs on several versions; `encoding="locale"` keeps the old behaviour for one call, and `PYTHONUTF8=0` for a process. `base64.urlsafe_b64decode()` accepts unpadded input unless `padded=True` is passed.
- Security releases of 2026-10-25: 3.15.2, 3.14.10, and 3.13.18. The `tar` extraction filter now rejects a link member that resolves to the destination directory itself (CVE-2026-114583). 3.15.2 also fixes a deadlock in 3.15.0 and 3.15.1 when threads import `package.submodule` for the first time at once.
