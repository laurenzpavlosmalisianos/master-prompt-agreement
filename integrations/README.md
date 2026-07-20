# Integration Layer

This directory contains optional native packaging for specific agent runtimes.

Source of truth:

- `runtime/` for always-on operative rules
- `task_orders/` for reusable workflows
- `practice_guides/` for specialized on-demand Practice Guides

The integration layer must stay thin. It exists for runtime-native packaging, not as a second source of truth.

Auxiliary integrations become runtime tools only when a runtime exposes or can invoke them. Runtime-native skills, hooks, permissions or extensions; direct APIs; remote or local CLIs; connectors; protocol bridges such as MCP when adopted; and equivalent mechanisms do not become canonical framework content. Record an approved integration in the SOW and project contract according to its capability, data, effect, persistence, permission, provenance, credential, trust, scope, approval, and control-role boundaries; the same rule applies regardless of product name or transport. When a hook, permission, wrapper, or other integration is claimed as a lifecycle guardrail or enforcement boundary, record demonstrated lifecycle coverage, uncovered or bypass paths, enforcement strength, and verification evidence.

## Recommended Installation Order

1. Direct file path
Use this when reliability matters more than convenience. For framework bootstrap, open `runtime/operative_charter.md` plus `task_orders/init.md`. For downstream project work, open `runtime/operative_charter.md`, then check the project root for `.mpa-bootstrap-recovery.json`, `.mpa-bootstrap.lock`, and `.mpa-bootstrap-recovery.tmp` before loading generated project authority or state. If all three are absent, open `AGENT_PROJECT.md`; check `TODO.md` and `DECISIONS.md` headers when present, and load full records only when the header, index, scope, task tag, or project contract indicates relevance. If any control exists, do not load the project contract, SOW, or state; use only bounded status inspection and exact-ID recovery when inspection identifies a permitted action, through a runner already supplied outside those surfaces. Then load the applicable Task Order or Practice Guide when ordinary work is permitted.

2. Project entrypoint integration
Use the `AGENTS.md` or `CLAUDE.md` installed by bootstrap when the repository
needs a default runtime entrypoint. Use separately rendered variants only for
inspection or approved native packaging.

3. Native skill or subagent integration
Use vendor-native wrappers only for workflows that are frequent enough to justify the extra packaging.

For Claude Code first-time setup, invoke the main session with `runtime/operative_charter.md` and `task_orders/init.md`. Do not use a `.claude/agents` wrapper for bootstrap unless a future native command package is added.

## Design Rules

- Do not duplicate methodology from `practice_guides/`.
- Integrations may add runtime-specific metadata, invocation hints, and scoping rules.
- Integrations should point to canonical files using rendered references. Use `--framework-ref` for shared or public output.
- Entry-point integrations must not import full Practice Guides into the always-on prompt.
- Runtime-native instruction surfaces should use the lowest-cost surface that preserves the needed authority, persistence, and enforcement strength: entrypoints for stable facts, path-scoped files or rules for local conventions, skills for reusable procedures, subagents for isolated side work, hooks or permissions only to their verified lifecycle coverage and enforcement strength, and invocation flags or output styles only for session posture.
- If workflow selection is unclear, entrypoints should point to `task_orders/README.md` rather than import every Task Order.
- Only the Operative Charter is always-on framework doctrine. Project entrypoints may also load the compact project contract required for project work.
- Charter-then-recovery-gate entrypoint ordering is a deterministic instruction-order contract, not a tool-enforced prelaunch gate. The neutral operative charter loads first; the gate then blocks generated project authority and state while recovery is unresolved. A runtime that eagerly expands project files must use explicit post-guard read instructions rather than eager imports. Native prelaunch enforcement is optional and may be claimed only for the lifecycle paths its integration has demonstrated.
- Do not add a native wrapper unless the Task Order or Practice Guide is used often enough to justify it.
- Use `runtime/operative_schedule.json` for Practice Guide wrapper candidates. A setup wrapper may route to `task_orders/init.md` when it stays thin and does not duplicate doctrine.
- Use only auxiliary integrations approved by the current User or SOW, and apply equivalent scrutiny whenever their capability, data, or effect boundary is equivalent. Official provenance or prior review informs the trust decision but does not grant access or action authority.
- For MCP specifically, restrict exposed tools and OAuth scopes to the minimum required set. Require approval for sensitive tool calls unless the current User or SOW grants that exact server, tool, action, scope, and effect. Prior review may support the grant, but does not create one.

