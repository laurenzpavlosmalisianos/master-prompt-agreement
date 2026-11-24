---
name: mpa-root-cause
description: "Method for finding the root cause of a failure before fixing it. Use when debugging a regression, a flaky or intermittent test, a crash without an obvious cause, or a bug where one fix has already failed. For active incidents or data loss, use mpa-incident."
---

# Root cause

- Capture the failing output before editing anything—only what is not already in context: logs, traces, screenshots, inputs, environment, and recent changes. The next run may not fail the same way.
- For a regression, isolate what changed since the last known-good state (commit diff, `git bisect`, dependency, configuration, or environment diff) before theorizing through the codebase.
- Keep more than one hypothesis until evidence removes the others. The first plausible explanation is often a contributing factor, not the cause.
- Build the smallest reproduction that shows the failure before it can show the fix. Prefer batched, read-only probes that discriminate between hypotheses over speculative edits.
- For an intermittent failure, narrow the conditions first and repeat runs. One passing run proves nothing about a failure that occurs one time in twenty.
- Fix once the causal chain is supported by evidence, with the smallest change that closes it. Stacked speculative fixes hide which one mattered and widen the diff.
- Set a budget per hypothesis (three failed attempts is a reasonable default). When it is spent, revert your own unvalidated edits and temporary debug code, keep the captured evidence, and reopen the hypotheses or ask the user. Signs the budget is spent: the same error repeats, edits toggle back and forth, or the edited area keeps growing.
- Failed attempts kept in context anchor reasoning toward the same path. After a spent budget, start a fresh context (or a clean-context helper agent) with only the task, constraints, captured evidence, and ruled-out hypotheses, or restate them cleanly before trying again.
- When an agent workflow loops or repeats, find the earliest prompt, context, tool result, or stored memory that starts the repetition. Retries and sampling changes are mitigations.
- After the fix, rerun the original reproduction, check neighbouring cases, and add a regression test that fails without the fix where the project has tests (otherwise state what went unchecked).
- Report the cause, the evidence for it, and what was ruled out. For an intermittent symptom, state how many passing runs were observed.
