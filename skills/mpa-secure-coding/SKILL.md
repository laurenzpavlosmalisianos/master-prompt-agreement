---
name: mpa-secure-coding
description: "Checks for app code that handles authentication, authorization, untrusted input, or secrets. Use when changing login, OIDC/JWT, access checks, one-time links, CORS/CSRF, rate limits, HTTP, GraphQL, gRPC, or webhook endpoints, or command strings built from data."
---

# Secure coding

Name the trust boundaries the change touches (input source, privilege, reachable targets) and review the finished diff as an attacker would.

## Input and interpretation

- For files and embedded databases, open through handle-relative APIs and authorize the opened handle. Checking a path and then reopening it leaves a race.
- Every nested parser reads a command string again: `ssh host cmd`, `sudo sh -c`, `su -c`, cron lines, Makefile recipes, CI fields. Pass data as arguments, standard input, files, or environment variables instead of interpolating it into command strings.

## Authorization

- An OIDC ID token is not an API bearer token, and an access token is not proof of user identity. Validate signature, issuer, audience, and expiry, plus `nonce` on ID tokens.
- Where a one-time link carries a reset, login, or invite token, serve its landing page with `Referrer-Policy: no-referrer` and no third-party scripts, and redirect to a URL without the token once it is read.
- A validation layer that returns success without an authorization check is a bypass. Authorization runs first and fails closed, including when the check throws, times out, or lacks configuration.
- Enforce authorization inside the service itself rather than trusting upstream gateway or proxy headers alone.

## Requests, responses, and secrets

- Set limits before exposing an expensive operation (page size, payload, query complexity or depth, rate, concurrency, paid-API spend per principal) and rate-limit login, password reset, and second-factor endpoints.
- Do not reflect an unvalidated `Origin` header (or a loose suffix or regex match) in CORS responses with credentials. Keep CSRF protection on every state-changing route that browsers authenticate automatically; exempt only webhooks that verify a signature.
- Secrets do not go in command arguments (visible in process lists), and `set -x` stays off around them.
