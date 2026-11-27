---
name: mpa-release
description: "Checks before a release or deployment: which test failures block it and keeping readiness apart from approval. Use when preparing a release, tagging a version, deploying, or publishing a package or image."
---

# Release

- Test failures or skips on parsers, deserializers, upload paths, or other untrusted-input code block a release. They are not noise.
- Keep technical readiness separate from approval to merge, deploy, tag, or publish.
