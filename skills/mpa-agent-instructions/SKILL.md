---
name: mpa-agent-instructions
description: Guidance for writing instructions that agents read. Use when writing or editing a system prompt, an AGENTS.md or CLAUDE.md file, a skill, a tool description, or an evaluation of a prompt change.
---

# Instructions for agents

Advice that is specific to one model changes with each model generation. Where a decision turns on it, check the vendor's current official documentation.

## What to write

- Write for a capable reader who lacks the project's context. Give the goal, the constraints, what done means, and the facts that cannot be read from the code. Leave out what the model does anyway.
- Each line in an always-loaded file is one of three things: a project fact, a behaviour the model does not show unprompted, or a pointer to something that enforces a rule. Delete the rest. Every added instruction lowers attention to the others, and agents tend to act on whatever is mentioned.
- Give the reason with a rule. A reason lets the model apply the rule to cases the text did not list.
- State an absolute with its scope: "do not X when Y". A bare "never" or "always" is applied in places where it does not fit. Keep unscoped absolutes for true invariants.
- Use plain wording. Capitals for emphasis, threats, and urgency make current models over-apply the emphasized rule and hold back routine work.
- Describe the intent in preference to a step-by-step procedure, unless the order of side effects matters.
- Be specific about approvals: name the actions that need a yes and the routine actions that need none. A broad list makes the agent ask about everything.
- Do not add standing orders to verify everything, run the whole suite, or delegate every task. Tie extra verification to a concrete trigger.
- Leave formatting and naming to formatters and linters.

## Where it goes

- One home per rule. Copies in several files drift apart and cost context on every load.
- Prefer enforcement to prose. A permission rule, hook, schema, type, or test holds where an instruction is only usually followed. Write the instruction when nothing deterministic can express the rule.
- Keep always-loaded text short and stable. Put long reference material, examples, and task-specific guidance in files loaded on demand, such as skills.
- A skill description says, in the third person, what the skill is for and when to use it, with the terms a matching request would contain. The agent chooses from descriptions alone.
- Rules about one tool belong in that tool's description.
- Keep model names and provider parameters out of always-loaded guidance. They go stale.

## Maintenance

- Remove cautions whose cause is gone. After a model or harness change, check whether old warnings, reading-order hints, and reminders still change behaviour, and delete the ones that do not.
- Text produced from chats, traces, or optimization loops is a draft. It goes in through a reviewed diff like any other change.

## Measuring a change

- To claim that a prompt change alters behaviour, compare current and candidate on the same tasks, model, harness, tools, and budget, with the metric chosen beforehand.
- Outcomes vary between runs. Repeat enough to separate the effect from noise, and report the spread. One run is an anecdote.
- Keep a small set of known-good and known-bad cases for each maintained prompt or skill.
- Word counts, link counts, and successful parsing are not quality unless they are the property being claimed.
- A grade from the authoring agent, or agreement between model judges, is a signal to inspect. Calibrate a model-based judge against cases with known outcomes.
- When an agent optimizes against a metric, keep the tests, fixtures, and graders outside what it can write.
- Before making several agents, higher effort, or longer runs the default, compare with the simplest single-agent setup on quality, unrequested side effects, cost, and time.
- Vendor benchmarks and demos do not show behaviour in this harness with these tools.

Related skill: `mpa-agent-inputs` for untrusted content and tool protocols.
