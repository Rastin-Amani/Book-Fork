# Product UI & UX

Server-rendered FastAPI + Jinja2 + HTMX + Alpine + Tailwind + daisyUI. No SPA
framework. The browser-facing app lives under `/app/*`; admin under `/admin/*`.

> **Design note.** The frontend follows the "Warm Paper Workspace" system: a
> cream canvas, a single amber action colour, flat 6px geometry, hairline pebble
> borders instead of shadows, and self-hosted DM Sans. It is implemented as a
> custom daisyUI 5 theme plus design tokens in `static/css/input.css`. Full
> tokens, components and rules live in [`../DESIGN.md`](../DESIGN.md).

## Application shell

A persistent shell (`templates/layouts/base.html`) with a sticky cream top bar
(brand, centred-left primary nav, dark “New translation” and account menu), a
toast root, and `<main id="app-content">`. Internal navigation is HTMX-boosted and
swaps only `#app-content`, so the shell and toast system stay alive. Templates
render either the full document or just the content region based on
`HX-Request`.

## Routes

```
/                         landing
/login /signup            auth
/app                      dashboard
/app/translations         list
/app/translations/new     upload + options + estimate
/app/translations/{id}    job page (polling, actions, download)
/app/translations/{id}/review
/app/documents            list
/app/documents/{id}       detail (+ source download)
/app/glossaries           list / new / detail (terms)
/app/translation-memory   list
/app/providers            list / new / test / toggle / delete
/app/settings             hub
/app/settings/languages
/app/settings/profiles
/app/settings/billing
/admin, /admin/{resource}   declarative admin CRUD (see ../docs/admin-guide.md)
```

Every `/app/*` and `/admin/*` route requires authentication; `/admin/*` also
requires the user's email to be listed in the `admin.emails` setting.

## Workspace bootstrap

Every user gets a personal workspace on first use
(`app/workspaces/service.py`), backed by `workspaces` + `workspace_members`
(owner membership allowed by a PocketBase rule so bootstrap works under the
user's own token). All resources are workspace-scoped.

## New-translation workflow

Upload (or pick) a document → source/target language → profile → provider →
quality → review the estimate → start. The estimate is rendered server-side
(`partials/estimate.html`) with words/tokens, provider/model, and whether Book Fork
credits or the user's own API are used.

- **Language picker** options come from the language registry (native names,
  direction), never a hardcoded list. Source supports **Auto-detect**; when
  chosen, the source is detected at creation time via the document engine +
  detector and persisted on the document.
- **Provider selection** offers Auto (Book Fork), your connections (…your API), with
  advanced provider/model via the connection's default model.
- **Create** builds a `TranslationPlan` (capability- and cost-aware), stores its
  snapshot on the job and queues it; the worker does the rest.

## Job page

Shows document, source→target, status, progress bar, completed/total/failed
segments, provider/model, credits. HTMX polls
`/app/translations/{id}/status` every 2s **only while the job is active**
(rendered `job-active` flag), returning `partials/job_status.html`. Actions are
state-gated: Cancel while active, Retry-failed when failed, Download when an
output exists. Progress and status come from the server, never faked.

## Review

A simple per-segment Original/Translation view with save, approve, and (future)
regenerate/add-term hooks — a foundation for a fuller CAT workflow.

## Providers, glossaries, memory, settings

- Providers: add (name, base URL, API key, default model, billing mode), **Test
  connection** (safe diagnostic), enable/disable, delete. Keys are encrypted and
  never displayed after saving.
- Glossaries: create, per-term table (source/target language, terms,
  preferred/forbidden, notes), add/delete.
- Translation memory: read-only list.
- Settings: languages (direction/script/native names), profiles, billing
  (balance + transactions + usage).

## RTL / LTR

Direction and language are rendered from backend metadata (`lang`/`dir`,
native-name `dir`). Nothing hardcodes `fa = rtl` in templates or JS.

## Accessibility & mobile

Semantic HTML, labels, keyboard-friendly controls, visible focus, `role="alert"`
on errors, and content frozen on HTMX swaps. Layouts use responsive grids and
overflow-contained tables for 360px+.

## Reusable components

`templates/partials/` and `templates/components/`: estimate, job-status, segment
row, provider row, connection test, glossary term row, nav, toast.
