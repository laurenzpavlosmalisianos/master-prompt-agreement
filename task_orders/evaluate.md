Task Order — Design Evaluation

<!-- mpa-workflow-contract: {"outcome_enum":["Adopt","Adapt","Reject","Needs evidence"]} -->

Objective

Evaluate an external idea, pattern, or design against the project's architecture, constraints, and measured behavior. Extract what is useful, reject what does not belong, explain why.

Procedure

1. Read `AGENT_PROJECT.md` for active constraints, stack, and measured project behavior. Consult `STATEMENT_OF_WORK.md` for canonical non-negotiables or project terms that are not fully captured in the runtime contract.
2. Treat external claims as hypotheses until checked. Create a compact claim ledger for material claims about performance, security, compatibility, maintenance, licensing, or user value: claim, source or provenance, project evidence or measurement, and status `validated | contradicted | unresolved`.
3. Analyze the shared idea on three axes:

Axis 1 — Hard Violations (automatic disqualifiers)

Check the idea against the project's non-negotiable constraints. Any single violation is grounds for rejection unless the core concept can be cleanly separated from the violation.

Axis 2 — Architectural Fit

Does the idea align with or conflict with existing design decisions?

- Domain model — does it respect the existing data structures and abstractions?
- Code architecture — does it fit the existing structure? Can it use existing patterns?
- Performance — does it add weight (extra dependencies, complex operations)?
- Consistency — does it create patterns that diverge from the rest of the project?

Axis 3 — Abstractable Value

Even when an idea is rejected as a whole, evaluate whether any individual concept can be extracted and adapted.

- Is there a technique worth adopting?
- Is there a structural idea that improves organization?
- If nothing is abstractable, say so explicitly. Do not force value extraction.

4. Deliver an evaluation response:

- Adopt — the idea fits with minimal or no modification. Describe what to implement and where it goes.
- Adapt — the core concept has value but needs reworking. Describe what to keep, what to discard, and how to implement.
- Reject — the idea conflicts with recorded project constraints, architecture, standards, or measured behavior. Explain the conflicts clearly so the reasoning is reusable for similar ideas.
- Needs evidence — a material claim remains unresolved and would change the decision.

For each axis, be specific. Name the exact rules that apply. Reference the specific files or components that would be affected.

This task order is read-only. Adopt or Adapt describes a candidate; it does not
authorize implementation, file edits, dependency changes, external responses,
commits, or state-file updates. Route an ordinary downstream or project-local
candidate to planning only after separate authorization. Route any candidate
that would change a shared or reusable framework product surface to
`task_orders/framework_semantic_audit.md`; only an accepted result may enter
`task_orders/framework_improvement.md`. Needs evidence stops for the missing
evidence.

Acceptance Criteria

- Every relevant project constraint has been checked.
- Evaluation Response is one of: Adopt, Adapt, Reject, or Needs evidence.
- Reasoning cites specific runtime project contract sections, SOW sections, MSA sections, or measured project behavior.
- Adopt or Adapt was routed by ownership: downstream or project-local work to
  separately authorized planning, and shared or reusable framework-product work
  to report-only framework semantic audit. Nothing was implemented inside the
  evaluation.

Notes

- Every recommendation justified against the project's standards, not general best practices.
- Push back on ideas that add complexity without earning it.
- Prioritize consistency over novelty.
- Be direct. "This is clever but wrong for this project" is a valid assessment.
