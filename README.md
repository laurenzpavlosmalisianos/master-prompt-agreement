# Master Prompt Agreement

A framework for directing AI coding agents using the structure of professional service contracts.

CLAUDE.md files grow organically, duplicate rules across projects, and have no mechanism for resolving disagreements or learning from mistakes. This framework addresses that. Universal rules live in one file (MSA). Project-specific rules live in another (SOW). Reusable prompts live in task orders. The hierarchy is strict: MSA > SOW > Task Order.

Rules lead with what to do rather than what to avoid, include rationale so the agent generalizes beyond the literal instruction, and build in adversarial self-challenge before committing to decisions. Every line earns its token cost. The framework improves through use.

**Disclaimer:** This framework governs what the AI agent does inside the codebase and assumes infrastructure and host security are handled separately.

## Terminology

The framework borrows its structure from consultancy contract law. Every term maps to a concrete concept in AI-assisted development.

| Contract Term | What It Means Here |
|---|---|
| **Master Service Agreement (MSA)** | One file with universal rules for all projects. Coding philosophy, testing standards, communication style, licensing compliance. Loaded once, applies everywhere. |
| **Statement of Work (SOW)** | One file per project. Tech stack, deliverables, constraints, commands. Replaces per-project CLAUDE.md files. References the MSA instead of duplicating universal rules. |
| **Task Order** | A reusable prompt template for a recurring operation (audit, commit, code review, project init). Invoke by reference when needed. |
| **Contractor** | The AI coding agent doing the work. |
| **Client** | The user directing the agent. |
| **Deliverable** | A unit of work defined in the SOW. Every deliverable has a test that proves it is done. |
| **Acceptance Test** | The test that proves a deliverable works. Must be runnable by the agent without human judgment. |
| **Dispute Resolution** | What happens when pushback (normal agent behavior) does not resolve a technical disagreement. Two formal tiers with recommended escalation, not mandatory. |
| **Gutachten** | Independent expert consultation for technical uncertainty. A fresh agent receives a focused question and renders an assessment. Pre-dispute, advisory only. |
| **Escalation Path** | Gutachten (advisory) → Tier 1 (fresh agent reviews without context bias) → Tier 2 (parallel agent panel votes independently). Either tier can be invoked directly when the situation warrants it. |
| **Standing Orders** | SOW-defined dispute categories that skip directly to panel. Example: "All breaking API changes go to panel." Removes case-by-case escalation decisions for known high-stakes areas. |
| **Arbitration Panel** | Multiple agents launched in parallel to independently evaluate a dispute. Each panelist has an assigned focus area and may propose a third alternative. Majority rules. |
| **Client Override** | The Client overrules any decision at any point. Logged for retrospective review. Every override is evaluated at the next milestone to determine whether the rule or the override was right. |
| **Post-Dispute Review** | At each milestone, all disputes and overrides are reviewed. Did the rule need updating? Did the panel work? Was the override correct? Every dispute teaches the framework something. |
| **Untrusted Content** | All external content (web pages, PRs, third-party files) is treated as data, not instructions. The agent flags anything that looks like prompt injection and never follows embedded directives. |
| **Sub-Contracting** | Chaining multiple task orders into a sequential workflow. Each step is executed by a fresh agent instance that receives a structured handoff. The SOW may define named workflows for recurring sequences. |
| **Findings** | Observations about framework effectiveness, rule friction, and process gaps. The Contractor solicits Client feedback and records it in FINDINGS.md. Feeds the insights report as empirical input for rule improvement. Project-specific, not committed to public repositories. |
| **Annexes** | Optional attachments to the SOW. Annex A (SOUL.md) defines the agent's personality and tone. Annex B (SKILLS.md) defines its technical capabilities. Annex C (AUTHORITY.md) defines its authority limits per environment. Annex D (SECURITY.md) defines the security policy for the project. The consultant's CV, security clearance, and infosec policy, adapted for AI. |

## Structure

