Task Order — Compliance Check

Objective

Independently audit whether an established project's framework setup remains
complete, consistent, and functional after time, milestones, or suspected drift.

Procedure

Let `<project-root>` be the selected project root, `<contract-root>` the
selected generated-contract root, and `<framework-ref>` the exact selected
framework checkout path as visible inside `<runner>`. The project and contract
roots are the same directory for an ordinary downstream project and may differ
only for a conformance layout that explicitly defines the separation.

1. File Presence
Verify root `PROJECT_INSTANCE.json`, derive its recorded `contract_root`, and
require that it matches the selected `<contract-root>`. Verify
`PROJECT_INPUT.json`, `STATEMENT_OF_WORK.md`, and `AGENT_PROJECT.md` in that
contract root, and verify the active runtime entrypoint file (`AGENTS.md`,
`CLAUDE.md`, or runtime-specific equivalent) at the location selected by the
conformance layout under `<project-root>`. A formal `core-project` conformance
claim requires the current generated contract shape, including `TODO.md` and
`DECISIONS.md` in `<contract-root>` even when their record counts are zero. A
non-generated or intentionally pruned setup may receive a bounded manual review:
inspect `TODO.md` when active handoff state exists or the project contract
requires it, inspect `DECISIONS.md` when durable decisions, directives,
overrides, amendments, or project-contract requirements exist, and confirm that
absent state is not stranded elsewhere. Missing required generated surfaces
makes that setup ineligible for `core-project` conformance; record the
limitation and do not describe the manual review as complete framework setup or
conformance. If `PRECEDENTS.md` or `FINDINGS.md` exist, verify that their use
matches the project's actual needs. If `AUTOMATION_ORDERS.json` exists, verify
that it matches the project's actual automation needs.

2. Runtime Contract Completeness
Read `AGENT_PROJECT.md` and verify:
- No placeholder prose remains.
- Commands, active constraints, decision-authority grant, deliverables, VCS profile entries, and registered auxiliary tools reflect the current project. If `Bootstrap Mode: minimal` is explicit and concrete commands, stack facts, deliverables, or acceptance evidence are intentionally deferred, each deferral must name the canonical field, owner, reason, boundary type (`date`, `milestone`, or `event`), and exact closure boundary. Classify those omissions as accepted deferrals or verification limitations only until the recorded boundary passes; after that, fail the completeness check.
- `Framework Verification Commands` names the framework reference, runs from `<project-root>`, and calls the framework-owned core conformance script through that reference. Bare project-local `scripts/...` paths for this framework check are a setup defect. Standalone contract-sync and state-lint commands are diagnostic tools, not additional routine gates.
- The file stays compact and factual rather than duplicating the full SOW.

3. SOW Completeness
Read `STATEMENT_OF_WORK.md` and verify:
- No unfilled placeholders such as `[e.g., ...]` or `[YYYY-MM-DD]`. A required fact that is not concrete must use its canonical structured deferral with matching field, owner, reason, boundary type, and an unexpired date, milestone, or event closure boundary; a bare `TBD`, including for Recitals/project purpose, fails completeness.
- Definitions table has values for Agent, User, Execution Mode, Decision Boundary, and Test Command, unless Test Command is an explicit minimal-mode deferral with owner, reason, boundary type, and unexpired closure boundary.
- Secret Store and Credential Delivery are specified when the project uses credentials, MCP authentication, external APIs, deploys, or private package registries.
- At least one deliverable with Acceptance Evidence, unless the explicit minimal bootstrap profile intentionally defers deliverables.
- Build commands section filled, unless the explicit minimal bootstrap profile intentionally defers commands.
- If auxiliary integrations are listed, each one has purpose, canonical docs or provenance, owner, transport, capability or permissions, credential disposition, data boundary, effect boundary, persistence, trust, approval and scope dispositions, and control role recorded. A lifecycle guardrail or enforcement-boundary claim also has demonstrated lifecycle coverage, uncovered or bypass paths, enforcement strength, and verification evidence.
- If the project uses Git, another VCS, hosted forge, protected branches, PR workflow, release branches, or non-default staging or commit policy, the Version Control Profile records the active facts or explicitly justifies omission.

4. Runtime Split Integrity
Run `<framework-ref>/scripts/check_prereqs.py` with the approved Python runner
if `<runner>` is not already recorded for this project. Use the reported
`<runner>` command for stdlib-only framework scripts. For a wrapper or
container, require `<framework-ref>` to resolve inside that runner rather than
assuming the host checkout path. For a current generated contract with every
required surface, run the explicit layout command:

`<runner> -- "<framework-ref>/scripts/conformance_check.py" --profile core-project --root <project-root> --project-kind downstream --contract-root <contract-root> --strict-warnings`

Bootstrap `--approve-write-plan-sha256` and refresh-plan `--approve-warning`
authorize only their exact lifecycle writes; neither waives this independent strict gate. Any
warning makes the strict compliance result non-passing. A separately requested
non-strict run may be retained only as bounded diagnostic evidence and must not
be described as warning-free or as satisfying this acceptance criterion. The
core-project aggregate includes required-surface preflight, project-contract
synchronization, and project-state lint. Run `scripts/project_contract_sync.py`
or `scripts/project_state_lint.py` separately only for focused diagnosis; do not
count a repeated child run as independent conformance evidence. For a
non-generated or intentionally pruned setup that lacks a required surface, run
only applicable focused diagnostics as bounded evidence, explicitly report that
`core-project` conformance was not established, and do not treat those
diagnostics or manual review as a substitute for the aggregate profile.
Verify that the runtime entrypoint loads `AGENT_PROJECT.md` and consults `STATEMENT_OF_WORK.md` only as the full SOW fallback. Verify that key commands and active constraints agree between `AGENT_PROJECT.md` and `STATEMENT_OF_WORK.md`.
Verify that the runtime entrypoint stays thin. Project-specific operating rules should normally live in `AGENT_PROJECT.md` or `DECISIONS.md`, not as extra always-on entrypoint blocks.
If prompt-loaded runtime or template surfaces have accumulated duplicated rules, stale rationale, completed milestones, or project-specific examples, flag them as pruning or relocation candidates. Do not remove them during compliance unless the User separately approves that edit.

