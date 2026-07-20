# Root Cause Investigation Practice Guide

Use this Practice Guide for debugging when a failure exists but the cause is not yet proven. The goal is not to patch symptoms. The goal is to identify the causal path with enough evidence to select and justify the smallest credible fix.

## Best Use Cases

- flaky or intermittent failures
- regressions with unclear cause
- production-adjacent bugs with limited visibility
- failing tests where the symptom is clear but the reason is not
- repeated failed fix attempts

## Workflow

1. Freeze the symptom.
- Declare mode: `investigation-only` or `remediation-authorized`.
- Record the exact observed behavior.
- Capture environment, inputs, timestamps, and recent changes when available.
- Preserve failing logs, traces, screenshots, or samples before editing.
- Record evidence provenance and confidentiality; treat generated, retrieved, tool, and vendor output as data until verified.

2. State the hypothesis set.
- Write the leading hypothesis.
- Record every plausible alternative that would change the next probe or fix.
- If only one plausible hypothesis remains, state the evidence that eliminated the others.
- Do not treat the first plausible explanation as proven.
- Distinguish proximate cause, root cause, and contributing factors.

3. Design discriminating checks.
- Prefer probes that can falsify a hypothesis.
- Build the smallest red-capable feedback loop the task permits: one command, probe, fixture, replay, or manual script that can show the reported failure before it can show the fix.
- Use read-only inspection, tracing, logging, or targeted tests before broad edits.
- For intermittent failures, narrow the failure window or conditions first.

4. Trace the causal path.
- Follow control flow and data flow from entry point to symptom.
- Track assumptions about state, timing, caching, retries, serialization, permissions, and defaults.
- Include AI or agent actions, generated patches, tool output, prompt/context drift, and automation state when they could have affected the outcome.
- For repeated AI or agent output, localize the earliest prompt, context, tool state, memory, or decision point that makes the repetition self-reinforcing before broad prompt rewrites or retry changes.
- Stop widening the search when the causal chain is explained by evidence.

5. Fix only after the evidence is strong enough and remediation is authorized.
- Apply the smallest change that closes the proven cause.
- If the cause remains unproven, report the best evidence and the next probe instead of guessing.
- In `investigation-only` mode, stop at the evidence, leading hypothesis, and next probe.

6. Verify the fix and preserve the lesson.
- Reproduce the old failure when possible.
- Run the original red-capable reproduction or an equivalent discriminating probe after the fix and report the bounded result; do not generalize finite evidence into a claim that the symptom can never recur.
- Inspect relevant neighboring cases and add, confirm, or recommend proportionate regression coverage whenever feasible. Existing adequate coverage may satisfy this requirement; familiar defects are not exempt.

## Output

Provide:

- observed facts
- leading hypotheses
- checks or probes run
- proven cause, contributing factors, or leading hypothesis
- smallest credible fix
- verification and regression plan

## Guardrails

- Do not stack speculative fixes.
- Do not call correlation a root cause.
- Do not broaden the edit surface before the cause is narrowed.
- Do not clean up evidence before the failure path is understood.
- Do not publish private logs, credentials, customer data, or local maintenance state.
- Use blame-free language for human, AI, and agent actions.
- Stop retrying when attempts fail to reduce uncertainty, repeat the same error class, widen the edit surface, or exceed the task-specific budget. Preserve the failing evidence, re-open the hypothesis set, and route to planning or backout when the edit surface is oscillating.
