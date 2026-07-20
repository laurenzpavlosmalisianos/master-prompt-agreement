# Logical Spec Review Practice Guide

Use this Practice Guide when requirements, acceptance criteria, policies, state machines, billing rules, permissions, migrations, or structured prompts need logical coherence review before implementation or code review.

## Best Use Cases

- logic-heavy business rules with exceptions, tiers, or precedence
- authorization, billing, quota, eligibility, validation, or routing matrices
- state transitions, workflow gates, lifecycle rules, and rollout conditions
- generated specifications, plans, or prompt artifacts that may hide contradictions
- reviews where tests pass but the stated rules may be incomplete or inconsistent

## Workflow

1. Define the vocabulary.

- List the domain terms, entities, states, predicates, and outputs.
- Give each term one meaning. If a term has two plausible meanings, mark the ambiguity.
- Separate facts already approved from inferences and proposed rules.

2. Atomize the rules.

- Rewrite compound requirements as small propositions, invariants, preconditions, postconditions, and exceptions.
- Mark each rule as required, forbidden, optional, or derived.
- Preserve source or stakeholder provenance for behavior-affecting rules, assumptions, inferred rules, and conflict resolutions.

3. Check consistency and satisfiability.

- Look for direct contradictions, circular definitions, impossible preconditions, and incompatible defaults.
- Confirm that at least one valid input or state can satisfy all required rules.
- Check whether the rules accidentally permit forbidden, unsafe, out-of-scope, or privilege-expanding states, not only whether valid states exist.
- Check that required exceptions do not erase the base rule.

4. Check completeness and exclusivity.

- Partition the input or state space into cases.
- Identify missing cases, overlapping cases, and ties with no precedence rule.
- Check boundary values, null or unknown states, empty sets, and invalid inputs.
- For state machines, every allowed transition should have a source, target, trigger, guard, and failure behavior.

5. Check implication direction.

- Verify `if A then B` has not been reversed into `if B then A`.
- Distinguish necessary conditions from sufficient conditions.
- Check quantifiers: all, any, exactly one, at least one, at most one, none.
- Check temporal claims: before, after, until, unless, eventually, and never.

6. Translate logic into verification.

- Turn each material case or invariant into an acceptance check, test, assertion, schema rule, lint rule, or review question.
- For deny, exclusion, precedence, validator, or failure rules, include a negative case that would fail if the rule were omitted or applied to the wrong surface.
- Prefer a small decision table or truth table when it exposes cases more clearly than prose.
- Do not force every issue into a deterministic check; keep semantic judgments, policy choices, and authority questions as review findings or hold points.
- Keep untestable or policy-owned choices as open questions or hold points.

## Output

Provide:

1. vocabulary and approved facts
2. rule set or decision table
3. contradictions or ambiguous terms
4. missing, overlapping, or impossible cases
5. accepted invariants and precedence rules, with source or authority noted where material
6. tests, assertions, or review checks to add
7. open questions and stop conditions

## Guardrails

- Do not formalize simple tasks that already have obvious acceptance checks.
- Do not use logic notation as decoration; use it only when it exposes a real case or contradiction.
- Do not treat a generated spec as authoritative until its rules are checked against project facts.
- Do not hide product, legal, security, or stakeholder decisions inside derived rules.
- Do not widen implementation scope merely because the logical review found future cases.
