Task Order — Audit

Objective

Verify that the project meets all requirements defined in the SOW and MSA through systematic review of every relevant source file.

Procedure

1. Read the SOW and TODO.md for project context and current state.
2. If Annex D (SECURITY.md) exists, read it. Use its checklist as additional audit criteria alongside the SOW's Code Review Checklist.
3. Read every relevant source file in the codebase. Do not limit yourself to what the checklists mention.
4. Use the SOW's Code Review Checklist as minimum coverage. Apply independent judgment: if you find a problem no checklist addresses, report it.
5. For each finding, classify severity:
   - Blocker — deployment or security issue. Must fix before release.
   - Defect — functional or standards violation. Fix before next deploy.
   - Advisory — improvement opportunity. Log for Client decision.
6. For any blocker or defect: fix it directly if the fix is unambiguous. Add it to TODO.md if it requires Client decision.
7. Run the SOW's Test Command and Build Command. Confirm zero failures and zero warnings.
8. Deliver a summary: total checks (pass/fail count), blockers fixed and how, defects fixed and how, items added to TODO.md for Client decision, advisories with one-line rationale each.

Acceptance Criteria

- Every file in scope has been reviewed.
- All blockers are fixed or logged in TODO.md with rationale.
- Test Command and Build Command pass with zero warnings.
- Report delivered.

Notes

- No senior developer reviewing the code should find anything to criticize that the audit missed. The audit is adversarial by nature. Assume mistakes were made. Assume corners were cut.
