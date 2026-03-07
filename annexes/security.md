Annex D — Security Policy (SECURITY.md)

_In consultancy framework agreements, this annex would define the information security policy the contractor must follow. Here it defines the security standards the Contractor must apply when writing, reviewing, or modifying code._

Vulnerability Checklist

[Select applicable items for this project. Remove items that do not apply.]

Input Handling
- Validate and sanitize all input at system boundaries (user input, API parameters, file uploads, URL parameters).
- Use parameterized queries for all database operations. No string concatenation in queries.
- Validate file paths to prevent path traversal. Reject `..` sequences and absolute paths in user input.

Output Handling
- Do not expose internal details in user-facing error messages (stack traces, file paths, SQL queries, dependency versions).
- Encode output for the target context (HTML, URL, JavaScript, SQL) to prevent injection.

Authentication and Authorization
- Do not implement custom authentication or session management when a framework-provided or well-established solution exists.
- Apply authorization checks at the server/backend. Never rely on client-side access control alone.

Cryptography
- Do not implement custom cryptographic algorithms. Use established libraries (libsodium, OpenSSL, Web Crypto API, ring).
- Do not use deprecated algorithms (MD5 for integrity, SHA-1 for signatures, DES, RC4, ECB mode).
- Do not hardcode cryptographic keys, IVs, or salts.

Dependencies
- Before adding a dependency, check for known vulnerabilities (npm audit, pip-audit, cargo audit, or equivalent).
- Prefer dependencies with active maintenance, security policies, and responsible disclosure processes.

Least Privilege
- Request minimum necessary permissions. Use read-only access when write is not needed.
- Scope API tokens and credentials to the narrowest required access level.
- Do not run processes as root or with elevated privileges unless explicitly required.

Secure Defaults
- Enable HTTPS, secure cookies, and security headers where applicable.
- Disable debug mode, verbose logging, and development endpoints in production configurations.

Compliance Requirements

[Applicable compliance frameworks. Delete if none. Examples:]
- SOC 2 Type II
- HIPAA
- PCI DSS
- GDPR (data processing requirements)

External References

_Authoritative sources for security audits and code review. The Contractor shall consult these when performing audits (task_orders/audit.md) or adversarial reviews (task_orders/review.md) on projects where this annex is active. These are reference materials, not checklists to follow verbatim. Apply the subset relevant to the project's tech stack and attack surface._

OWASP Top 10 (2025): Web application security risks — https://owasp.org/Top10/2025/
OWASP Top 10 Project: Project home, all editions — https://owasp.org/www-project-top-ten/
CWE Top 25 (2025): Most dangerous software weakness types — https://cwe.mitre.org/top25/
MITRE ATT&CK: Adversary tactics, techniques, procedures — https://attack.mitre.org/
OWASP ASVS 5.0: Application security verification standard — https://owasp.org/www-project-application-security-verification-standard/
NIST SSDF (SP 800-218): Secure software development framework — https://csrc.nist.gov/projects/ssdf
CISA Secure by Design: Secure-by-default development principles — https://www.cisa.gov/resources-tools/resources/secure-by-design

Notes

- This annex is optional. If omitted, MSA Article 8.1.6 applies as the universal minimum.
- When this annex conflicts with MSA Article 8.1, the stricter rule applies.
- The audit task order (task_orders/audit.md) uses this annex as additional audit criteria when present.
