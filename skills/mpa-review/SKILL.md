---
name: mpa-review
description: "Checks for reviewing a diff, branch, or subsystem for defects: how far a change reaches, whether its tests can fail, and how to confirm a finding. Use when asked to review, check, or give feedback on code, a diff, a commit series, or a pull request."
---

# Review

A review reports; it changes code only when the request includes fixing. For a change from outside the team, apply the `mpa-external-contribution` skill first and do not run the change.

## How far to look

- Start at the diff and widen only as far as a changed invariant travels: return values and signatures, permission semantics, data shape and nullability, defaults and flags, ordering, caching, retries, error handling. The size of a diff says little about its reach.
- Search for consumers that a reference search misses: reflection, string-keyed registries, dependency-injection bindings, configuration and environment defaults, serialized, wire, database, and queue formats, build and packaging globs.
- Follow each affected path until something would catch a break: a type or schema rejection, a failing test, a runtime assertion. If nothing would, report that path as unverified.
- For a series of dependent commits, review the combined result against the base. Each commit being acceptable does not make the sum acceptable.
- Look for breaks that stay silent: stale caches, two copies of one policy check drifting apart, a validator reading the wrong source of truth, partial rollout with old and new versions running together.
- When auditing a subsystem, read every file in scope, including the ones no checklist mentions, and keep a list of what was read and what was left out.

## Tests as evidence

- Tests that arrive with the change are evidence to inspect. For each one that matters, check that it would fail if the behaviour broke. An expected value recomputed through the code under test, or an assertion that a mock was called, proves only the wiring.
- New tests passing says nothing about old guarantees. Check that deny, validation, and error paths have negative cases.
- A green run, a coverage figure, or a test count does not show that the changed path ran. Check which tests were selected, skipped, or filtered.
- A flaky test that passes on retry has not passed. Treat it as an open defect until its source is known.
- When the security or integration behaviour of a real component is the claim, a self-written mock of that component is an assumption. Label it as one.

## Findings

- Try to refute each candidate before reporting it: read the real callers, types, configuration defaults, and reachability. A second pass in the same context that agrees with the first is not independent confirmation.
- Classify linter, scanner, and validator output before it becomes a finding: real defect, accepted project exception, false positive, stale data, or tool limit.
- Keep what could not be confirmed in a separate list of open questions, each with the evidence that would settle it. Do not give those a severity.
- Report maintainability concerns only when they connect to the changed behaviour and a concrete failure.
- For a change that crosses a trust boundary, alters authentication or permissions, touches signing or cryptography, widens outbound access, or changes schema or state irreversibly, recommend review by a person. If the review ran in the session that wrote such a change, say so.

## Report

- Findings first: file and line, the smallest reproduction, expected and actual behaviour, the proposed fix or test.
- Open questions.
- Coverage: what was inspected, which checks ran and their result, what was not covered.
