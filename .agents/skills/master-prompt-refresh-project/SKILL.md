---
name: master-prompt-refresh-project
description: Use when a user wants to inspect or classify an existing generated Master Prompt Agreement instance, update, refresh, or revise a verified complete current-format instance, recover an interrupted transaction from its closed control state, or restore an approved plan-bound preimage. Thin wrapper over task_orders/framework_refresh.md. Do not use for first-time project setup; use master-prompt-new-project instead.
---

# Master Prompt Agreement Project Refresh

1. Read `../../../runtime/operative_charter.md` from the explicitly selected framework checkout.
2. After loading the charter and before loading generated project authority or state, resolve the target project root without opening generated authority and check for `<project-root>/.mpa-bootstrap-recovery.json`, `<project-root>/.mpa-bootstrap.lock`, and `<project-root>/.mpa-bootstrap-recovery.tmp`. If any exists, stop ordinary work and permit only bounded read-only recovery-status inspection through `../../../scripts/project_refresh.py inspect` and, only when inspection reports a permitted recovery action and exact transaction ID, recovery through `recover --action rollback|finalize --approve-transaction-id <transaction-id>`, using a runner already supplied by the runtime or operator without reading generated project authority. If no such runner is available or inspection identifies no permitted recovery action, report the blocker and await direction; do not edit or delete a transaction-control artifact manually.
3. Read `../../../task_orders/framework_refresh.md` and follow it as the workflow source of truth. This skill grants no additional authority or procedure.
4. Consult `../../../UPDATING.md` only when the User asks for update explanation, manual command guidance, or troubleshooting; it is informative orientation, not the workflow owner.
5. Use this skill only for an existing generated instance. First current-format setup uses `master-prompt-new-project`; unsupported existing state follows the Task Order's reviewed manual or supporting-checkout route.
