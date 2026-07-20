# AGENTS.md — master_prompt_agreement

<repository-role>
This checkout authors the Master Prompt Agreement framework. Treat this root `AGENTS.md` as framework-maintenance instructions only.
Do not copy this root file into downstream projects. For a target project, use `GETTING_STARTED.md` and `task_orders/init.md` so the bootstrap script renders the target-local runtime entrypoint.
</repository-role>

<framework-rules>
Read `runtime/operative_charter.md` before acting. It is the always-on operative charter.
<!-- mpa-entrypoint-contract: entrypoint-recovery-guard-v2 -->
After loading the operative charter and before loading `AGENT_PROJECT.md`, `STATEMENT_OF_WORK.md`, or project state, check for any member of the closed transaction-control set in the project root (the directory containing this entrypoint): `.mpa-bootstrap-recovery.json`, `.mpa-bootstrap.lock`, or `.mpa-bootstrap-recovery.tmp`. If any exists, stop ordinary project work and do not load generated project authority or state. Permit only bounded read-only recovery-status inspection through the selected framework's `scripts/project_refresh.py inspect` route and, only when that inspection reports a permitted recovery action and exact transaction ID, recovery through its `recover --action rollback|finalize --approve-transaction-id <transaction-id>` route. Invoke those routes only through a runner already supplied by the runtime or operator without reading generated project authority; if no such runner is available or inspection does not identify a permitted recovery action, report the recovery blocker and await direction. Do not edit or delete any transaction-control artifact manually.
Consult `master_service_agreement.md` only when interpreting the canonical rule text, resolving ambiguity, or revising the framework itself.
This root `AGENTS.md` is the neutral repository-maintenance entrypoint, and `runtime/operative_charter.md` supplies the compact always-on rule layer.
If `private/authoring/AGENT_PROJECT.md` exists, load it after the operative charter as the concrete authoring-project runtime layer and resolve its project-state references against `private/authoring/`.
Consult `private/authoring/STATEMENT_OF_WORK.md` only for authoring-project ambiguity. Revise the concrete authoring contract through the retained-source procedure in `private/authoring/README.md`, not by hand-editing rendered contract files. If the private authoring instance is absent, continue under this generic maintainer contract.
</framework-rules>

<repo-scope>
This repository authors the framework itself. Keep the public core product surface limited to doctrine, templates, runtime files, practice guides, task orders, integrations, and deterministic support for setup, validation, routing, source workflows, automation, conformance, and publication. Public orientation and support surfaces include the repository entrypoint, README, getting-started and architecture docs, annexes, examples, assets, tests, license, and notice files.
</repo-scope>

<template-discipline>
Tracked public or downstream templates and this `AGENTS.md` are framework product surfaces. Update them when generic, source-backed framework improvements require it.
Do not write local maintenance notes, chat-derived context, or repository-local working state into public templates or public docs. Keep downstream template files clean and generic.
</template-discipline>

<maintenance-boundary>
Tracked non-public authoring records are reviewable repository surfaces, not public product files or downstream templates; the release selector owns their exact path classification.
Ignored local maintenance records may exist beside the framework. Treat them as private workspace state, not doctrine, not downstream templates, and not part of the framework product surface. Do not reference local maintenance state in framework product files unless the task explicitly revises that boundary.
</maintenance-boundary>
