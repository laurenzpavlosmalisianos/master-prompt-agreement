# Implementation Planning Practice Guide

Use this Practice Guide when the approach is chosen but the work still needs an executable plan. It turns one approved approach into ordered, verifiable work slices.

## Output Shape

Produce a compact implementation plan with:

1. Objective and accepted decisions
2. Constraints, dependencies, and assumptions
3. Critical surfaces, security/privacy/source-trust boundaries, and review burden
4. Intent artifacts to keep synchronized, if any
5. Ordered work slices
6. Proof step per slice
7. Decision, approval, or evidence hold points
8. Residual risks

## Workflow

1. Lock the objective, constraints, and acceptance evidence from the task contract or request.
2. Separate accepted decisions from open questions. Do not hide unresolved product or architecture choices inside the plan.
3. Mark affected surfaces as critical, non-critical, or unknown using the project contract and inspected evidence. Include secrets, PII, auth/authz, migrations, external inputs, dependency or generated-code changes, untrusted repo/web content, and network/file-system side effects when relevant.
4. Identify durable intent artifacts that must remain true after the work, such as the SOW, runtime project contract, task contract, decision record, design spec, migration plan, or test plan.
5. Decompose the work into the smallest slices that each produce a visible artifact or evidence step.
6. Order the slices by dependency, risk reduction, and reversibility.
7. Attach a proof step and any manual acceptance item to each slice.
8. Add hold points where the plan should stop for approval, missing evidence, architecture review, critical-surface review, or owner decision.
9. If an unresolved architecture decision blocks sequencing, insert a decision spike or hold point; do not present dependent slices as executable until resolved.
10. Keep the plan proportional to the task. A small change needs a short plan.
11. For long-running, delegated, or plan-only work, treat the plan as executable instruction and review it before execution. A reviewed plan is not blanket approval for irreversible, privileged, destructive, or externally visible actions; preserve explicit hold points for those.

## Slice Quality Bar

Good:

- add schema field, run migration dry check, verify approved old-client behavior
- update API handler, run focused test, verify the approved client contract, including any intentional break
- flip rollout flag in staging, verify metrics, confirm rollback path

Bad:

- implement backend
- update frontend
- finish feature

## Rules

- Use `task_contract` when scope or acceptance is still unclear.
- Use `task_orders/ideate.md` when the approach itself is not settled yet.
- Prefer exact files, surfaces, and commands when known. If not known, say what must be discovered first.
- Each slice should have one clear objective and one clear proof step.
- For slices that touch critical or sensitive surfaces, include the required isolation, permission, rollback, or human-review condition.
- For validators, generated artifacts, policy gates, and reusable workflow files, the proof step should name the declared product surface, semantic invariant, independent expected result, and negative case when risk justifies it.
- During delegated or long-running execution, record material deviations from the plan as discovered constraint, conservative decision, evidence, affected slice, and owner-approval need; update the governing intent before continuing if the deviation changes scope, architecture, risk, or acceptance.
- Do not turn optional future work into current scope.
- Do not stuff the plan with speculative code or giant pasted implementations.
- For behavior changes that revise accepted intent, update the governing intent artifact before or with implementation; for behavior-preserving refactors, sync the artifact after code only when it prevents drift.
- Do not create a new durable intent artifact just because a temporary task prompt existed.
- Keep stack-specific examples in project-local notes when they are needed; do not turn them into framework defaults.

## Guardrails

- The plan should reduce execution ambiguity, not create ceremony.
- Planning is not implementation. Do not claim the work is done.
- Do not mark a dependent slice executable while a blocking decision remains unresolved.
