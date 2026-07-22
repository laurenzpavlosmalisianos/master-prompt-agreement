# Getting Started

Use this file when you have just downloaded the framework and want an agent to set up a downstream project.

## Product And Target Entrypoints

The root `AGENTS.md` guides an agent that is using this framework distribution.
Do not copy it into a downstream project. Follow `task_orders/init.md` so the
framework renders the governing contract from the declarative model and its
`statement_of_work_template.md` and `runtime/project_template.md` projections,
receipt-declared state from `project_state_templates/`, and a target-local
entrypoint or selected wrapper from `integrations/templates/`.

The root `CLAUDE.md` is a Claude Code wrapper for the same product guidance; do
not copy it into a target either. Generated downstream files may use the same
names, but they contain target-specific authority and framework references.

## Requirements

Core lifecycle scripts require Python 3.14 or newer and the POSIX transaction
primitives reported by `scripts/check_prereqs.py`, including descriptor-relative
no-follow file access, advisory locking, and directory-safe synchronization.
Support is capability-based: use only an environment where the prerequisite
report exits successfully and sets `runner_usable` to `true`, then qualify the
first bounded lifecycle transaction on the selected project filesystem.

Native Windows is not currently a supported environment for bootstrap or
refresh transactions. A POSIX container or comparable approved POSIX
environment may be used. The `py -3 -E -S -B` spelling is only a candidate
diagnostic runner; its presence does not establish native Windows support, and
it is usable only when the same prerequisite report confirms every required
capability.

## Launch With Both Directories

The setup agent must be able to read this framework checkout and inspect or write the target project. Prefer a runtime launch that grants both roots explicitly instead of broad host access.

Codex CLI:

```bash
codex --cd /abs/path/to/framework-checkout --add-dir /abs/path/to/project
```

Codex app:

Open a workspace that includes this framework checkout and the target project, or add the target project as an approved writable root before asking the agent to run setup.

Claude Code:

```bash
cd /abs/path/to/project
claude --add-dir /abs/path/to/framework-checkout
```

Other filesystem-capable agents:

Give the agent explicit read access to this framework checkout and explicit write access to the target project. Do not use global filesystem access merely to bypass missing workspace roots.

## Runtime Choice

| Target runtime | Bootstrap value | Generated entrypoint |
|---|---|---|
| Codex | `codex` | `AGENTS.md` |
| Claude Code | `claude-code` | `CLAUDE.md` |
| Other filesystem-capable agent | `generic` | `AGENTS.md` |

## Fast Path

Open this repository and an existing target-project root in a
filesystem-capable agent, then use one of these prompts. Bootstrap does not
create the governed project root. If that directory does not yet exist, create
and approve it as a separate environment action before starting this workflow.
Bootstrap also requires every selected managed output path to be unoccupied.
An ordinary same-name file such as `AGENTS.md`, `CLAUDE.md`, `TODO.md`,
`DECISIONS.md`, or root `PROJECT_INSTANCE.json` is preserved and blocks any plan
that would overwrite it; route that collision to reviewed project-specific
integration or select a non-colliding layout before bootstrap. Replace the
three angle-bracket values below with the selected paths and runtime from the
table above:

```text
Read <framework-checkout>/runtime/operative_charter.md and <framework-checkout>/task_orders/init.md, then set up <project-root> using runtime <codex|claude-code|generic>. Follow the Task Order exactly: inspect the target; preserve any collision; ask only for missing project facts; qualify the intended runner; confirm a live or pinned framework reference and a fresh-checkout-stable reference for any generated files that may be shared; build temporary retained input from the minimal example and only the relevant schema definitions; render and explain the exact dry-run plan; and stop for the required digest and warning approvals before any write. Do not place a maintainer's personal checkout path in shared output.
```

## What Setup Creates

Default setup creates:

- `STATEMENT_OF_WORK.md`
- `AGENT_PROJECT.md`
- `AGENTS.md` for Codex or generic agents, or `CLAUDE.md` for Claude Code
- `TODO.md`
- `DECISIONS.md`
- `PROJECT_INPUT.json`, the retained fully materialized regeneration source
- project-root `PROJECT_INSTANCE.json`, the single current generated-instance
  receipt

Retained input can contain concrete project paths, commands, and other private
facts. Do not store secrets in it. Minimize unnecessary sensitive material while
retaining required project facts, and review the retained file before tracking,
sharing, or publishing the downstream repository; use approved indirection for
sensitive values. Ignore rules in the framework checkout do not sanitize a
downstream repository. The instance receipt uses
the retained contract effective date and does not accumulate refresh timestamps
or history. Its `contract_root` field locates the retained input, authority, and
state when an explicitly selected layout keeps those surfaces in a nested
directory.

