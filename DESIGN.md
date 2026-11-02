# Book Fork — Design System

> "Warm Paper Workspace": a cream canvas, one amber action colour, flat 6px
> geometry, hairline borders instead of shadows, and a friendly geometric sans.

This is the implemented visual system. It is shared with the marketing site
(`Book-Fork-Marketing`) and mapped onto daisyUI 5 so every component inherits
it. The single source of truth for tokens is [`static/css/input.css`](static/css/input.css);
this document explains the decisions and the rules that keep it coherent.

**Mode:** Operate for the product (`/app`, `/admin`), Persuade for the landing
page, Read for auth. The system is light-only.

---

## Surfaces

| Level | Token | Value | Role |
| --- | --- | --- | --- |
| 1 | `base-100` | `#fbfaf6` | Page canvas — never pure white at the base |
| 2 | `base-200` | `#f4f2eb` | Raised fills, icon tiles, quiet panels |
| 3 | `base-300` | `#e5e3db` | Hairlines, dividers, progress tracks |
| 4 | `neutral` | `#121212` | The one ink chamber per screen (dashboard hero, marketing CTA) |

## Colour

| Token | Value | Use |
| --- | --- | --- |
| `base-content` | `#121212` | Primary text, ink filled buttons |
| `base-content/60` | — | Secondary text |
| `base-content/45` | — | Eyebrows, metadata, timestamps |
| `primary` | `#e8aa42` | **The** primary action and progress |
| `secondary` / `neutral` | `#121212` | Dark filled nav action and the ink chamber |
| `accent` / `info` | `#214c7e` | Links, focus, informational status |
| `success` | `#2f7d4f` | Completed, enabled, validated |
| `warning` | `#d9660a` | Estimates, caution |
| `error` | `#b23b30` | Failed, destructive, validation |

Use **only semantic tokens** — `bg-base-100`, `border-base-300`,
`text-base-content/60`, `bg-primary/10`. Named palette tokens are retired so
the theme stays coherent.

## Typography

- **DM Sans** (self-hosted variable, the "matter" substitute) via `--font-sans`.
  Weights 400 body, 500 UI/links, 600–700 headings. Never below 400.
- **Mono** (`--font-mono`) for eyebrows, IDs, counts, configuration and code.
- Display and page titles use tight tracking (`-0.03em`) and short leading;
  body copy stays near `0`; eyebrows use positive tracking (`0.14–0.16em`).

| Role | Class / size |
| --- | --- |
| Display | hero and marketing only |
| Page title | `text-[28px] font-semibold tracking-[-0.03em]` |
| Section title | `text-[15px] font-semibold tracking-[-0.01em]` |
| Eyebrow | `font-mono text-[10.5px] uppercase tracking-[0.16em] text-base-content/45` |
| Body | 14–15px, `text-base-content/60` |

## Shape & elevation

- 6px radius everywhere (`--radius-box`, `--radius-field`, `--radius-selector`);
  pills and avatars use `rounded-full`.
- **No drop shadows on content surfaces** — separate with a 1px `base-300`
  border or the cream→raised difference. The only elevation is `shadow-lg` on
  genuinely floating overlays: dropdowns, popovers and toasts.

## Built from daisyUI primitives

No bespoke component classes. Templates compose daisyUI components and Tailwind
utilities directly:

| Content block | daisyUI component |
| --- | --- |
| Shell and navigation | `navbar`, `menu`, `dropdown`, `btn btn-ghost` |
| Page headers | `breadcrumbs`, `btn btn-primary`, `btn btn-outline` |
| Cards and panels | `card card-border`, `card-body` |
| Stats | `stats stats-vertical sm:stats-horizontal`, `stat` |
| Tables | `table` inside `overflow-x-auto` |
| Status | `badge` with tone utilities from the palette |
| Progress | `progress progress-primary` |
| Forms | `input`, `select`, `textarea`, `file-input`, `checkbox` |
| Notices | `alert alert-error alert-soft`, `alert alert-warning alert-soft` |
| Empty states | `card`, `card-body items-center text-center` |
| Settings index | `card card-border` grid with `menu` for quick actions |
| Auth providers | `btn btn-outline` |

The `status_badge(status)` macro (`components/status.html`) maps state to a
`badge` tone: green = done, red = failed, blue = active, grey = idle.

## Layout & navigation

- App shell (`layouts/base.html`): sticky translucent cream top bar, brand left,
  primary nav next to it, dark "New translation" plus account menu right.
  Mobile collapses to a `menu` panel. `max-w-6xl`, `px-5 sm:px-8`.
- Auth (`layouts/auth.html`): split panel — proposition on raised cream left,
  carded provider buttons right; stacks on mobile.
- Dashboard: one ink `bg-neutral` welcome chamber, then a stats strip, then a
  2/3 + 1/3 content grid. Only the dashboard uses the dark chamber.
- Detail and workflow pages: breadcrumbs, one page header with a single amber
  action, then carded content. Forms use a 1-column reading width, or a
  2-column form + sticky action rail for the translation workflow.
- Internal navigation is HTMX-boosted and swaps only `#app-content`; layouts emit
  just `<main id="app-content">` for `HX-Request`.

## Motion

- 150–200ms colour/transform transitions only; no entrance choreography.
- Press feedback is instant (`btn` handles it).
- `prefers-reduced-motion` collapses every animation and transition.

## Rules

**Do** keep the cream canvas, reserve amber for the single primary action, use
6px radii, separate with hairline borders, use DM Sans ≥400, keep mono for
technical text, and use semantic tokens only.

**Don't** use white as the page background, put two amber CTAs in one view, add
drop shadows to cards, exceed 12px radius, stack two dark chambers on one screen,
or use chromatic colour as decoration.

## Files

- `static/css/input.css` — theme tokens, the local font and a minimal element base.
  No component classes.
- `static/fonts/dm-sans-*.woff2` — self-hosted font (CSP is `font-src 'self'`).
- `static/favicon.svg` — ink tile + gold Book Fork mark (book with a fork cut into its edge).
- `templates/components/` — `brand`, `icons`, `nav`, `toast`, `status`.
- `templates/layouts/` — `base` (app), `auth`.