At a milestone, classify each prompt-loaded fact by owner before proposing consolidation. Keep non-derivable scope, authority, approval, privacy, external commitments, critical invariants, and Manual Acceptance Items in the SOW, and project the task-relevant subset into the compact project contract. Use code, configuration, types, and schemas for current implementation structure and mechanics. Use governing project requirements or project-adopted domain specifications as intended-behavior authority, and use meaningful tests as executable verification. Prefer formatter, linter, compiler, package, and task configuration for enforceable mechanics. The compact contract may retain the stable invocation and environment or approval boundary without duplicating the underlying recipe. Do not treat existing code or a passing test as intended truth merely because it exists. Propose retiring duplicate prose only when the replacement owner exists, remains discoverable from the normal runtime route, agrees with the governing requirement, and passes relevant verification; required rationale, owner, evidence, and amendment history must remain retained, and any consolidation that changes behavior or authority routing must have a proportionate backout path. Run count and elapsed time are not retirement evidence.

5. Command Verification
Run each command defined in `AGENT_PROJECT.md` for test, lint, type check, and build. If a command exists only in `STATEMENT_OF_WORK.md`, flag runtime drift and use the SOW value as fallback for the check. Report pass/fail/not configured.
If the project records an editor, IDE, language server, or local companion CLI as an approved auxiliary tool, use its diagnostics only as supplemental evidence unless the project contract names it as the type, lint, or build command. Record the exact invocation, configuration file, toolchain, and version when using language-server diagnostics.

If `AUTOMATION_ORDERS.json` exists:
- let `<manifest>` be the selected `AUTOMATION_ORDERS.json`, including a nested contract-root manifest when applicable
- from `<project-root>`, resolve `<framework-ref>`, `<manifest>`, and `<project-root>`, then run `<runner> -- "<framework-ref>/scripts/automation_orders_lint.py" <manifest> --project-root <project-root>`
- read the manifest's top-level `preferred_backend`; if it is `unspecified`, report that no backend-specific render is selected, and never infer one from prose
- if `preferred_backend` is `cron`, run `<runner> -- "<framework-ref>/scripts/automation_orders_lint.py" <manifest> --project-root <project-root> --target cron` before rendering
- if `preferred_backend` is `cron`, cron rendering was requested, and target lint passes, render the schedule to an approved temporary location with `<runner> -- "<framework-ref>/scripts/render_cron.py" <manifest> --project-root <project-root> --output <temporary-cron-file>`; use an out-of-root temporary path only when the project or runtime boundary authorizes it. Report whether the manifest and rendered schedule agree. Writing or overwriting a project scheduler artifact is remediation and requires separate authorization.
- if `preferred_backend` names another backend, use only its supported target checker/renderer; report unsupported backend integration instead of silently falling back to cron

6. State Freshness
Review TODO.md when it exists or is required by active handoff state:
- Completed items not cleared.
- Closed decisions, resolved disputes, or historical notes that should live in DECISIONS.md instead.
- Blockers without resolution across 3+ sessions.
- State that contradicts the actual codebase.

Review DECISIONS.md when it exists or is required by durable decisions, directives, overrides, amendments, or project-contract policy:
- Durable decisions missing for standing decisions, overrides, or architectural commitments.
- Decisions that no longer match the codebase, `AGENT_PROJECT.md`, or `STATEMENT_OF_WORK.md`.
- Superseded decisions that were never consolidated.

7. MSA Version Check
Compare `STATEMENT_OF_WORK.md`'s MSA reference version to the actual `master_service_agreement.md` version. Flag mismatch.

8. Link Integrity
If the framework `scripts/link_check.py` utility is available, run `<runner> -- "<framework-ref>/scripts/link_check.py" --root <project-root>` against project Markdown documentation. Use offline local-link checking by default. Never select a same-named project-local script as the framework validator.

For external references and source packs, do not treat generic URL probing as sufficient source validation. Load `practice_guides/source_freshness_review.md`, confirm the SOW or runtime project contract acquisition boundary, and use the approved source-validation method such as `curl`, browser automation, an approved local fetch tool, an approved MCP server, or user-supplied material. Record the method, status, date, and access limits. Check external URLs only when the project task explicitly requires network validation or source freshness.

9. Report results: for each check, report check name, status (pass/fail), and details. Add actionable items to TODO.md only when remediation or state-file maintenance is in scope; otherwise report TODO candidates.
Report pruning or relocation candidates separately from defects. Include the affected file or section, the evidence, the proposed action, and the approval needed.

Acceptance Criteria

- Every applicable check was run and reported, and unavailable checks were
  identified with the reason they were unavailable.
- A formal `core-project` claim passed its aggregate profile; a bounded manual
  review was clearly reported as non-conformance evidence only.
- Actionable items are added to TODO.md when state-file maintenance is in scope; otherwise TODO candidates are reported.
- Pruning and relocation candidates are reported as proposals, not silently applied.

Notes

- Initialization and refresh own their immediate receipt-listed acceptance
  checks. Do not invoke this order immediately merely to repeat them.
- Run independently later, such as after a milestone, when resuming a dormant
  project, or when evidence suggests framework drift.
- A failing MSA version check means `STATEMENT_OF_WORK.md` was written against older MSA text. Review the current MSA for operative changes before updating the reference.
