---
name: mpa-delegation
description: "Rules for handing work to helper agents, parallel sessions, or unattended runs and for taking their results back. Use when spawning subagents, splitting a task across parallel agents or worktrees, starting a background or scheduled run, or merging work that another agent produced."
---

# Delegation and unattended work

A helper's report is a claim to check, and a helper's agreement is not the user's approval.

- Say what the helper may change. A helper usually inherits the parent's permissions and sandbox, including a bypass mode, and an instruction not to edit is not a control.
- Split along what changes independently. Two writers on one file, lockfile, schema, migration sequence, or generated artifact produce a conflict that a merge settles by dropping one side.
- Check before relying on it: read the diff a helper produced, not its summary, rerun the check it reports as passed, and confirm that cited files and lines exist.
- Helpers that share a model, a prompt, or a context give one opinion, however many agree. A reviewer that was handed the author's conclusion reviews the conclusion; pass the task and the diff without the reasoning.
- Merge parallel results one at a time and rerun the checks on the combined state; branches that pass alone can fail together. Settle a conflict by reading both sides, not by taking one wholesale.
- Before starting, fix the check that defines done, a turn or spend cap, where the result is delivered, and who reviews it. A turn that ends in text has not shown that the task is finished, so cap automatic continuations.
- At the end, stop the background jobs the run started and remove its temporary files and work trees, after confirming that nothing uncommitted is left in them.
