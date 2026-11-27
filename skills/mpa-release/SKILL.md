---
name: mpa-release
description: "Checks before a release or deployment: what was verified against the exact candidate, what can be rolled back, and what remains open. Use when preparing a release, tagging a version, deploying, or publishing a package or image."
---

# Release

- Test failures or skips on parsers, deserializers, upload paths, or other untrusted-input code block a release. They are not noise.
- Keep technical readiness separate from approval to merge, deploy, tag, or publish.
