Task Order — Compliance Check

Objective

Validate that the project's framework setup is complete, consistent, and functional.

Procedure

1. File Presence
Verify in project root: CLAUDE.md (with framework path and SOW), TODO.md, DECISIONS.md.

2. SOW Completeness
Read the SOW and verify:
- No unfilled placeholders ([e.g., ...], [YYYY-MM-DD], TBD markers older than one milestone).
- Definitions table has values for Contractor, Client, Test Command.
- At least one deliverable with acceptance test.
- Build commands section filled.

3. Command Verification
Run each SOW-defined command (test, lint, type check, build). Report pass/fail/not configured.

4. State Freshness
Review TODO.md:
- Completed items not cleared (MSA 6.1.7).
- Blockers without resolution across 3+ sessions.
- State that contradicts the actual codebase.

5. MSA Version Check
Compare the SOW's MSA reference version to the actual MSA version. Flag mismatch.

6. Report results: for each check, report check name, status (pass/fail), and details. Add actionable items to TODO.md.

Acceptance Criteria

- Every check run and reported.
- Actionable items added to TODO.md.

Notes

- Run after project initialization to verify setup before starting work.
- Run periodically (e.g., after a milestone or when resuming a dormant project) to detect drift.
- A failing MSA version check means the SOW was written against an older MSA. Review the changelog for breaking changes before updating the reference.
