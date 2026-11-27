---
name: mpa-security-audit
description: "Rules for a read-only security audit: approval for active testing, untrusted targets, and confirmed findings. Use when asked for a vulnerability audit, threat assessment, penetration test, or dedicated security review. For coding checks, use mpa-secure-coding; for PR review, use mpa-review."
---

# Security audit

For an active incident or a suspected compromise, use the `mpa-incident` skill first.

## Rules of engagement

- Report only. Propose fixes and tests; edit only when the request includes remediation.
- Testing that changes state, touches production or third-party systems, generates traffic or cost, or exploits a target needs explicit approval that names targets, exclusions, permitted techniques, accounts, and stop conditions.

## Where to look

- Check that monitoring and anomaly containment also cover privileged or service accounts and test runs.
- For a small diff touching shared auth, routing, configuration, or policy, trace callers and built artifacts.

## Quality of findings

- A finding is a demonstrated breach of a boundary: source-to-sink trace with file and line, preconditions, impact shown on a harmless test resource or proven statically, smallest fix, and severity.
- Do not probe live infrastructure to settle an open question blocked by an unknown runtime or deployment fact; state the blocker and a safe way to check it.
- Keep disproved candidates with their counter-evidence, so they are not hunted again.
- A missing extra safeguard behind a control that already stops the attack is a hardening note with no severity, not a finding.
- Cap severity at the demonstrated impact; weakening a control ranks below bypassing the same boundary. Reachability only from trusted configuration, tests, local tooling, an intended extension point, or permitted actions affecting only the actor is not exploitability. Prefer no finding to a speculative one.
- For a confirmed issue, hunt variants in neighbouring code and supported branches, recommend the narrowest fix that closes the class with a regression test, and verify any fix against current code before closing it.

## Report

- Findings, open questions, hardening notes, coverage and gaps, and remaining exposure.
- Redact secrets, personal data, and production identifiers before sharing.
