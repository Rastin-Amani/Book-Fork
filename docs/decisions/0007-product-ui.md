# ADR 0007 — Product UI architecture

- **Status:** Accepted
- **Date:** 2026-10-05

## Context

Phase 7 needs a complete, coherent application UI without a SPA framework, over
an existing server-rendered shell. The product owner previously asked to defer
bespoke visual design.

## Decision

- **Server-rendered, HTMX-driven.** A persistent shell swaps only `#app-content`
  for internal navigation; fragments are returned for `HX-Request`.
- **Functionality now, visuals later.** Pages use flat daisyUI defaults with
  correct states (empty/loading/error), preserving structure so visual design can
  be applied later without rework.
- **Per-request repository bundle** bound to the user's token (`app/api/
  repositories.py`); routes contain orchestration only, services hold logic.
- **Workspace bootstrap** with a PocketBase rule allowing an owner to create
  their first membership row under the user's own token.
- **Polling, not WebSockets,** for job progress; polling is gated to active jobs.
- **Language metadata drives direction**; no hardcoded RTL lists in the UI.

## Consequences

- No JavaScript framework; behaviour stays in HTMX + small Alpine use.
- Admin pages are separate and gated by an `admin.emails` setting.
- The UI is restyleable without touching routing/handlers.

> **Update (Phase 8).** The "visuals later" posture is complete: bespoke visual
> design was delivered as the "Warm Paper Workspace" daisyUI theme, applied
> without changing routing or handlers — exactly as anticipated. See
> [`../../DESIGN.md`](../../DESIGN.md).
