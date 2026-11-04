# Security Policy

## Supported versions

Book Fork is pre-1.0. Security fixes land on `main` and in the newest release;
older releases are not patched separately.

| Version | Supported |
| --- | --- |
| 0.6.x | Yes |
| < 0.6 | No |

## Reporting a vulnerability

Please **do not open a public issue** for a vulnerability.

Use GitHub's private vulnerability reporting:
<https://github.com/Rastin-Amani/Book-Fork/security/advisories/new>

Include:

- what the issue is and the impact you believe it has
- the affected version or commit
- reproduction steps or a proof of concept
- any suggested fix or mitigation

You can expect an acknowledgement within a few days. We will confirm the issue,
agree on a disclosure timeline, and credit you in the advisory unless you prefer
to stay anonymous.

## Scope

In scope:

- authentication and session handling
- authorization between workspaces and users
- provider credential storage and exposure
- CSRF, SSRF, path traversal, and injection in the web app
- unsafe document parsing or export
- secrets accidentally committed to the repository

Out of scope:

- findings that require a compromised host or database
- missing hardening headers with no demonstrated impact
- reports from automated scanners without a reproduction
- social engineering and physical access

## Hardening already in place

- Provider API keys and session tokens encrypted at rest with Fernet.
- HttpOnly session cookie; the PocketBase bearer token is never exposed to JS.
- CSRF protection on browser mutations; rate-limited auth.
- SSRF guard for user-supplied provider endpoints.
- Path-traversal-safe storage keys and sensitive log redaction.
- Server-side authorization plus PocketBase collection rules as defence in depth.

The full audit is in [`docs/security-audit.md`](docs/security-audit.md).