Optional files such as `FINDINGS.md`, `REVIEWER_LANE_FEEDBACK.md`, `FRAMEWORK_FEEDBACK.md`, `PRECEDENTS.md`, `SOURCE_PACKS.md`, `SOURCE_UPDATE.md`, `SOURCE_MONITOR_RESEARCHER.md`, `SECURITY_VERIFICATION.md`, and `AUTOMATION_ORDERS.json` are selected during initial setup or a later approved candidate-input refresh only when the project needs them. The source-monitor brief is generated immutable procedure from retained configuration; the other listed optional surfaces are retained mutable state. Procedures may update a receipt-declared mutable surface while preserving its origin marker, but project-specific monitor additions belong in the declared source/state/overlay owners rather than edits to the generated brief. Do not create, copy, rename, or delete an optional generated surface ad hoc. A candidate-disabled optional surface is retired only through the exact plan-bound `RETIRE-IMMUTABLE-####` or `RETIRE-MUTABLE-####` action matching its receipt partition, a path-specific warning, and the applicable verified exact-preimage controls.

After setup, route source monitoring, retained research, reviewer feedback, and
reusable improvement candidates through [Source And Feedback](docs/source_and_feedback.md).
Those optional workflows are not part of the initialization packet unless the
project selects them.

## Detailed Procedure

`<framework-checkout-on-diagnostic-host>` is the exact framework path in the
environment that launches `scripts/check_prereqs.py`. `<runner>` means the exact
tested interpreter reported by its no-error result with `runner_usable: true`,
plus an unchanged container or `uv` prefix only when that exact boundary invoked
the successful diagnostic. A wrapper-prefixed runner can use a different
working directory or mount namespace, so
`<framework-checkout-as-visible-to-runner>` is the exact framework path that the
selected runner can resolve. Use that path for every framework-owned script;
do not assume bare `scripts/...` resolves from the runner's working directory.
`<contract-root-ref>` is `.` for the default project-root layout or the selected
safe project-relative nested contract directory. Omit
`<contract-root-create-flag>` when that directory exists; otherwise it is
exactly `--create-contract-root` when creation of the reviewed nested directory
is authorized. Preserve both values unchanged between dry run and write.

Choose the framework reference deliberately and require
`--framework-revision-policy <live|pinned>` in both the dry-run and approved
write command. If generated files may be committed, shared, or published, also
require `--framework-ref <stable-framework-reference>`.

If you maintain a reusable bootstrap profile, pass it only after reviewing it as
setup input. The profile fills absent reusable fields; confirmed project answers
replace profile fields atomically. Keep identity, scope, stack, architecture,
commands, deliverables, and project paths in the project answers. Use the same
`--setup-profile <profile-json>` in the dry run and approved write command, and review
the applied/overridden field report before writing.
Start from `examples/project_bootstrap_profile.example.json` when you need the
neutral profile shape. Do not add project facts to that reusable profile.

Resolve every framework script through
`<framework-checkout-as-visible-to-runner>` inside the retained execution
boundary; no framework-root working directory is implied. Use an answers file
in a temporary location outside the framework and target roots. Do not run
`project_bootstrap.py` until `task_orders/init.md` has produced a valid
temporary answers JSON. For manual preparation, copy the minimal
`examples/project_bootstrap_answers.example.json` to a temporary path, consult
only the relevant definitions in `examples/project_bootstrap_answers.schema.json`
for the selected fields and optional modules, and replace every placeholder
before the dry run. The full schema is compiler input, not a mandatory prompt
import; semantically review the actual rendered dry-run outputs. Manual
preparation still uses bootstrap and the generated receipt; it is not permission
to hand-copy or prune generated outputs.

A minimal command sequence has two stages. First, use one already-available
stdlib-capable runner to inspect prerequisites. For example:

```bash
python3 -E -S -B -- "<framework-checkout-on-diagnostic-host>/scripts/check_prereqs.py"
```

`python3 -E -S -B`, `py -3 -E -S -B`, and `uv run python -E -S -B` are
candidate invocation spellings, not evidence merely because their executables
exist. `-E` ignores `PYTHON*` environment configuration, `-S` suppresses
automatic `site`, `.pth`, and startup-customization loading, and `-B` prevents
bytecode writes. Prefer to run the diagnostic through the exact intended Linux
container and `uv` prefix when that approved boundary already exists. Choose one
available form; do not install or initialize a runner merely to perform
prerequisite discovery.

