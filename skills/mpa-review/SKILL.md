---
name: mpa-review
description: "Checks for reviewing a diff, branch, or subsystem for defects: how far a change reaches, whether its tests can fail, and how to confirm a finding. Use when asked to review, check, or give feedback on code, a diff, a commit series, or a pull request. For untrusted fork PRs, use mpa-external-contribution."
---

# Review

A review reports; it changes code only when the request includes fixing. For a change from outside the team, apply the `mpa-external-contribution` skill first and do not run the change.

- Widen from the diff only as far as a changed invariant travels (signatures and return values, permissions, data shape and nullability, defaults, ordering, caching, error handling), including consumers a reference search misses: string-keyed registries, dependency-injection bindings, configuration defaults, serialized and wire formats, build globs. Follow each path until a type, test, or assertion would catch a break; report it as unverified if nothing would.
- Review a series of dependent commits as one combined result against the base.
- For each test that matters, check that it would fail if the behaviour broke. An expected value computed through the code under test, or an assertion that a mock was called, proves only the wiring. Look for deleted or softened assertions, newly skipped tests, loosened lint or policy rules, and missing negative cases on deny and error paths. A failing or skipped test on a parser, deserializer, upload path, or other untrusted-input code blocks a release; it is not noise.
- Before reporting a finding, try to refute it by reading the real callers, types, configuration defaults, and reachability. Agreement from a second pass in the same context is not independent confirmation.
- For a subsystem audit, define scope up front (excluding generated or vendored files unless relevant), read every file in scope including ones no checklist mentions (batching reads or splitting independent modules across scoped read-only helper agents when supported), and record what was read and what was left out.
- Keep what could not be confirmed in a separate list of open questions, each with the evidence that would settle it, and put that list in the report. Do not give those a severity.
- Coverage: what was inspected, which checks ran and their result, what was not covered.
