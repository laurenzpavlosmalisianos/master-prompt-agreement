---
name: mpa-release
description: "Checks before a release or deployment: what was verified against the exact candidate, what can be rolled back, and what remains open. Use when preparing a release, tagging a version, deploying, or publishing a package or image."
---

# Release

## Tie the evidence to one candidate

- Name the exact candidate: commit, tag, or artifact digest, plus the target environment. Test results and scans collected against a different commit or build do not count for this one.
- Say which checks ran against the candidate and which results are carried over from earlier.

## What a green run does not cover

- Passing tests do not cover rollout: migration order, configuration and secrets in the target environment, old and new versions running together, caches, and feature-flag defaults.
- A check that only verifies shape, counts, or the presence of a file does not verify the behaviour it is named after.
- Test failures or skips on parsers, deserializers, upload paths, or other untrusted-input code block a release. They are not noise.
- Treat as blocking until a person accepts them: unexpected lockfile or package-source changes, missing provenance where the project requires it, unresolved advisories on reachable code, unmet licence or attribution obligations, and undocumented compatibility breaks.
- Documentation, changelog, and runbooks that no longer match user-visible or operational behaviour are release gaps.

## Rollback

- Name the rollback or containment path and whether it was exercised. For each irreversible step in the sequence, name its stop condition. For data changes see the `mpa-migration` skill.
- State the entry criteria for the rollout, the signal that aborts it, and the action taken on abort.

## Report

- Keep two answers apart: whether the candidate is technically ready, and whether release is approved. A recommendation to release is not permission to merge, deploy, tag, or publish. Those stay under the project's approval rules.
- Contents: candidate identity, checks run and their results, checks not run, rollback path, open items with who accepts each.
