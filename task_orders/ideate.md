Task Order — Structured Ideation

Objective

Generate and evaluate solution approaches for a problem using epistemic rigor. Produce multiple competing hypotheses, check for reasoning biases, and deliver a ranked recommendation with explicit confidence levels.

Procedure

0. Load Project Boundary

Read `AGENT_PROJECT.md` for active constraints, approval boundaries, and project facts. Consult `STATEMENT_OF_WORK.md`, `TODO.md`, `DECISIONS.md`, or `PRECEDENTS.md` when authority, current state, durable decisions, or recorded triggers can affect the recommendation.

1. Problem Decomposition

State clearly:
- What is the problem?
- What constraints apply? (SOW, technical, resource, time.)
- What does a good solution look like? Define criteria for evaluating approaches.

2. Hypothesis Generation

Generate two or three materially distinct viable approaches by default. Use one approach when evidence shows only one viable option; use more only when the problem materially benefits from more breadth. For each approach, describe the mechanism and its key trade-offs.

Do not evaluate during generation. Separate divergent and convergent thinking. The goal is breadth before depth.

3. Evidence Gathering

<!-- mpa-full-order-obligation: IDEATE-escalate-source-or-safety -->

For each approach:
- What evidence supports it? (Prior art, documentation, empirical data, known patterns.)
- What evidence contradicts it? (Known failure modes, incompatibilities, resource costs.)
- What is unknown? (Untested assumptions, missing data.)

Prefer primary sources over secondary. Flag evidence gaps explicitly.

4. Bias Check

Before ranking, verify:
- Anchoring — Am I favoring the first idea generated?
- Confirmation bias — Am I selectively gathering evidence for a preferred approach?
- Availability bias — Am I overweighting recent or memorable examples?
- Sunk cost — Am I favoring an approach because of prior investment in similar solutions?

Report disconfirming evidence and any bias that changed the ranking. Omit ceremonial "no bias detected" narration when no bias materially affected the ranking.

5. Confidence Assessment

For each approach, state a confidence level (high, medium, low) with explicit reasoning:
- High — strong supporting evidence, no significant unknowns, fits constraints well.
- Medium — reasonable evidence but notable unknowns or trade-offs.
- Low — speculative, limited evidence, or significant risks.

6. Synthesis

If one approach clearly dominates: recommend it with justification against the evaluation criteria.

If no clear winner: present ranked options with trade-off analysis. State what additional information would resolve the tie.

If strongest elements span multiple approaches: combine them into a hybrid recommendation. Explain which elements come from which approach and why.

Acceptance Criteria

- Two or three materially distinct viable approaches considered by default, or the single viable approach is justified.
- Evidence cited for and against each approach.
- Bias check performed when it affects ranking, with material findings reported.
- Confidence levels stated with justification.
- Recommendation justified against the evaluation criteria defined in step 1.

Notes

- This task order is for open-ended problem solving. For evaluating an existing idea or external proposal, use task_orders/evaluate.md instead.
- After an approach is chosen, classify its ownership. Use
  `task_orders/plan.md` or `practice_guides/implementation_planning.md` only for
  separately authorized downstream or project-local execution. Route a shared
  or reusable framework-product candidate to
  `task_orders/framework_semantic_audit.md`; a chosen direction does not bypass
  semantic ownership review or authorize implementation.
- When the problem is well-constrained and only one viable approach exists, say so. Do not force three alternatives when they do not exist.
- The value is in the reasoning process, not the format. Adapt the structure to the problem's complexity.
