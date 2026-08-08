# Runtime Task: Review

Use for adversarial code review.

Consult `STATEMENT_OF_WORK.md`, `TODO.md`, `DECISIONS.md`, or `PRECEDENTS.md` when authority, approval, current state, durable decisions, or recorded triggers can affect the task.

<!-- mpa-common-precondition -->
<!-- mpa-obligation: REVIEW-evidence-scope -->
<!-- mpa-obligation: REVIEW-dependent-aggregate-binding -->
<!-- mpa-obligation: REVIEW-dependent-union-review -->
<!-- mpa-obligation: REVIEW-schema-and-open-probes -->
<!-- mpa-obligation: REVIEW-remediation-gated -->
<!-- mpa-obligation: REVIEW-multi-agent-validated -->

1. Choose the smallest justified Evidence Scope.
   For a dependent change set, bind the immutable base identity, immutable member identities, declared member order and dependency relationships, final aggregate revision or snapshot, and complete base-to-candidate diff or an unambiguous digest of that evidence; rebind after any change to a bound identity, member order, dependency relationship, or aggregate. Review the aggregate and project-required intermediate states; component approvals do not approve the union.
2. Map changed invariants and direct consumers before widening.
3. Read the evidence in that scope before widening.
4. Keep a compact coverage manifest: reviewed surfaces, evidence, checks, exclusions, findings, open probes, and validation status.
5. Hunt for bugs, edge cases, standards violations, and fragile assumptions.
6. Classify material tool output before treating it as a finding.
7. If multiple AI reviewers or external AI reports are used, coordinator must dedupe, source-check, reload evidence, preserve dissent, and validate claims before final findings.
8. Report findings only unless remediation is explicitly in scope or approved; TODO/state edits also require scope or approval. Before remediation, classify context and ownership in this order: an exact-candidate review invoked by active `framework_improvement` returns accepted corrections to that workflow as `revise`; otherwise shared or reusable framework-product findings remain report-only and route to `framework_semantic_audit`; only ordinary downstream or project-local findings may use approved review-remediation authority.
9. Prefer concrete findings over speculative noise.
10. Load `runtime/finding_schema.json`; use its fields, enums, and conditional constraints.
11. Put consequential unresolved hypotheses in Open Probes, not Findings.
12. Deliver findings first with file and line references.

Checks:

- findings are discrete and evidenced
- validator, linter, scanner, benchmark, and audit output is triaged before use
- severity matches exploit path or failure path
- unsupported suspicions are rejected or listed as Open Probes with required evidence
- remediation and state edits stay inside approved scope
- framework-product findings and active framework-improvement reviews remain report-only and follow their owning routes
- Evidence Scope is the smallest sufficient slice
- dependent change-set review is rebound to the current aggregate and covers required intermediate states; component approvals are not union approval
- coverage manifest records reviewed surfaces, evidence, checks, exclusions, findings, and validation status
- unchanged consumers were checked when shared behavior changed
- multi-agent outputs were coordinator-validated before adoption
