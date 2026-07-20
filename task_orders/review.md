Task Order — Adversarial Review

Objective

Find supported bugs, edge cases, weaknesses, and standards violations in the requested scope. Actively try to falsify both the work and the candidate findings, then report only findings supported by current project evidence.

Procedure

1. Read `AGENT_PROJECT.md` for active constraints, commands, and deliverables. Consult `STATEMENT_OF_WORK.md` for the full Code Review Checklist or when canonical project terms are unclear.
2. Start with the smallest Evidence Scope that can justify the task. Use this order: `patch`, `touched-files`, `commit-series`, `feature-slice`, `trust-boundary`, `repo-slice`.
3. Check whether the scope intersects a Critical Surface in the project contract. If it does, review changed lines and relevant unchanged support code line by line before relying on summaries or generated tests.
4. Before widening, identify any changed invariant or shared behavior in scope. Ask what unchanged callers, readers, jobs, or boundaries depend on the old behavior.
5. Read only the evidence required by the chosen scope. Widen the scope only when the defect path or changed invariant crosses file, module, or trust-boundary edges.
6. Treat tests written by the same agent or same change author as evidence to inspect, not independent proof. Verify that the tests can fail for the defect they claim to cover.
7. For each function, module, or component, ask:
   - What happens with empty input? Null? Undefined?
   - What happens with huge input?
   - What happens at boundaries?
   - Did they handle the error path? Verify it.
   - What assumptions were made, and which evidence supports them?
   - Does it match the active project constraints? (No JS on a zero-JS site. No external deps on a self-hosted project.)
   For code-quality weaknesses, use `practice_guides/change_impact_review.md` as the heuristic baseline for changed invariants, silent break modes, and maintainability smells. Project standards override generic smell probes; report smells as judgment-backed Weakness findings unless a documented standard or behavior defect supports a stronger classification.
8. If validator, linter, scanner, benchmark, Lighthouse, or audit output is part of the evidence, classify each material item before it drives an edit or finding:
   - Confirmed defect - supported by current project facts, code path, configured version, or applicable primary source.
   - Accepted project exception - allowed by the SOW, runtime project contract, or durable project decision.
   - Current-tooling false positive - tool output conflicts with current primary sources or inspected behavior.
   - Stale source, project, or tooling issue - the output depends on outdated assumptions, docs, rules, defaults, or tool data.
   - Environment or tool limitation - the check cannot observe the relevant runtime, browser, data, or configuration state.
   - Unresolved question - evidence is insufficient; report the next source or probe instead of treating it as a defect.
9. For high-risk, security-sensitive, release-blocking, or wide-scope reviews, try to refute material findings and approvals through distinct independent lenses such as exploitability, trust-boundary crossing, existing mitigations, concurrency, dependency or supply-chain risk, and changed-invariant impact. Do not count repeated agreement from the same context as independent review.
10. When multiple AI reviewers, subagents, browser-assisted reviewers, or external reviewer reports are used, follow `task_orders/orchestrate.md` for live fan-out and coordinator validation. This review supplies the distinct refutation questions, evidence scope, and coverage record; it does not restate the lane-launch, lifecycle, first-pass isolation, or post-blind procedure.
11. Keep a compact coverage manifest for every review: file or surface, evidence inspected, checks, findings, exclusions, and validation status.
12. Load `runtime/finding_schema.json` and classify each finding with its fields, enums, and conditional constraints. Accepted exceptions, false positives, and rejected claims are dispositions, not evidence statuses. An unresolved hypothesis cannot be reported as a Finding.
13. Category definitions:
   - Bug — code does not do what it claims. Provide reproduction steps.
   - Edge Case — code fails under specific input. Provide the input.
   - Weakness — code works but is fragile, unclear, or violates a standard. Explain why.
   - Standards Violation — code violates the MSA, project contract, canonical project terms, or applicable standards. Cite the clause or section.
   - Security — a supported defect or weakness affects confidentiality, integrity, availability, authentication, authorization, privacy, or a trust boundary. Trace the affected path, impact, and existing mitigation.
   - Performance — a measurable or path-proven defect affects latency, throughput, resource use, or scaling behavior. State the workload and comparison basis.
   - Documentation — governed documentation contradicts, omits, or misstates required or current behavior. Cite the governing source and practical consequence.
   - Process — a governed workflow, control, route, or verification step fails its declared result or authority boundary. Cite the step and observed failure.
