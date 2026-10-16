state_schema_version: 1
durable_decision_count: 0
directive_count: 0

<!-- mpa-generated-state-origin: master-prompt-agreement/project-state/v1 -->

# Decisions

_Project-local durable technical decisions and User directives._

Use this file for durable project choices and explicit User directives that should guide future sessions. Do not use it as a chat log.

When adding the first record, declare `record_timezone: <IANA timezone name>`
before any title or dated record and after the origin marker when present,
separate from the numeric count header. Manual files need no origin marker
or title.
All record dates in this file use that calendar. Validation compares
them with today's date in the declared timezone and rejects future dates.
Review existing dates before changing the calendar convention; do not invent
event timestamps from date-only records. Empty files may omit this metadata.

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
