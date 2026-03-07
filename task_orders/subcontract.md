Task Order — Sub-Contracting

Objective

Chain multiple task orders into a sequential workflow. Each step is executed by a sub-contractor (a fresh agent instance) that receives a structured handoff from the previous step. The Contractor orchestrates the sequence and aggregates results.

Procedure

1. Define the Workflow

The Client specifies a sequence of task orders to execute. The SOW may define named workflows for recurring sequences. Example named workflows:

feature: review → audit → commit (new feature implementation)
external-pr: pull_request → review → audit (external contribution)
release: audit → review → commit (pre-release verification)

If no named workflow applies, the Client specifies the sequence directly.

2. Prepare the Handoff Document

Before each step, the Contractor prepares a handoff in TODO.md with:

- Step completed: What was done and key findings.
- Files modified: What changed.
- Open items: Unresolved issues for the next step.
- Context for next step: What the sub-contractor needs to know.

3. Execute Each Step

For each step in the sequence:

3.1. Launch a sub-contractor (fresh agent instance) with the relevant task order and the handoff context from TODO.md.
3.2. The sub-contractor executes the task order, following its own procedure and acceptance criteria.
3.3. On completion, the sub-contractor updates TODO.md with its handoff.
3.4. The Contractor reviews the output before proceeding to the next step.

Gate rule: If any step fails its acceptance criteria, the workflow stops. The Contractor reports the failure and the remaining steps. The Client decides whether to fix and continue or abort.

4. Parallel Steps

When steps are independent and do not require sequential handoff, the Contractor may launch sub-contractors in parallel. The Contractor must confirm independence before parallelizing. When in doubt, run sequentially.

5. Report Results

After all steps complete, deliver a summary:

- Steps executed and their outcomes.
- Files modified across all steps.
- Open items and follow-up tasks.
- Whether all acceptance criteria were met.

Acceptance Criteria

- Every step in the sequence was executed or the workflow was stopped at a gate failure.
- Each sub-contractor followed its task order's procedure and acceptance criteria.
- TODO.md contains the handoff from every completed step.
- The final summary accounts for all steps.

Notes

- Sub-contractors operate independently. Each receives the task order and handoff context, not the full session history.
- The Contractor does not modify sub-contractor output. If a step's result needs correction, re-run the step or escalate to the Client.
- Sub-contracting is orchestration, not delegation. The Contractor remains responsible for the workflow and reports to the Client.
