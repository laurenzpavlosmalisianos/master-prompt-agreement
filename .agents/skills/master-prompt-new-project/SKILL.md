---
name: master-prompt-new-project
description: Use when a user wants to apply the Master Prompt Agreement framework to a new project or an existing repository with no framework-generated surfaces and no selected managed-output collision, invokes $master-prompt-new-project, says new project, bootstraps project files, renders Codex/Claude/generic runtime entrypoints, or asks to set up Master Prompt Agreement in a repository. Thin wrapper over GETTING_STARTED.md and task_orders/init.md.
---

# Master Prompt Agreement Project Init

1. Read `../../../runtime/operative_charter.md`.
2. Read `../../../GETTING_STARTED.md`.
3. Read `../../../task_orders/init.md`.
4. Follow `../../../task_orders/init.md` exactly as the setup source of truth. Do not add setup doctrine, project facts, or methodology to this skill.
5. Use this skill only to route `$master-prompt-new-project` or equivalent Codex setup requests.
6. Do not implement setup through hooks. Hooks are for separately approved lifecycle controls whose coverage and enforcement strength have been verified after an approved setup path exists.
7. For public or shared downstream output, follow the stable framework-reference rule in `../../../task_orders/init.md` and `../../../GETTING_STARTED.md`.

Do not copy the source package root `AGENTS.md` or `CLAUDE.md` into a downstream project. Bootstrap renders downstream state files from `project_state_templates/` and runtime entrypoints from `integrations/templates/`.
