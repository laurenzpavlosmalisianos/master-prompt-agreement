---
name: mpa-root-cause
description: Method for finding the cause of a failure before fixing it. Use when debugging a regression, a flaky or intermittent test, a crash without an obvious cause, or a bug where one fix has already failed.
---

# Root cause

- Save the failing output before editing anything: logs, traces, screenshots, inputs, environment, and what changed recently. The next run may not fail the same way.
- Keep more than one hypothesis until evidence removes the others. The first plausible explanation is often a contributing factor, not the cause.
- Build the smallest reproduction that shows the failure before it can show the fix: one command, fixture, or script. Prefer a probe that can prove a hypothesis wrong, and read-only inspection before edits.
- For an intermittent failure, narrow the conditions first and repeat runs. One passing run proves nothing about a failure that occurs one time in twenty.
- Fix once the causal chain is supported by evidence, with the smallest change that closes it. Stacked speculative fixes hide which one mattered and widen the diff.
- Set a budget per hypothesis; three failed attempts is a reasonable default. When it is spent, revert your own unvalidated edits and temporary debug code, keep the captured evidence, and reopen the hypotheses or ask the user. Signs the budget is spent: the same error repeats, edits toggle back and forth, the edited area keeps growing.
- Failed attempts that stay in context bias the next attempt toward the same idea. Restate the original task and its constraints before trying again.
- When an agent workflow loops or repeats, find the earliest prompt, context, tool result, or stored memory that starts the repetition. Retries and sampling changes are mitigations.
- After the fix, rerun the original reproduction, check neighbouring cases, and add a regression test that fails without the fix.
- Report the cause, the evidence for it, and what was ruled out. A finite number of passing runs does not show that an intermittent symptom is gone; say how many runs there were.
