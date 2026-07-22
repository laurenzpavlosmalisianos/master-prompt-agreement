# Runtime Task: Audit

Use for systematic project or subsystem audits.

Consult `STATEMENT_OF_WORK.md`, `TODO.md`, `DECISIONS.md`, or `PRECEDENTS.md` when authority, approval, current state, durable decisions, or recorded triggers can affect the task.

<!-- mpa-common-precondition -->
<!-- mpa-obligation: AUDIT-coverage-ledger -->
<!-- mpa-obligation: AUDIT-shared-runtime-verifier-ownership -->
<!-- mpa-obligation: AUDIT-schema-classification -->
<!-- mpa-obligation: AUDIT-remediation-gated -->
<!-- mpa-obligation: AUDIT-verification-gap-disclosed -->

1. Define the audit scope and checklist sources.
2. Read every relevant file in scope.
3. Apply the checklist as a floor, not a ceiling.
4. Classify material tool output before treating it as a finding.
5. For partitioned audits, keep a coordinator-owned coverage ledger with reviewer, evidence, findings, rejected/deferred claims, and validation status. Coordinator or named-verifier ownership applies to global builds, full tests, packaging, benchmarks, global or shared-state cleanup, operations that mutate shared runtime, lifecycle, cache, or index state, other non-isolated stateful operations, and work that materially contends for a bounded shared resource; ordinary isolated project-scoped commands, including cleanup confined to worker-owned outputs, are not serialized merely because they execute in the same runtime. A bounded handoff exception must define how access is serialized or isolated. Approved human-reviewer reports may be evidence, but coordinator validation still governs final findings.
6. Load `runtime/finding_schema.json`; use its fields, enums, and conditional constraints. Report supported findings and Open Probes by default; fix them only when remediation is explicitly in scope or approved. Before remediation, classify context and ownership in this order: an exact-candidate audit invoked by active `framework_improvement` returns accepted corrections to that workflow as `revise`; otherwise shared or reusable framework-product findings remain report-only and route to `framework_semantic_audit`; only ordinary downstream or project-local findings may use approved audit-remediation authority.
7. Run relevant verification commands only when authorized and feasible. Classify material failures, warnings, skipped checks, and limitations. Zero untriaged material outputs are allowed; zero failures is required only when remediation or release gates make it the acceptance condition.

Checks:

- every file in scope was reviewed
- validator, linter, scanner, benchmark, and audit output is triaged before use
- partitioned audit coverage is ledgered and coordinator-validated
- global verification, shared-state mutation or cleanup, non-isolated stateful work, and material shared-resource contention are coordinator- or named-verifier-owned; ordinary isolated project-scoped commands, including cleanup confined to worker-owned outputs, are not serialized merely because they share a runtime
- supported findings and Open Probes are reported; fixes and state-file edits happen only when remediation or state-file maintenance is in scope
- framework-product findings and active framework-improvement audits remain report-only and follow their owning routes
- authorized relevant checks ran, or the gap and remaining risk were disclosed
- material failures, warnings, skipped checks, and limitations were triaged
- accepted exceptions and rejected claims are concise and justified
