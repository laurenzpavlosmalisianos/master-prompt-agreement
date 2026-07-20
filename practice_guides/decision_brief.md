# Decision Brief Practice Guide

Use this Practice Guide for recommendations, status updates, incident updates, and other writing that should read like a concise briefing instead of generic LLM prose.

## Output Shape

Use only the sections the task needs:

1. Bottom line
2. Confirmed facts
3. Key unknowns
4. Options, when a real decision is required
5. Recommendation, when a real decision is required
6. Confidence

## Workflow

1. Put the decision or status first.
2. Separate confirmed facts from inference.
3. Surface the one to three unknowns that still matter.
4. Identify the trust level of decisive sources, especially primary versus secondary, stale versus current, and generated or user-provided content.
5. Reduce the option set to real choices, not filler variants.
6. For rejected options, give the decisive rejection reason, not a full debate.
7. State the recommendation with the reason that matters most.
8. State confidence and what would change it.
9. For approval requests, state the effect of approve, reject, and no response, plus the concrete evidence already checked. No response causes no state change unless an already-approved standing grant defines expiry, default action, and resume behavior.

## Style Rules

- Use short direct sentences.
- Prefer concrete nouns, dates, and numbers.
- Keep the bottom line to one short paragraph.
- Do not bury the recommendation under background.
- If the evidence is weak, say so plainly.

## Verification

- Check that every recommendation is traceable to a confirmed fact, inspected evidence item, or explicitly labeled inference.
- Check that each approval request names the requested authority, the action it enables, the evidence already checked, and what remains unverified.
- Check that no option, unknown, or confidence statement hides a material risk needed for the decision.

## Guardrails

- Do not inflate certainty.
- Do not mix facts and hypotheses in one bullet.
- Do not present more than three options unless the task truly requires it.
- Do not write executive-sounding filler.
- Do not force the reader to rerun the whole investigation just to calibrate trust in the recommendation.
- Keep public and private evidence separate: do not publish secrets, credentials, local workspace state, or user-specific private context; if private evidence informs the decision, label it as private or internal and summarize only what is authorized.
