---
name: mpa-secure-coding
description: Checks for code that handles authentication, authorization, untrusted input, secrets, or outbound requests. Use when writing or changing login, sessions, tokens, access checks, file uploads, URL fetching, or HTTP, GraphQL, gRPC, and webhook endpoints.
---

# Secure coding

Name the trust boundaries the change touches: who supplies each input, what privilege the code runs with, and what it can reach if a neighbouring component is compromised. Then read the finished diff the way an attacker would.

## Input and interpretation

- Model output, tool results, and retrieved content are untrusted input, the same as a request body.
- Parsing a URL is not a server-side request forgery control. Allowlist destinations, resolve and check the address that is actually connected to, and restrict redirects.
- Process arguments go in an array, not a shell string. On Windows an argument array is re-joined into a command line, so user-influenced arguments must not reach `.bat`, `.cmd`, or `cmd.exe`.
- Do not deserialize untrusted data with a decoder that can instantiate types named in the payload.
- For files and embedded databases, open through handle-relative APIs and authorize the opened handle. Checking a path and then reopening it leaves a race.

## Authorization

- Check authorization on the server, next to the protected operation, for the object and the tenant, not only that the caller is logged in. Identifiers supplied by the client (object, tenant, account, parent) are attacker-chosen selectors. Unguessable IDs, hidden fields, generated types, and frontend checks are not authorization.
- On nested routes, load the child only through the verified parent relationship.
- Token scopes limit what a client may do for a user. The user's own permission still needs checking.
- An OIDC ID token is not an API bearer token, and an access token is not proof of user identity. Validate signature, issuer, audience, expiry, and nonce.
- A signed URL carries the target user and an expiry inside the signed parameters and does not rely on the session. Whoever holds the URL is authorized, so sign nothing broader than the one action.
- A validation layer that returns success without an authorization check is a bypass. Authorization runs first and fails closed.
- An authorization decision or a secret placed only in a prompt is not enforced. Put it in code.

## Requests and responses

- Reject unknown fields that could set privileged attributes. Allowlist dynamic structure: sort and filter fields, operators, expansions, GraphQL fields, callback URLs, webhook event types.
- Set limits before exposing an expensive operation: page size, payload, nesting or query complexity, rate, concurrency, and paid-API spend per principal. Rate-limit login, password reset, and second-factor endpoints.
- Define what a repeated or reordered request does for mutations, payments, webhooks, and jobs. After a mutation with an unknown result, do not retry until an idempotency key or a reconciliation rules out a duplicate.
- Return the minimum fields. Generic serializers and resolvers leak properties added later.
- Reverse-proxy trust lists exact upstream addresses. A wildcard lets a client spoof its address past rate limits and allowlists.
- No wildcard CORS origin together with credentials. Keep CSRF protection on every state-changing route that browsers authenticate automatically; exempt only webhooks that verify a signature.
- Webhooks verify signature and a timestamp or nonce window. GraphQL authorizes per resolver and limits depth. gRPC authorizes per method.

## Secrets and updates

- Prefer short-lived credentials that can be revoked without a redeploy.
- An updater checks that the update is current and meant for this target. A valid signature alone allows replay and downgrade.

## Evidence

- Add a negative test for each security property relied on: denied access, cross-tenant access, malformed input, replay.
- A passing schema linter, typed DTO, or gateway rule does not show that authorization, tenancy, or limits are enforced.
- Active scanning or fuzzing, and sending non-public code to a hosted scanner, follow the `mpa-security-audit` skill.

Related skills: `mpa-database`, `mpa-agent-inputs`, `mpa-data-privacy`.
