# Book Fork — Design System

> "Warm Paper Workspace": a cream canvas, one amber action colour, flat 6px
> geometry, hairline borders instead of shadows, and a friendly geometric sans.

This is the implemented visual system. It is derived from the boords.com style
reference and mapped onto daisyUI 5 so every component inherits it. The single
source of truth for tokens is [`static/css/input.css`](static/css/input.css);
this document explains the decisions and the rules that keep it coherent.

**Mode:** Operate for the product (`/app`, `/admin`), Persuade for the landing
page, Read for auth. The system is light-only.

---

## Surfaces

| Level | Token | Value | Role |
| --- | --- | --- | --- |
| 1 | `bg-warm-cream` / `base-100` | `#fafaf5` | Page canvas — never pure white at the base |
| 2 | `bg-pure-white` | `#ffffff` | Cards, panels, tables |
| 3 | `bg-stone-gray` | `#e9e9e7` | Dividers, subtle fills, progress tracks |
| 4 | `bg-ink-black` | `#121212` | The one dark section (landing "provider" band) |

## Colour

| Token | Value | Use |
| --- | --- | --- |
| `ink-black` | `#121212` | Primary text, dark filled buttons |
| `graphite` | `#4d4d4d` | Secondary text |
| `mid-gray` | `#7d7d7d` | Tertiary text, eyebrows, icons |
| `muted-ash` | `#898989` | Placeholders |
| `pebble-border` | `#cecdca` | Hairline card/input borders |
| `stone-gray` | `#e9e9e7` | Row dividers |
| `warm-gold` | `#e8aa42` | **The** primary action (`btn-primary`) and progress |
| `deep-amber` | `#eb6c00` | Error accent / validation marks |
| `storyboard-blue` | `#214c7e` | Links, informational status, focus |
| `sketch-blue` | `#daeef8` | Status pill background |

daisyUI theme mapping (`@plugin "daisyui/theme"`, name `book-fork`):

- `base-100/200/300` → cream / raised cream / soft divider
- `primary` → `#e8aa42` with `primary-content` `#121212`
- `secondary` / `neutral` → `#121212` (dark filled button)
- `accent` / `info` → `#214c7e`
- `success` `#2f7d4f`, `warning` `#eb6c00`, `error` `#b23b30`
- `--radius-box/field/selector: 6px`, `--depth: 0`, `--noise: 0`, `--border: 1px`

## Typography

- **DM Sans** (self-hosted variable, the "matter" substitute) via `--font-sans`.
  Weights 400 body, 500 UI/links, 600–700 headings. Never below 400.
- **System mono** (`--font-mono`) for IDs, counts, config and code.
- Positive tracking (`0.05–0.1em`) only on small-caps eyebrows; body and display
  use normal or slightly tight tracking.

| Role | Class / size |
| --- | --- |
| Display | `text-[40px] sm:text-[58px]` hero |
| Page title | `.t-h1` (~26px) |
| Section title | `.t-h2` (~19–16px) |
| Eyebrow | `.eyebrow` (11px, upper, `0.1em`) |
| Body | 14–15px, `text-graphite` |

## Shape & elevation

- 6px radius everywhere (cards, buttons, inputs, images); pills use `rounded-full`.
- **No drop shadows on surfaces** — separate with a 1px `pebble-border` or the
  cream→white difference. The only elevation is `.t-float`
  (`rgba(0,0,0,.1) 0 2px 8px`) for genuinely floating overlays: the user menu,
  toasts and the landing hero preview card.

## Components

- **`.t-card`** — white surface + pebble border + 6px radius. The one container.
- **`.t-table`** — borderless rows with hairline dividers, uppercase micro-header,
  hover tint on cream. Use inside `.t-card`.
- **`.t-status`** — blue status pill with a leading dot.
- **`.eyebrow`** — small-caps category label above headings.
- **`.nav-item`** — menu/dropdown row.
- **`.link`** — blue text link, underline on hover.
- **`.btn-primary`** — the single amber action per view.
- **`.btn-neutral`** — dark filled (`#121212`) for the persistent nav action.
- **`status_badge(status)`** macro (`components/status.html`) — tones by state:
  green = done, red = failed, blue = active, gray = idle.

## Layout & navigation

- App shell (`layouts/base.html`): sticky cream top bar, brand left, primary nav
  centred-left, dark "New translation" + account menu right. Mobile collapses to
  a disclosure panel. `max-w-[1200px]`.
- Auth (`layouts/auth.html`): split panel — value proposition left, carded form
  right; stacks on mobile.
- Internal navigation is HTMX-boosted and swaps only `#app-content`; layouts emit
  just `<main id="app-content">` for `HX-Request`.

## Rules

**Do** keep the cream canvas, reserve amber for the single primary action, use 6px
radii, separate with hairline borders, use DM Sans ≥400, keep mono for technical
text.

**Don't** use white as the page background, put two amber CTAs in one view, add
drop shadows to cards, exceed 12px radius, or use chromatic colour as decoration.

## Files

- `static/css/input.css` — tokens, daisyUI theme, `@font-face`, component classes.
- `static/fonts/dm-sans-*.woff2` — self-hosted font (CSP is `font-src 'self'`).
- `static/favicon.svg` — ink tile + gold Book Fork mark (book with a fork cut into its edge).
- `templates/components/` — `brand`, `icons`, `nav`, `toast`, `status`.
- `templates/layouts/` — `base` (app), `auth`.
