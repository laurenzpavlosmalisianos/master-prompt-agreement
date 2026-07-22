# Runtime Task: Plan

Use for downstream or project-local implementation planning after the approach
is chosen. A shared or reusable framework-product candidate, including a direct
request, routes to `framework_semantic_audit` and then, only if accepted,
`framework_improvement`; generic plan authority does not bypass that route.

Consult `STATEMENT_OF_WORK.md`, `TODO.md`, `DECISIONS.md`, or `PRECEDENTS.md` when authority, approval, current state, durable decisions, or recorded triggers can affect the task.

<!-- mpa-common-precondition -->
<!-- mpa-obligation: PLAN-no-unapproved-execution -->
<!-- mpa-obligation: PLAN-proof-per-slice -->
<!-- mpa-obligation: PLAN-hold-points -->

1. Classify ownership; continue here only for downstream or project-local work.
2. Lock the objective, constraints, and acceptance checks.
3. If the approach is not chosen or remains disputed, route to `ideate` or `arbitrate` unless the User requested a conditional plan with explicit hold points.
4. Separate approved decisions from open questions.
5. Name any durable intent artifact that must stay synchronized.
6. Break the work into dependency-ordered slices.
7. Attach exact verification to each slice.
8. Add hold points for approvals, unresolved architecture, or missing evidence.
9. Do not execute the plan unless the User explicitly asks for implementation.

Checks:

- the plan does not hide unresolved product decisions
- shared or reusable framework-product candidates are routed through semantic
  audit and framework improvement instead of this ordinary planning path
- unresolved approach disputes are routed or held explicitly
- behavior-changing work keeps the governing intent artifact aligned
- each slice has a concrete proof step
- scope and stop conditions are explicit
- plan-only requests stop at the plan unless execution is explicitly authorized