Continue only when `check_prereqs.py` exits zero and reports
`runner_usable: true`. Copy its exact tested interpreter into the answers file as
`framework_verification_runner` and use that runner for bootstrap. If the
successful diagnostic was deliberately invoked through a stable container,
environment wrapper, or `uv run python -E -S -B`, record that exact invocation prefix
instead of substituting a merely discovered alternate launcher. A reusable setup profile must
not provide this environment capability. The value prefixes framework-owned
Python scripts only. Bootstrap validates it, records it in the SOW, and projects
it into the runtime contract; later agents must stop instead of silently
replacing it when it is unavailable.
The accepted direct and bounded `exec`-wrapper forms are defined under bootstrap
in [`scripts/README.md`](scripts/README.md); do not record a shell, evaluator, or
unvalidated opaque wrapper as the runner.

Then use that exact retained runner for the dry run and pass the confirmed
revision policy explicitly:

```bash
<runner> -- "<framework-checkout-as-visible-to-runner>/scripts/project_bootstrap.py" --dry-run --answers <temporary-answers-json> --project-root /abs/path/to/project --contract-root <contract-root-ref> <contract-root-create-flag> --runtime <codex|claude-code|generic> --framework-revision-policy <live|pinned>
```

Stop after the dry run. Review the resolved target and contract root, exact input and optional-profile digests, runtime and wrappers, framework reference, revision policy and captured identity, ordered warnings and informational `warnings_sha256`, planned outputs, rendered-output digests, and `write_plan_sha256`. Continue only by rerunning the same bootstrap command without `--dry-run`, preserving the reviewed arguments and adding `--approve-write-plan-sha256 <reviewed-write-plan-sha256>`. This option is required for every write, including a plan with no warnings. Its domain-separated digest binds the complete rendered plan; any input, profile, target, warning, framework, runtime, wrapper, or output change requires a new dry run and review. Missing, malformed, stale, or repeated approvals fail before the writer is called. Plan approval does not approve conformance warnings or relax the strict initial acceptance performed inside the write transaction.

Use `uv run python -E -S -B` only when it actually invoked the successful prerequisite diagnostic in the approved environment. Otherwise retain the exact tested interpreter and flags reported by that diagnostic; do not replace them with a discovered `uv`, `python3`, or `py` spelling. `py -3 -E -S -B` is not a native-Windows support claim. Do not install `uv`, download Python, resolve dependencies, or create environments during bootstrap unless the user approves that state-changing setup step. Record the project-specific command form in the SOW.

The agent should write `<temporary-answers-json>` as a temporary file, never
put secret values in it, review the complete dry-run plan and its
`write_plan_sha256` with the user, fix warnings when possible, and rerun without
`--dry-run` only with
`--approve-write-plan-sha256 <reviewed-write-plan-sha256>`. If
the target project root does not exist, stop
bootstrap; create and approve that root through a separate environment action,
then restart the dry run against the existing directory.

Bootstrap creates a first current-format instance only when the target has no
framework-generated surfaces and every selected managed output path is free.
An unmarked ordinary same-name file is not a generated surface, but bootstrap
still preserves it and rejects a plan that would collide with it. Select a
reviewed non-colliding layout or integrate/relocate the ordinary file through a
separate project-specific change; do not overwrite it. A nested contract root
can move only the surfaces assigned to that layout, while root
`PROJECT_INSTANCE.json` remains root-scoped. If the target already has a
complete current-format instance, stop and follow [UPDATING.md](UPDATING.md) and
`task_orders/framework_refresh.md`. If framework surfaces are partial,
malformed, inconsistent, older, or unrecognized, fail closed and prepare a
separately reviewed manual project update; a clearly newer schema requires a
supporting newer framework checkout. Do not use bootstrap rerender or state
reset as an update path. If any of
`.mpa-bootstrap-recovery.json`, `.mpa-bootstrap.lock`, or
`.mpa-bootstrap-recovery.tmp` exists at the project root, stop before loading
generated project authority and follow the inspection-gated exact-ID recovery
route.

Framework-rendered mutable and optional project-state files carry a closed
origin marker. Current-instance validation requires that marker, and bounded
bootstrap discovery uses it to reject state-only residue outside the newly
requested output graph without reserving safely inspectable generic state
filenames. A singly linked regular same-name file within the byte bound and
without the marker remains ordinary; type, hard-link, size, race, read, or
marker-identity inspection failures make discovery fail closed. On a
receipt-listed current instance, a missing, late, or malformed marker is an
unrecognized existing format and routes to reviewed manual project update;
bootstrap does not infer markerless state-only residue or repair markers.

