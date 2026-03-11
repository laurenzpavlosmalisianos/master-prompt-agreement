Task Order — Insights Report

Objective

Generate a retrospective report after a milestone. Identify what worked, what failed, and what rules need to evolve.

Triggers (MSA 10.1.1): (a) all SOW deliverables are completed, (b) a project milestone defined in the SOW is reached, or (c) the Client requests it.

Procedure

1. Gather Evidence
Read: TODO.md, DECISIONS.md, FINDINGS.md (if exists), ARBITRATION.md (if exists), git log since last milestone.

2. Analyze Patterns
For each category:
- Mistakes Made: What errors occurred? Was there a rule that should have prevented it?
- Rules That Helped: Which MSA/SOW rules prevented errors or guided good decisions?
- Rules That Hindered: Which rules caused friction or were consistently overridden?
- Missing Rules: Were there situations where no rule existed and one would have helped?

3. Classify Findings
For each finding, propose one of:
- New rule — draft text, specify MSA (universal) or SOW (project-specific).
- Modify rule — cite clause and proposed change.
- Remove rule — cite clause and evidence of net harm.
- No action — reasoning for status quo.

4. Review Overrides
For any Client overrides since last milestone (MSA 3.3):
- Was the override correct in hindsight?
- If yes: propose updating the contradicted rule.
- If no: the original rule stands reinforced.

5. Deliver report in the following format:

Session Insights — [Project Name] — [Date]
Milestone: [what was completed]
Findings: [#] [Category: Mistake/Help/Hinder/Missing] [Description] [Proposal: New/Modify/Remove/No action] [Scope: MSA/SOW]
Override Review: [Override description] [Correct: Yes/No] [Action: Update rule / Rule reinforced]
Recommended Changes: [full text of each proposed rule change]

Acceptance Criteria

- All work, decisions, disputes, and overrides since last milestone reviewed.
- Every finding has a proposal (including "no action" with reasoning).
- Proposals distinguish MSA-scope from SOW-scope.
