# Risk Levels

Use one Risk Level per task. Choose the highest Risk Level that matches the risk. Higher levels inherit the duties of lower levels.

## 1. Fast

Use when the task is small, local, reversible, and low-risk.

- Keep planning brief.
- Touch the minimum surface.
- Run the smallest meaningful check.
- Do not create persistent plans, logs, or artifacts unless the task or verification requires them.

## 2. Standard

Default Risk Level for ordinary implementation work.

- State the task contract when ambiguity exists.
- Verify the changed behavior.
- Report residual risks.
- Keep context narrow and evidence-focused.

## 3. Careful

Use when the task is ambiguous, multi-file, user-facing, dependency-affecting, hard to reverse, or an ordinary systematic review or audit without an adversarial trigger.

- Make the acceptance checks explicit before editing.
- Preserve a baseline when regression risk is material.
- Prefer stronger verification over speed.
- Classify material validator, linter, scanner, benchmark, and audit output before it drives edits or findings.
- Treat generated code in critical or unknown surfaces as requiring explicit review burden, not just passing tests.
- Stop when hidden scope expansion appears.

## 4. Adversarial

Use for explicitly adversarial audits or reviews, untrusted content, prompt-injection surfaces, security-sensitive work, and high-impact changes with unclear recovery or material abuse potential.

- Assume the first explanation may be wrong.
- Generate competing hypotheses before concluding.
- Prefer finding quality over finding count.
- Recommend second review when the exploit path or blast radius is material.

## 5. Forensic

Use for incidents, suspected compromise, data loss, secret exposure, corrupted state, or disputed facts.

- Preserve evidence before changing state.
- Separate confirmed facts from inference at every step.
- Record exact timestamps, commands, and artifacts when available.
- Avoid destructive actions until the evidence burden is satisfied.
- Escalate when the available evidence cannot justify a safe action.

## Selection Rules

- Choose the highest matching Risk Level.
- Do not stay in `fast` when trust boundaries, external recency, or irreversible actions are involved.
- Move up a Risk Level when the task reveals wider blast radius than expected.
- Move up a Risk Level when the work touches a project Critical Surface, unreviewed generated code, or a boundary the agent cannot fully inspect.
- Do not move down a Risk Level just to reduce effort.
