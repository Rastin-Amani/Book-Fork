# Security audit (Phase 8)

Scope: the whole repository. This records what was verified, what was added, and
the deliberate limitations. Nothing here relies on UI hiding for authorization.

## File & archive security

| Control | Where | Status |
|---|---|---|
| Upload size ceiling | `MAX_REQUEST_BYTES` (transport) + `upload.maximum_file_size` (product) | ✅ both enforced; product limit via `app/services/limits.py` |
| Content-sniffed type | `documents/safety.py::sniff_kind` (magic bytes first, extension second) | ✅ |
| Archive path traversal | `safe_member_name` rejects absolute/`..`/backslash/`.` members | ✅ |
| ZIP bomb | per-entry and total uncompressed size + compression-ratio limits | ✅ (limits in `ArchiveLimits`, ceilings from settings) |
| Symlinks | `inspect_archive` rejects symlink members | ✅ |
| Temp cleanup | `safe_temp_dir` context manager; retention sweep for stray temp files | ✅ |
| Source isolation | sources stored under `documents/{id}/...`, never overwritten | ✅ |
| Authorization before download | workspace ownership checked in `app.py`/`translate.py` before streaming | ✅ |
| Signed URLs | S3 backend supports `generate_download_url`; local streams via the app | ✅ |

A user cannot reach another workspace's document by guessing an id: every read
compares `document.workspace` to the caller's workspace and returns 404 on
mismatch (tested in `tests/integration/test_e2e_flow.py` and `test_web.py`).

## SSRF

`app/security/urls.py` validates every user-supplied provider URL before use
(also enforced again in `ProviderRuntime`). Blocked: loopback, private, link-local,
multicast, reserved, unspecified and the cloud metadata address, for both IPv4 and
IPv6 (including IPv4-mapped IPv6), plus non-HTTP schemes and URLs with embedded
credentials. Private endpoints are permitted only with `allow_private` in the
connection config (needed for local Ollama). A DNS-resolution test uses a patched
resolver. See `tests/unit/test_ssrf_matrix.py`.

**Known limitation:** the check is time-of-check, not time-of-use. A DNS-rebinding
attack could resolve to a different address at connect time. The transport does not
follow redirects from untrusted endpoints (`follow_redirects=False`). Address
pinning is the documented upgrade path.

## Authentication & authorization

- Sessions are encrypted HttpOnly cookies; validated against PocketBase on each
  non-asset request.
- Sign-in is OAuth2-only (Google / GitHub). Each attempt carries a signed,
  HttpOnly, 10-minute `state` cookie and a PKCE verifier; the callback is a
  top-level navigation and rejects missing, forged, expired or non-ASCII state.
  Passwords, OTP and MFA are disabled on the PocketBase users collection.
- Admin routes require `admin.emails` membership **and** run with the superuser
  service token; ordinary users never see other workspaces.
- No authorization decision relies on hidden UI. Cross-workspace and unauthenticated
  access are tested.
- Provider credentials live in `provider_credentials`, which has all PocketBase
  rules set to `null` (superuser/service only) and are never rendered after saving.
- CSRF is enforced on every state-changing route, including all admin mutations.

**Known limitation:** the per-process rate limiter does not coordinate across
replicas; move to a shared store when scaled out.

## Browser security headers

`app/web/security_headers.py` sets CSP, `X-Content-Type-Options`, `Referrer-Policy`,
`Permissions-Policy`, `X-Frame-Options`, `Cross-Origin-Opener-Policy` and HSTS (in
production). The default CSP is explicitly HTMX/Alpine-compatible
(`'unsafe-eval'` for Alpine's evaluator, `'unsafe-inline'` for inline styles) and is
overridable with `CONTENT_SECURITY_POLICY`.

## Rate limiting & abuse prevention

Sensitive operations are rate limited per user/IP: authentication, upload,
provider connection test, translation creation and retry. Thresholds are
environment configuration. Business limits (uploads/day, jobs/day, concurrent jobs
per workspace, retries per job) are read from `system_settings` and default to
unlimited when unset. The book price is snapshotted on the job when it is
created, so a settings change cannot reprice an order that is already running.

## Logging & privacy

Structured logs redact sensitive keys (secret/token/password/credential/…);
document bodies and prompts are never logged. Request ids are minted server-side
(the inbound `X-Request-ID` is not trusted) and echoed back.

## Hardcoding audit

Searched the codebase for business leakage. Findings and dispositions:

| Pattern | Disposition |
|---|---|
| `English`, `Persian`, `German`, `Japanese`, `Arabic` in `app/`/`worker/` | Only a comment in `language/models.py`; all language data is seeded. |
| vendor names (`openai`, `anthropic`, …) | Provider **type enum** and the generic OpenAI-compatible adapter — an implementation capability, not a hidden default translator. |
| `temperature=0.3`, `chunk_size=500`, `RTL_LANGUAGES`, `book_chunks`, `price_per_book=` | Not present as behaviour. `chunk_size` occurrences are I/O buffer sizes. |
| `sleep(2)` | Not present. |
| `if language == "…"` | Not present. |
| `BackgroundTasks` | Not used; the durable worker is a separate process. |
| module-level global clients | Not present; everything is composed in `AppContext`. |
| raw `PocketBaseClient(...)` outside repositories/auth/context | Not present. |
| `os.environ` outside `app/config.py` | Not present. |

Every business default lives in `system_settings`, `seeds/`, or provider/model
records. Environment variables hold only infrastructure and secrets.
