Task Order — Adversarial Review

Objective

Find every bug, edge case, and weakness in the code. Assume mistakes were made. Prove those assumptions right.

Procedure

1. Read the SOW for project constraints and the Code Review Checklist.
2. Read all files changed since the last commit (or all files if scope is the full codebase).
3. For each function, module, or component, ask:
   - What happens with empty input? Null? Undefined?
   - What happens with huge input?
   - What happens at boundaries? Off-by-one errors are everywhere.
   - Did they handle the error path? Really? Prove it.
   - What assumptions were made? Break those assumptions.
   - Does it match the SOW constraints? (No JS on a zero-JS site. No external deps on a self-hosted project.)
4. Classify each finding:
   - Bug — code does not do what it claims. Provide reproduction steps.
   - Edge Case — code fails under specific input. Provide the input.
   - Weakness — code works but is fragile, unclear, or violates a standard. Explain why.
   - Standards Violation — code violates MSA, SOW, or applicable standards. Cite the clause.
5. Add findings to TODO.md or fix directly if unambiguous.
6. Deliver findings as a structured list: file and line number, category (Bug / Edge Case / Weakness / Standards Violation), description, proposed fix or test to add.

Acceptance Criteria

- Every file in scope has been reviewed adversarially.
- All findings are classified and documented.
- No finding is dismissed without evidence.

Notes

- "That looks too simple. They probably forgot something."
- "Happy path works? Now break it."
- "They said it handles errors? Prove it."
- "This code looks correct. Find where it is not."