## Rendering

Templates live under `integrations/templates/`.

Directories such as `integrations/templates/codex/skills/project-init/`, `integrations/templates/codex/skills/project-refresh/`, and `integrations/templates/codex/skills/seo/` are template packaging surfaces for optional runtime-native wrappers. They are not generated artifacts and they are not additional source-of-truth content. The canonical methodology remains in `task_orders/` or `practice_guides/`.

The current `SKILL.md` wrappers use the shared Agent Skills package shape, but they remain registered under the Codex family because this repository declares and tests their discovery/rendering behavior only for that family. The package shape is portable; cross-runtime support is claimed only after the corresponding runtime family, discovery path, and verification are added. No workflow doctrine is Codex-owned.

The integration families, entrypoints, and optional native wrapper paths are registered in `integrations/registry.json` so template updates do not require chasing hardcoded wrapper maps across multiple scripts. Validation budgets stay in `scripts/validate_framework.py`, not in the registry, so the registry remains declarative.

Framework scripts are stdlib-only. In the commands below, `<runner>` means the already-available framework runner reported by `scripts/check_prereqs.py`, such as `uv run python -B`, `python3 -B`, or `py -3 -B`. `<framework-checkout-as-visible-to-runner>` is the exact absolute framework checkout path inside that runner; a wrapper or container can resolve a different path from the host. Do not install `uv`, download Python, resolve dependencies, or create environments during integration rendering unless the user approves that state-changing setup step.

Render them with:

```bash
<runner> <framework-checkout-as-visible-to-runner>/scripts/render_integrations.py --integration all --output-dir <new-empty-output-dir> --framework-ref <stable-framework-reference>
```

Use a new or empty output directory for a clean render. The renderer validates
and snapshots every selected regular source, placeholder, target, and collision
before the first output write, then installs each complete file atomically. It
rejects symlink path components. Existing rendered targets require `--force`;
unrelated existing files are not pruned. Use
`--framework-ref <stable-framework-reference>` for output that may be committed,
shared, or published; omit it only for local inspection artifacts that will not
leave the machine.

Options:

- `--integration codex`
- `--integration claude-code`
- `--integration generic`
- `--integration all`
- `--output-dir <new-empty-output-dir>`
- `--framework-root /absolute/path/to/framework`
- `--framework-ref <reference resolved from the downstream project root>`
- `--contract-root <directory relative to the downstream project root; default .>`
- `--force`

`--framework-root` is the framework root used for resolving template files and as the default project-root-based framework reference. The renderer writes concrete files to the output directory. Use `--framework-ref` when rendered files will be committed to a shared or public repository, and supply it exactly as the downstream project root resolves it. Root entrypoints retain that reference; nested Codex `SKILL.md` outputs rebase relative framework and project-file references from each skill directory. Do not pre-rebase them. Absolute, home-relative, and environment-based framework references remain anchored. Use `--contract-root` when the project contract and optional surfaces live in a nested project directory; it is always specified relative to the downstream project root.

## Using Rendered Outputs

Separately rendered outputs are optional review and native-packaging artifacts.
Normal project setup uses `task_orders/init.md` and the framework runner
confirmed by `scripts/check_prereqs.py` to invoke
`scripts/project_bootstrap.py`, which installs the selected project entrypoint
directly. Do not hand-copy a separately rendered entrypoint as a substitute for
bootstrap or refresh.

Codex:

- Generated entrypoint: `codex/AGENTS.md`
- Generated optional skills: `codex/.agents/skills/<name>/SKILL.md`
- Bootstrap installs the selected Codex entrypoint as the downstream repository
  `AGENTS.md`; the separately rendered `codex/AGENTS.md` is for inspection or
  approved native packaging.
