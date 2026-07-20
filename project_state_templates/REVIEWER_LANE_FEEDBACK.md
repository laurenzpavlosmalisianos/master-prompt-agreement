<!-- mpa-generated-state-origin: master-prompt-agreement/project-state/v1 -->

# Reviewer Lane Feedback

Status: project-local, evidence-bound, non-benchmark.
Context-loading: opt-in only. Load this file only for reviewer routing, external-review orchestration, source-monitoring strategy, prompt-agent-quality work, or decision-triggered insights.

Use this file to record what actually happened when reviewer lanes were used. A reviewer lane can be a local subagent, browser-backed external reviewer, deep-research surface, bounded wrapper, deterministic checker, connector, human reviewer, or other bounded review source.

This file is not a model leaderboard. It is not proof that one model is better than another. It is routing evidence for future work.

## Closeout Trigger

At task closeout, update this file when reviewer lanes were used, planned then skipped, reviewer findings were accepted or rejected, or a commit, pull request, release, or milestone claims external review. If that condition applies but it is unclear whether the observation is reusable, ask one concise follow-up before closeout. Do not install mandatory VCS hooks or block commits only because this optional file is absent.

## Marker Rules

Reviewer reports should emit short single-line JSON markers when reviewer lanes are planned or used. Raw local agent session logs, browser transcripts, screenshots, and private wrapper logs may support audit work, but they are not the primary source of truth.

Supported markers:

```text
REVIEWER_LANE_USED {"lane_id":"local_schema_reviewer","task_ref":"ORCH-R1","lane_class":"local_subagent","purpose":"schema review","output_ref":"REVIEWER_LANE_FEEDBACK.md","evidence_refs":["REVIEWER_LANE_FEEDBACK.md#local-schema-reviewer"]}
REVIEWER_LANE_SKIPPED {"lane_id":"deep_research_lane","task_ref":"ORCH-R1","reason_category":"not_needed","reason":"Primary-source evidence and local checks were sufficient."}
REVIEWER_FINDING_ACCEPTED {"finding_id":"R1-F1","source_lane_id":"local_schema_reviewer","evidence_ref":"REVIEWER_LANE_FEEDBACK.md#local-schema-reviewer","action_ref":"task_orders/orchestrate.md","reason":"Finding identified a missing reviewer-lane record."}
REVIEWER_FINDING_REJECTED {"finding_id":"R1-F2","source_lane_id":"external_chat_reviewer","evidence_ref":"REVIEWER_LANE_FEEDBACK.md#external-chat-reviewer","reason_category":"unsupported","reason":"Claim lacked inspected evidence."}
LANE_FIT_OBSERVATION {"lane_id":"local_schema_reviewer","task_ref":"ORCH-R1","claim_type":"strength","claim":"Converted reviewer-lane risk into a lintable contract.","evidence_refs":["REVIEWER_LANE_FEEDBACK.md#local-schema-reviewer"],"routing_implication":"Use for schema, invariant, and contract-review passes.","confidence":"medium"}
```

## Lane Summaries

Keep one section per lane. Keep each section short. Use "no direct evidence" when the project has no attributable use of the lane.

## Lane: [lane_id]

Runtime Class: [local_subagent / external_chat / deep_research / bounded_wrapper / deterministic_script / human / other]
Evidence Basis: [single-observation / repeated-in-project / repeated-across-projects / public-source-backed / design-judgment]
Confidence: [low / medium / high]

#### Used For

- [observed task, or "no direct evidence"]

#### Worked

- [observed strength plus evidence reference, or "no direct evidence"]

#### Limits Or Failure Modes

- [observed limit plus evidence reference, or "no direct evidence"]

#### Best Future Use

- [routing implication, or "no direct evidence"]

#### Avoid Or Do Not Rely On For

- [avoid task or limit, or "no direct evidence"]

#### Evidence

- [marker, report, accepted/rejected finding, or sanitized review artifact]

## Promotion Rules

- Project-local process observations go to `FINDINGS.md`.
- Sanitized reusable framework candidates go to `FRAMEWORK_FEEDBACK.md`.
- A qualifying decision-triggered retrospective narrative goes to
  `task_orders/insights.md` output; ordinary milestone completion is not a
  trigger.
- Reviewer-lane feedback does not itself authorize framework changes.

## Forbidden

- model rankings, winners, scores, or benchmark claims
- unsupported general claims about model intelligence or model quality
- raw local agent session logs, raw transcripts, screenshots, or browser history as primary evidence
- private paths, project names, account names, secrets, credentials, private URLs, or private writing profiles
- broad retrospectives unrelated to reviewer routing or reviewer-lane quality