If the downstream project files will be committed to a shared or public repository, avoid writing a personal absolute framework path into the runtime entrypoint. Use `--framework-ref` with a stable project reference that the generated entrypoint can resolve from a fresh downstream checkout, such as a vendored, submodule, or relative framework reference. Use environment variables or shared mounts only for private or team repositories where that external prerequisite is documented. `pinned` means the operator keeps that reference fixed until an explicit revision-selection action; `live` means the operative charter may change as the reference changes, before generated project files are refreshed. Neither policy fetches or selects a newer checkout. After setup, verify that the generated `AGENTS.md` or `CLAUDE.md` resolves `runtime/operative_charter.md` through that reference.

## Optional Native Wrappers

The canonical setup workflow is still `task_orders/init.md`. Native wrappers are convenience routing layers only.

When Codex uses rendered integrations, invoke the `master-prompt-new-project` skill as `$master-prompt-new-project`. The skill is rendered from the `project-init` folder and routes setup requests to this file and `task_orders/init.md`; it is not a separate setup specification. The optional `master-prompt-refresh-project` skill rendered from `project-refresh` routes existing-instance work to `UPDATING.md` and `task_orders/framework_refresh.md`. Do not create a custom prompt that duplicates either lifecycle procedure.

When either skill should be a receipt-managed output of the generated downstream instance, pass `--runtime-wrapper project_init` and/or `--runtime-wrapper project_refresh` on both the dry run and the approved write. Bootstrap records the complete wrapper-ID set in retained input, binds the rendered outputs in the root receipt, and routes later changes through refresh. The hyphenated `project-init` and `project-refresh` names are template-folder names, not registry IDs.

Use `<runner> -- "<framework-checkout-as-visible-to-runner>/scripts/render_integrations.py" --integration codex --output-dir <render-dir> --framework-ref <stable-framework-ref>` only for reviewed standalone or user-level integration packaging outside a receipt-managed generated instance. Supply `--framework-ref` exactly as the destination project resolves it; the renderer rebases relative references inside nested Codex skills, so do not pre-rebase them from the skill directory. Generic entrypoint and task-order routing remains sufficient without these wrappers. Package a plugin only when you want to distribute a stable bundle of skills, app integrations, MCP configuration, hooks, or assets.

For Claude Code, the normal project surface is the generated `CLAUDE.md`. Use Claude-specific skills, agents, hooks, or rules only when a project needs those runtime-native surfaces.

Hooks are not the primary setup path. Use them only for deterministic lifecycle enforcement, such as checking command policy or post-run validation after the project has an approved runtime setup.

## Verification

The approved non-dry bootstrap runs one strict union of the receipt-listed
active profiles inside the write transaction; any conformance warning or error
fails the transaction and triggers rollback. A zero exit is the deterministic
initialization result, not merely a file-write receipt. If rollback cannot
finish, any remaining `.mpa-bootstrap-recovery.json`, `.mpa-bootstrap.lock`, or
`.mpa-bootstrap-recovery.tmp` keeps the project on the recovery path.

Do not immediately rerun the same conformance profiles; rerun conformance only
for recovery verification, focused diagnosis, later drift, or independently
requested evidence. A later standalone core diagnostic uses:

```bash
<runner> -- "<framework-checkout-as-visible-to-runner>/scripts/conformance_check.py" --profile core-project --root /abs/path/to/project --project-kind downstream --contract-root <contract-root-ref> --strict-warnings
```

The core-project aggregate includes required-surface preflight,
project-contract synchronization, and project-state lint. Run
`scripts/project_contract_sync.py` or `scripts/project_state_lint.py` separately
only for focused diagnosis; their
repeated execution is not independent conformance evidence. See `CONFORMANCE.md`
for profile definitions. The receipt is the profile inventory for a separately
required rerun; do not infer coverage from optional-file guesses.

The generated `AGENT_PROJECT.md` also contains the routine core conformance
command for later drift checks and task-time verification. It targets the
project root and passes the selected contract-root reference. It runs
from the downstream project root and calls the framework-owned script through
the approved framework reference using the SOW's confirmed Framework
Verification Runner. It must not be rewritten as a project-local `scripts/...`
command unless the framework is intentionally vendored there, and the runner
must not be silently replaced when unavailable.

Review the rendered authority, retained input, and every requested Manual
Acceptance Item after the transaction. Post-write human or manual review remains
a distinct acceptance obligation; deterministic conformance does not replace
it. If that review finds a correction, use an exact approved refresh plan rather
than rerunning bootstrap or hand-editing generated surfaces. Remove the temporary
raw answers file using the environment's approved cleanup method only after the
transaction succeeds and required post-write review is complete. The retained
project input, not that temporary file, owns future regeneration.
