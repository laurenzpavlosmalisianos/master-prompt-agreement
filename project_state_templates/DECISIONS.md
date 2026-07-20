state_schema_version: 1
durable_decision_count: 0
directive_count: 0

<!-- mpa-generated-state-origin: master-prompt-agreement/project-state/v1 -->

# Decisions

_Project-local durable technical decisions and User directives._

Use this file for durable project choices and explicit User directives that should guide future sessions. Do not use it as a chat log.

Each decision begins `- YYYY-MM-DD, decision_id: <unique-id>`. Its indented,
case-sensitive fields are `Status`, `Scope`, `Decision`, `Rationale`,
`Alternatives considered`, `Evidence or verification`, `Authority source`,
`Supersession relationship`, and `Review trigger`; every field must be
nonempty. Decision `Status` is `active` or `superseded`. `Supersession
relationship` is exactly `none`, `supersedes <decision_id>`, or `superseded by
<decision_id>`; a superseded decision names its replacement.

Each directive begins `- YYYY-MM-DD, directive_id: <unique-id>`. Its indented,
case-sensitive fields are `Status`, `Directive`, `Authority source`, `Scope`,
`Expiry or review trigger`, and `Affected files or surfaces`; every field must
be nonempty. Directive `Status` is `active`, `superseded`, `expired`, or
`revoked`.
