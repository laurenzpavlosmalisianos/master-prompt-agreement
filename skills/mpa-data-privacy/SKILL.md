---
name: mpa-data-privacy
description: Rules for handling personal, customer, or production-derived data. Use when a task touches user records, logs, exports, test fixtures, analytics, or screenshots that may hold real data, or sends such data to an external service or a hosted model.
---

# Personal and production data

This covers handling. Whether processing is lawful is decided by the people accountable for the data, not here.

## Classify

- Name each kind of data in play, including the ones that get overlooked: logs, traces, screenshots, prompts, model output, embeddings, agent memory, and inferred attributes. A mixed data set takes the highest sensitivity it contains.
- Data of unknown classification is not sent out, stored durably, or published until that is resolved.
- Being public, being reachable internally, or already sitting in a log is not permission to reuse or pass on.
- Use only the fields the purpose needs. Prefer synthetic, aggregate, pseudonymized, or schema-only data. A new purpose needs a new approval.

## Sending data out

- Passing data to a hosted model, a browser session, a tool server, a scanner, an analytics service, or an outside reviewer is a disclosure. Screenshots, clipboard, uploads, embeddings, and sending the same prompt to several models all count.
- Before sending, settle the minimal content, the redaction, the recipient, how long it is kept, and who approved it.
- When the recipient's retention, training use, logging, or administrator access is unknown, shrink the content, use synthetic data, stay local, or ask.

## Redaction and storage

- Check redaction in the final output, including hidden data: spreadsheet columns, document metadata, image regions, chart labels, log context. A model's statement that it redacted is not a check.
- Masking, hashing, truncating, or aggregating is not anonymization until linkage and inference were considered. A hash of a low-entropy identifier is reversible by enumeration.
- Use stable pseudonyms when relationships between records matter.
- Keep credentials, session values, raw prompts, raw traces, raw screenshots, and sensitive personal data out of tickets, shared logs, and third-party telemetry. Send analytics services pseudonymous IDs only.
- Do not write personal data or inferred profile facts into persistent agent memory without explicit approval for that kind of write.

## Test data

- Prefer synthetic values or reserved ranges that cannot identify a real person or tenant.
- Check fixtures, snapshots, golden files, recordings, seeds, local databases, and CI artifacts for live data. Copies of production tend to arrive there unnoticed.
- Production-derived data needs an approved purpose, minimization, a retention limit, and a deletion path before it is used.

## Copies and deletion

- Track every durable copy the task creates: reports, caches, downloads, fixtures, logs, embeddings, exports, temporary files. Note where each is and how it is deleted.
- On suspected exposure, stop further spread, keep the evidence, and report before cleaning up. See the `mpa-incident` skill.
- Delete user, customer, or production data only with approval for that exact target, then verify the primary location and the known copies.
- Deletion must reach derived copies too: caches, search and vector indexes, analytics snapshots, backups within their retention rules.
