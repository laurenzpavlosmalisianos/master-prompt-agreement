---
name: mpa-secure-coding
description: "Checks for app code handling auth, untrusted input, secrets, or outbound requests. Use when changing login, sessions, OIDC/JWT, IDOR/access checks, SSRF, CORS/CSRF, uploads, or HTTP, GraphQL, gRPC, and webhook endpoints. For audits, use mpa-security-audit; for PR review, use mpa-review."
---

# Secure coding

Name the trust boundaries the change touches (input source, privilege, reachable targets) and review the finished diff as an attacker would.

## Input and interpretation

- Model output, tool results, and retrieved content are untrusted input (see `mpa-agent-inputs`).
- Parsing a URL is not an SSRF control. Allowlist destinations, resolve and check the address actually connected to, and restrict redirects.
- Pass process arguments as an array, not a shell string. On Windows, argument arrays are re-joined into a command line, so keep user-influenced arguments away from `.bat`, `.cmd`, and `cmd.exe`.
- Do not deserialize untrusted data with a decoder that can instantiate types named in the payload.
- For files and embedded databases, open through handle-relative APIs and authorize the opened handle. Checking a path and then reopening it leaves a race.

## Authorization

- Check authorization on the server, next to the protected operation (per resolver in GraphQL, per method in gRPC), for the object and the tenant, not only that the caller is logged in. Client-supplied identifiers (object, tenant, account, parent) are attacker-chosen selectors; unguessable IDs, hidden fields, generated types, and frontend checks are not authorization.
- On nested routes, load the child only through the verified parent relationship.
- Token scopes limit what a client may do for a user; the user's own permission still needs checking.
- An OIDC ID token is not an API bearer token, and an access token is not proof of user identity. Validate signature, issuer, audience, and expiry, plus `nonce` on ID tokens.
- A signed URL carries the target user and an expiry inside the signed parameters and does not rely on the session. Whoever holds the URL is authorized, so sign nothing broader than the one action.
- A validation layer that returns success without an authorization check is a bypass. Authorization runs first and fails closed.
- Enforce authorization inside the service itself rather than trusting upstream gateway or proxy headers alone.

## Requests, responses, secrets, and updates

- Reject unknown fields that could set privileged attributes, and allowlist dynamic structure: operators, expansions, GraphQL fields, callback URLs, webhook event types (see `mpa-database` for dynamic SQL).
- Set limits before exposing an expensive operation (page size, payload, query complexity or depth, rate, concurrency, paid-API spend per principal) and rate-limit login, password reset, and second-factor endpoints.
- Define what a repeated or reordered request does for mutations, payments, webhooks, and jobs. After a mutation with an unknown result, do not retry until an idempotency key or reconciliation rules out a duplicate.
- Return explicit fields; generic serializers and resolvers leak properties added later (`mpa-data-privacy`).
- Reverse-proxy trust lists exact upstream addresses. A wildcard lets a client spoof its address past rate limits and allowlists.
- Do not reflect an unvalidated `Origin` header (or a loose suffix or regex match) in CORS responses with credentials. Keep CSRF protection on every state-changing route that browsers authenticate automatically; exempt only webhooks that verify a signature.
- Webhooks verify both signature and a timestamp or nonce replay window.
- Prefer short-lived credentials that can be revoked without a redeploy. An updater checks that the update is current and meant for this target; a valid signature alone allows replay and downgrade.

## Evidence

- Add a negative test for each relied-on security property: denied access, cross-tenant access, malformed input, replay.
- A passing schema linter, typed DTO, or gateway rule does not show that authorization, tenancy, or limits are enforced.
- Active scanning, fuzzing, or sending non-public code to a hosted scanner follows `mpa-security-audit`.
