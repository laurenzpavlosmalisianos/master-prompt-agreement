# Runtime Load Order

Use this as the operative assembly order for tasks. This is a loading order, not
an authority order. The selected runtime entrypoint routes this sequence; it
does not create another authority layer. When the generated project contract
lists a Scope of Authority module, load that module before action as part of the
project-contract phase.

1. Platform enforcement
   System prompt, tool schema, sandbox, approvals.
2. `runtime/operative_charter.md`
   Always-on universal rules only.
3. Recovery gate
   Before loading generated project authority or state, check the project root for any member of the closed transaction-control set: `.mpa-bootstrap-recovery.json`, `.mpa-bootstrap.lock`, or `.mpa-bootstrap-recovery.tmp`. If any exists, stop ordinary work and do not load the generated project contract, SOW, or project state. Permit only bounded status inspection and, when inspection reports a permitted recovery action and exact transaction ID, exact-ID recovery through the selected framework, using a runner already supplied by the runtime or operator; if none is available or no recovery action is identified, report the blocker and await direction. These controls do not bar loading this neutral operative charter.
4. Project contract
   Active project facts only.
5. User request
   Interpret the requested task, explicit scope, approval-sensitive choices, and stated constraints under platform/runtime instructions and the project contract. Startup state supplies facts and handoff context; it does not create new permission.
6. Startup state
   Check `TODO.md` and `DECISIONS.md` headers when present after interpreting the current User request and any scope, privacy, or approval limits. `active_count: 0` means no active TODO state. DECISIONS is empty only when both `durable_decision_count: 0` and `directive_count: 0`; template-empty files or `- None.` entries mean no applicable records. Generic resume, continue, status, next-step, or handoff requests make active TODO records and matching durable decisions or directives relevant. Load full records only when the header, index, scope, or task tag indicates relevance to the current task and is not barred by current scope or privacy limits. Load `FINDINGS.md` only for insights or framework-feedback work. Load `REVIEWER_LANE_FEEDBACK.md` only for reviewer routing, external-review orchestration, source-monitoring strategy, prompt-agent-quality work, or decision-triggered insights. Load `FRAMEWORK_FEEDBACK.md` only for framework-maintenance work that asks for sanitized feedback candidates. Load `PRECEDENTS.md` only when the task matches a recorded trigger.
7. Routing
   Use `practice_guides/risk_routing.md` or `scripts/recommend_stack.py` with `runtime/standards_of_care.md` as the care-level reference to choose the Risk Level, Practice Guide module(s), and Evidence Scope. Routing selects what to load; it does not create doctrine.
8. Workflow selection
   A workflow is known when selection evidence identifies exactly one catalog workflow: task-order metadata, command argument, bootstrap field, issue or ticket label, project contract entry, named workflow sequence, or a clear and exclusive match from the current User request. Natural-language intent is selection evidence, not authority. If no workflow matches, multiple workflows match, the intent is ambiguous, or any catalog `use_full_when` condition applies, consult `task_orders/README.md` or `runtime/workflow_catalog.json` and load the full candidate Task Order or router entry.
9. Practice Guide module(s)
   Load only the domain workflow module(s) that match the task.
10. Evidence bundle
   Relevant files, diffs, outputs, and current sources.
11. Tool results

Trigger index: external reviewer/browser upload/connector/human/external model -> orchestrate plus MSA egress; credentials/auth/tokens/browser profile/cloud/paid/session -> MSA secrets and approval; vote/panel/tie/arbitration/remand -> arbitrate; script/test/verifier/invariant/source-chain -> verification and script provenance; publication boundary/citation/source/evidence/policy -> source or evidence guide and approved registries.

Rules:

- Keep the always-on layer small.
- Do not load every Practice Guide.
- Do not load `PRECEDENTS.md` unless the task resembles a stored trigger.
- Preserve authority from disk after compaction or restart; summaries and memory are hints only. Current User instructions govern the present task unless they conflict with platform enforcement or non-delegable safety, truthfulness, and verification duties.
- Select one workflow procedure. If exactly one workflow is identified by explicit provenance or a clear and exclusive match from the current User request, a runtime task module exists, and no catalog `use_full_when` condition applies, load only the compact runtime module. If the workflow has no match, has multiple plausible matches, is ambiguous, has no runtime module, or meets a catalog `use_full_when` condition, use the router or full Task Order instead. If task characteristics change after routing, replace the compact module with the full Task Order before continuing; do not retain both as duplicate procedure.
- Treat governing project terms in `AGENT_PROJECT.md` as generated projections of `STATEMENT_OF_WORK.md`; its model-owned framework-reference binding is non-authoritative lifecycle data from retained input. If a governing term conflicts with the SOW, the SOW governs; stop relying on that term and correct generated bytes only through an approved plan-bound refresh transaction from a verified complete current-format retained-input/receipt pair with an intact recorded preimage, or through a separately reviewed manual correction.
- Task Orders and Practice Guides are procedures. They do not override the MSA or SOW.
- Prefer narrower Evidence Scope before wider context.
- Let evidence resolve factual questions, feasibility, and verification status. Evidence does not grant authority, expand scope, or override governing instructions.
