Task Order — Audit

Objective

Verify that the requested project, subsystem, or evidence scope meets all active and canonical project requirements through systematic review of every relevant source file in scope.

This Task Order owns the broad audit workflow and reporting shape. For
security-specific standards, trust-boundary checks, and vulnerability triage
criteria, load `practice_guides/security_audit.md`.

Procedure

1. Read `AGENT_PROJECT.md` for project context. Read `TODO.md` when it exists or active handoff state or project policy requires it. Consult `STATEMENT_OF_WORK.md` for the full Code Review Checklist, acceptance terms, or other canonical SOW terms. Read `DECISIONS.md` for durable exceptions or directives when it exists. Read `PRECEDENTS.md` when the audit scope matches a recorded trigger.
2. Read every active policy or verification file referenced by the SOW or `AGENT_PROJECT.md`. If Annex D (`SECURITY.md`) exists, read it. If `SECURITY_VERIFICATION.md` exists and is active for the audited scope, read it. Use their checklists as additional audit criteria alongside the project contract and the SOW Code Review Checklist.
3. Read every relevant source file within the audit scope. Do not limit yourself to what the checklists mention.
4. Use the project contract plus the SOW Code Review Checklist as minimum coverage. Apply independent judgment: if you find a problem no checklist addresses, report it.
5. If validator, linter, scanner, benchmark, Lighthouse, or audit output is part of the evidence, classify each material item before it drives an edit or finding:
   - Confirmed defect - supported by current project facts, code path, configured version, or applicable primary source.
   - Accepted project exception - allowed by the SOW, runtime project contract, or durable project decision.
   - Current-tooling false positive - tool output conflicts with current primary sources or inspected behavior.
   - Stale source, project, or tooling issue - the output depends on outdated assumptions, docs, rules, defaults, or tool data.
   - Environment or tool limitation - the check cannot observe the relevant runtime, browser, data, or configuration state.
   - Unresolved question - evidence is insufficient; report the next source or probe instead of treating it as a defect.
6. Keep a compact coverage manifest for every audit. Map each in-scope file, source, or surface to the reviewer, evidence inspected, checks, findings, exclusions, rejected or deferred claims, and validation status. When live reviewers or scoped workers partition the audit, use `task_orders/orchestrate.md` for lane selection, launch envelopes, handoffs, lifecycle, coordinator validation, and ownership of global verification or shared-state work while this Audit Task Order remains the owner of coverage and finding disposition. Isolated cleanup confined to worker-owned outputs remains worker-local under that procedure. Human-reviewer reports are evidence for coordinator validation, not a bypass around project approval, communication, or confidentiality boundaries.
7. When the classification depends on living standards, browser behavior, laws, platform defaults, vendor guidance, or versioned APIs, verify through the project-approved acquisition method before acting.
8. If state-file maintenance is explicitly in scope or approved, record recurring accepted exceptions or false positives in receipt-declared DECISIONS.md or PRECEDENTS.md, preserving the generated-state origin marker. Otherwise list them as decision or precedent candidates in the audit report. Do not create an absent optional PRECEDENTS.md ad hoc; route its enablement through candidate-input refresh. Project records into the SOW or `AGENT_PROJECT.md` only when they are active verification policy and contract maintenance is in scope or approved.
9. Load `runtime/finding_schema.json` and classify each finding with its fields, enums, and conditional constraints. Accepted exceptions, false positives, and rejected claims are dispositions, not evidence statuses. Only supported issues enter the Findings list. A consequential but unresolved hypothesis belongs in an Open Probes section with the exact evidence needed to resolve it.
10. Keep the findings section limited to supported Findings and Open Probes, then route remediation by ownership:
    - First, when this audit is the risk-matched post-verification exact-candidate pass invoked by an active `framework_improvement` workflow, keep it report-only. Return every accepted correction to that workflow as `revise`; do not edit the candidate from the audit pass. This active-workflow route takes precedence over the general shared-framework route.
    - Otherwise, for a finding about a shared or reusable framework-product surface, keep this audit report-only. Return a bounded finding handoff to `task_orders/framework_semantic_audit.md`; only an accepted semantic result may enter `task_orders/framework_improvement.md` for proportional evaluation and authorized implementation. Generic audit-remediation authority does not bypass that route.
    - For ordinary downstream or project-local work, fix unambiguous findings only when remediation is explicitly in scope or approved; otherwise propose the fix or test without editing files.
11. Add ordinary downstream or project-local items to TODO.md only when remediation or state-file maintenance is explicitly in scope; otherwise list TODO candidates in the audit report. Do not add the report-only framework-product findings from step 10 to TODO.md or other project state.
12. Run every verification command or acceptance check applicable to the audited scope when authorized and feasible. If a project contract command is missing or ambiguous, consult the SOW fallback. Treat an intentional absence in a minimal, documentation-only, research, or non-code project as a reported verification limitation, not automatic drift. Classify every material failure, warning, and tool limitation as a Finding, Open Probe, accepted exception, false positive, stale source/tooling issue, or verification limitation. Require zero untriaged material outputs. Require zero failures only when the audit also includes approved remediation or an explicit release gate.
13. Deliver a compact audit summary after the findings section: scope and exclusions, coverage manifest location or table, objective checks by state (`pass | fail | not run | accepted exception`), separate manual-acceptance results where applicable, remediation performed only when in scope, TODO candidates requiring User decision, accepted exceptions or rejected claims with one-line rationale each, and residual risk.

Acceptance Criteria

- Every file in scope has been reviewed.
- Material tool output has been classified before it drives edits or findings.
- Every audit includes a coverage manifest with validation status.
- Blocking gate effects are reported with rationale, and fixed or logged in TODO.md only when remediation or state-file maintenance is in scope.
- Shared or reusable framework-product findings remained report-only and followed semantic audit into framework improvement; an exact-candidate audit invoked by framework improvement returned accepted corrections as `revise` without editing the candidate.
- Applicable verification commands or acceptance checks were run when authorized and feasible. Failures, warnings, and limitations are classified and reported. Zero untriaged material outputs remain; zero failing checks are required only when the audit includes approved remediation or an explicit release gate.
- Report delivered.

Notes

- Audit with a falsification mindset: challenge the implementation, challenge the evidence, and challenge candidate findings before reporting them.
- State residual risk when the available evidence cannot support stronger assurance.
