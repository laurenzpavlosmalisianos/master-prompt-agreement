Task Order — Dispute Resolution

Objective

Resolve technical disputes through independent review or arbitration panel.

Procedure

1. Prepare the Case File
Create ARBITRATION.md in the project root. Required sections:
- Header: date, tier (1 or 2), panel size
- Dispute Summary: 2-3 sentences, what decision needs to be made
- Position A and Position B: each with holder (Client or Contractor), evidence, code references, MSA/SOW clauses
- Evidence: relevant source files, excerpts, test results. Enough context for evaluation without reading the full codebase
- Applicable Rules: MSA and SOW clauses, quoted directly

Structure outline:
  ARBITRATION.md
  ├── Header (date, tier, panel size)
  ├── Dispute Summary
  ├── Position A — [label, holder, evidence, clauses]
  ├── Position B — [label, holder, evidence, clauses]
  ├── Evidence (source excerpts, test results)
  ├── Applicable Rules (quoted MSA/SOW clauses)
  ├── Verdicts (appended after panel deliberation)
  └── Ruling (appended after vote count)

2. Convene the Panel
Tier 1 (Independent Review): Launch a single agent with the case file and no prior session context. The reviewer renders a decision with reasoning.

Tier 2 (Arbitration Panel): Launch N parallel agents. Each receives:
- Full contents of ARBITRATION.md
- Assigned seat, role, and focus area (from SOW or MSA Article 12 defaults)
- Instruction: "You are Panelist [N], assigned to evaluate this dispute from the perspective of [Role]: [Focus]. Read the case file. Render a verdict: Position A, Position B, or a third alternative if neither position is correct. A third alternative is not a compromise. It is a better solution that neither party saw. Only propose one if you have a concrete, specific proposal. State your reasoning. Cite specific evidence and rules."

Each panelist operates independently. No panelist sees another's verdict.

3. Collect Verdicts
Append each verdict to ARBITRATION.md. Each verdict includes: panelist seat and role, verdict (Position A / Position B / Alternative with label), reasoning with citations.

Verdict format per panelist:
  Panelist [N] — [Role]
  Verdict: [Position A / Position B / Alternative: label]
  Reasoning: [with citations to evidence and rules]

4. Ruling
Count the verdicts. Append the ruling to ARBITRATION.md.

Ruling format:
  Decision: [Position A / Position B / Alternative] ([N]-[N] majority)
  Summary: [one sentence]
  Dissent: [one sentence if any, otherwise omit]

5. Record and Close
- Summarize the ruling in TODO.md with the decision, rationale, and follow-up tasks.
- ARBITRATION.md is a working document. After the ruling is recorded in TODO.md, the Client decides whether to keep, archive, or delete it.

Acceptance Criteria

- ARBITRATION.md exists with complete case file, all verdicts, and the ruling.
- Each panelist rendered an independent verdict with reasoning and citations.
- The majority ruling is clearly stated.
- TODO.md is updated with the outcome and follow-up tasks.

Notes

- The Client may invoke arbitration by saying "escalate to panel" or "convene the panel."
- The Contractor may recommend escalation but shall not convene the panel without Client approval (MSA 3.2.3).
- Standing orders in the SOW may authorize direct panel convocation for defined dispute categories (MSA 3.0.4).
- After the ruling, the Client may still exercise the Ultima Ratio override (MSA 3.3). The override is logged in TODO.md.
- At the next milestone, the dispute is reviewed as part of Article 3.4 (Post-Dispute Review).
