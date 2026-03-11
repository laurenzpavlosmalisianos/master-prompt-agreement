Statement of Work — [PROJECT NAME]

SOW Version: 1.0.0  MSA Reference: master_service_agreement.md v1.0.0  Date: [YYYY-MM-DD]

All values not specified below fall back to MSA Article 12 defaults.

Definitions

Contractor: [e.g., Claude Code (claude-opus-4-6)]
Client: [Your name]
Test Command: [e.g., uv run pytest, cargo test, npm test]
Lint Command: [e.g., uv run ruff check src/, cargo clippy, eslint]
Type Check Command: [e.g., uv run mypy --strict src/, tsc --noEmit]
Package Manager: [e.g., uv, cargo, pnpm, none]
Language Standard: [e.g., Python 3.14, Rust 2024 edition, TypeScript 5.7 strict]
AI Disclosure: [e.g., none, Co-Authored-By tag, NOTICE file entry, commit footer. Required by EU AI Act / California AI Transparency Act / organizational policy / none]

Arbitration Panel

_Delete this section to use MSA defaults._

Seat 1: [model] — [role] — [focus]
Seat 2: [model] — [role] — [focus]
Seat 3: [model] — [role] — [focus]

Standing Panel Orders

_Delete this section if no dispute categories require automatic escalation to panel._

Disputes in the following categories go directly to Tier 2 (Arbitration Panel) without requiring escalation through Tier 1:

- [e.g., All breaking API changes]
- [e.g., All security-related decisions]
- [e.g., All database schema migrations]

Gutachten

_Delete this line to use MSA default (requires Client approval)._

Gutachten Approval: [Required / Autonomous]

Recitals

[2-3 sentences: what this project is, what it does, who it serves.]

Scope of Work

In scope:
- [What to build, maintain, or modify]

Out of scope:
- [What not to touch]

Technical Specifications

Tech stack: [Language/framework, key dependencies]

Architecture: [Brief description or reference to docs]

File structure:
[key directories and files]

Deliverables and Acceptance Tests

1. [Deliverable description] — [Test file/command] — [Pass criteria]
2. [Deliverable description] — [Test file/command] — [Pass criteria]

Acceptance Checklist (per deliverable):
- [ ] [Criterion 1, e.g., output compiles/renders without errors]
- [ ] [Criterion 2, e.g., no unresolved references or broken links]
- [ ] [Criterion 3, e.g., output within defined constraints (size, format, structure)]
- [ ] [Project-specific criteria]

_Use for deliverables where automated tests are not applicable (Art. 5.1.1). Delete this section if all deliverables have automated tests._

Examples:
1. User authentication API — test/auth.test.ts — All endpoints return correct status codes, tokens expire after configured TTL
2. Data export CLI command — test/export.test.ts — Exports CSV and JSON formats, handles empty datasets without error

Project-Specific Constraints

- [e.g., No `Any` type annotations. All types explicit or inferred, never escaped.]
- [e.g., No `.unwrap()` in production code. Use `?` operator or explicit error handling.]
- [e.g., TypeScript `strict: true`. No type assertions (`as Type`) without justification.]
- [e.g., Standard library preferred. Every PyPI/crate/npm dependency must be justified.]

Build and Development Commands

[dev command] — Development
[build command] — Build
[build-all command] — Regenerate all deliverable artifacts from source
[test command] — Test
[lint command] — Lint
[deploy command] — Deploy (if applicable)

Command Restrictions

_Delete this section if no command restrictions apply._

[command] — never run — [reason] — use [alternative] instead

Examples:
npm run dev — never run — starts server, blocks terminal — use npm run check instead
npm test (unfiltered) — never run — full suite too slow for iteration — use npx vitest --run test/specific.test.ts instead

Applicable Standards

- [e.g., Python 3.14 stdlib, Rust Reference (2024 edition), PostgreSQL 17 docs]

Code Review Checklist

_Project-specific items beyond MSA Article 8.1._

1. [e.g., No `unsafe` blocks without a `// SAFETY:` comment explaining the invariant.]
2. [e.g., No `print()` or `console.log()` in production code. Use structured logging.]
3. [e.g., All public functions have type hints. `mypy --strict` must pass with zero errors.]
4. [e.g., `#[deny(clippy::pedantic)]` or equivalent strictest linter config for the language.]

Workflows

_Delete this section if no recurring task order sequences are needed._

Named workflows for sub-contracting (see task_orders/subcontract.md):

[name]: [sequence] ([when to use])

Examples:
feature: review → audit → commit (new feature implementation)
external-pr: pull_request → review → audit (external contribution)

Annexes

_Optional. Delete if not used._

- Annex A — Contractor Profile (SOUL.md): [path or inline]
- Annex B — Contractor Qualifications (SKILLS.md): [path or inline]
- Annex C — Scope of Authority (AUTHORITY.md): [path or inline]
- Annex D — Security Policy (SECURITY.md): [path or inline]
