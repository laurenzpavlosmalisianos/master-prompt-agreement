---
name: mpa-review
description: "Checks for reviewing a diff, branch, or subsystem for defects: how far a change reaches, whether its tests can fail, and how to confirm a finding. Use when asked to review, check, or give feedback on code, a diff, a commit series, or a pull request. For untrusted fork PRs, use mpa-external-contribution."
---

# Review

A review reports; it changes code only when the request includes fixing. For a change from outside the team, apply the `mpa-external-contribution` skill first and do not run the change.

- For a subsystem audit, define scope up front (excluding generated or vendored files unless relevant), read every file in scope including ones no checklist mentions (batching reads or splitting independent modules across scoped read-only helper agents when supported), and record what was read and what was left out.
- Keep what could not be confirmed in a separate list of open questions, each with the evidence that would settle it, and put that list in the report. Do not give those a severity.
- Coverage: what was inspected, which checks ran and their result, what was not covered.
