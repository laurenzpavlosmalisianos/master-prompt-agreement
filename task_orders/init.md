Task Order — Project Initialization

Objective

Set up a new project with the Master Prompt Agreement framework: AGENTS.md with SOW, TODO.md, DECISIONS.md, and optionally FINDINGS.md.

Procedure

1. Check if the framework path is already known (from prior configuration, environment variable, or the invoking command). If not, ask the Client.
2. Read the MSA from that directory.
3. Read `statement_of_work_template.md` to understand what needs to be filled in.
4. If the project already has code, read the existing codebase first to pre-fill what you can (language, structure, dependencies, existing test commands). Present findings and ask the Client to confirm or correct.
5. Ask the Client the following, in order. Do not ask all questions at once. Group them naturally and let the Client respond in batches.

Project identity:
- What is this project? (1-2 sentences for the Recitals)
- What language, framework, and key dependencies?
- What language standard or version? (e.g., Python 3.14, Rust 2024 edition, TypeScript 5.7 strict)
- What package manager?
- Brief architecture description? (e.g., monolith, microservices, static site)

Scope:
- What should the Contractor build, maintain, or modify?
- What is out of scope?

Commands:
- How to run the project locally?
- How to build for production?
- Is there a single command to regenerate all deliverable artifacts from source? (Build All Command.)
- How to run tests? Lint? Type check?
- How to deploy (if applicable)?
- Are there commands the agent should never run? (Command Restrictions.)

Constraints:
- Any non-negotiable rules specific to this project?
- Any technology or pattern prohibitions?

Deliverables:
- What are the first deliverables?
- What test proves each deliverable is done?
- For non-code deliverables: what acceptance checklist criteria apply? (Art. 5.1.1.)

Standards:
- Any version-pinned documentation to follow? (Applicable Standards.)
- Any project-specific code review items beyond the MSA?
- Does AI-generated code require disclosure? (Co-author tags, NOTICE file, commit footer, or none.)

Dispute resolution:
- Does this project need a custom Arbitration Panel composition, or do MSA defaults work?
- Are there dispute categories that should always go directly to panel? (Standing Panel Orders.)
- Should the Contractor be able to request Gutachten (expert consultation) autonomously, or require Client approval? (MSA default: requires approval.)

Workflows (optional):
- Are there recurring task order sequences that should be defined as named workflows? (Sub-contracting.)

Scope of authority (optional):
- Does this project have environment-specific restrictions or data sensitivity rules? (Annex C, AUTHORITY.md)

Security (optional):
- Does this project have specific security requirements beyond MSA 8.1.6? (Annex D, SECURITY.md)
- Are there applicable compliance frameworks? (SOC 2, HIPAA, PCI DSS, GDPR)

Contractor profile (optional):
- Should the Contractor have a specific personality or communication style for this project? (Annex A, SOUL.md)
- Are there specific capabilities or known limitations to document? (Annex B, SKILLS.md)

6. Fill in the SOW from the Client's answers. Do not invent answers. If the Client skips a question, leave the section with a placeholder or omit optional sections.
7. Copy the AGENTS.md template to the project root. Replace the `@` path with the actual framework path and replace the SOW placeholder with the filled-in SOW content. If the target agent expects a different entrypoint file name, rename it at this step.
8. Create TODO.md and DECISIONS.md in the project root.
9. Ask the Client to review the generated files. Apply corrections.

Acceptance Criteria

- AGENTS.md or the target agent's equivalent entrypoint file exists in the project root with framework path and filled SOW.
- TODO.md and DECISIONS.md exist in the project root.
- Client has reviewed and approved the generated files.
- The Contractor can begin work without further setup questions.

Notes

- If the Client does not know an answer yet (e.g., deploy command), mark it as TBD in the SOW.
- Optional sections (Arbitration Panel, Standing Panel Orders, Gutachten, Command Restrictions, Workflows, Annexes, Security Policy) should be deleted from the SOW if not used, not left with placeholder text.
- For projects that accept external contributions, mention the pull_request.md task order as a workflow option.
