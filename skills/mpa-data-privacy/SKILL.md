---
name: mpa-data-privacy
description: "Rules for handling PII, personal, customer, or production-derived data, redaction, and anonymization. Use when touching user records, logs, exports, test fixtures, analytics, or screenshots that may hold real data, or sending them to an external service or hosted model."
---

# Personal and production data

This covers handling. Whether processing is lawful is decided by the people accountable for the data, not here.

## Classify

- Data of unknown classification is not sent out, stored durably, or published until resolved.

## Sending data out

- Passing data to a hosted model, browser session, tool server, scanner, analytics service, or outside reviewer is a disclosure—including screenshots, clipboard, uploads, embeddings, and multi-model fan-out.

## Redaction and storage

- Check redaction in the final output, including hidden data: spreadsheet columns, document metadata, image regions, chart labels, log context. A model's claim that it redacted is not a check.

## Test data, copies, and deletion

- Track every durable copy created (reports, caches, downloads, fixtures, logs, embeddings, exports, temporary files), where it lives, and how it is deleted.
- Delete user, customer, or production data only with approval for that exact target, then verify the primary location, known copies, and derived stores: caches, search and vector indexes, analytics snapshots, and backups within retention rules.