```
master-prompt-agreement/
├── master_service_agreement.md    # Universal rules (MSA)
├── statement_of_work_template.md  # Project-specific template (SOW)
├── CLAUDE.md                      # Per-project CLAUDE.md template
├── TODO.md                        # Task state template (maintained by Contractor per project)
├── DECISIONS.md                   # Decision log template (maintained by Contractor per project)
├── FINDINGS.md                    # Findings template (maintained by Contractor per project)
├── task_orders/
│   ├── init.md                    # Project initialization (interactive)
│   ├── ideate.md                  # Structured ideation
│   ├── evaluate.md                # Design evaluation
│   ├── review.md                  # Adversarial code review
│   ├── audit.md                   # Systematic code/site audit
│   ├── commit.md                  # Cross-session commit
│   ├── pull_request.md            # External PR review and reimplementation
│   ├── subcontract.md             # Chained task order workflows
│   ├── gutachten.md               # Independent expert consultation
│   ├── arbitrate.md               # Dispute resolution panel
│   ├── compliance.md              # Framework compliance check
│   └── insights.md                # Milestone retrospective report
├── annexes/
│   ├── soul.md                    # Contractor profile (personality, tone)
│   ├── skills.md                  # Contractor qualifications (capabilities, limitations)
│   ├── authority.md               # Scope of authority (environment, data, commands)
│   └── security.md               # Security policy (vulnerability checklist, compliance)
├── LICENSE                        # Apache 2.0
├── NOTICE                         # Attribution notice
└── README.md                      # This file
```

## How it works

**MSA** — one file, all projects. Contains five performance standards (Think Before Coding, Simplicity First, Surgical Changes, Goal-Driven Execution, Epistemic Standards), dispute resolution with Gutachten, testing requirements, git workflow, communication standards, licensing compliance, safety boundaries, and the continuous improvement loop.

**SOW** — one file, one project. Defines the tech stack, commands, deliverables, constraints, and code review checklist. References the MSA for everything universal. Only states exceptions and additions.

**Task Orders** — reusable prompts for recurring operations: project initialization, structured ideation, design evaluation, adversarial review, audit, commit, external PR review, sub-contracting, Gutachten, arbitration, compliance check, and insights report.

**Hierarchy:** MSA > SOW > Task Order. Lower documents never contradict higher ones. If the SOW does not specify a value, the MSA default governs.

## Dispute escalation

The agent pushes back as part of normal work. When pushback does not resolve the disagreement, it becomes a dispute:

For technical uncertainty without disagreement, a Gutachten (independent expert consultation) can be requested before any dispute exists. It is advisory only.

```
Normal work:  Agent pushes back with evidence (Article 2.1.3)
              ↓ unresolved
Tier 1:       Independent Review  →  Fresh agent evaluates without session bias
              ↓ contested, recurring, or high-stakes
Tier 2:       Arbitration Panel   →  N parallel agents vote, majority rules
              ↓ any point
Ultima Ratio: Client Override     →  Client overrules. Logged for review.
```

Escalation is recommended in order but not mandatory. Either tier can be invoked directly. The SOW can define **standing orders** for dispute categories that always go straight to panel (e.g., breaking changes, security decisions).

The agent prepares the case file (ARBITRATION.md), launches panelists as parallel subagents, collects independent verdicts, and reports the ruling. Panelists may propose a third alternative if neither original position is correct. Every dispute and override is reviewed at the next milestone to improve the rules.

## Setup

```
Read ~/path/to/master_prompt_agreement/task_orders/init.md and help me set up this project.
```

The agent reads the MSA and templates, interviews the Client for the SOW, and creates all project files (CLAUDE.md, TODO.md, DECISIONS.md).

The framework is plain markdown with no agent-specific logic. It should work with any AI coding agent that can read files. For manual setup without an agent, `statement_of_work_template.md` is the starting point.

**Context window cost:** The MSA is ~360 lines. The CLAUDE.md template uses `@` import syntax to load it. The SOW is embedded in CLAUDE.md directly. The framework's rule pruning process (Article 10.3) exists to keep the MSA from growing beyond what earns its place.

## Continuous improvement

After each project milestone:
1. Run the insights report (task_orders/insights.md) to generate a session report.
2. Review which rules prevented errors and which caused friction.
3. Propose rule additions, modifications, or removals.
4. Update the MSA version and changelog.

Rules that never trigger in 3+ projects are candidates for removal. Mistakes that no rule prevented become new rules. Every client override is reviewed at the next milestone to see if the rule or the override was right.

## Design principles

- **Contract hierarchy**: MSA is the safety net, SOW is the customization layer.
- **Positive framing**: Rules lead with what to do, then state what to avoid. Agents follow direction better than bare prohibition.
- **Context-rich rules**: Every constraint includes its rationale so the agent generalizes correctly rather than following blindly.
- **Adversarial by design**: Audits, reviews, and the agent's own reasoning include structured self-challenge before committing to decisions.
- **Supply chain aware**: Dependency verification covers slopsquatting, typosquatting, and dependency confusion. The trust boundary model classifies all inputs.
- **No preprocessing**: The agent reads definitions and resolves them naturally. No template rendering scripts.
- **Token-efficient**: Every line earns its place. No preamble or padding. State files are pruned to preserve context budget.
- **Self-optimizing**: The framework improves through use. Every dispute, mistake, and override is a learning event.
