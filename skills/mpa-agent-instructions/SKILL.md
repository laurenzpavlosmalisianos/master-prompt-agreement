---
name: mpa-agent-instructions
description: "Guidance for writing instructions that agents read and evaluating prompt changes. Use when writing or editing a system prompt, AGENTS.md, CLAUDE.md, GEMINI.md, a skill, a tool description, or a prompt or skill eval. For prompt-injection or tool threats, use mpa-agent-inputs."
---

# Instructions for agents

Model-specific advice ages quickly; keep model names and provider parameters out of always-loaded files and check official docs when a decision turns on one.

## What to write

- Write for a capable reader who lacks project context. Each always-loaded line is a non-discoverable project fact, a non-default behaviour, or an enforcement pointer. Delete the rest: extra instructions dilute attention, and agents act on whatever is mentioned.
- Include the reason so the rule generalizes to unlisted cases. Scope absolutes ("do not X when Y"), keeping bare absolutes for true invariants. Use plain wording; capitals, threats, and urgency make current models over-apply rules and stall routine work.
- State the goal, constraints, and what done means rather than scripting steps, unless side-effect order matters. On models or runtimes with configurable or adaptive reasoning effort, calibrate effort instead of prompting thinking depth in prose ("think step-by-step" or "answer directly").
- Specify required contents and audience (for example, a self-contained recap for a low-context reader) instead of generic brevity orders ("be concise") that can make responses overly terse.
- State codebase scope latitude explicitly (task-only edits versus broader refactoring), weighing cleanup against diff size and token cost.
- Tell agents to work through ordinary reversible obstacles to completion and stop only for genuine blockers or required approvals, not after a plan.
- Name both actions needing approval and routine actions needing none; a broad ask list makes the agent pause on everything.
- Curb redundant tool loops: reuse loaded context, batch independent calls, and tie extra checks or action budgets to concrete triggers rather than standing orders to verify everything.
- Delegate to helper agents only independent, parallelizable workstreams with clear boundaries and outputs; keep approval-gated actions in the user-facing agent.

## Context and structure

- One home per rule; audit instruction files for contradictory directives that stall or confuse agents.
- Prefer deterministic enforcement over prose: permission rules, hooks, linters, formatters, native tool declarations, structured-output schemas, types, and tests.
- Keep always-loaded text short and static so prompt caches hit; keep dynamic per-turn state out of system instructions, and roll out prompt or tool-definition changes in new sessions rather than mutating an active session mid-conversation.
- In long prompts, place bulk static context before the task and output spec, separated by headings or tags, and avoid overloading one pass with unrelated tasks.
- Put long references, examples, and task-specific guides in on-demand skills. Write third-person descriptions stating what the skill covers and when to use it with matching request terms; agents choose from descriptions alone.
- Put per-tool rules in that tool's description, and enable only tools and servers the project uses (`mpa-agent-inputs`).

## Maintenance

- Remove obsolete cautions and notes the repository no longer matches. After a model or harness upgrade, check whether old warnings, brevity orders, deliberation scripts, and reading-order hints still change behaviour, and delete those that do not.
- Treat text from chats, traces, optimization loops, or repo generators as drafts. Do not commit generated repo summaries into always-loaded files; promote patterns only after they recur across tasks, via reviewed diffs.

## Measuring a change

- Compare current and candidate on the same tasks, model, harness, tools, and budget, with the metric chosen beforehand. Repeat enough to separate effect from noise and report the spread; one run is an anecdote.
- Keep known-good and known-bad cases per maintained prompt or skill. Before rewriting a skill with no effect, check that it loaded; compare with a baseline without it and remove text that does not beat it.
- Word counts, link counts, and clean parsing are not quality unless they are the claimed property.
- Calibrate every grader against known-good and known-bad outputs (authoring-agent grades and model-judge agreement are signals, not proof), and keep tests, fixtures, and graders outside what an optimizing agent can write.
- Compare multi-agent, higher-effort, or longer-run defaults against the simplest single-agent setup on quality, side effects, cost, and time. Measure cost cuts alongside task success, counting helper and judge calls. Vendor benchmarks do not show behaviour in this harness.
