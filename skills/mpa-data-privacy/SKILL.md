---
name: mpa-data-privacy
description: "Rules for handling PII, personal, customer, or production-derived data, redaction, and anonymization. Use when touching user records, logs, exports, test fixtures, analytics, or screenshots that may hold real data, or sending them to an external service or hosted model."
---

# Personal and production data

This covers handling. Whether processing is lawful is decided by the people accountable for the data, not here.

## Classify

- Name each kind of data in play, including overlooked artifacts: logs, traces, screenshots, prompts, model output, embeddings, agent memory, and inferred attributes. A mixed set takes the highest sensitivity it contains.
- Data of unknown classification is not sent out, stored durably, or published until resolved.
- Being public, reachable internally, or already in a log is not permission to reuse or pass on.
- Use only the fields the purpose needs; prefer synthetic, reserved-range, aggregate, pseudonymized, or schema-only data. A new purpose needs new approval.

## Sending data out

- Passing data to a hosted model, browser session, tool server, scanner, analytics service, or outside reviewer is a disclosure—including screenshots, clipboard, uploads, embeddings, and multi-model fan-out.
- Before sending, settle minimal content, redaction, recipient, retention, and approval. When retention, training use, logging, or admin access is unknown, shrink the content, use synthetic data, stay local, or ask.

## Redaction and storage

- Check redaction in the final output, including hidden data: spreadsheet columns, document metadata, image regions, chart labels, log context. A model's claim that it redacted is not a check.
- Masking, hashing, truncating, or aggregating is not anonymization until linkage and inference are considered. A hash of a low-entropy identifier is reversible by enumeration.
- Keep credentials, session values, raw prompts, raw traces, raw screenshots, and sensitive personal data out of tickets, shared logs, and third-party telemetry; send analytics services pseudonymous IDs only.
- Do not write personal data or inferred profile facts into persistent agent memory without explicit approval (`mpa-agent-inputs`).

## Test data, copies, and deletion

- Check fixtures, snapshots, golden files, recordings, seeds, local databases, and CI artifacts for live data. Production-derived data needs an approved purpose, minimization, a retention limit, and a deletion path.
- Track every durable copy created (reports, caches, downloads, fixtures, logs, embeddings, exports, temporary files), where it lives, and how it is deleted.
- On suspected exposure, stop spread and use `mpa-incident`.
- Delete user, customer, or production data only with approval for that exact target, then verify the primary location, known copies, and derived stores: caches, search and vector indexes, analytics snapshots, and backups within retention rules.
