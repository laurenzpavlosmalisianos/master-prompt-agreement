<!-- mpa-generated-state-origin: master-prompt-agreement/project-state/v1 -->

# Precedents

Purpose: compressed durable lessons, not session logs.

Each precedent should state:

- Citation: stable identifier such as `P-2026-04-13-01`
- Trigger: when the precedent applies
- Holding: the lesson or rule
- Required Checks: what must be verified next time
- Source: issue, incident, decision, or commit that justified the precedent

When adding records, keep this index compact. Each index entry should name the
trigger pattern and cite the matching precedent ID so agents can decide whether
to load the full record.

Create a precedent after a repeated failure loop, complex incident, arbitration,
accepted exception, or recurring review finding when the lesson is likely to
change future checks.

Example format:

```markdown
- Citation: `P-YYYY-MM-DD-01`
  Trigger: [task pattern, failure mode, or trust boundary]
  Holding: [one sentence]
  Required Checks: [one short list]
  Source: [issue, incident, decision, or commit]
```

Rules:

- Prefer one precedent over a long retrospective.
- Keep each precedent short enough to scan quickly.
- Delete or supersede stale precedents explicitly.
- Project-specific precedents stay in the project where they apply.
- If a precedent appears reusable across projects, route it through `task_orders/insights.md` as a curated framework candidate instead of copying raw project state into framework files.

## Trigger Index

- None.

## Records

- None.
