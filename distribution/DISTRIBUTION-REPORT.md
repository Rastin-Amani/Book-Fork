# Distribution Report

## Project

- **Name:** Book Fork
- **Repository:** <https://github.com/Rastin-Amani/Book-Fork>
- **Website:** <https://bookfork.space>
- **Managed app:** <https://app.bookfork.space>
- **Version:** v0.6.1 (pre-1.0)
- **License:** MIT
- **Campaign date:** 2026-11-04
- **Mode:** AUTONOMOUS, limited to channels with legitimate account access
- **Budget:** $0

## Executive summary

This run prepared the public launch surface rather than posting to third-party
communities. The repository was already public; it lacked a launch README,
screenshots, CI, a security policy, issue templates and repository metadata.

- Opportunities discovered: 14
- Qualified opportunities: 9
- Executed actions: 8
- Verified live results: 5 at time of writing (README, metadata, CI, release
  surface, container build)
- Manual actions required: 5
- Blocked actions: 0
- Rejected / removed: 0
- Articles published: 0 (launch copy prepared in `distribution/LAUNCH.md`)
- Directory submissions: 0
- Community submissions: 0
- Package releases: existing v0.6.1 release
- Launches: 0 (no external launch post sent)

## Channels executed

| Destination | Type | Action | Status | URL | Notes |
|---|---|---|---|---|---|
| GitHub README | Repository | Rebuilt as launch README with badges, screenshots, architecture, quick start, limits | LIVE | <https://github.com/Rastin-Amani/Book-Fork> | Verified on `main` |
| GitHub About | Repository | Description, homepage, 16 topics | LIVE | <https://github.com/Rastin-Amani/Book-Fork> | Applied with `gh repo edit` |
| GitHub Actions | CI | `ruff`, format check, strict mypy, 427 pytest tests | LIVE | <https://github.com/Rastin-Amani/Book-Fork/actions/workflows/ci.yml> | Run 41858974459 succeeded |
| GHCR workflow | Packaging | Multi-arch image on main and tags | LIVE | <https://github.com/Rastin-Amani/Book-Fork/pkgs/container/book-fork> | Run 41858974344 published linux/amd64 and linux/arm64 |
| Screenshots | Repository | 8 product screens from a seeded demo workspace | LIVE | `.github/assets/screenshots/` | Dashboard, estimate, review, progress, documents, glossaries, providers, mobile |
| Social preview asset | Repository | 1280×640 launch card | READY | `.github/assets/social-preview.png` | GitHub has no API for uploading it; see manual actions |
| Security policy | Repository | Private reporting route, scope, hardening summary | LIVE | `SECURITY.md` | Points at GitHub private advisories |
| Issue templates | Repository | Bug report, feature request, contact links | LIVE | `.github/ISSUE_TEMPLATE/` | Blank issues disabled |
| Launch copy | Repository | Channel-native copy for HN, Reddit, Product Hunt, X, LinkedIn | READY | `distribution/LAUNCH.md` | Not posted; see manual actions |

## Code and product fixes made during readiness

| Change | Why |
|---|---|
| Job page resolves the model identifier from the job snapshot | Previously showed a raw PocketBase relation id |
| Document table no longer collapses names to a few characters | Long book titles were truncated despite available width |
| `var/` excluded from mypy | Local demo/PB state is git-ignored but was still scanned |

All gates pass: ruff, ruff format, strict mypy, and 427 tests.

## Screenshots

The screenshots were captured from the real application running against a
temporary local PocketBase with seeded demo data (workspace “Atlas Studio”,
eight books, six jobs, glossary terms, memory entries and provider connections).
No production customer data was used. Files live in
`.github/assets/screenshots/` and the launch card in
`.github/assets/social-preview.png`.

## Manual actions required

| Destination | Exact blocker | Prepared asset | Required human action |
|---|---|---|---|
| GitHub social preview | GitHub exposes no upload API for repository social previews | `.github/assets/social-preview.png` | Repository → Settings → General → Social preview → upload the PNG |
| Hacker News | HN requires human-authored submission text and a personal account | Fact sheet and title options in `distribution/LAUNCH.md` | Write the post in your own words and submit Show HN from your account |
| Reddit (r/selfhosted, r/opensource) | Posting requires a human account with community history; self-promotion rules apply per subreddit | Finished posts in `distribution/LAUNCH.md` | Re-read each subreddit’s current rules, then post from your account |
| Product Hunt | Makers must submit through their personal account and confirm the launch | Tagline, description, first comment in `distribution/LAUNCH.md` | Create or use the maker account, upload gallery images, schedule the launch |
| Directories / awesome lists | Each destination requires rule review and a submission or PR; some require account history | Short blurb in `distribution/LAUNCH.md` | Submit to the shortlist below, newest rules first |

