---
name: mpa-secure-coding
description: "Checks for app code handling auth, untrusted input, secrets, or outbound requests. Use when changing login, sessions, OIDC/JWT, IDOR/access checks, SSRF, CORS/CSRF, uploads, or HTTP, GraphQL, gRPC, and webhook endpoints. For audits, use mpa-security-audit; for PR review, use mpa-review."
---

# Secure coding

Name the trust boundaries the change touches (input source, privilege, reachable targets) and review the finished diff as an attacker would.

## Input and interpretation

- For files and embedded databases, open through handle-relative APIs and authorize the opened handle. Checking a path and then reopening it leaves a race.

## Authorization

- An OIDC ID token is not an API bearer token, and an access token is not proof of user identity. Validate signature, issuer, audience, and expiry, plus `nonce` on ID tokens.
- Where a one-time link carries a reset, login, or invite token, serve its landing page with `Referrer-Policy: no-referrer` and no third-party scripts, and redirect to a URL without the token once it is read.
- A validation layer that returns success without an authorization check is a bypass. Authorization runs first and fails closed, including when the check throws, times out, or lacks configuration.
- Enforce authorization inside the service itself rather than trusting upstream gateway or proxy headers alone.

## Requests, responses, secrets, and updates

- Set limits before exposing an expensive operation (page size, payload, query complexity or depth, rate, concurrency, paid-API spend per principal) and rate-limit login, password reset, and second-factor endpoints.
- Do not reflect an unvalidated `Origin` header (or a loose suffix or regex match) in CORS responses with credentials. Keep CSRF protection on every state-changing route that browsers authenticate automatically; exempt only webhooks that verify a signature.
