---
name: mpa-root-cause
description: "Method for finding the root cause of a failure before fixing it. Use when debugging a regression, a flaky or intermittent test, a crash without an obvious cause, or a bug where one fix has already failed. For active incidents or data loss, use mpa-incident."
---

# Root cause

- Capture the failing output before editing anything—only what is not already in context: logs, traces, screenshots, inputs, environment, and recent changes. The next run may not fail the same way.
- For an intermittent failure, narrow the conditions first and repeat runs. One passing run proves nothing about a failure that occurs one time in twenty.
- Fix once the causal chain is supported by evidence, with the smallest change that closes it. Stacked speculative fixes hide which one mattered and widen the diff.
- When an agent workflow loops, repeats, or stops with work open, find the earliest prompt, context, tool result, stored memory, or harness rule that causes it, such as a loop that treats a text-only turn as done. Retries and sampling changes are mitigations.