14. Only supported issues enter the Findings list. A consequential but unresolved hypothesis belongs in an Open Probes section with the exact evidence needed to resolve it. Do not preserve unsupported suspicions as findings.
15. When the classification depends on living standards, browser behavior, laws, platform defaults, vendor guidance, or versioned APIs, verify through the project-approved acquisition method before acting.
16. Ordinary review findings belong in the review report or approved TODO candidates. Write to `FINDINGS.md` only when it is receipt-declared mutable state and the issue is a framework/process-effectiveness observation suitable for later `task_orders/insights.md`; preserve its exact generated-state origin marker. If that optional file is absent, keep the observation in the report unless a separately approved candidate-input refresh enables it. The shared/reusable framework-product and active framework-improvement branches in step 18 remain report-only and do not write their candidate findings into project state.
17. If state-file maintenance is explicitly in scope or approved, record recurring accepted exceptions or false positives in receipt-declared DECISIONS.md or PRECEDENTS.md, preserving the generated-state origin marker. Otherwise list them as decision or precedent candidates in the review report. Do not create an absent optional PRECEDENTS.md ad hoc; route its enablement through candidate-input refresh. Project records into the SOW or `AGENT_PROJECT.md` only when they are active verification policy and contract maintenance is in scope or approved.
18. Route remediation by ownership:
   - First, when this review is the post-verification exact-candidate pass invoked by an active `framework_improvement` workflow, keep it report-only. Return every accepted correction to that workflow as `revise`; do not edit the candidate from the review pass. This active-workflow route takes precedence over the general shared-framework route.
   - Otherwise, for a finding about a shared or reusable framework-product surface, keep this review report-only. Return a bounded finding handoff to `task_orders/framework_semantic_audit.md`; only an accepted semantic result may enter `task_orders/framework_improvement.md` for proportional evaluation and authorized implementation. Generic review-remediation authority does not bypass that route.
   - For ordinary downstream or project-local work, retain the normal rule: fix unambiguous findings only when remediation is explicitly in scope or approved; otherwise propose the fix or test without editing files.
19. Add ordinary downstream or project-local findings to TODO.md only when remediation or state-file maintenance is explicitly in scope; otherwise list TODO candidates in the review report. Do not add the report-only framework-product findings from step 18 to TODO.md.
20. Deliver findings as a structured list using the required report fields in `runtime/finding_schema.json`, including file and line number, smallest reproduction or discriminating probe, command and environment when relevant, expected versus actual result, proposed fix or test, and residual risk.

Acceptance Criteria

- Every file in scope has been reviewed adversarially.
- A coverage manifest records reviewed surfaces, evidence, checks, exclusions, and validation status.
- Critical surfaces in scope have been reviewed line by line where the evidence permits it.
- The chosen scope is the smallest one that can justify the findings.
- Changed invariants and unchanged consumers have been checked when relevant.
- Same-author tests were inspected for meaningful failure modes before being used as proof.
- Material tool output has been classified before it drives edits or findings.
- High-risk findings or approvals were challenged through distinct refutation lenses when the scope warranted it.
- Multi-agent or external AI review outputs were deduped, source-checked, and validated by the coordinator before final findings.
- All findings are classified and documented under `runtime/finding_schema.json`.
- Unsupported suspicions are either rejected or listed as Open Probes with the evidence required to resolve them.
- Shared or reusable framework-product findings remained report-only and followed semantic audit into framework improvement; an exact-candidate review invoked by framework improvement returned accepted corrections as `revise` without editing the candidate.
- Remediation or TODO edits were performed only when explicitly in scope or approved.

Notes

- Prefer falsification over suspicion: challenge correctness, then challenge the finding.
- Happy-path evidence is incomplete until relevant failure paths and boundaries are checked.
- If evidence is insufficient, report the missing evidence or probe instead of overstating a defect.
