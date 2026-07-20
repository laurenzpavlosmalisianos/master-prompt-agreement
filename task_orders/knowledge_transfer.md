Task Order — Knowledge Transfer

Objective

Help the user understand a session, change, subsystem, decision, or workflow through evidence-backed explanation and optional comprehension checks.

This is the process-control workflow for knowledge transfer. For the specialist
presentation standards, explanation quality criteria, and lightweight
comprehension-check rules, load `practice_guides/knowledge_transfer.md`.

Use this Task Order only when the user asks to learn, be taught, be onboarded, understand why something changed, verify their own understanding, or when the governing task contract makes reviewer or owner understanding an explicit acceptance condition. Do not use it as the default final-summary workflow for ordinary implementation, review, audit, or source-update work.

Procedure

1. Establish the learning scope.

- Identify the object of understanding: session, diff, feature, bug, architecture, workflow, or decision.
- Identify the requested depth: overview, maintainer-level, or deep technical walkthrough.
- If the scope is unclear, choose the smallest useful scope and state that assumption.

2. Gather the evidence.

- Read `AGENT_PROJECT.md` for active project context and evidence surfaces. Consult `STATEMENT_OF_WORK.md` when canonical project terms, acceptance terms, or omitted details affect the explanation.
- Read the relevant task output, files, diffs, tests, logs, docs, and decision records.
- Treat summaries, external explanations, chat excerpts, and generated notes as context only.
- Use current-source review only when the explanation depends on volatile external facts.

3. Load `practice_guides/knowledge_transfer.md`.

4. Follow `practice_guides/knowledge_transfer.md` for the understanding map, explanation sequence, optional comprehension checks, and durable-output boundary.

5. Preserve durable output only when requested.

- Keep transient learning checklists in the conversation.
- Write durable onboarding notes, runbooks, decision briefs, or code comments only when they are useful project artifacts.
- Do not store teaching notes as project policy, standing instructions, memory, TODOs, or decisions unless they independently qualify for that state surface.

Acceptance Criteria

- The explanation is grounded in inspected evidence.
- The user-facing learning scope is explicit.
- The understanding map covers the relevant problem, mechanism, solution, tradeoffs, edge cases, verification, impact, and gaps.
- Any checkpoint questions are optional, bounded, and followed by corrections or explanation.
- No persistent teaching artifact is created without request and an appropriate project state surface.

Notes

- Knowledge transfer is a user-facing comprehension workflow, not a replacement for review, audit, or implementation verification.
- Prefer concise maintainer explanations over broad tutorials unless the user asks for deeper teaching.