- Install optional skills only in a Codex-scanned skill location when the workflow is frequent enough to justify native discovery. The canonical workflow remains in `task_orders/` or `practice_guides/`.
- Invoke the `master-prompt-new-project` skill rendered from the `project-init` folder as `$master-prompt-new-project`. Do not create a second setup specification in a custom prompt or hook.
- Use the `master-prompt-refresh-project` skill rendered from the `project-refresh` folder to inspect and classify an existing generated instance. A verified complete current-format identity pair with an intact recorded preimage is required for refresh planning or contract revision, and successful apply must reach exact-current acceptance. The exact plan selects either the normal verified-bundle basis or, only where permitted, the explicit `ACCEPT-NO-POST-APPLY-BACKOUT` basis; mutable-state retirement and post-success restore are available only on the bundle branch. Closed transaction-control evidence independently governs exact-ID recovery before authority loading. The skill routes to `UPDATING.md` and `task_orders/framework_refresh.md`, never to `task_orders/init.md`; it is not a second lifecycle specification.
- The refresh wrapper is optional. The project entrypoint plus the canonical update guide and Task Order remain sufficient when no runtime-native wrapper is installed.

Claude Code:

- Generated entrypoint: `claude-code/CLAUDE.md`
- Generated optional agents: `claude-code/.claude/agents/`
- Bootstrap installs the selected Claude Code entrypoint as the downstream
  `CLAUDE.md`. Use separately rendered optional agents or hooks only when the
  project explicitly needs Claude-native packaging.

Generic filesystem-capable agents:

- Generated entrypoint: `generic/AGENTS.md`
- Bootstrap installs the generic entrypoint when the runtime reads a repository
  instruction file but has no dedicated integration family.
- For agents that do not auto-load repository instruction files, use this manual load card: read `<framework-ref>/runtime/operative_charter.md`; check the project root for `.mpa-bootstrap-recovery.json`, `.mpa-bootstrap.lock`, and `.mpa-bootstrap-recovery.tmp`; only when all three are absent, read the downstream `AGENT_PROJECT.md` and any configured Scope of Authority, load the selected Task Order, inspect the target project, run `<framework-ref>/scripts/check_prereqs.py` with an already-available stdlib-capable Python command, and use its reported runner for framework scripts. When any control exists, do not read generated project authority or state; use an externally supplied runner for bounded status inspection and exact-ID recovery only when inspection identifies a permitted action, or stop and request direction.
  From the project root, run `<runner> <framework-ref>/scripts/conformance_check.py --profile core-project --root <project-root> --project-kind <downstream|framework-authoring> --contract-root <contract-root> --strict-warnings` as the routine verification gate. Root `PROJECT_INSTANCE.json` identifies the project lifecycle instance; substitute its recorded project kind and contract root rather than treating the receipt as nested. `<contract-root>` is `.` for an ordinary downstream layout.
  Use `<runner> <framework-ref>/scripts/project_contract_sync.py <project-root> --project-kind <downstream|framework-authoring> --contract-root <contract-root>` only for focused diagnosis.

## Validation

Run:

```bash
<runner> <framework-checkout-as-visible-to-runner>/scripts/validate_framework.py
```

This checks configured file-size ceilings and required integration files. Those
ceilings are structural guardrails only; passing them does not measure tokens,
prompt or context cost, prompt bloat, compactness, or output quality.

Check reference freshness with:

```bash
<runner> <framework-checkout-as-visible-to-runner>/scripts/check_reference_freshness.py
```

This checks source-maintenance Markdown in the current authoring tree and a downstream root `SOURCE_PACKS.md` when one exists. Bracketed date fields in exact release-manifest-declared files under `project_state_templates/` are uninstantiated blueprint syntax, not source-state claims; the same placeholder in copied or rendered project state remains a warning and fails `--warnings-as-errors`. In a freshly exported public framework checkout with no project source pack yet, the command can pass with no source-pack files inspected; use `--reference-dir` or create project `SOURCE_PACKS.md` when a concrete source registry must be checked.
