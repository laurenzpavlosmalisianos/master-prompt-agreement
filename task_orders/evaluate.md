Task Order — Design Evaluation

Objective

Evaluate an external idea, pattern, or design against the project's architecture and philosophy. Extract what is useful, reject what does not belong, explain why.

Procedure

1. Read the SOW for the full set of constraints and design principles.
2. Analyze the shared idea on three axes:

Axis 1 — Hard Violations (automatic disqualifiers)

Check the idea against the SOW's non-negotiable constraints. Any single violation is grounds for rejection unless the core concept can be cleanly separated from the violation.

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

3. Deliver a verdict:

- Adopt — the idea fits with minimal or no modification. Describe what to implement and where it goes.
- Adapt — the core concept has value but needs reworking. Describe what to keep, what to discard, and how to implement.
- Reject — the idea conflicts with the project's philosophy. Explain the conflicts clearly so the reasoning is reusable for similar ideas.

For each axis, be specific. Name the exact rules that apply. Reference the specific files or components that would be affected.

Acceptance Criteria

- Every SOW constraint relevant to the idea has been checked.
- Verdict is one of: Adopt, Adapt, or Reject.
- Reasoning cites specific SOW rules or MSA clauses.

Notes

- Every recommendation justified against the project's standards, not general best practices.
- Push back on ideas that add complexity without earning it (MSA 2.2, Simplicity First).
- Prioritize consistency over novelty.
- Be direct. "This is clever but wrong for this project" is a valid assessment.
