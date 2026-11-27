---
name: mpa-agent-instructions
description: "Guidance for writing instructions that agents read and evaluating prompt changes. Use when writing or editing a system prompt, AGENTS.md, CLAUDE.md, GEMINI.md, a skill, a tool description, or a prompt or skill eval. For prompt-injection or tool threats, use mpa-agent-inputs."
---

# Instructions for agents

Model-specific advice ages quickly; keep model names and provider parameters out of always-loaded files and check official docs when a decision turns on one.

## What to write

- Include the reason so the rule generalizes to unlisted cases. Scope absolutes ("do not X when Y"), keeping bare absolutes for true invariants. Use plain wording; capitals, threats, and urgency can make some models over-apply rules and stall routine work.
- State the goal, constraints, and what done means rather than scripting steps, unless side-effect order matters. Where effort is configurable, calibrate it instead of prompting thinking depth in prose ("think step-by-step", "answer directly") or asking for written-out reasoning in the reply, which some models decline.
- State scope latitude (task-only edits versus broader refactoring) and who owns the code, weighing cleanup against diff size and token cost; some models weigh ownership above a scope limit, so keep the two consistent.

## Measuring a change

- Compare current and candidate on the same tasks, harness, tools, and budget, on each model the prompt targets, with the metric chosen beforehand. Repeat enough to separate effect from noise and report the spread.
- Keep known-good and known-bad cases per maintained prompt or skill. Before rewriting a skill with no effect, check that it loaded; compare with a baseline without it and remove text that does not beat it.
- Test skill descriptions with requests that should and should not trigger them, including near-misses, and hold some back from tuning.
- Calibrate every grader against known-good and known-bad outputs (authoring-agent grades and model-judge agreement are signals, not proof), and keep tests, fixtures, and graders outside what an optimizing agent can write.