## Qualified manual next steps

These were verified as relevant but not submitted because the action requires a
human account, a rule check immediately before posting, or both.

| Destination | Fit | Why not automated |
|---|---|---|
| Awesome Selfhosted | Strong | PR must follow the list’s current entry format and non-commercial criteria |
| Awesome Python | Medium | Project is an application, not a library; check current inclusion rules |
| selfh.st / self-hosted directories | Strong | Submission forms, some with moderation |
| OpenAlternative / open-source alternatives | Medium | Needs an “alternative to” positioning and current submission rules |
| Product Hunt | Strong | Maker account, gallery, launch scheduling |
| Show HN | Strong | Human-authored text required by current guidelines |
| r/selfhosted | Strong | Account history and subreddit self-promotion rules |
| r/opensource | Strong | Same |
| dev.to / Hashnode article | Medium | Article should be published from the maintainer account with canonical link |

## Blocked / skipped

| Destination | Reason | Revisit |
|---|---|---|
| Paid directories and launch boosts | $0 budget; no spending authorised | Only if explicitly approved |
| Bulk cold outreach | Would require scraping and mass sending; not appropriate | Skip |
| Fake accounts, vote coordination, review buying | Prohibited | Never |
| Production demo seeding | Customer data must not be used for screenshots | Not needed; local demo used |

## Performance

No external campaign has been sent yet, so there is no attributable traffic or
signup data. The repository was public before this run with 0 stars and no
topics. Measure after the first launch post:

| Destination | Clicks | Stars | Clones | Signups | Notes |
|---|---:|---:|---:|---:|---|
| GitHub README | — | — | — | — | Baseline only |
| Managed app | — | — | — | — | Baseline only |

## What worked

- The app was already runnable; a local PocketBase and seeded demo data produced
  real screenshots without touching production.
- The existing docs set was strong enough to link from the README instead of
  duplicating it.
- CI passed on the first run, including the new README changes.

## What did not work / constraints

- GitHub offers no API to upload the social preview; this remains a one-click
  manual step.
- Launch platforms all require a human account or human-authored text under
  current rules. No submission was faked or automated around those controls.
- The first multi-arch container build is slower than the CI job (about three
  minutes), but completed successfully.

## Content created

- `README.md` — launch README with badges, screenshots, feature set, stack,
  pipeline, quick start, self-host vs managed, security, limitations, structure
  and documentation map.
- `SECURITY.md` — supported versions, private reporting, scope, existing
  hardening.
- `distribution/LAUNCH.md` — finished copy for Show HN (fact sheet, human-only),
  r/selfhosted, r/opensource, Product Hunt, X, LinkedIn and a directory blurb.
- `.github/assets/screenshots/*.png` — eight product screens.
- `.github/assets/social-preview.png` — 1280×640 launch card.
- `.github/workflows/ci.yml`, `.github/workflows/container.yml`.
- `.github/ISSUE_TEMPLATE/` and `.github/pull_request_template.md`.

## Lessons

- The highest-leverage readiness work was not copy: it was making the real UI
  show its own value (model names, full document titles) and capturing it with
  believable demo data.
- Pre-1.0 products benefit more from an honest limitations section than from
  broader claims. The README now states OAuth-only login, two provider
  protocols, missing glossary attachment and the lack of checkout up front.

## Next distribution cycle

1. Upload the social preview and confirm the GitHub About panel.
2. Publish the dev.to technical article with a canonical link to the repo.
3. Submit to Awesome Selfhosted after checking its current entry criteria.
4. Launch on Product Hunt and post the Show HN from a personal account.
5. Measure stars, clones, managed signups and provider-key connections for two
   weeks; then decide whether the next release needs its own announcement.

## Evidence

- CI run: <https://github.com/Rastin-Amani/Book-Fork/actions/runs/41858974459>
- README commit: `15abde8`
- UI fixes commit: `eadbdc3`
- Repository: <https://github.com/Rastin-Amani/Book-Fork>
- Managed app: <https://app.bookfork.space/login>
- Website: <https://bookfork.space/en/>
